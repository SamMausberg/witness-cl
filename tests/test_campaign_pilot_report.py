"""Descriptive arithmetic and orchestration fixtures; never empirical observations.

In-memory binary traces test exact32-stream denominators. Files under tmp_path
test report gates, not model performance, and are never exported to artifacts.
The existing publisher suite independently tests raw-receipt replay bindings.
"""

from copy import deepcopy

import pytest

from tools import campaign_pilot_report as pilot
from witness_cl.campaign_io import read, save, sha
from test_audit_campaign_mechanism import campaign_records as fixture_campaign_records

campaign_records = fixture_campaign_records

SEEDS = list(range(101100, 101132))


def measured_call():
    return {"generation_attempted": True, "status": "completed",
            "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}


@pytest.fixture(scope="module")
def records():
    values = []
    for stream_index, seed in enumerate(SEEDS):
        for arm in pilot.ARMS:
            for phase, count in pilot.PHASES.items():
                for index in range(count):
                    old = phase in {"old_before", "old_after"}
                    operation = pilot.OPERATIONS[index // 8] if phase == "final" else "sum"
                    if old:
                        cutoff = 64 if arm == "full_history" else 48
                        if arm == "delayed" and phase == "old_after":
                            cutoff += 1 if stream_index % 2 == 0 else -1
                        correct = index < cutoff
                    elif phase == "final":
                        correct = (index >= 2 if arm == "full_history" else index < 24 if arm == "ace"
                                   else not (stream_index == 0 and index == 0))
                    else:
                        correct = True
                    cohort = "old" if old else phase
                    evaluator = {"data_sha256": f"{seed}-{cohort}-{index}", "data_seed": index,
                                 "definition": {"operation": operation, "family": index % 8},
                                 "generator": "unit-arithmetic-fixture", "split": "development",
                                 "seed": seed, "condition": "reuse"}
                    trace = {"status": "completed", "reward": int(correct), "evaluator": evaluator,
                             "question": f"{cohort}-{index}", "schema": "unit fixture",
                             "actions": [{"action": "QUERY"}], "answer_action_index": 0,
                             "episode_nonce": f"{seed}-{arm}-{phase}-{index}",
                             "episode_index": index if phase == "ordinary" else 8 if phase == "old_before" else 24,
                             "model_calls": [measured_call()] * (3 if arm == "ace" and phase == "ordinary" else 1)}
                    values.append({"seed": seed, "arm": arm, "condition": "reuse", "phase": phase,
                                   "index": index, "trace": trace,
                                   "sampling_seed": pilot.campaign.sampling_seed(seed, phase, index)})
    # Two lifecycle chains in an in-memory arithmetic fixture. These minimal
    # rows are deliberately not usable as real SQL/provenance audit records.
    scope = {"schema_sha256": "schema", "catalog_sha256": "catalog"}
    entries = [{"key": f"relation-{letter}", "view": {"key": f"view-{letter}"}, "scope": scope,
                "source": {"episode_index": index}, "corroboration": {"episode_index": index + 8}}
               for index, letter in enumerate("ab")]
    registry_events = []
    for index, letter in ((0, "a"), (1, "b"), (8, "a"), (9, "b")):
        registry_events.append({"event": "provisional_admission" if index < 8 else "corroborated",
            "entry": f"relation-{letter}", "episode_index": index,
            "episode_id": f"{SEEDS[0]}-delayed-ordinary-{index}"})
    for row in values:
        if row["seed"] != SEEDS[0] or row["arm"] != "delayed":
            continue
        trace, current = row["trace"], row["trace"]["episode_index"]
        prior = []
        for entry in entries:
            if entry["source"]["episode_index"] < current:
                prior.append(deepcopy(entry))
                if entry["corroboration"]["episode_index"] >= current:
                    prior[-1]["corroboration"] = None
        row["before_snapshot"] = {"registry": {"entries": prior}}
        trace["compatibility"] = {"status": "observed", **scope}
        trace["selected_entries"] = [entry for entry in prior if entry["corroboration"] is not None]
        if row["phase"] == "ordinary":
            trace["memory"] = {"registry": {"events": [event for event in registry_events if event["episode_index"] <= current]}}
            event = next((event for event in registry_events if event["episode_index"] == current), None)
            if event:
                trace["admission"] = {"status": "provisional" if current < 8 else "corroborated", "entry": event["entry"]}
        if row["phase"] == "final" and row["index"] == 1:
            trace["actions"] = [{"action": "COMPOSE", "compiled": {"used_views": ["view-a", "view-b"]}}]
    return values


def events():
    return [{"seed": SEEDS[0], "arm": "delayed", "condition": "reuse", "phase": "final", "index": 1,
             "qualifying_event": True, "structural_mechanism_event": True, "entry_key": key}
            for key in ("relation-a", "relation-b")] + [
        {"seed": SEEDS[1], "arm": "delayed", "condition": "reuse", "phase": "final", "index": 2,
         "qualifying_event": False, "structural_mechanism_event": False, "entry_key": "relation-c"}]


@pytest.fixture(scope="module")
def result(records):
    return pilot.descriptive(records, events(), SEEDS)


def test_mechanism_census_counts_every_arm_stream_including_zero_and_shared_episode(result):
    rows = result["stream_metrics"]
    assert len(rows) == 96
    delayed = [row for row in rows if row["arm"] == "delayed"]
    assert delayed[0]["mechanism"] == {"recorded_events": 2, "qualifying_events": 2,
                                      "structural_events": 2, "qualifying_episodes": 1,
                                      "qualifying_relations": 2}
    assert delayed[1]["mechanism"]["recorded_events"] == 1
    assert sum(row["mechanism"]["qualifying_events"] == 0 for row in rows) == 95
    assert result["by_arm"]["full_history"]["mechanism"]["qualifying_events"] == 0
    assert result["by_arm"]["ace"]["mechanism"]["qualifying_events"] == 0
    assert result["by_arm"]["delayed"]["mechanism"]["streams_with_qualifying_events"] == 1


def test_lifecycle_funnel_deduplicates_persistent_events_and_preserves_zero_stages(result):
    rows = result["stream_metrics"]
    positive = next(row for row in rows if row["seed"] == SEEDS[0] and row["arm"] == "delayed")["lifecycle_funnel"]
    assert positive["own_source_admissions"] == positive["later_corroborations"] == 2
    assert positive["ever_eligible_relations"] == positive["eligible_relations_at_final_start"] == 2
    assert positive["retrieved_relations"] == positive["executed_relations"] == positive["qualifying_chains"] == 2
    assert positive["executed_query_relation_uses"] == 2
    assert positive["retrieved_relation_episode_pairs"] > positive["retrieved_relations"]
    assert len(positive["lifecycle_events"]) == 4
    assert sum(positive["ordinary_admission_statuses"].values()) == 24
    negative = next(row for row in rows if row["seed"] == SEEDS[-1] and row["arm"] == "delayed")["lifecycle_funnel"]
    assert negative["own_source_admissions"] == negative["qualifying_chains"] == 0
    assert negative["correct_direct_source_episodes"] == 24


def test_funnel_matches_real_executor_software_receipts_without_promoting_test_doubles(campaign_records):
    audited = pilot.audit_records(campaign_records)
    funnel = pilot.lifecycle_funnel(campaign_records, audited["events"])
    assert funnel["ordinary_episodes"] == 16
    assert funnel["own_source_admissions"] == funnel["later_corroborations"] == 8
    assert funnel["ever_eligible_relations"] == 8
    assert funnel["executed_relations"] == funnel["executed_query_relation_uses"] == 6
    assert funnel["qualifying_chains"] == 0
    assert len(funnel["lifecycle_events"]) == 16


def test_retention_variance_uses32_stream_contrasts_not6144_binary_pairs(result):
    assert len(result["retention_pairs"]) == 6144
    delayed = result["by_arm"]["delayed"]["retention"]
    assert delayed["paired_n"] == 2048
    assert delayed["wrong_to_correct"] == delayed["correct_to_wrong"] == 16
    assert delayed["discordant_pairs"] == 32
    contrast = delayed["contrast_distribution"]
    assert contrast["n"] == 32
    assert contrast["values"] == [1 / 64, -1 / 64] * 16
    assert contrast["mean"] == 0
    assert contrast["sample_variance"] == pytest.approx(32 / (31 * 64**2))
    assert result["by_arm"]["full_history"]["retention"]["contrast_distribution"]["sample_variance"] == 0
    assert result["by_arm"]["full_history"]["retention"]["both_correct"] == 2048
    assert result["by_arm"]["ace"]["retention"]["discordant_pairs"] == 0


def test_future_ceiling_has_exact_operation_denominators_and_perfect_stream_counts(result):
    history = result["by_arm"]["full_history"]["future"]
    assert history["n"] == 1024 and history["correct"] == 960
    assert history["perfect_streams"] == 0
    assert history["by_outer_operation"]["mean"]["correct"] == 192
    assert history["by_outer_operation"]["max"]["perfect_streams"] == 32
    assert all(row["n"] == 256 for row in history["by_outer_operation"].values())
    delayed = result["by_arm"]["delayed"]["future"]
    assert delayed["correct"] == 1023 and delayed["perfect_streams"] == 31
    assert delayed["observed_remaining_error_rate"] == 1 / 1024
    assert result["by_arm"]["ace"]["future"]["by_outer_operation"]["mean_square"]["accuracy"] == 0


def test_all_phases_and_ace_update_calls_enter_full_cost(result):
    assert result["by_arm"]["full_history"]["full_cost"]["calls"] == 32 * 184
    assert result["by_arm"]["ace"]["full_cost"]["calls"] == 32 * (184 + 48)
    assert result["physical_cost"]["calls"] == 17664 + 32 * 48
    assert result["physical_cost"]["total_tokens"] == (17664 + 32 * 48) * 100


@pytest.mark.parametrize("change", ["missing", "duplicate", "wrong_seed"])
def test_no_partial_or_unassigned_effect_estimates(records, change):
    modified = list(records)
    if change == "missing":
        modified.pop()
    elif change == "duplicate":
        modified[-1] = modified[-2]
    else:
        modified[-1] = {**modified[-1], "seed": 7}
    with pytest.raises(ValueError, match="partial|duplicate, missing, or unassigned"):
        pilot.descriptive(modified, events(), SEEDS)


def test_mismatched_old_pair_and_relabelled_outer_operation_fail(records):
    values = list(records)
    ordinal = next(i for i, row in enumerate(values) if row["phase"] == "old_after")
    values[ordinal] = deepcopy(values[ordinal])
    values[ordinal]["trace"]["evaluator"]["data_sha256"] = "different rows"
    with pytest.raises(ValueError, match="same frozen problem"):
        pilot.descriptive(values, events(), SEEDS)


def test_old_sampling_seed_pair_is_explicit_and_must_match_derived_assignment(records, result):
    first = result["retention_pairs"][0]
    assert first["sampling_seed"] == pilot.campaign.sampling_seed(first["seed"], "old_before", first["index"])
    values = list(records)
    ordinal = next(i for i, row in enumerate(values) if row["phase"] == "old_after")
    values[ordinal] = {**values[ordinal], "sampling_seed": 9}
    with pytest.raises(ValueError, match="sampling seed differs"):
        pilot.descriptive(values, events(), SEEDS)
    values = list(records)
    ordinal = next(i for i, row in enumerate(values) if row["phase"] == "final")
    values[ordinal] = deepcopy(values[ordinal])
    values[ordinal]["trace"]["evaluator"]["definition"]["operation"] = "min"
    with pytest.raises(ValueError, match="assigned eight problems"):
        pilot.descriptive(values, events(), SEEDS)


def test_unknown_usage_and_unassigned_mechanism_event_fail(records):
    modified = list(records)
    modified[0] = deepcopy(modified[0])
    modified[0]["trace"]["model_calls"][0]["usage"] = None
    with pytest.raises(ValueError, match="unknown or uncertain"):
        pilot.descriptive(modified, events(), SEEDS)
    wrong = events()
    wrong[0]["seed"] = 7
    with pytest.raises(ValueError, match="unassigned or invalid event"):
        pilot.descriptive(records, wrong, SEEDS)


def source_identity():
    names = ("src/witness_cl/campaign_env.py", "experiments/delayed_sql.py",
             "tools/audit_campaign_mechanism.py")
    return {name: sha(pilot.ROOT / name) for name in names}


def blocks(tmp_path, *, complete=True):
    paths = [tmp_path / "development", tmp_path / "additional-28"]
    for path, seeds in zip(paths, (SEEDS[:4], SEEDS[4:]), strict=True):
        frozen = {"kind": "development", "split": "development", "seeds": seeds,
                  "arms": list(pilot.ARMS), "conditions": ["reuse"], "old_replicates": 8,
                  "cold_start_each_episode": False, "contains_test_double_calls": False,
                  "planned_records": 552 * len(seeds), "source_sha256": source_identity(),
                  "runtime_config": {"unit_fixture": True}, "client_config": {"unit_fixture": True},
                  "runtime_receipt": {"model_sha256": "not-a-model-unit-fixture"}, "limits": {"fixed": True}}
        save(path / "freeze.json", frozen)
        save(path / "summary.json", {"complete": complete})
        save(path / "audit.json", {"complete": complete, "consistent": True,
                                   "records_replayed": frozen["planned_records"]})
    return paths


def test_partial_blocks_return_readiness_without_effects_or_auditing_outcomes(tmp_path, monkeypatch):
    paths = blocks(tmp_path, complete=False)
    monkeypatch.setattr(pilot.publication, "verified_custom", lambda *_: pytest.fail("partial outcome inspection"))
    report = pilot.build_report(paths, SEEDS)
    assert report["complete"] is False and report["planned_records"] == 17664
    assert report["partial_effect_estimates"] is False
    assert "by_arm" not in report and "mechanism_census" not in report
    assert "No partial mechanism" in pilot.render_markdown(report)


@pytest.mark.parametrize("change", ["overlap", "model", "learner", "split", "panels", "denominator"])
def test_wrong_block_seeds_or_identity_or_denominator_are_rejected(tmp_path, change):
    paths = blocks(tmp_path, complete=False)
    frozen = read(paths[1] / "freeze.json")
    if change == "overlap":
        frozen["seeds"][0] = SEEDS[0]
    elif change == "model":
        frozen["runtime_receipt"]["model_sha256"] = "another-model"
    elif change == "learner":
        frozen["source_sha256"]["experiments/delayed_sql.py"] = "modified-learner"
    elif change == "split":
        frozen["split"] = "confirmation"
    elif change == "panels":
        frozen["old_replicates"] = 1
    else:
        frozen["planned_records"] -= 1
    save(paths[1] / "freeze.json", frozen)
    with pytest.raises(ValueError):
        pilot.build_report(paths, SEEDS)


def test_raw_binding_failure_cannot_be_turned_into_complete_pilot(tmp_path, monkeypatch):
    paths = blocks(tmp_path)

    def invalid(*_args):
        raise ValueError("audit raw-receipt inventory changed")

    monkeypatch.setattr(pilot.publication, "verified_custom", invalid)
    monkeypatch.setattr(pilot, "descriptive", lambda *_: pytest.fail("invalid inputs reached arithmetic"))
    with pytest.raises(ValueError, match="raw-receipt"):
        pilot.build_report(paths, SEEDS)


def test_both_complete_blocks_are_verified_before_aggregation_and_manifest_metadata_survives(tmp_path, monkeypatch, records):
    paths = blocks(tmp_path)
    verified = []
    monkeypatch.setattr(pilot.publication, "verified_custom", lambda _inputs, path, *_: verified.append(path))
    monkeypatch.setattr(pilot.campaign, "load_records", lambda path:
                        [row for row in records if row["seed"] in read(path / "freeze.json")["seeds"]])
    monkeypatch.setattr(pilot, "verified_mechanism", lambda path, *_:
                        [event for event in events() if event["seed"] in read(path / "freeze.json")["seeds"]])
    manifest = tmp_path / "manifest.json"
    save(manifest, {"kind": pilot.KIND, "expected_seeds": SEEDS,
                    "protocol_amendment": "32 descriptive streams; no automatic continuation"})
    report = pilot.build_report(paths, SEEDS, manifest_path=manifest)
    assert verified == paths and report["complete"]
    assert len(report["stream_metrics"]) == 96
    assert len(report["mechanism_census"]["events"]) == 3
    assert report["mechanism_census"]["qualifying_events"] == 2
    assert report["manifest_sha256"] == sha(manifest)
    assert report["reporting_source_sha256"]["tools/campaign_pilot_report.py"] == sha(pilot.ROOT / "tools/campaign_pilot_report.py")
    assert "protocol_amendment" in report["prospective_manifest"]
    assert report["automatic_confirmation_authorized"] is False


def test_cached_mechanism_census_is_bound_to_current_audit_and_zero_is_valid(tmp_path, records, monkeypatch):
    directory = blocks(tmp_path)[0]
    frozen = read(directory / "freeze.json")
    audit = {"records_sha256": "records", "journals_sha256": "journals"}
    cache = {"consistent": True, "model_calls_made": 0, "records": 552 * 4, "events": [],
             "qualifying_event_count": 0, "structural_event_count": 0,
             "freeze_sha256": sha(directory / "freeze.json"), "summary_sha256": sha(directory / "summary.json"),
             "audit_sha256": sha(directory / "audit.json"), **audit}
    save(directory / "audit-mechanism.json", cache)
    source = [row for row in records if row["seed"] in SEEDS[:4]]
    regenerated = {key: value for key, value in cache.items() if not key.endswith("sha256")}
    monkeypatch.setattr(pilot, "audit_records", lambda _: regenerated)
    assert pilot.verified_mechanism(directory, frozen, audit, source, pilot.publication.Inputs()) == []
    cache["audit_sha256"] = "stale"
    save(directory / "audit-mechanism.json", cache)
    with pytest.raises(ValueError, match="input binding changed"):
        pilot.verified_mechanism(directory, frozen, audit, source, pilot.publication.Inputs())


def test_truncated_cache_with_recomputed_zero_counts_cannot_hide_used_relations(tmp_path, records, monkeypatch):
    directory = blocks(tmp_path)[0]
    frozen = read(directory / "freeze.json")
    audit = {"records_sha256": "records", "journals_sha256": "journals"}
    cached = {"consistent": True, "model_calls_made": 0, "records": 552 * 4, "events": [],
              "qualifying_event_count": 0, "structural_event_count": 0,
              "freeze_sha256": sha(directory / "freeze.json"), "summary_sha256": sha(directory / "summary.json"),
              "audit_sha256": sha(directory / "audit.json"), **audit}
    save(directory / "audit-mechanism.json", cached)
    regenerated = {key: value for key, value in cached.items() if not key.endswith("sha256")}
    regenerated.update(events=[{"qualifying_event": True}], qualifying_event_count=1, structural_event_count=1)
    calls = []
    monkeypatch.setattr(pilot, "audit_records", lambda source: calls.append(len(source)) or regenerated)
    source = [row for row in records if row["seed"] in SEEDS[:4]]
    with pytest.raises(ValueError, match="complete independent regeneration"):
        pilot.verified_mechanism(directory, frozen, audit, source, pilot.publication.Inputs())
    assert calls == [552 * 4]


def test_independent_census_comparison_ignores_only_new_offline_timing():
    proof = {"events": [{"qualifying_event": True, "interventions": [
        {"elapsed_seconds": 0.1, "answer_wrong": True, "sql": "source retained"}]}]}
    same = deepcopy(proof)
    same["events"][0]["interventions"][0]["elapsed_seconds"] = 9
    assert pilot.mechanism_semantics(proof) == pilot.mechanism_semantics(same)
    same["events"][0]["interventions"][0]["answer_wrong"] = False
    assert pilot.mechanism_semantics(proof) != pilot.mechanism_semantics(same)


def complete_report(result):
    return {"schema_version": 1, "kind": pilot.KIND, "status": "complete_descriptive_pilot", "complete": True,
            "expected_seeds": SEEDS, "manifest_sha256": "unit-fixture", "scope": "Descriptive only.",
            "automatic_confirmation_authorized": False, "mechanism_census": {"events": events()},
            "input_inventory": {"unit_arithmetic_fixture": True}, **result}


def test_artifacts_are_hash_bound_deterministic_and_cannot_regress_to_partial(tmp_path, result):
    report = complete_report(result)
    first = pilot.write_report(tmp_path, report)
    encoded = (tmp_path / "report.json").read_bytes()
    assert all(sha(tmp_path / value["path"]) == value["sha256"] for value in first["artifacts"].values())
    pilot.write_report(tmp_path, report)
    assert (tmp_path / "report.json").read_bytes() == encoded
    assert len(read(tmp_path / "retention-pairs.json")) == 6144
    assert len(read(tmp_path / "stream-metrics.json")) == 96
    partial = {**report, "complete": False}
    with pytest.raises(ValueError, match="cannot be replaced with an incomplete"):
        pilot.write_report(tmp_path, partial)


def test_report_has_no_inference_or_automatic_confirmation_fields(result):
    report = complete_report(result)
    rendered = pilot.render_markdown(report)
    assert "sample denominator 31" in rendered
    assert "Fixed-program interventions" in rendered
    assert "automatic follow-on run" in rendered
    assert not {"p_value", "confidence_interval", "recommended_n", "all_five_pass"}.intersection(report)
