"""Paired CPU v5 probe-selection experiment. No native agent benchmark or LLM.

The pilot and holdout use the same frozen algorithm. Raw per-episode rows retain
all exploration costs. Evaluator counterfactuals appear only in reporting.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import platform
import random
import statistics
import time
from itertools import product
from pathlib import Path
import numpy as np
from scipy.stats import t as student_t
from witness_cl.latent import Machine, Program, LatentSpace, value
from witness_cl.latent_agent import LatentAgent
from witness_cl.latent_v5 import DecisionDirectedAgent

METHODS = ('v4_B16', 'v5_decision_B16', 'v5_decision_untrained_B16', 'full_history_optimistic')


def mean(x):
    return statistics.mean(x) if x else 0.0


def comparison(summaries, candidate, baseline, field='mean_return'):
    left = {s['seed']: s[field] for s in summaries if s['method'] == candidate}
    right = {s['seed']: s[field] for s in summaries if s['method'] == baseline}
    diffs = [left[k] - right[k] for k in sorted(left)]
    center = mean(diffs)
    sd = statistics.stdev(diffs) if len(diffs) > 1 else 0.0
    half = float(student_t.ppf(.975, len(diffs)-1)) * sd / len(diffs)**.5 if sd else 0.0
    return {'candidate': candidate, 'baseline': baseline, 'metric': field,
            'mean_difference': center, 'ci95_paired_t': [center-half, center+half],
            'positive_seeds': sum(x > 0 for x in diffs), 'negative_seeds': sum(x < 0 for x in diffs),
            'tied_seeds': sum(x == 0 for x in diffs)}


def run(offset: int, seeds: int, episodes: int, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    ps = tuple(Program.word(word, 2) for word in product(range(2), repeat=4))
    goals = ((0, 2), (2, 0))
    rows = []; summaries = []; tables = []
    run_started = time.perf_counter()
    for seed in range(offset, offset + seeds):
        rng = random.Random(seed)
        world = Machine(2, 2, 2, tuple((rng.randrange(2), rng.randrange(2)) for _ in range(4)))
        tables.append({'seed': seed, 'table': world.table})
        for method in METHODS:
            if method.startswith('v5_'):
                agent = DecisionDirectedAgent(LatentSpace(2, 2, 2), ps, goals, budget=16,
                    seed=seed, trainable='untrained' not in method, max_models=4096)
                space = agent.space
            elif method == 'v4_B16':
                agent = LatentAgent(LatentSpace(2, 2, 2), ps, goals, budget=16, seed=seed)
                space = agent.space
            else:
                agent = None; space = LatentSpace(2, 2, 2)
            start = len(rows); deficit = worst = violations = model_rollouts = 0
            previous = [value(world, ps[0], r) for r in goals]
            started = time.perf_counter()
            for episode in range(episodes):
                goal = 0 if episode < episodes//3 or episode >= 2*episodes//3 else 1
                rewards = goals[goal]
                before_nodes = agent.nodes if agent else 0
                if agent:
                    ticket = agent.choose(goal); chosen = ticket.program
                else:
                    models = list(space.completions())
                    scores = []
                    for j, p in enumerate(ps):
                        vals = [value(m, p, rewards) for m in models]
                        scores.append((max(vals), mean(vals), -j))
                        model_rollouts += len(models)
                    chosen = max(range(len(ps)), key=lambda j: scores[j])
                # This is the only environment trace given to the learner.
                trace = ps[chosen].rollout(world)
                reward = sum(rewards[o] for _, o in trace)
                anchor = value(world, ps[0], rewards)
                deficit += anchor - reward; worst = max(worst, deficit)
                if agent:
                    for g, r in enumerate(goals):
                        current = value(world, ps[agent.incumbents[g]], r)
                        violations += current < previous[g]; previous[g] = current
                rows.append({'seed': seed, 'method': method, 'episode': episode, 'goal': goal,
                    'program': chosen, 'reward': reward, 'anchor': anchor, 'prefix_deficit': deficit,
                    'spent': agent.spent if agent else 0,
                    'information_gain': getattr(agent, 'last_information_gain', 0),
                    'checker_nodes': agent.nodes-before_nodes if agent else 0,
                    'trace': json.dumps(trace, separators=(',', ':'))})
                if agent:
                    agent.observe(ticket, trace)
                else:
                    space.observe(trace)
            elapsed = time.perf_counter() - started
            own = rows[start:]
            summaries.append({'seed': seed, 'method': method,
                'mean_return': mean([r['reward'] for r in own]),
                'late_A': mean([r['reward'] for r in own[-8:]]),
                'worst_prefix_deficit': worst, 'incumbent_violations': violations,
                'spent': agent.spent if agent else 0, 'seconds': elapsed,
                'checker_nodes': agent.nodes if agent else 0,
                'model_rollouts': getattr(agent, 'model_rollouts', model_rollouts),
                'labelled_models_enumerated': getattr(agent, 'labelled_models_enumerated', 0),
                'profile_builds': getattr(agent, 'profile_builds', 0),
                'profile_cache_hits': getattr(agent, 'profile_cache_hits', 0),
                'max_behavioral_profiles': getattr(agent, 'max_behavioral_profiles', 0),
                'unknown': agent.unknown if agent else 0,
                'neural_updates': agent.proposer.updates if agent else 0,
                'fit_branches': space.fit_branches, 'final_partials': len(space.partials)})
        if (seed-offset+1) % 10 == 0:
            print(f'completed {seed-offset+1}/{seeds} seeds; {time.perf_counter()-run_started:.1f}s', flush=True)
    aggregates = []
    for method in METHODS:
        part = [s for s in summaries if s['method'] == method]
        aggregates.append({'method': method, **{k: mean([s[k] for s in part]) for k in part[0]
                            if k not in ('method', 'seed')},
                           'max_worst_prefix_deficit': max(s['worst_prefix_deficit'] for s in part),
                           'total_incumbent_violations': sum(s['incumbent_violations'] for s in part)})
    paired = [comparison(summaries, candidate, baseline, field)
              for candidate, baseline in (('v5_decision_B16', 'v4_B16'),
                  ('v5_decision_B16', 'full_history_optimistic'),
                  ('v5_decision_B16', 'v5_decision_untrained_B16'))
              for field in ('mean_return', 'late_A')]
    with gzip.open(out/'episodes.csv.gz', 'wt', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    result = {'status': 'executed exact finite CPU mechanism study; no LLM or native benchmark',
        'seed_offset': offset, 'seeds': seeds, 'episodes': episodes, 'horizon': 4,
        'episode_rows': len(rows), 'methods': METHODS,
        'selection_rule': 'max guaranteed sum-goal minimax regret reduction/(1+debit); lower debit; larger current upper gain; proposer order; abstain at zero',
        'uncertainty': 'paired seed Student t intervals; descriptive, not multiplicity adjusted',
        'limitations': ['tiny same-distribution realizable stationary finite class',
            'uniform generated tables sampled with replacement; fresh seeds are not disjoint worlds',
            'same episode/action budget, unequal total compute',
            'v5 exact enumeration is exponential; no scalable inference claim',
            'sum-goal regret reduction is not a reward improvement guarantee',
            'baseline uses original uniform labelled-model mean tie-break'],
        'aggregates': aggregates, 'paired': paired, 'per_seed': summaries, 'worlds_evaluator_only': tables,
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'platform': platform.platform()},
        'source_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path('src/witness_cl/latent_v5.py'), Path('experiments/latent_v5.py'))}}
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    for a in aggregates:
        print(a['method'], 'return', round(a['mean_return'], 6), 'late', round(a['late_A'], 6),
              'max deficit', a['max_worst_prefix_deficit'], 'seconds', round(a['seconds'], 4), flush=True)
    print(json.dumps(paired, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed-offset', type=int, required=True)
    parser.add_argument('--seeds', type=int, default=20)
    parser.add_argument('--episodes', type=int, default=48)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.seeds < 2 or args.episodes < 24 or args.episodes % 3:
        raise ValueError('at least two seeds and 24 episodes divisible by three required')
    run(args.seed_offset, args.seeds, args.episodes, args.out)
