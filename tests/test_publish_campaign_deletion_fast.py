"""Temporary schema fixtures exercise publication gates, never research outcomes."""
import os
import shutil

import pytest

from test_publish_campaign import deletion_bundle
from test_publish_campaign_fast import bundle as fast_bundle
from tools import publish_campaign as pub
from witness_cl.campaign_io import read, save


CUTOFFS = ("last_call_start_utc", "generation_deadline_utc", "report_deadline_utc")


def rebind(out, *, parent=False):
    frozen = read(out / "freeze.json")
    if parent:
        from pathlib import Path
        source = Path(frozen["source_study"])
        source_audit = read(source / "audit.json")
        frozen.update(source_freeze_sha256=pub.file_sha(source / "freeze.json"),
                      source_audit_sha256=pub.file_sha(source / "audit.json"),
                      source_records_sha256=source_audit["records_sha256"],
                      source_journals_sha256=source_audit["journals_sha256"])
    save(out / "freeze.json", frozen)
    for case in read(out / "cases.json"):
        path = out / "episodes" / (case["key"] + ".json")
        if path.exists():
            record = read(path)
            record["freeze_sha256"] = pub.file_sha(out / "freeze.json")
            save(path, record)
    audit = read(out / "audit.json")
    tracker = pub.Inputs()
    audit.update(freeze_sha256=pub.file_sha(out / "freeze.json"),
                 summary_sha256=pub.file_sha(out / "summary.json"),
                 records_sha256=tracker.tree(out / "episodes") if (out / "episodes").exists() else pub.digest({}),
                 journals_sha256=tracker.tree(out / "calls") if (out / "calls").exists() else pub.digest({}))
    save(out / "audit.json", audit)


def bundle(tmp_path, *, eligible=0):
    source = fast_bundle(tmp_path)
    out = deletion_bundle(tmp_path, eligible=eligible, source=source)
    source_freeze = read(source / "freeze.json")
    frozen = read(out / "freeze.json")
    frozen.update(source_schedule="fast240", source_schedule_sha256=pub.file_sha(source / "schedule.json"),
                  **{key: source_freeze[key] for key in CUTOFFS})
    save(out / "freeze.json", frozen)
    summary = read(out / "summary.json")
    summary.update(source_schedule="fast240", agent_reruns_performed=eligible,
                   status="complete" if eligible else "no_reruns_performed")
    save(out / "summary.json", summary)
    rebind(out)
    return out, source


@pytest.mark.parametrize("eligible", [0, 1])
def test_fast_deletion_accepts_complete_parent_and_reports_zero_without_a_rerun(tmp_path, eligible):
    out, _ = bundle(tmp_path, eligible=eligible)
    snapshot = pub.build_snapshot([out])
    result = snapshot["studies"][0]
    assert result["status"] == "complete" and result["outcomes_publishable"]
    assert not result["primary_claim"]
    assert result["deletion"]["source_schedule"] == "fast240"
    assert result["deletion"]["agent_reruns_performed"] == eligible
    assert result["deletion"]["answer_flips_to_wrong"] == eligible
    assert result["deletion"]["original_acquisition_and_evaluation_cost"]["calls"] == 240
    assert result["physical_cost"]["calls"] == eligible
    if not eligible:
        assert result["deletion"]["status"] == "no_reruns_performed"
        assert not result["deletion"]["rerun_outcomes_measured"]
        assert "no reruns performed" in pub.render_tex(snapshot)
        assert "no reruns performed" in pub.render_markdown(snapshot)


@pytest.mark.parametrize("mutation", ["adapter", "schedule_hash", *CUTOFFS, "zero_status", "rerun_count"])
def test_fast_deletion_cannot_change_its_schedule_cutoffs_or_zero_case_status(tmp_path, mutation):
    out, _ = bundle(tmp_path)
    frozen = read(out / "freeze.json")
    summary = read(out / "summary.json")
    if mutation == "adapter":
        frozen.pop("source_schedule")
    elif mutation == "schedule_hash":
        frozen["source_schedule_sha256"] = "0" * 64
    elif mutation in CUTOFFS:
        frozen[mutation] = "2026-09-11T00:00:00+00:00"
    elif mutation == "zero_status":
        summary["status"] = "complete"
    else:
        summary["agent_reruns_performed"] = 1
    save(out / "freeze.json", frozen)
    save(out / "summary.json", summary)
    rebind(out)
    result = pub.build_snapshot([out])["studies"][0]
    assert result["status"] == "invalid" and not result["outcomes_publishable"]
    assert "deletion" not in result


@pytest.mark.parametrize("mutation", ["incomplete_audit", "partial_replay", "incomplete_summary", "missing_record"])
def test_fast_deletion_requires_every_parent_record_and_complete_replay(tmp_path, mutation):
    out, source = bundle(tmp_path)
    audit = read(source / "audit.json")
    if mutation == "incomplete_audit":
        audit["complete"] = False
    elif mutation == "partial_replay":
        audit["records_replayed"] = 239
    elif mutation == "incomplete_summary":
        summary = read(source / "summary.json")
        summary["complete"] = False
        save(source / "summary.json", summary)
        audit["summary_sha256"] = pub.file_sha(source / "summary.json")
    else:
        item = read(source / "schedule.json")[-1]
        (source / "episodes" / (item["key"] + ".json")).unlink()
        audit["records_sha256"] = pub.Inputs().tree(source / "episodes")
    save(source / "audit.json", audit)
    rebind(out, parent=True)
    result = pub.build_snapshot([out])["studies"][0]
    assert result["status"] == "invalid" and not result["outcomes_publishable"]
    assert "deletion" not in result


@pytest.mark.parametrize("mutation", ["case_database", "rerun_database"])
def test_fast_deletion_keeps_the_original_database_binding(tmp_path, mutation):
    out, _ = bundle(tmp_path, eligible=1)
    cases = read(out / "cases.json")
    path = out / "episodes" / (cases[0]["key"] + ".json")
    record = read(path)
    if mutation == "case_database":
        cases[0]["original_data_sha256"] = "0" * 64
        save(out / "cases.json", cases)
        frozen = read(out / "freeze.json")
        frozen["cases_sha256"] = pub.digest(cases)
        save(out / "freeze.json", frozen)
        record["case_sha256"] = pub.digest(cases[0])
    else:
        record["trace"]["evaluator"]["data_sha256"] = "0" * 64
    save(path, record)
    rebind(out)
    result = pub.build_snapshot([out])["studies"][0]
    assert result["status"] == "invalid" and "database" in result["reason"]
    assert "deletion" not in result


@pytest.mark.parametrize("unknown_usage", [False, True])
def test_interrupted_deletion_keeps_accounting_without_complete_case_flips(tmp_path, unknown_usage):
    out, _ = bundle(tmp_path, eligible=1)
    summary = read(out / "summary.json")
    summary.update(complete=False, status="incomplete", completed_cases=0,
                   agent_reruns_performed=0, answer_flips_to_wrong=123)
    save(out / "summary.json", summary)
    case = read(out / "cases.json")[0]
    path = out / "episodes" / (case["key"] + ".json")
    record = read(path)
    record["trace"]["status"] = "resource_stop"
    save(path, record)
    if unknown_usage:
        save(out / "calls" / case["key"] / "000.json", {"state": "pending", "calls": []})
    snapshot = pub.build_snapshot([out])
    result = snapshot["studies"][0]
    assert result["status"] == "incomplete" and not result["outcomes_publishable"]
    assert result["planned_records"] == 1 and result["progress"]["completed_records"] == 0
    assert result["physical_cost"]["calls"] == 1
    assert result["physical_cost"]["unknown_usage_calls"] == int(unknown_usage)
    assert result["physical_cost"]["total_tokens"] == (None if unknown_usage else 100)
    assert "deletion" not in result
    assert "answers flip to wrong" not in pub.render_tex(snapshot)
    markdown = pub.render_markdown(snapshot)
    assert "answers flip to wrong" not in markdown
    assert "Incomplete diagnostic usage" in markdown
    assert "Complete physical usage" not in markdown


def test_fast_deletion_relative_parent_survives_artifact_bundle_relocation(tmp_path):
    original = tmp_path / "original"
    out, source = bundle(original, eligible=1)
    frozen = read(out / "freeze.json")
    frozen["source_study_relative_to_output"] = os.path.relpath(source, out)
    save(out / "freeze.json", frozen)
    rebind(out)
    relocated = tmp_path / "relocated"
    shutil.move(original, relocated)
    result = pub.build_snapshot([relocated / out.name])["studies"][0]
    assert result["status"] == "complete" and result["deletion"]["agent_reruns_performed"] == 1
    assert read(relocated / out.name / "freeze.json")["source_study"] == str(source)
    assert not source.exists()  # The unchanged absolute provenance is not a runtime dependency.


@pytest.mark.parametrize("locator", ["", "/missing-parent", "../missing-parent"])
def test_deletion_relative_locator_never_silently_falls_back_to_absolute_parent(tmp_path, locator):
    out, source = bundle(tmp_path)
    frozen = read(out / "freeze.json")
    frozen["source_study_relative_to_output"] = locator
    save(out / "freeze.json", frozen)
    rebind(out)
    assert source.is_dir()
    result = pub.build_snapshot([out])["studies"][0]
    assert result["status"] == "invalid" and not result["outcomes_publishable"]


def test_deletion_relative_locator_preserves_bound_parent_identity(tmp_path):
    out, _ = bundle(tmp_path / "first")
    _, other_source = bundle(tmp_path / "other")
    other_freeze = read(other_source / "freeze.json")
    other_freeze["different_schema_fixture"] = True
    save(other_source / "freeze.json", other_freeze)
    frozen = read(out / "freeze.json")
    frozen["source_study_relative_to_output"] = os.path.relpath(other_source, out)
    save(out / "freeze.json", frozen)
    rebind(out)
    result = pub.build_snapshot([out])["studies"][0]
    assert result["status"] == "invalid" and "source study changed" in result["reason"]
