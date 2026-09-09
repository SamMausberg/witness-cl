"""Real SQLite semantic fixtures for the supported source-lifting language."""
from dataclasses import asdict, FrozenInstanceError
import json
import sqlite3

import pytest

from witness_cl.source_views import SourceView, UnsupportedSource, lift_source, reconstruct


SCHEMA = '''CREATE TABLE orders (
    id INTEGER, customer INTEGER, amount NUMERIC, qty INTEGER,
    region TEXT, status TEXT);
CREATE TABLE profiles (customer INTEGER, revision INTEGER, active INTEGER, tier TEXT);
CREATE TABLE refunds (order_id INTEGER, amount NUMERIC);'''
ROWS = [(1, 10, 125, 2, 'North', 'confirmed'),
        (2, 10, None, 1, 'North', 'confirmed'),
        (3, 20, 450, 3, 'South', 'pending'),
        (4, 30, 125, 4, 'North', 'confirmed'),
        (5, 30, 0, 1, 'North', 'confirmed')]


def database(rows=ROWS):
    db = sqlite3.connect(':memory:')
    db.executescript(SCHEMA)
    db.executemany('INSERT INTO orders VALUES (?,?,?,?,?,?)', rows)
    db.executemany('INSERT INTO profiles VALUES (?,?,?,?)', [
        (10, 1, 0, 'Silver'), (10, 2, 1, 'Gold'),
        (20, 1, 1, 'Silver'), (30, 1, 1, 'Gold')])
    db.executemany('INSERT INTO refunds VALUES (?,?)', [(1, 50), (1, 25), (4, None)])
    return db


def scalar(db, sql, params=None):
    result = db.execute(sql, params or {}).fetchall()
    assert len(result) == 1 and len(result[0]) == 1
    return result[0][0]


@pytest.mark.parametrize('rows', [ROWS, [], [ROWS[1]], [ROWS[2]], ROWS + [ROWS[0]]])
@pytest.mark.parametrize('sql,params', [
    ('SELECT COALESCE(SUM(amount / 100.0 * qty), 0) FROM orders', {}),
    ('SELECT SUM(amount / 100 * qty) FROM orders', {}),
    ('SELECT AVG(COALESCE(amount, 0)) FROM orders', {}),
    ('SELECT AVG(amount) FROM orders', {}),
    ('SELECT COUNT(*) FROM orders', {}),
    ('SELECT COUNT(amount) FROM orders', {}),
    ('SELECT COUNT(DISTINCT customer) FROM orders', {}),
    ('SELECT SUM(DISTINCT amount) FROM orders', {}),
    ('SELECT MIN(amount) + MAX(amount) FROM orders', {}),
    ('SELECT COALESCE(AVG(amount) - SUM(qty) / NULLIF(COUNT(*),0), 0) FROM orders', {}),
    ("SELECT SUM(amount) / :scale FROM orders WHERE region = 'North' AND status=:s",
     {'scale': 100.0, 's': 'confirmed', 'unused': 19}),
    ('SELECT ROUND(SUM(CAST(amount AS REAL))/100.0, 2) AS total FROM orders;', {}),
    ('''SELECT COALESCE(SUM(o.amount/100.0*o.qty),0) FROM orders o
        JOIN profiles p ON o.customer=p.customer
        WHERE p.active=1 AND p.tier='Gold' AND o.region='North' ''', {}),
    ('''WITH current AS (SELECT * FROM profiles WHERE active=1),
        refunded AS (SELECT order_id,SUM(amount)/100.0 AS refund FROM refunds GROUP BY order_id)
        SELECT COALESCE(SUM(o.amount/100.0*o.qty-COALESCE(r.refund,0)),0)
        FROM orders o JOIN current p ON p.customer=o.customer
        LEFT JOIN refunded r ON r.order_id=o.id WHERE p.tier='Gold' ''', {}),
    ('''SELECT SUM(o.amount) FROM orders o JOIN profiles p ON p.customer=o.customer
        WHERE p.revision=(SELECT MAX(q.revision) FROM profiles q
                          WHERE q.customer=p.customer) AND p.tier='Gold' ''', {}),
    ('''SELECT SUM(x.total) FROM
        (SELECT customer,SUM(amount) AS total FROM orders GROUP BY customer) x''', {}),
])
def test_reconstructs_real_sqlite_aggregates_with_nulls_empty_rows_and_duplicates(rows, sql, params):
    view = lift_source(sql, params, SCHEMA, 'Own answered query?')
    with database(rows) as db:
        expected = scalar(db, sql, params)
        actual = scalar(db, *reconstruct(view))
        assert actual == expected
        cursor = db.execute(view.sql, dict(view.params))
        assert tuple(c[0] for c in cursor.description) == view.columns


def test_lift_exposes_qualified_join_columns_and_preserves_numeric_semantic_constants():
    sql = '''SELECT SUM(COALESCE(o.amount,0)/100.0*o.qty) FROM orders o
        JOIN profiles p ON p.customer=o.customer
        WHERE p.active=1 AND p.tier='Gold' AND o.region='North' AND o.amount>0'''
    view = lift_source(sql, {}, SCHEMA, 'Gross?')
    assert view.measure_columns == ('m0',)
    assert view.lineage['m0'] == 'COALESCE("o"."amount", 0) / 100.0 * "o"."qty"'
    assert '"o"."customer"' in view.lineage.values()
    assert '"p"."customer"' in view.lineage.values()
    assert set(view.params.values()) == {'Gold', 'North'}
    assert '"p"."active" = 1' in view.sql
    assert '"o"."amount" > 0' in view.sql
    assert '100.0' in view.sql
    assert view.source_sql == sql and view.source_params == {}


def test_predicate_rebinding_is_explicit_and_does_not_remove_training_scope():
    view = lift_source("SELECT SUM(amount) FROM orders WHERE region='North'", {}, SCHEMA, 'Sum?')
    assert view.params == {'sv_text_0': 'North'}
    with database() as db:
        assert scalar(db, *reconstruct(view)) == 250
        assert scalar(db, view.reconstruction_sql, {'sv_text_0': 'South'}) == 450
    assert view.params == {'sv_text_0': 'North'}


def test_projection_only_bindings_do_not_leak_into_view_and_generated_names_are_fresh():
    sql = "SELECT SUM(amount)/:scale FROM orders WHERE region='North' AND qty>:sv_text_0"
    params = {'scale': 100.0, 'sv_text_0': 0, 'unused': 'preserved only as provenance'}
    view = lift_source(sql, params, SCHEMA, 'Sum?')
    assert view.params == {'sv_text_0': 0, 'sv_text_1': 'North'}
    assert view.reconstruction_params == {'scale': 100.0, 'sv_text_0': 0, 'sv_text_1': 'North'}
    assert view.source_params == params
    params['scale'] = 3
    assert view.source_params['scale'] == 100.0


def test_measure_deduplication_does_not_conflate_distinct_and_ordinary_aggregates():
    view = lift_source('SELECT SUM(amount)-SUM(DISTINCT amount)+COUNT(amount) FROM orders',
                       {}, SCHEMA, 'Aggregate?')
    assert view.measure_columns == ('m0',)
    with database() as db:
        assert scalar(db, *reconstruct(view)) == 129


@pytest.mark.parametrize('aggregate,nonempty,empty', [
    ('COALESCE(SUM(amount),0)', 700, 0), ('COUNT(*)', 5, 0), ('AVG(amount)', 175, None),
])
def test_empty_intervention_keeps_outer_semantics_and_uses_same_bindings(aggregate, nonempty, empty):
    view = lift_source(f'SELECT {aggregate} FROM orders', {}, SCHEMA, 'Value?')
    with database() as db:
        assert scalar(db, *reconstruct(view)) == nonempty
        assert scalar(db, *reconstruct(view, empty=True)) == empty
    assert reconstruct(view)[1] == reconstruct(view, empty=True)[1]


def test_empty_check_can_expose_constant_count_arithmetic_as_noncontributing():
    view = lift_source('SELECT COUNT(*) * 0 + 3 FROM orders', {}, SCHEMA, 'Value?')
    with database() as db:
        assert scalar(db, *reconstruct(view)) == scalar(db, *reconstruct(view, empty=True)) == 3


def test_sum_reconstruction_does_not_identify_null_semantics_for_future_average():
    """Two all-database SUM-equivalent row views disagree on a later AVG task."""
    one = lift_source('SELECT COALESCE(SUM(amount),0) FROM orders', {}, SCHEMA, 'Sum?')
    two = lift_source('SELECT COALESCE(SUM(COALESCE(amount,0)),0) FROM orders', {}, SCHEMA, 'Sum?')
    rows = [(1, 1, None, 1, 'North', 'confirmed'), (2, 2, 2, 1, 'North', 'confirmed')]
    with database(rows) as db:
        assert scalar(db, *reconstruct(one)) == scalar(db, *reconstruct(two)) == 2
        assert scalar(db, *reconstruct(one, empty=True)) == 0
        assert scalar(db, *reconstruct(two, empty=True)) == 0
        assert scalar(db, f'SELECT AVG(m0) FROM ({one.sql})', one.params) == 2
        assert scalar(db, f'SELECT AVG(m0) FROM ({two.sql})', two.params) == 1


def test_zero_and_null_measure_interventions_are_distinct_for_count():
    view = lift_source('SELECT COUNT(*) FROM orders', {}, SCHEMA, 'Count?')
    with database() as db:
        assert scalar(db, f'SELECT COUNT(0) FROM ({view.sql})') == 5
        assert scalar(db, f'SELECT COUNT(NULL) FROM ({view.sql})') == 0


def test_nested_cte_names_and_reconstruction_aliases_cannot_capture_original_references():
    sql = '''WITH sv_reconstruct AS (SELECT amount FROM orders),
        sv_empty AS (SELECT * FROM sv_reconstruct)
        SELECT SUM(amount) FROM sv_empty'''
    view = lift_source(sql, {}, SCHEMA, 'Sum?')
    with database() as db:
        assert scalar(db, *reconstruct(view)) == 700
        assert scalar(db, *reconstruct(view, empty=True)) is None


def test_quoted_identifiers_and_sql_shaped_literal_are_not_interpreted_as_tokens():
    schema = 'CREATE TABLE "Odd Table" ("Amount $" REAL, "Where?" TEXT)'
    sql = '''SELECT SUM("Amount $") FROM "Odd Table" WHERE "Where?"='-- ; ? :x '' North' '''
    view = lift_source(sql, {}, schema, 'Sum?')
    with sqlite3.connect(':memory:') as db:
        db.execute(schema)
        db.execute('INSERT INTO "Odd Table" VALUES (?,?)', (3.5, "-- ; ? :x ' North"))
        assert scalar(db, *reconstruct(view)) == 3.5


def test_case_insensitive_sqlite_public_schema_resolution():
    view = lift_source('SELECT SUM(AMOUNT) FROM ORDERS', {}, SCHEMA, 'Sum?')
    with database() as db:
        assert scalar(db, *reconstruct(view)) == 700


def test_serialization_is_deterministic_validated_and_mapping_snapshots_are_immutable():
    view = lift_source("SELECT SUM(amount) FROM orders WHERE region='North'", {}, SCHEMA, 'Sum?')
    encoded = json.loads(json.dumps(view.to_dict()))
    assert SourceView.from_dict(encoded) == view
    assert json.loads(json.dumps(asdict(view))) == encoded
    again = lift_source(view.source_sql, {}, SCHEMA, 'Different wording?')
    assert again.key == view.key
    with pytest.raises(FrozenInstanceError):
        view.question = 'changed'
    for mapping in (view.params, view.source_params, view.lineage, view.column_origins,
                    view.reconstruction_params):
        with pytest.raises(TypeError):
            mapping['bad'] = 3
        with pytest.raises(TypeError):
            mapping.update({'bad': 3})
    encoded['sql'] = 'SELECT 3'
    with pytest.raises(UnsupportedSource, match='key'):
        SourceView.from_dict(encoded)


@pytest.mark.parametrize('sql', [
    'SELECT SUM(amount), COUNT(*) FROM orders',
    'SELECT amount FROM orders',
    'SELECT SUM(amount)+qty FROM orders',
    'SELECT SUM(amount) FROM orders GROUP BY region',
    'SELECT SUM(amount) FROM orders HAVING SUM(amount)>0',
    'SELECT SUM(amount) FROM orders ORDER BY amount',
    'SELECT SUM(amount) FROM orders LIMIT 1',
    'SELECT DISTINCT SUM(amount) FROM orders',
    'SELECT SUM(amount) OVER () FROM orders',
    'SELECT SUM(amount) FILTER (WHERE qty>0) FROM orders',
    'SELECT SUM(amount) FROM orders UNION SELECT SUM(amount) FROM refunds',
    'SELECT MIN(amount,qty) FROM orders',
    'SELECT GROUP_CONCAT(region) FROM orders',
    'SELECT SUM(random()) FROM orders',
    'SELECT SUM((SELECT MAX(amount) FROM refunds)) FROM orders',
    'SELECT SUM(MAX(amount)) FROM orders',
    'SELECT SUM(amount) FROM orders JOIN profiles USING(customer)',
    'SELECT SUM(amount) FROM orders NATURAL JOIN profiles',
    'WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT SUM(n) FROM x',
    'SELECT SUM(amount) FROM main.orders',
    'SELECT SUM(amount) FROM absent',
    'SELECT SUM(absent) FROM orders',
    'SELECT COUNT(customer) FROM orders JOIN profiles ON orders.customer=profiles.customer',
    'SELECT SUM(x.amount) FROM (SELECT amount, qty AS amount FROM orders) x',
    'SELECT SUM(amount) FROM orders; SELECT 2',
    'SELECT SUM(amount) FROM orders -- discarded comment',
    'SELECT SUM(amount) FROM orders /* discarded comment */',
    'DELETE FROM orders',
    'SELECT SUM(:missing) FROM orders',
    'SELECT SUM(?) FROM orders',
    'SELECT SUM(@n) FROM orders',
    'SELECT SUM($n) FROM orders',
    'SELECT COUNT(*)',
    '',
])
def test_explicit_abstentions_cover_unsupported_syntax_and_ambiguous_scopes(sql):
    with pytest.raises(UnsupportedSource) as error:
        lift_source(sql, {}, SCHEMA, 'Question?')
    assert error.value.reason


@pytest.mark.parametrize('params', [
    {'x': True}, {'x': float('nan')}, {'x': float('inf')}, {'x': 2**63},
    {'x': []}, {'x': {}}, {'x': 'x\x00'}, {'x': 'x'*4097}, {'bad-name': 1},
    {f'x{i}': i for i in range(129)},
])
def test_invalid_bindings_are_explicit_abstentions(params):
    with pytest.raises(UnsupportedSource):
        lift_source('SELECT SUM(amount) FROM orders', params, SCHEMA, 'Question?')


def test_source_and_generated_complexity_limits():
    with pytest.raises(UnsupportedSource, match='byte limit'):
        lift_source('SELECT SUM(amount) FROM orders'+' '*16384, {}, SCHEMA, 'Question?')
    schema = {'wide': {f'c{i}': 'INTEGER' for i in range(128)}}
    with pytest.raises(UnsupportedSource, match='column limit'):
        lift_source('SELECT SUM(c0+1) FROM wide', {}, schema, 'Question?')
    sql = 'SELECT '+ '+'.join(f'SUM(amount+{i})' for i in range(17))+' FROM orders'
    with pytest.raises(UnsupportedSource, match='measure column limit'):
        lift_source(sql, {}, SCHEMA, 'Question?')


def test_invalid_public_schema_abstains_without_database_access():
    for schema in ('DROP TABLE orders', {'orders': ['amount']}, {},
                   {'orders': {'amount': 'REAL'}, 'ORDERS': {'amount': 'REAL'}}):
        with pytest.raises(UnsupportedSource):
            lift_source('SELECT SUM(amount) FROM orders', {}, schema, 'Question?')


@pytest.mark.parametrize('argument', ['gross', '(gross)', '"GROSS"'])
def test_exact_cte_measure_copy_is_exposed_once_and_measure_override_cannot_bypass_it(argument):
    from witness_cl.relational_program import compile_program

    sql = f'''WITH lines AS (SELECT customer, amount/100.0*qty AS gross FROM orders)
              SELECT SUM({argument}) FROM lines'''
    view = lift_source(sql, {}, SCHEMA, 'Gross?')
    assert view.columns == ('c0', 'm0')
    assert view.measure_columns == ('m0',)
    assert view.column_origins == {
        'c0': 'derived_or_unresolved_column', 'm0': 'derived_or_unresolved_column'}
    program = {'op': 'group', 'input': {'op': 'scan', 'view': view.key}, 'keys': [],
               'aggregates': [{'name': 'answer', 'op': 'sum', 'expr': {'op': 'col', 'name': 'm0'}}]}
    actual = compile_program(program, [view])
    zero = compile_program(program, [view], measure_overrides={view.key: {'m0': 0}})
    assert actual.measure_references == ((view.key, 'm0'),)
    with database() as db:
        assert scalar(db, *reconstruct(view)) == 21
        assert scalar(db, actual.prepared.sql, actual.prepared.parameters) == 21
        assert scalar(db, zero.prepared.sql, zero.prepared.parameters) == 0


def test_direct_physical_measure_is_labeled_physical_and_its_duplicate_is_removed():
    view = lift_source('SELECT SUM(amount) FROM orders', {}, SCHEMA, 'Sum?')
    assert view.column_origins['m0'] == 'physical_column'
    assert all(kind == 'physical_column' for kind in view.column_origins.values())
    assert 'c2' not in view.columns
    assert list(view.lineage.values()).count('"orders"."amount"') == 1
    with database() as db:
        assert scalar(db, *reconstruct(view)) == 700


def test_origin_metadata_distinguishes_expressions_row_markers_and_unresolved_columns():
    view = lift_source('SELECT SUM(amount/100.0)+COUNT(*) FROM orders', {}, SCHEMA, 'Sum and count?')
    assert view.column_origins['m0'] == 'scalar_expression'
    assert view.column_origins['m1'] == 'row_marker'
    assert all(view.column_origins[c] == 'physical_column' for c in view.columns if c.startswith('c'))
    # Even a simple passthrough CTE column is conservatively unresolved.
    cte = lift_source('WITH x AS (SELECT * FROM orders) SELECT SUM(amount) FROM x', {}, SCHEMA, 'Sum?')
    assert set(cte.column_origins.values()) == {'derived_or_unresolved_column'}


def test_distinct_derived_aliases_are_explicitly_unresolved_not_claimed_deduplicated():
    """Exact root-column deduplication is not recursive SQL equivalence analysis."""
    from witness_cl.relational_program import compile_program

    view = lift_source('''WITH lines AS (SELECT amount/100.0 AS gross,
                         amount/100.0 AS another_gross FROM orders)
                         SELECT SUM(gross) FROM lines''', {}, SCHEMA, 'Gross?')
    assert view.columns == ('c1', 'm0')
    assert view.column_origins['c1'] == 'derived_or_unresolved_column'
    program = {'op': 'group', 'input': {'op': 'scan', 'view': view.key}, 'keys': [],
               'aggregates': [{'name': 'answer', 'op': 'sum', 'expr': {'op': 'col', 'name': 'c1'}}]}
    actual = compile_program(program, [view])
    zero = compile_program(program, [view], measure_overrides={view.key: {'m0': 0}})
    assert actual.measure_references == ()
    with database() as db:
        # No measured m-dependence does not establish absence of learned computation.
        assert scalar(db, actual.prepared.sql, actual.prepared.parameters) == 7
        assert scalar(db, zero.prepared.sql, zero.prepared.parameters) == 7
