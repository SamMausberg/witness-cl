#!/usr/bin/env python3
"""Freeze and execute the unchanged native CL-Bench default database schedule.

No model call occurs in fetch/freeze/audit/report. Resume starts only untouched
runs after completed runs; a partially executed native run is never retried.
Completed runs can be audited by replaying every recorded model response against
fresh native task state, without a model endpoint or hidden-input injection.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.request import Request, build_opener, ProxyHandler, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from witness_cl.campaign_io import JournalClient, RecordedClient, read, save, study_lock, usage
from witness_cl.model_campaign import build_client
from witness_cl.model_v8 import InferenceBudget
from witness_cl.query_memory import canonical, digest
from integrations.clbench.ace import LocalClientTransport, make_ace
from integrations.clbench.native import UPSTREAM_COMMIT, inspect_pin, load_native, make_bridge
from integrations.clbench.witness import make_witness

DATASET = "continual-learning-bench/database-exploration"
REVISION = "a0cc57eeb9a54f01c0490a1b46cb705b4e05aa19"
ASSETS = {
    "products.db": {"bytes": 397910016, "sha256": "edf8ee80ff125de0bfd6c37a1d185efa9e3037ce28eb1bd1d32ae0829bd264a6"},
    "products_drifted.db": {"bytes": 432148480, "sha256": "a53d523f70604be0e4328f3722417895250ac35e1127cc504b609576aee70fad"},
}
ARMS = ("full_history", "ace", "witness_stateful", "witness_stateless")
DEFAULT_ASSETS = Path.home() / ".local/share/witness-cl/native-datasets" / REVISION
DEFAULT_RUNTIME = Path.home() / ".local/share/witness-cl/campaign"
DEFAULT_OUTPUT = ROOT / "artifacts/campaign/native"


def utc():
    return datetime.now(timezone.utc).isoformat()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        while block := source.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


@contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def planned_runs():
    jobs = []
    for index in range(5):
        # Fixed rotation counterbalances execution order; no result selects a job.
        order = ARMS[index % len(ARMS):] + ARMS[:index % len(ARMS)]
        for arm in order:
            jobs.append({"key": f"permutation-{index:02d}-{arm}", "run_index": index, "arm": arm})
    return jobs


def verify_assets(directory):
    directory = Path(directory).resolve()
    result = {}
    for name, expected in ASSETS.items():
        path = directory / name
        if not path.is_file() or path.stat().st_size != expected["bytes"]:
            raise ValueError("missing or wrong-size official asset: " + name)
        actual = file_sha(path)
        if actual != expected["sha256"]:
            raise ValueError("official asset hash mismatch: " + name)
        result[name] = {"path": str(path), **expected}
    return result


def fetch_assets(directory):
    directory = Path(directory).resolve()
    if directory.is_relative_to(ROOT):
        raise ValueError("native database assets must stay outside the repository")
    directory.mkdir(parents=True, exist_ok=True)
    for name, expected in ASSETS.items():
        path = directory / name
        if path.exists():
            if path.stat().st_size != expected["bytes"] or file_sha(path) != expected["sha256"]:
                raise ValueError("existing asset differs; refusing overwrite: " + name)
            continue
        part = path.with_suffix(".db.part")
        url = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{name}"
        start = part.stat().st_size if part.exists() else 0
        if start > expected["bytes"]:
            raise ValueError("partial download exceeds expected asset size")
        if start < expected["bytes"]:
            request = Request(url, headers={"Range": f"bytes={start}-"} if start else {})
            with urlopen(request, timeout=60) as response:
                if start and (response.status != 206 or response.headers.get("Content-Range") !=
                              f"bytes {start}-{expected['bytes'] - 1}/{expected['bytes']}"):
                    raise RuntimeError("asset server did not honor exact resume range")
                with part.open("ab") as target:
                    while block := response.read(8 * 1024 * 1024):
                        if target.tell() + len(block) > expected["bytes"]:
                            raise ValueError("download exceeds expected size")
                        target.write(block)
                    target.flush()
                    os.fsync(target.fileno())
        if part.stat().st_size != expected["bytes"] or file_sha(part) != expected["sha256"]:
            raise ValueError("downloaded asset failed exact hash check")
        part.replace(path)
        print(json.dumps({"event": "official_native_asset_verified", "name": name, **expected}), flush=True)
    result = {"dataset": DATASET, "revision": REVISION, "assets": verify_assets(directory)}
    save(directory / "receipt.json", result)
    return result


def attach_assets(upstream, directory):
    assets = verify_assets(directory)
    target = Path(upstream) / "data/database_exploration"
    for name, entry in assets.items():
        path = target / name
        if path.exists() or path.is_symlink():
            if not path.is_file() or file_sha(path) != entry["sha256"]:
                raise ValueError("upstream asset path already contains different data")
        else:
            path.symlink_to(entry["path"])
    return assets


def source_manifest():
    paths = list((ROOT / "src/witness_cl").rglob("*.py"))
    paths += list((ROOT / "integrations/clbench").glob("*.py"))
    paths += [Path(__file__), ROOT / "tools/campaign_runtime.py", ROOT / "docs/campaign/NATIVE_PROTOCOL.md",
              ROOT / "src/witness_cl/_vendor/ace/PROVENANCE.json",
              ROOT / "src/witness_cl/_vendor/ace/LICENSE.txt"]
    return {str(path.relative_to(ROOT)): file_sha(path) for path in sorted(paths)}


def upstream_manifest(upstream):
    upstream = Path(upstream)
    inspect_pin(upstream)
    paths = list((upstream / "src").rglob("*.py"))
    paths += list((upstream / "src/tasks/database_exploration").rglob("*.json"))
    paths += [upstream / "data/database_exploration/questions.json",
              upstream / "data/database_exploration/questions_post_drift.json"]
    return {str(path.relative_to(upstream)): file_sha(path) for path in sorted(paths)}


def dependency_versions():
    return {name: importlib.metadata.version(name) for name in
            ("numpy", "sqlglot", "pydantic", "litellm", "openai")}


def freeze(output, upstream, assets, runtime_config, *, runtime_cache=DEFAULT_RUNTIME,
           runtime_receipt=None, key_file=None):
    output, upstream = Path(output).resolve(), Path(upstream).resolve()
    if (output / "freeze.json").exists() or (output / "runs").exists():
        raise ValueError("native freeze/output already exists; never overwrite a prior campaign")
    api = load_native(upstream)
    asset_receipts = attach_assets(upstream, assets)
    pre = read(upstream / "data/database_exploration/questions.json")
    post = read(upstream / "data/database_exploration/questions_post_drift.json")
    orders = {}
    for index in range(5):
        sequence = api.database._build_schema_drift_question_sequence(
            pre_questions=pre, post_questions=post, pre_drift_count=20, post_drift_count=20,
            seed=42, run_index=index)
        orders[str(index)] = [row["question_id"] for row in sequence]
    cfg = read(runtime_config)
    runtime_receipt = ROOT / "artifacts/campaign/runtime/server.json" if runtime_receipt is None else Path(runtime_receipt)
    key_file = Path(runtime_cache) / "runtime/server.key" if key_file is None else Path(key_file)
    health = runtime_health({"runtime_config": cfg}, runtime_cache, runtime_receipt, key_file)
    client_config = build_client(cfg, key_file).snapshot_config()
    protocol = {
        "schema_version": 1, "created_utc": utc(), "purpose": "native_external_domain_evaluation",
        "upstream": str(upstream), "upstream_commit": UPSTREAM_COMMIT,
        "upstream_files": upstream_manifest(upstream), "sources": source_manifest(),
        "dataset": DATASET, "dataset_revision": REVISION, "assets": asset_receipts,
        "runtime_config": cfg, "runtime_config_sha256": digest(cfg),
        "runtime_environment": health, "client_config": client_config,
        "contains_test_double_calls": False,
        "python": sys.version, "dependencies": dependency_versions(),
        "task": {"name": "database_exploration", "schedule": "default", "variant": "schema_drift",
                 "seed": 42, "runs": 5, "questions_per_run": 40, "query_budget": 15,
                 "mode": "permute", "default_schedule_unmodified": True},
        "arms": list(ARMS), "jobs": planned_runs(), "question_orders": orders,
        "limits": {"output_tokens": 4096, "model_calls_per_run": 2000,
                   "model_tokens_per_run": 150_000_000, "client_timeout_seconds": 180.0,
                   "run_deadline": None, "context_tokens": cfg["server"]["context_tokens"]},
        "icl": {"reserve_tokens": 5120, "history_policy": "unchanged_upstream_fifo_and_token_calibration"},
        "resume_policy": "completed_runs_only; partial_runs_retained_incomplete_never_retried",
        "scoring": "unchanged native reward and accuracy; paired stateful-minus-stateless Witness gain",
        "sampling_boundary": "five permutations of fixed databases, not independent new-database samples",
    }
    for name, expected in protocol["sources"].items():
        target = output / "sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        if file_sha(target) != expected:
            raise ValueError("native source changed during immutable copy")
    save(output / "freeze.json", protocol)
    save(output / "freeze.sha256.json", {"sha256": file_sha(output / "freeze.json")})
    return {"status": "frozen_before_generation", "jobs": len(protocol["jobs"]),
            "questions": 800, "freeze": str(output / "freeze.json")}


def verify_freeze(output):
    output = Path(output)
    protocol = read(output / "freeze.json")
    if file_sha(output / "freeze.json") != read(output / "freeze.sha256.json")["sha256"]:
        raise ValueError("native protocol freeze changed")
    if source_manifest() != protocol["sources"]:
        raise ValueError("native campaign source changed after freeze")
    if upstream_manifest(protocol["upstream"]) != protocol["upstream_files"]:
        raise ValueError("native upstream source/data questions changed")
    if sys.version != protocol["python"] or dependency_versions() != protocol["dependencies"]:
        raise ValueError("native runtime Python/dependency versions changed")
    for entry in protocol["assets"].values():
        path = Path(entry["path"])
        if path.stat().st_size != entry["bytes"] or file_sha(path) != entry["sha256"]:
            raise ValueError("frozen native database asset changed")
    return protocol


def runtime_health(protocol, runtime_cache, runtime_receipt, key_file):
    cfg = protocol["runtime_config"]
    conversion = read(Path(runtime_cache) / "conversion.json")
    receipt = read(runtime_receipt)
    if conversion.get("status") != "verified" or receipt.get("config") != cfg:
        raise ValueError("runtime conversion/configuration does not match native freeze")
    if (receipt.get("status") != "running" or receipt.get("model_sha256") != conversion.get("output_sha256")
            or receipt.get("conversion_receipt_sha256") != file_sha(Path(runtime_cache) / "conversion.json")):
        raise ValueError("runtime server/conversion provenance mismatch")
    os.kill(receipt["pid"], 0)
    cmdline = Path(f"/proc/{receipt['pid']}/cmdline").read_bytes().split(b"\x00")
    model_path = Path(runtime_cache) / "models" / cfg["model"]["filename"]
    actual_command = [word.decode() for word in cmdline if word]
    from tools.campaign_runtime import backend_identity
    backend = Path(actual_command[0]).resolve().parents[2]
    identity = backend_identity(cfg, backend)
    if (actual_command != receipt["command"] or identity != receipt["backend"]
            or file_sha(Path(f"/proc/{receipt['pid']}/exe")) != identity["binary_sha256"]
            or conversion.get("backend") != identity or conversion.get("model") != cfg["model"]):
        raise ValueError("native backend binary, libraries, command or conversion differ from frozen runtime")
    if str(model_path).encode() not in cmdline or file_sha(model_path) != receipt["model_sha256"]:
        raise ValueError("serving process/model bytes differ from runtime provenance")
    opener = build_opener(ProxyHandler({}))
    base = f"http://{cfg['server']['host']}:{cfg['server']['port']}"
    headers = {"Authorization": "Bearer " + Path(key_file).read_text().strip()}
    with opener.open(Request(base + "/health", headers=headers), timeout=10) as response:
        health = json.load(response)
    with opener.open(Request(base + "/v1/models", headers=headers), timeout=10) as response:
        models = json.load(response)
    if health.get("status") != "ok" or cfg["model"]["alias"] not in {
            row.get("id") for row in models.get("data", [])}:
        raise ValueError("native runtime endpoint is not healthy with the frozen model alias")
    return {"model_sha256": receipt["model_sha256"], "config_sha256": digest(cfg),
            "conversion_sha256": file_sha(Path(runtime_cache) / "conversion.json"),
            "backend": receipt["backend"], "health_status": health["status"],
            "model_ids": sorted(row["id"] for row in models["data"])}


def journal_calls(directory):
    paths = sorted(Path(directory).glob("*.json"), key=lambda path: int(path.stem))
    if [int(path.stem) for path in paths] != list(range(len(paths))):
        raise ValueError("native model-call journal has gaps")
    calls = []
    for path in paths:
        item = read(path)
        if item.get("state") != "recorded" or len(item.get("calls", [])) != 1:
            raise ValueError("uncertain native invocation retained; replay prohibited")
        call = item["calls"][0]
        if call.get("status") != "completed" or call.get("usage") is None:
            raise ValueError("failed native invocation cannot be replayed or retried")
        calls.append(call)
    if usage(calls)["unknown_usage_calls"]:
        raise ValueError("native journal contains unknown usage")
    return calls


def validate_calls(calls, protocol):
    from witness_cl.model_v9_compatible import WIRE_SCHEMA_POLICY, portable_schema
    cfg = protocol["client_config"]
    if protocol.get("contains_test_double_calls") is not False:
        raise ValueError("native real-model protocol requires explicit test-double exclusion")
    for call in calls:
        if call.get("test_double") or call.get("status") != "completed" or call.get("usage") is None:
            raise ValueError("native test-double, failed or unmeasured model call")
        request = call.get("request_config", {})
        if call.get("decoding") != cfg["decoding"]:
            raise ValueError("native decoding receipt differs from freeze")
        if any(request.get(key) != value for key, value in cfg["decoding"].items() if key != "thinking"):
            raise ValueError("native wire decoding differs from freeze")
        if (request.get("model") != cfg["model"] or request.get("max_tokens") != 4096
                or request.get("chat_template_kwargs") != {"enable_thinking": cfg["decoding"]["thinking"]}
                or call.get("wire_schema_policy") != WIRE_SCHEMA_POLICY
                or call.get("response_schema") != portable_schema(call.get("host_response_schema"))):
            raise ValueError("native request model, schema or allowance differs from freeze")
        cost = usage([call])
        if cost["total_tokens"] > cfg["context_tokens"] or cost["completion_tokens"] > 4096:
            raise ValueError("native usage exceeds frozen context or output allowance")


def partial_journal_usage(directory):
    """Expose known partial costs without converting pending/unknown calls to zero."""
    calls, uncertain = [], 0
    for path in Path(directory).glob("*.json"):
        item = read(path)
        if item.get("state") != "recorded" or not item.get("calls"):
            uncertain += 1
        calls.extend(item.get("calls", []))
    measured = usage(calls)
    measured["uncertain_invocations"] = uncertain
    if uncertain or measured["unknown_usage_calls"]:
        measured["total_tokens"] = None
    return measured


def make_system(api, arm, transport, protocol):
    model = protocol["runtime_config"]["model"]["alias"]
    if arm == "full_history":
        return make_bridge(api, transport=transport, model=model,
                           max_tokens=protocol["limits"]["context_tokens"],
                           reserve_tokens=protocol["icl"]["reserve_tokens"])
    if arm == "ace":
        return make_ace(api, transport=transport, model=model)
    if arm in ("witness_stateful", "witness_stateless"):
        return make_witness(api, transport=transport, model=model)
    raise ValueError("unknown frozen native arm")


def trace_semantics(trace):
    """Ignore timestamps/temp paths, preserving every model-visible action/outcome."""
    return [{"query": row["query"]["prompt"], "instance_id": row["query"]["instance_id"],
             "action": row["response"]["action"], "observation": row["observation"]["content"],
             "done": row["done"]} for row in trace["interactions"]]


def execute_native(protocol, job, client, *, live_trace=None):
    api = load_native(protocol["upstream"])
    limits = protocol["limits"]
    budget = InferenceBudget(max_total_tokens=limits["model_tokens_per_run"],
                             max_calls=limits["model_calls_per_run"])
    client.model = protocol["runtime_config"]["model"]["alias"]
    transport = LocalClientTransport(client, budget, output_tokens=limits["output_tokens"])
    system = make_system(api, job["arm"], transport, protocol)
    trace_module = importlib.import_module(api.interface.__package__ + ".trace_storage")
    params = {"schedule": "default", "run_index": job["run_index"], "rollout_index": job["run_index"]}
    with working_directory(protocol["upstream"]):
        task = api.database.DatabaseExploration(**params)
        recorder = trace_module.TraceRecorder(
            system_name=job["arm"], task_name="database_exploration", system_params={"model": client.model},
            task_params=params, run_group_id="witness-native-frozen", run_index=job["run_index"],
            task_brief=task.get_agent_brief(), live_trace_path=live_trace,
        )
        try:
            result = api.interface.run_task(task, system, trace_recorder=recorder,
                show_progress=False, reset_between_instances=job["arm"] == "witness_stateless")
            trace = recorder.finalize(result)
            outcomes = [asdict(row) for row in result.instance_outcomes]
            ids = [row["instance_id"] for row in outcomes]
            if ids != protocol["question_orders"][str(job["run_index"])]:
                raise ValueError("native result order differs from official frozen permutation")
            return {"status": "completed", "job": job, "metrics": deepcopy(result.metrics),
                "score": result.score, "outcomes": outcomes, "trace": trace,
                "calls": transport.records, "usage": usage(transport.records),
                "system_artifacts": system.get_run_artifacts(), "budget": budget.to_dict()}
        finally:
            # Successful native evaluate closes its temporary DB; failures need cleanup too.
            connection = getattr(task, "_conn", None)
            if connection is not None:
                connection.close()
                task._conn = None
            temporary = getattr(task, "_temp_db_path", None)
            if temporary is not None and temporary.exists():
                temporary.unlink()


def run(output, runtime_cache, runtime_receipt, key_file, *, max_runs=None):
    with study_lock(output):
        return _run(output, runtime_cache, runtime_receipt, key_file, max_runs=max_runs)


def _run(output, runtime_cache, runtime_receipt, key_file, *, max_runs=None):
    output = Path(output).resolve()
    protocol = verify_freeze(output)
    if ROOT.resolve() != (output / "sources").resolve():
        raise ValueError("native generation must run immutable sources/tools/native_campaign.py")
    environment = runtime_health(protocol, runtime_cache, runtime_receipt, key_file)
    if environment != protocol["runtime_environment"]:
        raise ValueError("native runtime differs from pre-generation frozen provenance")
    activation = output / "execution_environment.json"
    if activation.exists() and read(activation) != environment:
        raise ValueError("native execution environment changed after activation")
    if not activation.exists():
        save(activation, environment)
    count = 0
    for job in protocol["jobs"]:
        directory = output / "runs" / job["key"]
        result_path = directory / "result.json"
        if result_path.exists():
            result = read(result_path)
            if result.get("status") != "completed":
                raise ValueError("partial native run retained; automatic retry is prohibited")
            if file_sha(result_path) != read(directory / "result.sha256.json")["sha256"]:
                raise ValueError("completed native result changed")
            continue
        journal = directory / "calls"
        if list(journal.glob("*.json")) or (directory / "started.json").exists():
            raise ValueError("partial native run retained; native resume only starts untouched runs")
        save(directory / "started.json", {"job": job, "started_utc": utc(),
            "freeze_sha256": file_sha(output / "freeze.json")})
        client = build_client(protocol["runtime_config"], key_file,
                              max_output=protocol["limits"]["output_tokens"],
                              timeout=protocol["limits"]["client_timeout_seconds"])
        measured = JournalClient(client, journal)
        print(json.dumps({"event": "native_run_started", **job}), flush=True)
        try:
            result = execute_native(protocol, job, measured, live_trace=directory / "live_trace.json")
            calls = journal_calls(journal)
            validate_calls(calls, protocol)
            if calls != result["calls"]:
                raise ValueError("native in-memory calls differ from durable call journal")
            result["freeze_sha256"] = file_sha(output / "freeze.json")
            result["calls_sha256"] = digest(calls)
            expected_hash = hashlib.sha256((canonical(result) + "\n").encode()).hexdigest()
            save(directory / "result.sha256.json", {"sha256": expected_hash})
            save(result_path, result)
        except BaseException as exc:
            save(directory / "incomplete.json", {"status": "incomplete", "job": job,
                "error_type": type(exc).__name__, "error": str(exc),
                "automatic_retry_prohibited": True})
            raise
        print(json.dumps({"event": "native_run_completed", **job, "score": result["score"],
                          "usage": result["usage"]}), flush=True)
        count += 1
        if max_runs is not None and count >= max_runs:
            break
    return report(output)


def audit(output, *, replay=False):
    with study_lock(output):
        return _audit(output, replay=replay)


def _audit(output, *, replay=False):
    output = Path(output).resolve()
    protocol = verify_freeze(output)
    checks = []
    for job in protocol["jobs"]:
        directory = output / "runs" / job["key"]
        path = directory / "result.json"
        if not path.exists():
            checks.append({"job": job["key"], "status": "incomplete" if (directory / "started.json").exists() else "not_started"})
            continue
        result = read(path)
        if file_sha(path) != read(directory / "result.sha256.json")["sha256"]:
            raise ValueError("native result hash changed")
        calls = journal_calls(directory / "calls")
        validate_calls(calls, protocol)
        if result.get("freeze_sha256") != file_sha(output / "freeze.json") or result.get("job") != job:
            raise ValueError("native result belongs to a different frozen job")
        if calls != result["calls"] or digest(calls) != result["calls_sha256"]:
            raise ValueError("native call journal/result mismatch")
        if usage(calls) != result["usage"] or len(result["outcomes"]) != 40:
            raise ValueError("native usage or completeness mismatch")
        if [row["instance_id"] for row in result["outcomes"]] != protocol["question_orders"][str(job["run_index"])]:
            raise ValueError("native question order mismatch")
        if replay:
            client = RecordedClient(calls)
            replayed = execute_native(protocol, job, client)
            if (client.index != len(calls) or replayed["metrics"] != result["metrics"]
                    or trace_semantics(replayed["trace"]) != trace_semantics(result["trace"])
                    or replayed["system_artifacts"] != result["system_artifacts"]):
                raise ValueError("native replay did not exactly reproduce behavior/state")
        checks.append({"job": job["key"], "status": "passed", "model_free_replay": replay})
    report(output)
    result = {"checks": checks, "all_complete_and_passed": all(row["status"] == "passed" for row in checks),
              "model_free_replay": replay, "model_calls_made": 0,
              "contains_test_double_calls": False, "freeze_sha256": file_sha(output / "freeze.json"),
              "report_sha256": file_sha(output / "report.json"),
              "result_sha256": {job["key"]: file_sha(output / "runs" / job["key"] / "result.json")
                  for job in protocol["jobs"] if (output / "runs" / job["key"] / "result.json").exists()}}
    save(output / "audit.json", result)
    return result


def report(output):
    output = Path(output)
    protocol = read(output / "freeze.json")
    rows = []
    for job in protocol["jobs"]:
        path = output / "runs" / job["key"] / "result.json"
        if path.exists():
            result = read(path)
            if (file_sha(path) != read(path.parent / "result.sha256.json")["sha256"]
                    or result.get("freeze_sha256") != file_sha(output / "freeze.json")
                    or result.get("job") != job or result.get("status") != "completed"):
                raise ValueError("native report input integrity mismatch")
            rows.append({**job, "status": "completed", "reward": result["score"],
                "accuracy": result["metrics"]["accuracy"], "queries": result["metrics"]["total_queries"],
                "compiled_view_queries": sum(event.get("event") in {"native_use", "native_compose"}
                    for event in result["system_artifacts"].get("events", [])),
                "corroborations": sum(event.get("event") == "native_witness_committed"
                    and event.get("state") == "corroborated"
                    for event in result["system_artifacts"].get("events", [])),
                **result["usage"]})
        else:
            directory = path.parent
            started = (directory / "started.json").exists()
            row = {**job, "status": "incomplete" if started else "not_started"}
            if started:
                row.update(partial_journal_usage(directory / "calls"))
            rows.append(row)
    gains = []
    for index in range(5):
        paired = {row["arm"]: row for row in rows if row["run_index"] == index and row["status"] == "completed"}
        if {"witness_stateful", "witness_stateless"} <= paired.keys():
            gains.append({"run_index": index, "reward_gain": paired["witness_stateful"]["reward"] - paired["witness_stateless"]["reward"],
                          "accuracy_gain": paired["witness_stateful"]["accuracy"] - paired["witness_stateless"]["accuracy"]})
    result = {"status": "completed" if all(row["status"] == "completed" for row in rows) else "incomplete",
              "runs": rows, "paired_stateful_gains": gains,
              "native_scores_available": any(row["status"] == "completed" for row in rows),
              "independent_new_database_claim": False}
    save(output / "report.json", result)
    lines = ["# Native CL-Bench DatabaseExploration", "", f"Status: **{result['status']}**. All five default permutations and four arms were frozen before generation.", "",
             "| Run | Arm | Status | Reward | Accuracy | QUERY count | Tokens |", "|---|---|---|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['run_index']} | {row['arm']} | {row['status']} | {row.get('reward', '—')} | {row.get('accuracy', '—')} | {row.get('queries', '—')} | {row.get('total_tokens', '—')} |")
    lines += ["", "Stateful gain is paired Witness stateful minus Witness reset after every question. These runs permute fixed official databases; they are not independent new-database replications.", "",
              "Partial native runs remain incomplete and are never silently retried. All recorded model calls, native traces, failed calls and unknown usage remain in their run directories."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "freeze", "run", "resume", "audit", "report"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--upstream", type=Path, default=Path("/tmp/witness-clbench-native"))
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--runtime-config", type=Path, default=ROOT / "configs/campaign_runtime.json")
    parser.add_argument("--runtime-cache", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--runtime-receipt", type=Path, default=ROOT / "artifacts/campaign/runtime/server.json")
    parser.add_argument("--key-file", type=Path, default=DEFAULT_RUNTIME / "runtime/server.key")
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    if args.max_runs is not None and args.max_runs < 1:
        parser.error("--max-runs must be positive")
    if args.command == "fetch":
        result = fetch_assets(args.assets)
    elif args.command == "freeze":
        result = freeze(args.output, args.upstream, args.assets, args.runtime_config,
                        runtime_cache=args.runtime_cache, runtime_receipt=args.runtime_receipt,
                        key_file=args.key_file)
    elif args.command in ("run", "resume"):
        result = run(args.output, args.runtime_cache, args.runtime_receipt, args.key_file, max_runs=args.max_runs)
    elif args.command == "audit":
        result = audit(args.output, replay=args.replay)
    else:
        result = report(args.output)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
