"""Fail-closed provenance and finite runtime configuration checks; no GPU needed."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gh200_runtime", ROOT / "tools/gh200_runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
CONFIG = json.loads((ROOT / "configs/v10_gh200_runtime.json").read_text())


@pytest.mark.parametrize(
    "group,key,value",
    [
        ("server", "host", "0.0.0.0"),
        ("server", "maximum_lifetime_seconds", 0),
        ("server", "maximum_lifetime_seconds", 14401),
        ("server", "context_tokens", True),
        ("server", "parallel_sequences", 2),
        ("download", "parallel_requests", 100),
        ("download", "deadline_seconds", 0),
        ("model", "filename", "../weights.gguf"),
        ("model", "sha256", "z" * 64),
    ],
)
def test_unsafe_or_unbounded_config_rejected_before_serving(tmp_path, group, key, value):
    cfg = deepcopy(CONFIG)
    cfg[group][key] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        runtime.load_config(path)


def test_corrupt_same_size_weights_fail_publisher_hash(tmp_path):
    cfg = deepcopy(CONFIG)
    cfg["model"].update(filename="small.gguf", bytes=4, sha256=hashlib.sha256(b"good").hexdigest())
    (tmp_path / "models").mkdir()
    path = tmp_path / "models/small.gguf"
    path.write_bytes(b"evil")
    with pytest.raises(ValueError, match="SHA-256"):
        runtime.verify_model(cfg, tmp_path)
    path.write_bytes(b"good")
    verified_path, digest = runtime.verify_model(cfg, tmp_path)
    assert verified_path == path
    assert digest == cfg["model"]["sha256"]


def test_truncated_weights_fail_size_before_hash(tmp_path, monkeypatch):
    cfg = deepcopy(CONFIG)
    cfg["model"].update(filename="small.gguf", bytes=4)
    (tmp_path / "models").mkdir()
    (tmp_path / "models/small.gguf").write_bytes(b"bad")

    def forbidden_hash(path):
        raise AssertionError("size check must run before reading all weights")

    monkeypatch.setattr(runtime, "sha256", forbidden_hash)
    with pytest.raises(ValueError, match="byte size"):
        runtime.verify_model(cfg, tmp_path)
