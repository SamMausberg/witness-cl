"""Delayed source-view learning through ordinary native QUERY/ANSWER actions.

All checks precede ANSWER and consume the current native question's query budget.
Only delivered CORRECT feedback commits witnesses. The adapter has no database
handle, path, evaluator answer, or post-terminal SQL channel. Native certification
stays UNKNOWN: agreement at two observed bindings is empirical evidence.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
import math
import re

import sqlglot
from sqlglot import exp
from sqlglot.tokens import TokenType

from witness_cl.abstraction_v8 import equal_scalar
from witness_cl.delayed_memory import CompatibilityScope, DelayedRegistry, Witness, reconstruct_bound
from witness_cl.query_memory import canonical, digest, _view_payload
from witness_cl.relational_program import PROGRAM_GUIDE, compile_program
from witness_cl.source_views import UnsupportedSource, lift_source
from .ace import accounted_call
from .core import ExperienceLedger

NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
NATIVE_ACTION_SCHEMA = {
    "oneOf": [
        {"type": "object", "properties": {"action": {"enum": ["QUERY", "ANSWER"]},
            "content": {"type": "string"}}, "required": ["action", "content"],
            "additionalProperties": False},
        {"type": "object", "properties": {"action": {"enum": ["USE"]},
            "view": {"type": "string"}, "bindings": {"type": "object"}},
            "required": ["action", "view", "bindings"], "additionalProperties": False},
        {"type": "object", "properties": {"action": {"enum": ["COMPOSE"]},
            "program": {"type": "object"}}, "required": ["action", "program"],
            "additionalProperties": False},
    ]
}


def render_bound_sql(sql, parameters):
    """Render finite typed SQLite literals by AST node, never text replacement."""
    roots = sqlglot.parse(sql, read="sqlite")
    if len(roots) != 1 or not isinstance(roots[0], exp.Select):
        raise ValueError("one SELECT required for compiled native SQL")
    seen = set()
    def substitute(node):
        if not isinstance(node, exp.Placeholder):
            return node
        if node.name not in parameters:
            raise ValueError("missing native SQL binding")
        seen.add(node.name)
        value = parameters[node.name]
        if type(value) not in (str, int, float, type(None)):
            raise ValueError("finite typed SQLite scalar binding required")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("finite SQLite real required")
        if type(value) is int and not -(2**63) <= value < 2**63:
            raise ValueError("SQLite integer out of range")
        if type(value) is str and ("\x00" in value or len(value.encode()) > 4096):
            raise ValueError("bounded SQLite text without NUL required")
        return exp.convert(value)
    rendered = roots[0].transform(substitute).sql(dialect="sqlite")
    if seen != parameters.keys():
        raise ValueError("unused compiled native binding")
    if len(rendered.encode()) > 16384:
        raise ValueError("native compiled SQL byte ceiling exceeded")
    return rendered


def query_result_text(observation):
    if not observation.startswith("Query result (") or ":\n\n" not in observation:
        raise ValueError("native QUERY observation required")
    return observation.split(":\n\n", 1)[1]


def numeric_scalar(observation, *, allow_null=False):
    """Reject truncated/ambiguous display tables; accept only one numeric cell."""
    result = query_result_text(observation)
    lines = result.splitlines()
    if len(lines) != 3 or " | " in lines[0] or not re.fullmatch(r"-+", lines[1]):
        raise ValueError("complete one-column one-row numeric native result required")
    raw = lines[2].strip()
    if raw == "NULL" and allow_null:
        return None
    if not NUMBER.fullmatch(raw):
        raise ValueError("native result is not a finite numeric scalar")
    value = float(raw) if any(c in raw for c in ".eE") else int(raw)
    if not math.isfinite(value):
        raise ValueError("native result is nonfinite")
    return value


def terminal_correct(content):
    # Exact line anchor avoids matching INCORRECT or text inside the answer.
    return bool(re.match(r"\AQuestion \d+: CORRECT!\n", content))


def observed_schema_tables(ddl):
    """Parse native .schema's semicolon-free CREATE concatenation safely.

Token boundaries avoid splitting CREATE text inside a quoted string or nested
expression. SQLite's internal bookkeeping tables are not a source-view schema;
their original DDL remains visible in the ordinary observation.
"""
    if type(ddl) is not str or len(ddl.encode()) > 65536:
        raise ValueError("bounded delivered native DDL required")
    depth, starts = 0, []
    for token in sqlglot.tokenize(ddl, read="sqlite"):
        if token.token_type == TokenType.CREATE and depth == 0:
            starts.append(token.start)
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced delivered schema")
    if depth or not starts:
        raise ValueError("complete delivered CREATE TABLE schema required")
    tables = {}
    for start, end in zip(starts, starts[1:] + [len(ddl)]):
        tree = sqlglot.parse_one(ddl[start:end], read="sqlite")
        if (not isinstance(tree, exp.Create) or str(tree.args.get("kind")).upper() != "TABLE"
                or not isinstance(tree.this, exp.Schema) or not isinstance(tree.this.this, exp.Table)):
            raise ValueError("native schema must contain CREATE TABLE DDL")
        name = tree.this.this.name.lower()
        if not name.startswith("sqlite_"):
            if name in tables:
                raise ValueError("duplicate observed schema table")
            tables[name] = tree.sql(dialect="sqlite")
    return tables


def make_witness(api, *, transport, model, name="witness_delayed_native"):
    class NativeWitness(api.interface.ContinualLearningSystem):
        supports_baseline = True
        parallel_safe = False

        def __init__(self):
            self.model, self._name = model, name
            self.registry = DelayedRegistry()
            self.experience = ExperienceLedger()
            self.schema_tables = {}
            self.epoch = 0
            self.epoch_notice = "initial native database"
            self.episode = 0
            self.conversation = []
            self.evidence = []
            self.events = []
            self.last_direct = None
            self.pending = None
            self.last_kind = None
            self.last_query_sql = None
            self.selected_entries = []

        @property
        def name(self):
            return self._name

        def schema(self):
            return ";\n".join(self.schema_tables[key] for key in sorted(self.schema_tables))

        def scope(self):
            # Native has no custom fixture catalog. Scope uses only actually
            # observed DDL and the public migration notice, not task metadata.
            return CompatibilityScope(digest(self.schema()), digest({
                "domain": "native_database_exploration", "epoch": self.epoch,
                "public_notice": self.epoch_notice,
            }))

        def _bound_memory(self):
            def size():
                return len(canonical({"schema": self.schema(), "evidence": self.evidence,
                    "entries": [entry.to_dict() for entry in self.registry.entries]}).encode())
            while len(self.registry.entries) > 16:
                removed = self.registry.entries.pop(0)
                self.events.append({"event": "native_relation_evicted", "entry": removed.key})
            while size() > 65536:
                if self.evidence:
                    removed = self.evidence.pop(0)
                    self.events.append({"event": "native_evidence_evicted", "receipt": digest(removed)})
                elif self.registry.entries:
                    removed = self.registry.entries.pop(0)
                    self.events.append({"event": "native_relation_evicted", "entry": removed.key})
                else:
                    raise ValueError("observed native schema exceeds active memory ceiling")

        def _emit(self, query, payload, kind):
            action = query.response_schema.model_validate(payload)
            self.last_kind = kind
            self.last_query_sql = payload["content"] if payload["action"] == "QUERY" else None
            self.conversation.append({"role": "assistant", "content": action.model_dump_json()})
            self.experience.begin(prompt=query.prompt, action_json=action.model_dump_json(),
                response_schema=query.response_schema.model_json_schema(), instance_id=query.instance_id)
            return api.interface.Response(action, metadata={
                "system_type": self.name, "native_certificate": "UNKNOWN",
                "witness_action_kind": kind, "witness_episode_index": self.episode,
            })

        def _pending_response(self, query):
            pending = self.pending
            if pending["next_check"] < len(pending["checks"]):
                index = pending["next_check"]
                pending["next_check"] += 1
                return self._emit(query, {"action": "QUERY", "content": pending["checks"][index]},
                                  "reconstruction" if index == 0 else "empty_relation")
            return self._emit(query, pending["answer_action"], "answer_after_checks")

        def _stage(self, query, answer_action):
            if self.last_direct is None or not self.schema():
                return False
            try:
                raw_answer = answer_action["content"].strip()
                if not NUMBER.fullmatch(raw_answer):
                    return False
                answer = float(raw_answer) if any(c in raw_answer for c in ".eE") else int(raw_answer)
                source_answer = numeric_scalar(self.last_direct["observation"])
                if not equal_scalar(answer, source_answer):
                    return False
                match = re.search(r"Queries used so far this question: (\d+)/(\d+)", query.prompt)
                if match is None or int(match[2]) - int(match[1]) < 2:
                    return False
                view = lift_source(self.last_direct["sql"], {}, self.schema(), query.prompt)
                scope = self.scope()
                existing = self.registry.existing(view, scope)
                candidate = self.registry.matching(view, scope, self.episode)
                if existing is not None and candidate is None:
                    return False
                checked_view = candidate.view if candidate is not None else view
                checks = [render_bound_sql(*reconstruct_bound(checked_view, dict(view.params), empty=empty))
                          for empty in (False, True)]
            except (ValueError, TypeError, KeyError, UnsupportedSource, sqlglot.errors.SqlglotError) as exc:
                self.events.append({"event": "native_admission_skipped", "reason": str(exc),
                                    "episode_index": self.episode})
                return False
            self.pending = {
                "view": view, "scope": scope, "candidate": candidate,
                "source": deepcopy(self.last_direct), "answer": answer,
                "answer_action": deepcopy(answer_action), "checks": checks,
                "next_check": 0, "results": {}, "episode_id": query.instance_id,
            }
            return True

        def respond(self, query):
            if self.experience.pending:
                raise RuntimeError("native feedback must precede next respond")
            self.conversation.append({"role": "user", "content": query.prompt})
            notice = "NOTICE: The live database schema or contents may have changed"
            if notice in query.prompt:
                self.epoch += 1
                self.epoch_notice = query.prompt.split("\n\n", 1)[0]
                self.schema_tables.clear()
                self.events.append({"event": "public_migration_notice", "epoch": self.epoch,
                                    "episode_index": self.episode})
            if self.pending is not None:
                return self._pending_response(query)
            self.selected_entries = self.registry.selected(query.prompt, self.scope(), self.episode)
            views = [entry.view for entry in self.selected_entries]
            instructions = (
                "Solve the native database question. Use QUERY with SQL and ANSWER with the exact "
                "value. Observe schema through ordinary .schema queries before assuming table meanings. "
                "You may USE a visible view with its exact typed bindings to execute its original "
                "aggregate, or COMPOSE a program over visible views. These execute ordinary charged "
                "queries; inspect their result before ANSWER. Relations may fail under changed data.\n"
                + PROGRAM_GUIDE + "\nVisible corroborated relations:\n"
                + canonical([_view_payload(view) for view in views])
            )
            raw = accounted_call(api, self, transport,
                messages=[{"role": "system", "content": instructions},
                    {"role": "user", "content": "Previously observed schema and exact evidence:\n"
                     + canonical({"schema": self.schema(), "evidence": self.evidence})}]
                    + deepcopy(self.conversation),
                schema=NATIVE_ACTION_SCHEMA, phase="native:witness:solve")
            kind = "ordinary"
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("native witness action must be an object")
                if payload.get("action") == "USE":
                    if set(payload) != {"action", "view", "bindings"}:
                        raise ValueError("USE fields mismatch")
                    view = next((v for v in views if v.key == payload["view"]), None)
                    if view is None:
                        raise ValueError("USE selected no eligible view")
                    compiled = render_bound_sql(*reconstruct_bound(view, payload["bindings"]))
                    self.events.append({"event": "native_use", "episode_index": self.episode,
                                        "action": deepcopy(payload), "sql": compiled})
                    payload, kind = {"action": "QUERY", "content": compiled}, "use"
                elif payload.get("action") == "COMPOSE":
                    if set(payload) != {"action", "program"}:
                        raise ValueError("COMPOSE fields mismatch")
                    program = compile_program(payload["program"], views)
                    compiled = render_bound_sql(program.prepared.sql, program.prepared.parameters)
                    self.events.append({"event": "native_compose", "episode_index": self.episode,
                        "action": deepcopy(payload), "sql": compiled,
                        "source_uses": [asdict(use) for use in program.source_uses]})
                    payload, kind = {"action": "QUERY", "content": compiled}, "compose"
                elif (set(payload) != {"action", "content"} or payload["action"] not in {"QUERY", "ANSWER"}
                      or not isinstance(payload["content"], str)):
                    raise ValueError("native QUERY/ANSWER fields mismatch")
                if payload["action"] == "ANSWER" and self._stage(query, payload):
                    return self._pending_response(query)
            except (ValueError, TypeError, KeyError, sqlglot.errors.SqlglotError) as exc:
                self.events.append({"event": "invalid_native_action", "error": str(exc),
                                    "episode_index": self.episode, "response": raw})
                self.conversation.append({"role": "user", "content": "Invalid action: " + str(exc)})
                payload, kind = {"action": "QUERY", "content": ""}, "invalid"
            return self._emit(query, payload, kind)

        def observe(self, observation, next_query=None):
            terminal = api.interface.observation_marks_instance_complete(observation)
            record = self.experience.observe(content=observation.content, instance_complete=terminal)
            self.conversation.append({"role": "user", "content": observation.content})
            if not terminal:
                if self.last_kind == "ordinary" and self.last_query_sql is not None:
                    self.last_direct = {"sql": self.last_query_sql, "observation": observation.content,
                                        "turn": record.turn}
                    if self.last_query_sql.strip().lower().startswith(".schema"):
                        try:
                            ddl = query_result_text(observation.content)
                            self.schema_tables.update(observed_schema_tables(ddl))
                        except (ValueError, sqlglot.errors.SqlglotError):
                            pass
                    else:
                        self.evidence.append(deepcopy(self.last_direct))
                    self._bound_memory()
                elif self.pending is not None and self.last_kind in {"reconstruction", "empty_relation"}:
                    self.pending["results"][self.last_kind] = {
                        "sql": self.last_query_sql, "observation": observation.content, "turn": record.turn}
                return
            if self.pending is not None:
                pending = self.pending
                try:
                    results = pending["results"]
                    reconstruction = numeric_scalar(results["reconstruction"]["observation"])
                    empty = numeric_scalar(results["empty_relation"]["observation"], allow_null=True)
                    if not terminal_correct(observation.content):
                        raise ValueError("terminal correctness did not pass")
                    if not equal_scalar(reconstruction, pending["answer"]):
                        raise ValueError("reconstruction mismatch")
                    if empty is not None and equal_scalar(empty, pending["answer"]):
                        raise ValueError("empty relation did not change the answer")
                    view = pending["view"]
                    witness = Witness(str(pending["episode_id"]), self.episode, pending["answer"],
                        digest(pending["source"]), digest(results["reconstruction"]),
                        digest(results["empty_relation"]), tuple(sorted(view.params.items())))
                    if pending["candidate"] is None:
                        entry = self.registry.add(view, pending["scope"], witness)
                    else:
                        entry = self.registry.corroborate(pending["candidate"].key, view,
                                                         pending["scope"], witness)
                    self.events.append({"event": "native_witness_committed", "entry": entry.key,
                                        "state": entry.state, "episode_index": self.episode})
                except (ValueError, TypeError, KeyError) as exc:
                    self.events.append({"event": "native_witness_rejected", "reason": str(exc),
                                        "episode_index": self.episode})
            self.pending = None
            self.evidence.append({"episode_index": self.episode, "feedback": observation.content})
            self._bound_memory()
            self.last_direct = None
            self.conversation = []
            self.episode += 1

        def reset(self):
            self.registry = DelayedRegistry()
            self.experience.reset()
            self.schema_tables.clear()
            self.epoch = self.episode = 0
            self.epoch_notice = "initial native database"
            self.conversation = []
            self.evidence = []
            self.events = []
            self.last_direct = self.pending = None
            self.last_kind = self.last_query_sql = None
            self.selected_entries = []
            transport.reset()

        def get_run_artifacts(self):
            return {"artifact_type": "native_delayed_witness", "registry": self.registry.snapshot(),
                "experience": self.experience.to_jsonable(), "events": deepcopy(self.events),
                "native_certificate": "UNKNOWN", "source_coverage": "supported scalar aggregate SQL",
                "public_schema": self.schema(), "epoch": self.epoch,
                "exact_evidence": deepcopy(self.evidence),
                "all_checks_are_native_pre_answer_queries": True}

    return NativeWitness()
