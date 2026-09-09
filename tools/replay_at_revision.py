#!/usr/bin/env python3
"""Replay a current-study artifact against its frozen Git source checkpoint.

The current auditor is copied into a disposable checkout of the recorded learner
revision. This keeps the auditor's additional checks while preserving the exact
learner code, protocol and environment generator. No model is contacted.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


def validate_output(output, root, run_directory):
    """Keep diagnostics outside immutable raw runs and historical evidence."""
    output, root, run_directory = output.resolve(), root.resolve(), run_directory.resolve()
    for version in range(1, 10):
        if output.is_relative_to(root / "artifacts" / f"v{version}"):
            raise ValueError("cannot overwrite historical evidence")
    if output.is_relative_to(run_directory):
        raise ValueError("replay output must be outside the immutable run")
    return output


def extract_source(bundle, source):
    """Git owns this archive, but path escapes and links are still rejected."""
    source = source.resolve()
    with tarfile.open(bundle) as archive:
        for member in archive.getmembers():
            if (
                member.issym()
                or member.islnk()
                or not (source / member.name).resolve().is_relative_to(source)
            ):
                raise ValueError("unsafe repository archive member")
        archive.extractall(source, filter="data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", args.revision + "^{commit}"],
        cwd=root,
        text=True,
    ).strip()
    output = validate_output(args.output, root, args.directory)
    with tempfile.TemporaryDirectory(prefix="witness-study-replay-") as directory:
        workspace = Path(directory)
        bundle = workspace / "source.tar"
        with bundle.open("wb") as handle:
            subprocess.run(
                ["git", "archive", "--format=tar", revision], cwd=root, stdout=handle, check=True
            )
        source = workspace / "source"
        source.mkdir()
        extract_source(bundle, source)
        shutil.copyfile(root / "tools/replay_study.py", source / "tools/replay_study.py")
        command = [
            sys.executable,
            str(source / "tools/replay_study.py"),
            str(args.directory.resolve()),
            "--output",
            str(output),
        ]
        if args.freeze:
            command += ["--freeze", str(args.freeze.resolve())]
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        subprocess.run(command, cwd=source, env=environment, check=True)
        receipt = json.loads(output.read_text())
        receipt["revision_replay"] = {
            "source_revision": revision,
            "source_archive_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "auditor_copied_from_current_tree": True,
            "inherited_pythonpath_removed": True,
        }
        output.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
