"""Independent client/accounting and experience-only memory regression tests.

All inference responses are deterministic fakes. No model or server is called.
Only local synthetic observations appear in memory fixtures.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
import math
import time

import pytest

import witness_cl.model_v8 as model
import witness_cl.memory_v8 as memory
from witness_cl.fragments_v8 import Fragment, FragmentError
from witness_cl.model_v8 import BudgetStop, InferenceBudget, LocalInference
from witness_cl.memory_v8 import ExperienceMemory, parse_action


MESSAGES = [{'role': 'system', 'content': 'Return JSON.'},
            {'role': 'user', 'content': 'Synthetic question only.'}]


def client(tmp_path, **kwargs):
    key = tmp_path / 'test-key'
    key.write_text('local-test-only-no-real-authority')
    return LocalInference(key_file=key, max_output=20, context_tokens=128, **kwargs)


def reply(prompt=10, completion=5, *, content='{"action":"ANSWER","value":2}',
          model_name='witness-v8-qwen3-4b-q8'):
    return {'model': model_name, 'usage': {'prompt_tokens': prompt,
            'completion_tokens': completion, 'total_tokens': prompt + completion},
            'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}


def install_fake(monkeypatch, obj, responses):
    calls = []
    queue = list(responses)
    def post(path, payload, timeout):
        calls.append((path, deepcopy(payload), timeout))
        if not queue:
            raise AssertionError('unexpected retry or additional model request')
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)
    monkeypatch.setattr(obj, '_post', post)
    return calls


def test_complete_charges_exact_usage_and_freezes_complete_messages(tmp_path, monkeypatch):
    obj = client(tmp_path)
    calls = install_fake(monkeypatch, obj, [{'input_tokens': 10}, reply()])
    messages = deepcopy(MESSAGES)
    records, budget = [], InferenceBudget(max_total_tokens=40)
    answer = obj.complete(messages, budget, phase='ordinary', records=records)
    assert json.loads(answer)['value'] == 2
    assert budget.calls == 1 and budget.total_tokens == 15
    assert (budget.prompt_tokens, budget.completion_tokens, budget.unknown_usage_calls) == (10, 5, 0)
    assert [path for path, _, _ in calls] == ['/v1/chat/completions/input_tokens', '/v1/chat/completions']
    assert calls[0][1] == calls[1][1]
    body = calls[-1][1]
    assert body['messages'] == MESSAGES and body['max_tokens'] == 20
    assert body['cache_prompt'] is False and body['chat_template_kwargs']['enable_thinking'] is False
    assert body['response_format'] == {'type': 'json_object'}
    assert 'tools' not in body and 'functions' not in body
    assert records[0]['response_model'] == obj.model
    assert records[0]['status'] == 'completed' and records[0]['generation_attempted']
    messages[0]['content'] = 'changed after request'
    messages.append({'role': 'user', 'content': 'future observation'})
    assert records[0]['messages'] == MESSAGES
    assert 'local-test-only-no-real-authority' not in json.dumps(records)


@pytest.mark.parametrize('overrides', [
    {'max_total_tokens': 0}, {'max_total_tokens': True}, {'max_calls': -1},
    {'max_calls': 1.5}, {'deadline': float('nan')}, {'deadline': -1},
    {'total_tokens': -1}, {'calls': True}, {'unknown_usage_calls': -1},
])
def test_invalid_budget_cannot_bypass_caps(overrides):
    with pytest.raises(ValueError):
        InferenceBudget(**overrides)


@pytest.mark.parametrize('input_tokens,output_tokens', [(-1, 1), (0, 0), (True, 1), (0, True), (1.0, 1)])
def test_budget_rejects_invalid_reservation_units(input_tokens, output_tokens):
    with pytest.raises(ValueError):
        InferenceBudget().check(input_tokens, output_tokens)


@pytest.mark.parametrize('budget', [
    InferenceBudget(max_calls=1, calls=1),
    InferenceBudget(max_total_tokens=5),
    InferenceBudget(deadline=1.),
])
def test_exhausted_budget_stops_before_any_transport(tmp_path, monkeypatch, budget):
    obj = client(tmp_path)
    calls = install_fake(monkeypatch, obj, [])
    with pytest.raises(BudgetStop):
        obj.complete(MESSAGES, budget, phase='ordinary', records=[])
    assert calls == []


def test_context_and_preflight_budget_stop_without_truncation(tmp_path, monkeypatch):
    obj = client(tmp_path)
    calls = install_fake(monkeypatch, obj, [{'input_tokens': 109}])
    records, budget = [], InferenceBudget()
    with pytest.raises(BudgetStop, match='full_context_ceiling_no_truncation'):
        obj.complete(MESSAGES, budget, phase='ordinary', records=records)
    assert len(calls) == 1 and calls[0][1]['messages'] == MESSAGES
    assert budget.calls == 0 and budget.unknown_usage_calls == 0
    assert records[0]['preflight_tokens'] == 109
    assert records[0]['generation_attempted'] is False
    assert records[0]['status'] == 'preflight_failed'
    assert records[0]['stop_reason'] == 'full_context_ceiling_no_truncation'
    assert budget.tokenization_seconds == records[0]['tokenization_seconds']


@pytest.mark.parametrize('count', [{}, {'input_tokens': True}, {'input_tokens': -1},
                                   {'input_tokens': '10'}, [], None])
def test_invalid_token_preflight_is_recorded_without_inference(tmp_path, monkeypatch, count):
    obj = client(tmp_path)
    calls = install_fake(monkeypatch, obj, [count])
    records, budget = [], InferenceBudget()
    with pytest.raises(RuntimeError, match='exact count'):
        obj.complete(MESSAGES, budget, phase='ordinary', records=records)
    assert len(calls) == 1 and budget.calls == 0
    assert records[0]['status'] == 'preflight_failed'
    assert records[0]['usage'] is None and not records[0]['generation_attempted']
    assert records[0]['tokenization_seconds'] >= 0


def test_preflight_transport_failure_is_timed_and_not_retried(tmp_path, monkeypatch):
    obj = client(tmp_path)
    calls = install_fake(monkeypatch, obj, [TimeoutError('test timeout')])
    records, budget = [], InferenceBudget()
    with pytest.raises(TimeoutError):
        obj.complete(MESSAGES, budget, phase='reflection', records=records)
    assert len(calls) == 1 and budget.calls == 0
    assert records[0]['phase'] == 'reflection' and records[0]['status'] == 'preflight_failed'
    assert records[0]['error_type'] == 'TimeoutError'
    assert budget.tokenization_seconds == records[0]['tokenization_seconds']


@pytest.mark.parametrize('outcome', [TimeoutError('test timeout'), {'choices': []},
    {'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 99}},
    {'usage': {'prompt_tokens': 10, 'completion_tokens': True, 'total_tokens': 11}},
])
def test_unknown_inference_usage_stays_unknown_and_aborts(tmp_path, monkeypatch, outcome):
    obj = client(tmp_path)
    calls = install_fake(monkeypatch, obj, [{'input_tokens': 10}, outcome])
    records, budget = [], InferenceBudget()
    with pytest.raises((RuntimeError, TimeoutError)):
        obj.complete(MESSAGES, budget, phase='ordinary', records=records)
    assert len(calls) == 2 and budget.calls == 1 and budget.unknown_usage_calls == 1
    assert records[0]['usage'] is None and records[0]['status'] == 'failed'
    assert records[0]['generation_attempted']
    # These counters contain only known usage; the None/unknown flag prohibits
    # reporting the failed attempted inference as a measured zero-token call.
    assert budget.total_tokens == 0


@pytest.mark.parametrize('outcome,preflight,error', [
    (reply(prompt=10, completion=21), 10, 'per-call output cap'),
    (reply(prompt=9), 10, 'accounting mismatch'),
    (reply(prompt=125, completion=5), 10, 'accounting mismatch'),
    (reply(model_name='other-unapproved-model'), 10, 'model identity mismatch'),
])
def test_backend_identity_and_cap_mismatches_abort_with_known_cost(tmp_path, monkeypatch, outcome, preflight, error):
    obj = client(tmp_path)
    install_fake(monkeypatch, obj, [{'input_tokens': preflight}, outcome])
    records, budget = [], InferenceBudget()
    with pytest.raises(RuntimeError, match=error):
        obj.complete(MESSAGES, budget, phase='ordinary', records=records)
    assert budget.calls == 1 and budget.unknown_usage_calls == 0
    assert budget.total_tokens == outcome['usage']['total_tokens']
    assert records[0]['usage'] == outcome['usage'] and records[0]['status'] == 'failed'


def test_actual_total_token_overrun_is_charged_then_aborts(tmp_path, monkeypatch):
    obj = client(tmp_path)
    install_fake(monkeypatch, obj, [{'input_tokens': 10}, reply(prompt=40, completion=5)])
    records, budget = [], InferenceBudget(max_total_tokens=30)
    with pytest.raises(RuntimeError, match='reserved token budget'):
        obj.complete(MESSAGES, budget, phase='ordinary', records=records)
    assert budget.total_tokens == 45 and records[0]['usage']['total_tokens'] == 45


@pytest.mark.parametrize('endpoint', ['https://127.0.0.1:1', 'http://localhost:1',
    'http://192.0.2.1:1', 'http://127.0.0.1:1/v1', 'http://x:y@127.0.0.1:1',
    'http://127.0.0.1:1?other=1', 'http://127.0.0.1:1#fragment'])
def test_only_literal_loopback_endpoint_allowed(tmp_path, endpoint):
    with pytest.raises(ValueError):
        client(tmp_path, endpoint=endpoint)


def test_local_transport_explicitly_disables_environment_proxy(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(model, 'build_opener', lambda *handlers: captured.extend(handlers))
    monkeypatch.setenv('HTTP_PROXY', 'http://example.invalid:8888')
    client(tmp_path)
    proxies = [h for h in captured if isinstance(h, model.ProxyHandler)]
    assert len(proxies) == 1 and proxies[0].proxies == {}
    assert any(isinstance(h, model.NoRedirect) for h in captured)
    with pytest.raises(RuntimeError, match='redirects'):
        model.NoRedirect().redirect_request(None, None, None, None, None, None)


@pytest.mark.parametrize('text', [
    '{"action":"ANSWER","value":true}',
    '{"action":"ANSWER","value":NaN}',
    '{"action":"ANSWER","value":1e999}',
    '{"action":"ANSWER","value":'+ '9'*400 + '}',
    '{"action":["ANSWER"],"value":1}',
    '{"action":"ANSWER","action":"QUERY","value":1}',
    '{"action":"ANSWER","value":1,"seed":90000}',
    '{"action":"RUN","command":"anything"}',
    '{"action":"USE","entry":true,"params":{}}',
    '{"action":"USE","entry":2,"params":{}}',
    '{"action":"QUERY","sql":"DELETE FROM orders","params":{}}',
    '{"action":"QUERY","sql":"SELECT :v","params":{"v":true}}',
    '[]', 'not JSON', 'x'*16385,
])
def test_action_parser_rejects_malformed_or_unauthorized_output(text):
    with pytest.raises(ValueError):
        parse_action(text)


def test_action_literals_stay_data_and_never_change_sql_text():
    payload = {'action': 'QUERY', 'sql': 'SELECT :value AS x',
               'params': {'value': "x'; DELETE FROM orders; --"}}
    parsed = parse_action(json.dumps(payload))
    prepared = Fragment.from_query(parsed['sql'], parsed['params']).compile()
    assert prepared.sql == 'SELECT :value AS x'
    assert prepared.parameters == payload['params']
    assert parse_action('{"action":"ANSWER","value":-1.25}')['value'] == -1.25


def trace(*, reward=1., truncated=False):
    return {'question': 'What is the amount for North?', 'answer': 10, 'reward': reward,
        'seed': 'EVALUATOR-SEED-MUST-NOT-APPEAR', '_gold_sql': 'EVALUATOR-GOLD-MUST-NOT-APPEAR',
        'queries': [
            {'sql': 'SELECT description FROM catalog', 'params': {},
             'columns': ['description'], 'rows': [['Amounts are dollars.']], 'error': None,
             'truncated': truncated},
            {'sql': 'SELECT amount FROM orders WHERE region=:region', 'params': {'region': 'North'},
             'columns': ['amount'], 'rows': [[10]], 'error': None, 'truncated': False},
        ]}


def conversation():
    return [{'role': 'user', 'content': 'What is the amount for North?'},
            {'role': 'assistant', 'content': '{"action":"QUERY","sql":"SELECT 10","params":{}}'},
            {'role': 'user', 'content': 'Observed rows: [[10]]'},
            {'role': 'assistant', 'content': '{"action":"ANSWER","value":10}'},
            {'role': 'user', 'content': 'Correctness feedback: 1'}]


def fragment_choice(**overrides):
    return dict({'source_index': 1, 'guard_index': 0, 'description': 'Amounts by region'}, **overrides)


def admit(obj, source=None, specs=None):
    obj.finish(trace() if source is None else source, conversation(),
               json.dumps({'fragments': [fragment_choice()] if specs is None else specs}))


def test_full_history_is_complete_deepcopied_and_untruncated(monkeypatch):
    obj = ExperienceMemory('full_history')
    original = conversation()
    obj.finish(trace(), original)
    original[0]['content'] = 'caller edit'
    original.clear()
    before = deepcopy(obj.snapshot())
    prefix, selected = obj.prefix('a new composition')
    assert selected == [] and prefix[1:] == conversation()
    prefix[1]['content'] = 'consumer edit'
    assert obj.snapshot() == before
    monkeypatch.setattr(memory, 'MAX_RAW_BYTES', obj.raw_bytes)
    with pytest.raises(ValueError, match='raw-history storage ceiling'):
        obj.finish(trace(), conversation())
    assert obj.snapshot() == before


@pytest.mark.parametrize('arm', ['full_history', 'verbatim', 'stateless'])
def test_nonreflecting_controls_do_not_call_reflection(arm):
    obj = ExperienceMemory(arm)
    assert obj.reflection(trace(), conversation()) is None
    obj.finish(trace(), conversation())
    if arm == 'stateless':
        assert obj.history == obj.episodes == obj.entries == obj.insights == []
        assert len(obj.prefix('anything')[0]) == 1


def test_verbatim_and_insights_use_real_visible_experience_only():
    verbatim = ExperienceMemory('verbatim')
    verbatim.finish(trace(), conversation())
    text = json.dumps(verbatim.prefix('North amount')[0])
    assert 'Amounts are dollars.' in text
    assert 'EVALUATOR-' not in text
    insights = ExperienceMemory('insights')
    prompt = insights.reflection(trace(), conversation())
    assert json.loads(prompt[1]['content'])['episode'] == conversation()
    insights.finish(trace(), conversation(), '{"insights":["Amounts are dollars; witnessed in catalog."]}')
    assert insights.insights == ['Amounts are dollars; witnessed in catalog.']
    assert 'untrusted evidence' in insights.prefix('next')[0][-1]['content']


@pytest.mark.parametrize('bad', ['{"insights":[1]}', '{"insights":[] ,"extra":1}',
    '{"insights":'+json.dumps(['x']*17)+'}', '{"insights":'+json.dumps(['x'*513])+'}'])
def test_rejected_insight_updates_preserve_prior_memory(bad):
    obj = ExperienceMemory('insights')
    obj.finish(trace(), conversation(), '{"insights":["prior"]}')
    obj.finish(trace(), conversation(), bad)
    assert obj.insights == ['prior']
    assert obj.events[-2]['kind'] == 'rejected_reflection'


def test_fragment_admission_uses_only_executed_source_and_complete_guard():
    obj = ExperienceMemory('fragments')
    own = trace()
    reflection = obj.reflection(own, conversation())
    assert 'EVALUATOR-' not in json.dumps(reflection)
    admit(obj, own)
    assert len(obj.entries) == 1
    entry = obj.entries[0]
    assert entry.fragment().original_prepared_query.sql == own['queries'][1]['sql']
    assert entry.guard_fragment().original_prepared_query.sql == own['queries'][0]['sql']
    expected = json.loads(entry.expected)
    assert expected == {'columns': ['description'], 'rows': [['Amounts are dollars.']], 'truncated': False}
    evidence = memory.canonical({k: own[k] for k in ('question', 'queries', 'answer', 'reward')})
    assert entry.provenance == hashlib.sha256(evidence.encode()).hexdigest()
    with pytest.raises(FrozenInstanceError):
        entry.description = 'changed'
    own['queries'][0]['rows'][0][0] = 'caller change'
    assert json.loads(entry.expected) == expected
    prefix, selected = obj.prefix('North amounts')
    assert selected == [entry] and 'untrusted evidence' in prefix[-1]['content']
    assert 'EVALUATOR-' not in json.dumps(prefix)


@pytest.mark.parametrize('change', ['unsuccessful', 'bad_source', 'failed_source', 'failed_guard', 'truncated_guard'])
def test_unwitnessed_or_incomplete_fragment_reflection_is_rejected(change):
    obj = ExperienceMemory('fragments')
    own = trace()
    choices = [fragment_choice()]
    if change == 'unsuccessful': own['reward'] = 0.
    if change == 'bad_source': choices[0]['source_index'] = 99
    if change == 'failed_source': own['queries'][1]['error'] = 'failed SELECT'
    if change == 'failed_guard': own['queries'][0]['error'] = 'failed SELECT'
    if change == 'truncated_guard': own['queries'][0]['truncated'] = True
    if own['reward'] == 0:
        assert obj.reflection(own, conversation()) is None
    admit(obj, own, choices)
    assert obj.entries == []
    assert obj.events[-2]['kind'] == 'rejected_reflection'


def test_later_invalid_fragment_makes_whole_update_atomic():
    obj = ExperienceMemory('fragments')
    admit(obj)
    before = list(obj.entries)
    replacement = fragment_choice(description='replacement that must not survive rejected batch')
    admit(obj, specs=[replacement, fragment_choice(source_index=99)])
    assert obj.entries == before
    assert obj.events[-2]['kind'] == 'rejected_reflection'


def test_fragment_entry_cap_and_content_only_retrieval():
    obj = ExperienceMemory('fragments')
    for index in range(18):
        own = trace()
        own['queries'][1]['sql'] = f'SELECT amount AS amount_{index} FROM orders WHERE region=:region'
        admit(obj, own, [fragment_choice(description=f'Amounts region record_{index}')])
    assert len(obj.entries) == 16 and obj.memory_bytes() <= memory.MAX_MEMORY_BYTES
    prefix, selected = obj.prefix('region record_17')
    assert len(selected) == 2 and selected[0].description.endswith('record_17')
    assert all('entry' in x for x in json.loads(prefix[-1]['content'].split('\n', 1)[1]))
    old = deepcopy(obj.snapshot())
    exported = obj.snapshot()
    exported['entries'][0]['description'] = 'external mutation'
    exported['events'].clear()
    assert obj.snapshot() == old


def test_checked_and_unchecked_memory_share_identical_admission_and_retrieval():
    checked, unchecked = ExperienceMemory('fragments'), ExperienceMemory('fragments_unchecked')
    admit(checked); admit(unchecked)
    assert checked.entries == unchecked.entries
    assert checked.prefix('North amounts') == unchecked.prefix('North amounts')
    # The harness alone chooses whether to execute applicability checks. Neither
    # memory object can run SQL or grant additional action authority itself.


def test_serialized_memory_counts_journals_and_peak_after_final_event():
    obj = ExperienceMemory('stateless')
    before = obj.memory_bytes()
    obj.finish(trace(), conversation())
    snap = obj.snapshot()
    measured = {k: v for k, v in snap.items() if k not in ('memory_bytes', 'active_memory_bytes')}
    assert obj.memory_bytes() == len(memory.canonical(measured).encode())
    assert obj.memory_bytes() > before and obj.memory_bytes() > obj.active_memory_bytes()
    assert obj.peak_memory_bytes >= obj.memory_bytes()
    assert snap['events'][-1]['kind'] == 'episode_observed'
    assert 'active_memory_bytes' in snap['events'][-1]


@pytest.mark.parametrize('arm,field', [('full_history', 'history'), ('verbatim', 'episodes')])
def test_raw_history_cap_counts_the_serialized_retained_container(arm, field):
    obj = ExperienceMemory(arm)
    for _ in range(3):
        obj.finish(trace(), conversation())
    assert obj.raw_bytes == len(memory.canonical(getattr(obj, field)).encode())
    assert obj.memory_bytes() > obj.raw_bytes
    assert obj.peak_memory_bytes >= obj.memory_bytes()


def test_repeated_bindings_refresh_one_typed_template_with_new_provenance():
    obj = ExperienceMemory('fragments')
    admit(obj)
    old = obj.entries[0]
    own = trace()
    own['queries'][1]['params']['region'] = 'South'
    own['question'] = 'What is the amount for South?'
    admit(obj, own)
    assert len(obj.entries) == 1
    assert obj.entries[0].template_key() == old.template_key()
    assert obj.entries[0].provenance != old.provenance
    assert obj.entries[0].fragment().original_prepared_query.parameters == {'region': 'South'}
    assert obj.active_memory_bytes() <= memory.MAX_MEMORY_BYTES
