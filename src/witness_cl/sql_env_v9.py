"""v9-only correction for SQLite's column-free reads of transient relations.

A fresh inherited session contains exactly the evaluator's allowlisted physical
 tables. SQL cannot create objects, attach databases, or load extensions. SQLite
also exposes eponymous virtual tables without CREATE TABLE, so their registered
module names are inventoried privately at setup and excluded from this exception.
This policy applies to that fixed connection, not externally mutated databases.
"""
from __future__ import annotations

import sqlite3
import time

from .sql_env_v8 import (
    EpisodeSession as _EpisodeSessionV8,
    EpisodeSpec,
    evaluator_metadata,
    make_stream,
)


class EpisodeSessionV9(_EpisodeSessionV8):
    def __init__(self, spec: EpisodeSpec, **limits):
        started = time.perf_counter()
        self._virtual_module_names = frozenset()
        super().__init__(spec, **limits)
        try:
            # Host-only setup, before the session is returned to a caller. Keep
            # query_only and extension disabling in place; never expose this
            # metadata or inventory query as a learner observation.
            self._db.set_authorizer(None)
            rows = self._db.execute('PRAGMA module_list').fetchall()
            if not rows or any(len(row) != 1 or type(row[0]) is not str for row in rows):
                raise RuntimeError('SQLite virtual-module inventory unavailable')
            self._virtual_module_names = frozenset(row[0].casefold() for row in rows)
        except Exception:
            self.close()
            raise
        finally:
            if not self.closed:
                self._db.set_authorizer(self._authorize)
        self.setup_seconds = time.perf_counter() - started

    def _authorize(self, action, first, second, database, source):
        decision = super()._authorize(action, first, second, database, source)
        if decision == sqlite3.SQLITE_OK:
            return decision
        # COUNT(*) can generate READ(cte_name, '', None, None), without a
        # physical-column read. Every persistent relation is already governed
        # by the inherited allowlist. Deny SQLite's internal relations and all
        # registered eponymous modules before admitting a transient name.
        if (action == sqlite3.SQLITE_READ and type(first) is str and first
                and second == '' and database is None):
            name = first.casefold()
            if (not name.startswith(('sqlite_', 'pragma_'))
                    and name not in self._virtual_module_names):
                return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY


EpisodeSession = EpisodeSessionV9


def open_episode(spec: EpisodeSpec, **limits) -> EpisodeSessionV9:
    return EpisodeSessionV9(spec, **limits)
