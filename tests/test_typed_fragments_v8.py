"""Typed compiler/SQLite correspondence and adversarial untrusted-data tests."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
from itertools import product
import json
from pathlib import Path
import sqlite3
import struct

import pytest

from witness_cl.fragments_v8 import (
    Fragment, FragmentError, Hole, MAX_PAYLOAD_BYTES, MAX_SQL_BYTES, MAX_SYNTAX_NODES,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts/v8'


@pytest.fixture(scope='module')
def oracle():
    return [json.loads(line) for line in (ARTIFACTS / 'formal-fragments.jsonl').read_text().splitlines()]


def _parameters(request):
    pairs = {}
    for parameter in request['parameters']:
        value = parameter['value']
        if parameter['kind'] == 'real':
            value = struct.unpack('>d', value['binary64_bits'].to_bytes(8, 'big'))[0]
        if parameter['name'] in pairs:
            assert type(pairs[parameter['name']]) is type(value)
            assert pairs[parameter['name']] == value
        pairs[parameter['name']] = value
    return pairs


def test_formal_fragment_fixture_has_current_source_provenance(oracle):
    report = json.loads((ARTIFACTS / 'formal-audit.json').read_text())
    assert report['passed']
    assert report['fragment_fixture']['line_count'] == len(oracle)
    assert report['fragment_fixture']['exit_code'] == 0
    assert hashlib.sha256((ARTIFACTS / 'formal-fragments.jsonl').read_bytes()).hexdigest() == (
        report['fragment_fixture']['sha256'])
    for source, digest in {**report['source_sha256'], **report['build_input_sha256']}.items():
        assert hashlib.sha256((ROOT / 'formal' / source).read_bytes()).hexdigest() == digest, source
    for source, digest in report['runtime_source_sha256'].items():
        assert hashlib.sha256((ROOT / source).read_bytes()).hexdigest() == digest, source
    names = report['theorems_by_file']['WitnessCL/TypedFragments.lean']
    assert report['new_theorem_count'] == len(names) == 12
    assert len(report['theorem_axioms']) == report['theorem_count'] == 89
    assert all(name in report['theorem_axioms'] for name in names)
    assert not report['source_placeholder_or_custom_axiom_tokens']
    assert not report['unexpected_axioms']


def test_fixture_covers_named_repeats_quotes_real_null_and_hostile_text(oracle):
    header = oracle[0]
    assert header['schema'] == 'witness-cl-typed-fragments-v1'
    rows = [r for r in oracle if r['kind'] == 'request']
    assert len(rows) == 36
    assert {(r['source_id'], r['amount'], r['label']) for r in rows} == set(product(
        range(header['source_count']), header['amounts'], header['labels']))
    assert len(oracle) == 38


def test_every_lean_witness_and_composition_matches_python_and_sqlite(oracle):
    with sqlite3.connect(':memory:') as database:
        database.execute('CREATE TABLE sentinel(value INTEGER)')
        database.execute('INSERT INTO sentinel VALUES (42)')
        for row in oracle:
            if row['kind'] != 'request':
                continue
            original = row['original']
            fragment = Fragment.from_query(original['sql'], _parameters(original))
            compiled = fragment.compile()
            assert original == row['expanded']
            assert compiled == fragment.original_prepared_query
            assert compiled.sql == row['expanded']['sql']
            assert compiled.parameters == _parameters(row['expanded'])
            assert compiled.sql == row['changed']['sql']
            changed = fragment.compile(_parameters(row['changed']))
            assert changed.sql == compiled.sql
            # Witness replay is literal request identity, including SQL bytes.
            source_answer = database.execute(original['sql'], _parameters(original)).fetchall()
            assert database.execute(compiled.sql, compiled.parameters).fetchall() == source_answer
            composed = fragment.compose('SELECT amount + :amount AS combined FROM saved',
                                        {'amount': 3}, alias='saved')
            assert composed.sql == row['composition']['sql']
            assert composed.parameters == _parameters(row['composition'])
            # The two scopes intentionally reuse the name "amount" with
            # different values. Structural renaming must preserve both.
            result = database.execute(composed.sql, composed.parameters).fetchall()
            amount_column = next(i for i, description in enumerate(
                database.execute(compiled.sql, compiled.parameters).description)
                                 if description[0] == 'amount')
            assert result == [(source_answer[0][amount_column] + 3,)]
        assert database.execute('SELECT value FROM sentinel').fetchall() == [(42,)]


def test_new_aggregate_composition_matches_explicit_query_on_same_database():
    with sqlite3.connect(':memory:') as database:
        database.execute('CREATE TABLE lines(team TEXT, item TEXT, amount INTEGER)')
        database.executemany('INSERT INTO lines VALUES (?, ?, ?)',
                             [('A', 'x', 2), ('A', 'y', 3), ('A', 'z', 1), ('B', 'q', 50)])
        sql = 'SELECT item, amount FROM lines WHERE team = :team'
        original = database.execute(sql, {'team': 'A'}).fetchall()
        assert original == [('x', 2), ('y', 3), ('z', 1)]
        fragment = Fragment.from_query(sql, {'team': 'A'})
        query = fragment.compose('SELECT SUM(amount) * :scale FROM learned WHERE amount > :threshold',
                                 {'scale': 2, 'threshold': 1}, alias='learned')
        composed = database.execute(query.sql, query.parameters).fetchall()
        expanded = database.execute('SELECT SUM(amount) * 2 FROM lines WHERE team = ? AND amount > 1',
                                    ('A',)).fetchall()
        assert composed == expanded == [(10,)]


def test_fragment_and_serialized_roundtrip_are_immutable_and_exact():
    bindings = {'label': "O'Reilly", 'value': -0.0}
    fragment = Fragment.from_query('SELECT :value, :label', bindings)
    bindings['label'] = 'mutated'
    payload = fragment.to_dict()
    assert Fragment.from_dict(payload) == fragment
    assert json.dumps(Fragment.from_dict(payload).to_dict(), sort_keys=True) == json.dumps(payload, sort_keys=True)
    assert fragment.compile().parameters['label'] == "O'Reilly"
    assert struct.pack('>d', fragment.compile().parameters['value']) == struct.pack('>d', -0.0)
    detached = fragment.compile().parameters
    detached['label'] = 'mutated'
    payload['witness']['label'] = 'mutated'
    assert fragment.compile().parameters['label'] == "O'Reilly"
    with pytest.raises(FrozenInstanceError):
        fragment.sql = 'SELECT 0'
    with pytest.raises(FrozenInstanceError):
        fragment.holes[0].name = 'changed'


@pytest.mark.parametrize('change', [
    lambda p: p.update(extra='field'),
    lambda p: p.update(format_version=True),
    lambda p: p.update(sha256='0' * 64),
    lambda p: p.update(sql='SELECT :x + 1'),
    lambda p: p['holes'][0].update(kind='text'),
    lambda p: p['witness'].update(x=True),
    lambda p: p['witness'].update(x=4),
])
def test_serialized_fragment_rejects_tampering(change):
    payload = deepcopy(Fragment.from_query('SELECT :x', {'x': 3}).to_dict())
    change(payload)
    with pytest.raises(FragmentError):
        Fragment.from_dict(payload)


@pytest.mark.parametrize('bad', [True, False, float('nan'), float('inf'), -float('inf'),
                                 2**63, -(2**63)-1, [], {}, b'text', 'NUL\x00text'])
def test_binding_boundary_rejects_unsupported_or_nonfinite_values(bad):
    with pytest.raises(FragmentError):
        Fragment.from_query('SELECT :x', {'x': bad})


@pytest.mark.parametrize('original,replacement', [(1, 1.0), (1.0, 1), (None, 'NULL'), ('3', 3), (None, 0)])
def test_new_bindings_preserve_exact_witness_types(original, replacement):
    fragment = Fragment.from_query('SELECT :x', {'x': original})
    with pytest.raises(FragmentError, match='exact types'):
        fragment.compile({'x': replacement})


@pytest.mark.parametrize('sql,bindings', [
    ('SELECT :x -- hidden', {'x': 1}),
    ('SELECT /* hidden */ :x', {'x': 1}),
    ('SELECT :x; SELECT 2', {'x': 1}),
    ('SELECT :x;', {'x': 1}),
    ('SELECT ?', {}), ('SELECT @x', {'x': 1}), ('SELECT $x', {'x': 1}),
    ('SELECT :1', {}), ('SELECT :', {}),
    ('SELECT :xé', {'x': 1}), ('SELECT :x😀', {'x': 1}),
    ("SELECT 'unterminated", {}), ('SELECT "unterminated', {}),
    ('SELECT `unterminated', {}), ('SELECT [unterminated', {}),
    ('SELECT :missing', {}), ('SELECT 1', {'unused': 1}),
    ('DELETE FROM example', {}), ('', {}), ('SELECT 1\x00', {}),
])
def test_unsupported_sql_lexical_forms_fail_closed(sql, bindings):
    with pytest.raises(FragmentError):
        Fragment.from_query(sql, bindings)


@pytest.mark.parametrize('quoted', ["':inside'';--/*?@$'", '"col:inside"";--"',
                                   '`col:inside``;--`', '[col:inside;--]'])
def test_quoted_text_is_never_a_parameter_or_comment(quoted):
    sql = f'SELECT {quoted}, :actual'
    fragment = Fragment.from_query(sql, {'actual': 'safe'})
    assert fragment.compile().sql == sql
    assert fragment.holes == (Hole('actual', 'text'),)
    composite = fragment.compose('SELECT :actual FROM saved', {'actual': 'outer'}, alias='saved')
    assert quoted in composite.sql
    assert ':wcl_inner_0' in composite.sql and ':wcl_outer_0' in composite.sql


def test_sqlite_executes_all_supported_identifier_quote_styles():
    with sqlite3.connect(':memory:') as database:
        database.execute('CREATE TABLE t("c:one" INTEGER, "c`two" INTEGER, "c three" INTEGER)')
        database.execute('INSERT INTO t VALUES (1, 2, 3)')
        fragment = Fragment.from_query('SELECT "c:one", `c``two`, [c three], :x FROM t', {'x': 4})
        compiled = fragment.compile()
        assert database.execute(compiled.sql, compiled.parameters).fetchall() == [(1, 2, 3, 4)]


def test_expansion_never_interpolates_text_values_into_sql():
    hostile = "'); ATTACH DATABASE '/tmp/escape' AS other; --"
    fragment = Fragment.from_query('SELECT :value', {'value': 'ordinary'})
    compiled = fragment.compile({'value': hostile})
    assert compiled.sql == 'SELECT :value'
    assert hostile not in compiled.sql
    with sqlite3.connect(':memory:') as database:
        assert database.execute(compiled.sql, compiled.parameters).fetchall() == [(hostile,)]
        assert len(database.execute('PRAGMA database_list').fetchall()) == 1


@pytest.mark.parametrize('alias', ['x; DROP TABLE t', 'a.b', 'x"', '', 'x-y', 'é'])
def test_composition_alias_cannot_inject_identifiers(alias):
    fragment = Fragment.from_query('SELECT :x AS amount', {'x': 1})
    with pytest.raises(FragmentError, match='alias'):
        fragment.compose('SELECT amount FROM saved', alias=alias)


def test_name_prefixes_remain_disjoint_for_repeated_and_similar_names():
    fragment = Fragment.from_query('SELECT :a + :aa + :a + :wcl_outer_0 AS amount',
                                   {'a': 1, 'aa': 2, 'wcl_outer_0': 3})
    compiled = fragment.compose('SELECT amount + :a + :wcl_inner_0 FROM saved',
                                {'a': 4, 'wcl_inner_0': 5}, alias='saved')
    assert len(compiled.parameters) == 5
    with sqlite3.connect(':memory:') as database:
        assert database.execute(compiled.sql, compiled.parameters).fetchall() == [(16,)]


def test_caps_include_utf8_bytes_syntax_and_retained_witness_payload():
    with pytest.raises(FragmentError, match='byte limit'):
        Fragment.from_query("SELECT '" + 'é' * (MAX_SQL_BYTES // 2) + "'")
    with pytest.raises(FragmentError, match='syntax-node'):
        Fragment.from_query('SELECT ' + ' + '.join([':x'] * MAX_SYNTAX_NODES), {'x': 1})
    with pytest.raises(FragmentError, match='payload limit'):
        Fragment.from_query('SELECT :x', {'x': 'x' * MAX_PAYLOAD_BYTES})
    fragment = Fragment.from_query('SELECT :x', {'x': 'small'})
    with pytest.raises(FragmentError, match='payload limit'):
        fragment.compile({'x': 'x' * MAX_PAYLOAD_BYTES})


def test_sql_chunks_still_require_the_external_read_only_executor():
    # A parameter lexer does not establish SQL authority. This prefix-valid
    # write reaches the real executor as untrusted SQL, which must reject it.
    fragment = Fragment.from_query('WITH x AS (SELECT 1) DELETE FROM protected')
    with sqlite3.connect(':memory:') as database:
        database.execute('CREATE TABLE protected(value INTEGER)')
        database.execute('INSERT INTO protected VALUES (9)')
        database.set_authorizer(lambda action, *args:
                                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_DELETE else sqlite3.SQLITE_OK)
        with pytest.raises(sqlite3.DatabaseError):
            database.execute(fragment.compile().sql, fragment.compile().parameters)
        assert database.execute('SELECT * FROM protected').fetchall() == [(9,)]


def test_observed_check_does_not_identify_units_or_protect_first_drift_failure(oracle):
    row = oracle[-1]
    assert row['kind'] == 'guard_counterexample'
    assert [scale * row['observed_amount'] for scale in row['possible_scales']] == [0, 0]
    assert [scale * row['future_amount'] for scale in row['possible_scales']] == [1, 100]
    assert row['guard'] is True
    assert row['guarded_answer'] == 1 != row['ordinary_answer'] == 100
    assert row['rejected_answer'] == row['ordinary_answer']
