"""Online binary-outcome neural diagnostic, NOT LLM fine-tuning."""
import argparse,json
from pathlib import Path
import numpy as np
from witness_cl.versioned_training import OnlineNetwork,ModuleArchive

def truth(x,k):
    return int((x[0]+.65*x[1]>0) if k==0 else ((x[0]-.8*x[1]<0) if k==1 else (x[0]*x[1]>0)))

def run(out:Path,seeds:int=20,episodes:int=1600):
    results=[]
    for seed in range(seeds):
        rng=np.random.default_rng(seed)
        xs=rng.normal(size=(3,episodes,2))
        test=rng.normal(size=(3,512,2))
        for method in ('shared_equal_width','shared_equal_parameter_budget','shared_online_replay','versioned'):
            hidden=72 if method in ('shared_equal_parameter_budget','shared_online_replay') else 24
            net=OnlineNetwork(5,hidden,seed)
            archive=ModuleArchive()
            acquired={};forget=[];online=[];drifts=[];bytes_used=0
            reservoir=[];seen=0;update_count=0;replay_rng=np.random.default_rng(seed+999)
            for scope in range(3):
                if method=='versioned': net=OnlineNetwork(5,24,seed+scope)
                tag=np.eye(3)[scope]
                rewards=[]
                for x in xs[scope]:
                    f=np.r_[x,tag]
                    a=int(net.predict(f)>=0)
                    success=a==truth(x,scope)
                    rewards.append(int(success))
                    net.update_from_feedback(f,a,bool(success));update_count+=1
                    if method=='shared_online_replay':
                        if reservoir:
                            old_f,old_a,old_success=reservoir[int(replay_rng.integers(len(reservoir)))]
                            net.update_from_feedback(old_f,old_a,old_success);update_count+=1
                        seen+=1
                        item=(f.copy(),a,bool(success))
                        if len(reservoir)<256: reservoir.append(item)
                        else:
                            j=int(replay_rng.integers(seen))
                            if j<256: reservoir[j]=item
                online.append((float(np.mean(rewards[:100])),float(np.mean(rewards[-200:]))))
                if method=='versioned': archive.register(f'public-schema-{scope}',net.freeze())
                for old in range(scope+1):
                    X=np.column_stack((test[old],np.tile(np.eye(3)[old],(512,1))))
                    pred=archive.predict(f'public-schema-{old}',X) if method=='versioned' else net.predict(X)
                    acc=float(np.mean((pred>=0)==np.array([truth(x,old) for x in test[old]])))
                    if old==scope: acquired[old]=(acc,pred.copy())
                    else:
                        forget.append(acquired[old][0]-acc)
                        drifts.append(float(np.max(np.abs(acquired[old][1]-pred))))
                bytes_used=archive.parameter_bytes if method=='versioned' else sum(a.nbytes for a in (net.w,net.b,net.v,net.c))
            results.append(dict(seed=seed,method=method,early=float(np.mean([a for a,b in online])),late=float(np.mean([b for a,b in online])),mean_forgetting=float(np.mean(forget)),worst_forgetting=float(max(forget)),max_logit_drift=max(drifts),parameter_bytes=bytes_used,learner_updates=update_count,replay_payload_bytes=len(reservoir)*(5*8+2)))
    summary=[]
    for method in ('shared_equal_width','shared_equal_parameter_budget','shared_online_replay','versioned'):
        rs=[r for r in results if r['method']==method]
        summary.append(dict(method=method,**{k:float(np.mean([r[k] for r in rs])) for k in rs[0] if k not in ('seed','method')}))
    out.mkdir(parents=True,exist_ok=True)
    (out/'versioned_training.json').write_text(json.dumps(dict(status='executed CPU neural toy; public scope identity; exact binary feedback',seeds=seeds,episodes_per_scope=episodes,records=seeds*4*3*episodes,summary=summary,per_seed=results),indent=2)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('artifacts/v3'));p.add_argument('--seeds',type=int,default=20);p.add_argument('--episodes',type=int,default=1600)
    a=p.parse_args();run(a.out,a.seeds,a.episodes)
