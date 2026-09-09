"""Offline protocol checks; scripted clients are explicitly marked as test doubles."""
from copy import deepcopy
from dataclasses import replace
import json
import sqlite3

import pytest

import experiments.sql_abstractions_v9 as harness
from witness_cl.memory_v8 import ARMS, canonical
from witness_cl.memory_v9 import ExperienceMemoryV9
from witness_cl.model_v8 import InferenceBudget
from witness_cl.model_v9 import DecodingV9
from witness_cl.sql_env_v8 import evaluator_expected, make_stream
from test_sql_harness_v8 import (
    ScriptedClient, answer_scalar, query, public_gross_client,
)


class Client(ScriptedClient):
    model = 'explicit-offline-test-double'
    context_tokens = 65536
    max_output = 4096
    response_mode = 'schema'
    endpoint = 'http://127.0.0.1:1'
    timeout = 1.
    decoding = DecodingV9(thinking=True)

    def __init__(self, respond):
        super().__init__(respond)
        self.caps = []

    def complete(self, messages, budget, **kwargs):
        self.caps.append((kwargs['phase'], kwargs['output_tokens']))
        return super().complete(messages, budget, **kwargs)


def gross_client():
    return Client(public_gross_client().respond)


def learned(arm='fragments'):
    stream = make_stream(92001, 'reuse')
    memory = ExperienceMemoryV9(arm, harness.V9_SYSTEM)
    client = gross_client()
    budget = InferenceBudget()
    trace = harness.execute_episode_v9(stream.ordinary[0], memory, client, budget,
                                       phase='ordinary', learn=True)
    assert trace['status'] == 'completed' and trace['reward'] == 1.
    assert client.caps[:3] == [('ordinary:solve', 2048)] * 3
    if arm in ('insights', 'fragments', 'fragments_unchecked'):
        assert client.caps[-1] == ('ordinary:reflection', 4096)
    return stream, memory, trace


def test_learned_relation_is_paid_and_composes_correctly_on_fresh_rows():
    stream, memory, acquisition = learned()
    assert acquisition['abstraction_proposal']['status'] == 'accepted'
    assert acquisition['select_attempts'] == 3
    assert acquisition['queries'][-1]['purpose'] == 'abstraction_reconstruction'
    assert acquisition['queries'][-1]['learning_check'] is True
    assert len(memory.entries) == 1
    fragment = memory.entries[0].fragment()
    assert fragment.original_prepared_query.sql not in [row['sql'] for row in acquisition['queries'][:2]]
    actions = [{'action': 'COMPOSE', 'entry': 0,
                'params': fragment.original_prepared_query.parameters,
                'outer_sql': 'SELECT AVG(gross) AS answer FROM reused', 'outer_params': {}}, answer_scalar]
    client = Client(lambda messages, phase, i: actions[i](messages) if callable(actions[i]) else actions[i])
    budget = InferenceBudget()
    before = memory.snapshot()
    spec = stream.ordinary[1]
    trace = harness.execute_episode_v9(spec, memory, client, budget, phase='final', learn=False)
    assert trace['reward'] == 1. and trace['answer'] == pytest.approx(evaluator_expected(spec))
    assert [row['purpose'] for row in trace['queries']] == ['applicability_check', 'fragment_composition']
    assert trace['select_attempts'] == 2 and budget.calls == 2 and budget.total_tokens == 20
    assert trace['before_memory_digest'] == trace['after_memory_digest']
    assert memory.snapshot() == before
    with sqlite3.connect(':memory:') as database:
        for table in spec._tables:
            database.execute(table.ddl)
            database.executemany(f'INSERT INTO "{table.name}" VALUES (' + ','.join('?' for _ in table.columns) + ')', table.rows)
        for record in trace['queries']:
            result = database.execute(record['sql'], record['params'])
            assert tuple(result.fetchall()) == record['rows']


@pytest.mark.parametrize('arm', ARMS)
def test_panels_never_reflect_or_update_any_arm(arm):
    stream, memory, _ = learned(arm)
    before = memory.snapshot()
    client = gross_client()
    trace = harness.execute_episode_v9(stream.old_panel[0], memory, client, InferenceBudget(),
                                       phase='old_after', learn=False)
    assert trace['status'] == 'completed' and trace['reward'] == 1.
    assert memory.snapshot() == before
    assert all(phase.endswith(':solve') for phase, _ in client.caps)
    with pytest.raises(ValueError, match='frozen'):
        harness.execute_episode_v9(stream.old_panel[0], memory, client, InferenceBudget(),
                                   phase='old_before', learn=True)


def test_ordinary_query_preserves_legal_sqlite_text_and_unused_bindings():
    actions = [query('SELECT :value AS observed;', {'value': 3, 'unused': 'still literal data'}), answer_scalar]
    client = Client(lambda messages, phase, i: actions[i](messages) if callable(actions[i]) else actions[i])
    trace = harness.execute_episode_v9(make_stream(92001, 'reuse').ordinary[0],
                                       ExperienceMemoryV9('stateless', harness.V9_SYSTEM), client,
                                       InferenceBudget(), phase='ordinary', learn=False)
    assert trace['status'] == 'completed' and trace['answer'] == 3
    assert trace['queries'][0]['sql'] == actions[0]['sql']
    assert trace['queries'][0]['params'] == actions[0]['params']
    assert trace['select_attempts'] == 1


def test_first_prompts_match_and_evaluator_metadata_never_enters_learning(monkeypatch):
    original = harness.evaluator_metadata
    canary = 'private-evaluator-canary-77c4'
    monkeypatch.setattr(harness, 'evaluator_metadata', lambda spec: {**original(spec), 'canary': canary})
    firsts = []
    for arm in ARMS:
        stream = make_stream(92001, 'reuse')
        memory = ExperienceMemoryV9(arm, harness.V9_SYSTEM)
        client = gross_client()
        trace = harness.execute_episode_v9(stream.ordinary[0], memory, client, InferenceBudget(),
                                           phase='ordinary', learn=True)
        firsts.append(client.seen[0]['messages'])
        assert trace['evaluator']['canary'] == canary
        assert canary not in canonical(client.seen) + canonical(memory.snapshot())
        assert not any(term in canonical(client.seen) for term in ('names_seed', 'data_seed', 'gold_sql', '92001'))
        assert type(trace['feedback']['correct']) is bool
    assert all(messages == firsts[0] for messages in firsts)


def test_combined_budget_counts_each_call_once_and_stops_across_arms():
    total = InferenceBudget(max_calls=1)
    local_a, local_b = InferenceBudget(), InferenceBudget()
    client = Client(lambda *_: {'action': 'ANSWER', 'value': 0})
    paired = harness._SharedBudgetClient(client, total)
    spec = make_stream(92001, 'reuse').ordinary[0]
    first = harness.execute_episode_v9(spec, ExperienceMemoryV9('stateless', harness.V9_SYSTEM),
                                       paired, local_a, phase='ordinary', learn=True)
    second = harness.execute_episode_v9(spec, ExperienceMemoryV9('stateless', harness.V9_SYSTEM),
                                        paired, local_b, phase='ordinary', learn=True)
    assert first['status'] == 'completed'
    assert second['status'] == 'resource_stop' and second['answer'] is None
    assert local_a.calls == total.calls == 1 and local_b.calls == 0
    assert total.total_tokens == local_a.total_tokens == 10
    assert total.prompt_tokens == 7 and total.completion_tokens == 3


def test_qualification_default_runs_only_warm_and_freezes_configuration(tmp_path):
    client = Client(lambda *_: {'action': 'ANSWER', 'value': 0})
    out = tmp_path / 'qualification'
    manifest = harness.run_study(out, client, arms=('stateless',))
    assert manifest['status'] == 'completed'
    assert manifest['stage'] == 'qualification' and manifest['completed_episode_records'] == 8
    assert manifest['required_records_complete'] and manifest['usage_verified']
    assert manifest['source_sha256'] == manifest['source_sha256_after']
    assert manifest['client_config_unchanged'] and manifest['system_prompt'] == harness.V9_SYSTEM
    assert manifest['total_budget']['calls'] == 8 and manifest['total_budget']['total_tokens'] == 80
    assert manifest['contains_test_double_calls'] and manifest['warm_qualified'] is False
    rows = [json.loads(line) for line in next(out.glob('*.jsonl')).read_text().splitlines()]
    assert [row['episode_index'] for row in rows] == list(range(8))
    assert all(row['phase'] == 'ordinary' and row['learn'] is True for row in rows)
    with pytest.raises(FileExistsError):
        harness.run_study(out, client, arms=('stateless',))


def test_full_stage_gate_stops_before_panels_without_discarding_warm_memory(tmp_path):
    def respond(messages, phase, index):
        return {'insights': ['This observed answer was incorrect; do not reuse zero.']} if phase.endswith(':reflection') else {'action': 'ANSWER', 'value': 0}
    result = harness.run_study(tmp_path / 'gated', Client(respond), stage='full', arms=('insights',))
    assert result['status'] == 'competence_gate_failed'
    assert result['completed_episode_records'] == 8 and not result['required_records_complete']
    summary = json.loads((tmp_path / 'gated' / 'summary.json').read_text())
    assert summary[0]['phase_counts'] == {'ordinary': 8, 'old_before': 0, 'old_after': 0, 'final': 0}
    assert summary[0]['memory']['insights']
    assert summary[0]['ordinary_budget']['calls'] == 16 and summary[0]['panel_budget']['calls'] == 0


def test_shared_resource_stop_keeps_partial_records_and_cannot_qualify(tmp_path):
    limits = replace(harness.DEFAULT_LIMITS, total_calls=1)
    result = harness.run_study(tmp_path / 'stopped', Client(lambda *_: {'action': 'ANSWER', 'value': 0}),
                               arms=('full_history', 'stateless'), limits=limits)
    assert result['status'] == 'stopped' and not result['required_records_complete']
    assert result['total_budget']['calls'] == 1 and result['total_budget']['total_tokens'] == 10
    assert result['warm_qualified'] is False and result['resources_complete'] is False
    assert result['completed_episode_records'] == 2


@pytest.mark.parametrize('seeds', [(90000,), (92004,), (True,), (92000, 92000)])
def test_only_declared_v9_development_seeds_are_accepted(tmp_path, seeds):
    with pytest.raises(ValueError, match='92000'):
        harness.run_study(tmp_path / 'invalid', Client(lambda *_: None), seeds=seeds)
    assert not (tmp_path / 'invalid').exists()


def test_source_change_invalidates_even_complete_synthetic_run(tmp_path, monkeypatch):
    fingerprints = iter([{'test_source': 'before'}, {'test_source': 'after'}])
    monkeypatch.setattr(harness, 'source_hashes', lambda: next(fingerprints))
    result = harness.run_study(tmp_path / 'source-changed',
                               Client(lambda *_: {'action': 'ANSWER', 'value': 0}), arms=('stateless',))
    assert result['completed_episode_records'] == 8
    assert result['status'] == 'invalidated' and result['source_unchanged'] is False
    assert result['warm_qualified'] is False


def test_combined_budget_checks_shared_tokens_and_accounts_backend_excess():
    local = InferenceBudget(max_total_tokens=1000)
    total = InferenceBudget(max_total_tokens=20)
    joined = harness._CombinedBudget(local, total)
    with pytest.raises(harness.BudgetStop, match='model_token_ceiling'):
        joined.check(15, 6)
    joined.check(5, 5)
    joined.calls += 1
    joined.prompt_tokens += 15
    joined.completion_tokens += 10
    joined.total_tokens += 25
    joined.tokenization_seconds += .2
    joined.inference_seconds += .3
    assert joined.total_tokens > joined.max_total_tokens
    assert local.total_tokens == total.total_tokens == 25
    assert local.calls == total.calls == 1
    assert total.tokenization_seconds == .2 and total.inference_seconds == .3


@pytest.mark.parametrize('shared_cap', [49, 50])
def test_real_v9_client_enforces_shared_reservation_and_keeps_overflow_costs(tmp_path, monkeypatch, shared_cap):
    from witness_cl.model_v9 import LocalInferenceV9

    key = tmp_path / 'offline-only.key'
    key.write_text('not-a-real-credential')
    client = LocalInferenceV9(key_file=key, endpoint='http://127.0.0.1:1', model='offline-fake-transport',
                              max_output=20, context_tokens=128)
    paths = []

    def fake_post(path, body, timeout):
        paths.append(path)
        if path.endswith('/input_tokens'):
            return {'input_tokens': 10}
        return {'model': client.model, 'usage': {'prompt_tokens': 15, 'completion_tokens': 20, 'total_tokens': 35},
                'choices': [{'finish_reason': 'stop', 'message': {'content': '{"action":"ANSWER","value":0}'}}]}

    monkeypatch.setattr(client, '_post', fake_post)
    total = InferenceBudget(max_total_tokens=shared_cap, total_tokens=20, prompt_tokens=20, calls=1)
    local = InferenceBudget(max_total_tokens=1000)
    paired = harness._SharedBudgetClient(client, total)
    records = []
    if shared_cap == 49:
        with pytest.raises(harness.BudgetStop, match='model_token_ceiling'):
            paired.complete([{'role': 'user', 'content': 'Observed evidence only.'}], local,
                             phase='ordinary:solve', records=records, output_tokens=20)
        assert paths == ['/v1/chat/completions/input_tokens']
        assert local.total_tokens == local.calls == 0
        assert total.total_tokens == 20 and total.calls == 1
        assert records[0]['generation_attempted'] is False and records[0]['usage'] is None
    else:
        with pytest.raises(RuntimeError, match='backend exceeded reserved token budget'):
            paired.complete([{'role': 'user', 'content': 'Observed evidence only.'}], local,
                             phase='ordinary:solve', records=records, output_tokens=20)
        assert paths == ['/v1/chat/completions/input_tokens', '/v1/chat/completions']
        assert local.total_tokens == 35 and total.total_tokens == 55
        assert local.calls == 1 and total.calls == 2
        assert records[0]['status'] == 'failed' and records[0]['usage']['total_tokens'] == 35
        assert local.unknown_usage_calls == total.unknown_usage_calls == 0
    assert total.tokenization_seconds == local.tokenization_seconds
    assert total.inference_seconds == local.inference_seconds
