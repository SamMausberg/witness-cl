#!/usr/bin/env python3
"""Replay frozen v9 evidence using its original source revision in a temporary tree.

Current SQLite safety fixes intentionally change a frozen source hash. Running
the original replay at its exact revision preserves provenance without pretending
that the patched source produced the historical results. No model calls occur.
The Python/SQLite runtime is recorded; only repository source is historical.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time


FROZEN_REVISION = "88b0a1b7c093c21135489a3e5cbbda3bb0634536"
LEGACY_OUTPUTS = (
    "/tmp/witness-v9-diagnostic-replay.json",
    "/tmp/witness-v9-first-replay.json",
    "/tmp/witness-v9-json-replay.json",
    "/tmp/witness-v9-portable-replay.json",
)


def checked_output(path: Path, root: Path) -> Path:
    """Check each derived destination too, including existing symlink aliases."""
    resolved = path.resolve()
    for version in range(1, 10):
        if resolved.is_relative_to((root / "artifacts" / f"v{version}").resolve()):
            raise ValueError("Legacy replay must not overwrite frozen v1-v9 artifacts.")
    return resolved


def file_signature(path: Path) -> tuple[int, ...] | None:
    """Compare file writes without assuming wall-clock and filesystem resolution agree."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/v10/legacy-replay.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        output = checked_output(args.output, root)
        log = checked_output(output.with_suffix(".log"), root)
        summaries = checked_output(output.parent / "legacy", root)
        copied_outputs = {
            name: checked_output(summaries / Path(name).name, root) for name in LEGACY_OUTPUTS
        }
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.time_ns()
    previous_outputs = {name: file_signature(Path(name)) for name in LEGACY_OUTPUTS}
    report = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_revision": FROZEN_REVISION,
        "source_scope": "exact git archive; current interpreter and SQLite, not historical runtime",
        "python": sys.version,
        "python_executable": sys.executable,
        "sqlite_version": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "model_calls": 0,
        "passed": False,
    }
    with tempfile.TemporaryDirectory(prefix="witness-cl-legacy-") as temporary:
        directory = Path(temporary)
        archive = directory / "source.tar"
        try:
            with archive.open("wb") as handle:
                # This exact, trusted commit is fixed in source. The CLI never
                # accepts an arbitrary revision or archive from another party.
                subprocess.run(
                    ["git", "archive", "--format=tar", FROZEN_REVISION],
                    cwd=root,
                    stdout=handle,
                    check=True,
                )
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                f"Could not archive frozen revision {FROZEN_REVISION}. "
                "Fetch full Git history (actions/checkout fetch-depth: 0 in CI) and retry."
            ) from exc
        report["source_archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        checkout = directory / "source"
        checkout.mkdir()
        with tarfile.open(archive) as handle:
            handle.extractall(checkout, filter="data")
        command = ["make", "v9-audit", "PYTHON=" + sys.executable]
        report["command"] = command
        # Avoid inheriting a caller's custom package path. The archived Makefile
        # supplies its own src/ path to each experiment replay.
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(
            command,
            cwd=checkout,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        log.write_text(result.stdout)
        report["exit_code"] = result.returncode
        report["log"] = os.path.relpath(log, output.parent)
        report["log_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
        summaries.mkdir(exist_ok=True)
        report["replays"] = []
        for name in LEGACY_OUTPUTS:
            path = Path(name)
            if not path.is_file() or file_signature(path) == previous_outputs[name]:
                report["replays"].append({"name": path.name, "produced": False})
                continue
            copied = copied_outputs[name]
            shutil.copyfile(path, copied)
            report["replays"].append(
                {
                    "name": path.name,
                    "produced": True,
                    "path": os.path.relpath(copied, output.parent),
                    "sha256": hashlib.sha256(copied.read_bytes()).hexdigest(),
                    "result": json.loads(copied.read_text()),
                }
            )
        report["passed"] = result.returncode == 0 and all(
            row["produced"] for row in report["replays"]
        )
    report["elapsed_seconds"] = (time.time_ns() - started) / 1_000_000_000
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("passed", "source_revision", "exit_code", "elapsed_seconds")
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
