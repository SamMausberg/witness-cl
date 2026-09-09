"""Delayed, receipt-backed source-view promotion without evaluator routing.

The registry never executes SQL or decides whether an answer is correct. A host
commits witnesses only after current direct-query feedback and charged checks.
Its state machine independently enforces time, scope, bindings and immutability.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import math
import re

from .abstraction_v8 import equal_scalar
from .query_memory import (
    MAX_ACTIVE_BYTES, MAX_RETRIEVED, MAX_VIEWS, QueryMemory, _view_payload,
    _words, canonical, digest,
)
from .source_views import SourceView, reconstruct

_HASH = re.compile(r"[0-9a-f]{64}\Z")
ARMS = ("delayed", "immediate", "view_text")


def _hash(value):
    if type(value) is not str or not _HASH.fullmatch(value):
        raise ValueError("a SHA-256 receipt is required")


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _typed(bindings):
    return {key: type(value).__name__ for key, value in sorted(bindings.items())}


@dataclass(frozen=True)
class CompatibilityScope:
    schema_sha256: str
    catalog_sha256: str

    def __post_init__(self):
        _hash(self.schema_sha256)
        _hash(self.catalog_sha256)

    @classmethod
    def from_observation(cls, schema: str, catalog_result: dict):
        if type(schema) is not str or not schema:
            raise ValueError("public schema text required")
        if (catalog_result.get("error") is not None
                or catalog_result.get("truncated") is not False
                or list(catalog_result.get("columns", [])) != [
                    "table_name", "column_name", "description"]):
            raise ValueError("complete directly observed catalog columns required")
        rows = catalog_result.get("rows")
        if (not isinstance(rows, (list, tuple)) or not rows
                or any(not isinstance(row, (list, tuple)) or len(row) != 3
                       or any(type(cell) is not str for cell in row) for row in rows)):
            raise ValueError("nonempty text-only catalog rows required")
        # Ordering is canonical but duplicates are preserved. No evaluator ID
        # or hidden convention stamp participates in this compatibility key.
        return cls(digest(schema), digest(sorted([list(row) for row in rows])))


def normalized_template(view: SourceView) -> str:
    """Identify unchanged lifted code/wrapper, allowing only typed row bindings.

    Outer-only parameters remain fixed values. Questions, source spelling and
    concrete row bindings are provenance, not permission to change the program.
    This intentionally abstains on semantically equivalent but differently
    structured SQL; it is not a semantic equivalence checker.
    """
    if not isinstance(view, SourceView):
        raise ValueError("immutable SourceView required")
    return digest({
        "sql": view.sql,
        "binding_types": _typed(view.params),
        "columns": view.columns,
        "lineage": view.lineage,
        "column_origins": view.column_origins,
        "measure_columns": view.measure_columns,
        "reconstruction_sql": view.reconstruction_sql,
        "outer_bindings": {key: value for key, value in view.reconstruction_params.items()
                           if key not in view.params},
    })


def reconstruct_bound(view: SourceView, bindings: dict, *, empty=False):
    """Execute the original immutable wrapper with only its typed row holes changed."""
    if type(bindings) is not dict or _typed(bindings) != _typed(view.params):
        raise ValueError("binding names and exact types must match the source")
    # SourceView validates scalar ranges, Unicode and named-hole bounds.
    for value in bindings.values():
        if type(value) is float and not math.isfinite(value):
            raise ValueError("finite bindings required")
        if type(value) is int and not -(2**63) <= value < 2**63:
            raise ValueError("SQLite signed-int64 bindings required")
        if type(value) is str and ("\x00" in value or len(value.encode("utf-8")) > 4096):
            raise ValueError("bounded UTF-8 binding text required")
    sql, params = reconstruct(view, empty=empty)
    params.update(bindings)
    return sql, params


@dataclass(frozen=True)
class Witness:
    episode_id: str
    episode_index: int
    answer: int | float
    source_sha256: str
    reconstruction_sha256: str
    dependence_sha256: str
    bindings: tuple[tuple[str, object], ...]

    def __post_init__(self):
        if (type(self.episode_id) is not str or not self.episode_id
                or type(self.episode_index) is not int or self.episode_index < 0
                or not _finite(self.answer)):
            raise ValueError("an identified episode with a finite scalar witness is required")
        for name in ("source_sha256", "reconstruction_sha256", "dependence_sha256"):
            _hash(getattr(self, name))
        if (type(self.bindings) is not tuple
                or any(type(pair) is not tuple or len(pair) != 2 for pair in self.bindings)
                or self.bindings != tuple(sorted(dict(self.bindings).items()))):
            raise ValueError("immutable sorted unique binding pairs required")
        for key, value in self.bindings:
            if (type(key) is not str or type(value) not in (str, int, float, type(None))
                    or (type(value) in (int, float) and not _finite(value))):
                raise ValueError("exact finite scalar witness bindings required")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, payload):
        fields = dict(payload)
        fields["bindings"] = tuple(tuple(pair) for pair in fields["bindings"])
        return cls(**fields)


@dataclass(frozen=True)
class DelayedEntry:
    key: str
    template_sha256: str
    view: SourceView
    scope: CompatibilityScope
    source: Witness
    corroboration: Witness | None = None

    def __post_init__(self):
        if self.template_sha256 != normalized_template(self.view):
            raise ValueError("template identity mismatch")
        if canonical(dict(self.source.bindings)) != canonical(self.view.params):
            raise ValueError("source witness bindings mismatch")
        expected = digest({"view": self.view.key, "scope": asdict(self.scope),
                           "source": self.source.to_dict()})
        if self.key != expected:
            raise ValueError("entry identity mismatch")
        if self.corroboration is not None:
            later = self.corroboration
            if (later.episode_index <= self.source.episode_index
                    or later.episode_id == self.source.episode_id
                    or _typed(dict(later.bindings)) != _typed(self.view.params)
                    or canonical(dict(later.bindings)) == canonical(self.view.params)
                    or equal_scalar(later.answer, self.source.answer)):
                raise ValueError("corroboration requires later changed binding and output")

    @property
    def state(self):
        return "corroborated" if self.corroboration is not None else "provisional"

    def to_dict(self):
        return {"key": self.key, "template_sha256": self.template_sha256,
                "view": self.view.to_dict(), "scope": asdict(self.scope),
                "source": self.source.to_dict(),
                "corroboration": None if self.corroboration is None else self.corroboration.to_dict()}

    @classmethod
    def from_dict(cls, payload):
        p = dict(payload)
        p["view"] = SourceView.from_dict(p["view"])
        p["scope"] = CompatibilityScope(**p["scope"])
        p["source"] = Witness.from_dict(p["source"])
        if p["corroboration"] is not None:
            p["corroboration"] = Witness.from_dict(p["corroboration"])
        return cls(**p)


class DelayedRegistry:
    def __init__(self):
        self.entries: list[DelayedEntry] = []
        self.events: list[dict] = []

    def existing(self, view, scope):
        template = normalized_template(view)
        return next((entry for entry in self.entries
                     if entry.scope == scope and entry.template_sha256 == template), None)

    def matching(self, view, scope, episode_index):
        entry = self.existing(view, scope)
        if (entry is None or entry.corroboration is not None
                or episode_index <= entry.source.episode_index
                or canonical(view.params) == canonical(entry.view.params)):
            return None
        return entry

    def add(self, view: SourceView, scope: CompatibilityScope, witness: Witness):
        if self.existing(view, scope) is not None:
            raise ValueError("an unchanged template already has a source witness")
        key = digest({"view": view.key, "scope": asdict(scope), "source": witness.to_dict()})
        entry = DelayedEntry(key, normalized_template(view), view, scope, witness)
        self.entries.append(entry)
        self.events.append({"event": "provisional_admission", "entry": key,
                            "episode_id": witness.episode_id, "episode_index": witness.episode_index})
        return entry

    def corroborate(self, key, current_view, scope, witness: Witness):
        entry = next((entry for entry in self.entries if entry.key == key), None)
        if (entry is None or entry.corroboration is not None or entry.scope != scope
                or entry.template_sha256 != normalized_template(current_view)
                or canonical(dict(witness.bindings)) != canonical(current_view.params)):
            raise ValueError("current direct source must match the unchanged provisional template")
        promoted = replace(entry, corroboration=witness)
        self.entries[self.entries.index(entry)] = promoted
        self.events.append({"event": "corroborated", "entry": key,
                            "episode_id": witness.episode_id, "episode_index": witness.episode_index,
                            "effective_after_episode_index": witness.episode_index})
        return promoted

    def selected(self, question, scope, episode_index, *, immediate=False):
        eligible = [entry for entry in self.entries if entry.scope == scope
                    and entry.source.episode_index < episode_index
                    and (immediate or (entry.corroboration is not None
                                      and entry.corroboration.episode_index < episode_index))]
        words = _words(question)
        ranked = sorted(enumerate(eligible),
                        key=lambda pair: (len(words & _words(pair[1].view.question)), pair[0]),
                        reverse=True)
        return [entry for _, entry in ranked[:MAX_RETRIEVED]]

    def snapshot(self):
        return {"entries": [entry.to_dict() for entry in self.entries],
                "events": deepcopy(self.events)}

    @classmethod
    def from_snapshot(cls, snapshot):
        registry = cls()
        registry.entries = [DelayedEntry.from_dict(p) for p in snapshot["entries"]]
        if len({entry.key for entry in registry.entries}) != len(registry.entries):
            raise ValueError("duplicate restored entries")
        identities = [(entry.template_sha256, entry.scope) for entry in registry.entries]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate restored scoped templates")
        registry.events = deepcopy(snapshot["events"])
        return registry


class DelayedMemory(QueryMemory):
    """Exact SQL evidence plus a delayed registry; view_text shares its lifecycle."""
    def __init__(self, arm="delayed"):
        if arm not in ARMS:
            raise ValueError("unknown delayed-memory arm")
        super().__init__("sql_archive")
        self.arm = arm
        self.registry = DelayedRegistry()
        self.ordinary_count = 0

    def active_payload(self):
        # Reserve the largest possible top-four retrieval, including currently
        # provisional entries. The full immutable provenance registry is stored
        # separately and counted in retained-state bytes, not hidden as free
        # memory or incorrectly exposed as model context.
        payloads = [_view_payload(entry.view) for entry in self.registry.entries]
        largest = sorted(payloads, key=lambda p: len(canonical(p).encode()), reverse=True)
        return {"prior_sql_and_feedback": self.evidence,
                "source_derived_views": largest[:MAX_RETRIEVED]}

    def snapshot(self):
        return {"arm": self.arm, "active": deepcopy(self.active_payload()),
                "events": deepcopy(self.events), "registry": self.registry.snapshot(),
                "ordinary_count": self.ordinary_count, "active_bytes": self.active_bytes()}

    @classmethod
    def from_snapshot(cls, snapshot):
        memory = cls(snapshot["arm"])
        memory.evidence = deepcopy(snapshot["active"]["prior_sql_and_feedback"])
        memory.registry = DelayedRegistry.from_snapshot(snapshot["registry"])
        memory.events = deepcopy(snapshot["events"])
        memory.ordinary_count = snapshot["ordinary_count"]
        if (type(memory.ordinary_count) is not int or memory.ordinary_count < 0
                or memory.active_bytes() != snapshot["active_bytes"]
                or memory.active_bytes() > MAX_ACTIVE_BYTES
                or len(memory.registry.entries) > MAX_VIEWS):
            raise ValueError("invalid restored memory bounds/count")
        return memory

    def prefix_for_episode(self, question, schema, scope, episode_index):
        if scope is not None and scope.schema_sha256 != digest(schema):
            raise ValueError("scope does not describe the current public schema")
        selected = [] if scope is None else self.registry.selected(
            question, scope, episode_index, immediate=self.arm == "immediate")
        payload = {"prior_sql_and_feedback": deepcopy(self.evidence),
                   "source_derived_views": [_view_payload(entry.view) for entry in selected]}
        if not self.evidence and not selected:
            return [], []
        messages = [{"role": "user", "content":
                     "Prior own experience. Numeric answers concern old rows. The views below "
                     "match current observed schema and catalog; their predicates remain in force. "
                     + ("Immediate-reuse ablation: these views need not be corroborated.\n"
                        if self.arm == "immediate" else
                        "Provisional relations are excluded from this view list.\n")
                     + canonical(payload)}]
        return messages, [entry.view for entry in selected]

    def prefix(self, question, schema):
        # A caller lacking a current paid public scope cannot retrieve views.
        return self.prefix_for_episode(question, schema, None, self.ordinary_count)

    def selected(self, question, schema):
        raise ValueError("delayed selection requires current catalog scope and episode index")

    def add_view(self, *args, **kwargs):
        raise ValueError("use the delayed registry with complete charged witnesses")

    def _bound(self):
        while len(self.registry.entries) > MAX_VIEWS:
            removed = self.registry.entries.pop(0)
            self.events.append({"event": "entry_evicted", "entry": removed.key, "reason": "count"})
        while self.active_bytes() > MAX_ACTIVE_BYTES:
            if self.evidence:
                removed = self.evidence.pop(0)
                self.events.append({"event": "evidence_evicted", "record_sha256": digest(removed)})
            elif self.registry.entries:
                removed = self.registry.entries.pop(0)
                self.events.append({"event": "entry_evicted", "entry": removed.key, "reason": "bytes"})
            else:
                raise ValueError("empty delayed memory exceeds its bound")

    def finish(self, trace, conversation):
        super().finish(trace, conversation)
        self.ordinary_count += 1
