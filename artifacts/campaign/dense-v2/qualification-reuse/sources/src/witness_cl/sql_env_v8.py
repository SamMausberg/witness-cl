"""Evaluator-owned, bounded SQL episodes for testing learned query abstractions.

Only PublicEpisode, QueryResult and Feedback may cross the learner boundary.
The generator and EpisodeSpec are evaluator fixtures, not a learner API or a
feature library. Query text is ordinary SQLite, not a supplied answer grammar.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import random
import re
import sqlite3
import time
from typing import TypeAlias


Scalar: TypeAlias = int | float | str | None
MAX_SELECTS = 8
MAX_ROWS = 50
MAX_SQL_BYTES = 16_384
MAX_RESULT_BYTES = 65_536
MAX_CELL_BYTES = 4_096
MAX_VM_STEPS = 200_000
MAX_QUERY_SECONDS = 0.25
CONDITIONS = ('reuse', 'nonreuse', 'near_match')
SPLITS = ('development', 'heldout')


@dataclass(frozen=True)
class PublicEpisode:
    question: str
    schema: str
    max_selects: int = MAX_SELECTS


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Scalar, ...], ...]
    error: str | None
    attempt: int
    truncated: bool = False


@dataclass(frozen=True)
class Feedback:
    """Ordinary accuracy only; it never reveals the evaluator's target."""
    reward: float


@dataclass(frozen=True)
class _Table:
    name: str
    columns: tuple[tuple[str, str], ...]
    rows: tuple[tuple[Scalar, ...], ...]

    @property
    def ddl(self) -> str:
        return f'CREATE TABLE {self.name} (' + ', '.join(
            f'{name} {kind}' for name, kind in self.columns) + ');'


@dataclass(frozen=True)
class _Convention:
    cents: bool
    null_is_zero: bool
    history: bool
    current_by_flag: bool


@dataclass(frozen=True)
class SemanticRecipe:
    """Evaluator-only minimal dependency program; never a supplied learner DSL."""
    normalized_query: tuple[str, ...]
    dependencies: tuple[tuple[str, tuple], ...]
    required_relations: tuple[str, ...]
    required_subskills: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict:
        return dict(normalized_query=self.normalized_query, dependencies=self.dependencies,
                    required_relations=self.required_relations,
                    required_subskills=self.required_subskills, fingerprint=self.fingerprint)


@dataclass(frozen=True)
class EpisodeSpec:
    """Hidden evaluator fixture. Never serialize this object into a model call."""
    _public: PublicEpisode
    _tables: tuple[_Table, ...]
    _expected: float
    _gold_sql: str
    _recipe: SemanticRecipe
    _metadata: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class StreamSpec:
    ordinary: tuple[EpisodeSpec, ...]
    old_panel: tuple[EpisodeSpec, ...]
    final_panel: tuple[EpisodeSpec, ...]
    _metadata: tuple[tuple[str, object], ...]

    def evaluator_metadata(self) -> dict:
        """Artifact provenance only; never include this in learner routing."""
        return dict(self._metadata) | {
            'ordinary': [evaluator_metadata(e) for e in self.ordinary],
            'final_panel': [evaluator_metadata(e) for e in self.final_panel],
            'old_panel': 'fixed fresh datasets with ordinary questions 0 through 7 and their original schemas/conventions',
        }


def evaluator_metadata(spec: EpisodeSpec) -> dict:
    return dict(spec._metadata) | {'semantic_recipe': spec._recipe.to_dict()}


def evaluator_recipe(spec: EpisodeSpec) -> SemanticRecipe:
    return spec._recipe


def evaluator_expected(spec: EpisodeSpec) -> float:
    return spec._expected


def evaluator_sql(spec: EpisodeSpec) -> str:
    return spec._gold_sql


_FUNCTIONS = frozenset({
    'abs', 'avg', 'char', 'coalesce', 'concat', 'concat_ws', 'count', 'format',
    'glob', 'hex', 'ifnull', 'iif', 'instr', 'length', 'like', 'lower', 'ltrim',
    'max', 'min', 'nullif', 'printf', 'quote', 'replace', 'round', 'rtrim',
    'sign', 'substr', 'substring', 'sum', 'total', 'trim', 'typeof', 'unicode',
    'upper', 'row_number', 'rank', 'dense_rank', 'first_value', 'last_value',
    'lag', 'lead', 'nth_value', 'ntile', 'percent_rank', 'cume_dist',
})


class EpisodeSession:
    """Evaluator tool adapter; the model receives .public and tool return data.

    This is an in-process capability boundary for a text-only model. It is not
    a Python sandbox for adversarial code that can introspect this object.
    """
    def __init__(self, spec: EpisodeSpec, *, max_vm_steps=MAX_VM_STEPS,
                 max_query_seconds=MAX_QUERY_SECONDS, allow_learning_checks=False):
        if type(spec) is not EpisodeSpec:
            raise ValueError('an evaluator EpisodeSpec is required')
        if type(allow_learning_checks) is not bool:
            raise ValueError('allow_learning_checks must be an explicit boolean')
        self._allow_learning_checks = allow_learning_checks
        if (type(max_vm_steps) is not int or max_vm_steps < 1
                or type(max_query_seconds) not in (int, float)
                or not math.isfinite(max_query_seconds) or max_query_seconds <= 0):
            raise ValueError('positive finite SQL limits required')
        setup_started = time.perf_counter()
        self.public = spec._public
        self._expected = spec._expected
        self._allowed_tables = frozenset(t.name for t in spec._tables)
        self._db = sqlite3.connect(':memory:')
        self._db.enable_load_extension(False)
        self._db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_BYTES)
        self._db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_RESULT_BYTES)
        self._db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 128)
        self._db.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 64)
        self._db.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 16)
        self._db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 128)
        for table in spec._tables:
            self._db.execute(table.ddl)
            marks = ','.join('?' for _ in table.columns)
            self._db.executemany(f'INSERT INTO {table.name} VALUES ({marks})', table.rows)
        self._db.commit()
        self._db.execute('PRAGMA query_only=ON')
        self._db.execute('PRAGMA trusted_schema=OFF')
        self._db.set_authorizer(self._authorize)
        self.max_vm_steps = max_vm_steps
        self.max_query_seconds = max_query_seconds
        self.select_attempts = 0
        self.query_seconds = 0.0
        self.vm_steps = 0
        self.closed = False
        self.answered = False
        self.setup_seconds = time.perf_counter() - setup_started

    def _authorize(self, action, first, second, database, source):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if (action == sqlite3.SQLITE_READ and first in self._allowed_tables
                and (database == 'main' or (database is None and second == ''))):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (second or '').lower() in _FUNCTIONS:
            return sqlite3.SQLITE_OK
        # Includes writes, PRAGMA/table-valued PRAGMA, ATTACH, transactions,
        # recursive CTE execution, extension/file functions and schema tables.
        return sqlite3.SQLITE_DENY

    def query(self, sql: str, parameters: dict[str, Scalar] | None = None, *,
              learning_check: bool = False) -> QueryResult:
        if self.closed:
            return QueryResult((), (), 'episode is closed for queries', self.select_attempts)
        if type(learning_check) is not bool:
            return QueryResult((), (), 'learning_check must be an explicit boolean', self.select_attempts)
        if learning_check:
            if not self._allow_learning_checks:
                return QueryResult((), (), 'learning checks are not enabled', self.select_attempts)
            if not self.answered:
                return QueryResult((), (), 'learning checks require an answered episode', self.select_attempts)
        elif self.answered:
            return QueryResult((), (), 'episode is closed for queries', self.select_attempts)
        if self.select_attempts >= MAX_SELECTS:
            return QueryResult((), (), 'SELECT attempt budget exhausted', self.select_attempts)
        self.select_attempts += 1
        attempt = self.select_attempts
        started = time.perf_counter()
        steps = 0

        def progress():
            nonlocal steps
            steps += 100
            return int(steps >= self.max_vm_steps
                       or time.perf_counter() - started >= self.max_query_seconds)

        try:
            if type(sql) is not str or len(sql.encode('utf-8')) > MAX_SQL_BYTES:
                raise ValueError('SQL must be UTF-8 text of at most 16384 bytes')
            # Authorizer is authoritative. Prefix check also excludes EXPLAIN,
            # empty statements and non-SELECT operations before compilation.
            stripped = re.sub(r'\A(?:\s|--[^\n]*(?:\n|$)|/\*.*?\*/)*', '', sql, flags=re.S)
            if not re.match(r'(?i)(SELECT|WITH)\b', stripped):
                raise ValueError('only one SELECT or nonrecursive WITH SELECT is permitted')
            if parameters is None:
                parameters = {}
            if (type(parameters) is not dict or len(parameters) > 128
                    or any(type(k) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', k)
                           for k in parameters)
                    or any(type(v) not in (int, float, str, type(None))
                           or (type(v) is float and not math.isfinite(v))
                           or (type(v) is int and not -(2**63) <= v < 2**63)
                           or (type(v) is str and len(v.encode('utf-8')) > MAX_CELL_BYTES)
                           for v in parameters.values())):
                raise ValueError('bounded named scalar literal parameters required')
            self._db.set_progress_handler(progress, 100)
            cursor = self._db.execute(sql, parameters)
            if cursor.description is None:
                raise ValueError('a SELECT result is required')
            columns = tuple(c[0] for c in cursor.description)
            raw = cursor.fetchmany(MAX_ROWS + 1)
            truncated = len(raw) > MAX_ROWS
            rows = tuple(tuple(row) for row in raw[:MAX_ROWS])
            payload_bytes = sum(len(c.encode('utf-8')) for c in columns)
            for row in rows:
                for cell in row:
                    if type(cell) not in (int, float, str, type(None)):
                        raise ValueError('only numeric, text and NULL result cells are permitted')
                    if type(cell) is float and not math.isfinite(cell):
                        raise ValueError('non-finite result cells are not permitted')
                    size = len(cell.encode('utf-8')) if type(cell) is str else 8
                    if size > MAX_CELL_BYTES:
                        raise ValueError('result cell byte limit exceeded')
                    payload_bytes += size
            if payload_bytes > MAX_RESULT_BYTES:
                raise ValueError('result byte limit exceeded')
            if time.perf_counter() - started > self.max_query_seconds:
                raise ValueError('query time limit exceeded')
            return QueryResult(columns, rows, None, attempt, truncated)
        except (sqlite3.Error, ValueError, OverflowError) as exc:
            return QueryResult((), (), str(exc)[:256], attempt)
        finally:
            self._db.set_progress_handler(None, 0)
            self.query_seconds += time.perf_counter() - started
            self.vm_steps += steps

    def answer(self, value: float) -> Feedback:
        if self.closed or self.answered:
            raise RuntimeError('one answer is allowed before episode closure')
        self.answered = True
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
        correct = valid and abs(value - self._expected) <= 1e-6 * (1 + abs(self._expected))
        return Feedback(float(correct))

    def close(self):
        if not self.closed:
            self._db.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def open_episode(spec: EpisodeSpec, **limits) -> EpisodeSession:
    return EpisodeSession(spec, **limits)


def _seed(seed: int, *parts) -> int:
    return int.from_bytes(hashlib.sha256(repr((seed, parts)).encode()).digest()[:8], 'big')


def _names(seed: int) -> dict[str, str]:
    rng = random.Random(seed)
    keys = ('orders', 'profiles', 'refunds', 'shipments', 'oid', 'ocid', 'amount',
            'quantity', 'status', 'order_day', 'channel', 'pid', 'pcid', 'region',
            'tier', 'revision', 'active', 'rid', 'roid', 'refund_amount', 'sid',
            'soid', 'ship_day', 'delivered')
    result = {}
    used = set()
    for key in keys:
        while True:
            name = ('r_' if key in keys[:4] else 'c_') + ''.join(rng.choices('abcdefhijkmnpqrstuvwxyz', k=6))
            if name not in used:
                used.add(name)
                result[key] = name
                break
    return result


def _convention(seed: int, split: str) -> _Convention:
    # Hold out combinations, not individual concepts: parity gives eight
    # disjoint four-bit combinations per split, including both values of each.
    parity = SPLITS.index(split)
    choices = [bits for bits in range(16) if bits.bit_count() % 2 == parity]
    bits = random.Random(seed).choice(choices)
    return _Convention(*(bool(bits & (1 << i)) for i in range(4)))


_WARM = (
    ('gross', 'What is the total gross order value?'),
    ('mean_gross', 'What is the average gross order value?'),
    ('confirmed_units', 'How many units occur in confirmed orders?'),
    ('north_customers', 'How many customers currently belong to the North region?'),
    ('north_gross', 'What is the total gross order value for customers currently in the North region?'),
    ('refunds', 'What is the total monetary value of all refund records?'),
    ('refunded_orders', 'How many distinct orders have at least one refund record?'),
    ('gold_gross', 'What is the total gross order value for customers currently in the Gold tier?'),
)

_COMPOSITIONS = {
    'development': (
        ('north_confirmed_net', 'What is the total net order value of confirmed orders for customers currently in the North region?'),
        ('gold_mean_net', 'What is the average net order value for customers currently in the Gold tier?'),
        ('south_refund_percentage', 'What percentage of gross order value was refunded for customers currently in the South region? Only orders with a reportable gross value contribute to either total.'),
        ('gold_positive_customers', 'How many distinct current Gold-tier customers have at least one confirmed order with positive net value?'),
        ('region_mean_net_gap', 'What is average net order value in the current North region minus average net order value in the current South region?'),
        ('gold_confirmed_gross_share', 'What percentage of all confirmed gross order value belongs to customers currently in the Gold tier?'),
        ('north_mean_refund_count', 'Among orders for current North-region customers that have at least one refund record, what is the mean number of refund records per order?'),
        ('gold_max_customer_net', 'What is the largest total net order value for any single customer currently in the Gold tier?'),
    ),
    'heldout': (
        ('south_cancelled_net', 'What is the total net order value of cancelled orders for customers currently in the South region who also have at least one confirmed order?'),
        ('silver_net_per_unit', 'For customers currently in the Silver tier, what is total net order value divided by total units of orders with reportable net value?'),
        ('north_overrefunded_percentage', 'Among reportable orders for current North-region customers, what percentage have refunds larger than their gross value?'),
        ('silver_two_refunded_customers', 'How many current Silver-tier customers have at least two distinct orders with refund records?'),
        ('tier_total_net_gap', 'What is total net order value for current Gold-tier customers minus that for current Silver-tier customers?'),
        ('web_refund_share', 'What percentage of the refund value attached to reportable orders comes from web-channel orders?'),
        ('confirmed_max_refund_count', 'What is the maximum number of refund records on a single confirmed order?'),
        ('south_min_customer_net', 'What is the smallest total net order value among current South-region customers with at least one order?'),
    ),
}

_SHIPPING = {
    'development': (
        ('delivered_north_net', 'What is total net order value of delivered orders for customers currently in the North region?'),
        ('gold_confirmed_mean_lag', 'For delivered confirmed orders of current Gold-tier customers, what is the mean number of days from order placement to the latest shipment?'),
        ('south_two_delivered_customers', 'How many current South-region customers have at least two distinct delivered orders?'),
        ('gold_undelivered_net', 'What is the total net order value of orders not yet delivered for customers currently in the Gold tier?'),
        ('confirmed_delivered_unit_share', 'What percentage of confirmed-order units belongs to delivered orders?'),
        ('north_delivered_refunds', 'What is the total refund value attached to delivered orders of customers currently in the North region?'),
        ('delivered_mean_refund_count', 'Among delivered orders with at least one refund record, what is the mean number of refund records per order?'),
        ('delivered_max_customer_net', 'What is the maximum total net order value of delivered orders for a single customer?'),
    ),
    'heldout': (
        ('south_late_gross', 'What is total gross order value for current South-region customers whose latest shipment was more than three days after order placement?'),
        ('silver_refunded_max_lag', 'Among delivered orders with refund records for current Silver-tier customers, what is the largest lag in days from order placement to the latest shipment?'),
        ('gold_two_undelivered_customers', 'How many current Gold-tier customers have at least two distinct orders not yet delivered?'),
        ('cancelled_delivered_net', 'What is the total net order value of delivered cancelled orders whose customer also has at least one pending order not yet delivered?'),
        ('web_delivered_gross_share', 'What percentage of reportable gross order value on web-channel orders belongs to delivered orders?'),
        ('south_undelivered_refunds', 'For current South-region customers with at least one order not yet delivered, what is the mean customer total of refunds on those undelivered orders?'),
        ('delivered_multi_refund_share', 'What percentage of delivered orders has at least two refund records?'),
        ('delivered_min_customer_net', 'What is the smallest total net order value among customers with at least one delivered order?'),
    ),
}


def _catalog(n, c):
    rows = []
    def add(table, column, description):
        rows.append((n.get(table, table), n.get(column, column), description))
    add('orders', '*', 'One row per order. Gross value is unit amount times quantity. Net value is gross value minus the sum of refund records for that order. Monetary outputs are dollars.')
    add('orders', 'oid', 'Unique order identifier; refund and shipment order references point here.')
    add('orders', 'ocid', 'Customer reference, matching the customer reference in the profile table. Select one current profile per customer before joining orders.')
    unit = 'integer cents; divide by 100.0 to obtain dollars' if c.cents else 'dollars; no unit conversion'
    missing = ('A NULL unit amount means zero; retain this order in monetary averages and totals.' if c.null_is_zero else
               'A NULL unit amount is unreported; exclude this order from monetary totals, averages and reportable-order ratios. Counts and unit counts still include it.')
    add('orders', 'amount', 'Unit amount is stored in ' + unit + '. ' + missing)
    add('orders', 'quantity', 'Positive integer quantity purchased in this order.')
    add('orders', 'status', 'Order status: confirmed, cancelled, or pending. Include all statuses unless the question restricts them.')
    add('orders', 'order_day', 'Integer day of order placement; shipment day minus this value is shipment lag in days.')
    add('orders', 'channel', 'Order channel: web or store.')
    mult = 'Historical snapshots; multiple profile rows can share a customer reference.' if c.history else 'Exactly one profile row per customer reference.'
    select = ('The current profile is the unique row whose current flag equals 1; largest revision need not be current.' if c.current_by_flag else
              'The current profile is the row with greatest revision per customer; the current flag is an unreliable legacy field and must not select the row.')
    add('profiles', '*', 'Customer profiles. ' + mult + ' ' + select)
    add('profiles', 'pid', 'Unique profile-row identifier; this is not the order customer reference.')
    add('profiles', 'pcid', 'Customer reference used by orders; it may repeat across profile snapshots.')
    add('profiles', 'region', 'Region for this profile snapshot: North or South; use the current snapshot.')
    add('profiles', 'tier', 'Tier for this profile snapshot: Gold or Silver; use the current snapshot.')
    add('profiles', 'revision', 'Integer profile revision, unique within each customer.')
    add('profiles', 'active', 'Current flag; see the profile-table convention to decide whether it is authoritative.')
    add('refunds', '*', 'Refund events. An order can have multiple records; sum refund amounts once per order before combining them with order values or shipments. Orders without refund events have zero refunds.')
    add('refunds', 'rid', 'Unique refund-record identifier.')
    add('refunds', 'roid', 'Order reference matching the order identifier.')
    add('refunds', 'refund_amount', 'Refund amount stored in ' + unit + '; never NULL.')
    add('shipments', '*', 'Shipment events. An order can have multiple records. An order is delivered if any record has delivered flag 1; no shipment records means not delivered. The latest shipment has greatest shipment day. Aggregate per order before joining other event tables.')
    add('shipments', 'sid', 'Unique shipment-record identifier.')
    add('shipments', 'soid', 'Order reference matching the order identifier.')
    add('shipments', 'ship_day', 'Integer shipment day. Use greatest shipment day per order for latest-shipment lag.')
    add('shipments', 'delivered', 'Delivery indicator, 0 or 1; any 1 for an order means delivered.')
    return tuple(rows)


def _world(data_seed, n, c):
    rng = random.Random(data_seed)
    profiles, current = [], {}
    for customer in range(1, 9):
        count = rng.choice((2, 3)) if c.history else 1
        flagged = rng.randrange(count)
        selected = flagged if c.current_by_flag else count - 1
        for k in range(count):
            region = ('North', 'South')[(customer + k) % 2]
            tier = ('Gold', 'Silver')[(customer // 2 + k) % 2]
            row = (len(profiles) + 1, customer, region, tier, k + 1, int(k == flagged))
            profiles.append(row)
            if k == selected:
                current[customer] = (region, tier)
    orders, refunds, shipments, lines = [], [], [], []
    scale = 100 if c.cents else 1
    for oid in range(1, 33):
        cid = (oid - 1) % 8 + 1
        dollars = None if oid % 7 == 0 else rng.randrange(12, 801) / 4
        amount = None if dollars is None else dollars * scale
        if c.cents and amount is not None:
            amount = int(amount)
        qty = rng.randint(1, 5)
        status = ('confirmed', 'cancelled', 'pending')[(oid + rng.randrange(3)) % 3]
        day = rng.randint(1, 20)
        channel = rng.choice(('web', 'store'))
        orders.append((oid, cid, amount, qty, status, day, channel))
        refund_values = [rng.randrange(1, 601) / 4 for _ in range(oid % 3)]
        for value in refund_values:
            stored = int(value * scale) if c.cents else value
            refunds.append((len(refunds) + 1, oid, stored))
        shipment_rows = []
        for k in range(oid % 4):
            shipment_rows.append((len(shipments) + 1, oid, day + k + rng.randint(1, 6), int((oid + k) % 3 == 0)))
            shipments.append(shipment_rows[-1])
        gross = dollars * qty if dollars is not None else (0.0 if c.null_is_zero else None)
        refund = sum(refund_values)
        lines.append(dict(oid=oid, cid=cid, region=current[cid][0], tier=current[cid][1],
                          gross=gross, net=None if gross is None else gross - refund,
                          qty=qty, status=status, channel=channel, refund=refund,
                          nrefund=len(refund_values), delivered=int(any(r[3] for r in shipment_rows)),
                          lag=max((r[2] for r in shipment_rows), default=day) - day if shipment_rows else None))
    def table(key, cols, records):
        return _Table(n[key], tuple((n[name], kind) for name, kind in cols), tuple(records))
    tables = (
        _Table('catalog', (('table_name', 'TEXT'), ('column_name', 'TEXT'), ('description', 'TEXT')), _catalog(n, c)),
        table('orders', (('oid', 'INTEGER'), ('ocid', 'INTEGER'), ('amount', 'NUMERIC'), ('quantity', 'INTEGER'),
                         ('status', 'TEXT'), ('order_day', 'INTEGER'), ('channel', 'TEXT')), orders),
        table('profiles', (('pid', 'INTEGER'), ('pcid', 'INTEGER'), ('region', 'TEXT'), ('tier', 'TEXT'),
                           ('revision', 'INTEGER'), ('active', 'INTEGER')), profiles),
        table('refunds', (('rid', 'INTEGER'), ('roid', 'INTEGER'), ('refund_amount', 'NUMERIC')), refunds),
        table('shipments', (('sid', 'INTEGER'), ('soid', 'INTEGER'), ('ship_day', 'INTEGER'), ('delivered', 'INTEGER')), shipments),
    )
    return tables, lines, current


def _base_sql(n, c):
    unit = '100.0' if c.cents else '1.0'
    amount = f'o.{n["amount"]}'
    if c.null_is_zero:
        amount = f'COALESCE({amount},0)'
    gross = f'({amount}/{unit}*o.{n["quantity"]})'
    if c.current_by_flag:
        selection = f'p.{n["active"]}=1'
    else:
        selection = f'p.{n["revision"]}=(SELECT MAX(p2.{n["revision"]}) FROM {n["profiles"]} p2 WHERE p2.{n["pcid"]}=p.{n["pcid"]})'
    return f'''WITH current_profiles AS (
SELECT p.* FROM {n['profiles']} p WHERE {selection}
), refund_totals AS (
SELECT {n['roid']} AS oid,SUM({n['refund_amount']}/{unit}) AS refund,COUNT(*) AS nrefund FROM {n['refunds']} GROUP BY {n['roid']}
), delivery_totals AS (
SELECT {n['soid']} AS oid,MAX({n['delivered']}) AS delivered,MAX({n['ship_day']}) AS latest_day FROM {n['shipments']} GROUP BY {n['soid']}
), lines AS (
SELECT o.{n['oid']} AS oid,o.{n['ocid']} AS cid,p.{n['region']} AS region,p.{n['tier']} AS tier,
{gross} AS gross,{gross}-COALESCE(r.refund,0) AS net,o.{n['quantity']} AS qty,
o.{n['status']} AS status,o.{n['channel']} AS channel,COALESCE(r.refund,0) AS refund,COALESCE(r.nrefund,0) AS nrefund,
COALESCE(s.delivered,0) AS delivered,s.latest_day-o.{n['order_day']} AS lag
FROM {n['orders']} o JOIN current_profiles p ON p.{n['pcid']}=o.{n['ocid']}
LEFT JOIN refund_totals r ON r.oid=o.{n['oid']} LEFT JOIN delivery_totals s ON s.oid=o.{n['oid']}
) '''


def _answer_recipe(kind, lines, current, final=False):
    """Independent Python scalar oracle paired with a hidden reference SELECT."""
    rows = [r for r in lines if not final or (r['delivered'] and r['nrefund'] >= 2)]
    source = '(SELECT * FROM lines WHERE delivered=1 AND nrefund>=2)' if final else 'lines'
    def filt(**equals):
        return [r for r in rows if all(r[k] == v for k, v in equals.items())]
    def total(rs, key):
        return sum(r[key] for r in rs if r[key] is not None)
    def mean(rs, key):
        values = [r[key] for r in rs if r[key] is not None]
        return sum(values) / len(values) if values else 0.0
    def ratio(a, b):
        return a / b if b else 0.0
    def count_customers(rs, minimum=1):
        return sum(sum(r['cid'] == cid for r in rs) >= minimum for cid in range(1, 9))
    def extreme_customer(rs, maximum):
        values = [total([r for r in rs if r['cid'] == cid], 'net') for cid in sorted({r['cid'] for r in rs})]
        return (max(values) if maximum else min(values)) if values else 0.0
    def sql(expr, where='1'):
        return f'SELECT COALESCE({expr},0) FROM {source} WHERE {where}'
    north, south, gold, silver = filt(region='North'), filt(region='South'), filt(tier='Gold'), filt(tier='Silver')
    confirmed, delivered = filt(status='confirmed'), filt(delivered=1)
    reportable = [r for r in rows if r['gross'] is not None]
    table = {
        'gross': (total(rows, 'gross'), sql('SUM(gross)')),
        'mean_gross': (mean(rows, 'gross'), sql('AVG(gross)')),
        'confirmed_units': (total(confirmed, 'qty'), sql('SUM(qty)', "status='confirmed'")),
        'north_gross': (total(north, 'gross'), sql('SUM(gross)', "region='North'")),
        'refunds': (total(rows, 'refund'), sql('SUM(refund)')),
        'refunded_orders': (sum(r['nrefund'] > 0 for r in rows), sql('COUNT(*)', 'nrefund>0')),
        'gold_gross': (total(gold, 'gross'), sql('SUM(gross)', "tier='Gold'")),
        'north_confirmed_net': (total(filt(region='North', status='confirmed'), 'net'), sql('SUM(net)', "region='North' AND status='confirmed'")),
        'gold_mean_net': (mean(gold, 'net'), sql('AVG(net)', "tier='Gold'")),
        'south_refund_percentage': (100*ratio(total([r for r in south if r['gross'] is not None], 'refund'), total(south, 'gross')), sql('100.0*SUM(refund)/NULLIF(SUM(gross),0)', "region='South' AND gross IS NOT NULL")),
        'gold_positive_customers': (count_customers([r for r in gold if r['status']=='confirmed' and r['net'] is not None and r['net']>0]), sql('COUNT(DISTINCT cid)', "tier='Gold' AND status='confirmed' AND net>0")),
        'region_mean_net_gap': (mean(north, 'net')-mean(south, 'net'), sql("COALESCE(AVG(CASE WHEN region='North' THEN net END),0)-COALESCE(AVG(CASE WHEN region='South' THEN net END),0)")),
        'gold_confirmed_gross_share': (100*ratio(total([r for r in confirmed if r['tier']=='Gold'], 'gross'), total(confirmed, 'gross')), sql("100.0*SUM(CASE WHEN tier='Gold' THEN gross ELSE 0 END)/NULLIF(SUM(gross),0)", "status='confirmed'")),
        'north_mean_refund_count': (mean([r for r in north if r['nrefund']>0], 'nrefund'), sql('AVG(nrefund)', "region='North' AND nrefund>0")),
        'south_cancelled_net': (total([r for r in filt(region='South', status='cancelled') if r['cid'] in {s['cid'] for s in confirmed}], 'net'), sql('SUM(net)', f"region='South' AND status='cancelled' AND cid IN (SELECT cid FROM {source} WHERE status='confirmed')")),
        'silver_net_per_unit': (ratio(total(silver, 'net'), total([r for r in silver if r['net'] is not None], 'qty')), sql('SUM(net)/NULLIF(1.0*SUM(qty),0)', "tier='Silver' AND net IS NOT NULL")),
        'north_overrefunded_percentage': (100*ratio(sum(r['refund']>r['gross'] for r in north if r['gross'] is not None), sum(r['gross'] is not None for r in north)), sql('100.0*SUM(CASE WHEN refund>gross THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0)', "region='North' AND gross IS NOT NULL")),
        'tier_total_net_gap': (total(gold,'net')-total(silver,'net'), sql("COALESCE(SUM(CASE WHEN tier='Gold' THEN net END),0)-COALESCE(SUM(CASE WHEN tier='Silver' THEN net END),0)")),
        'web_refund_share': (100*ratio(total([r for r in reportable if r['channel']=='web'],'refund'),total(reportable,'refund')), sql("100.0*SUM(CASE WHEN channel='web' THEN refund ELSE 0 END)/NULLIF(SUM(refund),0)", 'gross IS NOT NULL')),
        'confirmed_max_refund_count': (max((r['nrefund'] for r in confirmed),default=0), sql('MAX(nrefund)', "status='confirmed'")),
        'delivered_north_net': (total(filt(delivered=1,region='North'),'net'), sql('SUM(net)', "delivered=1 AND region='North'")),
        'gold_confirmed_mean_lag': (mean(filt(delivered=1,tier='Gold',status='confirmed'),'lag'), sql('AVG(lag)', "delivered=1 AND tier='Gold' AND status='confirmed'")),
        'gold_undelivered_net': (total(filt(delivered=0,tier='Gold'),'net'), sql('SUM(net)', "delivered=0 AND tier='Gold'")),
        'confirmed_delivered_unit_share': (100*ratio(total([r for r in confirmed if r['delivered']],'qty'),total(confirmed,'qty')), sql('100.0*SUM(CASE WHEN delivered=1 THEN qty ELSE 0 END)/NULLIF(SUM(qty),0)', "status='confirmed'")),
        'north_delivered_refunds': (total(filt(region='North',delivered=1),'refund'), sql('SUM(refund)', "region='North' AND delivered=1")),
        'delivered_mean_refund_count': (mean([r for r in delivered if r['nrefund']>0],'nrefund'), sql('AVG(nrefund)', 'delivered=1 AND nrefund>0')),
        'south_late_gross': (total([r for r in south if r['lag'] is not None and r['lag']>3],'gross'), sql('SUM(gross)', "region='South' AND lag>3")),
        'silver_refunded_max_lag': (max((r['lag'] for r in silver if r['delivered'] and r['nrefund']>0),default=0), sql('MAX(lag)', "tier='Silver' AND delivered=1 AND nrefund>0")),
        'cancelled_delivered_net': (total([r for r in filt(status='cancelled',delivered=1) if r['cid'] in {s['cid'] for s in filt(status='pending',delivered=0)}],'net'), sql('SUM(net)', f"status='cancelled' AND delivered=1 AND cid IN (SELECT cid FROM {source} WHERE status='pending' AND delivered=0)")),
        'web_delivered_gross_share': (100*ratio(total(filt(channel='web',delivered=1),'gross'),total(filt(channel='web'),'gross')), sql('100.0*SUM(CASE WHEN delivered=1 THEN gross ELSE 0 END)/NULLIF(SUM(gross),0)', "channel='web'")),
        'south_undelivered_refunds': (ratio(total(filt(region='South',delivered=0),'refund'),len({r['cid'] for r in filt(region='South',delivered=0)})), f"SELECT COALESCE(AVG(refund_total),0) FROM (SELECT cid,SUM(refund) AS refund_total FROM {source} WHERE region='South' AND delivered=0 GROUP BY cid)"),
        'delivered_multi_refund_share': (100*ratio(sum(r['nrefund']>=2 for r in delivered),len(delivered)), sql('100.0*SUM(CASE WHEN nrefund>=2 THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0)', 'delivered=1')),
    }
    grouped_counts = {
        'silver_two_refunded_customers': ([r for r in silver if r['nrefund']>0], "tier='Silver' AND nrefund>0"),
        'south_two_delivered_customers': (filt(region='South',delivered=1), "region='South' AND delivered=1"),
        'gold_two_undelivered_customers': (filt(tier='Gold',delivered=0), "tier='Gold' AND delivered=0"),
    }
    extremes = {
        'gold_max_customer_net': (gold, "tier='Gold'", True),
        'south_min_customer_net': (south, "region='South'", False),
        'delivered_max_customer_net': (delivered, 'delivered=1', True),
        'delivered_min_customer_net': (delivered, 'delivered=1', False),
    }
    if kind == 'north_customers':
        # The reference uses profile rows, so customers with zero orders would
        # also count; this fixture currently supplies every customer orders.
        return float(sum(region=='North' for region,tier in current.values())), "SELECT COUNT(*) FROM current_profiles WHERE {REGION}='North'"
    if kind in grouped_counts:
        rs, where = grouped_counts[kind]
        return float(count_customers(rs, 2)), f'SELECT COUNT(*) FROM (SELECT cid FROM {source} WHERE {where} GROUP BY cid HAVING COUNT(*)>=2)'
    if kind in extremes:
        rs, where, maximum = extremes[kind]
        aggregate = 'MAX' if maximum else 'MIN'
        return float(extreme_customer(rs,maximum)), f'SELECT COALESCE({aggregate}(amount),0) FROM (SELECT COALESCE(SUM(net),0) AS amount FROM {source} WHERE {where} GROUP BY cid)'
    value, query = table[kind]
    return float(value), query


def _episode(seed, condition, split, index, names_seed, convention, kind, question, final=False, panel=None):
    n = _names(names_seed)
    panel = panel or ('final' if final else 'ordinary')
    data_seed = _seed(seed, 'data', index, panel)
    tables, lines, current = _world(data_seed, n, convention)
    expected, query = _answer_recipe(kind, lines, current, final)
    recipe = _semantic_recipe(query)
    query = query.replace('{REGION}', n['region'])
    if final:
        question = 'Restrict the calculation to delivered orders with at least two refund records. ' + question
    if condition == 'near_match' and index == 8 and not final:
        question = 'The warehouse has been migrated; consult its current documentation before reusing earlier conventions. ' + question
    question += (' Return one number. Monetary outputs are dollars. An empty total or undefined ratio or average is 0. '
                 'The catalog table documents the current schema and business conventions.')
    public = PublicEpisode(question, '\n'.join(t.ddl for t in tables))
    metadata = tuple(dict(seed=seed, condition=condition, split=split, index=index,
                         panel=panel, phase=panel if panel in ('old','final') else ('warm','composition','new_relation')[index//8],
                         template=kind, names_seed=names_seed, data_seed=data_seed,
                         convention=(convention.cents,convention.null_is_zero,convention.history,convention.current_by_flag)).items())
    return EpisodeSpec(public, tables, expected, _base_sql(n, convention)+query, recipe, metadata)


def make_stream(seed: int, condition: str, split: str = 'development') -> StreamSpec:
    """Build fixtures without executing tools or exposing any evaluator state.

    Calling split='heldout' constructs data; it is not an authorization to run
    a confirmatory experiment. Protocol freezing and execution belong to caller.
    """
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError('nonnegative 63-bit evaluator seed required')
    if condition not in CONDITIONS or split not in SPLITS:
        raise ValueError('unknown condition or split')
    base_names = _seed(seed, 'names')
    base_convention = _convention(_seed(seed, 'conventions'), split)
    definitions = _WARM + _COMPOSITIONS[split] + _SHIPPING[split]
    def settings(index):
        if condition == 'nonreuse':
            return _seed(seed, 'names', index), _convention(_seed(seed, 'conventions', index), split)
        if condition == 'near_match' and index >= 8:
            # Complementing four independent bits preserves the split parity.
            c = base_convention
            return base_names, _Convention(not c.cents,not c.null_is_zero,not c.history,not c.current_by_flag)
        return base_names, base_convention
    ordinary = []
    for index, (kind, question) in enumerate(definitions):
        names_seed, convention = settings(index)
        ordinary.append(_episode(seed,condition,split,index,names_seed,convention,kind,question))
    old_panel = []
    for index, (kind, question) in enumerate(_WARM):
        names_seed, convention = settings(index)
        old_panel.append(_episode(seed,condition,split,index,names_seed,convention,kind,question,panel='old'))
    final_panel = []
    for offset, (kind, question) in enumerate(_COMPOSITIONS[split]):
        index = 24 + offset
        names_seed, convention = settings(index)
        final_panel.append(_episode(seed,condition,split,index,names_seed,convention,kind,question,True))
    metadata = tuple(dict(generator_version='sql_env_v8.1',seed=seed,condition=condition,split=split,
                         ordinary_count=24,old_count=8,final_count=8,
                         split_rule='disjoint four-bit convention parity and disjoint post-warm question templates',
                         fresh_rows_per_question=True).items())
    return StreamSpec(tuple(ordinary),tuple(old_panel),tuple(final_panel),metadata)


# Minimal data dependencies of the semantic column aliases used by reference
# tails. Unused CTEs from _base_sql are deliberately absent from this program.
_GROSS_NODE = ('multiply', ('decode_currency_and_null', ('column','orders.unit_amount')),
               ('column','orders.quantity'))
_REFUND_NODE = ('lookup_or_zero', ('group_by','refunds.order_reference',
                                  ('sum',('decode_currency',('column','refunds.amount')))),
                ('column','orders.order_identifier'))
_CURRENT_NODE = ('select_current', ('relation','profiles'),
                 ('documented_selection','flag_or_greatest_revision'))
_PROFILE_JOIN = ('lookup_unique', _CURRENT_NODE, ('column','orders.customer_reference'))
_DELIVERED_NODE = ('lookup_or_zero', ('group_by','shipments.order_reference',
                                     ('max',('column','shipments.delivered'))),
                   ('column','orders.order_identifier'))
_DEPENDENCIES = {
    'oid': (('column','orders.order_identifier'), ('orders',), ('order_presence',)),
    'cid': (('column','orders.customer_reference'), ('orders',), ('order_presence',)),
    'gross': (_GROSS_NODE, ('orders',), ('order_amount',)),
    'net': (('subtract',_GROSS_NODE,_REFUND_NODE), ('orders','refunds'), ('order_amount','refund_events')),
    'refund': (_REFUND_NODE, ('orders','refunds'), ('refund_events',)),
    'nrefund': (('lookup_or_zero',('group_by','refunds.order_reference',('count','refunds')),
                 ('column','orders.order_identifier')), ('orders','refunds'), ('order_presence','refund_events')),
    'qty': (('column','orders.quantity'), ('orders',), ('order_quantity',)),
    'status': (('column','orders.status'), ('orders',), ('order_status',)),
    'channel': (('column','orders.channel'), ('orders',), ('order_channel',)),
    'region': (('project','profiles.region',_PROFILE_JOIN), ('orders','profiles'), ('profile_current',)),
    'tier': (('project','profiles.tier',_PROFILE_JOIN), ('orders','profiles'), ('profile_current',)),
    'delivered': (_DELIVERED_NODE, ('orders','shipments'), ('shipment_events',)),
    'lag': (('subtract',('lookup',('group_by','shipments.order_reference',
                                  ('max',('column','shipments.day'))),('column','orders.order_identifier')),
             ('column','orders.placement_day')), ('orders','shipments'), ('shipment_events',)),
}


def _semantic_recipe(reference_tail: str) -> SemanticRecipe:
    """Normalize evaluator query structure and expand only demanded measures.

    Literal values and randomized physical names are not novelty evidence.
    Operators, aggregation grains, referenced business columns and nested
    SELECT structure are retained. This parses our finite reference tails only;
    it is never used to parse, generate, route or restrict learner SQL.
    """
    tail = reference_tail.replace('{REGION}', 'region')
    raw = re.findall(r"'(?:''|[^'])*'|(?:\d+(?:\.\d*)?|\.\d+)|[A-Za-z_][A-Za-z0-9_]*|>=|<=|<>|!=|[^\s]", tail)
    normalized = tuple('<literal>' if token.startswith("'") else '<number>' if token[0].isdigit() else token.lower()
                       for token in raw)
    if 'current_profiles' in normalized:
        # This special source is one row per customer, not an order join.
        dependencies = (('region',('project','profiles.region',_CURRENT_NODE)),)
        relations, skills = ('profiles',), ('profile_current',)
    else:
        demanded = sorted(set(normalized) & _DEPENDENCIES.keys())
        dependencies = tuple((name,_DEPENDENCIES[name][0]) for name in demanded)
        relations = tuple(sorted({'orders'} | {r for name in demanded for r in _DEPENDENCIES[name][1]}))
        skills = tuple(sorted({skill for name in demanded for skill in _DEPENDENCIES[name][2]}))
    digest = hashlib.sha256(repr((normalized,dependencies)).encode()).hexdigest()
    return SemanticRecipe(normalized,dependencies,relations,skills,digest)
