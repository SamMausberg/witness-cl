"""CPU mechanism experiments for v0.2. No LLM/public-benchmark results."""
from __future__ import annotations
import argparse,csv,gzip,json,math,random,statistics,time
from pathlib import Path
import numpy as np
from witness_cl.adaptive import Rule,Observation,RecurringAgent,GrowingEvidence
from witness_cl.programs import affine_class
from witness_cl.core import WitnessAgent
from witness_cl.types import Scope,Feedback
from witness_cl.relational import Column,Snapshot,schema_grammar
from witness_cl.protected import ProtectedResidual
from witness_cl.tracking import FixedShareRouter

def ci(values):
    values=np.asarray(values,dtype=float)
    rng=np.random.default_rng(1701)
    boots=np.mean(rng.choice(values,size=(2000,len(values))),axis=1)
    return [float(x) for x in np.quantile(boots,[.025,.975])]

def arithmetic_tiers():
    initial=tuple(Rule(p.key,p) for p in affine_class(7))
    expansion=tuple(Rule(f'q:{a}:{b}:{c}',lambda x,a=a,b=b,c=c:(a*x*x+b*x+c)%7)
                    for a in range(1,7) for b in range(7) for c in range(7))
    return initial,expansion

def summarize(rows,keys):
    out=[]
    groups={}
    for row in rows:
        groups.setdefault(tuple(row[k] for k in keys),[]).append(row)
    for key,runs in groups.items():
        summary=dict(zip(keys,key));summary['seeds']=len(runs)
        for name in runs[0]:
            if name not in keys and name!='seed' and isinstance(runs[0][name],(float,int)):
                summary[name]=statistics.mean(r[name] for r in runs)
        summary['reward_ci95']=ci([r['reward'] for r in runs])
        summary['per_seed']=runs
        out.append(summary)
    return out

def arithmetic(out,seeds=20,episodes=512):
    modes=['stationary','novel_inputs','hidden_shift','misspecified','recurring','rapid_switch','noisy_feedback']
    tiers=arithmetic_tiers();runs=[]
    with gzip.open(out/'arithmetic_episodes.csv.gz','wt',newline='') as f:
        writer=csv.writer(f);writer.writerow(['mode','seed','method','episode','x','action','reward','observed_success','empirical_unanimity','certified'])
        for mode in modes:
            for seed in range(seeds):
                rng=random.Random(seed)
                params=[(rng.randrange(1,7),rng.randrange(7)) for _ in range(3)]
                data=[]
                for t in range(episodes):
                    x=rng.randrange(2 if t<episodes//2 else 2,7) if mode=='novel_inputs' and t>=episodes//2 else rng.randrange(2 if mode=='novel_inputs' else 7)
                    j=(t//64)%3 if mode=='recurring' else ((t//4)%3 if mode=='rapid_switch' else int(t>=episodes//2 and mode=='hidden_shift'))
                    a,b=params[j];y=(a*x*x+b)%7 if mode=='misspecified' else (a*x+b)%7
                    data.append((x,y,rng.random()<.05 if mode=='noisy_feedback' else False))
                for method in ['v1_original','v2_reset_only','v2_recurring']:
                    agent=WitnessAgent(affine_class(7)) if method=='v1_original' else RecurringAgent(tiers,reuse=method=='v2_recurring')
                    scope=Scope('observable-system','unchanged')
                    scores=[];wrongcert=0;falseconsensus=0;protected_checks=0
                    for t,(x,y,flip) in enumerate(data):
                        d=agent.decide(scope,x) if method=='v1_original' else agent.decide(x)
                        reward=int(d.action==y);observed=bool(reward)^flip
                        scores.append(reward)
                        consensus=d.certified if method=='v1_original' else d.empirical_unanimity
                        wrongcert+=int(d.certified and not reward)
                        falseconsensus+=int(consensus and not reward)
                        before={} if method=='v1_original' else agent.archived_outputs(range(7))
                        if method=='v1_original':
                            agent.observe(Feedback(t,scope,x,d.action,observed))
                        else:
                            agent.observe(Observation(t,x,d.action,observed))
                            after=agent.archived_outputs(range(7))
                            assert all(after[k]==v for k,v in before.items())
                            protected_checks+=len(before)*7
                        writer.writerow([mode,seed,method,t,x,d.action,reward,int(observed),int(consensus),int(d.certified)])
                    runs.append(dict(mode=mode,method=method,seed=seed,reward=statistics.mean(scores),
                        late_reward=statistics.mean(scores[episodes//2:]),wrong_certificates=wrongcert,
                        wrong_empirical_consensus=falseconsensus,archive_invariance_checks=protected_checks,
                        resets=getattr(agent,'resets',0),expansions=getattr(agent,'expansions',0),
                        archived_rules=len(getattr(agent,'archive',{})),
                        hypothesis_evaluations=sum(v.evaluations for v in agent.spaces.values()) if method=='v1_original' else agent.total_evaluations))
            print('arithmetic',mode,'finished',flush=True)
    result=summarize(runs,['mode','method'])
    (out/'arithmetic.json').write_text(json.dumps(result,indent=2))
    return result

class Static:
    def __init__(self,rules):
        self.space=GrowingEvidence(rules)
    def decide(self,x):
        votes={}
        for r in self.space.live:
            y=r(x);votes[y]=votes.get(y,0)+1
        return min(votes,key=lambda a:(-votes[a],a)) if votes else 0
    def observe(self,e):self.space.observe(e)

def relational(out,seeds=20,episodes=384):
    runs=[]
    cols=(Column('gross','int'),Column('fee','int'),Column('done','bool'),Column('refund','bool'))
    tiers=schema_grammar(cols)
    with gzip.open(out/'relational_episodes.csv.gz','wt',newline='') as f:
        wr=csv.writer(f);wr.writerow(['mode','seed','method','episode','action','reward','rows'])
        for mode in ['stationary_net','recurring_recipes','out_of_grammar']:
            for seed in range(seeds):
                rng=random.Random(seed+991)
                tasks=[]
                for t in range(episodes):
                    rows=tuple((rng.randrange(1,200),rng.randrange(0,30),rng.choice([0,1]),rng.choice([None,0,1]))
                               for _ in range(rng.randrange(8,25)))
                    snap=Snapshot(cols,rows)
                    regime=(t//64)%3 if mode=='recurring_recipes' else 1
                    # Independent evaluator, not a hidden plan passed into grammar generation.
                    if regime==0:y=sum(r[0] for r in rows if r[2]==1)
                    elif regime==1:y=sum(r[0]-r[1] for r in rows if r[2]==1 and (r[3] or 0)==0)
                    else:y=sum(r[1] for r in rows)
                    if mode=='out_of_grammar':y=sum(r[0]*r[1] for r in rows if r[2]==1)
                    tasks.append((snap,y))
                for method in ['static_initial_grammar','full_grammar_replay','adaptive_reset_only','adaptive_recurring']:
                    if method=='static_initial_grammar':agent=Static(tiers[0])
                    elif method=='full_grammar_replay':agent=Static(tuple(r for tier in tiers for r in tier))
                    else:agent=RecurringAgent(tiers,reuse=method=='adaptive_recurring')
                    scores=[];evals=0
                    for t,(snap,y) in enumerate(tasks):
                        a=agent.decide(snap) if isinstance(agent,Static) else agent.decide(snap).action
                        reward=int(a==y);scores.append(reward)
                        event=Observation(t,snap,a,bool(reward))
                        agent.observe(event)
                        if method=='full_grammar_replay':
                            # Mathematically equivalent full-history rebuild, no forgetting trick.
                            history=tuple(agent.space.history)
                            agent=Static(tuple(r for tier in tiers for r in tier))
                            for e in history:agent.observe(e)
                            evals+=agent.space.evaluations
                        wr.writerow([mode,seed,method,t,a,reward,len(snap.rows)])
                    runs.append(dict(mode=mode,method=method,seed=seed,reward=statistics.mean(scores),
                        late_reward=statistics.mean(scores[episodes//2:]),resets=getattr(agent,'resets',0),
                        expansions=getattr(agent,'expansions',0),archived_rules=len(getattr(agent,'archive',{})),
                        evaluations=evals if method=='full_grammar_replay' else getattr(agent,'total_evaluations',agent.space.evaluations)))
            print('relational',mode,'finished',flush=True)
    result=summarize(runs,['mode','method'])
    (out/'relational.json').write_text(json.dumps(result,indent=2))
    return result

def audit_power(out,replications=4000):
    rng=np.random.default_rng(20260908);stakes=np.array([.1,.25,.5,.75,1.])
    rows=[]
    # Same +.05 global benefit; the sparse residual has +.5 conditional effect.
    for case in ['diffuse_gain','sparse_local_gain','sparse_null','sparse_harm']:
        for horizon in [128,512,2048]:
            capital=np.ones((replications,len(stakes)));passed=np.zeros(replications,bool)
            forks=np.zeros(replications,int);stop=np.full(replications,horizon)
            for t in range(horizon):
                gate=np.ones(replications,bool) if case=='diffuse_gain' else rng.random(replications)<.1
                win=.525 if case=='diffuse_gain' else (.75 if case=='sparse_local_gain' else (.5 if case=='sparse_null' else .4))
                d=np.where(gate,np.where(rng.random(replications)<win,1.,-1.),0.)
                capital*=1+d[:,None]*stakes
                now=(capital.mean(axis=1)>=40)&~passed
                stop[now]=t+1
                forks+=gate&~passed
                passed|=now
            # Dense and screened tests have exactly equal paths; dense forks each case.
            rows.append(dict(case=case,horizon=horizon,replications=replications,
                admission_rate=float(passed.mean()),mean_deployment_opportunities=float(stop.mean()),
                dense_mean_extra_rollouts=float(stop.mean()),screened_mean_extra_rollouts=float(forks.mean()),
                dense_mean_total_rollouts=float(2*stop.mean()),screened_mean_total_rollouts=float(stop.mean()+forks.mean())))
    # A live randomized experiment has one observed reward, not hidden paired data.
    for gain in [.0,.05,.3]:
        for horizon in [128,512,2048]:
            cap=np.ones((replications,len(stakes)));passed=np.zeros(replications,bool)
            for _ in range(horizon):
                assigned=rng.random(replications)<.5
                r=rng.random(replications)<np.where(assigned,.5+gain,.5)
                z=np.where(assigned,1.,-1.)*(2*r.astype(float)-1.)
                cap*=1+z[:,None]*stakes
                passed|=cap.mean(axis=1)>=40
            rows.append(dict(case='live_randomized',gain=gain,horizon=horizon,replications=replications,
                             admission_rate=float(passed.mean()),rollouts_per_opportunity=1))
    (out/'audit_power.json').write_text(json.dumps(rows,indent=2))
    return rows

def training(out,seeds=20):
    runs=[]
    for rank in [0,4,12,24]:
        for seed in range(seeds):
            rng=np.random.default_rng(seed);d=24
            Q,_=np.linalg.qr(rng.normal(size=(d,d)))
            anchors=Q[:,:rank].T
            base=rng.normal(size=d)
            desired=base+rng.normal(size=d)
            protected=ProtectedResidual(base,anchors)
            naive=base.copy()
            for t in range(2048):
                x=rng.normal(size=d)
                y=float(x@desired)  # actual labeled online feedback
                protected.update(x,y,.01)
                naive-=.01*(x@naive-y)*x
            test=rng.normal(size=(512,d));truth=test@desired
            projection_error=float(np.linalg.norm(anchors@(desired-base))**2) if rank else 0.
            runs.append(dict(rank=rank,seed=seed,base_mse=float(np.mean((test@base-truth)**2)),
                protected_mse=float(np.mean((protected.predict(test)-truth)**2)),
                naive_mse=float(np.mean((test@naive-truth)**2)),protected_max_drift=protected.protected_drift(),
                naive_max_drift=float(np.max(np.abs(anchors@(naive-base)))) if rank else 0.,
                irreducible_population_mse=projection_error))
    (out/'training.json').write_text(json.dumps(runs,indent=2))
    return runs

def tracking(out,seeds=20,horizon=4096):
    runs=[]
    for block in [32,128,512]:
        for seed in range(seeds):
            router=FixedShareRouter(4,4,eta=.15,share=1/block,exploration=.02,seed=seed)
            cumulative=0.
            for t in range(horizon):
                ticket=router.choose([0,1,2,3])
                loss=float(ticket.action!=((t//block)%4))
                router.observe(ticket,loss);cumulative+=loss
            runs.append(dict(block=block,seed=seed,reward=1-cumulative/horizon,regret=cumulative,
                             expected_bound=router.expected_regret_bound(horizon,(horizon-1)//block)))
    (out/'tracking.json').write_text(json.dumps(runs,indent=2))
    return runs

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('artifacts/v2'))
    p.add_argument('--part',choices=['arithmetic','relational','audit','training','tracking','all'],default='all')
    p.add_argument('--seeds',type=int,default=20);args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter()
    funcs={'arithmetic':lambda:arithmetic(args.out,args.seeds),'relational':lambda:relational(args.out,args.seeds),
           'audit':lambda:audit_power(args.out),'training':lambda:training(args.out,args.seeds),
           'tracking':lambda:tracking(args.out,args.seeds)}
    for key in funcs if args.part=='all' else [args.part]:funcs[key]()
    print('elapsed seconds',time.perf_counter()-start)
