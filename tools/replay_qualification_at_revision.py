#!/usr/bin/env python3
"""Audit a cold qualification using its exact trusted Git source checkpoint."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.replay_at_revision import extract_source, validate_output


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strict_json(text):
    value = json.loads(text)

    def check(item):
        if isinstance(item, dict):
            for entry in item.values():
                check(entry)
        elif isinstance(item, list):
            for entry in item:
                check(entry)
        elif type(item) is float and not math.isfinite(item):
            raise ValueError("nonfinite artifact number")

    check(value)
    return value


def validate_artifacts(directory):
    for name in ("freeze.json", "manifest.json", "summary.json"):
        strict_json((directory / name).read_text())
    for line in (directory / "episodes.jsonl").read_text().splitlines():
        strict_json(line)
    manifest = strict_json((directory / "manifest.json").read_text())
    for key in (
        "max_total_tokens",
        "max_calls",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "calls",
        "unknown_usage_calls",
    ):
        value = manifest["budget"][key]
        if type(value) is not int or value < 0:
            raise ValueError("qualification ledger requires exact nonnegative integers: " + key)


def replay(directory, revision):
    directory = Path(directory).resolve()
    validate_artifacts(directory)
    frozen = strict_json((directory / "freeze.json").read_text())
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", revision + "^{commit}"],
        cwd=ROOT,
        text=True,
    ).strip()
    with tempfile.TemporaryDirectory(prefix="witness-qualification-replay-") as workspace:
        base = Path(workspace)
        bundle, source = base / "source.tar", base / "source"
        with bundle.open("wb") as handle:
            subprocess.run(
                ["git", "archive", "--format=tar", revision], cwd=ROOT, stdout=handle, check=True
            )
        source.mkdir()
        extract_source(bundle, source)
        for name, digest in frozen["source_sha256"].items():
            path = (source / name).resolve()
            if (
                not path.is_relative_to(source.resolve())
                or not path.is_file()
                or sha(path) != digest
            ):
                raise ValueError(
                    "checkpoint does not contain the frozen qualification source: " + name
                )
        code = (
            "import json,sys; sys.path.insert(0,sys.argv[1]); "
            "from tools import qualify_sql_solver as q; "
            "q.select_bounded_reasoning() if sys.argv[3]=='bounded' else None; "
            "print(json.dumps(q.audit(sys.argv[2])))"
        )
        mode = "bounded" if "reasoning_budget_tokens" in frozen["client_config"] else "nonthinking"
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        raw = subprocess.check_output(
            [sys.executable, "-c", code, str(source), str(directory), mode],
            cwd=source,
            env=environment,
            text=True,
        )
        report = strict_json(raw)
        report["revision_replay"] = {
            "source_revision": revision,
            "archive_sha256": sha(bundle),
            "wrapper_sha256": sha(__file__),
            "source_verified_before_execution": True,
            "imports_from_archived_source": True,
            "network_calls": 0,
            "strict_finite_artifact_numbers": True,
            "exact_integer_ledger": True,
            "raw_artifacts_modified": False,
        }
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = validate_output(args.output, ROOT, args.directory)
    result = replay(args.directory, args.revision)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "records_replayed": result["records_replayed"],
                "sql_replayed": result["sql_replayed"],
                "qualified": result["qualified"],
            }
        )
    )


if __name__ == "__main__":
    main()
