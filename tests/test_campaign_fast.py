"""Fast-study schedule, receipt, deadline and replay tests; no model inference."""
from datetime import datetime

import pytest

from tools import campaign_fast as fast
from witness_cl.campaign_io import read, save
from witness_cl.model_v8 import BudgetStop, InferenceBudget
from test_sql_harness_v8 import ScriptedClient


class Client(ScriptedClient):
    def __init__(self):
        self.ace = False
        super().__init__(self.respond)

    def respond(self, _messages, phase, _index):
        if phase == "ace:reflector:reflection":
            return {"bullet_tags": []}
        if phase == "ace:curator:reflection":
            return {"reasoning": "Software fixture only.", "operations": []}
        response = {"reasoning": "Software fixture only.", "final_answer": {
            "action": "QUERY", "sql": "SELECT 0", "params": {}, "answer": True}}
        if self.ace:
            response["bullet_ids"] = []
        return response

    def complete(self, *args, response_schema=None, **kwargs):
        self.ace = "bullet_ids" in (response_schema or {}).get("properties", {})
        return super().complete(*args, response_schema=response_schema, **kwargs)


def setup(out):
    return fast.freeze(out, runtime_config={}, runtime_receipt={},
                       client_config={"model": "explicit-offline-test-double", "context_tokens": 65536},
                       allow_test_double=True)


def test_exact240_schedule_retains_original_sparse_indices_and_episode_identities():
    plan = fast.planned_records(fast.protocol())
    assert len(plan) == len({row["key"] for row in plan}) == 240
    for seed in fast.SEEDS:
        for arm in fast.ARMS:
            rows = [row for row in plan if row["seed"] == seed and row["arm"] == arm]
            assert [(row["phase"], row["index"]) for row in rows] == (
                [("ordinary", index) for index in range(8)] + [("old_before", index) for index in fast.OLD]
                + [("ordinary", index) for index in range(8, 24)] + [("old_after", index) for index in fast.OLD]
                + [("final", index) for index in fast.FINAL])
            for index in fast.OLD:
                before = next(row for row in rows if row["phase"] == "old_before" and row["index"] == index)
                after = next(row for row in rows if row["phase"] == "old_after" and row["index"] == index)
                bi, ai = (fast.campaign.episode_identity(row) for row in (before, after))
                assert bi["sampling_seed"] == ai["sampling_seed"]
                assert bi["episode_index"] == 8 and ai["episode_index"] == 24
                for row in (before, after):
                    spec = fast.campaign.make_episode(seed, "development", "reuse", row["phase"], index, old_replicates=8)
                    assert dict(spec._metadata)["index"] == index


def test_adapter_is_explicit_scoped_and_rejects_modified_schedule():
    original = fast.campaign.planned_records
    frozen = fast.protocol()
    with fast.adapted(frozen):
        assert fast.campaign.planned_records is fast.planned_records
    assert fast.campaign.planned_records is original
    frozen["old_indices"] = [0]
    with pytest.raises(ValueError, match="exact prospectively assigned"):
        with fast.adapted(frozen):
            pytest.fail("modified protocol accepted")
    assert fast.campaign.planned_records is original


def test_fresh_seed_registry_rejects_overlap(tmp_path):
    save(tmp_path / "earlier/freeze.json", {"seeds": [101100]})
    assert len(fast.validate_fresh_seeds(tmp_path)) == 1
    save(tmp_path / "overlap/freeze.json", {"seeds": [fast.SEEDS[0]]})
    with pytest.raises(ValueError, match="overlap"):
        fast.validate_fresh_seeds(tmp_path)


def test_cutoff_precedes_pending_journal_write_and_does_not_call_client(tmp_path, monkeypatch):
    model = Client()
    journal = fast.deadline_journal(fast.protocol())(model, tmp_path)
    monkeypatch.setattr(fast.time, "time", lambda: datetime.fromisoformat(fast.LAST_CALL_START).timestamp())
    with pytest.raises(BudgetStop, match="fast_declared"):
        journal.complete([], InferenceBudget(), phase="ordinary:solve", records=[], output_tokens=4096)
    assert not model.seen and not list(tmp_path.glob("*.json"))


def test_recorded_calls_replay_after_cutoff_and_live_request_has_finish_deadline(tmp_path, monkeypatch):
    model = Client()
    cutoff = datetime.fromisoformat(fast.LAST_CALL_START).timestamp()
    monkeypatch.setattr(fast.time, "time", lambda: cutoff - 1)
    journal = fast.deadline_journal(fast.protocol())(model, tmp_path)
    budget, calls = InferenceBudget(), []
    first = journal.complete([], budget, phase="ordinary:solve", records=calls, output_tokens=4096)
    assert budget.deadline == float("inf")
    monkeypatch.setattr(fast.time, "time", lambda: cutoff + 600)
    replay = fast.deadline_journal(fast.protocol())(model, tmp_path)
    assert replay.complete([], InferenceBudget(), phase="ordinary:solve", records=[], output_tokens=4096) == first
    assert len(model.seen) == 1


@pytest.mark.parametrize("completed_ace_roles", [1, 2])
def test_deadline_during_ace_reflector_or_curator_marks_one_stopped_episode(tmp_path, monkeypatch, completed_ace_roles):
    out = tmp_path / "study"
    setup(out)
    cutoff = datetime.fromisoformat(fast.LAST_CALL_START).timestamp()
    current = [cutoff - 10]
    preceding_episodes = next(index for index, row in enumerate(fast.planned_records(fast.protocol()))
                              if row["arm"] == "ace")
    monkeypatch.setattr(fast.time, "time", lambda: current[0])

    class CrossingClient(Client):
        def complete(self, *args, **kwargs):
            answer = super().complete(*args, **kwargs)
            # Derive the first ACE position from the fixed seed rotation. After its
            # solve (or reflector), subsequent ACE update calls must not start.
            if len(self.seen) == preceding_episodes + completed_ace_roles:
                current[0] = cutoff
            return answer

    model = CrossingClient()
    result = fast.run(out, model)
    records = sorted((out / "episodes").glob("*.json"))
    assert result["completed_records"] == preceding_episodes + 1
    stopped = [read(path) for path in records if read(path)["trace"]["status"] == "resource_stop"]
    assert len(stopped) == 1 and stopped[0]["arm"] == "ace"
    assert stopped[0]["trace"]["memory_update_failure"]["error_type"] == "BudgetStop"
    assert len(model.seen) == preceding_episodes + completed_ace_roles
    audited = fast.audit(out)
    assert audited["complete"] is False and audited["records_replayed"] == preceding_episodes
    assert len(audited["stopped_records"]) == 1 and audited["cost"]["unknown_usage_calls"] == 0


def test_complete240_replay_uses_same_learner_and_all_ace_updates_but_never_claims_scripted_evidence(tmp_path):
    out = tmp_path / "study"
    frozen = setup(out)
    model = Client()
    assert fast.run(out, model, max_new_records=5)["completed_records"] == 5
    assert fast.run(out, model)["completed_records"] == 240
    assert len(model.seen) == 336
    audited = fast.audit(out)
    assert audited["complete"] and audited["records_replayed"] == 240 and audited["network_calls"] == 0
    assert read(out / "summary.json")["planned_records"] == 240
    assert len(read(out / "summary.json")["groups"]) == 6
    with fast.adapted(frozen):
        records = fast.campaign.load_records(out)
    assert all(record["before_snapshot"] == record["trace"]["memory"]
               for record in records if record["phase"] != "ordinary")
    result = fast.report(out)
    assert result["contains_test_double_calls"] is True and result["complete"] is False
    assert "groups" not in result and result["original_32_stream_pilot_completed"] is False


def test_fast_freeze_source_and_protocol_are_immutable(tmp_path):
    out = tmp_path / "study"
    frozen = setup(out)
    assert "docs/campaign/TIME_BUDGET_AMENDMENT.md" in frozen["source_sha256"]
    with pytest.raises(ValueError, match="never overwrites"):
        setup(out)
    altered = read(out / "freeze.json")
    altered["last_call_start_utc"] = fast.REPORT_DEADLINE
    save(out / "freeze.json", altered)
    with pytest.raises(ValueError, match="prospectively assigned"):
        fast.verify(out)
