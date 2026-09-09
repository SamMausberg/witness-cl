# Ordinary SQL and stored-fragment parsing in v9

`src/witness_cl/actions_v9.py:parse_action(text)` separates an ordinary `QUERY`
from the stricter representation used to capture executable memories. It is integrated into the v9 learning runner; the earlier diagnostic runners
retain their frozen v8 parser.

For ordinary queries, it validates the exact action keys, UTF-8 SQL size and
at most 128 named scalar parameters. Parameter values are signed int64,
finite real, bounded text or null; booleans and containers are rejected.
Parameter names match the executor's ASCII identifier rule. The shared strict
JSON reader rejects duplicate keys and nonfinite constants and retains its
16,384-byte whole-action limit. Consequently SQL plus its JSON envelope and
bindings must fit that limit, in addition to the executor's SQL-size check.

SQL and bindings are returned unchanged. A trailing semicolon, comments and
unused extra bindings may therefore reach SQLite. The parser does not remove
terminators, rewrite placeholders, discard bindings, repair expressions or
perform any query. Ordinary invalid SQL reaches the existing session and
consumes an attempted SELECT there.

Every ordinary request must still use the bounded `open_episode(...).query`
path. Its statement-prefix rule, SQLite authorizer, read-only database, result
bounds, time/VM limits and eight-attempt ceiling remain authoritative. Parsing
`DELETE`, `PRAGMA`, `ATTACH`, or multiple statements does not authorize them;
the executor rejects them and records the attempted interaction.

`ANSWER`, `USE` and `COMPOSE` use the existing v8 action parser. Rebinding and
composition still run the strict fragment checks once the selected entry is
known. Those stored-fragment rules continue to reject unsupported syntax,
unused captured bindings and mismatched typed holes. The frozen compiler and
all v8 files are unchanged.

Forty-two focused offline cases include actual SQLite execution of accepted
forms, rejected writes/PRAGMA/ATTACH/multiple statements, unchanged catalog
readback, charged syntax errors, strict JSON and scalar bounds, and preservation
of the fragment path:

```sh
python3 -m pytest -q tests/test_actions_v9.py
```
