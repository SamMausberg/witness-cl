"""Own-experience controls for the source-derived computation experiment.

Numeric observations remain in the complete trace archive. Compact controls
retain SQL and feedback, plus exact text-only observations such as documentation.
The view-text and view-program arms share exactly the same memory payload.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

import sqlglot
from sqlglot import exp

ARMS = ("full_history", "sql_archive", "view_text", "view_program")
VIEW_ARMS = frozenset(("view_text", "view_program"))
MAX_ACTIVE_BYTES = 65_536
MAX_VIEWS = 16
MAX_RETRIEVED = 4


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _words(text: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z][a-z0-9_]*", text.lower()))


def _documentation_projection(query: dict) -> bool:
    """Retain only direct catalog columns, not numeric results cast to TEXT."""
    try:
        tree = sqlglot.parse_one(query["sql"], read="sqlite")
        if not isinstance(tree, exp.Select) or tree.args.get("with_") or tree.args.get("joins"):
            return False
        source = tree.args.get("from_")
        if source is None or not isinstance(source.this, exp.Table):
            return False
        table = source.this
        if table.name.casefold() != "catalog" or table.db or table.catalog:
            return False
        allowed = {"table_name", "column_name", "description"}
        for expression in tree.expressions:
            if isinstance(expression, exp.Star):
                continue
            if not isinstance(expression, exp.Column):
                return False
            if not isinstance(expression.this, exp.Star) and expression.name not in allowed:
                return False
            if expression.table and expression.table != table.alias_or_name:
                return False
        return bool(tree.expressions)
    except (ValueError, TypeError, sqlglot.errors.SqlglotError):
        return False


def _view_payload(view: Any) -> dict:
    return {
        "view": view.key,
        "source_question": view.question,
        "sql": view.sql,
        "bindings": deepcopy(view.params),
        "columns": list(view.columns),
        "derived_measure_columns": list(view.measure_columns),
        "column_lineage": deepcopy(view.lineage),
        "column_origins": deepcopy(view.column_origins),
    }


class QueryMemory:
    def __init__(self, arm: str):
        if arm not in ARMS:
            raise ValueError("unknown query-memory arm")
        self.arm = arm
        self.history: list[list[dict]] = []
        self.evidence: list[dict] = []
        self.views: list[tuple[str, Any]] = []
        self.events: list[dict] = []

    def active_payload(self) -> dict:
        if self.arm == "full_history":
            return {"history": self.history}
        return {
            "evidence": self.evidence,
            "views": [
                {"schema_sha256": schema, **_view_payload(view)} for schema, view in self.views
            ],
        }

    def active_bytes(self) -> int:
        return len(canonical(self.active_payload()).encode())

    def snapshot(self) -> dict:
        return {
            "arm": self.arm,
            "active": deepcopy(self.active_payload()),
            "events": deepcopy(self.events),
            "active_bytes": self.active_bytes(),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict):
        """Restore exact persisted state; callers select specialized subclasses."""
        memory = cls(snapshot["arm"])
        active = snapshot["active"]
        if memory.arm == "full_history":
            memory.history = deepcopy(active["history"])
        else:
            memory.evidence = deepcopy(active["evidence"])
            # Base compact snapshots historically store only a retrieval
            # projection of views. They cannot restore executable provenance.
            if active["views"]:
                raise ValueError("base view snapshots lack full source provenance; use DelayedMemory")
            memory.views = []
        memory.events = deepcopy(snapshot["events"])
        if memory.active_bytes() != snapshot["active_bytes"]:
            raise ValueError("restored active-state byte count mismatch")
        return memory

    def state_digest(self) -> str:
        return digest(self.snapshot())

    def selected(self, question: str, schema: str) -> list[Any]:
        if self.arm not in VIEW_ARMS:
            return []
        schema_hash = digest(schema)
        eligible = [view for saved_schema, view in self.views if saved_schema == schema_hash]
        words = _words(question)
        ranked = sorted(
            enumerate(eligible),
            key=lambda pair: (len(words & _words(pair[1].question)), pair[0]),
            reverse=True,
        )
        return [view for _, view in ranked[:MAX_RETRIEVED]]

    def prefix(self, question: str, schema: str) -> tuple[list[dict], list[Any]]:
        if self.arm == "full_history":
            return deepcopy([message for episode in self.history for message in episode]), []
        selected = self.selected(question, schema)
        payload = {"prior_sql_and_feedback": deepcopy(self.evidence)}
        if self.arm in VIEW_ARMS:
            # The payload is deliberately identical for text and program arms.
            payload["source_derived_views"] = [_view_payload(view) for view in selected]
        if not self.evidence and not selected:
            return [], selected
        return [
            {
                "role": "user",
                "content": "Prior own experience. Numeric output rows are omitted from this compact "
                "memory; statements and feedback retain their original scope. Views preserve their "
                "stored predicates and can still be wrong for a new question.\n"
                + canonical(payload),
            }
        ], selected

    def _bound(self) -> None:
        if self.arm == "full_history":
            return
        while len(self.views) > MAX_VIEWS:
            _, view = self.views.pop(0)
            self.events.append({"event": "view_evicted", "key": view.key, "reason": "count"})
        while self.active_bytes() > MAX_ACTIVE_BYTES:
            if self.evidence:
                removed = self.evidence.pop(0)
                self.events.append({"event": "evidence_evicted", "record_sha256": digest(removed)})
            elif self.views:
                _, view = self.views.pop(0)
                self.events.append({"event": "view_evicted", "key": view.key, "reason": "bytes"})
            else:
                raise ValueError("empty memory exceeds its byte bound")

    def add_view(self, schema: str, view: Any, *, evidence_digest: str) -> None:
        if self.arm not in VIEW_ARMS:
            raise ValueError("this control cannot admit executable views")
        # The caller must verify reconstruction against the actual charged source
        # episode before admission; no field supplied by a model can approve it.
        schema_hash = digest(schema)
        self.views = [pair for pair in self.views if pair[1].key != view.key]
        self.views.append((schema_hash, view))
        self.events.append(
            {"event": "view_admitted", "key": view.key, "evidence_sha256": evidence_digest}
        )
        self._bound()

    def finish(self, trace: dict, conversation: list[dict]) -> None:
        if not trace.get("learn") or trace.get("phase") != "ordinary":
            raise ValueError("only ordinary learning episodes can update memory")
        correct = trace.get("feedback", {}).get("correct")
        if type(correct) is not bool:
            raise ValueError("exact Boolean task feedback required")
        if self.arm == "full_history":
            self.history.append(deepcopy(conversation))
        else:
            for query in trace["queries"]:
                if query.get("learning_check"):
                    continue
                record = {
                    "kind": "query",
                    "question": trace["question"],
                    "sql": query["sql"],
                    "params": deepcopy(query["params"]),
                    "columns": deepcopy(query["columns"]),
                    "error": query["error"],
                    "terminal": query.get("terminal", False),
                    "terminal_answer_correct": correct if query.get("terminal") else None,
                }
                if (
                    query["error"] is None
                    and query["truncated"] is False
                    and query["rows"]
                    and _documentation_projection(query)
                    and all(type(cell) is str for row in query["rows"] for cell in row)
                ):
                    record["text_rows"] = deepcopy(query["rows"])
                self.evidence = [
                    old for old in self.evidence if canonical(old) != canonical(record)
                ]
                self.evidence.append(record)
            self._bound()
        self.events.append({"event": "episode_observed", "trace_sha256": digest(trace)})
