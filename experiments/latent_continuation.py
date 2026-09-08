"""Executed CPU mechanism study, not CL-Bench or an LLM experiment.

Each arm receives only public reward objectives and its own action/output traces.
The evaluator alone constructs or inspects the hidden transducer. Goal A-B-A
recurs; the transition model is stationary. This is NOT hidden-regime recurrence.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import json
import platform
import random
import statistics
import time
from itertools import product
from pathlib import Path
import numpy as np
from witness_cl.latent import Machine, Program, LatentSpace, compare, value
from witness_cl.latent_agent import LatentAgent


def make_world(seed: int) -> Machine:
    # Include action/state aliasing. No table, hidden state or latent ID reaches agents.
    rng=random.Random(seed)
    return Machine(2,2,2,tuple((rng.randrange(2),rng.randrange(2)) for _ in range(4)))


def mean(xs): return statistics.mean(xs) if xs else 0.
def sd(xs): return statistics.stdev(xs) if len(xs)>1 else 0.


def run(seeds: int, episodes: int, out: Path, seed_offset: int = 0):
    out.mkdir(parents=True,exist_ok=True)
    H=4
    ps=tuple(Program.word(word,2) for word in product(range(2),repeat=H))
    goals=((0,2),(2,0))
    methods=('anchor','full_history_optimistic','last_output_model',
             'latent_neural_B0','latent_neural_B16','latent_neural_B64','latent_untrained_B64','latent_unguided_B64')
    rows=[];summaries=[]
    for seed in range(seed_offset,seed_offset+seeds):
        world=make_world(seed)
        optimal=[max(value(world,p,r) for p in ps) for r in goals]
        for method in methods:
            agent=None
            if method.startswith('latent_'):
                budget=int(method.rsplit('B',1)[1])
                agent=LatentAgent(LatentSpace(2,2,2),ps,goals,budget=budget,seed=seed,
                                 trainable='untrained' not in method,max_nodes=100000,informative_probes='unguided' not in method)
                space=agent.space
            else:space=LatentSpace(2,2,2)
            # Reactive ablation: estimate P(output | last output, action), no latent memory.
            reactive=np.ones((3,2,2),dtype=float)
            deficit=worst=0
            old_returns=[value(world,ps[0],r) for r in goals]
            violations=0
            started=time.perf_counter()
            prior_rows=len(rows)
            for episode in range(episodes):
                # Public utility changes A-B-A; transition law and initial state do not.
                goal=0 if episode<episodes//3 or episode>=2*episodes//3 else 1
                r=goals[goal]
                nodes=0
                if agent is not None:
                    before=agent.nodes
                    ticket=agent.choose(goal)
                    chosen=ticket.program
                    nodes=agent.nodes-before
                    for g in range(len(goals)):
                        current=value(world,ps[agent.incumbents[g]],goals[g])
                        violations+=int(current<old_returns[g])
                        old_returns[g]=current
                    program=ps[chosen]
                elif method=='anchor':
                    chosen=0;program=ps[0]
                elif method=='full_history_optimistic':
                    # Exact all-model optimistic planning, without a risk restriction.
                    models=list(space.completions())
                    scores=[]
                    for j,p in enumerate(ps):
                        vals=[value(m,p,r) for m in models]
                        scores.append((max(vals),mean(vals),-j))
                    chosen=max(range(len(ps)),key=lambda j:scores[j]);program=ps[chosen]
                else:
                    # Observation-reactive finite-horizon dynamic programming.
                    probs=reactive/reactive.sum(axis=-1,keepdims=True)
                    future=np.zeros(3)
                    policies=[]
                    for t in reversed(range(H)):
                        q=np.zeros((3,2))
                        for last in range(3):
                            for a in range(2):
                                q[last,a]=sum(probs[last,a,o]*(r[o]+future[o]) for o in range(2))
                        actions=q.argmax(axis=1)
                        policies.append(actions)
                        future=q.max(axis=1)
                    policies=list(reversed(policies))
                    levels=[]
                    for t in range(H):
                        levels.append(tuple(int(policies[t][2 if t==0 else i%2]) for i in range(2**t)))
                    program=Program(2,tuple(levels));chosen=-1
                trace=program.rollout(world)
                reward=sum(r[o] for _,o in trace)
                anchor=value(world,ps[0],r)
                deficit+=anchor-reward;worst=max(worst,deficit)
                rows.append({'seed':seed,'method':method,'episode':episode,'goal':goal,'reward':reward,
                    'anchor':anchor,'oracle_word':optimal[goal],'program':chosen,'deficit':deficit,
                    'spent':agent.spent if agent else 0,'checker_nodes':nodes,
                    'partials':len(space.partials)})
                if agent is not None:agent.observe(ticket,trace)
                else:
                    space.observe(trace)
                    last=2
                    for a,o in trace:reactive[last,a,o]+=1;last=o
            elapsed=time.perf_counter()-started
            own=rows[prior_rows:]
            last=min(8,episodes//3)
            # Held-out public reward objective: propose a new program using accumulated dynamics.
            transfer_r=(-1,3)
            models=list(space.completions())
            best=max(range(len(ps)),key=lambda j:mean([value(m,ps[j],transfer_r) for m in models]))
            # Diagnostic only, NOT appended as an observed label or included in online reward.
            summaries.append({'seed':seed,'method':method,'mean_return':mean([x['reward'] for x in own]),
                'early':mean([x['reward'] for x in own[:last]]),'late_A':mean([x['reward'] for x in own[-last:]]),
                'mean_gain_vs_anchor':mean([x['reward']-x['anchor'] for x in own]),
                'gap_to_word_oracle':mean([x['oracle_word']-x['reward'] for x in own]),
                'worst_prefix_deficit':worst,'incumbent_violations':violations,
                'spent':agent.spent if agent else 0,'seconds':elapsed,
                'fit_branches':space.fit_branches,'partials':len(space.partials),
                'raw_trace_bytes':sum(len(t)*2*8 for t in space.history),
                'partial_payload_bytes':len(space.partials)*space.states*space.actions*2*8,
                'proposer_bytes':agent.proposer.parameter_bytes if agent else 0,
                'neural_updates':agent.proposer.updates if agent else 0,
                'comparison_nodes':agent.nodes if agent else 0,'unknown':agent.unknown if agent else 0,
                'promotions':agent.promotions if agent else 0,
                'heldout_objective_diagnostic':value(world,ps[best],transfer_r)})
    with gzip.open(out/'latent_episodes.csv.gz','wt',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    aggregates=[]
    for method in methods:
        part=[s for s in summaries if s['method']==method]
        aggregates.append({'method':method,**{k:{'mean':mean([p[k] for p in part]),'sd':sd([p[k] for p in part])}
                           for k in part[0] if k not in ('method','seed')},
                           'max_worst_prefix_deficit':max(p['worst_prefix_deficit'] for p in part)})
    paired=[]
    baseline={s['seed']:s for s in summaries if s['method']=='full_history_optimistic'}
    for method in methods:
        if not method.startswith('latent_'):continue
        diffs=[s['mean_return']-baseline[s['seed']]['mean_return'] for s in summaries if s['method']==method]
        paired.append({'method':method,'mean_difference':mean(diffs),'sd_difference':sd(diffs),
                       'ci95_t':list(__import__('scipy.stats',fromlist=['t']).t.interval(.95,len(diffs)-1,
                                    loc=mean(diffs),scale=sd(diffs)/len(diffs)**.5)) if sd(diffs)>0 else [mean(diffs)]*2})
    result={'status':'executed CPU synthetic mechanism study; no LLM/native benchmark',
            'seed_definition':'independent uniformly generated 2-state binary-action binary-output tables',
            'limitations':['small realizable deterministic class','known upper state bound and true resets',
                'open-loop 4-step library in experiment; checker also supports observation trees',
                'public reward recurrence, not hidden transition-regime recurrence',
                'no total wall-time matched benchmark','raw_trace_bytes excludes Python object overhead'],
            'seeds':seeds,'seed_offset':seed_offset,'episodes':episodes,'episode_rows':len(rows),'horizon':H,
            'aggregates':aggregates,'paired_vs_full_history':paired,'per_seed':summaries,
            'environment':{'python':platform.python_version(),'numpy':np.__version__,'platform':platform.platform()}}
    (out/'latent_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    for a in aggregates:
        print(a['method'], 'return',round(a['mean_return']['mean'],4),'late',round(a['late_A']['mean'],4),
              'deficit',a['max_worst_prefix_deficit'],'sec',round(a['seconds']['mean'],4),flush=True)
    print('rows',len(rows),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seeds',type=int,default=20);p.add_argument('--episodes',type=int,default=48)
    p.add_argument('--out',type=Path,default=Path('artifacts/v4'));p.add_argument('--seed-offset',type=int,default=0)
    args=p.parse_args()
    if args.seeds<2 or args.episodes<12:raise ValueError('at least two seeds and twelve episodes required')
    run(args.seeds,args.episodes,args.out,args.seed_offset)
