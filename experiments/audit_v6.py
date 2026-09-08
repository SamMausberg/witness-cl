"""Replay completed v6 evidence without invoking any agent or planner."""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import statistics
from itertools import product
from pathlib import Path
from witness_cl.latent import Machine, Program


def audit(directory: Path):
    if not __debug__:
        raise RuntimeError('audit requires assertions; do not use Python -O')
    summary=json.loads((directory/'summary.json').read_text())
    with gzip.open(directory/'episodes.csv.gz','rt') as f:
        rows=list(csv.DictReader(f))
    assert len(rows)==summary['episode_rows']
    programs=tuple(Program.word(w,3) for w in product(range(2),repeat=3))
    rewards=((0,1,2),(2,1,0))
    worlds=tuple(Machine(2,2,3,t) for t in product(tuple(product(range(2),range(3))),repeat=4))
    traces=tuple(tuple(p.rollout(m) for p in programs) for m in worlds)
    values=tuple(tuple(tuple(sum(r[o] for _,o in tr) for r in rewards) for tr in ts) for ts in traces)
    true_tables={r['seed']:tuple(map(tuple,r['table'])) for r in summary['worlds_evaluator_only']}
    streams={}
    guarded_prefixes=promotions=unknown=0
    for row in rows:
        key=int(row['seed']),row['method']
        streams.setdefault(key,[]).append(row)
    assert len(streams)==summary['seeds']*len(summary['methods'])
    for (seed,method),stream in streams.items():
        assert method in ('depth_two_B16', 'informative_zero_loss_B16', 'optimistic_B16', 'v4_frozen_ranker_B16', 'full_history_optimistic')
        guarded = method != 'full_history_optimistic'
        assert len(stream)==summary['episodes']
        true_id=next(i for i,m in enumerate(worlds) if m.table==true_tables[seed])
        compatible=list(range(len(worlds)))
        last_incumbents=[0,0]; spent=deficit=0
        for episode,row in enumerate(stream):
            assert int(row['episode'])==episode
            goal=int(row['goal']);chosen=int(row['program'])
            assert 0 <= chosen < len(programs)
            assert row['guarded'] == str(guarded)
            assert row['status'] in (('exact', 'unknown') if method in ('depth_two_B16', 'informative_zero_loss_B16', 'optimistic_B16') else ('not_metered',))
            assert goal==(0 if episode<8 or episode>=16 else 1)
            trace=tuple(map(tuple,json.loads(row['trace'])))
            assert trace==traces[true_id][chosen]
            reward=values[true_id][chosen][goal];anchor=values[true_id][0][goal]
            assert int(row['reward'])==reward and int(row['anchor'])==anchor
            deficit+=anchor-reward
            assert int(row['prefix_deficit'])==deficit
            if guarded:
                old=json.loads(row['incumbents_before']);new=json.loads(row['incumbents_after'])
                assert all(isinstance(xs, list) and len(xs)==2 and all(type(j) is int and 0<=j<len(programs) for j in xs) for xs in (old,new))
                assert old==last_incumbents
                for g in range(2):
                    assert min(values[m][new[g]][g]-values[m][old[g]][g] for m in compatible)>=0
                    promotions+=new[g]!=old[g]
                debit=int(row['debit']);lower=min(values[m][chosen][goal]-values[m][new[goal]][goal] for m in compatible)
                assert debit>=max(0,-lower)
                assert debit >= 0
                spent+=debit
                assert int(row['spent'])==spent and 0<=spent<=16 and deficit<=spent
                if row['status']=='unknown':
                    unknown+=1
                    assert old==new and chosen==old[goal] and debit==0
                last_incumbents=new
                guarded_prefixes+=1
            compatible=[m for m in compatible if traces[m][chosen]==trace]
            assert true_id in compatible and len(compatible)==int(row['compatible_models'])
        expected=next(s for s in summary['per_seed'] if s['seed']==seed and s['method']==method)
        assert abs(statistics.mean(int(r['reward']) for r in stream)-expected['mean_return'])<1e-12
    return dict(status='passed independent raw-data replay',directory=str(directory),episodes=len(rows),
                streams=len(streams),guarded_prefixes=guarded_prefixes,promotions=promotions,unknown_fallbacks=unknown,
                violations=0, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                episodes_sha256=hashlib.sha256((directory/'episodes.csv.gz').read_bytes()).hexdigest(),
                summary_sha256=hashlib.sha256((directory/'summary.json').read_bytes()).hexdigest())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directories',nargs='+',type=Path);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();result=[audit(d) for d in args.directories]
    args.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
