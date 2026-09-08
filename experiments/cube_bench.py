"""CPU-only factorization timing. Not a GPU or end-to-end LLM measurement."""
from __future__ import annotations
import json,random,statistics,time
from pathlib import Path
from witness_cl.relational import Column,Snapshot,schema_grammar,cube_evaluate
out=Path('artifacts/v2')
cs=(Column('gross','int'),Column('fee','int'),Column('done','bool'),Column('refund','bool'))
plans=tuple(r.evaluate for t in schema_grammar(cs) for r in t)
rng=random.Random(919);results=[]
for rows in [32,512,8192]:
    snapshots=[Snapshot(cs,tuple((rng.randrange(1000),rng.randrange(100),rng.choice([None,0,1]),rng.choice([None,0,1])) for _ in range(rows))) for _ in range(12)]
    timings={'naive':[],'cube':[]}
    for j,snapshot in enumerate(snapshots):
        # Alternate execution order, changing data each repetition.
        outputs={}
        for method in (['naive','cube'] if j%2 else ['cube','naive']):
            start=time.perf_counter_ns()
            outputs[method]=tuple(p(snapshot) for p in plans) if method=='naive' else cube_evaluate(plans,snapshot)
            timings[method].append((time.perf_counter_ns()-start)/1e6)
        assert outputs['naive']==outputs['cube']
    # First two repetitions treated as warmup; included raw but excluded summaries.
    n=statistics.median(timings['naive'][2:]);c=statistics.median(timings['cube'][2:])
    results.append(dict(rows=rows,plans=len(plans),naive_median_ms=n,cube_median_ms=c,
                        reference_speed_ratio=n/c,raw_ms=timings,cpu_only=True))
(out/'cube_bench.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
