#!/usr/bin/env python3
"""Audit the additive v8 module without changing any frozen v7 source or artifact.

Run from repository root: python3 formal/audit_v8.py --output artifacts/v8
The archived v7 audit command remains reproducible at the v7 frozen revision.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from audit import declarations, run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/v8'))
    args = parser.parse_args()
    formal = Path(__file__).resolve().parent
    root = formal.parent
    output = args.output.resolve()
    if any(output.is_relative_to(root / 'artifacts' / ('v' + str(v))) for v in range(1, 8)):
        raise SystemExit('v8 audit must not overwrite archived version artifacts')
    output.mkdir(parents=True, exist_ok=True)
    lake = os.environ.get('LAKE') or shutil.which('lake')
    if lake is None:
        fallback = Path.home() / '.elan/bin/lake'
        if fallback.is_file():
            lake = str(fallback)
    if lake is None:
        raise SystemExit('pinned lake not found; set LAKE')
    by_file, hashes, forbidden = {}, {}, []
    for file in sorted((formal / 'WitnessCL').glob('*.lean')):
        source = file.read_text()
        names, bad = declarations(source)
        by_file[str(file.relative_to(formal))] = names
        hashes[str(file.relative_to(formal))] = hashlib.sha256(file.read_bytes()).hexdigest()
        forbidden.extend(bad)
    names = [name for group in by_file.values() for name in group]
    if len(names) != len(set(names)) or not names:
        raise SystemExit('duplicate or empty theorem inventory')
    version = run([lake, 'env', 'lean', '--version'], formal, output / 'formal-version.txt')
    build = run([lake, 'build', 'WitnessCL', 'WitnessCL.TypedFragments'],
                formal, output / 'formal-build.txt')
    report = {
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'typed prepared-request compilation; SQLite semantics and learned truth remain outside Lean',
        'toolchain': (formal / 'lean-toolchain').read_text().strip(),
        'compiler': version.stdout.strip(), 'build_exit_code': build.returncode,
        'theorem_count': len(names),
        'new_theorem_count': len(by_file['WitnessCL/TypedFragments.lean']),
        'theorems_by_file': by_file, 'source_sha256': hashes,
        'build_input_sha256': {
            name: hashlib.sha256((formal / name).read_bytes()).hexdigest()
            for name in ['WitnessCL.lean', 'FragmentFixture.lean', 'lakefile.toml',
                         'lean-toolchain', 'audit.py', 'audit_v8.py']},
        'runtime_source_sha256': {
            'src/witness_cl/fragments_v8.py': hashlib.sha256(
                (root / 'src/witness_cl/fragments_v8.py').read_bytes()).hexdigest()},
        'source_placeholder_or_custom_axiom_tokens': forbidden,
        'allowed_standard_axioms': ['Classical.choice', 'Quot.sound', 'propext'],
        'theorem_axioms': {}, 'passed': False,
    }
    if version.returncode == 0 and build.returncode == 0 and not forbidden:
        audit_file = formal / '.lake' / 'AxiomAuditV8.lean'
        audit_file.write_text('import WitnessCL\nimport WitnessCL.TypedFragments\n\n' +
                             ''.join('#print axioms ' + name + '\n' for name in names))
        audit = run([lake, 'env', 'lean', str(audit_file.relative_to(formal))],
                    formal, output / 'formal-axioms.txt')
        pattern = r"'([^']+)' (does not depend on any axioms|depends on axioms: \[([^\]]*)\])"
        parsed = {m[1]: [] if m[3] is None else [a.strip() for a in m[3].split(',')]
                  for m in re.finditer(pattern, audit.stdout)}
        unexpected = sorted({a for group in parsed.values() for a in group} -
                            set(report['allowed_standard_axioms']))
        report.update({
            'audit_exit_code': audit.returncode, 'theorem_axioms': parsed,
            'unexpected_axioms': unexpected,
            'axiom_usage_counts': dict(sorted(Counter(a for group in parsed.values() for a in group).items())),
            'axiom_free_theorems': sum(not group for group in parsed.values()),
            'passed': audit.returncode == 0 and set(parsed) == set(names) and not unexpected,
        })
    if report['passed']:
        fixture = subprocess.run([lake, 'env', 'lean', '--run', 'FragmentFixture.lean'],
                                 cwd=formal, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, check=False)
        fixture_path = output / 'formal-fragments.jsonl'
        fixture_path.write_text(fixture.stdout)
        (output / 'formal-fragments-stderr.txt').write_text(fixture.stderr)
        report['fragment_fixture'] = {
            'path': fixture_path.name, 'exit_code': fixture.returncode,
            'sha256': hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
            'line_count': len(fixture.stdout.splitlines()),
        }
        report['passed'] = fixture.returncode == 0 and bool(fixture.stdout)
    (output / 'formal-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report.get(key) for key in
                     ['passed', 'theorem_count', 'new_theorem_count', 'build_exit_code',
                      'audit_exit_code', 'axiom_free_theorems', 'unexpected_axioms']}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
