"""Scripted end-to-end mechanism tests; no empirical model scores."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from experiments import delayed_sql as study
from test_sql_harness_v8 import ScriptedClient
from witness_cl.delayed_memory import DelayedMemory
from witness_cl.model_v8 import InferenceBudget
from witness_cl.query_memory import QueryMemory, canonical
from witness_cl.relational_program import compile_program
from witness_cl.sql_env_v8 import PublicEpisode, _Table
from witness_cl.sql_env_v9 import make_stream, open_episode


def fixture(tier="Gold", values=(1, 2), *, average=False, convention="dollars"):
    table = _Table("amounts", (("amount", "INTEGER"), ("tier", "TEXT")),
                   tuple((value, tier) for value in values) + ((123, "Unused"),))
    catalog = _Table("catalog", (("table_name", "TEXT"), ("column_name", "TEXT"),
                                 ("description", "TEXT")),
                     (("amounts", "amount", f"Values are {convention}; NULL means zero."),
                      ("amounts", "tier", "Customer tier.")))
    base = make_stream(94001, "reuse").ordinary[0]
    expected = sum(values) * 2.0 / (len(values) if average else 1)
    return replace(base, _tables=(table, catalog), _expected=expected,
                   _public=PublicEpisode(
                       f"Return {'average' if average else 'total'} amount times two for {tier}.",
                       table.ddl + "\n" + catalog.ddl))


def query(tier="Gold", *, sql=None, answer=True):
    return {"action": "QUERY", "sql": sql or
            f"SELECT COALESCE(SUM(amount * 2.0),0) FROM amounts WHERE tier='{tier}'",
            "params": {}, "answer": answer}


def run(memory=None, *, spec=None, actions=None, phase="ordinary", nonce=None,
        raw_responses=False):
    memory = DelayedMemory() if memory is None else memory
    actions = [query()] if actions is None else actions
    def response(_messages, _phase, index):
        action = actions[min(index, len(actions) - 1)]
        if raw_responses or hasattr(memory, "decode_generator"):
            return action
        return {"reasoning": "Use the observed catalog for this software fixture.",
                "final_answer": action}

    client = ScriptedClient(response)
    budget = InferenceBudget()
    ordinal = getattr(memory, "ordinary_count", len(memory.events))
    trace = study.execute_episode(
        fixture() if spec is None else spec, memory, client, budget,
        phase=phase, learn=phase == "ordinary", episode_nonce=nonce or f"episode-{ordinal}")
    assert all(record.get("test_double") is True for record in trace["model_calls"])
    return trace, memory, client, budget


def compose(view, *, action="COMPOSE", operation="avg"):
    return {"action": action, "answer": True, "program": {
        "op": "group", "input": {"op": "scan", "view": view.key}, "keys": [],
        "aggregates": [{"name": "answer", "op": operation,
                        "expr": {"op": "col", "name": "m0"}}]}}


def ready_memory(arm="delayed"):
    _, memory, _, _ = run(DelayedMemory(arm))
    trace, _, _, _ = run(memory, spec=fixture("Silver", (4, 6)), actions=[query("Silver")])
    assert trace["admission"]["status"] == "corroborated"
    return memory


def test_three_episode_chain_has_independent_corroboration_fresh_composition_and_causal_flip():
    first, memory, _, _ = run()
    assert first["reward"] == 1 and first["admission"]["status"] == "provisional"
    assert first["select_attempts"] == 4  # Catalog, direct SQL, reconstruction, empty.
    original = memory.registry.entries[0].view
    second, _, client, _ = run(memory, spec=fixture("Silver", (4, 6)), actions=[query("Silver")])
    assert second["reward"] == 1 and second["admission"]["status"] == "corroborated"
    assert second["selected_views"] == []
    assert any('"source_derived_views":[]' in message["content"]
               for message in client.seen[0]["messages"])
    assert second["admission"]["checked_view_key"] == original.key
    assert memory.registry.entries[0].view is original
    future_spec = fixture(values=(7, 11), average=True)
    third, _, _, _ = run(memory, spec=future_spec, actions=[compose(original)], phase="final")
    assert third["reward"] == 1 and third["answer"] == 18
    assert third["select_attempts"] == 2 and len(third["selected_views"]) == 1
    assert third["queries"][1]["purpose"] == "fragment_composition"
    assert third["before_memory_digest"] == third["after_memory_digest"]
    fixed = third["actions"][0]["executed_program"]
    intervened = compile_program(fixed, [original], measure_overrides={original.key: {"m0": 0}})
    with open_episode(future_spec) as session:
        result = session.query(intervened.prepared.sql, intervened.prepared.parameters)
        assert result.rows == ((0.0,),)
        assert session.answer(result.rows[0][0]).reward == 0.0
    without = deepcopy(memory)
    without.registry.entries.clear()
    deleted, _, _, _ = run(without, spec=future_spec, actions=[compose(original)], phase="final")
    assert deleted["reward"] == 0 and deleted["status"] == "no_valid_answer"


@pytest.mark.parametrize("arm", ["full_history", "sql_archive", "delayed", "immediate", "view_text"])
def test_every_arm_pays_for_and_sees_same_current_catalog(arm):
    memory = DelayedMemory(arm) if arm in {"delayed", "immediate", "view_text"} else QueryMemory(arm)
    trace, _, client, _ = run(memory)
    assert trace["queries"][0]["purpose"] == "compatibility_catalog"
    assert trace["queries"][0]["attempt"] == 1 and trace["queries"][0]["host_issued"]
    assert trace["compatibility"]["status"] == "observed"
    assert "Values are dollars" in canonical(client.seen[0]["messages"])
    schema = trace["model_calls"][0]["response_schema"]
    assert set(schema["properties"]) == {"reasoning", "final_answer"}
    assert schema["properties"]["final_answer"] == study.action_schema(arm)


def test_same_binding_or_same_answer_or_wrong_feedback_cannot_promote():
    for tier, values, sql in [("Gold", (3, 4), None), ("Silver", (1, 2), None),
                              ("Silver", (4, 6), "SELECT 9")]:
        _, memory, _, _ = run()
        trace, _, _, _ = run(memory, spec=fixture(tier, values), actions=[query(tier, sql=sql)])
        assert memory.registry.entries[0].state == "provisional"
        assert trace["admission"]["status"] != "corroborated"


def test_changed_catalog_excludes_old_views_without_numeric_guard():
    memory = ready_memory()
    view = memory.registry.entries[0].view
    trace, _, _, _ = run(memory, spec=fixture(values=(7, 11), average=True, convention="cents"),
                         actions=[compose(view)], phase="final")
    assert trace["selected_views"] == [] and trace["reward"] == 0
    assert not any(q["purpose"] == "applicability_check" for q in trace["queries"])


@pytest.mark.parametrize("phase", ["old_before", "old_after", "final"])
def test_frozen_panels_cannot_provision_or_corroborate(phase):
    _, memory, _, _ = run()
    before = deepcopy(memory.snapshot())
    trace, _, _, _ = run(memory, spec=fixture("Silver", (4, 6)), actions=[query("Silver")], phase=phase)
    assert trace["reward"] == 1 and memory.snapshot() == before
    assert "admission" not in trace
    assert all(not query["learning_check"] for query in trace["queries"])


def test_text_control_has_identical_delayed_lifecycle_payload_but_only_direct_queries():
    text = ready_memory("view_text")
    program = ready_memory()
    assert text.active_payload() == program.active_payload()
    view = text.registry.entries[0].view
    trace, _, _, _ = run(text, actions=[compose(view), query()], phase="final")
    assert trace["queries"][1]["purpose"] == "unavailable_action" and trace["reward"] == 1


def test_five_model_actions_and_two_learning_checks_fit_shared_eight_select_allowance():
    actions = [query(sql="SELECT COUNT(*) FROM amounts", answer=False)] * 4 + [query()]
    trace, memory, _, budget = run(actions=actions)
    assert trace["admission"]["status"] == "provisional"
    assert trace["select_attempts"] == 8 and budget.calls == 5
    assert [q["attempt"] for q in trace["queries"]] == list(range(1, 9))
    assert memory.ordinary_count == 1


@pytest.mark.parametrize("action", ["COMPOSE", "PROGRAM"])
def test_closed_composition_aliases_use_identical_compiler(action):
    memory = ready_memory()
    trace, _, _, _ = run(memory, spec=fixture(values=(7, 11), average=True),
                         actions=[compose(memory.registry.entries[0].view, action=action)], phase="final")
    assert trace["reward"] == 1 and trace["actions"][0]["compiled"]["measure_references"]


def test_checkpoint_resume_keeps_future_selection_and_memory_digests():
    memory = ready_memory()
    restored = DelayedMemory.from_snapshot(json.loads(json.dumps(memory.snapshot())))
    view = memory.registry.entries[0].view
    original, _, _, _ = run(memory, spec=fixture(values=(7, 11), average=True),
                            actions=[compose(view)], phase="final")
    resumed, _, _, _ = run(restored, spec=fixture(values=(7, 11), average=True),
                           actions=[compose(view)], phase="final")
    assert resumed["selected_views"] == original["selected_views"]
    assert resumed["answer"] == original["answer"]
    assert resumed["after_memory_digest"] == original["after_memory_digest"]
    _, history, _, _ = run(QueryMemory("full_history"))
    assert QueryMemory.from_snapshot(json.loads(json.dumps(history.snapshot()))).state_digest() == history.state_digest()


def test_ace_official_generator_and_two_updates_are_charged_and_panels_remain_frozen():
    from witness_cl.ace_memory import ACEMemory

    actions = [
        {"reasoning": "Use current SQL.", "bullet_ids": [], "final_answer": query()},
        {"reflection": "Correct current-query answer.", "bullet_tags": []},
        {"reasoning": "Retain observed convention.", "operations": [
            {"type": "ADD", "section": "CODE SNIPPETS & TEMPLATES",
             "content": "For this schema, twice the amount is amount * 2.0."}]},
    ]
    trace, memory, client, budget = run(ACEMemory(), actions=actions)
    assert trace["status"] == "completed" and trace["reward"] == 1
    assert budget.calls == 3 and memory.updates == 1 and memory.pending is None
    assert trace["after_memory_digest"] == memory.state_digest()
    assert trace["model_calls"][0]["response_schema"]["properties"]["final_answer"] == study.action_schema("ace")
    assert set(trace["model_calls"][0]["response_schema"]["properties"]) == {
        "reasoning", "bullet_ids", "final_answer"}
    assert trace["actions"][0]["rationale"] == "Use current SQL."
    assert trace["actions"][0]["raw_response"] == trace["model_calls"][0]["content"]
    assert [record["phase"] for record in trace["model_calls"]] == [
        "ordinary:solve", "ace:reflector:reflection", "ace:curator:reflection"]
    assert "Values are dollars" in canonical(client.seen[0]["messages"])
    before = deepcopy(memory.snapshot())
    panel, _, _, budget = run(memory, actions=[actions[0]], phase="final")
    assert panel["reward"] == 1 and budget.calls == 1
    assert memory.snapshot() == before


def test_common_reasoning_response_is_exactly_recorded_and_charged():
    response = {"reasoning": "The catalog states dollars and NULL means zero; use the current tier.",
                "final_answer": query()}
    trace, memory, client, budget = run(actions=[response], raw_responses=True)
    assert trace["response_policy"] == "catalog_reasoning_v2"
    assert trace["reward"] == 1 and trace["admission"]["status"] == "provisional"
    assert trace["actions"][0]["raw_response"] == trace["model_calls"][0]["content"] == canonical(response)
    assert trace["actions"][0]["rationale"] == response["reasoning"]
    assert budget.calls == 1 and budget.total_tokens == 10  # Explicit software-test accounting.
    assert trace["select_attempts"] == 4
    prompt = client.seen[0]["messages"][0]["content"]
    assert "brief plan before issuing SQL" in prompt and "row multiplicity" in prompt
    assert memory.registry.entries[0].view.source_sql == response["final_answer"]["sql"]


@pytest.mark.parametrize("response", [
    query(),
    {"reasoning": 1, "final_answer": query()},
    {"reasoning": "Plan.", "final_answer": query(), "helper": "unrecognized"},
    {"reasoning": "Plan.", "final_answer": []},
    {"reasoning": "Plan.", "final_answer": {**query(), "answer": "yes"}},
    '{"reasoning":"a","reasoning":"b","final_answer":{}}',
    '{"reasoning":"a","final_answer":{"action":"QUERY","sql":"SELECT :x","params":{"x":NaN},"answer":true}}',
])
def test_invalid_common_envelope_consumes_an_attempt_and_preserves_raw_response(response):
    good = {"reasoning": "Apply the observed conventions.", "final_answer": query()}
    trace, _, _, budget = run(actions=[response, good], raw_responses=True)
    assert trace["reward"] == 1 and budget.calls == 2 and budget.total_tokens == 20
    assert trace["queries"][1]["purpose"] == "invalid_action"
    assert trace["queries"][1]["sql"] == "" and trace["select_attempts"] == 5
    assert "invalid" in trace["actions"][0]
    assert trace["actions"][0]["raw_response"] == trace["model_calls"][0]["content"]


def test_reasoning_cannot_execute_sql_or_change_the_source_admitted():
    response = {"reasoning": "SELECT 999999; this quoted text is only a software fixture rationale.",
                "final_answer": query()}
    trace, _, _, _ = run(actions=[response], raw_responses=True)
    assert trace["reward"] == 1 and trace["answer"] == 6
    assert all("999999" not in row["sql"] for row in trace["queries"])


def test_all_eight_campaign_fixture_templates_survive_until_corroboration():
    """Oracle-authored fixture actions test lifecycle capacity, never solver quality."""
    from witness_cl.campaign_env import make_stream as make_campaign

    stream = make_campaign(96100)
    memory = DelayedMemory()
    for index, spec in enumerate(stream.ordinary[:16]):
        trace, _, _, _ = run(memory, spec=spec, nonce=f"capacity-fixture-{index}",
                             actions=[query(sql=spec._gold_sql)])
        assert trace["reward"] == 1
        assert trace["admission"]["status"] == ("provisional" if index < 8 else "corroborated")
        assert memory.active_bytes() <= 65_536
    assert len(memory.registry.entries) == 8
    assert all(entry.corroboration is not None for entry in memory.registry.entries)
    assert len(canonical(memory.snapshot()).encode()) > memory.active_bytes()
    assert not any(event["event"] == "entry_evicted" for event in memory.events)
