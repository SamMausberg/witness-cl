#!/usr/bin/env python3
"""Independent campaign SQL replay, provenance chains and causal diagnostics.

No model calls or learner mutations. The caller separately verifies the run
freeze, exact prompt replay and population protocol. Test doubles are counted
and can never become empirical qualifying events.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage

from experiments.audit_sql_abstractions_v9 import SQLiteReplayV9
from witness_cl.campaign_env import make_episode
from witness_cl.delayed_memory import (
    CompatibilityScope, DelayedEntry, DelayedMemory, Witness,
    normalized_template, reconstruct_bound,
)
from witness_cl.query_memory import canonical, digest
from witness_cl.relational_program import ProgramError, compile_program
from witness_cl.source_views import SourceView, _schema, lift_source
from witness_cl.sql_env_v9 import evaluator_metadata

RESULT_FIELDS = ("columns", "rows", "error", "truncated")
CATALOG_SQL = ("SELECT table_name,column_name,description FROM catalog "
               "ORDER BY table_name,column_name,description")


class AuditError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AuditError(message)


def exact(actual, expected, message):
    require(canonical(actual) == canonical(expected), message)


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def correct(value, expected):
    return finite(value) and abs(value - expected) <= 1e-6 * (1 + abs(expected))


def scalar(result):
    if result["error"] is not None or result["truncated"]:
        return {"status": "execution_failure", "value": None}
    rows = result["rows"]
    if len(rows) != 1 or len(rows[0]) != 1:
        return {"status": "nonscalar", "value": None}
    value = rows[0][0]
    return {"status": "numeric" if finite(value) else "null" if value is None else "nonnumeric",
            "value": value}


def _words(text):
    return set(re.findall(r"[a-z][a-z0-9_]*", text.lower()))


def _select(before, question, scope, episode_index, arm):
    entries = []
    for payload in before.get("registry", {}).get("entries", []):
        entry = DelayedEntry.from_dict(payload)
        if (entry.scope == scope and entry.source.episode_index < episode_index
                and (arm == "immediate" or (entry.corroboration is not None
                     and entry.corroboration.episode_index < episode_index))):
            entries.append(entry)
    ranked = sorted(enumerate(entries), key=lambda pair: (
        len(_words(question) & _words(pair[1].view.question)), pair[0]), reverse=True)
    return [entry for _, entry in ranked[:4]]


def resolve_measure_lineage(view: SourceView, column: str, public_schema: str):
    """Resolve CTE/projection aliases to physical-column computation paths.

    This proves syntactic dataflow through the supplied SQL. It does not prove
    business meaning, multiplicity correctness, or equivalence on other data.
    Ambiguous/unresolved leaves and unsupported expressions remain unknown.
    """
    report = {"column": column, "recorded_origin": view.column_origins[column],
              "status": "unknown", "physical_columns": [], "nodes": [],
              "computed_from_physical_columns": False,
              "scope": "Resolved SQL dataflow only; no semantic-equivalence or meaning proof."}
    try:
        schema = _schema(public_schema)
        root = lineage(column, view.sql, dialect="sqlite", schema=schema)
        nodes = list(root.walk())
        require(len(nodes) <= 256, "lineage graph bound exceeded")
        physical, transformed, unknown = set(), False, False
        operations = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Neg,
                      exp.Coalesce, exp.Nullif, exp.Cast, exp.Round, exp.Abs,
                      exp.Sum, exp.Avg, exp.Count, exp.Min, exp.Max, exp.Case, exp.If)
        for node in nodes:
            expression = node.expression
            report["nodes"].append({"name": node.name, "expression": expression.sql(dialect="sqlite"),
                                    "children": [child.name for child in node.downstream]})
            if isinstance(expression, exp.Table):
                reference = sqlglot.parse_one(node.name, read="sqlite")
                table = expression.name.lower()
                if (not isinstance(reference, exp.Column) or table not in schema
                        or reference.name.lower() not in schema[table]
                        or expression.db or expression.catalog):
                    unknown = True
                else:
                    physical.add((table, reference.name.lower()))
                continue
            body = expression.this if isinstance(expression, exp.Alias) else expression
            while isinstance(body, exp.Paren):
                body = body.this
            if not node.downstream:
                if body.find(exp.Column) is not None or not isinstance(body, (exp.Literal, exp.Null)):
                    unknown = True
            if body.find(exp.Subquery, exp.Window, exp.Star) is not None:
                unknown = True
            for parameter in body.find_all(exp.Placeholder):
                if parameter.name not in view.params:
                    unknown = True
            transformed |= any(isinstance(part, operations) for part in body.walk())
            for part in body.find_all(exp.Func):
                if not isinstance(part, operations):
                    unknown = True
        report["physical_columns"] = [list(pair) for pair in sorted(physical)]
        if not unknown:
            report["status"] = ("resolved_computation" if physical and transformed else
                                "resolved_physical_copy" if physical else "constant_only")
            report["computed_from_physical_columns"] = bool(physical and transformed)
    except (ValueError, TypeError, KeyError, RecursionError, sqlglot.errors.SqlglotError) as exc:
        report["reason"] = str(exc)[:256]
    return report


def _operations(program):
    counts, aggregates = Counter(), set()

    def visit(node):
        if isinstance(node, dict):
            if node.get("op") == "group":
                counts["groups"] += 1
                counts["groups_with_keys"] += bool(node["keys"])
                aggregates.update(item["op"] for item in node["aggregates"])
            if node.get("op") == "join":
                counts["joins"] += 1
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(program)
    return {"aggregates": sorted(aggregates), **{name: counts[name] for name in
                                               ("groups", "groups_with_keys", "joins")}}


def _source_operations(view):
    tree = sqlglot.parse_one(view.source_sql, read="sqlite")
    return sorted({part.key for part in tree.expressions[0].find_all(exp.AggFunc)})


def _usage(trace):
    totals = Counter()
    records = trace.get("model_calls")
    require(type(records) is list, "model call ledger missing")
    for call in records:
        require(type(call.get("generation_attempted")) is bool, "call attempt flag missing")
        attempted = call["generation_attempted"]
        totals["generation_calls"] += attempted
        totals["test_double_calls"] += call.get("test_double") is True
        require(call.get("status") in {"completed", "failed", "preflight_failed"},
                "unfinished or unknown call status")
        if call.get("test_double") is not True:
            require(type(call.get("request_config")) is dict
                    and type(call.get("max_output_tokens")) is int and call["max_output_tokens"] > 0,
                    "real inference call lacks effective request/output-cap receipt")
            if attempted:
                require(type(call.get("preflight_tokens")) is int,
                        "real inference attempt lacks token preflight")
        usage = call.get("usage")
        if usage is None:
            totals["unknown_usage_calls"] += attempted
            continue
        require(attempted, "usage without generation")
        values = [usage.get(name) for name in ("prompt_tokens", "completion_tokens", "total_tokens")]
        require(all(type(value) is int and value >= 0 for value in values), "invalid exact token ledger")
        require(values[0] + values[1] == values[2], "token sum mismatch")
        for key, value in zip(("prompt_tokens", "completion_tokens", "total_tokens"), values):
            totals[key] += value
        if "max_output_tokens" in call:
            require(values[1] <= call["max_output_tokens"], "output cap exceeded")
        if call.get("preflight_tokens") is not None:
            require(type(call["preflight_tokens"]) is int and call["preflight_tokens"] >= 0,
                    "invalid preflight count")
            require(values[0] >= call["preflight_tokens"], "prompt usage below preflight")
    solve_calls = [call for call in records if call.get("phase") == trace["phase"] + ":solve"]
    reflection_calls = [call for call in records if call not in solve_calls]
    require(len(solve_calls) <= 5,
            "solver action-call allowance exceeded")
    completed = sum(call["status"] == "completed" for call in solve_calls)
    require(completed >= len(trace["actions"]), "action lacks a completed solver call")
    if trace["status"] in {"completed", "no_valid_answer"}:
        require(completed == len(trace["actions"]), "completed solver/action count mismatch")
    require(not reflection_calls or (trace["arm"] == "ace" and trace["learn"]
            and len(reflection_calls) <= 2 and all(call.get("phase") in {
                "ace:reflector:reflection", "ace:curator:reflection"} for call in reflection_calls)),
            "undeclared model calls outside solver/ACE updates")
    return dict(totals)


def _spec(record):
    trace = record["trace"]
    metadata = trace.get("evaluator", {})
    spec = make_episode(record["seed"], metadata["split"], record["condition"],
                        record["phase"], record["index"],
                        old_replicates=metadata.get("old_replicates", 8))
    exact(metadata, evaluator_metadata(spec), "evaluator fixture provenance mismatch")
    exact(trace["question"], spec._public.question, "public question mismatch")
    exact(trace["schema"], spec._public.schema, "public schema mismatch")
    return spec


def _compiled(compiled):
    return {"sql": compiled.prepared.sql, "params": compiled.prepared.parameters,
            "used_views": list(compiled.used_views),
            "measure_references": list(compiled.measure_references),
            "source_uses": [asdict(use) for use in compiled.source_uses]}


def _audit_actions(trace, views):
    ordinary = [(index, query) for index, query in enumerate(trace["queries"])
                if not query["learning_check"] and not query.get("host_issued")]
    require(len(ordinary) == len(trace["actions"]), "action/query cardinality mismatch")
    compiled = {}
    for action_index, (action, (_, query)) in enumerate(zip(trace["actions"], ordinary)):
        if "invalid" in action:
            require(query["purpose"] == "invalid_action", "invalid action purpose mismatch")
            exact((query["sql"], query["params"]), ("", {}), "invalid action executed SQL")
            continue
        require(type(action.get("answer")) is bool, "terminal request must be Boolean")
        kind = action.get("action")
        if kind == "QUERY":
            exact((query["sql"], query["params"]), (action["sql"], action["params"]),
                  "direct action/request mismatch")
            require(query["purpose"] == "ordinary", "direct query purpose mismatch")
            exact(query["terminal_requested"], action["answer"], "terminal request mismatch")
            continue
        require(kind in {"USE", "COMPOSE", "PROGRAM"}, "unknown action")
        if trace["arm"] not in {"delayed", "immediate"}:
            require(query["purpose"] == "unavailable_action", "unavailable executable action ran")
            exact((query["sql"], query["params"]), ("", {}), "unavailable action executed SQL")
            continue
        program = ({"op": "scan", "view": action["view"], "bindings": action["params"]}
                   if kind == "USE" else action["program"])
        try:
            built = compile_program(program, views)
        except (ProgramError, ValueError, TypeError, KeyError, RecursionError):
            require(query["purpose"] == "invalid_program", "invalid program executed")
            exact((query["sql"], query["params"]), ("", {}), "invalid program SQL mismatch")
            require("compiled" not in action, "invalid program has compiled metadata")
            continue
        exact(action.get("executed_program"), program, "executed program mismatch")
        for key, value in _compiled(built).items():
            exact(action.get("compiled", {}).get(key), value, "compiled " + key + " mismatch")
        exact((query["sql"], query["params"]),
              (built.prepared.sql, built.prepared.parameters), "compiled request mismatch")
        exact(query["terminal_requested"], action["answer"], "program terminal request mismatch")
        require(query["purpose"] == ("fragment_use" if kind == "USE" else "fragment_composition"),
                "compiled query purpose mismatch")
        compiled[action_index] = built
    return ordinary, compiled


def _verify_admission(record, selected, scope, after):
    trace = record["trace"]
    admission = trace.get("admission", {})
    status = admission.get("status")
    before_entries = {p["key"]: DelayedEntry.from_dict(p) for p in
                      record["before_snapshot"].get("registry", {}).get("entries", [])}
    after_entries = {entry.key: entry for entry in after.registry.entries}
    added = set(after_entries) - set(before_entries)
    promoted = []
    for key in set(before_entries) & set(after_entries):
        old, new = before_entries[key], after_entries[key]
        for field in ("view", "source", "scope", "template_sha256"):
            require(getattr(old, field) == getattr(new, field), "immutable entry was changed")
        if old.corroboration != new.corroboration:
            require(old.corroboration is None and new.corroboration is not None,
                    "corroboration was overwritten or erased")
            promoted.append(key)
    removed = set(before_entries) - set(after_entries)
    new_events = trace["memory"]["events"][len(record["before_snapshot"]["events"]):]
    for key in removed:
        require(any(event.get("event") == "entry_evicted" and event.get("entry") == key
                    for event in new_events), "entry disappeared without eviction receipt")
    if status not in {"provisional", "corroborated"}:
        require(not added and not promoted, "registry changed without successful admission")
        return None
    require(trace["learn"] and trace["phase"] == "ordinary" and trace["reward"] == 1.0,
            "admission requires ordinary correct feedback")
    require(scope is not None, "admission without current observed compatibility")
    source_index = admission["source_query_index"]
    exact(source_index, trace["answer_query_index"], "admission source is not terminal")
    require(trace["actions"][trace["answer_action_index"]]["action"] == "QUERY",
            "admission requires an independent direct query")
    source = trace["queries"][source_index]
    current = lift_source(source["sql"], source["params"], trace["schema"], trace["question"])
    exact(admission["view"], current.to_dict(), "admission source lift mismatch")
    key = admission["entry"]
    if status == "provisional":
        require(added == {key} and not promoted, "unexpected provisional state changes")
        entry = after_entries[key]
        checked = current
        require(entry.corroboration is None, "source admission was prematurely promoted")
    else:
        require(not added and promoted == [key], "unexpected corroboration state changes")
        entry = after_entries[key]
        checked = before_entries[key].view
        require(key not in {e.key for e in selected} or trace["arm"] == "immediate",
                "provisional candidate was executable during corroboration")
        require(normalized_template(current) == entry.template_sha256, "changed corroboration template")
    exact(asdict(entry.scope), asdict(scope), "admission compatibility mismatch")
    exact(admission["checked_view_key"], checked.key, "changed source reconstruction")
    exact(admission["checked_bindings"], current.params, "reconstruction binding mismatch")
    check_index, empty_index = admission["verification_query_index"], admission["dependence_query_index"]
    require(source_index < check_index < empty_index < len(trace["queries"]),
            "learning checks must follow the direct answer")
    check, empty = trace["queries"][check_index], trace["queries"][empty_index]
    for query, is_empty in ((check, False), (empty, True)):
        require(query["learning_check"] is True, "admission check not charged as learning")
        sql, params = reconstruct_bound(checked, dict(current.params), empty=is_empty)
        exact((query["sql"], query["params"]), (sql, params), "frozen wrapper check mismatch")
    require(check["purpose"] == ("source_reconstruction" if status == "provisional" else "delayed_corroboration")
            and empty["purpose"] == "empty_relation_check", "check purpose mismatch")
    reconstructed, intervention = scalar(check), scalar(empty)
    require(reconstructed["status"] == "numeric" and correct(reconstructed["value"], trace["answer"]),
            "source reconstruction did not match direct answer")
    require(intervention["status"] == "null" or (intervention["status"] == "numeric"
            and not correct(intervention["value"], trace["answer"])), "source relation was noncontributing")
    witness = Witness(trace["episode_nonce"], trace["episode_index"], trace["answer"],
                      digest(source), digest(check), digest(empty), tuple(sorted(current.params.items())))
    exact(admission["witness"], witness.to_dict(), "admission witness receipt mismatch")
    require((entry.source if status == "provisional" else entry.corroboration) == witness,
            "registry witness is not the observed charged evidence")
    return entry


@dataclass(frozen=True)
class _AuditView:
    key: str
    sql: str
    params: dict
    columns: tuple
    measure_columns: tuple


def _interventions(replay, program, views, entry, expected):
    records = []
    view = entry.view

    def run(kind, chosen_views, **kwargs):
        started = time.perf_counter()
        try:
            compiled = compile_program(program, chosen_views, **kwargs)
        except (ProgramError, ValueError, TypeError, KeyError) as exc:
            result = {"status": "compilation_failure", "error": str(exc)[:256],
                      "sql": None, "params": None, "result": None, "answer_wrong": None}
        else:
            output = replay.query(compiled.prepared.sql, compiled.prepared.parameters)
            observed = scalar(output)
            interpretable = observed["status"] in {"numeric", "null"}
            result = {"status": observed["status"], "sql": compiled.prepared.sql,
                      "params": compiled.prepared.parameters, "result": output,
                      "answer_wrong": not correct(observed["value"], expected) if interpretable else None}
        records.append({"kind": kind, "view_key": view.key, "learner_observation": False,
                        "elapsed_seconds": time.perf_counter() - started, **result})

    emptied = _AuditView(view.key, "SELECT * FROM (" + view.sql + ") AS audit_empty WHERE 0",
                         dict(view.params), view.columns, view.measure_columns)
    run("empty_relation", [emptied if selected.key == view.key else selected for selected in views])
    for column in view.measure_columns:
        for replacement in (0, None):
            run("measure_override", views, measure_overrides={view.key: {column: replacement}})
            records[-1].update(column=column, replacement=replacement)
    return records


def audit_records(records):
    """Audit an ordered complete-prefix ledger; return every event and first five.

    Raises AuditError on inconsistent SQL, provenance, selection, or accounting.
    A partial schedule is auditable but this function makes no population claim.
    """
    records = list(records)
    previous, seen_positions, seen_nonces, last_ordinary, provenance = {}, set(), set(), {}, {}
    totals, statuses = Counter(), Counter()
    events, episode_reports = [], []
    for ordinal, record in enumerate(records):
        trace = record["trace"]
        stream = (record["seed"], record["condition"], record["arm"])
        position = (*stream, record["phase"], record["index"])
        require(position not in seen_positions, "duplicate stream/phase/episode record")
        seen_positions.add(position)
        nonce_key = (*stream, trace["episode_nonce"])
        require(nonce_key not in seen_nonces, "reused current-episode nonce")
        seen_nonces.add(nonce_key)
        exact(trace["phase"], record["phase"], "record/trace phase mismatch")
        exact(trace["arm"], record["arm"], "record/trace arm mismatch")
        require(trace["learn"] is (record["phase"] == "ordinary"), "learning/panel flag mismatch")
        if record["phase"] == "ordinary":
            exact(trace["episode_index"], record["index"], "ordinary chronology mismatch")
            exact(record["index"], last_ordinary.get(stream, -1) + 1,
                  "ordinary episode prefix is missing or out of order")
            last_ordinary[stream] = record["index"]
        before = record["before_snapshot"]
        exact(digest(before), trace["before_memory_digest"], "before snapshot hash mismatch")
        exact(digest(trace["memory"]), trace["after_memory_digest"], "after snapshot hash mismatch")
        if stream in previous:
            exact(before, previous[stream], "broken per-stream memory continuity")
        else:
            require(not before.get("registry", {}).get("entries"), "source prefix missing from audited ledger")
        previous[stream] = deepcopy(trace["memory"])
        if not trace["learn"]:
            exact(before, trace["memory"], "frozen panel changed persistent memory")
        spec = _spec(record)
        calls = _usage(trace)
        totals.update(calls)
        statuses[trace["status"]] += 1
        queries = trace["queries"]
        require(type(queries) is list and 1 <= len(queries) <= 8, "query allowance/ledger mismatch")
        exact(trace["select_attempts"], len(queries), "SELECT attempt count mismatch")
        exact((queries[0]["sql"], queries[0]["params"]), (CATALOG_SQL, {}), "missing common catalog query")
        require(queries[0].get("host_issued") is True and queries[0]["purpose"] == "compatibility_catalog",
                "catalog query must be host-issued and charged")
        for index, query in enumerate(queries):
            exact(query["attempt"], index + 1, "noncontiguous SELECT charges")
            for field in ("learning_check", "terminal_requested", "terminal"):
                require(type(query.get(field)) is bool, "query control flag is not Boolean")
            require(index == 0 or not query.get("host_issued"), "undeclared host-issued query")
            require(not query["learning_check"] or trace["learn"], "learning check on frozen panel")
        try:
            scope = CompatibilityScope.from_observation(trace["schema"], queries[0])
        except ValueError:
            scope = None
            require(trace["compatibility"]["status"] == "unavailable", "invalid compatibility acceptance")
        else:
            exact(trace["compatibility"], {"status": "observed", **asdict(scope), "query_index": 0,
                                          "receipt_sha256": digest(queries[0])}, "public scope receipt mismatch")
        delayed_arm = trace["arm"] in {"delayed", "immediate", "view_text"}
        selected = _select(before, trace["question"], scope, trace["episode_index"], trace["arm"]) if delayed_arm else []
        exact(trace.get("selected_entries", []), [entry.to_dict() for entry in selected], "illegal view selection")
        views = [entry.view for entry in selected]
        exact(trace["selected_views"], [view.to_dict() for view in views], "selected source-view mismatch")
        for view in views:
            regenerated = lift_source(view.source_sql, view.source_params, trace["schema"], view.question)
            exact(regenerated.to_dict(), view.to_dict(), "selected view does not derive from its source")
        ordinary, compiled = _audit_actions(trace, views)
        terminal_indices = [i for i, query in enumerate(queries) if query["terminal"]]
        require(len(terminal_indices) <= 1, "multiple terminal queries")
        terminal = terminal_indices[0] if terminal_indices else None
        replay = SQLiteReplayV9(spec)
        try:
            for query in queries:
                actual = replay.query(query["sql"], query["params"])
                exact({field: query[field] for field in RESULT_FIELDS}, actual, "independent SQL replay mismatch")
                totals["recorded_sql_replays"] += 1
            if terminal is None:
                exact(trace["answer"], None, "answer without current terminal query")
                exact(trace["reward"], 0.0, "reward without terminal query")
            else:
                answer = scalar(queries[terminal])
                require(answer["status"] == "numeric", "terminal answer is not a finite scalar")
                exact(trace["answer"], answer["value"], "host answer differs from current query")
                exact(trace["reward"], float(correct(answer["value"], spec._expected)), "answer score mismatch")
                exact(trace["answer_query_index"], terminal, "terminal query pointer mismatch")
                action_index = trace["answer_action_index"]
                require(type(action_index) is int and 0 <= action_index < len(ordinary)
                        and ordinary[action_index][0] == terminal, "terminal action pointer mismatch")
                require(trace["actions"][action_index]["answer"] is True, "unrequested terminal answer")
                require(all(query["learning_check"] for query in queries[terminal + 1:]),
                        "ordinary execution after terminal answer")
            if "feedback" in trace:
                exact(trace["feedback"], {"correct": trace["reward"] == 1.0}, "feedback mismatch")
            if delayed_arm:
                after = DelayedMemory.from_snapshot(trace["memory"])
                entry = _verify_admission(record, selected, scope, after)
                if entry is not None:
                    stage = "source" if trace["admission"]["status"] == "provisional" else "corroboration"
                    provenance.setdefault((*stream, entry.key), {})[stage] = {
                        "record_ordinal": ordinal, "record_index": record["index"],
                        "episode_id": trace["episode_nonce"], "data_sha256": trace["evaluator"]["data_sha256"],
                        "test_double_calls": calls.get("test_double_calls", 0),
                        "unknown_usage_calls": calls.get("unknown_usage_calls", 0)}
            if terminal is not None and trace["reward"] == 1.0 and trace["answer_action_index"] in compiled:
                built = compiled[trace["answer_action_index"]]
                program = trace["actions"][trace["answer_action_index"]]["executed_program"]
                operations = _operations(program)
                for entry in selected:
                    if entry.view.key not in built.used_views:
                        continue
                    previous_events = provenance.get((*stream, entry.key), {})
                    source, corroboration = previous_events.get("source"), previous_events.get("corroboration")
                    chain = bool(source and corroboration and source["record_ordinal"] < corroboration["record_ordinal"] < ordinal)
                    fresh = bool(chain and len({source["data_sha256"], corroboration["data_sha256"],
                                                trace["evaluator"]["data_sha256"]}) == 3)
                    source_operations = _source_operations(entry.view)
                    novel = sorted(set(operations["aggregates"]) - set(source_operations))
                    new_operation = bool(novel or operations["joins"] or operations["groups_with_keys"]
                                         or operations["groups"] > 1)
                    interventions = _interventions(replay, program, views, entry, spec._expected)
                    totals["intervention_sql_calls"] += sum(item["sql"] is not None for item in interventions)
                    lineages = {column: resolve_measure_lineage(entry.view, column, trace["schema"])
                                for column in entry.view.measure_columns}
                    empty_wrong = any(item["kind"] == "empty_relation" and item["answer_wrong"] is True
                                      for item in interventions)
                    computed_wrong = any(item["kind"] == "measure_override" and item["answer_wrong"] is True
                                         and lineages[item["column"]]["computed_from_physical_columns"]
                                         for item in interventions)
                    simulated = calls.get("test_double_calls", 0) + sum(
                        stage.get("test_double_calls", 0) for stage in previous_events.values())
                    unknown = calls.get("unknown_usage_calls", 0) + sum(
                        stage.get("unknown_usage_calls", 0) for stage in previous_events.values())
                    structural = bool(trace["arm"] == "delayed" and chain and fresh and new_operation
                                      and empty_wrong and computed_wrong)
                    event = {"record_ordinal": ordinal, "seed": record["seed"], "condition": record["condition"],
                             "arm": trace["arm"], "phase": trace["phase"], "index": record["index"],
                             "episode_id": trace["episode_nonce"], "entry_key": entry.key,
                             "view_key": entry.view.key, "source": source, "corroboration": corroboration,
                             "complete_chronological_chain": chain, "three_fresh_data_snapshots": fresh,
                             "new_outer_operation": new_operation, "new_aggregate_operations": novel,
                             "program_operations": operations, "source_operations": source_operations,
                             "changed_corroboration_bindings": entry.corroboration is not None,
                             "execution_bindings": [dict(use.bindings) for use in built.source_uses
                                                    if use.view_key == entry.view.key],
                             "lineage": lineages, "interventions": interventions,
                             "empty_relation_flips_to_wrong": empty_wrong,
                             "computed_measure_flips_to_wrong": computed_wrong,
                             "structural_mechanism_event": structural, "test_double_calls": simulated,
                             "unknown_usage_calls": unknown, "qualifying_event": structural and not simulated and not unknown,
                             "agent_deletion_rerun": "not_performed_by_this_offline_auditor"}
                    events.append(event)
        finally:
            replay.close()
        episode_reports.append({"record_ordinal": ordinal, "seed": record["seed"],
                                "condition": record["condition"], "arm": trace["arm"],
                                "phase": trace["phase"], "index": record["index"],
                                "status": trace["status"], "reward": trace["reward"], **calls})
    qualifying = [event for event in events if event["qualifying_event"]]
    return {"kind": "campaign_independent_sql_and_mechanism_audit", "consistent": True,
            "records": len(records), "streams": len(previous), "totals": dict(totals),
            "status_counts": dict(statuses), "events": events,
            "qualifying_event_count": len(qualifying),
            "structural_event_count": sum(event["structural_mechanism_event"] for event in events),
            "first_five": qualifying[:5], "episodes": episode_reports,
            "model_calls_made": 0, "counterfactuals_are_learner_observations": False,
            "runtime_sql_wall_cap_reproduced": False, "replay_emergency_sql_wall_cap_seconds": 2.0,
            "protocol_freeze_and_prompt_replay": "caller_must_verify_separately",
            "population_or_noninferiority_claim": False}


def prepare_deletion_cases(records, audit=None, *, limit=5):
    """Create reviewable agent-rerun inputs, without running a model.

    Remove only the learned registry relation. Its source SQL evidence remains;
    success despite deletion is an informative negative result. Test-double
    cases remain marked and cannot establish an empirical ablation.
    """
    records = list(records)
    require(type(limit) is int and limit >= 0, "nonnegative deletion-case limit required")
    audit = audit_records(records) if audit is None else audit
    cases = []
    for event in audit["events"]:
        if not event["structural_mechanism_event"]:
            continue
        record = records[event["record_ordinal"]]
        memory = DelayedMemory.from_snapshot(record["before_snapshot"])
        before_evidence = deepcopy(memory.evidence)
        memory.registry.entries = [entry for entry in memory.registry.entries if entry.key != event["entry_key"]]
        require(memory.evidence == before_evidence, "deletion changed exact SQL evidence")
        cases.append({"seed": record["seed"], "condition": record["condition"], "arm": record["arm"],
                      "phase": record["phase"], "index": record["index"],
                      "episode_index": record["trace"]["episode_index"],
                      "original_episode_nonce": record["trace"]["episode_nonce"],
                      "sampling_seed": record.get("sampling_seed"),
                      "original_record_ordinal": event["record_ordinal"],
                      "original_before_sha256": digest(record["before_snapshot"]),
                      "before_snapshot": memory.snapshot(), "removed_entry_key": event["entry_key"],
                      "removed_view_key": event["view_key"], "original_answer": record["trace"]["answer"],
                      "source_sql_evidence_preserved": True,
                      "test_double": bool(event["test_double_calls"]), "learn": False})
        if len(cases) == limit:
            break
    return cases if limit else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    records = [json.loads(line) for line in args.records.read_text().splitlines() if line.strip()]
    result = audit_records(records)
    serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.out is not None:
        if args.out.exists():
            raise FileExistsError("audit receipts are immutable")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized)
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
