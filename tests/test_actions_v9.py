"""Ordinary parser/executor integration with real ephemeral SQLite, no model."""
import json

import pytest

from witness_cl.actions_v9 import parse_action
from witness_cl.fragments_v8 import Fragment, FragmentError
from witness_cl.memory_v8 import parse_action as strict_parse
from witness_cl.sql_env_v8 import make_stream, open_episode


def query(sql, params=None):
    return json.dumps({'action': 'QUERY', 'sql': sql, 'params': {} if params is None else params})


@pytest.mark.parametrize('sql,params,expected', [
    ('SELECT 7;', {'unused': 99}, 7),
    ('-- documentation comment\nSELECT :n; -- trailing comment', {'n': 11, 'unused': None}, 11),
    ('/* leading */ WITH x AS (SELECT :n AS amount) SELECT amount FROM x;', {'n': 12}, 12),
    ('SELECT :x AS value /* inner comment */;', {'x': "SQL-shaped text: '; DROP TABLE catalog; --"}, "SQL-shaped text: '; DROP TABLE catalog; --"),
    ('SELECT @n;', {'n': 13}, 13),
    ('SELECT $n;', {'n': 14}, 14),
])
def test_sqlite_supported_ordinary_syntax_executes_exactly_once(sql, params, expected):
    parsed = parse_action(query(sql, params))
    assert parsed['sql'] == sql and parsed['params'] == params
    with open_episode(make_stream(92000, 'reuse').ordinary[0]) as session:
        result = session.query(parsed['sql'], parsed['params'])
        assert result.error is None and result.rows == ((expected,),)
        assert session.select_attempts == result.attempt == 1


@pytest.mark.parametrize('sql', [
    'DELETE FROM catalog;',
    "INSERT INTO catalog VALUES ('injected','injected','injected');",
    'UPDATE catalog SET description = NULL;',
    'DROP TABLE catalog;',
    'PRAGMA query_only=OFF;',
    "ATTACH DATABASE ':memory:' AS other;",
    'WITH x AS (SELECT 1) DELETE FROM catalog;',
    'SELECT 1; SELECT 2;',
    'SELECT 1; DELETE FROM catalog;',
    "SELECT load_extension('not-an-extension');",
])
def test_parser_does_not_authorize_writes_or_multiple_statements(sql):
    parsed = parse_action(query(sql))
    assert parsed['sql'] == sql
    with open_episode(make_stream(92000, 'reuse').ordinary[0]) as session:
        before = session.query('SELECT COUNT(*) FROM catalog', {})
        blocked = session.query(parsed['sql'], parsed['params'])
        after = session.query('SELECT COUNT(*) FROM catalog', {})
        assert blocked.error is not None and blocked.attempt == 2
        assert before.rows == after.rows and after.error is None
        assert session.select_attempts == 3


@pytest.mark.parametrize('sql', ['', 'SELECT FROM', 'SELECT :missing'])
def test_bad_sql_reaches_the_charged_executor(sql):
    action = parse_action(query(sql))
    with open_episode(make_stream(92000, 'reuse').ordinary[0]) as session:
        result = session.query(action['sql'], action['params'])
        assert result.error is not None and result.attempt == session.select_attempts == 1


@pytest.mark.parametrize('params', [
    {'x': True}, {'x': []}, {'x': {}}, {'x': float('inf')},
    {'x': 2**63}, {'x': -(2**63)-1}, {'x': 'é'*2049},
    {'bad-name': 1}, {'x'*65: 1}, {f'p{i}': i for i in range(129)},
])
def test_bad_binding_types_sizes_and_names_are_rejected(params):
    with pytest.raises(ValueError):
        parse_action(query('SELECT :x', params))


@pytest.mark.parametrize('text', [
    '{"action":"QUERY","sql":"SELECT 1","sql":"SELECT 2","params":{}}',
    '{"action":"QUERY","sql":"SELECT :x","params":{"x":1,"x":2}}',
    '{"action":"QUERY","sql":"SELECT :x","params":{"x":NaN}}',
    '{"action":"QUERY","sql":"SELECT :x","params":{"x":1e400}}',
    '{"action":"QUERY","sql":1,"params":{}}',
    '{"action":"QUERY","sql":"SELECT 1","params":{},"extra":1}',
])
def test_strict_json_envelope_is_preserved(text):
    with pytest.raises(ValueError):
        parse_action(text)


def test_sql_and_complete_action_byte_ceilings_remain_bounded():
    with pytest.raises(ValueError):
        parse_action(query('SELECT 1' + ' '*16384))
    with pytest.raises(ValueError):
        parse_action(query('SELECT 1', {'a': 'a'*4096, 'b': 'b'*4096, 'c': 'c'*4096, 'd': 'd'*4096}))


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), '2', None])
def test_answer_remains_a_finite_exact_numeric_type(value):
    with pytest.raises(ValueError):
        parse_action(json.dumps({'action': 'ANSWER', 'value': value}))


def test_answer_and_memory_actions_retain_the_existing_path():
    for action in [
        {'action': 'ANSWER', 'value': 3.25},
        {'action': 'USE', 'entry': 0, 'params': {'n': 2}},
        {'action': 'COMPOSE', 'entry': 0, 'params': {'n': 2},
         'outer_sql': 'SELECT SUM(value) FROM reused', 'outer_params': {}},
    ]:
        encoded = json.dumps(action)
        assert parse_action(encoded) == strict_parse(encoded)
    with pytest.raises(ValueError):
        parse_action(json.dumps({'action': 'USE', 'entry': True, 'params': {}}))
    with pytest.raises(FragmentError):
        Fragment.from_query('SELECT :n AS value', {'n': 2}).compose('SELECT value FROM reused;', {}, alias='reused')
    with pytest.raises(FragmentError):
        Fragment.from_query('SELECT 7;', {'unused': 99})
    assert parse_action(query('SELECT 7;', {'unused': 99}))['sql'] == 'SELECT 7;'
