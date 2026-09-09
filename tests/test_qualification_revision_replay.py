"""Strict outer artifact checks and an actual archived no-network replay."""

import json
from pathlib import Path

import pytest

from tools.replay_qualification_at_revision import replay, strict_json, validate_artifacts

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_numbers_rejected_recursively(literal):
    with pytest.raises(ValueError, match="nonfinite"):
        strict_json('{"nested": [{"number": ' + literal + "}]}")
    assert strict_json(json.dumps({"content": literal})) == {"content": literal}


def test_boolean_cannot_impersonate_zero_ledger_count(tmp_path):
    for name in ("freeze.json", "summary.json"):
        (tmp_path / name).write_text("{}")
    (tmp_path / "episodes.jsonl").write_text("")
    budget = dict.fromkeys(
        (
            "max_total_tokens",
            "max_calls",
            "total_tokens",
            "prompt_tokens",
            "completion_tokens",
            "calls",
            "unknown_usage_calls",
        ),
        0,
    )
    budget["unknown_usage_calls"] = False
    (tmp_path / "manifest.json").write_text(json.dumps({"budget": budget}))
    with pytest.raises(ValueError, match="exact nonnegative integers"):
        validate_artifacts(tmp_path)


def test_original_qualification_replays_from_trusted_checkpoint():
    result = replay(ROOT / "artifacts/query_transfer/qualification", "6ccacb3")
    assert result["records_replayed"] == 32 and result["sql_replayed"] == 147
    assert result["qualified"] is False
    assert result["revision_replay"]["source_verified_before_execution"]
    assert result["revision_replay"]["raw_artifacts_modified"] is False
