#!/usr/bin/env python3
"""Separately bound offline report correction for unordered SQL lineage graphs.

The original frozen acquisition, audit criteria, raw receipts and failed report
remain untouched. Only lineage node and child presentation order is normalized;
every expression, graph edge, multiplicity, event and classification is retained.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

VERSION = "fast240_offline_lineage_order_report_v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def normalized_census(value):
    """Remove offline timings and order only explicitly labeled lineage graphs."""
    if isinstance(value, dict):
        result = {key: normalized_census(child) for key, child in value.items()
                  if key != "elapsed_seconds"}
        if "lineage" in result:
            for proof in result["lineage"].values():
                for node in proof["nodes"]:
                    require(isinstance(node["children"], list)
                            and all(isinstance(child, str) for child in node["children"]),
                            "invalid lineage child representation")
                    node["children"] = sorted(node["children"])
                # Sort complete node records, keeping duplicate nodes and edges.
                proof["nodes"] = sorted(proof["nodes"], key=canonical)
        return result
    if isinstance(value, (list, tuple)):
        return [normalized_census(child) for child in value]
    return value


def validate_census(regenerated, saved):
    selected = {key: saved.get(key) for key in regenerated}
    actual, expected = normalized_census(regenerated), normalized_census(selected)
    require(canonical(actual) == canonical(expected),
            "mechanism census differs beyond lineage presentation order or offline timing")
    return {"identical_after_declared_normalization": True,
            "normalized_census_sha256": hashlib.sha256(canonical(actual).encode()).hexdigest(),
            "normalization": "offline elapsed_seconds removed; lineage nodes and child names sorted with multiplicity retained",
            "classification_or_eligibility_changes": False}


def report(source_study, out):
    source_study, out = Path(source_study).resolve(), Path(out).resolve()
    require(not out.exists() and not out.is_relative_to(source_study),
            "corrected report must use a new directory outside the frozen study")
    source = source_study / "sources"
    require(not any(name.startswith(("witness_cl.", "experiments.", "tools.campaign"))
                    for name in sys.modules), "run corrected report in a fresh Python process")
    own_sha = sha(__file__)
    sys.path[:0] = [str(source), str(source / "src")]
    from tools import campaign_fast as fast
    from tools.audit_campaign_mechanism import audit_records
    from tools.campaign_fast_diagnostics import describe_complete
    from witness_cl.campaign_io import journal_usage, read, save, study_lock
    require(Path(fast.__file__).resolve() == source / "tools/campaign_fast.py",
            "corrected reporter must load the original frozen campaign implementation")
    with study_lock(source_study):
        frozen = fast.verify(source_study)
        require(not frozen["contains_test_double_calls"], "scripted calls cannot enter empirical reporting")
        with fast.adapted(frozen):
            records = fast.campaign.load_records(source_study)
            summary = fast.summarize(records, frozen)
        audited = read(source_study / "audit.json")
        census = read(source_study / "audit-mechanism.json")
        files = ("freeze.json", "freeze.sha256.json", "schedule.json", "summary.json",
                 "audit.json", "audit-mechanism.json", "report.log")
        inputs = {name: sha(source_study / name) for name in files}
        inputs.update(records_sha256=fast.campaign.artifact_digest(source_study / "episodes"),
                      journals_sha256=fast.campaign.artifact_digest(source_study / "calls"))
        require(audited["consistent"] and audited["complete"] and audited["records_replayed"] == 240
                and len(records) == 240 and summary["complete"]
                and summary == read(source_study / "summary.json"), "complete audited 240-record study required")
        for field, filename in (("freeze_sha256", "freeze.json"), ("summary_sha256", "summary.json"),
                                ("records_sha256", "records_sha256"), ("journals_sha256", "journals_sha256")):
            require(audited[field] == inputs[filename] and census[field] == inputs[filename],
                    "stale parent audit or mechanism binding")
        require(census["audit_sha256"] == inputs["audit.json"] and census["complete_schedule"]
                and not census["partial_census"], "complete bound mechanism census required")
        physical = journal_usage(source_study / "calls")
        require(physical == audited["cost"] == summary["cost"] and physical["unknown_usage_calls"] == 0,
                "raw physical cost differs from complete audit")
        require(not any(call.get("test_double") for row in records for call in row["trace"]["model_calls"]),
                "scripted call in real-model report")
        memories = {}
        for item, record in zip(fast.planned_records(frozen), records, strict=True):
            key = (item["seed"], item["condition"], item["arm"])
            memory = memories.setdefault(key, fast.campaign.memory_for(item["arm"]))
            after = fast.campaign.validate_record(source_study, frozen, item, record, memory.snapshot())
            if item["phase"] == "ordinary":
                memories[key] = after
        regenerated = audit_records(records)
        comparison = validate_census(regenerated, census)
        diagnostics = describe_complete(records, census["events"])
        result = {"experiment": fast.VERSION, "reporting_revision": VERSION, "complete": True,
                  "recorded_records": 240, "planned_records": 240, "expected_streams": 2,
                  "scope": frozen["scope"], "groups": summary["groups"], "physical_cost": physical,
                  "contains_test_double_calls": False, "confirmatory_result": False,
                  "original_32_stream_pilot_completed": False, "inference_or_noninferiority_claim": False,
                  "descriptive_diagnostics": diagnostics,
                  "mechanism": {"qualifying_events": census["qualifying_event_count"],
                      "structural_events": census["structural_event_count"], "partial_census": False,
                      "full_census_sha256": inputs["audit-mechanism.json"],
                      "agent_deletion_reruns_in_this_report": False},
                  "freeze_sha256": inputs["freeze.json"], "audit_sha256": inputs["audit.json"],
                  "offline_records_replayed": 240, "model_calls_made": 0, "comparison": comparison}
        manifest = {"reporting_revision": VERSION, "source_study": str(source_study),
                    "source_study_relative_to_output": os.path.relpath(source_study, out),
                    "inputs": inputs, "correction_source_sha256": own_sha,
                    "frozen_source_inventory": deepcopy(frozen["source_sha256"]),
                    "failed_report_preserved": True, "raw_results_or_frozen_sources_modified": False}
        require(sha(__file__) == own_sha, "reporter source changed during execution")
        out.mkdir(parents=True)
        shutil.copyfile(__file__, out / "campaign_fast_report.py")
        save(out / "replayed-mechanism.json", regenerated)
        save(out / "comparison.json", comparison)
        save(out / "report.json", result)
        lines = ["# Corrected offline two-stream descriptive report", "", frozen["scope"], "",
                 "All 240 assigned records passed offline prompt/SQL replay. This does not complete the original 32-stream pilot.", "",
                 "The frozen reporter failed because SQL lineage graph traversal order varied between processes. This separate report compares identical graph content after sorting node and child presentation order; audit criteria are unchanged.", "",
                 "| Stream | Arm | Ordinary /24 | Old before /4 | Old after /4 | Final /8 | Full tokens |",
                 "|---|---|---:|---:|---:|---:|---:|"]
        for row in summary["groups"]:
            values = [row["phases"][phase]["correct"] for phase in ("ordinary", "old_before", "old_after", "final")]
            lines.append(f"| {row['seed']} | {row['arm']} | {' | '.join(map(str, values))} | {row['cost']['total_tokens']} |")
        lines += ["", f"Qualifying fixed-program events: {census['qualifying_event_count']}. Structural events: {census['structural_event_count']}. All events and zero-count cells remain in the JSON report.",
                  "", "Actual agent relation-deletion reruns have their own separately frozen report and are not asserted here.",
                  "", f"Physical calls: {physical['calls']}; total tokens: {physical['total_tokens']}; unknown-usage calls: {physical['unknown_usage_calls']}."]
        (out / "REPORT.md").write_text("\n".join(lines) + "\n")
        manifest["outputs"] = {name: sha(out / name) for name in
                               ("campaign_fast_report.py", "replayed-mechanism.json", "comparison.json", "report.json", "REPORT.md")}
        save(out / "manifest.json", manifest)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-study", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = report(args.source_study, args.out)
    print(canonical({key: result[key] for key in ("reporting_revision", "complete", "offline_records_replayed", "model_calls_made")}))


if __name__ == "__main__":
    main()
