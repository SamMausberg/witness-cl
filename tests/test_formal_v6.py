"""Differential checks against the separately compiled Lean finite interpreter.

The checked-in oracle enumerates all labelled 2-state/2-action/2-output machines,
all words of length 0..4, and four cumulative reset histories per true machine.
This tests (and does not prove) the correspondence with the Python implementation.
Regenerate with `python3 formal/audit.py --output artifacts/v6`.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from itertools import product
from pathlib import Path

import pytest

from witness_cl.latent import LatentSpace, Machine, Program

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts/v6'

# Preserve the exact archived v6 build inputs, then permit only additive imports
# and targets in later versions. Every v6 module and fixture remains hash-exact.
V6_BUILD_INPUTS = {'WitnessCL.lean': 'import WitnessCL.Core\n'
                   'import WitnessCL.Refinement\n'
                   '\n'
                   'import WitnessCL.Continuation\n'
                   '\n'
                   'import WitnessCL.Latent\n'
                   '\n'
                   'import WitnessCL.Ambiguity\n'
                   '\n'
                   'import WitnessCL.Executable\n',
 'lakefile.toml': 'name = "witnesscl"\n'
                  'version = "0.1.0"\n'
                  'defaultTargets = ["WitnessCL"]\n'
                  '\n'
                  '[[lean_lib]]\n'
                  'name = "WitnessCL"\n'
                  '\n'
                  '[[lean_exe]]\n'
                  'name = "witness_fixture"\n'
                  'root = "ExecutableFixture"\n'}


def assert_additive_build_input(name, archived_digest):
    archived = V6_BUILD_INPUTS[name]
    assert hashlib.sha256(archived.encode()).hexdigest() == archived_digest
    current = (ROOT / 'formal' / name).read_text()
    if name == 'WitnessCL.lean':
        def imports(source):
            lines = [line.strip() for line in source.splitlines() if line.strip()]
            assert all(line.startswith('import ') and len(line.split()) == 2 for line in lines)
            return [line.split()[1] for line in lines]
        old_imports, current_imports = imports(archived), imports(current)
        assert [item for item in current_imports if item in old_imports] == old_imports
    else:
        old_config, current_config = tomllib.loads(archived), tomllib.loads(current)
        assert old_config.keys() == current_config.keys()
        for field, value in old_config.items():
            if field in ('defaultTargets', 'lean_lib', 'lean_exe'):
                assert all(item in current_config[field] for item in value), field
                assert isinstance(current_config[field], list)
            else:
                assert current_config[field] == value, field



def machine_from_id(identifier: int) -> Machine:
    return Machine(2, 2, 2, tuple(((identifier // 4**slot % 4) // 2,
                                   identifier // 4**slot % 2) for slot in range(4)))


@pytest.fixture(scope='module')
def oracle():
    with (ARTIFACTS / 'formal-runtime.jsonl').open() as handle:
        return [json.loads(line) for line in handle]


def test_lean_fixture_matches_audited_sources(oracle):
    report = json.loads((ARTIFACTS / 'formal-audit.json').read_text())
    assert report['passed']
    assert report['executable_fixture']['exit_code'] == 0
    assert report['executable_fixture']['line_count'] == len(oracle)
    assert hashlib.sha256((ARTIFACTS / 'formal-runtime.jsonl').read_bytes()).hexdigest() == (
        report['executable_fixture']['sha256'])
    for source, digest in {**report['source_sha256'], **report['build_input_sha256']}.items():
        if source in V6_BUILD_INPUTS:
            assert_additive_build_input(source, digest)
        else:
            assert hashlib.sha256((ROOT / 'formal' / source).read_bytes()).hexdigest() == digest, source
    assert not report['source_placeholder_or_custom_axiom_tokens']
    assert not report['unexpected_axioms']
    names = report['theorems_by_file']['WitnessCL/Executable.lean']
    assert len(names) == 12
    assert all(name in report['theorem_axioms'] for name in names)


def test_exhaustive_fixture_coverage(oracle):
    assert oracle[0] == dict(kind='header', schema='witness-cl-executable-v1',
                            states=2, actions=2, outputs=2, machines=256, max_word_length=4)
    traces = [row for row in oracle if row['kind'] == 'trace']
    histories = [row for row in oracle if row['kind'] == 'filter']
    expected = {(identifier, word) for identifier in range(256)
                for length in range(5) for word in product(range(2), repeat=length)}
    assert {(r['machine'], tuple(r['word'])) for r in traces} == expected
    assert len(traces) == 7936
    assert len(histories) == 1024
    assert {(r['truth'], len(r['history'])) for r in histories} == {
        (identifier, count) for identifier in range(256) for count in range(1, 5)}
    assert len(oracle) == 1 + len(traces) + len(histories)


def test_python_machine_and_program_word_match_lean(oracle):
    for row in oracle:
        if row['kind'] != 'trace':
            continue
        machine = machine_from_id(row['machine'])
        word = tuple(row['word'])
        trace = tuple(map(tuple, row['trace']))
        assert machine.run(word) == trace, (row['machine'], word)
        if word:
            assert Program.word(word, 2).rollout(machine) == trace, (row['machine'], word)
        state = 0
        for action in word:
            state = machine.table[state * 2 + action][0]
        assert state == row['final_state']


def test_python_partial_table_filter_matches_lean_history_filter(oracle):
    machines = [machine_from_id(i) for i in range(256)]
    for row in oracle:
        if row['kind'] != 'filter':
            continue
        space = LatentSpace(2, 2, 2)
        for raw_trace in row['history']:
            space.observe(tuple(map(tuple, raw_trace)))
        assert space.complete
        surviving_ids = [i for i, machine in enumerate(machines) if space.contains(machine)]
        assert surviving_ids == row['survivors'], (row['truth'], row['history'])
        assert row['truth'] in surviving_ids


def test_conflicting_observations_break_the_stationary_contract():
    # Even a true machine is correctly removed by corrupted evidence: the
    # preservation theorem requires traces generated by the same reset machine.
    truth = machine_from_id(0)
    space = LatentSpace(2, 2, 2)
    space.observe(truth.run((0,)))
    assert space.contains(truth)
    space.observe(((0, 1),))
    assert space.complete
    assert not space.contains(truth)
    assert not space.partials
