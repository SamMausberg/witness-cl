from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import native_campaign as campaign
from witness_cl.campaign_io import RecordedClient, save


def test_native_plan_is_exactly_five_matched_four_arm_default_permutations():
    jobs = campaign.planned_runs()
    assert len(jobs) == 20 and len({job["key"] for job in jobs}) == 20
    for index in range(5):
        assert {job["arm"] for job in jobs if job["run_index"] == index} == set(campaign.ARMS)
    assert [job["arm"] for job in jobs[:4]] == list(campaign.ARMS)
    assert jobs[4]["arm"] == "ace"


def test_native_journal_refuses_pending_unknown_and_gaps(tmp_path):
    save(tmp_path / "000.json", {"state": "pending"})
    partial = campaign.partial_journal_usage(tmp_path)
    assert partial["total_tokens"] is None and partial["uncertain_invocations"] == 1
    with pytest.raises(ValueError, match="uncertain"):
        campaign.journal_calls(tmp_path)
    save(tmp_path / "000.json", {"state": "recorded", "calls": [{"status": "failed", "usage": None}]})
    with pytest.raises(ValueError, match="failed"):
        campaign.journal_calls(tmp_path)
    (tmp_path / "000.json").rename(tmp_path / "001.json")
    with pytest.raises(ValueError, match="gaps"):
        campaign.journal_calls(tmp_path)


def test_native_asset_mismatch_is_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "products.db"
    path.write_bytes(b"wrong")
    monkeypatch.setattr(campaign, "ASSETS", {"products.db": {"bytes": 5, "sha256": "0" * 64}})
    with pytest.raises(ValueError, match="refusing overwrite"):
        campaign.fetch_assets(tmp_path)
    assert path.read_bytes() == b"wrong"


@pytest.fixture
def native_api():
    upstream = os.environ.get("WITNESS_CLBENCH_UPSTREAM")
    if not upstream or sys.version_info < (3, 13):
        pytest.skip("select optional pinned native Python 3.13 runtime")
    pytest.importorskip("litellm")
    return campaign.load_native(upstream)


class FixtureClient:
    def __init__(self):
        self.index = 0

    def complete(self, messages, budget, *, phase, records, output_tokens, response_schema):
        actions = [
            {"action": "QUERY", "content": ".schema"},
            {"action": "QUERY", "content": "SELECT SUM(amount) FROM items WHERE name = 'alpha'"},
            {"action": "ANSWER", "content": "7"},
            {"action": "QUERY", "content": "SELECT SUM(amount) FROM items WHERE name = 'beta'"},
            {"action": "ANSWER", "content": "11"},
        ]
        payload = actions[self.index]
        self.index += 1
        raw = json.dumps(payload)
        budget.calls += 1
        budget.prompt_tokens += 10
        budget.completion_tokens += 5
        budget.total_tokens += 15
        records.append({"status": "completed", "generation_attempted": True,
            "phase": phase, "messages": deepcopy(messages), "response_schema": deepcopy(response_schema),
            "max_output_tokens": output_tokens, "content": raw,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
        return raw


def test_native_execution_and_model_free_replay_use_original_runner(native_api, tmp_path, monkeypatch):
    database = tmp_path / "fixture.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE items (name TEXT, amount INTEGER)")
        conn.executemany("INSERT INTO items VALUES (?, ?)", [("alpha", 7), ("beta", 11)])
    questions = tmp_path / "fixture-questions.json"
    questions.write_text(json.dumps([
        {"question_id": "alpha", "question": "What is the sum for alpha?", "answer": "7", "answer_type": "integer"},
        {"question_id": "beta", "question": "What is the sum for beta?", "answer": "11", "answer_type": "integer"},
    ]))
    original_task = native_api.database.DatabaseExploration
    def fixture_task(**kwargs):
        assert kwargs == {"schedule": "default", "run_index": 0, "rollout_index": 0}
        return original_task(db_path=str(database), questions_path=str(questions),
                             num_instances=2, max_queries_per_question=8)
    monkeypatch.setattr(native_api.database, "DatabaseExploration", fixture_task)
    monkeypatch.setattr(campaign, "load_native", lambda root: native_api)
    protocol = {"upstream": str(native_api.root), "limits": {"model_tokens_per_run": 100000,
        "model_calls_per_run": 100, "output_tokens": 4096, "context_tokens": 65536},
        "runtime_config": {"model": {"alias": "fixture"}},
        "question_orders": {"0": ["alpha", "beta"]}}
    job = {"key": "fixture", "arm": "witness_stateful", "run_index": 0}
    actual = campaign.execute_native(protocol, job, FixtureClient(), live_trace=tmp_path / "live.json")
    assert actual["status"] == "completed" and actual["metrics"]["accuracy"] == 1
    assert actual["usage"]["total_tokens"] == 75
    recorded = RecordedClient(actual["calls"])
    replayed = campaign.execute_native(protocol, job, recorded)
    assert recorded.index == 5
    assert replayed["metrics"] == actual["metrics"]
    assert replayed["system_artifacts"] == actual["system_artifacts"]
    assert campaign.trace_semantics(replayed["trace"]) == campaign.trace_semantics(actual["trace"])
