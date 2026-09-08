"""Execute actual native runner/SQLite contracts using a synthetic fixture.

No language model or official benchmark data is used. This is integration
validation, not a benchmark score or evidence of learned improvement.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

from .core import CallUsage, ModelReply
from .native import UPSTREAM_COMMIT, UPSTREAM_URL, inject_transport, load_native, make_bridge


class FixtureTransport:
    """Scripted fixture actions; no model request and no hidden task access."""

    def __init__(self) -> None:
        self.calls = []
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1

    def complete(self, *, messages, response_schema) -> ModelReply:
        self.calls.append((deepcopy(messages), deepcopy(response_schema)))
        current = messages[-1]["content"]
        if "for alpha?" in current:
            if "Queries used so far this question: 0/4" in current:
                action = {"action": "QUERY", "content": "SELECT amount FROM items WHERE name = 'alpha'"}
            else:
                action = {"action": "ANSWER", "content": "7"}
        else:
            action = {"action": "ANSWER", "content": "intentionally incorrect"}
        return ModelReply(action, (CallUsage("scripted-contract-fixture"),))


def _fixture_task(api, directory: Path):
    db = directory / "fixture.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE items (name TEXT, amount INTEGER)")
        connection.executemany("INSERT INTO items VALUES (?, ?)", [("alpha", 7), ("beta", 11)])
    questions = directory / "questions.json"
    questions.write_text(json.dumps([
        {"question_id": "fixture-alpha", "question": "What is the amount for alpha?",
         "answer": "7", "sql": "SELECT amount FROM items WHERE name = 'alpha'"},
        {"question_id": "fixture-beta", "question": "What is the amount for beta?",
         "answer": "11", "sql": "SELECT amount FROM items WHERE name = 'beta'"},
    ]))
    return api.database.DatabaseExploration(
        db_path=str(db), questions_path=str(questions), num_instances=2,
        max_queries_per_question=4,
    )


def _fixture_token_counter(system):
    # Both arms use identical offline estimates. Usage remains unknown because
    # no model tokenizer/provider measured it; this does not mimic real tokens.
    system._estimate_message_tokens = lambda messages: sum(
        len(json.dumps(message)) // 4 + 4 for message in messages
    )
    system._response_schema_tokens = lambda schema: len(json.dumps(schema.model_json_schema())) // 4
    return system


def execute_fixture(upstream: str | Path) -> dict:
    started = time.perf_counter()
    api = load_native(upstream)
    reference_transport, bridge_transport = FixtureTransport(), FixtureTransport()
    reference = api.icl.ICLSystem(
        model="scripted-contract-fixture", provider_mode="litellm_chat",
        max_tokens=8192, reserve_tokens=512,
    )
    inject_transport(api, reference, reference_transport)
    bridge = make_bridge(api, transport=bridge_transport, model="scripted-contract-fixture")
    _fixture_token_counter(reference)
    _fixture_token_counter(bridge)
    with tempfile.TemporaryDirectory(prefix="witness-clbench-contract-") as temp:
        root = Path(temp)
        for name in ("reference", "bridge"):
            (root / name).mkdir()
        reference_result = api.interface.run_task(
            _fixture_task(api, root / "reference"), reference, show_progress=False,
        )
        bridge_result = api.interface.run_task(
            _fixture_task(api, root / "bridge"), bridge, show_progress=False,
        )
    parity = (
        reference_transport.calls == bridge_transport.calls
        and reference.messages == bridge.messages
        and reference_result.instance_outcomes == bridge_result.instance_outcomes
    )
    if not parity:
        raise AssertionError("native fixture diverged from upstream ICL control")
    records = bridge.experience.records
    if len(records) != 3 or "Correct answer: 11" not in records[-1].feedback:
        raise AssertionError("native post-action feedback contract changed")
    if "SELECT" in records[-1].feedback:
        raise AssertionError("native terminal feedback unexpectedly exposed reference SQL")
    return {
        "status": "native_contract_fixture_executed",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "upstream_repository": UPSTREAM_URL, "upstream_commit": UPSTREAM_COMMIT,
        "source_sha256": api.source_hashes,
        "bridge_source_sha256": {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                                  for name in ("core.py", "native.py", "smoke.py")},
        "python": sys.version,
        "packages": {name: version(name) for name in ("litellm", "pydantic", "openai", "pytest")},
        "official_benchmark_result": False, "official_benchmark_data_used": False,
        "language_model_used": False, "synthetic_fixture": True,
        "native_components_executed": ["ICLSystem", "DatabaseExploration", "run_task", "UsageEvent"],
        "bridge_control_prompt_action_outcome_parity": parity,
        "fixture_outcomes_not_benchmark_scores": [asdict(o) for o in bridge_result.instance_outcomes],
        "transport_calls_per_arm": len(bridge_transport.calls),
        "input_tokens": None, "output_tokens": None, "cost_usd": None,
        "token_counter": "identical deterministic fixture estimate; not a model tokenizer",
        "wall_seconds": time.perf_counter() - started,
        "legal_terminal_correct_answer_observed": True,
        "reference_sql_observed": False,
        "native_exact_certificate": "UNKNOWN",
        "scope": "Actual upstream code on two local fixture questions; no benchmark or learning claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = execute_fixture(args.upstream)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": manifest["status"], "parity": True,
                      "official_benchmark_result": False, "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
