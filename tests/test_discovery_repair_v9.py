"""Test-double repair sequences; these are runtime checks, not learned results."""
from contextlib import contextmanager
from copy import deepcopy
import json

import pytest

from witness_cl.discovery_repair_v9 import run_discovery_repair
from witness_cl.memory_v8 import canonical
from witness_cl.memory_v9 import ExperienceMemoryV9
from witness_cl.model_v8 import InferenceBudget
from witness_cl.model_v9 import LocalInferenceV9
from witness_cl.sql_env_v9 import make_stream, open_episode
from test_abstraction_v8 import observed, relation_from_catalog, fields_for
from test_sql_harness_v9 import Client


@contextmanager
def completed_episode(extra_queries=0, seed=92001):
    spec = make_stream(seed, 'reuse').ordinary[0]
    with open_episode(spec, allow_learning_checks=True) as session:
        rows = [observed(session, 'SELECT * FROM catalog')]
        for value in range(extra_queries):
            rows.append(observed(session, 'SELECT :observed AS observed', {'observed': value}))
        relation, params = relation_from_catalog(rows[0])
        rows.append(observed(session, 'SELECT COALESCE(SUM(gross),0) AS total FROM (' + relation + ')', params))
        answer = rows[-1]['rows'][0][0]
        trace = {'phase': 'ordinary', 'question': session.public.question, 'schema': session.public.schema,
                 'queries': rows, 'model_calls': [], 'answer': answer,
                 'reward': session.answer(answer).reward, 'status': 'completed'}
        assert trace['reward'] == 1.
        yield session, trace


def library():
    return ExperienceMemoryV9('fragments', 'Shared solver policy.')


def proposal(fields):
    return {'proposal': deepcopy(fields)}


def script(*responses):
    return Client(lambda messages, phase, index: responses[index])


def bad_alias(fields):
    result = deepcopy(fields)
    result['outer_sql'] = result['outer_sql'].replace('FROM reused', 'FROM calculation_result')
    return result


def unused_relation(trace, fields):
    result = deepcopy(fields)
    source = trace['queries'][fields['source_index']]
    result['outer_sql'] = source['sql']
    result['outer_params'] = deepcopy(source['params'])
    assert 'reused' not in result['outer_sql']
    return result


def test_failed_alias_then_feedback_guided_repair_pays_both_checks_before_admission():
    with completed_episode() as (session, trace):
        original = deepcopy(trace)
        fields = fields_for(trace)
        client = script(proposal(bad_alias(fields)), proposal(fields))
        memory, budget = library(), InferenceBudget()
        result = run_discovery_repair(trace, memory, client, budget, session, allow_learning=True)
        assert result['prototype_only'] and result['status'] == 'admitted'
        assert result['new_select_attempts'] == 3 and session.select_attempts == 5
        assert [row['purpose'] for row in trace['queries'][2:]] == [
            'abstraction_reconstruction', 'abstraction_reconstruction', 'abstraction_empty_relation_probe']
        assert [row['attempt'] for row in trace['queries']] == [1, 2, 3, 4, 5]
        assert 'calculation_result' in trace['queries'][2]['error']
        assert len(memory.entries) == 1 and len(result['attempts']) == 2
        assert budget.calls == 2 and budget.total_tokens == 20
        assert all(record['test_double'] is True for record in trace['model_calls'])
        followup = json.loads(client.seen[1]['messages'][1]['content'])
        assert followup['queries'] == json.loads(canonical(original['queries']))
        assert followup['answer'] == original['answer'] and followup['correct'] is True
        assert followup['repair_feedback'][0]['reconstruction']['error'] == trace['queries'][2]['error']
        assert 'CTE named reused' in client.seen[1]['messages'][0]['content']
        assert trace['queries'][:2] == original['queries']
        assert all(trace[key] == original[key] for key in ('question', 'schema', 'answer', 'reward', 'status'))
        event = memory.events[-1]
        assert event['kind'] == 'abstraction_empty_relation_checked'
        assert event['intervention_query_index'] == 4
        assert event['intervention_digest'] == result['attempts'][-1]['intervention_digest']
        assert event['scope'] == 'one_observed_outer_result_changed_under_empty_relation'


def test_matching_unused_cte_is_rejected_and_staged_admission_never_reaches_library():
    with completed_episode() as (session, trace):
        fields = fields_for(trace)
        client = script(proposal(unused_relation(trace, fields)), {'proposal': None})
        memory = library()
        before = memory.snapshot()
        result = run_discovery_repair(trace, memory, client, InferenceBudget(), session, allow_learning=True)
        assert result['status'] == 'abstained' and result['new_select_attempts'] == 2
        failed = result['attempts'][0]
        assert failed['status'] == 'dependence_rejected'
        assert failed['reconstruction']['rows'] == failed['intervention']['rows']
        assert failed['reconstruction']['rows'][0][0] == trace['answer']
        assert memory.snapshot() == before


def test_unused_cte_feedback_can_be_repaired_without_reusing_validation_as_a_witness():
    with completed_episode() as (session, trace):
        fields = fields_for(trace)
        client = script(proposal(unused_relation(trace, fields)), proposal(fields))
        memory = library()
        result = run_discovery_repair(trace, memory, client, InferenceBudget(), session, allow_learning=True)
        assert result['status'] == 'admitted' and result['new_select_attempts'] == 4
        assert session.select_attempts == 6 and len(memory.entries) == 1
        assert result['attempts'][0]['status'] == 'dependence_rejected'
        payload = json.loads(client.seen[1]['messages'][1]['content'])
        assert len(payload['queries']) == payload['original_query_count'] == 2
        assert 'unchanged' in payload['repair_feedback'][0]['error']


def test_null_empty_intervention_result_is_valid_changed_evidence():
    with completed_episode() as (session, trace):
        fields = fields_for(trace)
        fields['outer_sql'] = 'SELECT SUM(gross) AS total FROM reused'
        result = run_discovery_repair(trace, library(), script(proposal(fields)), InferenceBudget(),
                                      session, allow_learning=True)
        assert result['status'] == 'admitted'
        assert result['attempts'][0]['intervention']['rows'] == ((None,),)
        assert session.select_attempts == 4


def test_all_three_failed_repairs_preserve_an_existing_nonempty_library():
    memory = library()
    with completed_episode(seed=92000) as (session, trace):
        first = run_discovery_repair(trace, memory, script(proposal(fields_for(trace))), InferenceBudget(),
                                     session, allow_learning=True)
        assert first['status'] == 'admitted' and memory.entries
    before = memory.snapshot()
    with completed_episode() as (session, trace):
        bad = proposal(bad_alias(fields_for(trace)))
        budget = InferenceBudget()
        result = run_discovery_repair(trace, memory, script(bad, bad, bad), budget, session, allow_learning=True)
        assert result['status'] == 'attempt_cap' and len(result['attempts']) == 3
        assert result['new_select_attempts'] == 3 and budget.calls == 3 and budget.total_tokens == 30
        assert memory.snapshot() == before


@pytest.mark.parametrize('extra_queries,expected_status,new_selects,calls', [
    (3, 'admitted', 3, 2), (4, 'admitted', 2, 1), (5, 'select_cap', 0, 0),
])
def test_reconstruction_and_probe_share_the_original_eight_select_cap(extra_queries, expected_status, new_selects, calls):
    with completed_episode(extra_queries=extra_queries) as (session, trace):
        fields = fields_for(trace)
        responses = ([proposal(bad_alias(fields)), proposal(fields)] if extra_queries == 3 else [proposal(fields)])
        client, budget = script(*responses), InferenceBudget()
        result = run_discovery_repair(trace, library(), client, budget, session, allow_learning=True)
        assert result['status'] == expected_status and result['new_select_attempts'] == new_selects
        assert budget.calls == calls and session.select_attempts <= 8
        assert len(trace['queries']) == session.select_attempts


@pytest.mark.parametrize('field', ['source_index', 'guard_index'])
def test_successful_post_answer_checks_are_ineligible_source_and_guard_witnesses(field):
    with completed_episode() as (session, trace):
        fields = fields_for(trace)
        forged = deepcopy(fields)
        forged[field] = 2  # A successful but unused-CTE reconstruction is query2.
        client = script(proposal(unused_relation(trace, fields)), proposal(forged), {'proposal': None})
        memory = library()
        result = run_discovery_repair(trace, memory, client, InferenceBudget(), session, allow_learning=True)
        assert trace['queries'][2]['error'] is None and trace['queries'][2]['rows'][0][0] == trace['answer']
        assert result['attempts'][1]['status'] == 'proposal_rejected'
        assert 'original ordinary witness prefix' in result['attempts'][1]['error']
        assert result['new_select_attempts'] == 2 and not memory.entries


def test_malformed_proposal_uses_a_model_attempt_but_no_fictional_select():
    with completed_episode() as (session, trace):
        client = script('{"proposal":null,"proposal":null}', proposal(fields_for(trace)))
        budget = InferenceBudget()
        result = run_discovery_repair(trace, library(), client, budget, session, allow_learning=True)
        assert result['status'] == 'admitted' and result['new_select_attempts'] == 2
        assert result['attempts'][0]['status'] == 'proposal_rejected'
        assert 'duplicate JSON key' in result['attempts'][0]['error']
        assert budget.calls == 2 and [row['attempt'] for row in trace['queries']] == [1, 2, 3, 4]


@pytest.mark.parametrize('phase,learning', [('ordinary', False), ('old_before', True), ('final', True)])
def test_panels_and_disabled_learning_never_call_model_or_query(phase, learning):
    with completed_episode() as (session, trace):
        trace['phase'] = phase
        before = deepcopy(trace)
        client, memory = script(), library()
        result = run_discovery_repair(trace, memory, client, InferenceBudget(), session, allow_learning=learning)
        assert result['status'] == 'not_learning' and result['new_select_attempts'] == 0
        assert client.seen == [] and trace == before and not memory.entries
        assert not getattr(session, '_discovery_repair_v9_started', False)


def test_budget_failure_stops_before_another_query_or_proposal():
    with completed_episode() as (session, trace):
        client = script(proposal(bad_alias(fields_for(trace))))
        budget = InferenceBudget(max_calls=1)
        result = run_discovery_repair(trace, library(), client, budget, session, allow_learning=True)
        assert result['status'] == 'budget_stop' and result['new_select_attempts'] == 1
        assert len(client.seen) == budget.calls == 1 and session.select_attempts == 3


def test_unknown_model_usage_stops_without_reconstruction_or_retry(tmp_path, monkeypatch):
    key = tmp_path / 'offline-only.key'
    key.write_text('not-a-real-credential')
    client = LocalInferenceV9(key_file=key, endpoint='http://127.0.0.1:1', max_output=4096)
    paths = []
    def fake_post(path, body, timeout):
        paths.append(path)
        if path.endswith('/input_tokens'):
            return {'input_tokens': 10}
        raise OSError('explicit lost fake response')
    monkeypatch.setattr(client, '_post', fake_post)
    with completed_episode() as (session, trace):
        budget = InferenceBudget()
        result = run_discovery_repair(trace, library(), client, budget, session, allow_learning=True)
        assert result['status'] == 'model_failure' and result['new_select_attempts'] == 0
        assert budget.calls == 1 and budget.unknown_usage_calls == 1 and len(paths) == 2
        assert trace['model_calls'][0]['usage'] is None


def test_caller_forgery_of_original_answer_is_detected_before_querying():
    with completed_episode() as (session, trace):
        fields = fields_for(trace)
        def forge(messages, phase, index):
            trace['answer'] += 1
            return proposal(fields)
        result = run_discovery_repair(trace, library(), Client(forge), InferenceBudget(),
                                      session, allow_learning=True)
        assert result['status'] == 'evidence_changed' and session.select_attempts == 2


def test_hidden_trace_annotations_never_enter_repair_prompts():
    with completed_episode() as (session, trace):
        trace['evaluator'] = {'gold': 'private-evaluator-canary'}
        trace['future_question'] = 'private-future-canary'
        trace['other_arm'] = 'private-other-arm-canary'
        trace['queries'][0]['hidden_recipe'] = 'private-recipe-canary'
        client = script(proposal(bad_alias(fields_for(trace))), {'proposal': None})
        run_discovery_repair(trace, library(), client, InferenceBudget(), session, allow_learning=True)
        assert 'private-' not in canonical(client.seen)
        assert all(len(json.loads(call['messages'][1]['content'])['queries']) == 2 for call in client.seen)


def test_explicit_null_stops_immediately_and_cannot_reset_the_attempt_ceiling():
    with completed_episode() as (session, trace):
        memory = library()
        result = run_discovery_repair(trace, memory, script({'proposal': None}), InferenceBudget(),
                                      session, allow_learning=True)
        assert result['status'] == 'abstained' and result['new_select_attempts'] == 0
        client = script()
        again = run_discovery_repair(trace, memory, client, InferenceBudget(), session, allow_learning=True)
        assert again['status'] == 'already_attempted' and client.seen == [] and again['new_select_attempts'] == 0


def test_compiler_only_failures_cannot_reset_three_attempt_ceiling():
    with completed_episode() as (session, trace):
        memory, budget = library(), InferenceBudget()
        invalid = proposal(fields_for(trace))
        invalid['proposal']['source_index'] = 99
        result = run_discovery_repair(trace, memory, script(invalid, invalid, invalid), budget,
                                      session, allow_learning=True)
        assert result['status'] == 'attempt_cap' and budget.calls == 3 and session.select_attempts == 2
        client = script()
        again = run_discovery_repair(deepcopy(trace), memory, client, InferenceBudget(), session,
                                     allow_learning=True)
        assert again['status'] == 'already_attempted' and client.seen == [] and not memory.entries


def test_prior_learning_checks_cannot_be_presented_as_original_witnesses():
    with completed_episode() as (session, trace):
        result = session.query('SELECT 1', learning_check=True)
        from dataclasses import asdict
        trace['queries'].append({'sql': 'SELECT 1', 'params': {}, 'learning_check': True, **asdict(result)})
        client = script()
        outcome = run_discovery_repair(trace, library(), client, InferenceBudget(), session,
                                       allow_learning=True)
        assert outcome['status'] == 'not_eligible' and client.seen == [] and outcome['new_select_attempts'] == 0


def test_intervention_error_cannot_commit_a_successfully_reconstructed_entry():
    with completed_episode() as (session, trace):
        fields = fields_for(trace)
        fields['outer_sql'] = 'SELECT CASE WHEN COUNT(*)=0 THEN ABS(:bad) ELSE SUM(gross) END AS total FROM reused'
        fields['outer_params'] = {'bad': -(2**63)}
        memory = library()
        result = run_discovery_repair(trace, memory, script(proposal(fields), {'proposal': None}),
                                      InferenceBudget(), session, allow_learning=True)
        assert result['attempts'][0]['reconstruction']['error'] is None
        assert result['attempts'][0]['intervention']['error'] is not None
        assert result['attempts'][0]['status'] == 'dependence_rejected'
        assert result['new_select_attempts'] == 2 and not memory.entries
