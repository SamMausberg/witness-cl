"""Offline cold-state, accounting and tamper checks; fixtures are never qualified."""

import json
from copy import deepcopy

import pytest

from test_sql_harness_v9 import Client
from tools import qualify_sql_solver as q
from witness_cl.memory_v8 import ACTION_SCHEMA
from witness_cl.model_bounded_reasoning import LocalInferenceBoundedReasoning
from witness_cl.model_v8 import InferenceBudget
from witness_cl.model_v9 import DecodingV9
from witness_cl.model_v9_compatible import LocalInferenceV9Compatible


@pytest.fixture
def frozen(tmp_path):
    config = json.loads(q.CONFIG.read_text())
    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "status": "running",
                "config": config,
                "model_sha256": config["model"]["sha256"],
                "backend_commit": config["backend"]["commit"],
            }
        )
    )
    out = tmp_path / "qualification"
    q.create_freeze(out, runtime)
    return out


@pytest.fixture
def completed(frozen):
    client = Client(lambda messages, phase, index: {"action": "ANSWER", "value": -999})
    result = q.run(frozen, client, allow_test_double=True)
    assert result["saved_records"] == 32
    assert result["required_records_complete"]
    assert not result["qualified"]
    assert all(len(record["messages"]) == 2 for record in client.seen)
    assert all(record["phase"] == "ordinary:solve" for record in client.seen)
    return frozen


def test_all_episodes_run_despite_wrong_answers_and_remain_cold(completed):
    result = q.audit(completed)
    assert result["records_replayed"] == 32
    assert result["network_calls"] == 0 and result["sql_replayed"] == 0
    assert result["cost"]["calls"] == 32 and result["cost"]["total_tokens"] == 320
    assert len(result["groups"]) == 4
    assert all(g["n"] == 8 and g["correct"] == 0 for g in result["groups"])
    assert result["qualified"] is False


def test_each_seed_and_family_must_pass_own_fixed_gate():
    rows = [
        {"seed": seed, "episode_index": i, "reward": float(i % 8 < (7 if i < 8 else 6))}
        for seed in q.SEEDS
        for i in range(16)
    ]
    assert all(g["meets_accuracy_gate"] for g in q.summary(rows))
    rows[-4]["reward"] = 0.0
    assert [g["meets_accuracy_gate"] for g in q.summary(rows)] == [True, True, True, False]
    assert not q.summary(rows[:-1])[-1]["complete"]


def test_unknown_usage_is_retained_without_zero_token_imputation():
    cost = q.accounting([{"model_calls": [{"generation_attempted": True, "usage": None}]}])
    assert cost["calls"] == 1 and cost["unknown_usage_calls"] == 1
    assert cost["total_tokens"] == 0  # Known tokens only, not a claim of zero actual use.


def test_retry_and_source_change_are_rejected(completed, monkeypatch):
    with pytest.raises(ValueError, match="already attempted"):
        q.run(completed, Client(lambda *_: {}), allow_test_double=True)
    monkeypatch.setattr(q, "sources", lambda: {})
    with pytest.raises(ValueError, match="freeze"):
        q.audit(completed)


@pytest.mark.parametrize("target", ["episodes.jsonl", "summary.json", "freeze.json"])
def test_unbound_artifact_tampering_rejected(completed, target):
    path = completed / target
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="integrity"):
        q.audit(completed)


def test_tampered_reward_detected_even_after_rehash(completed):
    path = completed / "episodes.jsonl"
    rows = [json.loads(s) for s in path.read_text().splitlines()]
    rows[0]["reward"] = 1.0
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    q.save(completed / "summary.json", q.summary(rows))
    manifest = json.loads((completed / "manifest.json").read_text())
    manifest["raw_sha256"] = q.sha(path)
    manifest["summary_sha256"] = q.sha(completed / "summary.json")
    q.save(completed / "manifest.json", manifest)
    with pytest.raises(ValueError, match="reward"):
        q.audit(completed)


def test_tampered_cost_and_live_run_rejected(completed):
    path = completed / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["budget"]["total_tokens"] += 1
    q.save(path, manifest)
    with pytest.raises(ValueError, match="accounting"):
        q.audit(completed)
    manifest["status"] = "running"
    q.save(path, manifest)
    with pytest.raises(ValueError, match="integrity"):
        q.audit(completed)


@pytest.fixture
def bounded(monkeypatch):
    for name in ("SEEDS", "LIMITS", "DECODING", "REASONING_BUDGET", "SOURCES"):
        monkeypatch.setattr(q, name, deepcopy(getattr(q, name)))
    q.select_bounded_reasoning()


def test_bounded_policy_has_independent_seeds_limits_and_frozen_native_budget(bounded, frozen):
    cfg = json.loads((frozen / "freeze.json").read_text())
    assert cfg["seeds"] == [95102, 95103]
    assert cfg["limits"]["total_tokens"] == 1500000
    assert cfg["limits"]["solve_output_tokens"] == 4096
    assert cfg["client_config"]["reasoning_budget_tokens"] == 1024
    assert cfg["client_config"]["decoding"]["thinking"] is True
    assert cfg["gate"] == {"warm_minimum": 7, "composition_minimum": 6, "per_family_n": 8}
    q.check_freeze(cfg)
    cfg["client_config"]["reasoning_budget_tokens"] = 1023
    with pytest.raises(ValueError, match="freeze"):
        q.check_freeze(cfg)


def test_bounded_call_auditor_checks_both_native_wire_requests(bounded, tmp_path, monkeypatch):
    def post(self, path, body, timeout):
        if path.endswith("input_tokens"):
            return {"input_tokens": 17}
        return {
            "model": self.model,
            "usage": {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26},
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"action":"ANSWER","value":0}',
                        "reasoning_content": "test",
                    },
                }
            ],
        }

    monkeypatch.setattr(LocalInferenceV9Compatible, "_post", post)
    cfg = q.client_config(json.loads(q.CONFIG.read_text()))
    kwargs = {**cfg, "decoding": DecodingV9(**cfg["decoding"])}
    key = tmp_path / "test.key"
    key.write_text("explicit-offline-test-key")
    c = LocalInferenceBoundedReasoning(key_file=key, **kwargs)
    records = []
    c.complete(
        [{"role": "user", "content": "fixture"}],
        InferenceBudget(),
        phase="ordinary:solve",
        records=records,
        output_tokens=4096,
        response_schema=ACTION_SCHEMA,
    )
    manifest = {"client_config": cfg, "limits": q.LIMITS, "contains_test_double_calls": False}
    trace = {"phase": "ordinary", "arm": "full_history"}
    q.validate_qualification_call(records[0], trace, manifest)
    changed = deepcopy(records[0])
    changed["native_wire_requests"][0]["request_config"]["reasoning_budget_tokens"] = 1023
    with pytest.raises(ValueError, match="native wire"):
        q.validate_qualification_call(changed, trace, manifest)
    changed = deepcopy(records[0])
    changed["native_wire_requests"][1]["messages_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="native wire"):
        q.validate_qualification_call(changed, trace, manifest)
