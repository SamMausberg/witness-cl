"""Optional tests against unmodified pinned upstream code, not interface mocks.

WITNESS_CLBENCH_UPSTREAM=/path/to/pin python -m pytest tests/test_clbench_native.py
Run in the Python 3.13+ optional environment documented in integrations/clbench.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.clbench.core import CallUsage, ModelReply, TransportFailure
from integrations.clbench.native import inject_transport, load_native, make_bridge


@pytest.fixture(scope="module")
def api():
    path = os.environ.get("WITNESS_CLBENCH_UPSTREAM")
    if not path:
        pytest.skip("optional native CL-Bench checkout not selected")
    if sys.version_info < (3, 13):
        pytest.skip("native CL-Bench requires Python >=3.13")
    pytest.importorskip("litellm", reason="install requirements-native.txt")
    return load_native(path)


class Transport:
    def __init__(self, action=None, fail=None):
        self.calls = []
        self.resets = 0
        self.action = action or {"action": "ANSWER", "content": "7"}
        self.fail = fail

    def complete(self, *, messages, response_schema):
        self.calls.append((deepcopy(messages), deepcopy(response_schema)))
        if self.fail:
            raise self.fail
        return ModelReply(self.action, (CallUsage("fixture", 31, 5),))

    def reset(self):
        self.resets += 1


def control(api, transport, **kwargs):
    system = api.icl.ICLSystem(model="fixture", provider_mode="litellm_chat", **kwargs)
    inject_transport(api, system, transport)
    return system


def offline_counter(system):
    # This deterministic fixture estimator avoids tokenizer/model-network access.
    # It is installed identically on control and bridge; no token-speed claim.
    system._estimate_message_tokens = lambda messages: sum(
        len(json.dumps(m)) // 4 + 4 for m in messages
    )
    system._response_schema_tokens = lambda schema: len(json.dumps(schema.model_json_schema())) // 4
    return system


def query(api, prompt="question", **kwargs):
    return api.interface.Query(
        prompt=prompt, response_schema=api.database.DatabaseAction,
        instance_id="opaque-id", instance_index=0, **kwargs,
    )


def test_actual_upstream_icl_visible_history_and_fifo_parity(api):
    left, right = Transport(), Transport()
    reference = offline_counter(control(api, left, max_tokens=260, reserve_tokens=40))
    bridge = offline_counter(make_bridge(api, transport=right, model="fixture",
                                        max_tokens=260, reserve_tokens=40))
    for step in range(7):
        q = query(api, "question " + str(step) + " x" * 110)
        actual, expected = bridge.respond(q), reference.respond(q)
        assert actual.action == expected.action
        assert actual.metadata["witness_certificate"] == "UNKNOWN"
        obs = api.interface.Observation("feedback " + str(step), instance_complete=step % 2 == 0)
        bridge.observe(obs)
        reference.observe(obs)
        assert bridge.messages == reference.messages
        assert bridge.get_truncation_stats() == reference.get_truncation_stats()
        assert [(e.input_tokens, e.output_tokens) for e in bridge.consume_usage_events()] == [
            (e.input_tokens, e.output_tokens) for e in reference.consume_usage_events()
        ]
    assert left.calls == right.calls
    assert bridge.truncation_count > 0
    assert len(bridge.experience.records) == 7


def test_metadata_and_query_feedback_never_enter_transport(api):
    transport = Transport()
    system = offline_counter(make_bridge(api, transport=transport, model="fixture"))
    q = query(api, metadata={"db_path": "SECRET_PATH", "ground_truth": "SECRET_LABEL"},
              feedback=api.interface.Observation("DO_NOT_DUPLICATE"))
    system.respond(q)
    system.observe(api.interface.Observation(
        "visible observation", metadata={"ground_truth": "HIDDEN_EVALUATOR"},
    ))
    system.respond(query(api, "next"))
    rendered = json.dumps(transport.calls)
    for secret in ("SECRET_PATH", "SECRET_LABEL", "HIDDEN_EVALUATOR", "DO_NOT_DUPLICATE", "opaque-id"):
        assert secret not in rendered
    assert rendered.count("FEEDBACK: visible observation") == 1
    assert "ground_truth" not in json.dumps(system.experience.to_jsonable())


def test_schema_failure_retains_usage_and_has_no_successful_experience(api):
    transport = Transport(action={"action": "ANSWER"})
    system = offline_counter(make_bridge(api, transport=transport, model="fixture"))
    with pytest.raises(RuntimeError, match="LLM call failed"):
        system.respond(query(api))
    events = system.consume_usage_events()
    assert len(events) == 1 and events[0].input_tokens == 31
    assert events[0].metadata["failed"] is True
    assert not system.experience.pending and not system.experience.records


def test_failed_transport_retains_known_cost_and_unknown_is_not_zero(api):
    transport = Transport(fail=TransportFailure("provider failed", (CallUsage("fixture", 9, 2, cost_usd=0.01),)))
    system = offline_counter(make_bridge(api, transport=transport, model="fixture"))
    with pytest.raises(RuntimeError):
        system.respond(query(api))
    assert system.consume_usage_events()[0].cost_usd == 0.01
    transport.fail = OSError("unknown attempt outcome")
    with pytest.raises(RuntimeError):
        system.respond(query(api))
    event = system.consume_usage_events()[0]
    assert event.input_tokens is None and event.total_tokens is None and event.cost_usd is None


def test_reset_clears_memory_and_transport_but_preserves_undrained_usage(api):
    transport = Transport()
    system = offline_counter(make_bridge(api, transport=transport, model="fixture"))
    system.respond(query(api))
    system.observe(api.interface.Observation("visible"))
    system.reset()
    assert system.messages == [] and system.experience.records == ()
    assert system.interaction_count == 0 and transport.resets == 1
    assert len(system.consume_usage_events()) == 1
    assert system.consume_usage_events() == []
    assert system.supports_baseline and not system.parallel_safe


def fixture_task(api, tmp_path, *, num_instances=2):
    db = tmp_path / "fixture.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE items (name TEXT, amount INTEGER)")
        conn.executemany("INSERT INTO items VALUES (?, ?)", [("alpha", 7), ("beta", 11)])
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([
        {"question_id": "fixture-alpha", "question": "What is the amount for alpha?",
         "answer": "7", "sql": "SELECT amount FROM items WHERE name = 'alpha'"},
        {"question_id": "fixture-beta", "question": "What is the amount for beta?",
         "answer": "11", "sql": "SELECT amount FROM items WHERE name = 'beta'"},
    ]))
    return api.database.DatabaseExploration(
        db_path=str(db), questions_path=str(questions), num_instances=num_instances,
        max_queries_per_question=4,
    )


class FixtureTransport(Transport):
    def complete(self, *, messages, response_schema):
        self.calls.append((deepcopy(messages), deepcopy(response_schema)))
        current = messages[-1]["content"]
        if "for alpha?" in current:
            if "Queries used so far this question: 0/4" in current:
                action = {"action": "QUERY", "content": "SELECT amount FROM items WHERE name = 'alpha'"}
            else:
                action = {"action": "ANSWER", "content": "7"}
        else:
            action = {"action": "ANSWER", "content": "intentionally incorrect"}
        return ModelReply(action, (CallUsage("scripted-contract-fixture"),))


@pytest.mark.parametrize("stateless", [False, True])
def test_actual_native_runner_sqlite_feedback_and_instance_reset(api, tmp_path, stateless):
    task = fixture_task(api, tmp_path)
    transport = FixtureTransport()
    system = offline_counter(make_bridge(api, transport=transport, model="fixture"))
    result = api.interface.run_task(task, system, show_progress=False,
                                   reset_between_instances=stateless)
    assert result.score == pytest.approx(0.375)
    assert [o.reward for o in result.instance_outcomes] == [0.75, 0.0]
    assert [o.success for o in result.instance_outcomes] == [True, False]
    assert transport.resets == (2 if stateless else 1)
    records = system.experience.records
    assert len(records) == (1 if stateless else 3)
    # The actual pinned feedback reveals answer after failure, not SQL.
    assert "Correct answer: 11" in records[-1].feedback
    assert "SELECT" not in records[-1].feedback
    assert "11" not in json.dumps(transport.calls[-1])
    before_second_instance = transport.calls[-1][0]
    assert ("CORRECT!" in json.dumps(before_second_instance)) is (not stateless)
    if not stateless:
        assert "Query result" in records[0].feedback
        assert not records[0].instance_complete


def test_retry_usage_records_count_transport_duration_once(api):
    class Retrying(Transport):
        def complete(self, *, messages, response_schema):
            return ModelReply({"action": "ANSWER", "content": "7"},
                              (CallUsage("fixture", 10, 2), CallUsage("fixture", 12, 3)))
    system = offline_counter(make_bridge(api, transport=Retrying(), model="fixture"))
    system.respond(query(api))
    events = system.consume_usage_events()
    assert len(events) == 2
    assert events[0].metadata["transport_wall_seconds"] >= 0
    assert events[1].metadata["transport_wall_seconds"] == 0
    assert sum(e.total_tokens for e in events) == 27
