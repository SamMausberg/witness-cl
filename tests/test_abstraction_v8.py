"""Independent offline checks of synthesis, charged reconstruction and admission.

Scripted actions read only the public catalog and actual SELECT results. These
checks establish runtime contracts, not empirical abstraction discovery by an
LLM. No inference calls or held-out fixtures are used.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
import hashlib
import json

import pytest

import experiments.sql_abstractions_v8 as harness
import witness_cl.abstraction_v8 as abstraction
from witness_cl.abstraction_v8 import (
    admit_verified, equal_scalar, prepare_proposal, proposal_messages, scalar_result,
)
from witness_cl.memory_v8 import ExperienceMemory, canonical
from witness_cl.model_v8 import InferenceBudget
from witness_cl.sql_env_v8 import make_stream, open_episode


def observed(session, sql, params=None, *, learning=False):
    params = {} if params is None else params
    return {'sql': sql, 'params': deepcopy(params),
            'purpose': 'abstraction_reconstruction' if learning else 'ordinary_query',
            'learning_check': learning,
            **asdict(session.query(sql, params, learning_check=learning))}


def relation_from_catalog(row):
    """Derive physical columns and interpretation from a real public result."""
    records = [dict(zip(row['columns'], cells)) for cells in row['rows']]
    amount = next(r for r in records if r['description'].startswith('Unit amount is stored in '))
    quantity = next(r for r in records if r['table_name'] == amount['table_name']
                    and r['description'].startswith('Positive integer quantity'))
    quote = lambda name: '"' + name.replace('"', '""') + '"'
    value = quote(amount['column_name'])
    if 'NULL unit amount means zero' in amount['description']:
        value = f'COALESCE({value},0)'
    relation = (f'SELECT {value}/:scale*{quote(quantity["column_name"])} AS gross '
                f'FROM {quote(amount["table_name"])} '
                f'WHERE {quote(quantity["column_name"])}>=:minimum_quantity')
    params = {'scale': 100.0 if 'integer cents' in amount['description'] else 1.0,
              'minimum_quantity': 1}
    return relation, params


def fields_for(trace):
    relation, params = relation_from_catalog(trace['queries'][0])
    return {'source_index': len(trace['queries']) - 1, 'guard_index': 0,
            'sql': relation, 'params': params,
            'outer_sql': 'SELECT COALESCE(SUM(gross),0) AS total FROM reused',
            'outer_params': {},
            'description': 'Per-order gross values with observed units and NULL rules; quantity is a literal filter.'}


@contextmanager
def experience(extra_queries=0, *, spec=None):
    if spec is None:
        spec = make_stream(90000, 'reuse').ordinary[0]
    with open_episode(spec, allow_learning_checks=True) as session:
        rows = [observed(session, 'SELECT * FROM catalog')]
        for i in range(extra_queries):
            rows.append(observed(session, 'SELECT :seen AS seen', {'seen': i}))
        relation, params = relation_from_catalog(rows[0])
        rows.append(observed(session, f'SELECT COALESCE(SUM(gross),0) AS total FROM ({relation})', params))
        answer = scalar_result(rows[-1])
        trace = {'question': session.public.question, 'schema': session.public.schema,
                 'queries': rows, 'answer': answer, 'reward': session.answer(answer).reward,
                 'status': 'completed'}
        assert trace['reward'] == 1.
        yield session, trace


@pytest.fixture
def own_episode():
    with experience() as case:
        yield case


def prepare(trace, fields=None):
    return prepare_proposal(canonical({'proposal': fields_for(trace) if fields is None else fields}), trace)


def verify(session, trace, proposal):
    index = len(trace['queries'])
    trace['queries'].append(observed(session, proposal.request.sql, proposal.request.parameters, learning=True))
    return index


def test_new_relation_is_executed_and_admitted_with_exact_own_provenance(own_episode):
    session, trace = own_episode
    memory = ExperienceMemory('fragments')
    proposal = prepare(trace)
    assert proposal.fragment.sql != trace['queries'][proposal.source_index]['sql']
    assert proposal.fragment.compile().parameters == fields_for(trace)['params']
    with pytest.raises(FrozenInstanceError):
        proposal.source_index = 0
    index = verify(session, trace, proposal)
    entry = admit_verified(memory, proposal, trace, index)
    assert session.select_attempts == len(trace['queries']) == 3
    assert trace['queries'][-1]['attempt'] == 3
    assert memory.entries == [entry]
    assert entry.fragment() == proposal.fragment
    evidence = canonical({k: trace[k] for k in ('question', 'queries', 'answer', 'reward')})
    assert entry.provenance == hashlib.sha256(evidence.encode()).hexdigest()
    event = memory.events[-1]
    assert event['source_query_index'] == 1 and event['guard_query_index'] == 0
    assert event['verification_query_index'] == 2 and event['new_sql_text'] is True
    assert event['scope'] == 'one_own_observed_answer_only'
    assert memory.peak_memory_bytes == memory.memory_bytes()


def test_general_relation_supports_rebinding_and_a_new_outer_composition(own_episode):
    session, trace = own_episode
    proposal = prepare(trace)
    memory = ExperienceMemory('fragments_unchecked')
    entry = admit_verified(memory, proposal, trace, verify(session, trace, proposal))
    # A generic runtime transfer check, not an LLM-discovery or benchmark score.
    bindings = {**entry.fragment().compile().parameters, 'minimum_quantity': 2}
    request = entry.fragment().compose('SELECT AVG(gross) AS mean FROM reused', {}, alias='reused', bindings=bindings)
    with open_episode(make_stream(90000, 'reuse').ordinary[1]) as fresh:
        composed = fresh.query(request.sql, request.parameters)
        independent = fresh.query('SELECT AVG(gross) AS mean FROM (' + proposal.fragment.sql + ')', bindings)
        assert composed.error is None and composed.rows == independent.rows
        assert fresh.select_attempts == 2
    assert bindings != proposal.fragment.compile().parameters
    assert request.sql != proposal.request.sql


def test_proposal_prompt_excludes_top_level_and_nested_evaluator_fields(own_episode):
    _, trace = own_episode
    trace['evaluator'] = {'answer': 'private-canary-answer'}
    trace['seed'] = 'private-canary-seed'
    trace['phase'] = 'private-canary-phase'
    trace['queries'][0]['hidden_recipe'] = 'private-canary-recipe'
    messages = proposal_messages(trace)
    encoded = canonical(messages)
    assert 'private-canary' not in encoded
    public = json.loads(messages[-1]['content'])
    assert public['remaining_learning_selects'] == 6
    assert public['feedback_reward'] == 1.
    assert public['answer'] == trace['answer']
    assert [q['attempt'] for q in public['queries']] == [1, 2]
    trace['queries'][0]['rows'] = []
    assert json.loads(messages[-1]['content']) == public


@pytest.mark.parametrize('text', [
    'not JSON', '[]', '{}', '{"proposal":null,"approved":true}',
    '{"proposal":null,"proposal":null}', '{"proposal":true}',
    '{"proposal":[]}', '{"proposal":{"approved":true}}',
])
def test_malformed_envelope_cannot_approve_or_execute(text, own_episode):
    session, trace = own_episode
    with pytest.raises(ValueError):
        prepare_proposal(text, trace)
    assert session.select_attempts == 2


def test_explicit_abstention_does_not_request_verification(own_episode):
    session, trace = own_episode
    assert prepare_proposal('{"proposal":null}', trace) is None
    assert session.select_attempts == 2


@pytest.mark.parametrize('field,value', [
    ('source_index', -1), ('source_index', 2), ('source_index', True), ('source_index', 1.0),
    ('guard_index', -1), ('guard_index', 2), ('guard_index', False), ('guard_index', '0'),
    ('description', ''), ('description', 'x' * 513), ('description', None),
    ('sql', 'DELETE FROM catalog'), ('sql', 'SELECT 1; SELECT 2'),
    ('sql', 'SELECT 1 -- hidden'), ('sql', 'SELECT :xé'),
    ('params', {'scale': True, 'minimum_quantity': 1}),
    ('params', {'scale': 100.0}), ('outer_params', {'unexpected': 3}),
    ('outer_sql', 'DELETE FROM reused'), ('outer_sql', 'SELECT * FROM reused;'),
])
def test_malformed_or_unwitnessed_proposal_fields_are_rejected(field, value, own_episode):
    session, trace = own_episode
    fields = fields_for(trace)
    fields[field] = value
    with pytest.raises(ValueError):
        prepare(trace, fields)
    assert session.select_attempts == 2


@pytest.mark.parametrize('extra', ['verified', 'approved', 'expected', 'reward', 'evaluator', 'verification_index'])
def test_model_cannot_supply_host_admission_fields(extra, own_episode):
    _, trace = own_episode
    fields = fields_for(trace)
    fields[extra] = True
    with pytest.raises(ValueError, match='unsupported'):
        prepare(trace, fields)


@pytest.mark.parametrize('field,value', [('reward', 0.), ('reward', True), ('status', 'running'), ('status', 'resource_stop')])
def test_only_correct_completed_episodes_can_propose(field, value, own_episode):
    _, trace = own_episode
    trace[field] = value
    with pytest.raises(ValueError, match='correct completed'):
        prepare(trace)


@pytest.mark.parametrize('row_change', [
    {'error': 'interrupted'}, {'truncated': True}, {'rows': []},
    {'rows': [(1,), (2,)]}, {'rows': [(1, 2)]}, {'rows': [('7',)]},
    {'rows': [(None,)]}, {'rows': [(True,)]}, {'rows': [(float('nan'),)]},
    {'rows': [(10**1000,)]}, {'rows': [(-99999,)]},
])
def test_source_requires_complete_numeric_observation_of_confirmed_answer(row_change, own_episode):
    _, trace = own_episode
    trace['queries'][1].update(row_change)
    with pytest.raises(ValueError):
        prepare(trace)


@pytest.mark.parametrize('change', [{'error': 'denied'}, {'truncated': True}])
def test_incomplete_or_failed_guard_is_not_an_applicability_witness(change, own_episode):
    _, trace = own_episode
    trace['queries'][0].update(change)
    with pytest.raises(ValueError, match='applicability'):
        prepare(trace)


@pytest.mark.parametrize('field,value', [
    ('purpose', 'ordinary_query'), ('learning_check', False), ('learning_check', 1),
    ('sql', 'SELECT 0'), ('params', {}), ('attempt', 2), ('attempt', True),
    ('error', 'denied'), ('truncated', True), ('rows', [(-777,)]),
])
def test_inconsistent_or_failed_check_cannot_mutate_memory(field, value, own_episode):
    session, trace = own_episode
    memory = ExperienceMemory('fragments')
    proposal = prepare(trace)
    index = verify(session, trace, proposal)
    trace['queries'][index][field] = value
    before = memory.digest()
    with pytest.raises(ValueError):
        admit_verified(memory, proposal, trace, index)
    assert memory.digest() == before


@pytest.mark.parametrize('mutation', ['question', 'schema', 'answer', 'prior_sql', 'prior_rows'])
def test_admission_is_bound_to_immutable_preproposal_witness_prefix(mutation, own_episode):
    session, trace = own_episode
    proposal = prepare(trace)
    index = verify(session, trace, proposal)
    if mutation in ('question', 'schema'):
        trace[mutation] += 'changed'
    elif mutation == 'answer':
        trace['answer'] += 1
    elif mutation == 'prior_sql':
        trace['queries'][0]['sql'] = 'SELECT 1'
    else:
        trace['queries'][0]['rows'] = []
    memory = ExperienceMemory('fragments')
    before = memory.digest()
    with pytest.raises(ValueError, match='prefix changed'):
        admit_verified(memory, proposal, trace, index)
    assert memory.digest() == before


def test_failed_runtime_check_is_charged_and_leaves_prior_library_and_answer(own_episode):
    session, trace = own_episode
    memory = ExperienceMemory('fragments')
    fields = fields_for(trace)
    fields['outer_sql'] = 'SELECT nonexistent_column FROM reused'
    proposal = prepare(trace, fields)
    before = memory.digest()
    scored = trace['answer'], trace['reward'], trace['status']
    index = verify(session, trace, proposal)
    assert trace['queries'][index]['error']
    with pytest.raises(ValueError):
        admit_verified(memory, proposal, trace, index)
    assert session.select_attempts == 3
    assert memory.digest() == before
    assert (trace['answer'], trace['reward'], trace['status']) == scored
    with pytest.raises(RuntimeError, match='one answer'):
        session.answer(-1)


def test_seven_solve_attempts_leave_exactly_one_charged_learning_attempt():
    with experience(extra_queries=5) as (session, trace):
        proposal = prepare(trace)
        index = verify(session, trace, proposal)
        memory = ExperienceMemory('fragments')
        admit_verified(memory, proposal, trace, index)
        assert session.select_attempts == 8
        denied = session.query('SELECT 1', learning_check=True)
        assert denied.error == 'SELECT attempt budget exhausted'
        assert denied.attempt == session.select_attempts == 8


def test_exhausted_solve_budget_cannot_prepare_additional_learning_query():
    with experience(extra_queries=6) as (session, trace):
        with pytest.raises(ValueError, match='no SELECT'):
            prepare(trace)
        assert session.select_attempts == 8


def test_noncontiguous_prefix_cannot_claim_charged_provenance(own_episode):
    _, trace = own_episode
    trace['queries'][0]['attempt'] = 0
    with pytest.raises(ValueError, match='charged attempt'):
        prepare(trace)


def test_second_verification_is_not_part_of_the_frozen_single_proposal(own_episode):
    session, trace = own_episode
    proposal = prepare(trace)
    index = verify(session, trace, proposal)
    verify(session, trace, proposal)
    memory = ExperienceMemory('fragments')
    before = memory.digest()
    with pytest.raises(ValueError, match='one proposal'):
        admit_verified(memory, proposal, trace, index)
    assert memory.digest() == before


@pytest.mark.parametrize('arm', ['full_history', 'verbatim', 'insights', 'stateless'])
def test_admission_cannot_silently_change_other_memory_algorithms(arm, own_episode):
    session, trace = own_episode
    proposal = prepare(trace)
    index = verify(session, trace, proposal)
    memory = ExperienceMemory(arm)
    before = memory.digest()
    with pytest.raises(ValueError, match='only fragment'):
        admit_verified(memory, proposal, trace, index)
    assert memory.digest() == before


def test_finite_witness_can_accept_a_cached_constant_without_proving_transfer(own_episode):
    session, trace = own_episode
    fields = fields_for(trace)
    fields.update(sql='SELECT :remembered AS answer', params={'remembered': trace['answer']},
                  outer_sql='SELECT MAX(answer) FROM reused')
    proposal = prepare(trace, fields)
    memory = ExperienceMemory('fragments')
    entry = admit_verified(memory, proposal, trace, verify(session, trace, proposal))
    assert memory.events[-1]['new_sql_text'] is True
    assert memory.events[-1]['scope'] == 'one_own_observed_answer_only'
    # Same old task on fresh rows defeats the cached answer. Neither accepting
    # this witness nor recording new SQL text certifies semantic generality.
    with open_episode(make_stream(90000, 'reuse').old_panel[0]) as fresh:
        request = entry.fragment().compile()
        result = fresh.query(request.sql, request.parameters)
        assert result.error is None
        assert fresh.answer(result.rows[0][0]).reward == 0.


def test_unused_cte_reconstruction_is_finite_evidence_only(own_episode):
    session, trace = own_episode
    fields = fields_for(trace)
    fields.update(sql='SELECT :n AS unused', params={'n': 17},
                  outer_sql='SELECT :remembered AS answer', outer_params={'remembered': trace['answer']})
    proposal = prepare(trace, fields)
    memory = ExperienceMemory('fragments')
    admit_verified(memory, proposal, trace, verify(session, trace, proposal))
    assert memory.events[-1]['scope'] == 'one_own_observed_answer_only'
    assert 'generalization_proved' not in memory.events[-1]


def test_entry_byte_rejection_occurs_before_any_library_mutation(monkeypatch, own_episode):
    session, trace = own_episode
    proposal = prepare(trace)
    index = verify(session, trace, proposal)
    memory = ExperienceMemory('fragments')
    before = memory.digest()
    monkeypatch.setattr(abstraction, 'MAX_MEMORY_BYTES', 1)
    with pytest.raises(ValueError, match='entry byte cap'):
        admit_verified(memory, proposal, trace, index)
    assert memory.digest() == before


def test_refreshed_template_witness_replaces_entry_but_retains_journal():
    memory = ExperienceMemory('fragments')
    provenances = []
    for spec in (make_stream(90000, 'reuse').ordinary[0], make_stream(90000, 'reuse').old_panel[0]):
        with experience(spec=spec) as (session, trace):
            proposal = prepare(trace)
            entry = admit_verified(memory, proposal, trace, verify(session, trace, proposal))
            provenances.append(entry.provenance)
            assert len(memory.entries) == 1
    assert provenances[0] != provenances[1]
    assert len(memory.events) == 2
    assert memory.entries[0].provenance == provenances[-1]
    assert memory.peak_memory_bytes >= memory.memory_bytes()


@pytest.mark.parametrize('x,y,expected', [(True, 1, False), (10**1000, 1, False),
                                         (float('inf'), 1, False), (float('nan'), 1, False),
                                         (1., 1, True), (100, 100.00001, True), (100, 101, False)])
def test_finite_numeric_comparison_is_bounded(x, y, expected):
    assert equal_scalar(x, y) is expected


class PublicEvidenceClient:
    """Minimal budgeted test double for the actual synthesis harness path."""
    def __init__(self, *, fail_reconstruction=False, extra_queries=0):
        self.fail_reconstruction = fail_reconstruction
        self.extra_queries = extra_queries
        self.seen = []

    def complete(self, messages, budget, *, phase, records, output_tokens, response_schema=None):
        budget.check(7, output_tokens)
        frozen = deepcopy(messages)
        self.seen.append({'messages': frozen, 'phase': phase})
        if phase.endswith(':reflection'):
            visible = json.loads(frozen[-1]['content'])
            fields = fields_for(visible)
            if self.fail_reconstruction:
                fields['outer_sql'] = 'SELECT missing_column FROM reused'
            response = {'proposal': fields}
        else:
            observations = []
            for message in frozen:
                if message['role'] != 'user':
                    continue
                try:
                    body = json.loads(message['content'])
                except (ValueError, TypeError):
                    continue
                if 'tool_result' in body:
                    observations.append(body['tool_result'])
            if not observations:
                response = {'action': 'QUERY', 'sql': 'SELECT * FROM catalog', 'params': {}}
            elif len(observations) <= self.extra_queries:
                response = {'action': 'QUERY', 'sql': 'SELECT 0', 'params': {}}
            elif len(observations) == self.extra_queries + 1:
                relation, params = relation_from_catalog(observations[0])
                response = {'action': 'QUERY',
                            'sql': f'SELECT COALESCE(SUM(gross),0) AS total FROM ({relation})', 'params': params}
            else:
                response = {'action': 'ANSWER', 'value': scalar_result(observations[-1])}
        content = canonical(response)
        budget.calls += 1
        budget.prompt_tokens += 7
        budget.completion_tokens += 3
        budget.total_tokens += 10
        records.append({'messages': frozen, 'phase': phase, 'content': content,
                        'status': 'completed', 'generation_attempted': True,
                        'usage': {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10},
                        'response_schema': deepcopy(response_schema), 'test_double': True})
        return content


@pytest.mark.parametrize('arm', ['fragments', 'fragments_unchecked'])
def test_actual_harness_synthesizes_new_sql_and_charges_reflection_and_check(arm):
    memory = ExperienceMemory(arm)
    client, budget = PublicEvidenceClient(), InferenceBudget()
    trace = harness.execute_episode(make_stream(90000, 'reuse').ordinary[0], memory, client,
                                    budget, phase='ordinary', learn=True)
    assert trace['status'] == 'completed' and trace['reward'] == 1.
    assert trace['abstraction_proposal']['status'] == 'accepted'
    assert trace['select_attempts'] == 3 and budget.calls == 4
    assert budget.total_tokens == 40
    assert [r['attempt'] for r in trace['queries']] == [1, 2, 3]
    assert trace['queries'][-1]['learning_check'] is True
    assert trace['queries'][-1]['purpose'] == 'abstraction_reconstruction'
    assert len(memory.entries) == 1
    assert memory.entries[0].fragment().sql != trace['queries'][1]['sql']
    assert trace['model_calls'][-1]['response_schema'] == abstraction.PROPOSAL_SCHEMA
    assert all(key not in canonical(client.seen) for key in ('semantic_recipe', 'names_seed', 'data_seed', 'expected_answer'))
    assert memory.peak_memory_bytes >= memory.memory_bytes()


def test_actual_harness_retains_correct_answer_when_paid_reconstruction_fails():
    memory = ExperienceMemory('fragments')
    budget = InferenceBudget()
    trace = harness.execute_episode(make_stream(90000, 'reuse').ordinary[0], memory,
                                    PublicEvidenceClient(fail_reconstruction=True), budget,
                                    phase='ordinary', learn=True)
    assert trace['status'] == 'completed' and trace['reward'] == 1.
    assert trace['abstraction_proposal']['status'] == 'rejected'
    assert trace['queries'][-1]['error']
    assert trace['select_attempts'] == 3 and budget.calls == 4
    assert not memory.entries
    assert any(e['kind'] == 'rejected_abstraction' for e in memory.events)


def test_actual_harness_skips_synthesis_when_all_select_attempts_were_spent():
    memory = ExperienceMemory('fragments')
    client, budget = PublicEvidenceClient(extra_queries=6), InferenceBudget()
    trace = harness.execute_episode(make_stream(90000, 'reuse').ordinary[0], memory,
                                    client, budget, phase='ordinary', learn=True)
    assert trace['status'] == 'completed' and trace['reward'] == 1.
    assert trace['select_attempts'] == 8 and budget.calls == 9
    assert not memory.entries and 'abstraction_proposal' not in trace
    assert all(not r['phase'].endswith(':reflection') for r in client.seen)


def test_failed_new_proposal_preserves_an_existing_entry_and_its_provenance():
    memory = ExperienceMemory('fragments')
    with experience() as (session, trace):
        proposal = prepare(trace)
        admit_verified(memory, proposal, trace, verify(session, trace, proposal))
    before = memory.digest()
    assert len(memory.entries) == 1
    with experience(spec=make_stream(90000, 'reuse').old_panel[0]) as (session, trace):
        fields = fields_for(trace)
        fields['outer_sql'] = 'SELECT -99123 AS wrong_answer FROM reused LIMIT 1'
        proposal = prepare(trace, fields)
        index = verify(session, trace, proposal)
        assert trace['queries'][index]['error'] is None
        with pytest.raises(ValueError, match='reconstruction'):
            admit_verified(memory, proposal, trace, index)
        assert session.select_attempts == 3
    assert memory.digest() == before


def test_bounded_entry_fifo_retains_latest_actual_witness(monkeypatch):
    monkeypatch.setattr(abstraction, 'MAX_ENTRIES', 1)
    memory = ExperienceMemory('fragments')
    digests = []
    for suffix in ('', ' '):
        with experience() as (session, trace):
            fields = fields_for(trace)
            fields['sql'] += suffix
            proposal = prepare(trace, fields)
            entry = admit_verified(memory, proposal, trace, verify(session, trace, proposal))
            digests.append(entry.fragment().digest)
    assert digests[0] != digests[1]
    assert len(memory.entries) == 1 and memory.entries[0].fragment().digest == digests[-1]
    assert len(memory.events) == 2
    assert memory.peak_memory_bytes >= memory.memory_bytes()
