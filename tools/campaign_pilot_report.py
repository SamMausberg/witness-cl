#!/usr/bin/env python3
"""Describe the complete frozen 32-stream pilot; never size or start confirmation.

The previously assigned four-stream development and an independent 28-stream
pilot block must finish their exact schedules and model-free replay audits.
Until then, the only output is readiness and missing denominators. Complete
outputs include every mechanism event, every paired old-panel observation,
stream-level variance, future accuracy by outer operation, and full token costs.
No confidence interval, efficacy gate, power recommendation, or model call.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tools import campaign, publish_campaign as publication
from tools.audit_campaign_mechanism import audit_records
from witness_cl.campaign_io import canonical, read, save, sha, usage

ARMS = ("full_history", "ace", "delayed")
PHASES = {"ordinary": 24, "old_before": 64, "old_after": 64, "final": 32}
OPERATIONS = ("mean", "max", "variance", "mean_square")
RECORDS_PER_STREAM = sum(PHASES.values()) * len(ARMS)
KIND = "descriptive_pilot_32"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_seeds(expected_seeds):
    require(isinstance(expected_seeds, list) and len(expected_seeds) == 32
            and len(set(expected_seeds)) == 32
            and all(type(seed) is int and 0 <= seed < 2**63 for seed in expected_seeds),
            "exactly 32 distinct prospectively assigned independent stream seeds required")
    return expected_seeds


def distribution(values):
    """Descriptive sample moments; individual binary panels are not replicates."""
    require(bool(values), "descriptive distribution cannot be empty")
    return {"n": len(values), "values": list(values), "mean": statistics.mean(values),
            "sample_variance": statistics.variance(values) if len(values) > 1 else None,
            "sample_standard_deviation": statistics.stdev(values) if len(values) > 1 else None,
            "minimum": min(values), "median": statistics.median(values), "maximum": max(values)}


def total_cost(costs):
    costs = list(costs)
    for cost in costs:
        publication.known_cost(cost)
    result = {key: sum(cost[key] for cost in costs) for key in
              ("calls", "prompt_tokens", "completion_tokens", "total_tokens")}
    return {**result, "unknown_usage_calls": 0, "potential_generation_calls": 0,
            "scope": "all acquisition, reflection, checks, old panels, and final evaluation calls"}


def identity(frozen):
    """No mixing learner, generator, solver, decoding, or model bytes across blocks."""
    learner = campaign._learner_identity(frozen)
    require("src/witness_cl/campaign_env.py" in learner and "experiments/delayed_sql.py" in learner,
            "pilot learner/generator identity is missing")
    require(isinstance(frozen.get("runtime_receipt", {}).get("model_sha256"), str),
            "pilot model byte identity is missing")
    return {"learner_sha256": learner, "runtime_config": frozen["runtime_config"],
            "client_config": frozen["client_config"],
            "model_sha256": frozen["runtime_receipt"]["model_sha256"],
            "backend": frozen["runtime_receipt"].get("backend"),
            "limits": frozen["limits"], "split": frozen["split"],
            "mechanism_auditor_sha256": frozen["source_sha256"]["tools/audit_campaign_mechanism.py"]}


def readiness(studies, expected_seeds, inputs):
    validate_seeds(expected_seeds)
    require(len(studies) == 2 and len(set(studies)) == 2,
            "the fixed four-stream development and independent 28-stream pilot blocks are required")
    rows, frozen_blocks, seen = [], [], set()
    for directory in studies:
        row = {"study": str(directory), "frozen": (directory / "freeze.json").is_file(),
               "complete_audited": False,
               "recorded_episode_files": len(list((directory / "episodes").glob("*.json")))}
        if row["frozen"]:
            frozen = inputs.read(directory / "freeze.json")
            require(frozen.get("kind") == "development" and frozen.get("split") == "development"
                    and frozen.get("arms") == list(ARMS) and frozen.get("conditions") == ["reuse"]
                    and frozen.get("old_replicates") == 8 and frozen.get("cold_start_each_episode") is False
                    and frozen.get("contains_test_double_calls") is False,
                    "pilot must use the real development generator, three arms and full 64-pair old panels")
            seeds = frozen["seeds"]
            require(len(seeds) == len(set(seeds)) and set(seeds) <= set(expected_seeds)
                    and not seen.intersection(seeds), "unassigned or overlapping pilot stream seeds")
            seen.update(seeds)
            require(frozen["planned_records"] == RECORDS_PER_STREAM * len(seeds),
                    "pilot block denominator differs from 552 records per stream")
            row.update(seeds=seeds, planned_records=frozen["planned_records"])
            frozen_blocks.append((directory, frozen))
            if (directory / "summary.json").is_file() and (directory / "audit.json").is_file():
                summary, audit = (inputs.read(directory / name) for name in ("summary.json", "audit.json"))
                row["complete_audited"] = (summary.get("complete") is True and audit.get("complete") is True
                                           and audit.get("consistent") is True
                                           and audit.get("records_replayed") == frozen["planned_records"])
        rows.append(row)
    if len(frozen_blocks) == 2:
        require([len(frozen["seeds"]) for _, frozen in frozen_blocks] == [4, 28],
                "pilot block allocation must be the original 4 followed by independent 28 streams")
        require(seen == set(expected_seeds), "frozen blocks do not cover exactly the 32 planned streams")
        require(identity(frozen_blocks[0][1]) == identity(frozen_blocks[1][1]),
                "pilot blocks differ in learner, model, generator, or execution limits")
    return rows, frozen_blocks


def verified_mechanism(directory, frozen, audit, records, inputs):
    path = directory / "audit-mechanism.json"
    require(sha(ROOT / "tools/audit_campaign_mechanism.py")
            == frozen["source_sha256"]["tools/audit_campaign_mechanism.py"],
            "mechanism auditor differs from the frozen pilot implementation")
    require(len(records) == frozen["planned_records"], "mechanism census requires every assigned raw record")
    cached = None
    if path.is_file():
        cached = inputs.read(path)
        for field, name in (("freeze_sha256", "freeze.json"), ("summary_sha256", "summary.json"),
                            ("audit_sha256", "audit.json")):
            require(cached.get(field) == inputs.hash(directory / name), "mechanism audit input binding changed")
        for field in ("records_sha256", "journals_sha256"):
            require(cached.get(field) == audit[field], "mechanism audit raw receipt binding changed")
    # A cache with a truncated event list and recomputed counters must not turn
    # used relations into a false zero census. Regenerate every proof offline.
    result = audit_records(records)
    if cached is not None:
        require(canonical(mechanism_semantics({key: cached.get(key) for key in result}))
                == canonical(mechanism_semantics(result)),
                "cached mechanism census differs from complete independent regeneration")
    require(result.get("consistent") is True and result.get("model_calls_made") == 0
            and result.get("records") == frozen["planned_records"],
            "complete model-free mechanism census is required")
    events = result["events"]
    require(result["qualifying_event_count"] == sum(event.get("qualifying_event") is True for event in events)
            and result["structural_event_count"] == sum(event.get("structural_mechanism_event") is True for event in events),
            "mechanism census counts do not match all recorded events")
    publication.no_test_double(result)
    keys = set()
    for event in events:
        ordinal = event["record_ordinal"]
        require(type(ordinal) is int and 0 <= ordinal < len(records), "mechanism event ordinal is unassigned")
        record = records[ordinal]
        require(all(event[key] == record[key] for key in ("seed", "condition", "arm", "phase", "index")),
                "mechanism event belongs to a different source episode")
        key = (ordinal, event["entry_key"])
        require(key not in keys, "duplicate relation event in mechanism census")
        keys.add(key)
    return [{**mechanism_semantics(event), "source_study": str(directory)} for event in events]


def mechanism_semantics(value):
    """Exclude new offline wall-clock timings, preserving every proof and event."""
    if isinstance(value, dict):
        return {key: mechanism_semantics(child) for key, child in value.items() if key != "elapsed_seconds"}
    if isinstance(value, list):
        return [mechanism_semantics(child) for child in value]
    return value


def lifecycle_funnel(records, events):
    """Deduplicate persistent registry events and count observed eligibility/use."""
    acquisitions, corroborations, eligible, retrieved, executed = set(), set(), set(), set(), set()
    registry_events, admission_events, evictions, eligible_pairs, retrieved_pairs, executed_uses = {}, set(), set(), set(), set(), set()
    admission_statuses, correct_direct_sources = Counter(), set()
    final_eligible = set()
    for record in records:
        trace = record["trace"]
        episode = (record["phase"], record["index"])
        actions = trace.get("actions", [])
        if record["phase"] == "ordinary":
            admission = trace.get("admission", {})
            admission_statuses[admission.get("status", "not_applicable")] += 1
            answer_index = trace.get("answer_action_index")
            if (trace["reward"] == 1 and type(answer_index) is int and 0 <= answer_index < len(actions)
                    and actions[answer_index].get("action") == "QUERY"):
                correct_direct_sources.add(episode)
            for event in trace.get("memory", {}).get("registry", {}).get("events", []):
                key = (event["event"], event["entry"], event["episode_id"], event["episode_index"])
                require(key not in registry_events or registry_events[key] == event,
                        "conflicting duplicate lifecycle event identity")
                registry_events[key] = event
            if admission.get("status") in {"provisional", "corroborated"}:
                kind = "provisional_admission" if admission["status"] == "provisional" else "corroborated"
                admission_events.add((kind, admission["entry"], trace["episode_nonce"], trace["episode_index"]))
            for event in trace.get("memory", {}).get("events", []):
                if event.get("event") == "entry_evicted":
                    evictions.add(event["entry"])
        compatibility = trace.get("compatibility", {})
        scope = {key: compatibility.get(key) for key in ("schema_sha256", "catalog_sha256")}
        entries = record.get("before_snapshot", {}).get("registry", {}).get("entries", [])
        episode_index = trace.get("episode_index", -1)
        for entry in entries:
            corroboration = entry.get("corroboration")
            if (compatibility.get("status") == "observed" and entry["scope"] == scope
                    and entry["source"]["episode_index"] < episode_index and corroboration is not None
                    and corroboration["episode_index"] < episode_index):
                eligible.add(entry["key"])
                eligible_pairs.add((*episode, entry["key"]))
                if episode == ("final", 0):
                    final_eligible.add(entry["key"])
        selected = {entry["view"]["key"]: entry["key"] for entry in trace.get("selected_entries", [])}
        retrieved.update(selected.values())
        retrieved_pairs.update((*episode, entry_key) for entry_key in selected.values())
        for action_index, action in enumerate(actions):
            for view_key in action.get("compiled", {}).get("used_views", []):
                require(view_key in selected, "executed relation was not retrieved in the source episode")
                entry_key = selected[view_key]
                executed.add(entry_key)
                executed_uses.add((*episode, action_index, entry_key))
    registered = {key for key in registry_events if key[0] in {"provisional_admission", "corroborated"}}
    require(registered == admission_events, "registry lifecycle events differ from ordinary admission receipts")
    acquisitions.update(key[1] for key in registered if key[0] == "provisional_admission")
    corroborations.update(key[1] for key in registered if key[0] == "corroborated")
    qualifying = {event["entry_key"] for event in events if event["qualifying_event"]}
    require(corroborations <= acquisitions and eligible <= corroborations and retrieved <= eligible
            and executed <= retrieved and qualifying <= executed, "lifecycle funnel has an unobserved predecessor")
    return {"ordinary_episodes": sum(record["phase"] == "ordinary" for record in records),
            "correct_direct_source_episodes": len(correct_direct_sources),
            "own_source_admissions": len(acquisitions), "later_corroborations": len(corroborations),
            "ever_eligible_relations": len(eligible), "eligible_relation_episode_pairs": len(eligible_pairs),
            "eligible_relations_at_final_start": len(final_eligible),
            "retrieved_relations": len(retrieved), "retrieved_relation_episode_pairs": len(retrieved_pairs),
            "executed_relations": len(executed), "executed_query_relation_uses": len(executed_uses),
            "qualifying_chains": len(qualifying), "evicted_relations": len(evictions),
            "ordinary_admission_statuses": dict(sorted(admission_statuses.items())),
            "lifecycle_events": [deepcopy(registry_events[key]) for key in sorted(registered)],
            "execution_scope": "compiled SQL relation-use attempts; qualifying events additionally require correctness and offline interventions"}


def descriptive(records, events, expected_seeds):
    """Summarize an already verified complete ledger without changing any learner."""
    validate_seeds(expected_seeds)
    require(len(records) == RECORDS_PER_STREAM * 32, "no partial pilot effect estimates")
    positions = {(record["seed"], record["arm"], record["phase"], record["index"]): record for record in records}
    expected = {(seed, arm, phase, index) for seed in expected_seeds for arm in ARMS
                for phase, count in PHASES.items() for index in range(count)}
    require(set(positions) == expected and len(positions) == len(records),
            "pilot ledger has duplicate, missing, or unassigned observations")
    require(all(event.get("seed") in expected_seeds and event.get("arm") in ARMS
                and event.get("condition") == "reuse"
                and type(event.get("qualifying_event")) is bool
                and type(event.get("structural_mechanism_event")) is bool for event in events),
            "mechanism census contains an unassigned or invalid event")
    stream_metrics, pairs = [], []
    for seed in expected_seeds:
        for arm in ARMS:
            selected = [positions[(seed, arm, phase, index)] for phase, count in PHASES.items()
                        for index in range(count)]
            for record in selected:
                require(record["condition"] == "reuse" and record["trace"]["status"] in {"completed", "no_valid_answer"}
                        and type(record["trace"]["reward"]) in (int, float) and record["trace"]["reward"] in (0, 1),
                        "incomplete or invalid binary pilot outcome")
            cost = usage([call for record in selected for call in record["trace"]["model_calls"]])
            publication.known_cost(cost)
            old = Counter()
            for index in range(64):
                before, after = (positions[(seed, arm, phase, index)] for phase in ("old_before", "old_after"))
                bt, at = before["trace"], after["trace"]
                for key in ("data_sha256", "data_seed", "definition", "generator", "split", "seed", "condition"):
                    require(bt["evaluator"][key] == at["evaluator"][key], "old-panel pair is not the same frozen problem")
                require(bt["question"] == at["question"] and bt["schema"] == at["schema"],
                        "old-panel public task changed between paired observations")
                require(before.get("sampling_seed") == after.get("sampling_seed")
                        == campaign.sampling_seed(seed, "old_before", index),
                        "old-panel pair sampling seed differs from its frozen paired assignment")
                correct_before, correct_after = (int(trace["reward"]) for trace in (bt, at))
                state = {(0, 0): "both_wrong", (0, 1): "wrong_to_correct",
                         (1, 0): "correct_to_wrong", (1, 1): "both_correct"}[(correct_before, correct_after)]
                old[state] += 1
                pairs.append({"seed": seed, "arm": arm, "index": index,
                              "data_sha256": bt["evaluator"]["data_sha256"],
                              "sampling_seed": before["sampling_seed"],
                              "before_correct": correct_before, "after_correct": correct_after,
                              "after_minus_before": correct_after - correct_before, "pair_state": state})
            counts = {key: old[key] for key in ("both_wrong", "wrong_to_correct", "correct_to_wrong", "both_correct")}
            before_correct = old["correct_to_wrong"] + old["both_correct"]
            after_correct = old["wrong_to_correct"] + old["both_correct"]
            future = []
            for operation in OPERATIONS:
                items = [positions[(seed, arm, "final", index)] for index in range(32)
                         if positions[(seed, arm, "final", index)]["trace"]["evaluator"]["definition"]["operation"] == operation]
                require(len(items) == 8, "future outer operation does not have its assigned eight problems")
                correct = sum(item["trace"]["reward"] == 1 for item in items)
                future.append({"operation": operation, "n": 8, "correct": correct, "accuracy": correct / 8})
            relevant_events = [event for event in events if event["seed"] == seed and event["arm"] == arm]
            qualifying = [event for event in relevant_events if event["qualifying_event"]]
            stream_metrics.append({"seed": seed, "arm": arm, "records": 184,
                "full_cost": cost,
                "lifecycle_funnel": lifecycle_funnel(selected, relevant_events),
                "future": {"n": 32, "correct": sum(row["correct"] for row in future),
                           "accuracy": sum(row["correct"] for row in future) / 32, "by_outer_operation": future},
                "retention": {"paired_n": 64, "before_correct": before_correct, "after_correct": after_correct,
                    "before_accuracy": before_correct / 64, "after_accuracy": after_correct / 64,
                    "after_minus_before": (after_correct - before_correct) / 64,
                    "discordant_pairs": old["wrong_to_correct"] + old["correct_to_wrong"], **counts},
                "mechanism": {"recorded_events": len(relevant_events), "qualifying_events": len(qualifying),
                    "structural_events": sum(event["structural_mechanism_event"] for event in relevant_events),
                    "qualifying_episodes": len({(event["phase"], event["index"]) for event in qualifying}),
                    "qualifying_relations": len({event["entry_key"] for event in qualifying})}})
    by_arm = {}
    for arm in ARMS:
        rows = [row for row in stream_metrics if row["arm"] == arm]
        future_rows = [row["future"] for row in rows]
        retention_rows = [row["retention"] for row in rows]
        by_operation = {}
        for operation in OPERATIONS:
            values = [next(item for item in row["by_outer_operation"] if item["operation"] == operation)
                      for row in future_rows]
            correct = sum(item["correct"] for item in values)
            by_operation[operation] = {"n": 256, "correct": correct, "errors": 256 - correct,
                "accuracy": correct / 256, "observed_remaining_error_rate": 1 - correct / 256,
                "perfect_streams": sum(item["correct"] == 8 for item in values),
                "stream_accuracy_distribution": distribution([item["accuracy"] for item in values])}
        correct = sum(row["correct"] for row in future_rows)
        retention_counts = {key: sum(row[key] for row in retention_rows) for key in
            ("both_wrong", "wrong_to_correct", "correct_to_wrong", "both_correct", "discordant_pairs")}
        by_arm[arm] = {
            "streams": 32, "full_cost": total_cost(row["full_cost"] for row in rows),
            "lifecycle_funnel": {key: sum(row["lifecycle_funnel"][key] for row in rows) for key in (
                "correct_direct_source_episodes", "own_source_admissions", "later_corroborations",
                "ever_eligible_relations", "eligible_relation_episode_pairs", "eligible_relations_at_final_start",
                "retrieved_relations", "retrieved_relation_episode_pairs", "executed_relations",
                "executed_query_relation_uses", "qualifying_chains", "evicted_relations")},
            "future": {"n": 1024, "correct": correct, "errors": 1024 - correct, "accuracy": correct / 1024,
                       "observed_remaining_error_rate": 1 - correct / 1024,
                       "perfect_streams": sum(row["correct"] == 32 for row in future_rows),
                       "stream_accuracy_distribution": distribution([row["accuracy"] for row in future_rows]),
                       "by_outer_operation": by_operation},
            "retention": {"paired_n": 2048, **retention_counts,
                "contrast_distribution": distribution([row["after_minus_before"] for row in retention_rows]),
                "before_accuracy_distribution": distribution([row["before_accuracy"] for row in retention_rows]),
                "after_accuracy_distribution": distribution([row["after_accuracy"] for row in retention_rows]),
                "variance_unit": "one after-minus-before accuracy contrast per independent stream; ddof=1",
                "contrast_units": "accuracy proportion; 0.01 is one percentage point",
                "discordance_unit": "paired binary outcomes on the same old problem, clustered within streams"},
            "mechanism": {"qualifying_events": sum(row["mechanism"]["qualifying_events"] for row in rows),
                          "streams_with_qualifying_events": sum(row["mechanism"]["qualifying_events"] > 0 for row in rows),
                          "qualifying_event_count_distribution": distribution([row["mechanism"]["qualifying_events"] for row in rows])},
        }
    return {"stream_metrics": stream_metrics, "retention_pairs": pairs, "by_arm": by_arm,
            "physical_cost": total_cost(row["full_cost"] for row in stream_metrics)}


def build_report(studies, expected_seeds, *, manifest_path=None):
    studies = [Path(path).resolve() for path in studies]
    inputs = publication.Inputs()
    manifest_hash = inputs.hash(manifest_path) if manifest_path is not None else None
    reporting_sources = {name: inputs.hash(ROOT / name) for name in (
        "tools/campaign_pilot_report.py", "tools/publish_campaign.py", "tools/campaign.py",
        "tools/audit_campaign_mechanism.py", "src/witness_cl/campaign_io.py")}
    readiness_rows, frozen_blocks = readiness(studies, expected_seeds, inputs)
    report = {"schema_version": 1, "kind": KIND, "status": "awaiting_complete_audits",
              "complete": False, "manifest_sha256": manifest_hash, "expected_seeds": expected_seeds,
              "streams": 32, "planned_records": 17664, "studies": readiness_rows,
              "confirmatory_result": False, "automatic_confirmation_authorized": False,
              "model_calls_made": 0,
              "reporting_source_sha256": reporting_sources,
              "scope": "Descriptive development pilot only. No hypothesis test, power adjustment, or automatic confirmation.",
              "partial_effect_estimates": False}
    if manifest_path is not None:
        report["prospective_manifest"] = inputs.read(manifest_path)
    if len(frozen_blocks) != 2 or not all(row["complete_audited"] for row in readiness_rows):
        report["missing_frozen_seeds"] = [seed for seed in expected_seeds
                                          if not any(seed in frozen["seeds"] for _, frozen in frozen_blocks)]
        return report
    records, events = [], []
    for directory, frozen in frozen_blocks:
        summary, audit = (inputs.read(directory / name) for name in ("summary.json", "audit.json"))
        publication.verified_custom(inputs, directory, frozen, summary, audit)
        block = campaign.load_records(directory)
        records.extend(block)
        events.extend(verified_mechanism(directory, frozen, audit, block, inputs))
    result = descriptive(records, events, expected_seeds)
    report.update(status="complete_descriptive_pilot", complete=True, **result,
                  mechanism_census={"events": events,
                      "qualifying_events": sum(event["qualifying_event"] for event in events),
                      "structural_events": sum(event["structural_mechanism_event"] for event in events),
                      "all_events_included": True, "zero_count_stream_arm_rows_included": True,
                      "independently_regenerated_from_all_records": True,
                      "offline_wall_clock_timings_omitted": True,
                      "event_unit": "one successfully used relation in one episode; multiple relations can share an episode",
                      "agent_relation_deletion": "not performed; offline fixed-program interventions are not agent reruns"},
                  identity=identity(frozen_blocks[0][1]),
                  input_inventory={"files": inputs.files, "trees": inputs.trees})
    return report


def render_markdown(report):
    lines = ["# 32-stream descriptive pilot", "", f"Status: **{report['status']}**.", "", report["scope"], ""]
    if not report["complete"]:
        lines += ["No partial mechanism, retention variance, future accuracy, or token-effect estimates are reported.", "",
                  "| Study | Recorded episode files | Planned records | Complete audited |", "|---|---:|---:|---|"]
        for row in report["studies"]:
            lines.append(f"| {row['study']} | {row['recorded_episode_files']} | {row.get('planned_records', 'not frozen')} | {row['complete_audited']} |")
        return "\n".join(lines) + "\n"
    lines += ["All 32 independent streams are complete: 17,664 episodes, with 64 paired old problems and 32 future problems per arm per stream.", "",
              "| Arm | Qualifying events | Streams with events | Future correct / 1024 | Perfect streams | Mean old change | Old contrast variance | Wrong→correct | Correct→wrong | Full tokens |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for arm in ARMS:
        row = report["by_arm"][arm]
        mechanism, future, retention = (row[key] for key in ("mechanism", "future", "retention"))
        contrast = retention["contrast_distribution"]
        lines.append(f"| {arm} | {mechanism['qualifying_events']} | {mechanism['streams_with_qualifying_events']} | {future['correct']} | {future['perfect_streams']} | {contrast['mean']:.6f} | {contrast['sample_variance']:.8f} | {retention['wrong_to_correct']} | {retention['correct_to_wrong']} | {row['full_cost']['total_tokens']} |")
    lines += ["", "Old change is after minus before, in accuracy proportions. Variance uses 32 stream contrasts with the sample denominator 31; individual old problems are not independent stream replicates.", "",
              "| Arm | Own-source admissions | Later corroborations | Ever eligible relations | Retrieved relations | Executed relations | Qualifying chains |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for arm in ARMS:
        row = report["by_arm"][arm]["lifecycle_funnel"]
        lines.append(f"| {arm} | {row['own_source_admissions']} | {row['later_corroborations']} | {row['ever_eligible_relations']} | {row['retrieved_relations']} | {row['executed_relations']} | {row['qualifying_chains']} |")
    lines += ["", "The lifecycle funnel deduplicates persistent event identities. Eligibility requires later episode order and the current observed compatibility scope; execution counts compiled SQL relation-use attempts. Per-stream rows preserve zero counts and every ordinary admission status.", "",
              "| Arm | Future outer operation | Correct / 256 | Accuracy | Remaining observed error rate | Perfect streams |",
              "|---|---|---:|---:|---:|---:|"]
    for arm in ARMS:
        for operation, row in report["by_arm"][arm]["future"]["by_outer_operation"].items():
            lines.append(f"| {arm} | {operation} | {row['correct']} | {row['accuracy']:.6f} | {row['observed_remaining_error_rate']:.6f} | {row['perfect_streams']} |")
    lines += ["", "The full mechanism census includes zero-count stream/arm rows. Fixed-program interventions in that census do not establish agent deletion-rerun effects.", "",
              "Artifacts: `mechanism-census.json`, `stream-metrics.json`, `retention-pairs.json`, and `input-inventory.json`. Costs include every acquisition, reflection, check, and evaluation call. No confirmatory conclusion or automatic follow-on run is authorized."]
    return "\n".join(lines) + "\n"


def write_report(out, report):
    out = Path(out)
    if (out / "report.json").exists():
        previous = read(out / "report.json")
        require(previous.get("manifest_sha256") == report.get("manifest_sha256")
                and previous.get("expected_seeds") == report.get("expected_seeds"),
                "report output belongs to a different prospective pilot")
        require(not previous.get("complete") or report.get("complete"),
                "completed pilot cannot be replaced with an incomplete report")
    result = deepcopy(report)
    artifacts = {}
    for field, filename in (("mechanism_census", "mechanism-census.json"),
                            ("stream_metrics", "stream-metrics.json"),
                            ("retention_pairs", "retention-pairs.json"),
                            ("input_inventory", "input-inventory.json")):
        if field in result:
            save(out / filename, result.pop(field))
            artifacts[field] = {"path": filename, "sha256": sha(out / filename)}
    result["artifacts"] = artifacts
    save(out / "report.json", result)
    (out / "REPORT.md").write_text(render_markdown(report))
    save(out / "report.sha256.json", {"sha256": sha(out / "report.json")})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = read(args.manifest)
    require(manifest.get("schema_version") == 1 and manifest.get("kind") == KIND,
            "frozen descriptive pilot manifest required")
    expected = validate_seeds(manifest["expected_seeds"])
    rows = manifest["studies"]
    require([len(row["seeds"]) for row in rows] == [4, 28]
            and [seed for row in rows for seed in row["seeds"]] == expected,
            "manifest must bind the original 4 and new 28 seeds in order")
    studies = [Path(row["path"]).resolve() for row in rows]
    for path, row in zip(studies, rows, strict=True):
        if (path / "freeze.json").exists():
            require(read(path / "freeze.json")["seeds"] == row["seeds"], "manifest/study seed assignment differs")
    report = build_report(studies, expected, manifest_path=args.manifest)
    written = write_report(args.out, report)
    print(canonical({"status": written["status"], "complete": written["complete"],
                     "report": str(args.out / "report.json"), "model_calls_made": 0}))
    if not written["complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
