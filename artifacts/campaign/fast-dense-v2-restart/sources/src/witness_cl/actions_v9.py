"""Ordinary SQL transport validation for v9, separate from fragment capture.

QUERY preserves SQL and parameters exactly and delegates statement semantics and
read-only authorization to the existing bounded SQLite session. This module
never executes SQL. USE/COMPOSE retain the v8 fragment-action validation path.
"""
from __future__ import annotations

import math
import re

from .memory_v8 import json_object, parse_action as _fragment_action
from .sql_env_v8 import MAX_CELL_BYTES, MAX_SQL_BYTES

MAX_PARAMETERS = 128
_PARAMETER_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')


def parse_action(text: str) -> dict:
    """Parse a bounded action without rewriting an ordinary SQL request.

    The existing JSON reader retains its 16KiB whole-action ceiling and rejects
    duplicate keys/nonfinite JSON constants. Within that envelope, ordinary SQL
    has the executor's 16KiB UTF-8 ceiling and at most128 named scalar bindings.
    Bindings unused by SQL are permitted, as they are by SQLite's mapping API.
    Empty/invalid/non-read SQL is deliberately left for the charged executor to
    reject. A parsed QUERY is never an authorization to bypass that executor.
    """
    action = json_object(text)
    if action.get('action') != 'QUERY':
        # Preserve finite ANSWER and strict USE/COMPOSE behavior. Composition
        # and rebinding additionally validate against the selected fragment at
        # execution time, when its typed holes are available.
        return _fragment_action(text)
    if set(action) != {'action', 'sql', 'params'}:
        raise ValueError('unsupported action or keys')
    sql, params = action['sql'], action['params']
    if type(sql) is not str or len(sql.encode('utf-8')) > MAX_SQL_BYTES:
        raise ValueError('SQL must be UTF-8 text of at most 16384 bytes')
    if (type(params) is not dict or len(params) > MAX_PARAMETERS
            or any(type(name) is not str or _PARAMETER_NAME.fullmatch(name) is None
                   for name in params)):
        raise ValueError('at most128 bounded named scalar parameters required')
    for value in params.values():
        if type(value) not in (int, float, str, type(None)):
            raise ValueError('parameter values must be integer, finite real, text or NULL')
        if type(value) is int and not -(2**63) <= value < 2**63:
            raise ValueError('integer parameters must fit signed int64')
        if type(value) is float and not math.isfinite(value):
            raise ValueError('real parameters must be finite')
        if type(value) is str and len(value.encode('utf-8')) > MAX_CELL_BYTES:
            raise ValueError('text parameters must fit4096 UTF-8 bytes')
    return action
