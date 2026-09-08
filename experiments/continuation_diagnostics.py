from fractions import Fraction as Q
import argparse,json,random,time
from pathlib import Path
import numpy as np
from witness_cl.likelihood import LikelihoodBank
from witness_cl.coupling import coupled,independent
from witness_cl.continuation import Model,Policy,value
from witness_cl.vector_contract import packed_advantages

def run(out:Path,n=1000):
    false=hard=0;empty=0
    for seed in range(n):
        rng=random.Random(seed);b=LikelihoodBank([Q(1,2),Q(1,2)],Q(1,20));excluded=False;err=False
        for t in range(64):
            outcome=rng.random()<.9
            p=Q(9,10) if outcome else Q(1,10)
            b.observe_probabilities([p,1-p])
            excluded|=0 not in b.live
            err|=not outcome
            empty+=int(not b.live)
        false+=excluded;hard+=err
    calls=[];parity=True
    for seed in range(200):
        rng=random.Random(seed);H=32;d=rng.randrange(20,30)
        tape=tuple(rng.randrange(5) for _ in range(H))
        env=lambda s,a,u: ((s+int(a)+int(u))%10007,int(a)+int(u))
        b=lambda s,m,t: (0,m+1)
        c=lambda s,m,t: (int(m>=d),m+1)
        result=coupled(env,b,c,0,0,0,tape)
        parity &= result.baseline==independent(env,b,0,0,tape) and result.candidate==independent(env,c,0,0,tape)
        calls.append(result.environment_calls)
    timings=[]
    for M in (4,16,64):
        rng=np.random.default_rng(M);H,S,A=6,32,4
        ms=tuple(Model(rng.integers(0,S,(H,S,A)).tolist(),rng.integers(-10,20,(H,S,A)).tolist()) for _ in range(M))
        b=Policy(((0,)*S,)*H)
        def scalar():
            vals=[value(m,b) for m in ms]
            return [[[min(m.reward[t][s][a]+v[t+1][m.next_state[t][s][a]]-v[t][s] for m,v in zip(ms,vals)) for a in range(A)] for s in range(S)] for t in range(H)]
        assert packed_advantages(ms,b)[1].tolist()==scalar()
        def clock(f):
            vals=[]
            for _ in range(7):
                start=time.perf_counter();f();vals.append(time.perf_counter()-start)
            return float(np.median(vals))
        timings.append(dict(models=M,horizon=H,states=S,actions=A,scalar_seconds=clock(scalar),packed_seconds=clock(lambda:packed_advantages(ms,b))))
    data=dict(noise=dict(trials=n,steps=64,noise=.1,delta=.05,ever_true_excluded=false,rate=false/n,hard_elimination_loses_truth=hard,hard_rate=hard/n,empty_live_checks=empty),coupling=dict(trials=200,horizon=32,parity=parity,mean_environment_calls=float(np.mean(calls)),independent_calls=64,controller_calls=64),cpu_vectorization=timings)
    (out/'diagnostics.json').write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('artifacts/v3'));p.add_argument('--trials',type=int,default=1000);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);run(a.out,a.trials)
