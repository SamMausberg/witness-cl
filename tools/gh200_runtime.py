#!/usr/bin/env python3
"""Bounded GH200 setup with pinned weights, loopback serving, and receipts.

Python standard library only. No model-generated code is executed. Local model
weights, build tree, and credential stay outside the public repository.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = Path.home() / ".local/share/witness-cl"


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def command(args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=60)
    return {
        "command": args,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def inventory():
    return {
        "timestamp_utc": utc(),
        "architecture": platform.machine(),
        "python": sys.version,
        "platform": platform.platform(),
        "gpu": command(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,driver_version",
                "--format=csv,noheader,nounits",
            ]
        ),
        "gpu_compute": command(["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"]),
        "host_memory": command(["free", "-b"]),
        "numa_memory": {
            p.parent.name: p.read_text()
            for p in sorted(Path("/sys/devices/system/node").glob("node*/meminfo"))
        },
        "numa_cpus": {
            p.parent.name: p.read_text().strip()
            for p in sorted(Path("/sys/devices/system/node").glob("node*/cpulist"))
        },
        "cuda_compiler": command(["nvcc", "--version"]),
        "interpretation": "GPU memory.total is MiB of device memory. Linux MemTotal may include HBM as a memory-only NUMA node; do not add these totals.",
    }


def load_config(path):
    cfg = json.loads(Path(path).read_text())
    server = cfg["server"]
    if server["host"] != "127.0.0.1":
        raise ValueError("server must bind the explicit IPv4 loopback address")
    for key, low, high in [
        ("port", 1024, 65535),
        ("context_tokens", 1024, 131072),
        ("maximum_lifetime_seconds", 1, 14400),
        ("cpu_threads", 1, 64),
    ]:
        if type(server[key]) is not int or not low <= server[key] <= high:
            raise ValueError("invalid finite server limit: " + key)
    if server["parallel_sequences"] != 1:
        raise ValueError("this measured sequential runner requires one server slot")
    model = cfg["model"]
    if (
        len(model["sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in model["sha256"])
        or type(model["bytes"]) is not int
        or not 0 < model["bytes"] <= 100_000_000_000
        or Path(model["filename"]).name != model["filename"]
    ):
        raise ValueError("invalid pinned model descriptor")
    dl = cfg["download"]
    if not (
        type(dl["parallel_requests"]) is int
        and 1 <= dl["parallel_requests"] <= 16
        and type(dl["chunk_bytes"]) is int
        and 1_048_576 <= dl["chunk_bytes"] <= 268_435_456
        and type(dl["deadline_seconds"]) is int
        and 1 <= dl["deadline_seconds"] <= 1800
    ):
        raise ValueError("invalid finite download limits")
    return cfg


def verify_model(cfg, cache):
    path = cache / "models" / cfg["model"]["filename"]
    if path.stat().st_size != cfg["model"]["bytes"]:
        raise ValueError("model byte size differs from publisher record")
    digest = sha256(path)
    if digest != cfg["model"]["sha256"]:
        raise ValueError("model SHA-256 differs from publisher record")
    return path, digest


def download(cfg, cache, receipt_path):
    """Finite parallel HTTP ranges; never accept a partial or wrong hash as weights."""
    model, opts = cfg["model"], cfg["download"]
    dest = cache / "models" / model["filename"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _, digest = verify_model(cfg, cache)
        save(receipt_path, {"timestamp_utc": utc(), "already_present": True, "sha256": digest})
        return
    part = dest.with_suffix(dest.suffix + ".part")
    url = f"https://huggingface.co/{model['repository']}/resolve/{model['revision']}/{model['filename']}"
    started = time.monotonic()
    deadline = started + opts["deadline_seconds"]
    receipt = {
        "started_utc": utc(),
        "url": url,
        "model": model,
        "download": opts,
        "status": "started",
    }
    save(receipt_path, receipt)
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.ftruncate(fd, model["bytes"])
    completed = 0

    def fetch(start, stop):
        if time.monotonic() >= deadline:
            raise TimeoutError("download deadline")
        req = Request(url, headers={"Range": f"bytes={start}-{stop}"})
        with urlopen(req, timeout=min(60.0, max(0.001, deadline - time.monotonic()))) as response:
            expected = f"bytes {start}-{stop}/{model['bytes']}"
            if response.status != 206 or response.headers.get("Content-Range") != expected:
                raise RuntimeError("server did not honor exact HTTP range")
            pos = start
            while pos <= stop:
                if time.monotonic() >= deadline:
                    raise TimeoutError("download deadline")
                chunk = response.read(min(4 * 1024 * 1024, stop - pos + 1))
                if not chunk:
                    raise RuntimeError("incomplete HTTP range")
                written = os.pwrite(fd, chunk, pos)
                if written != len(chunk):
                    raise RuntimeError("short model write")
                pos += written
        return stop - start + 1

    try:
        with ThreadPoolExecutor(max_workers=opts["parallel_requests"]) as pool:
            futures = [
                pool.submit(fetch, start, min(model["bytes"] - 1, start + opts["chunk_bytes"] - 1))
                for start in range(0, model["bytes"], opts["chunk_bytes"])
            ]
            try:
                for future in as_completed(futures):
                    completed += future.result()
                    elapsed = time.monotonic() - started
                    print(
                        json.dumps(
                            {
                                "bytes": completed,
                                "fraction": completed / model["bytes"],
                                "seconds": round(elapsed, 2),
                                "MB_per_second": round(completed / elapsed / 1e6, 2),
                            }
                        ),
                        flush=True,
                    )
            except BaseException:
                for future in futures:
                    future.cancel()
                raise
        os.fsync(fd)
        digest = sha256(part)
        if digest != model["sha256"]:
            raise ValueError("download SHA-256 differs from publisher record")
        part.replace(dest)
        receipt.update(status="verified", sha256=digest, bytes=completed)
    except BaseException as exc:
        receipt.update(status="failed", error_type=type(exc).__name__, bytes_completed=completed)
        raise
    finally:
        os.close(fd)
        receipt.update(finished_utc=utc(), seconds=time.monotonic() - started)
        save(receipt_path, receipt)


def serve(cfg, cache, receipt_path):
    model_path, digest = verify_model(cfg, cache)
    checkout = cache / "llama.cpp"
    commit = command(["git", "-C", str(checkout), "rev-parse", "HEAD"])["stdout"].strip()
    dirty = command(["git", "-C", str(checkout), "status", "--porcelain"])["stdout"].strip()
    if commit != cfg["backend"]["commit"] or dirty:
        raise ValueError("backend checkout is not clean at pinned commit")
    binary = checkout / "build/bin/llama-server"
    # The command line references a file, never the secret value.
    key_path = cache / "runtime/server.key"
    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not key_path.exists():
        key_fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(key_fd, "w") as key:
            key.write(secrets.token_urlsafe(32) + "\n")
    if not key_path.read_text().strip() or key_path.stat().st_mode & 0o077:
        raise ValueError("local server credential must be nonempty and owner-only")
    s = cfg["server"]
    args = [
        str(binary),
        "--model",
        str(model_path),
        "--alias",
        cfg["model"]["alias"],
        "--host",
        s["host"],
        "--port",
        str(s["port"]),
        "--api-key-file",
        str(key_path),
        "--ctx-size",
        str(s["context_tokens"]),
        "--parallel",
        "1",
        "--n-gpu-layers",
        str(s["gpu_layers"]),
        "--threads",
        str(s["cpu_threads"]),
        "--flash-attn",
        "on",
        "--jinja",
        "--no-context-shift",
        "--no-webui",
        "--rope-scaling",
        s["rope_scaling"],
        "--rope-scale",
        str(s["rope_scale"]),
        "--yarn-orig-ctx",
        str(s["yarn_original_context"]),
    ]
    receipt = {
        "started_utc": utc(),
        "status": "starting",
        "config": cfg,
        "hardware": inventory(),
        "model_sha256": digest,
        "backend_commit": commit,
        "binary_sha256": sha256(binary),
        "command": args,
        "credential_value_recorded": False,
        "maximum_lifetime_seconds": s["maximum_lifetime_seconds"],
    }
    save(receipt_path, receipt)
    # Command-line flags define the experiment; unrelated server environment
    # defaults must not silently add a different context or remote listener.
    child_env = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_")}
    proc = subprocess.Popen(args, env=child_env)
    receipt.update(pid=proc.pid, status="running")
    save(receipt_path, receipt)

    def terminate(signum, frame):
        raise KeyboardInterrupt

    previous_term = signal.signal(signal.SIGTERM, terminate)
    try:
        receipt["returncode"] = proc.wait(timeout=s["maximum_lifetime_seconds"])
        receipt["status"] = "exited"
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)
        receipt.update(status="stopped", returncode=proc.returncode)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        receipt["finished_utc"] = utc()
        save(receipt_path, receipt)
    if receipt["returncode"]:
        raise SystemExit(receipt["returncode"])


def smoke(cfg, cache, receipt_path):
    """Two generic transport checks, deliberately outside benchmark episodes."""
    sys.path.insert(0, str(ROOT / "src"))
    from witness_cl.model_v8 import InferenceBudget
    from witness_cl.model_v9 import DecodingV9
    from witness_cl.model_v9_compatible import LocalInferenceV9Compatible

    s = cfg["server"]
    client = LocalInferenceV9Compatible(
        endpoint=f"http://{s['host']}:{s['port']}",
        model=cfg["model"]["alias"],
        key_file=cache / "runtime/server.key",
        context_tokens=s["context_tokens"],
        max_output=1024,
        timeout=120.0,
        response_mode="schema",
        decoding=DecodingV9(temperature=0.6, top_p=0.95, thinking=True),
    )
    budget = InferenceBudget(max_total_tokens=10000, max_calls=2, deadline=time.monotonic() + 180.0)
    records = []
    result = {
        "started_utc": utc(),
        "purpose": "generic transport smoke; not benchmark competence",
        "config": cfg,
        "source_sha256": {
            name: sha256(ROOT / name)
            for name in [
                "tools/gh200_runtime.py",
                "src/witness_cl/model_v8.py",
                "src/witness_cl/model_v9.py",
                "src/witness_cl/model_v9_compatible.py",
            ]
        },
        "records": records,
    }
    started = time.monotonic()
    try:
        value = client.complete(
            [
                {"role": "system", "content": "Return only the requested JSON object."},
                {"role": "user", "content": 'Compute 37 + 58. Return {"value": number}.'},
            ],
            budget,
            phase="runtime:solve",
            records=records,
            response_schema={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )
        result["arithmetic_correct"] = json.loads(value) == {"value": 95}
        value = client.complete(
            [
                {"role": "system", "content": "Return only the requested JSON object."},
                {
                    "role": "user",
                    "content": 'Return {"insight": "smoke only"}. This is a transport check.',
                },
            ],
            budget,
            phase="runtime:reflection",
            records=records,
            output_tokens=256,
            response_schema={
                "type": "object",
                "properties": {"insight": {"type": "string", "maxLength": 4096}},
                "required": ["insight"],
                "additionalProperties": False,
            },
        )
        result["reflection_correct"] = json.loads(value) == {"insight": "smoke only"}
        result["reflection_thinking_disabled"] = records[-1]["decoding"]["thinking"] is False
        result["wire_large_string_bound_removed"] = (
            "maxLength" not in records[-1]["response_schema"]["properties"]["insight"]
        )
        result["status"] = (
            "passed"
            if all(
                result[x]
                for x in [
                    "arithmetic_correct",
                    "reflection_correct",
                    "reflection_thinking_disabled",
                    "wire_large_string_bound_removed",
                ]
            )
            else "failed"
        )
    except Exception as exc:
        result.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        result.update(
            finished_utc=utc(), seconds=time.monotonic() - started, budget=budget.to_dict()
        )
        save(receipt_path, result)
    if result["status"] != "passed":
        raise RuntimeError("generic smoke did not pass")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inventory", "download", "verify", "serve", "smoke"])
    parser.add_argument("--config", type=Path, default=ROOT / "configs/v10_gh200_runtime.json")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    cfg = load_config(args.config)
    receipt = args.receipt or ROOT / f"artifacts/v10/runtime-{args.action}.json"
    if args.action == "inventory":
        save(receipt, inventory())
    elif args.action == "download":
        download(cfg, args.cache, receipt)
    elif args.action == "verify":
        path, digest = verify_model(cfg, args.cache)
        save(
            receipt,
            {
                "timestamp_utc": utc(),
                "filename": path.name,
                "sha256": digest,
                "bytes": path.stat().st_size,
                "status": "verified",
            },
        )
    elif args.action == "smoke":
        smoke(cfg, args.cache, receipt)
    else:
        serve(cfg, args.cache, receipt)


if __name__ == "__main__":
    main()
