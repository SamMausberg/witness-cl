"""Post-hoc exhaustive development diagnostic, never a new held-out claim."""
from itertools import product
import csv, gzip, hashlib, json, statistics, time
from pathlib import Path
from witness_cl.latent import LatentSpace, Machine, Program, value
from witness_cl.latent_agent import LatentAgent
from witness_cl.latent_v5 import DecisionDirectedAgent
from witness_cl.latent_v5_successor import WeakDominanceClosureAgent


def run():
    out = Path('artifacts/v5/experiment/successor_exhaustive'); out.mkdir(parents=True, exist_ok=True)
    ps = tuple(Program.word(w, 2) for w in product(range(2), repeat=4)); goals = ((0, 2), (2, 0))
    methods = ('v4_B16', 'v5_decision_B16', 'v5_weak_closure_B16', 'full_history_optimistic')
    rows = []; summaries = []; started = time.perf_counter()
    for index, table in enumerate(product(tuple(product(range(2), range(2))), repeat=4)):
        m = Machine(2, 2, 2, table)
        for name in methods:
            kind = {'v4_B16': LatentAgent, 'v5_decision_B16': DecisionDirectedAgent,
                    'v5_weak_closure_B16': WeakDominanceClosureAgent}.get(name)
            a = kind(LatentSpace(2, 2, 2), ps, goals, budget=16, seed=index) if kind else None
            space = a.space if a else LatentSpace(2, 2, 2)
            old = [value(m, ps[0], r) for r in goals]; deficit = worst = 0
            own = []; violations = 0; start = time.perf_counter()
            for n in range(48):
                g = 0 if n < 16 or n >= 32 else 1; r = goals[g]
                if a:
                    t = a.choose(g); j = t.program
                    now = [value(m, ps[k], q) for k, q in zip(a.incumbents, goals)]
                    violations += sum(v < u for u, v in zip(old, now)); old = now
                else:
                    models = list(space.completions()); scores = []
                    for p in ps:
                        vals = [value(x, p, r) for x in models]
                        scores.append((max(vals), statistics.mean(vals)))
                    j = max(range(len(ps)), key=lambda k: (*scores[k], -k))
                trace = ps[j].rollout(m); reward = sum(r[o] for _, o in trace)
                anchor = value(m, ps[0], r); deficit += anchor - reward; worst = max(worst, deficit)
                if a:
                    assert deficit <= a.spent <= 16
                    a.observe(t, trace); assert space.contains(m)
                else:
                    space.observe(trace)
                own.append(reward)
                rows.append({'table_index': index, 'method': name, 'episode': n, 'goal': g,
                             'program': j, 'reward': reward, 'anchor': anchor,
                             'deficit': deficit, 'spent': a.spent if a else 0})
            assert violations == 0
            summaries.append({'table_index': index, 'method': name,
                'mean_return': statistics.mean(own), 'late_A': statistics.mean(own[-8:]),
                'worst_prefix_deficit': worst, 'spent': a.spent if a else 0,
                'incumbent_violations': violations, 'seconds': time.perf_counter()-start,
                'weak_promotions': getattr(a, 'weak_promotions', 0)})
        if (index+1)%32 == 0:
            print(f'{index+1}/256 tables, {time.perf_counter()-started:.1f}s', flush=True)
    aggregates = []
    for name in methods:
        part = [s for s in summaries if s['method'] == name]
        aggregates.append({'method': name, **{k: statistics.mean([s[k] for s in part])
                            for k in part[0] if k not in ('table_index', 'method')},
                           'max_worst_prefix_deficit': max(s['worst_prefix_deficit'] for s in part)})
    before = {s['table_index']: s for s in summaries if s['method'] == 'v5_decision_B16'}
    after = {s['table_index']: s for s in summaries if s['method'] == 'v5_weak_closure_B16'}
    comparison = {field: {'mean_difference': statistics.mean([after[i][field]-before[i][field] for i in before]),
                    'improved_tables': sum(after[i][field] > before[i][field] for i in before),
                    'worsened_tables': sum(after[i][field] < before[i][field] for i in before)}
                  for field in ('mean_return', 'late_A')}
    result = {'status': 'post-hoc development diagnostic after v5 heldout rejection; not confirmatory',
        'population': 'all 256 labelled two-state binary-action binary-output transition tables',
        'proposer_initialization': 'one initialization per table: seed equals lexicographic table index',
        'episodes': 48, 'episode_rows': len(rows), 'aggregates': aggregates,
        'successor_vs_original': comparison, 'per_table': summaries,
        'uncertainty': 'no confidence interval: exhaustive finite population conditional on these initializations',
        'limitations': ['all observations overlap the finite development population', 'unequal total computation',
                       'one proposer initialization per table', 'weak closure does not resolve complementary probes'],
        'source_sha256': {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in
              ('src/witness_cl/latent_v5_successor.py', 'experiments/latent_v5_successor.py')}}
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    with gzip.open(out/'episodes.csv.gz', 'wt', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(json.dumps({'aggregates': aggregates, 'successor_vs_original': comparison}, indent=2), flush=True)


if __name__ == '__main__': run()
