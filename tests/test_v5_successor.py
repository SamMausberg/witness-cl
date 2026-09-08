from itertools import product
import random
from witness_cl.latent import LatentSpace, Machine, Program, value
from witness_cl.latent_v5 import DecisionDirectedAgent, guaranteed_regret_reductions
from witness_cl.latent_v5_successor import WeakDominanceClosureAgent


def test_zero_regret_does_not_mean_current_incumbent_is_optimal():
    ps = (Program.word((0,), 2), Program.word((1,), 2))
    truth = Machine(1, 2, 2, ((0, 0), (0, 1)))
    agents = [kind(LatentSpace(1, 2, 2), ps, ((0, 1),), budget=0)
              for kind in (DecisionDirectedAgent, WeakDominanceClosureAgent)]
    for a in agents:
        a.space.observe(((0, 0),))
        assert guaranteed_regret_reductions(a._get_profile()) == (0, 0)
    original, successor = [a.choose(0) for a in agents]
    assert original.program == 0 and successor.program == 1
    assert value(truth, ps[original.program], (0, 1)) == 0
    assert value(truth, ps[successor.program], (0, 1)) == 1
    assert successor.debit == 0 and agents[1].weak_promotions == 1
    agents[1].observe(successor, ps[successor.program].rollout(truth))


def test_successor_budget_and_incumbent_retention_on_all_two_state_tables():
    ps = tuple(Program.word(w, 2) for w in product(range(2), repeat=3))
    goals = ((0, 2), (2, 0))
    for index, table in enumerate(product(tuple(product(range(2), range(2))), repeat=4)):
        m = Machine(2, 2, 2, table)
        a = WeakDominanceClosureAgent(LatentSpace(2, 2, 2), ps, goals, budget=12, seed=index)
        old = [value(m, ps[0], r) for r in goals]; deficit = 0
        for n in range(12):
            g = n % 2; t = a.choose(g)
            now = [value(m, ps[j], r) for j, r in zip(a.incumbents, goals)]
            assert all(v >= u for u, v in zip(old, now)); old = now
            deficit += value(m, ps[0], goals[g]) - value(m, ps[t.program], goals[g])
            assert deficit <= a.spent <= 12
            a.observe(t, ps[t.program].rollout(m))
            assert a.space.contains(m)
