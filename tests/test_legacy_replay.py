"""Historical source replay must leave the live checkout and frozen records intact."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def replay_module(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "witness_legacy_replay", ROOT / "tools/replay_legacy.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.platform, "platform", lambda: "test-platform")
    return module


def test_every_frozen_version_and_symlink_alias_is_rejected(replay_module, tmp_path):
    for version in range(1, 10):
        archived = tmp_path / "artifacts" / f"v{version}"
        archived.mkdir(parents=True)
        with pytest.raises(ValueError, match="frozen"):
            replay_module.checked_output(archived / "receipt.json", tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "artifacts/v9", target_is_directory=True)
    with pytest.raises(ValueError, match="frozen"):
        replay_module.checked_output(alias / "receipt.json", tmp_path)


@pytest.mark.parametrize(
    "destination", ["receipt.json", "receipt.log", "legacy", "legacy/witness-v9-first-replay.json"]
)
def test_derived_output_symlinks_cannot_write_archived_evidence(
    replay_module,
    monkeypatch,
    tmp_path,
    destination,
):
    root = tmp_path / "project"
    archived = root / "artifacts/v9"
    archived.mkdir(parents=True)
    sentinel = archived / "protected.json"
    sentinel.write_text("frozen")
    output_dir = root / "artifacts/v10"
    output_dir.mkdir()
    alias = output_dir / destination
    alias.parent.mkdir(parents=True, exist_ok=True)
    alias.symlink_to(
        archived if destination == "legacy" else sentinel,
        target_is_directory=destination == "legacy",
    )
    monkeypatch.setattr(replay_module, "__file__", str(root / "tools/replay_legacy.py"))
    monkeypatch.setattr(
        sys, "argv", ["replay_legacy", "--output", str(output_dir / "receipt.json")]
    )
    monkeypatch.setattr(
        replay_module.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("Output guards must precede execution"),
    )
    with pytest.raises(SystemExit, match="frozen"):
        replay_module.main()
    assert sentinel.read_text() == "frozen"


@pytest.mark.parametrize("write_receipts", [True, False])
def test_exact_revision_replay_executes_only_in_disposable_source_tree(
    replay_module,
    monkeypatch,
    tmp_path,
    write_receipts,
):
    root = tmp_path / "project"
    root.mkdir()
    live_source = root / "SOURCE.txt"
    live_source.write_text("current source must stay unchanged")
    output = root / "artifacts/v10/receipt.json"
    monkeypatch.setattr(replay_module, "__file__", str(root / "tools/replay_legacy.py"))
    monkeypatch.setattr(sys, "argv", ["replay_legacy", "--output", str(output)])
    receipts = tuple(str(tmp_path / Path(name).name) for name in replay_module.LEGACY_OUTPUTS)
    if not write_receipts:
        for name in receipts:
            Path(name).write_text(json.dumps({"status": "passed", "claim_confirmed": False}))
    monkeypatch.setattr(replay_module, "LEGACY_OUTPUTS", receipts)
    monkeypatch.setenv("PYTHONPATH", "a-path-that-must-not-leak-into-legacy-replay")
    checkouts = []

    def execute(command, **kwargs):
        if command[0] == "git":
            assert command == [
                "git",
                "archive",
                "--format=tar",
                "88b0a1b7c093c21135489a3e5cbbda3bb0634536",
            ]
            assert kwargs["cwd"] == root
            with tarfile.open(fileobj=kwargs["stdout"], mode="w") as archive:
                payload = b"frozen source"
                member = tarfile.TarInfo("SOURCE.txt")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            return subprocess.CompletedProcess(command, 0)
        assert command == ["make", "v9-audit", "PYTHON=" + sys.executable]
        checkout = Path(kwargs["cwd"])
        checkouts.append(checkout)
        assert checkout != root and not checkout.is_relative_to(root)
        assert (checkout / "SOURCE.txt").read_text() == "frozen source"
        assert "PYTHONPATH" not in kwargs["env"]
        (checkout / "SOURCE.txt").write_text("legacy make may update its disposable tree")
        if write_receipts:
            for name in receipts:
                Path(name).write_text(json.dumps({"status": "passed", "claim_confirmed": False}))
        return subprocess.CompletedProcess(command, 0, stdout="replayed fixture\n")

    monkeypatch.setattr(replay_module.subprocess, "run", execute)
    assert replay_module.main() == (0 if write_receipts else 1)
    assert live_source.read_text() == "current source must stay unchanged"
    assert all(not checkout.exists() for checkout in checkouts)
    report = json.loads(output.read_text())
    assert report["passed"] == write_receipts and report["model_calls"] == 0
    assert report["source_revision"] == replay_module.FROZEN_REVISION
    assert all(row["produced"] == write_receipts for row in report["replays"])
    assert "current interpreter" in report["source_scope"]


def test_missing_historical_commit_explains_full_history_requirement(
    replay_module,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(replay_module, "__file__", str(tmp_path / "tools/replay_legacy.py"))
    monkeypatch.setattr(
        sys, "argv", ["replay_legacy", "--output", str(tmp_path / "out/receipt.json")]
    )

    def fail_archive(command, **kwargs):
        raise subprocess.CalledProcessError(128, command)

    monkeypatch.setattr(replay_module.subprocess, "run", fail_archive)
    with pytest.raises(SystemExit, match="fetch-depth: 0"):
        replay_module.main()
