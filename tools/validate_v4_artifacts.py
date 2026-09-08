"""Independently reconcile saved episode rows with reported primary metrics."""
from pathlib import Path
from collections import defaultdict
import csv,gzip,json,statistics,re,xml.etree.ElementTree as ET
R=Path(__file__).resolve().parents[1]
s=json.loads((R/'artifacts/v4/heldout/latent_summary.json').read_text())
with gzip.open(R/'artifacts/v4/heldout/latent_episodes.csv.gz','rt') as f:rows=list(csv.DictReader(f))
assert len(rows)==38400==s['episode_rows']
groups=defaultdict(list)
for r in rows:groups[int(r['seed']),r['method']].append(r)
assert len(groups)==800
for report in s['per_seed']:
    rs=groups[report['seed'],report['method']]
    assert len(rs)==48
    assert [int(x['episode']) for x in rs]==list(range(48))
    vals=[int(x['reward']) for x in rs]
    assert abs(statistics.mean(vals)-report['mean_return'])<1e-12
    assert abs(statistics.mean(vals[-8:])-report['late_A'])<1e-12
    deficit=worst=0
    for x in rs:
        deficit+=int(x['anchor'])-int(x['reward']);worst=max(worst,deficit)
        assert deficit==int(x['deficit'])
        if report['method'].startswith('latent_'):
            budget=int(report['method'].rsplit('B',1)[1])
            assert deficit<=int(x['spent'])<=budget
    assert worst==report['worst_prefix_deficit']
for a in s['aggregates']:
    vals=[x['mean_return'] for x in s['per_seed'] if x['method']==a['method']]
    assert abs(statistics.mean(vals)-a['mean_return']['mean'])<1e-12
xml=ET.parse(R/'artifacts/v4/pytest.xml')
assert sum(int(s.attrib['tests']) for s in xml.iter('testsuite'))==355
assert sum(int(s.attrib.get(k,0)) for s in xml.iter('testsuite') for k in ('errors','failures'))==0
formal='\n'.join(p.read_text() for p in (R/'formal').rglob('*.lean'))
assert len(re.findall(r'^theorem\s+',formal,re.M))==50
assert not re.search(r'^\s*(?:sorry|admit)\s*$',formal,re.M)
log=(R/'paper/main.log').read_text()
assert 'Overfull' not in log and 'undefined' not in log and 'Warning' not in log
print('38400 raw rows, 800 seed/system summaries, prefix ledgers and reported means reconciled.')
print('355 passing Python cases confirmed from XML; 50 Lean declarations counted, not compiled.')
print('Final LaTeX log contains no overfull boxes, unresolved references or warnings.')
