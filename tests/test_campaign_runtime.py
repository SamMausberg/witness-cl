"""Publisher provenance, safe resumption and exact campaign wire settings."""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import time

import pytest

from witness_cl.model_campaign import DecodingCampaign, LocalInferenceCampaign, build_client
from witness_cl.model_v8 import InferenceBudget

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "campaign_runtime", ROOT / "tools/campaign_runtime.py"
)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
CONFIG = json.loads((ROOT / "configs/campaign_runtime.json").read_text())


def entry(name, content, lfs=False):
    row = {
        "rfilename": name,
        "size": len(content),
        "blobId": hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest(),
    }
    if lfs:
        row["lfs"] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    return row


@pytest.mark.parametrize(
    "group,key,value",
    [
        ("model", "repository", "someone/untrusted"),
        ("model", "revision", "main"),
        ("model", "filename", "../model.gguf"),
        ("model", "outtype", "q8_0"),
        ("backend", "commit", "main"),
        ("server", "host", "0.0.0.0"),
        ("server", "context_tokens", True),
        ("server", "context_tokens", 262145),
        ("server", "maximum_lifetime_seconds", 0),
        ("server", "parallel_sequences", True),
        ("server", "parallel_sequences", 2),
        ("server", "rope_scaling", "yarn"),
    ],
)
def test_configuration_rejects_different_or_invalid_runtime(tmp_path, group, key, value):
    cfg = deepcopy(CONFIG)
    cfg[group][key] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        runtime.load_config(path)


def test_default_sustained_runtime_and_native_context():
    cfg = runtime.load_config(ROOT / "configs/campaign_runtime.json")
    assert cfg["server"]["maximum_lifetime_seconds"] is None
    assert cfg["server"]["context_tokens"] == 65536
    assert cfg["model"]["native_context_tokens"] == 262144
    args = runtime.server_command(cfg, "/cache", "/backend", "/private/key")
    assert args.count("--alias") == 1
    assert "yarn" not in " ".join(args)
    assert args[args.index("--port") + 1] == "18085"
    assert args[args.index("--cache-type-k") + 1] == "f16"


def test_memory_admission_refuses_overlap_and_includes_kv_and_reserve():
    model = {"num_hidden_layers": 48, "num_key_value_heads": 4, "head_dim": 128}
    occupied = runtime.memory_fit(CONFIG, 61_070_000_000, model, "97871, 48000\n")
    available = runtime.memory_fit(CONFIG, 61_070_000_000, model, "97871, 97000\n")
    assert occupied["fits"] is False
    assert available["fits"] is True
    assert occupied["kv_bytes_estimate"] == 6 * 2**30
    assert occupied["required_free_mib"] > 72000


def test_memory_admission_rejects_ambiguous_gpu_inventory():
    with pytest.raises(ValueError, match="one explicit GPU"):
        runtime.memory_fit(CONFIG, 100, {}, "97871, 97000\n97871, 97000\n")


@pytest.mark.parametrize("lfs", [True, False])
def test_same_size_corruption_fails_publisher_hash(tmp_path, lfs):
    descriptor = entry("model.safetensors" if lfs else "config.json", b"good", lfs)
    path = tmp_path / descriptor["rfilename"]
    path.write_bytes(b"evil")
    with pytest.raises(ValueError, match="publisher.*mismatch"):
        runtime.verify_file(path, descriptor)
    path.write_bytes(b"good")
    assert runtime.verify_file(path, descriptor)["sha256"] == hashlib.sha256(b"good").hexdigest()


def test_manifest_requires_official_identity_and_lfs_hashes():
    publisher = {
        "id": runtime.REPOSITORY,
        "sha": runtime.REVISION,
        "siblings": [entry(name, b"small") for name in runtime.SMALL_FILES]
        + [entry("model-00001-of-00001.safetensors", b"weights", True)],
    }
    assert len(runtime.publisher_files(publisher, CONFIG)) == len(runtime.SMALL_FILES) + 1
    invalid = deepcopy(publisher)
    del invalid["siblings"][-1]["lfs"]
    with pytest.raises(ValueError, match="LFS"):
        runtime.publisher_files(invalid, CONFIG)
    publisher["sha"] = "main"
    with pytest.raises(ValueError, match="pinned"):
        runtime.publisher_files(publisher, CONFIG)


class Response(io.BytesIO):
    def __init__(self, data, status, headers):
        super().__init__(data)
        self.status = status
        self.headers = headers


def test_interrupted_file_resumes_and_is_publisher_verified(tmp_path, monkeypatch):
    descriptor = entry("model-00001-of-00001.safetensors", b"abcdefgh", True)
    source = tmp_path / "source"
    source.mkdir()
    (source / (descriptor["rfilename"] + ".part")).write_bytes(b"abc")
    requests = []

    def fetch(request, timeout):
        requests.append(request)
        return Response(b"defgh", 206, {"Content-Range": "bytes 3-7/8"})

    monkeypatch.setattr(runtime, "urlopen", fetch)
    result = runtime.fetch_file(CONFIG, tmp_path, descriptor)
    assert requests[0].get_header("Range") == "bytes=3-"
    assert result["sha256"] == hashlib.sha256(b"abcdefgh").hexdigest()
    assert (source / descriptor["rfilename"]).read_bytes() == b"abcdefgh"
    assert not (source / (descriptor["rfilename"] + ".part")).exists()


def test_invalid_resume_response_does_not_append(tmp_path, monkeypatch):
    descriptor = entry("model-00001-of-00001.safetensors", b"abcdefgh", True)
    part = tmp_path / "source" / (descriptor["rfilename"] + ".part")
    part.parent.mkdir()
    part.write_bytes(b"abc")
    monkeypatch.setattr(runtime, "urlopen", lambda *a, **k: Response(b"abcdefgh", 200, {}))
    cfg = deepcopy(CONFIG)
    cfg["download"]["attempts_per_file"] = 1
    with pytest.raises(RuntimeError, match="resume range"):
        runtime.fetch_file(cfg, tmp_path, descriptor)
    assert part.read_bytes() == b"abc"


def test_historical_receipt_refused_including_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    old = tmp_path / "artifacts/v10"
    old.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(old)
    with pytest.raises(ValueError, match="historical"):
        runtime.save(alias / "receipt.json", {})


@pytest.mark.parametrize("value", [False, 0, -1, float("nan"), float("inf"), 3])
def test_campaign_repeat_penalty_validation(value):
    with pytest.raises(ValueError, match="repeat_penalty"):
        DecodingCampaign(repeat_penalty=value)


def test_campaign_penalty_is_identical_in_preflight_generation_and_receipt(tmp_path):
    key = tmp_path / "key"
    key.write_text("test-only")
    client = LocalInferenceCampaign(
        endpoint="http://127.0.0.1:18085",
        model="campaign",
        key_file=key,
        context_tokens=4096,
        max_output=128,
        timeout=10,
        response_mode="schema",
    )
    bodies = []

    def post(path, body, timeout):
        bodies.append((path, deepcopy(body)))
        if path.endswith("input_tokens"):
            return {"input_tokens": 12}
        return {
            "model": "campaign",
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            "choices": [{"message": {"content": '{"value":1}'}, "finish_reason": "stop"}],
        }

    client._post = post
    budget = InferenceBudget(max_total_tokens=1000, max_calls=2, deadline=time.monotonic() + 30)
    records = []
    client.complete(
        [{"role": "user", "content": "test"}],
        budget,
        phase="test:solve",
        records=records,
        response_schema={"type": "object"},
    )
    assert bodies[0][1] == bodies[1][1]
    assert bodies[0][1]["repeat_penalty"] == 1.05
    assert bodies[0][1]["presence_penalty"] == 0
    assert bodies[0][1]["frequency_penalty"] == 0
    assert bodies[0][1]["repeat_last_n"] == 65536
    assert bodies[0][1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert records[0]["decoding"]["repeat_penalty"] == 1.05
    assert records[0]["request_config"]["repeat_penalty"] == 1.05
    assert budget.total_tokens == 15


def test_client_factory_snapshot_has_effective_settings_without_credentials(tmp_path):
    key = tmp_path / "key"
    key.write_text("never-put-this-value-in-receipts")
    client = build_client(CONFIG, key)
    snapshot = client.snapshot_config()
    assert snapshot["repeat_penalty"] == 1.05
    assert snapshot["decoding"] == CONFIG["decoding"]
    assert snapshot["max_output"] == 4096
    assert "never-put-this-value" not in json.dumps(snapshot)


def test_dense_candidate_has_separate_pins_and_neutral_prompt_penalties(tmp_path):
    cfg = runtime.load_config(ROOT / "configs/campaign_runtime_dense.json")
    assert cfg["model"]["repository"] == "Qwen/Qwen3.6-27B"
    assert cfg["model"]["revision"] == runtime.DENSE_REVISION
    assert cfg["backend"]["commit"] == runtime.DENSE_BACKEND_COMMIT
    assert cfg["server"]["port"] == 18086
    key = tmp_path / "key"
    key.write_text("test-only")
    client = build_client(cfg, key)
    assert client.snapshot_config()["decoding"] == cfg["decoding"]
    assert client.decoding.presence_penalty == 0.0
    assert client.decoding.repeat_penalty == 1.0
    assert client.decoding.thinking is False
    cfg["backend"]["commit"] = runtime.BACKEND_COMMIT
    path = tmp_path / "bad-backend.json"
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="pinned backend"):
        runtime.load_config(path)


def test_hybrid_model_memory_estimate_uses_conservative_full_layer_bound():
    cfg = runtime.load_config(ROOT / "configs/campaign_runtime_dense.json")
    model = {"text_config": {"num_hidden_layers": 64, "num_key_value_heads": 4, "head_dim": 256,
                              "layer_types": ["linear_attention"] * 48 + ["full_attention"] * 16}}
    fit = runtime.memory_fit(cfg, 54_000_000_000, model, "97871, 97000\n")
    assert fit["fits"]
    assert fit["kv_bytes_estimate"] == 16 * 2**30
    assert fit["required_free_mib"] > 75000
