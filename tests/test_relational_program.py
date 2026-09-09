"""Compiler semantics and adversarial cases; no model-generated evidence."""

from copy import deepcopy
from dataclasses import dataclass, replace
import sqlite3

import pytest
import sqlglot
from sqlglot import exp

from witness_cl.relational_program import (
    MAX_DEPTH,
    PreparedQuery,
    ProgramError,
    compile_program,
)
from witness_cl.sql_env_v8 import PublicEpisode, _Table
from witness_cl.sql_env_v9 import make_stream, open_episode


@dataclass(frozen=True)
class View:
    key: str = "amounts"
    sql: str = (
        "SELECT customer AS c0, amount AS c1, region AS c2, COALESCE(amount,0) AS m0 FROM data"
    )
    params: dict | None = None
    columns: tuple = ("c0", "c1", "c2", "m0")
    measure_columns: tuple = ("m0",)

    def __post_init__(self):
        if self.params is None:
            object.__setattr__(self, "params", {})


def col(name, side=None):
    value = {"op": "col", "name": name}
    if side:
        value["side"] = side
    return value


def lit(value):
    return {"op": "lit", "value": value}


def binary(op, left, right):
    return {"op": op, "left": left, "right": right}


def scan(key="amounts", **kwargs):
    return {"op": "scan", "view": key, **kwargs}


def project(child, expression, name="answer"):
    return {"op": "project", "input": child, "columns": [{"name": name, "expr": expression}]}


def group(child, operation="sum", expression=None, *, name="answer", keys=None, **kwargs):
    agg = {"name": name, "op": operation, **kwargs}
    if expression is not None:
        agg["expr"] = expression
    return {"op": "group", "input": child, "keys": keys or [], "aggregates": [agg]}


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:", cached_statements=0)
    conn.execute("CREATE TABLE data(customer TEXT, amount INTEGER, region TEXT)")
    conn.executemany(
        "INSERT INTO data VALUES(?,?,?)",
        [("A", 1, "N"), ("A", None, "N"), ("B", 3, "S"), ("B", 3, "S")],
    )
    conn.execute("CREATE TABLE tags(customer TEXT, weight REAL)")
    conn.executemany("INSERT INTO tags VALUES(?,?)", [("A", 2.0), ("B", 4.0)])
    yield conn
    conn.close()


def execute(db, program, views=None, **kwargs):
    compiled = compile_program(program, [View()] if views is None else views, **kwargs)
    return db.execute(compiled.prepared.sql, compiled.prepared.parameters).fetchall(), compiled


@pytest.mark.parametrize(
    "operation,expression,expected",
    [
        ("sum", col("m0"), 7),
        ("avg", col("m0"), 1.75),
        ("count", None, 4),
        ("min", col("m0"), 0),
        ("max", col("m0"), 3),
    ],
)
def test_basic_aggregates_and_measure_lineage(db, operation, expression, expected):
    rows, compiled = execute(db, group(scan(), operation, expression))
    assert rows == [(expected,)]
    assert compiled.used_views == ("amounts",)
    assert compiled.output_columns == ("answer",)
    assert compiled.measure_references == (() if expression is None else (("amounts", "m0"),))


def test_distinct_and_projection(db):
    rows, _ = execute(db, group(scan(), "count", col("m0"), distinct=True))
    assert rows == [(3,)]
    program = project(scan(), col("c0"), "customer")
    program["distinct"] = True
    rows, _ = execute(db, program)
    assert sorted(rows) == [("A",), ("B",)]


def test_filter_case_and_real_ratio(db):
    conditional = {
        "op": "case",
        "when": binary("eq", col("c2"), lit("N")),
        "then": col("m0"),
        "else": lit(0),
    }
    grouped = group(scan(), "sum", conditional, name="numerator")
    grouped["aggregates"].append({"name": "denominator", "op": "sum", "expr": col("m0")})
    program = project(grouped, binary("safe_div", col("numerator"), col("denominator")))
    rows, compiled = execute(db, program)
    assert rows == [(1 / 7,)]
    assert compiled.measure_references == (("amounts", "m0"),)
    filtered = {"op": "filter", "input": scan(), "where": binary("eq", col("c2"), lit("N"))}
    assert execute(db, group(filtered, "sum", col("m0")))[0] == [(1,)]


def test_nested_group_then_max_has_no_bare_aggregate_columns(db):
    grouped = group(
        scan(), "sum", col("m0"), name="total", keys=[{"name": "customer", "expr": col("c0")}]
    )
    rows, compiled = execute(db, group(grouped, "max", col("total")))
    assert rows == [(6,)]
    assert compiled.measure_references == (("amounts", "m0"),)


@pytest.mark.parametrize("kind", ["inner", "left"])
def test_join_two_selected_views_then_group(db, kind):
    other = View(
        key="weights", sql="SELECT customer AS c0, weight AS m0 FROM tags", columns=("c0", "m0")
    )
    joined = {
        "op": "join",
        "left": scan(),
        "right": scan("weights"),
        "kind": kind,
        "on": binary("eq", col("c0", "left"), col("c0", "right")),
    }
    program = group(joined, "sum", binary("mul", col("left_m0"), col("right_m0")))
    rows, compiled = execute(db, program, [View(), other])
    assert rows == [(26.0,)]
    assert compiled.used_views == ("amounts", "weights")
    assert compiled.measure_references == (("amounts", "m0"), ("weights", "m0"))


def test_left_join_preserves_unmatched_rows(db):
    db.execute("DELETE FROM tags WHERE customer='B'")
    other = View(
        key="weights", sql="SELECT customer AS c0, weight AS m0 FROM tags", columns=("c0", "m0")
    )
    joined = {
        "op": "join",
        "left": scan(),
        "right": scan("weights"),
        "kind": "left",
        "on": binary("eq", col("c0", "left"), col("c0", "right")),
    }
    assert execute(db, group(joined, "count"), [View(), other])[0] == [(4,)]


def test_measure_override_preserves_rows_raw_columns_and_nulls(db):
    program = group(scan(), "sum", col("m0"), name="derived")
    program["aggregates"].extend(
        [
            {"name": "raw", "op": "sum", "expr": col("c1")},
            {"name": "rows", "op": "count"},
            {"name": "nonnull", "op": "count", "expr": col("m0")},
        ]
    )
    assert execute(db, program)[0] == [(7, 7, 4, 4)]
    assert execute(db, program, measure_overrides={"amounts": {"m0": 0}})[0] == [(0, 7, 4, 4)]
    assert execute(db, program, measure_overrides={"amounts": {"m0": None}})[0] == [(None, 7, 4, 0)]


def test_raw_recomputation_has_no_derived_measure_contribution(db):
    program = group(scan(), "sum", {"op": "coalesce", "args": [col("c1"), lit(0)]})
    factual, compiled = execute(db, program)
    counterfactual, _ = execute(db, program, measure_overrides={"amounts": {"m0": 0}})
    assert factual == counterfactual == [(7,)]
    assert compiled.measure_references == ()


def test_measure_used_in_filter_remains_reported_after_projection(db):
    filtered = {"op": "filter", "input": scan(), "where": binary("gt", col("m0"), lit(0))}
    rows, compiled = execute(db, group(filtered, "count"))
    assert rows == [(3,)]
    assert compiled.measure_references == (("amounts", "m0"),)


@pytest.mark.parametrize(
    "overrides",
    [
        {"amounts": {"c1": 0}},
        {"amounts": {"m0": 1}},
        {"amounts": {"m0": False}},
        {"amounts": {"m0": 0.0}},
        {"missing": {"m0": 0}},
        {"amounts": {}},
    ],
)
def test_interventions_cannot_change_raw_columns_or_inject_values(overrides):
    with pytest.raises(ProgramError):
        compile_program(group(scan(), "sum", col("m0")), [View()], measure_overrides=overrides)


def test_parameter_namespaces_are_independent_across_scans_and_literals(db):
    view = View(sql=View().sql + " WHERE region=:region", params={"region": "N"})
    joined = {
        "op": "join",
        "left": scan(bindings={"region": "N"}),
        "right": scan(bindings={"region": "S"}),
        "kind": "inner",
        "on": binary("eq", lit(1), lit(1)),
    }
    rows, compiled = execute(db, group(joined, "sum", col("right_m0")), [view])
    assert rows == [(12,)]
    assert len(compiled.prepared.bindings) == 4
    assert sorted(v for _, v in compiled.prepared.bindings if type(v) is str) == ["N", "S"]
    assert [dict(use.bindings) for use in compiled.source_uses] == [
        {"region": "N"},
        {"region": "S"},
    ]


@pytest.mark.parametrize("bindings", [{}, {"region": 1}, {"region": "N", "extra": 1}, []])
def test_rebinding_preserves_exact_learned_holes(bindings):
    view = View(sql=View().sql + " WHERE region=:region", params={"region": "N"})
    with pytest.raises(ProgramError):
        compile_program(scan(bindings=bindings), [view])


def test_source_quote_lexer_preserves_colons_and_escaped_quotes(db):
    sql = "SELECT ':x'';--@$?' AS c0, :x AS m0 FROM data WHERE region=:x"
    view = View(sql=sql, params={"x": "N"}, columns=("c0", "m0"))
    rows, compiled = execute(db, scan(), [view])
    assert rows == [(":x';--@$?", "N"), (":x';--@$?", "N")]
    assert "':x'';--@$?'" in compiled.prepared.sql
    assert len(compiled.prepared.parameters) == 1


def test_cte_and_parameter_prefixes_cannot_be_shadowed(db):
    view = View(
        sql=(
            "WITH wcl_program_0_relation_0 AS (SELECT amount FROM data) "
            "SELECT amount AS m0 FROM wcl_program_0_relation_0"
        ),
        columns=("m0",),
    )
    rows, compiled = execute(db, group(scan(), "sum", col("m0")), [view])
    assert rows == [(7,)]
    assert '"wcl_program_1_relation_0" AS' in compiled.prepared.sql


@pytest.mark.parametrize(
    "program",
    [
        {"op": "sql", "sql": "SELECT * FROM data"},
        {"op": "scan", "view": "data"},
        {"op": "scan", "view": "amounts", "sql": "SELECT * FROM data"},
        project(scan(), {"op": "raw", "sql": "(WITH reused AS (SELECT * FROM data) SELECT 1)"}),
        project(scan(), col('m0" FROM data; SELECT "m0')),
        project(scan(), col("data.amount")),
        project(scan(), {"op": "call", "function": "load_extension", "args": [lit("x")]}),
        project(scan(), {"op": "sum", "value": col("m0")}),
        project(scan(), col("m0", "left")),
        {"op": "scan", "view": ["amounts"]},
        {"op": [], "input": scan()},
        {"op": "filter", "input": scan(), "where": None},
    ],
)
def test_no_outer_raw_sql_tables_functions_or_malformed_nodes(program):
    with pytest.raises(ProgramError):
        compile_program(program, [View()])


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), 2**63, {}, [], "x" * 4097])
def test_invalid_literals_fail_closed(value):
    with pytest.raises(ProgramError):
        compile_program(project(scan(), lit(value)), [View()])


def test_binding_strings_cannot_become_sql(db):
    attack = "x'); WITH reused AS (SELECT * FROM data) SELECT 999; --"
    rows, compiled = execute(db, project(scan(), lit(attack)))
    assert rows == [(attack,)] * 4
    assert attack not in compiled.prepared.sql


@pytest.mark.parametrize(
    "sql,params",
    [
        ("SELECT amount AS m0 FROM data); SELECT 99", {}),
        ("DELETE FROM data RETURNING amount AS m0", {}),
        ("SELECT amount AS m0 FROM data -- comment", {}),
        ("SELECT :xé AS m0", {"x": 1}),
        ("SELECT ? AS m0", {}),
        ("SELECT :missing AS m0", {}),
        ("SELECT 1 AS m0", {"unused": 1}),
    ],
)
def test_invalid_source_transport_cannot_escape_cte(sql, params):
    with pytest.raises(ProgramError):
        compile_program(scan(), [View(sql=sql, params=params, columns=("m0",))])


def test_program_structural_and_output_bounds():
    nested = scan()
    for _ in range(MAX_DEPTH + 1):
        nested = {"op": "filter", "input": nested, "where": lit(1)}
    with pytest.raises(ProgramError, match="depth"):
        compile_program(nested, [View()])
    cyclic = {"op": "filter", "where": lit(1)}
    cyclic["input"] = cyclic
    with pytest.raises(ProgramError):
        compile_program(cyclic, [View()])
    program = project(scan(), col("m0"), "Answer")
    program["columns"].append({"name": "answer", "expr": lit(0)})
    with pytest.raises(ProgramError, match="unique"):
        compile_program(program, [View()])
    broad = project(scan(), lit(0))
    broad["columns"] = [
        {"name": f"x{i}", "expr": binary("add", lit(1), binary("mul", lit(2), lit(3)))}
        for i in range(32)
    ]
    with pytest.raises(ProgramError, match="node"):
        compile_program(broad, [View()])


def test_lifted_source_can_exceed_legacy_four_kib_limit(db):
    view = View(sql="SELECT " + " " * 4300 + "amount AS m0 FROM data", columns=("m0",))
    rows, compiled = execute(db, group(scan(), "sum", col("m0")), [view])
    assert rows == [(7,)]
    assert len(compiled.prepared.sql.encode()) > 4096
    with pytest.raises(ProgramError):
        compile_program(scan(), [replace(view, sql="SELECT " + " " * 17000 + "1 AS m0")])


def test_cte_composition_retains_sqlite_text_affinity(db):
    db.execute("INSERT INTO data VALUES ('1', 5, 'N')")
    filtered = {"op": "filter", "input": scan(), "where": binary("eq", col("c0"), lit(1))}
    assert execute(db, group(filtered, "count"))[0] == [(1,)]


def test_sum_preservation_does_not_identify_avg_null_semantics(db):
    db.execute("DELETE FROM data")
    db.executemany("INSERT INTO data VALUES(?,?,?)", [("A", None, "N"), ("A", 2, "N")])
    raw = View(sql="SELECT amount AS m0 FROM data", columns=("m0",))
    zero = View(sql="SELECT COALESCE(amount,0) AS m0 FROM data", columns=("m0",))
    assert execute(db, group(scan(), "sum", col("m0")), [raw])[0] == [(2,)]
    assert execute(db, group(scan(), "sum", col("m0")), [zero])[0] == [(2,)]
    assert execute(db, group(scan(), "avg", col("m0")), [raw])[0] == [(2.0,)]
    assert execute(db, group(scan(), "avg", col("m0")), [zero])[0] == [(1.0,)]


def test_finite_reconstruction_and_empty_dependence_still_do_not_prove_transfer(db):
    counted = group(scan(), "count", name="n")
    program = project(
        counted,
        {"op": "case", "when": binary("gt", col("n"), lit(0)), "then": lit(3), "else": lit(0)},
    )
    db.execute("DELETE FROM data")
    db.executemany("INSERT INTO data VALUES(?,?,?)", [("A", 1, "N"), ("A", 2, "N")])
    assert execute(db, program)[0] == [(3,)]
    db.execute("DELETE FROM data")
    assert execute(db, program)[0] == [(0,)]
    db.executemany("INSERT INTO data VALUES(?,?,?)", [("A", 2, "N"), ("A", 2, "N")])
    assert execute(db, program)[0] == [(3,)]
    assert db.execute("SELECT SUM(amount) FROM data").fetchone() == (4,)


def test_outer_relation_references_are_host_generated(db):
    program = project(group(scan(), "sum", col("m0")), binary("safe_div", col("answer"), lit(7)))
    _, compiled = execute(db, program)
    tree = sqlglot.parse_one(compiled.prepared.sql, read="sqlite")
    physical = [
        table for table in tree.find_all(exp.Table) if not table.name.startswith("wcl_program_")
    ]
    assert [table.name for table in physical] == ["data"]
    source_cte = tree.args["with_"].expressions[0]
    assert all(table.find_ancestor(exp.CTE) is source_cte for table in physical)


def test_compiled_program_executes_with_one_charged_bounded_select():
    table = _Table(
        "data",
        (("customer", "TEXT"), ("amount", "INTEGER"), ("region", "TEXT")),
        (("A", 1, "N"), ("A", None, "N"), ("B", 3, "S")),
    )
    original = make_stream(94001, "reuse").ordinary[0]
    spec = replace(original, _tables=(table,), _public=PublicEpisode("Return total.", table.ddl))
    compiled = compile_program(group(scan(), "sum", col("m0")), [View()])
    with open_episode(spec) as session:
        result = session.query(compiled.prepared.sql, compiled.prepared.parameters)
        assert result.error is None and result.rows == ((4,),)
        assert session.select_attempts == 1


def test_prepared_query_is_immutable_and_returns_parameter_copies():
    prepared = PreparedQuery("SELECT :x", (("x", 3),))
    params = prepared.parameters
    params["x"] = 5
    assert prepared.parameters == {"x": 3}
    with pytest.raises(ProgramError):
        PreparedQuery("SELECT :x", (("x", 1), ("x", 2)))


def test_compilation_does_not_mutate_program_or_sources():
    view = View()
    program = group(scan(), "sum", col("m0"))
    saved = deepcopy((program, view))
    compile_program(program, [view], measure_overrides={"amounts": {"m0": 0}})
    assert (program, view) == saved


def test_real_source_view_lift_rebinds_and_changes_only_derived_measure(db):
    from witness_cl.source_views import lift_source

    view = lift_source(
        "SELECT COALESCE(SUM(amount),0) FROM data WHERE region='N'",
        {},
        {"data": {"customer": "TEXT", "amount": "INTEGER", "region": "TEXT"}},
        "Total amount in N?",
    )
    program = group(scan(view.key, bindings={"sv_text_0": "S"}), "sum", col("m0"))
    assert execute(db, program, [view])[0] == [(6,)]
    assert execute(db, program, [view], measure_overrides={view.key: {"m0": 0}})[0] == [(0,)]
    assert execute(db, program, [view], measure_overrides={view.key: {"m0": None}})[0] == [(None,)]


def test_invalid_source_column_metadata_cannot_use_sqlite_quoted_string_fallback(db):
    view = View(sql="SELECT amount AS actual FROM data", columns=("missing",), measure_columns=())
    compiled = compile_program(scan(), [view])
    with pytest.raises(sqlite3.OperationalError, match="no such column"):
        db.execute(compiled.prepared.sql, compiled.prepared.parameters)


@pytest.mark.parametrize(
    "expression,expected",
    [
        (binary("add", lit(2), lit(3)), 5),
        (binary("sub", lit(2), lit(3)), -1),
        (binary("mod", lit(5), lit(3)), 2),
        (binary("div", lit(1), lit(2)), 0.5),
        (binary("div", lit(1), lit(0)), None),
        (binary("safe_div", lit(1), lit(0)), 0),
        (binary("safe_div", lit(None), lit(2)), 0),
        (binary("ne", lit(2), lit(3)), 1),
        (binary("lt", lit(2), lit(3)), 1),
        (binary("le", lit(2), lit(2)), 1),
        (binary("ge", lit(2), lit(3)), 0),
        (binary("and", lit(1), lit(None)), None),
        (binary("or", lit(1), lit(None)), 1),
        ({"op": "not", "value": lit(None)}, None),
        ({"op": "neg", "value": lit(3)}, -3),
        ({"op": "abs", "value": lit(-3)}, 3),
        ({"op": "is_null", "value": lit(None)}, 1),
        ({"op": "in", "value": lit(2), "options": [lit(1), lit(2)]}, 1),
    ],
)
def test_expression_sqlite_semantics(db, expression, expected):
    rows, _ = execute(db, project(group(scan(), "count"), expression))
    assert rows == [(expected,)]
