"""Pure-Python contract tests; native benchmark packages are optional."""
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.clbench.core import (  # noqa: E402
    CallUsage, ExperienceLedger, ModelReply, native_certificate,
)


def begin(ledger):
    ledger.begin(prompt="question", action_json='{"action":"ANSWER","content":"7"}',
                 response_schema={"type": "object"}, instance_id="opaque-instance")


def test_ledger_requires_matched_feedback_and_preserves_empty_observation():
    ledger = ExperienceLedger()
    with pytest.raises(RuntimeError, match="unmatched"):
        ledger.observe(content="invented", instance_complete=True)
    begin(ledger)
    with pytest.raises(RuntimeError, match="previous response"):
        begin(ledger)
    row = ledger.observe(content="", instance_complete=False)
    assert row.feedback == ""
    assert not row.instance_complete
    assert not ledger.pending
    with pytest.raises(RuntimeError, match="unmatched"):
        ledger.observe(content="duplicate", instance_complete=True)


def test_ledger_is_immutable_and_reset_removes_all_learned_state():
    ledger = ExperienceLedger()
    begin(ledger)
    row = ledger.observe(content="Correct answer: 11", instance_complete=True)
    with pytest.raises(FrozenInstanceError):
        row.feedback = "modified"
    export = ledger.to_jsonable()
    export[0]["feedback"] = "modified"
    assert ledger.records[0].feedback == "Correct answer: 11"
    begin(ledger)
    ledger.reset()
    assert ledger.records == () and not ledger.pending


def test_ledger_schema_identity_and_raw_post_action_feedback():
    ledger = ExperienceLedger()
    begin(ledger)
    row = ledger.observe(content="INCORRECT. Correct answer: 11", instance_complete=True)
    assert row.evidence_origin == "native_observation_content"
    assert len(row.schema_sha256) == 64
    assert set(ledger.to_jsonable()[0]) == {
        "turn", "instance_id", "prompt", "action_json", "schema_sha256",
        "feedback", "instance_complete", "evidence_origin",
    }


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_usage_rejects_invalid_token_counts(value):
    with pytest.raises(ValueError):
        CallUsage("fixture", input_tokens=value)


@pytest.mark.parametrize("value", [-0.1, True, float("inf"), float("nan")])
def test_usage_rejects_invalid_cost(value):
    with pytest.raises(ValueError):
        CallUsage("fixture", cost_usd=value)


def test_missing_usage_is_unknown_and_reply_requires_accounting():
    assert CallUsage("fixture", input_tokens=10).total_tokens is None
    assert CallUsage("fixture", input_tokens=10, output_tokens=2).total_tokens == 12
    with pytest.raises(ValueError):
        ModelReply({}, ())
    with pytest.raises(ValueError):
        ModelReply({}, [CallUsage("fixture")])
    with pytest.raises(ValueError):
        CallUsage("fixture", input_tokens=1, cached_input_tokens=2)


def test_native_certification_unconditionally_abstains():
    decision = native_certificate()
    assert decision.status == "UNKNOWN"
    assert "No verified native" in decision.reason
    with pytest.raises(FrozenInstanceError):
        decision.status = "PASS"
