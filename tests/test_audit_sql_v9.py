"""Bounded offline replay mutations. All receipts remain explicit test doubles.

These temporary artifacts validate the auditor; they are not model evidence or
eligible resource comparisons. No model server, heldout fixture, or pilot source
is modified by this file.
"""
from copy import deepcopy
from dataclasses import replace
import contextlib
import io
import hashlib
import json
from pathlib import Path
import shutil
import time

import pytest

import experiments.audit_sql_abstractions_v9 as audit
import experiments.sql_abstractions_v9 as harness
from witness_cl.memory_v8 import canonical
from witness_cl.model_v9 import DecodingV9, LocalInferenceV9
from test_audit_sql_v8 import OfflineClient, latest_public_and_tools


class OfflineClientV9(OfflineClient):
    model = 'explicit-v9-offline-test-double'
    context_tokens = 65536
    max_output = 4096
    endpoint = 'http://127.0.0.1:1'
    timeout = 1.
    response_mode = 'schema'
    decoding = DecodingV9(temperature=.6, top_p=.95, top_k=20, presence_penalty=1.5, thinking=True)

    def complete(self, messages, budget, **kwargs):
        content = super().complete(messages, budget, **kwargs)
        action = json.loads(content)
        if action.get('action') == 'QUERY' and action.get('sql') == 'SELECT 1 AS observed':
            action['sql'] = 'SELECT :value AS observed; -- ordinary SQLite comment'
            action['params'] = {'value': 1, 'unused': 'accepted literal binding'}
            content = canonical(action)
            kwargs['records'][-1]['content'] = content
        return content


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def freeze(directory):
    manifest = read(directory / 'manifest.json')
    fields = ('source_sha256', 'client_config', 'system_prompt_sha256', 'limits',
              'seeds', 'conditions', 'arms', 'stage', 'minimum_warm_correct', 'gate_after_warm')
    path = directory / 'test-freeze.json'
    write(path, {key: manifest[key] for key in fields})
    return path


@pytest.fixture(scope='module')
def artifacts(tmp_path_factory):
    root = tmp_path_factory.mktemp('v9-auditor-offline')
    configs = {
        'qualification': {'arms': ('full_history', 'insights', 'stateless')},
        'full': {'stage': 'full', 'arms': ('fragments',), 'gate_after_warm': False},
        'gated': {'stage': 'full', 'arms': ('full_history',)},
        'stopped': {'arms': ('stateless',), 'stop_after': 2},
    }
    expected = {'qualification': 'completed', 'full': 'completed',
                'gated': 'competence_gate_failed', 'stopped': 'stopped'}
    paths = {}
    for name, config in configs.items():
        directory = root / name
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = harness.run_study(directory, OfflineClientV9(generalized=name == 'full'),
                                          seeds=(92001,), **config)
        assert manifest['status'] == expected[name], manifest
        assert manifest['contains_test_double_calls'] is True
        assert manifest['claim_confirmed'] is False and manifest['warm_qualified'] is False
        freeze(directory)
        paths[name] = directory
    return paths


def clone(artifacts, name, tmp_path):
    target = tmp_path / name
    shutil.copytree(artifacts[name], target)
    return target


def report(directory):
    return audit.audit_directory(directory, freeze_path=directory / 'test-freeze.json')


def records(directory, filename=None):
    path = directory / filename if filename else sorted(directory.glob('*.jsonl'))[0]
    return path, [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def edit_records(directory, mutate, filename=None):
    path, rows = records(directory, filename)
    mutate(rows)
    path.write_text(''.join(canonical(row) + '\n' for row in rows), encoding='utf-8')
    manifest = read(directory / 'manifest.json')
    manifest['raw_sha256'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    write(directory / 'manifest.json', manifest)


def edit_summary(directory, mutate):
    path = directory / 'summary.json'
    summary = read(path)
    mutate(summary)
    write(path, summary)
    manifest = read(directory / 'manifest.json')
    manifest['summary_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    write(directory / 'manifest.json', manifest)


def assert_rejected(directory):
    result = report(directory)
    assert result['status'] == 'failed', result
    assert result['failures'], result
    assert result['resource_comparison_complete'] is False
    assert result['claim_confirmed'] is False


@pytest.mark.parametrize('name,complete', [('qualification', True), ('full', True),
                                           ('gated', False), ('stopped', False)])
def test_valid_offline_artifacts_replay_without_becoming_real_comparisons(artifacts, name, complete):
    result = report(artifacts[name])
    assert result['status'] == 'passed', result
    assert result['required_records_complete'] is complete
    assert result['pilot_completeness'] == ('complete' if complete else 'partial')
    assert result['known_usage_complete'] is True
    assert result['resource_comparison_complete'] is False and result['claim_confirmed'] is False
    _, rows = records(artifacts[name])
    if name == 'full':
        assert any(row.get('abstraction_proposal', {}).get('status') == 'accepted' for row in rows)
        assert any(query['purpose'] == 'fragment_composition' for row in rows for query in row['queries'])
    if name == 'qualification':
        assert any(query['sql'].endswith('-- ordinary SQLite comment') and 'unused' in query['params']
                   for row in rows for query in row['queries'])


def test_evaluator_extra_message_cannot_enter_an_otherwise_valid_prompt(artifacts, tmp_path):
    directory = clone(artifacts, 'qualification', tmp_path)
    edit_records(directory, lambda rows: rows[0]['model_calls'][0]['messages'].append(
        {'role': 'user', 'content': 'Private evaluator canary: gold answer 77123; future seed 92002.'}))
    assert_rejected(directory)


def test_shared_ledger_cannot_understate_known_call_usage(artifacts, tmp_path):
    directory = clone(artifacts, 'qualification', tmp_path)
    manifest = read(directory / 'manifest.json')
    manifest['total_budget']['total_tokens'] -= 1
    write(directory / 'manifest.json', manifest)
    assert_rejected(directory)


def test_local_ledger_is_checked_even_after_summary_hash_is_refreshed(artifacts, tmp_path):
    directory = clone(artifacts, 'qualification', tmp_path)
    edit_summary(directory, lambda rows: rows[0]['ordinary_budget'].__setitem__(
        'calls', rows[0]['ordinary_budget']['calls'] - 1))
    assert_rejected(directory)


def test_reordered_episodes_are_not_a_valid_partial_schedule(artifacts, tmp_path):
    directory = clone(artifacts, 'full', tmp_path)
    def mutate(rows):
        rows[0], rows[1] = rows[1], rows[0]
    edit_records(directory, mutate)
    assert_rejected(directory)


def test_frozen_panel_cannot_replace_learned_memory(artifacts, tmp_path):
    directory = clone(artifacts, 'full', tmp_path)
    def mutate(rows):
        panel = next(row for row in rows if row['phase'] == 'old_before')
        panel['memory_snapshot']['entries'] = []
        panel['after_memory_digest'] = '0' * 64
    edit_records(directory, mutate)
    assert_rejected(directory)


def test_admission_source_index_must_match_own_model_proposal(artifacts, tmp_path):
    directory = clone(artifacts, 'full', tmp_path)
    def mutate(rows):
        accepted = next(row for row in rows if row.get('abstraction_proposal', {}).get('status') == 'accepted')
        accepted['abstraction_proposal']['model_fields']['source_index'] = 0
    edit_records(directory, mutate)
    assert_rejected(directory)


def test_reconstruction_binding_cannot_differ_from_the_verified_request(artifacts, tmp_path):
    directory = clone(artifacts, 'full', tmp_path)
    def mutate(rows):
        checked = next(query for row in rows for query in row['queries']
                       if query['purpose'] == 'abstraction_reconstruction')
        key = next(iter(checked['params']))
        checked['params'][key] += 1
    edit_records(directory, mutate)
    assert_rejected(directory)


def test_proposal_cannot_see_the_later_reconstruction_observation(artifacts, tmp_path):
    directory = clone(artifacts, 'full', tmp_path)
    def mutate(rows):
        accepted = next(row for row in rows if row.get('abstraction_proposal', {}).get('status') == 'accepted')
        reflection = next(call for call in accepted['model_calls'] if call['phase'].endswith(':reflection'))
        payload = json.loads(reflection['messages'][1]['content'])
        payload['queries'].append(deepcopy(accepted['queries'][-1]))
        reflection['messages'][1]['content'] = canonical(payload)
    edit_records(directory, mutate)
    assert_rejected(directory)


def test_retrieved_entry_provenance_cannot_be_forged(artifacts, tmp_path):
    directory = clone(artifacts, 'full', tmp_path)
    def mutate(rows):
        row = next(row for row in rows if row['retrieved_provenance'])
        row['retrieved_provenance'][0] = '0' * 64
    edit_records(directory, mutate)
    assert_rejected(directory)


def test_source_freeze_mismatch_is_rejected(artifacts, tmp_path):
    directory = clone(artifacts, 'qualification', tmp_path)
    manifest = read(directory / 'manifest.json')
    name = next(iter(manifest['source_sha256']))
    manifest['source_sha256'][name] = '0' * 64
    write(directory / 'manifest.json', manifest)
    assert_rejected(directory)


def test_external_prompt_freeze_mismatch_is_rejected(artifacts, tmp_path):
    directory = clone(artifacts, 'qualification', tmp_path)
    path = directory / 'test-freeze.json'
    value = read(path)
    value['system_prompt_sha256'] = '0' * 64
    write(path, value)
    assert_rejected(directory)


def test_equivalent_sql_cannot_replace_the_exact_model_request(artifacts, tmp_path):
    directory = clone(artifacts, 'qualification', tmp_path)
    edit_records(directory, lambda rows: rows[0]['queries'][0].update(sql='SELECT 1 AS observed', params={}))
    assert_rejected(directory)


def test_unknown_usage_cannot_be_reported_as_complete(artifacts, tmp_path):
    directory = clone(artifacts, 'qualification', tmp_path)
    edit_records(directory, lambda rows: rows[0]['model_calls'][0].update(usage=None))
    assert_rejected(directory)


def test_output_cap_cannot_change_for_one_call(artifacts, tmp_path):
    directory = clone(artifacts, 'qualification', tmp_path)
    edit_records(directory, lambda rows: rows[0]['model_calls'][0].update(max_output_tokens=2049))
    assert_rejected(directory)


def test_boolean_feedback_must_match_actual_answer_correctness(artifacts, tmp_path):
    directory = clone(artifacts, 'qualification', tmp_path)
    def mutate(rows):
        row = next(row for row in rows if row['reward'] == 0.)
        row['feedback']['correct'] = True
    edit_records(directory, mutate)
    assert_rejected(directory)


class BodyClientV9(LocalInferenceV9):
    """Use the real request/accounting code with a strictly offline transport."""
    def complete(self, messages, budget, **kwargs):
        records = kwargs['records']
        first = len(records)
        try:
            return super().complete(messages, budget, **kwargs)
        finally:
            for record in records[first:]:
                record['test_double'] = True

    def _post(self, path, body, timeout):
        if path.endswith('/input_tokens'):
            # A tiny measured wait makes the failed preflight's retained time
            # distinct from zero without assuming timer precision.
            time.sleep(.001)
            return {'input_tokens': 10}
        assert path == '/v1/chat/completions'
        _, tools = latest_public_and_tools(body['messages'])
        action = ({'action': 'ANSWER', 'value': tools[-1]['rows'][0][0]} if tools else
                  {'action': 'QUERY', 'sql': 'SELECT :value AS observed; -- exact body',
                   'params': {'value': 1, 'unused': 'literal'}})
        return {'model': self.model,
                'usage': {'prompt_tokens': 10, 'completion_tokens': 3, 'total_tokens': 13},
                'choices': [{'finish_reason': 'stop', 'message': {'content': canonical(action)}}]}


@pytest.fixture(scope='module')
def shaped_artifacts(tmp_path_factory):
    root = tmp_path_factory.mktemp('v9-auditor-effective-body')
    key = root / 'offline-only.key'
    key.write_text('not-a-real-credential', encoding='utf-8')
    paths = {}
    for name, mode, shared_cap in (('schema', 'schema', 3000000), ('json', 'json', 3000000),
                                    ('shared_stop', 'schema', 55)):
        client = BodyClientV9(key_file=key, endpoint='http://127.0.0.1:1',
                              model='explicit-offline-body-test-double', context_tokens=65536,
                              max_output=20, timeout=1., response_mode=mode,
                              decoding=DecodingV9(temperature=.6, top_p=.95, top_k=20,
                                                   presence_penalty=1.5, thinking=True))
        limits = replace(harness.DEFAULT_LIMITS, solve_output_tokens=20,
                         reflection_output_tokens=20, total_tokens=shared_cap)
        directory = root / name
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = harness.run_study(directory, client, seeds=(92001,),
                                          arms=('full_history', 'stateless'), limits=limits)
        assert manifest['status'] == ('stopped' if name == 'shared_stop' else 'completed'), manifest
        assert manifest['contains_test_double_calls'] is True
        freeze(directory)
        paths[name] = directory
    return paths


@pytest.mark.parametrize('mode', ['schema', 'json'])
def test_complete_effective_request_bodies_replay_in_both_response_modes(shaped_artifacts, mode):
    directory = shaped_artifacts[mode]
    result = report(directory)
    assert result['status'] == 'passed', result
    assert result['required_records_complete'] and result['known_usage_complete']
    assert result['resource_comparison_complete'] is False
    _, rows = records(directory)
    for row in rows:
        for call in row['model_calls']:
            assert call['test_double'] is True and call['response_mode'] == mode
            assert call['decoding']['thinking'] is True
            assert call['request_config']['chat_template_kwargs'] == {'enable_thinking': True}
            if mode == 'json':
                assert call['response_schema'] is None
                assert call['request_config']['response_format'] == {'type': 'json_object'}
            else:
                assert call['request_config']['response_format']['schema'] == call['response_schema']


@pytest.mark.parametrize('mutation', ['request_temperature', 'decoding_seed', 'response_mode'])
def test_full_shaped_test_double_cannot_bypass_effective_configuration_checks(shaped_artifacts, tmp_path, mutation):
    directory = clone(shaped_artifacts, 'schema', tmp_path)
    def mutate(rows):
        call = rows[0]['model_calls'][0]
        if mutation == 'request_temperature':
            call['request_config']['temperature'] = .1
        elif mutation == 'decoding_seed':
            call['decoding']['seed'] = 43
        else:
            call['response_mode'] = 'json'
    edit_records(directory, mutate)
    assert_rejected(directory)


def test_json_mode_cannot_silently_add_a_schema_to_the_effective_request(shaped_artifacts, tmp_path):
    directory = clone(shaped_artifacts, 'json', tmp_path)
    edit_records(directory, lambda rows: rows[0]['model_calls'][0]['request_config']['response_format'].update(
        schema=deepcopy(harness.ACTION_SCHEMA)))
    assert_rejected(directory)


def test_shared_preflight_stop_preserves_its_time_and_known_prior_usage(shaped_artifacts):
    directory = shaped_artifacts['shared_stop']
    result = report(directory)
    assert result['status'] == 'passed', result
    assert result['known_usage_complete'] is True and result['required_records_complete'] is False
    assert result['resource_comparison_complete'] is False
    manifest = read(directory / 'manifest.json')
    assert manifest['total_budget']['calls'] == 2 and manifest['total_budget']['total_tokens'] == 26
    _, rows = records(directory, '92001-reuse-stateless.jsonl')
    assert len(rows) == 1 and rows[0]['status'] == 'resource_stop'
    receipt = rows[0]['model_calls'][0]
    assert receipt['generation_attempted'] is False and receipt['usage'] is None
    assert receipt['preflight_tokens'] == 10 and receipt['tokenization_seconds'] >= .001
    summary = read(directory / 'summary.json')
    arm = next(row for row in summary if row['arm'] == 'stateless')
    assert arm['ordinary_budget']['tokenization_seconds'] == receipt['tokenization_seconds']
    assert arm['ordinary_budget']['calls'] == arm['ordinary_budget']['total_tokens'] == 0


def test_a_missing_preflight_cannot_be_disguised_as_an_unrecorded_budget_stop(shaped_artifacts, tmp_path):
    directory = clone(shaped_artifacts, 'shared_stop', tmp_path)
    _, rows = records(directory, '92001-reuse-stateless.jsonl')
    seconds = rows[0]['model_calls'][0]['tokenization_seconds']
    edit_records(directory, lambda rows: rows[0].update(model_calls=[]), filename='92001-reuse-stateless.jsonl')
    def reduce_time(summary):
        row = next(row for row in summary if row['arm'] == 'stateless')
        row['ordinary_budget']['tokenization_seconds'] -= seconds
    edit_summary(directory, reduce_time)
    manifest = read(directory / 'manifest.json')
    manifest['total_budget']['tokenization_seconds'] -= seconds
    write(directory / 'manifest.json', manifest)
    assert_rejected(directory)


@pytest.mark.parametrize('sql,allowed', [
    ('WITH x AS (SELECT 1 AS value) SELECT COUNT(*) FROM x', True),
    ("SELECT COUNT(*) FROM json_each('[1,2]')", False),
    ("WITH unused AS (WITH json_each AS (SELECT 99) SELECT * FROM json_each) SELECT COUNT(*) FROM json_each('[1,2]')", False),
])
def test_independent_replay_authorizes_derived_counts_but_not_virtual_modules(sql, allowed):
    spec = harness.make_stream(92001, 'reuse').ordinary[0]
    database = audit.SQLiteReplayV9(spec)
    try:
        result = database.query(sql, {})
    finally:
        database.close()
    assert (result['error'] is None) is allowed
    if allowed:
        assert result['rows'] == [[1]]


def test_independent_portable_schema_normalization_keeps_all_other_constraints():
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['notes'],
              'properties': {'notes': {'type': 'array', 'maxItems': 16,
                                       'items': {'type': 'string', 'maxLength': 4096}},
                             'small': {'type': 'string', 'minLength': 1, 'maxLength': 512},
                             'edge': {'type': 'string', 'maxLength': 2000},
                             'scalar': {'type': 'number'}}}
    original = deepcopy(schema)
    expected = deepcopy(schema)
    del expected['properties']['notes']['items']['maxLength']
    result = audit.portable_wire_schema(schema)
    assert result == expected and schema == original
    result['required'].append('small')
    assert schema == original


@pytest.mark.parametrize('mutation', [None, 'host', 'wire'])
def test_portable_receipt_checks_original_host_schema_and_actual_wire_schema(tmp_path, monkeypatch, mutation):
    from collections import Counter
    from witness_cl.memory_v9 import reflection_schema_v9
    from witness_cl.model_v8 import InferenceBudget
    from test_model_v9_compatible import client, response

    instance = client(tmp_path)
    schema = reflection_schema_v9('insights')
    messages = [{'role': 'user', 'content': 'Observed evidence for a portable reflection.'}]
    content = canonical({'insights': ['Observed SQL remains scoped evidence.']})
    def fake_post(path, body, timeout):
        return {'input_tokens': 10} if path.endswith('/input_tokens') else response(instance.model, content)
    monkeypatch.setattr(instance, '_post', fake_post)
    records = []
    instance.complete(messages, InferenceBudget(), phase='ordinary:reflection', records=records,
                       output_tokens=256, response_schema=schema)
    record = records[0]
    record['test_double'] = True
    if mutation == 'host':
        record['host_response_schema']['properties']['insights']['items']['maxLength'] = 4095
    elif mutation == 'wire':
        record['response_schema']['properties']['insights']['items']['maxLength'] = 4096
        record['request_config']['response_format']['schema'] = deepcopy(record['response_schema'])
    manifest = {'source_sha256': {name: 'a' * 64 for name in audit.PORTABLE_SOURCE_FILES},
                'client_config': {'model': instance.model, 'context_tokens': instance.context_tokens,
                                  'response_mode': 'schema', 'decoding': instance.decoding.to_dict()},
                'limits': {'solve_output_tokens': 256, 'reflection_output_tokens': 256}}
    budget = audit.ChargedBudget(audit.Budget(max_calls=10, max_total_tokens=10000),
                                 audit.Budget(max_calls=10, max_total_tokens=10000))
    counts, issues = Counter(), []
    if mutation is None:
        assert audit.check_call(record, messages, 'ordinary:reflection', schema, budget,
                                 manifest, counts, issues) == ('completed', content)
        assert budget.local.total_tokens == budget.total.total_tokens == 17
        assert counts['test_double_calls'] == 1 and issues == []
    else:
        with pytest.raises(audit.AuditError):
            audit.check_call(record, messages, 'ordinary:reflection', schema, budget,
                              manifest, counts, issues)
