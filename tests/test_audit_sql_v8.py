"""Offline pilot/replay mutation tests. No model server, inference or holdout."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import experiments.audit_sql_abstractions_v8 as audit
import experiments.sql_abstractions_v8 as harness
from witness_cl.memory_v8 import ARMS, canonical
from witness_cl.model_v8 import BudgetStop


def latest_public_and_tools(messages):
    start = None
    public = None
    for i, message in enumerate(messages):
        if message['role'] != 'user':
            continue
        try:
            value = json.loads(message['content'])
        except ValueError:
            continue
        if type(value) is dict and 'question' in value and 'schema' in value:
            public, start = value, i
    assert public is not None
    tools = []
    for message in messages[start + 1:]:
        if message['role'] == 'user':
            try:
                value = json.loads(message['content'])
            except ValueError:
                continue
            if 'tool_result' in value:
                tools.append(value['tool_result'])
    return public, tools


def gross_relation(result):
    # Names, units and null semantics come only from a returned catalog SELECT.
    rows = [dict(zip(result['columns'], row)) for row in result['rows']]
    amount = next(r for r in rows if r['description'].startswith('Unit amount is stored in '))
    quantity = next(r for r in rows if r['description'].startswith('Positive integer quantity'))
    column = '"' + amount['column_name'] + '"'
    if 'NULL unit amount means zero' in amount['description']:
        column = f'COALESCE({column},0)'
    sql = f'SELECT {column}/:divisor * "{quantity["column_name"]}" AS gross FROM "{amount["table_name"]}"'
    return sql, {'divisor': 100.0 if 'integer cents' in amount['description'] else 1.0}


class OfflineClient:
    """Persisted mock receipts, explicitly flagged as non-inference test data."""
    model = 'witness-v8-qwen3-4b-q8'
    context_tokens = 32768

    def __init__(self, *, generalized=False, failure=None):
        self.generalized = generalized
        self.failure = failure

    def complete(self, messages, budget, *, phase, records, output_tokens, response_schema=None):
        if self.failure == 'wall' or self.failure == 'reflection_wall' and phase.endswith(':reflection'):
            raise BudgetStop('wall_time_ceiling')
        if self.failure == 'context':
            records.append({'messages': deepcopy(messages), 'phase': phase,
                            'preflight_tokens': self.context_tokens, 'max_output_tokens': output_tokens,
                            'tokenization_seconds': 0., 'generation_attempted': False, 'usage': None,
                            'response_schema': deepcopy(response_schema), 'status': 'preflight_failed',
                            'error_type': 'BudgetStop', 'stop_reason': 'full_context_ceiling_no_truncation',
                            'test_double': True})
            raise BudgetStop('full_context_ceiling_no_truncation')
        budget.check(7, output_tokens)
        frozen = deepcopy(messages)
        record = {'messages': frozen, 'phase': phase, 'preflight_tokens': 7,
                  'max_output_tokens': output_tokens, 'tokenization_seconds': 0.,
                  'inference_seconds': 0., 'generation_attempted': True,
                  'response_schema': deepcopy(response_schema), 'response_model': self.model,
                  'test_double': True}
        records.append(record)
        budget.calls += 1
        if self.failure == 'unknown_usage':
            budget.unknown_usage_calls += 1
            record.update(status='failed', usage=None, error_type='RuntimeError')
            record.pop('response_model')
            raise RuntimeError('simulated lost response; usage unknown')
        budget.prompt_tokens += 7
        budget.completion_tokens += 3
        budget.total_tokens += 10
        if phase.endswith(':reflection'):
            payload = json.loads(messages[1]['content'])
            if 'prior_insights' in payload:
                result = {'insights': ['Literal SELECT results are observations, not future task answers.']}
            elif self.generalized:
                sql, params = gross_relation(payload['queries'][0])
                aggregate = 'AVG' if 'average gross' in payload['question'] else 'SUM'
                result = {'proposal': {'source_index': 1, 'guard_index': 0,
                                       'sql': sql, 'params': params,
                                       'outer_sql': f'SELECT {aggregate}(gross) AS answer FROM reused',
                                       'outer_params': {},
                                       'description': 'Per-order dollar gross; catalog determines units and null interpretation.'}}
            else:
                result = {'proposal': None}
        else:
            public, tools = latest_public_and_tools(frozen)
            if self.generalized and 'total gross order value?' in public['question']:
                if not tools:
                    result = {'action': 'QUERY', 'sql': 'SELECT * FROM catalog', 'params': {}}
                elif len(tools) == 1:
                    sql, params = gross_relation(tools[0])
                    result = {'action': 'QUERY', 'sql': 'SELECT SUM(gross) AS answer FROM (' + sql + ')', 'params': params}
                else:
                    result = {'action': 'ANSWER', 'value': tools[-1]['rows'][0][0]}
            elif self.generalized and 'average gross order value?' in public['question']:
                if not tools:
                    visible = next(m['content'] for m in frozen if m['content'].startswith('Learned executable memories'))
                    entry = json.loads(visible.split('\n', 1)[1])[0]
                    result = {'action': 'COMPOSE', 'entry': 0, 'params': entry['witness_params'],
                              'outer_sql': 'SELECT AVG(gross) AS answer FROM reused', 'outer_params': {}}
                else:
                    result = {'action': 'ANSWER', 'value': tools[-1]['rows'][0][0]}
            elif not tools:
                result = {'action': 'QUERY', 'sql': 'SELECT 1 AS observed', 'params': {}}
            else:
                result = {'action': 'ANSWER', 'value': tools[-1]['rows'][0][0]}
        content = canonical(result)
        record.update(status='completed', content=content, finish_reason='stop',
                      usage={'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10})
        return content


@pytest.fixture(scope='module')
def pilot_artifacts(tmp_path_factory):
    root = tmp_path_factory.mktemp('sql-audit-v8')
    partial = root / 'partial'
    generalized = root / 'generalized'
    complete = root / 'complete'
    unknown = root / 'unknown'
    exhausted = root / 'exhausted'
    assert harness.run_pilot(partial, OfflineClient(), stop_after=4)['status'] == 'stopped'
    assert harness.run_pilot(generalized, OfflineClient(generalized=True),
                             arms=('fragments',), stop_after=2)['status'] == 'stopped'
    assert harness.run_pilot(complete, OfflineClient())['status'] == 'completed'
    assert harness.run_pilot(unknown, OfflineClient(failure='unknown_usage'))['status'] == 'failed'
    assert harness.run_pilot(exhausted, OfflineClient(failure='context'),
                             arms=('stateless',))['status'] == 'incomplete'
    return dict(root=root, partial=partial, generalized=generalized, complete=complete,
                unknown=unknown, exhausted=exhausted)


def clone(pilot_artifacts, name, tmp_path):
    out = tmp_path / name
    shutil.copytree(pilot_artifacts[name], out)
    return out


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def edit_records(directory, mutate, *, filename=None, refresh_hash=True):
    path = directory / filename if filename else sorted(directory.glob('*.jsonl'))[0]
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    mutate(rows)
    path.write_text(''.join(canonical(row) + '\n' for row in rows))
    if refresh_hash:
        manifest = read(directory / 'manifest.json')
        manifest['raw_sha256'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        write(directory / 'manifest.json', manifest)
    return path


def assert_failed(report, fragment):
    assert report['status'] == 'failed', report
    assert any(fragment in row['message'] for row in report['failures']), report


def test_partial_pilot_has_valid_replay_without_becoming_a_complete_comparison(pilot_artifacts):
    report = audit.audit_directory(pilot_artifacts['partial'])
    assert report['status'] == 'passed', report
    assert report['pilot_completeness'] == 'partial'
    assert not report['planned_records_complete']
    assert not report['required_records_complete']
    assert not report['resource_comparison_complete'] and not report['claim_confirmed']
    assert report['known_usage_complete'] and report['sqlite_outcomes_complete']
    assert report['checked']['episodes'] == 4
    assert report['checked']['select_attempts'] == 4
    assert report['checked']['test_double_calls'] >= 8


def test_generalized_relation_reconstruction_and_new_composition_replay(pilot_artifacts):
    report = audit.audit_directory(pilot_artifacts['generalized'])
    assert report['status'] == 'passed', report
    assert report['checked']['correct_episodes'] == 2
    assert report['checked']['accepted_reconstruction_witnesses'] == 2
    assert report['checked']['reconstruction_selects'] == 2
    assert report['checked']['executed_compositions'] == 1
    assert report['checked']['select_attempts'] == 6
    assert report['pilot_completeness'] == 'partial'


def test_complete_planned_grid_and_all_summaries_are_verified_without_claiming_inference(pilot_artifacts):
    report = audit.audit_directory(pilot_artifacts['complete'])
    assert report['status'] == 'passed', report
    assert report['pilot_completeness'] == 'complete'
    assert report['planned_records_complete'] and report['required_records_complete']
    assert report['full_six_arm_grid']
    assert report['checked']['episodes'] == 288
    assert report['checked']['select_attempts'] == 288
    assert report['independent_reference_cases'] == 48
    assert not report['resource_comparison_complete']  # Explicit mock receipts.
    assert not report['claim_confirmed']


def test_unknown_usage_failure_remains_unknown_and_partial(pilot_artifacts):
    report = audit.audit_directory(pilot_artifacts['unknown'])
    assert report['status'] == 'passed', report
    assert report['pilot_completeness'] == 'partial'
    assert report['checked']['unknown_usage_calls'] == 1
    assert report['checked']['runtime_failed_episodes'] == 1
    assert not report['known_usage_complete']
    assert not report['resource_comparison_complete']


def test_resource_exhaustion_cannot_be_labeled_completed(pilot_artifacts):
    manifest = read(pilot_artifacts['exhausted'] / 'manifest.json')
    assert manifest['status'] == 'incomplete' and manifest['required_records_complete'] is False
    report = audit.audit_directory(pilot_artifacts['exhausted'])
    assert report['status'] == 'passed', report
    assert report['pilot_completeness'] == 'partial'
    assert report['checked']['resource_stopped_episodes'] == 25
    assert not report['required_records_complete']


@pytest.mark.parametrize('seeds', [(81000,), (89999,), (90004,), (True,), (90000, 90000), ()])
def test_pilot_rejects_holdout_or_undeclared_seed_before_creating_artifacts(tmp_path, seeds):
    path = tmp_path / 'rejected'
    with pytest.raises(ValueError):
        harness.run_pilot(path, OfflineClient(), seeds=seeds)
    assert not path.exists()


def test_source_change_marks_pilot_invalidated_and_replay_rejects_it(tmp_path, monkeypatch):
    actual = harness.source_hashes
    calls = 0

    def changed_source():
        nonlocal calls
        calls += 1
        result = actual()
        if calls > 1:
            result[next(iter(result))] = '0' * 64
        return result

    monkeypatch.setattr(harness, 'source_hashes', changed_source)
    path = tmp_path / 'invalidated'
    manifest = harness.run_pilot(path, OfflineClient(), arms=('stateless',), stop_after=1)
    assert manifest['status'] == 'invalidated'
    assert manifest['source_unchanged'] is False
    assert_failed(audit.audit_directory(path), 'source was changed')


def test_raw_hash_tampering_is_rejected_before_replay(pilot_artifacts, tmp_path):
    path = clone(pilot_artifacts, 'partial', tmp_path)
    edit_records(path, lambda rows: rows[0].update(answer=99), refresh_hash=False)
    assert_failed(audit.audit_directory(path), 'raw digest mismatch')


@pytest.mark.parametrize('mutate,reason', [
    (lambda r: r['queries'][0]['rows'][0].__setitem__(0, 999), 'SQLite result'),
    (lambda r: r['queries'][0].update(attempt=2), 'attempts'),
    (lambda r: r['queries'][0].update(attempt=True), 'exact integer'),
    (lambda r: r.update(select_attempts=True), 'exact integer'),
    (lambda r: r['model_calls'][0].update(inference_seconds=999), 'setup/query/model time'),
    (lambda r: r['queries'][0].update(learning_check=True), 'learning-check'),
    (lambda r: r['queries'][0].update(sql='SELECT 2 AS observed'), 'compiled model action'),
    (lambda r: r['queries'][0].update(hidden_task_id='leak'), 'covert extra fields'),
    (lambda r: r.update(answer=99), 'returned model ANSWER'),
    (lambda r: r.update(reward=1.), 'correctness feedback'),
    (lambda r: r.update(select_attempts=0), 'SELECT total'),
    (lambda r: r['model_calls'][0].update(response_model='different-backbone'), 'model alias'),
    (lambda r: r['model_calls'][0]['usage'].update(total_tokens=11), 'usage sum'),
    (lambda r: r['model_calls'][0].update(preflight_tokens=8), 'token/context limits'),
    (lambda r: r['model_calls'][0].update(max_output_tokens=385), 'output cap'),
    (lambda r: r['model_calls'][0].update(response_schema=None), 'response schema'),
    (lambda r: r['model_calls'][1]['messages'].append({'role': 'user', 'content': 'secret evaluator answer'}), 'legal own-history'),
])
def test_recomputed_raw_hash_does_not_hide_semantic_or_protocol_tampering(pilot_artifacts, tmp_path, mutate, reason):
    path = clone(pilot_artifacts, 'partial', tmp_path)
    edit_records(path, lambda rows: mutate(rows[0]))
    assert_failed(audit.audit_directory(path), reason)


def test_proposal_reflection_cannot_see_future_validation_result(pilot_artifacts, tmp_path):
    path = clone(pilot_artifacts, 'generalized', tmp_path)

    def mutate(rows):
        record = rows[0]['model_calls'][-1]
        payload = json.loads(record['messages'][1]['content'])
        payload['queries'].append(deepcopy(rows[0]['queries'][-1]))
        record['messages'][1]['content'] = canonical(payload)

    edit_records(path, mutate)
    assert_failed(audit.audit_directory(path), 'legal own-history')


def test_admitted_relation_and_reconstruction_cannot_be_forged(pilot_artifacts, tmp_path):
    path = clone(pilot_artifacts, 'generalized', tmp_path)
    edit_records(path, lambda rows: rows[0]['abstraction_proposal'].update(fragment_digest='0' * 64))
    assert_failed(audit.audit_directory(path), 'proposal/admission')


def test_cross_episode_entry_provenance_cannot_be_invented(pilot_artifacts, tmp_path):
    path = clone(pilot_artifacts, 'generalized', tmp_path)
    edit_records(path, lambda rows: rows[1]['retrieved_provenance'].__setitem__(0, '0' * 64))
    assert_failed(audit.audit_directory(path), 'evidence provenance')


def test_reconstruction_result_tampering_fails_independent_sqlite(pilot_artifacts, tmp_path):
    path = clone(pilot_artifacts, 'generalized', tmp_path)
    edit_records(path, lambda rows: rows[0]['queries'][-1]['rows'][0].__setitem__(0, 999))
    assert_failed(audit.audit_directory(path), 'SQLite result')


def test_missing_or_reordered_phase_is_not_a_valid_partial_prefix(pilot_artifacts, tmp_path):
    path = clone(pilot_artifacts, 'generalized', tmp_path)
    edit_records(path, lambda rows: rows[1].update(episode_index=2))
    assert_failed(audit.audit_directory(path), 'phase grid')


def test_partial_grid_cannot_claim_complete_and_summary_totals_cannot_drift(pilot_artifacts, tmp_path):
    path = clone(pilot_artifacts, 'partial', tmp_path)
    manifest = read(path / 'manifest.json')
    manifest.update(status='completed', required_records_complete=True)
    write(path / 'manifest.json', manifest)
    assert_failed(audit.audit_directory(path), 'completeness claim')
    manifest.update(status='stopped', required_records_complete=False)
    write(path / 'manifest.json', manifest)
    summary = read(path / 'summary.json')
    summary[0]['ordinary_budget']['total_tokens'] += 1
    write(path / 'summary.json', summary)
    assert_failed(audit.audit_directory(path), 'budget counter')


def test_current_source_map_and_external_freeze_are_bound(pilot_artifacts, tmp_path):
    path = clone(pilot_artifacts, 'partial', tmp_path)
    manifest = read(path / 'manifest.json')
    freeze = tmp_path / 'freeze.json'
    write(freeze, {k: manifest[k] for k in ('source_sha256', 'seeds', 'conditions', 'arms', 'model', 'context_tokens')})
    report = audit.audit_directory(path, freeze_path=freeze)
    assert report['status'] == 'passed', report
    assert report['checked_freeze_sha256'] == hashlib.sha256(freeze.read_bytes()).hexdigest()
    bad_freeze = read(freeze)
    bad_freeze['model'] = 'changed'
    write(freeze, bad_freeze)
    assert_failed(audit.audit_directory(path, freeze_path=freeze), 'external freeze')
    manifest['source_sha256']['src/witness_cl/fragments_v8.py'] = '0' * 64
    write(path / 'manifest.json', manifest)
    assert_failed(audit.audit_directory(path), 'frozen source drift')


def test_extra_raw_files_and_duplicate_json_keys_are_rejected(pilot_artifacts, tmp_path):
    path = clone(pilot_artifacts, 'partial', tmp_path)
    (path / 'foreign.jsonl').write_text('{}\n')
    assert_failed(audit.audit_directory(path), 'file/hash/name grid')
    (path / 'foreign.jsonl').unlink()
    manifest_path = path / 'manifest.json'
    manifest_path.write_text(manifest_path.read_text().replace('"version": 8', '"version": 8, "version": 8', 1))
    assert_failed(audit.audit_directory(path), 'duplicate JSON key')


def test_elapsed_overrun_cannot_qualify_for_a_resource_comparison(pilot_artifacts, tmp_path):
    path = clone(pilot_artifacts, 'complete', tmp_path)
    manifest = read(path / 'manifest.json')
    manifest['elapsed_seconds'] = manifest['wall_seconds_cap'] + 1
    write(path / 'manifest.json', manifest)
    report = audit.audit_directory(path)
    assert report['status'] == 'passed', report  # Honest saved overspend, not a valid cap claim.
    assert report['wall_cap_respected'] is False
    assert 'recorded pilot elapsed time exceeds declared wall ceiling' in report['protocol_issues']
    assert report['resource_comparison_complete'] is False


@pytest.mark.parametrize('failure,arms', [('wall', ('stateless',)), ('reflection_wall', ('insights',))])
def test_scheduled_records_cannot_continue_after_a_claimed_global_wall_stop(tmp_path, failure, arms):
    path = tmp_path / 'impossible-wall-schedule'
    # This deliberately dishonest clock stub claims wall exhaustion while the
    # runner's real global deadline still permits subsequent episodes.
    harness.run_pilot(path, OfflineClient(failure=failure), arms=arms, stop_after=2)
    assert_failed(audit.audit_directory(path), 'reported global wall stop')


def test_actual_prepilot_source_receipt_format_is_supported(pilot_artifacts):
    freeze = Path(__file__).resolve().parents[1] / 'artifacts/v8/prepilot-freeze.json'
    report = audit.audit_directory(pilot_artifacts['partial'], freeze_path=freeze)
    assert report['status'] == 'passed', report
    assert report['checked_freeze_sha256'] == hashlib.sha256(freeze.read_bytes()).hexdigest()
    assert report['checked_model_provenance_sha256'] == read(freeze)['model_provenance_sha256']
