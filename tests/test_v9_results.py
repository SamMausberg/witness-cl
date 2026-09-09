"""Report-consumer mutations on temporary copies of saved development evidence.

These tests do not call a model, replay SQLite, or change original receipts.
Rebound hashes below are simulated to test the consumer's additional invariants;
they are not newly audited scientific evidence.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('v9_descriptive_report_tests', REPO / 'tools/v9_results.py')
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)
DIAGNOSTIC = '4b-original'
ATTEMPT, FREEZE = 'prospective-92001', 'prepilot-freeze.json'


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, allow_nan=False) + '\n')


def base(root):
    return root / 'artifacts/v9'


def diagnostic_receipt(root, name=DIAGNOSTIC):
    return next(r for r in read(base(root) / 'diagnostics/replay-all.json')
                if Path(r['directory']).name == name)


@pytest.fixture(scope='module')
def saved_tree(tmp_path_factory):
    root = tmp_path_factory.mktemp('v9-report-evidence')
    shutil.copytree(REPO / 'artifacts/v9', base(root))
    required = {'experiments/audit_competence_v9.py',
                'experiments/audit_sql_abstractions_v9.py',
                'experiments/audit_sql_abstractions_v8.py'}
    for path in base(root).rglob('*.json'):
        value = read(path)
        records = value if isinstance(value, list) else [value]
        for record in records:
            if not isinstance(record, dict):
                continue
            for field in ('source_sha256', 'support_sha256', 'checked_source_sha256',
                          'checked_support_sha256', 'auditor_dependencies_sha256'):
                mapping = record.get(field)
                if isinstance(mapping, dict):
                    required.update(mapping)
    for name in required:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # Receipt hashes refer to the historical implementation. Current SQLite
        # compatibility fixes must not be relabeled as the original source.
        target.write_bytes(subprocess.check_output(
            ['git', 'show', '88b0a1b7c093c21135489a3e5cbbda3bb0634536:' + name], cwd=REPO))
    (root / 'paper').mkdir()
    return root


@pytest.fixture
def tree(saved_tree, tmp_path, monkeypatch):
    root = tmp_path / 'temporary-report-only'
    shutil.copytree(saved_tree, root)
    monkeypatch.setattr(report, 'ROOT', root)
    return root


def rebind_diagnostic(root, rows, receipt):
    directory = base(root) / 'diagnostics' / DIAGNOSTIC
    raw = directory / 'episodes.jsonl'
    raw.write_text(''.join(json.dumps(r, allow_nan=False) + '\n' for r in rows))
    manifest = read(directory / 'manifest.json')
    manifest['raw_sha256'] = report.sha(raw)
    write(directory / 'manifest.json', manifest)
    receipt.update(raw_sha256=report.sha(raw), manifest_sha256=report.sha(directory / 'manifest.json'))
    return receipt


def rebind_attempt(root, rows_by_name):
    directory = base(root) / ATTEMPT
    for name, rows in rows_by_name.items():
        (directory / name).write_text(''.join(json.dumps(r, allow_nan=False) + '\n' for r in rows))
    manifest = read(directory / 'manifest.json')
    manifest['raw_sha256'] = {p.name: report.sha(p) for p in directory.glob('*.jsonl')}
    write(directory / 'manifest.json', manifest)
    receipt_path = base(root) / (ATTEMPT + '-replay.json')
    receipt = read(receipt_path)
    receipt.update(raw_sha256=manifest['raw_sha256'], manifest_sha256=report.sha(directory / 'manifest.json'))
    write(receipt_path, receipt)


def test_actual_saved_evidence_generates_exact_descriptive_totals_in_temporary_tree(tree, capsys):
    report.main()
    capsys.readouterr()
    result = read(base(tree) / 'results.json')
    totals = result['totals']
    assert (totals['calls'], totals['known_tokens'], totals['unknown_calls'],
            totals['unknown_reservation']) == (244, 366795, 2, 9109)
    assert totals['token_upper_bound'] == 375904
    assert totals['token_allowance_including_unknown_reservations'] == 375904
    assert result['claim_confirmed'] is False
    assert [(r['arm'], r['correct'], r['n']) for r in result['final_arms']] == [
        ('full_history', 8, 8), ('insights', 6, 8), ('fragments', 7, 8)]
    assert (tree / 'paper/v9_diagnostics.tex').is_file()
    assert (tree / 'paper/v9_warm.tex').is_file()


def test_diagnostic_and_partial_attempt_positive_receipt_checks(tree):
    receipts = report.checked_diagnostic_receipts()
    assert set(receipts) == set(report.DIAGNOSTICS)
    diagnostic = report.checked_diagnostic(DIAGNOSTIC, receipts[DIAGNOSTIC])
    assert (diagnostic['calls'], diagnostic['tokens'], diagnostic['correct']) == (16, 10438, 0)
    attempt = report.checked_attempt(ATTEMPT, FREEZE)
    assert (attempt['calls'], attempt['known_tokens'], attempt['unknown_calls'],
            attempt['unknown_reservation']) == (7, 8956, 1, 5585)
    assert attempt['complete'] is False


def test_stale_diagnostic_manifest_is_rejected_even_with_unchanged_raw(tree):
    receipt = diagnostic_receipt(tree)
    path = base(tree) / 'diagnostics' / DIAGNOSTIC / 'manifest.json'
    manifest = read(path)
    manifest['correct'] = 8
    write(path, manifest)
    assert receipt['raw_sha256'] == report.sha(path.parent / 'episodes.jsonl')
    with pytest.raises(ValueError):
        report.checked_diagnostic(DIAGNOSTIC, receipt)


@pytest.mark.parametrize('mutation', ['wrong', 'duplicate', 'missing'])
def test_diagnostic_replay_roster_must_match_exactly_once(tree, mutation):
    path = base(tree) / 'diagnostics/replay-all.json'
    receipts = read(path)
    if mutation == 'wrong':
        receipts[0]['directory'] = str(path.parent / 'unexpected-diagnostic')
    elif mutation == 'duplicate':
        receipts.append(deepcopy(receipts[0]))
    else:
        receipts.pop()
    write(path, receipts)
    with pytest.raises(ValueError):
        report.checked_diagnostic_receipts()


@pytest.mark.parametrize('field,value', [
    ('status', 'failed'), ('raw_sha256', '0' * 64),
    ('checked_source_sha256', {}), ('known_usage_complete', False)])
def test_diagnostic_receipt_cannot_disagree_with_verified_inputs(tree, field, value):
    receipt = diagnostic_receipt(tree)
    receipt[field] = value
    with pytest.raises(ValueError):
        report.checked_diagnostic(DIAGNOSTIC, receipt)


def test_rebound_diagnostic_score_cannot_disagree_with_saved_raw(tree):
    receipt = diagnostic_receipt(tree)
    path = base(tree) / 'diagnostics' / DIAGNOSTIC / 'manifest.json'
    manifest = read(path)
    manifest['correct'] = 8
    write(path, manifest)
    receipt['manifest_sha256'] = report.sha(path)
    receipt['checked']['correct_episodes'] = 8
    with pytest.raises(ValueError):
        report.checked_diagnostic(DIAGNOSTIC, receipt)


@pytest.mark.parametrize('field,value', [('calls', -1), ('total_tokens', True),
                                         ('unknown_usage_calls', 1), ('prompt_tokens', 10049)])
def test_diagnostic_budget_must_have_valid_counts_and_match_raw(tree, field, value):
    receipt = diagnostic_receipt(tree)
    path = base(tree) / 'diagnostics' / DIAGNOSTIC / 'manifest.json'
    manifest = read(path)
    manifest['budget'][field] = value
    write(path, manifest)
    receipt['manifest_sha256'] = report.sha(path)
    receipt['recorded_budget'] = deepcopy(manifest['budget'])
    with pytest.raises(ValueError):
        report.checked_diagnostic(DIAGNOSTIC, receipt)


@pytest.mark.parametrize('field,value', [('total_tokens', 611), ('prompt_tokens', -1),
                                         ('completion_tokens', True)])
def test_rebound_diagnostic_call_usage_still_requires_valid_additive_counts(tree, field, value):
    rows = report.read_lines(base(tree) / 'diagnostics' / DIAGNOSTIC / 'episodes.jsonl')
    rows[0]['model_calls'][0]['usage'][field] = value
    receipt = rebind_diagnostic(tree, rows, diagnostic_receipt(tree))
    with pytest.raises(ValueError):
        report.checked_diagnostic(DIAGNOSTIC, receipt)


@pytest.mark.parametrize('mutation', ['raw_mismatch', 'raw_missing', 'dependency_missing',
                                      'unknown_count', 'reservation', 'known_tokens'])
def test_attempt_receipt_raw_dependencies_and_ledger_counts_are_required(tree, mutation):
    path = base(tree) / (ATTEMPT + '-replay.json')
    receipt = read(path)
    if mutation == 'raw_mismatch':
        receipt['raw_sha256'][next(iter(receipt['raw_sha256']))] = '0' * 64
    elif mutation == 'raw_missing':
        receipt.pop('raw_sha256')
    elif mutation == 'dependency_missing':
        receipt['auditor_dependencies_sha256'] = {}
    elif mutation == 'unknown_count':
        receipt['counts']['unknown_usage_calls'] = 0
    elif mutation == 'reservation':
        receipt['counts']['unknown_usage_reserved_tokens'] = 1
    else:
        receipt['counts']['known_total_tokens'] += 1
    write(path, receipt)
    with pytest.raises(ValueError):
        report.checked_attempt(ATTEMPT, FREEZE)


@pytest.mark.parametrize('field,value', [('preflight_tokens', -1), ('preflight_tokens', True),
                                         ('max_output_tokens', 0)])
def test_unknown_generation_requires_valid_reservation_inputs(tree, field, value):
    directory = base(tree) / ATTEMPT
    rows_by_name = {p.name: report.read_lines(p) for p in directory.glob('*.jsonl')}
    unknown = next(c for rows in rows_by_name.values() for r in rows for c in r['model_calls']
                   if c.get('generation_attempted') and c.get('usage') is None)
    unknown[field] = value
    rebind_attempt(tree, rows_by_name)
    with pytest.raises(ValueError):
        report.checked_attempt(ATTEMPT, FREEZE)


def test_aggregate_includes_diagnostic_unknown_calls_and_reservations(tree, monkeypatch, capsys):
    # Isolate aggregation with a synthetic checked-summary return value. This is
    # not a replacement receipt, and no original diagnostic row is modified.
    checked = report.checked_diagnostic
    def with_unknown(name, receipt):
        result = checked(name, receipt)
        if name == DIAGNOSTIC:
            result.update(unknown_calls=1, unknown_reservation=1234)
        return result
    monkeypatch.setattr(report, 'checked_diagnostic', with_unknown)
    report.main()
    capsys.readouterr()
    totals = read(base(tree) / 'results.json')['totals']
    assert totals['unknown_calls'] == 3 and totals['unknown_reservation'] == 10343
    assert totals['token_allowance_including_unknown_reservations'] == 377138


@pytest.mark.parametrize('mutation', ['budget', 'elapsed', 'qualified', 'complete',
                                      'episodes', 'correct'])
def test_attempt_replay_metadata_must_match_the_reported_manifest_and_raw(tree, mutation):
    path = base(tree) / (ATTEMPT + '-replay.json')
    receipt = read(path)
    if mutation == 'budget':
        receipt['total_budget']['total_tokens'] -= 1
    elif mutation == 'elapsed':
        receipt['elapsed_seconds'] = 0
    elif mutation == 'qualified':
        receipt['warm_qualified'] = True
    elif mutation == 'complete':
        receipt['required_records_complete'] = True
    elif mutation == 'episodes':
        receipt['counts']['episodes'] += 1
    else:
        receipt['counts']['correct_episodes'] -= 1
    write(path, receipt)
    with pytest.raises(ValueError):
        report.checked_attempt(ATTEMPT, FREEZE)
