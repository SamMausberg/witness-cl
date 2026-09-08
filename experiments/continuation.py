"""Deterministic stateful mechanism study. Not a language-model benchmark.

The algorithm sees its own executed transitions only. Enumerating supplied
models for planning is charged separately and is not treated as environment
feedback. Baselines share the exact same model family and online evidence API.
"""
from __future__ import annotations
import argparse,csv,gzip,json,random,time
from dataclasses import asdict
from pathlib import Path
import numpy as np
from witness_cl.continuation import Model,Policy,ModelBank,ContractAgent,value,optimal,rollout,improve


def family(seed:int,domain:str)->tuple[Model,...]:
    rng=random.Random(seed)
    H,S,A=5,4,3
    features=[[rng.randrange(1,16) for _ in range(S)] for _ in range(H)]
    models=[]
    for mask in range(16):
        ns=[];rs=[]
        for t in range(H):
            nt=[];rt=[]
            for s in range(S):
                bit=(mask&features[t][s]).bit_count()%2
                if domain=='delayed_damage':
                    if s==2:
                        nt.append((2,2,0));rt.append((0,1,0))
                    else:
                        nt.append((s,0 if bit else 2,1 if bit else 0))
                        rt.append((2+int(s==1),3+int(s==1),0))
                elif domain=='compositional_navigation':
                    # Three operations; relation bit determines which traversal
                    # reaches a rewarding state on the NEXT step.
                    nt.append(((s+1)%4,(s+1+bit)%4,(s+2-bit)%4))
                    rt.append((1+int(s==3),int(s==3)*4,1+int(s==3)*3))
                else:
                    raise ValueError(domain)
            ns.append(tuple(nt));rs.append(tuple(rt))
        models.append(Model(tuple(ns),tuple(rs),f'latent-{mask}'))
    # Accidental semantic duplicates are rejected by ModelBank; deduplicate here.
    return tuple({m.key:m for m in models}.values())


def control_policy(bank:ModelBank,baseline:Policy,state:int,method:str,rng:random.Random)->Policy:
    H,S,A=bank.models[0].shape
    if method=='frozen_anchor': return baseline
    if method=='raw_evidence_optimistic':
        # Strong model-based full-history control, NOT an LLM ICL result.
        candidates=[optimal(m) for m in bank.live]
        return max(candidates,key=lambda p:max(value(m,p)[0][state] for m in bank.live))
    if method=='greedy_immediate':
        return Policy(tuple(tuple(max(range(A),key=lambda a:sum(m.reward[t][s][a] for m in bank.live)) for s in range(S)) for t in range(H)))
    if method=='uniform_explore_then_plan':
        if len(bank.live)>1:
            return Policy(tuple(tuple(rng.randrange(A) for _ in range(S)) for _ in range(H)))
        return optimal(bank.live[0])
    raise ValueError(method)


def run(out:Path,seeds:int=20,episodes:int=64):
    out.mkdir(parents=True,exist_ok=True)
    rows=[];results=[]
    methods=('frozen_anchor','greedy_immediate','raw_evidence_optimistic','uniform_explore_then_plan','contract_budget0','contract_budget4','contract_budget16')
    for domain in ('delayed_damage','compositional_navigation'):
        for seed in range(seeds):
            models=family(seed,domain)
            truth=models[(seed*7+3)%len(models)]
            H,S,_=truth.shape
            baseline=Policy(((0,)*S,)*H)
            for method in methods:
                rng=random.Random(seed+101)
                agent=ContractAgent(models,baseline,int(method.split('budget')[-1])) if method.startswith('contract_') else None
                bank=agent.bank if agent else ModelBank(models)
                reward=[];regret=0;max_regret=0;unsafe=0
                start=time.perf_counter()
                for t in range(episodes):
                    state=(seed+t)%S
                    before=len(bank.live)
                    if agent:
                        ticket=agent.choose(t,state);policy=ticket.policy
                    else:
                        policy=control_policy(bank,baseline,state,method,rng)
                    events=rollout(truth,policy,state,t)
                    r=sum(e.reward for e in events)
                    br=value(truth,baseline)[0][state]
                    opt=value(truth,optimal(truth))[0][state]
                    regret+=br-r;max_regret=max(max_regret,regret)
                    unsafe+=int(r<br)
                    if agent: agent.observe(ticket,events)
                    else: bank.observe(events)
                    reward.append(r)
                    rows.append(dict(domain=domain,seed=seed,method=method,episode=t,state=state,reward=r,anchor_reward=br,oracle_reward=opt,live_before=before,live_after=len(bank.live),regret=regret,debit=ticket.debit if agent else '',spent=agent.spent if agent else '',planning_rollouts=agent.planning_model_rollouts if agent else '',transitions=json.dumps([asdict(e) for e in events],separators=(',',':'))))
                results.append(dict(domain=domain,seed=seed,method=method,mean=float(np.mean(reward)),early=float(np.mean(reward[:8])),late=float(np.mean(reward[-16:])),max_prefix_regret=max_regret,adverse_episodes=unsafe,spent=agent.spent if agent else None,live=len(bank.live),cpu_seconds=time.perf_counter()-start,planning_rollouts=agent.planning_model_rollouts if agent else None,evidence_checks_upper=bank.evaluations))
    summary=[]
    for domain in ('delayed_damage','compositional_navigation'):
        for method in methods:
            group=[r for r in results if r['domain']==domain and r['method']==method]
            agg={'domain':domain,'method':method,'seeds':seeds}
            for metric in ('mean','early','late','max_prefix_regret','adverse_episodes','cpu_seconds'):
                arr=np.array([r[metric] for r in group],float)
                agg[metric]=dict(mean=float(arr.mean()),std=float(arr.std(ddof=1)) if seeds>1 else 0)
            agg['worst_prefix_regret']=max(r['max_prefix_regret'] for r in group)
            summary.append(agg)
    with gzip.open(out/'episodes.csv.gz','wt',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    data=dict(status='executed synthetic deterministic finite-family study; no LLM',seeds=seeds,episodes=episodes,records=len(rows),summary=summary,per_seed=results)
    (out/'continuation.json').write_text(json.dumps(data,indent=2)+'\n')
    print('records',len(rows))
    for x in summary:
        print(x['domain'],x['method'],'early',round(x['early']['mean'],3),'late',round(x['late']['mean'],3),'prefix_worst',x['worst_prefix_regret'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('artifacts/v3'));p.add_argument('--seeds',type=int,default=20);p.add_argument('--episodes',type=int,default=64)
    a=p.parse_args();run(a.out,a.seeds,a.episodes)
