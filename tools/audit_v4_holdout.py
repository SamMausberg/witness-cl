"""Check that later checker optimizations did not alter held-out controller behavior."""
from pathlib import Path
import csv,gzip,json,hashlib,statistics,sys
from scipy import stats
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from latent_continuation import make_world

def rows(path):
    with gzip.open(path,'rt') as f:return list(csv.DictReader(f))
old=rows(ROOT/'artifacts/v4/pre_backend/heldout_episodes.csv.gz')
new=rows(ROOT/'artifacts/v4/heldout/latent_episodes.csv.gz')
# Profiling counters are allowed to change; actions and learning are not.
exclude={'checker_nodes'}
fields=[k for k in old[0] if k not in exclude and 'nodes' not in k]
assert len(old)==len(new)
for a,b in zip(old,new):
    assert all(a[k]==b[k] for k in fields),(a,b)
s=json.loads((ROOT/'artifacts/v4/heldout/latent_summary.json').read_text())
per={(x['seed'],x['method']):x for x in s['per_seed']}
pairs=[]
for a,b in [('latent_neural_B64','latent_unguided_B64'),('latent_neural_B64','latent_untrained_B64')]:
    ds=[per[i,a]['mean_return']-per[i,b]['mean_return'] for i in range(10000,10100)]
    m=statistics.mean(ds);sd=statistics.stdev(ds)
    ci=list(stats.t.interval(.95,len(ds)-1,loc=m,scale=sd/len(ds)**.5)) if sd else [m,m]
    pairs.append(dict(a=a,b=b,mean_difference=m,ci95_t=ci))
dev={make_world(i).table for i in range(20)}
held={make_world(i).table for i in range(10000,10100)}
paths=['src/witness_cl/latent.py','src/witness_cl/latent_agent.py','experiments/latent_continuation.py']
result={'status':'all selected behavioral fields identical after backend refinement',
        'rows_compared':len(new),'fields':fields,
        'original_freeze':'heldout_protocol.json is retained unchanged; local record, not external preregistration',
        'changes_after_first_holdout':['exact residual DAG replaces repeated structural suffix checks',
          'strict JSON candidate registration and input validation added; no new candidates in fixed-library study'],
        'no_holdout_controller_tuning':True,
        'unique_development_tables':len(dev),'unique_heldout_tables':len(held),
        'overlap_tables':len(dev&held),'finite_class_size':256,
        'paired_secondary':pairs,
        'sha256_final':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}}
(ROOT/'artifacts/v4/holdout_audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
