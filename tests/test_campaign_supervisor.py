import os
import sys

import pytest

from tools.campaign_supervisor import Supervisor, validate_plan
from witness_cl.campaign_io import read, save


def prepare(tmp_path, *, main_status="completed_through_requested_stage", failure=False):
    main = tmp_path / "main"
    main.mkdir()
    save(main / "sequence-status.json", {"pid": os.getpid(), "through": "development", "status": main_status})
    marker = tmp_path / "marker"
    commands = [
        {"name": "first", "argv": [sys.executable, "-c", "raise SystemExit(3)" if failure else "pass"]},
        {"name": "second", "argv": [sys.executable, "-c", "from pathlib import Path; Path(__import__('sys').argv[1]).touch()", str(marker)]},
    ]
    plan = {"schema_version": 1, "cwd": str(tmp_path),
            "source_inputs": [str(__file__)],
            "adopt_sequence": {"directory": str(main), "pid": os.getpid(), "through": "development"},
            "commands": commands}
    path = tmp_path / "plan.json"
    save(path, plan)
    return path, marker


def test_collection_completion_is_not_a_positive_research_claim(tmp_path):
    plan, marker = prepare(tmp_path)
    runner = Supervisor(tmp_path / "supervisor", plan)
    runner.run()
    state = read(runner.out / "status.json")
    assert marker.exists()
    assert state["status"] == "collection_complete_scientific_review_required"
    assert state["research_claim_established"] is False
    marker.unlink()
    runner.run()
    assert not marker.exists()  # Completed commands are not invoked again.


def test_failed_command_stops_without_retry_or_skipping_ahead(tmp_path):
    plan, marker = prepare(tmp_path, failure=True)
    runner = Supervisor(tmp_path / "supervisor", plan)
    with pytest.raises(RuntimeError, match="no automatic retry"):
        runner.run()
    assert not marker.exists()
    assert read(runner.out / "commands/first.json")["returncode"] == 3
    with pytest.raises(ValueError, match="prior command did not finish"):
        runner.run()


def test_failed_development_cannot_start_auxiliary_calls(tmp_path):
    plan, marker = prepare(tmp_path, main_status="stopped")
    runner = Supervisor(tmp_path / "supervisor", plan)
    with pytest.raises(ValueError, match="adopted development stopped"):
        runner.run()
    assert not marker.exists()
    assert not (runner.out / "commands").exists()


def test_adoption_detects_replaced_process_or_changed_plan(tmp_path):
    path, _ = prepare(tmp_path, main_status="running")
    runner = Supervisor(tmp_path / "supervisor", path)
    assert runner.adopt_state() == "running"
    runner.bound["adopted_process"]["start_ticks"] = "replaced"
    with pytest.raises(ValueError, match="process disappeared or changed"):
        runner.adopt_state()
    plan = read(path)
    plan["commands"][0]["argv"][-1] = "print('changed')"
    save(path, plan)
    with pytest.raises(ValueError, match="plan or launcher sources changed"):
        Supervisor(runner.out, path)


def test_shell_commands_and_duplicate_names_are_rejected(tmp_path):
    path, _ = prepare(tmp_path)
    plan = read(path)
    plan["commands"][0]["argv"] = "echo unsafe"
    with pytest.raises(ValueError, match="argv list"):
        validate_plan(plan)
    plan = read(path)
    plan["commands"][1]["name"] = plan["commands"][0]["name"]
    with pytest.raises(ValueError, match="unique"):
        validate_plan(plan)


def test_durable_handoff_survives_main_sequence_continuation(tmp_path):
    path, marker = prepare(tmp_path)
    runner = Supervisor(tmp_path / "supervisor", path)
    runner.run()
    save(tmp_path / "main/sequence-status.json", {
        "pid": os.getpid() + 1, "through": "diagnostics", "status": "completed_through_requested_stage"})
    marker.unlink()
    Supervisor(runner.out, path).run()
    assert not marker.exists()


def test_future_outputs_do_not_change_explicit_source_binding(tmp_path):
    path, _ = prepare(tmp_path)
    plan = read(path)
    future = tmp_path / "generated.json"
    plan["commands"][1]["argv"] = [sys.executable, "-c", "pass", str(future)]
    save(path, plan)
    runner = Supervisor(tmp_path / "supervisor", path)
    future.write_text("{}\n")
    runner.run()
    assert read(runner.out / "status.json")["status"] == "collection_complete_scientific_review_required"


def test_unbound_future_python_entrypoint_cannot_be_planned(tmp_path):
    path, _ = prepare(tmp_path)
    plan = read(path)
    plan["commands"][1]["argv"] = [sys.executable, str(tmp_path / "future.py")]
    with pytest.raises(ValueError, match="frozen present source inputs"):
        validate_plan(plan)
