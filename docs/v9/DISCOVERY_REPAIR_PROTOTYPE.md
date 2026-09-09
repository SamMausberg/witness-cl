# Feedback-guided discovery repair prototype

`src/witness_cl/discovery_repair_v9.py` is a separate prototype. No frozen runner
imports it, and no model experiment has been run with it. The tests use explicit
test doubles and local development fixtures; their successes are implementation
checks, not empirical learning results.

The trusted caller supplies a correct completed ordinary trace, its same answered
open session with learning checks enabled, the current fragment memory, and the
existing inference budget. `run_discovery_repair(..., allow_learning=True)` permits
at most three proposal attempts in one operation per physical session. Repeating
the call is rejected even after null output, compiler-only failures, or a budget
stop; copying the trace does not reset the session's private invocation marker.
Panels and disabled learning return before any
model call, query, or memory update. A prefix that already contains learning checks
cannot be presented again as a new ordinary witness prefix.

The original question, schema, submitted answer, Boolean correctness, and ordinary
observations remain fixed. Only those original observations are eligible source
and guard indexes. Subsequent proposal messages also contain the model's earlier
proposal and its actual validation error or reconstruction/intervention result.
Hidden annotations, evaluator answers, future questions, and other-arm state are
excluded. Feedback explains the structural `reused` alias; it supplies no domain
SQL implementation. The host does not rewrite the model's output.

For each well-formed proposal, the existing compiler prepares a reconstruction
against the complete charged query prefix. A real `learning_check=True` SELECT
must reproduce the original own observed answer. Admission is then validated on
a deep copy of the library, while the existing one-check prefix invariant still
holds. Nothing has been committed to the real library at this point.

The host next spends another SELECT on the same outer query with the learned
relation replaced by `SELECT * FROM (<learned prepared query>) WHERE 0`. This keeps
its columns while emptying its rows. An error, truncation, changed result columns,
or unchanged outer result rejects the candidate. Numeric scalar equality uses the
same tolerance as reconstruction; NULL or no rows may be a valid changed result.
Only after a complete changed result does the staged library commit. Its new event
records the original-evidence digest, reconstruction and intervention indexes,
and the actual intervention digest.

This rejects the observed unused-CTE pattern: outer SQL that independently repeats
the physical calculation has the same result when the proposed relation is
emptied. Passing the intervention is still evidence for one observed outer result
on one database. It does not prove that the relation has the intended meaning,
that it generalizes, or that every apparent dependence is useful. A legitimate
relation whose observed result is unchanged by emptying it may be conservatively
rejected.

Every model call and preflight uses the caller's existing budget and retains its
receipt in `trace['model_calls']`. Every executed reconstruction and intervention,
including SQL errors, appends a charged contiguous row to `trace['queries']` and
uses the same eight-SELECT episode allowance. A parse/compiler rejection costs a
model attempt but does not invent a SELECT. Fewer than two remaining SELECTs stops
before another proposal, because admission requires both checks. A null proposal,
first admission, three attempts, budget failure, unknown model usage, or changed
evidence also stops the routine. The returned bounded journal includes incremental
call, query, VM, timing, and memory-digest information for the future caller to
retain and account for.

A future comparison should give the text-memory control the same maximum of three
reflection opportunities for format/validation errors and charge its actual calls,
tokens, and time. The fragment arm must additionally pay its actual SQL checks.
Integrating this prototype requires a new prospective protocol and a matching
auditor for multiple proposals and staged intervention admission; it cannot change
the interpretation of the frozen v9 study.
