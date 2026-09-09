#!/usr/bin/env python3
"""Current-execution SQL with delayed, independently witnessed promotion.

All arms receive the same charged current catalog. Only ordinary direct correct
answers may update a registry, within the original eight-SELECT allowance.
"""

from __future__ import annotations

from dataclasses import asdict
from copy import deepcopy
import hashlib
import json
import math
import time

from witness_cl.abstraction_v8 import equal_scalar, scalar_result
from witness_cl.ace_memory import extract_json_from_text
from witness_cl.model_v8 import BudgetStop
from witness_cl.query_memory import canonical, digest
from witness_cl.delayed_memory import (
    CompatibilityScope, DelayedMemory, Witness, reconstruct_bound,
)
from witness_cl.relational_program import PROGRAM_GUIDE, ProgramError, compile_program
from witness_cl.source_views import UnsupportedSource, lift_source
from witness_cl.sql_env_v9 import evaluator_metadata, open_episode

MAX_ACTIONS = 5
SOLVE_OUTPUT_TOKENS = 4096
RESPONSE_POLICY = "catalog_reasoning_v2"
SCALAR_SCHEMA = {"anyOf": [{"type": "number"}, {"type": "string"}, {"type": "null"}]}
ACTION_SCHEMA = {
    "anyOf": [
        {
            "type": "object",
            "properties": {
                "action": {"const": "QUERY"},
                "sql": {"type": "string"},
                "params": {"type": "object", "additionalProperties": SCALAR_SCHEMA},
                "answer": {"type": "boolean"},
            },
            "required": ["action", "sql", "params", "answer"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"const": "COMPOSE"},
                "program": {"type": "object"},
                "answer": {"type": "boolean"},
            },
            "required": ["action", "program", "answer"],
            "additionalProperties": False,
        },
    ]
}
SYSTEM = (
    """Solve the current database question using only its schema, your own prior
experience, and current SQL observations. Each episode has fresh transaction rows;
old numeric answers do not apply. The catalog table describes the current schema and documented business
conventions. They may change during the stream. The host has already charged
one SELECT to provide the complete current catalog before your first action; schema names alone do not reveal meaning. Follow its units, NULL,
current-profile, and row-multiplicity conventions exactly. SQLite integer division
truncates: use REAL arithmetic when fractions are required.

Return a JSON object with reasoning and final_answer using the supplied schema.
In reasoning, give a brief plan before issuing SQL: identify the relevant current
catalog conventions for units, NULL values, current profiles and row multiplicity,
and explain how the planned computation follows them. Check only conventions
relevant to this question. On later actions, account for observed query results
or errors. Do not assume that a familiar column name or an earlier episode's
convention applies now. Put exactly one action in final_answer. When the schema
includes ACE bullet_ids, include those citations as required by its playbook.
QUERY is {"action":"QUERY","sql":"SELECT ...",
"params":{},"answer":false}. It executes a read-only SELECT and returns its result.
Use answer:true when that SELECT returns the single finite numeric answer to the
current question. The host submits the exact current scalar; you cannot submit an
old number or round the result. A constant SELECT is not evidence that it answers
the question. Errors and exploratory queries consume the same SELECT allowance.
You have at most five model actions. An invalid response also consumes an attempt.

The available_actions field declares your tools. When COMPOSE is available, it
executes a structured outer computation over selected learned view IDs in one SQL
statement. QUERY remains available as fallback. Otherwise, view definitions are
SQL text that you may incorporate into your own QUERY; COMPOSE is unavailable.
The program and text views have exactly the same stored SQL and column information.
A view preserves its predicates: do not assume it contains rows that were filtered
out. Derived columns are computations learned from source queries, not certified
meanings for every new question. Prefer a matching stored computation when useful,
but inspect its source and lineage and solve directly when it does not apply.

COMPOSE action: {"action":"COMPOSE","program":{...},"answer":true_or_false}.
"""
    + PROGRAM_GUIDE
)


ACTION_SCHEMA["anyOf"].append(deepcopy(ACTION_SCHEMA["anyOf"][1]))
ACTION_SCHEMA["anyOf"][-1]["properties"]["action"] = {"const": "PROGRAM"}
ACTION_SCHEMA["anyOf"].append({
    "type": "object", "properties": {
        "action": {"const": "USE"}, "view": {"type": "string"},
        "params": {"type": "object", "additionalProperties": SCALAR_SCHEMA},
        "answer": {"type": "boolean"}},
    "required": ["action", "view", "params", "answer"], "additionalProperties": False})
SYSTEM += "\nUSE scans a selected relation: {\"action\":\"USE\",\"view\":\"visible key\",\"params\":{},\"answer\":false}. COMPOSE computes over selected views; PROGRAM is an equivalent alias.\n"


def parse_json_response(text):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj

    def reject_constant(value):
        raise ValueError("nonfinite JSON number")

    if type(text) is not str or len(text.encode()) > 32_768:
        raise ValueError("bounded JSON response required")
    payload = json.loads(text, object_pairs_hook=unique, parse_constant=reject_constant)

    def finite_json(value):
        if type(value) is float and not math.isfinite(value):
            raise ValueError("nonfinite JSON scalar")
        if type(value) is str:
            value.encode("utf-8")
        elif type(value) is dict:
            for key, item in value.items():
                finite_json(key)
                finite_json(item)
        elif type(value) is list:
            for item in value:
                finite_json(item)

    finite_json(payload)
    return payload


def parse_response_envelope(text):
    payload = parse_json_response(text)
    if (type(payload) is not dict or set(payload) != {"reasoning", "final_answer"}
            or type(payload["reasoning"]) is not str
            or type(payload["final_answer"]) is not dict):
        raise ValueError("exact reasoning string and final_answer action envelope required")
    return payload


def parse_action(text):
    action = parse_json_response(text)
    if type(action) is not dict or type(action.get("answer")) is not bool:
        raise ValueError("action object with explicit answer Boolean required")
    if action.get("action") == "QUERY":
        if set(action) != {"action", "sql", "params", "answer"}:
            raise ValueError("unsupported QUERY fields")
        if type(action["sql"]) is not str or type(action["params"]) is not dict:
            raise ValueError("SQL text and named parameters required")
    elif action.get("action") in {"COMPOSE", "PROGRAM"}:
        if set(action) != {"action", "program", "answer"} or type(action["program"]) is not dict:
            raise ValueError("unsupported COMPOSE fields")
    elif action.get("action") == "USE":
        if (set(action) != {"action", "view", "params", "answer"}
                or type(action["view"]) is not str or type(action["params"]) is not dict):
            raise ValueError("unsupported USE fields")
    else:
        raise ValueError("unknown action")

    return action


def action_schema(arm):
    return deepcopy(ACTION_SCHEMA if arm in {"delayed", "immediate"} else ACTION_SCHEMA["anyOf"][0])


def solver_schema(arm):
    return {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "final_answer": action_schema(arm)},
        "required": ["reasoning", "final_answer"], "additionalProperties": False,
    }


def _dependent(empty, answer):
    if empty["error"] is not None or empty["truncated"] is not False:
        return False
    rows = empty["rows"]
    if len(rows) == 1 and len(rows[0]) == 1 and rows[0][0] is None:
        return True
    try:
        return not equal_scalar(scalar_result(empty), answer)
    except (ValueError, TypeError, KeyError):
        return False


def _learn_source(trace, memory, scope, terminal_source, query, remaining):
    """One exact-template candidate, checked against a later independent answer.

    No hidden reference SQL, evaluator template name or future schedule is used.
    The original view and wrapper survive corroboration byte-for-byte.
    """
    admission = trace["admission"] = {"status": "no_correct_direct_source"}
    if trace["reward"] != 1.0 or terminal_source is None:
        return
    if scope is None:
        admission["status"] = "current_catalog_unavailable"
        return
    try:
        view = lift_source(terminal_source["sql"], terminal_source["params"],
                           trace["schema"], trace["question"])
        # Enforce the executable compiler's limits at acquisition as well as
        # extraction's limits. No query is needed for this structural check.
        compile_program({"op": "scan", "view": view.key}, [view])
    except (UnsupportedSource, ProgramError, ValueError, TypeError, KeyError) as exc:
        admission.update(status="unsupported", reason=str(exc)[:256])
        return
    admission.update(view=view.to_dict(), source_query_index=trace["answer_query_index"])
    existing = memory.registry.existing(view, scope)
    candidate = memory.registry.matching(view, scope, trace["episode_index"])
    if existing is not None and candidate is None:
        admission.update(status="existing_template_without_new_corroboration",
                         entry=existing.key)
        return
    if candidate is not None and equal_scalar(trace["answer"], candidate.source.answer):
        admission.update(status="unchanged_output", entry=candidate.key)
        return
    if remaining < 2:
        admission["status"] = "insufficient_select_allowance"
        return
    source_view = view if candidate is None else candidate.view
    bindings = dict(view.params)
    purpose = "source_reconstruction" if candidate is None else "delayed_corroboration"
    admission["checked_view_key"] = source_view.key
    admission["checked_bindings"] = bindings
    if candidate is not None:
        admission["entry"] = candidate.key
    try:
        sql, params = reconstruct_bound(source_view, bindings)
        check = query(sql, params, purpose, learning_check=True)
        admission["verification_query_index"] = len(trace["queries"]) - 1
        try:
            matched = equal_scalar(scalar_result(check), trace["answer"])
        except (ValueError, TypeError, KeyError):
            matched = False
        if not matched:
            admission["status"] = "reconstruction_rejected"
            return
        sql, params = reconstruct_bound(source_view, bindings, empty=True)
        empty = query(sql, params, "empty_relation_check", learning_check=True)
        admission["dependence_query_index"] = len(trace["queries"]) - 1
        if not _dependent(empty, trace["answer"]):
            admission["status"] = "dependence_rejected"
            return
        witness = Witness(
            episode_id=trace["episode_nonce"], episode_index=trace["episode_index"],
            answer=trace["answer"], source_sha256=digest(terminal_source),
            reconstruction_sha256=digest(check), dependence_sha256=digest(empty),
            bindings=tuple(sorted(bindings.items())))
        if candidate is None:
            entry = memory.registry.add(view, scope, witness)
            admission["status"] = "provisional"
        else:
            entry = memory.registry.corroborate(candidate.key, view, scope, witness)
            admission["status"] = "corroborated"
        admission.update(entry=entry.key, template_sha256=entry.template_sha256,
                         witness=witness.to_dict())
        memory._bound()
    except (UnsupportedSource, ProgramError, ValueError, TypeError, KeyError) as exc:
        admission.update(status="check_rejected", reason=str(exc)[:256])


def execute_episode(
    spec,
    memory,
    client,
    budget,
    *,
    phase,
    learn,
    episode_nonce,
    solve_output_tokens=SOLVE_OUTPUT_TOKENS,
    episode_index=None,
):
    if (getattr(memory, "arm", None) not in {
            "full_history", "sql_archive", "delayed", "immediate", "view_text", "ace"}
            or any(not callable(getattr(memory, name, None)) for name in
                   ("state_digest", "snapshot", "prefix", "finish"))):
        raise ValueError("explicit campaign memory interface required")
    if type(learn) is not bool or phase not in {"ordinary", "old_before", "old_after", "final"}:
        raise ValueError("explicit declared phase and learning flag required")
    if learn and phase != "ordinary":
        raise ValueError("evaluation panels cannot learn")
    if type(episode_nonce) is not str or not episode_nonce:
        raise ValueError("opaque current-episode nonce required")
    if episode_index is None:
        episode_index = getattr(memory, "ordinary_count", sum(
            event.get("event") in {"episode_observed", "ace_update"} for event in memory.events))
    if type(episode_index) is not int or episode_index < 0:
        raise ValueError("nonnegative ordinary episode index required")
    before = memory.state_digest()
    original_memory = memory
    if not learn:
        memory = deepcopy(memory)
    started = time.monotonic()
    trace = {
        "phase": phase,
        "learn": learn,
        "episode_nonce": episode_nonce,
        "episode_index": episode_index,
        "arm": memory.arm,
        "status": "running",
        "answer": None,
        "reward": 0.0,
        "queries": [],
        "model_calls": [],
        "actions": [],
        "before_memory_digest": before,
        "system_prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
        "response_policy": RESPONSE_POLICY,
    }
    conversation = []
    with open_episode(spec, allow_learning_checks=learn) as session:
        trace.update(question=session.public.question, schema=session.public.schema)
        conversation.append(
            {
                "role": "user",
                "content": canonical(
                    {
                        "question": session.public.question,
                        "schema": session.public.schema,
                        "snapshot": episode_nonce,
                        "rows_are_fresh": True,
                        "current_catalog_is_authoritative": True,
                        "available_actions": ["QUERY", "USE", "COMPOSE", "PROGRAM"]
                        if memory.arm in {"delayed", "immediate"}
                        else ["QUERY"],
                        "remaining_selects": session.public.max_selects,
                    }
                ),
            }
        )

        def query(sql, params, purpose, *, learning_check=False, terminal=False):
            result = session.query(sql, params, learning_check=learning_check)
            record = {
                "sql": sql,
                "params": deepcopy(params),
                "purpose": purpose,
                "learning_check": learning_check,
                "terminal_requested": terminal,
                "terminal": False,
                **asdict(result),
            }
            trace["queries"].append(record)
            return record

        def observe(row, note=None):
            payload = {
                "current_result": {
                    key: row[key] for key in ("columns", "rows", "error", "truncated")
                },
                "remaining_selects": session.public.max_selects - session.select_attempts,
            }
            if note is not None:
                payload["note"] = note
            conversation.append({"role": "user", "content": canonical(payload)})

        catalog = query(
            "SELECT table_name,column_name,description FROM catalog "
            "ORDER BY table_name,column_name,description", {}, "compatibility_catalog")
        catalog["host_issued"] = True
        observe(catalog, "Current catalog, charged equally to every arm.")
        try:
            scope = CompatibilityScope.from_observation(session.public.schema, catalog)
        except ValueError as exc:
            scope = None
            trace["compatibility"] = {"status": "unavailable", "reason": str(exc)}
        else:
            trace["compatibility"] = {"status": "observed", **asdict(scope),
                                      "query_index": 0, "receipt_sha256": digest(catalog)}
        if isinstance(memory, DelayedMemory):
            prefix, selected = memory.prefix_for_episode(
                session.public.question, session.public.schema, scope, episode_index)
            selected_entries = [] if scope is None else memory.registry.selected(
                session.public.question, scope, episode_index, immediate=memory.arm == "immediate")
            trace["selected_entries"] = [entry.to_dict() for entry in selected_entries]
        else:
            prefix, selected = memory.prefix(session.public.question, session.public.schema)
        trace["selected_views"] = [view.to_dict() for view in selected]
        terminal_source = None
        try:
            for action_index in range(MAX_ACTIONS):
                schema = action_schema(memory.arm)
                messages = [{"role": "system", "content": SYSTEM}] + prefix + conversation
                if hasattr(memory, "generator_messages"):
                    messages = [{"role": "system", "content": SYSTEM}] + memory.generator_messages(
                        session.public.question, deepcopy(conversation), schema)
                    schema = memory.generator_schema(schema)
                else:
                    schema = solver_schema(memory.arm)
                content = client.complete(
                    messages,
                    budget,
                    phase=phase + ":solve",
                    records=trace["model_calls"],
                    output_tokens=solve_output_tokens,
                    response_schema=schema,
                )
                conversation.append({"role": "assistant", "content": content})
                rationale = None
                try:
                    if hasattr(memory, "decode_generator"):
                        decoded = memory.decode_generator(content)
                        # Preserve the official ACE decoder and citation handling.
                        # Schema-conforming generation still exposes its rationale
                        # in the same trace field as the other agents.
                        payload = extract_json_from_text(content)
                        rationale = payload.get("reasoning") if isinstance(payload, dict) else None
                    else:
                        payload = parse_response_envelope(content)
                        rationale = payload["reasoning"]
                        decoded = payload["final_answer"]
                    action = parse_action(canonical(decoded))
                except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
                    trace["actions"].append({"invalid": str(exc)[:256], "raw_response": content,
                                             "rationale": rationale})
                    observe(query("", {}, "invalid_action"), str(exc)[:256])
                    continue
                action_record = deepcopy(action)
                action_record.update(raw_response=content, rationale=rationale)
                trace["actions"].append(action_record)
                if action["action"] in {"COMPOSE", "PROGRAM", "USE"}:
                    if memory.arm not in {"delayed", "immediate"}:
                        observe(
                            query("", {}, "unavailable_action"),
                            "COMPOSE is unavailable; use QUERY.",
                        )
                        continue
                    try:
                        program = ({"op": "scan", "view": action["view"], "bindings": action["params"]}
                                   if action["action"] == "USE" else action["program"])
                        compiled = compile_program(program, selected)
                        action_record["executed_program"] = deepcopy(program)
                    except (ProgramError, ValueError, TypeError, KeyError, RecursionError) as exc:
                        observe(query("", {}, "invalid_program"), str(exc)[:256])
                        continue
                    action_record["compiled"] = {
                        "sql": compiled.prepared.sql,
                        "params": compiled.prepared.parameters,
                        "used_views": list(compiled.used_views),
                        "measure_references": list(compiled.measure_references),
                        "source_uses": [asdict(use) for use in compiled.source_uses],
                        "scope": "structural metadata; contribution requires counterfactual execution",
                    }
                    row = query(
                        compiled.prepared.sql,
                        compiled.prepared.parameters,
                        "fragment_use" if action["action"] == "USE" else "fragment_composition",
                        terminal=action["answer"],
                    )
                else:
                    row = query(
                        action["sql"], action["params"], "ordinary", terminal=action["answer"]
                    )
                observe(row)
                if not action["answer"]:
                    continue
                try:
                    value = scalar_result(row)
                except (ValueError, TypeError, KeyError):
                    conversation.append(
                        {
                            "role": "user",
                            "content": "The terminal query must return exactly one finite numeric scalar without truncation or error. Try again.",
                        }
                    )
                    continue
                row["terminal"] = True
                trace["answer"] = value
                trace["reward"] = session.answer(value).reward
                trace["answer_query_index"] = len(trace["queries"]) - 1
                trace["answer_action_index"] = action_index
                trace["status"] = "completed"
                if action["action"] == "QUERY":
                    terminal_source = row
                break
            if not session.answered:
                trace["reward"] = session.answer(None).reward
                trace["status"] = "no_valid_answer"
            trace["feedback"] = {"correct": trace["reward"] == 1.0}
            conversation.append({"role": "user", "content": canonical(trace["feedback"])})
            if learn and isinstance(memory, DelayedMemory):
                _learn_source(trace, memory, scope, terminal_source, query,
                              session.public.max_selects - session.select_attempts)
            if learn:
                memory.finish(trace, conversation)
                if hasattr(memory, "update"):
                    try:
                        memory.update(client, budget, trace["model_calls"],
                                      output_tokens=solve_output_tokens)
                    except Exception as exc:
                        trace["memory_update_failure"] = {
                            "error_type": type(exc).__name__, "error": str(exc)[:256]}
        except BudgetStop as exc:
            trace.update(status="resource_stop", error=str(exc)[:256])
        except Exception as exc:
            trace.update(
                status="runtime_failure", error_type=type(exc).__name__, error=str(exc)[:256]
            )
        finally:
            trace.update(
                select_attempts=session.select_attempts,
                query_seconds=session.query_seconds,
                vm_steps=session.vm_steps,
                setup_seconds=session.setup_seconds,
            )
    after = original_memory.state_digest()
    if not learn and after != before:
        raise AssertionError("evaluation changed learned memory")
    trace.update(
        after_memory_digest=after,
        memory=original_memory.snapshot(),
        memory_bytes=len(canonical(original_memory.snapshot()).encode()),
        elapsed_seconds=time.monotonic() - started,
        evaluator=evaluator_metadata(spec),
        conversation=conversation,
    )
    return trace
