#!/usr/bin/env python3
"""Final bounded development attempt with a portable schema transport.

The runner and validators are unchanged. Extend the frozen dependency inventory
with this selected entrypoint and its explicit client adapter.
"""
from pathlib import Path
import argparse
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from experiments import sql_abstractions_v9 as pilot
from witness_cl.model_v9_compatible import LocalInferenceV9Compatible
from witness_cl.model_v9 import DecodingV9

PORTABLE_SOURCE_FILES = ('src/witness_cl/model_v9_compatible.py',
                         'experiments/portable_stream_v9.py')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--key-file', type=Path, required=True)
    a = p.parse_args()
    client = LocalInferenceV9Compatible(endpoint='http://127.0.0.1:18085',
        model='witness-v9-qwen35-9b-q8', key_file=a.key_file, context_tokens=65536,
        max_output=4096, timeout=120, response_mode='schema',
        decoding=DecodingV9(temperature=.6, top_p=.95, top_k=20, min_p=0.,
                            presence_penalty=1.5, seed=42, thinking=True))
    limits = pilot.ResourceLimitsV9(wall_seconds=1800, ordinary_tokens=1000000,
        panel_tokens=1000000, total_tokens=3000000, total_calls=1200,
        solve_output_tokens=2048, reflection_output_tokens=4096)
    ordinary_sources = pilot.SOURCE_FILES
    pilot.SOURCE_FILES = (*ordinary_sources, *PORTABLE_SOURCE_FILES)
    try:
        result = pilot.run_study(a.out, client, stage='full', seeds=(92003,),
            conditions=('reuse',), arms=('full_history','insights','fragments'),
            limits=limits, minimum_warm_correct=7, gate_after_warm=True)
    finally:
        pilot.SOURCE_FILES = ordinary_sources
    return 0 if result['status'] == 'completed' else 2

if __name__ == '__main__':
    raise SystemExit(main())
