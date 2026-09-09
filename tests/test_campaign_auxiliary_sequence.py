"""Orchestration tests only: no endpoint, benchmark execution, or model calls."""

from copy import deepcopy
from pathlib import Path
import subprocess

import pytest

from tools import campaign_auxiliary_sequence as auxiliary
from witness_cl.campaign_io import read, save, sha


def runner(tmp_path, cls=auxiliary.AuxiliarySequence):
    config = tmp_path / "runtime.json"
    receipt = tmp_path / "server.json"
    save(config, read(auxiliary.ROOT / "configs/campaign_runtime_dense.json"))
    save(receipt, {"config": read(config), "model_sha256": "test-runtime-sha"})
    return cls(tmp_path / "auxiliary", tmp_path / "main",
        auxiliary.ROOT / "configs/campaign_sequence_dense_v2.json", config, receipt,
        tmp_path / "server.key", native_python=tmp_path / "native-venv/bin/python",
        upstream=tmp_path / "upstream", assets=tmp_path / "assets",
        runtime_cache=tmp_path / "runtime-cache", python=tmp_path / "venv/bin/python")


class Harness(auxiliary.AuxiliarySequence):
    def require_main(self, kind):
        self.events.append(("gate", kind))
        if getattr(self, "failed_gate", None) == kind:
            raise ValueError("incomplete or failed prerequisite")

    def freeze(self, stage):
        self.events.append(("freeze", stage))
        return self.out / stage

    def execute(self, stage, directory):
        self.events.append(("execute", stage))
        return {"complete": True, "negative_result": True}

    def completed(self, stage):
        self.events.append(("verified_complete", stage))
        return {"complete": True}


def harness(tmp_path):
    value = runner(tmp_path, Harness)
    value.events = []
    return value


def test_prospective_schedule_is_exact_and_does_not_create_output(tmp_path):
    value = runner(tmp_path)
    prospective = value.prospective()
    assert not value.out.exists()
    assert not value.upstream.exists()
    assert [job["name"] for job in prospective["stages"]] == list(auxiliary.STAGES)
    small, development_deletion, native, formal, deletion = prospective["stages"]
    assert small["seeds"] == list(range(102000, 102004))
    assert small["planned_records"] == 480
    assert formal["seeds"] == list(range(300000, 300064))
    assert formal["planned_records"] == 7680
    assert small["checkpoints"] == formal["checkpoints"] == [8, 16, 24]
    assert native["planned_questions"] == 800
    assert len(native["jobs"]) == 20
    assert native["query_budget"] == 15
    assert development_deletion["source_study"] == str(value.main_out / "development")
    assert deletion["source_study"] == str(value.main_out / "confirmation")
    assert prospective["environments"]["native_python"].endswith("native-venv/bin/python")
    assert prospective["environments"]["native_upstream"] == str(value.upstream)
    assert prospective["environments"]["native_assets"] == str(value.assets)


@pytest.mark.parametrize("field,replacement", [("streams", 63), ("probes_per_checkpoint", 7),
                                               ("development_seed_start", 102001)])
def test_reserved_assay_schedule_cannot_change(field, replacement):
    plan = read(auxiliary.ROOT / "configs/campaign_sequence_dense_v2.json")
    plan["separate_assay"][field] = replacement
    with pytest.raises(ValueError, match="exact reserved"):
        auxiliary.validate_auxiliary_plan(plan)


def test_native_permutation_selection_is_rejected():
    plan = read(auxiliary.ROOT / "configs/campaign_sequence_dense_v2.json")
    plan["native"]["permutations"] = [2]
    with pytest.raises(ValueError, match="five-by-forty"):
        auxiliary.validate_auxiliary_plan(plan)


def test_registry_binds_paths_and_runtime_without_reading_secret(tmp_path):
    value = runner(tmp_path)
    assert not value.key_file.exists()  # The launcher must never read credentials.
    value.register()
    value.register()
    frozen = read(value.out / "auxiliary-sequence.json")
    assert frozen["prospective"]["runtime"]["key_file"] == str(value.key_file)
    value.upstream = tmp_path / "other-upstream"
    with pytest.raises(ValueError, match="paths.*changed"):
        value.register()


def test_changed_runtime_receipt_cannot_resume_existing_registry(tmp_path):
    value = runner(tmp_path)
    value.register()
    save(value.runtime_receipt, {"config": read(value.runtime_config), "model_sha256": "different"})
    with pytest.raises(ValueError, match="runtime receipts.*changed"):
        value.register()


def test_failure_of_main_qualification_prevents_every_freeze(tmp_path):
    value = harness(tmp_path)
    value.failed_gate = "qualification"
    with pytest.raises(ValueError, match="prerequisite"):
        value.run("deletion")
    assert value.events == [("gate", "qualification")]


def test_development_deletion_and_native_precede_main_confirmation_gate(tmp_path):
    value = harness(tmp_path)
    value.failed_gate = "confirmation"
    value.run("native")
    assert value.events == [
        ("gate", "qualification"), ("freeze", "assay-development"), ("execute", "assay-development"),
        ("gate", "development"), ("freeze", "development-deletion"), ("execute", "development-deletion"),
        ("freeze", "native"), ("execute", "native"),
    ]
    summary = read(value.out / "summary.json")
    assert summary["status"] == "completed_through_requested_stage"
    assert summary["native_environment"]["native_upstream"] == str(value.upstream)


def test_negative_confirmation_and_negative_development_ablation_do_not_skip_diagnostics(tmp_path):
    value = harness(tmp_path)
    save(value.main_out / "confirmation/analysis.json", {"all_five_pass": False})
    value.run("deletion")
    assert value.events[-5:] == [
        ("gate", "confirmation"), ("freeze", "assay-diagnostic"), ("execute", "assay-diagnostic"),
        ("freeze", "deletion"), ("execute", "deletion"),
    ]
    assert [name for event, name in value.events if event == "execute"] == list(auxiliary.STAGES)
    assert read(value.out / "summary.json")["outcome_stopping"] is False


def test_incomplete_confirmation_preserves_prior_completed_diagnostics(tmp_path):
    value = harness(tmp_path)
    value.failed_gate = "confirmation"
    with pytest.raises(ValueError, match="prerequisite"):
        value.run("deletion")
    assert value.events[-1] == ("gate", "confirmation")
    assert not any(name in {"assay-diagnostic", "deletion"} for _, name in value.events)
    assert len(read(value.out / "summary.json")["completed_stages"]) == 3


@pytest.mark.parametrize("through", auxiliary.STAGES)
def test_through_stops_only_at_complete_stage_boundary(tmp_path, through):
    value = harness(tmp_path)
    value.run(through)
    executed = [name for event, name in value.events if event == "execute"]
    assert executed == list(auxiliary.STAGES[:auxiliary.STAGES.index(through) + 1])


def test_already_complete_stage_is_verified_without_rerunning(tmp_path):
    value = harness(tmp_path)
    save(value.out / "assay-development/audit.json", {"complete": True})
    value.run("assay-development")
    assert value.events[-1] == ("verified_complete", "assay-development")
    assert not any(event == "execute" for event, _ in value.events)


def test_commands_use_frozen_scripts_full_schedules_and_native_replay(tmp_path):
    value = runner(tmp_path)
    calls = []
    value.invoke = lambda script, args, label, **kwargs: calls.append((script, args, label, kwargs))
    value.completed = lambda stage: {"complete": True}
    for stage in auxiliary.STAGES:
        directory = value.out / stage
        value.execute(stage, directory)
    assert len(calls) == 10
    assert all("/sources/tools/" in str(script) for script, _, _, _ in calls)
    assert not any(arg in {"--max-new-records", "--max-runs"} for _, args, _, _ in calls for arg in args)
    native = [item for item in calls if item[2].startswith("native-")]
    assert len(native) == 2 and all(item[3] == {"native": True} for item in native)
    assert "--replay" in native[1][1]
    assert [args[0] for _, args, _, _ in calls] == [
        "resume", "audit", "deletion-resume", "deletion-audit", "resume", "audit",
        "resume", "audit", "deletion-resume", "deletion-audit"]


def test_failed_subprocess_is_durably_recorded_and_not_retried(tmp_path, monkeypatch):
    value = runner(tmp_path)
    value.register()
    calls = []

    def failed(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(4, command)

    monkeypatch.setattr(auxiliary.subprocess, "run", failed)
    with pytest.raises(subprocess.CalledProcessError):
        value.invoke(Path("frozen.py"), ["resume"], "assay-run")
    assert len(calls) == 1
    receipt = read(next((value.out / "invocations").glob("*.json")))
    assert receipt["status"] == "stopped"
    assert receipt["error_type"] == "CalledProcessError"
    assert receipt["finished_utc"]


def test_partial_freeze_never_silently_overwrites_output(tmp_path):
    value = runner(tmp_path)
    (value.out / "assay-development/sources").mkdir(parents=True)
    value.invoke = lambda *_args, **_kwargs: pytest.fail("must not refreeze")
    with pytest.raises(ValueError, match="partial freeze retained"):
        value.freeze("assay-development")


def deletion_fixture(value, count):
    directory = value.out / "development-deletion"
    source = value.main_out / "development"
    save(source / "freeze.json", {"fixture": "structural orchestration test only"})
    save(source / "audit.json", {"fixture": True})
    cases = [{"key": f"case-{i}"} for i in range(count)]
    selection = {"events": deepcopy(cases)}
    frozen = {"experiment": "agent_relation_deletion_v1", "contains_test_double_calls": False,
        "source_sha256": {},
        "runtime_config": read(value.runtime_config), "runtime_receipt": read(value.runtime_receipt),
        "source_study": str(source), "source_freeze_sha256": sha(source / "freeze.json"),
        "source_audit_sha256": sha(source / "audit.json"),
        "source_records_sha256": auxiliary.campaign.artifact_digest(source / "episodes"),
        "source_journals_sha256": auxiliary.campaign.artifact_digest(source / "calls"),
        "learn": False, "feedback_to_original_campaign": False, "planned_cases": count}
    save(directory / "freeze.json", frozen)
    save(directory / "freeze.sha256.json", {"sha256": sha(directory / "freeze.json")})
    save(directory / "cases.json", cases)
    save(directory / "mechanism-selection.json", selection)
    return directory, frozen, cases, selection


@pytest.mark.parametrize("count", [0, 6])
def test_deletion_requires_entire_prospective_parent_census_including_zero(tmp_path, monkeypatch, count):
    value = runner(tmp_path)
    directory, _, cases, selection = deletion_fixture(value, count)
    monkeypatch.setattr(auxiliary.campaign, "load_records", lambda _: [])
    monkeypatch.setattr(auxiliary.campaign_assay, "all_deletion_cases", lambda _: (cases, selection))
    assert value.check_stage_freeze("development-deletion")["planned_cases"] == count
    save(directory / "cases.json", cases[:-1] if count else [{"unassigned": True}])
    with pytest.raises(ValueError, match="entire parent structural-event census"):
        value.check_stage_freeze("development-deletion")


@pytest.mark.parametrize("count", [0, 6])
def test_zero_case_and_no_flip_deletion_are_complete_results(tmp_path, count):
    value = runner(tmp_path)
    directory, _, _, _ = deletion_fixture(value, count)
    cost = {"calls": count, "prompt_tokens": count, "completion_tokens": count,
            "total_tokens": count * 2, "unknown_usage_calls": 0}
    summary = {"complete": True, "completed_cases": count, "answer_flips_to_wrong": 0,
               "correct_despite_deletion": count, "physical_diagnostic_cost": cost}
    save(directory / "summary.json", summary)
    audit = {"complete": True, "consistent": True, "cases_replayed": count, "model_calls_made": 0,
             "freeze_sha256": sha(directory / "freeze.json"), "summary_sha256": sha(directory / "summary.json"),
             "records_sha256": auxiliary.campaign.artifact_digest(directory / "episodes"),
             "journals_sha256": auxiliary.campaign.artifact_digest(directory / "calls")}
    save(directory / "audit.json", audit)
    assert value.completed("development-deletion")["complete"]
    summary["physical_diagnostic_cost"]["unknown_usage_calls"] = 1
    save(directory / "summary.json", summary)
    audit["summary_sha256"] = sha(directory / "summary.json")
    save(directory / "audit.json", audit)
    with pytest.raises(ValueError, match="unknown or uncertain usage"):
        value.completed("development-deletion")


def test_main_gate_checks_actual_assigned_denominator_and_never_confirmation_success(tmp_path, monkeypatch):
    value = runner(tmp_path)
    save(value.main_out / "sequence.json", {"plan": value.plan})
    config = read(value.runtime_config)
    client = {"model": config["model"]["alias"], "decoding": config["decoding"],
              "endpoint": "http://{host}:{port}".format(**config["server"]),
              "context_tokens": config["server"]["context_tokens"], "max_output": 4096,
              "timeout": 180.0, "response_mode": "schema"}
    directory = value.main_out / "confirmation"
    frozen = {"kind": "confirmation", "seeds": list(range(11000000, 11000048)),
              "arms": value.plan["arms"], "conditions": ["reuse"], "old_replicates": 8,
              "client_config": client}
    schedule = auxiliary.campaign.planned_records(frozen)
    frozen["planned_records"] = len(schedule)
    assert len(schedule) == 552 * 48
    save(directory / "freeze.json", frozen)
    save(directory / "schedule.json", schedule)
    save(directory / "summary.json", {"fixture": "already-audited gate unit test"})
    save(directory / "audit.json", {"fixture": True})
    (directory / "analysis.json").write_text("INVALID JSON: must never be read as a success gate")
    cost = {"calls": 1, "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
            "unknown_usage_calls": 0}
    audited = {"records_replayed": len(schedule), "network_calls": 0, "cost": cost,
               "records_sha256": "already-verified", "journals_sha256": "already-verified"}
    monkeypatch.setattr(auxiliary.campaign, "_study_evidence", lambda *_args, **_kwargs:
                        (directory, frozen, {"complete": True}, audited,
                         {name: directory / name for name in ("freeze.json", "summary.json", "audit.json")}))
    value.require_main("confirmation")
    assert read(value.out / "prerequisites/confirmation.json")["studies"][0]["kind"] == "confirmation"
    audited["records_replayed"] -= 1
    with pytest.raises(ValueError, match="complete assigned schedule"):
        value.require_main("confirmation")
