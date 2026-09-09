"""Compile bounded relational programs over selected, learned SQL views.

The model supplies a JSON AST, never outer SQL. Every outer relation reference,
operator and identifier is emitted by this compiler. Physical-table SQL occurs
only inside a selected source view. Sources must already have executed as
standalone read-only queries; the final request still needs the ordinary SQLite
authorizer and resource limits. Compilation is not an execution authorization.

This is capability confinement, not a semantic correctness or transfer proof.
In particular, a constant answer conditioned on a nonempty view can still pass
an empty-relation intervention. Measure overrides support the stronger, local
diagnostic of replacing derived columns while retaining all other source data.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Mapping, Protocol, Sequence

import sqlglot
from sqlglot import exp

from .fragments_v8 import Fragment, FragmentError, Scalar

MAX_PROGRAM_BYTES = 16_384
MAX_SQL_BYTES = 16_384
MAX_QUERY_PAYLOAD_BYTES = 65_536
MAX_PARAMETERS = 128
MAX_NODES = 128
MAX_DEPTH = 16
MAX_COLUMNS = 32
MAX_SOURCE_VIEWS = 4
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z", re.ASCII)
_BINARY = {
    "add": "+",
    "sub": "-",
    "mul": "*",
    "mod": "%",
    "eq": "=",
    "ne": "!=",
    "lt": "<",
    "le": "<=",
    "gt": ">",
    "ge": ">=",
    "and": "AND",
    "or": "OR",
}
_AGGREGATES = {"sum": "SUM", "avg": "AVG", "count": "COUNT", "min": "MIN", "max": "MAX"}


class ProgramError(ValueError):
    """The model program or selected source violates the compiler contract."""


def _scalar(value):
    try:
        Fragment.from_query("SELECT :value", {"value": value})
    except FragmentError as exc:
        raise ProgramError("invalid finite SQLite scalar") from exc
    if type(value) is str and len(value.encode("utf-8")) > 4096:
        raise ProgramError("text literal exceeds the executor cell limit")


@dataclass(frozen=True)
class PreparedQuery:
    """New compiler request with the unchanged executor's 16 KiB SQL limit."""

    sql: str
    bindings: tuple[tuple[str, Scalar], ...]

    def __post_init__(self):
        if type(self.sql) is not str or not 1 <= len(self.sql.encode("utf-8")) <= MAX_SQL_BYTES:
            raise ProgramError("compiled SQL byte limit exceeded")
        if (
            type(self.bindings) is not tuple
            or len(self.bindings) > MAX_PARAMETERS
            or any(type(pair) is not tuple or len(pair) != 2 for pair in self.bindings)
        ):
            raise ProgramError("bounded immutable parameter pairs required")
        names = []
        for name, value in self.bindings:
            _name(name)
            _scalar(value)
            names.append(name)
        if names != sorted(set(names)):
            raise ProgramError("parameter names must be sorted and unique")
        if (
            len(json.dumps(self.to_dict(), allow_nan=False).encode("utf-8"))
            > MAX_QUERY_PAYLOAD_BYTES
        ):
            raise ProgramError("compiled query payload byte limit exceeded")

    @property
    def parameters(self):
        return dict(self.bindings)

    def to_dict(self):
        return {"sql": self.sql, "parameters": self.parameters}


def _namespace_source(sql, witness, bindings, prefix):
    """Rename colon holes without changing any other source byte.

    Deliberately excludes comments, separators and alternative bind syntax.
    SQLGlot separately checks the standalone SELECT root; SQLite remains the
    authoritative execution parser. This lexer never authorizes a query.
    """
    if type(sql) is not str or not sql or "\x00" in sql or len(sql.encode("utf-8")) > MAX_SQL_BYTES:
        raise ProgramError("source SQL byte limit exceeded")
    if not isinstance(witness, Mapping) or type(bindings) is not dict:
        raise ProgramError("source bindings must be mappings")
    if len(witness) > MAX_PARAMETERS or witness.keys() != bindings.keys():
        raise ProgramError("source bindings must match the learned holes")
    for name, original in witness.items():
        _name(name)
        _scalar(original)
        _scalar(bindings[name])
        if type(bindings[name]) is not type(original):
            raise ProgramError("source bindings must preserve exact learned types")
    names = {name: prefix + str(i) for i, name in enumerate(sorted(witness))}
    pieces, seen = [], set()
    i = start = 0
    while i < len(sql):
        char = sql[i]
        if char in "'\"`[":
            closer = "]" if char == "[" else char
            i += 1
            while i < len(sql):
                if sql[i] == closer:
                    if char != "[" and i + 1 < len(sql) and sql[i + 1] == closer:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            else:
                raise ProgramError("unterminated source SQL quote")
            continue
        if sql.startswith(("--", "/*"), i) or char in ";?@$":
            raise ProgramError("unsupported source SQL comment, separator or parameter syntax")
        if char == ":":
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", sql[i + 1 :], re.ASCII)
            if match is None:
                raise ProgramError("malformed source parameter")
            name = match.group()
            end = i + 1 + len(name)
            if name not in names or (end < len(sql) and ord(sql[end]) >= 128):
                raise ProgramError("unknown or non-ASCII source parameter")
            pieces.extend((sql[start:i], ":" + names[name]))
            seen.add(name)
            i = start = end
            continue
        i += 1
    if seen != witness.keys():
        raise ProgramError("unused source binding")
    pieces.append(sql[start:])
    return PreparedQuery("".join(pieces), tuple(sorted((names[k], bindings[k]) for k in names)))


class SourceViewLike(Protocol):
    key: str
    sql: str
    params: Mapping[str, Scalar]
    columns: tuple[str, ...]
    measure_columns: tuple[str, ...]


Reference = tuple[str, str]


@dataclass(frozen=True)
class SourceUse:
    view_key: str
    bindings: tuple[tuple[str, Scalar], ...]


@dataclass(frozen=True)
class CompiledProgram:
    prepared: PreparedQuery
    used_views: tuple[str, ...]
    measure_references: tuple[Reference, ...]
    output_columns: tuple[str, ...]
    source_uses: tuple[SourceUse, ...]


@dataclass
class _Relation:
    name: str
    columns: dict[str, frozenset[Reference]]


def _name(value):
    if type(value) is not str or _NAME.fullmatch(value) is None:
        raise ProgramError("column names must be bounded ASCII identifiers")
    return value


def _quote(value):
    return '"' + _name(value) + '"'


def _object(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys():
        raise ProgramError("program object is missing required fields")
    if value.keys() - set(required) - set(optional):
        raise ProgramError("unsupported program fields")


def _list(value, minimum=0, maximum=MAX_COLUMNS):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ProgramError("program list exceeds its structural bound")
    return value


def _boolean(value):
    if type(value) is not bool:
        raise ProgramError("an explicit Boolean is required")
    return value


def _unique_names(names):
    if len(set(name.lower() for name in names)) != len(names):
        raise ProgramError("column names must be unique ignoring ASCII case")


class _Compiler:
    def __init__(self, views, measure_overrides):
        self.views = {}
        all_text = []
        for view in views:
            if type(view.key) is not str or not 1 <= len(view.key) <= 128:
                raise ProgramError("source view key must be bounded text")
            if view.key in self.views:
                raise ProgramError("duplicate selected source key")
            if type(view.columns) is not tuple or not 1 <= len(view.columns) <= MAX_COLUMNS:
                raise ProgramError("source columns must be a bounded immutable tuple")
            for column in view.columns:
                _name(column)
            _unique_names(view.columns)
            if (
                type(view.measure_columns) is not tuple
                or any(c not in view.columns for c in view.measure_columns)
                or len(set(view.measure_columns)) != len(view.measure_columns)
            ):
                raise ProgramError("derived measure columns must be unique source columns")
            try:
                # This parser checks the standalone root; emitted source text is
                # unchanged. Source execution at acquisition is a separate duty.
                _namespace_source(view.sql, view.params, dict(view.params), "validation_")
                roots = sqlglot.parse(view.sql, read="sqlite")
                if len(roots) != 1 or not isinstance(roots[0], exp.Select):
                    raise ProgramError("source must be one standalone SELECT")
            except (FragmentError, sqlglot.errors.ParseError) as exc:
                raise ProgramError("invalid standalone source SQL") from exc
            self.views[view.key] = view
            all_text.extend((view.sql.lower(), view.key.lower(), *view.columns))
        if len(self.views) > MAX_SOURCE_VIEWS:
            raise ProgramError("too many selected source views")
        occupied = "\n".join(all_text).lower()
        nonce = 0
        while f"wcl_program_{nonce}_" in occupied:
            nonce += 1
        self.prefix = f"wcl_program_{nonce}_"
        self.overrides = {} if measure_overrides is None else measure_overrides
        if type(self.overrides) is not dict:
            raise ProgramError("measure overrides must be a host mapping")
        for key, replacements in self.overrides.items():
            if key not in self.views or type(replacements) is not dict or not replacements:
                raise ProgramError("measure override names an unknown source")
            view = self.views[key]
            for column, value in replacements.items():
                if column not in view.measure_columns:
                    raise ProgramError("only derived measure columns may be overridden")
                if not (value is None or (type(value) is int and value == 0)):
                    raise ProgramError("measure intervention must be integer zero or NULL")
        self.nodes = 0
        self.ctes = []
        self.bindings = {}
        self.used = set()
        self.references = set()
        self.source_uses = []

    def tick(self, depth):
        self.nodes += 1
        if depth > MAX_DEPTH or self.nodes > MAX_NODES:
            raise ProgramError("program depth or node bound exceeded")

    def literal(self, value):
        _scalar(value)
        name = self.prefix + "literal_" + str(len(self.bindings))
        self.bindings[name] = value
        return ":" + name

    def add_relation(self, sql, columns):
        name = self.prefix + "relation_" + str(len(self.ctes))
        self.ctes.append((_quote(name), sql))
        return _Relation(name, columns)

    def expression(self, node, contexts, depth):
        self.tick(depth)
        if type(node) is not dict or type(node.get("op")) is not str:
            raise ProgramError("expression requires a named operation")
        op = node["op"]
        if op == "col":
            _object(node, ("op", "name"), ("side",))
            name = _name(node["name"])
            side = node.get("side", "input")
            if type(side) is not str or side not in contexts:
                raise ProgramError("column reference has no such input side")
            alias, columns = contexts[side]
            if name not in columns:
                raise ProgramError("column is absent from the selected input")
            return _quote(alias) + "." + _quote(name), columns[name]
        if op == "lit":
            _object(node, ("op", "value"))
            return self.literal(node["value"]), frozenset()
        if op in _BINARY or op in ("div", "safe_div"):
            _object(node, ("op", "left", "right"))
            left, lrefs = self.expression(node["left"], contexts, depth + 1)
            right, rrefs = self.expression(node["right"], contexts, depth + 1)
            if op == "div":
                sql = f"((1.0 * {left}) / {right})"
            elif op == "safe_div":
                sql = f"COALESCE((1.0 * {left}) / NULLIF({right}, 0), 0)"
            else:
                sql = f"({left} {_BINARY[op]} {right})"
            return sql, lrefs | rrefs
        if op in ("neg", "not", "is_null", "abs"):
            _object(node, ("op", "value"))
            value, refs = self.expression(node["value"], contexts, depth + 1)
            sql = {
                "neg": f"(-{value})",
                "not": f"(NOT {value})",
                "is_null": f"({value} IS NULL)",
                "abs": f"ABS({value})",
            }[op]
            return sql, refs
        if op == "coalesce":
            _object(node, ("op", "args"))
            args = [self.expression(x, contexts, depth + 1) for x in _list(node["args"], 2, 8)]
            return "COALESCE(" + ", ".join(x[0] for x in args) + ")", frozenset().union(
                *(x[1] for x in args)
            )
        if op == "case":
            _object(node, ("op", "when", "then", "else"))
            args = [self.expression(node[k], contexts, depth + 1) for k in ("when", "then", "else")]
            return (
                f"(CASE WHEN {args[0][0]} THEN {args[1][0]} ELSE {args[2][0]} END)",
                frozenset().union(*(x[1] for x in args)),
            )
        if op == "in":
            _object(node, ("op", "value", "options"))
            value, refs = self.expression(node["value"], contexts, depth + 1)
            options = [
                self.expression(x, contexts, depth + 1) for x in _list(node["options"], 1, 16)
            ]
            return f"({value} IN (" + ", ".join(x[0] for x in options) + "))", refs.union(
                *(x[1] for x in options)
            )
        raise ProgramError("unsupported expression operation")

    def relation(self, node, depth=0):
        self.tick(depth)
        if type(node) is not dict or type(node.get("op")) is not str:
            raise ProgramError("relation requires a named operation")
        op = node["op"]
        if op == "scan":
            _object(node, ("op", "view"), ("bindings",))
            key = node["view"]
            if type(key) is not str or key not in self.views:
                raise ProgramError("scan must select an available learned view")
            view = self.views[key]
            params = node.get("bindings", dict(view.params))
            if type(params) is not dict:
                raise ProgramError("scan bindings must be a JSON object")
            source = _namespace_source(
                view.sql,
                view.params,
                params,
                self.prefix + "scan_" + str(len(self.source_uses)) + "_",
            )
            self.bindings.update(source.parameters)
            self.source_uses.append(SourceUse(key, tuple(sorted(params.items()))))
            self.used.add(key)
            columns = {c: frozenset(((key, c),)) for c in view.columns}
            source_relation = self.add_relation(source.sql, columns)
            if key in self.overrides:
                selections = []
                for column in view.columns:
                    value = self.overrides[key].get(column, "unchanged")
                    term = (
                        '"s".' + _quote(column)
                        if value == "unchanged"
                        else ("NULL" if value is None else "0")
                    )
                    selections.append(term + " AS " + _quote(column))
                source_relation = self.add_relation(
                    "SELECT "
                    + ", ".join(selections)
                    + " FROM "
                    + _quote(source_relation.name)
                    + ' AS "s"',
                    columns,
                )
            return source_relation
        if op == "join":
            _object(node, ("op", "left", "right", "kind", "on"))
            if node["kind"] not in ("inner", "left"):
                raise ProgramError("only inner and left joins are supported")
            left = self.relation(node["left"], depth + 1)
            right = self.relation(node["right"], depth + 1)
            predicate, refs = self.expression(
                node["on"], {"left": ("l", left.columns), "right": ("r", right.columns)}, depth + 1
            )
            self.references.update(refs)
            columns = {}
            selections = []
            for prefix, alias, relation in (("left_", "l", left), ("right_", "r", right)):
                for name, lineage in relation.columns.items():
                    output = _name(prefix + name)
                    selections.append(f"{_quote(alias)}.{_quote(name)} AS {_quote(output)}")
                    columns[output] = lineage
            if len(columns) > MAX_COLUMNS:
                raise ProgramError("join output exceeds the column bound")
            return self.add_relation(
                "SELECT "
                + ", ".join(selections)
                + " FROM "
                + _quote(left.name)
                + ' AS "l" '
                + node["kind"].upper()
                + " JOIN "
                + _quote(right.name)
                + ' AS "r" ON '
                + predicate,
                columns,
            )
        if op not in ("filter", "project", "group"):
            raise ProgramError("unsupported relation operation")
        if op == "filter":
            _object(node, ("op", "input", "where"))
        elif op == "project":
            _object(node, ("op", "input", "columns"), ("distinct",))
        else:
            _object(node, ("op", "input", "keys", "aggregates"))
        child = self.relation(node["input"], depth + 1)
        contexts = {"input": ("i", child.columns)}
        from_sql = " FROM " + _quote(child.name) + ' AS "i"'
        if op == "filter":
            predicate, refs = self.expression(node["where"], contexts, depth + 1)
            self.references.update(refs)
            return self.add_relation(
                'SELECT "i".*' + from_sql + " WHERE " + predicate, child.columns
            )
        selections = []
        columns = {}
        group_by = []
        items = _list(node["columns"], 1) if op == "project" else _list(node["keys"], 0, 8)
        for item in items:
            _object(item, ("name", "expr"))
            name = _name(item["name"])
            expression, refs = self.expression(item["expr"], contexts, depth + 1)
            selections.append(expression + " AS " + _quote(name))
            if op == "group":
                group_by.append(expression)
                self.references.update(refs)
            if name in columns:
                raise ProgramError("duplicate output column")
            columns[name] = refs
        if op == "group":
            for aggregate in _list(node["aggregates"], 1, 16):
                self.tick(depth + 1)
                _object(aggregate, ("name", "op"), ("expr", "distinct"))
                name = _name(aggregate["name"])
                kind = aggregate["op"]
                if type(kind) is not str or kind not in _AGGREGATES:
                    raise ProgramError("unsupported aggregation")
                distinct = _boolean(aggregate.get("distinct", False))
                if "expr" not in aggregate:
                    if kind != "count" or distinct:
                        raise ProgramError("only nondistinct COUNT may omit its expression")
                    expression, refs = "*", frozenset()
                else:
                    expression, refs = self.expression(aggregate["expr"], contexts, depth + 1)
                if name in columns:
                    raise ProgramError("duplicate group output column")
                columns[name] = refs
                selections.append(
                    _AGGREGATES[kind]
                    + "("
                    + ("DISTINCT " if distinct else "")
                    + expression
                    + ") AS "
                    + _quote(name)
                )
        _unique_names(columns)
        if len(columns) > MAX_COLUMNS:
            raise ProgramError("relation output exceeds the column bound")
        distinct_sql = (
            "DISTINCT " if op == "project" and _boolean(node.get("distinct", False)) else ""
        )
        sql = "SELECT " + distinct_sql + ", ".join(selections) + from_sql
        if group_by:
            sql += " GROUP BY " + ", ".join(group_by)
        return self.add_relation(sql, columns)


def compile_program(
    program: dict,
    selected_views: Sequence[SourceViewLike],
    *,
    measure_overrides: dict[str, dict[str, int | None]] | None = None,
) -> CompiledProgram:
    """Compile one model AST to one SELECT, with no database access.

    ``measure_overrides`` is a host-only offline intervention, never an AST
    field. It changes only named derived measures, retaining rows and every
    other column. The normal and intervened executions require identical
    programs/bindings and separate charged execution receipts.
    """
    try:
        serialized = json.dumps(program, allow_nan=False, ensure_ascii=False)
        if len(serialized.encode("utf-8")) > MAX_PROGRAM_BYTES:
            raise ProgramError("program JSON byte bound exceeded")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProgramError("program must be bounded finite JSON") from exc
    compiler = _Compiler(selected_views, measure_overrides)
    relation = compiler.relation(program)
    sql = "WITH " + ", ".join(name + " AS (" + body + ")" for name, body in compiler.ctes)
    sql += " SELECT " + ", ".join('"output".' + _quote(c) for c in relation.columns)
    sql += " FROM " + _quote(relation.name) + ' AS "output"'
    all_refs = compiler.references.union(*(refs for refs in relation.columns.values()))
    measure_refs = tuple(
        sorted(
            (key, column)
            for key, column in all_refs
            if column in compiler.views[key].measure_columns
        )
    )
    if compiler.overrides.keys() - compiler.used:
        raise ProgramError("intervention names a source absent from this program")
    try:
        prepared = PreparedQuery(sql, tuple(sorted(compiler.bindings.items())))
    except ProgramError as exc:
        raise ProgramError("compiled query exceeds the SQL/payload limits") from exc
    return CompiledProgram(
        prepared,
        tuple(sorted(compiler.used)),
        measure_refs,
        tuple(relation.columns),
        tuple(compiler.source_uses),
    )


PROGRAM_GUIDE = """Use a JSON relational program; never provide SQL inside it.
Relation nodes:
scan: {"op":"scan","view":"visible key","bindings":{}} (bindings optional).
filter: {"op":"filter","input":REL,"where":EXPR}.
project: {"op":"project","input":REL,"columns":[{"name":"answer","expr":EXPR}],"distinct":false}.
group: {"op":"group","input":REL,"keys":[{"name":"key","expr":EXPR}],"aggregates":[{"name":"answer","op":"sum","expr":EXPR,"distinct":false}]}.
Use keys=[] for a scalar aggregate. Aggregates are sum/avg/count/min/max;
only nondistinct count may omit expr. Ratios use project over grouped outputs.
Nested groups are allowed, for example MAX over per-customer SUM results.
join: {"op":"join","left":REL,"right":REL,"kind":"inner","on":EXPR}.
Join kind is inner/left. Its predicate columns require side=left/right; outputs
are named left_<old_name> and right_<old_name>. Other columns omit side.
Expressions: {"op":"col","name":"m0"}; {"op":"lit","value":0};
binary {"op":"add","left":EXPR,"right":EXPR}, with add/sub/mul/div/safe_div/mod,
eq/ne/lt/le/gt/ge/and/or. div is REAL division; safe_div returns zero for NULL or
zero denominators. Unary neg/not/is_null/abs use value:EXPR.
coalesce uses args:[EXPR,...]; case uses when/then/else:EXPR;
in uses value:EXPR and options:[EXPR,...]. Literals are finite numbers/text/NULL.
Use only actual visible source columns; no physical table names or SQL nodes.
"""
