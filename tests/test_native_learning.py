"""Native lifecycle tests; selected upstream environment is required for runner cases."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.clbench.core import CallUsage, ModelReply
from integrations.clbench.native import load_native
from integrations.clbench.ace import make_ace
from integrations.clbench.witness import make_witness, numeric_scalar, observed_schema_tables, render_bound_sql, terminal_correct


def test_literal_renderer_preserves_sqlite_scalar_types_and_quotes():
    params = {"text": "literal :n and O'Reilly", "n": -8, "real": 2.5, "nil": None}
    source = "SELECT :text AS t, :n AS n, :real AS r, :nil AS x, ':n' AS unchanged"
    rendered = render_bound_sql(source, params)
    with sqlite3.connect(":memory:") as conn:
        assert conn.execute(source, params).fetchall() == conn.execute(rendered).fetchall()
    with pytest.raises(ValueError):
        render_bound_sql("SELECT :x", {"x": True})
    with pytest.raises(ValueError):
        render_bound_sql("SELECT :x", {"x": float("inf")})


def test_scalar_parser_and_feedback_cannot_confuse_incorrect_or_truncation():
    assert numeric_scalar("Query result (1/15 queries used, 14 remaining):\n\nvalue\n-----\n7") == 7
    assert not terminal_correct("Question 1: INCORRECT.\nYour answer: CORRECT!")
    assert terminal_correct("Question 1: CORRECT!\nYour answer: 7")
    with pytest.raises(ValueError):
        numeric_scalar("Query result (1/15 queries used, 14 remaining):\n\nv\n-\n7\n... (showing first 50 rows)")


def test_native_semicolon_free_schema_and_internal_sqlite_metadata():
    schema = "CREATE TABLE first (id INTEGER PRIMARY KEY AUTOINCREMENT, note TEXT DEFAULT 'CREATE TABLE quoted(x)')\n\nCREATE TABLE sqlite_sequence(name,seq)\n\nCREATE TABLE second (value REAL)"
    tables = observed_schema_tables(schema)
    assert set(tables) == {"first", "second"}
    assert "CREATE TABLE quoted(x)" in tables["first"]
    from witness_cl.source_views import lift_source
    view = lift_source("SELECT SUM(value) FROM second", {}, ";\n".join(tables.values()), "Return total value")
    assert view.measure_columns == ("m0",)


@pytest.fixture
def native_api():
    path = os.environ.get("WITNESS_CLBENCH_UPSTREAM")
    if not path or sys.version_info < (3, 13):
        pytest.skip("select pinned upstream in optional Python 3.13 environment")
    pytest.importorskip("litellm")
    return load_native(path)


def task_fixture(api, tmp_path, *, num_instances=3, max_queries=8, first_answer="7"):
    db = tmp_path / "products.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE items (name TEXT, amount INTEGER)")
        # The real benchmark's .schema concatenates multiple un-terminated
        # CREATE statements and includes sqlite_sequence. Exercise that shape.
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY AUTOINCREMENT, note TEXT)")
        conn.executemany("INSERT INTO items VALUES (?, ?)", [("alpha", 7), ("beta", 11), ("gamma", 19)])
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([
        {"question_id": "alpha", "question": "What is the sum for alpha?", "answer": first_answer, "answer_type": "integer"},
        {"question_id": "beta", "question": "What is the sum for beta?", "answer": "11", "answer_type": "integer"},
        {"question_id": "gamma", "question": "How many items have name gamma?", "answer": "1", "answer_type": "integer"},
    ]))
    return api.database.DatabaseExploration(db_path=str(db), questions_path=str(questions),
                                           num_instances=num_instances, max_queries_per_question=max_queries)


class ScriptedWitness:
    def __init__(self):
        self.calls = []
        self.index = 0

    def reset(self):
        self.index = 0

    def complete(self, *, messages, response_schema):
        self.calls.append(deepcopy(messages))
        actions = [
            {"action": "QUERY", "content": ".schema"},
            {"action": "QUERY", "content": "SELECT SUM(amount) FROM items WHERE name = 'alpha'"},
            {"action": "ANSWER", "content": "7"},
            {"action": "QUERY", "content": "SELECT SUM(amount) FROM items WHERE name = 'beta'"},
            {"action": "ANSWER", "content": "11"},
            None,
            {"action": "ANSWER", "content": "1"},
        ]
        action = actions[self.index]
        if action is None:
            views = json.loads(messages[0]["content"].split("Visible corroborated relations:\n")[1])
            assert len(views) == 1
            view = views[0]
            action = {"action": "COMPOSE", "program": {"op": "group", "keys": [],
                "input": {"op": "scan", "view": view["view"],
                          "bindings": {key: "gamma" for key in view["bindings"]}},
                "aggregates": [{"name": "answer", "op": "count"}]}}
        self.index += 1
        return ModelReply(action, (CallUsage("fixture", 13, 7),))


def test_actual_native_delayed_preanswer_checks_then_composition(native_api, tmp_path):
    transport = ScriptedWitness()
    system = make_witness(native_api, transport=transport, model="fixture")
    result = native_api.interface.run_task(task_fixture(native_api, tmp_path), system, show_progress=False)
    assert all(outcome.success for outcome in result.instance_outcomes)
    registry = system.registry.snapshot()
    assert len(registry["entries"]) == 1
    entry = registry["entries"][0]
    assert entry["source"]["episode_index"] == 0
    assert entry["corroboration"]["episode_index"] == 1
    assert any(event["event"] == "native_compose" for event in system.events)
    actions = [(json.loads(row.action_json)["action"], row.instance_id) for row in system.experience.records]
    assert actions == [("QUERY", "alpha")] * 4 + [("ANSWER", "alpha")] + [
        ("QUERY", "beta")] * 3 + [("ANSWER", "beta"), ("QUERY", "gamma"), ("ANSWER", "gamma")]
    assert len(transport.calls) == 7  # Checks and pending ANSWER do not invoke the model.
    for messages in transport.calls[:5]:
        assert messages[0]["content"].endswith("Visible corroborated relations:\n[]")
    assert system.get_run_artifacts()["native_certificate"] == "UNKNOWN"
    assert len(system.consume_usage_events()) == 0  # The native runner already drained events.
    assert system.evidence  # Exact observations survive native episode boundaries.
    # A public migration notice removes all previous scopes from executable selection.
    transport.index = 2
    query = native_api.interface.Query(
        prompt="NOTICE: The live database schema or contents may have changed since your earlier exploration.\n\nQuestion 4/4\nWhat is the sum for alpha?\nQueries used so far this question: 0/8",
        response_schema=native_api.database.DatabaseAction, instance_id="after-drift", instance_index=3,
        metadata={"db_path": "SECRET_EVALUATOR_PATH"},
    )
    system.respond(query)
    assert system.epoch == 1 and system.selected_entries == []
    assert "SECRET_EVALUATOR_PATH" not in json.dumps(transport.calls[-1])
    system.reset()
    assert not system.registry.entries and not system.evidence and not system.experience.records


def test_native_insufficient_budget_submits_answer_without_admission_checks(native_api, tmp_path):
    transport = ScriptedWitness()
    system = make_witness(native_api, transport=transport, model="fixture")
    result = native_api.interface.run_task(task_fixture(native_api, tmp_path, num_instances=1, max_queries=2),
                                           system, show_progress=False)
    assert result.instance_outcomes[0].success
    assert len(system.experience.records) == 3
    assert not system.registry.entries and system.pending is None


def test_native_matching_checks_do_not_admit_after_incorrect_feedback(native_api, tmp_path):
    transport = ScriptedWitness()
    system = make_witness(native_api, transport=transport, model="fixture")
    result = native_api.interface.run_task(task_fixture(native_api, tmp_path, num_instances=1, first_answer="8"),
                                           system, show_progress=False)
    assert not result.instance_outcomes[0].success
    assert len(system.experience.records) == 5  # Both checks were charged before the failed answer.
    assert not system.registry.entries and system.pending is None
    assert any(event["event"] == "native_witness_rejected" for event in system.events)


class ScriptedACE:
    def __init__(self):
        self.calls = []

    def reset(self):
        pass

    def complete_phase(self, *, messages, response_schema, phase):
        self.calls.append((deepcopy(messages), phase))
        if "reflector" in phase:
            action = {"bullet_tags": []}
        elif "curator" in phase:
            action = {"reasoning": "visible", "operations": [{"type": "ADD", "section": "OTHERS", "content": "observed prior episode"}]}
        else:
            text = messages[0]["content"]
            answer = "1" if "name gamma?" in text else "11" if "sum for beta?" in text else "7"
            action = {"reasoning": "fixture", "bullet_ids": [], "final_answer": {"action": "ANSWER", "content": answer}}
        return ModelReply(action, (CallUsage("fixture", 10, 5),))


def test_actual_native_ace_roles_observe_update_and_reset(native_api, tmp_path):
    transport = ScriptedACE()
    system = make_ace(native_api, transport=transport, model="fixture")
    result = native_api.interface.run_task(task_fixture(native_api, tmp_path), system, show_progress=False)
    assert all(outcome.success for outcome in result.instance_outcomes)
    assert len(transport.calls) == 9
    assert "products.db" not in json.dumps(transport.calls)
    assert system.memory.updates == 3
    assert "observed prior episode" in system.memory.playbook
    system.reset()
    assert system.memory.updates == 0 and not system.experience.records
