"""Integrated read-only learning/auditing; one observed action outcome per episode."""
from __future__ import annotations
import argparse,csv,gzip,json,random,statistics
from pathlib import Path
from witness_cl.system import ContinualSystem
from witness_cl.adaptive import Rule,RecurringAgent,Observation
from witness_cl.relational import Column,Snapshot,schema_grammar


def run(out:Path,seeds=20,episodes=512):
    results=[]
    columns=(Column('gross','int'),Column('fee','int'),Column('done','bool'),Column('refund','bool'))
    tiers=schema_grammar(columns)
    with gzip.open(out/'integrated_episodes.csv.gz','wt',newline='') as handle:
        w=csv.writer(handle);w.writerow(['mode','seed','method','episode','action','reward','audit_index','treatment'])
        for mode in ['stationary','recurring']:
            for seed in range(seeds):
                rng=random.Random(seed+3119)
                tasks=[]
                for t in range(episodes):
                    rows=tuple((rng.randrange(1,200),rng.randrange(30),rng.randrange(2),rng.choice([None,0,1]))
                               for _ in range(rng.randrange(8,25)))
                    regime=(t//128)%3 if mode=='recurring' else 1
                    y=(sum(r[0] for r in rows if r[2]==1) if regime==0 else
                       (sum(r[0]-r[1] for r in rows if r[2]==1 and (r[3] or 0)==0) if regime==1 else sum(r[1] for r in rows)))
                    tasks.append((Snapshot(columns,rows),y))
                for method in ['audited_live','ungated_proposer']:
                    agent=ContinualSystem(tiers,Rule('constant-zero',lambda x:0),seed=seed) if method=='audited_live' else RecurringAgent(tiers)
                    scores=[]
                    for t,(snap,y) in enumerate(tasks):
                        if method=='audited_live':
                            ticket=agent.decide(t,snap);a=ticket.action;r=int(a==y)
                            agent.observe(ticket,bool(r));index=ticket.audit_index;treat=int(ticket.treatment)
                        else:
                            a=agent.decide(snap).action;r=int(a==y)
                            agent.observe(Observation(t,snap,a,bool(r)));index=None;treat=None
                        scores.append(r);w.writerow([mode,seed,method,t,a,r,index,treat])
                    results.append(dict(mode=mode,seed=seed,method=method,reward=statistics.mean(scores),
                                        late_reward=statistics.mean(scores[episodes//2:]),
                                        promotions=len(agent.promotions) if method=='audited_live' else 0,
                                        audit_trials=agent.audit_episodes if method=='audited_live' else 0,
                                        proposals=agent.next_index-1 if method=='audited_live' else 0))
            print(mode,'finished',flush=True)
    summary=[]
    for mode in ['stationary','recurring']:
        for method in ['audited_live','ungated_proposer']:
            rows=[r for r in results if r['mode']==mode and r['method']==method]
            summary.append(dict(mode=mode,method=method,seeds=seeds,
                **{key:statistics.mean(r[key] for r in rows) for key in ['reward','late_reward','promotions','audit_trials','proposals']}))
    (out/'integrated.json').write_text(json.dumps({'summary':summary,'per_seed':results},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('artifacts/v2'))
    p.add_argument('--seeds',type=int,default=20);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);run(a.out,a.seeds)
