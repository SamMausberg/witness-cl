"""Report-consumer checks use tiny marked fixtures, never model scores."""

from copy import deepcopy
import json

import pytest

from experiments import stateful_sql as study
from test_sql_harness_v9 import Client
from tools.current_results import memory_diagnostics, render, summarize


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture
def completed(tmp_path):
    directory = tmp_path / "offline-completed"
    study.run_study(
        directory, Client(lambda *_: {"action": "ANSWER", "value": 0}), arms=("evidence",)
    )
    return directory


def test_marked_fixture_totals_and_external_directory(completed):
    result = summarize(completed)
    assert result["directory"] == str(completed.resolve())
    assert result["calls"] == 8 and result["known_tokens"] == 80
    assert result["known_prompt_tokens"] == 56 and result["known_completion_tokens"] == 24
    assert result["unknown_usage_calls"] == 0 and result["token_total_complete"]
    assert result["receipt_consistency"]["contains_test_double_calls"] is True
    row = result["groups"][0]
    assert row["warm_n"] == row["episodes"] == 8
    assert row["selects"] == 0 and row["warm_costs"] == {
        "selects": 0,
        "calls": 8,
        "known_tokens": 80,
    }
    assert row["zero_sql_answers"] == 8 and row["zero_sql_correct_answers"] == 0
    assert row["attempted_use_actions"] == row["executed_memory_actions"] == 0


def test_whole_run_costs_are_separate_from_warm_only_accuracy(tmp_path):
    directory = tmp_path / "nine-episodes"
    study.run_study(
        directory,
        Client(lambda *_: {"action": "ANSWER", "value": 0}),
        arms=("evidence",),
        stage="full",
        gate_after_warm=False,
        stop_after=9,
    )
    result = summarize(directory)
    row = result["groups"][0]
    assert result["status"] == "stopped" and not result["required_records_complete"]
    assert row["episodes"] == row["calls"] == 9 and row["known_tokens"] == 90
    assert row["warm_n"] == 8 and row["warm_costs"]["known_tokens"] == 80
    assert row["phases"]["old_before"]["n"] == 1
    assert "all recorded phases" in row["cost_scope"]


def test_live_receipt_cannot_be_published(completed):
    path = completed / "manifest.json"
    manifest = read(path)
    manifest["status"] = "running"
    write(path, manifest)
    with pytest.raises(ValueError, match="live run"):
        summarize(completed)


def test_changed_raw_or_extra_raw_file_is_rejected(completed):
    raw = next(completed.glob("*.jsonl"))
    original = raw.read_text()
    raw.write_text(original + " ")
    with pytest.raises(ValueError, match="raw hash"):
        summarize(completed)
    raw.write_text(original)
    (completed / "unreported.jsonl").write_text(original)
    with pytest.raises(ValueError, match="inventory"):
        summarize(completed)


@pytest.mark.parametrize(
    "field", ["calls", "total_tokens", "prompt_tokens", "completion_tokens", "unknown_usage_calls"]
)
def test_every_global_usage_counter_is_checked(completed, field):
    path = completed / "manifest.json"
    manifest = read(path)
    manifest["total_budget"][field] += 1
    write(path, manifest)
    with pytest.raises(ValueError, match="ledger mismatch|budget counter mismatch"):
        summarize(completed)


def test_changed_summary_or_source_is_rejected(completed):
    summary = completed / "summary.json"
    original = summary.read_text()
    summary.write_text(original + " ")
    with pytest.raises(ValueError, match="summary hash"):
        summarize(completed)
    summary.write_text(original)
    path = completed / "manifest.json"
    manifest = read(path)
    manifest["source_unchanged"] = False
    write(path, manifest)
    with pytest.raises(ValueError, match="source/configuration changed"):
        summarize(completed)


def test_nonfinite_elapsed_time_is_not_published(completed):
    path = completed / "manifest.json"
    manifest = read(path)
    manifest["elapsed_seconds"] = float("nan")
    write(path, manifest)
    with pytest.raises(ValueError, match="elapsed time"):
        summarize(completed)


def test_unknown_usage_is_a_lower_bound_not_a_zero_token_completion(tmp_path):
    class Failed(Client):
        def complete(self, messages, budget, *, phase, records, output_tokens, response_schema):
            budget.check(7, output_tokens)
            budget.calls += 1
            budget.unknown_usage_calls += 1
            records.append(
                {
                    "messages": deepcopy(messages),
                    "phase": phase,
                    "status": "failed",
                    "generation_attempted": True,
                    "usage": None,
                    "response_schema": deepcopy(response_schema),
                    "test_double": True,
                }
            )
            raise RuntimeError("marked unknown-usage failure")

    directory = tmp_path / "failure"
    study.run_study(directory, Failed(lambda *_: None), arms=("evidence",))
    result = summarize(directory)
    assert result["status"] == "failed" and result["calls"] == 1
    assert result["known_tokens"] == 0 and result["unknown_usage_calls"] == 1
    assert result["unknown_token_count"] is None and result["token_total_complete"] is False
    assert result["groups"][0]["unknown_usage_calls"] == 1
    assert result["groups"][0]["zero_sql_answers"] == 0


def test_guard_only_observations_and_numeric_matches_are_not_fragment_execution():
    traces = [
        {
            "answer": 4,
            "reward": 1,
            "select_attempts": 1,
            "actions": [{"action": "USE", "guard_passed": False}, {"action": "ANSWER", "value": 4}],
            "queries": [{"purpose": "applicability_check", "rows": [[4]]}],
        },
        {
            "answer": 8,
            "reward": 1,
            "select_attempts": 2,
            "actions": [
                {"action": "COMPOSE", "guard_passed": True, "executed_fragment_digest": "d"},
                {"action": "ANSWER", "value": 8},
            ],
            "queries": [{"purpose": "applicability_check"}, {"purpose": "fragment_composition"}],
        },
        {
            "answer": 0,
            "reward": 1,
            "select_attempts": 0,
            "actions": [{"action": "ANSWER", "value": 0}],
            "queries": [],
        },
    ]
    counts = memory_diagnostics(traces)
    assert counts["attempted_use_actions"] == counts["attempted_compose_actions"] == 1
    assert counts["applicability_check_queries"] == 2
    assert counts["rejected_guard_actions"] == counts["guard_only_memory_actions"] == 1
    assert counts["executed_memory_actions"] == 1
    assert counts["correct_episodes_with_guard_queries_without_fragment_execution"] == 1
    assert counts["zero_sql_answers"] == counts["zero_sql_correct_answers"] == 1
    assert counts["guard_answer_causal_dependence_established"] is False
    assert "excludes guard-only" in counts["executed_memory_action_scope"]


def test_adaptive_runs_render_separately_and_aggregate_only_expenditure(completed, tmp_path):
    other = tmp_path / "separate-run"
    study.run_study(
        other,
        Client(lambda *_: {"action": "ANSWER", "value": 0}),
        arms=("evidence",),
        seeds=(94001,),
    )
    studies = [summarize(completed), summarize(other)]
    result = render(studies, tmp_path / "results", tmp_path / "paper")
    assert len(result["studies"]) == 2 and result["total_calls"] == 16
    assert result["total_known_tokens"] == 160
    assert result["native_benchmark"] is False and result["confirmatory"] is False
    assert "no pooled accuracy or significance" in result["aggregate_scope"]
    table = (tmp_path / "paper/gh200_table.tex").read_text()
    assert "All SELECTs" in table and "Known tokens" in table
    assert "Costs cover all recorded phases" in table
    assert "94000" in table and "94001" in table
    assert (tmp_path / "paper/gh200_warm.pdf").is_file()
    with pytest.raises(ValueError, match="duplicate run"):
        render([studies[0], studies[0]], tmp_path / "duplicates", tmp_path / "unused-paper")
