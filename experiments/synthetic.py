"""Reproducible CPU mechanism experiment, NOT a CL-Bench or LLM result.

Learners see public scope, integer input, their chosen action, and binary success.
No true coefficient or correct answer is supplied to a learner.
"""
from __future__ import annotations
import argparse
import csv
import json
import platform
import random
import statistics
import sys
import time
from pathlib import Path
from witness_cl.programs import affine_class
from witness_cl.core import WitnessAgent
from witness_cl.baselines import Stateless, WindowReplayInduction, ExactLookup, FullReplayInduction
from witness_cl.types import Scope, Feedback

MODES = ["interleaved", "novel_inputs", "public_shift", "hidden_shift", "misspecified"]

def stream(seed: int, episodes: int, mode: str, modulus=7, scopes=4):
    rng=random.Random(seed)
    params=[(rng.randrange(1,modulus),rng.randrange(modulus)) for _ in range(scopes)]
    for t in range(episodes):
        k=(t//12)%scopes
        late=t>=episodes//2
        if mode in ("novel_inputs","misspecified"):
            x=rng.randrange(2,modulus) if late else rng.randrange(2)
        else:
            x=rng.randrange(modulus)
        a,b=params[k]
        if mode in ("public_shift","hidden_shift") and late:
            a,b=(a+1)%modulus,(b+1)%modulus
        y=(a*x*x+b)%modulus if mode=="misspecified" else (a*x+b)%modulus
        version="v2" if mode=="public_shift" and late else "v1"
        yield t,Scope(f"public-system-{k}",version),x,y,"late" if late else "early"

def bootstrap_ci(values, seed=1701, samples=2000):
    rng=random.Random(seed)
    means=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(samples))
    return [means[int(.025*samples)],means[int(.975*samples)]]

def run(out: Path, seeds: int=20, episodes: int=384):
    out.mkdir(parents=True,exist_ok=True)
    programs=affine_class(7)
    factories={"stateless":Stateless,"window_replay_24":lambda:WindowReplayInduction(programs,24),
        "lookup_bounded_24":lambda:ExactLookup(7,24),"lookup_full":lambda:ExactLookup(7),
        "full_replay_induction":lambda:FullReplayInduction(programs),
        "witness":lambda:WitnessAgent(programs)}
    aggregates=[]
    started=time.perf_counter()
    with (out/"episodes.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=["mode","seed","method","episode","scope","version","x",
            "action","reward","certified","wrong_certificate","phase","live_hypotheses"])
        writer.writeheader()
        for mode in MODES:
            per_method={name:[] for name in factories}
            for seed in range(seeds):
                tasks=list(stream(seed,episodes,mode))
                for name,factory in factories.items():
                    agent=factory(); scores=[]; late=[]; certified=[]; wrong=0
                    method_start=time.perf_counter()
                    for t,scope,x,y,phase in tasks:
                        d=agent.decide(scope,x)
                        reward=int(d.action==y)
                        scores.append(reward)
                        if phase=="late": late.append(reward)
                        certified.append(int(d.certified)); wrong+=int(d.certified and not reward)
                        agent.observe(Feedback(t,scope,x,d.action,bool(reward)))
                        writer.writerow(dict(mode=mode,seed=seed,method=name,episode=t,scope=scope.name,
                            version=scope.version,x=x,action=d.action,reward=reward,certified=int(d.certified),
                            wrong_certificate=int(d.certified and not reward),phase=phase,
                            live_hypotheses=d.live_hypotheses))
                    evals=(sum(v.evaluations for v in agent.spaces.values()) if name=="witness"
                           else getattr(agent,"evaluations",0))
                    per_method[name].append(dict(reward=statistics.mean(scores),late_reward=statistics.mean(late),
                        certified_fraction=statistics.mean(certified),wrong_certificates=wrong,
                        hypothesis_evaluations=evals,
                        active_witnesses=(sum(len(v.witnesses) for v in agent.spaces.values()) if name=="witness" else 0),seconds=time.perf_counter()-method_start))
            for name,runs in per_method.items():
                row=dict(mode=mode,method=name,seeds=seeds,episodes_per_seed=episodes)
                for key in runs[0]: row[key]=statistics.mean(x[key] for x in runs)
                row["reward_ci95_seed_bootstrap"]=bootstrap_ci([x["reward"] for x in runs])
                row["late_ci95_seed_bootstrap"]=bootstrap_ci([x["late_reward"] for x in runs])
                row["per_seed"]=runs
                aggregates.append(row)
            print(mode,"finished",flush=True)
    result={"kind":"synthetic_mechanism_check_not_llm_benchmark", "python":sys.version,
        "platform":platform.platform(),"elapsed_seconds":time.perf_counter()-started,
        "modulus":7,"public_scopes":4,"seed_ids":list(range(seeds)),"rows":aggregates}
    (out/"summary.json").write_text(json.dumps(result,indent=2))
    lines=["# Executed synthetic mechanism check","", "These are symbolic CPU controls, not language-model or CL-Bench results.","",
        "| Scenario | Method | Reward | Late reward | Certified fraction | Wrong certificates / seed |", 
        "|---|---|---:|---:|---:|---:|"]
    for row in aggregates:
        lines.append(f"| {row['mode']} | {row['method']} | {100*row['reward']:.2f}% | {100*row['late_reward']:.2f}% | {100*row['certified_fraction']:.2f}% | {row['wrong_certificates']:.2f} |")
    (out/"RESULTS.md").write_text("\n".join(lines)+"\n")
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,default=Path("artifacts/synthetic"))
    p.add_argument("--seeds",type=int,default=20)
    p.add_argument("--episodes",type=int,default=384)
    args=p.parse_args()
    if args.seeds<2 or args.episodes<48: p.error("use at least two seeds and 48 episodes")
    run(args.out,args.seeds,args.episodes)
