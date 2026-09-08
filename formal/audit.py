#!/usr/bin/env python3
"""Build all Lean modules and reject unapproved axioms in every project theorem.

Run from the repository root: python3 formal/audit.py --output artifacts/v5
Requires the pinned Lean toolchain. LAKE may specify a non-PATH lake executable.
The audit does not verify the Python/C++ runtime or research assumptions.
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


def run(command: list[str], cwd: Path, log: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    log.write_text('$ ' + ' '.join(command) + '\n' + result.stdout +
                   '\nexit_code=' + str(result.returncode) + '\n')
    return result


def declarations(source: str) -> tuple[list[str], list[str]]:
    # These files use block/line comments and unindented namespace/theorem
    # declarations. Do not silently accept another declaration style.
    code = re.sub(r'/\-.*?\-/', '', source, flags=re.S)
    code = re.sub(r'--[^\n]*', '', code)
    forbidden = re.findall(r'\b(?:sorry|admit|axiom)\b', code)
    namespace = ''
    names = []
    for line in code.splitlines():
        if match := re.fullmatch(r'namespace (\S+)\s*', line):
            namespace = match[1]
        if match := re.match(r'^theorem (\w+)\b', line):
            names.append(namespace + '.' + match[1])
    count = len(re.findall(r'\btheorem\s+\w+', code))
    if count != len(names):
        raise ValueError('Unsupported theorem declaration layout; update audit parser.')
    return names, forbidden


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/v5'))
    args = parser.parse_args()
    formal = Path(__file__).resolve().parent
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lake = os.environ.get('LAKE') or shutil.which('lake')
    if lake is None:
        fallback = Path.home() / '.elan/bin/lake'
        if fallback.is_file():
            lake = str(fallback)
    if lake is None:
        raise SystemExit('lake not found; install the pinned toolchain or set LAKE.')
    by_file = {}
    forbidden = []
    hashes = {}
    for file in sorted((formal / 'WitnessCL').glob('*.lean')):
        source = file.read_text()
        names, bad = declarations(source)
        by_file[str(file.relative_to(formal))] = names
        forbidden.extend(bad)
        hashes[str(file.relative_to(formal))] = hashlib.sha256(source.encode()).hexdigest()
    names = [name for group in by_file.values() for name in group]
    if len(names) != len(set(names)) or not names:
        raise SystemExit('Duplicate or empty theorem inventory.')
    version = run([lake, 'env', 'lean', '--version'], formal, output / 'formal-version.txt')
    build = run([lake, 'build'], formal, output / 'formal-build.txt')
    report = {
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'toolchain': (formal / 'lean-toolchain').read_text().strip(),
        'compiler': version.stdout.strip(),
        'build_exit_code': build.returncode,
        'theorem_count': len(names),
        'theorems_by_file': by_file,
        'source_sha256': hashes,
        'source_placeholder_or_custom_axiom_tokens': forbidden,
        'allowed_standard_axioms': ['Classical.choice', 'Quot.sound', 'propext'],
        'theorem_axioms': {},
        'passed': False,
    }
    if version.returncode == 0 and build.returncode == 0 and not forbidden:
        audit_file = formal / '.lake' / 'AxiomAudit.lean'
        audit_file.write_text('import WitnessCL\n\n' + ''.join('#print axioms ' + name + '\n' for name in names))
        audit = run([lake, 'env', 'lean', str(audit_file.relative_to(formal))],
                    formal, output / 'formal-axioms.txt')
        pattern = r"'([^']+)' (does not depend on any axioms|depends on axioms: \[([^\]]*)\])"
        parsed = {}
        for match in re.finditer(pattern, audit.stdout):
            parsed[match[1]] = [] if match[3] is None else [a.strip() for a in match[3].split(',')]
        unexpected = sorted({a for group in parsed.values() for a in group} - set(report['allowed_standard_axioms']))
        report.update({
            'audit_exit_code': audit.returncode,
            'theorem_axioms': parsed,
            'unexpected_axioms': unexpected,
            'axiom_usage_counts': dict(sorted(Counter(a for group in parsed.values() for a in group).items())),
            'axiom_free_theorems': sum(not group for group in parsed.values()),
            'passed': audit.returncode == 0 and set(parsed) == set(names) and not unexpected,
        })
    (output / 'formal-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report.get(key) for key in
                     ['passed', 'theorem_count', 'build_exit_code', 'audit_exit_code',
                      'axiom_free_theorems', 'axiom_usage_counts', 'unexpected_axioms']}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
