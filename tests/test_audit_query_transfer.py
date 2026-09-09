"""Scripted trace fixtures test audit claims, never empirical learning scores."""
from copy import deepcopy
from dataclasses import replace

import pytest

from test_query_transfer import fixture_spec, query, run, view_program
from tools.audit_query_transfer import AuditError, audit_episode, fixture_for_trace
from witness_cl.query_memory import QueryMemory
from witness_cl.source_views import _digest


def acquired_memory():
    spec = fixture_spec(expected=0.03)
    trace, memory, _, _ = run(QueryMemory('view_program'),
                              [query('SELECT COALESCE(SUM(amount/100.0),0) FROM amounts')], spec=spec)
    assert trace['admission']['status'] == 'admitted'
    return spec, trace, memory


def fresh_program(*, aggregate='avg', raw_recomputation=False, expected=0.06):
    _, training, memory = acquired_memory()
    spec = fixture_spec((5, 7), expected=expected)
    spec = replace(spec, _public=replace(spec._public, question='Return the mean amount in dollars.'))
    action = view_program(training['admission']['view']['key'])
    agg = action['program']['aggregates'][0]
    agg['op'] = aggregate
    if raw_recomputation:
        agg['expr'] = {'op': 'div', 'left': {'op': 'col', 'name': 'c0'},
                       'right': {'op': 'lit', 'value': 100.0}}
    trace, _, _, _ = run(memory, [action], spec=spec, phase='old_before', learn=False, nonce='fresh-b')
    return trace, spec


def test_replays_every_direct_source_and_admission_check_independently():
    spec, trace, _ = acquired_memory()
    result = audit_episode(trace, spec)
    assert result['consistent'] and result['correct']
    assert result['diagnostic_sql_calls'] == result['recorded_queries'] == 3
    assert result['intervention_sql_calls'] == 0
    assert not result['terminal_program']
    assert result['primary_candidate'] is None
    assert all(not call['learner_observation'] for call in result['diagnostic_sql'])


def test_correct_derived_feature_use_is_only_a_local_candidate_awaiting_provenance():
    trace, spec = fresh_program()
    result = audit_episode(trace, spec)
    assert result['actual_answer'] == (5 / 100 + 7 / 100) / 2
    assert result['terminal_program'] and result['correct']
    assert result['local_candidate_pending_provenance']
    assert result['primary_candidate'] is None
    assert not result['prior_own_admission_verified']
    assert result['freshness_status'] == 'requires_whole_run_provenance'
    assert result['diagnostic_sql_calls'] == 3
    assert result['replay_sql_calls'] == 1 and result['intervention_sql_calls'] == 2
    for intervention in result['interventions']:
        assert intervention['origin'] == 'scalar_expression'
        assert intervention['has_column_dependency']
        assert intervention['structurally_referenced']
        assert intervention['new_aggregate_ops'] == ['avg']
        assert intervention['output_changed_exact']
        assert intervention['output_changed_at_task_tolerance']
        assert intervention['local_candidate_pending_provenance']
    assert {r['counterfactual_scalar']['status'] for r in result['interventions']} == {'numeric', 'null'}


def test_raw_column_recomputation_survives_both_measure_interventions():
    trace, spec = fresh_program(raw_recomputation=True)
    result = audit_episode(trace, spec)
    assert result['correct'] and not result['local_candidate_pending_provenance']
    assert result['structural_measure_references'] == []
    for row in result['interventions']:
        assert not row['structurally_referenced']
        assert row['output_changed_exact'] is False
        assert row['output_changed_at_task_tolerance'] is False
        assert row['counterfactual_scalar'] == {'status': 'numeric', 'value': (5 / 100 + 7 / 100) / 2}


def test_same_operator_and_binding_has_contribution_but_no_new_operation_claim():
    trace, spec = fresh_program(aggregate='sum', expected=0.12)
    result = audit_episode(trace, spec)
    assert result['correct']
    assert not result['local_candidate_pending_provenance']
    assert all(x['output_changed_exact'] and not x['new_operation_or_binding']
               for x in result['interventions'])


def test_wrong_terminal_program_does_not_become_candidate_despite_measure_dependence():
    trace, spec = fresh_program(expected=12)
    result = audit_episode(trace, spec)
    assert not result['correct'] and not result['local_candidate_pending_provenance']
    assert all(x['output_changed_exact'] for x in result['interventions'])


def test_direct_physical_measure_is_distinguished_from_learned_expression():
    training_spec = fixture_spec()
    training, memory, _, _ = run(QueryMemory('view_program'), spec=training_spec)
    action = view_program(training['admission']['view']['key'])
    action['program']['aggregates'][0]['op'] = 'avg'
    spec = fixture_spec((5, 7), expected=6)
    trace, _, _, _ = run(memory, [action], spec=spec, phase='old_before', learn=False)
    result = audit_episode(trace, spec)
    assert result['correct'] and not result['local_candidate_pending_provenance']
    assert {x['origin'] for x in result['interventions']} == {'physical_column'}
    assert all(x['has_column_dependency'] for x in result['interventions'])


def test_changed_bindings_can_qualify_without_a_new_aggregate_operation():
    spec = fixture_spec(expected=0.03)
    training, memory, _, _ = run(QueryMemory('view_program'), [query(
        'SELECT COALESCE(SUM(amount/100.0),0) FROM amounts WHERE amount>:cut',
        params={'cut': 0})], spec=spec)
    assert training['admission']['status'] == 'admitted'
    action = view_program(training['admission']['view']['key'])
    action['program']['input']['bindings'] = {'cut': 5}
    fresh = fixture_spec((5, 7), expected=0.07)
    trace, _, _, _ = run(memory, [action], spec=fresh, phase='old_before', learn=False)
    result = audit_episode(trace, fresh)
    assert result['local_candidate_pending_provenance']
    assert all(row['changed_bindings'] and row['new_aggregate_ops'] == []
               for row in result['interventions'])


@pytest.mark.parametrize('source,source_expected,fresh_expected,origin,has_column', [
    ('SELECT COUNT(*) FROM amounts', 2, 1, 'row_marker', False),
    ('WITH x AS (SELECT amount/100.0 AS gross FROM amounts) SELECT COALESCE(SUM(gross),0) FROM x',
     0.03, 0.06, 'derived_or_unresolved_column', True),
    ('SELECT COALESCE(SUM(1/100.0),0) FROM amounts', 0.02, 0.01, 'scalar_expression', False),
])
def test_origins_and_real_column_requirement_prevent_overstated_expression_claims(
        source, source_expected, fresh_expected, origin, has_column):
    spec = fixture_spec(expected=source_expected)
    training, memory, _, _ = run(QueryMemory('view_program'), [query(source)], spec=spec)
    assert training['admission']['status'] == 'admitted'
    action = view_program(training['admission']['view']['key'])
    action['program']['aggregates'][0]['op'] = 'avg'
    fresh = fixture_spec((5, 7), expected=fresh_expected)
    trace, _, _, _ = run(memory, [action], spec=fresh, phase='old_before', learn=False)
    result = audit_episode(trace, fresh)
    assert result['correct'] and not result['local_candidate_pending_provenance']
    assert all(row['origin'] == origin and row['has_column_dependency'] is has_column
               for row in result['interventions'])


def test_counterfactual_compilation_failure_is_inconclusive_and_not_a_sql_call(monkeypatch):
    from tools import audit_query_transfer as audit
    from witness_cl.relational_program import ProgramError
    trace, spec = fresh_program()
    original = audit.compile_program

    def bounded(program, selected_views, **kwargs):
        if kwargs.get('measure_overrides'):
            raise ProgramError('compiled SQL byte limit exceeded')
        return original(program, selected_views, **kwargs)

    monkeypatch.setattr(audit, 'compile_program', bounded)
    result = audit.audit_episode(trace, spec)
    assert result['consistent'] and result['correct']
    assert result['diagnostic_sql_calls'] == 1
    assert result['intervention_sql_calls'] == 0
    assert not result['local_candidate_pending_provenance']
    assert all(row['intervention_compilation_error'] and row['output_changed_exact'] is None
               for row in result['interventions'])


@pytest.mark.parametrize('mutation', ['sql', 'binding', 'ast', 'metadata'])
def test_compiled_program_request_and_exact_ast_are_rechecked(mutation):
    trace, spec = fresh_program()
    if mutation == 'sql':
        trace['queries'][0]['sql'] = 'SELECT 0.06'
    elif mutation == 'binding':
        trace['queries'][0]['params']['invented'] = 3
    elif mutation == 'ast':
        trace['actions'][0]['program']['aggregates'][0]['op'] = 'sum'
    else:
        trace['actions'][0]['compiled']['measure_references'] = []
    with pytest.raises(AuditError, match='PROGRAM'):
        audit_episode(trace, spec)


def test_rehashed_view_sql_cannot_override_source_provenance():
    trace, spec = fresh_program()
    payload = trace['selected_views'][0]
    payload['sql'] = payload['sql'].replace('100.0', '200.0')
    payload['reconstruction_sql'] = payload['reconstruction_sql'].replace('100.0', '200.0')
    payload['key'] = _digest(payload)
    with pytest.raises(AuditError, match='regeneration'):
        audit_episode(trace, spec)


def test_invalid_source_view_hash_is_rejected():
    trace, spec = fresh_program()
    trace['selected_views'][0]['sql'] = 'SELECT 6'
    with pytest.raises(AuditError, match='source view'):
        audit_episode(trace, spec)


def test_host_numeric_answer_is_not_rounded_or_compared_at_reward_tolerance():
    spec = fixture_spec(expected=3 / 7)
    trace, _, _, _ = run(actions=[query('SELECT SUM(amount)/7.0 FROM amounts')], spec=spec)
    result = audit_episode(trace, spec)
    assert result['actual_answer'] == 3 / 7
    trace['answer'] = round(trace['answer'], 6)
    with pytest.raises(AuditError, match='exact host-emitted'):
        audit_episode(trace, spec)


def test_sqlite_rows_are_checked_without_rounding():
    trace, spec = fresh_program()
    trace['queries'][0]['rows'] = [[0.060000000000001]]
    with pytest.raises(AuditError, match='SQLite replay') as failure:
        audit_episode(trace, spec)
    assert failure.value.diagnostic['diagnostic_sql_calls'] == 1
    assert failure.value.diagnostic['diagnostic_sql'][0]['result']['rows'] == [[(5 / 100 + 7 / 100) / 2]]


def test_exact_and_task_tolerance_effects_are_separately_reported():
    spec = fixture_spec(expected=3e-12)
    training, memory, _, _ = run(QueryMemory('view_program'),
                                [query('SELECT COALESCE(SUM(amount/1000000000000.0),0) FROM amounts')], spec=spec)
    # Its tiny source difference cannot pass the online tolerance-based empty
    # gate. The audit must not invent prior admission from a manually supplied view.
    assert training['admission']['status'] == 'dependence_rejected'
    from witness_cl.source_views import SourceView
    view = SourceView.from_dict(training['admission']['view'])
    memory.add_view(spec._public.schema, view, evidence_digest='explicit-test-only-unverified')
    action = view_program(view.key)
    action['program']['aggregates'][0]['op'] = 'avg'
    fresh = fixture_spec((5, 7), expected=6e-12)
    trace, _, _, _ = run(memory, [action], spec=fresh, phase='old_before', learn=False)
    result = audit_episode(trace, fresh)
    numeric = next(r for r in result['interventions'] if r['replacement'] == 0)
    assert numeric['output_changed_exact']
    assert not numeric['output_changed_at_task_tolerance']
    assert numeric['local_candidate_exact_pending_provenance']
    assert not numeric['local_candidate_pending_provenance']
    assert result['primary_candidate'] is None


def test_invalid_action_then_direct_query_is_replayed_in_order():
    spec = fixture_spec()
    trace, _, _, _ = run(actions=[{'action': 'ANSWER', 'value': 3, 'answer': True}, query()], spec=spec)
    result = audit_episode(trace, spec)
    assert result['replay_sql_calls'] == 2 and result['correct']


def test_invalid_program_then_direct_query_is_replayed_in_order():
    spec = fixture_spec()
    action = {'action': 'PROGRAM', 'program': {'op': 'made_up'}, 'answer': True}
    trace, _, _, _ = run(QueryMemory('view_program'), [action, query()], spec=spec)
    result = audit_episode(trace, spec)
    assert result['replay_sql_calls'] == 4 and result['correct']


def test_unavailable_program_is_replayed_as_a_charged_failure():
    spec = fixture_spec()
    action = {'action': 'PROGRAM', 'program': {'op': 'made_up'}, 'answer': True}
    trace, _, _, _ = run(QueryMemory('sql_archive'), [action, query()], spec=spec)
    result = audit_episode(trace, spec)
    assert result['replay_sql_calls'] == 2 and result['correct']


def test_false_admission_status_cannot_replace_the_missing_empty_check():
    spec, trace, _ = acquired_memory()
    trace['queries'].pop()
    trace['select_attempts'] -= 1
    with pytest.raises(AuditError, match='admission check cardinality') as failure:
        audit_episode(trace, spec)
    assert failure.value.diagnostic['diagnostic_sql_calls'] == 2


def test_failed_completed_action_budget_has_no_invented_terminal_program():
    spec = fixture_spec()
    trace, _, _, _ = run(QueryMemory('sql_archive'), [query('SELECT amount FROM amounts')], spec=spec)
    assert trace['status'] == 'no_valid_answer'
    result = audit_episode(trace, spec)
    assert result['consistent'] and not result['correct']
    assert result['diagnostic_sql_calls'] == 6
    assert result['actual_answer'] is None and result['interventions'] == []


def test_public_fixture_mismatch_is_rejected_before_replay():
    trace, spec = fresh_program()
    with pytest.raises(AuditError, match='public question'):
        audit_episode(trace, replace(spec, _public=replace(spec._public, question='Another task')))


def test_audit_does_not_mutate_trace_or_append_counterfactual_observations():
    trace, spec = fresh_program()
    before = deepcopy(trace)
    result = audit_episode(trace, spec)
    assert trace == before
    assert result['counterfactuals_are_learner_observations'] is False
    assert not result['whole_run_provenance_verified']


def test_fixture_coordinates_are_explicit_and_transfer_indexes_ordinary():
    coordinates = {'seed': 94001, 'condition': 'reuse', 'replay_split': 'development',
                   'phase': 'transfer', 'episode_index': 8}
    spec = fixture_for_trace(coordinates)
    assert spec._public.question
    with pytest.raises(AuditError, match='coordinate'):
        fixture_for_trace({'seed': 94001})
    with pytest.raises(AuditError, match='index'):
        fixture_for_trace({**coordinates, 'episode_index': 100})
