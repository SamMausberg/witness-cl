"""Local prequential relational feature search, with no deployed-system authority.

The evaluator owns SQLite databases and gold report specifications. A learner
sees only immutable results of two fixed SELECT measurements and its subsequent
scalar answer feedback. It proposes frozen numerical policies over a bounded
typed feature grammar. A separate caller owns any fresh statistical audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from itertools import combinations_with_replacement
import json
import math
import random
import re
import sqlite3
import time
from typing import TypeAlias

import numpy as np


Mono: TypeAlias = tuple[int, int, int, int, int, int]
Row: TypeAlias = tuple[int, int, int, int, int, int]
ReportSpec: TypeAlias = tuple[tuple[Mono, int], ...]


def _make_basis():
    result = []
    for degree in range(4):
        for factors in combinations_with_replacement(range(6), degree):
            result.append(tuple(factors.count(i) for i in range(6)))
    return tuple(result)


BASIS: tuple[Mono, ...] = _make_basis()
INITIAL_FEATURES: tuple[Mono, ...] = BASIS[:7]
_BASIS_SET = frozenset(BASIS)
_NAMES = ('i.x0', 'i.x1', 'i.x2', 'i.x3', 'g.w0', 'g.w1')
_ITEM_QUERY = 'SELECT id, group_id, x0, x1, x2, x3 FROM items ORDER BY id'
_GROUP_QUERY = 'SELECT id, w0, w1 FROM groups ORDER BY id'


def _mono(mono) -> Mono:
    if (type(mono) is not tuple or len(mono) != 6
            or any(type(v) is not int or v < 0 for v in mono) or sum(mono) > 3):
        raise ValueError('immutable six-variable monomial of total degree <= 3 required')
    return mono


@dataclass(frozen=True)
class Observation:
    """Learner-visible measurements, never a database handle or a gold label."""
    rows: tuple[Row, ...]
    items: tuple[tuple[int, ...], ...] = ()
    groups: tuple[tuple[int, ...], ...] = ()
    query_count: int = 0
    query_seconds: float = 0.0

    def __post_init__(self):
        if type(self.rows) is not tuple or len(self.rows) > 40:
            raise ValueError('at most 40 immutable joined rows required')
        for row in self.rows:
            if (type(row) is not tuple or len(row) != 6
                    or any(type(v) is not int for v in row)
                    or any(abs(v) > 3 for v in row[:4])
                    or any(abs(v) > 2 for v in row[4:])):
                raise ValueError('bounded six-integer joined row required')
        for records, width, limit in ((self.items, 6, 40), (self.groups, 3, 8)):
            if (type(records) is not tuple or len(records) > limit
                    or any(type(row) is not tuple or len(row) != width
                           or any(type(v) is not int for v in row) for row in records)):
                raise ValueError('immutable bounded raw query records required')
        if (type(self.query_count) is not int or self.query_count < 0
                or type(self.query_seconds) not in (int, float)
                or not math.isfinite(self.query_seconds) or self.query_seconds < 0):
            raise ValueError('valid actual query accounting required')
        if any(not 0 <= row[0] <= 1_000_000 or any(abs(v) > 2 for v in row[1:])
               for row in self.groups):
            raise ValueError('bounded group identifiers and weights required')
        if any(not 0 <= row[0] <= 1_000_000 or not 0 <= row[1] <= 1_000_000
               or any(abs(v) > 3 for v in row[2:]) for row in self.items):
            raise ValueError('bounded item identifiers and values required')
        if self.items or self.groups:
            group_map = {row[0]: row[1:] for row in self.groups}
            if len(group_map) != len(self.groups) or len({r[0] for r in self.items}) != len(self.items):
                raise ValueError('raw measurement keys must be unique')
            if any(row[1] not in group_map for row in self.items):
                raise ValueError('measurement includes an unresolved foreign key')
            joined = tuple(row[2:] + group_map[row[1]] for row in self.items)
            if joined != self.rows:
                raise ValueError('joined rows must match the two visible query results')

    @property
    def payload_bytes(self) -> int:
        # Numeric payload only; Python object overhead is measured separately.
        return 8 * (6 * len(self.rows) + 6 * len(self.items) + 3 * len(self.groups))

    def to_dict(self):
        return {'rows': self.rows, 'items': self.items, 'groups': self.groups,
                'query_count': self.query_count, 'query_seconds': self.query_seconds}


def feature_value(observation: Observation, mono: Mono) -> int:
    _mono(mono)
    if type(observation) is not Observation:
        raise ValueError('immutable visible observation required')
    total = 0
    for row in observation.rows:
        term = 1
        for value, exponent in zip(row, mono):
            for _ in range(exponent):
                term *= value
        total += term
    return total


class SQLiteContext:
    """Evaluator-owned synthetic database with strictly read-only query access."""
    def __init__(self, items, groups, *, max_vm_steps=100_000, max_query_seconds=.25):
        if (type(max_vm_steps) is not int or max_vm_steps < 1
                or type(max_query_seconds) not in (int, float)
                or not math.isfinite(max_query_seconds) or max_query_seconds <= 0):
            raise ValueError('positive finite SQL work/time limits required')
        # Validate public table dimensions/domain before constructing SQL state.
        if (type(items) is not tuple or type(groups) is not tuple or len(items) > 40 or len(groups) > 8
                or any(type(row) is not tuple for row in items + groups)):
            raise ValueError('bounded immutable synthetic table tuples required')
        item_rows, group_rows = items, groups
        group_map = {row[0]: row[1:] for row in group_rows if len(row) == 3}
        if any(len(row) != 6 or row[1] not in group_map for row in item_rows):
            raise ValueError('invalid item schema or foreign key')
        joined = tuple(row[2:] + group_map[row[1]] for row in item_rows)
        Observation(joined, item_rows, group_rows)
        started = time.perf_counter()
        self._db = sqlite3.connect(':memory:')
        self._db.enable_load_extension(False)
        self._db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16384)
        self._db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 262144)
        self._db.execute('PRAGMA foreign_keys=ON')
        self._db.execute('CREATE TABLE groups(id INTEGER PRIMARY KEY,w0 INTEGER,w1 INTEGER)')
        self._db.execute('CREATE TABLE items(id INTEGER PRIMARY KEY,group_id INTEGER REFERENCES groups(id),'
                         'x0 INTEGER,x1 INTEGER,x2 INTEGER,x3 INTEGER)')
        self._db.executemany('INSERT INTO groups VALUES(?,?,?)', group_rows)
        self._db.executemany('INSERT INTO items VALUES(?,?,?,?,?,?)', item_rows)
        self._db.commit()
        self._db.execute('PRAGMA query_only=ON')
        self._db.execute('PRAGMA trusted_schema=OFF')
        self._db.set_authorizer(self._authorize)
        self.max_vm_steps, self.max_query_seconds = max_vm_steps, max_query_seconds
        self.query_count = self.answer_query_count = 0
        self.query_seconds = self.answer_query_seconds = 0.0
        self.setup_seconds = time.perf_counter() - started
        self.closed = False

    @staticmethod
    def _authorize(action, first, second, database, source):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if (action == sqlite3.SQLITE_READ and first in ('items', 'groups')
                and (database == 'main' or (database is None and second == ''))):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (second or '').lower() in ('sum', 'coalesce'):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def _query(self, sql: str, *, row_limit=40, answer=False):
        """Internal fixed-query execution; every attempt is charged, including errors."""
        if self.closed:
            raise RuntimeError('SQLite context is closed')
        if type(sql) is not str or len(sql) > 16384:
            raise ValueError('bounded SQL text required')
        if type(row_limit) is not int or not 0 <= row_limit <= 40:
            raise ValueError('bounded result row limit required')
        started = time.perf_counter()
        steps = 0
        def progress():
            nonlocal steps
            steps += 1
            return int(steps >= self.max_vm_steps
                       or time.perf_counter() - started >= self.max_query_seconds)
        self._db.set_progress_handler(progress, 1)
        try:
            cursor = self._db.execute(sql)
            rows = tuple(tuple(row) for row in cursor.fetchmany(row_limit + 1))
            if len(rows) > row_limit:
                raise ValueError('query result row cap exceeded')
            if len(repr(rows).encode()) > 262144:
                raise ValueError('query result byte cap exceeded')
            return rows
        finally:
            self._db.set_progress_handler(None, 0)
            elapsed = time.perf_counter() - started
            if answer:
                self.answer_query_count += 1
                self.answer_query_seconds += elapsed
            else:
                self.query_count += 1
                self.query_seconds += elapsed

    def observe(self) -> Observation:
        before = self.query_seconds
        items = self._query(_ITEM_QUERY, row_limit=40)
        groups = self._query(_GROUP_QUERY, row_limit=8)
        group_map = {row[0]: row[1:] for row in groups}
        joined = tuple(row[2:] + group_map[row[1]] for row in items)
        return Observation(joined, items, groups, 2, self.query_seconds - before)

    def answer(self, report_spec: ReportSpec) -> float:
        """Gold SQL evaluation is evaluator-only and never passed to a learner."""
        if type(report_spec) is not tuple or not 1 <= len(report_spec) <= 2:
            raise ValueError('one or two immutable gold terms required')
        expressions = []
        for term in report_spec:
            if type(term) is not tuple or len(term) != 2:
                raise ValueError('gold term must pair typed monomial and coefficient')
            mono, coefficient = term
            _mono(mono)
            if type(coefficient) is not int or not 0 < abs(coefficient) <= 10:
                raise ValueError('bounded nonzero integer gold coefficient required')
            factors = [name for name, exponent in zip(_NAMES, mono) for _ in range(exponent)]
            expressions.append('(' + str(coefficient) + '*' + ('*'.join(factors) or '1') + ')')
        sql = ('SELECT COALESCE(SUM(' + '+'.join(expressions) + '),0) '
               'FROM items i JOIN groups g ON i.group_id=g.id')
        return float(self._query(sql, row_limit=1, answer=True)[0][0])

    def close(self):
        if not self.closed:
            self._db.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def make_context(seed: int) -> SQLiteContext:
    if type(seed) is not int:
        raise ValueError('integer evaluator seed required')
    rng = random.Random(seed)
    groups = tuple((i, rng.randint(-2, 2), rng.randint(-2, 2)) for i in range(rng.randint(3, 8)))
    items = tuple((i, rng.randrange(len(groups))) + tuple(rng.randint(-3, 3) for _ in range(4))
                  for i in range(rng.randint(12, 40)))
    return SQLiteContext(items, groups)


@dataclass(frozen=True)
class FrozenPolicy:
    features: tuple[Mono, ...]
    coefficients: tuple[float, ...]

    def __post_init__(self):
        if (type(self.features) is not tuple or type(self.coefficients) is not tuple
                or not 1 <= len(self.features) <= 84 or len(self.features) != len(self.coefficients)):
            raise ValueError('unique immutable bounded feature/coefficient tuples required')
        for mono in self.features:
            _mono(mono)
        if len(set(self.features)) != len(self.features):
            raise ValueError('policy features must be unique')
        if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e12
               for v in self.coefficients):
            raise ValueError('bounded finite scalar coefficients required')

    def predict(self, observation: Observation) -> float:
        prediction = math.fsum(float(c) * feature_value(observation, m)
                               for m, c in zip(self.features, self.coefficients))
        if not math.isfinite(prediction):
            raise ArithmeticError('nonfinite policy prediction')
        return prediction

    def predict_with_cost(self, observation: Observation) -> tuple[float, int]:
        return self.predict(observation), len(self.features) * len(observation.rows)

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(',', ':'), allow_nan=False)
        return hashlib.sha256(encoded.encode()).hexdigest()

    @property
    def payload_bytes(self) -> int:
        return len(self.features) * (6 * 8 + 8)

    def to_dict(self):
        return {'features': self.features, 'coefficients': self.coefficients}

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {'features', 'coefficients'}:
            raise ValueError('exact serialized policy fields required')
        return cls(tuple(tuple(m) for m in value['features']), tuple(value['coefficients']))


@dataclass
class _Item:
    observation: Observation
    target: float
    cache: dict = field(default_factory=dict)


@dataclass
class _Report:
    history: list[_Item] = field(default_factory=list)
    active: tuple[Mono, ...] = INITIAL_FEATURES
    policy: FrozenPolicy = field(default_factory=lambda: FrozenPolicy(INITIAL_FEATURES, (0.0,) * 7))
    updates: int = 0
    cursor: int = 0
    proposals: dict[str, FrozenPolicy] = field(default_factory=dict)
    promoted: set[str] = field(default_factory=set)


class Learner:
    """Own-feedback fitting only; numerical proposals have no admission authority.

    Reuse changes bounded candidate-search order. The bank contains monomial
    syntax from previously promoted proposals, never targets or gold reports.
    """
    MODES = ('grow_reuse', 'grow_no_reuse', 'full_ridge', 'full_history_sparse')

    def __init__(self, mode='grow_reuse', *, max_history=64, max_features=12,
                 bank_limit=32, max_reports=32, search_candidates=16,
                 max_candidate_features=128, max_fits=128, ridge=1e-10):
        if mode not in self.MODES:
            raise ValueError('unknown bounded learner mode')
        limits = (max_history, max_features, bank_limit, max_reports, search_candidates,
                  max_candidate_features, max_fits)
        if any(type(v) is not int or v < 1 for v in limits):
            raise ValueError('positive integer learning resource limits required')
        if (max_history > 256 or not 7 <= max_features <= 12 or bank_limit > 32
                or max_reports > 32 or search_candidates > 84
                or max_candidate_features > 128 or max_fits > 128):
            raise ValueError('reference learning size limit exceeded')
        if type(ridge) not in (float, int) or not math.isfinite(ridge) or ridge <= 0:
            raise ValueError('positive finite ridge penalty required')
        self.mode, self.max_history, self.max_features = mode, max_history, max_features
        self.bank_limit, self.max_reports, self.search_candidates = bank_limit, max_reports, search_candidates
        self.max_candidate_features, self.max_fits, self.ridge = max_candidate_features, max_fits, ridge
        self._reports: dict[str, _Report] = {}
        self._bank: dict[Mono, int] = {}
        self.feature_events: list[dict] = []
        self._event_limit = max_reports * (max_features - len(INITIAL_FEATURES))
        self.metrics = {'updates': 0, 'fits': 0, 'candidate_scores': 0,
                        'feature_evaluations': 0, 'row_feature_evaluations': 0,
                        'fit_matrix_elements': 0, 'fit_rhs_elements': 0,
                        'fit_augmented_elements': 0, 'fit_seconds': 0.0,
                        'update_seconds': 0.0, 'fit_failures': 0,
                        'history_evictions': 0, 'history_bytes': 0,
                        'feature_cache_bytes': 0, 'peak_history_bytes': 0,
                        'proposed_policy_bytes': 0}
        self._fit_calls = 0
        self._candidates_seen = set()

    @staticmethod
    def _report_name(report):
        if type(report) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', report) is None:
            raise ValueError('bounded public report token required')

    def _matrix(self, history, features):
        for mono in features:
            if mono not in self._candidates_seen:
                if len(self._candidates_seen) >= self.max_candidate_features:
                    raise RuntimeError('candidate feature cap exceeded')
                self._candidates_seen.add(mono)
        matrix = []
        for item in history:
            values = []
            for mono in features:
                if mono not in item.cache:
                    item.cache[mono] = feature_value(item.observation, mono)
                    self.metrics['feature_evaluations'] += 1
                    self.metrics['row_feature_evaluations'] += len(item.observation.rows)
                values.append(item.cache[mono])
            matrix.append(values)
        return np.asarray(matrix, dtype=float).reshape(len(history), len(features))

    def _fit(self, matrix, target, *, regularization=0.0):
        if self._fit_calls >= self.max_fits:
            raise RuntimeError('numerical fit cap exceeded')
        self._fit_calls += 1
        self.metrics['fits'] += 1
        self.metrics['fit_matrix_elements'] += int(matrix.size)
        self.metrics['fit_rhs_elements'] += int(target.size)
        started = time.perf_counter()
        try:
            scale = np.maximum(1.0, np.linalg.norm(matrix, axis=0))
            normalized = matrix / scale
            if regularization:
                normalized = np.vstack((normalized, math.sqrt(regularization) * np.eye(matrix.shape[1])))
                target = np.r_[target, np.zeros(matrix.shape[1])]
            self.metrics['fit_augmented_elements'] += int(normalized.size + target.size)
            weights = np.linalg.lstsq(normalized, target, rcond=1e-12)[0]
            weights = weights / (scale[:, None] if weights.ndim == 2 else scale)
            if not np.isfinite(weights).all() or np.any(np.abs(weights) > 1e12):
                raise ArithmeticError('nonfinite or excessive fitted coefficients')
            return weights
        finally:
            self.metrics['fit_seconds'] += time.perf_counter() - started

    def _grow(self, report, state, target):
        active = state.active
        matrix = self._matrix(state.history, active)
        coefficients = self._fit(matrix, target)
        residual = target - matrix @ coefficients
        can_grow = (len(active) < self.max_features and len(target) >= len(active) + 2
                    and np.linalg.norm(residual) > 1e-8 * (1 + np.linalg.norm(target)))
        if can_grow:
            available = [m for m in BASIS if m not in active]
            bank = sorted((m for m in available if m in self._bank),
                          key=lambda m: (-self._bank[m], BASIS.index(m))) if self.mode == 'grow_reuse' else []
            rest = [m for m in available if m not in bank]
            start = state.cursor % len(rest) if rest else 0
            ordered = bank + rest[start:] + rest[:start]
            candidates = tuple(ordered[:self.search_candidates])
            state.cursor += self.search_candidates
            if candidates:
                candidate_matrix = self._matrix(state.history, candidates)
                # Remove directions the present basis already explains. This is
                # one bounded numerical fit, with several candidate columns.
                projection = self._fit(matrix, candidate_matrix)
                orthogonal = candidate_matrix - matrix @ projection
                norms = np.linalg.norm(orthogonal, axis=0)
                scores = np.abs(orthogonal.T @ residual) / np.maximum(norms, 1e-12)
                scores[norms < 1e-10] = 0
                self.metrics['candidate_scores'] += len(candidates)
                best = int(np.argmax(scores))
                if scores[best] > 1e-8 * (1 + np.linalg.norm(target)):
                    mono = candidates[best]
                    active = active + (mono,)
                    matrix = self._matrix(state.history, active)
                    coefficients = self._fit(matrix, target)
                    if len(self.feature_events) >= self._event_limit:
                        raise RuntimeError('feature event cap exceeded')
                    self.feature_events.append({'report': report, 'update': state.updates,
                                                'feature': mono,
                                                'source': 'promoted_bank' if mono in bank else 'typed_grammar',
                                                'candidate_count': len(candidates)})
                    state.active = active
        return FrozenPolicy(active, tuple(float(v) for v in coefficients))

    def _sparse(self, state, target):
        all_matrix = self._matrix(state.history, BASIS)
        residual = target.copy()
        selected = []
        coefficients = np.empty(0)
        for _ in range(3):
            norms = np.linalg.norm(all_matrix, axis=0)
            scores = np.abs(all_matrix.T @ residual) / np.maximum(norms, 1e-12)
            scores[norms < 1e-12] = 0
            scores[selected] = -1
            self.metrics['candidate_scores'] += len(BASIS) - len(selected)
            best = int(np.argmax(scores))
            if scores[best] <= 1e-10 * (1 + np.linalg.norm(target)):
                break
            selected.append(best)
            matrix = all_matrix[:, selected]
            coefficients = self._fit(matrix, target)
            residual = target - matrix @ coefficients
            if np.linalg.norm(residual) <= 1e-9 * (1 + np.linalg.norm(target)):
                break
        if not selected:
            return FrozenPolicy((BASIS[0],), (0.0,))
        return FrozenPolicy(tuple(BASIS[i] for i in selected), tuple(float(v) for v in coefficients))

    def observe(self, report: str, observation: Observation, target: float) -> None:
        self._report_name(report)
        if type(observation) is not Observation:
            raise ValueError('immutable visible measurement required')
        if type(target) not in (float, int) or not math.isfinite(target) or abs(target) > 1e9:
            raise ValueError('finite bounded scalar feedback target required')
        if report not in self._reports and len(self._reports) >= self.max_reports:
            raise ValueError('public report registry cap exceeded')
        started = time.perf_counter()
        state = self._reports.setdefault(report, _Report())
        state.history.append(_Item(observation, float(target)))
        if len(state.history) > self.max_history:
            state.history.pop(0)
            self.metrics['history_evictions'] += 1
        state.updates += 1
        self.metrics['updates'] += 1
        self._fit_calls, self._candidates_seen = 0, set()
        target_vector = np.asarray([item.target for item in state.history], dtype=float)
        try:
            if self.mode == 'full_ridge':
                matrix = self._matrix(state.history, BASIS)
                policy = FrozenPolicy(BASIS, tuple(float(v) for v in self._fit(
                    matrix, target_vector, regularization=self.ridge)))
            elif self.mode == 'full_history_sparse':
                policy = self._sparse(state, target_vector)
            else:
                policy = self._grow(report, state, target_vector)
            state.policy = policy
        except (np.linalg.LinAlgError, ArithmeticError, RuntimeError):
            # Real feedback remains recorded. A failed numerical proposal cannot
            # replace the previous frozen policy and has no admission authority.
            self.metrics['fit_failures'] += 1
        finally:
            self.metrics['update_seconds'] += time.perf_counter() - started
            self._refresh_bytes()

    def _refresh_bytes(self):
        history = sum(item.observation.payload_bytes + 8 for state in self._reports.values()
                      for item in state.history)
        cache = sum(8 * len(item.cache) for state in self._reports.values() for item in state.history)
        self.metrics['history_bytes'], self.metrics['feature_cache_bytes'] = history, cache
        self.metrics['peak_history_bytes'] = max(self.metrics['peak_history_bytes'], history + cache)
        self.metrics['proposed_policy_bytes'] = sum(
            policy.payload_bytes for state in self._reports.values() for policy in state.proposals.values())

    def propose(self, report: str) -> FrozenPolicy:
        self._report_name(report)
        if report not in self._reports:
            return FrozenPolicy(INITIAL_FEATURES, (0.0,) * 7)
        state = self._reports[report]
        policy = state.policy
        state.proposals.setdefault(policy.digest, policy)
        # Up to 128 frozen versions per report; callers retaining older versions
        # still have immutable policies, but their promotion must be re-proposed.
        while len(state.proposals) > 128:
            expired = next(iter(state.proposals))
            state.proposals.pop(expired)
            state.promoted.discard(expired)
        self._refresh_bytes()
        return policy

    def on_promotion(self, report: str, policy: FrozenPolicy) -> None:
        self._report_name(report)
        if (type(policy) is not FrozenPolicy or report not in self._reports
                or self._reports[report].proposals.get(policy.digest) != policy):
            raise ValueError('promotion must name a frozen proposal from this report')
        state = self._reports[report]
        if policy.digest in state.promoted:
            return
        state.promoted.add(policy.digest)
        if self.mode != 'grow_reuse':
            return
        for mono, coefficient in zip(policy.features, policy.coefficients):
            if mono in INITIAL_FEATURES or abs(coefficient) <= 1e-8:
                continue
            if mono in self._bank:
                self._bank[mono] += 1
            elif len(self._bank) < self.bank_limit:
                self._bank[mono] = 1

    @property
    def bank(self) -> tuple[Mono, ...]:
        return tuple(sorted(self._bank, key=lambda m: (-self._bank[m], BASIS.index(m))))

    def report_summary(self, report: str) -> dict:
        self._report_name(report)
        state = self._reports.get(report)
        if state is None:
            return {'updates': 0, 'history': 0, 'features': INITIAL_FEATURES, 'bank_size': len(self._bank)}
        return {'updates': state.updates, 'history': len(state.history),
                'features': state.policy.features, 'active_features': state.active,
                'policy_digest': state.policy.digest, 'bank_size': len(self._bank),
                'last_fit_calls': self._fit_calls,
                'last_distinct_candidates': len(self._candidates_seen)}
