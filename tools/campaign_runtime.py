#!/usr/bin/env python3
"""Prepare publisher-verified BF16 weights and serve an isolated campaign endpoint.

Downloads resume at file boundaries and within interrupted files. Every completed
file is checked against the pinned publisher's LFS SHA-256 or Git blob identity.
Conversion uses a clean pinned llama.cpp checkout and an isolated environment.
Preparation never starts inference; ``serve`` is a separate explicit action.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = Path.home() / ".local/share/witness-cl/campaign"
DEFAULT_BACKEND = Path.home() / ".local/share/witness-cl/llama.cpp"
REPOSITORY = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
REVISION = "b2cff646eb4bb1d68355c01b18ae02e7cf42d120"
BACKEND_COMMIT = "91f6a6cf361385700bbe15981f0f39909df77498"
DENSE_REPOSITORY = "Qwen/Qwen3.6-27B"
DENSE_REVISION = "6a9e13bd6fc8f0983b9b99948120bc37f49c13e9"
DENSE_BACKEND_COMMIT = "434ddbbc0e30522e897670681e503b797c12b7c1"
PINNED_MODELS = {
    (REPOSITORY, REVISION): BACKEND_COMMIT,
    (DENSE_REPOSITORY, DENSE_REVISION): DENSE_BACKEND_COMMIT,
}
SMALL_FILES = {
    "LICENSE",
    "README.md",
    "chat_template.jinja",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors.index.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
}


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save(path, data):
    """Atomic progress receipt; refuse paths inside preserved historical evidence."""
    path = Path(path).resolve()
    historical = ROOT / "artifacts"
    if path.is_relative_to(historical):
        parts = path.relative_to(historical).parts
        if parts and re.fullmatch(r"v[0-9]+", parts[0]):
            raise ValueError("campaign receipts cannot overwrite historical artifacts")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("w") as out:
        json.dump(data, out, indent=2, allow_nan=False)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(path)


def load_config(path):
    cfg = json.loads(Path(path).read_text())
    model, server, download = cfg["model"], cfg["server"], cfg["download"]
    pin = PINNED_MODELS.get((model["repository"], model["revision"]))
    if pin is None:
        raise ValueError("campaign requires the exact pinned official publisher")
    if cfg["backend"]["commit"] != pin or model["outtype"] != "bf16":
        raise ValueError("campaign conversion requires pinned backend and BF16")
    if Path(model["filename"]).name != model["filename"] or not model["filename"].endswith(".gguf"):
        raise ValueError("model filename must be a local GGUF basename")
    if server["host"] != "127.0.0.1" or server["rope_scaling"] != "none":
        raise ValueError("campaign endpoint must be loopback with no RoPE extension")
    if server["kv_cache_dtype"] != "f16":
        raise ValueError("campaign memory estimate requires the declared f16 KV cache")
    for key, low, high in (
        ("port", 1024, 65535),
        ("context_tokens", 1024, 262144),
        ("cpu_threads", 1, 64),
        ("gpu_layers", 0, 999),
        ("memory_reserve_mib", 1024, 65536),
    ):
        if type(server[key]) is not int or not low <= server[key] <= high:
            raise ValueError("invalid campaign server limit: " + key)
    if server["parallel_sequences"] != 1 or type(server["parallel_sequences"]) is not int:
        raise ValueError("initial campaign requires one slot")
    if server["context_tokens"] > model["native_context_tokens"]:
        raise ValueError("configured context exceeds publisher native context")
    if cfg["decoding"]["repeat_last_n"] != server["context_tokens"]:
        raise ValueError("explicit repetition window must cover the configured context")
    lifetime = server["maximum_lifetime_seconds"]
    if lifetime is not None and (type(lifetime) is not int or lifetime <= 0):
        raise ValueError("lifetime must be positive seconds or explicit null for sustained serving")
    for key, low, high in (
        ("parallel_files", 1, 8),
        ("attempts_per_file", 1, 10),
        ("timeout_seconds", 1, 300),
    ):
        if type(download[key]) is not int or not low <= download[key] <= high:
            raise ValueError("invalid download limit: " + key)
    return cfg


def publisher_files(publisher, cfg):
    """Reject malformed metadata before creating paths or trusting file hashes."""
    model = cfg["model"]
    if publisher.get("id") != model["repository"] or publisher.get("sha") != model["revision"]:
        raise ValueError("publisher response does not identify the pinned model revision")
    selected = []
    names = set()
    for entry in publisher.get("siblings", []):
        name = entry["rfilename"]
        if name not in SMALL_FILES and not re.fullmatch(
            r"model-[0-9]{5}-of-[0-9]{5}\.safetensors", name
        ):
            continue
        if name in names or type(entry.get("size")) is not int or entry["size"] <= 0:
            raise ValueError("invalid or duplicate publisher file")
        names.add(name)
        if name.endswith(".safetensors"):
            lfs = entry.get("lfs", {})
            if lfs.get("size") != entry["size"] or not re.fullmatch(
                "[0-9a-f]{64}", lfs.get("sha256", "")
            ):
                raise ValueError("safetensors require publisher LFS SHA-256 and size")
        elif not re.fullmatch("[0-9a-f]{40}", entry.get("blobId", "")):
            raise ValueError("small files require publisher Git blob identity")
        selected.append(entry)
    if not SMALL_FILES.issubset(names) or not any(n.endswith(".safetensors") for n in names):
        raise ValueError("publisher manifest is missing conversion inputs")
    return selected


def verify_file(path, entry):
    path = Path(path)
    if path.stat().st_size != entry["size"]:
        raise ValueError("publisher byte size mismatch: " + entry["rfilename"])
    digest = sha256(path)
    if "lfs" in entry:
        if digest != entry["lfs"]["sha256"]:
            raise ValueError("publisher LFS SHA-256 mismatch: " + entry["rfilename"])
    else:
        content = path.read_bytes()
        blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if blob != entry["blobId"]:
            raise ValueError("publisher Git blob mismatch: " + entry["rfilename"])
    return {
        "filename": entry["rfilename"],
        "bytes": entry["size"],
        "sha256": digest,
        "publisher_lfs_sha256": entry.get("lfs", {}).get("sha256"),
        "publisher_git_blob": entry["blobId"],
    }


def fetch_file(cfg, cache, entry):
    destination = Path(cache) / "source" / entry["rfilename"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return {**verify_file(destination, entry), "already_present": True}
    part = destination.with_suffix(destination.suffix + ".part")
    opts = cfg["download"]
    url = f"https://huggingface.co/{cfg['model']['repository']}/resolve/{cfg['model']['revision']}/{entry['rfilename']}"
    for attempt in range(opts["attempts_per_file"]):
        start = part.stat().st_size if part.exists() else 0
        if start > entry["size"]:
            raise ValueError("partial file exceeds publisher size")
        try:
            if start < entry["size"]:
                headers = {"User-Agent": "witness-cl-campaign/1"}
                if start:
                    headers["Range"] = f"bytes={start}-"
                with urlopen(
                    Request(url, headers=headers), timeout=opts["timeout_seconds"]
                ) as response:
                    if start and (
                        response.status != 206
                        or response.headers.get("Content-Range")
                        != f"bytes {start}-{entry['size'] - 1}/{entry['size']}"
                    ):
                        raise RuntimeError("server did not honor exact resume range")
                    if not start and response.status != 200:
                        raise RuntimeError("unexpected initial download response")
                    with part.open("ab") as output:
                        while block := response.read(8 * 1024 * 1024):
                            if output.tell() + len(block) > entry["size"]:
                                raise ValueError("download exceeds publisher size")
                            output.write(block)
                        output.flush()
                        os.fsync(output.fileno())
            verified = verify_file(part, entry)
            part.replace(destination)
            return {**verified, "already_present": False, "attempts": attempt + 1}
        except Exception:
            if attempt + 1 == opts["attempts_per_file"]:
                raise
            # A completed wrong file will never become valid through appending.
            if part.exists() and part.stat().st_size == entry["size"]:
                part.rename(part.with_name(part.name + f".rejected-{time.time_ns()}"))
            time.sleep(min(2**attempt, 16))
    raise AssertionError("unreachable")


def download(cfg, cache, receipt_path):
    cache = Path(cache)
    publisher_path = cache / "publisher.json"
    if publisher_path.exists():
        publisher = json.loads(publisher_path.read_text())
    else:
        url = f"https://huggingface.co/api/models/{cfg['model']['repository']}/revision/{cfg['model']['revision']}?blobs=true"
        with urlopen(url, timeout=60) as response:
            publisher = json.load(response)
        publisher_files(publisher, cfg)
        save(publisher_path, publisher)
    files = publisher_files(publisher, cfg)
    result = {
        "started_utc": utc(),
        "status": "downloading",
        "model": cfg["model"],
        "publisher_manifest_sha256": sha256(publisher_path),
        "files": [],
        "generation_calls": 0,
        "source_sha256": sha256(__file__),
    }
    save(receipt_path, result)
    try:
        with ThreadPoolExecutor(max_workers=cfg["download"]["parallel_files"]) as pool:
            futures = {pool.submit(fetch_file, cfg, cache, entry): entry for entry in files}
            for future in as_completed(futures):
                result["files"].append(future.result())
                save(receipt_path, result)
                print(
                    json.dumps(
                        {
                            "verified": result["files"][-1]["filename"],
                            "completed": len(result["files"]),
                            "total": len(files),
                        }
                    ),
                    flush=True,
                )
        source_cfg = json.loads((cache / "source/config.json").read_text())
        source_cfg = source_cfg.get("text_config", source_cfg)
        if (
            source_cfg["max_position_embeddings"] != cfg["model"]["native_context_tokens"]
            or source_cfg.get("rope_scaling") is not None
            or source_cfg.get("rope_parameters", {}).get("rope_type", "default") != "default"
        ):
            raise ValueError("publisher native context does not match campaign config")
        index = json.loads((cache / "source/model.safetensors.index.json").read_text())
        declared = {
            entry["rfilename"] for entry in files if entry["rfilename"].endswith(".safetensors")
        }
        if set(index["weight_map"].values()) != declared:
            raise ValueError("weight index and publisher shards differ")
        result["status"] = "verified"
    except BaseException as exc:
        result.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        result["finished_utc"] = utc()
        save(receipt_path, result)
    return result


def backend_identity(cfg, backend):
    backend = Path(backend)
    commit = subprocess.check_output(
        ["git", "-C", str(backend), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(backend), "status", "--porcelain"], text=True
    ).strip()
    if commit != cfg["backend"]["commit"] or dirty:
        raise ValueError("backend checkout must be clean at the pinned commit")
    libraries = {
        str(path.relative_to(backend)): sha256(path)
        for path in sorted((backend / "build/bin").glob("*.so*"))
        if path.is_file() and not path.is_symlink()
    }
    return {
        "commit": commit,
        "converter_sha256": sha256(backend / "convert_hf_to_gguf.py"),
        "binary_sha256": sha256(backend / "build/bin/llama-server"),
        "shared_libraries_sha256": libraries,
    }


def convert(cfg, cache, backend, python, receipt_path):
    cache, backend = Path(cache), Path(backend)
    identity = backend_identity(cfg, backend)
    publisher = json.loads((cache / "publisher.json").read_text())
    inputs = [
        verify_file(cache / "source" / e["rfilename"], e) for e in publisher_files(publisher, cfg)
    ]
    destination = cache / "models" / cfg["model"]["filename"]
    manifest = cache / "conversion.json"
    if destination.exists():
        previous = json.loads(manifest.read_text())
        if (
            previous["status"] != "verified"
            or previous["output_sha256"] != sha256(destination)
            or previous["backend"] != identity
            or previous["inputs"] != inputs
        ):
            raise ValueError("existing conversion differs from its provenance receipt")
        save(receipt_path, {**previous, "already_present": True})
        return previous
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".partial.gguf")
    args = [
        str(python),
        str(backend / "convert_hf_to_gguf.py"),
        str(cache / "source"),
        "--outfile",
        str(temporary),
        "--outtype",
        "bf16",
    ]
    result = {
        "started_utc": utc(),
        "status": "converting",
        "backend": identity,
        "inputs": inputs,
        "model": cfg["model"],
        "command": args,
        "source_sha256": sha256(__file__),
        "environment": subprocess.check_output(
            [str(python), "-m", "pip", "freeze", "--all"], text=True
        ),
        "generation_calls": 0,
    }
    save(receipt_path, result)
    try:
        child_env = {
            k: v for k, v in os.environ.items() if k not in ("NO_LOCAL_GGUF", "PYTHONPATH")
        }
        child_env.update(
            CUDA_VISIBLE_DEVICES="",
            OMP_NUM_THREADS="8",
            OPENBLAS_NUM_THREADS="8",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
        )
        subprocess.run(args, env=child_env, check=True)
        with temporary.open("rb") as data:
            if data.read(4) != b"GGUF":
                raise ValueError("conversion did not produce a GGUF file")
        result.update(
            output_sha256=sha256(temporary),
            output_bytes=temporary.stat().st_size,
            status="verified",
            output_path=str(destination),
        )
        temporary.replace(destination)
        save(manifest, result)
    except BaseException as exc:
        result.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        result["finished_utc"] = utc()
        save(receipt_path, result)
    save(manifest, result)
    return result


def server_command(cfg, cache, backend, key_path):
    server = cfg["server"]
    return [
        str(Path(backend) / "build/bin/llama-server"),
        "--model",
        str(Path(cache) / "models" / cfg["model"]["filename"]),
        "--alias",
        cfg["model"]["alias"],
        "--host",
        server["host"],
        "--port",
        str(server["port"]),
        "--api-key-file",
        str(key_path),
        "--ctx-size",
        str(server["context_tokens"]),
        "--parallel",
        "1",
        "--n-gpu-layers",
        str(server["gpu_layers"]),
        "--threads",
        str(server["cpu_threads"]),
        "--flash-attn",
        "on",
        "--cache-type-k",
        server["kv_cache_dtype"],
        "--cache-type-v",
        server["kv_cache_dtype"],
        "--jinja",
        "--no-context-shift",
        "--no-webui",
        "--rope-scaling",
        "none",
    ]


def memory_fit(cfg, model_bytes, source_config, gpu_query=None):
    """Conservative allocation estimate, not a guarantee about CUDA workspace."""
    source_config = source_config.get("text_config", source_config)
    if gpu_query is None:
        gpu_query = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            text=True,
        )
    lines = gpu_query.strip().splitlines()
    if len(lines) != 1:
        raise ValueError("campaign memory admission requires one explicit GPU")
    total_mib, free_mib = (int(value.strip()) for value in lines[0].split(","))
    if not 0 <= free_mib <= total_mib or type(model_bytes) is not int or model_bytes <= 0:
        raise ValueError("invalid model size or GPU memory inventory")
    kv_bytes = (
        2
        * source_config["num_hidden_layers"]
        * source_config["num_key_value_heads"]
        * source_config["head_dim"]
        * cfg["server"]["context_tokens"]
        * 2
    )
    required_mib = math.ceil((model_bytes + kv_bytes) / 2**20) + cfg["server"]["memory_reserve_mib"]
    return {
        "timestamp_utc": utc(),
        "model_bytes": model_bytes,
        "kv_bytes_estimate": kv_bytes,
        "reserve_mib": cfg["server"]["memory_reserve_mib"],
        "required_free_mib": required_mib,
        "gpu_total_mib": total_mib,
        "gpu_free_mib": free_mib,
        "fits": free_mib >= required_mib,
        "interpretation": "pre-launch estimate with explicit f16 KV cache and workspace reserve; actual allocation remains measured at startup",
        "hybrid_attention_bound": "all layers charged full-attention KV even when linear attention uses less",
    }


def serve(cfg, cache, backend, receipt_path):
    cache = Path(cache)
    identity = backend_identity(cfg, backend)
    conversion = json.loads((cache / "conversion.json").read_text())
    model = cache / "models" / cfg["model"]["filename"]
    if (
        conversion["status"] != "verified"
        or conversion["backend"] != identity
        or conversion["model"] != cfg["model"]
        or conversion["output_sha256"] != sha256(model)
    ):
        raise ValueError("converted model provenance does not match campaign runtime")
    source = cache / "source/config.json"
    source_record = next(row for row in conversion["inputs"] if row["filename"] == "config.json")
    if sha256(source) != source_record["sha256"]:
        raise ValueError("model architecture changed after conversion")
    fit = memory_fit(cfg, model.stat().st_size, json.loads(source.read_text()))
    save(Path(receipt_path).with_suffix(".memory-fit.json"), fit)
    if not fit["fits"]:
        raise RuntimeError("insufficient free GPU memory; leave existing servers untouched")
    key_path = cache / "runtime/server.key"
    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not key_path.exists():
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as key:
            key.write(secrets.token_urlsafe(32) + "\n")
    if not key_path.read_text().strip() or key_path.stat().st_mode & 0o077:
        raise ValueError("credential must be nonempty and owner-only")
    args = server_command(cfg, cache, backend, key_path)
    result = {
        "started_utc": utc(),
        "status": "starting",
        "config": cfg,
        "command": args,
        "backend": identity,
        "model_sha256": conversion["output_sha256"],
        "conversion_receipt_sha256": sha256(cache / "conversion.json"),
        "source_sha256": sha256(__file__),
        "credential_value_recorded": False,
        "memory_fit": fit,
        "hardware": subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv"],
            text=True,
        ),
    }
    save(receipt_path, result)
    child_env = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_")}
    process = subprocess.Popen(args, env=child_env)
    result.update(status="running", pid=process.pid)
    save(receipt_path, result)

    def stop(signum, frame):
        raise KeyboardInterrupt

    old_handler = signal.signal(signal.SIGTERM, stop)
    try:
        process.wait(timeout=cfg["server"]["maximum_lifetime_seconds"])
        result["status"] = "exited"
    except (KeyboardInterrupt, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=30)
        result["status"] = "stopped"
    finally:
        signal.signal(signal.SIGTERM, old_handler)
        result.update(returncode=process.returncode, finished_utc=utc())
        save(receipt_path, result)
    return process.returncode


def smoke(cfg, cache, backend, receipt_path):
    """Two frozen generic calls; costs are setup, never benchmark observations."""
    sys.path.insert(0, str(ROOT / "src"))
    from witness_cl.model_campaign import build_client
    from witness_cl.model_v8 import InferenceBudget

    cache = Path(cache)
    identity = backend_identity(cfg, backend)
    conversion = json.loads((cache / "conversion.json").read_text())
    if conversion["status"] != "verified" or conversion["backend"] != identity:
        raise ValueError("smoke requires verified campaign conversion provenance")
    client = build_client(cfg, cache / "runtime/server.key", max_output=256, timeout=120)
    budget = InferenceBudget(max_total_tokens=10000, max_calls=2, deadline=time.monotonic() + 300)
    cases = [
        {
            "prompt": 'Compute 37 + 58. Return only {"value": number}.',
            "schema": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            "expected": {"value": 95},
        },
        {
            "prompt": 'Return exactly {"note":"runtime transport only","payload":{"value":1,"items":["a"]}}.',
            "schema": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "maxLength": 4096},
                    "payload": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "integer"},
                            "items": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
                        },
                        "required": ["value", "items"],
                        "additionalProperties": False,
                    },
                },
                "required": ["note", "payload"],
                "additionalProperties": False,
            },
            "expected": {"note": "runtime transport only", "payload": {"value": 1, "items": ["a"]}},
        },
    ]
    sources = [
        "tools/campaign_runtime.py",
        "src/witness_cl/model_campaign.py",
        "src/witness_cl/model_v8.py",
        "src/witness_cl/model_v9.py",
        "src/witness_cl/model_v9_compatible.py",
    ]
    result = {
        "started_utc": utc(),
        "status": "frozen_before_calls",
        "cases": cases,
        "purpose": "generic setup transport only; not SQL qualification or benchmark evidence",
        "client": client.snapshot_config(),
        "config": cfg,
        "backend": identity,
        "model_sha256": conversion["output_sha256"],
        "source_sha256": {name: sha256(ROOT / name) for name in sources},
        "records": [],
        "case_results": [],
    }
    save(receipt_path, result)
    started = time.monotonic()
    try:
        for case in cases:
            content = client.complete(
                [
                    {"role": "system", "content": "Return only the requested JSON object."},
                    {"role": "user", "content": case["prompt"]},
                ],
                budget,
                phase="runtime:smoke",
                records=result["records"],
                response_schema=case["schema"],
            )
            result["case_results"].append(json.loads(content) == case["expected"])
            save(receipt_path, result)
        result["status"] = "passed" if all(result["case_results"]) else "failed"
    except BaseException as exc:
        result.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        result.update(
            finished_utc=utc(), seconds=time.monotonic() - started, budget=budget.to_dict()
        )
        save(receipt_path, result)
    if result["status"] != "passed":
        raise RuntimeError("generic transport smoke did not pass")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["download", "convert", "serve", "smoke"])
    parser.add_argument("--config", type=Path, default=ROOT / "configs/campaign_runtime.json")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--backend", type=Path, default=DEFAULT_BACKEND)
    parser.add_argument("--python", type=Path, default=DEFAULT_CACHE / "conversion-venv/bin/python")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    cfg = load_config(args.config)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    receipt = args.receipt or ROOT / f"artifacts/campaign/runtime/{args.action}-{stamp}.json"
    if args.action == "download":
        download(cfg, args.cache, receipt)
    elif args.action == "convert":
        convert(cfg, args.cache, args.backend, args.python, receipt)
    elif args.action == "smoke":
        smoke(cfg, args.cache, args.backend, receipt)
    else:
        raise SystemExit(serve(cfg, args.cache, args.backend, receipt))


if __name__ == "__main__":
    main()
