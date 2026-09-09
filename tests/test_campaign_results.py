import pytest

from tools.campaign import artifact_digest
from tools.campaign_results import audited_study
from witness_cl.campaign_io import save, sha


def complete_fixture(directory):
    save(directory / "freeze.json", {"contains_test_double_calls": False,
                                      "arms": ["full_history", "ace", "delayed"]})
    save(directory / "summary.json", {"complete": True, "cost": {"unknown_usage_calls": 0}})
    save(directory / "episodes/one.json", {"synthetic_test_marker": "original"})
    save(directory / "calls/one/000.json", {"synthetic_test_marker": "original"})
    save(directory / "audit.json", {
        "consistent": True, "complete": True,
        "freeze_sha256": sha(directory / "freeze.json"),
        "summary_sha256": sha(directory / "summary.json"),
        "records_sha256": artifact_digest(directory / "episodes"),
        "journals_sha256": artifact_digest(directory / "calls"),
        "cost": {"unknown_usage_calls": 0},
    })


@pytest.mark.parametrize("path", ["episodes/one.json", "calls/one/000.json"])
def test_reporting_rejects_stale_audit_after_raw_evidence_changes(tmp_path, path):
    complete_fixture(tmp_path)
    audited_study(tmp_path)
    save(tmp_path / path, {"synthetic_test_marker": "tampered"})
    with pytest.raises(ValueError, match="complete audit bound"):
        audited_study(tmp_path)
