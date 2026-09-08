"""A known limitation: two useful free probes can each have zero initial score."""
from itertools import product
import pytest
from witness_cl.latent import LatentSpace, Machine, Program, compare
from witness_cl.latent_v5 import DecisionDirectedAgent, guaranteed_regret_reductions
from witness_cl.latent_v5_successor import WeakDominanceClosureAgent


@pytest.mark.parametrize('kind', [DecisionDirectedAgent, WeakDominanceClosureAgent])
def test_complementary_free_probes_remain_a_failure_for_both_selectors(kind):
    programs = tuple(Program.word((a,), 5) for a in range(5))
    rewards = ((5, 5, 5, 0, 10),)
    worlds = [Machine(1, 5, 5, tuple((0, o) for o in
              (0, 1+a, 1+b, 4-(a^b), 3+(a^b)))) for a, b in product(range(2), repeat=2)]
    def space():
        s = LatentSpace(1, 5, 5)
        # Explicit finite correlated class, not the benchmark's unconstrained one.
        s.partials = tuple(m.table for m in worlds)
        return s
    a = kind(space(), programs, rewards, budget=0)
    assert guaranteed_regret_reductions(a._get_profile()) == (0, 0, 0, 5, 5)
    for _ in range(4):
        t = a.choose(0)
        assert t.program == 0 and t.debit == 0
        a.observe(t, programs[0].rollout(worlds[0]))
        assert len(list(a.space.completions())) == 4
    for world in worlds:
        s = space()
        for index in (1, 2):
            c = compare(s, programs[index], programs[0], rewards[0])
            assert c.lower == c.upper == 0
            s.observe(programs[index].rollout(world))
        informed = kind(s, programs, rewards, budget=0)
        ticket = informed.choose(0)
        assert compare(s, programs[ticket.program], programs[0], rewards[0]).lower == 5
        assert informed.spent == 0
