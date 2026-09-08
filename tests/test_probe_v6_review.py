"""Independent adversarial checks and a cheap decision-edge diagnostic.

The pair-count scorer below is a prior-free, worst-outcome adaptation used only
for this finite mechanism test. It is not a reproduction of Bayesian EC2 and
inherits no EC2 approximation claim.
"""
from itertools import combinations, product

import pytest

from witness_cl.latent import LatentSpace, Machine, Program, compare
from witness_cl.latent_v5 import decision_profile


def parity_case(bits=2):
    programs = tuple(Program.word((a,), 5) for a in range(bits + 3))
    rewards = ((5, 5, 5, 0, 10),)
    worlds = tuple(
        Machine(1, bits + 3, 5,
                tuple((0, output) for output in
                      (0, *(1 + b for b in bs), 3 + sum(bs) % 2,
                       4 - sum(bs) % 2)))
        for bs in product(range(2), repeat=bits)
    )
    space = LatentSpace(1, bits + 3, 5)
    space.partials = tuple(world.table for world in worlds)
    return space, programs, rewards, worlds


def unique_optimum_edge_gains(profile):
    """Count eliminated cross-decision pairs, taking the worst observation.

    Deliberately limited to unique single-goal optima to avoid silently changing
    the problem through arbitrary tie-breaking or overlapping decision regions.
    All inputs come from the learner's finite class, never the true evaluator.
    """
    assert profile.status == "exact"
    labels = []
    for world in profile.returns:
        assert all(len(value) == 1 for value in world)
        values = tuple(value[0] for value in world)
        best = max(values)
        assert values.count(best) == 1
        labels.append(values.index(best))
    edges = tuple((a, b) for a, b in combinations(range(len(labels)), 2)
                  if labels[a] != labels[b])
    gains = []
    for p in range(len(profile.traces[0])):
        outcomes = {traces[p] for traces in profile.traces}
        remaining = max(
            sum(profile.traces[a][p] == profile.traces[b][p] == observation
                for a, b in edges)
            for observation in outcomes
        )
        gains.append(len(edges) - remaining)
    return tuple(gains)


@pytest.mark.parametrize("bits", [2, 3])
def test_cheap_decision_edges_detect_free_parity_probes(bits):
    space, programs, rewards, _ = parity_case(bits)
    profile = decision_profile(space, programs, rewards)
    gains = unique_optimum_edge_gains(profile)
    assert gains[0] == 0
    assert all(gains[p] > 0 for p in range(1, bits + 1))
    assert all(compare(space, programs[p], programs[0], rewards[0]).lower == 0
               for p in range(1, bits + 1))


@pytest.mark.parametrize("bits", [2, 3])
def test_greedy_zero_loss_edge_diagnostic_resolves_every_parity_world(bits):
    _, programs, rewards, worlds = parity_case(bits)
    for true_world in worlds:
        space, _, _, _ = parity_case(bits)
        probes = []
        for _ in range(bits):
            gains = unique_optimum_edge_gains(decision_profile(space, programs, rewards))
            free = tuple(p for p in range(len(programs))
                         if compare(space, programs[p], programs[0], rewards[0]).lower >= 0)
            chosen = max(free, key=lambda p: (gains[p], -p))
            assert gains[chosen] > 0
            probes.append(chosen)
            space.observe(programs[chosen].rollout(true_world))
            assert space.contains(true_world)
        assert len(set(probes)) == bits
        assert tuple(space.completions()) == (true_world,)
        assert any(compare(space, p, programs[0], rewards[0]).lower == 5
                   for p in programs)


import sys
from witness_cl.probe_v6 import (DepthTwoProbeAgent, InformativeZeroLossAgent,
                                 OptimisticProbeAgent)

AGENTS = (DepthTwoProbeAgent, InformativeZeroLossAgent, OptimisticProbeAgent)


def protected_snapshot(agent):
    """Independent snapshot of evidence, permissions, learned state and ledgers."""
    p = agent.proposer
    s = agent.space
    return (
        s.states, s.actions, s.outputs, s.max_partials, s.partials,
        tuple(s.history), s.complete, s.generation, s.fit_branches,
        agent.programs, agent.rewards, agent.budget, agent.spent,
        tuple(agent.incumbents), agent.episodes, agent.era, agent.pending,
        tuple(agent.certificates), agent.promotions, agent.weak_promotions,
        agent.comparisons, agent.nodes, agent.unknown, agent.last_plan,
        agent.planning_work, agent.planning_seconds, agent.profile_builds,
        agent.completion_attempts, agent.labelled_models_enumerated,
        p.visits.tobytes(), p.w1.tobytes(), p.w2.tobytes(), p.b1.tobytes(),
        p.b2, p.updates,
    )


def make_agent(kind=DepthTwoProbeAgent, bits=2, **kwargs):
    space, programs, rewards, _ = parity_case(bits)
    return kind(space, programs, rewards, budget=0, trainable=False,
                max_seconds=10, **kwargs)


@pytest.mark.parametrize("kind", AGENTS)
def test_planning_is_pure_and_preserves_existing_trace_hook(kind):
    agent = make_agent(kind)
    before = protected_snapshot(agent)
    previous = sys.gettrace()

    def observer(frame, event, arg):
        return observer

    try:
        sys.settrace(observer)
        result = agent.plan(0)
        assert result.status == "exact"
        assert sys.gettrace() is observer
    finally:
        sys.settrace(previous)
    assert protected_snapshot(agent) == before


@pytest.mark.parametrize("kind", AGENTS)
@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_unexpected_planning_failure_restores_trace_without_mutation(kind, failure):
    agent = make_agent(kind)
    before = protected_snapshot(agent)

    def broken_rank(*args, **kwargs):
        raise failure("injected ranker failure")

    agent.proposer.rank = broken_rank
    previous = sys.gettrace()

    def observer(frame, event, arg):
        return observer

    try:
        sys.settrace(observer)
        with pytest.raises(failure, match="injected ranker failure"):
            agent.choose(0)
        assert sys.gettrace() is observer
    finally:
        sys.settrace(previous)
    assert protected_snapshot(agent) == before


@pytest.mark.parametrize("kind", AGENTS)
def test_work_interruption_before_commit_does_not_admit_partial_result(kind):
    space = LatentSpace(1, 2, 2)
    space.partials = (((0, 0), (0, 1)),)
    programs = tuple(Program.word((a,), 2) for a in range(2))
    agent = kind(space, programs, ((0, 1),), trainable=False, max_seconds=10)
    exact = agent.plan(0)
    assert exact.status == "exact" and exact.promote and exact.program == 1
    agent.max_work = exact.work - 1
    before = protected_snapshot(agent)
    interrupted = agent.plan(0)
    assert interrupted.status == "unknown" and interrupted.reason == "work cap"
    assert interrupted.work <= agent.max_work
    assert interrupted.program == 0 and interrupted.debit == 0
    assert not interrupted.promote and interrupted.lower is None
    assert protected_snapshot(agent) == before
    ticket = agent.choose(0)
    assert ticket.program == 0 and ticket.debit == 0
    assert agent.incumbents == [0] and not agent.certificates and agent.spent == 0


@pytest.mark.parametrize("kind", AGENTS)
def test_expired_cooperative_deadline_preserves_evidence_and_incumbent(kind):
    agent = make_agent(kind)
    agent.max_seconds = 1e-12
    before = protected_snapshot(agent)
    result = agent.plan(0)
    assert result.status == "unknown" and result.reason == "elapsed cap"
    assert result.work == 0 and not result.promote and result.debit == 0
    assert protected_snapshot(agent) == before


def test_duplicate_cover_work_cannot_hide_behind_distinct_model_limit():
    agent = make_agent(max_work=6000, max_models=4)
    agent.space.partials *= 1000
    before = protected_snapshot(agent)
    result = agent.plan(0)
    assert result.status == "unknown" and result.reason == "work cap"
    assert result.work == agent.max_work
    assert result.labelled_models <= 4
    assert not result.promote and result.debit == 0
    assert protected_snapshot(agent) == before


def test_profile_construction_work_is_charged_before_planning():
    agent = make_agent(max_work=3000)
    before = protected_snapshot(agent)
    result = agent.plan(0)
    assert result.status == "unknown" and result.reason == "work cap"
    assert 0 < result.completion_attempts <= 4
    assert result.work == agent.max_work
    assert protected_snapshot(agent) == before


def test_each_reported_second_probe_has_exact_branch_local_debit():
    agent = make_agent()
    plan = agent.plan(0)
    assert plan.status == "exact" and plan.guaranteed_gain == 5 and plan.branches
    all_worlds = tuple(agent.space.completions())
    for observed, second, debit in plan.branches:
        branch_worlds = tuple(m for m in all_worlds
                              if agent.programs[plan.program].rollout(m) == observed)
        assert branch_worlds
        branch = LatentSpace(agent.space.states, agent.space.actions, agent.space.outputs)
        branch.partials = tuple(m.table for m in branch_worlds)
        check = compare(branch, agent.programs[second], agent.programs[plan.incumbent],
                        agent.rewards[0])
        assert check.status == "exact"
        assert debit == max(0, -check.lower)
        assert plan.debit + debit <= agent.budget - agent.spent
    assert not agent.space.history and agent.space.generation == 0


def test_completed_plan_is_not_reused_after_real_observation_or_goal_change():
    space, programs, rewards, worlds = parity_case()
    agent = DepthTwoProbeAgent(space, programs, (rewards[0], (0, 0, 0, 10, 0)),
                              trainable=False, max_seconds=10)
    before = agent.plan(0)
    ticket = agent.choose(0)
    agent.observe(ticket, programs[ticket.program].rollout(worlds[0]))
    current = agent.plan(1)
    assert current.generation == before.generation + 1
    issued = agent.choose(1)
    assert issued.goal == 1 and issued.generation == current.generation
    assert issued.program == current.program
    assert agent.last_plan is not before


def test_duplicate_profile_attempts_are_charged_before_distinct_model_yield():
    space = LatentSpace(1, 1, 1)
    space.partials = (((0, 0),),) * 1000
    agent = DepthTwoProbeAgent(space, (Program.word((0,), 1),), ((0,),),
                              trainable=False, max_models=1, max_work=1000, max_seconds=10)
    before = protected_snapshot(agent)
    result = agent.plan(0)
    assert result.status == "unknown" and result.reason == "work cap"
    assert result.labelled_models == 1 and result.completion_attempts > 1
    assert result.work == agent.max_work
    assert protected_snapshot(agent) == before


@pytest.mark.parametrize("budget", [0, 1, 2, 3, 5])
def test_positive_branch_cost_requires_path_budget_and_is_charged_on_execution(budget):
    for true_world in parity_case()[3]:
        space, programs, _, _ = parity_case()
        rewards = ((5, 4, 4, 0, 10),)
        agent = DepthTwoProbeAgent(space, programs, rewards, budget=budget,
                                  trainable=False, max_seconds=10)
        debt = 0
        for _ in range(4):
            plan = agent.plan(0)
            assert plan.status == "exact"
            remaining = agent.budget - agent.spent
            for observed, second, branch_debit in plan.branches:
                branch = LatentSpace(1, 5, 5)
                branch.partials = tuple(m.table for m in agent.space.completions()
                                        if programs[plan.program].rollout(m) == observed)
                check = compare(branch, programs[second], programs[plan.incumbent], rewards[0])
                assert branch_debit == max(0, -check.lower)
                assert plan.debit + branch_debit <= remaining
            ticket = agent.choose(0)
            trace = programs[ticket.program].rollout(true_world)
            debt += 5 - sum(rewards[0][output] for _, output in trace)
            assert debt <= agent.spent <= budget
            agent.observe(ticket, trace)
            assert agent.space.contains(true_world)
        if budget < 2:
            assert agent.incumbents == [0] and agent.spent == 0
        else:
            assert agent.spent == 2
            assert sum(rewards[0][o] for _, o in programs[agent.incumbents[0]].rollout(true_world)) == 10


def test_final_checker_failure_discards_completed_promotion(monkeypatch):
    import witness_cl.probe_v6 as implementation
    space = LatentSpace(1, 2, 2)
    space.partials = (((0, 0), (0, 1)),)
    programs = tuple(Program.word((a,), 2) for a in range(2))
    agent = InformativeZeroLossAgent(space, programs, ((0, 1),),
                                     trainable=False, max_seconds=10)
    before = protected_snapshot(agent)
    original = implementation.compare
    calls = 0

    def fail_final(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("final checker failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(implementation, "compare", fail_final)
    with pytest.raises(RuntimeError, match="final checker failure"):
        agent.choose(0)
    assert calls == 3
    assert protected_snapshot(agent) == before


def _frozen_preflight_fixture(tmp_path, monkeypatch):
    import json
    pytest.importorskip("scipy")
    import experiments.probe_v6 as harness
    frozen = {
        "source_sha256": harness.source_hashes(),
        "holdout": dict(phase="holdout", seed_offset=61000, seeds=40, episodes=24,
                        max_work=2_000_000, max_seconds=1.0, max_models=4096,
                        max_nodes=100000, trainable=False, methods=list(harness.METHODS)),
    }
    freeze = tmp_path / "freeze.json"
    freeze.write_text(json.dumps(frozen))

    def stop_before_compute(*args, **kwargs):
        raise RuntimeError("preflight passed, intentionally stop before experiment")

    monkeypatch.setattr(harness, "product", stop_before_compute)
    return harness, freeze


def test_identical_json_frozen_configuration_passes_preflight(tmp_path, monkeypatch):
    harness, freeze = _frozen_preflight_fixture(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="preflight passed, intentionally stop"):
        harness.run(61000, 40, tmp_path / "valid", phase="holdout", freeze=freeze)
    assert (tmp_path / "valid" / "manifest.json").exists()


@pytest.mark.parametrize("override", [
    {"offset": 61001}, {"seeds": 39}, {"max_work": 1_999_999},
    {"max_seconds": 0.9}, {"phase": "development"},
])
def test_frozen_configuration_rejects_changed_caps_or_population(tmp_path, monkeypatch, override):
    harness, freeze = _frozen_preflight_fixture(tmp_path, monkeypatch)
    parameters = dict(offset=61000, seeds=40, out=tmp_path / "invalid",
                      max_work=2_000_000, max_seconds=1.0, phase="holdout", freeze=freeze)
    parameters.update(override)
    with pytest.raises(RuntimeError, match="configuration differs from frozen protocol"):
        harness.run(**parameters)
    assert not (tmp_path / "invalid" / "manifest.json").exists()
