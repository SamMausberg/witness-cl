"""Saved-record progress uses temporary schema fixtures, never model results."""
import pytest

from tools import campaign, campaign_fast as fast, publish_campaign as pub
from witness_cl.campaign_io import read, save


def incomplete(tmp_path, *, count=3, fast_kind=False, manifest_count=None):
    out = tmp_path / "progress-schema-fixture"
    frozen = fast.protocol() if fast_kind else {
        "kind": "development", "seeds": [7], "conditions": ["reuse"],
        "arms": ["full_history", "ace", "delayed"], "old_replicates": 8,
        "cold_start_each_episode": False}
    frozen["contains_test_double_calls"] = False
    schedule = (fast.planned_records if fast_kind else campaign.planned_records)(frozen)
    frozen.update(planned_records=len(schedule), schedule_sha256=pub.digest(schedule))
    save(out / "freeze.json", frozen)
    save(out / "schedule.json", schedule)
    for item in schedule[:count]:
        save(out / "episodes" / (item["key"] + ".json"), {
            **item, "schema_fixture": True, "freeze_sha256": pub.file_sha(out / "freeze.json"),
            "trace": {"phase": item["phase"], "arm": item["arm"], "status": "completed",
                      "reward": 1.0, "model_calls": []}})
    if manifest_count is not None:
        save(out / "manifest.json", {"status": "running", "completed_records": manifest_count,
                                     "planned_records": len(schedule)})
    return out


def inspect(out):
    return pub.build_snapshot([out])["studies"][0]


def test_incomplete_progress_uses161_saved_records_without_changing_lagging_manifest(tmp_path):
    out = incomplete(tmp_path, count=161, manifest_count=160)
    manifest_hash = pub.file_sha(out / "manifest.json")
    study = inspect(out)
    assert study["status"] == "incomplete"
    assert study["progress"]["saved_records"] == study["progress"]["completed_records"] == 161
    assert study["progress"]["progress_source"] == "contiguous_frozen_schedule_prefix"
    assert pub.file_sha(out / "manifest.json") == manifest_hash
    assert read(out / "manifest.json")["completed_records"] == 160
    assert not study["outcomes_publishable"] and not study["primary_claim"]
    assert all(key not in study for key in ("descriptive", "mechanism", "analysis", "physical_cost"))
    snapshot = pub.build_snapshot([out])
    assert "161/552" in pub.render_markdown(snapshot)
    assert snapshot == pub.build_snapshot([out])


@pytest.mark.parametrize("fast_kind", [False, True])
def test_unstarted_frozen_schedule_reports_zero_without_manifest(tmp_path, fast_kind):
    out = incomplete(tmp_path, count=0, fast_kind=fast_kind)
    study = inspect(out)
    assert study["status"] == "incomplete"
    assert study["progress"]["saved_records"] == study["progress"]["completed_records"] == 0
    assert study["progress"]["planned_records"] == (240 if fast_kind else 552)
    assert not (out / "episodes").exists() and not (out / "manifest.json").exists()


@pytest.mark.parametrize("mutation", ["hole", "unplanned", "nested", "record_identity",
                                    "freeze_identity", "trace_identity", "schedule", "duplicate", "malformed"])
def test_incomplete_progress_rejects_holes_unplanned_records_and_wrong_identities(tmp_path, mutation):
    out = incomplete(tmp_path)
    schedule = read(out / "schedule.json")
    path = out / "episodes" / (schedule[0]["key"] + ".json")
    if mutation == "hole":
        path.unlink()
    elif mutation in {"unplanned", "nested"}:
        save(out / "episodes" / ("extra.json" if mutation == "unplanned" else "nested/extra.json"), {})
    elif mutation == "malformed":
        save(path, [])
    elif mutation in {"record_identity", "freeze_identity", "trace_identity"}:
        record = read(path)
        if mutation == "record_identity":
            record["index"] += 1
        elif mutation == "freeze_identity":
            record["freeze_sha256"] = "0" * 64
        else:
            record["trace"]["arm"] = "another_arm"
        save(path, record)
    else:
        schedule[1] = schedule[0]
        save(out / "schedule.json", schedule)
        if mutation == "duplicate":
            frozen = read(out / "freeze.json")
            frozen["schedule_sha256"] = pub.digest(schedule)
            save(out / "freeze.json", frozen)
    study = inspect(out)
    assert study["status"] == "invalid"
    assert not study["outcomes_publishable"] and not study["primary_claim"]
    assert "descriptive" not in study


def test_stopped_attempt_is_saved_but_not_counted_as_completed(tmp_path):
    out = incomplete(tmp_path, count=3, manifest_count=2)
    item = read(out / "schedule.json")[2]
    path = out / "episodes" / (item["key"] + ".json")
    record = read(path)
    record["trace"]["status"] = "resource_stop"
    save(path, record)
    study = inspect(out)
    assert study["status"] == "incomplete"
    assert study["progress"]["saved_records"] == 3
    assert study["progress"]["completed_records"] == 2
    assert study["progress"]["stopped_attempt_records"] == 1
    assert "3/552" in pub.render_markdown(pub.build_snapshot([out]))


@pytest.mark.parametrize("native", [True, False])
def test_native_and_deletion_progress_rules_do_not_require_custom_schedule(tmp_path, native):
    frozen = {"contains_test_double_calls": False}
    if native:
        frozen.update(jobs=[], task={})
    else:
        frozen.update(experiment="agent_relation_deletion_v1", planned_cases=0)
    save(tmp_path / "freeze.json", frozen)
    study = inspect(tmp_path)
    assert study["status"] == "incomplete" and "progress" not in study
    assert not (tmp_path / "schedule.json").exists()


@pytest.mark.parametrize("invalid_checksum", [False, True])
def test_assay_progress_accepts_only_matching_bound_checksum_sidecars(tmp_path, invalid_checksum):
    out = incomplete(tmp_path, count=1)
    frozen = read(out / "freeze.json")
    frozen["experiment"] = "common_source_matched_evidence_v1"
    save(out / "freeze.json", frozen)
    item = read(out / "schedule.json")[0]
    path = out / "episodes" / (item["key"] + ".json")
    record = read(path)
    record["freeze_sha256"] = pub.file_sha(out / "freeze.json")
    save(path, record)
    save(path.with_suffix(".sha256.json"), {
        "record_sha256": "0" * 64 if invalid_checksum else pub.digest(record)})
    study = inspect(out)
    assert study["status"] == ("invalid" if invalid_checksum else "incomplete")
    if not invalid_checksum:
        assert study["progress"]["saved_records"] == 1
        assert study["progress"]["completed_records"] == 1
    assert not study["outcomes_publishable"]
