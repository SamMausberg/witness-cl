"""Offline v9 transport invariants; every backend response is an explicit fake."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json

import pytest

from witness_cl.model_v8 import BudgetStop, InferenceBudget
from witness_cl.model_v9 import DecodingV9, LocalInferenceV9


def client(tmp_path, **kwargs):
    key = tmp_path / 'synthetic-local-key'
    key.write_text('offline-test-no-authority')
    return LocalInferenceV9(key_file=key, model='offline-v9', context_tokens=128,
                            max_output=32, **kwargs)


def response(*, content='{"value":2}', reasoning=None, completion=6, finish='stop', prompt=10):
    return {'model': 'offline-v9',
            'usage': {'prompt_tokens': prompt, 'completion_tokens': completion,
                      'total_tokens': prompt + completion},
            'choices': [{'message': {'content': content, 'reasoning_content': reasoning},
                         'finish_reason': finish}]}


def fake_transport(monkeypatch, obj, replies):
    seen = []
    pending = list(replies)
    def post(path, payload, timeout):
        seen.append((path, deepcopy(payload)))
        assert pending, 'unexpected request or hidden retry'
        item = pending.pop(0)
        if isinstance(item, Exception):
            raise item
        return deepcopy(item)
    monkeypatch.setattr(obj, '_post', post)
    return seen


def test_effective_decoding_schema_and_messages_are_identical_and_frozen(tmp_path, monkeypatch):
    decoding = DecodingV9(temperature=.6, top_p=.95, top_k=30, min_p=.02,
                         presence_penalty=.5, seed=17, thinking=True)
    obj = client(tmp_path, decoding=decoding)
    messages = [{'role': 'user', 'content': 'Own synthetic observations'}]
    schema = {'type': 'object', 'properties': {'value': {'type': 'number'}}}
    original_messages, original_schema = deepcopy(messages), deepcopy(schema)
    seen = []
    backend_reply = response(reasoning='A bounded synthetic intermediate.')
    def post(path, payload, timeout):
        seen.append((path, deepcopy(payload)))
        if path.endswith('/input_tokens'):
            # Caller and transport mutations cannot change the effective
            # generation request or its audit record after preflight.
            messages[0]['content'] = 'future observation'
            schema['type'] = 'array'
            payload['messages'][0]['content'] = 'transport mutation'
            payload['response_format']['schema']['type'] = 'string'
            obj.decoding = DecodingV9()
            return {'input_tokens': 10}
        return backend_reply
    monkeypatch.setattr(obj, '_post', post)
    records, budget = [], InferenceBudget()
    assert obj.complete(messages, budget, phase='diagnostic', records=records,
                        output_tokens=24, response_schema=schema) == '{"value":2}'
    assert len(seen) == 2 and seen[0][1] == seen[1][1]
    body = seen[0][1]
    assert body['messages'] == original_messages
    assert body['response_format']['schema'] == original_schema
    assert body['chat_template_kwargs'] == {'enable_thinking': True}
    assert body['max_tokens'] == 24 and body['cache_prompt'] is False
    for name, value in decoding.to_dict().items():
        if name != 'thinking':
            assert body[name] == value
    assert records[0]['request_config'] == {k: v for k, v in body.items() if k != 'messages'}
    assert records[0]['messages'] == original_messages
    assert records[0]['response_schema'] == original_schema
    assert records[0]['decoding'] == decoding.to_dict()
    assert records[0]['reasoning_content'] == 'A bounded synthetic intermediate.'
    backend_reply['usage']['total_tokens'] = 999
    assert records[0]['usage']['total_tokens'] == budget.total_tokens == 16
    assert 'offline-test-no-authority' not in json.dumps(records)
    assert 'Authorization' not in json.dumps(records)


def test_json_mode_omits_schema_for_both_requests(tmp_path, monkeypatch):
    obj = client(tmp_path, response_mode='json')
    seen = fake_transport(monkeypatch, obj, [{'input_tokens': 10}, response()])
    records = []
    obj.complete([], InferenceBudget(), phase='diagnostic', records=records,
                 response_schema={'type': 'object'})
    assert seen[0][1] == seen[1][1]
    assert seen[0][1]['response_format'] == {'type': 'json_object'}
    assert records[0]['response_schema'] is None and records[0]['response_mode'] == 'json'


def test_reasoning_only_exhaustion_keeps_known_cost_and_empty_action(tmp_path, monkeypatch):
    obj = client(tmp_path, decoding=DecodingV9(thinking=True))
    seen = fake_transport(monkeypatch, obj, [
        {'input_tokens': 10}, response(content=None, reasoning='Still deriving SQL.', completion=32, finish='length')])
    budget, records = InferenceBudget(), []
    assert obj.complete([], budget, phase='solve', records=records) == ''
    assert len(seen) == 2 and budget.calls == 1
    assert (budget.prompt_tokens, budget.completion_tokens, budget.total_tokens) == (10, 32, 42)
    assert budget.unknown_usage_calls == 0
    assert records[0]['status'] == 'completed' and records[0]['content_was_null'] is True
    assert records[0]['finish_reason'] == 'length'
    assert records[0]['reasoning_content'] == 'Still deriving SQL.'


@pytest.mark.parametrize('kwargs', [
    {'temperature': True}, {'temperature': float('nan')}, {'top_p': 0},
    {'top_k': -1}, {'min_p': 1.1}, {'presence_penalty': float('inf')},
    {'seed': True}, {'seed': 2**32}, {'thinking': 1},
])
def test_invalid_decoding_cannot_reach_transport(kwargs):
    with pytest.raises(ValueError):
        DecodingV9(**kwargs)


def test_decoding_is_immutable_and_mode_is_validated_before_key_read(tmp_path):
    with pytest.raises(FrozenInstanceError):
        DecodingV9().thinking = True
    with pytest.raises(ValueError, match='response_mode'):
        LocalInferenceV9(key_file=tmp_path / 'absent', response_mode='unrestricted')


@pytest.mark.parametrize('failure', ['context', 'reservation'])
def test_full_prompt_and_output_reservation_stop_before_generation(tmp_path, monkeypatch, failure):
    obj = client(tmp_path)
    seen = fake_transport(monkeypatch, obj, [{'input_tokens': 110 if failure == 'context' else 10}])
    budget = InferenceBudget(max_total_tokens=1000 if failure == 'context' else 40)
    records = []
    with pytest.raises(BudgetStop):
        obj.complete([], budget, phase='solve', records=records)
    assert len(seen) == 1 and budget.calls == 0 and budget.total_tokens == 0
    assert records[0]['status'] == 'preflight_failed'
    assert records[0]['generation_attempted'] is False


@pytest.mark.parametrize('failure', ['short_prompt', 'excess_output', 'unknown_usage'])
def test_backend_accounting_errors_are_charged_and_never_retried(tmp_path, monkeypatch, failure):
    obj = client(tmp_path)
    reply = response(prompt=9 if failure == 'short_prompt' else 10,
                     completion=33 if failure == 'excess_output' else 6)
    if failure == 'unknown_usage':
        del reply['usage']
    seen = fake_transport(monkeypatch, obj, [{'input_tokens': 10}, reply])
    budget, records = InferenceBudget(), []
    with pytest.raises(RuntimeError):
        obj.complete([], budget, phase='solve', records=records)
    assert len(seen) == 2 and budget.calls == 1 and records[0]['status'] == 'failed'
    assert budget.unknown_usage_calls == int(failure == 'unknown_usage')
    assert budget.total_tokens == (0 if failure == 'unknown_usage' else reply['usage']['total_tokens'])
