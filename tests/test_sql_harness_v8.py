"""Offline protocol tests: scripted public-evidence actions, never model inference.

The scripted solver derives unit/column choices from its own catalog observation.
Evaluator fixtures are used only by the test after the interaction for grading
and independent SQLite replay, never to choose a client action.
"""
from __future__ import annotations

from copy import deepcopy
import json
import sqlite3

import pytest

import experiments.sql_abstractions_v8 as harness
from witness_cl.memory_v8 import ARMS, ExperienceMemory, canonical
from witness_cl.model_v8 import InferenceBudget
from witness_cl.sql_env_v8 import evaluator_expected, make_stream


class ScriptedClient:
    """Fixed local test double with explicit fake-token budget accounting."""
    def __init__(self, respond):
        self.respond = respond
        self.seen = []

    def complete(self, messages, budget, *, phase, records, output_tokens, response_schema=None):
        budget.check(7, output_tokens)
        frozen = deepcopy(messages)
        index = len(self.seen)
        self.seen.append({'messages': frozen, 'phase': phase})
        answer = self.respond(frozen, phase, index)
        content = answer if type(answer) is str else canonical(answer)
        budget.calls += 1
        budget.prompt_tokens += 7
        budget.completion_tokens += 3
        budget.total_tokens += 10
        records.append({'messages': deepcopy(frozen), 'phase': phase, 'content': content,
                        'status': 'completed', 'generation_attempted': True,
                        'usage': {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10},
                        'response_schema': deepcopy(response_schema), 'test_double': True})
        return content


def latest_tool(messages):
    for message in reversed(messages):
        if message['role'] != 'user':
            continue
        try:
            payload = json.loads(message['content'])
        except (ValueError, TypeError):
            continue
        if 'tool_result' in payload:
            return payload['tool_result']
    raise AssertionError('no visible tool observation')


def query(sql, params=None):
    return {'action': 'QUERY', 'sql': sql, 'params': {} if params is None else params}


def answer_scalar(messages, *_):
    result = latest_tool(messages)
    assert result['error'] is None
    return {'action': 'ANSWER', 'value': result['rows'][0][0]}


def normalized_gross_from_catalog(result):
    """No generator imports, family labels, stored recipes or evaluator SQL."""
    assert result['error'] is None and result['truncated'] is False
    rows = [dict(zip(result['columns'], row)) for row in result['rows']]
    amount = next(r for r in rows if r['description'].startswith('Unit amount is stored in '))
    quantity = next(r for r in rows if r['table_name'] == amount['table_name'] and
                    r['description'].startswith('Positive integer quantity'))
    value = '"' + amount['column_name'].replace('"', '""') + '"'
    if 'NULL unit amount means zero' in amount['description']:
        value = f'COALESCE({value}, 0)'
    sql = f'SELECT {value} / :divisor * "{quantity["column_name"]}" AS gross FROM "{amount["table_name"]}"'
    divisor = 100.0 if 'integer cents' in amount['description'] else 1.0
    return sql, {'divisor': divisor}


def public_gross_client(*, reflection=True):
    def respond(messages, phase, index):
        if phase.endswith(':reflection'):
            system = messages[0]['content']
            if 'insights' in system:
                return {'insights': ['Use the observed catalog to identify units and NULL semantics.']}
            assert reflection
            payload = json.loads(messages[1]['content'])
            sql, params = normalized_gross_from_catalog(payload['queries'][0])
            return {'proposal': {'source_index': 1, 'guard_index': 0, 'sql': sql, 'params': params,
                                 'outer_sql': 'SELECT SUM(gross) AS answer FROM reused', 'outer_params': {},
                                 'description': 'Gross order values normalized using observed catalog units and NULL rules.'}}
        if index == 0:
            return query('SELECT * FROM catalog')
        if index == 1:
            sql, params = normalized_gross_from_catalog(latest_tool(messages))
            return query('SELECT SUM(gross) AS answer FROM (' + sql + ')', params)
        result = latest_tool(messages)
        assert result['error'] is None
        return {'action': 'ANSWER', 'value': result['rows'][0][0]}
    return ScriptedClient(respond)


def learned_memory(condition='reuse', arm='fragments'):
    stream = make_stream(90000, condition)
    memory = ExperienceMemory(arm)
    client = public_gross_client()
    budget = InferenceBudget()
    trace = harness.execute_episode(stream.ordinary[0], memory, client, budget,
                                    phase='ordinary', learn=True)
    assert trace['status'] == 'completed' and trace['reward'] == 1.
    assert trace['select_attempts'] == (3 if arm.startswith('fragments') else 2)
    if arm.startswith('fragments'):
        assert len(memory.entries) == 1
        assert trace['abstraction_proposal']['status'] == 'accepted'
        assert trace['queries'][2]['purpose'] == 'abstraction_reconstruction'
        assert trace['queries'][2]['learning_check'] is True
        assert memory.entries[0].fragment().compile().sql not in [q['sql'] for q in trace['queries'][:2]]
    return stream, memory, trace


def test_compose_learned_relation_uses_fresh_rows_and_matches_independent_sqlite():
    stream, memory, learned = learned_memory()
    original = memory.entries[0].fragment().compile()
    actions = [
        {'action': 'COMPOSE', 'entry': 0, 'params': original.parameters,
         'outer_sql': 'SELECT AVG(gross) AS answer FROM reused', 'outer_params': {}},
        answer_scalar,
    ]
    client = ScriptedClient(lambda messages, phase, i:
                            actions[i](messages) if callable(actions[i]) else actions[i])
    budget = InferenceBudget()
    before = deepcopy(memory.snapshot())
    spec = stream.ordinary[1]  # Different public question and fresh data.
    trace = harness.execute_episode(spec, memory, client, budget, phase='final', learn=False)
    assert trace['status'] == 'completed' and trace['reward'] == 1.
    assert trace['answer'] == pytest.approx(evaluator_expected(spec))
    assert [q['purpose'] for q in trace['queries']] == ['applicability_check', 'fragment_composition']
    assert [q['attempt'] for q in trace['queries']] == [1, 2]
    assert trace['select_attempts'] == 2 and budget.calls == 2
    assert budget.total_tokens == 20
    assert trace['actions'][0]['guard_passed'] is True
    assert trace['before_memory_digest'] == trace['after_memory_digest']
    assert memory.snapshot() == before
    assert trace['queries'][1]['sql'] != learned['queries'][1]['sql']
    # Test-only replay reads evaluator table fixtures after all model inputs
    # have been frozen. It uses SQLite directly, not session.query or gold SQL.
    with sqlite3.connect(':memory:') as database:
        for table in spec._tables:
            database.execute(table.ddl)
            database.executemany(f'INSERT INTO "{table.name}" VALUES (' +
                                 ','.join('?' for _ in table.columns) + ')', table.rows)
        for record in trace['queries']:
            result = database.execute(record['sql'], record['params'])
            assert tuple(d[0] for d in result.description) == record['columns']
            assert tuple(result.fetchall()) == record['rows']


def test_failed_applicability_check_charges_one_attempt_and_never_executes_fragment():
    stream, memory, _ = learned_memory('near_match')
    bindings = memory.entries[0].fragment().compile().parameters
    actions = [{'action': 'USE', 'entry': 0, 'params': bindings}, query('SELECT 7 AS observed'), answer_scalar]
    client = ScriptedClient(lambda messages, phase, i:
                            actions[i](messages) if callable(actions[i]) else actions[i])
    budget = InferenceBudget()
    trace = harness.execute_episode(stream.ordinary[8], memory, client, budget,
                                    phase='ordinary', learn=False)
    assert trace['status'] == 'completed'
    assert trace['actions'][0]['guard_passed'] is False
    assert 'executed_fragment_digest' not in trace['actions'][0]
    assert [q['purpose'] for q in trace['queries']] == ['applicability_check', 'ordinary_query']
    assert trace['select_attempts'] == 2 and budget.calls == 3
    assert trace['answer'] == 7  # Submitted only after observing SELECT 7.
    assert 'Witnessed applicability rows do not match' in canonical(client.seen[1])


def test_unchecked_control_executes_identical_fragment_without_guard_query():
    stream, memory, _ = learned_memory(arm='fragments_unchecked')
    bindings = memory.entries[0].fragment().compile().parameters
    actions = [{'action': 'COMPOSE', 'entry': 0, 'params': bindings,
                'outer_sql': 'SELECT AVG(gross) FROM reused', 'outer_params': {}}, answer_scalar]
    client = ScriptedClient(lambda messages, phase, i:
                            actions[i](messages) if callable(actions[i]) else actions[i])
    trace = harness.execute_episode(stream.ordinary[1], memory, client, InferenceBudget(),
                                    phase='final', learn=False)
    assert trace['reward'] == 1.
    assert [q['purpose'] for q in trace['queries']] == ['fragment_composition']
    assert trace['select_attempts'] == 1
    assert 'guard_passed' not in trace['actions'][0]


def test_guard_that_spends_last_select_cannot_execute_fragment():
    stream, memory, _ = learned_memory()
    bindings = memory.entries[0].fragment().compile().parameters
    actions = [query('SELECT 1')] * 7 + [{'action': 'USE', 'entry': 0, 'params': bindings},
                                      {'action': 'ANSWER', 'value': 1}]
    budget = InferenceBudget()
    client = ScriptedClient(lambda messages, phase, i: actions[i])
    trace = harness.execute_episode(stream.ordinary[0], memory, client, budget,
                                    phase='old_after', learn=False)
    assert trace['status'] == 'completed'
    assert trace['select_attempts'] == 8 and budget.calls == 9
    assert [q['attempt'] for q in trace['queries']] == list(range(1, 9))
    assert trace['queries'][-1]['purpose'] == 'applicability_check'
    assert trace['actions'][7]['guard_passed'] is True
    assert not any('executed_fragment_digest' in action for action in trace['actions'])
    assert 'no SELECT allowance remains' in canonical(client.seen[-1])


@pytest.mark.parametrize('arm', ARMS)
def test_frozen_panel_never_reflects_or_mutates_any_memory_arm(arm):
    stream, memory, _ = learned_memory(arm=arm)
    before = deepcopy(memory.snapshot())
    client = public_gross_client(reflection=False)
    trace = harness.execute_episode(stream.old_panel[0], memory, client, InferenceBudget(),
                                    phase='old_after', learn=False)
    assert trace['status'] == 'completed' and trace['reward'] == 1.
    assert trace['before_memory_digest'] == trace['after_memory_digest']
    assert memory.snapshot() == before
    assert all(call['phase'].endswith(':solve') for call in client.seen)


def test_model_call_ceiling_stops_without_guessing_or_publishing_unobserved_answer():
    spec = make_stream(90000, 'reuse').ordinary[0]
    client = ScriptedClient(lambda *_: query('SELECT 123 AS observed'))
    budget = InferenceBudget(max_calls=1)
    memory = ExperienceMemory('full_history')
    before = memory.digest()
    trace = harness.execute_episode(spec, memory, client, budget, phase='ordinary', learn=True)
    assert trace['status'] == 'resource_stop' and trace['stop_reason'] == 'model_call_ceiling'
    assert trace['answer'] is None and trace['reward'] == 0.
    assert trace['select_attempts'] == 1 and budget.calls == 1
    assert trace['before_memory_digest'] == trace['after_memory_digest'] == before
    assert not memory.history


def test_token_ceiling_before_first_call_does_not_execute_or_guess():
    spec = make_stream(90000, 'reuse').ordinary[0]
    client = ScriptedClient(lambda *_: {'action': 'ANSWER', 'value': 999})
    trace = harness.execute_episode(spec, ExperienceMemory('stateless'), client,
                                    InferenceBudget(max_total_tokens=390), phase='ordinary', learn=True)
    assert trace['status'] == 'resource_stop'
    assert trace['answer'] is None and trace['reward'] == 0.
    assert trace['queries'] == trace['model_calls'] == client.seen == []
    assert trace['select_attempts'] == 0


def test_invalid_actions_and_memory_requests_are_charged_before_recovery():
    spec = make_stream(90000, 'reuse').ordinary[0]
    actions = ['not json', {'action': 'USE', 'entry': 0, 'params': {}},
               query('SELECT 7 AS observed'), answer_scalar]
    client = ScriptedClient(lambda messages, phase, i:
                            actions[i](messages) if callable(actions[i]) else actions[i])
    budget = InferenceBudget()
    trace = harness.execute_episode(spec, ExperienceMemory('fragments'), client, budget,
                                    phase='ordinary', learn=False)
    assert trace['status'] == 'completed'
    assert [q['purpose'] for q in trace['queries']] == [
        'invalid_model_action', 'invalid_memory_action', 'ordinary_query']
    assert [q['attempt'] for q in trace['queries']] == [1, 2, 3]
    assert trace['select_attempts'] == 3 and budget.calls == 4
    assert trace['queries'][0]['error'] and trace['queries'][1]['error']
    assert trace['answer'] == 7


def test_exhausted_select_ceiling_does_not_record_additional_query_attempts():
    spec = make_stream(90000, 'reuse').ordinary[0]
    client = ScriptedClient(lambda *_: 'not json')
    budget = InferenceBudget()
    trace = harness.execute_episode(spec, ExperienceMemory('stateless'), client, budget,
                                    phase='ordinary', learn=False)
    assert trace['status'] == 'no_valid_answer'
    assert trace['answer'] is None and trace['reward'] == 0.
    assert budget.calls == harness.MAX_ACTIONS
    assert trace['select_attempts'] == 8
    assert len(trace['queries']) == 8
    assert [q['attempt'] for q in trace['queries']] == list(range(1, 9))


def test_evaluator_provenance_is_appended_after_all_model_and_memory_messages(monkeypatch):
    canary = 'evaluator-only-canary-74e1d90b19'
    actual_metadata = harness.evaluator_metadata
    monkeypatch.setattr(harness, 'evaluator_metadata',
                        lambda spec: {**actual_metadata(spec), 'private_canary': canary})
    stream = make_stream(90000, 'reuse')
    memory = ExperienceMemory('full_history')
    clients, traces = [], []
    for _ in range(2):
        client = public_gross_client()
        trace = harness.execute_episode(stream.ordinary[0], memory, client, InferenceBudget(),
                                        phase='ordinary', learn=True)
        assert trace['reward'] == 1.
        assert trace['evaluator']['private_canary'] == canary
        clients.append(client)
        traces.append(trace)
    visible = canonical([client.seen for client in clients])
    stored = canonical(memory.snapshot())
    assert canary not in visible and canary not in stored
    forbidden = ('names_seed', 'data_seed', 'semantic_recipe', 'gold_sql', 'reference_sql',
                 'expected_answer', 'template_fingerprint')
    assert all(term not in visible and term not in stored for term in forbidden)
    assert '90000' not in visible
    # Appending the raw evaluator record cannot retroactively change an earlier
    # prompt, nor can the full-history control ingest it on the next episode.
    assert all('evaluator' not in call['messages'][-1]['content'] for trace in traces
               for call in trace['model_calls'])
    for call in traces[0]['model_calls']:
        assert canary not in canonical(call)
    assert any('correctness_feedback' in message['content']
               for episode in memory.history for message in episode)


def test_correct_query_alone_does_not_admit_memory_after_wrong_final_answer():
    spec = make_stream(90000, 'reuse').ordinary[0]
    actions = [query('SELECT * FROM catalog'), {'action': 'ANSWER', 'value': -1234567}]
    client = ScriptedClient(lambda messages, phase, i: actions[i])
    memory = ExperienceMemory('fragments')
    trace = harness.execute_episode(spec, memory, client, InferenceBudget(),
                                    phase='ordinary', learn=True)
    assert trace['status'] == 'completed' and trace['reward'] == 0.
    assert not memory.entries
    assert all(not call['phase'].endswith(':reflection') for call in client.seen)
