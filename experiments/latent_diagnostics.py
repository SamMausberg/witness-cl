"""Checker cost, capacity stress, poisoned proposer, and assumption counterexamples."""
from __future__ import annotations
import argparse,json,random,statistics,time
from itertools import product
from pathlib import Path
import numpy as np
from witness_cl.latent import Machine,Program,LatentSpace,compare,value,possible_traces
from witness_cl.latent_agent import LatentAgent


def main(out):
    out.mkdir(parents=True,exist_ok=True)
    rng=random.Random(20260908)
    records=[]
    for category in ('identical','shared_suffix','unrelated'):
        for trial in range(20):
            m=Machine(2,3,2,tuple((rng.randrange(2),rng.randrange(2)) for _ in range(6)))
            s=LatentSpace(2,3,2)
            for _ in range(2):s.observe(m.run(tuple(rng.randrange(3) for _ in range(3))))
            bw=tuple(rng.randrange(3) for _ in range(5))
            cw=(bw if category=='identical' else ((bw[0]+1)%3,)+bw[1:] if category=='shared_suffix'
                else tuple(rng.randrange(3) for _ in range(5)))
            p,b=Program.word(cw,2),Program.word(bw,2)
            times={};checks={}
            for close in (False,True):
                elapsed=[]
                for _ in range(7):
                    start=time.perf_counter();c=compare(s,p,b,(-1,2),max_nodes=1000000,close_suffixes=close)
                    elapsed.append(time.perf_counter()-start)
                times[str(close)]=statistics.median(elapsed);checks[str(close)]=c
            assert checks['True'].status==checks['False'].status=='exact'
            assert (checks['True'].lower,checks['True'].upper)==(checks['False'].lower,checks['False'].upper)
            records.append({'category':category,'trial':trial,'unclosed_seconds':times['False'],
                'closed_seconds':times['True'],'unclosed_nodes':checks['False'].nodes,
                'closed_nodes':checks['True'].nodes,'closures':checks['True'].closed_suffixes,
                'speedup':times['False']/times['True'],'parity':True})
    scale=[]
    for k in (1,2,3,4,5):
        for h in (2,4,6):
            s=LatentSpace(k,3,2)
            start=time.perf_counter()
            c=compare(s,Program.word((1,)*h,2),Program.word((0,)*h,2),(-1,2),max_nodes=20000)
            scale.append({'states':k,'horizon':h,'status':c.status,'nodes':c.nodes,
                          'seconds':time.perf_counter()-start})
    ps=tuple(Program.word(w,2) for w in product(range(2),repeat=3))
    poison=[]
    for seed in range(50):
        rr=random.Random(seed+30000)
        m=Machine(2,2,2,tuple((rr.randrange(2),rr.randrange(2)) for _ in range(4)))
        a=LatentAgent(LatentSpace(2,2,2),ps,((0,2),(2,0)),budget=12,seed=seed)
        deficit=worst=0;previous=[value(m,ps[0],r) for r in a.rewards]
        mutations=0
        for n in range(24):
            # Simulated catastrophic proposer overwrites. Still only the checker may commit.
            a.proposer.w1[:]=np.random.default_rng(seed*100+n).normal(0,20,a.proposer.w1.shape)
            a.proposer.w2[:]=-10
            mutations+=1
            g=n%2;t=a.choose(g)
            new=[value(m,ps[j],r) for j,r in zip(a.incumbents,a.rewards)]
            assert all(x>=y for x,y in zip(new,previous));previous=new
            ret=value(m,ps[t.program],a.rewards[g]);deficit+=value(m,ps[0],a.rewards[g])-ret
            worst=max(worst,deficit);assert deficit<=a.spent<=12
            a.observe(t,ps[t.program].rollout(m))
        poison.append({'seed':seed,'mutations':mutations,'violations':0,'worst_deficit':worst,'spent':a.spent})
    # Unannounced transition drift: evidence and memory cannot identify it before feedback.
    old=Machine(1,2,2,((0,0),(0,1)))
    new=Machine(1,2,2,((0,1),(0,0)))
    s=LatentSpace(1,2,2);s.observe(old.run((0,)));s.observe(old.run((1,)))
    p,b=Program.word((1,1),2),Program.word((0,0),2)
    c=compare(s,p,b,(0,1))
    assert c.admits and value(new,p,(0,1))<value(new,b,(0,1))
    drift={'old_certificate_lower':c.lower,'new_world_actual_difference':value(new,p,(0,1))-value(new,b,(0,1)),
           'meaning':'hidden drift violates stationarity; archive/feedback cannot prevent first regression'}
    report={'status':'executed CPU diagnostics; not end-to-end serving','checker':records,
            'scale_stress':scale,'poisoned_proposer':poison,'unannounced_drift':drift,
            'aggregate':{cat:{'median_query_speedup':statistics.median(x['speedup'] for x in records if x['category']==cat),
              'total_node_ratio':sum(x['unclosed_nodes'] for x in records if x['category']==cat)/sum(x['closed_nodes'] for x in records if x['category']==cat)}
              for cat in ('identical','shared_suffix','unrelated')}}
    (out/'latent_diagnostics.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['aggregate'],indent=2));print('scale unknown',sum(x['status']=='unknown' for x in scale),'of',len(scale))
    print('proposer mutations',sum(p['mutations'] for p in poison),'violations',sum(p['violations'] for p in poison))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('artifacts/v4'));main(p.parse_args().out)
