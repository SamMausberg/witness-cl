"""Frozen finite CPU protocol with independent evaluator-only trace replay.

No LLM calls, model-weight updates, schedule input, or evaluator labels enter the
agent. Completed output directories are immutable; failed runs retain evidence.
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
import traceback
from itertools import product
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t
from witness_cl.latent import LatentSpace, Machine, Program
from witness_cl.latent_agent import LatentAgent
from witness_cl.probe_v6 import DepthTwoProbeAgent, InformativeZeroLossAgent, OptimisticProbeAgent

METHODS = ('depth_two_B16', 'informative_zero_loss_B16', 'optimistic_B16',
           'v4_frozen_ranker_B16', 'full_history_optimistic')
BOUNDED = dict(zip(METHODS[:3], (DepthTwoProbeAgent, InformativeZeroLossAgent, OptimisticProbeAgent)))
GOALS = ((0, 1, 2), (2, 1, 0))
EPISODES = 24


def mean(xs):
    return statistics.mean(xs) if xs else 0.0


def paired(summaries, candidate, baseline, metric='mean_return'):
    left = {r['seed']: r[metric] for r in summaries if r['method'] == candidate}
    right = {r['seed']: r[metric] for r in summaries if r['method'] == baseline}
    differences = [left[s] - right[s] for s in sorted(left)]
    center = mean(differences)
    sd = statistics.stdev(differences) if len(differences) > 1 else 0.0
    half = float(student_t.ppf(.975, len(differences)-1)) * sd / len(differences)**.5 if sd else 0.0
    return dict(candidate=candidate, baseline=baseline, metric=metric,
                mean_difference=center, ci95_paired_t=[center-half, center+half],
                positive=sum(d > 0 for d in differences), negative=sum(d < 0 for d in differences),
                tied=sum(d == 0 for d in differences))


def source_hashes():
    files = [*Path('src/witness_cl').glob('*.py'), Path('experiments/probe_v6.py'),
             Path('docs/v6/EVALUATION.md'), Path('docs/v6/RESEARCH_BOUNDARIES.md')]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def write_rows(out, rows):
    if rows:
        with gzip.open(out/'episodes.csv.gz', 'wt', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)


def run(offset, seeds, out, max_work=2_000_000, max_seconds=1.0, phase='development', freeze=None):
    out.mkdir(parents=True, exist_ok=False)
    manifest = dict(phase=phase, seed_offset=offset, seeds=seeds, episodes=EPISODES,
                    max_work=max_work, max_seconds=max_seconds, max_models=4096,
                    max_nodes=100000, trainable=False, source_sha256=source_hashes(),
                    methods=list(METHODS), unix_started=time.time(), protocol='docs/v6/EVALUATION.md')
    if freeze is not None:
        frozen = json.loads(freeze.read_text())
        if frozen['source_sha256'] != manifest['source_sha256']:
            raise RuntimeError('source drift after freeze')
        expected = frozen.get('holdout', {})
        actual = {k: manifest[k] for k in ('phase', 'seed_offset', 'seeds', 'episodes', 'max_work', 'max_seconds', 'max_models', 'max_nodes', 'trainable', 'methods')}
        if actual != expected:
            raise RuntimeError('run configuration differs from frozen protocol')
        manifest['freeze_sha256'] = hashlib.sha256(freeze.read_bytes()).hexdigest()
    elif phase == 'holdout':
        raise ValueError('holdout requires a pre-existing source freeze')
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    programs = tuple(Program.word(word, 3) for word in product(range(2), repeat=3))
    # Independent evaluator universe: never passed to the candidate agents.
    universe = tuple(Machine(2, 2, 3, table) for table in product(tuple(product(range(2), range(3))), repeat=4))
    universe_traces = tuple(tuple(p.rollout(m) for p in programs) for m in universe)
    universe_values = np.array([[[sum(r[o] for _, o in tr) for r in GOALS] for tr in ts]
                                for ts in universe_traces], dtype=np.int64)
    table_to_index = {m.table: i for i, m in enumerate(universe)}
    rows, summaries, worlds = [], [], []
    run_start = time.perf_counter()
    try:
        for seed in range(offset, offset+seeds):
            rng = random.Random(seed)
            world = Machine(2, 2, 3, tuple((rng.randrange(2), rng.randrange(3)) for _ in range(4)))
            true_index = table_to_index[world.table]
            worlds.append(dict(seed=seed, table=world.table))
            for method in METHODS:
                constructed = time.perf_counter()
                if method in BOUNDED:
                    agent = BOUNDED[method](LatentSpace(2, 2, 3), programs, GOALS, budget=16,
                        seed=seed, trainable=False, max_work=max_work, max_seconds=max_seconds, max_models=4096)
                    space = agent.space
                elif method == 'v4_frozen_ranker_B16':
                    agent = LatentAgent(LatentSpace(2, 2, 3), programs, GOALS, budget=16, seed=seed, trainable=False)
                    space = agent.space
                else:
                    agent, space = None, LatentSpace(2, 2, 3)
                construction_seconds = time.perf_counter() - constructed
                compatible = list(range(len(universe)))
                deficit = worst_deficit = cumulative_debit = 0
                start = len(rows)
                for episode in range(EPISODES):
                    goal = 0 if episode < 8 or episode >= 16 else 1
                    before = agent.incumbents.copy() if agent else [0, 0]
                    started = time.perf_counter()
                    if agent:
                        ticket = agent.choose(goal)
                        chosen = ticket.program
                    else:
                        models = tuple(space.completions())
                        candidate_values = [[sum(GOALS[goal][o] for _, o in p.rollout(m)) for m in models]
                                            for p in programs]
                        chosen = max(range(len(programs)), key=lambda j: (max(candidate_values[j]), mean(candidate_values[j]), -j))
                    planning_seconds = time.perf_counter()-started
                    plan = getattr(agent, 'last_plan', None)
                    audit_start = time.perf_counter()
                    # Recompute both protected monotonicity and the charged loss
                    # from the independently replayed compatible world indices.
                    if agent:
                        cumulative_debit += ticket.debit
                        if agent.spent != cumulative_debit:
                            raise AssertionError('risk ledger refunded or reused an announced debit')
                        for g in range(len(GOALS)):
                            delta = universe_values[compatible, agent.incumbents[g], g] - universe_values[compatible, before[g], g]
                            if int(delta.min()) < 0:
                                raise AssertionError('protected incumbent regressed over compatible class')
                        actual_lower = int((universe_values[compatible, chosen, goal] - universe_values[compatible, ticket.incumbent, goal]).min())
                        if ticket.debit < max(0, -actual_lower) or not 0 <= agent.spent <= agent.budget:
                            raise AssertionError('unchecked risk debit or overspent budget')
                        if plan and plan.status != 'exact' and (chosen != before[goal] or ticket.debit or agent.incumbents != before):
                            raise AssertionError('partial plan mutated protected state')
                    # Only this real simulated trace is supplied to observe.
                    trace = programs[chosen].rollout(world)
                    reward = sum(GOALS[goal][o] for _, o in trace)
                    anchor = int(universe_values[true_index, 0, goal])
                    deficit += anchor-reward
                    worst_deficit = max(worst_deficit, deficit)
                    if agent and deficit > agent.spent:
                        raise AssertionError('completed-prefix anchor guarantee violated')
                    audit_seconds = time.perf_counter()-audit_start
                    update_start = time.perf_counter()
                    if agent:
                        agent.observe(ticket, trace)
                    else:
                        space.observe(trace)
                    update_seconds = time.perf_counter()-update_start
                    audit_start = time.perf_counter()
                    compatible = [m for m in compatible if universe_traces[m][chosen] == trace]
                    if not space.complete or {m.table for m in space.completions()} != {universe[m].table for m in compatible}:
                        raise AssertionError('runtime model cover differs from independent full-history replay')
                    if true_index not in compatible or (agent and agent.proposer.updates != 0):
                        raise AssertionError('true-model loss or unexpected weight adaptation')
                    audit_seconds += time.perf_counter()-audit_start
                    rows.append(dict(seed=seed, method=method, episode=episode, goal=goal, program=chosen,
                        reward=reward, anchor=anchor, prefix_deficit=deficit, spent=agent.spent if agent else 0,
                        debit=ticket.debit if agent else 0, guarded=agent is not None,
                        incumbents_before=json.dumps(before), incumbents_after=json.dumps(agent.incumbents if agent else before),
                        plan_lower=plan.lower if plan else None, plan_upper=plan.upper if plan else None,
                        status=plan.status if plan else 'not_metered',
                        reason=plan.reason if plan else '', guaranteed_gain=plan.guaranteed_gain if plan else 0,
                        work=plan.work if plan else 0, completion_attempts=plan.completion_attempts if plan else 0,
                        labelled_models=plan.labelled_models if plan else 0,
                        planning_seconds=planning_seconds, update_seconds=update_seconds, audit_seconds=audit_seconds,
                        compatible_models=len(compatible), trace=json.dumps(trace, separators=(',', ':'))))
                own = rows[start:]
                summaries.append(dict(seed=seed, method=method,
                    mean_return=mean([r['reward'] for r in own]), late_A=mean([r['reward'] for r in own[-8:]]),
                    spent=agent.spent if agent else 0, worst_prefix_deficit=worst_deficit,
                    incumbent_violations=0, admission_violations=0, coverage_violations=0, neural_updates=0,
                    construction_seconds=construction_seconds,
                    planning_seconds=sum(r['planning_seconds'] for r in own), update_seconds=sum(r['update_seconds'] for r in own),
                    audit_seconds=sum(r['audit_seconds'] for r in own), work=sum(r['work'] for r in own),
                    completion_attempts=sum(r['completion_attempts'] for r in own), labelled_models=sum(r['labelled_models'] for r in own),
                    exact_decisions=sum(r['status']=='exact' for r in own), unknown_decisions=sum(r['status']=='unknown' for r in own),
                    final_compatible_models=len(compatible), final_partials=len(space.partials)))
            print(f'{phase}: {seed-offset+1}/{seeds} seeds, {time.perf_counter()-run_start:.1f}s', flush=True)
            (out/'checkpoint.json').write_text(json.dumps(dict(completed_seeds=seed-offset+1, per_seed=summaries), indent=2)+'\n')
        aggregates=[]
        for method in METHODS:
            selected=[r for r in summaries if r['method']==method]
            aggregates.append(dict(method=method, **{k:mean([r[k] for r in selected]) for k in selected[0] if k not in ('seed','method')},
                                   max_worst_prefix_deficit=max(r['worst_prefix_deficit'] for r in selected)))
        comparisons=[paired(summaries,c,b,metric) for c,b in
                     ((METHODS[0],METHODS[1]),(METHODS[0],METHODS[2]),(METHODS[0],METHODS[3]),(METHODS[0],METHODS[4]))
                     for metric in ('mean_return','late_A','planning_seconds')]
        result=dict(status='completed; all independent finite-contract audits passed', **manifest,
                    episode_rows=len(rows), aggregates=aggregates, paired=comparisons, per_seed=summaries,
                    worlds_evaluator_only=worlds, unique_tables=len({tuple(map(tuple,w['table'])) for w in worlds}),
                    elapsed_seconds=time.perf_counter()-run_start,
                    environment=dict(python=platform.python_version(), numpy=np.__version__, platform=platform.platform()),
                    limitations=['finite stationary realizable class with true resets and known reward goals',
                        'same-distribution seeds sampled with replacement; not disjoint-domain generalization',
                        'cooperative time cap can cause hardware-dependent UNKNOWN; line counts are not FLOPs',
                        'common ceilings are not equal realized compute; controls without line metering are diagnostic',
                        'all neural rankers frozen; no conclusion about online model-weight learning',
                        'paired t intervals are descriptive and secondary contrasts are not multiplicity-adjusted'])
        write_rows(out,rows)
        (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
        (out/'checkpoint.json').unlink()
        print(json.dumps(dict(aggregates=aggregates,primary=comparisons[0]),indent=2),flush=True)
    except BaseException:
        write_rows(out,rows)
        (out/'failure.json').write_text(json.dumps(dict(traceback=traceback.format_exc(), completed_episode_rows=len(rows),
                                                          per_seed=summaries),indent=2)+'\n')
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--seed-offset',type=int,required=True)
    parser.add_argument('--seeds',type=int,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--max-work',type=int,default=2_000_000)
    parser.add_argument('--max-seconds',type=float,default=1.0)
    parser.add_argument('--phase',choices=('development','holdout','exploratory'),default='development')
    parser.add_argument('--freeze',type=Path)
    args=parser.parse_args()
    if args.seeds<2 or args.max_work<1 or args.max_seconds<=0:
        parser.error('at least two seeds and positive resource caps required')
    run(args.seed_offset,args.seeds,args.out,args.max_work,args.max_seconds,args.phase,args.freeze)
