#!/usr/bin/env python3
"""Frozen common-source, matched-evidence causal assay; no probe learning.

The live full-history donor acquires every source and pays every check exactly
once. Frozen forks expose identical direct evidence, including check outputs.
Their representation and executable eligibility are the only memory changes.
Logical fork costs include the complete donor prefix; physical costs count the
shared donor once. This diagnostic is separate from the primary campaign.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from experiments.delayed_sql import execute_episode
from tools import campaign
from witness_cl.campaign_env import make_episode
from witness_cl.campaign_io import JournalClient, RecordedClient, journal_usage, read, save, sha, study_lock, usage
from witness_cl.delayed_memory import DelayedMemory, DelayedRegistry
from witness_cl.query_memory import _view_payload, canonical, digest

VERSION = "common_source_matched_evidence_v1"
ARMS = ("sql_archive_extra_evidence", "view_text", "immediate", "delayed")
CHECKPOINTS = (8, 16, 24)


def utc():
    return datetime.now(timezone.utc).isoformat()


def seed_for(*values, bits=63):
    return int.from_bytes(hashlib.sha256(canonical([VERSION, *values]).encode()).digest()[:8], "big") % (2**bits)


def default_seeds(kind):
    if kind not in {"development", "diagnostic"}:
        raise ValueError("assay kind must be development or diagnostic")
    start, count = (102000, 4) if kind == "development" else (300000, 64)
    return list(range(start, start + count))


def public_query_evidence(trace, *, allow_incomplete=False):
    """Exact allowlisted observations, including every numeric check result."""
    correct = trace.get("feedback", {}).get("correct")
    if type(correct) is not bool and not allow_incomplete:
        raise ValueError("ordinary terminal Boolean feedback required")
    return [
        {
            "episode_nonce": trace["episode_nonce"],
            "episode_index": trace["episode_index"],
            **({"question": trace["question"], "schema": trace["schema"]} if i == 0 else {}),
            "query_index": i,
            "sql": row["sql"],
            "params": deepcopy(row["params"]),
            "result": {key: deepcopy(row[key]) for key in ("columns", "rows", "error", "truncated")},
            "learning_check": row["learning_check"],
            "terminal": row["terminal"],
            "terminal_answer_correct": correct if row["terminal"] else None,
        }
        for i, row in enumerate(trace["queries"])
    ]


class DonorMemory(DelayedMemory):
    """Full-history source policy plus an invisible, deterministic check registry.

Subclassing uses the existing executor's same-session post-feedback checks;
the model receives no registry entries or executable tools during collection.
"""
    def __init__(self):
        super().__init__("delayed")
        self.arm = "full_history"
        self.history = []
        self.exact_evidence = []

    def active_payload(self):
        return {"history": self.history}

    def snapshot(self):
        return {"kind": "assay_full_history_donor", "arm": self.arm,
                "history": deepcopy(self.history), "exact_evidence": deepcopy(self.exact_evidence),
                "registry": self.registry.snapshot(), "events": deepcopy(self.events),
                "ordinary_count": self.ordinary_count, "active_bytes": self.active_bytes()}

    @classmethod
    def from_snapshot(cls, snapshot):
        if snapshot.get("kind") != "assay_full_history_donor":
            raise ValueError("wrong donor snapshot")
        memory = cls()
        memory.history = deepcopy(snapshot["history"])
        memory.exact_evidence = deepcopy(snapshot["exact_evidence"])
        memory.registry = DelayedRegistry.from_snapshot(snapshot["registry"])
        memory.events = deepcopy(snapshot["events"])
        memory.ordinary_count = snapshot["ordinary_count"]
        if canonical(memory.snapshot()) != canonical(snapshot):
            raise ValueError("donor checkpoint did not restore exactly")
        return memory

    def prefix_for_episode(self, question, schema, scope, episode_index):
        return deepcopy([message for episode in self.history for message in episode]), []

    def _bound(self):
        # Full history has the frozen model-context limit, not silent eviction.
        # The hidden check registry obeys the normal count/retrieval-byte bounds.
        registry_only = DelayedMemory("delayed")
        registry_only.registry = self.registry
        registry_only._bound()
        self.events.extend(registry_only.events)

    def finish(self, trace, conversation):
        if not trace.get("learn") or trace.get("phase") != "ordinary":
            raise ValueError("donor collection requires an ordinary learning episode")
        evidence = public_query_evidence(trace)
        # execute_episode ordinarily records these checks outside conversation.
        # Explicitly expose their exact SQL, bindings AND observed numeric rows.
        for item in evidence:
            if item["learning_check"]:
                conversation.append({"role": "user", "content":
                                     "Host check executed after the terminal answer within the original SELECT allowance. "
                                     + canonical(item)})
        self.history.append(deepcopy(conversation))
        self.exact_evidence.extend(evidence)
        self.ordinary_count += 1
        self.events.append({"event": "donor_episode_observed", "trace_sha256": digest(trace)})


class ForkMemory(DelayedMemory):
    """Immutable probe memory with a byte-identical direct-evidence prefix."""
    def __init__(self, arm, donor):
        if arm not in ARMS:
            raise ValueError("unknown assay fork")
        super().__init__("delayed")
        self.assay_arm = arm
        self.arm = "sql_archive" if arm == "sql_archive_extra_evidence" else arm
        self.registry = DelayedRegistry.from_snapshot(donor.registry.snapshot())
        self.exact_evidence = deepcopy(donor.exact_evidence)
        self.ordinary_count = donor.ordinary_count

    def active_payload(self):
        return {"common_direct_evidence": self.exact_evidence}

    def snapshot(self):
        return {"kind": "assay_frozen_fork", "arm": self.arm, "assay_arm": self.assay_arm,
                "exact_evidence": deepcopy(self.exact_evidence), "registry": self.registry.snapshot(),
                "ordinary_count": self.ordinary_count, "active_bytes": self.active_bytes()}

    def prefix_for_episode(self, question, schema, scope, episode_index):
        if scope is not None and scope.schema_sha256 != digest(schema):
            raise ValueError("current paid scope does not match current schema")
        entries = [] if scope is None or self.arm == "sql_archive" else self.registry.selected(
            question, scope, episode_index, immediate=self.arm == "immediate")
        # Identical wording for text and executable forks avoids a second cue.
        payload = {"common_direct_evidence": deepcopy(self.exact_evidence),
                   "source_derived_views": [_view_payload(entry.view) for entry in entries]}
        return [{"role": "user", "content":
                 "Prior source episodes and every paid direct check are reproduced below. "
                 "Old numeric results concern old rows. The current action schema determines "
                 "whether view definitions may be executed by a tool or incorporated into QUERY.\n"
                 + canonical(payload)}], [entry.view for entry in entries]

    def finish(self, *args, **kwargs):
        raise ValueError("assay probes cannot learn")


def planned_records(frozen):
    plan = []
    for seed in frozen["seeds"]:
        for checkpoint in CHECKPOINTS:
            for index in range(checkpoint - 8, checkpoint):
                plan.append({"seed": seed, "role": "donor", "checkpoint": checkpoint,
                             "index": index, "phase": "ordinary", "arm": "full_history",
                             "key": f"{seed}-donor-{index:03d}"})
            for index in range(checkpoint - 8, checkpoint):
                offset = (seed + index) % len(ARMS)
                for arm in ARMS[offset:] + ARMS[:offset]:
                    plan.append({"seed": seed, "role": "probe", "checkpoint": checkpoint,
                                 "index": index, "phase": "final", "arm": arm,
                                 "key": f"{seed}-checkpoint-{checkpoint:02d}-probe-{index:03d}-{arm}"})
    return plan


def source_inventory():
    sources = campaign.source_inventory()
    for path in (Path(__file__), ROOT / "docs/campaign/MATCHED_EVIDENCE_ASSAY.md"):
        sources[str(path.relative_to(ROOT))] = sha(path)
    return dict(sorted(sources.items()))


def freeze(out, *, kind, runtime_config, runtime_receipt, client_config,
           seeds=None, allow_test_double=False):
    out = Path(out)
    if out.exists():
        raise ValueError("assay output already exists; never overwrite a freeze")
    seeds = default_seeds(kind) if seeds is None else seeds
    required = 4 if kind == "development" else 64
    if (kind not in {"development", "diagnostic"} or not seeds
            or len(set(seeds)) != len(seeds)
            or any(type(s) is not int or not 0 <= s < 2**63 for s in seeds)
            or (not allow_test_double and len(seeds) != required)):
        raise ValueError("independent fixed four-stream development or64-stream diagnostic required")
    if not allow_test_double and (runtime_receipt.get("status") != "running"
                                 or runtime_receipt.get("config") != runtime_config
                                 or not runtime_receipt.get("model_sha256")):
        raise ValueError("running exact pinned runtime receipt required")
    if not allow_test_double and (
            client_config.get("model") != runtime_config["model"]["alias"]
            or client_config.get("decoding") != runtime_config["decoding"]
            or client_config.get("context_tokens") != runtime_config["server"]["context_tokens"]
            or client_config.get("endpoint") != "http://{host}:{port}".format(**runtime_config["server"])
            or client_config.get("max_output") != 4096 or client_config.get("response_mode") != "schema"):
        raise ValueError("assay client differs from frozen runtime and action interface")
    frozen = {
        "schema_version": 1, "experiment": VERSION, "kind": kind, "created_utc": utc(),
        "seeds": seeds, "split": "diagnostic", "condition": "reuse", "arms": list(ARMS),
        "checkpoints": list(CHECKPOINTS), "probes_per_checkpoint": 8,
        "source_sha256": source_inventory(), "runtime_config": deepcopy(runtime_config),
        "environment": campaign.environment_fingerprint(),
        "runtime_receipt": deepcopy(runtime_receipt), "client_config": deepcopy(client_config),
        "contains_test_double_calls": allow_test_double,
        "limits": {"solve_output_tokens": 4096, "max_model_calls_per_episode": 5,
                   "max_selects_per_episode": 8, "max_solve_actions": 5},
        "eligibility": "view_text and delayed use identical corroborated relations; immediate also exposes provisional",
        "evidence": "all donor SQL, exact bindings, results including numeric checks, terminal Boolean feedback; no eviction",
        "donor": "full_history; no views exposed; checks after terminal feedback within original allowance",
        "probe_rows": "final blocks0/1/2 preserve schema/conventions and use fresh rows at checkpoints8/16/24",
        "accounting": "each logical fork pays complete donor prefix plus its own probes; physical donor generated once",
        "stopping": "complete all scheduled records; stop only integrity/runtime/source failure or unknown usage",
        "wall_deadline_seconds": None, "confirmatory_primary_result": False,
    }
    plan = planned_records(frozen)
    fixtures = {}
    for item in plan:
        key = f"{item['seed']}-{item['phase']}-{item['index']}"
        if key not in fixtures:
            spec = make_episode(item["seed"], "diagnostic", "reuse", item["phase"], item["index"])
            fixtures[key] = dict(spec._metadata)["data_sha256"]
    frozen.update(planned_records=len(plan), schedule_sha256=digest(plan), fixtures_sha256=digest(fixtures))
    out.mkdir(parents=True)
    for name, expected in frozen["source_sha256"].items():
        target = out / "sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        if sha(target) != expected:
            raise ValueError("source changed during assay freeze")
    save(out / "freeze.json", frozen)
    save(out / "freeze.sha256.json", {"sha256": sha(out / "freeze.json")})
    save(out / "schedule.json", plan)
    return frozen


def verify_freeze(out):
    out = Path(out)
    frozen = read(out / "freeze.json")
    if read(out / "freeze.sha256.json") != {"sha256": sha(out / "freeze.json")}:
        raise ValueError("assay freeze digest mismatch")
    if source_inventory() != frozen["source_sha256"]:
        raise ValueError("assay frozen source changed; retain this study and freeze a new version")
    if campaign.environment_fingerprint() != frozen["environment"]:
        raise ValueError("assay Python, SQLite or dependency environment changed")
    if (frozen["experiment"] != VERSION or frozen["arms"] != list(ARMS)
            or frozen["checkpoints"] != list(CHECKPOINTS)
            or read(out / "schedule.json") != planned_records(frozen)
            or digest(planned_records(frozen)) != frozen["schedule_sha256"]):
        raise ValueError("assay fixed schedule changed")
    return frozen


def record_path(out, item):
    return Path(out) / "episodes" / (item["key"] + ".json")


def save_record(path, record):
    # Commit digest before result so every committed record has a checksum.
    save(path.with_suffix(".sha256.json"), {"record_sha256": digest(record)})
    save(path, record)


def read_record(path):
    record = read(path)
    if read(path.with_suffix(".sha256.json")) != {"record_sha256": digest(record)}:
        raise ValueError("assay record hash mismatch")
    return record


def prefix_ledger(donors):
    return {"records": [{"key": record["key"], "sha256": digest(record)} for record in donors],
            "cost": receipt_cost(donors),
            "select_attempts": sum(record["trace"]["select_attempts"] for record in donors),
            "learning_checks": sum(sum(row["learning_check"] for row in record["trace"]["queries"]) for record in donors),
            "evidence_sha256": digest([item for record in donors for item in public_query_evidence(record["trace"], allow_incomplete=True)])}


def journal_summary(directory):
    paths = sorted(Path(directory).glob("[0-9][0-9][0-9].json"))
    if [path.stem for path in paths] != [f"{i:03d}" for i in range(len(paths))]:
        raise ValueError("non-contiguous assay invocation journal")
    receipts = [read(path) for path in paths]
    return {"invocations": len(receipts), "uncertain_invocations": sum(
        receipt.get("state") != "recorded" or len(receipt.get("calls", [])) != 1
        for receipt in receipts)}


def receipt_cost(records):
    cost = usage([call for record in records for call in record["trace"]["model_calls"]])
    uncertain = sum(record.get("journal", {}).get("uncertain_invocations", 0) for record in records)
    cost["uncertain_invocations"] = uncertain
    if uncertain or cost["unknown_usage_calls"]:
        cost["total_tokens"] = None
    return cost


def journal_cost(out):
    cost = journal_usage(Path(out) / "calls")
    cost["uncertain_invocations"] = sum(journal_summary(path)["uncertain_invocations"]
                                        for path in (Path(out) / "calls").glob("*") if path.is_dir())
    return cost


def validate_record(record, item, frozen, before, ledger, out):
    if (any(record[k] != item[k] for k in item)
            or record["freeze_sha256"] != sha(Path(out) / "freeze.json")
            or canonical(record["before_snapshot"]) != canonical(before)
            or record["shared_prefix_ledger"] != ledger):
        raise ValueError("assay checkpoint, prefix ledger or schedule mismatch")
    if record["journal"] != journal_summary(Path(out) / "calls" / record["key"]):
        raise ValueError("assay invocation journal summary differs")
    if usage(record["trace"]["model_calls"])["unknown_usage_calls"] or record["journal"]["uncertain_invocations"]:
        raise ValueError("unknown usage retained; assay cannot continue past this record")
    if record["trace"]["status"] in {"resource_stop", "runtime_failure"}:
        raise ValueError("failed assay record retained; no automatic paid retry")
    if record["journal"]["invocations"] != len(record["trace"]["model_calls"]):
        raise ValueError("extra invocation outside completed assay trace")
    for i, call in enumerate(record["trace"]["model_calls"]):
        campaign.validate_call(call, frozen, record["sampling_seed"])
        if read(Path(out) / "calls" / record["key"] / f"{i:03d}.json") != {"state": "recorded", "calls": [call]}:
            raise ValueError("assay model-call journal differs")


def execute_record(item, memory, client, frozen):
    sample_seed = seed_for("sampling", item["seed"], item["role"], item["index"], bits=32)
    previous = getattr(client, "decoding", None)
    if previous is not None:
        client.decoding = replace(previous, seed=sample_seed)
    try:
        spec = make_episode(item["seed"], frozen["split"], frozen["condition"], item["phase"], item["index"])
        trace = execute_episode(
            spec, memory, client, campaign.budget_for(frozen), phase=item["phase"],
            learn=item["role"] == "donor", episode_index=item["index"] if item["role"] == "donor" else item["checkpoint"],
            episode_nonce=digest([VERSION, item["seed"], item["role"], item["index"]])[:24],
            solve_output_tokens=frozen["limits"]["solve_output_tokens"])
    finally:
        if previous is not None:
            client.decoding = previous
    return trace, sample_seed


def run(out, client, *, max_new_records=None):
    with study_lock(out):
        return _run(out, client, max_new_records=max_new_records)


def _run(out, client, *, max_new_records=None):
    out = Path(out)
    frozen = verify_freeze(out)
    if not frozen["contains_test_double_calls"] and ROOT.resolve() != (out / "sources").resolve():
        raise ValueError("real assays must run the immutable sources/tools/campaign_assay.py")
    if not frozen["contains_test_double_calls"] and client.snapshot_config() != frozen["client_config"]:
        raise ValueError("actual assay client differs from freeze")
    serving = None if frozen["contains_test_double_calls"] else campaign.runtime_identity(frozen)
    records, donors, memories = [], {}, {}
    new = 0
    manifest = {"experiment": VERSION, "status": "running", "started_utc": utc(),
                "planned_records": frozen["planned_records"], "completed_records": 0,
                "runtime_identity": serving}
    save(out / "manifest.json", manifest)
    try:
        for item in planned_records(frozen):
            seed = item["seed"]
            donor = memories.setdefault(seed, DonorMemory())
            source_records = donors.setdefault(seed, [])
            memory = DonorMemory.from_snapshot(donor.snapshot()) if item["role"] == "donor" else ForkMemory(item["arm"], donor)
            before = memory.snapshot()
            ledger = prefix_ledger(source_records)
            path = record_path(out, item)
            if path.exists():
                record = read_record(path)
            else:
                if max_new_records is not None and new >= max_new_records:
                    manifest["status"] = "checkpointed"
                    break
                verify_freeze(out)
                # Set the actual transport's seed, not only its journal wrapper.
                original = getattr(client, "decoding", None)
                sampling_seed = seed_for("sampling", seed, item["role"], item["index"], bits=32)
                if original is not None:
                    client.decoding = replace(original, seed=sampling_seed)
                journal = JournalClient(client, out / "calls" / item["key"])
                try:
                    trace, observed_seed = execute_record(item, memory, journal, frozen)
                finally:
                    if original is not None:
                        client.decoding = original
                if not journal.all_calls_consumed() or observed_seed != sampling_seed:
                    raise ValueError("orphaned assay call receipt or sampling mismatch")
                record = {**item, "freeze_sha256": sha(out / "freeze.json"),
                          "before_snapshot": before, "shared_prefix_ledger": ledger,
                          "journal": journal_summary(out / "calls" / item["key"]),
                          "sampling_seed": sampling_seed, "trace": trace, "recorded_utc": utc()}
                save_record(path, record)
                new += 1
            records.append(record)
            validate_record(record, item, frozen, before, ledger, out)
            if item["role"] == "donor":
                memories[seed] = DonorMemory.from_snapshot(record["trace"]["memory"])
                source_records.append(record)
            elif canonical(record["trace"]["memory"]) != canonical(before):
                raise ValueError("assay probe changed its frozen state")
            manifest["completed_records"] = len(records)
            save(out / "manifest.json", manifest)
        else:
            manifest["status"] = "completed"
    except BaseException as exc:
        manifest.update(status="failed", error_type=type(exc).__name__, error=str(exc)[:1000])
        raise
    finally:
        physical = journal_cost(out)
        manifest.update(finished_utc=utc(), physical_cost=physical)
        save(out / "manifest.json", manifest)
        save(out / "summary.json", summarize(records, frozen, physical_cost=physical))
    return manifest


def load_records(out, frozen=None):
    frozen = verify_freeze(out) if frozen is None else frozen
    plan = planned_records(frozen)
    expected_names = {item["key"] + ".json" for item in plan}
    actual_names = {path.name for path in (Path(out) / "episodes").glob("*.json")
                    if not path.name.endswith(".sha256.json")}
    if actual_names - expected_names:
        raise ValueError("unplanned assay episode receipt")
    records = []
    missing = False
    for item in plan:
        path = record_path(out, item)
        if not path.exists():
            missing = True
        else:
            if missing:
                raise ValueError("assay results have a gap in their frozen execution order")
            records.append(read_record(path))
    allowed_calls = {item["key"] for item in plan[:len(records) + 1]}
    if {path.name for path in (Path(out) / "calls").glob("*") if path.is_dir()} - allowed_calls:
        raise ValueError("assay invocation skips the frozen schedule")
    return records


def summarize(records, frozen, *, physical_cost=None):
    def valid(items):
        return all(record["trace"]["status"] in {"completed", "no_valid_answer"}
                   and receipt_cost([record])["total_tokens"] is not None for record in items)
    groups = []
    for seed in frozen["seeds"]:
        source = [r for r in records if r["seed"] == seed and r["role"] == "donor"]
        for checkpoint in CHECKPOINTS:
            prefix = [r for r in source if r["index"] < checkpoint]
            for arm in ARMS:
                probes = [r for r in records if r["seed"] == seed and r["role"] == "probe"
                          and r["checkpoint"] == checkpoint and r["arm"] == arm]
                groups.append({"seed": seed, "checkpoint": checkpoint, "arm": arm,
                               "donor_episodes": len(prefix), "probes": len(probes),
                               "correct": sum(r["trace"]["reward"] == 1 for r in probes),
                               "complete": len(prefix) == checkpoint and len(probes) == 8 and valid(prefix + probes),
                               "logical_cost_including_full_prefix": receipt_cost(prefix + probes),
                               "logical_selects_including_full_prefix": sum(r["trace"]["select_attempts"] for r in prefix + probes),
                               "executed_view_actions": sum(sum("compiled" in a for a in r["trace"]["actions"]) for r in probes),
                               "common_evidence_sha256": prefix_ledger(prefix)["evidence_sha256"]})
    total = receipt_cost(records) if physical_cost is None else physical_cost
    return {"experiment": VERSION, "kind": frozen["kind"], "records": len(records),
            "complete": len(records) == frozen["planned_records"] and valid(records), "groups": groups,
            "physical_cost": total, "physical_selects": sum(r["trace"]["select_attempts"] for r in records),
            "logical_checkpoint_costs_overlap": True,
            "contains_test_double_calls": frozen["contains_test_double_calls"],
            "population_or_primary_claim": False,
            "unknown_usage_requires_stop": total["unknown_usage_calls"] > 0 or total["uncertain_invocations"] > 0}


def audit(out):
    with study_lock(out):
        return _audit(out)


def _audit(out):
    out = Path(out)
    frozen = verify_freeze(out)
    records = load_records(out, frozen)
    memories, donors = {}, {}
    for item, record in zip(planned_records(frozen), records):
        donor = memories.setdefault(item["seed"], DonorMemory())
        source = donors.setdefault(item["seed"], [])
        memory = DonorMemory.from_snapshot(donor.snapshot()) if item["role"] == "donor" else ForkMemory(item["arm"], donor)
        validate_record(record, item, frozen, memory.snapshot(), prefix_ledger(source), out)
        replay = RecordedClient(record["trace"]["model_calls"])
        actual, sampling_seed = execute_record(item, memory, replay, frozen)
        if (replay.index != len(replay.calls) or sampling_seed != record["sampling_seed"]
                or canonical(campaign.semantic(actual)) != canonical(campaign.semantic(record["trace"]))):
            raise ValueError("assay independent transcript replay differs: " + item["key"])
        if item["role"] == "donor":
            memories[item["seed"]] = memory
            source.append(record)
    summary = summarize(records, frozen, physical_cost=journal_cost(out))
    if read(out / "summary.json") != summary:
        raise ValueError("assay summary differs from raw receipts")
    result = {"consistent": True, "complete": summary["complete"], "records_replayed": len(records),
              "model_calls_made": 0, "freeze_sha256": sha(out / "freeze.json"),
              "summary_sha256": sha(out / "summary.json"),
              "records_sha256": campaign.artifact_digest(out / "episodes"),
              "journals_sha256": campaign.artifact_digest(out / "calls"),
              "contains_test_double_calls": frozen["contains_test_double_calls"],
              "physical_cost": summary["physical_cost"], "primary_claim": False}
    save(out / "audit.json", result)
    return result


def all_deletion_cases(records, mechanism_audit=None):
    """Freeze the complete eligible census; no first-five outcome selection."""
    from tools.audit_campaign_mechanism import audit_records, prepare_deletion_cases
    mechanism_audit = audit_records(records) if mechanism_audit is None else mechanism_audit
    cases = prepare_deletion_cases(records, mechanism_audit,
                                   limit=len(mechanism_audit["events"]))
    for index, case in enumerate(cases):
        original = records[case["original_record_ordinal"]]
        case.update(key=f"deletion-{index:05d}", original_record_sha256=digest(original),
                    original_data_sha256=original["trace"]["evaluator"]["data_sha256"],
                    original_correct=original["trace"]["reward"] == 1.0)
        if not case["original_correct"] or case["sampling_seed"] is None:
            raise ValueError("deletion requires a correct source execution with frozen sampling seed")
    return cases, mechanism_audit


def deletion_source_inventory(source_schedule="campaign"):
    sources = source_inventory()
    if source_schedule == "fast240":
        for name in ("tools/campaign_fast.py", "docs/campaign/FAST_DELETION_PLAN.md"):
            sources[name] = sha(ROOT / name)
    elif source_schedule != "campaign":
        raise ValueError("unknown deletion source schedule")
    return sources


def resolve_deletion_source(out, frozen):
    """Locate a relocated parent without rewriting its original provenance."""
    if "source_study_relative_to_output" in frozen:
        locator = frozen["source_study_relative_to_output"]
        if not isinstance(locator, str) or not locator or Path(locator).is_absolute():
            raise ValueError("deletion parent locator must be a nonempty relative path")
        source = (Path(out) / locator).resolve()
    else:
        source = Path(frozen["source_study"]).resolve()
    if not source.is_dir():
        raise ValueError("deletion parent locator does not resolve to an existing directory")
    return source


def load_deletion_source(source_study, original, audit_receipt, source_schedule):
    """Explicitly validate the sparse parent schedule before enumerating cases."""
    if source_schedule == "fast240":
        from tools import campaign_fast as fast
        fast.validate_protocol(original)
        if (read(source_study / "freeze.sha256.json") != {"sha256": sha(source_study / "freeze.json")}
                or original["fixtures_sha256"] != fast.fixture_digest(original)
                or original["source_sha256"].get("tools/campaign_fast.py") != sha(ROOT / "tools/campaign_fast.py")):
            raise ValueError("fast deletion parent fixture or schedule implementation changed")
        plan = fast.planned_records(original)
        with fast.adapted(original):
            records = campaign.load_records(source_study)
        expected_summary = fast.summarize(records, original)
    elif source_schedule == "campaign":
        if original.get("experiment") == "descriptive_fast_240_v1":
            raise ValueError("fast parent requires the explicit fast240 deletion schedule adapter")
        plan = campaign.planned_records(original)
        records = campaign.load_records(source_study)
        expected_summary = campaign.summarize(records, original)
    else:
        raise ValueError("unknown deletion source schedule")
    if (read(source_study / "schedule.json") != plan or digest(plan) != original["schedule_sha256"]
            or original["planned_records"] != len(plan) or len(records) != len(plan)
            or audit_receipt.get("records_replayed") != len(plan)
            or read(source_study / "summary.json") != expected_summary
            or not expected_summary["complete"]
            or original["environment"] != campaign.environment_fingerprint()):
        raise ValueError("deletion source is not the complete exact audited schedule")
    # Reproduce every parent transition offline, retaining semantic panel indices,
    # sampling seeds and direct SQL observations. No model requests are made.
    memories = {}
    for item, record in zip(plan, records, strict=True):
        key = (item["seed"], item["condition"], item["arm"])
        memory = memories.setdefault(key, campaign.memory_for(item["arm"]))
        after = campaign.validate_record(source_study, original, item, record, memory.snapshot())
        if item["phase"] == "ordinary":
            memories[key] = after
    if journal_usage(source_study / "calls") != audit_receipt["cost"] or expected_summary["cost"] != audit_receipt["cost"]:
        raise ValueError("deletion source cost differs from its complete raw journal")
    if not original["contains_test_double_calls"] and any(
            call.get("test_double") for record in records for call in record["trace"]["model_calls"]):
        raise ValueError("scripted parent calls cannot enter real deletion evidence")
    return records


def freeze_deletion(out, source_study, *, source_schedule="campaign"):
    """Bind all eligible cases from a completed, already replay-audited campaign."""
    out, source_study = Path(out).resolve(), Path(source_study).resolve()
    if out.exists():
        raise ValueError("deletion diagnostic output already exists")
    original = read(source_study / "freeze.json")
    audit_receipt = read(source_study / "audit.json")
    if (audit_receipt.get("consistent") is not True or audit_receipt.get("complete") is not True
            or audit_receipt.get("freeze_sha256") != sha(source_study / "freeze.json")
            or audit_receipt.get("summary_sha256") != sha(source_study / "summary.json")
            or audit_receipt.get("records_sha256") != campaign.artifact_digest(source_study / "episodes")
            or audit_receipt.get("journals_sha256") != campaign.artifact_digest(source_study / "calls")
            or audit_receipt["cost"]["unknown_usage_calls"]):
        raise ValueError("deletion requires a complete source campaign audit bound to all current receipts")
    # Preserve the original generator/executor/runtime implementation. A later
    # algorithm revision must not silently rerun old cases under new semantics.
    for path, expected in original["source_sha256"].items():
        if path.startswith("src/") or path == "experiments/delayed_sql.py":
            if not (ROOT / path).is_file() or sha(ROOT / path) != expected:
                raise ValueError("deletion source generator or executor differs from original campaign")
    records = load_deletion_source(source_study, original, audit_receipt, source_schedule)
    cases, mechanism = all_deletion_cases(records)
    if not original["contains_test_double_calls"] and any(case["test_double"] for case in cases):
        raise ValueError("scripted source event cannot enter a real deletion diagnostic")
    frozen = {
        "schema_version": 1, "experiment": "agent_relation_deletion_v1", "created_utc": utc(),
        "source_study": str(source_study), "source_freeze_sha256": sha(source_study / "freeze.json"),
        "source_study_relative_to_output": os.path.relpath(source_study, out),
        "source_audit_sha256": sha(source_study / "audit.json"),
        "source_records_sha256": campaign.artifact_digest(source_study / "episodes"),
        "source_journals_sha256": campaign.artifact_digest(source_study / "calls"),
        "source_sha256": deletion_source_inventory(source_schedule), "environment": campaign.environment_fingerprint(),
        "source_schedule": source_schedule, "source_schedule_sha256": sha(source_study / "schedule.json"),
        "runtime_config": deepcopy(original["runtime_config"]),
        "runtime_receipt": deepcopy(original["runtime_receipt"]),
        "client_config": deepcopy(original["client_config"]),
        "contains_test_double_calls": original["contains_test_double_calls"],
        "source_split": original["split"], "old_replicates": original["old_replicates"],
        "cases_sha256": digest(cases), "planned_cases": len(cases),
        "limits": {"solve_output_tokens": 4096, "max_model_calls_per_episode": 5,
                   "max_selects_per_episode": 8, "max_solve_actions": 5},
        "selection": "all structural mechanism events in the complete source campaign; no first-five truncation",
        "intervention": "remove only one registry relation; retain every original direct SQL evidence record",
        "sampling": "original episode nonce, original sampling seed and same fresh database snapshot",
        "learn": False, "feedback_to_original_campaign": False,
        "original_acquisition_and_evaluation_cost": audit_receipt["cost"],
        "primary_or_population_claim": False,
    }
    if source_schedule == "fast240":
        frozen.update({key: original[key] for key in (
            "last_call_start_utc", "generation_deadline_utc", "report_deadline_utc")})
    out.mkdir(parents=True)
    for path, expected in frozen["source_sha256"].items():
        target = out / "sources" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
        if sha(target) != expected:
            raise ValueError("source changed during deletion diagnostic freeze")
    save(out / "cases.json", cases)
    save(out / "mechanism-selection.json", mechanism)
    frozen["selection_receipt_sha256"] = sha(out / "mechanism-selection.json")
    save(out / "freeze.json", frozen)
    save(out / "freeze.sha256.json", {"sha256": sha(out / "freeze.json")})
    return {"status": "frozen", "planned_cases": len(cases), "contains_test_double_calls": original["contains_test_double_calls"]}


def verify_deletion_freeze(out):
    out = Path(out)
    frozen = read(out / "freeze.json")
    cases = read(out / "cases.json")
    if (frozen.get("experiment") != "agent_relation_deletion_v1"
            or read(out / "freeze.sha256.json") != {"sha256": sha(out / "freeze.json")}
            or digest(cases) != frozen["cases_sha256"] or len(cases) != frozen["planned_cases"]
            or deletion_source_inventory(frozen.get("source_schedule", "campaign")) != frozen["source_sha256"]
            or campaign.environment_fingerprint() != frozen["environment"]
            or sha(out / "mechanism-selection.json") != frozen["selection_receipt_sha256"]):
        raise ValueError("deletion diagnostic manifest, source or environment changed")
    if frozen.get("source_schedule") == "fast240":
        source = resolve_deletion_source(out, frozen)
        parent = read(source / "freeze.json")
        if any(frozen.get(key) != parent.get(key) for key in (
                "last_call_start_utc", "generation_deadline_utc", "report_deadline_utc")):
            raise ValueError("fast deletion deadline differs from the parent protocol")
        for filename, key in (("freeze.json", "source_freeze_sha256"),
                              ("audit.json", "source_audit_sha256"),
                              ("schedule.json", "source_schedule_sha256")):
            if sha(source / filename) != frozen[key]:
                raise ValueError("fast deletion parent receipt changed")
        for directory, key in (("episodes", "source_records_sha256"), ("calls", "source_journals_sha256")):
            if campaign.artifact_digest(source / directory) != frozen[key]:
                raise ValueError("fast deletion parent raw records changed")
    return frozen, cases


def execute_deletion_case(case, client, frozen):
    memory = DelayedMemory.from_snapshot(case["before_snapshot"])
    if case["removed_entry_key"] in {entry.key for entry in memory.registry.entries}:
        raise ValueError("removed relation is still present")
    original = getattr(client, "decoding", None)
    if original is not None:
        client.decoding = replace(original, seed=case["sampling_seed"])
    try:
        spec = make_episode(case["seed"], frozen["source_split"], case["condition"],
                            case["phase"], case["index"], old_replicates=frozen["old_replicates"])
        if case.get("original_data_sha256", dict(spec._metadata)["data_sha256"]) != dict(spec._metadata)["data_sha256"]:
            raise ValueError("deletion database differs from its original episode")
        trace = execute_episode(spec, memory, client, campaign.budget_for(frozen),
                                phase=case["phase"], learn=False,
                                episode_nonce=case["original_episode_nonce"],
                                episode_index=case["episode_index"],
                                solve_output_tokens=frozen["limits"]["solve_output_tokens"])
    finally:
        if original is not None:
            client.decoding = original
    if canonical(trace["memory"]) != canonical(case["before_snapshot"]):
        raise ValueError("relation-deletion probe learned")
    return trace


def deletion_report(records, frozen, physical):
    completed = [r for r in records if r["trace"]["status"] in {"completed", "no_valid_answer"}]
    complete = len(completed) == frozen["planned_cases"] and physical["unknown_usage_calls"] == 0
    return {"experiment": frozen["experiment"], "planned_cases": frozen["planned_cases"],
            "recorded_cases": len(records), "completed_cases": len(completed),
            "complete": complete,
            "status": ("no_reruns_performed" if frozen["planned_cases"] == 0 else
                       "complete" if complete else "incomplete"),
            "source_schedule": frozen.get("source_schedule", "campaign"),
            "agent_reruns_performed": len(completed),
            "answer_flips_to_wrong": sum(r["trace"]["reward"] != 1 for r in completed),
            "correct_despite_deletion": sum(r["trace"]["reward"] == 1 for r in completed),
            "physical_diagnostic_cost": physical,
            "original_acquisition_and_evaluation_cost": frozen["original_acquisition_and_evaluation_cost"],
            "contains_test_double_calls": frozen["contains_test_double_calls"],
            "case_selection_was_frozen_before_rerun": True,
            "feedback_to_original_campaign": False, "population_claim": False}


def run_deletion(out, client, *, max_new_records=None, replay=False):
    out = Path(out).resolve()
    with study_lock(out):
        frozen, cases = verify_deletion_freeze(out)
        if max_new_records is not None and (type(max_new_records) is not int or max_new_records < 0):
            raise ValueError("nonnegative deletion checkpoint size required")
        keys = [case["key"] for case in cases]
        episode_files = {path.stem for path in (out / "episodes").glob("*.json")
                         if not path.name.endswith(".sha256.json")}
        if episode_files != set(keys[:len(episode_files)]):
            raise ValueError("deletion records are not the frozen case prefix")
        call_dirs = {path.name for path in (out / "calls").iterdir() if path.is_dir()} if (out / "calls").exists() else set()
        if call_dirs - set(keys[:len(episode_files) + 1]):
            raise ValueError("deletion model journal skips the frozen case census")
        if not frozen["contains_test_double_calls"]:
            if ROOT.resolve() != (out / "sources").resolve():
                raise ValueError("real deletion diagnostics must execute immutable sources/tools/campaign_assay.py")
            if not replay and cases and client.snapshot_config() != frozen["client_config"]:
                raise ValueError("deletion client differs from frozen source policy")
            if not replay and cases:
                save(out / "execution_environment.json", campaign.runtime_identity(frozen))
        records, new, replayed, stopped = [], 0, 0, []
        try:
            for case in cases:
                path = out / "episodes" / (case["key"] + ".json")
                if path.exists():
                    record = read_record(path)
                elif replay:
                    break
                else:
                    if max_new_records is not None and new >= max_new_records:
                        break
                    previous = getattr(client, "decoding", None)
                    if previous is not None:
                        client.decoding = replace(previous, seed=case["sampling_seed"])
                    journal_type = JournalClient
                    if frozen.get("source_schedule") == "fast240":
                        from tools.campaign_fast import deadline_journal
                        journal_type = deadline_journal(frozen)
                    journal = journal_type(client, out / "calls" / case["key"])
                    try:
                        trace = execute_deletion_case(case, journal, frozen)
                    finally:
                        if previous is not None:
                            client.decoding = previous
                    if not journal.all_calls_consumed():
                        raise ValueError("deletion diagnostic has orphaned model calls")
                    record = {"key": case["key"], "case_sha256": digest(case),
                              "freeze_sha256": sha(out / "freeze.json"), "trace": trace,
                              "journal": journal_summary(out / "calls" / case["key"]),
                              "recorded_utc": utc()}
                    save_record(path, record)
                    new += 1
                records.append(record)
                if (record["case_sha256"] != digest(case) or record["freeze_sha256"] != sha(out / "freeze.json")
                        or record["journal"] != journal_summary(out / "calls" / case["key"])):
                    raise ValueError("deletion case or journal identity changed")
                if record["journal"]["invocations"] != len(record["trace"]["model_calls"]):
                    raise ValueError("deletion trace omits journaled invocation")
                for i, call in enumerate(record["trace"]["model_calls"]):
                    campaign.validate_call(call, frozen, case["sampling_seed"])
                    if read(out / "calls" / case["key"] / f"{i:03d}.json") != {"state": "recorded", "calls": [call]}:
                        raise ValueError("deletion raw model receipt differs")
                if (record["trace"]["status"] in {"runtime_failure", "resource_stop"}
                        or receipt_cost([record])["total_tokens"] is None):
                    if len(episode_files) > len(records):
                        raise ValueError("deletion records continue after an interrupted case")
                    stopped.append({"key": case["key"], "status": record["trace"]["status"],
                                    "error": record["trace"].get("error"), "full_episode_replayed": False})
                    break  # Retain the attempt; never replace it or run later cases.
                if replay:
                    model = RecordedClient(record["trace"]["model_calls"])
                    actual = execute_deletion_case(case, model, frozen)
                    if (model.index != len(model.calls)
                            or canonical(campaign.semantic(actual)) != canonical(campaign.semantic(record["trace"]))):
                        raise ValueError("relation-deletion transcript replay differs")
                    replayed += 1
        finally:
            summary = deletion_report(records, frozen, journal_cost(out))
            if not replay:
                save(out / "summary.json", summary)
        if replay:
            if read(out / "summary.json") != summary:
                raise ValueError("relation-deletion report differs from receipts")
            result = {"consistent": summary["physical_diagnostic_cost"]["unknown_usage_calls"] == 0,
                      "complete": summary["complete"], "cases_replayed": replayed,
                      "recorded_cases": len(records), "stopped_cases": stopped,
                      "model_calls_made": 0, "freeze_sha256": sha(out / "freeze.json"),
                      "summary_sha256": sha(out / "summary.json"),
                      "records_sha256": campaign.artifact_digest(out / "episodes"),
                      "journals_sha256": campaign.artifact_digest(out / "calls")}
            save(out / "audit.json", result)
            return result
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--kind", choices=("development", "diagnostic"), required=True)
    p.add_argument("--runtime-config", type=Path, default=ROOT / "configs/campaign_runtime.json")
    p.add_argument("--runtime-receipt", type=Path, required=True)
    p.add_argument("--key-file", type=Path, required=True)
    p = sub.add_parser("deletion-freeze")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--source-study", type=Path, required=True)
    p.add_argument("--source-schedule", choices=("campaign", "fast240"), default="campaign")
    for command in ("deletion-run", "deletion-resume", "deletion-audit"):
        p = sub.add_parser(command)
        p.add_argument("--out", type=Path, required=True)
        if command != "deletion-audit":
            p.add_argument("--key-file", type=Path, required=True)
            p.add_argument("--max-new-records", type=int)
    for command in ("run", "resume", "audit", "report"):
        p = sub.add_parser(command)
        p.add_argument("--out", type=Path, required=True)
        if command in {"run", "resume"}:
            p.add_argument("--key-file", type=Path, required=True)
            p.add_argument("--max-new-records", type=int)
    args = parser.parse_args()
    if args.command == "deletion-freeze":
        result = freeze_deletion(args.out, args.source_study, source_schedule=args.source_schedule)
    elif args.command in {"deletion-run", "deletion-resume"}:
        from witness_cl.model_campaign import build_client
        frozen, _ = verify_deletion_freeze(args.out)
        result = run_deletion(args.out, build_client(frozen["runtime_config"], args.key_file),
                              max_new_records=args.max_new_records)
    elif args.command == "deletion-audit":
        result = run_deletion(args.out, None, replay=True)
    elif args.command == "freeze":
        from witness_cl.model_campaign import build_client
        config = read(args.runtime_config)
        client = build_client(config, args.key_file)
        result = freeze(args.out, kind=args.kind, runtime_config=config,
                        runtime_receipt=read(args.runtime_receipt), client_config=client.snapshot_config())
        result = {k: result[k] for k in ("experiment", "kind", "seeds", "planned_records")}
    elif args.command in {"run", "resume"}:
        from witness_cl.model_campaign import build_client
        frozen = verify_freeze(args.out)
        result = run(args.out, build_client(frozen["runtime_config"], args.key_file),
                     max_new_records=args.max_new_records)
    elif args.command == "audit":
        result = audit(args.out)
    else:
        frozen = verify_freeze(args.out)
        result = summarize(load_records(args.out, frozen), frozen, physical_cost=journal_cost(args.out))
    print(canonical(result))


if __name__ == "__main__":
    main()
