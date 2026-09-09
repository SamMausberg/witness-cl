"""Oracle-authored software fixtures; test doubles never become model evidence."""
from copy import deepcopy
import json

import pytest

from experiments.delayed_sql import execute_episode
from test_sql_harness_v8 import ScriptedClient
from tools.audit_campaign_mechanism import (
    AuditError, audit_records, prepare_deletion_cases, resolve_measure_lineage,
)
from witness_cl.campaign_env import make_episode
from witness_cl.delayed_memory import DelayedMemory
from witness_cl.model_v8 import InferenceBudget
from witness_cl.query_memory import digest
from witness_cl.source_views import lift_source


def direct(sql):
    return {"action": "QUERY", "sql": sql, "params": {}, "answer": True}


def compose(view, *, operation="avg", raw_column=None):
    return {"action": "COMPOSE", "answer": True, "program": {
        "op": "project", "input": {
            "op": "group", "input": {"op": "scan", "view": view.key}, "keys": [],
            "aggregates": [{"name": "value", "op": operation,
                            "expr": {"op": "col", "name": raw_column or "m0"}}]},
        "columns": [{"name": "answer", "expr": {
            "op": "coalesce", "args": [{"op": "col", "name": "value"}, {"op": "lit", "value": 0}]}}]}}


def append_record(records, memory, spec, action, phase, index):
    before = deepcopy(memory.snapshot())
    client = ScriptedClient(lambda *_: {"reasoning": "Software fixture only.", "final_answer": action})
    trace = execute_episode(spec, memory, client, InferenceBudget(), phase=phase,
                            learn=phase == "ordinary", episode_nonce=f"fixture-{phase}-{index}",
                            episode_index=index if phase == "ordinary" else memory.ordinary_count)
    record = {"seed": 96100, "condition": "reuse", "arm": "delayed", "phase": phase,
              "index": index, "trace": trace, "before_snapshot": before, "sampling_seed": 314}
    records.append(record)
    return record


@pytest.fixture(scope="module")
def campaign_records():
    records, memory = [], DelayedMemory()
    for index in range(16):
        spec = make_episode(96100, "development", "reuse", "ordinary", index)
        record = append_record(records, memory, spec, direct(spec._gold_sql), "ordinary", index)
        assert record["trace"]["reward"] == 1
    for index in range(6):
        spec = make_episode(96100, "development", "reuse", "final", index)
        record = append_record(records, memory, spec, compose(memory.registry.entries[index].view),
                               "final", index)
        assert record["trace"]["reward"] == 1
    return records


def test_audit_verifies_full_chains_and_resolves_real_cte_computations(campaign_records):
    report = audit_records(campaign_records)
    assert report["consistent"] and report["records"] == 22
    assert report["structural_event_count"] == 6
    assert report["qualifying_event_count"] == 0 and report["first_five"] == []
    assert report["totals"]["test_double_calls"] == 22
    assert report["totals"]["generation_calls"] == 22
    assert report["totals"]["total_tokens"] == 220
    assert report["model_calls_made"] == 0
    for event in report["events"]:
        assert event["complete_chronological_chain"] and event["three_fresh_data_snapshots"]
        assert event["new_outer_operation"] and event["empty_relation_flips_to_wrong"]
        assert event["computed_measure_flips_to_wrong"]
        proof = event["lineage"]["m0"]
        assert proof["recorded_origin"] == "derived_or_unresolved_column"
        assert proof["status"] == "resolved_computation" and proof["physical_columns"]
        assert event["agent_deletion_rerun"] == "not_performed_by_this_offline_auditor"


def test_deletion_cases_are_deterministic_preserve_evidence_and_do_not_mutate_records(campaign_records):
    before = deepcopy(campaign_records)
    report = audit_records(campaign_records)
    cases = prepare_deletion_cases(campaign_records, report)
    assert len(cases) == 5
    assert [case["index"] for case in cases] == list(range(5))
    for case in cases:
        original = campaign_records[case["original_record_ordinal"]]
        old = DelayedMemory.from_snapshot(original["before_snapshot"])
        new = DelayedMemory.from_snapshot(case["before_snapshot"])
        assert new.evidence == old.evidence
        assert len(new.registry.entries) == len(old.registry.entries) - 1
        assert case["removed_entry_key"] not in {entry.key for entry in new.registry.entries}
        assert case["sampling_seed"] == 314 and case["test_double"] is True
        assert case["learn"] is False
    assert campaign_records == before
    assert prepare_deletion_cases(campaign_records, report, limit=0) == []


@pytest.mark.parametrize("mutation", ["sql_result", "token_sum", "query_charge", "source_hash",
                                      "selected_view", "changed_binding", "freshness", "frozen_state"])
def test_corrupted_evidence_never_passes_audit(campaign_records, mutation):
    records = deepcopy(campaign_records)
    if mutation == "sql_result":
        records[0]["trace"]["queries"][1]["rows"] = [[999]]
    elif mutation == "token_sum":
        records[0]["trace"]["model_calls"][0]["usage"]["total_tokens"] = 99
    elif mutation == "query_charge":
        records[0]["trace"]["queries"][1]["attempt"] = 1
    elif mutation == "source_hash":
        records[0]["trace"]["admission"]["witness"]["source_sha256"] = digest("fabricated")
    elif mutation == "selected_view":
        records[16]["trace"]["selected_views"] = []
    elif mutation == "changed_binding":
        records[8]["trace"]["admission"]["checked_bindings"]["sv_text_0"] = "web"
    elif mutation == "freshness":
        records[16]["trace"]["evaluator"]["data_sha256"] = records[0]["trace"]["evaluator"]["data_sha256"]
    else:
        records[16]["trace"]["memory"]["ordinary_count"] += 1
        records[16]["trace"]["after_memory_digest"] = digest(records[16]["trace"]["memory"])
    with pytest.raises((AuditError, ValueError)):
        audit_records(records)


def test_missing_source_prefix_is_rejected(campaign_records):
    with pytest.raises(AuditError, match="prefix.*missing"):
        audit_records(campaign_records[8:])


def test_duplicate_records_and_broken_continuity_are_rejected(campaign_records):
    with pytest.raises(AuditError, match="duplicate"):
        audit_records([campaign_records[0], campaign_records[0]])
    records = deepcopy(campaign_records)
    records[1]["before_snapshot"]["events"] = []
    records[1]["trace"]["before_memory_digest"] = digest(records[1]["before_snapshot"])
    with pytest.raises(AuditError, match="continuity"):
        audit_records(records)


def test_lineage_does_not_upgrade_physical_copy_or_constant_marker_to_computation():
    schema = "CREATE TABLE amounts(value REAL);"
    physical = lift_source("SELECT SUM(value) FROM amounts", {}, schema, "Sum values")
    copied = lift_source("WITH x AS (SELECT value AS v FROM amounts) SELECT SUM(v) FROM x",
                         {}, schema, "Sum copied values")
    marker = lift_source("SELECT COUNT(*) FROM amounts", {}, schema, "Count rows")
    computed = lift_source("WITH x AS (SELECT value * 2.0 AS v FROM amounts) SELECT SUM(v) FROM x",
                           {}, schema, "Sum twice values")
    for source in (physical, copied):
        report = resolve_measure_lineage(source, "m0", schema)
        assert report["status"] == "resolved_physical_copy"
        assert report["computed_from_physical_columns"] is False
    assert resolve_measure_lineage(marker, "m0", schema)["status"] == "constant_only"
    assert resolve_measure_lineage(computed, "m0", schema)["status"] == "resolved_computation"


def test_json_roundtrip_does_not_change_audit_conclusions(campaign_records):
    report = audit_records(json.loads(json.dumps(campaign_records)))
    assert report["structural_event_count"] == 6
