"""Mechanism and authorization tests, not a benchmark-superiority claim."""
from dataclasses import FrozenInstanceError, replace
from itertools import product
import copy
import sys

import numpy as np
import pytest

from witness_cl.latent import LatentSpace, Machine, Program, compare, value
from witness_cl.probe_v6 import DepthTwoProbeAgent, InformativeZeroLossAgent, OptimisticProbeAgent


ARMS = (DepthTwoProbeAgent, InformativeZeroLossAgent, OptimisticProbeAgent)


def parity_problem(bits=2):
    actions = bits + 3
    programs = tuple(Program.word((i,), 5) for i in range(actions))
    rewards = ((5, 5, 5, 0, 10),)
    worlds = []
    for setting in product((0, 1), repeat=bits):
        parity = sum(setting) % 2
        outputs = (0,) + tuple(1 + bit for bit in setting) + (4-parity, 3+parity)
        worlds.append(Machine(1, actions, 5, tuple((0, o) for o in outputs)))
    space = LatentSpace(1, actions, 5)
    space.partials = tuple(m.table for m in worlds)
    return space, programs, rewards, tuple(worlds)


def snapshot(agent):
    return (copy.deepcopy(agent.space.__dict__), tuple(agent.incumbents), agent.spent,
            agent.pending, tuple(agent.certificates), agent.episodes,
            agent.proposer.w1.copy(), agent.proposer.visits.copy(), agent.proposer.updates,
            agent.planning_work, agent.planning_seconds)


def assert_same_snapshot(before, after):
    for x, y in zip(before, after):
        if isinstance(x, np.ndarray):
            assert np.array_equal(x, y)
        else:
            assert x == y


@pytest.mark.parametrize('arm', ARMS)
@pytest.mark.parametrize('world_id', range(4))
def test_complementarity_all_worlds_returns_10_at_zero_risk(arm, world_id):
    space, programs, rewards, worlds = parity_problem()
    agent = arm(space, programs, rewards, budget=0, trainable=False, max_seconds=10)
    world = worlds[world_id]
    observed = []
    for _ in range(3):
        old = agent.incumbents[0]
        old_value = value(world, programs[old], rewards[0])
        ticket = agent.choose(0)
        assert agent.last_plan.status == 'exact'
        checked = compare(space, programs[ticket.program], programs[old], rewards[0])
        assert checked.admits
        assert ticket.debit == agent.spent == 0
        assert value(world, programs[agent.incumbents[0]], rewards[0]) >= old_value
        trace = programs[ticket.program].rollout(world)
        observed.append(sum(rewards[0][o] for _, o in trace))
        agent.observe(ticket, trace)
        assert space.contains(world)
    assert observed == [5, 5, 10]
    assert len(space.history) == 3
    assert agent.proposer.updates == 0
    assert agent.certificates[-1][-1] == 5


@pytest.mark.parametrize('arm', ARMS)
def test_plan_pure_and_immutable(arm):
    space, programs, rewards, _ = parity_problem()
    agent = arm(space, programs, rewards, trainable=False, max_seconds=10)
    before = snapshot(agent)
    plan = agent.plan(0)
    assert plan.status == 'exact'
    assert_same_snapshot(before, snapshot(agent))
    with pytest.raises(FrozenInstanceError):
        plan.debit = 100
    if arm is DepthTwoProbeAgent:
        assert plan.program in (1, 2)
        assert plan.guaranteed_gain == 5
        assert len(plan.branches) == 2
        assert all(debit == 0 for _, _, debit in plan.branches)


@pytest.mark.parametrize('arm', ARMS)
def test_work_boundary_exact_at_limit_unknown_one_event_before(arm):
    space, programs, rewards, _ = parity_problem()
    agent = arm(space, programs, rewards, trainable=False, max_seconds=10)
    work = agent.plan(0).work
    agent.max_work = work
    assert agent.plan(0).status == 'exact'
    agent.max_work = work - 1
    plan = agent.plan(0)
    assert plan.status == 'unknown'
    assert plan.reason == 'work cap'
    assert plan.work == work - 1
    assert plan.program == plan.incumbent == 0
    assert plan.lower is plan.upper is None
    assert plan.debit == 0 and not plan.promote
    assert agent.spent == 0 and agent.pending is None


@pytest.mark.parametrize('arm', ARMS)
def test_tiny_elapsed_limit_unknown_no_mutation(arm):
    space, programs, rewards, _ = parity_problem()
    agent = arm(space, programs, rewards, max_seconds=1e-12, trainable=False)
    before = snapshot(agent)
    plan = agent.plan(0)
    assert plan.status == 'unknown' and plan.reason == 'elapsed cap'
    assert_same_snapshot(before, snapshot(agent))


@pytest.mark.parametrize('rank', [[-1], [999], [True], [1, 1], ['1'], iter([1])])
def test_malformed_proposals_fail_closed(rank):
    space, programs, rewards, _ = parity_problem()
    agent = DepthTwoProbeAgent(space, programs, rewards, trainable=False)
    agent.proposer.rank = lambda *args, **kwargs: rank
    plan = agent.plan(0)
    assert plan.status == 'unknown' and plan.program == 0
    assert plan.debit == 0 and not plan.promote
    assert not agent.certificates and not space.history


def test_trace_hook_restored_on_exact_limit_and_unexpected_exception():
    space, programs, rewards, _ = parity_problem()
    agent = DepthTwoProbeAgent(space, programs, rewards, trainable=False, max_seconds=10)
    old = sys.gettrace()
    def previous(frame, event, arg):
        return previous
    try:
        sys.settrace(previous)
        assert agent.plan(0).status == 'exact'
        assert sys.gettrace() is previous
        agent.max_work = 1
        assert agent.plan(0).status == 'unknown'
        assert sys.gettrace() is previous
        agent.max_work = 10000
        def failure(*args, **kwargs):
            raise RuntimeError('test rank failure')
        agent.proposer.rank = failure
        with pytest.raises(RuntimeError, match='test rank failure'):
            agent.plan(0)
        assert sys.gettrace() is previous
        assert agent.pending is None and agent.spent == 0
    finally:
        sys.settrace(old)


def test_duplicate_completion_work_is_bounded_before_dedup_yield():
    space, programs, rewards, _ = parity_problem()
    # The fixed cap reaches profile enumeration after root candidate checks.
    space.partials = space.partials * 500
    agent = DepthTwoProbeAgent(space, programs, rewards, trainable=False,
                               max_work=280_000, max_seconds=10)
    plan = agent.plan(0)
    assert plan.status == 'unknown' and plan.reason == 'work cap'
    assert plan.work == 280_000
    assert plan.completion_attempts > plan.labelled_models
    assert plan.labelled_models == 4
    assert agent.spent == 0 and space.history == []


@pytest.mark.parametrize('arm', ARMS)
def test_invalid_feedback_ticket_or_action_cannot_update_state(arm):
    space, programs, rewards, worlds = parity_problem()
    agent = arm(space, programs, rewards, trainable=False, max_seconds=10)
    ticket = agent.choose(0)
    before = snapshot(agent)
    trace = programs[ticket.program].rollout(worlds[0])
    with pytest.raises(ValueError, match='foreign'):
        agent.observe(replace(ticket), trace)
    assert_same_snapshot(before, snapshot(agent))
    with pytest.raises(ValueError, match='action'):
        agent.observe(ticket, (((ticket.program+1) % len(programs), trace[0][1]),))
    assert_same_snapshot(before, snapshot(agent))
    agent.observe(ticket, trace)
    with pytest.raises(ValueError, match='foreign'):
        agent.observe(ticket, trace)
    assert len(space.history) == 1


@pytest.mark.parametrize('arm', ARMS)
def test_unknown_checker_and_incomplete_class_do_not_promote(arm):
    space, programs, rewards, _ = parity_problem()
    agent = arm(space, programs, rewards, trainable=False, max_nodes=1)
    assert agent.plan(0).status == 'unknown'
    space.complete = False
    plan = agent.plan(0)
    assert plan.status == 'unknown' and plan.work == 0
    space.complete = True
    space.partials = ()
    assert agent.plan(0).status == 'inconsistent'
    assert not agent.certificates and agent.spent == 0


@pytest.mark.parametrize('arm', ARMS)
def test_all_real_episode_debits_remain_nonrefundable(arm):
    space = LatentSpace(1, 2, 2)
    programs = (Program.word((0,), 2), Program.word((1,), 2))
    rewards = ((0, 2),)
    world = Machine(1, 2, 2, ((0, 1), (0, 0)))
    agent = arm(space, programs, rewards, budget=2, trainable=False, max_seconds=10)
    previous_spent = 0
    for _ in range(5):
        old = agent.incumbents[0]
        ticket = agent.choose(0)
        comparison = compare(space, programs[ticket.program], programs[old], rewards[0])
        assert comparison.status == 'exact'
        assert ticket.debit >= max(0, -comparison.lower)
        assert previous_spent <= agent.spent <= agent.budget
        assert agent.spent == previous_spent + ticket.debit
        actual_deficit = value(world, programs[old], rewards[0]) - value(world, programs[ticket.program], rewards[0])
        assert actual_deficit <= ticket.debit
        agent.observe(ticket, programs[ticket.program].rollout(world))
        assert agent.spent == previous_spent + ticket.debit
        previous_spent = agent.spent


def test_depth_two_limit_three_bit_parity_stalls_but_cheap_probes_solve():
    # Honest limitation: depth two does not resolve arbitrary complementarity.
    for arm, expected in ((DepthTwoProbeAgent, [5]*4),
                          (InformativeZeroLossAgent, [5, 5, 5, 10])):
        space, programs, rewards, worlds = parity_problem(bits=3)
        agent = arm(space, programs, rewards, budget=0, trainable=False, max_seconds=10)
        observed = []
        for _ in range(4):
            ticket = agent.choose(0)
            assert agent.last_plan.status == 'exact'
            trace = programs[ticket.program].rollout(worlds[0])
            observed.append(sum(rewards[0][o] for _, o in trace))
            agent.observe(ticket, trace)
        assert observed == expected


@pytest.mark.parametrize('field, value_', [('max_work', 0), ('max_work', True),
                                         ('max_seconds', float('inf')),
                                         ('max_seconds', 0), ('max_models', 0)])
def test_invalid_resource_limits_rejected(field, value_):
    space, programs, rewards, _ = parity_problem()
    with pytest.raises(ValueError):
        DepthTwoProbeAgent(space, programs, rewards, **{field: value_})


def test_model_cap_never_truncates_into_a_certificate():
    space, programs, rewards, _ = parity_problem()
    agent = DepthTwoProbeAgent(space, programs, rewards, max_models=3, trainable=False)
    plan = agent.plan(0)
    assert plan.status == 'unknown' and plan.reason == 'distinct model cap'
    assert plan.labelled_models == 3 and plan.program == 0
    assert plan.lower is None and not plan.promote


def test_program_registry_rejects_executable_untyped_proposals():
    space, programs, rewards, _ = parity_problem()
    agent = DepthTwoProbeAgent(space, programs, rewards, trainable=False)
    with pytest.raises(ValueError, match='typed Program'):
        agent.register('import os')
    assert agent.programs == programs


@pytest.mark.parametrize('alias', ['relative', 'symlink'])
def test_trace_scope_canonicalizes_file_aliases(alias, tmp_path):
    from pathlib import Path
    from types import SimpleNamespace
    import os
    from witness_cl import probe_v6
    from witness_cl.probe_v6 import _Meter, _PlanningLimit

    source = Path(probe_v6.__file__).resolve()
    if alias == 'relative':
        filename = os.path.relpath(source)
    else:
        link = tmp_path / 'linked_planner.py'
        try:
            link.symlink_to(source)
        except OSError:
            pytest.skip('test host cannot create symlinks')
        filename = str(link)
    frame = SimpleNamespace(f_code=SimpleNamespace(co_filename=filename))
    meter = _Meter(1, 10)
    meter.trace(frame, 'line', None)
    assert meter.work == 1
    with pytest.raises(_PlanningLimit, match='work cap'):
        meter.trace(frame, 'line', None)
    assert meter.work == 1


def test_global_branch_threshold_avoids_unnecessary_debit():
    from fractions import Fraction
    from witness_cl.probe_v6 import _threshold_choices
    branches = (((0, 10, 0, 1), (1, 0, 1, 2)), ((5, 0, 0, 3),))
    plans = list(_threshold_choices(branches))
    best = max(plans, key=lambda p: Fraction(6-p[0], 1+p[1]))
    assert best[0:2] == (5, 0)
    assert best[2][0][3] == 2
    assert Fraction(6-best[0], 1+best[1]) == 1


def test_threshold_frontier_matches_cartesian_plan_enumeration():
    from fractions import Fraction
    import random
    from witness_cl.probe_v6 import _threshold_choices
    rng = random.Random(606)
    for _ in range(100):
        branches = tuple(tuple((rng.randrange(11), rng.randrange(5), i, i)
                               for i in range(4)) for _ in range(3))
        first_debit = rng.randrange(5)
        def score(worst, debit):
            return Fraction(10-worst, 1+first_debit+debit)
        exhaustive = max(score(max(a[0] for a in plan), max(a[1] for a in plan))
                         for plan in product(*branches))
        frontier = max(score(worst, debit) for worst, debit, _ in _threshold_choices(branches))
        assert frontier == exhaustive
