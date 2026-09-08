"""Reconcile archived raw controller records and documented v3 aggregate claims."""
from pathlib import Path
import csv,gzip,json,math
ROOT=Path(__file__).resolve().parents[1];A=ROOT/'artifacts/v3'
def main():
 c=json.loads((A/'continuation.json').read_text())
 with gzip.open(A/'episodes.csv.gz','rt') as f: rows=list(csv.DictReader(f))
 assert len(rows)==c['records']==17920
 groups={}
 for r in rows: groups.setdefault((r['domain'],int(r['seed']),r['method']),[]).append(r)
 for x in c['per_seed']:
  rs=groups[(x['domain'],x['seed'],x['method'])]
  assert len(rs)==64
  assert math.isclose(sum(int(r['reward']) for r in rs[-16:])/16,x['late'],abs_tol=1e-12)
  regret=0;worst=0;spent=0
  for r in rs:
   events=json.loads(r['transitions']);assert len(events)==5
   state=int(r['state'])
   for step,event in enumerate(events):
    assert event['episode']==int(r['episode']) and event['step']==step and event['state']==state
    state=event['next_state']
   assert sum(e['reward'] for e in events)==int(r['reward'])
   regret+=int(r['anchor_reward'])-int(r['reward']);worst=max(worst,regret)
   assert regret==int(r['regret'])
   if r['method'].startswith('contract_budget'):
    B=int(r['method'].removeprefix('contract_budget'));spent+=int(r['debit'])
    assert regret<=spent<=B and spent==int(r['spent'])
  assert worst==x['max_prefix_regret']
 for domain in ['delayed_damage','compositional_navigation']:
  for seed in range(20):
   ix={x['method']:x for x in c['per_seed'] if x['domain']==domain and x['seed']==seed}
   assert ix['contract_budget4']['late']==ix['raw_evidence_optimistic']['late']
 n=json.loads((A/'versioned_training.json').read_text())
 assert n['records']==384000 and len(n['per_seed'])==80
 for x in n['per_seed']:
  if x['method']=='versioned': assert x['max_logit_drift']==x['mean_forgetting']==x['worst_forgetting']==0
 print('17,920 archived rows reconciled; all budget prefixes, 40 paired late-return ties, and 20 frozen-module retention results checked.')
if __name__=='__main__':main()
