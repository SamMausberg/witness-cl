"""SQLite semantics, feedback boundaries, frozen policies, and bounded growth."""
from dataclasses import FrozenInstanceError, fields
from itertools import product
import inspect
import json
import math
import sqlite3

import numpy as np
import pytest

from witness_cl.relational_v7 import (
    BASIS, INITIAL_FEATURES, FrozenPolicy, Learner, Observation, SQLiteContext,
    feature_value, make_context,
)


MODES = Learner.MODES
INTERACTION = (1, 1, 0, 0, 0, 0)


def training_example(seed, spec=(((1, 1, 0, 0, 0, 0), 2),)):
    with make_context(seed) as context:
        return context.observe(), context.answer(spec)


def test_basis_has_all_84_typed_degree_three_features():
    assert len(BASIS) == len(set(BASIS)) == 84
    assert len(INITIAL_FEATURES) == 7
    assert all(sum(m) <= 1 for m in INITIAL_FEATURES)
    assert INTERACTION not in INITIAL_FEATURES and INTERACTION in BASIS
    assert all(type(m) is tuple and len(m) == 6 and sum(m) <= 3 for m in BASIS)


@pytest.mark.parametrize('seed', range(4))
def test_all_basis_features_match_independent_sqlite_join_and_sum(seed):
    with make_context(seed) as context:
        observed = context.observe()
        assert observed.query_count == context.query_count == 2
        assert context.answer_query_count == 0
        for mono in BASIS:
            assert feature_value(observed, mono) == context.answer(((mono, 1),))
        assert context.answer_query_count == 84
        assert context.query_count == 2
        assert 12 <= len(observed.rows) <= 40
        assert observed.query_seconds >= 0
        assert context.setup_seconds >= 0


def test_measurements_record_both_tables_and_foreign_key_join():
    items = ((0, 1, 3, -1, 0, 2), (1, 0, -3, 1, 2, 0))
    groups = ((0, 2, -1), (1, -2, 1))
    with SQLiteContext(items, groups) as context:
        observed = context.observe()
        assert observed.items == items and observed.groups == groups
        assert observed.rows == ((3, -1, 0, 2, -2, 1), (-3, 1, 2, 0, 2, -1))
        spec = (((1, 0, 0, 0, 1, 0), 2), ((0, 1, 0, 0, 0, 1), -1))
        assert context.answer(spec) == sum(2*r[0]*r[4]-r[1]*r[5] for r in observed.rows)


@pytest.mark.parametrize('sql', [
    'DELETE FROM items',
    'WITH unused AS (SELECT 1) DELETE FROM items',
    'PRAGMA query_only=OFF',
    "ATTACH DATABASE ':memory:' AS unauthorized",
    "SELECT load_extension('untrusted')",
    'SELECT name FROM sqlite_master',
    'CREATE TABLE injected(x INTEGER)',
])
def test_sql_authorizer_rejects_nonread_and_unapproved_functions(sql):
    with make_context(20) as context:
        before = context.observe().rows
        queries = context.query_count
        with pytest.raises(sqlite3.DatabaseError):
            context._query(sql)
        assert context.query_count == queries + 1
        assert context.observe().rows == before


def test_sql_vm_limit_and_time_limit_interrupt_and_charge_attempts():
    items = ((0, 0, 1, 2, 3, 1),)
    groups = ((0, 1, -1),)
    for kwargs in ({'max_vm_steps': 1}, {'max_query_seconds': 1e-12}):
        with SQLiteContext(items, groups, **kwargs) as context:
            with pytest.raises(sqlite3.OperationalError, match='interrupted'):
                context.observe()
            assert context.query_count == 1
            assert context.query_seconds > 0


def test_query_result_row_cap_and_closed_context_fail():
    context = make_context(21)
    with pytest.raises(ValueError, match='row cap'):
        context._query('SELECT id FROM items', row_limit=1)
    assert context.query_count == 1
    context.close()
    with pytest.raises(RuntimeError, match='closed'):
        context.observe()


@pytest.mark.parametrize('spec', [
    (), (((4, 0, 0, 0, 0, 0), 1),), (((1, 0, 0, 0, 0, 0), True),),
    (("DROP TABLE items", 1),), (((1, 0, 0, 0, 0, 0), 0),),
])
def test_gold_renderer_rejects_untyped_specs_without_query(spec):
    with make_context(22) as context:
        with pytest.raises(ValueError):
            context.answer(spec)
        assert context.answer_query_count == context.query_count == 0


def test_no_hidden_spec_seed_handle_or_evaluator_label_in_measurement_api():
    assert {f.name for f in fields(Observation)} == {
        'rows', 'items', 'groups', 'query_count', 'query_seconds'}
    assert tuple(inspect.signature(Learner.observe).parameters) == (
        'self', 'report', 'observation', 'target')
    observed, target = training_example(23)
    assert all('sql' not in key and 'target' not in key and 'seed' not in key
               for key in observed.to_dict())
    learner = Learner()
    learner.observe('public_report', observed, target)
    with pytest.raises(ValueError):
        learner.observe('public_report', observed, None)


def test_visible_measurements_and_policy_serialization_have_no_mutable_aliases():
    observed, _ = training_example(24)
    with pytest.raises(FrozenInstanceError):
        observed.rows = ()
    policy = FrozenPolicy((INTERACTION,), (2.0,))
    payload = json.loads(json.dumps(policy.to_dict()))
    copied = FrozenPolicy.from_dict(payload)
    prediction, digest = copied.predict(observed), copied.digest
    payload['features'][0][0] = 3
    payload['coefficients'][0] = 999
    assert copied.predict(observed) == prediction and copied.digest == digest
    assert copied == policy and copied.digest == policy.digest
    with pytest.raises(FrozenInstanceError):
        copied.coefficients = (1.0,)
    assert copied.predict_with_cost(observed) == (prediction, len(observed.rows))


@pytest.mark.parametrize('mode', ('grow_reuse', 'grow_no_reuse'))
def test_actual_interaction_feature_is_added_from_own_feedback(mode):
    learner = Learner(mode)
    first = learner.propose('report_a')
    for i in range(32):
        observed, target = training_example(7000+i)
        learner.observe('report_a', observed, target)
    policy = learner.propose('report_a')
    assert INTERACTION in policy.features and INTERACTION not in first.features
    assert any(event['feature'] == INTERACTION for event in learner.feature_events)
    assert all(event['candidate_count'] <= 16 for event in learner.feature_events)
    for seed in range(8000, 8008):
        observed, target = training_example(seed)
        assert abs(policy.predict(observed)-target) <= 1e-6*(1+abs(target))
    assert learner.metrics['fit_failures'] == 0
    assert learner.metrics['feature_evaluations'] > 0
    assert learner.metrics['row_feature_evaluations'] > learner.metrics['feature_evaluations']


def test_bank_changes_only_on_promotion_of_own_frozen_proposal():
    learner = Learner('grow_reuse')
    for i in range(16):
        learner.observe('report_a', *training_example(7000+i))
    assert learner.bank == ()
    policy = learner.propose('report_a')
    learner.on_promotion('report_a', policy)
    assert INTERACTION in learner.bank
    counts = dict(learner._bank)
    learner.on_promotion('report_a', policy)
    assert learner._bank == counts
    with pytest.raises(ValueError, match='frozen proposal'):
        learner.on_promotion('other_report', policy)
    with pytest.raises(ValueError, match='frozen proposal'):
        learner.on_promotion('report_a', FrozenPolicy((BASIS[-1],), (1.0,)))
    observed, target = training_example(8100)
    digest, prediction = policy.digest, policy.predict(observed)
    for i in range(16):
        learner.observe('report_b', *training_example(7200+i))
    assert any(event['report'] == 'report_b' and event['source'] == 'promoted_bank'
               for event in learner.feature_events)
    assert policy.digest == digest and policy.predict(observed) == prediction


@pytest.mark.parametrize('mode', ('grow_no_reuse', 'full_ridge', 'full_history_sparse'))
def test_control_promotions_do_not_create_shared_bank(mode):
    learner = Learner(mode)
    learner.observe('report_a', *training_example(7000))
    learner.on_promotion('report_a', learner.propose('report_a'))
    assert learner.bank == ()


def test_full_history_sparse_strong_control_recovers_two_term_report():
    spec = ((INTERACTION, 2), ((0, 0, 1, 0, 1, 0), -1))
    learner = Learner('full_history_sparse')
    for i in range(40):
        learner.observe('report_a', *training_example(7300+i, spec))
    policy = learner.propose('report_a')
    assert len(policy.features) <= 3
    for seed in range(8200, 8210):
        observed, target = training_example(seed, spec)
        assert abs(policy.predict(observed)-target) <= 1e-6*(1+abs(target))
    assert learner.metrics['candidate_scores'] >= 84
    assert learner.report_summary('report_a')['last_fit_calls'] <= 3
    assert learner.report_summary('report_a')['last_distinct_candidates'] == 84


@pytest.mark.parametrize('mode', MODES)
def test_history_and_work_resource_limits_are_visible(mode):
    learner = Learner(mode, max_history=8, max_reports=1)
    for i in range(12):
        learner.observe('a', *training_example(7400+i))
    assert learner.report_summary('a')['history'] == 8
    assert learner.metrics['history_evictions'] == 4
    assert learner.metrics['history_bytes'] > 0 and learner.metrics['feature_cache_bytes'] > 0
    assert learner.report_summary('a')['last_distinct_candidates'] <= 84
    assert learner.report_summary('a')['last_fit_calls'] <= 3
    with pytest.raises(ValueError, match='registry cap'):
        learner.observe('b', *training_example(7500))


def test_failed_fit_cannot_replace_previous_policy():
    learner = Learner('full_ridge', max_candidate_features=7)
    before = learner.propose('a')
    learner.observe('a', *training_example(7600))
    after = learner.propose('a')
    assert learner.metrics['fit_failures'] == 1
    assert after == before
    assert learner.report_summary('a')['history'] == 1


@pytest.mark.parametrize('mode', MODES)
def test_empty_join_has_zero_sum_and_finite_policy(mode):
    with SQLiteContext((), ((0, 1, -1),)) as context:
        observed = context.observe()
        assert observed.rows == ()
        assert context.answer(((BASIS[0], 2),)) == 0
    learner = Learner(mode)
    learner.observe('a', observed, 0)
    assert learner.propose('a').predict(observed) == 0


@pytest.mark.parametrize('mode', ('grow_reuse', 'grow_no_reuse', 'full_history_sparse'))
def test_count_feature_learns_constant_per_row_report(mode):
    learner = Learner(mode)
    spec = ((BASIS[0], 3),)
    for i in range(16):
        learner.observe('a', *training_example(7700+i, spec))
    observed, target = training_example(8300, spec)
    assert abs(learner.propose('a').predict(observed)-target) < 1e-6*(1+abs(target))


@pytest.mark.parametrize('mode', MODES)
def test_quartic_parity_is_not_representable_by_degree_three_library(mode):
    # On the full Boolean cube, fourth-degree parity is orthogonal to every
    # monomial of total degree <= 3. The evaluator really executes quartic SQL.
    learner = Learner(mode, search_candidates=84)
    examples = []
    for signs in product((-1, 1), repeat=4):
        with SQLiteContext(((0, 0)+signs,), ((0, 1, 1),)) as context:
            observed = context.observe()
            target = float(context._query(
                'SELECT SUM(i.x0*i.x1*i.x2*i.x3) FROM items i', row_limit=1, answer=True)[0][0])
        examples.append((observed, target))
        learner.observe('quartic', observed, target)
    policy = learner.propose('quartic')
    assert any(abs(policy.predict(o)-y) > 1e-3 for o, y in examples)
    assert not hasattr(policy, 'certified')
    assert all(sum(m) <= 3 for m in policy.features)


@pytest.mark.parametrize('mode', MODES)
def test_noisy_feedback_produces_only_finite_uncertified_proposals(mode):
    learner = Learner(mode)
    for i in range(20):
        observed, target = training_example(7800+i)
        learner.observe('noisy', observed, target + (.25 if i % 2 else -.25))
    policy = learner.propose('noisy')
    observed, _ = training_example(8400)
    assert math.isfinite(policy.predict(observed))
    assert not hasattr(policy, 'certified')


@pytest.mark.parametrize('kwargs', [
    {'max_history': 257}, {'max_reports': 33}, {'max_features': 13},
    {'bank_limit': 33}, {'search_candidates': 85}, {'max_fits': 0},
    {'max_candidate_features': 129}, {'ridge': float('nan')},
])
def test_invalid_resource_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        Learner(**kwargs)


def test_observation_rejects_false_join_and_out_of_bound_unreferenced_group():
    with pytest.raises(ValueError):
        Observation(((1, 0, 0, 0, 0, 0),), ((0, 0, 1, 0, 0, 0),), ((0, 1, 1),))
    with pytest.raises(ValueError):
        Observation((), (), ((0, 999, 0),))
    with pytest.raises(ValueError):
        SQLiteContext(iter(()), ())


def test_companion_full_history_window_retains_256_observed_examples_with_cached_features():
    learner = Learner('full_history_sparse', max_history=256)
    observed = Observation(((1, 0, 0, 0, 1, 0),))
    for _ in range(257):
        learner.observe('a', observed, 1.0)
    assert learner.report_summary('a')['history'] == 256
    assert learner.metrics['history_evictions'] == 1
    # Each event's 84 feature values were extracted once despite every refit.
    assert learner.metrics['feature_evaluations'] == 257 * 84
    assert learner.metrics['feature_cache_bytes'] == 256 * 84 * 8


def test_full_ridge_control_recovers_report_with_sufficient_retained_history():
    learner = Learner('full_ridge', max_history=256)
    spec = ((INTERACTION, 2), ((0, 0, 1, 0, 1, 0), -1))
    for i in range(120):
        learner.observe('a', *training_example(9000+i, spec))
    policy = learner.propose('a')
    assert len(policy.features) == 84
    for i in range(10):
        observed, target = training_example(9500+i, spec)
        assert abs(policy.predict(observed)-target) <= 1e-6*(1+abs(target))
    assert learner.metrics['fit_failures'] == 0
