"""Finite-population accounting correspondence; no statistical validity claim."""
from __future__ import annotations

from fractions import Fraction
import hashlib
from itertools import product
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts/v7'


@pytest.fixture(scope='module')
def oracle():
    with (ARTIFACTS / 'formal-statistical.jsonl').open() as handle:
        return [json.loads(line) for line in handle]


def test_statistical_bridge_fixture_provenance(oracle):
    report = json.loads((ARTIFACTS / 'formal-audit.json').read_text())
    assert report['passed']
    assert report['statistical_fixture']['exit_code'] == 0
    assert report['statistical_fixture']['line_count'] == len(oracle)
    assert hashlib.sha256((ARTIFACTS / 'formal-statistical.jsonl').read_bytes()).hexdigest() == (
        report['statistical_fixture']['sha256'])
    for source, digest in {**report['source_sha256'], **report['build_input_sha256']}.items():
        assert hashlib.sha256((ROOT / 'formal' / source).read_bytes()).hexdigest() == digest, source
    assert not report['source_placeholder_or_custom_axiom_tokens']
    assert not report['unexpected_axioms']
    names = report['theorems_by_file']['WitnessCL/StatisticalBridge.lean']
    assert len(names) == 14
    assert all(name in report['theorem_axioms'] for name in names)


def test_statistical_bridge_exhaustive_coverage(oracle):
    assert oracle[0] == dict(kind='header', schema='witness-cl-statistical-bridge-v1',
                            contexts=2, bound=2, versions=9, promotions=2)
    rows = oracle[1:]
    assert all(row['kind'] == 'chain' for row in rows)
    assert len(rows) == 2916
    assert {(tuple(r['versions']), tuple(r['tolerances'])) for r in rows} == {
        (versions, tolerances)
        for versions in product(range(9), repeat=3)
        for tolerances in product(range(2), repeat=2)}


def test_actual_population_totals_and_failure_events_match_lean(oracle):
    for row in oracle[1:]:
        returns = [[identifier % 3, identifier // 3] for identifier in row['versions']]
        assert row['returns'] == returns
        totals = list(map(sum, returns))
        assert row['totals'] == totals
        assert row['final_total'] == totals[-1]
        failures = [totals[i + 1] + tolerance < totals[i]
                    for i, tolerance in enumerate(row['tolerances'])]
        assert row['failed'] == failures
        # Exact expected-return normalization under the declared uniform law.
        means = [Fraction(total, 2) for total in totals]
        assert failures == [means[i + 1] + Fraction(tolerance, 2) < means[i]
                            for i, tolerance in enumerate(row['tolerances'])]


def test_all_historical_population_bounds_match_lean(oracle):
    for row in oracle[1:]:
        for historical in range(3):
            tolerance = sum(row['tolerances'][historical:])
            failures = sum(row['failed'][historical:])
            bound = row['final_total'] + tolerance + 4 * failures
            assert row['suffix_tolerances'][historical] == tolerance
            assert row['suffix_failures'][historical] == failures
            assert row['historical_bounds'][historical] == bound
            assert row['totals'][historical] <= bound
            if not failures:
                assert row['totals'][historical] <= row['final_total'] + tolerance
                if not tolerance:
                    assert row['totals'][historical] <= row['final_total']


def test_equal_population_mean_allows_context_regression_and_distribution_shift(oracle):
    row = next(r for r in oracle[1:] if r['versions'] == [4, 6, 6] and r['tolerances'] == [0, 0])
    old, candidate, _ = row['returns']
    assert old == [1, 1] and candidate == [0, 2]
    assert not any(row['failed'])
    assert sum(old) == sum(candidate)
    assert candidate[0] < old[0]
    # A new context law concentrated on context zero reverses the guarantee.
    assert Fraction(candidate[0], 1) < Fraction(old[0], 1)


def test_nonzero_promotion_tolerances_accumulate(oracle):
    row = next(r for r in oracle[1:] if r['versions'] == [8, 7, 6] and r['tolerances'] == [1, 1])
    assert row['totals'] == [4, 3, 2]
    assert row['failed'] == [False, False]
    assert row['totals'][0] - row['final_total'] == sum(row['tolerances']) == 2
    assert row['historical_bounds'][0] == row['totals'][0]
