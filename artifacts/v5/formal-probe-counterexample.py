#!/usr/bin/env python3
"""Reproduce a zero-loss complementary-probe failure of the frozen v5 rule.

From repository root:
  PYTHONPATH=src python3 artifacts/v5/formal-probe-counterexample.py

This is an executable finite diagnostic, not a Lean theorem. The admissible
class is explicitly restricted to the four listed worlds; it is not the initial
unconstrained class of the two-state experiment. No algorithm source is changed.
"""
from __future__ import annotations
import json
from pathlib import Path

from witness_cl.latent import LatentSpace, Machine, Program, compare
from witness_cl.latent_v5 import (
    DecisionDirectedAgent, decision_profile, guaranteed_regret_reductions,
)


def main() -> None:
    programs = tuple(Program.word((action,), 5) for action in range(5))
    rewards = ((5, 5, 5, 0, 10),)
    worlds = []
    for first_bit in (0, 1):
        for second_bit in (0, 1):
            parity = first_bit ^ second_bit
            outputs = (0, 1 + first_bit, 1 + second_bit, 4 - parity, 3 + parity)
            worlds.append(Machine(1, 5, 5, tuple((0, output) for output in outputs)))

    def initial_space() -> LatentSpace:
        space = LatentSpace(1, 5, 5)
        # Explicitly specified four-model class, held fixed before any evidence.
        space.partials = tuple(world.table for world in worlds)
        return space

    space = initial_space()
    agent = DecisionDirectedAgent(space, programs, rewards, budget=0)
    initial_gains = guaranteed_regret_reductions(decision_profile(space, programs, rewards))
    priced = []
    for program in programs:
        result = compare(space, program, programs[0], rewards[0])
        priced.append({'status': result.status, 'lower': result.lower, 'upper': result.upper})
    anchor_runs = []
    for episode in range(4):
        ticket = agent.choose(0)
        trace = programs[ticket.program].rollout(worlds[0])
        anchor_runs.append({'episode': episode, 'chosen_program': ticket.program,
                            'reward': sum(rewards[0][output] for _, output in trace),
                            'spent': agent.spent,
                            'information_gain': agent.last_information_gain})
        agent.observe(ticket, trace)
        assert space.partials == tuple(world.table for world in worlds)
    assert initial_gains == (0, 0, 0, 5, 5)
    assert all(row['chosen_program'] == 0 and row['spent'] == 0 for row in anchor_runs)

    alternative = initial_space()
    safe_probe_runs = []
    for program_id in (1, 2):
        certificate = compare(alternative, programs[program_id], programs[0], rewards[0])
        assert certificate.status == 'exact' and certificate.lower == certificate.upper == 0
        trace = programs[program_id].rollout(worlds[0])
        alternative.observe(trace)
        safe_probe_runs.append({
            'program': program_id,
            'certified_difference': [certificate.lower, certificate.upper],
            'trace': trace,
            'reward': sum(rewards[0][output] for _, output in trace),
            'remaining_models': len(list(alternative.completions())),
            'next_guaranteed_reductions': guaranteed_regret_reductions(
                decision_profile(alternative, programs, rewards)),
        })
    informed = DecisionDirectedAgent(alternative, programs, rewards, budget=0)
    informed_ticket = informed.choose(0)
    final_certificate = compare(alternative, programs[3], programs[0], rewards[0])
    assert informed_ticket.program == 3
    assert final_certificate.lower == final_certificate.upper == 5
    assert informed.spent == 0
    report = {
        'status': 'executed finite deterministic counterexample; not a Lean theorem',
        'class': 'four explicitly specified one-state worlds indexed by two latent bits',
        'restriction': 'not the initial unconstrained two-state benchmark class',
        'reward_by_output': rewards[0],
        'world_output_vectors': [[edge[1] for edge in world.table] for world in worlds],
        'programs': ['anchor', 'reveal first bit', 'reveal second bit',
                     'choose even parity', 'choose odd parity'],
        'initial_guaranteed_reductions': initial_gains,
        'initial_comparisons_to_anchor': priced,
        'frozen_rule_anchor_runs': anchor_runs,
        'alternative_zero_loss_probe_sequence': safe_probe_runs,
        'after_safe_probes': {'chosen_program': informed_ticket.program,
                              'certified_gain': final_certificate.lower,
                              'spent': informed.spent},
        'conclusion': 'Positive one-probe guaranteed regret reduction is not necessary for a useful zero-loss probe sequence; abstention can stall forever.',
        'safety_scope': 'No ledger or admission violation; this refutes exploration completeness only.',
        'algorithm_changed': False,
    }
    output = Path(__file__).with_suffix('.json')
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
