"""Archive/path isolation for trusted Git revision replay; no model calls."""

from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from tools.replay_at_revision import extract_source, validate_output


@pytest.mark.parametrize("kind", ["parent", "absolute", "symbolic", "hard"])
def test_archive_escape_and_link_members_are_rejected(tmp_path, kind):
    bundle = tmp_path / "source.tar"
    source = tmp_path / "source"
    source.mkdir()
    member = tarfile.TarInfo(
        "../outside"
        if kind == "parent"
        else str(tmp_path / "outside")
        if kind == "absolute"
        else "link"
    )
    if kind in ("symbolic", "hard"):
        member.type = tarfile.SYMTYPE if kind == "symbolic" else tarfile.LNKTYPE
        member.linkname = "../outside"
    with tarfile.open(bundle, "w") as archive:
        archive.addfile(member)
    with pytest.raises(ValueError, match="unsafe repository archive"):
        extract_source(bundle, source)
    assert not (tmp_path / "outside").exists()


def test_regular_archive_extracts_exact_bytes(tmp_path):
    bundle = tmp_path / "source.tar"
    source = tmp_path / "source"
    source.mkdir()
    body = b"pinned source bytes\n"
    member = tarfile.TarInfo("src/module.py")
    member.size = len(body)
    with tarfile.open(bundle, "w") as archive:
        archive.addfile(member, BytesIO(body))
    extract_source(bundle, source)
    assert (source / "src/module.py").read_bytes() == body


def test_output_cannot_reenter_historical_or_raw_evidence_via_symlink(tmp_path):
    root = tmp_path / "repo"
    historical = root / "artifacts/v9"
    historical.mkdir(parents=True)
    run = root / "artifacts/v10/immutable-run"
    run.mkdir(parents=True)
    alias = tmp_path / "old"
    alias.symlink_to(historical, target_is_directory=True)
    for output in (historical / "receipt.json", alias / "receipt.json", run / "manifest.json"):
        with pytest.raises(ValueError):
            validate_output(output, root, run)
    allowed = root / "artifacts/v10/replay.json"
    assert validate_output(allowed, root, run) == allowed.resolve()


def test_frozen_real_run_replays_without_using_active_learner_sources(tmp_path):
    root = Path(__file__).resolve().parents[1]
    directory = root / "artifacts/v10/development-94000"
    if not (directory / "summary.json").exists():
        pytest.skip("requires retained first GH200 development evidence")
    revision = "11be4c4"
    if subprocess.run(
        ["git", "cat-file", "-e", revision + "^{commit}"], cwd=root, capture_output=True
    ).returncode:
        pytest.skip("requires complete Git research history")
    output = tmp_path / "replay.json"
    subprocess.run(
        [
            sys.executable,
            str(root / "tools/replay_at_revision.py"),
            str(directory),
            "--revision",
            revision,
            "--freeze",
            str(root / "artifacts/v10/pre-run-freeze.json"),
            "--output",
            str(output),
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    result = json.loads(output.read_text())
    assert result["records_replayed"] == 24 and result["sql_replayed"] == 39
    assert result["study_status"] == "competence_gate_failed" and result["status"] == "partial"
    assert result["revision_replay"]["source_revision"].startswith(revision)
    assert result["revision_replay"]["inherited_pythonpath_removed"]
