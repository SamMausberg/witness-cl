"""Freeze the v7 source/protocol only after the exact development grid completes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'src'))
from experiments.relational_v7 import Config, HOLDOUT_SEEDS, METHODS, default_config, source_hashes

EXTRA_SOURCES=(
    'tools/freeze_v7.py','tools/v7_results.py',
    'tests/test_relational_v7.py','tests/test_statistical_gate_v7.py',
    'tests/test_statistical_bridge_v7.py','tests/test_formal_v6.py',
    'docs/v7/REPRESENTATION.md','docs/v7/RESEARCH_BOUNDARIES.md',
    'formal/WitnessCL/StatisticalBridge.lean','formal/StatisticalFixture.lean',
    'formal/WitnessCL.lean','formal/lakefile.toml','formal/lean-toolchain',
)


def freeze(development,out):
    development,out=Path(development),Path(out)
    if out.exists(): raise ValueError('refusing to overwrite an existing freeze')
    manifest=json.loads((development/'manifest.json').read_text())
    expected=dict(status='complete',seeds=list(range(80000,80004)),methods=list(METHODS),
                  protocols=['matched','budget'],config=default_config())
    for field,value in expected.items():
        if manifest.get(field)!=value: raise ValueError('incomplete or nonprotocol development: '+field)
    for name,digest in manifest['source_sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('development source changed: '+name)
    raw={}
    for protocol in expected['protocols']:
        for seed in expected['seeds']:
            for method in METHODS:
                file=development/f'{protocol}-{seed}-{method}.json'
                data=json.loads(file.read_text())
                if (data['status']!='complete' or data['error'] is not None
                        or data['test_episode_limit'] is not None):
                    raise ValueError('failed/partial development arm: '+file.name)
                raw[file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
    replay_path=development.parent/'development-replay.json'
    receipts=json.loads(replay_path.read_text())
    matches=[r for r in receipts if Path(r.get('directory','')).resolve()==development.resolve()]
    if len(matches)!=1 or matches[0].get('status')!='passed' or matches[0].get('failures'):
        raise ValueError('a passing independent development replay is required')
    replay=matches[0]
    if replay.get('raw_sha256')!=raw or replay.get('manifest_sha256')!=hashlib.sha256((development/'manifest.json').read_bytes()).hexdigest():
        raise ValueError('development replay does not match exact raw evidence')
    if replay.get('replay_source_sha256')!=hashlib.sha256((ROOT/'experiments/audit_relational_v7.py').read_bytes()).hexdigest():
        raise ValueError('development replay source changed')
    hashes=source_hashes()
    hashes.update({name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in EXTRA_SOURCES})
    data=dict(format_version=1,created_at_utc=datetime.now(timezone.utc).isoformat(),
              parent_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              seeds=list(HOLDOUT_SEEDS),methods=list(METHODS),protocols=['matched','budget'],
              config=default_config(),source_sha256=hashes,
              development_directory=str(development.resolve().relative_to(ROOT)),
              development_manifest_sha256=hashlib.sha256((development/'manifest.json').read_bytes()).hexdigest(),
              development_raw_sha256=raw,
              development_replay_sha256=hashlib.sha256(replay_path.read_bytes()).hexdigest(),
              development_replay_source_sha256=replay['replay_source_sha256'],
              statement='All specified source/protocol inputs are frozen before any untouched evaluation stream. No development outcome selects a hyperparameter; fixes require a new preserved development run and protocol record.')
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x') as f: f.write(json.dumps(data,indent=2)+'\n')
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--development',type=Path,default=ROOT/'artifacts/v7/development')
    parser.add_argument('--out',type=Path,default=ROOT/'artifacts/v7/freeze.json')
    args=parser.parse_args();data=freeze(args.development,args.out)
    print(json.dumps(dict(freeze=str(args.out),source_files=len(data['source_sha256']),seeds=data['seeds']),indent=2))

if __name__=='__main__':main()
