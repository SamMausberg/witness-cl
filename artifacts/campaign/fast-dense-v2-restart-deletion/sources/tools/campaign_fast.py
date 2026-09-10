#!/usr/bin/env python3
"""Separate, time-bounded descriptive study; never a replacement 32-stream result.

Exactly two fresh streams, three unchanged arms, and 240 assigned episodes.
This wrapper explicitly installs its frozen schedule and summary callbacks in
the campaign runner process. Learner, SQL executor, inference settings, source
validation, call journals and ordinary record replay remain unchanged.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tools import campaign
from witness_cl.campaign_io import JournalClient, canonical, journal_usage, read, save, sha, study_lock
from witness_cl.model_v8 import BudgetStop

VERSION = "descriptive_fast_240_v1"
SEEDS = [101302, 101303]
ARMS = ["full_history", "ace", "delayed"]
OLD = [0, 3, 4, 6]
FINAL = [0, 3, 9, 12, 18, 23, 29, 30]
LAST_CALL_START = "2026-09-10T00:37:00+00:00"
GENERATION_DEADLINE = "2026-09-10T00:40:00+00:00"
REPORT_DEADLINE = "2026-09-10T00:43:00+00:00"
BASE_INVENTORY = campaign.source_inventory
BASE_SUMMARIZE = campaign.summarize
BASE_EXECUTE = campaign.execute_episode


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def source_inventory():
    extra = ("tools/campaign_fast.py", "tools/campaign_fast_diagnostics.py",
             "tools/campaign_pilot_report.py", "tools/publish_campaign.py",
             "docs/campaign/TIME_BUDGET_AMENDMENT.md")
    return {**BASE_INVENTORY(), **{name: sha(ROOT / name) for name in extra}}


def validate_fresh_seeds(root):
    inspected = {}
    for path in sorted(Path(root).rglob("freeze.json")):
        if "sources" in path.relative_to(root).parts:
            continue
        frozen = read(path)
        require(not set(frozen.get("seeds", [])).intersection(SEEDS),
                "fresh fast-study seeds overlap an existing frozen study")
        inspected[str(path.resolve())] = sha(path)
    return inspected


def protocol():
    return {"experiment": VERSION, "kind": VERSION, "split": "development",
            "seeds": SEEDS, "arms": ARMS, "conditions": ["reuse"], "old_replicates": 8,
            "old_indices": OLD, "final_indices": FINAL, "cold_start_each_episode": False,
            "last_call_start_utc": LAST_CALL_START, "generation_deadline_utc": GENERATION_DEADLINE,
            "report_deadline_utc": REPORT_DEADLINE,
            "schedule_adapter": "explicit scoped campaign_fast schedule/summary/source callbacks",
            "independent_streams": 2, "confirmatory_result": False,
            "original_32_stream_pilot_completed": False}


def validate_protocol(frozen):
    require(all(frozen.get(key) == value for key, value in protocol().items()),
            "fast study differs from the exact prospectively assigned protocol")


def planned_records(frozen):
    validate_protocol(frozen)
    phases = ([('ordinary', index) for index in range(8)]
              + [('old_before', index) for index in OLD]
              + [('ordinary', index) for index in range(8, 24)]
              + [('old_after', index) for index in OLD]
              + [('final', index) for index in FINAL])
    records = []
    for seed in SEEDS:
        for position, (phase, index) in enumerate(phases):
            offset = (seed + position) % len(ARMS)
            for arm in ARMS[offset:] + ARMS[:offset]:
                records.append({"seed": seed, "condition": "reuse", "phase": phase, "index": index,
                                "arm": arm, "key": campaign.record_key(seed, "reuse", phase, index, arm)})
    return records


def fixture_digest(frozen):
    fixtures = {}
    for row in planned_records(frozen):
        key = campaign.record_key(row["seed"], "reuse", row["phase"], row["index"], "fixture")
        if key not in fixtures:
            spec = campaign.make_episode(row["seed"], "development", "reuse", row["phase"], row["index"], old_replicates=8)
            fixtures[key] = dict(spec._metadata)["data_sha256"]
    return digest(fixtures)


def summarize(records, frozen):
    validate_protocol(frozen)
    value = BASE_SUMMARIZE(records, frozen)
    value.update(kind=VERSION, experiment=VERSION, planned_records=240, recorded_records=len(records),
                 complete=len(records) == 240 and all(record["trace"]["status"] in
                          {"completed", "no_valid_answer"} for record in records)
                          and value["cost"]["unknown_usage_calls"] == 0,
                 expected_phase_counts_per_stream_arm={"ordinary": 24, "old_before": 4,
                                                       "old_after": 4, "final": 8},
                 confirmatory=False, claim_confirmed=False, original_32_stream_pilot_completed=False)
    return value


def deadline_journal(frozen):
    start_cutoff = datetime.fromisoformat(frozen["last_call_start_utc"]).timestamp()
    finish_cutoff = datetime.fromisoformat(frozen["generation_deadline_utc"]).timestamp()

    class DeadlineJournal(JournalClient):
        def complete(self, messages, budget, **kwargs):
            path = self.directory / f"{self.index:03d}.json"
            if path.exists():
                # Already funded, completely recorded calls can replay after
                # the cutoff. Unknown calls retain the normal no-retry rule.
                return super().complete(messages, budget, **kwargs)
            if time.time() >= start_cutoff:
                raise BudgetStop("fast_declared_call_start_cutoff")
            original = budget.deadline
            budget.deadline = min(original, time.monotonic() + max(0, finish_cutoff - time.time()))
            try:
                return super().complete(messages, budget, **kwargs)
            finally:
                budget.deadline = original

    return DeadlineJournal


def deadline_episode(*args, **kwargs):
    trace = BASE_EXECUTE(*args, **kwargs)
    failure = trace.get("memory_update_failure", {})
    if failure.get("error_type") == "BudgetStop":
        # ACE catches update exceptions internally. Mark the recorded episode
        # incomplete before the outer runner saves it; do not alter its learner
        # state, requests, outputs, or partially completed update receipts.
        trace.update(status="resource_stop", error=failure.get("error", "ACE update budget stop"))
    return trace


@contextmanager
def adapted(frozen, *, generation=False):
    """Visible, temporary protocol adapter; never edits the underlying files."""
    validate_protocol(frozen)
    replacements = {"planned_records": planned_records, "summarize": summarize,
                    "source_inventory": source_inventory}
    if generation:
        replacements["JournalClient"] = deadline_journal(frozen)
        replacements["execute_episode"] = deadline_episode
    previous = {name: getattr(campaign, name) for name in replacements}
    require(previous["planned_records"] is not planned_records, "nested fast adapter is prohibited")
    try:
        for name, replacement in replacements.items():
            setattr(campaign, name, replacement)
        yield
    finally:
        for name, original in previous.items():
            setattr(campaign, name, original)


def freeze(out, *, runtime_config, runtime_receipt, client_config, qualification_report=None,
           allow_test_double=False):
    out = Path(out)
    require(not out.exists(), "fast freeze never overwrites an existing output")
    hashes = source_inventory()
    evidence, files = {}, {}
    seed_registry = {}
    if not allow_test_double:
        seed_registry = validate_fresh_seeds(ROOT / "artifacts/campaign")
        require(time.time() < datetime.fromisoformat(LAST_CALL_START).timestamp(), "fast collection cutoff already passed")
        require(runtime_receipt.get("status") == "running" and runtime_receipt.get("config") == runtime_config
                and runtime_receipt.get("model_sha256"), "running exact model-byte receipt required")
        require(qualification_report is not None and len(qualification_report) == 2,
                "both complete audited qualification studies are required")
        expected = {"model": runtime_config["model"]["alias"], "decoding": runtime_config["decoding"],
                    "context_tokens": runtime_config["server"]["context_tokens"],
                    "endpoint": "http://{host}:{port}".format(**runtime_config["server"]),
                    "response_mode": "schema", "max_output": 4096, "timeout": 180.0}
        require(all(client_config.get(key) == value for key, value in expected.items()),
                "fast client differs from the unchanged qualified runtime")
        evidence, files = campaign._prerequisites(kind="development", seeds=SEEDS, conditions=["reuse"],
            client_config=client_config, source_hashes=hashes, qualification_report=qualification_report,
            model_identity={"runtime_config": runtime_config, "model_sha256": runtime_receipt["model_sha256"]})
        require({condition for row in evidence["qualification"] for condition in row["conditions"]}
                == {"reuse", "drift"}, "both reuse and drift qualifications must be retained")
    frozen = {"schema_version": 1, **protocol(), "created_utc": campaign.utc(),
              "source_sha256": hashes, "environment": campaign.environment_fingerprint(),
              "runtime_config": deepcopy(runtime_config), "runtime_receipt": deepcopy(runtime_receipt),
              "client_config": deepcopy(client_config), "contains_test_double_calls": allow_test_double,
              "limits": {"solve_output_tokens": 4096, "max_model_calls_per_episode": 7,
                         "max_selects_per_episode": 8, "max_solve_actions": 5},
              "prerequisites": evidence, "evidence_sha256": {name: sha(path) for name, path in files.items()},
              "stopping": "complete 240 assignments or stop at declared deadline/integrity failure; never substitute streams",
              "scope": "new descriptive two-stream study; no noninferiority or confirmatory claim",
              "analysis": {"scope": "descriptive raw counts and full costs only"}}
    frozen["prior_freezes_checked_for_seed_overlap"] = seed_registry
    plan = planned_records(frozen)
    frozen.update(planned_records=240, schedule_sha256=digest(plan), fixtures_sha256=fixture_digest(frozen))
    for name, expected in hashes.items():
        target = out / "sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        require(sha(target) == expected, "source changed during fast freeze")
    for name, path in files.items():
        target = out / "evidence" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        require(sha(target) == frozen["evidence_sha256"][name], "prerequisite changed during freeze")
    save(out / "schedule.json", plan)
    save(out / "freeze.json", frozen)
    save(out / "freeze.sha256.json", {"sha256": sha(out / "freeze.json")})
    return frozen


def verify(out):
    out = Path(out)
    frozen = read(out / "freeze.json")
    validate_protocol(frozen)
    require(read(out / "freeze.sha256.json") == {"sha256": sha(out / "freeze.json")}, "fast freeze digest mismatch")
    require(fixture_digest(frozen) == frozen["fixtures_sha256"], "fast sparse fixture identity changed")
    with adapted(frozen):
        campaign._require_frozen_execution(out, frozen)
        campaign.check_study(out, frozen)
    return frozen


def run(out, client, *, max_new_records=None):
    frozen = verify(out)
    with adapted(frozen, generation=True):
        result = campaign.run(out, client, max_new_records=max_new_records)
    result.update(experiment=VERSION, last_call_start_utc=LAST_CALL_START,
                  generation_deadline_utc=GENERATION_DEADLINE, original_32_stream_pilot_completed=False)
    save(Path(out) / "manifest.json", result)
    return result


def audit(out):
    out = Path(out)
    frozen = verify(out)
    with study_lock(out), adapted(frozen):
        records = campaign.load_records(out)
        memories, replayed, stopped = {}, [], []
        for item, record in zip(planned_records(frozen), records, strict=False):
            group = (item["seed"], item["condition"], item["arm"])
            memory = memories.setdefault(group, campaign.memory_for(item["arm"]))
            unknown = any(call.get("generation_attempted") and call.get("usage") is None
                          for call in record["trace"]["model_calls"])
            if record["trace"]["status"] in {"resource_stop", "runtime_failure"} or unknown:
                # Preserve the terminal incomplete attempt and its costs. It is
                # not a successfully replayed episode or a complete assignment.
                require(record is records[-1], "stopped record must terminate the recorded schedule")
                require(record["before_snapshot"] == memory.snapshot()
                        and record["freeze_sha256"] == sha(out / "freeze.json"), "stopped record provenance changed")
                for index, call in enumerate(record["trace"]["model_calls"]):
                    campaign.validate_call(call, frozen, record["sampling_seed"])
                    require(read(out / "calls" / item["key"] / f"{index:03d}.json")["calls"] == [call],
                            "stopped record call receipt changed")
                stopped.append({"key": item["key"], "status": record["trace"]["status"],
                                "error": record["trace"].get("error"), "full_episode_replayed": False})
                break
            memory = campaign.validate_record(out, frozen, item, record, memory.snapshot())
            if item["phase"] == "ordinary":
                memories[group] = memory
            replayed.append(record)
        summary = summarize(records, frozen)
        require(read(out / "summary.json") == summary, "fast summary differs from raw records")
        physical = journal_usage(out / "calls")
        if len(records) == 240 and not stopped:
            require(physical == summary["cost"], "complete fast study has unaccounted physical calls")
        result = {"experiment": VERSION, "consistent": physical["unknown_usage_calls"] == 0,
                  "complete": summary["complete"] and not stopped, "records_replayed": len(replayed),
                  "recorded_records": len(records), "planned_records": 240, "stopped_records": stopped,
                  "network_calls": 0, "cost": physical, "freeze_sha256": sha(out / "freeze.json"),
                  "summary_sha256": sha(out / "summary.json"),
                  "records_sha256": campaign.artifact_digest(out / "episodes"),
                  "journals_sha256": campaign.artifact_digest(out / "calls"),
                  "claim_confirmed": False, "scope": "complete-record prefix replay; stopped attempts explicitly unreplayed"}
        save(out / "audit.json", result)
        return result


def mechanism(out):
    out = Path(out)
    audited = audit(out)
    frozen = verify(out)
    with study_lock(out), adapted(frozen):
        from tools.audit_campaign_mechanism import audit_records
        records = campaign.load_records(out)[:audited["records_replayed"]]
        result = audit_records(records)
        result.update(experiment=VERSION, complete_schedule=audited["complete"],
                      freeze_sha256=sha(out / "freeze.json"), audit_sha256=sha(out / "audit.json"),
                      summary_sha256=sha(out / "summary.json"),
                      records_sha256=audited["records_sha256"], journals_sha256=audited["journals_sha256"],
                      partial_census=not audited["complete"], primary_or_population_claim=False)
        save(out / "audit-mechanism.json", result)
        return result


def report(out):
    out = Path(out)
    frozen = verify(out)
    with adapted(frozen):
        records = campaign.load_records(out)
        summary = summarize(records, frozen)
    physical = journal_usage(out / "calls")
    result = {"experiment": VERSION, "complete": False, "recorded_records": len(records),
              "planned_records": 240, "expected_streams": 2, "physical_cost": physical,
              "scope": frozen["scope"], "original_32_stream_pilot_completed": False,
              "confirmatory_result": False, "inference_or_noninferiority_claim": False,
              "deadline": {key: frozen[key] for key in ("last_call_start_utc", "generation_deadline_utc", "report_deadline_utc")},
              "freeze_sha256": sha(out / "freeze.json")}
    result["contains_test_double_calls"] = frozen["contains_test_double_calls"]
    audit_path = out / "audit.json"
    if audit_path.exists():
        audited = read(audit_path)
        require(audited["freeze_sha256"] == sha(out / "freeze.json")
                and audited["summary_sha256"] == sha(out / "summary.json")
                and audited["records_sha256"] == campaign.artifact_digest(out / "episodes")
                and audited["journals_sha256"] == campaign.artifact_digest(out / "calls"), "fast audit is stale")
        result.update(audit_sha256=sha(audit_path), complete=audited["complete"] and audited["consistent"] and summary["complete"]
                      and not frozen["contains_test_double_calls"])
    require(frozen["contains_test_double_calls"] or not any(call.get("test_double")
            for record in records for call in record["trace"]["model_calls"]), "scripted call in empirical fast report")
    if result["complete"]:
        result["groups"] = summary["groups"]
    mechanism_path = out / "audit-mechanism.json"
    if mechanism_path.exists():
        from tools.audit_campaign_mechanism import audit_records
        from tools.campaign_pilot_report import mechanism_semantics
        census = read(mechanism_path)
        require(census["freeze_sha256"] == result["freeze_sha256"]
                and census["audit_sha256"] == result.get("audit_sha256")
                and census["summary_sha256"] == sha(out / "summary.json")
                and census["records_sha256"] == campaign.artifact_digest(out / "episodes")
                and census["journals_sha256"] == campaign.artifact_digest(out / "calls"), "mechanism census is stale")
        regenerated = audit_records(records[:audited["records_replayed"]])
        require(canonical(mechanism_semantics(regenerated))
                == canonical(mechanism_semantics({key: census.get(key) for key in regenerated})),
                "fast mechanism census differs from complete independent replay")
        result["mechanism"] = {"qualifying_events": census["qualifying_event_count"],
            "structural_events": census["structural_event_count"], "partial_census": census["partial_census"],
            "full_census_sha256": sha(mechanism_path), "agent_deletion_reruns_performed": False}
        if result["complete"]:
            from tools.campaign_fast_diagnostics import describe_complete
            result["descriptive_diagnostics"] = describe_complete(records, census["events"])
    save(out / "report.json", result)
    lines = ["# Separate two-stream descriptive study", "", f"Complete and audited: **{result['complete']}**. Recorded {len(records)} of 240 assigned episodes.",
             "", result["scope"], "", "This does not complete or replace the previously assigned 32-stream pilot.", "",
             f"Physical model calls: {physical['calls']}; tokens: {physical['total_tokens']}; unknown-usage calls: {physical['unknown_usage_calls']}."]
    if result["complete"]:
        lines += ["", "| Stream | Arm | Ordinary /24 | Old before /4 | Old after /4 | Future /8 | Full tokens |",
                  "|---|---|---:|---:|---:|---:|---:|"]
        for row in summary["groups"]:
            values = [row["phases"][phase]["correct"] for phase in ("ordinary", "old_before", "old_after", "final")]
            lines.append(f"| {row['seed']} | {row['arm']} | {' | '.join(map(str, values))} | {row['cost']['total_tokens']} |")
    else:
        lines += ["", "Incomplete or unaudited assignment: no comparative accuracy or token-saving estimate."]
    if "mechanism" in result:
        lines += ["", f"Qualifying fixed-program mechanism events: {result['mechanism']['qualifying_events']}. Partial census: {result['mechanism']['partial_census']}. Agent relation-deletion reruns were not performed."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run", "resume", "audit", "mechanism", "report"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path)
    parser.add_argument("--runtime-receipt", type=Path)
    parser.add_argument("--qualification-report", type=Path, nargs=2)
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    if args.command != "freeze":
        copied = args.out.resolve() / "sources/tools/campaign_fast.py"
        if Path(__file__).resolve() != copied:
            os.execv(sys.executable, [sys.executable, str(copied), *sys.argv[1:]])
    if args.command in {"freeze", "run", "resume"}:
        from witness_cl.model_campaign import build_client
        require(args.key_file is not None, "local credential file path required")
        if args.command == "freeze":
            require(args.runtime_config is not None and args.runtime_receipt is not None,
                    "runtime config and receipt required")
            cfg = read(args.runtime_config)
            client = build_client(cfg, args.key_file)
            result = freeze(args.out, runtime_config=cfg, runtime_receipt=read(args.runtime_receipt),
                            client_config=client.snapshot_config(), qualification_report=args.qualification_report)
            result = {key: result[key] for key in ("experiment", "planned_records", "seeds", "last_call_start_utc")}
        else:
            frozen = verify(args.out)
            result = run(args.out, build_client(frozen["runtime_config"], args.key_file))
    else:
        result = {"audit": audit, "mechanism": mechanism, "report": report}[args.command](args.out)
    print(canonical(result))


if __name__ == "__main__":
    main()
