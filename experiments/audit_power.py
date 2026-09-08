"""Monte Carlo audit-cost diagnostic, NOT empirical evidence about an LLM.

Floating log-space simulation of the same finite betting mixture. The executable
admission reference uses Fraction arithmetic; this diagnostic is only for power.
The paired difference is +1, 0, -1 with fixed disagreement rate 0.3.
"""
from pathlib import Path
import argparse
import json
import numpy as np

def run(out: Path, replicates: int = 2000, horizon: int = 2048):
    rng=np.random.default_rng(741)
    stakes=np.array([.1,.25,.5,.75,1.])
    rows=[]
    for mean in [-.1,0.,.02,.05,.1,.2]:
        caps=np.zeros((replicates,len(stakes)))
        first=np.full(replicates,horizon+1,dtype=int)
        plus=(.3+mean)/2; minus=(.3-mean)/2
        for t in range(1,horizon+1):
            u=rng.random(replicates)
            d=np.where(u<plus,1,np.where(u<plus+minus,-1,0))
            with np.errstate(divide='ignore'):
                caps+=np.log1p(d[:,None]*stakes)
            loge=np.logaddexp.reduce(caps,axis=1)-np.log(len(stakes))
            first[(first>horizon)&(loge>=np.log(40))]=t
        row={'true_mean_difference':mean,'replicates':replicates,'horizon':horizon,
             'disagreement_rate':.3,'delta_global':.05,'candidate_index':1,
             'crossing_fraction':float(np.mean(first<=horizon))}
        for h in [12,128,512,2048]:
            if h<=horizon: row[f'pass_by_{h}']=float(np.mean(first<=h))
        hits=first[first<=horizon]
        row['median_crossing_among_passed']=float(np.median(hits)) if len(hits) else None
        rows.append(row)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'kind':'synthetic_audit_power_diagnostic_not_llm','seed':741,'rows':rows},indent=2)+'\n')
    print(out)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=Path('artifacts/audit_power.json'))
    p.add_argument('--replicates',type=int,default=2000)
    a=p.parse_args()
    if a.replicates<100:p.error('replicates >=100 required')
    run(a.out,a.replicates)
