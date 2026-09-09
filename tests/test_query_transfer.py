"""Marked scripted-client integration tests, never empirical model scores."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from experiments import query_transfer as study
from test_sql_harness_v8 import ScriptedClient
from witness_cl.model_v8 import InferenceBudget
from witness_cl.query_memory import ARMS, QueryMemory, canonical, digest
from witness_cl.source_views import UnsupportedSource, lift_source
from witness_cl.sql_env_v8 import PublicEpisode, _Table
from witness_cl.sql_env_v9 import make_stream


TOTAL_SQL = "SELECT COALESCE(SUM(amount),0) AS total FROM amounts"


def fixture_spec(values=(1, 2), *, expected=None):
    """Small SQL fixture whose canned actions never read evaluator fields."""
    table = _Table("amounts", (("amount", "INTEGER"),), tuple((x,) for x in values))
    catalog = _Table(
        "catalog",
        (("table_name", "TEXT"), ("column_name", "TEXT"), ("description", "TEXT")),
        (("amounts", "amount", "Amount in dollars; NULL means zero."),),
    )
    base = make_stream(94001, "reuse").ordinary[0]
    return replace(
        base,
        _tables=(table, catalog),
        _public=PublicEpisode(
            "Return the total amount in dollars.", table.ddl + "\n" + catalog.ddl
        ),
        _expected=sum(x or 0 for x in values) if expected is None else expected,
    )


def query(sql=TOTAL_SQL, *, params=None, answer=True):
    return {
        "action": "QUERY",
        "sql": sql,
        "params": {} if params is None else params,
        "answer": answer,
    }


def client(actions):
    return ScriptedClient(lambda _messages, _phase, i: actions[min(i, len(actions) - 1)])


def run(memory=None, actions=None, *, spec=None, phase="ordinary", learn=True, nonce="snapshot-a"):
    memory = QueryMemory("sql_archive") if memory is None else memory
    scripted = client([query()] if actions is None else actions)
    budget = InferenceBudget()
    trace = study.execute_episode(
        fixture_spec() if spec is None else spec,
        memory,
        scripted,
        budget,
        phase=phase,
        learn=learn,
        episode_nonce=nonce,
    )
    assert all(record.get("test_double") is True for record in trace["model_calls"])
    return trace, memory, scripted, budget


def selected_payload(messages):
    return next(
        json.loads(message["content"].split("\n", 1)[1])
        for message in messages
        if message["content"].startswith("Prior own experience.")
    )


def view_program(key):
    return {
        "action": "PROGRAM",
        "answer": True,
        "program": {
            "op": "group",
            "input": {"op": "scan", "view": key},
            "keys": [],
            "aggregates": [{"name": "answer", "op": "sum", "expr": {"op": "col", "name": "m0"}}],
        },
    }


@pytest.mark.parametrize("arm", ARMS)
def test_host_answers_exact_current_sql_scalar_without_rounding(arm):
    trace, _, _, budget = run(
        QueryMemory(arm),
        [query("SELECT SUM(amount)/7.0 FROM amounts")],
        spec=fixture_spec(expected=3 / 7),
    )
    assert trace["status"] == "completed" and trace["reward"] == 1.0
    assert trace["answer"] == 3 / 7
    answered = trace["queries"][trace["answer_query_index"]]
    assert answered["rows"] == ((3 / 7,),)
    assert budget.calls == 1


def test_fresh_answer_is_executed_again_despite_old_history():
    _, memory, _, _ = run(QueryMemory("full_history"))
    trace, _, scripted, _ = run(
        memory, spec=fixture_spec((5, 7)), learn=False, phase="old_before", nonce="snapshot-b"
    )
    assert trace["answer"] == 12 and trace["reward"] == 1.0
    assert trace["select_attempts"] == 1
    assert "snapshot-a" in canonical(scripted.seen[0]["messages"])
    assert "snapshot-b" in canonical(scripted.seen[0]["messages"])


def test_direct_old_numeric_answer_is_rejected_and_charged():
    trace, _, _, _ = run(actions=[{"action": "ANSWER", "value": 3, "answer": True}, query()])
    assert trace["answer"] == 3 and trace["reward"] == 1.0
    assert trace["select_attempts"] == 2
    assert trace["queries"][0]["purpose"] == "invalid_action"
    assert trace["answer_query_index"] == 1


def test_current_execution_does_not_claim_constant_query_semantic_correctness():
    trace, _, _, _ = run(actions=[query("SELECT 3")], spec=fixture_spec((5, 7)))
    assert trace["status"] == "completed" and trace["answer"] == 3
    assert trace["reward"] == 0.0


@pytest.mark.parametrize("arm", ARMS)
def test_declared_tools_match_response_schema(arm):
    trace, _, scripted, _ = run(QueryMemory(arm))
    current = json.loads(scripted.seen[0]["messages"][-1]["content"])
    expected = {"QUERY", "PROGRAM"} if arm == "view_program" else {"QUERY"}
    assert set(current["available_actions"]) == expected
    schema = trace["model_calls"][0]["response_schema"]
    branches = schema.get("anyOf", [schema])
    assert {branch["properties"]["action"]["const"] for branch in branches} == expected


@pytest.mark.parametrize("arm", ["full_history", "sql_archive", "view_text"])
def test_unavailable_program_cannot_execute_and_consumes_an_attempt(arm):
    trace, _, _, _ = run(QueryMemory(arm), [view_program("invented"), query()])
    assert trace["status"] == "completed" and trace["reward"] == 1.0
    assert trace["queries"][0]["purpose"] == "unavailable_action"
    assert trace["queries"][0]["error"] is not None
    assert trace["select_attempts"] >= 2


@pytest.mark.parametrize("phase", ["old_before", "old_after", "final"])
@pytest.mark.parametrize("arm", ARMS)
def test_frozen_panels_cannot_mutate_memory_or_admit(phase, arm):
    _, memory, _, _ = run(QueryMemory(arm))
    before = deepcopy(memory.snapshot())
    trace, _, _, _ = run(memory, phase=phase, learn=False, spec=fixture_spec((5, 7)))
    assert trace["reward"] == 1.0
    assert trace["before_memory_digest"] == trace["after_memory_digest"]
    assert memory.snapshot() == before
    assert not any(row["learning_check"] for row in trace["queries"])
    assert "admission" not in trace
    with pytest.raises(ValueError, match="cannot learn"):
        run(memory, phase=phase, learn=True)


@pytest.mark.parametrize("arm", ["view_text", "view_program"])
def test_admission_executes_two_real_checks_under_same_select_cap(arm):
    trace, memory, _, budget = run(QueryMemory(arm))
    assert trace["admission"]["status"] == "admitted"
    assert len(memory.views) == 1
    assert trace["select_attempts"] == 3
    assert [q["attempt"] for q in trace["queries"]] == [1, 2, 3]
    assert [q["purpose"] for q in trace["queries"]] == [
        "ordinary",
        "source_reconstruction",
        "empty_relation_check",
    ]
    assert [q["learning_check"] for q in trace["queries"]] == [False, True, True]
    assert trace["queries"][1]["rows"] == ((3,),)
    assert trace["queries"][2]["rows"] == ((0,),)
    assert budget.calls == 1  # Host checks are not extra model inference.


def test_six_model_actions_plus_two_checks_exactly_exhaust_select_budget():
    actions = [query("SELECT * FROM catalog", answer=False)] * 5 + [query()]
    trace, memory, _, budget = run(QueryMemory("view_program"), actions)
    assert trace["admission"]["status"] == "admitted"
    assert trace["select_attempts"] == 8
    assert [q["attempt"] for q in trace["queries"]] == list(range(1, 9))
    assert len(memory.views) == 1 and budget.calls == 6


def test_empty_dependence_must_fail_when_source_answer_is_zero():
    trace, memory, _, _ = run(QueryMemory("view_program"), spec=fixture_spec((0, 0)))
    assert trace["answer"] == 0 and trace["reward"] == 1.0
    assert trace["admission"]["status"] == "dependence_rejected"
    assert not memory.views and trace["select_attempts"] == 3


def test_incorrect_or_unsupported_source_cannot_be_admitted():
    wrong, memory, _, _ = run(QueryMemory("view_program"), [query("SELECT 100")])
    assert wrong["admission"]["status"] == "no_correct_direct_source"
    assert not memory.views
    unsupported, memory, _, _ = run(QueryMemory("view_program"), [query("SELECT 3")])
    assert unsupported["reward"] == 1.0 and unsupported["status"] == "completed"
    assert unsupported["admission"]["status"] == "unsupported"
    assert not memory.views and memory.evidence


def test_model_cannot_self_approve_or_supply_source_payload():
    malicious = {**query(), "admission": {"status": "admitted", "view": {"sql": "SELECT 3"}}}
    trace, memory, _, _ = run(QueryMemory("view_program"), [malicious, query("SELECT 3")])
    assert trace["queries"][0]["purpose"] == "invalid_action"
    assert not memory.views


def test_program_compilation_failure_is_charged_and_does_not_abort_episode():
    bad = {
        "action": "PROGRAM",
        "answer": True,
        "program": {"op": "sql", "sql": "SELECT 999 FROM amounts"},
    }
    trace, _, _, _ = run(QueryMemory("view_program"), [bad, query()])
    assert trace["status"] == "completed" and trace["reward"] == 1.0
    assert trace["queries"][0]["purpose"] == "invalid_program"
    assert trace["select_attempts"] == 4


@pytest.mark.parametrize("fail_empty", [False, True])
def test_source_reconstruction_compilation_failure_does_not_erase_answer(monkeypatch, fail_empty):
    real = study.reconstruct

    def fail(view, *, empty=False):
        if empty == fail_empty:
            raise UnsupportedSource("generated SQL exceeds its bounded language")
        return real(view, empty=empty)

    monkeypatch.setattr(study, "reconstruct", fail)
    trace, memory, _, _ = run(QueryMemory("view_program"))
    assert trace["status"] == "completed" and trace["reward"] == 1.0
    assert trace["admission"]["status"] in {"unsupported", "compilation_rejected"}
    assert not memory.views and memory.evidence
    assert trace["select_attempts"] == (2 if fail_empty else 1)


def test_only_the_accepted_terminal_query_gets_answer_feedback():
    trace, memory, _, _ = run(actions=[query("SELECT amount FROM amounts"), query()])
    assert trace["reward"] == 1.0 and trace["answer_query_index"] == 1
    rejected, accepted = memory.evidence
    assert rejected["terminal"] is False
    assert rejected["terminal_answer_correct"] is None
    assert accepted["terminal"] is True and accepted["terminal_answer_correct"] is True


def test_view_text_and_program_store_and_show_the_same_payload():
    _, text, _, _ = run(QueryMemory("view_text"))
    _, program, _, _ = run(QueryMemory("view_program"))
    assert text.active_payload() == program.active_payload()
    spec = fixture_spec((5, 7))
    text_messages, text_views = text.prefix(spec._public.question, spec._public.schema)
    program_messages, program_views = program.prefix(spec._public.question, spec._public.schema)
    assert text_messages == program_messages
    assert [v.to_dict() for v in text_views] == [v.to_dict() for v in program_views]
    assert selected_payload(text_messages) == selected_payload(program_messages)


def test_views_replay_on_fresh_data_without_numeric_applicability_guard():
    _, memory, _, _ = run(QueryMemory("view_program"))
    view = memory.views[0][1]
    before = memory.state_digest()
    trace, _, _, _ = run(
        memory, [view_program(view.key)], spec=fixture_spec((5, 7)), phase="final", learn=False
    )
    assert trace["reward"] == 1.0 and trace["answer"] == 12
    assert trace["select_attempts"] == 1
    assert trace["actions"][0]["compiled"]["measure_references"] == [(view.key, "m0")]
    assert trace["before_memory_digest"] == trace["after_memory_digest"] == before


def test_changed_public_schema_excludes_old_view():
    _, memory, _, _ = run(QueryMemory("view_program"))
    spec = fixture_spec()
    assert memory.selected(spec._public.question, spec._public.schema)
    assert (
        memory.selected(spec._public.question, spec._public.schema + "\nCREATE TABLE extra(x);")
        == []
    )


def test_compact_archive_keeps_documentation_and_feedback_but_not_numeric_rows():
    trace, memory, _, _ = run(actions=[query("SELECT * FROM catalog", answer=False), query()])
    assert len(memory.evidence) == 2
    docs, numeric = memory.evidence
    assert docs["text_rows"] == (("amounts", "amount", "Amount in dollars; NULL means zero."),)
    assert "rows" not in numeric and "text_rows" not in numeric
    assert numeric["sql"] == TOTAL_SQL and numeric["terminal_answer_correct"] is True
    assert trace["queries"][1]["rows"] == ((3,),)  # Complete audit archive retains actual data.
    wrong, memory, _, _ = run(actions=[query("SELECT 100")])
    assert wrong["reward"] == 0.0
    assert memory.evidence[0]["terminal_answer_correct"] is False


def test_query_memory_prefix_contains_only_public_own_experience():
    _, memory, _, _ = run(
        QueryMemory("view_program"), [query("SELECT * FROM catalog", answer=False), query()]
    )
    _, _, scripted, _ = run(memory, phase="final", learn=False)
    visible = canonical(scripted.seen[0]["messages"])
    for forbidden in (
        "semantic_recipe",
        "data_seed",
        "names_seed",
        '"_expected"',
        '"evaluator"',
        "_gold_sql",
        "feedback_reward",
        "source_query_index",
    ):
        assert forbidden not in visible
    assert "amounts" in visible and "source_derived_views" in visible


def test_compact_memory_eviction_is_bounded_and_recorded(monkeypatch):
    import witness_cl.query_memory as memory_module

    monkeypatch.setattr(memory_module, "MAX_ACTIVE_BYTES", 650)
    memory = QueryMemory("sql_archive")
    for i in range(6):
        run(
            memory,
            [query("SELECT COALESCE(SUM(amount),0)+:offset FROM amounts", params={"offset": i})],
            spec=fixture_spec(expected=3 + i),
            nonce=f"snapshot-{i}",
        )
    assert memory.active_bytes() <= 650
    assert any(event["event"] == "evidence_evicted" for event in memory.events)
    assert len(memory.evidence) < 6
    assert memory.evidence[-1]["params"] == {"offset": 5}


def test_view_count_cap_eviction_is_shared_between_text_and_program(monkeypatch):
    import witness_cl.query_memory as memory_module

    monkeypatch.setattr(memory_module, "MAX_VIEWS", 1)
    memories = []
    spec = fixture_spec()
    for arm in ("view_text", "view_program"):
        memory = QueryMemory(arm)
        for divisor in (1.0, 2.0):
            sql = f"SELECT COALESCE(SUM(amount/{divisor}),0) FROM amounts"
            view = lift_source(sql, {}, spec._public.schema, "A fixture source")
            memory.add_view(spec._public.schema, view, evidence_digest=digest({"fixture": divisor}))
        assert len(memory.views) == 1
        assert any(
            event["event"] == "view_evicted" and event["reason"] == "count"
            for event in memory.events
        )
        memories.append(memory)
    assert memories[0].active_payload() == memories[1].active_payload()


@pytest.mark.parametrize(
    "payload",
    [
        '{"action":"QUERY","sql":"SELECT 1","params":{"x":1e999},"answer":true}',
        '{"action":"QUERY","sql":"SELECT 1","params":{},"answer":true,"answer":false}',
        '{"action":"QUERY","sql":"SELECT 1","params":{},"answer":1}',
    ],
)
def test_malformed_action_cannot_poison_memory_serialization(payload):
    trace, memory, _, _ = run(actions=[payload, query()])
    assert trace["status"] == "completed" and trace["reward"] == 1.0
    assert trace["queries"][0]["purpose"] == "invalid_action"
    assert memory.evidence


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT CAST(SUM(amount) AS TEXT) FROM amounts",
        "SELECT '3' AS description",
        "WITH catalog AS (SELECT '3' AS description) SELECT description FROM catalog",
    ],
)
def test_text_encoded_numeric_results_are_not_retained_as_documentation(sql):
    trace, memory, _, _ = run(actions=[query(sql, answer=False), query()])
    assert trace["status"] == "completed"
    assert trace["queries"][0]["rows"]
    assert "text_rows" not in memory.evidence[0]


def test_direct_catalog_projection_is_preserved_exactly():
    _, memory, _, _ = run(actions=[query("SELECT description FROM catalog", answer=False), query()])
    assert memory.evidence[0]["text_rows"] == (("Amount in dollars; NULL means zero.",),)


def test_reconstruction_mismatch_cannot_be_admitted(monkeypatch):
    monkeypatch.setattr(study, "reconstruct", lambda _view, **_kwargs: ("SELECT 100", {}))
    trace, memory, _, _ = run(QueryMemory("view_program"))
    assert trace["status"] == "completed" and trace["reward"] == 1.0
    assert trace["admission"]["status"] == "reconstruction_rejected"
    assert trace["select_attempts"] == 2 and not memory.views
    assert memory.evidence[0]["terminal_answer_correct"] is True


def test_only_the_host_selected_terminal_source_is_eligible():
    trace, memory, _, _ = run(QueryMemory("view_program"), [query(answer=False), query("SELECT 3")])
    assert trace["status"] == "completed" and trace["reward"] == 1.0
    assert trace["answer_query_index"] == 1
    assert trace["admission"]["status"] == "unsupported"
    assert not memory.views


def test_invalid_utf8_response_is_rejected_without_losing_following_valid_answer():
    invalid = '{"action":"QUERY","sql":"SELECT \'\ud800\'","params":{},"answer":true}'
    trace, memory, _, _ = run(actions=[invalid, query()])
    assert trace["status"] == "completed" and trace["reward"] == 1.0
    assert trace["queries"][0]["purpose"] == "invalid_action"
    assert memory.evidence
    canonical(trace).encode("utf-8")
