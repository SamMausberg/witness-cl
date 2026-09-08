"""Dependency-free transport and observed-experience contracts.

These records preserve what was delivered through the normal task interface.
They do not infer a world model, certify native tasks, or train a policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Protocol


@dataclass(frozen=True)
class CallUsage:
    """One transport attempt. Missing measurements stay unknown, never zero."""

    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cost_usd: float | None = None
    response_id: str | None = None
    provider: str = "injected_transport"

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model:
            raise ValueError("usage model must be a nonempty string")
        for name in ("input_tokens", "output_tokens", "cached_input_tokens"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        if self.cost_usd is not None and (
            isinstance(self.cost_usd, bool)
            or not isinstance(self.cost_usd, (int, float))
            or not math.isfinite(self.cost_usd)
            or self.cost_usd < 0
        ):
            raise ValueError("cost_usd must be finite and nonnegative, or None")
        if (
            self.cached_input_tokens is not None
            and self.input_tokens is not None
            and self.cached_input_tokens > self.input_tokens
        ):
            raise ValueError("cached input tokens cannot exceed input tokens")

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ModelReply:
    action: dict[str, Any] | str
    usage: tuple[CallUsage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.action, (dict, str)):
            raise TypeError("transport action must be a JSON object or JSON string")
        if type(self.usage) is not tuple or not self.usage or not all(isinstance(u, CallUsage) for u in self.usage):
            raise ValueError("each transport reply needs at least one usage record")


class TransportFailure(RuntimeError):
    """Transport failure with known attempted-call accounting."""

    def __init__(self, message: str, usage: tuple[CallUsage, ...] = ()) -> None:
        super().__init__(message)
        self.usage = usage


class StructuredTransport(Protocol):
    def complete(
        self, *, messages: list[dict[str, Any]], response_schema: dict[str, Any]
    ) -> ModelReply: ...

    def reset(self) -> None: ...


@dataclass(frozen=True)
class CertificateDecision:
    status: str = "UNKNOWN"
    reason: str = "No verified native predictive-model/reset contract is installed."


def native_certificate() -> CertificateDecision:
    """The bridge has no path that can claim an exact native certificate."""
    return CertificateDecision()


@dataclass(frozen=True)
class Experience:
    turn: int
    instance_id: str | None
    prompt: str
    action_json: str
    schema_sha256: str
    feedback: str
    instance_complete: bool
    evidence_origin: str = "native_observation_content"


class ExperienceLedger:
    """Append immutable action/feedback pairs; ignore task/evaluator metadata.

    Instance identities are audit identifiers only. No ledger content is injected
    into the model beyond the upstream ICL history. reset() starts a new run.
    """

    def __init__(self) -> None:
        self._records: list[Experience] = []
        self._pending: dict[str, Any] | None = None

    @property
    def pending(self) -> bool:
        return self._pending is not None

    @property
    def records(self) -> tuple[Experience, ...]:
        return tuple(self._records)

    def begin(
        self, *, prompt: str, action_json: str, response_schema: dict[str, Any],
        instance_id: str | None,
    ) -> None:
        if self.pending:
            raise RuntimeError("observe the previous response before another respond")
        if not isinstance(prompt, str) or not isinstance(action_json, str):
            raise TypeError("prompt and action_json must be strings")
        if instance_id is not None and not isinstance(instance_id, str):
            raise TypeError("instance_id is an opaque string or None")
        parsed = json.loads(action_json)
        if not isinstance(parsed, dict):
            raise ValueError("action_json must encode an object")
        schema_bytes = json.dumps(
            response_schema, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()
        self._pending = {
            "turn": len(self._records), "instance_id": instance_id,
            "prompt": prompt, "action_json": action_json,
            "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        }

    def observe(self, *, content: str, instance_complete: bool) -> Experience:
        if self._pending is None:
            raise RuntimeError("feedback has no unmatched executed response")
        if not isinstance(content, str) or type(instance_complete) is not bool:
            raise TypeError("feedback requires string content and a boolean boundary")
        record = Experience(
            **self._pending, feedback=content, instance_complete=instance_complete,
        )
        self._records.append(record)
        self._pending = None
        return record

    def reset(self) -> None:
        self._records.clear()
        self._pending = None

    def to_jsonable(self) -> list[dict[str, Any]]:
        return [asdict(record) for record in self._records]
