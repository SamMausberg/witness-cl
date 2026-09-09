"""Portable-schema transport tests with no server, inference, or source edits."""
from copy import deepcopy
import importlib
import json
import sys

import pytest

from witness_cl.memory_v8 import canonical
from witness_cl.memory_v9 import ExperienceMemoryV9, reflection_schema_v9
from witness_cl.model_v8 import InferenceBudget
from witness_cl.model_v9 import DecodingV9
from witness_cl.model_v9_compatible import (
    LocalInferenceV9Compatible, WIRE_SCHEMA_POLICY, portable_schema,
)


def client(tmp_path, **kwargs):
    key = tmp_path / 'offline-only.key'
    key.write_text('not-a-real-credential', encoding='utf-8')
    return LocalInferenceV9Compatible(
        key_file=key, endpoint='http://127.0.0.1:1', model='explicit-offline-compatible-test',
        max_output=4096, context_tokens=65536,
        decoding=DecodingV9(temperature=.6, top_p=.95, top_k=20, presence_penalty=1.5, thinking=True),
        **kwargs)


def response(model, content):
    return {'model': model, 'usage': {'prompt_tokens': 10, 'completion_tokens': 7, 'total_tokens': 17},
            'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}


def test_portable_schema_removes_only_large_integer_bounds_and_deepcopies():
    schema = {
        'type': 'object', 'additionalProperties': False, 'required': ['notes'],
        'properties': {
            'notes': {'type': 'array', 'maxItems': 16, 'items': {'type': 'string', 'maxLength': 4096}},
            'small': {'type': 'string', 'minLength': 1, 'maxLength': 512},
            'edge': {'type': 'string', 'maxLength': 2000},
            'large': {'type': 'string', 'maxLength': 2001},
            'number': {'type': 'number', 'minimum': 0},
        },
    }
    original = deepcopy(schema)
    expected = deepcopy(schema)
    del expected['properties']['notes']['items']['maxLength']
    del expected['properties']['large']['maxLength']
    wire = portable_schema(schema)
    assert wire == expected and schema == original
    wire['required'].append('small')
    wire['properties']['small']['maxLength'] = 2
    assert schema == original
    assert portable_schema(None) is None


@pytest.mark.parametrize('phase,thinking', [('ordinary:solve', True), ('ordinary:reflection', False)])
def test_effective_bodies_match_and_phase_policy_is_restored(tmp_path, monkeypatch, phase, thinking):
    instance = client(tmp_path)
    original_decoding = instance.decoding
    host_schema = reflection_schema_v9('insights')
    frozen_host = deepcopy(host_schema)
    messages = [{'role': 'user', 'content': 'Actual visible observations.'}]
    original_messages = deepcopy(messages)
    requests = []
    raw_content = 'not repaired: { malformed output'

    def fake_post(path, body, timeout):
        requests.append((path, deepcopy(body)))
        assert instance.decoding.thinking is thinking
        if path.endswith('/input_tokens'):
            # Caller-side changes after dispatch cannot rewrite the frozen
            # original host schema, model messages, or next effective request.
            host_schema['properties']['insights']['items']['maxLength'] = 9999
            messages[0]['content'] = 'Changed after dispatch.'
            body['max_tokens'] = 1
            return {'input_tokens': 10}
        return response(instance.model, raw_content)

    monkeypatch.setattr(instance, '_post', fake_post)
    records = []
    budget = InferenceBudget()
    content = instance.complete(messages, budget, phase=phase, records=records,
                                output_tokens=256, response_schema=host_schema)
    assert content == raw_content and records[0]['content'] == raw_content
    assert requests[0][1] == requests[1][1]
    body = requests[0][1]
    assert body['messages'] == original_messages
    assert body['max_tokens'] == 256
    assert body['chat_template_kwargs'] == {'enable_thinking': thinking}
    assert body['response_format'] == {'type': 'json_object', 'schema': portable_schema(frozen_host)}
    assert records[0]['host_response_schema'] == frozen_host
    assert records[0]['response_schema'] == portable_schema(frozen_host)
    assert records[0]['request_config'] == {key: value for key, value in body.items() if key != 'messages'}
    assert records[0]['decoding']['thinking'] is thinking
    assert records[0]['wire_schema_policy'] == WIRE_SCHEMA_POLICY
    assert records[0]['reflection_thinking'] is False
    assert instance.decoding is original_decoding and instance.decoding.thinking is True
    assert budget.calls == 1 and budget.total_tokens == 17
    assert budget.prompt_tokens == 10 and budget.completion_tokens == 7 and budget.unknown_usage_calls == 0


def test_removed_wire_limit_does_not_repair_output_or_weaken_host_admission(tmp_path, monkeypatch):
    instance = client(tmp_path)
    oversized = canonical({'insights': ['x' * 4097]})
    def fake_post(path, body, timeout):
        return {'input_tokens': 10} if path.endswith('/input_tokens') else response(instance.model, oversized)
    monkeypatch.setattr(instance, '_post', fake_post)
    records = []
    result = instance.complete([{'role': 'user', 'content': 'Observed episode.'}], InferenceBudget(),
                                phase='ordinary:reflection', records=records,
                                output_tokens=4096, response_schema=reflection_schema_v9('insights'))
    assert result == oversized
    memory = ExperienceMemoryV9('insights', 'Shared policy.')
    memory.insights = ['Prior supported evidence.']
    memory.finish({'question': 'Current question', 'queries': [], 'answer': 1, 'reward': 0.}, [], result)
    assert memory.insights == ['Prior supported evidence.']
    assert memory.events[-2]['kind'] == 'rejected_reflection'


@pytest.mark.parametrize('failure,calls,tokens,unknown', [
    ('preflight', 0, 0, 0), ('generation', 1, 0, 1), ('identity', 1, 17, 0),
])
def test_failures_preserve_accounting_markers_and_restore_thinking(tmp_path, monkeypatch, failure, calls, tokens, unknown):
    instance = client(tmp_path)
    original = instance.decoding
    schema = reflection_schema_v9('insights')
    def fake_post(path, body, timeout):
        assert body['chat_template_kwargs'] == {'enable_thinking': False}
        if path.endswith('/input_tokens'):
            if failure == 'preflight':
                raise OSError('explicit fake preflight failure')
            return {'input_tokens': 10}
        if failure == 'generation':
            raise OSError('explicit fake generation failure')
        return response('wrong-model-identity', '{"insights":[]}')
    monkeypatch.setattr(instance, '_post', fake_post)
    records = []
    budget = InferenceBudget()
    with pytest.raises((OSError, RuntimeError)):
        instance.complete([{'role': 'user', 'content': 'Observed evidence.'}], budget,
                           phase='ordinary:reflection', records=records,
                           output_tokens=256, response_schema=schema)
    assert instance.decoding is original and instance.decoding.thinking is True
    assert budget.calls == calls and budget.total_tokens == tokens and budget.unknown_usage_calls == unknown
    assert len(records) == 1
    assert records[0]['host_response_schema'] == schema
    assert records[0]['response_schema'] == portable_schema(schema)
    assert records[0]['wire_schema_policy'] == WIRE_SCHEMA_POLICY
    assert records[0]['reflection_thinking'] is False
    if failure == 'identity':
        assert records[0]['usage']['total_tokens'] == 17
    else:
        assert records[0]['usage'] is None


def test_compatible_transport_rejects_json_mode_before_requests(tmp_path, monkeypatch):
    instance = client(tmp_path, response_mode='json')
    def forbidden(*args):
        raise AssertionError('no transport may run')
    monkeypatch.setattr(instance, '_post', forbidden)
    records = []
    budget = InferenceBudget()
    with pytest.raises(ValueError, match='schema mode'):
        instance.complete([], budget, phase='ordinary:reflection', records=records, response_schema={})
    assert records == [] and budget.calls == 0 and budget.total_tokens == 0
    assert instance.decoding.thinking is True


@pytest.mark.parametrize('fail', [False, True])
def test_wrapper_extends_dependencies_only_during_main_and_restores_them(tmp_path, monkeypatch, fail):
    from experiments import sql_abstractions_v9 as pilot
    original = pilot.SOURCE_FILES
    wrapper = importlib.import_module('experiments.portable_stream_v9')
    assert pilot.SOURCE_FILES is original
    observed = {}
    monkeypatch.setattr(wrapper, 'LocalInferenceV9Compatible', lambda **kwargs: observed.setdefault('client', kwargs))
    def fake_run(out, instance, **kwargs):
        assert pilot.SOURCE_FILES == (*original, *wrapper.PORTABLE_SOURCE_FILES)
        assert kwargs['stage'] == 'full' and kwargs['gate_after_warm'] is True
        assert kwargs['minimum_warm_correct'] == 7
        assert kwargs['limits'].solve_output_tokens == 2048 and kwargs['limits'].reflection_output_tokens == 4096
        assert instance['decoding'].thinking is True and instance['response_mode'] == 'schema'
        if fail:
            raise RuntimeError('explicit offline run failure')
        return {'status': 'completed'}
    monkeypatch.setattr(pilot, 'run_study', fake_run)
    monkeypatch.setattr(sys, 'argv', ['portable_stream_v9.py', '--out', str(tmp_path / 'unused-output'),
                                     '--key-file', str(tmp_path / 'unused-key')])
    if fail:
        with pytest.raises(RuntimeError, match='offline run failure'):
            wrapper.main()
    else:
        assert wrapper.main() == 0
    assert pilot.SOURCE_FILES is original
    assert not (tmp_path / 'unused-output').exists()
