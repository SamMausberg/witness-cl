"""Protocol, persistence and finite-null checks for the paired betting gate."""
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from itertools import product
import json
import math

import pytest

from witness_cl.statistical_gate_v7 import PairedBettingGate, constant_difference_min_pairs


def start(gate, suffix='0'):
    return gate.start('candidate-' + suffix, 'incumbent-' + suffix, 'public-scope')


def test_token_is_frozen_and_identifies_candidate_reference_and_scope():
    gate = PairedBettingGate()
    token = start(gate)
    with pytest.raises(FrozenInstanceError):
        token.scope = 'changed'
    result = gate.result(token)
    assert result.candidate_digest == 'candidate-0'
    assert result.incumbent_digest == 'incumbent-0'
    assert result.scope == 'public-scope' and result.status == 'collecting'
    assert result.allocated_alpha == 0.025


@pytest.mark.parametrize('kwargs', [
    {'alpha_total': 0}, {'alpha_total': 1}, {'alpha_total': float('nan')},
    {'alpha_total': float('inf')}, {'alpha_total': True}, {'alpha_total': 10**1000},
    {'max_pairs': 0}, {'max_pairs': 65}, {'max_pairs': True},
    {'max_audits': 0}, {'max_audits': 4097}, {'max_audits': True},
])
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        PairedBettingGate(**kwargs)


@pytest.mark.parametrize('arguments', [('', 'base', 'scope'), ('candidate', '', 'scope'),
                                         ('candidate', 'base', ''), ('candidate', 'base', []),
                                         ('candidate', 'base', 'x' * 257)])
def test_invalid_start_does_not_spend_error_budget(arguments):
    gate = PairedBettingGate()
    before = gate.snapshot()
    with pytest.raises(ValueError):
        gate.start(*arguments)
    assert gate.snapshot() == before and gate.allocated_alpha_total == 0


def test_every_started_audit_spends_its_allocation_without_refund():
    gate = PairedBettingGate(max_pairs=1, max_audits=4)
    total = Fraction(0)
    for index in range(1, 5):
        token = start(gate, str(index))
        alpha = Fraction.from_float(gate.alpha_total) / (index * (index + 1))
        total += alpha
        assert gate.result(token).allocated_alpha_exact == str(alpha)
        assert gate.allocated_alpha_total_exact == total
        result = gate.observe_pair(token, 0, 0, f'pair-{index}')
        assert result.status == 'inconclusive'
        assert gate.allocated_alpha_total_exact == total
    assert total < Fraction.from_float(gate.alpha_total)
    before = gate.snapshot()
    with pytest.raises(RuntimeError, match='audit cap'):
        start(gate, 'beyond-cap')
    assert gate.snapshot() == before


def test_active_audit_cannot_be_replaced_and_early_finish_does_not_refund():
    gate = PairedBettingGate()
    token = start(gate)
    before = gate.snapshot()
    with pytest.raises(RuntimeError, match='active audit'):
        start(gate, 'replacement')
    assert gate.snapshot() == before
    closed = gate.finish_inconclusive(token)
    assert closed.status == 'inconclusive' and closed.pairs == 0
    assert gate.allocated_alpha_total == 0.025
    second = start(gate, 'second')
    assert second.audit_index == 2
    assert gate.result(second).allocated_alpha == pytest.approx(0.05 / 6)


@pytest.mark.parametrize('candidate,incumbent', [
    (-0.1, 0), (1.1, 0), (0, -0.1), (0, 1.1), (float('nan'), 0),
    (0, float('inf')), (True, 0), (0, False), ('0.5', 0), (10**1000, 0),
])
def test_invalid_pair_is_transactional(candidate, incumbent):
    gate = PairedBettingGate()
    token = start(gate)
    before = gate.snapshot()
    with pytest.raises(ValueError):
        gate.observe_pair(token, candidate, incumbent, 'unconsumed')
    assert gate.snapshot() == before
    assert gate.observe_pair(token, 1, 0, 'unconsumed').pairs == 1


@pytest.mark.parametrize('field,value', [('scope', 'other-scope'),
                                         ('candidate_digest', 'changed-candidate'),
                                         ('incumbent_digest', 'changed-reference')])
def test_changed_policy_or_scope_is_rejected(field, value):
    gate = PairedBettingGate()
    token = start(gate)
    before = gate.snapshot()
    with pytest.raises(ValueError):
        gate.observe_pair(replace(token, **{field: value}), 1, 0, 'unconsumed')
    with pytest.raises(ValueError):
        gate.observe_pair(token, 1, 0, 'unconsumed', **{field: value})
    assert gate.snapshot() == before


def test_foreign_stale_and_reused_tokens_or_samples_cannot_add_wealth():
    gate = PairedBettingGate(max_pairs=1)
    token = start(gate)
    other = start(PairedBettingGate())
    before = gate.snapshot()
    with pytest.raises(ValueError, match='foreign'):
        gate.observe_pair(other, 1, 0, 'p0')
    assert gate.snapshot() == before
    gate.observe_pair(token, 1, 0, 'p0')
    new = start(gate, 'new')
    before = gate.snapshot()
    with pytest.raises(ValueError, match='completed'):
        gate.observe_pair(token, 1, 0, 'p1')
    with pytest.raises(ValueError, match='already consumed'):
        gate.observe_pair(new, 1, 0, 'p0')
    assert gate.snapshot() == before


def test_duplicate_in_active_audit_is_transactional():
    gate = PairedBettingGate()
    token = start(gate)
    gate.observe_pair(token, 1, 0, 'p0')
    before = gate.snapshot()
    with pytest.raises(ValueError, match='already consumed'):
        gate.observe_pair(token, 1, 0, 'p0')
    assert gate.snapshot() == before


def test_log_betting_statistic_matches_required_fixed_bet():
    gate = PairedBettingGate()
    token = start(gate)
    pairs = [(1, 0), (0, 1), (.8, .3), (.2, .2)]
    expected = 0.0
    for index, (candidate, incumbent) in enumerate(pairs):
        expected += math.log1p(0.5 * (candidate - incumbent))
        result = gate.observe_pair(token, candidate, incumbent, str(index))
        assert result.log_wealth == expected
        assert result.log_threshold == -math.log(result.allocated_alpha)


def test_first_audit_accepts_only_after_ten_perfect_pairs():
    gate = PairedBettingGate()
    token = start(gate)
    for index in range(10):
        result = gate.observe_pair(token, 1, 0, f'p{index}')
        assert result.status == ('collecting' if index < 9 else 'accepted')
    assert result.log_wealth >= result.log_threshold
    assert gate.active_token is None
    before = gate.snapshot()
    with pytest.raises(ValueError, match='completed'):
        gate.observe_pair(token, 1, 0, 'after-acceptance')
    assert gate.snapshot() == before


@pytest.mark.parametrize('candidate,incumbent', [(0, 0), (0.5, 0.5), (0, 1)])
def test_nonpositive_differences_are_inconclusive_at_64(candidate, incumbent):
    gate = PairedBettingGate()
    token = start(gate)
    for index in range(64):
        result = gate.observe_pair(token, candidate, incumbent, str(index))
    assert result.status == 'inconclusive' and result.pairs == 64
    assert result.log_wealth <= 0
    assert gate.allocated_alpha_total == .025


def test_exact_capital_blocks_an_upward_rounded_false_crossing(monkeypatch):
    import witness_cl.statistical_gate_v7 as implementation
    gate = PairedBettingGate()
    token = start(gate)
    monkeypatch.setattr(implementation.math, 'log1p', lambda value: 100.0)
    result = gate.observe_pair(token, 0, 1, 'adverse')
    assert result.log_wealth > result.log_threshold
    assert result.status == 'collecting'  # actual capital is only one half


def test_resumed_checkpoint_preserves_spending_and_sample_reuse_rejection():
    gate = PairedBettingGate()
    first = start(gate)
    gate.observe_pair(first, 1, 0, 'p0')
    gate.finish_inconclusive(first)
    second = start(gate, 'second')
    gate.observe_pair(second, .5, .25, 'p1')
    saved = json.loads(json.dumps(gate.snapshot()))
    restored = PairedBettingGate.from_snapshot(saved, minimum_started_audits=2,
                                             expected_journal_hash=gate.journal_hash)
    assert restored.snapshot() == saved
    assert restored.result(restored.active_token) == gate.result(second)
    before = restored.snapshot()
    with pytest.raises(ValueError, match='already consumed'):
        restored.observe_pair(restored.active_token, 1, 0, 'p0')
    assert restored.snapshot() == before
    restored.finish_inconclusive(restored.active_token)
    third = start(restored, 'third')
    assert third.audit_index == 3
    assert restored.result(third).allocated_alpha == pytest.approx(.05 / 12)
    assert restored.allocated_alpha_total == pytest.approx(.05 * 3 / 4)


def test_older_checkpoint_is_rejected_when_external_counter_or_head_is_pinned():
    gate = PairedBettingGate()
    first = start(gate)
    old = gate.snapshot()
    gate.finish_inconclusive(first)
    start(gate, 'second')
    with pytest.raises(ValueError, match='older'):
        PairedBettingGate.from_snapshot(old, minimum_started_audits=2)
    with pytest.raises(ValueError, match='trusted journal head'):
        PairedBettingGate.from_snapshot(old, expected_journal_hash=gate.journal_hash)


@pytest.mark.parametrize('change', ['reward', 'counter', 'total', 'hash', 'extra_event_field', 'format_bool'])
def test_checkpoint_tampering_is_rejected(change):
    gate = PairedBettingGate()
    token = start(gate)
    gate.observe_pair(token, 1, 0, 'p0')
    saved = gate.snapshot()
    if change == 'reward':
        saved['events'][-1]['candidate_reward'] = 0
    elif change == 'counter':
        saved['started_audits'] = 0
    elif change == 'total':
        saved['allocated_alpha_total_exact'] = '0'
    elif change == 'hash':
        saved['journal_hash'] = '0' * 64
    elif change == 'extra_event_field':
        saved['events'][-1]['untrusted_field'] = 'x'
    elif change == 'format_bool':
        saved['format_version'] = True
    with pytest.raises(ValueError):
        PairedBettingGate.from_snapshot(saved)


def test_finite_null_enumeration_controls_anytime_false_acceptance():
    # Every length-eight +/-1 path has probability 1/256 under the exact null.
    # Enumerating all paths checks stopping after every pair, not just at n=8.
    accepted = 0
    for outcomes in product((0, 1), repeat=8):
        gate = PairedBettingGate(alpha_total=.2, max_pairs=8)
        token = start(gate)
        for index, win in enumerate(outcomes):
            result = gate.observe_pair(token, win, 1 - win, str(index))
            if result.status == 'accepted':
                accepted += 1
                break
    probability = Fraction(accepted, 2**8)
    assert probability == Fraction(1, 64)
    assert probability <= Fraction.from_float(.2) / 2


def test_zero_variance_power_limit_is_visible():
    assert constant_difference_min_pairs(.05, .025) is None
    assert constant_difference_min_pairs(.1, .025) is None
    assert constant_difference_min_pairs(.2, .025) == 39
    assert constant_difference_min_pairs(1, .025) == 10
    assert constant_difference_min_pairs(0, .025) is None
    gate = PairedBettingGate()
    token = start(gate)
    for index in range(39):
        result = gate.observe_pair(token, .2, 0, str(index))
    assert result.status == 'accepted'


def test_positive_mean_alternative_has_low_half_bet_eventual_power():
    # Independent analytic counterexample: D is +1 with probability 11/20,
    # and -1 otherwise. Its mean gain is +0.1, but half-bet log capital has
    # negative drift. This is a power failure under an alternative, not a
    # false-acceptance or validity failure under the null.
    p = Fraction(11, 20)
    assert 2 * p - 1 == Fraction(1, 10)
    log_growth = float(p) * math.log(1.5) + float(1-p) * math.log(.5)
    assert log_growth < -.08

    # Stronger: E[sqrt(next capital / current capital)] < 1, so sqrt(E_t)
    # is itself a nonnegative supermartingale under this positive alternative.
    # Ville then bounds eventual acceptance at alpha_j by sqrt(alpha_j).
    half_moment = float(p) * math.sqrt(1.5) + float(1-p) * math.sqrt(.5)
    assert half_moment < 1
    first_alpha = PairedBettingGate().alpha_total / 2
    assert math.sqrt(first_alpha) < .159

    # A smaller prespecified bet has positive log growth on the same law.
    # That suggests predictable adaptation or a fixed mixture for a later
    # design; it does not change the current gate or its 64-pair protocol.
    smaller_bet_growth = float(p)*math.log(1.1) + float(1-p)*math.log(.9)
    assert smaller_bet_growth > .005
