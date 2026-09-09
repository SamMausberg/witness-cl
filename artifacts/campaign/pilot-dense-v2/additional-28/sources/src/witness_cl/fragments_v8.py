"""Immutable typed SQL fragments learned from a caller's observed query.

This module compiles data; it never opens a database or executes SQL. SQL chunks
remain untrusted and every compiled request must use the same restricted SQLite
executor as an ordinary query. Exact reconstruction of a witness is not evidence
that different bindings, composition, or a future database answer correctly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Mapping, TypeAlias

Scalar: TypeAlias = int | float | str | None
MAX_SQL_BYTES = 4096
# Nodes in the Text/Hole fragment AST, not nodes in SQLite's internal SQL AST.
MAX_SYNTAX_NODES = 32
MAX_PAYLOAD_BYTES = 8192
_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z', re.ASCII)
_START = re.compile(r'\s*(?:SELECT|WITH)\b', re.IGNORECASE | re.ASCII)
_OUTER = re.compile(r'\s*SELECT\b', re.IGNORECASE | re.ASCII)


class FragmentError(ValueError):
    """A fragment or binding failed the fixed compiler's structural contract."""


def _kind(value: Scalar) -> str:
    if value is None:
        return 'null'
    if type(value) is int:
        if not -(2**63) <= value < 2**63:
            raise FragmentError('integer binding is outside SQLite signed int64')
        return 'integer'
    if type(value) is float:
        if not math.isfinite(value):
            raise FragmentError('real binding must be finite')
        return 'real'
    if type(value) is str:
        if '\x00' in value:
            raise FragmentError('NUL text bindings are unsupported')
        return 'text'
    raise FragmentError('bindings must be exact int, finite float, str, or None; bool is not integer')


def _canonical(value) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError) as exc:
        raise FragmentError('payload is not valid finite UTF-8 JSON') from exc


def _pairs(bindings: Mapping[str, Scalar]) -> tuple[tuple[str, Scalar], ...]:
    if not isinstance(bindings, Mapping):
        raise FragmentError('bindings must be a mapping')
    for name, value in bindings.items():
        if type(name) is not str or not _NAME.fullmatch(name):
            raise FragmentError('binding names must be ASCII identifiers without colon')
        _kind(value)
    result = tuple(sorted(bindings.items()))
    if len(_canonical(dict(result))) > MAX_PAYLOAD_BYTES:
        raise FragmentError('binding payload limit exceeded')
    return result


@dataclass(frozen=True)
class Text:
    value: str


@dataclass(frozen=True)
class Hole:
    name: str
    kind: str


Part: TypeAlias = Text | Hole


def _lex(sql: str, kinds: Mapping[str, str]) -> tuple[Part, ...]:
    """Split named parameters, respecting SQLite's four identifier/string quotes.

    This is a parameter lexer, not a SQL semantic parser or authorization layer.
    Comments, statement separators and alternate parameter forms are deliberately
    unsupported. All bytes outside parameter names are preserved.
    """
    if type(sql) is not str or not sql or '\x00' in sql:
        raise FragmentError('SQL must be nonempty text without NUL')
    try:
        sql_size = len(sql.encode('utf-8'))
    except UnicodeError as exc:
        raise FragmentError('SQL must be valid UTF-8') from exc
    if sql_size > MAX_SQL_BYTES:
        raise FragmentError('SQL byte limit exceeded')
    if not _START.match(sql):
        raise FragmentError('a SELECT or WITH query is required')
    parts: list[Part] = []
    seen = set()
    start = i = 0
    while i < len(sql):
        char = sql[i]
        if char in "'\"`[":
            closer = ']' if char == '[' else char
            i += 1
            while i < len(sql):
                if sql[i] == closer:
                    # SQLite escapes quotes/backticks by doubling; bracket
                    # identifiers end at their first closing bracket.
                    if char != '[' and i + 1 < len(sql) and sql[i + 1] == closer:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            else:
                raise FragmentError('unterminated SQL quote')
            continue
        if sql.startswith('--', i) or sql.startswith('/*', i):
            raise FragmentError('SQL comments are unsupported')
        if char == ';':
            raise FragmentError('statement separators are unsupported')
        if char in '?@$':
            raise FragmentError('only colon-named bindings are supported')
        if char == ':':
            match = re.match(r'[A-Za-z_][A-Za-z0-9_]*', sql[i + 1:], re.ASCII)
            if match is None:
                raise FragmentError('malformed named parameter')
            name = match.group()
            end = i + len(name) + 1
            # SQLite admits non-ASCII bytes in parameter identifiers. Splitting
            # :xé as the hole x plus a text chunk would name a different SQLite
            # binding and would break structural namespace renaming.
            if end < len(sql) and ord(sql[end]) >= 128:
                raise FragmentError('parameter names must end at an ASCII token boundary')
            if name not in kinds:
                raise FragmentError('missing binding for :' + name)
            if i > start:
                parts.append(Text(sql[start:i]))
            parts.append(Hole(name, kinds[name]))
            seen.add(name)
            i = end
            start = i
            continue
        i += 1
    if start < len(sql):
        parts.append(Text(sql[start:]))
    if set(kinds) != seen:
        raise FragmentError('unused binding names are forbidden')
    if len(parts) > MAX_SYNTAX_NODES:
        raise FragmentError('fragment syntax-node limit exceeded')
    return tuple(parts)


@dataclass(frozen=True)
class PreparedQuery:
    sql: str
    bindings: tuple[tuple[str, Scalar], ...]

    def __post_init__(self):
        if type(self.bindings) is not tuple or any(type(pair) is not tuple or len(pair) != 2
                                                   for pair in self.bindings):
            raise FragmentError('prepared bindings must be immutable pairs')
        if _pairs(dict(self.bindings)) != self.bindings:
            raise FragmentError('prepared bindings must be sorted and unique')
        if type(self.sql) is not str or len(self.sql.encode('utf-8')) > MAX_SQL_BYTES:
            raise FragmentError('compiled SQL byte limit exceeded')
        if len(_canonical({'sql': self.sql, 'bindings': dict(self.bindings)})) > MAX_PAYLOAD_BYTES:
            raise FragmentError('compiled payload limit exceeded')

    @property
    def parameters(self) -> dict[str, Scalar]:
        return dict(self.bindings)

    def to_dict(self) -> dict:
        return {'sql': self.sql, 'parameters': self.parameters}


@dataclass(frozen=True)
class Fragment:
    sql: str
    witness: tuple[tuple[str, Scalar], ...]
    parts: tuple[Part, ...] = field(init=False)
    holes: tuple[Hole, ...] = field(init=False)

    def __post_init__(self):
        if type(self.witness) is not tuple or any(type(pair) is not tuple or len(pair) != 2
                                                for pair in self.witness):
            raise FragmentError('witness must be immutable binding pairs')
        pairs = _pairs(dict(self.witness))
        if pairs != self.witness:
            raise FragmentError('witness binding pairs must be sorted and unique')
        kinds = {name: _kind(value) for name, value in pairs}
        parts = _lex(self.sql, kinds)
        object.__setattr__(self, 'parts', parts)
        object.__setattr__(self, 'holes', tuple(Hole(name, kinds[name]) for name in sorted(kinds)))
        if len(_canonical(self.to_dict())) > MAX_PAYLOAD_BYTES:
            raise FragmentError('fragment payload limit exceeded')

    @classmethod
    def from_query(cls, sql: str, bindings: Mapping[str, Scalar] | None = None) -> Fragment:
        return cls(sql, _pairs({} if bindings is None else bindings))

    def _payload(self) -> dict:
        return {'format_version': 1, 'sql': self.sql,
                'holes': [{'name': h.name, 'kind': h.kind} for h in self.holes],
                'witness': dict(self.witness)}

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self._payload())).hexdigest()

    def to_dict(self) -> dict:
        return {**self._payload(), 'sha256': self.digest}

    @classmethod
    def from_dict(cls, payload: dict) -> Fragment:
        if type(payload) is not dict or set(payload) != {'format_version', 'sql', 'holes', 'witness', 'sha256'}:
            raise FragmentError('invalid fragment payload fields')
        if type(payload['format_version']) is not int or payload['format_version'] != 1:
            raise FragmentError('unsupported fragment format')
        if len(_canonical(payload)) > MAX_PAYLOAD_BYTES:
            raise FragmentError('fragment payload limit exceeded')
        rebuilt = cls.from_query(payload['sql'], payload['witness'])
        if _canonical(payload) != _canonical(rebuilt.to_dict()):
            raise FragmentError('fragment digest or typed witness metadata mismatch')
        return rebuilt

    def _checked(self, bindings: Mapping[str, Scalar] | None) -> tuple[tuple[str, Scalar], ...]:
        pairs = self.witness if bindings is None else _pairs(bindings)
        if {name: _kind(value) for name, value in pairs} != {h.name: h.kind for h in self.holes}:
            raise FragmentError('binding names and exact types must match the learned holes')
        return pairs

    def compile(self, bindings: Mapping[str, Scalar] | None = None) -> PreparedQuery:
        pairs = self._checked(bindings)
        sql = ''.join(p.value if isinstance(p, Text) else ':' + p.name for p in self.parts)
        return PreparedQuery(sql, pairs)

    @property
    def original_prepared_query(self) -> PreparedQuery:
        return PreparedQuery(self.sql, self.witness)

    def _namespaced(self, prefix: str, bindings: Mapping[str, Scalar] | None) -> PreparedQuery:
        pairs = self._checked(bindings)
        names = {hole.name: prefix + str(i) for i, hole in enumerate(self.holes)}
        sql = ''.join(p.value if isinstance(p, Text) else ':' + names[p.name] for p in self.parts)
        return PreparedQuery(sql, tuple(sorted((names[name], value) for name, value in pairs)))

    def compose(self, outer_sql: str, outer_bindings: Mapping[str, Scalar] | None = None, *,
                alias: str, bindings: Mapping[str, Scalar] | None = None) -> PreparedQuery:
        if type(alias) is not str or not _NAME.fullmatch(alias):
            raise FragmentError('CTE alias must be an ASCII identifier')
        if type(outer_sql) is not str or not _OUTER.match(outer_sql):
            raise FragmentError('composition requires an outer SELECT')
        outer = Fragment.from_query(outer_sql, outer_bindings)
        inner_query = self._namespaced('wcl_inner_', bindings)
        outer_query = outer._namespaced('wcl_outer_', None)
        sql = f'WITH "{alias}" AS ({inner_query.sql}) {outer_query.sql}'
        return PreparedQuery(sql, tuple(sorted(inner_query.bindings + outer_query.bindings)))
