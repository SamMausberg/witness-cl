from itertools import product
import random
import numpy as np
import pytest
from witness_cl.latent import LatentSpace, Machine, Program, value
from witness_cl.latent_v5 import (DecisionDirectedAgent, DecisionProfile, decision_profile,
                                minimax_regret_sum, guaranteed_regret_reductions)


def programs(horizon=3):
    return tuple(Program.word(word, 2) for word in product(range(2), repeat=horizon))


def direct_regret(a):
    return sum(min(max(max(a[m, q, g] for q in range(a.shape[1])) - a[m, p, g]
                           for m in range(a.shape[0])) for p in range(a.shape[1]))
               for g in range(a.shape[2]))


def test_regret_matches_independent_scalar_definition_and_duplicate_invariance():
    a = np.random.default_rng(12).integers(-8, 9, (9, 5, 3))
    assert minimax_regret_sum(a) == direct_regret(a)
    assert minimax_regret_sum(np.concatenate([a, a[:4]])) == direct_regret(a)
    assert minimax_regret_sum(a[:4]) <= minimax_regret_sum(a)


def test_regret_arithmetic_does_not_overflow_int64():
    a = np.array([[[2**62], [-2**62]], [[-2**62], [2**62]]], dtype=np.int64)
    assert minimax_regret_sum(a) == 2**63


def test_probe_can_distinguish_worlds_without_resolving_decisions():
    # The two outcomes differ, but every world prefers the same program.
    p = DecisionProfile('exact', (((((0, 0),)), (((1, 0),))),
                                  ((((0, 1),)), (((1, 1),)))),
                        (((2,), (0,)), ((4,), (1,))), 2, 4)
    assert guaranteed_regret_reductions(p) == (0, 0)


@pytest.mark.parametrize('seed', range(8))
def test_exact_quotient_and_each_outcome_regret_contraction(seed):
    rng = random.Random(seed)
    m = Machine(2, 2, 2, tuple((rng.randrange(2), rng.randrange(2)) for _ in range(4)))
    s = LatentSpace(2, 2, 2)
    s.observe(m.run((0, 1)))
    ps = programs(); rewards = ((0, 2), (2, 0))
    p = decision_profile(s, ps, rewards)
    a = np.asarray(p.returns)
    initial = direct_regret(a)
    assert p.status == 'exact'
    assert p.labelled_models == len(list(s.completions()))
    assert len(p.traces) == len(set(tuple(q.rollout(x) for q in ps) for x in s.completions()))
    gains = guaranteed_regret_reductions(p)
    for j in range(len(ps)):
        after = []
        for trace in set(row[j] for row in p.traces):
            subset = np.asarray([r for tr, r in zip(p.traces, p.returns) if tr[j] == trace])
            after.append(direct_regret(subset))
        assert gains[j] == initial - max(after) >= 0


def test_cap_unknown_has_no_profile_and_no_unpriced_probe():
    s = LatentSpace(2, 2, 2)
    p = decision_profile(s, programs(), ((0, 2),), max_models=1)
    assert p.status == 'unknown' and p.traces == p.returns == ()
    a = DecisionDirectedAgent(s, programs(), ((0, 2),), budget=16, max_models=1)
    t = a.choose(0)
    assert t.program == 0 and t.debit == a.spent == 0 and a.unknown > 0


@pytest.mark.parametrize('seed', range(12))
def test_integrated_prefix_budget_retention_and_only_executed_feedback(seed):
    rng = random.Random(seed)
    m = Machine(2, 2, 2, tuple((rng.randrange(2), rng.randrange(2)) for _ in range(4)))
    ps = programs(); goals = ((0, 2), (2, 0))
    a = DecisionDirectedAgent(LatentSpace(2, 2, 2), ps, goals, budget=12, seed=seed)
    previous = [value(m, ps[0], r) for r in goals]
    deficit = 0
    for n in range(18):
        g = n % 2
        t = a.choose(g)
        current = [value(m, ps[j], r) for j, r in zip(a.incumbents, goals)]
        assert all(x >= y for x, y in zip(current, previous))
        previous = current
        deficit += value(m, ps[0], goals[g]) - value(m, ps[t.program], goals[g])
        assert deficit <= a.spent <= 12
        trace = ps[t.program].rollout(m)
        a.observe(t, trace)
        assert a.space.contains(m)
        assert len(a.space.history) == n + 1 and a.space.history[-1] == trace
    assert a.proposer.updates == 18


def test_profile_cache_invalidated_by_evidence_and_registration():
    a = DecisionDirectedAgent(LatentSpace(1, 2, 2), (Program.word((0, 0), 2),), ((0, 2),))
    a._get_profile(); a._get_profile()
    assert a.profile_builds == a.profile_cache_hits == 1
    a.space.observe(((0, 0), (0, 0)))
    a._get_profile()
    assert a.profile_builds == 2
    a.register(Program.word((1, 1), 2))
    assert len(a._get_profile().traces[0]) == 2 and a.profile_builds == 3
