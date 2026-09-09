#!/usr/bin/env python3
"""One frozen, cold-start development qualification; no learning or model retry."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from experiments import stateful_sql as study
from tools.replay_study import RecordedClient, semantic, validate_call
from witness_cl.evidence_memory import EvidenceMemory
from witness_cl.model_v8 import BudgetStop, InferenceBudget
from witness_cl.model_v9 import DecodingV9
from witness_cl.model_v9_compatible import LocalInferenceV9Compatible
from witness_cl.sql_env_v9 import make_stream, open_episode

SEEDS = (95100, 95101)
LIMITS = {
    "wall_seconds": 2700,
    "total_tokens": 750000,
    "total_calls": 384,
    "solve_output_tokens": 2048,
    "reflection_output_tokens": 2048,
}
DECODING = asdict(DecodingV9(temperature=0.7, top_p=0.8, thinking=False))
CONFIG = ROOT / "configs/query_transfer_runtime.json"
SOURCES = (
    *study.SOURCE_FILES,
    "tools/qualify_sql_solver.py",
    "tools/replay_study.py",
    "tools/gh200_runtime.py",
    "configs/query_transfer_runtime.json",
    "docs/research/SOLVER_QUALIFICATION.md",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    return {name: sha(ROOT / name) for name in SOURCES}


def save(path, value):
    study.write_json(Path(path), value)


def utc():
    return datetime.now(timezone.utc).isoformat()


def client_config(config):
    s = config["server"]
    return {
        "endpoint": f"http://{s['host']}:{s['port']}",
        "model": config["model"]["alias"],
        "context_tokens": s["context_tokens"],
        "max_output": 2048,
        "timeout": 120.0,
        "response_mode": "schema",
        "decoding": DECODING,
    }


def snapshot_client(client):
    return {
        **{
            k: getattr(client, k)
            for k in client_config(json.loads(CONFIG.read_text()))
            if k != "decoding"
        },
        "decoding": asdict(client.decoding),
    }


def create_freeze(out, runtime_receipt):
    out = Path(out)
    if out.exists():
        raise ValueError("qualification output already exists; no overwrite or retry")
    config = json.loads(CONFIG.read_text())
    runtime = json.loads(Path(runtime_receipt).read_text())
    if (
        runtime["status"] != "running"
        or runtime["config"] != config
        or runtime["model_sha256"] != config["model"]["sha256"]
        or runtime["backend_commit"] != config["backend"]["commit"]
    ):
        raise ValueError("runtime receipt does not bind the configured running backend")
    result = {
        "kind": "cold_sql_qualification_freeze",
        "created_utc": utc(),
        "source_sha256": sources(),
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "system_prompt": study.V9_SYSTEM,
        "seeds": list(SEEDS),
        "indices": list(range(16)),
        "condition": "reuse",
        "split": "development",
        "learn": False,
        "cold_start_each_episode": True,
        "limits": LIMITS,
        "client_config": client_config(config),
        "runtime_config": config,
        "runtime_startup_receipt": runtime,
        "runtime_receipt_sha256": sha(runtime_receipt),
        "gate": {"warm_minimum": 7, "composition_minimum": 6, "per_family_n": 8},
    }
    out.mkdir(parents=True)
    save(out / "freeze.json", result)
    return result


def check_freeze(frozen):
    if (
        frozen["source_sha256"] != sources()
        or frozen["system_prompt"] != study.V9_SYSTEM
        or frozen["seeds"] != list(SEEDS)
        or frozen["indices"] != list(range(16))
        or frozen["limits"] != LIMITS
        or frozen["client_config"] != client_config(json.loads(CONFIG.read_text()))
        or frozen["runtime_config"] != json.loads(CONFIG.read_text())
        or frozen["gate"] != {"warm_minimum": 7, "composition_minimum": 6, "per_family_n": 8}
        or frozen["learn"] is not False
        or frozen["cold_start_each_episode"] is not True
    ):
        raise ValueError("qualification freeze differs from current sources or protocol")


def summary(rows):
    groups = []
    for seed in SEEDS:
        for name, start, minimum in (("warm", 0, 7), ("composition", 8, 6)):
            selected = [
                r for r in rows if r["seed"] == seed and start <= r["episode_index"] < start + 8
            ]
            correct = sum(r["reward"] == 1 for r in selected)
            groups.append(
                {
                    "seed": seed,
                    "family": name,
                    "n": len(selected),
                    "correct": correct,
                    "minimum_correct": minimum,
                    "complete": len(selected) == 8,
                    "meets_accuracy_gate": len(selected) == 8 and correct >= minimum,
                }
            )
    return groups


def accounting(rows):
    result = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "unknown_usage_calls": 0,
        "tokenization_seconds": 0.0,
        "inference_seconds": 0.0,
    }
    for r in rows:
        for call in r["model_calls"]:
            for key in ("tokenization_seconds", "inference_seconds"):
                result[key] += call.get(key, 0.0)
            if call["generation_attempted"]:
                result["calls"] += 1
                if call.get("usage") is None:
                    result["unknown_usage_calls"] += 1
                else:
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        result[key] += call["usage"][key]
    return result


def run(out, client, *, allow_test_double=False):
    out = Path(out)
    frozen = json.loads((out / "freeze.json").read_text())
    check_freeze(frozen)
    if (out / "manifest.json").exists() or (out / "episodes.jsonl").exists():
        raise ValueError("qualification was already attempted")
    simulated = not isinstance(client, LocalInferenceV9Compatible)
    if simulated and not allow_test_double:
        raise ValueError("native client required")
    if not simulated and snapshot_client(client) != frozen["client_config"]:
        raise ValueError("client differs from freeze")
    started, started_unix = time.monotonic(), time.time()
    budget = InferenceBudget(
        max_total_tokens=LIMITS["total_tokens"],
        max_calls=LIMITS["total_calls"],
        deadline=started + LIMITS["wall_seconds"],
    )
    manifest = {
        "kind": "cold_sql_backbone_qualification",
        "status": "running",
        "started_unix": started_unix,
        "freeze_sha256": sha(out / "freeze.json"),
        "contains_test_double_calls": simulated,
        "planned_records": 32,
    }
    save(out / "manifest.json", manifest)
    rows = []
    try:
        with (out / "episodes.jsonl").open("x") as raw:
            for seed in SEEDS:
                stream = make_stream(seed, "reuse", split="development")
                for index, spec in enumerate(stream.ordinary[:16]):
                    check_freeze(frozen)
                    if not simulated and snapshot_client(client) != frozen["client_config"]:
                        raise RuntimeError("client configuration changed")
                    budget.check(0, LIMITS["solve_output_tokens"])
                    memory = EvidenceMemory("full_history", frozen["system_prompt"])
                    trace = study.execute_episode(
                        spec,
                        memory,
                        client,
                        budget,
                        phase="ordinary",
                        learn=False,
                        solve_output_tokens=2048,
                        reflection_output_tokens=2048,
                    )
                    trace.update(
                        seed=seed,
                        arm="full_history",
                        condition="reuse",
                        episode_index=index,
                        qualification_family="warm" if index < 8 else "composition",
                    )
                    rows.append(trace)
                    raw.write(json.dumps(trace, allow_nan=False) + "\n")
                    raw.flush()
                    print(
                        json.dumps(
                            {
                                "seed": seed,
                                "episode": index,
                                "status": trace["status"],
                                "reward": trace["reward"],
                                "calls": budget.calls,
                                "known_tokens": budget.total_tokens,
                                "seconds": round(time.monotonic() - started, 2),
                            }
                        ),
                        flush=True,
                    )
                    if (
                        trace["status"] in ("resource_stop", "backend_or_runtime_failure")
                        or budget.unknown_usage_calls
                    ):
                        raise BudgetStop(trace.get("stop_reason", trace["status"]))
        manifest["status"] = "completed"
    except BaseException as exc:
        manifest.update(
            status="stopped", failure={"type": type(exc).__name__, "reason": str(exc)[:256]}
        )
    finally:
        groups = summary(rows)
        save(out / "summary.json", groups)
        manifest.update(
            finished_utc=utc(),
            saved_records=len(rows),
            budget=budget.to_dict(),
            source_sha256_after=sources(),
            client_config_after=snapshot_client(client) if not simulated else None,
            raw_sha256=sha(out / "episodes.jsonl"),
            summary_sha256=sha(out / "summary.json"),
            elapsed_seconds=time.monotonic() - started,
        )
        complete = (
            len(rows) == 32
            and budget.unknown_usage_calls == 0
            and manifest["status"] == "completed"
            and manifest["source_sha256_after"] == frozen["source_sha256"]
            and (simulated or manifest["client_config_after"] == frozen["client_config"])
            and manifest["elapsed_seconds"] <= LIMITS["wall_seconds"]
        )
        manifest.update(
            required_records_complete=complete,
            qualified=complete and not simulated and all(g["meets_accuracy_gate"] for g in groups),
            unknown_token_count=None if budget.unknown_usage_calls else 0,
            cost_scope="all qualification calls; startup excluded; unknown tokens excluded",
        )
        if not complete:
            manifest["status"] = "stopped"
        save(out / "manifest.json", manifest)
    return manifest


def audit(out):
    out = Path(out)
    frozen = json.loads((out / "freeze.json").read_text())
    manifest = json.loads((out / "manifest.json").read_text())
    check_freeze(frozen)
    if (
        manifest["status"] == "running"
        or manifest["freeze_sha256"] != sha(out / "freeze.json")
        or manifest["raw_sha256"] != sha(out / "episodes.jsonl")
        or manifest["summary_sha256"] != sha(out / "summary.json")
        or manifest["source_sha256_after"] != frozen["source_sha256"]
        or datetime.fromisoformat(frozen["created_utc"]).timestamp() > manifest["started_unix"]
    ):
        raise ValueError("run integrity, timing or freeze mismatch")
    if (
        type(manifest["elapsed_seconds"]) not in (int, float)
        or not math.isfinite(manifest["elapsed_seconds"])
        or manifest["elapsed_seconds"] < 0
        or (
            not manifest["contains_test_double_calls"]
            and manifest["client_config_after"] != frozen["client_config"]
        )
    ):
        raise ValueError("elapsed time or final client configuration mismatch")
    rows = [json.loads(s) for s in (out / "episodes.jsonl").read_text().splitlines()]
    expected = [(seed, i) for seed in SEEDS for i in range(16)]
    if [(r["seed"], r["episode_index"]) for r in rows] != expected[: len(rows)] or len(rows) > 32:
        raise ValueError("qualification schedule differs from freeze")
    groups = summary(rows)
    if json.loads((out / "summary.json").read_text()) != groups:
        raise ValueError("group summary does not match raw observations")
    cost = accounting(rows)
    for key, value in cost.items():
        if abs(manifest["budget"][key] - value) > 1e-7:
            raise ValueError("raw call accounting differs from manifest: " + key)
    if manifest["saved_records"] != len(rows):
        raise ValueError("incorrect saved record count")
    if cost["total_tokens"] > LIMITS["total_tokens"] or cost["calls"] > LIMITS["total_calls"]:
        raise ValueError("declared resource cap exceeded")
    simulated = any(c.get("test_double") is True for r in rows for c in r["model_calls"])
    if simulated != manifest["contains_test_double_calls"]:
        raise ValueError("test fixture marker mismatch")
    native_manifest = {
        "client_config": frozen["client_config"],
        "limits": LIMITS,
        "contains_test_double_calls": simulated,
    }
    if simulated:
        native_manifest["client_config"] = {
            **frozen["client_config"],
            "model": "explicit-offline-test-double",
        }
    replayed, sql_count, partial = 0, 0, []
    for trace in rows:
        for call in trace["model_calls"]:
            validate_call(call, trace, native_manifest)
        memory = EvidenceMemory("full_history", frozen["system_prompt"])
        if (
            trace["learn"] is not False
            or trace["before_memory_digest"] != memory.digest()
            or trace["after_memory_digest"] != memory.digest()
            or trace["memory_snapshot"] != memory.snapshot()
        ):
            raise ValueError("qualification episode retained or mutated state")
        spec = make_stream(trace["seed"], "reuse").ordinary[trace["episode_index"]]
        with open_episode(spec, allow_learning_checks=False) as session:
            for query in trace["queries"]:
                if query["learning_check"] is not False:
                    raise ValueError("qualification unexpectedly used learning checks")
                actual = asdict(session.query(query["sql"], query["params"], learning_check=False))
                if semantic(actual) != semantic({k: query[k] for k in actual}):
                    raise ValueError("independent SQL replay mismatch")
                sql_count += 1
            if session.answer(trace["answer"]).reward != trace["reward"]:
                raise ValueError("independent reward mismatch")
        if all(c["status"] == "completed" for c in trace["model_calls"]):
            client = RecordedClient(trace["model_calls"], max_output=2048)
            repeated = study.execute_episode(
                spec,
                memory,
                client,
                InferenceBudget(),
                phase="ordinary",
                learn=False,
                reflection_output_tokens=2048,
            )
            if client.errors or client.index != len(trace["model_calls"]):
                raise ValueError("model call replay mismatch")
            for key in ("actions", "answer", "reward", "queries", "status", "evaluator"):
                if semantic(repeated[key]) != semantic(trace[key]):
                    raise ValueError("same-runner replay mismatch: " + key)
            replayed += 1
        else:
            partial.append([trace["seed"], trace["episode_index"]])
    complete = (
        len(rows) == 32
        and cost["unknown_usage_calls"] == 0
        and not partial
        and manifest["status"] == "completed"
        and manifest["elapsed_seconds"] <= LIMITS["wall_seconds"]
    )
    if manifest["required_records_complete"] != complete:
        raise ValueError("completeness claim differs from raw observations")
    qualified = complete and not simulated and all(g["meets_accuracy_gate"] for g in groups)
    if manifest["qualified"] != qualified:
        raise ValueError("qualification claim differs from frozen gate")
    return {
        "kind": "independent_sql_and_same_runner_replay",
        "network_calls": 0,
        "records": len(rows),
        "records_replayed": replayed,
        "partial_records": partial,
        "sql_replayed": sql_count,
        "groups": groups,
        "cost": cost,
        "qualified": qualified,
        "population_claim": False,
        "auditor_sha256": sha(__file__),
        "freeze_sha256": manifest["freeze_sha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run", "audit"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runtime-receipt", type=Path)
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        if args.runtime_receipt is None:
            parser.error("freeze requires --runtime-receipt")
        result = create_freeze(args.out, args.runtime_receipt)
        print(
            json.dumps(
                {
                    "freeze_sha256": sha(args.out / "freeze.json"),
                    "created_utc": result["created_utc"],
                }
            )
        )
    elif args.action == "run":
        if args.key_file is None:
            parser.error("run requires --key-file")
        frozen = json.loads((args.out / "freeze.json").read_text())
        check_freeze(frozen)
        cfg = dict(frozen["client_config"])
        cfg["decoding"] = DecodingV9(**cfg["decoding"])
        result = run(args.out, LocalInferenceV9Compatible(key_file=args.key_file, **cfg))
        print(json.dumps(result))
    else:
        result = audit(args.out)
        save(args.out / "audit.json", result)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
