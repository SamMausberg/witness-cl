"""Conservative source-derived row views; no database access or semantic oracle.

Only a successful caller-owned scalar aggregate is eligible at the *caller*.
This module does not inspect rewards, execute a query, or certify generalization.
Its AST transformation must still pass a charged SQLite reconstruction check.
In particular, preserving SUM on every database does not identify AVG semantics.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
import hashlib
import json
import math
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, build_scope

MAX_SOURCE_BYTES = 16_384
MAX_GENERATED_BYTES = 16_384
MAX_AST_NODES = 2_048
MAX_COLUMNS = 128
MAX_MEASURES = 16
MAX_BINDINGS = 128
_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z', re.ASCII)
_ASCII_FOLD = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
_AGGREGATES = (exp.Sum, exp.Avg, exp.Count, exp.Min, exp.Max)
_SCALAR_FUNCTIONS = (exp.Coalesce, exp.Nullif, exp.Cast, exp.Round, exp.Abs)
_PROJECTION_NODES = (
    exp.Alias, exp.Identifier, exp.Literal, exp.Null, exp.Paren,
    exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Neg, exp.Placeholder,
    exp.DataType, exp.DataTypeParam,
)


class UnsupportedSource(ValueError):
    """The declared, conservative lifting language does not cover this source."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _FrozenDict(dict):
    """JSON-serializable immutable snapshot, including against augmented update."""

    def _immutable(self, *args, **kwargs):
        raise TypeError('SourceView mappings are immutable')

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable
    __ior__ = _immutable

    def __deepcopy__(self, memo):
        return self


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def _text(value, limit, label):
    if type(value) is not str or not value or '\x00' in value:
        raise UnsupportedSource(f'{label} must be nonempty text without NUL')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError as exc:
        raise UnsupportedSource(f'{label} must be UTF-8') from exc
    if size > limit:
        raise UnsupportedSource(f'{label} byte limit exceeded')


def _bindings(params):
    if not isinstance(params, Mapping) or len(params) > MAX_BINDINGS:
        raise UnsupportedSource('at most 128 named scalar bindings are supported')
    result = {}
    for name, value in params.items():
        if type(name) is not str or len(name) > 64 or not _NAME.fullmatch(name):
            raise UnsupportedSource('binding names must be ASCII identifiers of at most 64 chars')
        valid = value is None or type(value) is str
        valid |= type(value) is int and -(2**63) <= value < 2**63
        valid |= type(value) is float and math.isfinite(value)
        if not valid:
            raise UnsupportedSource('bindings must be finite SQLite scalar values; bool is excluded')
        if type(value) is str:
            if '\x00' in value:
                raise UnsupportedSource('NUL binding text is unsupported')
            try:
                size = len(value.encode('utf-8'))
            except UnicodeError as exc:
                raise UnsupportedSource('binding text must be UTF-8') from exc
            if size > 4096:
                raise UnsupportedSource('binding text byte limit exceeded')
        result[name] = value
    return result


def _digest(payload):
    # The question is provenance rather than the executable identity.
    semantic = {k: v for k, v in payload.items() if k not in {'key', 'question'}}
    return hashlib.sha256(_canonical(semantic).encode('utf-8')).hexdigest()


def _column_identity(column):
    # SQLite identifiers ignore ASCII case, including inside quoted names.
    return column.table.translate(_ASCII_FOLD), column.name.translate(_ASCII_FOLD)


@dataclass(frozen=True)
class SourceView:
    key: str
    sql: str
    params: dict
    columns: tuple[str, ...]
    lineage: dict[str, str]
    column_origins: dict[str, str]
    measure_columns: tuple[str, ...]
    source_sql: str
    source_params: dict
    reconstruction_sql: str
    reconstruction_params: dict
    question: str

    def __post_init__(self):
        _text(self.sql, MAX_GENERATED_BYTES, 'view SQL')
        _text(self.source_sql, MAX_SOURCE_BYTES, 'source SQL')
        _text(self.reconstruction_sql, MAX_GENERATED_BYTES, 'reconstruction SQL')
        _text(self.question, MAX_SOURCE_BYTES, 'question')
        if (type(self.columns) is not tuple or not 1 <= len(self.columns) <= MAX_COLUMNS
                or any(type(c) is not str or not _NAME.fullmatch(c) for c in self.columns)
                or len({c.lower() for c in self.columns}) != len(self.columns)):
            raise UnsupportedSource('view columns must be unique bounded ASCII identifiers')
        if (type(self.measure_columns) is not tuple
                or not 1 <= len(self.measure_columns) <= MAX_MEASURES
                or len(set(self.measure_columns)) != len(self.measure_columns)
                or not set(self.measure_columns) <= set(self.columns)):
            raise UnsupportedSource('measure columns must be a nonempty subset of view columns')
        if (not isinstance(self.lineage, Mapping) or set(self.lineage) != set(self.columns)
                or any(type(v) is not str or not v for v in self.lineage.values())):
            raise UnsupportedSource('each view column requires expression lineage')
        if (not isinstance(self.column_origins, Mapping)
                or set(self.column_origins) != set(self.columns)
                or any(type(v) is not str or v not in {
                    'physical_column', 'derived_or_unresolved_column', 'scalar_expression', 'row_marker'}
                       for v in self.column_origins.values())):
            raise UnsupportedSource('each view column requires a conservative origin classification')
        for name in ('params', 'source_params', 'reconstruction_params'):
            object.__setattr__(self, name, _FrozenDict(_bindings(getattr(self, name))))
        object.__setattr__(self, 'lineage', _FrozenDict(self.lineage))
        object.__setattr__(self, 'column_origins', _FrozenDict(self.column_origins))
        if type(self.key) is not str or self.key != _digest(self.to_dict()):
            raise UnsupportedSource('view key does not match its payload')

    def to_dict(self):
        result = {f.name: getattr(self, f.name) for f in fields(self)}
        for key in ('params', 'lineage', 'column_origins', 'source_params', 'reconstruction_params'):
            result[key] = dict(result[key])
        for key in ('columns', 'measure_columns'):
            result[key] = list(result[key])
        return result

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping) or set(value) != {f.name for f in fields(cls)}:
            raise UnsupportedSource('serialized SourceView has unexpected fields')
        payload = dict(value)
        for key in ('columns', 'measure_columns'):
            if type(payload[key]) not in (list, tuple):
                raise UnsupportedSource(f'{key} must be a sequence')
            payload[key] = tuple(payload[key])
        return cls(**payload)


def _lexical_check(sql):
    """Reject unsupported comments/binding forms outside SQLite quoted tokens."""
    i = 0
    while i < len(sql):
        char = sql[i]
        if char in "'\"`[":
            end = ']' if char == '[' else char
            i += 1
            while i < len(sql):
                if sql[i] == end:
                    if end != ']' and i + 1 < len(sql) and sql[i + 1] == end:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            else:
                raise UnsupportedSource('unterminated quoted token')
            continue
        if sql.startswith('--', i) or sql.startswith('/*', i):
            raise UnsupportedSource('comments are outside the lifting language')
        if char in '?@$':
            raise UnsupportedSource('only colon-named bindings are supported')
        if char == ';' and sql[i + 1:].strip():
            raise UnsupportedSource('exactly one statement is required')
        i += 1


def _schema(public_schema):
    """Accept public CREATE TABLE DDL or table -> column -> declared type mappings."""
    if isinstance(public_schema, str):
        _text(public_schema, 65_536, 'public schema')
        result = {}
        try:
            statements = sqlglot.parse(public_schema, read='sqlite')
        except SqlglotError as exc:
            raise UnsupportedSource('cannot parse public schema') from exc
        for node in statements:
            if (not isinstance(node, exp.Create) or node.args.get('kind') != 'TABLE'
                    or not isinstance(node.this, exp.Schema)
                    or not isinstance(node.this.this, exp.Table)):
                raise UnsupportedSource('public schema must contain only explicit CREATE TABLE DDL')
            table = node.this.this
            if table.db or table.catalog:
                raise UnsupportedSource('qualified databases are unsupported')
            columns = {}
            for definition in node.this.expressions:
                if isinstance(definition, exp.ColumnDef):
                    kind = definition.args.get('kind')
                    columns[definition.name] = kind.sql() if kind else 'UNKNOWN'
            if not columns or table.name.lower() in {k.lower() for k in result}:
                raise UnsupportedSource('public schema tables require unique names and columns')
            result[table.name] = columns
    elif isinstance(public_schema, Mapping):
        result = {}
        for table, columns in public_schema.items():
            if not isinstance(columns, Mapping):
                raise UnsupportedSource('public schema mapping requires column/type mappings')
            result[table] = dict(columns)
    else:
        raise UnsupportedSource('public schema must be DDL text or a table/column mapping')
    if not result or len(result) > 128:
        raise UnsupportedSource('public schema requires at most 128 nonempty tables')
    normalized = {}
    for table, columns in result.items():
        if type(table) is not str or not table or not columns or len(columns) > MAX_COLUMNS:
            raise UnsupportedSource('invalid public table or column count')
        if table.lower() in normalized:
            raise UnsupportedSource('case-insensitive duplicate public table')
        normalized[table.lower()] = {}
        for column, dtype in columns.items():
            if type(column) is not str or not column or type(dtype) is not str:
                raise UnsupportedSource('public columns require text names and declared types')
            if column.lower() in normalized[table.lower()]:
                raise UnsupportedSource('case-insensitive duplicate public column')
            normalized[table.lower()][column.lower()] = dtype
    return normalized


def _parameter_names(tree):
    names = set()
    for node in tree.find_all(exp.Placeholder):
        if not node.name or not _NAME.fullmatch(node.name):
            raise UnsupportedSource('only colon-named placeholders are supported')
        names.add(node.name)
    if tree.find(exp.Parameter):
        raise UnsupportedSource('alternate parameters are unsupported')
    return names


def _parameterize_where(tree, bindings):
    index = 0
    for where in tree.find_all(exp.Where):
        for comparison in where.find_all(exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE):
            # Nested WHEREs are visited separately, with no repeated literal after replacement.
            left, right = comparison.this, comparison.expression
            literal = (right if isinstance(left, exp.Column) else
                       left if isinstance(right, exp.Column) else None)
            if not isinstance(literal, exp.Literal) or not literal.is_string:
                continue
            while f'sv_text_{index}' in bindings:
                index += 1
            name = f'sv_text_{index}'
            bindings[name] = literal.this
            literal.replace(exp.Placeholder(this=name))
            index += 1
    if len(bindings) > MAX_BINDINGS:
        raise UnsupportedSource('lifting would exceed the binding limit')


def _validate_tree(tree):
    if not isinstance(tree, exp.Select) or len(tree.expressions) != 1:
        raise UnsupportedSource('one scalar SELECT projection is required')
    if tree.args.get('from_') is None:
        raise UnsupportedSource('a row source is required')
    for key in ('distinct', 'group', 'having', 'qualify', 'order', 'limit', 'offset',
                'windows', 'locks', 'into', 'laterals', 'connect', 'match'):
        if tree.args.get(key):
            raise UnsupportedSource(f'root {key} is outside the scalar aggregate language')
    for node in tree.walk():
        if isinstance(node, (exp.DDL, exp.DML, exp.Command)):
            raise UnsupportedSource('only read-only SELECT syntax is supported')
        if isinstance(node, (exp.Union, exp.Intersect, exp.Except, exp.Window,
                             exp.Lateral, exp.Values, exp.Filter, exp.WithinGroup)):
            raise UnsupportedSource(f'{type(node).__name__} is outside the lifting language')
        if isinstance(node, exp.With) and node.args.get('recursive'):
            raise UnsupportedSource('recursive CTEs are unsupported')
        if isinstance(node, exp.Join) and (node.args.get('using') or node.args.get('method')):
            raise UnsupportedSource('USING/NATURAL joins require unsupported coalesced-column handling')
        if isinstance(node, exp.Func) and not isinstance(
                node, _AGGREGATES + _SCALAR_FUNCTIONS + (exp.And, exp.Or, exp.Case, exp.If)):
            raise UnsupportedSource(f'function {type(node).__name__} is outside the lifting language')
        if isinstance(node, exp.Table) and (node.db or node.catalog or not node.name):
            raise UnsupportedSource('only unqualified named table/CTE sources are supported')
    if sum(1 for _ in tree.walk()) > MAX_AST_NODES:
        raise UnsupportedSource('AST node limit exceeded')


def lift_source(sql, params, public_schema, question) -> SourceView:
    """Lift a supported own aggregate into a row relation and scalar reconstruction.

    Exposed c-columns are qualified columns of the root FROM/JOIN sources, in
    public schema/projection order. m-columns are distinct aggregate arguments;
    an exact matching c-column is removed so it cannot bypass m-intervention.
    COUNT(*) gets a constant 1 marker. Predicates are preserved, not removed.
    column_origins marks every CTE/subquery output as derived_or_unresolved;
    it does not recursively prove expression equivalence or physical lineage.
    Different CTE columns can still compute the same value. An m-column role
    alone does not establish that a normalization was learned: it can be a
    direct physical column, an expression, an unresolved output, or a row marker.
    String equality/range literals directly compared to columns in WHERE become
    witness-bound parameters. Rebinding is a hypothesis, not a proved contract.
    """
    _text(sql, MAX_SOURCE_BYTES, 'source SQL')
    _text(question, MAX_SOURCE_BYTES, 'question')
    original_params = _bindings(params)
    bindings = dict(original_params)
    _lexical_check(sql)
    schema = _schema(public_schema)
    try:
        statements = [x for x in sqlglot.parse(sql, read='sqlite') if x is not None]
        if len(statements) != 1:
            raise UnsupportedSource('exactly one statement is required')
        tree = statements[0]
        _validate_tree(tree)
        if not _parameter_names(tree) <= bindings.keys():
            raise UnsupportedSource('source SQL is missing a named binding')
        tree = qualify(tree, dialect='sqlite', schema=schema, infer_schema=False,
                       quote_identifiers=True, identify=True, validate_qualify_columns=True,
                       allow_partial_qualification=False)
        scope = build_scope(tree)
        if scope is None:
            raise UnsupportedSource('unable to resolve source scope')
        for nested in scope.traverse():
            for _, source in nested.selected_sources.values():
                if isinstance(source, exp.Table) and source.name.lower() not in schema:
                    raise UnsupportedSource('source table is absent from the public schema')
        if scope.external_columns:
            raise UnsupportedSource('unresolved root column references')
        _parameterize_where(tree, bindings)
        identifiers = {x.name.lower() for x in tree.find_all(exp.Identifier)}
        alias = 'sv_reconstruct'
        while alias.lower() in identifiers:
            alias += '_'
        expressions, lineage, origins = [], {}, {}
        source_columns = {}
        for table_alias, (_, source) in scope.selected_sources.items():
            if isinstance(source, Scope):
                names = source.expression.named_selects
                if (not names or any(not x or x == '*' for x in names)
                        or len({x.lower() for x in names}) != len(names)):
                    raise UnsupportedSource('derived source requires unique explicit output columns')
            elif isinstance(source, exp.Table):
                names = list(schema[source.name.lower()])
            else:
                raise UnsupportedSource('unsupported source scope')
            for column in names:
                expr = exp.column(column, table=table_alias, quoted=True)
                name = f'c{len(expressions)}'
                expressions.append(exp.alias_(expr, name, quoted=True))
                lineage[name] = expr.sql(dialect='sqlite')
                origins[name] = ('derived_or_unresolved_column' if isinstance(source, Scope)
                                 else 'physical_column')
                source_columns[_column_identity(expr)] = name
        measures = {}
        duplicate_columns = set()

        def rewrite(node):
            if isinstance(node, _AGGREGATES):
                if node.expressions or any(node.args.get(k) for k in ('filter', 'order')):
                    raise UnsupportedSource('multiargument or ordered aggregates are unsupported')
                argument = node.this
                distinct = isinstance(argument, exp.Distinct)
                if distinct:
                    if len(argument.expressions) != 1:
                        raise UnsupportedSource('DISTINCT requires one aggregate argument')
                    argument = argument.expressions[0]
                while isinstance(argument, exp.Paren):
                    argument = argument.this
                row_marker = isinstance(argument, exp.Star)
                if isinstance(argument, exp.Star):
                    if not isinstance(node, exp.Count) or distinct:
                        raise UnsupportedSource('only COUNT(*) supports a star')
                    argument = exp.Literal.number(1)
                if argument is None or argument.find(exp.AggFunc, exp.Subquery, exp.Order, exp.Star):
                    raise UnsupportedSource('aggregate arguments must be scalar row expressions')
                encoded = argument.sql(dialect='sqlite')
                if encoded not in measures:
                    if len(measures) >= MAX_MEASURES:
                        raise UnsupportedSource('measure column limit exceeded')
                    name = f'm{len(measures)}'
                    measures[encoded] = name
                    expressions.append(exp.alias_(argument.copy(), name, quoted=True))
                    lineage[name] = encoded
                    duplicate = (source_columns.get(_column_identity(argument))
                                 if isinstance(argument, exp.Column) else None)
                    if duplicate is not None:
                        duplicate_columns.add(duplicate)
                        origins[name] = origins[duplicate]
                    else:
                        origins[name] = 'row_marker' if row_marker else 'scalar_expression'
                column = exp.column(measures[encoded], table=alias, quoted=True)
                result = node.copy()
                result.set('this', exp.Distinct(expressions=[column]) if distinct else column)
                return result
            if not isinstance(node, _PROJECTION_NODES + _SCALAR_FUNCTIONS):
                raise UnsupportedSource('projection must contain only supported scalar aggregates/arithmetic')
            result = node.copy()
            for key, child in node.args.items():
                if isinstance(child, exp.Expression):
                    result.set(key, rewrite(child))
                elif isinstance(child, list):
                    result.set(key, [rewrite(x) if isinstance(x, exp.Expression) else x for x in child])
            return result

        reconstruction_projection = rewrite(tree.expressions[0])
        if not measures:
            raise UnsupportedSource('at least one supported aggregate is required')
        expressions = [e for e in expressions if e.alias not in duplicate_columns]
        lineage = {k: v for k, v in lineage.items() if k not in duplicate_columns}
        origins = {k: v for k, v in origins.items() if k not in duplicate_columns}
        if len(expressions) > MAX_COLUMNS:
            raise UnsupportedSource('lifted column limit exceeded')
        view = tree.copy()
        view.set('expressions', expressions)
        view_sql = view.sql(dialect='sqlite')
        # A subquery retains the original CTE's lexical scope without exporting
        # its names into a caller's outer query. No rows are materialized here.
        reconstruction = exp.select(reconstruction_projection).from_(
            exp.Subquery(this=view.copy(), alias=exp.TableAlias(this=exp.to_identifier(alias, quoted=True))))
        reconstruction_sql = reconstruction.sql(dialect='sqlite')
        payload = {
            'sql': view_sql,
            'params': {k: bindings[k] for k in sorted(_parameter_names(view))},
            'columns': tuple(lineage), 'lineage': lineage, 'column_origins': origins,
            'measure_columns': tuple(measures.values()),
            'source_sql': sql, 'source_params': original_params,
            'reconstruction_sql': reconstruction_sql,
            'reconstruction_params': {
                k: bindings[k] for k in sorted(_parameter_names(reconstruction))},
            'question': question,
        }
        return SourceView(key=_digest(payload), **payload)
    except UnsupportedSource:
        raise
    except (SqlglotError, KeyError, TypeError, ValueError, RecursionError) as exc:
        raise UnsupportedSource(f'cannot safely lift source: {type(exc).__name__}: {exc}') from exc


def reconstruct(view: SourceView, *, empty: bool = False) -> tuple[str, dict]:
    """Return a charged scalar reconstruction request, optionally emptying rows.

    The empty intervention preserves the *outer aggregate*, including COALESCE
    and arithmetic. It shows witness dependence on source rows, not future
    usefulness or dependence on a particular learned measure column.
    """
    if not isinstance(view, SourceView) or type(empty) is not bool:
        raise UnsupportedSource('reconstruct requires a SourceView and a Boolean empty flag')
    if not empty:
        return view.reconstruction_sql, dict(view.reconstruction_params)
    tree = sqlglot.parse_one(view.reconstruction_sql, read='sqlite')
    relation = tree.args['from_'].this
    inner = relation.this
    empty_relation = exp.select('*').from_(
        exp.Subquery(this=inner.copy(), alias=exp.TableAlias(
            this=exp.to_identifier('sv_empty', quoted=True)))).where(exp.false())
    relation.set('this', empty_relation)
    sql = tree.sql(dialect='sqlite')
    _text(sql, MAX_GENERATED_BYTES, 'empty reconstruction SQL')
    return sql, dict(view.reconstruction_params)
