"""Integration tests use marked scripts, never empirical learner scores."""

import json
from copy import deepcopy

import pytest
from test_sql_harness_v8 import answer_scalar
from test_sql_harness_v9 import Client, gross_client

from experiments import stateful_sql as study
from witness_cl.evidence_memory import ARMS, EvidenceMemory
from witness_cl.memory_v8 import MAX_MEMORY_BYTES, canonical
from witness_cl.model_v8 import InferenceBudget
from witness_cl.sql_env_v9 import make_stream, open_episode


def acquire(arm="fragments"):
    stream = make_stream(94000, "reuse")
    memory = EvidenceMemory(arm, study.V9_SYSTEM)
    client = gross_client()
    trace = study.execute_episode(
        stream.ordinary[0],
        memory,
        client,
        InferenceBudget(),
        phase="ordinary",
        learn=True,
    )
    assert trace["status"] == "completed" and trace["reward"] == 1.0
    return stream, memory, trace, client


def test_integrated_discovery_pays_intervention_and_composes_on_fresh_rows():
    stream, memory, trace, _ = acquire()
    assert trace["discovery_repair"]["status"] == "admitted"
    assert "prototype_only" not in trace["discovery_repair"]
    assert trace["select_attempts"] == 4
    assert trace["queries"][-1]["purpose"] == "abstraction_empty_relation_probe"
    assert len(memory.entries) == 1
    assert len(memory.evidence) == 3  # Two original observations + answer receipt.
    assert all("reused" not in row.get("sql", "") for row in memory.evidence)
    fragment = memory.entries[0].fragment()
    actions = [
        {
            "action": "COMPOSE",
            "entry": 0,
            "params": fragment.original_prepared_query.parameters,
            "outer_sql": "SELECT AVG(gross) AS answer FROM reused",
            "outer_params": {},
        },
        answer_scalar,
    ]
    client = Client(
        lambda messages, phase, i: actions[i](messages) if callable(actions[i]) else actions[i]
    )
    before = memory.snapshot()
    result = study.execute_episode(
        stream.ordinary[1],
        memory,
        client,
        InferenceBudget(),
        phase="final",
        learn=False,
    )
    assert result["reward"] == 1.0 and result["select_attempts"] == 2
    assert memory.snapshot() == before


@pytest.mark.parametrize("arm", ARMS)
def test_shared_initial_prompt_and_frozen_panels(arm):
    stream, memory, _, client = acquire(arm)
    empty = EvidenceMemory("full_history", study.V9_SYSTEM)
    reference_client = gross_client()
    study.execute_episode(
        stream.ordinary[0],
        empty,
        reference_client,
        InferenceBudget(),
        phase="ordinary",
        learn=False,
    )
    assert client.seen[0]["messages"] == reference_client.seen[0]["messages"]
    before = memory.snapshot()
    panel_client = gross_client()
    result = study.execute_episode(
        stream.old_panel[0],
        memory,
        panel_client,
        InferenceBudget(),
        phase="old_after",
        learn=False,
    )
    assert result["reward"] == 1.0
    assert memory.snapshot() == before
    assert all(call["phase"].endswith(":solve") for call in panel_client.seen)


def test_evidence_keeps_exact_observations_without_reflection_or_hidden_metadata():
    _, memory, trace, client = acquire("evidence")
    assert len(client.seen) == 3
    assert not memory.insights and not memory.entries
    assert len(memory.evidence) == 3
    for row, source in zip(memory.evidence, trace["queries"]):
        assert all(row[key] == source[key] for key in ("sql", "params", "columns", "rows"))
    assert "evaluator" not in canonical(memory.evidence)
    assert "94000" not in canonical(memory.evidence)


def test_failed_answer_preserves_observations_and_exact_negative_feedback():
    _, memory, trace, _ = acquire("evidence")
    failure = deepcopy(trace)
    failure.update(answer=-999, reward=0.0, evaluator={"secret": "DO_NOT_RETAIN"})
    fresh = EvidenceMemory("evidence", study.V9_SYSTEM)
    fresh.finish(failure, [])
    assert len(fresh.evidence) == 3
    assert all(row["kind"] == "observation" for row in fresh.evidence[:2])
    assert fresh.evidence[-1] == {
        "kind": "answer_feedback",
        "question": trace["question"],
        "answer": -999,
        "correct": False,
    }
    assert "correct=false" in fresh.prefix(trace["question"])[0][1]["content"]
    assert "DO_NOT_RETAIN" not in canonical(fresh.snapshot())


def test_fifo_cap_and_eviction_are_accounted_for():
    _, memory, trace, _ = acquire("evidence")
    for index in range(20):
        item = deepcopy(trace)
        item["queries"][0]["rows"] = ((str(index) + "x" * 10000,),)
        memory.finish(item, [])
    assert memory.active_memory_bytes() <= MAX_MEMORY_BYTES
    assert any(event["kind"] == "fifo_eviction" for event in memory.events)
    assert memory.memory_bytes() >= memory.active_memory_bytes()
    assert memory.peak_memory_bytes >= memory.memory_bytes()


def test_new_seeds_freeze_and_test_double_scope(tmp_path):
    client = Client(lambda *_: {"action": "ANSWER", "value": 0})
    out = tmp_path / "development"
    result = study.run_study(out, client, arms=("evidence",))
    assert result["version"] == 10 and result["seeds"] == [94000]
    assert result["source_unchanged"] and result["usage_verified"]
    assert result["contains_test_double_calls"] and not result["warm_qualified"]
    assert result["total_budget"]["calls"] == 8
    assert "docs/v10/PROTOCOL.md" in result["source_sha256"]
    with pytest.raises(FileExistsError):
        study.run_study(out, client, arms=("evidence",))
    for seed in (92003, 93000, 94004):
        with pytest.raises(ValueError, match="development"):
            study.run_study(tmp_path / str(seed), client, seeds=(seed,))


@pytest.mark.parametrize("name", ("json_each", "json_tree", "jsonb_each", "jsonb_tree"))
def test_lazy_json_virtual_modules_remain_forbidden(name):
    with open_episode(make_stream(94000, "reuse").ordinary[0]) as session:
        result = session.query(f"SELECT COUNT(*) FROM {name}('[1,2]')")
        assert result.error is not None
        allowed = session.query("WITH x AS (SELECT 1 AS a) SELECT COUNT(*) FROM x")
        assert allowed.error is None and allowed.rows == ((1,),)


def test_saved_transcript_replay_checks_memory_and_detects_prompt_tampering(tmp_path):
    from tools.replay_study import audit, sha

    directory = tmp_path / "study"
    client = Client(lambda *_: {"action": "ANSWER", "value": 0})
    study.run_study(directory, client, arms=("evidence",))
    result = audit(directory)
    assert result["status"] == "passed" and result["records_replayed"] == 8
    raw = next(directory.glob("*.jsonl"))
    traces = [json.loads(line) for line in raw.read_text().splitlines()]
    traces[0]["model_calls"][0]["messages"][-1]["content"] += " hidden answer"
    raw.write_text("".join(canonical(trace) + "\n" for trace in traces))
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["raw_sha256"][raw.name] = sha(raw)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="transcript mismatch"):
        audit(directory)
