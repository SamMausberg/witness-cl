#!/usr/bin/env python3
"""Online source-derived computation experiment, with current-execution answers.

Development implementation. A separate frozen protocol is required before any
model study. Ordinary and evaluation episodes share one visible action contract;
only ordinary episodes can mutate learned memory.
"""

from __future__ import annotations

from dataclasses import asdict
from copy import deepcopy
import hashlib
import json
import math
import time

from witness_cl.abstraction_v8 import equal_scalar, scalar_result
from witness_cl.model_v8 import BudgetStop
from witness_cl.query_memory import QueryMemory, VIEW_ARMS, canonical, digest
from witness_cl.relational_program import PROGRAM_GUIDE, ProgramError, compile_program
from witness_cl.source_views import UnsupportedSource, lift_source, reconstruct
from witness_cl.sql_env_v9 import evaluator_metadata, open_episode

MAX_ACTIONS = 6
SOLVE_OUTPUT_TOKENS = 4096
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
                "action": {"const": "PROGRAM"},
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
old numeric answers do not apply. In this study the schema and documented business
conventions are fixed within a stream. The catalog table describes them. Read it
when needed; schema names alone do not reveal meaning. Follow its units, NULL,
current-profile, and row-multiplicity conventions exactly. SQLite integer division
truncates: use REAL arithmetic when fractions are required.

Return exactly one JSON action. QUERY is {"action":"QUERY","sql":"SELECT ...",
"params":{},"answer":false}. It executes a read-only SELECT and returns its result.
Use answer:true when that SELECT returns the single finite numeric answer to the
current question. The host submits the exact current scalar; you cannot submit an
old number or round the result. A constant SELECT is not evidence that it answers
the question. Errors and exploratory queries consume the same SELECT allowance.
You have at most six model actions. An invalid response also consumes an attempt.

The available_actions field declares your tools. When PROGRAM is available, it
executes a structured outer computation over selected learned view IDs in one SQL
statement. QUERY remains available as fallback. Otherwise, view definitions are
SQL text that you may incorporate into your own QUERY; PROGRAM is unavailable.
The program and text views have exactly the same stored SQL and column information.
A view preserves its predicates: do not assume it contains rows that were filtered
out. Derived columns are computations learned from source queries, not certified
meanings for every new question. Prefer a matching stored computation when useful,
but inspect its source and lineage and solve directly when it does not apply.

PROGRAM action: {"action":"PROGRAM","program":{...},"answer":true_or_false}.
"""
    + PROGRAM_GUIDE
)


def parse_action(text):
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
        raise ValueError("bounded JSON action required")
    action = json.loads(text, object_pairs_hook=unique, parse_constant=reject_constant)
    if type(action) is not dict or type(action.get("answer")) is not bool:
        raise ValueError("action object with explicit answer Boolean required")
    if action.get("action") == "QUERY":
        if set(action) != {"action", "sql", "params", "answer"}:
            raise ValueError("unsupported QUERY fields")
        if type(action["sql"]) is not str or type(action["params"]) is not dict:
            raise ValueError("SQL text and named parameters required")
    elif action.get("action") == "PROGRAM":
        if set(action) != {"action", "program", "answer"} or type(action["program"]) is not dict:
            raise ValueError("unsupported PROGRAM fields")
    else:
        raise ValueError("unknown action")

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

    finite_json(action)
    return action


def action_schema(arm):
    return deepcopy(ACTION_SCHEMA if arm == "view_program" else ACTION_SCHEMA["anyOf"][0])


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
):
    if not isinstance(memory, QueryMemory):
        raise ValueError("explicit query memory required")
    if type(learn) is not bool or phase not in {"ordinary", "old_before", "old_after", "final"}:
        raise ValueError("explicit declared phase and learning flag required")
    if learn and phase != "ordinary":
        raise ValueError("evaluation panels cannot learn")
    if type(episode_nonce) is not str or not episode_nonce:
        raise ValueError("opaque current-episode nonce required")
    before = memory.state_digest()
    started = time.monotonic()
    trace = {
        "phase": phase,
        "learn": learn,
        "episode_nonce": episode_nonce,
        "status": "running",
        "answer": None,
        "reward": 0.0,
        "queries": [],
        "model_calls": [],
        "actions": [],
        "before_memory_digest": before,
        "system_prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
    }
    conversation = []
    with open_episode(spec, allow_learning_checks=learn) as session:
        trace.update(question=session.public.question, schema=session.public.schema)
        prefix, selected = memory.prefix(session.public.question, session.public.schema)
        trace["selected_views"] = [view.to_dict() for view in selected]
        conversation.append(
            {
                "role": "user",
                "content": canonical(
                    {
                        "question": session.public.question,
                        "schema": session.public.schema,
                        "snapshot": episode_nonce,
                        "rows_are_fresh": True,
                        "schema_and_documented_conventions_fixed_within_stream": True,
                        "available_actions": ["QUERY", "PROGRAM"]
                        if memory.arm == "view_program"
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

        terminal_source = None
        try:
            for action_index in range(MAX_ACTIONS):
                content = client.complete(
                    [{"role": "system", "content": SYSTEM}] + prefix + conversation,
                    budget,
                    phase=phase + ":solve",
                    records=trace["model_calls"],
                    output_tokens=solve_output_tokens,
                    response_schema=action_schema(memory.arm),
                )
                conversation.append({"role": "assistant", "content": content})
                try:
                    action = parse_action(content)
                except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
                    trace["actions"].append({"invalid": str(exc)[:256]})
                    observe(query("", {}, "invalid_action"), str(exc)[:256])
                    continue
                action_record = deepcopy(action)
                trace["actions"].append(action_record)
                if action["action"] == "PROGRAM":
                    if memory.arm != "view_program":
                        observe(
                            query("", {}, "unavailable_action"),
                            "PROGRAM is unavailable; use QUERY.",
                        )
                        continue
                    try:
                        compiled = compile_program(action["program"], selected)
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
                        "program",
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
            if learn and memory.arm in VIEW_ARMS:
                if trace["reward"] != 1.0 or terminal_source is None:
                    trace["admission"] = {"status": "no_correct_direct_source"}
                else:
                    try:
                        view = lift_source(
                            terminal_source["sql"],
                            terminal_source["params"],
                            session.public.schema,
                            session.public.question,
                        )
                    except UnsupportedSource as exc:
                        trace["admission"] = {"status": "unsupported", "reason": str(exc)}
                    else:
                        admission = {
                            "status": "pending",
                            "view": view.to_dict(),
                            "source_query_index": trace["answer_query_index"],
                        }
                        trace["admission"] = admission
                        try:
                            reconstruction_sql, reconstruction_params = reconstruct(view)
                            check = query(
                                reconstruction_sql,
                                reconstruction_params,
                                "source_reconstruction",
                                learning_check=True,
                            )
                            try:
                                matched = equal_scalar(scalar_result(check), trace["answer"])
                            except (ValueError, TypeError, KeyError):
                                matched = False
                            if not matched:
                                admission["status"] = "reconstruction_rejected"
                            else:
                                empty_sql, empty_params = reconstruct(view, empty=True)
                                empty = query(
                                    empty_sql,
                                    empty_params,
                                    "empty_relation_check",
                                    learning_check=True,
                                )
                                try:
                                    dependent = not equal_scalar(
                                        scalar_result(empty), trace["answer"]
                                    )
                                except (ValueError, TypeError, KeyError):
                                    dependent = False
                                if dependent:
                                    memory.add_view(
                                        session.public.schema,
                                        view,
                                        evidence_digest=digest(
                                            {
                                                "source": terminal_source,
                                                "reconstruction": check,
                                                "empty": empty,
                                                "feedback": trace["feedback"],
                                            }
                                        ),
                                    )
                                    admission["status"] = "admitted"
                                else:
                                    admission["status"] = "dependence_rejected"
                        except (UnsupportedSource, ValueError, TypeError, KeyError) as exc:
                            admission.update(status="compilation_rejected", reason=str(exc)[:256])
            if learn:
                memory.finish(trace, conversation)
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
    after = memory.state_digest()
    if not learn and after != before:
        raise AssertionError("evaluation changed learned memory")
    trace.update(
        after_memory_digest=after,
        memory=memory.snapshot(),
        memory_bytes=len(canonical(memory.snapshot()).encode()),
        elapsed_seconds=time.monotonic() - started,
        evaluator=evaluator_metadata(spec),
        conversation=conversation,
    )
    return trace
