#!/usr/bin/env python3
"""Publish complete, audit-bound campaign observations; never invoke a model.

The status files retain every discovered study, including failed gates and
incomplete or invalid inputs. Partial outcome estimates never enter the paper.
Repeated publication of unchanged inputs is byte-for-byte deterministic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from witness_cl.campaign_io import canonical, save, usage

ENDPOINTS = ("accuracy_full_history", "accuracy_ace", "tokens_full_history",
             "tokens_ace", "retention")
LABELS = ("Future accuracy: delayed $-$ history", "Future accuracy: delayed $-$ ACE",
          "Total token ratio: delayed / history", "Total token ratio: delayed / ACE",
          "Old accuracy: after $-$ before")
MAX_JSON_BYTES = 256 * 1024 * 1024
PRUNED = {"sources", "runtime", ".git", "calls", "episodes", "runs", "publication"}
FAST_PROTOCOL = "descriptive_fast_240_v1"


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def label(path):
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def study_name(path):
    path = Path(path).resolve()
    campaign_root = (ROOT / "artifacts/campaign").resolve()
    return " / ".join(path.relative_to(campaign_root).parts) if path.is_relative_to(campaign_root) else path.name


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def no_test_double(value):
    if isinstance(value, dict):
        for key, child in value.items():
            require(not (key in {"test_double", "contains_test_double_calls"} and child is True),
                    "scripted test-double observations cannot be published as measurements")
            if key == "test_double_calls":
                require(child in (0, False, None), "test-double call count is nonzero")
            no_test_double(child)
    elif isinstance(value, list):
        for child in value:
            no_test_double(child)


class Inputs:
    """Small-file hashes plus compact, complete raw-record inventory digests."""

    def __init__(self):
        self.files = {}
        self.trees = {}

    def read(self, path):
        path = Path(path)
        require(path.stat().st_size <= MAX_JSON_BYTES, "JSON input exceeds publication size bound")
        raw = path.read_bytes()
        self.files[label(path)] = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(
            ValueError("nonfinite JSON number: " + x)))
        return value

    def hash(self, path):
        value = file_sha(path)
        self.files[label(path)] = value
        return value

    def tree(self, directory):
        directory = Path(directory)
        require(directory.is_dir(), "raw receipt directory is missing: " + directory.name)
        hashes = {}
        for path in sorted(directory.rglob("*.json")):
            require(not path.is_symlink(), "raw receipt symlinks are not accepted")
            require(path.stat().st_size <= MAX_JSON_BYTES, "raw JSON exceeds size bound")
            raw = path.read_bytes()
            no_test_double(json.loads(raw))
            hashes[str(path.relative_to(directory))] = hashlib.sha256(raw).hexdigest()
        value = digest(hashes)
        self.trees[label(directory)] = {"sha256": value, "json_files": len(hashes)}
        return value

    def sources(self, directory, frozen):
        inventory = frozen.get("source_sha256", frozen.get("sources"))
        require(isinstance(inventory, dict) and inventory, "frozen source inventory is missing")
        for name, expected in sorted(inventory.items()):
            path = Path(directory) / "sources" / name
            require(path.resolve().is_relative_to((Path(directory) / "sources").resolve()),
                    "frozen source path escapes source snapshot")
            require(self.hash(path) == expected, "frozen source snapshot changed: " + name)


def known_cost(cost, *, allow_zero=False):
    require(isinstance(cost, dict), "measured cost ledger is missing")
    for name in ("unknown_usage_calls", "potential_generation_calls", "uncertain_invocations"):
        require(cost.get(name, 0) == 0, "unknown or uncertain model usage")
    require(type(cost.get("calls")) is int and cost["calls"] >= (0 if allow_zero else 1),
            "completed experiment has no measured model calls")
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        require(type(cost.get(name)) is int and cost[name] >= 0, "invalid measured token count")
    require(cost["prompt_tokens"] + cost["completion_tokens"] == cost["total_tokens"],
            "token ledger does not reconcile")


def bound(inputs, directory, receipt, bindings):
    for field, name in bindings.items():
        require(receipt.get(field) == inputs.hash(Path(directory) / name),
                "receipt is not bound to current " + name)


def saved_custom_progress(inputs, directory, frozen, *, assay=False):
    """Count committed schedule-prefix records without computing outcomes."""
    directory = Path(directory)
    schedule = inputs.read(directory / "schedule.json")
    require(isinstance(schedule, list) and type(frozen.get("planned_records")) is int
            and len(schedule) == frozen["planned_records"]
            and digest(schedule) == frozen.get("schedule_sha256"), "frozen schedule changed")
    require(all(isinstance(item, dict) and isinstance(item.get("key"), str)
                and item["key"] not in {"", ".", ".."}
                and Path(item["key"]).name == item["key"] for item in schedule),
            "invalid frozen schedule identity")
    names = [item["key"] + ".json" for item in schedule]
    require(len(set(names)) == len(names), "duplicated frozen schedule identity")
    episodes = directory / "episodes"
    require(not episodes.is_symlink() and (not episodes.exists() or episodes.is_dir()),
            "raw episode directory is invalid")
    paths = {str(path.relative_to(episodes)): path for path in episodes.rglob("*.json")}
    sidecars = {name for name in paths if assay and name.endswith(".sha256.json")}
    saved = set(paths) - sidecars
    require(saved <= set(names), "unplanned raw episode file")
    require(saved == set(names[:len(saved)]), "raw episodes are not a contiguous frozen schedule prefix")
    require(sidecars <= {name[:-5] + ".sha256.json" for name in saved},
            "unplanned episode checksum file")
    freeze_hash = inputs.hash(directory / "freeze.json")
    completed = 0
    for item in schedule[:len(saved)]:
        path = paths[item["key"] + ".json"]
        require(not path.is_symlink(), "raw receipt symlinks are not accepted")
        record = inputs.read(path)
        require(isinstance(record, dict), "raw episode is not a record object")
        require(all(record.get(key) == value for key, value in item.items()),
                "raw episode does not match its scheduled assignment")
        require(record.get("freeze_sha256") == freeze_hash, "raw episode belongs to another freeze")
        trace = record["trace"]
        require(isinstance(trace, dict), "raw episode trace is not an object")
        expected_arm = "sql_archive" if item["arm"] == "sql_archive_extra_evidence" else item["arm"]
        require(trace.get("phase") == item["phase"] and trace.get("arm") == expected_arm,
                "raw episode trace identity differs from its assignment")
        require(trace.get("status") in {"completed", "no_valid_answer", "resource_stop", "runtime_failure"},
                "raw episode has no terminal status")
        completed += trace["status"] in {"completed", "no_valid_answer"}
        checksum = item["key"] + ".sha256.json"
        if checksum in sidecars:
            require(not paths[checksum].is_symlink(), "raw receipt symlinks are not accepted")
            require(inputs.read(paths[checksum]) == {"record_sha256": digest(record)},
                    "episode checksum differs from saved record")
    return {"saved_records": len(saved), "completed_records": completed,
            "stopped_attempt_records": len(saved) - completed, "planned_records": len(schedule),
            "progress_source": "contiguous_frozen_schedule_prefix"}


def verified_custom(inputs, directory, frozen, summary, audit, *, assay=False):
    require(frozen.get("contains_test_double_calls") is False,
            "explicit real-model source declaration is required")
    require(summary.get("complete") is True and audit.get("complete") is True
            and audit.get("consistent") is True, "complete consistent audit required")
    require(audit.get("model_calls_made" if assay else "network_calls") == 0,
            "audit must be model-free replay")
    bound(inputs, directory, audit,
          {"freeze_sha256": "freeze.json", "summary_sha256": "summary.json"})
    inputs.sources(directory, frozen)
    for field, name in (("records_sha256", "episodes"), ("journals_sha256", "calls")):
        require(audit.get(field) == inputs.tree(Path(directory) / name),
                "audit raw-receipt inventory changed: " + name)
    require(audit.get("records_replayed") == frozen.get("planned_records"),
            "audit did not replay every prespecified record")
    schedule = inputs.read(Path(directory) / "schedule.json")
    require(digest(schedule) == frozen.get("schedule_sha256")
            and len(schedule) == frozen["planned_records"], "frozen schedule changed")
    require(isinstance(frozen.get("seeds"), list) and frozen["seeds"]
            and len(frozen["seeds"]) == len(set(frozen["seeds"]))
            and all(type(seed) is int and 0 <= seed < 2**63 for seed in frozen["seeds"]),
            "unique independent stream identities required")
    from tools.campaign import planned_records, summarize
    if assay:
        from tools.campaign_assay import planned_records as assay_plan
        expected_schedule = assay_plan(frozen)
        require(frozen.get("arms") == ["sql_archive_extra_evidence", "view_text", "immediate", "delayed"]
                and frozen.get("checkpoints") == [8, 16, 24]
                and frozen.get("probes_per_checkpoint") == 8, "assay protocol denominator changed")
    elif frozen.get("experiment") == FAST_PROTOCOL or frozen.get("kind") == FAST_PROTOCOL:
        from tools.campaign_fast import planned_records as fast_plan, summarize as fast_summary
        expected_schedule = fast_plan(frozen)
        summarize = fast_summary
    else:
        require(type(frozen.get("old_replicates")) is int and frozen["old_replicates"] >= 1,
                "frozen old-panel count is missing")
        expected_schedule = planned_records(frozen)
        if frozen["kind"] == "confirmation":
            require(len(frozen["seeds"]) >= 48 and frozen["old_replicates"] == 8
                    and frozen["planned_records"] == 552 * len(frozen["seeds"]),
                    "confirmation requires at least48 complete552-record independent streams")
    require(schedule == expected_schedule, "declared schedule differs from the actual frozen task protocol")
    expected_files = {item["key"] + ".json" for item in schedule}
    episode_files = {p.name for p in (Path(directory) / "episodes").glob("*.json")
                     if not p.name.endswith(".sha256.json")}
    require(episode_files == expected_files, "scheduled raw episode count or identity differs")
    require({p.name for p in (Path(directory) / "calls").iterdir() if p.is_dir()}
            == {item["key"] for item in schedule}, "scheduled model-call directories differ")
    compact = []
    freeze_hash = inputs.hash(Path(directory) / "freeze.json")
    for item in schedule:
        record = inputs.read(Path(directory) / "episodes" / (item["key"] + ".json"))
        require(all(record.get(key) == value for key, value in item.items()),
                "raw episode does not match its scheduled assignment")
        require(record.get("freeze_sha256") == freeze_hash,
                "raw episode belongs to another freeze")
        trace = record["trace"]
        expected_arm = "sql_archive" if item["arm"] == "sql_archive_extra_evidence" else item["arm"]
        require(trace.get("phase") == item["phase"] and trace.get("arm") == expected_arm
                and trace.get("status") in {"completed", "no_valid_answer"}, "raw episode is incomplete or misassigned")
        require(type(trace.get("reward")) in (int, float) and trace["reward"] in (0, 1),
                "raw outcome is not an exact binary reward")
        measured = usage(trace["model_calls"])
        known_cost(measured)
        raw_calls = []
        paths = sorted((Path(directory) / "calls" / item["key"]).glob("*.json"))
        require([p.stem for p in paths] == [f"{i:03d}" for i in range(len(paths))],
                "episode call journal has gaps")
        for path in paths:
            receipt = inputs.read(path)
            require(receipt.get("state") == "recorded" and len(receipt.get("calls", [])) == 1,
                    "raw model invocation is pending or ambiguous")
            raw_calls.extend(receipt["calls"])
        require(raw_calls == trace["model_calls"], "raw journal differs from episode model calls")
        small = {**item, "trace": {"reward": trace["reward"], "status": trace["status"], "model_calls": [
            {"generation_attempted": c["generation_attempted"], "usage": c.get("usage")}
            for c in trace["model_calls"]]}}
        if assay:
            small["trace"].update(select_attempts=trace["select_attempts"],
                                  compiled=sum("compiled" in action for action in trace["actions"]))
            small["shared_prefix_ledger"] = record["shared_prefix_ledger"]
        compact.append(small)
    cost = summary["physical_cost" if assay else "cost"]
    known_cost(cost)
    require(audit.get("physical_cost" if assay else "cost") == cost,
            "audit cost differs from complete summary")
    if assay:
        verify_assay_groups(compact, frozen, summary)
        actual_cost = usage([call for record in compact for call in record["trace"]["model_calls"]])
        require(all(cost.get(key) == value for key, value in actual_cost.items()),
                "assay physical cost differs from raw model calls")
    else:
        recalculated = summarize(compact, frozen)
        require(all(summary.get(key) == value for key, value in recalculated.items()),
                "summary denominators, outcomes or costs differ from scheduled raw records")
    no_test_double(summary)


def verify_assay_groups(records, frozen, summary):
    require(len(summary["groups"]) == len(frozen["seeds"]) * 3 * 4,
            "assay has missing or extra groups")
    for seed in frozen["seeds"]:
        for checkpoint in (8, 16, 24):
            donor = [r for r in records if r["seed"] == seed and r["role"] == "donor" and r["index"] < checkpoint]
            prefix_cost = usage([c for r in donor for c in r["trace"]["model_calls"]])
            evidence_hashes = set()
            for arm in frozen["arms"]:
                probes = [r for r in records if r["seed"] == seed and r["role"] == "probe"
                          and r["checkpoint"] == checkpoint and r["arm"] == arm]
                groups = [g for g in summary["groups"] if (g["seed"], g["checkpoint"], g["arm"]) == (seed, checkpoint, arm)]
                require(len(donor) == checkpoint and len(probes) == 8 and len(groups) == 1,
                        "assay checkpoint denominator differs")
                group = groups[0]
                actual_cost = usage([c for r in donor + probes for c in r["trace"]["model_calls"]])
                require(group["donor_episodes"] == checkpoint and group["probes"] == 8
                        and group["correct"] == sum(r["trace"]["reward"] for r in probes)
                        and group.get("complete") is True
                        and all(group["logical_cost_including_full_prefix"].get(k) == v for k, v in actual_cost.items()),
                        "assay logical prefix costs or outcomes differ from raw receipts")
                require(group["logical_selects_including_full_prefix"] == sum(r["trace"]["select_attempts"] for r in donor + probes)
                        and group["executed_view_actions"] == sum(r["trace"]["compiled"] for r in probes),
                        "assay query or executable-action denominator differs")
                for probe in probes:
                    ledger = probe["shared_prefix_ledger"]
                    require(len(ledger["records"]) == checkpoint
                            and all(ledger["cost"].get(k) == v for k, v in prefix_cost.items()),
                            "assay fork did not pay its complete donor prefix")
                    evidence_hashes.add(ledger["evidence_sha256"])
                require(group["common_evidence_sha256"] in evidence_hashes, "assay shared evidence hash differs")
            require(len(evidence_hashes) == 1, "assay arms did not receive the same donor evidence")


def confirmation_prerequisites(inputs, directory, frozen):
    """Check the bound prospective denominator without rerunning power simulations."""
    n = len(frozen["seeds"])
    require(n >= 48 and frozen.get("old_replicates") == 8
            and frozen["planned_records"] == 552 * n,
            "confirmation requires at least48 complete552-record independent streams")
    evidence = frozen.get("evidence_sha256", {})
    sizing = frozen.get("prerequisites", {}).get("sizing", {})
    require(sizing.get("streams") == n and len(sizing.get("seeds", [])) == 32
            and len(set(sizing["seeds"])) == 32 and not set(sizing["seeds"]) & set(frozen["seeds"]),
            "confirmation denominator is not bound to32 independent sizing streams")
    values = {}
    for name in ("freeze.json", "summary.json", "audit.json", "power.json"):
        relative = "sizing/" + name
        path = Path(directory) / "evidence" / relative
        expected = inputs.hash(path)
        require(expected == evidence.get(relative) == sizing.get("sha256", {}).get(name),
                "prospective sizing prerequisite changed: " + name)
        values[name] = inputs.read(path)
    source, summary, audit, power = (values[name] for name in ("freeze.json", "summary.json", "audit.json", "power.json"))
    require(source.get("kind") == "sizing" and source.get("seeds") == sizing["seeds"]
            and source.get("old_replicates") == 8 and source.get("conditions") == ["reuse"]
            and set(source.get("arms", [])) == {"full_history", "ace", "delayed"}
            and source.get("planned_records") == 552 * 32,
            "bound sizing panel has the wrong assignment")
    require(summary.get("complete") is True and audit.get("complete") is True
            and audit.get("consistent") is True and audit.get("network_calls") == 0,
            "sizing prerequisite is not completely replay-audited")
    require(audit.get("records_replayed") == 552 * 32
            and source.get("client_config") == frozen.get("client_config")
            and source.get("runtime_config") == frozen.get("runtime_config")
            and source.get("runtime_receipt", {}).get("model_sha256")
                == frozen.get("runtime_receipt", {}).get("model_sha256")
            and frozen.get("runtime_receipt", {}).get("model_sha256"),
            "sizing replay denominator, model bytes or client policy differ from confirmation")
    for field, name in (("freeze_sha256", "freeze.json"), ("summary_sha256", "summary.json")):
        require(audit.get(field) == sizing["sha256"][name], "sizing audit binds different inputs")
    for field, name in (("freeze_sha256", "freeze.json"), ("summary_sha256", "summary.json"), ("audit_sha256", "audit.json")):
        require(power.get(field) == sizing["sha256"][name], "power planning binds different sizing inputs")
    known_cost(summary["cost"])
    require(audit.get("cost") == summary["cost"] and source.get("contains_test_double_calls") is False,
            "sizing costs or real-model declaration differ")
    require(len(summary.get("groups", [])) == 32 * 3, "sizing summary omits assigned stream groups")
    totals = {name: 0 for name in ("calls", "prompt_tokens", "completion_tokens", "total_tokens")}
    for seed in sizing["seeds"]:
        for arm in ("full_history", "ace", "delayed"):
            groups = [g for g in summary["groups"] if (g.get("seed"), g.get("arm"), g.get("condition")) == (seed, arm, "reuse")]
            require(len(groups) == 1 and groups[0].get("records") == 184,
                    "sizing group has wrong episode denominator")
            group = groups[0]
            for phase, count in (("ordinary", 24), ("old_before", 64), ("old_after", 64), ("final", 32)):
                panel = group["phases"][phase]
                require(type(panel.get("n")) is int and panel["n"] == count
                        and type(panel.get("correct")) is int and 0 <= panel["correct"] <= count,
                        "sizing group has wrong panel denominator")
            known_cost(group["cost"])
            require(group["cost"]["calls"] >= 184, "sizing calls omit assigned episodes")
            for name in totals:
                totals[name] += group["cost"][name]
    require(all(summary["cost"].get(key) == value for key, value in totals.items()),
            "sizing total cost differs from complete assigned groups")
    no_test_double(values)
    require(power.get("streams") == n and power.get("pilot_n") == 32
            and power.get("analysis_source_sha256") == frozen["source_sha256"].get("src/witness_cl/campaign_analysis.py"),
            "power report does not prescribe the actual confirmation denominator")
    simulations = power.get("joint_power_simulations", [])
    last = simulations[-1] if simulations else {}
    require(last.get("streams") == n and last.get("trials") == 100000 and last.get("seed") == 271828
            and type(last.get("one_sided_95_mc_lower")) in (int, float)
            and math.isfinite(last["one_sided_95_mc_lower"]) and 0.80 < last["one_sided_95_mc_lower"] <= 1,
            "final prospective joint-power bound is missing or does not pass")


def confirmation(inputs, directory, frozen, summary):
    """Recalculate the recorded analysis without accepting hand-entered estimates."""
    from witness_cl.campaign_analysis import analyze
    require(frozen["kind"] == "confirmation", "only confirmation supplies primary estimates")
    confirmation_prerequisites(inputs, directory, frozen)
    analysis = inputs.read(Path(directory) / "analysis.json")
    bound(inputs, directory, analysis, {"freeze_sha256": "freeze.json", "audit_sha256": "audit.json",
                                      "summary_sha256": "summary.json"})
    name = "src/witness_cl/campaign_analysis.py"
    expected = frozen["source_sha256"].get(name)
    require(expected == analysis.get("analysis_source_sha256"),
            "recorded analysis must match frozen analysis source")
    require(inputs.hash(ROOT / name) == expected,
            "publisher analysis implementation differs from the frozen analysis source")
    require(frozen["conditions"] == ["reuse"]
            and set(frozen["arms"]) == {"full_history", "ace", "delayed"},
            "primary analysis requires the paired reuse study")
    require(len(frozen["seeds"]) == len(set(frozen["seeds"])), "duplicate stream identities")
    rows = []
    panels = {"ordinary": 24, "old_before": 64, "old_after": 64, "final": 32}
    require(len(summary["groups"]) == len(frozen["seeds"]) * 3, "unexpected paired groups")
    for seed in frozen["seeds"]:
        arms = {}
        for arm in frozen["arms"]:
            matches = [g for g in summary["groups"] if g["seed"] == seed
                       and g["arm"] == arm and g["condition"] == "reuse"]
            require(len(matches) == 1, "missing or duplicated paired group")
            group = matches[0]
            require(group["records"] == sum(panels.values()), "incomplete assigned stream")
            for phase, count in panels.items():
                panel = group["phases"][phase]
                require(panel["n"] == count and type(panel["correct"]) is int
                        and 0 <= panel["correct"] <= count, "incomplete or invalid panel")
            known_cost(group["cost"])
            arms[arm] = {"future_accuracy": group["phases"]["final"]["correct"] / 32,
                         "old_before_accuracy": group["phases"]["old_before"]["correct"] / 64,
                         "old_after_accuracy": group["phases"]["old_after"]["correct"] / 64,
                         "total_tokens": group["cost"]["total_tokens"]}
        rows.append({"seed": seed, "complete": True, "arms": arms})
    recomputed = analyze(rows, frozen_n=len(frozen["seeds"]))
    require(all(analysis.get(k) == v for k, v in recomputed.items()),
            "analysis does not equal the prespecified five-endpoint calculation")
    return analysis


def mechanism(inputs, directory, audit):
    path = Path(directory) / "audit-mechanism.json"
    if not path.exists():
        return None
    value = inputs.read(path)
    bound(inputs, directory, value, {"freeze_sha256": "freeze.json", "summary_sha256": "summary.json",
                                   "audit_sha256": "audit.json"})
    require(value.get("consistent") is True and value.get("model_calls_made") == 0,
            "complete model-free mechanism audit required")
    for field in ("records_sha256", "journals_sha256"):
        require(value.get(field) == audit.get(field), "mechanism audit raw inputs changed")
    no_test_double(value)
    events = [e for e in value["events"] if e.get("qualifying_event") is True]
    require(len(events) == value["qualifying_event_count"], "mechanism event count differs")
    return {"qualifying_event_count": len(events), "totals": value["totals"],
            "events": events, "agent_deletion_rerun": "not established by offline intervention",
            "scope": "fixed-program interventions; no model generations in auditor"}


def diagnostic(inputs, directory, frozen, summary):
    from tools.campaign_results import arm_metrics
    from witness_cl.campaign_analysis import diagnose
    path = Path(directory) / "diagnostic-analysis.json"
    if not path.exists():
        return None
    result = inputs.read(path)
    bound(inputs, directory, result, {"freeze_sha256": "freeze.json", "summary_sha256": "summary.json",
                                     "audit_sha256": "audit.json"})
    require(result.get("analysis_source_sha256") ==
            frozen["source_sha256"].get("src/witness_cl/campaign_analysis.py"),
            "diagnostic analysis source differs from freeze")
    rows = [{"seed": seed, "complete": True, "conditions": {
        condition: arm_metrics(summary, seed, condition) for condition in frozen["conditions"]}}
        for seed in frozen["seeds"]]
    calculated = diagnose(rows, conditions=frozen["conditions"])
    require(all(result.get(k) == v for k, v in calculated.items()),
            "diagnostic analysis differs from complete paired-stream calculation")
    inputs.hash(ROOT / "src/witness_cl/campaign_analysis.py")
    return result


def descriptive_groups(summary, *, assay=False):
    """Keep arms/conditions/checkpoints separate; never pool distinct studies."""
    groups = {}
    for row in summary["groups"]:
        key = (row.get("condition", "reuse"), row.get("checkpoint"), row["arm"])
        group = groups.setdefault(key, {"condition": key[0], "checkpoint": key[1], "arm": key[2],
                                       "streams": 0, "correct": 0, "n": 0, "tokens": 0})
        group["streams"] += 1
        panel = {"correct": row["correct"], "n": row["probes"]} if assay else row["phases"]["final"]
        require(type(panel["n"]) is int and 0 <= panel["correct"] <= panel["n"],
                "invalid descriptive outcome count")
        group["correct"] += panel["correct"]
        group["n"] += panel["n"]
        cost = row["logical_cost_including_full_prefix"] if assay else row["cost"]
        known_cost(cost)
        group["tokens"] += cost["total_tokens"]
    return [groups[key] for key in sorted(groups, key=str)]


def verified_native(inputs, directory, frozen, audit):
    require(frozen.get("contains_test_double_calls") is False, "native real-model declaration missing")
    require(audit.get("all_complete_and_passed") is True, "complete native replay required")
    require(audit.get("model_free_replay") is True and audit.get("model_calls_made") == 0,
            "native audit must be a complete model-free replay")
    bound(inputs, directory, audit, {"freeze_sha256": "freeze.json", "report_sha256": "report.json"})
    inputs.sources(directory, frozen)
    jobs = frozen["jobs"]
    from tools.native_campaign import planned_runs
    require(jobs == planned_runs() and frozen["task"].get("runs") == 5
            and frozen["task"].get("questions_per_run") == 40
            and frozen["task"].get("query_budget") == 15
            and frozen["task"].get("schedule") == "default",
            "native result must cover the unchanged five-permutation four-arm default panel")
    require(jobs and len({j["key"] for j in jobs}) == len(jobs), "native jobs missing or duplicated")
    checks = {c["job"]: c for c in audit["checks"]}
    require(len(checks) == len(audit["checks"]) == len(jobs), "native audit has missing or duplicate jobs")
    rows = []
    for job in jobs:
        check = checks[job["key"]]
        require(check.get("status") == "passed" and check.get("model_free_replay") is True,
                "native job requires actual model-free behavioral replay")
        run = Path(directory) / "runs" / job["key"]
        result = inputs.read(run / "result.json")
        result_hash = inputs.hash(run / "result.json")
        require(audit.get("result_sha256", {}).get(job["key"]) == result_hash,
                "native audit is not bound to current run result")
        require(inputs.read(run / "result.sha256.json")["sha256"] == result_hash,
                "native completed result changed")
        require(result.get("freeze_sha256") == inputs.hash(Path(directory) / "freeze.json"),
                "native result belongs to another freeze")
        require(result.get("job") == job, "native result belongs to another job")
        no_test_double(result)
        require(result.get("status") == "completed", "partial native result")
        calls = result["calls"]
        require(digest(calls) == result["calls_sha256"] and usage(calls) == result["usage"],
                "native calls/usage changed")
        known_cost(result["usage"])
        recorded = []
        for path in sorted((run / "calls").glob("*.json")):
            receipt = inputs.read(path)
            require(receipt.get("state") == "recorded", "native pending call")
            recorded.extend(receipt.get("calls", []))
        require(calls == recorded, "native raw journal differs from completed result")
        require([r["instance_id"] for r in result["outcomes"]]
                == frozen["question_orders"][str(job["run_index"])]
                and len(result["outcomes"]) == frozen["task"]["questions_per_run"],
                "native assigned question panel is incomplete")
        rows.append({**job, "reward": result["score"], "accuracy": result["metrics"]["accuracy"],
                     "queries": result["metrics"]["total_queries"], **result["usage"]})
    gains = []
    for index in sorted({row["run_index"] for row in rows}):
        pair = {r["arm"]: r for r in rows if r["run_index"] == index}
        stateful, stateless = pair["witness_stateful"], pair["witness_stateless"]
        gains.append({"run_index": index, "accuracy_gain": stateful["accuracy"] - stateless["accuracy"],
                      "reward_gain": stateful["reward"] - stateless["reward"]})
    return {"runs": rows, "paired_stateful_gains": gains,
            "scope": "descriptive fixed-database permutations, not independent new databases"}


def verified_deletion(inputs, directory, frozen, summary, audit):
    """Publish all frozen eligible agent reruns, including an empty event census."""
    require(frozen.get("contains_test_double_calls") is False, "deletion real-model declaration missing")
    require(summary.get("complete") is True and audit.get("complete") is True
            and audit.get("consistent") is True and audit.get("model_calls_made") == 0,
            "complete model-free deletion replay required")
    bound(inputs, directory, audit, {"freeze_sha256": "freeze.json", "summary_sha256": "summary.json"})
    inputs.sources(directory, frozen)
    cases = inputs.read(Path(directory) / "cases.json")
    selection = inputs.read(Path(directory) / "mechanism-selection.json")
    require(digest(cases) == frozen.get("cases_sha256") and len(cases) == frozen.get("planned_cases")
            and inputs.hash(Path(directory) / "mechanism-selection.json") == frozen.get("selection_receipt_sha256"),
            "frozen deletion census changed")
    eligible = [event for event in selection["events"] if event.get("structural_mechanism_event") is True]
    require(len(eligible) == len(cases) == selection.get("structural_event_count")
            and selection.get("consistent") is True and selection.get("model_calls_made") == 0,
            "deletion excludes eligible frozen mechanism events")
    no_test_double(cases)
    no_test_double(selection)
    require(audit.get("cases_replayed") == len(cases), "not every eligible deletion case was replayed")
    for field, name in (("records_sha256", "episodes"), ("journals_sha256", "calls")):
        path = Path(directory) / name
        # A zero-case diagnostic legitimately never creates receipt directories.
        actual = inputs.tree(path) if path.exists() else digest({})
        require(audit.get(field) == actual, "deletion audit raw inputs changed")
    from tools.campaign_assay import resolve_deletion_source
    source = resolve_deletion_source(directory, frozen)
    require(inputs.hash(source / "freeze.json") == frozen["source_freeze_sha256"]
            and inputs.hash(source / "audit.json") == frozen["source_audit_sha256"],
            "deletion source study changed")
    source_audit = inputs.read(source / "audit.json")
    require(source_audit.get("complete") is True and source_audit.get("consistent") is True
            and source_audit.get("records_sha256") == frozen["source_records_sha256"]
            and source_audit.get("journals_sha256") == frozen["source_journals_sha256"],
            "deletion source acquisition was not completely audited")
    require(inputs.tree(source / "episodes") == frozen["source_records_sha256"]
            and inputs.tree(source / "calls") == frozen["source_journals_sha256"],
            "deletion original records or journals changed")
    source_schedule = inputs.read(source / "schedule.json")
    source_freeze = inputs.read(source / "freeze.json")
    require(digest(source_schedule) == source_freeze["schedule_sha256"], "deletion source schedule changed")
    from tools.campaign import planned_records
    source_adapter = frozen.get("source_schedule", "campaign")
    require(source_adapter in {"campaign", "fast240"}, "unknown deletion source schedule adapter")
    if source_adapter == "fast240":
        from tools.campaign_fast import planned_records
        require(source_freeze.get("experiment") == FAST_PROTOCOL
                and source_freeze.get("planned_records") == 240,
                "fast deletion requires the complete 240-record parent")
        require(inputs.hash(source / "schedule.json") == frozen.get("source_schedule_sha256"),
                "fast deletion parent schedule binding changed")
        require(all(frozen.get(key) == source_freeze.get(key) for key in (
            "last_call_start_utc", "generation_deadline_utc", "report_deadline_utc")),
            "fast deletion cutoffs differ from the parent freeze")
        name = "tools/campaign_fast.py"
        require(source_freeze["source_sha256"].get(name) == inputs.hash(ROOT / name),
                "fast deletion schedule implementation differs from its frozen parent")
        source_summary = inputs.read(source / "summary.json")
        verified_custom(inputs, source, source_freeze, source_summary, source_audit)
        require(summary.get("source_schedule") == source_adapter
                and summary.get("agent_reruns_performed") == len(cases)
                and summary.get("status") == ("complete" if cases else "no_reruns_performed"),
                "fast deletion rerun status differs from the frozen census")
    else:
        require(source_freeze.get("experiment") != FAST_PROTOCOL,
                "fast deletion parent requires the explicit fast240 schedule adapter")
    require(source_schedule == planned_records(source_freeze)
            and len(source_schedule) == source_audit.get("records_replayed") == selection.get("records"),
            "deletion source or selection census omits scheduled records")
    known_cost(source_audit["cost"])
    require(summary["original_acquisition_and_evaluation_cost"] == frozen["original_acquisition_and_evaluation_cost"]
            == source_audit["cost"], "original acquisition cost differs across deletion receipts")
    require(summary.get("case_selection_was_frozen_before_rerun") is True
            and summary.get("feedback_to_original_campaign") is False,
            "deletion observations must not update the source campaign")
    from witness_cl.delayed_memory import DelayedMemory
    records, all_calls = [], []
    for ordinal, (case, event) in enumerate(zip(cases, eligible)):
        require(case["key"] == f"deletion-{ordinal:05d}"
                and case["original_record_ordinal"] == event["record_ordinal"]
                and case["removed_entry_key"] == event["entry_key"]
                and case["removed_view_key"] == event["view_key"], "deletion case differs from full eligible census")
        item = source_schedule[case["original_record_ordinal"]]
        original = inputs.read(source / "episodes" / (item["key"] + ".json"))
        require(digest(original) == case["original_record_sha256"] and original["trace"]["reward"] == 1
                and case.get("original_correct") is True and case.get("learn") is False,
                "deletion baseline or learning boundary differs")
        require(all(case.get(key) == original.get(key) for key in ("seed", "condition", "arm", "phase", "index", "sampling_seed"))
                and case["original_episode_nonce"] == original["trace"]["episode_nonce"]
                and case["episode_index"] == original["trace"]["episode_index"],
                "deletion episode, nonce or paired sampling differs from baseline")
        if source_adapter == "fast240":
            require(isinstance(case.get("original_data_sha256"), str)
                    and case["original_data_sha256"] == original["trace"]["evaluator"]["data_sha256"],
                    "fast deletion database binding differs from its source episode")
        memory = DelayedMemory.from_snapshot(original["before_snapshot"])
        previous = len(memory.registry.entries)
        memory.registry.entries = [entry for entry in memory.registry.entries if entry.key != case["removed_entry_key"]]
        require(len(memory.registry.entries) == previous - 1
                and canonical(memory.snapshot()) == canonical(case["before_snapshot"]),
                "deletion must remove only its relation and preserve original SQL evidence")
        path = Path(directory) / "episodes" / (case["key"] + ".json")
        record = inputs.read(path)
        require(record.get("case_sha256") == digest(case)
                and record.get("freeze_sha256") == inputs.hash(Path(directory) / "freeze.json"),
                "deletion outcome belongs to another case or freeze")
        trace = record["trace"]
        if source_adapter == "fast240":
            require(trace["evaluator"]["data_sha256"] == case["original_data_sha256"],
                    "fast deletion rerun database differs from its source episode")
        require(trace.get("status") in {"completed", "no_valid_answer"}
                and trace.get("learn") is False and trace.get("reward") in (0, 1)
                and trace.get("phase") == case["phase"] and trace.get("arm") == case["arm"]
                and trace.get("episode_index") == case["episode_index"]
                and trace.get("episode_nonce") == case["original_episode_nonce"]
                and canonical(trace["memory"]) == canonical(case["before_snapshot"]),
                "deletion did not complete with immutable memory")
        calls = []
        for path in sorted((Path(directory) / "calls" / case["key"]).glob("*.json")):
            receipt = inputs.read(path)
            require(receipt.get("state") == "recorded" and len(receipt.get("calls", [])) == 1,
                    "deletion has uncertain invocation")
            calls.extend(receipt["calls"])
        require(calls == trace["model_calls"], "deletion journal differs from outcome")
        known_cost(usage(calls))
        all_calls.extend(calls)
        records.append(record)
    actual_names = {p.name for p in (Path(directory) / "episodes").glob("*.json")
                    if not p.name.endswith(".sha256.json")}
    require(actual_names == {case["key"] + ".json" for case in cases}, "extra or missing deletion outcome")
    require({p.name for p in (Path(directory) / "calls").glob("*") if p.is_dir()}
            == {case["key"] for case in cases}, "extra or missing deletion invocation directory")
    actual_cost = usage(all_calls)
    known_cost(summary["physical_diagnostic_cost"], allow_zero=not cases)
    require(all(summary["physical_diagnostic_cost"].get(key) == value for key, value in actual_cost.items()),
            "deletion physical cost differs from raw rerun calls")
    flips = sum(record["trace"]["reward"] == 0 for record in records)
    require(summary.get("planned_cases") == summary.get("recorded_cases") == summary.get("completed_cases") == len(cases)
            and summary.get("answer_flips_to_wrong") == flips
            and summary.get("correct_despite_deletion") == len(cases) - flips,
            "deletion denominators or outcomes differ from the frozen census")
    return {"eligible_cases": len(cases), "answer_flips_to_wrong": flips,
            "correct_despite_deletion": len(cases) - flips,
            "source_schedule": source_adapter, "agent_reruns_performed": len(cases),
            "status": "complete" if cases else "no_reruns_performed",
            "physical_diagnostic_cost": summary["physical_diagnostic_cost"],
            "original_acquisition_and_evaluation_cost": source_audit["cost"],
            "scope": "conditional frozen event census; no independent-stream population claim",
            "rerun_outcomes_measured": bool(cases)}


def inspect_study(directory, inputs):
    directory = Path(directory).resolve()
    result = {"path": label(directory), "name": study_name(directory), "status": "pending",
              "outcomes_publishable": False, "primary_claim": False}
    if not (directory / "freeze.json").exists():
        result["reason"] = "No frozen study is present."
        return result
    try:
        frozen = inputs.read(directory / "freeze.json")
        native = "jobs" in frozen and "task" in frozen
        assay = frozen.get("experiment") == "common_source_matched_evidence_v1"
        deletion = frozen.get("experiment") == "agent_relation_deletion_v1"
        result.update(kind="native" if native else "agent_deletion" if deletion else ("assay_" if assay else "") + frozen["kind"],
                      freeze_sha256=inputs.hash(directory / "freeze.json"),
                      created_utc=frozen.get("created_utc"),
                      planned_records=frozen.get("planned_records", frozen.get("planned_cases")),
                      streams=len(frozen.get("seeds", [])),
                      conditions=frozen.get("conditions", []))
        if frozen.get("kind") == FAST_PROTOCOL:
            result.update(descriptive_only=True, original_32_stream_pilot_completed=False,
                          inference_scope="Two-stream descriptive diagnostic; accuracy superiority, two-point retention "
                                          "noninferiority and original pilot completion are not established.")
        if frozen.get("contains_test_double_calls") is True:
            result.update(status="excluded_test_double", reason="Scripted software tests supply no model results.")
            return result
        if (directory / "manifest.json").exists():
            manifest = inputs.read(directory / "manifest.json")
            result["progress"] = {k: manifest[k] for k in
                                  ("status", "completed_records", "planned_records", "started_utc",
                                   "finished_utc", "cost", "physical_cost", "error_type", "error")
                                  if k in manifest}
        summary_path = directory / ("report.json" if native else "summary.json")
        summary = inputs.read(summary_path) if summary_path.exists() else {}
        complete = summary.get("status") == "completed" if native else summary.get("complete") is True
        if not complete:
            if not native and not deletion:
                progress = saved_custom_progress(inputs, directory, frozen, assay=assay)
                result["progress"] = {**result.get("progress", {}), **progress}
            elif deletion and (summary or (directory / "calls").exists()):
                result["progress"] = {key: summary[key] for key in
                                      ("status", "recorded_cases", "completed_cases") if key in summary}
                result["progress"]["planned_records"] = frozen["planned_cases"]
                if type(summary.get("completed_cases")) is int:
                    result["progress"]["completed_records"] = summary["completed_cases"]
                calls = directory / "calls"
                if calls.exists():
                    from witness_cl.campaign_io import journal_usage
                    inputs.tree(calls)
                    result["physical_cost"] = journal_usage(calls)
                    result["physical_cost_scope"] = "incomplete diagnostic; raw invocation accounting only"
            result.update(status="incomplete", reason="Awaiting the complete frozen schedule; no outcome estimates published.")
            return result
        if not (directory / "audit.json").exists():
            result.update(status="awaiting_audit", reason="Complete results need independent bound replay.")
            return result
        audit = inputs.read(directory / "audit.json")
        if native:
            result["native"] = verified_native(inputs, directory, frozen, audit)
        elif deletion:
            result["deletion"] = verified_deletion(inputs, directory, frozen, summary, audit)
            result["physical_cost"] = summary["physical_diagnostic_cost"]
            result["progress"] = {"completed_records": summary["completed_cases"]}
        else:
            verified_custom(inputs, directory, frozen, summary, audit, assay=assay)
            result["descriptive"] = descriptive_groups(summary, assay=assay)
            result["physical_cost"] = summary["physical_cost" if assay else "cost"]
            if assay:
                result["logical_checkpoint_costs_overlap"] = True
            elif frozen["kind"] == "qualification":
                result["qualification_passed"] = summary["qualified"]
                result["qualification_cells"] = summary["qualification_cells"]
            else:
                try:
                    result["mechanism"] = mechanism(inputs, directory, audit)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    result["mechanism_error"] = str(exc)
            if not assay and frozen["kind"] == "confirmation":
                try:
                    result["analysis"] = confirmation(inputs, directory, frozen, summary)
                    result["primary_claim"] = result["analysis"]["all_five_pass"]
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    result["analysis_error"] = str(exc)
            if not assay and frozen["kind"] == "diagnostic":
                try:
                    result["diagnostic"] = diagnostic(inputs, directory, frozen, summary)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    result["diagnostic_error"] = str(exc)
            if not assay and frozen["kind"] == "sizing" and (directory / "power.json").exists():
                try:
                    power = inputs.read(directory / "power.json")
                    bound(inputs, directory, power, {"freeze_sha256": "freeze.json",
                          "summary_sha256": "summary.json", "audit_sha256": "audit.json"})
                    result["power_planning"] = power
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    result["power_error"] = str(exc)
        result.update(status="complete", outcomes_publishable=True)
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        result.update(status="invalid", outcomes_publishable=False, primary_claim=False, reason=str(exc))
        for key in ("analysis", "descriptive", "mechanism", "native", "physical_cost", "diagnostic", "deletion"):
            result.pop(key, None)
    return result


def discover(root, *, max_studies=128):
    found = []
    root = Path(root)
    if not root.exists():
        return found
    for directory, children, files in os.walk(root):
        children[:] = sorted(c for c in children if c not in PRUNED and not c.startswith("."))
        if "freeze.json" in files:
            found.append(Path(directory))
            children[:] = []
            require(len(found) <= max_studies, "study discovery limit exceeded; provide explicit --study paths")
    return sorted(found)


def latex(value):
    escapes = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
               "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
               "^": r"\textasciicircum{}"}
    return "".join(escapes.get(c, c) for c in str(value))


def number(value, digits=2):
    require(isinstance(value, (int, float)) and math.isfinite(value), "finite displayed number required")
    return f"{value:.{digits}f}"


def render_tex(snapshot):
    lines = ["% Generated by tools/publish_campaign.py; never edit numeric entries by hand.",
             "% Input snapshot SHA256: " + snapshot["input_snapshot_sha256"]]
    confirmations = [s for s in snapshot["studies"] if s.get("analysis")]
    if not confirmations:
        lines += ["This Stage 1 registered-report manuscript has no complete, audit-bound confirmatory analysis.",
                  "Primary outcomes are unmeasured; pending, failed-integrity and scripted inputs",
                  "supply no effect estimate. Completed descriptive results appear separately below."]
    for study in confirmations or [None]:
        lines += [r"\begin{table*}[t]\centering\small",
                  r"\begin{tabular}{p{.32\textwidth}p{.14\textwidth}p{.18\textwidth}p{.18\textwidth}}",
                  r"\toprule Primary comparison & Estimate & One-sided lower bound & Decision\\\midrule"]
        for key, title in zip(ENDPOINTS, LABELS):
            if study is None:
                estimate, lower, decision = r"\pending", r"\pending", "Not evaluated"
            else:
                endpoint = study["analysis"]["endpoints"][key]
                token = key.startswith("tokens_")
                estimate = (number(endpoint["aggregate_token_ratio"], 3) if token
                            else number(100 * endpoint["mean"]) + " pp")
                lower = (number(endpoint["lower"], 1) + " tokens" if token
                         else number(100 * endpoint["lower"]) + " pp")
                decision = "Pass" if endpoint["passed"] else "Does not pass"
            lines.append(f"{title} & {estimate} & {lower} & {decision}" + r"\\")
        caption = ("Proposed complete-stream primary report; final sizing follows the 32-stream pilot." if study is None else
                   latex(study["name"]) + f": {study['analysis']['n']} independent streams. "
                   + ("All five endpoints pass." if study["primary_claim"] else "The five-endpoint conjunction does not pass."))
        lines += [r"\bottomrule\end{tabular}", r"\caption{" + caption
                  + r" Bounds use one-sided $\alpha=.01$. Accuracy bounds are percentage points;"
                  + r" token bounds apply to $0.8C-D$ in tokens, not to the displayed aggregate ratio."
                  + r" Thresholds are zero except $-2$ pp for retention.}"]
        if study is None or study is confirmations[0]:
            lines.append(r"\label{tab:primary}")
        lines.append(r"\end{table*}")
    lines += [r"\subsection{Mechanism observations}"]
    mechanisms = [s for s in snapshot["studies"] if s.get("mechanism")]
    lines += [r"\noindent\begin{minipage}{\columnwidth}\centering\small",
              r"\begin{tabular}{>{\raggedright\arraybackslash}p{.52\columnwidth}>{\raggedright\arraybackslash}p{.38\columnwidth}}",
              r"\toprule Complete study & Qualifying executions\\\midrule"]
    for study in mechanisms:
        lines.append(latex(study["name"]) + " & " + str(study["mechanism"]["qualifying_event_count"]) + r"\\")
    if not mechanisms:
        lines.append(r"Audited model-generated chains & \pending\\")
    lines += [r"\bottomrule\end{tabular}",
              r"\par\smallskip\raggedright\noindent\textbf{Complete mechanism census.} Counts require chronological admission, changed-binding",
              r"corroboration, fresh rows, new outer operation, and wrong outcomes after fixed-program",
              r"empty-relation and computed-measure interventions. These do not establish an agent rerun",
              r"after deleting a registry entry.\end{minipage}\par\smallskip"]
    if not mechanisms:
        lines += ["No complete audited mechanism census is available. Source admission, later corroboration",
                  "and execution are distinct events. Software lifecycle tests supply no model-generated chain."]
    else:
        lines += ["All qualifying events, lineage, intervention outcomes and eligible counts are retained",
                  "in the bound status artifact. A deterministic first-five selection is reported there",
                  "for every completed study; studies with zero events remain visible."]
    lines += [r"\subsection{Descriptive controls and benchmark contact}"]
    descriptive = [s for s in snapshot["studies"] if s.get("outcomes_publishable")]
    if not descriptive:
        lines += ["Qualification, development, sizing, matched-evidence assays, stable/drift adaptation,",
                  "nonreuse overhead and native stateful gain remain unmeasured in complete audited studies.",
                  "Incomplete runs remain visible in the status artifact without interim outcome estimates."]
    else:
        lines += [r"\begin{table*}[t]\centering\small",
                  r"\begin{tabular}{>{\raggedright\arraybackslash}p{.28\textwidth}>{\raggedright\arraybackslash}p{.13\textwidth}>{\raggedright\arraybackslash}p{.18\textwidth}>{\raggedright\arraybackslash}p{.27\textwidth}}",
                  r"\toprule Complete study & Evidence class & Schedule & Outcome status\\\midrule"]
        for study in descriptive:
            if "qualification_passed" in study:
                decision = "Qualification passes" if study["qualification_passed"] else "Qualification fails"
                cells = study["qualification_cells"]
                decision += "; " + str(sum(c["correct"] for c in cells)) + "/" + str(sum(c["n"] for c in cells)) + " correct"
            elif study.get("analysis"):
                decision = "Conjunction passes" if study["primary_claim"] else "Conjunction does not pass"
            elif study["kind"] == "native":
                gains = study["native"]["paired_stateful_gains"]
                decision = "Stateful gain " + number(100 * sum(g["accuracy_gain"] for g in gains) / len(gains)) + " pp"
            elif study.get("deletion"):
                deletion = study["deletion"]
                decision = (str(deletion["answer_flips_to_wrong"]) + "/" + str(deletion["eligible_cases"]) + " answers flip to wrong"
                            if deletion["eligible_cases"] else "Zero eligible cases; no reruns performed")
            else:
                decision = "Descriptive; no primary claim"
            count = ("Fixed-database permutations" if study["kind"] == "native" else
                     "All " + str(study["deletion"]["eligible_cases"]) + " frozen eligible events" if study.get("deletion") else
                     str(study["streams"]) + " streams; " + ", ".join(study["conditions"] or ["reuse"]))
            evidence_class = "Descriptive diagnostic" if study["kind"] == FAST_PROTOCOL else study["kind"]
            lines.append(" & ".join(map(latex, (study["name"], evidence_class, count, decision))) + r"\\")
        lines += [r"\bottomrule\end{tabular}\caption{Complete audited studies, including negative results.",
                  r"Full per-arm counts and costs appear in the accompanying status artifact; distinct",
                  r"studies are never pooled to enlarge the confirmation denominator.}\end{table*}"]
    lines += ["Matched-history fork costs include each complete donor prefix; overlapping checkpoint",
              "costs are not added as physical model usage. Native permutations reuse fixed databases",
              "and do not count as independent custom streams. A negative drift or stateful-gain result",
              "remains part of the report rather than becoming a reason to replace its schedule.",
              r"\subsection{Provenance and reporting boundary}",
              "The machine-readable status and its readable companion record every discovered study,",
              "input hashes, source and schedule bindings, completed record counts, measured costs and",
              "integrity failures. The publisher makes no model calls and accepts primary estimates only",
              "after recomputing the frozen analysis from complete audited panels. Missing measurements",
              "are never replaced with zeros, development estimates or test-double outputs.",
              "Earlier GH200 development does not contribute observations to these campaign tables."]
    if snapshot.get("setup"):
        lines += ["Generic transport smoke calls are recorded separately in the status artifact,",
                  "including failed setup attempts with unknown usage. They are not study observations."]
    return "\n".join(lines) + "\n"


def render_markdown(snapshot):
    lines = ["# Campaign status", "", "This is a deterministic snapshot of saved local receipts, not a live process monitor.",
             "Partial runs have no published outcome estimates. Complete negative results remain visible.",
             "", f"Input snapshot SHA256: `{snapshot['input_snapshot_sha256']}`.", "",
             "| Study | Class | Status | Saved records | Decision |",
             "|---|---|---|---:|---|"]
    for s in snapshot["studies"]:
        progress = s.get("progress", {})
        count = f"{progress.get('saved_records', progress.get('completed_records', 'unknown'))}/{s.get('planned_records', 'unknown')}"
        decision = ("All five pass" if s["primary_claim"] else "Five-endpoint conjunction does not pass") if s.get("analysis") else s.get("reason", "Descriptive only")
        if "qualification_passed" in s:
            decision = "Qualification passes" if s["qualification_passed"] else "Qualification fails"
        cells = [s["name"], s.get("kind", "pending"), s["status"], count, decision]
        lines.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    if not snapshot["studies"]:
        lines += ["", "No frozen campaign studies are present. Confirmation and native gain are unmeasured."]
    for s in snapshot["studies"]:
        lines += ["", "## " + s["name"], "", f"Source: `{s['path']}`."]
        for field in ("reason", "inference_scope", "analysis_error", "mechanism_error", "diagnostic_error", "power_error"):
            if field in s:
                lines += ["", field.replace("_", " ").capitalize() + ": " + s[field]]
        if s.get("physical_cost"):
            c = s["physical_cost"]
            if s.get("physical_cost_scope"):
                lines += ["", f"Incomplete diagnostic usage: {c['calls']:,} calls, "
                          f"{c['known_total_tokens']:,} known token subtotal, "
                          f"{c['unknown_usage_calls']:,} calls with unknown usage.",
                          "", "Saved progress (not an audited outcome estimate):",
                          "```json", canonical(s["progress"]), "```"]
            else:
                lines += ["", f"Complete physical usage: {c['calls']:,} calls, {c['total_tokens']:,} measured tokens."]
        elif s.get("progress"):
            lines += ["", "Saved progress (not an audited outcome estimate):", "```json", canonical(s["progress"]), "```"]
        if s.get("analysis"):
            lines += ["", "| Primary endpoint | Estimate | Lower bound | Threshold | Pass |",
                      "|---|---:|---:|---:|---|"]
            for key in ENDPOINTS:
                e = s["analysis"]["endpoints"][key]
                estimate = ("ratio " + number(e["aggregate_token_ratio"], 4) if key.startswith("tokens_") else number(e["mean"], 4))
                lines.append(f"| {key} | {estimate} | {number(e['lower'], 4)} | {e['null_boundary']} | {e['passed']} |")
            lines += ["", "Token lower bounds are for 0.8 × control cost − delayed cost, in tokens. Accuracy bounds use proportions."]
        if s.get("descriptive"):
            lines += ["", "Descriptive outcomes (complete studies only):", "",
                      "| Condition | Checkpoint | Arm | Streams | Final/probe correct | Tokens |",
                      "|---|---:|---|---:|---:|---:|"]
            for g in s["descriptive"]:
                lines.append(f"| {g['condition']} | {g['checkpoint'] or '—'} | {g['arm']} | {g['streams']} | {g['correct']}/{g['n']} | {g['tokens']} |")
            if s.get("logical_checkpoint_costs_overlap"):
                lines += ["", "Assay table tokens are logical fork totals including the full common donor prefix. Checkpoints overlap and must not be summed as physical cost."]
        if s.get("qualification_cells"):
            lines += ["", "Every qualification cell:", "", "| Seed | Arm | Family | Correct | Required | Pass |",
                      "|---:|---|---|---:|---:|---|"]
            for cell in s["qualification_cells"]:
                lines.append(f"| {cell['seed']} | {cell['arm']} | {cell['family']} | {cell['correct']}/{cell['n']} | {cell['minimum']} | {cell['pass']} |")
        if s.get("diagnostic"):
            lines += ["", "Descriptive paired-stream changes; two-sided 95% intervals without multiplicity adjustment:",
                      "", "| Contrast | Arm/control | Mean (pp) | Lower (pp) | Upper (pp) |",
                      "|---|---|---:|---:|---:|"]
            for contrast in ("drift_minus_stable", "delayed_minus_control_drift_change",
                             "delayed_minus_control_future_accuracy"):
                for arm, interval in s["diagnostic"].get(contrast, {}).items():
                    values = " | ".join(number(100 * interval[k]) for k in ("mean", "lower", "upper"))
                    lines.append(f"| {contrast} | {arm} | {values} |")
        if s.get("power_planning"):
            lines += ["", "Prospective power planning (not a measured confirmation result):",
                      "```json", canonical(s["power_planning"]), "```"]
        if s.get("mechanism"):
            m = s["mechanism"]
            lines += ["", f"Qualifying fixed-program events: {m['qualifying_event_count']}. Agent deletion reruns: **not established by this audit**.",
                      "", "The first five events in frozen record order (all events are in status.json):"]
            for event in m["events"][:5]:
                lines += ["```json", canonical(event), "```"]
        if s.get("deletion"):
            deletion = s["deletion"]
            if deletion["eligible_cases"]:
                lines += ["", f"Agent relation deletion: {deletion['answer_flips_to_wrong']}/{deletion['eligible_cases']} answers flip to wrong; "
                          f"{deletion['correct_despite_deletion']} remain correct despite deletion."]
            else:
                lines += ["", "The complete source campaign has **zero eligible deletion cases**: no reruns performed."]
            lines += ["", "Every eligible case was frozen before rerunning. Original direct SQL evidence remains; "
                      "rerun feedback does not reach the source campaign. These are conditional event counts, not independent-stream estimates.",
                      "", "Original acquisition/evaluation cost (separate from these additional reruns): "
                      + str(deletion["original_acquisition_and_evaluation_cost"]["total_tokens"]) + " tokens."]
        if s.get("native"):
            lines += ["", "Native CL-Bench, fixed-database permutations:", "",
                      "| Permutation | Arm | Accuracy | Reward | Queries | Tokens |",
                      "|---:|---|---:|---:|---:|---:|"]
            for row in s["native"]["runs"]:
                lines.append(f"| {row['run_index']} | {row['arm']} | {number(row['accuracy'], 4)} | {number(row['reward'], 4)} | {row['queries']} | {row['total_tokens']} |")
            for gain in s["native"]["paired_stateful_gains"]:
                lines.append(f"\nPermutation {gain['run_index']}: stateful accuracy gain {100 * gain['accuracy_gain']:.2f} pp; reward gain {gain['reward_gain']:.4f}.")
    if snapshot.get("setup"):
        lines += ["", "## Separate runtime setup calls", "",
                  "These generic transport checks are outside the study comparisons. Unknown usage is retained.",
                  "", "| Receipt | Status | Calls | Known token subtotal | Unknown-usage calls |",
                  "|---|---|---:|---:|---:|"]
        for receipt in snapshot["setup"]:
            cost = receipt.get("cost", {})
            lines.append(f"| {receipt['path']} | {receipt['status']} | {cost.get('calls', 'unknown')} | "
                         f"{cost.get('known_total_tokens', 'unknown')} | {cost.get('unknown_usage_calls', 'unknown')} |")
    lines += ["", "Full source, summary, analysis and raw-receipt inventory hashes are retained in status.json.",
              "No model calls, publication actions or remote writes are performed by this report builder."]
    return "\n".join(lines) + "\n"


def build_snapshot(directories, *, setup_paths=()):
    inputs = Inputs()
    studies = [inspect_study(path, inputs) for path in sorted(set(map(lambda p: Path(p).resolve(), directories)))]
    setup = []
    for path in sorted(set(map(Path, setup_paths))):
        receipt = {"path": label(path), "status": "invalid"}
        try:
            raw = inputs.read(path)
            no_test_double(raw)
            require(isinstance(raw.get("records"), list), "setup call records missing")
            receipt.update(status=raw["status"], cost=usage(raw["records"]),
                           purpose=raw.get("purpose", "generic runtime setup"))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            receipt["error"] = str(exc)
        setup.append(receipt)
    inventory = {"files": dict(sorted(inputs.files.items())), "trees": dict(sorted(inputs.trees.items()))}
    return {"schema_version": 1, "publisher_sha256": file_sha(__file__),
            "input_snapshot_sha256": digest(inventory), "inputs": inventory, "studies": studies,
            "setup": setup,
            "model_calls_made": 0, "partial_outcomes_published": False,
            "policy": "complete bound real-model measurements only; all discovered negative studies retained"}


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, default=ROOT / "artifacts/campaign")
    parser.add_argument("--study", type=Path, action="append", default=[])
    parser.add_argument("--status-dir", type=Path, default=ROOT / "artifacts/campaign/publication")
    parser.add_argument("--tex", type=Path, default=ROOT / "paper/campaign_results.tex")
    args = parser.parse_args()
    snapshot = build_snapshot([*discover(args.campaign_root), *args.study],
                              setup_paths=args.campaign_root.glob("runtime*/smoke*.json"))
    save(args.status_dir / "status.json", snapshot)
    write_text(args.status_dir / "STATUS.md", render_markdown(snapshot))
    write_text(args.tex, render_tex(snapshot))
    print(canonical({"studies": len(snapshot["studies"]), "input_snapshot_sha256": snapshot["input_snapshot_sha256"],
                     "status": label(args.status_dir / "STATUS.md"), "tex": label(args.tex), "model_calls_made": 0}))


if __name__ == "__main__":
    main()
