"""Transient schema fixtures test publication gates, never provide study data.

All pseudo-receipts below live under pytest tmp_path. They are deliberately small
stand-ins for audited files, not model results, and are never copied to artifacts
or the paper. Rendering tests cover negative outcomes as well as missing data.
"""
from copy import deepcopy
import shutil

import pytest

from tools import publish_campaign as pub
from witness_cl.campaign_analysis import analyze
from witness_cl.campaign_io import read, save, usage


def call(tokens=100):
    return {"status": "completed", "generation_attempted": True,
            "usage": {"prompt_tokens": tokens - 10, "completion_tokens": 10, "total_tokens": tokens}}


def test_failed_setup_unknown_usage_is_reported_separately(tmp_path):
    path = tmp_path / "smoke-failed.json"
    save(path, {"status": "failed", "purpose": "generic transport check",
                "records": [{"status": "failed", "generation_attempted": True, "usage": None}]})
    snapshot = pub.build_snapshot([], setup_paths=[path])
    assert snapshot["studies"] == []
    cost = snapshot["setup"][0]["cost"]
    assert cost["calls"] == 1 and cost["unknown_usage_calls"] == 1
    assert cost["total_tokens"] is None
    assert "Separate runtime setup calls" in pub.render_markdown(snapshot)
    assert "Primary outcomes are unmeasured" in pub.render_tex(snapshot)


def bundle(tmp_path, *, kind="development", test_double=False):
    """A complete small scheduled schema, explicitly not an inference run."""
    from tools.campaign import planned_records, summarize
    out = tmp_path / kind
    out.mkdir()
    name = "src/witness_cl/campaign_analysis.py"
    target = out / "sources" / name
    target.parent.mkdir(parents=True)
    shutil.copyfile(pub.ROOT / name, target)
    frozen = {"kind": kind, "contains_test_double_calls": test_double,
              "source_sha256": {name: pub.file_sha(target)}, "seeds": [1, 2],
              "conditions": ["reuse"], "arms": ["delayed"] if kind == "qualification" else ["full_history", "ace", "delayed"],
              "old_replicates": 1, "cold_start_each_episode": kind == "qualification",
              "qualification_gate": {"warm": 7, "binding": 6, "new_outer": 6, "future": 6}}
    schedule = planned_records(frozen)
    frozen.update(planned_records=len(schedule), schedule_sha256=pub.digest(schedule))
    save(out / "freeze.json", frozen)
    save(out / "schedule.json", schedule)
    records = []
    for item in schedule:
        correct = (item["index"] % 8 < 2) if kind == "qualification" else (
            item["phase"] != "final" or item["index"] < (16 if item["arm"] == "delayed" else 24))
        trace = {"phase": item["phase"], "arm": item["arm"], "status": "completed",
                 "reward": float(correct), "model_calls": [call()]}
        record = {**item, "schema_fixture": True, "freeze_sha256": pub.file_sha(out / "freeze.json"), "trace": trace}
        records.append(record)
        save(out / "episodes" / (item["key"] + ".json"), record)
        save(out / "calls" / item["key"] / "000.json", {"state": "recorded", "calls": [call()]})
    save(out / "summary.json", summarize(records, frozen))
    bind_audit(out)
    return out


def bind_audit(out):
    tracker = pub.Inputs()
    frozen, summary = read(out / "freeze.json"), read(out / "summary.json")
    audit = {"complete": True, "consistent": True, "network_calls": 0,
             "records_replayed": frozen["planned_records"],
             "freeze_sha256": pub.file_sha(out / "freeze.json"),
             "summary_sha256": pub.file_sha(out / "summary.json"),
             "records_sha256": tracker.tree(out / "episodes"),
             "journals_sha256": tracker.tree(out / "calls"), "cost": summary["cost"]}
    save(out / "audit.json", audit)


def confirmation_fixture(tmp_path):
    """Unit-test analyzed input; complete raw receipt gates are tested separately.

    This fixture is passed directly to confirmation(), never to build_snapshot().
    It cannot masquerade as an end-to-end audited empirical study.
    """
    out = tmp_path / "confirmation-analysis-unit"
    out.mkdir()
    name = "src/witness_cl/campaign_analysis.py"
    frozen = {"kind": "confirmation", "source_sha256": {name: pub.file_sha(pub.ROOT / name)},
              "seeds": list(range(200000, 200048)), "conditions": ["reuse"],
              "arms": ["full_history", "ace", "delayed"], "old_replicates": 8,
              "planned_records": 552 * 48, "evidence_sha256": {}, "prerequisites": {},
              "client_config": {"model": "analysis-unit-fixture"},
              "runtime_config": {"model": "analysis-unit-fixture"},
              "runtime_receipt": {"model_sha256": "a" * 64}}
    groups, rows = [], []
    for seed in frozen["seeds"]:
        arms = {}
        for arm in frozen["arms"]:
            correct = 16 if arm == "delayed" else 24
            groups.append({"seed": seed, "arm": arm, "condition": "reuse", "records": 184,
                           "cost": usage([call()] * 184), "phases": {
                               "ordinary": {"n": 24, "correct": 24},
                               "old_before": {"n": 64, "correct": 60},
                               "old_after": {"n": 64, "correct": 40},
                               "final": {"n": 32, "correct": correct}}})
            arms[arm] = {"future_accuracy": correct / 32, "old_before_accuracy": 60 / 64,
                         "old_after_accuracy": 40 / 64, "total_tokens": 18400}
        rows.append({"seed": seed, "complete": True, "arms": arms})
    summary = {"complete": True, "groups": groups, "cost": usage([call()] * frozen["planned_records"])}
    save(out / "summary.json", summary)
    save(out / "audit.json", {"unit_analysis_input": True})
    sizing = out / "evidence/sizing"
    sf = {"kind": "sizing", "seeds": list(range(32)), "old_replicates": 8,
          "conditions": ["reuse"], "arms": frozen["arms"], "planned_records": 552 * 32,
          "contains_test_double_calls": False,
          **{key: frozen[key] for key in ("client_config", "runtime_config", "runtime_receipt")}}
    pilot_groups = []
    for seed in sf["seeds"]:
        for template in groups[:3]:
            group = deepcopy(template)
            group["seed"] = seed
            pilot_groups.append(group)
    ss = {"complete": True, "cost": usage([call()] * sf["planned_records"]), "groups": pilot_groups}
    save(sizing / "freeze.json", sf)
    save(sizing / "summary.json", ss)
    sa = {"complete": True, "consistent": True, "network_calls": 0, "cost": ss["cost"],
          "records_replayed": sf["planned_records"],
          "freeze_sha256": pub.file_sha(sizing / "freeze.json"),
          "summary_sha256": pub.file_sha(sizing / "summary.json")}
    save(sizing / "audit.json", sa)
    power = {"streams": 48, "pilot_n": 32, "analysis_source_sha256": frozen["source_sha256"][name],
             "freeze_sha256": sa["freeze_sha256"], "summary_sha256": sa["summary_sha256"],
             "audit_sha256": pub.file_sha(sizing / "audit.json"),
             "joint_power_simulations": [{"streams": 48, "trials": 100000, "seed": 271828,
                                           "one_sided_95_mc_lower": 0.81}]}
    save(sizing / "power.json", power)
    hashes = {n: pub.file_sha(sizing / n) for n in ("freeze.json", "summary.json", "audit.json", "power.json")}
    frozen["evidence_sha256"] = {"sizing/" + n: h for n, h in hashes.items()}
    frozen["prerequisites"]["sizing"] = {"seeds": sf["seeds"], "streams": 48, "sha256": hashes}
    save(out / "freeze.json", frozen)
    analysis = analyze(rows, frozen_n=48)
    analysis.update(freeze_sha256=pub.file_sha(out / "freeze.json"),
                    summary_sha256=pub.file_sha(out / "summary.json"),
                    audit_sha256=pub.file_sha(out / "audit.json"),
                    analysis_source_sha256=frozen["source_sha256"][name])
    save(out / "analysis.json", analysis)
    return out, frozen, summary


def unit_confirmation_study(tmp_path):
    out, frozen, summary = confirmation_fixture(tmp_path)
    analysis = pub.confirmation(pub.Inputs(), out, frozen, summary)
    return {"path": str(out), "name": "confirmation", "kind": "confirmation", "status": "complete",
            "outcomes_publishable": True, "primary_claim": analysis["all_five_pass"],
            "streams": 48, "conditions": ["reuse"], "analysis": analysis}


def test_pending_inputs_are_unmeasured_and_deterministic(tmp_path):
    snapshot = pub.build_snapshot([tmp_path / "not-yet-frozen"])
    assert snapshot["studies"][0]["status"] == "pending"
    assert snapshot == pub.build_snapshot([tmp_path / "not-yet-frozen"])
    tex = pub.render_tex(snapshot)
    assert r"\pending" in tex and "Not evaluated" in tex
    assert "0.00 pp" not in tex
    assert "No frozen study" in pub.render_markdown(snapshot)
    assert snapshot["model_calls_made"] == 0


def test_complete_negative_confirmation_is_published(tmp_path):
    snapshot = pub.build_snapshot([])
    study = unit_confirmation_study(tmp_path)
    snapshot["studies"] = [study]
    assert study["status"] == "complete" and study["outcomes_publishable"]
    assert not study["primary_claim"]
    tex = pub.render_tex(snapshot)
    assert "conjunction does not pass" in tex and "-25.00 pp" in tex
    assert "Does not pass" in tex and "1.000" in tex
    assert "not to the displayed aggregate ratio" in tex
    assert "Five-endpoint conjunction does not pass" in pub.render_markdown(snapshot)


@pytest.mark.parametrize("target", ["summary.json", "freeze.json", "first_episode",
                                  "first_call", "sources/src/witness_cl/campaign_analysis.py"])
def test_stale_bound_inputs_suppress_outcomes(tmp_path, target):
    out = bundle(tmp_path)
    key = read(out / "schedule.json")[0]["key"]
    target = {"first_episode": f"episodes/{key}.json", "first_call": f"calls/{key}/000.json"}.get(target, target)
    path = out / target
    path.write_text(path.read_text() + " ")
    snapshot = pub.build_snapshot([out])
    assert snapshot["studies"][0]["status"] == "invalid"
    assert not snapshot["studies"][0]["outcomes_publishable"]
    assert "-25.00 pp" not in pub.render_tex(snapshot)


def test_tampered_analysis_does_not_change_endpoint_decisions(tmp_path):
    out, frozen, summary = confirmation_fixture(tmp_path)
    value = read(out / "analysis.json")
    value["all_five_pass"] = True
    value["endpoints"]["retention"]["mean"] = 0
    save(out / "analysis.json", value)
    with pytest.raises(ValueError, match="prespecified"):
        pub.confirmation(pub.Inputs(), out, frozen, summary)


def test_explicit_and_hidden_test_doubles_are_excluded(tmp_path):
    out = bundle(tmp_path, test_double=True)
    assert pub.build_snapshot([out])["studies"][0]["status"] == "excluded_test_double"
    frozen = read(out / "freeze.json")
    frozen["contains_test_double_calls"] = False
    save(out / "freeze.json", frozen)
    bind_audit(out)
    raw = out / "calls" / read(out / "schedule.json")[0]["key"] / "000.json"
    value = read(raw)
    value["calls"][0]["test_double"] = True
    save(raw, value)
    study = pub.build_snapshot([out])["studies"][0]
    assert study["status"] == "invalid" and "test-double" in study["reason"]


def test_partial_or_unknown_usage_never_becomes_confirmatory(tmp_path):
    out = bundle(tmp_path)
    summary = read(out / "summary.json")
    summary["complete"] = False
    save(out / "summary.json", summary)
    assert pub.build_snapshot([out])["studies"][0]["status"] == "incomplete"
    summary["complete"] = True
    summary["cost"]["unknown_usage_calls"] = 1
    summary["cost"]["total_tokens"] = None
    save(out / "summary.json", summary)
    bind_audit(out)
    study = pub.build_snapshot([out])["studies"][0]
    assert study["status"] == "invalid" and "unknown" in study["reason"]


def test_development_analysis_cannot_be_used_for_primary(tmp_path):
    out = bundle(tmp_path, kind="development")
    save(out / "analysis.json", {"all_five_pass": True})
    snapshot = pub.build_snapshot([out])
    study = snapshot["studies"][0]
    assert study["outcomes_publishable"] and "analysis" not in study
    assert not study["primary_claim"]
    assert "Not evaluated" in pub.render_tex(snapshot)


def test_failed_qualification_is_retained_in_both_reports(tmp_path):
    out = bundle(tmp_path, kind="qualification")
    snapshot = pub.build_snapshot([out])
    assert "Qualification fails" in pub.render_tex(snapshot)
    md = pub.render_markdown(snapshot)
    assert "Qualification fails" in md and "2/8" in md


def test_discovery_prunes_source_snapshots_and_receipts(tmp_path):
    for name in ("one", "two", "runtime/fake", "one/sources/fake", "calls/fake"):
        save(tmp_path / name / "freeze.json", {})
    assert pub.discover(tmp_path) == [tmp_path / "one", tmp_path / "two"]
    with pytest.raises(ValueError, match="discovery limit"):
        pub.discover(tmp_path, max_studies=1)


def test_latex_cannot_inject_commands_from_study_names():
    assert pub.latex(r"x_1%\input{secret}") == r"x\_1\%\textbackslash{}input\{secret\}"


def test_mechanism_zero_is_measured_but_agent_deletion_not_inferred(tmp_path):
    out = bundle(tmp_path, kind="development")
    audit = read(out / "audit.json")
    value = {k: audit[k] for k in ("freeze_sha256", "summary_sha256", "records_sha256", "journals_sha256")}
    value.update(audit_sha256=pub.file_sha(out / "audit.json"), consistent=True,
                 model_calls_made=0, events=[], qualifying_event_count=0, totals={})
    save(out / "audit-mechanism.json", value)
    snapshot = pub.build_snapshot([out])
    assert snapshot["studies"][0]["mechanism"]["qualifying_event_count"] == 0
    assert "development & 0" in pub.render_tex(snapshot)
    assert "not established by this audit" in pub.render_markdown(snapshot)


def test_nonfinite_and_missing_usage_rejected():
    with pytest.raises(ValueError):
        pub.number(float("nan"))
    with pytest.raises(ValueError):
        pub.known_cost({"calls": 1, "total_tokens": None})


def test_all_confirmation_studies_retained_without_selecting_winner(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    snapshot = pub.build_snapshot([])
    snapshot["studies"] = [unit_confirmation_study(first), unit_confirmation_study(second)]
    assert pub.render_tex(snapshot).count("conjunction does not pass") == 2
    assert pub.render_tex(snapshot).count(r"\label{tab:primary}") == 1


def test_frozen_source_not_current_workspace_hash_is_analysis_provenance(tmp_path):
    out, frozen, summary = confirmation_fixture(tmp_path)
    analysis = read(out / "analysis.json")
    analysis["analysis_source_sha256"] = "0" * 64
    save(out / "analysis.json", analysis)
    with pytest.raises(ValueError, match="frozen analysis source"):
        pub.confirmation(pub.Inputs(), out, frozen, summary)


def test_native_nonreplay_audit_cannot_publish(tmp_path):
    frozen = {"contains_test_double_calls": False}
    audit = {"all_complete_and_passed": True, "model_free_replay": False, "model_calls_made": 0}
    with pytest.raises(ValueError, match="model-free"):
        pub.verified_native(pub.Inputs(), tmp_path, frozen, audit)


def test_assay_overlapping_logical_costs_are_explicit():
    snapshot = pub.build_snapshot([])
    snapshot["studies"] = [{"path": "/schema-fixture", "name": "assay", "kind": "assay_diagnostic",
                            "status": "complete", "outcomes_publishable": True, "primary_claim": False,
                            "streams": 64, "conditions": [], "logical_checkpoint_costs_overlap": True,
                            "descriptive": [{"condition": "reuse", "checkpoint": 24, "arm": "delayed",
                                             "streams": 64, "correct": 300, "n": 512, "tokens": 900}]}]
    text = pub.render_markdown(deepcopy(snapshot))
    assert "must not be summed as physical cost" in text
    assert "300/512" in text


@pytest.mark.parametrize("field", ["record_count", "correct_count", "cost", "raw_outcome"])
def test_rebound_audit_cannot_publish_wrong_denominators_or_outcomes(tmp_path, field):
    out = bundle(tmp_path)
    summary = read(out / "summary.json")
    if field == "record_count":
        summary["groups"][0]["records"] = 184
    elif field == "correct_count":
        summary["groups"][0]["phases"]["final"]["correct"] -= 1
    elif field == "cost":
        summary["groups"][0]["cost"] = usage([call()])
    else:
        path = out / "episodes" / (read(out / "schedule.json")[0]["key"] + ".json")
        record = read(path)
        record["trace"]["reward"] = 0.0
        save(path, record)
    save(out / "summary.json", summary)
    bind_audit(out)
    result = pub.build_snapshot([out])["studies"][0]
    assert result["status"] == "invalid" and not result["outcomes_publishable"]
    assert "summary denominators" in result["reason"]


@pytest.mark.parametrize("mutation", ["small_n", "thin_schedule", "unbound_power", "wrong_power_n", "failed_power"])
def test_confirmation_requires_full_assigned_n_and_bound_prospective_power(tmp_path, mutation):
    out, frozen, summary = confirmation_fixture(tmp_path)
    if mutation == "small_n":
        frozen["seeds"] = [1, 2]
        frozen["planned_records"] = 552 * 2
    elif mutation == "thin_schedule":
        frozen["planned_records"] = 6
    else:
        path = out / "evidence/sizing/power.json"
        power = read(path)
        if mutation == "wrong_power_n":
            power["streams"] = 49
        elif mutation == "failed_power":
            power["joint_power_simulations"][-1]["one_sided_95_mc_lower"] = 0.79
        else:
            power["streams"] = 900
        save(path, power)
        if mutation != "unbound_power":
            frozen["evidence_sha256"]["sizing/power.json"] = pub.file_sha(path)
            frozen["prerequisites"]["sizing"]["sha256"]["power.json"] = pub.file_sha(path)
    with pytest.raises(ValueError):
        pub.confirmation(pub.Inputs(), out, frozen, summary)


def deletion_bundle(tmp_path, *, eligible=0):
    """Saved schema fixtures for the deletion publisher, never model evidence."""
    source = bundle(tmp_path)
    source_schedule = read(source / "schedule.json")
    cases, events = [], []
    if eligible:
        from test_delayed_sql import ready_memory
        from witness_cl.delayed_memory import DelayedMemory
        ordinal = next(i for i, item in enumerate(source_schedule) if item["arm"] == "delayed")
        item = source_schedule[ordinal]
        path = source / "episodes" / (item["key"] + ".json")
        original = read(path)
        memory = ready_memory()
        original["before_snapshot"] = memory.snapshot()
        original["sampling_seed"] = 314
        original["trace"].update(episode_index=2, episode_nonce="schema-unit-baseline")
        save(path, original)
        removed = memory.registry.entries[0]
        memory = DelayedMemory.from_snapshot(memory.snapshot())
        memory.registry.entries = []
        case = {key: original[key] for key in ("seed", "condition", "arm", "phase", "index", "sampling_seed")}
        case.update(key="deletion-00000", original_record_ordinal=ordinal,
                    original_record_sha256=pub.digest(original), original_correct=True, learn=False,
                    before_snapshot=memory.snapshot(), removed_entry_key=removed.key,
                    removed_view_key=removed.view.key, original_episode_nonce="schema-unit-baseline",
                    episode_index=2)
        cases.append(case)
        events.append({"structural_mechanism_event": True, "record_ordinal": ordinal,
                       "entry_key": removed.key, "view_key": removed.view.key})
        bind_audit(source)
    out = tmp_path / "deletion"
    source_frozen, source_audit = read(source / "freeze.json"), read(source / "audit.json")
    for name in source_frozen["source_sha256"]:
        target = out / "sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "sources" / name, target)
    selection = {"events": events, "consistent": True, "model_calls_made": 0,
                 "structural_event_count": eligible, "records": len(source_schedule)}
    save(out / "cases.json", cases)
    save(out / "mechanism-selection.json", selection)
    frozen = {"experiment": "agent_relation_deletion_v1", "contains_test_double_calls": False,
              "source_sha256": source_frozen["source_sha256"], "cases_sha256": pub.digest(cases),
              "planned_cases": eligible, "selection_receipt_sha256": pub.file_sha(out / "mechanism-selection.json"),
              "source_study": str(source), "source_freeze_sha256": pub.file_sha(source / "freeze.json"),
              "source_audit_sha256": pub.file_sha(source / "audit.json"),
              "source_records_sha256": source_audit["records_sha256"],
              "source_journals_sha256": source_audit["journals_sha256"],
              "original_acquisition_and_evaluation_cost": source_audit["cost"]}
    save(out / "freeze.json", frozen)
    for case in cases:
        trace = {"status": "completed", "learn": False, "reward": 0.0,
                 "memory": case["before_snapshot"], "model_calls": [call()],
                 "phase": case["phase"], "arm": case["arm"], "episode_index": 2,
                 "episode_nonce": "schema-unit-baseline"}
        save(out / "episodes" / (case["key"] + ".json"), {"case_sha256": pub.digest(case),
             "freeze_sha256": pub.file_sha(out / "freeze.json"), "trace": trace})
        save(out / "calls" / case["key"] / "000.json", {"state": "recorded", "calls": [call()]})
    summary = {"complete": True, "planned_cases": eligible, "recorded_cases": eligible,
               "completed_cases": eligible, "answer_flips_to_wrong": eligible,
               "correct_despite_deletion": 0, "physical_diagnostic_cost": usage([call()] * eligible),
               "case_selection_was_frozen_before_rerun": True, "feedback_to_original_campaign": False,
               "original_acquisition_and_evaluation_cost": source_audit["cost"]}
    save(out / "summary.json", summary)
    tracker = pub.Inputs()
    audit = {"consistent": True, "complete": True, "model_calls_made": 0, "cases_replayed": eligible,
             "freeze_sha256": pub.file_sha(out / "freeze.json"), "summary_sha256": pub.file_sha(out / "summary.json"),
             "records_sha256": tracker.tree(out / "episodes") if eligible else pub.digest({}),
             "journals_sha256": tracker.tree(out / "calls") if eligible else pub.digest({})}
    save(out / "audit.json", audit)
    return out


@pytest.mark.parametrize("eligible", [0, 1])
def test_agent_deletion_complete_census_and_zero_are_recognized(tmp_path, eligible):
    out = deletion_bundle(tmp_path, eligible=eligible)
    snapshot = pub.build_snapshot([out])
    result = snapshot["studies"][0]
    assert result["status"] == "complete" and result["kind"] == "agent_deletion"
    assert result["deletion"]["eligible_cases"] == eligible
    assert result["deletion"]["answer_flips_to_wrong"] == eligible
    assert result["physical_cost"]["calls"] == eligible
    if not eligible:
        assert "zero eligible deletion cases" in pub.render_markdown(snapshot)
        assert "Zero eligible cases; no rerun estimate" in pub.render_tex(snapshot)
    else:
        assert "1/1 answers flip to wrong" in pub.render_markdown(snapshot)


def test_deletion_cannot_drop_eligible_events_or_restate_wrong_counts(tmp_path):
    out = deletion_bundle(tmp_path, eligible=1)
    summary = read(out / "summary.json")
    summary["answer_flips_to_wrong"] = 0
    save(out / "summary.json", summary)
    audit = read(out / "audit.json")
    audit["summary_sha256"] = pub.file_sha(out / "summary.json")
    save(out / "audit.json", audit)
    result = pub.build_snapshot([out])["studies"][0]
    assert result["status"] == "invalid" and "denominators or outcomes" in result["reason"]


def test_candidate_labels_distinguish_identical_stage_names():
    root = pub.ROOT / "artifacts/campaign"
    assert pub.study_name(root / "coder-v1/qualification-reuse") == "coder-v1 / qualification-reuse"
    assert pub.study_name(root / "dense-v2/qualification-reuse") == "dense-v2 / qualification-reuse"


def test_zero_deletion_census_cannot_hide_an_eligible_event(tmp_path):
    out = deletion_bundle(tmp_path)
    selection = read(out / "mechanism-selection.json")
    selection["structural_event_count"] = 1
    save(out / "mechanism-selection.json", selection)
    frozen = read(out / "freeze.json")
    frozen["selection_receipt_sha256"] = pub.file_sha(out / "mechanism-selection.json")
    save(out / "freeze.json", frozen)
    audit = read(out / "audit.json")
    audit["freeze_sha256"] = pub.file_sha(out / "freeze.json")
    save(out / "audit.json", audit)
    result = pub.build_snapshot([out])["studies"][0]
    assert result["status"] == "invalid" and "eligible frozen mechanism events" in result["reason"]
