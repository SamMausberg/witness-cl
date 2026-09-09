"""Small synthetic report-consumer mutations, not execution or replay evidence.

No model, SQLite episode, real pilot mutation, or heldout construction is used.
These deliberately simulated receipts exercise the report's fail-closed gates;
only the independent auditor can supply a real run's replay receipt.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / 'tools/v8_results.py'
SPEC = importlib.util.spec_from_file_location('v8_descriptive_report', SOURCE)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def read(path):
    return json.loads(path.read_text())


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, allow_nan=False) + '\n')


def traces(arm):
    result = []
    for phase, index in report.SCHEDULE:
        snapshot = {'memory_bytes': 100, 'peak_memory_bytes': 400,
                    'active_memory_bytes': 60}
        result.append({
            'seed': 90000, 'condition': 'reuse', 'arm': arm,
            'phase': phase, 'episode_index': index, 'status': 'completed',
            'answer': 1, 'reward': 1.0, 'select_attempts': 1,
            'queries': [{'attempt': 1, 'sql': 'SELECT 1', 'error': None}],
            'actions': [{'action': 'QUERY'}, {'action': 'ANSWER'}],
            'model_calls': [{'status': 'completed', 'generation_attempted': True,
                             'usage': {'prompt_tokens': 10, 'completion_tokens': 2,
                                       'total_tokens': 12},
                             'tokenization_seconds': .05, 'inference_seconds': .15}],
            'query_seconds': .01, 'elapsed_seconds': .3,
            'memory_bytes': 100, 'memory_snapshot': snapshot,
        })
    return result


def raw_path(root, arm='full_history'):
    return root / 'artifacts/v8/development' / f'90000-reuse-{arm}.jsonl'


def rewrite_raw(root, entries, arm='full_history'):
    raw_path(root, arm).write_text(''.join(json.dumps(t, allow_nan=False) + '\n' for t in entries))


def refresh_receipt_hashes(root):
    """Simulate freshly bound hashes to exercise independent content checks."""
    study = root / 'artifacts/v8/development'
    manifest = read(study / 'manifest.json')
    manifest['raw_sha256'] = {p.name: report.sha(p) for p in study.glob('*.jsonl')}
    write(study / 'manifest.json', manifest)
    audit_path = root / 'artifacts/v8/development-replay.json'
    audit, = read(audit_path)
    audit.update(raw_sha256=manifest['raw_sha256'],
                 manifest_sha256=report.sha(study / 'manifest.json'),
                 summary_sha256=report.sha(study / 'summary.json'))
    write(audit_path, [audit])


@pytest.fixture
def verified_fixture(tmp_path):
    root = tmp_path / 'consumer-only-fixture'
    study = root / 'artifacts/v8/development'
    study.mkdir(parents=True)
    for name in report.SOURCE_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Synthetic hashed input for report consumer tests only.\n')
    auditor = root / 'experiments/audit_sql_abstractions_v8.py'
    auditor.write_text('Synthetic auditor identity; never executed.\n')
    provenance = root / 'artifacts/v8/model-provenance.json'
    write(provenance, {'kind': 'synthetic consumer-only fixture, no inference'})
    source_map = {name: report.sha(root / name) for name in report.SOURCE_FILES}
    freeze_path = root / 'artifacts/v8/prepilot-freeze.json'
    write(freeze_path, {'source_sha256': source_map,
                        'model_provenance_sha256': report.sha(provenance)})
    summary = []
    for arm in report.LABELS:
        entries = traces(arm)
        rewrite_raw(root, entries, arm)
        summary.append({'seed': 90000, 'condition': 'reuse', 'arm': arm,
                        'phase_counts': report.PHASE_COUNTS,
                        'memory': entries[-1]['memory_snapshot'],
                        'ordinary_budget': {'unknown_usage_calls': 0},
                        'panel_budget': {'unknown_usage_calls': 0}})
    write(study / 'summary.json', summary)
    raw_map = {p.name: report.sha(p) for p in study.glob('*.jsonl')}
    manifest = {'status': 'completed', 'source_unchanged': True,
                'required_records_complete': True, 'source_sha256': source_map,
                'seeds': [90000], 'conditions': ['reuse'], 'arms': list(report.LABELS),
                'raw_sha256': raw_map, 'completed_episode_records': 288,
                'elapsed_seconds': 100.0}
    write(study / 'manifest.json', manifest)
    audit = {'status': 'passed', 'manifest_status': 'completed',
             'pilot_completeness': 'complete', 'resource_comparison_complete': True,
             'planned_records_complete': True, 'required_records_complete': True,
             'known_usage_complete': True, 'sqlite_outcomes_complete': True,
             'full_six_arm_grid': True, 'wall_cap_respected': True,
             'failures': [], 'protocol_issues': [], 'checked': {},
             'checked_source_sha256': source_map, 'raw_sha256': raw_map,
             'manifest_sha256': report.sha(study / 'manifest.json'),
             'summary_sha256': report.sha(study / 'summary.json'),
             'checked_freeze_sha256': report.sha(freeze_path),
             'checked_model_provenance_sha256': report.sha(provenance),
             'auditor_source_sha256': report.sha(auditor)}
    write(root / 'artifacts/v8/development-replay.json', [audit])
    return root


def test_bound_fixture_counts_usage_and_snapshot_storage_peak(verified_fixture):
    manifest, audit, rows = report.load_verified(verified_fixture)
    records = report.summarize(rows)
    assert len(records) == 6
    for record in records:
        assert record['selects'] == record['model_calls'] == record['tokenization_calls'] == 48
        assert record['prompt_tokens'] == 480 and record['completion_tokens'] == 96
        assert record['model_seconds'] == pytest.approx(9.6)
        assert record['query_seconds'] == pytest.approx(.48)
        assert record['peak_memory_bytes'] == 400  # Historical snapshot peak, not current 100.
        assert record['last_memory_bytes'] == 100 and record['peak_active_memory_bytes'] == 60
        assert all(p['correct'] == p['n'] == 8 for p in record['phases'].values())
    assert not (verified_fixture / 'artifacts/v8/results.json').exists()


@pytest.mark.parametrize('relative', [
    'artifacts/v8/development/manifest.json',
    'artifacts/v8/development/summary.json',
    'artifacts/v8/prepilot-freeze.json',
    'experiments/audit_sql_abstractions_v8.py',
    'artifacts/v8/model-provenance.json',
    'src/witness_cl/sql_env_v8.py',
])
def test_stale_receipt_inputs_are_rejected(verified_fixture, relative):
    # Only temporary synthetic files are edited, never frozen real inputs.
    path = verified_fixture / relative
    path.write_text(path.read_text() + '\n')
    with pytest.raises(ValueError, match='stale audit|changed executed source'):
        report.load_verified(verified_fixture)


def test_changed_raw_and_raw_file_set_require_new_replay(verified_fixture):
    path = raw_path(verified_fixture)
    original = path.read_text()
    path.write_text(original.replace('"reward": 1.0', '"reward": 0.0', 1))
    with pytest.raises(ValueError, match='raw records changed'):
        report.load_verified(verified_fixture)
    path.write_text(original)
    path.with_name('unexpected.jsonl').write_text('{}\n')
    with pytest.raises(ValueError, match='raw file/hash/name grid'):
        report.load_verified(verified_fixture)


@pytest.mark.parametrize('mutate', [
    lambda a: a.update(resource_comparison_complete=False),
    lambda a: a.update(resource_comparison_complete='true'),
    lambda a: a.update(known_usage_complete=False),
    lambda a: a.update(pilot_completeness='partial'),
    lambda a: a.update(required_records_complete=False),
    lambda a: a['checked'].update(unknown_usage_calls=1),
    lambda a: a['checked'].update(test_double_calls=1),
    lambda a: a.update(protocol_issues=['unverified timing']),
])
def test_unknown_partial_or_unverified_replay_cannot_authorize_report(verified_fixture, mutate):
    path = verified_fixture / 'artifacts/v8/development-replay.json'
    audit, = read(path)
    mutate(audit)
    write(path, [audit])
    with pytest.raises(ValueError):
        report.load_verified(verified_fixture)


@pytest.mark.parametrize('mutation,error', [
    ('unknown_usage', 'unknown generation usage'),
    ('missing', 'complete eight-item phases'),
    ('duplicate', 'phase grid'),
    ('unknown_phase', 'phase grid'),
    ('mixed_arm', 'another run'),
    ('resource_stop', 'resource-stopped episode'),
])
def test_freshly_hashed_raw_still_rejects_unknown_or_incomplete_records(verified_fixture, mutation, error):
    entries = [json.loads(line) for line in raw_path(verified_fixture).read_text().splitlines()]
    if mutation == 'unknown_usage':
        entries[0]['model_calls'][0]['usage'] = None
    elif mutation == 'missing':
        entries.pop()
    elif mutation == 'duplicate':
        entries[1]['episode_index'] = entries[0]['episode_index']
    elif mutation == 'unknown_phase':
        entries[0]['phase'] = 'future'
    elif mutation == 'mixed_arm':
        entries[1]['arm'] = 'stateless'
    else:
        entries[0]['status'] = 'resource_stop'
    rewrite_raw(verified_fixture, entries)
    refresh_receipt_hashes(verified_fixture)
    with pytest.raises(ValueError, match=error):
        report.load_verified(verified_fixture)


def test_missing_source_map_and_unknown_summary_usage_are_rejected(verified_fixture):
    path = verified_fixture / 'artifacts/v8/development-replay.json'
    audit, = read(path)
    original = deepcopy(audit)
    audit['checked_source_sha256'].pop(next(iter(audit['checked_source_sha256'])))
    write(path, [audit])
    with pytest.raises(ValueError, match='frozen source hash maps'):
        report.load_verified(verified_fixture)
    write(path, [original])
    summary_path = verified_fixture / 'artifacts/v8/development/summary.json'
    summary = read(summary_path)
    summary[0]['panel_budget']['unknown_usage_calls'] = 1
    write(summary_path, summary)
    refresh_receipt_hashes(verified_fixture)
    with pytest.raises(ValueError, match='summary contains unknown usage'):
        report.load_verified(verified_fixture)


def test_summary_refuses_unknown_usage_even_without_loader():
    rows = {arm: traces(arm) for arm in report.LABELS}
    rows['full_history'][0]['model_calls'][0]['usage'] = None
    with pytest.raises(ValueError, match='unknown generation usage'):
        report.summarize(rows)


def test_preflight_only_budget_stop_counts_tokenization_time_but_not_invented_tokens():
    rows = {arm: traces(arm) for arm in report.LABELS}
    rows['full_history'][0]['model_calls'].append({
        'generation_attempted': False, 'status': 'preflight_failed',
        'error_type': 'BudgetStop', 'usage': None, 'tokenization_seconds': .25,
    })
    result = report.summarize(rows)[0]
    assert result['model_calls'] == 48 and result['tokenization_calls'] == 49
    assert result['preflight_only_calls'] == 1
    assert result['prompt_tokens'] == 480 and result['completion_tokens'] == 96
    assert result['model_seconds'] == pytest.approx(9.85)
