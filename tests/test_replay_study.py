"""Auditor mutations use temporary marked fixtures, never model experiments."""

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from experiments import stateful_sql as study
from test_sql_harness_v9 import Client, gross_client
from test_sql_harness_v8 import answer_scalar
from tools.replay_study import audit, sha, validate_call, outer_structure
from witness_cl.memory_v8 import ACTION_SCHEMA
from witness_cl.model_v9_compatible import portable_schema, WIRE_SCHEMA_POLICY


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture
def completed(tmp_path):
    directory = tmp_path / "completed"
    study.run_study(
        directory, Client(lambda *_: {"action": "ANSWER", "value": 0}), arms=("evidence",)
    )
    return directory


def rehash_raw(directory):
    manifest = read(directory / "manifest.json")
    manifest["raw_sha256"] = {p.name: sha(p) for p in directory.glob("*.jsonl")}
    write(directory / "manifest.json", manifest)


def test_complete_and_genuine_partial_have_different_status(completed, tmp_path):
    assert audit(completed)["status"] == "passed"
    directory = tmp_path / "partial"
    study.run_study(directory, Client(lambda *_: {"action": "ANSWER", "value": 0}), stop_after=1)
    result = audit(directory)
    assert result["status"] == "partial"
    assert result["schedule"]["saved_records"] == 1
    assert result["schedule"]["planned_records"] == 24
    assert result["records_replayed"] == 1


def test_rebound_truncated_raw_does_not_authenticate_old_summary(completed):
    path = next(completed.glob("*.jsonl"))
    path.write_text(path.read_text().splitlines()[0] + "\n")
    rehash_raw(completed)
    with pytest.raises(ValueError, match="summary differs"):
        audit(completed)


def test_missing_arm_rejected_even_after_rebinding_raw_inventory(tmp_path):
    directory = tmp_path / "study"
    study.run_study(
        directory,
        Client(lambda *_: {"action": "ANSWER", "value": 0}),
        arms=("full_history", "evidence"),
    )
    (directory / "94000-reuse-evidence.jsonl").unlink()
    rehash_raw(directory)
    with pytest.raises(ValueError, match="summary differs"):
        audit(directory)


def test_rebound_summary_cannot_inflate_accuracy(completed):
    summary = read(completed / "summary.json")
    summary[0]["phase_reward"]["ordinary"] = 1.0
    write(completed / "summary.json", summary)
    manifest = read(completed / "manifest.json")
    manifest["summary_sha256"] = sha(completed / "summary.json")
    write(completed / "manifest.json", manifest)
    with pytest.raises(ValueError, match="summary differs"):
        audit(completed)


def test_completed_claim_on_internally_consistent_partial_is_rejected(tmp_path):
    directory = tmp_path / "study"
    study.run_study(
        directory,
        Client(lambda *_: {"action": "ANSWER", "value": 0}),
        arms=("evidence",),
        stop_after=1,
    )
    manifest = read(directory / "manifest.json")
    manifest.update(status="completed", required_records_complete=True)
    write(directory / "manifest.json", manifest)
    with pytest.raises(ValueError, match="incomplete study claims completion"):
        audit(directory)


def test_manifest_episode_count_and_global_ledger_are_recomputed(completed):
    path = completed / "manifest.json"
    original = read(path)
    for mutate, message in [
        (lambda m: m.update(completed_episode_records=7), "episode count"),
        (lambda m: m["total_budget"].update(calls=7), "budget counter"),
        (lambda m: m["total_budget"].update(unknown_usage_calls=1), "budget counter"),
    ]:
        changed = deepcopy(original)
        mutate(changed)
        write(path, changed)
        with pytest.raises(ValueError, match=message):
            audit(completed)


def test_sql_and_admitted_state_replay_on_a_real_fixture(tmp_path):
    directory = tmp_path / "study"
    study.run_study(directory, gross_client(), arms=("fragments",), stop_after=1)
    result = audit(directory)
    assert result["status"] == "partial"
    assert result["records_replayed"] == 1 and result["sql_replayed"] == 4
    assert result["per_arm"]["94000-reuse-fragments"]["admitted"] == 1


def test_optional_pre_run_freeze_binds_external_configuration(completed, tmp_path):
    manifest = read(completed / "manifest.json")
    freeze = {
        k: manifest[k]
        for k in (
            "source_sha256",
            "system_prompt",
            "seeds",
            "arms",
            "limits",
            "conditions",
            "stage",
            "client_config",
        )
    }
    freeze["created_utc"] = datetime.fromtimestamp(
        manifest["started_unix"] - 1, timezone.utc
    ).isoformat()
    path = tmp_path / "pre-run.json"
    write(path, freeze)
    assert audit(completed, path)["schedule"]["pre_run_freeze_sha256"] == sha(path)
    freeze["client_config"]["model"] = "different-pinned-model"
    write(path, freeze)
    with pytest.raises(ValueError, match="pre-run freeze mismatch"):
        audit(completed, path)


def test_unknown_usage_partial_is_retained_and_never_imputed(tmp_path):
    class Failed(Client):
        def complete(self, messages, budget, *, phase, records, output_tokens, response_schema):
            budget.check(7, output_tokens)
            budget.calls += 1
            budget.unknown_usage_calls += 1
            records.append(
                {
                    "messages": deepcopy(messages),
                    "phase": phase,
                    "status": "failed",
                    "generation_attempted": True,
                    "usage": None,
                    "response_schema": deepcopy(response_schema),
                    "test_double": True,
                }
            )
            raise RuntimeError("simulated transport failure with unknown usage")

    directory = tmp_path / "failed"
    study.run_study(directory, Failed(lambda *_: None), arms=("evidence",))
    result = audit(directory)
    assert result["status"] == "partial" and result["records_replayed"] == 0
    assert len(result["partial_records"]) == 1 and result["recorded_totals"]["calls"] == 1
    manifest = read(directory / "manifest.json")
    manifest["total_budget"]["unknown_usage_calls"] = 0
    write(directory / "manifest.json", manifest)
    with pytest.raises(ValueError, match="budget counter mismatch"):
        audit(directory)


@pytest.mark.parametrize("followup_query", [False, True])
def test_correct_episode_does_not_alone_establish_fragment_answer_support(tmp_path, followup_query):
    original = gross_client()
    entry = {}

    def respond(messages, phase, index):
        if index < 4:
            return original.respond(messages, phase, index)
        if phase.endswith(":reflection"):
            return {"proposal": None}
        if index == 4:
            encoded = next(
                m["content"].split("\n", 1)[1]
                for m in messages
                if m["content"].startswith("Learned executable memories")
            )
            entry.update(json.loads(encoded)[0])
            return {
                "action": "COMPOSE",
                "entry": 0,
                "params": entry["witness_params"],
                "outer_sql": "SELECT "
                + ("SUM" if followup_query else "AVG")
                + "(gross) AS answer FROM reused",
                "outer_params": {},
            }
        if index == 5 and followup_query:
            return {
                "action": "QUERY",
                "sql": "SELECT AVG(gross) AS answer FROM (" + entry["sql"] + ")",
                "params": entry["witness_params"],
            }
        return answer_scalar(messages)

    directory = tmp_path / "uses"
    study.run_study(directory, Client(respond), arms=("fragments",), stop_after=2)
    result = audit(directory)
    assert result["status"] == "partial"
    assert len(result["fresh_use_interventions"]) == 1
    use = result["fresh_use_interventions"][0]
    assert use["executed_on_correct_episode"] and use["instance_dependent"]
    assert use["observational_answer_support"] is (not followup_query)
    assert use["later_ordinary_queries"] == int(followup_query)
    assert use["new_outer_structure"] is (not followup_query)
    assert use["model_answer_causal_dependence_established"] is False


def test_composition_structure_normalizes_literal_changes_without_claiming_equivalence():
    a = "SELECT SUM(gross) FROM reused WHERE region = :old AND gross > 4"
    b = " select  sum ( gross ) from reused where region=:new AND gross > 100 "
    assert outer_structure(a) == outer_structure(b)
    assert outer_structure(a) != outer_structure(a.replace("SUM", "AVG"))
    assert outer_structure('SELECT "A B" FROM reused') != outer_structure(
        'SELECT "A  B" FROM reused'
    )


def native_receipt():
    decoding = {
        "temperature": 0.6,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 1.5,
        "seed": 42,
        "thinking": True,
    }
    cfg = {
        "model": "pinned-backbone",
        "context_tokens": 65536,
        "response_mode": "schema",
        "decoding": decoding,
    }
    wire = portable_schema(ACTION_SCHEMA)
    request = {
        "model": cfg["model"],
        **{k: v for k, v in decoding.items() if k != "thinking"},
        "max_tokens": 2048,
        "cache_prompt": False,
        "stream": False,
        "response_format": {"type": "json_object", "schema": wire},
        "chat_template_kwargs": {"enable_thinking": True},
    }
    record = {
        "phase": "ordinary:solve",
        "generation_attempted": True,
        "status": "completed",
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
        "preflight_tokens": 100,
        "max_output_tokens": 2048,
        "host_response_schema": deepcopy(ACTION_SCHEMA),
        "response_schema": wire,
        "wire_schema_policy": WIRE_SCHEMA_POLICY,
        "decoding": deepcopy(decoding),
        "request_config": request,
        "response_model": cfg["model"],
        "content": "{}",
    }
    manifest = {
        "client_config": cfg,
        "limits": {"solve_output_tokens": 2048, "reflection_output_tokens": 4096},
        "contains_test_double_calls": False,
    }
    trace = {"phase": "ordinary", "arm": "evidence"}
    return record, trace, manifest


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda c: c.update(response_model="other-model"), "model identity"),
        (lambda c: c["decoding"].update(thinking=False), "decoding differs"),
        (lambda c: c["request_config"].update(cache_prompt=True), "request differs"),
        (lambda c: c.update(preflight_tokens=101), "shorter than preflight"),
        (
            lambda c: c["usage"].update(completion_tokens=2049, total_tokens=2149),
            "output allowance",
        ),
        (lambda c: c.update(inference_seconds=-1.0), "nonnegative"),
        (lambda c: c.update(test_double=True), "test-double marker"),
        (lambda c: c.update(generation_attempted=False), "unattempted generation"),
    ],
)
def test_native_receipt_configuration_and_accounting_tampering(mutation, message):
    call, trace, manifest = native_receipt()
    validate_call(call, trace, manifest)
    mutation(call)
    with pytest.raises(ValueError, match=message):
        validate_call(call, trace, manifest)
