"""Regression and authority checks for the v9 transient COUNT(*) exception."""
import sqlite3

import pytest

from witness_cl.sql_env_v8 import MAX_SELECTS, open_episode as open_v8
from witness_cl.sql_env_v9 import EpisodeSessionV9, make_stream, open_episode


# Exact valid query rejected in the saved 92000 development diagnostic, index 3.
CURRENT_NORTH = '''WITH current_profiles AS (
    SELECT c_cyvths, MAX(c_dqxvqb) AS max_revision
    FROM r_sbepiz GROUP BY c_cyvths
), north_customers AS (
    SELECT DISTINCT sp.c_cyvths FROM r_sbepiz sp
    JOIN current_profiles cp ON sp.c_cyvths = cp.c_cyvths
        AND sp.c_dqxvqb = cp.max_revision
    WHERE sp.c_fsmhkb = 'North'
) SELECT COUNT(*) FROM north_customers'''


@pytest.fixture(scope='module')
def spec():
    return make_stream(92000, 'reuse', split='development').ordinary[3]


class ObservedSession(EpisodeSessionV9):
    def __init__(self, *args, **kwargs):
        self.authorizations = []
        super().__init__(*args, **kwargs)

    def _authorize(self, action, first, second, database, source):
        decision = super()._authorize(action, first, second, database, source)
        self.authorizations.append((action, first, second, database, source, decision))
        return decision


def test_exact_observed_current_profile_query_is_correct_and_charged(spec):
    with open_v8(spec) as old:
        assert old.query(CURRENT_NORTH).error == 'not authorized'
    with ObservedSession(spec) as new:
        result = new.query(CURRENT_NORTH)
        assert result.error is None and result.rows == ((2,),)
        assert result.attempt == new.select_attempts == 1
        assert new.answer(2).reward == 1.0
        assert (sqlite3.SQLITE_READ, 'north_customers', '', None, None,
                sqlite3.SQLITE_OK) in new.authorizations
        assert new.setup_seconds > 0 and new.query_seconds > 0


@pytest.mark.parametrize('sql,expected', [
    ('WITH x AS (SELECT 1 AS v) SELECT COUNT(*) FROM x', 1),
    ('WITH x AS (VALUES (1),(2)), y AS (SELECT * FROM x) SELECT COUNT(*) FROM y', 2),
    ('SELECT COUNT(*) FROM (WITH x AS (SELECT 1) SELECT * FROM x)', 1),
    ('WITH "Count Rows" AS (SELECT 1 UNION ALL SELECT 2) SELECT COUNT(*) FROM "Count Rows"', 2),
    ('WITH "café" AS (SELECT 1) SELECT COUNT(*) FROM "café"', 1),
    ('WITH x AS MATERIALIZED (SELECT 1) SELECT COUNT(*) FROM x', 1),
    ('WITH x AS (SELECT * FROM catalog) SELECT COUNT(*) FROM x', 24),
])
def test_ordinary_nonrecursive_relations_and_quoted_names_remain_supported(spec, sql, expected):
    with open_episode(spec) as db:
        result = db.query(sql)
        assert result.error is None and result.rows == ((expected,),)
        assert result.attempt == 1


@pytest.mark.parametrize('sql', [
    'SELECT COUNT(*) FROM sqlite_schema',
    'SELECT COUNT(*) FROM main.sqlite_schema',
    'SELECT COUNT(*) FROM temp.sqlite_schema',
    'SELECT COUNT(*) FROM SQLITE_MASTER',
    'WITH x AS (SELECT 1 FROM sqlite_schema) SELECT COUNT(*) FROM x',
    'WITH sqlite_schema AS (SELECT 1) SELECT COUNT(*) FROM main.sqlite_schema',
    "SELECT COUNT(*) FROM pragma_table_info('catalog')",
    'SELECT COUNT(*) FROM pragma_table_list',
    "SELECT COUNT(*) FROM json_each('[1,2]') AS harmless",
    "SELECT COUNT(*) FROM JSON_TREE('[1,2]')",
    'SELECT COUNT(*) FROM dbstat AS harmless',
    'SELECT COUNT(*) FROM main.dbstat',
    "WITH unused AS (WITH json_each AS (SELECT 99) SELECT * FROM json_each) SELECT COUNT(*) FROM json_each('[1,2]')",
    "WITH unused AS (WITH dbstat AS (SELECT 99) SELECT * FROM dbstat) SELECT COUNT(*) FROM dbstat",
    "WITH json_each AS (SELECT 1) SELECT COUNT(*) FROM main.json_each('[1,2]')",
    'WITH x AS (SELECT 1) DELETE FROM catalog',
    "UPDATE catalog SET description='changed'",
    'PRAGMA query_only=OFF',
    "ATTACH DATABASE ':memory:' AS other",
    'BEGIN TRANSACTION',
    "SELECT load_extension('forbidden')",
    "SELECT readfile('/etc/passwd')",
    "SELECT writefile('/tmp/forbidden-v9','x')",
    "WITH x AS (SELECT readfile('/etc/passwd')) SELECT * FROM x",
    'WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x WHERE n<4) SELECT COUNT(*) FROM x',
])
def test_exception_cannot_read_forbidden_objects_or_execute_unsafe_actions(spec, sql):
    with open_episode(spec) as db:
        before = db.query('SELECT * FROM catalog')
        result = db.query(sql)
        after = db.query('SELECT * FROM catalog')
        assert result.error is not None, sql
        assert result.rows == () and result.attempt == 2
        assert db.select_attempts == 3 and before.rows == after.rows


def test_module_inventory_and_database_column_action_boundaries(spec):
    with open_episode(spec) as db:
        assert db._virtual_module_names
        for module in db._virtual_module_names:
            assert db._authorize(sqlite3.SQLITE_READ, module.upper(), '', None, None) == sqlite3.SQLITE_DENY
        for action, first, second, database in (
            (sqlite3.SQLITE_READ, 'new_cte', 'private_column', None),
            (sqlite3.SQLITE_READ, 'new_cte', '', 'main'),
            (sqlite3.SQLITE_READ, 'new_cte', '', 'temp'),
            (sqlite3.SQLITE_READ, 'new_cte', '', 'attached'),
            (sqlite3.SQLITE_READ, 'SQLITE_SCHEMA', '', None),
            (sqlite3.SQLITE_READ, 'PRAGMA_TABLE_LIST', '', None),
            (sqlite3.SQLITE_UPDATE, 'new_cte', '', None),
        ):
            assert db._authorize(action, first, second, database, None) == sqlite3.SQLITE_DENY
        # Constructor restored the authorizer after its private module inventory.
        assert db.query('SELECT * FROM sqlite_schema').error is not None


def test_transient_reads_preserve_query_and_learning_phase_limits(spec):
    sql = 'WITH x AS (SELECT :value) SELECT COUNT(*) FROM x'
    with open_episode(spec, allow_learning_checks=True) as db:
        assert db.query(sql, {'value': 9}).rows == ((1,),)
        db.answer(0)
        assert db.query(sql, {'value': 9}).error == 'episode is closed for queries'
        for index in range(1, MAX_SELECTS):
            assert db.query(sql, {'value': index}, learning_check=True).attempt == index + 1
        stopped = db.query(sql, {'value': 9}, learning_check=True)
        assert stopped.error == 'SELECT attempt budget exhausted'
        assert db.select_attempts == MAX_SELECTS


def test_transient_reads_preserve_vm_work_budget(spec):
    with open_episode(spec, max_vm_steps=100) as db:
        result = db.query('WITH x AS (SELECT * FROM catalog) SELECT COUNT(*) FROM x a CROSS JOIN x b CROSS JOIN x c')
        assert result.error is not None and result.attempt == 1
        assert db.vm_steps >= 100
