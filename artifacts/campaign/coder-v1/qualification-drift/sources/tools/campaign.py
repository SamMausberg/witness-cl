#!/usr/bin/env python3
"""Frozen, resumable independent-stream campaign; no favorable-outcome stopping."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from experiments.delayed_sql import execute_episode
from witness_cl.ace_memory import ACEMemory
from witness_cl.campaign_env import make_episode, schedule
from witness_cl.campaign_io import (
    JournalClient, RecordedClient, canonical, journal_usage, read, save, sha, study_lock, usage,
)
from witness_cl.delayed_memory import DelayedMemory
from witness_cl.model_v8 import InferenceBudget
from witness_cl.query_memory import QueryMemory

ARMS = ("full_history", "ace", "delayed", "immediate", "view_text", "sql_archive")
KINDS = ("qualification", "development", "sizing", "confirmation", "diagnostic")


def utc():
    return datetime.now(timezone.utc).isoformat()


def artifact_digest(directory):
    directory = Path(directory)
    hashes = {str(path.relative_to(directory)): sha(path)
              for path in sorted(directory.rglob("*.json"))}
    return hashlib.sha256(canonical(hashes).encode()).hexdigest()


def source_inventory():
    paths = set((ROOT / "src/witness_cl").rglob("*.py"))
    paths.update((ROOT / "src/witness_cl/_vendor").rglob("*.json"))
    paths.update((ROOT / "src/witness_cl/_vendor").rglob("LICENSE*"))
    paths.update(
        (ROOT / p)
        for p in (
            "experiments/delayed_sql.py",
            "tools/campaign.py",
            "tools/audit_campaign_mechanism.py",
            "tools/campaign_results.py",
            "experiments/audit_sql_abstractions_v8.py",
            "experiments/audit_sql_abstractions_v9.py",
            "pyproject.toml",
            "uv.lock",
            "docs/campaign/PLAN.md",
            "docs/campaign/QUALIFICATION.md",
            "docs/campaign/ANALYSIS.md",
            "configs/campaign_sequence.json",
        )
    )
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def environment_fingerprint():
    return {"python": sys.version, "sqlite": sqlite3.sqlite_version,
            "packages": {name: importlib.metadata.version(name)
                         for name in ("sqlglot", "numpy", "scipy")}}


def check_freeze(frozen):
    if source_inventory() != frozen["source_sha256"]:
        raise ValueError(
            "frozen source changed; preserve this study and start a separately versioned one"
        )
    if frozen["environment"] != environment_fingerprint():
        raise ValueError("Python/SQLite/dependency environment differs from the freeze")
    for name, module in tuple(sys.modules.items()):
        if name.startswith(("witness_cl.", "experiments.")) and getattr(module, "__file__", None):
            path = Path(module.__file__).resolve()
            if not path.is_relative_to(ROOT.resolve()):
                raise ValueError("loaded learner/environment module is outside frozen source bundle")
    plan = planned_records(frozen)
    if (len(plan) != frozen["planned_records"] or hashlib.sha256(canonical(plan).encode()).hexdigest()
            != frozen["schedule_sha256"]):
        raise ValueError("prespecified schedule identity changed")


def check_study(out, frozen):
    check_freeze(frozen)
    if read(Path(out) / "schedule.json") != planned_records(frozen):
        raise ValueError("schedule differs from freeze")
    for name, expected in frozen.get("evidence_sha256", {}).items():
        if sha(Path(out) / "evidence" / name) != expected:
            raise ValueError("bound prerequisite evidence changed")


def _require_frozen_execution(out, frozen):
    if not frozen["contains_test_double_calls"] and ROOT.resolve() != (Path(out) / "sources").resolve():
        raise ValueError("real studies must execute their immutable sources/tools/campaign.py")


def runtime_identity(frozen, *, proc_root=Path("/proc")):
    """Bind the live local process to the frozen model bytes and backend once."""
    receipt, cfg = frozen["runtime_receipt"], frozen["runtime_config"]
    if receipt.get("status") != "running" or receipt.get("config") != cfg:
        raise ValueError("runtime receipt does not bind the frozen configuration")
    process = Path(proc_root) / str(receipt["pid"])
    command = [word.decode() for word in (process / "cmdline").read_bytes().split(b"\0") if word]
    if command != receipt["command"]:
        raise ValueError("live serving process command differs from frozen runtime")

    def file_hash(path):
        with Path(path).open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()

    executable = Path(command[0]).resolve()
    backend = executable.parents[2]
    if (file_hash(process / "exe") != receipt["backend"]["binary_sha256"]
            or file_hash(executable) != receipt["backend"]["binary_sha256"]):
        raise ValueError("live server binary differs from frozen backend")
    commit = subprocess.check_output(["git", "-C", str(backend), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(backend), "status", "--porcelain"], text=True).strip()
    libraries = {str(path.relative_to(backend)): file_hash(path)
                 for path in sorted((backend / "build/bin").glob("*.so*"))
                 if path.is_file() and not path.is_symlink()}
    if (dirty or commit != cfg["backend"]["commit"] or commit != receipt["backend"]["commit"]
            or libraries != receipt["backend"]["shared_libraries_sha256"]
            or file_hash(backend / "convert_hf_to_gguf.py") != receipt["backend"]["converter_sha256"]):
        raise ValueError("backend checkout, converter or shared libraries differ from freeze")
    if command.count("--model") != 1:
        raise ValueError("exactly one serving model path required")
    model = Path(command[command.index("--model") + 1]).resolve()
    conversion_path = model.parent.parent / "conversion.json"
    conversion = read(conversion_path)
    if (model.name != cfg["model"]["filename"] or conversion.get("status") != "verified"
            or conversion.get("model") != cfg["model"]
            or conversion.get("backend") != receipt["backend"]
            or conversion.get("output_sha256") != receipt["model_sha256"]
            or file_hash(conversion_path) != receipt["conversion_receipt_sha256"]
            or file_hash(model) != receipt["model_sha256"]):
        raise ValueError("serving model bytes or conversion provenance differ from freeze")
    expected = {"--alias": cfg["model"]["alias"], "--host": cfg["server"]["host"],
                "--port": str(cfg["server"]["port"]),
                "--ctx-size": str(cfg["server"]["context_tokens"]),
                "--parallel": str(cfg["server"]["parallel_sequences"]),
                "--cache-type-k": cfg["server"]["kv_cache_dtype"],
                "--cache-type-v": cfg["server"]["kv_cache_dtype"],
                "--rope-scaling": cfg["server"]["rope_scaling"]}
    if any(command.count(key) != 1 or command[command.index(key) + 1] != value
           for key, value in expected.items()) or "--no-context-shift" not in command:
        raise ValueError("live server context/endpoint policy differs from freeze")
    return {"pid": receipt["pid"], "command_sha256": hashlib.sha256(canonical(command).encode()).hexdigest(),
            "model_sha256": receipt["model_sha256"], "backend": receipt["backend"],
            "conversion_sha256": receipt["conversion_receipt_sha256"], "checked_utc": utc()}


def _learner_identity(frozen):
    # Analysis/report/runner additions need not invalidate a previously qualified
    # learner. Every solver, memory, compiler, environment and inference module
    # that can affect its interactions does.
    excluded = {"src/witness_cl/campaign_analysis.py", "src/witness_cl/campaign_io.py"}
    return {name: value for name, value in frozen["source_sha256"].items()
            if (name.startswith("src/witness_cl/") and name not in excluded)
            or name == "experiments/delayed_sql.py"}


def _study_evidence(path, *, kinds, client_config, learner_hashes, model_identity=None):
    directory = Path(path)
    if directory.is_file():
        directory = directory.parent
    files = {name: directory / name for name in ("freeze.json", "summary.json", "audit.json")}
    frozen, summary, audited = (read(files[name]) for name in files)
    if (frozen["kind"] not in kinds or frozen.get("contains_test_double_calls") is not False
            or summary.get("complete") is not True or audited.get("consistent") is not True
            or audited.get("complete") is not True
            or audited.get("freeze_sha256") != sha(files["freeze.json"])
            or audited.get("summary_sha256") != sha(files["summary.json"])
            or audited.get("records_sha256") != artifact_digest(directory / "episodes")
            or audited.get("journals_sha256") != artifact_digest(directory / "calls")
            or summary.get("cost", {}).get("unknown_usage_calls") != 0
            or audited.get("cost", {}).get("unknown_usage_calls") != 0):
        raise ValueError("complete real audited prerequisite study with known costs required")
    if frozen["client_config"] != client_config or _learner_identity(frozen) != learner_hashes:
        raise ValueError("prerequisite model/decoding or learner source identity differs")
    if model_identity is not None and model_identity != {
            "runtime_config": frozen["runtime_config"],
            "model_sha256": frozen["runtime_receipt"].get("model_sha256")}:
        raise ValueError("prerequisite model bytes or runtime configuration differs")
    if summarize(load_records(directory), frozen) != summary:
        raise ValueError("prerequisite summary differs from complete raw episode records")
    return directory, frozen, summary, audited, files


def _prerequisites(*, kind, seeds, conditions, client_config, source_hashes,
                   qualification_report=None, power_report=None, development_report=None,
                   model_identity=None):
    evidence, input_files, observed_seeds = {}, {}, set()
    if kind not in {"development", "sizing", "confirmation"}:
        return evidence, input_files
    if qualification_report is None:
        raise ValueError("an audited successful qualification report is required")
    paths = qualification_report if isinstance(qualification_report, (list, tuple)) else [qualification_report]
    learner = _learner_identity({"source_sha256": source_hashes})
    covered = set()
    evidence["qualification"] = []
    for ordinal, path in enumerate(paths):
        _, frozen, summary, _, files = _study_evidence(
            path, kinds={"qualification"}, client_config=client_config, learner_hashes=learner,
            model_identity=model_identity)
        if summary.get("qualified") is not True or len(frozen["seeds"]) < 2:
            raise ValueError("every required qualification cell must pass on two independent streams")
        covered.update(frozen["conditions"])
        if set(frozen["seeds"]) & observed_seeds:
            raise ValueError("qualification streams must be independent across conditions")
        observed_seeds.update(frozen["seeds"])
        evidence["qualification"].append({"seeds": frozen["seeds"], "conditions": frozen["conditions"],
                                         "sha256": {name: sha(p) for name, p in files.items()}})
        input_files.update({f"qualification-{ordinal}/{name}": p for name, p in files.items()})
    if not set(conditions) <= covered:
        raise ValueError("qualification must cover each proposed stream condition")
    if kind == "confirmation":
        if power_report is None or development_report is None:
            raise ValueError("confirmation requires a bound sizing power report and mechanism readiness report")
        directory, frozen, _, _, files = _study_evidence(
            power_report, kinds={"sizing"}, client_config=client_config, learner_hashes=learner,
            model_identity=model_identity)
        power_path = Path(power_report)
        if power_path.is_dir():
            power_path = directory / "power.json"
        power = read(power_path)
        if (len(frozen["seeds"]) != 32 or frozen["conditions"] != ["reuse"]
                or set(frozen["arms"]) != {"full_history", "ace", "delayed"}
                or frozen["old_replicates"] != 8
                or any(power.get(key) != sha(files[name]) for key, name in (
                    ("freeze_sha256", "freeze.json"), ("summary_sha256", "summary.json"),
                    ("audit_sha256", "audit.json")))
                or power.get("analysis_source_sha256") != source_hashes["src/witness_cl/campaign_analysis.py"]
                or type(power.get("streams")) is not int or power["streams"] != len(seeds)
                or power.get("pilot_n") != 32):
            raise ValueError("confirmation n must equal a power report bound to 32 audited sizing streams")
        simulations = power.get("joint_power_simulations", [])
        last = simulations[-1] if simulations else {}
        if (last.get("streams") != len(seeds) or last.get("trials") != 100000
                or last.get("seed") != 271828
                or type(last.get("one_sided_95_mc_lower")) not in (int, float)
                or not math.isfinite(last["one_sided_95_mc_lower"])
                or not 0.80 < last["one_sided_95_mc_lower"] <= 1):
            raise ValueError("prespecified 100000-trial joint power lower bound must exceed 0.80")
        from tools.campaign_results import stream_metrics
        from witness_cl.campaign_analysis import joint_power_simulation, size_study

        _, rows = stream_metrics(directory)
        planned_power = size_study(rows)
        if (any(power.get(key) != value for key, value in planned_power.items() if key != "streams")
                or power["streams"] < planned_power["streams"]):
            raise ValueError("power report differs from the prespecified sizing calculation")
        expected_n = planned_power["streams"]
        for ordinal, simulation in enumerate(simulations):
            if (simulation.get("streams") != expected_n or simulation.get("trials") != 100000
                    or simulation.get("seed") != 271828
                    or (ordinal < len(simulations) - 1 and simulation.get("one_sided_95_mc_lower", 1) > 0.80)):
                raise ValueError("power simulation schedule differs from the fixed expansion rule")
            if simulation != joint_power_simulation(rows, expected_n):
                raise ValueError("joint power report differs from deterministic simulation replay")
            expected_n += max(1, (expected_n + 19) // 20)
        if set(frozen["seeds"]) & observed_seeds:
            raise ValueError("sizing streams overlap qualification streams")
        observed_seeds.update(frozen["seeds"])
        evidence["sizing"] = {"seeds": frozen["seeds"], "streams": power["streams"],
                              "sha256": {**{name: sha(p) for name, p in files.items()},
                                         "power.json": sha(power_path)}}
        input_files.update({f"sizing/{name}": p for name, p in files.items()})
        input_files["sizing/power.json"] = power_path
        directory, frozen, _, _, files = _study_evidence(
            development_report, kinds={"development"}, client_config=client_config, learner_hashes=learner,
            model_identity=model_identity)
        mechanism_path = directory / "audit-mechanism.json"
        mechanism = read(mechanism_path)
        events = [event for event in mechanism.get("events", []) if event.get("qualifying_event") is True]
        if (mechanism.get("consistent") is not True or len(events) < 5
                or len({event["seed"] for event in events}) < 3
                or any(event.get("arm") != "delayed" or event.get("test_double_calls") != 0
                       or event.get("unknown_usage_calls") != 0 or event["seed"] not in frozen["seeds"]
                       for event in events)):
            raise ValueError("readiness requires five real delayed mechanism events over three development streams")
        # Recompute the independent census from the exact audited episode prefix;
        # a manually edited readiness count is not evidence.
        from tools.audit_campaign_mechanism import audit_records

        replayed = audit_records(load_records(directory))
        expected_events = deepcopy(mechanism.get("events", []))
        actual_events = deepcopy(replayed["events"])
        if canonical(semantic(expected_events)) != canonical(semantic(actual_events)):
            raise ValueError("mechanism readiness report differs from independent replay")
        if set(frozen["seeds"]) & observed_seeds:
            raise ValueError("development streams overlap qualification or sizing streams")
        observed_seeds.update(frozen["seeds"])
        evidence["development"] = {"seeds": frozen["seeds"],
                                   "sha256": {**{name: sha(p) for name, p in files.items()},
                                              "audit-mechanism.json": sha(mechanism_path)}}
        input_files.update({f"development/{name}": p for name, p in files.items()})
        input_files["development/audit-mechanism.json"] = mechanism_path
    if set(seeds) & observed_seeds:
        raise ValueError("proposed seeds overlap already observed prerequisite streams")
    return evidence, input_files


def memory_for(arm, snapshot=None):
    cls = (
        ACEMemory
        if arm == "ace"
        else DelayedMemory
        if arm in {"delayed", "immediate", "view_text"}
        else QueryMemory
    )
    if snapshot is not None:
        return cls.from_snapshot(snapshot)
    return cls() if arm == "ace" else cls(arm)


def sampling_seed(seed, phase, index):
    cohort = "old" if phase in {"old_before", "old_after"} else phase
    return int.from_bytes(
        hashlib.sha256(canonical([seed, cohort, index]).encode()).digest()[:4], "big"
    )


def record_key(seed, condition, phase, index, arm):
    return f"{seed}-{condition}-{phase}-{index:03d}-{arm}"


def planned_records(frozen):
    records = []
    for seed in frozen["seeds"]:
        for condition in frozen["conditions"]:
            for position, (phase, index) in enumerate(
                schedule(
                    old_replicates=frozen["old_replicates"],
                    stage="qualification" if frozen["kind"] == "qualification" else "complete",
                )
            ):
                offset = (seed + position) % len(frozen["arms"])
                arms = frozen["arms"][offset:] + frozen["arms"][:offset]
                records.extend(
                    dict(
                        seed=seed,
                        condition=condition,
                        phase=phase,
                        index=index,
                        arm=arm,
                        key=record_key(seed, condition, phase, index, arm),
                    )
                    for arm in arms
                )
    return records


def freeze(
    out,
    *,
    kind,
    seeds,
    arms,
    conditions,
    runtime_config,
    runtime_receipt,
    client_config,
    old_replicates=8,
    allow_test_double=False,
    qualification_report=None,
    power_report=None,
    development_report=None,
):
    out = Path(out)
    if out.exists():
        raise ValueError("study output exists; freeze never overwrites evidence")
    if kind not in KINDS or not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("study kind and distinct seeds required")
    if any(type(s) is not int or not 0 <= s < 2**63 for s in seeds):
        raise ValueError("nonnegative integer seeds required")
    if not arms or len(set(arms)) != len(arms) or set(arms) - set(ARMS):
        raise ValueError("distinct supported arms required")
    if (not conditions or len(set(conditions)) != len(conditions)
            or set(conditions) - {"reuse", "drift", "nonreuse"}):
        raise ValueError("supported conditions required")
    if type(old_replicates) is not int or old_replicates < 1 or type(allow_test_double) is not bool:
        raise ValueError("positive old-panel count and explicit test-double Boolean required")
    if kind == "qualification" and len(conditions) != 1:
        raise ValueError("freeze each qualification condition as a separate complete study")
    if kind == "confirmation" and (
        len(seeds) < 48
        or set(arms) != {"full_history", "ace", "delayed"}
        or conditions != ["reuse"]
        or old_replicates != 8
    ):
        raise ValueError(
            "confirmation requires primary arms, reuse, 64 old probes and at least48 streams"
        )
    if kind == "sizing" and len(seeds) != 32:
        raise ValueError("sizing requires32 independent streams")
    if not allow_test_double:
        if (
            runtime_receipt.get("status") != "running"
            or runtime_receipt.get("config") != runtime_config
        ):
            raise ValueError("running pinned runtime receipt required")
        if not runtime_receipt.get("model_sha256"):
            raise ValueError("runtime must bind converted model bytes")
        from witness_cl.model_campaign import DecodingCampaign

        DecodingCampaign(**client_config["decoding"])
        if (client_config["model"] != runtime_config["model"]["alias"]
                or client_config["decoding"] != runtime_config["decoding"]
                or client_config["context_tokens"] != runtime_config["server"]["context_tokens"]
                or client_config["endpoint"] != "http://{host}:{port}".format(**runtime_config["server"])
                or client_config["response_mode"] != "schema" or client_config["max_output"] != 4096):
            raise ValueError("client policy must exactly match the pinned runtime and fixed interface")
    hashes = source_inventory()
    evidence, evidence_files = ({}, {}) if allow_test_double else _prerequisites(
        kind=kind, seeds=seeds, conditions=conditions, client_config=client_config, source_hashes=hashes,
        qualification_report=qualification_report, power_report=power_report,
        development_report=development_report,
        model_identity={"runtime_config": runtime_config,
                        "model_sha256": runtime_receipt.get("model_sha256")})
    evidence_hashes = {name: sha(path) for name, path in evidence_files.items()}
    split = {
        "qualification": "development",
        "development": "development",
        "sizing": "sizing",
        "confirmation": "confirmation",
        "diagnostic": "diagnostic",
    }[kind]
    frozen = {
        "schema_version": 1,
        "kind": kind,
        "created_utc": utc(),
        "split": split,
        "seeds": seeds,
        "arms": arms,
        "conditions": conditions,
        "old_replicates": old_replicates,
        "cold_start_each_episode": kind == "qualification",
        "source_sha256": hashes,
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "runtime_config": deepcopy(runtime_config),
        "runtime_receipt": deepcopy(runtime_receipt),
        "client_config": deepcopy(client_config),
        "contains_test_double_calls": allow_test_double,
        "limits": {
            "solve_output_tokens": 4096,
            "max_model_calls_per_episode": 7,
            "max_selects_per_episode": 8,
            "max_solve_actions": 5,
        },
        "sampling_seed_policy": "sha256([stream_seed,old_or_phase,index]) first4 bytes unsignedbigendian",
        "qualification_gate": {
            "warm": 7,
            "binding": 6,
            "new_outer": 6,
            "future": 6,
            "family_n": 8,
            "all_scheduled_records_required": True,
        },
        "analysis": {
            "alpha_per_endpoint": 0.01,
            "retention_margin": 0.02,
            "token_ratio": 0.8,
            "endpoint_power": 0.96,
            "sd_floor": 0.10,
            "unit": "independent_stream",
        },
        "stopping": "complete fixed schedule; stop only source/runtime/integrity or unknown usage",
        "wall_deadline_seconds": None,
        "environment": environment_fingerprint(),
        "prerequisites": evidence,
        "evidence_sha256": evidence_hashes,
    }
    plan = planned_records(frozen)
    frozen["planned_records"] = len(plan)
    frozen["schedule_sha256"] = hashlib.sha256(canonical(plan).encode()).hexdigest()
    # Evaluator hashes only: no target SQL or expected answer goes to the solver.
    fixtures = {}
    for r in plan:
        key = record_key(r["seed"], r["condition"], r["phase"], r["index"], "fixture")
        if key not in fixtures:
            spec = make_episode(
                r["seed"],
                split,
                r["condition"],
                r["phase"],
                r["index"],
                old_replicates=old_replicates,
            )
            fixtures[key] = dict(spec._metadata)["data_sha256"]
    frozen["fixtures_sha256"] = hashlib.sha256(canonical(fixtures).encode()).hexdigest()
    out.mkdir(parents=True)
    for name, expected in frozen["source_sha256"].items():
        destination = out / "sources" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
        if sha(destination) != expected:
            raise ValueError("source changed while preparing immutable study snapshot")
    for name, path in evidence_files.items():
        destination = out / "evidence" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        if sha(destination) != evidence_hashes[name]:
            raise ValueError("prerequisite evidence changed during freeze")
    save(out / "freeze.json", frozen)
    save(out / "schedule.json", plan)
    return frozen


def budget_for(frozen):
    limits = frozen["limits"]
    return InferenceBudget(
        max_total_tokens=limits["max_model_calls_per_episode"]
        * frozen["client_config"].get("context_tokens", 65536),
        max_calls=limits["max_model_calls_per_episode"],
    )


def semantic(value):
    excluded = {"elapsed_seconds", "setup_seconds", "query_seconds", "vm_steps"}
    if isinstance(value, dict):
        timing_owner = {"queries", "model_calls", "before_memory_digest"} <= value.keys()
        timing_owner |= value.get("kind") in {"empty_relation", "measure_override"}
        return {k: semantic(v) for k, v in value.items() if not (timing_owner and k in excluded)}
    if isinstance(value, (list, tuple)):
        return [semantic(v) for v in value]
    return value


def validate_call(call, frozen, expected_seed):
    """Compare measured requests with the exact frozen generation policy."""
    cost = usage([call])
    if call.get("attempt_uncertain"):
        if cost["unknown_usage_calls"] != 1:
            raise ValueError("uncertain invocation cannot have known token totals")
        return cost
    if frozen["contains_test_double_calls"]:
        if call.get("test_double") is not True:
            raise ValueError("unmarked response in scripted software test")
        return cost
    if call.get("test_double"):
        raise ValueError("scripted response in real campaign")
    cfg = frozen["client_config"]
    decoding = {**cfg["decoding"], "seed": expected_seed}
    if call.get("decoding") != decoding:
        raise ValueError("decoding receipt differs from frozen policy")
    request = call.get("request_config", {})
    for key, value in decoding.items():
        if key != "thinking" and request.get(key) != value:
            raise ValueError("wire decoding differs from freeze: " + key)
    if request.get("chat_template_kwargs") != {"enable_thinking": decoding["thinking"]}:
        raise ValueError("wire thinking policy differs from freeze")
    if request.get("model") != cfg["model"] or request.get("max_tokens") != 4096:
        raise ValueError("model or output allowance differs from freeze")
    if cost["known_total_tokens"] > cfg["context_tokens"]:
        raise ValueError("recorded usage exceeds frozen context")
    if call.get("usage") is not None and call["usage"]["completion_tokens"] > 4096:
        raise ValueError("recorded completion exceeds frozen allowance")
    from witness_cl.model_v9_compatible import portable_schema, WIRE_SCHEMA_POLICY

    if call.get("wire_schema_policy") != WIRE_SCHEMA_POLICY:
        raise ValueError("unrecognized schema transport policy")
    host = call.get("host_response_schema")
    if call.get("response_schema") != portable_schema(host):
        raise ValueError("wire schema differs from host schema adaptation")
    expected_request = {
        "model": cfg["model"], **{key: value for key, value in decoding.items() if key != "thinking"},
        "max_tokens": 4096, "cache_prompt": False, "stream": False,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": decoding["thinking"]},
    }
    if host is not None:
        expected_request["response_format"]["schema"] = portable_schema(host)
    if request != expected_request or call.get("max_output_tokens") != 4096:
        raise ValueError("effective wire request or output reservation differs from freeze")
    if call.get("response_mode") != "schema":
        raise ValueError("model response mode differs from freeze")
    if call.get("usage") is not None:
        preflight = call.get("preflight_tokens")
        if (type(preflight) is not int or preflight < 0
                or preflight + 4096 > cfg["context_tokens"]
                or call["usage"]["prompt_tokens"] < preflight
                or call.get("response_model") != cfg["model"]):
            raise ValueError("response identity or preflight accounting differs from freeze")
    return cost


def episode_identity(item):
    """Arm-shared opacity and paired old-panel randomness, derived from schedule."""
    seed, phase, index = (item[key] for key in ("seed", "phase", "index"))
    return {
        "sampling_seed": sampling_seed(seed, phase, index),
        "episode_nonce": hashlib.sha256(canonical([seed, phase, index]).encode()).hexdigest()[:24],
        "episode_index": index if phase == "ordinary" else (8 if phase == "old_before" else 24),
    }


def validate_record(out, frozen, item, record, before):
    """Verify schedule, raw receipts and exact offline transition before reuse."""
    identity = episode_identity(item)
    if (any(record.get(key) != item[key] for key in item)
            or record.get("freeze_sha256") != sha(Path(out) / "freeze.json")
            or record.get("sampling_seed") != identity["sampling_seed"]):
        raise ValueError("episode schedule, freeze or derived sampling seed mismatch")
    if canonical(record.get("before_snapshot")) != canonical(before):
        raise ValueError("checkpoint memory chain mismatch")
    expected = record["trace"]
    if (expected.get("episode_nonce") != identity["episode_nonce"]
            or expected.get("episode_index") != identity["episode_index"]):
        raise ValueError("derived opaque episode identity mismatch")
    calls = expected["model_calls"]
    if len(calls) > frozen["limits"]["max_model_calls_per_episode"]:
        raise ValueError("model invocation allowance exceeded")
    directory = Path(out) / "calls" / item["key"]
    if {p.name for p in directory.glob("*.json")} != {f"{i:03d}.json" for i in range(len(calls))}:
        raise ValueError("missing or orphaned raw model receipt")
    for i, call in enumerate(calls):
        validate_call(call, frozen, identity["sampling_seed"])
        if read(directory / f"{i:03d}.json") != {"state": "recorded", "calls": [call]}:
            raise ValueError("raw call journal differs from episode")
    if usage(calls)["unknown_usage_calls"]:
        raise ValueError("unknown usage retained; campaign cannot resume past it")
    if expected["status"] in {"resource_stop", "runtime_failure"}:
        raise ValueError("failed episode retained; automatic replacement prohibited")
    memory = memory_for(item["arm"], before)
    replay = RecordedClient(calls)
    spec = make_episode(item["seed"], frozen["split"], item["condition"], item["phase"],
                        item["index"], old_replicates=frozen["old_replicates"])
    trace = execute_episode(
        spec, memory, replay, budget_for(frozen), phase=item["phase"],
        learn=item["phase"] == "ordinary" and not frozen["cold_start_each_episode"],
        episode_nonce=identity["episode_nonce"], episode_index=identity["episode_index"],
        solve_output_tokens=frozen["limits"]["solve_output_tokens"])
    if replay.index != len(calls) or canonical(semantic(trace)) != canonical(semantic(expected)):
        raise ValueError("episode or memory transition differs under offline transcript replay: " + item["key"])
    return memory


def run(out, client, *, max_new_records=None):
    with study_lock(out):
        return _run(out, client, max_new_records=max_new_records)


def _run(out, client, *, max_new_records=None):
    out = Path(out)
    frozen = read(out / "freeze.json")
    _require_frozen_execution(out, frozen)
    check_study(out, frozen)
    load_records(out)  # Reject holes and unplanned episode files before generation.
    if max_new_records is not None and (type(max_new_records) is not int or max_new_records < 0):
        raise ValueError("checkpoint size must be a nonnegative integer")
    if not frozen["contains_test_double_calls"]:
        if (
            not hasattr(client, "snapshot_config")
            or client.snapshot_config() != frozen["client_config"]
        ):
            raise ValueError("actual client differs from freeze")
    serving = None if frozen["contains_test_double_calls"] else runtime_identity(frozen)
    plan = planned_records(frozen)
    if read(out / "schedule.json") != plan:
        raise ValueError("schedule differs fromfreeze")
    records = []
    memories = {}
    new = 0
    started = time.monotonic()
    manifest = {
        "kind": frozen["kind"],
        "status": "running",
        "freeze_sha256": sha(out / "freeze.json"),
        "planned_records": len(plan),
        "started_utc": utc(),
        "completed_records": 0,
        "contains_test_double_calls": frozen["contains_test_double_calls"],
        "runtime_identity": serving,
    }
    save(out / "manifest.json", manifest)
    try:
        for item in plan:
            seed, condition, phase, index, arm = (
                item[k] for k in ("seed", "condition", "phase", "index", "arm")
            )
            path = out / "episodes" / (item["key"] + ".json")
            group = (seed, condition, arm)
            memory = memories.setdefault(group, memory_for(arm))
            cold = frozen["cold_start_each_episode"]
            if cold:
                memory = memory_for(arm)
            before = memory.snapshot()
            if path.exists():
                record = read(path)
                validate_record(out, frozen, item, record, before)
            else:
                if max_new_records is not None and new >= max_new_records:
                    manifest["status"] = "checkpointed"
                    break
                check_study(out, frozen)
                spec = make_episode(
                    seed,
                    frozen["split"],
                    condition,
                    phase,
                    index,
                    old_replicates=frozen["old_replicates"],
                )
                identity = episode_identity(item)
                sample_seed = identity["sampling_seed"]
                original_decoding = getattr(client, "decoding", None)
                if original_decoding is not None:
                    client.decoding = replace(original_decoding, seed=sample_seed)
                journal = JournalClient(client, out / "calls" / item["key"])
                active = memory_for(arm, before)
                try:
                    trace = execute_episode(
                        spec,
                        active,
                        journal,
                        budget_for(frozen),
                        phase=phase,
                        learn=phase == "ordinary" and not cold,
                        episode_nonce=identity["episode_nonce"],
                        episode_index=identity["episode_index"],
                        solve_output_tokens=frozen["limits"]["solve_output_tokens"],
                    )
                finally:
                    if original_decoding is not None:
                        client.decoding = original_decoding
                if not journal.all_calls_consumed():
                    raise ValueError("orphaned call receipt during recovery")
                record = {
                    **item,
                    "freeze_sha256": sha(out / "freeze.json"),
                    "before_snapshot": before,
                    "sampling_seed": sample_seed,
                    "trace": trace,
                    "recorded_utc": utc(),
                }
                save(path, record)
                new += 1
            records.append(record)
            manifest["completed_records"] = len(records)
            costs = usage(record["trace"]["model_calls"])
            for call in record["trace"]["model_calls"]:
                validate_call(call, frozen, record["sampling_seed"])
            if costs["unknown_usage_calls"]:
                manifest["status"] = "unknown_usage"
                break
            if record["trace"]["status"] in {"resource_stop", "runtime_failure"}:
                manifest["status"] = "runtime_failure"
                break
            if phase == "ordinary" and not cold:
                memories[group] = memory_for(arm, record["trace"]["memory"])
            save(out / "manifest.json", manifest)
        else:
            manifest["status"] = "completed"
        manifest["source_unchanged"] = all(
            sha(ROOT / p) == v for p, v in frozen["source_sha256"].items()
        )
    except BaseException as exc:
        manifest.update(
            status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
            error_type=type(exc).__name__,
            error=str(exc)[:1000],
        )
        raise
    finally:
        manifest.update(
            finished_utc=utc(),
            invocation_seconds=time.monotonic() - started,
            cost=journal_usage(out / "calls"),
            checkpoint_cost=usage([call for r in records for call in r["trace"]["model_calls"]]),
        )
        save(out / "manifest.json", manifest)
        save(out / "summary.json", summarize(records, frozen))
    return manifest


def load_records(out):
    out = Path(out)
    frozen = read(out / "freeze.json")
    plan = planned_records(frozen)
    names = {r["key"] + ".json" for r in plan}
    if {p.name for p in (out / "episodes").glob("*.json")} - names:
        raise ValueError("unplanned episode file")
    records, gap = [], False
    for item in plan:
        path = out / "episodes" / (item["key"] + ".json")
        if not path.exists():
            gap = True
        elif gap:
            raise ValueError("episode files are not a contiguous prespecified schedule prefix")
        else:
            record = read(path)
            if any(record.get(key) != value for key, value in item.items()):
                raise ValueError("episode file differs from its prespecified schedule key")
            records.append(record)
    # One interrupted next episode may have durable model calls without a
    # checkpoint. Calls for a later episode would skip the declared schedule.
    allowed = {r["key"] for r in plan[:len(records) + 1]}
    call_dirs = {p.name for p in (out / "calls").iterdir() if p.is_dir()} if (out / "calls").exists() else set()
    if call_dirs - allowed:
        raise ValueError("model journal skips the prespecified schedule")
    return records


def summarize(records, frozen):
    groups = []
    for seed in frozen["seeds"]:
        for condition in frozen["conditions"]:
            for arm in frozen["arms"]:
                selected = [
                    r
                    for r in records
                    if (r["seed"], r["condition"], r["arm"]) == (seed, condition, arm)
                ]
                row = {
                    "seed": seed,
                    "condition": condition,
                    "arm": arm,
                    "records": len(selected),
                    "cost": usage([c for r in selected for c in r["trace"]["model_calls"]]),
                }
                row["phases"] = {
                    p: {
                        "n": len(items := [r for r in selected if r["phase"] == p]),
                        "correct": sum(r["trace"]["reward"] == 1.0 for r in items),
                    }
                    for p in ("ordinary", "old_before", "old_after", "final")
                }
                groups.append(row)
    cells = []
    if frozen["kind"] == "qualification":
        for seed in frozen["seeds"]:
            for arm in frozen["arms"]:
                for family, phase, start in (
                    ("warm", "ordinary", 0),
                    ("binding", "ordinary", 8),
                    ("new_outer", "ordinary", 16),
                    ("future", "final", 0),
                ):
                    selected = [
                        r
                        for r in records
                        if r["seed"] == seed
                        and r["arm"] == arm
                        and r["phase"] == phase
                        and start <= r["index"] < start + 8
                    ]
                    correct = sum(r["trace"]["reward"] == 1.0 for r in selected)
                    cells.append(
                        {
                            "seed": seed,
                            "arm": arm,
                            "family": family,
                            "n": len(selected),
                            "correct": correct,
                            "minimum": frozen["qualification_gate"][family],
                            "pass": len(selected) == 8
                            and correct >= frozen["qualification_gate"][family],
                        }
                    )
    complete = len(records) == frozen["planned_records"]
    costs = usage([c for r in records for c in r["trace"]["model_calls"]])
    return {
        "kind": frozen["kind"],
        "complete": complete,
        "groups": groups,
        "cost": costs,
        "qualification_cells": cells,
        "qualified": bool(cells)
        and complete
        and all(c["pass"] for c in cells)
        and costs["unknown_usage_calls"] == 0,
        "confirmatory": frozen["kind"] == "confirmation"
        and not frozen["contains_test_double_calls"],
        "claim_confirmed": False,
    }


def audit(out):
    with study_lock(out):
        return _audit(out)


def _audit(out):
    out = Path(out)
    frozen = read(out / "freeze.json")
    _require_frozen_execution(out, frozen)
    check_study(out, frozen)
    records = load_records(out)
    memories = {}
    queries = 0
    for item, record in zip(planned_records(frozen), records, strict=False):
        key = (item["seed"], item["condition"], item["arm"])
        memory = memories.setdefault(key, memory_for(item["arm"]))
        if frozen["cold_start_each_episode"]:
            memory = memory_for(item["arm"])
        memory = validate_record(out, frozen, item, record, memory.snapshot())
        if item["phase"] == "ordinary" and not frozen["cold_start_each_episode"]:
            memories[key] = memory
        queries += len(record["trace"]["queries"])
    summary = summarize(records, frozen)
    if read(out / "summary.json") != summary:
        raise ValueError("summary differs from raw records")
    cost = journal_usage(out / "calls")
    if len(records) == frozen["planned_records"] and cost != summary["cost"]:
        raise ValueError("completed study has unaccounted physical model calls")
    result = {
        "consistent": True,
        "records_replayed": len(records),
        "sql_replayed": queries,
        "complete": len(records) == frozen["planned_records"],
        "network_calls": 0,
        "freeze_sha256": sha(out / "freeze.json"),
        "summary_sha256": sha(out / "summary.json"),
        "records_sha256": artifact_digest(out / "episodes"),
        "journals_sha256": artifact_digest(out / "calls"),
        "cost": cost,
        "claim_confirmed": False,
    }
    save(out / "audit.json", result)
    return result


def mechanism(out):
    with study_lock(out):
        audited = _audit(out)
        if not audited["complete"]:
            raise ValueError("mechanism census requires the complete prespecified study")
        from tools.audit_campaign_mechanism import audit_records

        result = audit_records(load_records(out))
        result.update(freeze_sha256=sha(Path(out) / "freeze.json"),
                      summary_sha256=sha(Path(out) / "summary.json"),
                      audit_sha256=sha(Path(out) / "audit.json"),
                      records_sha256=audited["records_sha256"],
                      journals_sha256=audited["journals_sha256"])
        save(Path(out) / "audit-mechanism.json", result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--seeds", type=int, nargs="+", required=True)
    p.add_argument("--arms", nargs="+", choices=ARMS, default=["full_history", "ace", "delayed"])
    p.add_argument("--conditions", nargs="+", default=["reuse"])
    p.add_argument("--runtime-config", type=Path, default=ROOT / "configs/campaign_runtime.json")
    p.add_argument("--runtime-receipt", type=Path, required=True)
    p.add_argument("--key-file", type=Path, required=True)
    p.add_argument("--qualification-report", type=Path, nargs="+")
    p.add_argument("--power-report", type=Path)
    p.add_argument("--development-report", type=Path)
    for command in ("run", "resume", "audit", "report", "mechanism"):
        p = sub.add_parser(command)
        p.add_argument("--out", type=Path, required=True)
        if command in ("run", "resume"):
            p.add_argument("--key-file", type=Path, required=True)
            p.add_argument("--max-new-records", type=int)
    args = parser.parse_args()
    if args.command != "freeze":
        # Select the immutable program before constructing a client. The working
        # checkout may continue to change while either frozen study runs.
        script = args.out.resolve() / "sources/tools/campaign.py"
        if Path(__file__).resolve() != script:
            os.execv(sys.executable, [sys.executable, str(script), *sys.argv[1:]])
    if args.command == "freeze":
        from witness_cl.model_campaign import build_client

        config = read(args.runtime_config)
        client = build_client(config, args.key_file)
        result = freeze(
            args.out,
            kind=args.kind,
            seeds=args.seeds,
            arms=args.arms,
            conditions=args.conditions,
            runtime_config=config,
            runtime_receipt=read(args.runtime_receipt),
            client_config=client.snapshot_config(),
            qualification_report=args.qualification_report,
            power_report=args.power_report,
            development_report=args.development_report,
        )
        print(canonical({k: result[k] for k in ("kind", "planned_records", "seeds")}))
    elif args.command in ("run", "resume"):
        from witness_cl.model_campaign import build_client

        frozen = read(args.out / "freeze.json")
        result = run(
            args.out,
            build_client(frozen["runtime_config"], args.key_file),
            max_new_records=args.max_new_records,
        )
        print(canonical(result))
    elif args.command == "audit":
        print(canonical(audit(args.out)))
    elif args.command == "mechanism":
        print(canonical(mechanism(args.out)))
    else:
        frozen = read(args.out / "freeze.json")
        check_study(args.out, frozen)
        print(canonical(summarize(load_records(args.out), frozen)))


if __name__ == "__main__":
    main()
