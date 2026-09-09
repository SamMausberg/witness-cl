"""Software tests for exact common evidence and frozen causal forks."""
from copy import deepcopy
import json

import pytest

from experiments.delayed_sql import execute_episode
from test_delayed_sql import fixture, query
from test_audit_campaign_mechanism import campaign_records as fixture_campaign_records
from test_sql_harness_v8 import ScriptedClient
from tools import campaign_assay as assay
from witness_cl.campaign_io import read, save, sha, usage
from witness_cl.delayed_memory import CompatibilityScope
from witness_cl.model_v8 import InferenceBudget
from witness_cl.query_memory import canonical, digest

campaign_records = fixture_campaign_records


def wrapped_client(action):
    return ScriptedClient(lambda *args: {"reasoning": "Software fixture based on current observations.",
                                        "final_answer": action(*args)})


def donor_episode(memory, tier="Gold", values=(1, 2), index=0):
    client = wrapped_client(lambda *_: query(tier))
    trace = execute_episode(fixture(tier, values), memory, client, InferenceBudget(),
                            phase="ordinary", learn=True, episode_nonce=f"donor-{index}",
                            episode_index=index)
    return trace, client


def setup(out):
    return assay.freeze(out, kind="development", seeds=[829173], runtime_config={},
                        runtime_receipt={}, client_config={"model": "explicit-offline-test-double",
                                                           "context_tokens": 65536},
                        allow_test_double=True)


def test_donor_executes_checks_once_in_same_allowance_and_exposes_every_result():
    memory = assay.DonorMemory()
    first, first_client = donor_episode(memory)
    assert first["admission"]["status"] == "provisional"
    assert first["select_attempts"] == 4
    assert first["selected_views"] == []
    assert len(first_client.seen) == 1
    checks = [r for r in memory.exact_evidence if r["learning_check"]]
    assert len(checks) == 2
    assert checks[0]["result"]["rows"] == ((6.0,),)
    assert checks[1]["result"]["rows"] == ((0,),)
    for check in checks:
        assert any(canonical(check) in message["content"] for message in first["conversation"])
    second, second_client = donor_episode(memory, "Silver", (4, 6), 1)
    assert second["admission"]["status"] == "corroborated"
    assert second["select_attempts"] == 4
    assert len(memory.registry.entries) == 1
    # Every previous check is actually present in the next donor model prompt.
    for check in checks:
        assert any(canonical(check) in message["content"] for message in second_client.seen[0]["messages"])
    restored = assay.DonorMemory.from_snapshot(json.loads(canonical(memory.snapshot())))
    assert restored.state_digest() == memory.state_digest()


def test_forks_share_exact_evidence_and_text_delayed_payload_and_do_not_learn():
    donor = assay.DonorMemory()
    first, _ = donor_episode(donor)
    scope = CompatibilityScope.from_observation(first["schema"], first["queries"][0])
    immediate = assay.ForkMemory("immediate", donor)
    delayed = assay.ForkMemory("delayed", donor)
    text = assay.ForkMemory("view_text", donor)
    control = assay.ForkMemory("sql_archive_extra_evidence", donor)
    prefixes = {m.assay_arm: m.prefix_for_episode(first["question"], first["schema"], scope, 1)
                for m in (immediate, delayed, text, control)}
    assert len(prefixes["immediate"][1]) == 1
    assert prefixes["delayed"][1] == []
    assert prefixes["view_text"] == prefixes["delayed"]
    for memory in (immediate, delayed, text, control):
        assert memory.exact_evidence == donor.exact_evidence
        prefix = prefixes[memory.assay_arm][0][0]["content"]
        for item in donor.exact_evidence:
            assert canonical(item) in prefix
        with pytest.raises(ValueError, match="cannot learn"):
            memory.finish(first, first["conversation"])
    donor_episode(donor, "Silver", (4, 6), 1)
    text = assay.ForkMemory("view_text", donor)
    delayed = assay.ForkMemory("delayed", donor)
    assert text.prefix_for_episode(first["question"], first["schema"], scope, 2) == delayed.prefix_for_episode(first["question"], first["schema"], scope, 2)
    assert len(delayed.prefix_for_episode(first["question"], first["schema"], scope, 2)[1]) == 1


def test_frozen_schedule_independent_seeds_and_paired_probes():
    development, diagnostic = assay.default_seeds("development"), assay.default_seeds("diagnostic")
    assert len(development) == 4 and len(diagnostic) == 64
    assert not set(development) & set(diagnostic)
    plan = assay.planned_records({"seeds": development})
    assert len(plan) == 4 * (24 + 3 * 8 * 4)
    for checkpoint in assay.CHECKPOINTS:
        for seed in development:
            probes = [r for r in plan if r["seed"] == seed and r["checkpoint"] == checkpoint and r["role"] == "probe"]
            assert len(probes) == 32
            assert len({assay.seed_for("sampling", seed, "probe", r["index"], bits=32) for r in probes}) == 8


def test_run_resume_and_offline_replay_preserve_frozen_prefix_costs(tmp_path):
    out = tmp_path / "assay"
    setup(out)
    client = wrapped_client(lambda *_: {"action": "QUERY", "sql": "SELECT 0", "params": {}, "answer": True})
    first = assay.run(out, client, max_new_records=9)
    assert first["status"] == "checkpointed" and len(client.seen) == 9
    second = assay.run(out, client, max_new_records=3)
    assert second["completed_records"] == 12 and len(client.seen) == 12
    assert assay.audit(out)["records_replayed"] == 12
    records = assay.load_records(out)
    probes = [r for r in records if r["role"] == "probe"]
    assert len(probes) == 4
    assert all(r["shared_prefix_ledger"]["cost"]["total_tokens"] == 80 for r in probes)
    assert all(len(r["shared_prefix_ledger"]["records"]) == 8 for r in probes)
    assert len({r["shared_prefix_ledger"]["evidence_sha256"] for r in probes}) == 1
    assert all(r["before_snapshot"] == r["trace"]["memory"] for r in probes)
    summary = read(out / "summary.json")
    assert summary["physical_cost"]["total_tokens"] == 120
    assert all(row["logical_cost_including_full_prefix"]["total_tokens"] == 90
               for row in summary["groups"] if row["checkpoint"] == 8)
    complete = assay.run(out, client)
    assert complete["status"] == "completed" and len(client.seen) == 120
    audited = assay.audit(out)
    assert audited["complete"] and audited["records_replayed"] == 120
    assert all(row["complete"] for row in read(out / "summary.json")["groups"])


def test_assay_does_not_retry_an_uncertain_call_or_accept_modified_prefix(tmp_path):
    out = tmp_path / "assay"
    frozen = setup(out)
    first = assay.planned_records(frozen)[0]
    save(out / "calls" / first["key"] / "000.json", {"state": "pending"})
    client = wrapped_client(lambda *_: query())
    with pytest.raises(ValueError, match="unknown usage"):
        assay.run(out, client, max_new_records=1)
    assert not client.seen
    record = assay.read_record(assay.record_path(out, first))
    assert record["trace"]["status"] == "runtime_failure"
    assert read(out / "summary.json")["physical_cost"]["total_tokens"] is None
    assert read(out / "summary.json")["physical_cost"]["known_total_tokens"] == 0
    changed = deepcopy(record)
    changed["before_snapshot"]["ordinary_count"] = 3
    save(assay.record_path(out, first), changed)
    with pytest.raises(ValueError, match="record hash"):
        assay.read_record(assay.record_path(out, first))


def test_deletion_census_includes_every_eligible_case_and_rerun_preserves_sql(campaign_records):
    before = deepcopy(campaign_records)
    cases, report = assay.all_deletion_cases(campaign_records)
    assert len(cases) == report["structural_event_count"] == 6
    assert all(case["test_double"] is True for case in cases)
    assert [case["key"] for case in cases] == [f"deletion-{i:05d}" for i in range(6)]
    assert campaign_records == before
    case = cases[0]
    frozen = {"source_split": "development", "old_replicates": 8,
              "client_config": {"context_tokens": 65536},
              "limits": {"max_model_calls_per_episode": 5, "solve_output_tokens": 4096}}
    client = wrapped_client(lambda *_: {"action": "QUERY", "sql": "SELECT 0", "params": {}, "answer": True})
    trace = assay.execute_deletion_case(case, client, frozen)
    assert trace["reward"] == 0 and trace["status"] == "completed" and trace["learn"] is False
    assert trace["memory"] == case["before_snapshot"]
    original = campaign_records[case["original_record_ordinal"]]["before_snapshot"]
    assert original["active"]["prior_sql_and_feedback"] == case["before_snapshot"]["active"]["prior_sql_and_feedback"]
    assert not any(row["learning_check"] for row in trace["queries"])
    assert "original_record_sha256" not in canonical(client.seen)


def test_all_deletion_reruns_resume_and_replay_without_regenerating(tmp_path, campaign_records):
    out = tmp_path / "deletion"
    cases, mechanism = assay.all_deletion_cases(campaign_records)
    save(out / "cases.json", cases)
    save(out / "mechanism-selection.json", mechanism)
    frozen = {"experiment": "agent_relation_deletion_v1", "source_sha256": assay.source_inventory(),
              "environment": assay.campaign.environment_fingerprint(),
              "cases_sha256": digest(cases), "planned_cases": len(cases),
              "selection_receipt_sha256": sha(out / "mechanism-selection.json"),
              "source_split": "development", "old_replicates": 8,
              "contains_test_double_calls": True,
              "original_acquisition_and_evaluation_cost": usage([c for r in campaign_records for c in r["trace"]["model_calls"]]),
              "client_config": {"context_tokens": 65536},
              "limits": {"max_model_calls_per_episode": 5, "solve_output_tokens": 4096}}
    save(out / "freeze.json", frozen)
    save(out / "freeze.sha256.json", {"sha256": sha(out / "freeze.json")})
    client = wrapped_client(lambda *_: {"action": "QUERY", "sql": "SELECT 0", "params": {}, "answer": True})
    first = assay.run_deletion(out, client, max_new_records=2)
    assert first["recorded_cases"] == 2 and not first["complete"] and len(client.seen) == 2
    second = assay.run_deletion(out, client)
    assert second["complete"] and len(client.seen) == 6
    assert second["answer_flips_to_wrong"] == 6
    assert second["physical_diagnostic_cost"]["total_tokens"] == 60
    assert second["contains_test_double_calls"] is True
    audit = assay.run_deletion(out, None, replay=True)
    assert audit["complete"] and audit["cases_replayed"] == 6 and audit["model_calls_made"] == 0
