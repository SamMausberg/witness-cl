"""Deliberate saved-data tampering must fail independent numerical/gate replay."""
import copy
import json
from pathlib import Path

import pytest

from experiments.audit_relational_v7 import (
    ReplayFailure, audit_stream, checked_policy, reference_seed, replay_gate,
    replay_gold, replay_prediction, replay_reward, reconstructed_context,
)


@pytest.fixture(scope='module')
def saved_fixture():
    # The producer is used only to create a small actual-execution test fixture.
    # The independently tested verifier imports none of its implementations.
    from experiments.relational_v7 import Config, run_arm
    config = Config(warm_rounds=4, novel_rounds=4, retention_rounds=0,
                    snapshot_contexts=1, final_contexts=1)
    raw = run_arm(177, 'audited_full_history_sparse', 'matched', config=config)
    assert raw['status'] == 'complete'
    assert any(a['status'] == 'accepted' for a in raw['audits'])
    return json.loads(json.dumps(raw))


def test_saved_actual_fixture_replays_without_model_or_gate_import(saved_fixture):
    result = audit_stream(saved_fixture)
    assert result['checked']['ordinary_contexts'] == 32
    assert result['checked']['snapshot_contexts'] == 8
    assert result['checked']['final_contexts'] == 8
    assert result['checked']['gate_prefixes'] > 0
    source = (Path(__file__).resolve().parents[1]/'experiments/audit_relational_v7.py').read_text()
    assert 'from witness_cl' not in source
    assert 'from experiments.relational_v7' not in source


def test_independent_arithmetic_and_sql_share_no_producer_evaluator():
    seed = reference_seed(177, 0, 'ordinary')
    rows = reconstructed_context(seed)[2]
    policy = {'features': [[1, 0, 0, 0, 1, 0], [0, 1, 0, 0, 0, 1]], 'coefficients': [2.0, -1.0]}
    recipe = ((tuple(policy['features'][0]), 2), (tuple(policy['features'][1]), -1))
    prediction = replay_prediction(policy, rows)
    assert prediction == replay_gold(seed, recipe)
    assert replay_reward(prediction, prediction) == 1
    assert replay_reward(prediction+1, prediction) == 0
    assert len(checked_policy(policy)[2]) == 64


def test_tampered_accepted_status_caught_before_promotion(saved_fixture):
    raw = copy.deepcopy(saved_fixture)
    prefix = next(p['gate_prefix'] for a in raw['audits'] for p in a['pairs']
                  if p['gate_prefix']['status'] == 'collecting')
    prefix['status'] = 'accepted'
    with pytest.raises(ReplayFailure, match='gate result mismatch: status'):
        audit_stream(raw)


def test_tampered_gate_acceptance_caught_by_exact_replayed_wealth(saved_fixture):
    snapshot = copy.deepcopy(saved_fixture['gate_snapshot'])
    event = next(e for e in snapshot['events'] if e['kind'] == 'pair' and e['status'] == 'collecting')
    event['status'] = 'accepted'
    with pytest.raises(ReplayFailure, match='independent wealth'):
        replay_gate(snapshot)


def test_tampered_reward_caught_by_independent_sql_and_policy(saved_fixture):
    raw = copy.deepcopy(saved_fixture)
    row = raw['ordinary'][0]
    row['reward'] = 1-row['reward']
    row['rewards'][0] = row['reward']
    with pytest.raises(ReplayFailure, match='saved reward'):
        audit_stream(raw)


def test_tampered_actual_query_counter_caught(saved_fixture):
    raw = copy.deepcopy(saved_fixture)
    raw['ordinary'][0]['costs']['select_executions'] += 1
    with pytest.raises(ReplayFailure, match='counter mismatch'):
        audit_stream(raw)


def test_tampered_history_update_counter_caught(saved_fixture):
    raw = copy.deepcopy(saved_fixture)
    raw['ordinary'][0]['learner_updates'] += 1
    with pytest.raises(ReplayFailure, match='history update counter'):
        audit_stream(raw)


def test_tampered_policy_coefficients_caught_by_digest(saved_fixture):
    raw = copy.deepcopy(saved_fixture)
    digest = raw['ordinary'][0]['installed_digest']
    raw['policy_registry'][digest]['coefficients'][0] += 1
    with pytest.raises(ReplayFailure, match='policy digest mismatch'):
        audit_stream(raw)


def test_tampered_context_measurements_caught_by_seed_reconstruction(saved_fixture):
    raw = copy.deepcopy(saved_fixture)
    row = raw['ordinary'][0]['observation']['rows'][0]
    row[0] = row[0]+1
    with pytest.raises(ReplayFailure, match='independently regenerated context'):
        audit_stream(raw)


def test_tampered_gold_target_caught_by_sql(saved_fixture):
    raw = copy.deepcopy(saved_fixture)
    raw['ordinary'][0]['target'] += 1
    with pytest.raises(ReplayFailure, match='independent SQL'):
        audit_stream(raw)


def test_other_report_policy_mutation_caught(saved_fixture):
    raw = copy.deepcopy(saved_fixture)
    promotion = raw['promotions'][0]
    other = next(iter(promotion['other_policy_digests']))
    promotion['other_policy_digests'][other] = promotion['candidate_digest']
    with pytest.raises(ReplayFailure, match='another public report'):
        audit_stream(raw)


def test_alpha_refund_counter_and_duplicate_samples_caught(saved_fixture):
    snapshot = copy.deepcopy(saved_fixture['gate_snapshot'])
    snapshot['started_audits'] -= 1
    with pytest.raises(ReplayFailure, match='audit counter'):
        replay_gate(snapshot)
    snapshot = copy.deepcopy(saved_fixture['gate_snapshot'])
    pairs = [e for e in snapshot['events'] if e['kind'] == 'pair']
    pairs[1]['sample_id'] = pairs[0]['sample_id']
    with pytest.raises(ReplayFailure, match='duplicate'):
        replay_gate(snapshot)


def test_missing_or_misaligned_retention_and_final_panels_caught(saved_fixture):
    for label in ('after_warm', 'after_novel', 'final'):
        raw = copy.deepcopy(saved_fixture)
        raw['evaluations'][label].pop()
        with pytest.raises(ReplayFailure, match='panel length'):
            audit_stream(raw)
    raw = copy.deepcopy(saved_fixture)
    raw['evaluations']['after_novel'][0]['context_seed'] += 1
    with pytest.raises(ReplayFailure, match='declared namespace'):
        audit_stream(raw)


@pytest.mark.parametrize('field', ['shared_novel_first24_reward', 'shared_novel_first8_reward'])
def test_tampered_transfer_summary_caught(saved_fixture, field):
    raw = copy.deepcopy(saved_fixture)
    raw['summary'][field] += .125
    with pytest.raises(ReplayFailure, match='summary '+field):
        audit_stream(raw)


def test_audit_feedback_update_and_unaccepted_installation_caught(saved_fixture):
    raw = copy.deepcopy(saved_fixture)
    raw['audits'][0]['learner_updates_after'] += 1
    with pytest.raises(ReplayFailure, match='audit data updated'):
        audit_stream(raw)
    raw = copy.deepcopy(saved_fixture)
    row = raw['ordinary'][0]
    row['incumbent_after_digest'] = row['candidate_digest']
    with pytest.raises(ReplayFailure, match='without a matching authorized promotion'):
        audit_stream(raw)


def test_small_budget_companion_prefixes_and_fresh_audit_namespace():
    from experiments.relational_v7 import Config, run_arm
    config = Config(warm_rounds=4, novel_rounds=4, retention_rounds=0,
                    snapshot_contexts=0, final_contexts=1, total_select_budget=89)
    raw = json.loads(json.dumps(run_arm(178, 'audited_full_history_sparse', 'budget', config=config)))
    result = audit_stream(raw)
    assert result['checked']['budget_prefixes'] > 0
    assert result['summary']['total_select_executions'] <= 89
    assert result['summary']['work_select_executions'] <= 65
    if raw['audits'] and raw['audits'][0]['pairs']:
        pair = raw['audits'][0]['pairs'][0]
        report_id = raw['audits'][0]['report_id']
        matched_seed = reference_seed(178, raw['method'], 'matched', report_id, 1, 0, 'audit')
        assert pair['context_seed'] != matched_seed
