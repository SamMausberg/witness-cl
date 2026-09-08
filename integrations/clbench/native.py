"""Load and extend the actual pinned CL-Bench ICL implementation on demand.

The upstream package is loaded under an isolated module namespace because its
package name `src` can collide with other repositories. No source is copied or
patched. The adapter is programmatic; it is not a CLI-discoverable plugin.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

from .core import (
    CallUsage, ExperienceLedger, ModelReply, StructuredTransport,
    TransportFailure, native_certificate,
)

UPSTREAM_URL = "https://github.com/pgasawa/continual-learning-bench"
UPSTREAM_COMMIT = "5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26"
_SOURCE_FILES = (
    "src/interface.py", "src/usage.py", "src/runtime/runner.py",
    "src/systems/icl/system.py", "src/systems/utils/provider_adapters.py",
    "src/systems/utils/token_budget.py", "src/systems/utils/structured_output.py",
    "src/tasks/database_exploration/task.py",
    "src/tasks/database_exploration/prompts.py",
)


@dataclass(frozen=True)
class NativeAPI:
    root: Path
    interface: Any
    icl: Any
    usage: Any
    providers: Any
    database: Any
    registry: Any
    source_hashes: dict[str, str]


def inspect_pin(root: str | Path) -> dict[str, str]:
    root = Path(root).resolve()
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    if proc.stdout.strip() != UPSTREAM_COMMIT:
        raise ValueError(f"CL-Bench must be at exact commit {UPSTREAM_COMMIT}")
    diff = subprocess.run(
        ["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", "src"],
        capture_output=True,
    )
    if diff.returncode != 0:
        raise ValueError("CL-Bench source is modified; pin verification failed")
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in _SOURCE_FILES
    }


def load_native(root: str | Path) -> NativeAPI:
    """Require Python 3.13+, the exact source pin, and optional dependencies."""
    if sys.version_info < (3, 13):
        raise RuntimeError("Native CL-Bench requires Python >=3.13; core tests do not")
    root = Path(root).resolve()
    hashes = inspect_pin(root)
    namespace = "_witness_clbench_" + UPSTREAM_COMMIT[:12]
    if namespace in sys.modules:
        loaded = Path(sys.modules[namespace].__file__).resolve().parent.parent
        if loaded != root:
            raise ValueError("This process already loaded the pin from another checkout")
    else:
        spec = importlib.util.spec_from_file_location(
            namespace, root / "src" / "__init__.py",
            submodule_search_locations=[str(root / "src")],
        )
        if spec is None or spec.loader is None:
            raise ImportError("Could not construct native CL-Bench package")
        package = importlib.util.module_from_spec(spec)
        sys.modules[namespace] = package
        spec.loader.exec_module(package)

    def module(name: str) -> Any:
        return importlib.import_module(f"{namespace}.{name}")

    return NativeAPI(
        root, module("interface"), module("systems.icl.system"), module("usage"),
        module("systems.utils.provider_adapters"),
        module("tasks.database_exploration.task"), module("registry"), hashes,
    )


class _InjectedClient:
    """Narrow injection point used by unchanged upstream ICL.respond()."""

    def __init__(
        self, *, api: NativeAPI, transport: StructuredTransport, owner: Any,
        max_response_bytes: int = 262144,
    ) -> None:
        self.api, self.transport, self.owner = api, transport, owner
        self.max_response_bytes = max_response_bytes
        self.state = SimpleNamespace(provider="witness_injected", sent_message_count=0)

    def reset(self) -> None:
        self.transport.reset()
        self.state.sent_message_count = 0

    def state_metadata(self) -> dict[str, Any]:
        return {
            "provider": "injected_transport", "continuity_mode": "visible_context_only",
            "provider_native_hidden_state_used": False,
            "transport_state": "transport-defined; reset required",
            "sent_message_count": self.state.sent_message_count,
        }

    def _event(self, usage: CallUsage, elapsed: float, failed: bool) -> Any:
        return self.api.usage.UsageEvent(
            call_type="witness_bridge_transport", model=usage.model,
            provider=usage.provider, input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens, total_tokens=usage.total_tokens,
            cached_input_tokens=usage.cached_input_tokens, cost_usd=usage.cost_usd,
            response_id=usage.response_id,
            metadata={"transport_wall_seconds": elapsed, "failed": failed},
        )

    def respond_structured(self, *, messages: list[dict], response_schema: Any) -> Any:
        started = time.perf_counter()
        try:
            reply = self.transport.complete(
                messages=deepcopy(messages),
                response_schema=deepcopy(response_schema.model_json_schema()),
            )
        except Exception as exc:
            elapsed = time.perf_counter() - started
            known = exc.usage if isinstance(exc, TransportFailure) else ()
            for index, item in enumerate(known or (CallUsage(model=self.owner.model),)):
                self.owner.record_usage_event(self._event(item, elapsed if index == 0 else 0.0, True))
            raise
        elapsed = time.perf_counter() - started
        if not isinstance(reply, ModelReply):
            self.owner.record_usage_event(self._event(CallUsage(self.owner.model), elapsed, True))
            raise TypeError("transport did not return ModelReply")
        # A transport may return several retry records. Charge the enclosing
        # elapsed time once; per-retry durations are not separately measured.
        events = [self._event(item, elapsed if index == 0 else 0.0, False)
                  for index, item in enumerate(reply.usage)]
        try:
            raw = reply.action if isinstance(reply.action, str) else json.dumps(
                reply.action, allow_nan=False,
            )
            if len(raw.encode("utf-8")) > self.max_response_bytes:
                raise ValueError("structured transport output exceeds byte limit")
            action = response_schema.model_validate_json(raw)
        except Exception:
            # The provider call still cost resources even when schema parsing failed.
            for event in events:
                event.metadata["failed"] = True
                self.owner.record_usage_event(event)
            raise
        return self.api.providers.ProviderTurnResult(
            action=action, assistant_record=action.model_dump_json(), usage_events=events,
        )


def inject_transport(api: NativeAPI, system: Any, transport: StructuredTransport) -> Any:
    """Install identical transport on the upstream control or bridge for parity."""
    system._provider_client = _InjectedClient(api=api, transport=transport, owner=system)
    return system


def make_bridge(
    api: NativeAPI, *, transport: StructuredTransport, model: str,
    max_tokens: int = 8192, reserve_tokens: int = 512,
    system_prompt: str = "", name: str = "witness_history_bridge",
) -> Any:
    """Actual upstream ICL plus an observation-only audit ledger.

    No learned fact, certificate, task metadata, or ID changes the prompt. Exact
    Witness admission always abstains. Full native adaptation is still research.
    """
    if max_tokens <= reserve_tokens or reserve_tokens < 0:
        raise ValueError("context ceiling must exceed the nonnegative reserve")

    class NativeHistoryBridge(api.icl.ICLSystem):
        supports_baseline = True
        # Arbitrary injected transports may share a server or mutable state.
        parallel_safe = False

        def __init__(self) -> None:
            super().__init__(
                model=model, max_tokens=max_tokens, reserve_tokens=reserve_tokens,
                system_prompt=system_prompt, name=name, provider_mode="litellm_chat",
            )
            self.experience = ExperienceLedger()
            inject_transport(api, self, transport)

        def respond(self, query: Any) -> Any:
            if self.experience.pending:
                raise RuntimeError("native runner must observe feedback before next respond")
            response = super().respond(query)
            self.experience.begin(
                prompt=query.prompt or "(no content)",
                action_json=response.action.model_dump_json(),
                response_schema=query.response_schema.model_json_schema(),
                instance_id=query.instance_id,
            )
            response.metadata.update({
                "system_type": "witness_history_bridge",
                "adaptation": "upstream_raw_history_with_audit_ledger",
                "witness_certificate": native_certificate().status,
                "upstream_commit": UPSTREAM_COMMIT,
            })
            return response

        def observe(self, observation: Any, next_query: Any = None) -> None:
            self.experience.observe(
                content=observation.content,
                instance_complete=api.interface.observation_marks_instance_complete(observation),
            )
            # Native observe consumes content only; metadata and next_query are not read.
            super().observe(observation, next_query)

        def reset(self) -> None:
            super().reset()
            self.experience.reset()
            # Match upstream: preserve unconsumed usage until runner drains it.

        def get_run_artifacts(self) -> dict[str, Any]:
            artifacts = super().get_run_artifacts()
            artifacts.update({
                "artifact_type": "witness_history_bridge",
                "upstream_commit": UPSTREAM_COMMIT,
                "source_sha256": dict(api.source_hashes),
                "experience": self.experience.to_jsonable(),
                "pending_feedback": self.experience.pending,
                "native_certificate": vars(native_certificate()),
                "native_learning_algorithm_implemented": False,
            })
            return artifacts

    return NativeHistoryBridge()
