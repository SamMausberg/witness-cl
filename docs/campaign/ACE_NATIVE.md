# Official ACE and native delayed memory

`witness_cl.ace_memory.ACEMemory` uses the Generator, no-ground-truth Reflector,
and no-ground-truth Curator prompts from official
[`ace-agent/ace` at 82709de050e1db6e6ef2f07bcb0393560b94992a](https://github.com/ace-agent/ace/tree/82709de050e1db6e6ef2f07bcb0393560b94992a).
The exact upstream ADD merger and helpful/harmful counter functions are vendored
under `src/witness_cl/_vendor/ace`, with Apache-2.0 license and file provenance.
The only change in the full merger source is a relative import; its slug helper
is extracted unchanged from upstream `utils.py`. No network is needed at runtime.

The adapter invokes the actual three roles. Generator receives the current
episode and playbook, emits cited bullet IDs and an ordinary task action in its
`final_answer` field. Terminal public feedback drives one Reflector and one
Curator call per ordinary episode. Every call goes through the same measured
client and budget as solving. There are no hidden reference answers, automatic
retries, whole-playbook rewriting, or uncharged updates. SQL snippets remain
valid playbook content. The optional upstream bullet analyzer is off.

Official ACE at this pin implements ADD only; its merger ignores UPDATE, MERGE,
DELETE and CREATE_META. This behavior is preserved. CL-Bench's separately
vendored ACE has a modified merger with additional operations, so it is not an
exact merger reference for this baseline. The baseline should be described as
**official ACE adapted to the common observable tool interface**, not as an
exact reproduction of the benchmark authors' ACE configuration.

Declared adaptations are the nested action schema, the public-message-only
input boundary, shared local backbone/decoding/budgets, and a 65,536-byte active
playbook ceiling (16,384-token curator target). Over-cap or malformed curator
deltas are rejected in full; previously applied reflector counters remain, as
in the upstream ordering. The failed episode closes, its measured receipt stays
in the archive, and later episodes can update normally. Transport/integrity
failures propagate. Snapshot recovery preserves pending episodes and citations.

Runner hooks are `generator_messages(question, conversation, action_schema)`,
`generator_schema(action_schema)`, `decode_generator(text)`, then
`finish(trace, conversation)` and `update(client, budget, records)`. A runner may
prepend the same shared system message used by the other arms. Panel solving
uses a disposable memory clone. Using only `prefix()` is a playbook ablation,
not the three-role ACE baseline.

## Native CL-Bench

`integrations.clbench.ace.make_ace` and
`integrations.clbench.witness.make_witness` return real upstream
`ContinualLearningSystem` implementations. `LocalClientTransport` connects the
same local model client and preserves all call accounting across resets.
Pass these systems to the unchanged pinned native runner. The native system
sees only prompt, schema and observation content; evaluator metadata, database
paths and reference SQL never enter its input.

Native Witness preserves the complete official QUERY/ANSWER task. It supports
source-derived relation learning for the current conservative scalar-aggregate
lifting language and uses ordinary direct SQL for all other questions, including
text answers. It retains observed DDL and bounded exact query/feedback evidence.
Its 16-entry relation limit and 65,536-byte retained-state ceiling evict oldest
evidence before relations; each eviction is recorded. Only corroborated relations
from earlier episodes enter USE/COMPOSE selection.

The model's pending numeric answer is fixed before the adapter sends two
ordinary charged QUERY actions for reconstruction and relation deletion. Both
execute before ANSWER and consume the same native question's query budget. If
two slots are unavailable, the adapter submits the answer and skips admission.
Only terminal `CORRECT!` commits a provisional witness or later changed-binding
corroboration. An observed SQL reconstruction match cannot override incorrect
task feedback. Unknown/malformed/truncated result tables never count as a
successful check. Native numeric parsing covers only complete one-row,
one-column results; empty-intervention SQL NULL is recorded as changed output.

USE renders the stored aggregate with typed bindings. COMPOSE uses the shared
bounded relation compiler. Compiled bindings become SQLite literals through AST
replacement, preserving quoting and scalar types, and the final SQL is executed
through ordinary native QUERY. The public migration notice changes the scope
and clears observed DDL, requiring rediscovery and new corroboration. Existing
historical evidence remains visible with its original provenance.

The native contract lacks the custom fixture's complete world-model and exact
reset guarantees. Its certificate remains `UNKNOWN`; two observations establish
empirical agreement only. Native default run orderings share the same databases
and are not independent novel-database replications.

## Verification and evidence boundary

`tests/test_ace_memory.py` checks pinned hashes, exact ADD behavior, counter
updates, output envelopes, public input filtering, failure recovery, byte caps
and snapshot round trips. `tests/test_native_learning.py` checks native literal
rendering and strict scalar parsing, plus actual upstream runner fixtures for
provisional admission, later corroboration, new composition, migration,
insufficient query budget and failed-answer rejection.

Run native tests in the optional Python 3.13 environment with the exact upstream
checkout selected by `WITNESS_CLBENCH_UPSTREAM`. These scripted fixture results
are contract tests, not benchmark scores or model-mechanism evidence. A native
model experiment still requires the frozen official datasets/schedule and raw
model traces. Public database assets are not bundled or redistributed here.

Native `.schema` emits multiple CREATE TABLE statements separated by blank
lines without semicolons. The adapter separates statements at SQL token
boundaries and keeps observed user-table DDL; internal `sqlite_` bookkeeping DDL
remains visible in the original observation but does not enter the source-view
schema. The actual native lifecycle tests include several tables and SQLite's
automatic `sqlite_sequence`, so this path is exercised end to end.
