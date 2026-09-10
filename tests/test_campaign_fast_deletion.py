"""Explicit fast-parent deletion adaptation; scripted software checks only."""
from copy import deepcopy
from datetime import datetime
import shutil

import pytest

from test_audit_campaign_mechanism import campaign_records as fixture_campaign_records
from test_campaign_assay import wrapped_client
from test_campaign_fast import Client, setup
from tools import campaign_assay as assay
from tools import campaign_fast as fast
from witness_cl.campaign_io import read, save, sha, usage
from witness_cl.query_memory import digest

campaign_records = fixture_campaign_records


@pytest.fixture(scope="module")
def complete_fast(tmp_path_factory):
    out = tmp_path_factory.mktemp("fast-deletion-parent") / "study"
    # Scope the historical clock to fixture generation so deadline tests keep
    # control of time and deletion replay can run after the real cutoff.
    cutoff = datetime.fromisoformat(fast.LAST_CALL_START).timestamp()
    with pytest.MonkeyPatch.context() as clock:
        clock.setattr(fast.time, "time", lambda: cutoff - 60)
        frozen = setup(out)
        fast.run(out, Client())
    audited = fast.audit(out)
    assert audited["complete"] and audited["records_replayed"] == 240
    return out, frozen, audited


def test_full_fast_parent_adapter_freezes_zero_census_without_calling_a_model(tmp_path, complete_fast):
    source, original, _ = complete_fast
    out = tmp_path / "deletion"
    result = assay.freeze_deletion(out, source, source_schedule="fast240")
    assert result["planned_cases"] == 0
    frozen, cases = assay.verify_deletion_freeze(out)
    assert cases == [] and frozen["source_schedule"] == "fast240"
    assert frozen["source_schedule_sha256"] == sha(source / "schedule.json")
    assert frozen["last_call_start_utc"] == original["last_call_start_utc"]
    assert frozen["generation_deadline_utc"] == original["generation_deadline_utc"]
    assert "docs/campaign/FAST_DELETION_PLAN.md" in frozen["source_sha256"]
    model = Client()
    summary = assay.run_deletion(out, model)
    assert summary["complete"] and summary["status"] == "no_reruns_performed"
    assert summary["agent_reruns_performed"] == 0 and not model.seen
    audited = assay.run_deletion(out, None, replay=True)
    assert audited["complete"] and audited["cases_replayed"] == 0


def test_fast_parent_rejects_implicit_adapter_and_partial_or_changed_schedule(complete_fast):
    source, original, audited = complete_fast
    with pytest.raises(ValueError, match="explicit fast240"):
        assay.load_deletion_source(source, original, audited, "campaign")
    incomplete = {**audited, "records_replayed": 239}
    with pytest.raises(ValueError, match="complete exact audited schedule"):
        assay.load_deletion_source(source, original, incomplete, "fast240")
    changed = deepcopy(original)
    changed["old_indices"] = [0, 1, 2, 3]
    with pytest.raises(ValueError, match="exact prospectively assigned"):
        assay.load_deletion_source(source, changed, audited, "fast240")
    changed = {**original, "fixtures_sha256": "wrong"}
    with pytest.raises(ValueError, match="fixture or schedule implementation"):
        assay.load_deletion_source(source, changed, audited, "fast240")


def staged_cases(out, records):
    """Software-only journal fixture; no empirical parent or freeze claim."""
    cases, mechanism = assay.all_deletion_cases(records)
    source = out.parent / "source-bindings"
    for name in ("freeze.json", "audit.json", "schedule.json"):
        save(source / name, {"software_fixture": True,
                            "last_call_start_utc": fast.LAST_CALL_START,
                            "generation_deadline_utc": fast.GENERATION_DEADLINE,
                            "report_deadline_utc": fast.REPORT_DEADLINE})
    save(out / "cases.json", cases)
    save(out / "mechanism-selection.json", mechanism)
    frozen = {"experiment": "agent_relation_deletion_v1", "source_schedule": "fast240",
              "source_study": str(source), "source_freeze_sha256": sha(source / "freeze.json"),
              "source_audit_sha256": sha(source / "audit.json"),
              "source_schedule_sha256": sha(source / "schedule.json"),
              "source_records_sha256": assay.campaign.artifact_digest(source / "episodes"),
              "source_journals_sha256": assay.campaign.artifact_digest(source / "calls"),
              "source_sha256": assay.deletion_source_inventory("fast240"),
              "environment": assay.campaign.environment_fingerprint(),
              "cases_sha256": digest(cases), "planned_cases": len(cases),
              "selection_receipt_sha256": sha(out / "mechanism-selection.json"),
              "source_split": "development", "old_replicates": 8,
              "contains_test_double_calls": True,
              "original_acquisition_and_evaluation_cost": usage([]),
              "client_config": {"context_tokens": 65536},
              "limits": {"max_model_calls_per_episode": 5, "solve_output_tokens": 4096},
              "last_call_start_utc": fast.LAST_CALL_START,
              "generation_deadline_utc": fast.GENERATION_DEADLINE,
              "report_deadline_utc": fast.REPORT_DEADLINE}
    save(out / "freeze.json", frozen)
    save(out / "freeze.sha256.json", {"sha256": sha(out / "freeze.json")})
    return cases


@pytest.mark.parametrize("first_call_allowed", [False, True])
def test_deadline_keeps_all_cases_and_stopped_attempt_without_retry(
        tmp_path, campaign_records, monkeypatch, first_call_allowed):
    out = tmp_path / "deletion"
    cases = staged_cases(out, campaign_records)
    cutoff = datetime.fromisoformat(fast.LAST_CALL_START).timestamp()
    now = [cutoff - 1 if first_call_allowed else cutoff]
    monkeypatch.setattr(fast.time, "time", lambda: now[0])

    def respond(*_):
        now[0] = cutoff
        return {"action": "QUERY", "sql": "SELECT 0", "params": {}, "answer": False}

    model = wrapped_client(respond)
    summary = assay.run_deletion(out, model)
    assert not summary["complete"] and summary["status"] == "incomplete"
    assert summary["planned_cases"] == len(cases) == 6
    assert summary["recorded_cases"] == 1 and summary["completed_cases"] == 0
    assert len(model.seen) == int(first_call_allowed)
    paths = list((out / "calls").glob("*/*.json"))
    assert len(paths) == int(first_call_allowed)
    assert all(read(path)["state"] == "recorded" for path in paths)
    again = assay.run_deletion(out, model)
    assert again == summary and len(model.seen) == int(first_call_allowed)
    audited = assay.run_deletion(out, None, replay=True)
    assert not audited["complete"] and audited["cases_replayed"] == 0
    assert len(audited["stopped_cases"]) == 1 and audited["model_calls_made"] == 0


def test_deletion_rerun_rejects_a_changed_original_database(tmp_path, campaign_records):
    cases = staged_cases(tmp_path / "deletion", campaign_records)
    case = {**cases[0], "original_data_sha256": "different"}
    frozen, _ = assay.verify_deletion_freeze(tmp_path / "deletion")
    model = Client()
    with pytest.raises(ValueError, match="database differs"):
        assay.execute_deletion_case(case, model, frozen)
    assert not model.seen


def test_relocated_parent_replays_and_tampered_parent_is_rejected(tmp_path, complete_fast):
    original_tree = tmp_path / "original"
    source = original_tree / "parent"
    shutil.copytree(complete_fast[0], source)
    deletion = original_tree / "deletion"
    assay.freeze_deletion(deletion, source, source_schedule="fast240")
    frozen = read(deletion / "freeze.json")
    assert frozen["source_study"] == str(source.resolve())
    assert frozen["source_study_relative_to_output"] == "../parent"
    assay.run_deletion(deletion, Client())
    relocated = tmp_path / "relocated"
    shutil.move(original_tree, relocated)
    assert not source.exists()
    moved_deletion = relocated / "deletion"
    assert assay.resolve_deletion_source(moved_deletion, frozen) == relocated / "parent"
    restored, _ = assay.verify_deletion_freeze(moved_deletion)
    assert restored["source_study"] == str(source.resolve())  # Original provenance is unchanged.
    assert assay.run_deletion(moved_deletion, None, replay=True)["complete"]
    save(relocated / "parent/schedule.json", {"tampered": True})
    with pytest.raises(ValueError, match="parent receipt changed"):
        assay.verify_deletion_freeze(moved_deletion)


def test_parent_locator_legacy_and_no_fallback_for_present_relative_path(tmp_path):
    parent = tmp_path / "legacy-parent"
    parent.mkdir()
    out = tmp_path / "deletion"
    legacy = {"source_study": str(parent)}
    assert assay.resolve_deletion_source(out, legacy) == parent
    for locator in ("", str(parent), None):
        with pytest.raises(ValueError, match="nonempty relative path"):
            assay.resolve_deletion_source(out, {**legacy, "source_study_relative_to_output": locator})
    with pytest.raises(ValueError, match="does not resolve"):
        assay.resolve_deletion_source(out, {**legacy, "source_study_relative_to_output": "../missing"})
