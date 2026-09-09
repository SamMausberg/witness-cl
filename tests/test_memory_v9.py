from copy import deepcopy
import json

import pytest

from witness_cl.memory_v8 import ExperienceMemory, canonical
from witness_cl.memory_v9 import (
    ARMS, MAX_ENTRIES, MAX_INSIGHT_CHARACTERS, MAX_MEMORY_BYTES,
    ExperienceMemoryV9, reflection_schema_v9,
)


PROMPT = 'Shared bounded SQL-solving policy.'
TRACE = {'question': 'How many rows?', 'queries': [], 'answer': 7, 'reward': 0.0}
CONVERSATION = [
    {'role': 'user', 'content': 'How many rows?'},
    {'role': 'assistant', 'content': '{"action":"ANSWER","value":7}'},
    {'role': 'user', 'content': '{"answer_correct":false}'},
]


def test_all_six_arms_have_identical_initial_prefix_and_required_policy():
    expected = ([{'role': 'system', 'content': PROMPT}], [])
    assert all(ExperienceMemoryV9(arm, PROMPT).prefix('question') == expected for arm in ARMS)
    with pytest.raises(TypeError):
        ExperienceMemoryV9('insights')
    for invalid in ('', '  ', None, 1):
        with pytest.raises(ValueError):
            ExperienceMemoryV9('insights', invalid)


def test_reflection_uses_prior_context_visible_messages_and_boolean_feedback_only():
    memory = ExperienceMemoryV9('insights', PROMPT)
    memory.insights = ['SELECT COUNT(*) FROM observed_rows; evidence: seven rows.']
    trace = {**TRACE, 'evaluator': {'secret_target': 1234}, 'future_question': 'hidden'}
    reflected = memory.reflection(trace, CONVERSATION)
    payload = json.loads(reflected[1]['content'])
    assert set(payload) == {'prior_insights', 'episode', 'answer_correct'}
    assert payload['answer_correct'] is False
    assert payload['prior_insights'] == memory.insights
    assert payload['episode'] == CONVERSATION
    assert 'secret_target' not in reflected[1]['content']
    assert 'SQL snippets' in reflected[0]['content']
    assert json.loads(memory.reflection({**TRACE, 'reward': 1}, CONVERSATION)[1]['content'])['answer_correct'] is True
    for invalid in (True, '1', None, 0.5, float('nan')):
        with pytest.raises(ValueError):
            memory.reflection({**TRACE, 'reward': invalid}, CONVERSATION)


def test_long_sql_context_update_and_rejection_are_atomic_and_accounted():
    memory = ExperienceMemoryV9('insights', PROMPT)
    sql_note = 'Observed SQL: SELECT SUM(amount) FROM orders; ' + 'scoped evidence ' * 200
    assert 512 < len(sql_note) <= MAX_INSIGHT_CHARACTERS
    memory.finish(TRACE, CONVERSATION, canonical({'insights': [sql_note]}))
    before = memory.snapshot()
    assert before['insights'] == [sql_note]
    assert sql_note in json.loads(memory.prefix('amount')[0][-1]['content'].split('\n', 1)[1])
    memory.finish(TRACE, CONVERSATION, canonical({'insights': ['replacement', 42]}))
    after = memory.snapshot()
    assert after['insights'] == before['insights']
    assert after['events'][-2]['kind'] == 'rejected_reflection'
    assert after['events'][-1]['kind'] == 'episode_observed'
    assert after['active_memory_bytes'] == before['active_memory_bytes']
    assert after['memory_bytes'] > before['memory_bytes']
    assert after['peak_memory_bytes'] >= after['memory_bytes']
    assert memory.digest() == memory.digest()
    after['insights'].clear()
    assert memory.insights == [sql_note]


def test_context_item_count_character_and_encoded_active_caps():
    memory = ExperienceMemoryV9('insights', PROMPT)
    # 61440 text bytes plus JSON structure: legal, and larger than v8's parser cap.
    near_cap = ['x' * 4096] * 15
    memory.finish(TRACE, CONVERSATION, canonical({'insights': near_cap}))
    assert memory.insights == near_cap
    assert memory.active_memory_bytes() <= MAX_MEMORY_BYTES
    for notes in (
        ['x'] * (MAX_ENTRIES + 1),
        ['x' * (MAX_INSIGHT_CHARACTERS + 1)],
        ['x' * MAX_INSIGHT_CHARACTERS] * MAX_ENTRIES,
        ['\U0001f642' * MAX_INSIGHT_CHARACTERS] * 4,
    ):
        prior = list(memory.insights)
        memory.finish(TRACE, CONVERSATION, canonical({'insights': notes}))
        assert memory.insights == prior
        assert memory.events[-2]['kind'] == 'rejected_reflection'
    # This output fits the response cap but its retained entries wrapper exceeds it.
    exact = ['x' * 4096] * 15 + ['x']
    padding = MAX_MEMORY_BYTES - len(canonical({'insights': exact}).encode())
    exact[-1] += 'x' * padding
    assert len(exact[-1]) <= MAX_INSIGHT_CHARACTERS
    assert len(canonical({'insights': exact}).encode()) == MAX_MEMORY_BYTES
    memory.finish(TRACE, CONVERSATION, canonical({'insights': exact}))
    assert memory.insights == near_cap
    assert memory.events[-2]['error'] == 'insight active byte cap'
    schema = reflection_schema_v9('insights')['properties']['insights']
    assert schema['maxItems'] == MAX_ENTRIES
    assert schema['items']['maxLength'] == MAX_INSIGHT_CHARACTERS


@pytest.mark.parametrize('text', [
    '{"insights":["new"],"insights":["duplicate"]}',
    '{"insights":["new"],"extra":true}',
    '{"insights":[NaN]}',
    '{"insights":["\\ud800"]}',
    '[]',
])
def test_malformed_context_rejects_entire_update(text):
    memory = ExperienceMemoryV9('insights', PROMPT)
    memory.insights = ['prior evidence']
    memory.finish(TRACE, CONVERSATION, text)
    assert memory.insights == ['prior evidence']
    assert memory.events[-2]['kind'] == 'rejected_reflection'


@pytest.mark.parametrize('arm', [arm for arm in ARMS if arm != 'insights'])
def test_other_arms_retain_v8_finish_and_nonempty_prefix_behavior(arm):
    old = ExperienceMemory(arm)
    new = ExperienceMemoryV9(arm, PROMPT)
    old.finish(deepcopy(TRACE), deepcopy(CONVERSATION))
    new.finish(deepcopy(TRACE), deepcopy(CONVERSATION))
    assert new.snapshot() == old.snapshot()
    assert new.digest() == old.digest()
    if arm in ('full_history', 'verbatim'):
        old_messages, old_entries = old.prefix('rows')
        new_messages, new_entries = new.prefix('rows')
        old_messages[0]['content'] = PROMPT
        assert new_messages == old_messages
        assert new_entries == old_entries
