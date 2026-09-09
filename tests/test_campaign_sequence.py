import pytest

from tools.campaign_sequence import ROOT, Sequence, seeds_for, validate_plan
from witness_cl.campaign_io import read, save


def plan():
    return read(ROOT / "configs/campaign_sequence.json")


def test_seed_registry_keeps_studies_disjoint_even_after_sizing():
    validate_plan(plan(), confirmation_n=419)
    bad = plan()
    bad["confirmation"]["seed_start"] = bad["sizing"]["seed_start"]
    with pytest.raises(ValueError, match="share stream seeds"):
        validate_plan(bad, confirmation_n=419)
    bad = plan()
    bad["separate_assay"]["seed_start"] = bad["development"]["seed_start"]
    with pytest.raises(ValueError, match="assay streams overlap"):
        validate_plan(bad)


class Harness(Sequence):
    def __init__(self, tmp_path, *, failures=(), mechanism_count=5):
        self.out = tmp_path
        self.plan = plan()
        self.events = []
        self.failures = failures
        self.mechanism_count = mechanism_count

    def freeze(self, job, kind, *, confirmation_n=None):
        self.events.append(("freeze", job["name"]))
        if kind == "confirmation":
            assert len(seeds_for(job, confirmation_n=confirmation_n)) == 419
        directory = self.out / job["name"]
        directory.mkdir(exist_ok=True)
        return directory

    def execute(self, directory, *, mechanism=False):
        self.events.append(("execute", directory.name))
        if mechanism:
            save(directory / "audit-mechanism.json", {"events": [
                {"qualifying_event": True, "seed": i % 3} for i in range(self.mechanism_count)
            ]})
        return {"qualified": directory.name not in self.failures}

    def invoke(self, script, arguments, log_name):
        self.events.append(("invoke", log_name))
        if log_name == "sizing-power":
            save(self.out / "sizing/power.json", {"streams": 419})
        if log_name == "confirmation-analysis":
            save(self.out / "confirmation/analysis.json", {"all_five_pass": False})


def test_both_qualifications_freeze_first_and_failure_keeps_second_scheduled_run(tmp_path):
    runner = Harness(tmp_path, failures=("qualification-reuse",))
    with pytest.raises(ValueError, match="completed qualification failed"):
        runner.run("diagnostics")
    assert runner.events == [
        ("freeze", "qualification-reuse"), ("freeze", "qualification-drift"),
        ("execute", "qualification-reuse"), ("execute", "qualification-drift"),
    ]


def test_no_mechanism_cannot_consume_fresh_sizing_or_confirmation(tmp_path):
    runner = Harness(tmp_path, mechanism_count=0)
    with pytest.raises(ValueError, match="mechanism development gate failed"):
        runner.run("confirmation")
    assert not any(name in {"sizing", "confirmation"} for _, name in runner.events)


def test_negative_confirmation_still_runs_all_diagnostics(tmp_path):
    runner = Harness(tmp_path)
    runner.run("diagnostics")
    assert runner.events[-6:] == [
        ("freeze", "stable-drift"), ("execute", "stable-drift"),
        ("invoke", "stable-drift-analysis"),
        ("freeze", "nonreuse"), ("execute", "nonreuse"),
        ("invoke", "nonreuse-analysis"),
    ]
    assert read(tmp_path / "confirmation/analysis.json")["all_five_pass"] is False


def test_changed_existing_stage_cannot_be_resumed_under_new_plan(tmp_path):
    runner = Harness(tmp_path)
    job = runner.plan["qualification"][0]
    directory = tmp_path / job["name"]
    directory.mkdir()
    save(directory / "freeze.json", {"kind": "qualification", "seeds": [7, 8],
                                      "arms": ["full_history"], "conditions": ["reuse"]})
    with pytest.raises(ValueError, match="differs from the frozen stage schedule"):
        Sequence.freeze(runner, job, "qualification")
