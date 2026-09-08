"""Independent replay of saved v5 episode arithmetic and experiment provenance."""
from __future__ import annotations
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import random
import statistics
from witness_cl.latent import Machine, Program


def world(seed):
    rng = random.Random(seed)
    return tuple((rng.randrange(2), rng.randrange(2)) for _ in range(4))


def audit(directory):
    summary = json.loads((directory/'summary.json').read_text())
    with gzip.open(directory/'episodes.csv.gz', 'rt') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == summary['episode_rows'] == summary['seeds'] * 48 * 4
    own = defaultdict(list)
    for row in rows:
        own[int(row['seed']), row['method']].append(row)
    checked = prefixes = 0
    for record in summary['per_seed']:
        seed, method = record['seed'], record['method']
        part = own[seed, method]
        assert [int(x['episode']) for x in part] == list(range(48))
        machine = Machine(2, 2, 2, world(seed)); deficit = worst = spent = 0
        observed = []
        for episode, row in enumerate(part):
            goal = 0 if episode < 16 or episode >= 32 else 1
            rewards = ((0, 2), (2, 0))[goal]
            index = int(row['program'])
            word = tuple((index >> shift) & 1 for shift in (3, 2, 1, 0))
            trace = Program.word(word, 2).rollout(machine)
            assert json.loads(row['trace']) == [list(x) for x in trace]
            reward = sum(rewards[o] for _, o in trace)
            anchor = sum(rewards[o] for _, o in machine.run((0, 0, 0, 0)))
            assert int(row['reward']) == reward and int(row['anchor']) == anchor
            assert int(row['goal']) == goal
            observed.append(reward)
            deficit += anchor - reward; worst = max(worst, deficit)
            assert int(row['prefix_deficit']) == deficit
            if method != 'full_history_optimistic':
                assert spent <= int(row['spent']) <= 16
                spent = int(row['spent'])
                assert deficit <= spent
                prefixes += 1
            checked += 1
        assert record['mean_return'] == statistics.mean(observed)
        assert record['late_A'] == statistics.mean(observed[-8:])
        assert record['worst_prefix_deficit'] == worst
        assert record['spent'] == spent
        assert record['incumbent_violations'] == 0
    return {'status': 'passed', 'episode_rewards_and_traces_replayed': checked,
            'budget_prefixes_checked': prefixes,
            'incumbent_violations_reported': 0,
            'incumbent_retention_note': 'trajectory tests independently verify this; episode CSV does not store incumbent IDs'}


def main():
    root = Path('artifacts/v5/experiment')
    results = {split: audit(root/split) for split in ('pilot', 'holdout')}
    pilot = {world(s) for s in range(20000, 20020)}
    holdout = {world(s) for s in range(30000, 30100)}
    old_pilot = {world(s) for s in range(20)}
    old_holdout = {world(s) for s in range(10000, 10100)}
    freeze = json.loads((root/'protocol_freeze.json').read_text())
    source_match = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
                    for p, h in freeze['files'].items() if not p.startswith('docs/')}
    assert all(source_match.values())
    result = {'audits': results, 'frozen_source_matches': source_match,
        'world_overlap': {'v5_pilot_unique': len(pilot), 'v5_holdout_unique': len(holdout),
            'v5_pilot_holdout_shared': len(pilot & holdout),
            'v5_holdout_shared_with_v4_development': len(holdout & old_pilot),
            'v5_holdout_shared_with_v4_holdout': len(holdout & old_holdout),
            'note': 'exact labelled transition tables, not behavioral isomorphism classes'}}
    (root/'audit.json').write_text(json.dumps(result, indent=2)+'\n')
    s = json.loads((root/'holdout/summary.json').read_text())
    aggregates = {a['method']: a for a in s['aggregates']}
    compact = {'status': 'primary v5 probe-selection hypothesis rejected',
        'primary': s['paired'][0], 'all_paired_comparisons': s['paired'],
        'methods': s['aggregates'], 'world_overlap': result['world_overlap'],
        'cost_ratios': {'v5_over_v4_seconds': aggregates['v5_decision_B16']['seconds']/aggregates['v4_B16']['seconds'],
            'v5_over_full_history_seconds': aggregates['v5_decision_B16']['seconds']/aggregates['full_history_optimistic']['seconds']},
        'audit': results, 'source_hashes': s['source_sha256']}
    (root/'paper_summary.json').write_text(json.dumps(compact, indent=2)+'\n')
    files = [Path('src/witness_cl/latent.py'), Path('src/witness_cl/latent_agent.py'),
             Path('src/witness_cl/latent_v5.py'), Path('experiments/latent_v5.py'),
             Path('experiments/audit_v5.py'), Path('tests/test_v5_decision.py'),
             Path('src/witness_cl/latent_v5_successor.py'), Path('experiments/latent_v5_successor.py'),
             Path('tests/test_v5_successor.py'), Path('tests/test_v5_complementarity.py')]
    files += sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json' and p.suffix != '.log')
    manifest = {'status': 'post-execution SHA256 manifest; local freeze predates execution',
                'sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    print(json.dumps(compact['cost_ratios'], indent=2))


if __name__ == '__main__':
    main()
