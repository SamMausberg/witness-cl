"""Transient publication schema fixtures; no generated research observations."""
from copy import deepcopy
import shutil

import pytest

from tools import campaign_fast as fast
from tools import publish_campaign as pub
from witness_cl.campaign_io import read, save


def bundle(tmp_path):
    """Build all 240 schema records under pytest's temporary directory only."""
    out = tmp_path / "fast-schema-fixture"
    inventory = {}
    for name in ("tools/campaign_fast.py", "src/witness_cl/campaign_analysis.py"):
        target = out / "sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pub.ROOT / name, target)
        inventory[name] = pub.file_sha(target)
    frozen = {**fast.protocol(), "contains_test_double_calls": False,
              "source_sha256": inventory, "planned_records": 240}
    schedule = fast.planned_records(frozen)
    frozen["schedule_sha256"] = pub.digest(schedule)
    save(out / "freeze.json", frozen)
    save(out / "schedule.json", schedule)
    records = []
    for item in schedule:
        call = {"generation_attempted": True, "status": "completed",
                "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
        correct = item["phase"] != "final" or item["arm"] != "delayed"
        trace = {"phase": item["phase"], "arm": item["arm"], "status": "completed",
                 "reward": int(correct), "model_calls": [call]}
        record = {**item, "schema_fixture": True,
                  "freeze_sha256": pub.file_sha(out / "freeze.json"), "trace": trace}
        records.append(record)
        save(out / "episodes" / (item["key"] + ".json"), record)
        save(out / "calls" / item["key"] / "000.json", {"state": "recorded", "calls": [call]})
    save(out / "summary.json", fast.summarize(records, frozen))
    rebind_audit(out)
    return out


def rebind_audit(out):
    tracker = pub.Inputs()
    frozen, summary = read(out / "freeze.json"), read(out / "summary.json")
    save(out / "audit.json", {
        "experiment": fast.VERSION, "complete": True, "consistent": True,
        "network_calls": 0, "records_replayed": frozen["planned_records"],
        "freeze_sha256": pub.file_sha(out / "freeze.json"),
        "summary_sha256": pub.file_sha(out / "summary.json"),
        "records_sha256": tracker.tree(out / "episodes"),
        "journals_sha256": tracker.tree(out / "calls"), "cost": summary["cost"]})


def test_complete_fast_negative_stays_descriptive_and_preserves_all_denominators(tmp_path):
    out = bundle(tmp_path)
    save(out / "analysis.json", {"all_five_pass": True})
    snapshot = pub.build_snapshot([out])
    study = snapshot["studies"][0]
    assert study["status"] == "complete" and study["outcomes_publishable"]
    assert study["kind"] == fast.VERSION and study["descriptive_only"]
    assert not study["primary_claim"] and not study["original_32_stream_pilot_completed"]
    assert "analysis" not in study and study["streams"] == 2 and study["planned_records"] == 240
    assert study["physical_cost"]["calls"] == 240
    rows = {row["arm"]: row for row in study["descriptive"]}
    assert set(rows) == set(fast.ARMS)
    assert all(row["n"] == 16 and row["streams"] == 2 for row in rows.values())
    assert rows["delayed"]["correct"] == 0 and rows["full_history"]["correct"] == 16
    assert all(row["tokens"] == 8000 for row in rows.values())
    tex = pub.render_tex(snapshot)
    assert "Descriptive diagnostic" in tex and "Primary outcomes are unmeasured" in tex
    assert "descriptive\\_fast\\_240\\_v1" not in tex
    markdown = pub.render_markdown(snapshot)
    assert "0/16" in markdown and "noninferiority" in markdown
    assert snapshot == pub.build_snapshot([out])


@pytest.mark.parametrize("mutation", ["old_indices", "seeds", "kind", "planned_records"])
def test_fast_rebound_freeze_cannot_change_its_exact_protocol(tmp_path, mutation):
    out = bundle(tmp_path)
    frozen = read(out / "freeze.json")
    if mutation == "old_indices":
        frozen["old_indices"] = [0, 1, 2, 3]
    elif mutation == "seeds":
        frozen["seeds"] = [9, 10]
    elif mutation == "kind":
        frozen["kind"] = "confirmation"
    else:
        frozen["planned_records"] = 239
    save(out / "freeze.json", frozen)
    rebind_audit(out)
    study = pub.build_snapshot([out])["studies"][0]
    assert study["status"] == "invalid" and not study["outcomes_publishable"]
    assert not study["primary_claim"]


@pytest.mark.parametrize("mutation", ["outcome", "group_cost", "complete", "journal", "raw_status"])
def test_fast_incomplete_or_inconsistent_data_never_publish(tmp_path, mutation):
    out = bundle(tmp_path)
    summary = read(out / "summary.json")
    if mutation == "outcome":
        summary["groups"][0]["phases"]["final"]["correct"] += 1
    elif mutation == "group_cost":
        cost = summary["groups"][0]["cost"]
        cost["prompt_tokens"] += 1
        cost["total_tokens"] += 1
    elif mutation == "complete":
        summary["complete"] = False
    else:
        item = read(out / "schedule.json")[0]
        if mutation == "journal":
            path = out / "calls" / item["key"] / "000.json"
            receipt = read(path)
            receipt["state"] = "pending"
            save(path, receipt)
        else:
            path = out / "episodes" / (item["key"] + ".json")
            record = read(path)
            record["trace"]["status"] = "resource_stop"
            save(path, record)
    save(out / "summary.json", summary)
    rebind_audit(out)
    study = pub.build_snapshot([out])["studies"][0]
    assert study["status"] == ("incomplete" if mutation == "complete" else "invalid")
    assert not study["outcomes_publishable"] and not study["primary_claim"]
    assert "descriptive" not in study


def test_fast_test_double_source_is_excluded_before_any_measurement(tmp_path):
    out = bundle(tmp_path)
    frozen = deepcopy(read(out / "freeze.json"))
    frozen["contains_test_double_calls"] = True
    save(out / "freeze.json", frozen)
    study = pub.build_snapshot([out])["studies"][0]
    assert study["status"] == "excluded_test_double" and not study["outcomes_publishable"]
