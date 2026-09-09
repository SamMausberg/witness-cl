# v8 bounded SQL environment

This is a synthetic evaluator and executable interface, not an empirical claim
that an agent discovers useful abstractions or beats a memory baseline. No LLM
or heldout evaluation is performed by the environment. Frozen v7 files remain
unchanged.

## Learner-visible contract

`make_stream(seed, condition, split='development')` returns an evaluator-owned,
immutable `StreamSpec`. Its `ordinary` tuple contains 24 `EpisodeSpec` fixtures;
`old_panel` and `final_panel` each contain eight. A harness opens an episode with
`open_episode(spec)` and sends **only** `session.public` to the learner. That
frozen `PublicEpisode` contains a natural-language question, the complete
physical CREATE TABLE schema, and the eight-SELECT limit. It has no task ID,
family label, phase, seed, target, reference SQL, database path or semantic
feature list. Random names are opaque and generated independently of the
business conventions.

The text model may submit arbitrary ordinary SQLite through
`session.query(sql, parameters=None)`. Named parameters bind finite integer,
float, text or NULL literals; they cannot substitute identifiers or execute SQL.
Each return is an immutable `QueryResult(columns, rows, error, attempt,
truncated)`. There is no predefined semantic action grammar, table-reading
schedule or answer-query library supplied to the model. SQLite syntax and the
published interface limits are fixed prior knowledge.

`session.answer(value)` terminates ordinary answering and returns `Feedback(reward)`.
Reward is exactly 1 when a finite numeric answer is within
`1e-6 * (1 + abs(target))` of the target, and 0 otherwise. It reveals no target
value. Wrong or malformed answers also terminate ordinary answering. A second answer
is prohibited. Query count is reported separately from accuracy; the environment
applies no accuracy discount or preferential reward to any learner arm.

The evaluator may open an ordinary learning episode with
`open_episode(spec, allow_learning_checks=True)`. Only this explicit capability
permits `session.query(sql, parameters, learning_check=True)` after the answer,
for sample-consistency checks of experience-derived proposals. Both gates are
required, learning checks before an answer are rejected, and ordinary queries
remain closed after an answer. The same lifetime eight-attempt budget,
read-only authorizer, row/byte/VM/time limits and query accounting apply. A check
cannot change feedback or submit another answer. Calls rejected for disabled
capability, wrong phase or closed session execute nothing and consume no SQL
slot, like existing post-closure calls.

The fixed harness enables this capability only for ordinary `learn=True`
episodes; its model action schema must not expose `learning_check`. Panel
sessions keep the default `allow_learning_checks=False`. The capability is an
evaluator setting, not a learner-selected permission. Comparing a synthesized
query against witnessed rows establishes sample consistency only; it does not
prove universal semantics, genuine abstraction or later useful composition.

The hidden `EpisodeSpec`, `evaluator_expected`, `evaluator_sql`,
`evaluator_recipe`, and `evaluator_metadata` are evaluator/auditor APIs. They must
never enter a model prompt, retrieval key, memory proposal, applicability check,
or solver dispatch. This is a capability boundary for a text-only model with a
fixed tool dispatcher. It does not sandbox adversarial Python that can inspect
objects in the evaluator process.

## Identifiable conventions and actual relations

Each fresh database has 32 orders, eight customers with one to three profile
rows each, zero to two refund events per order, and zero to three shipment
events per order. A 24-row `catalog(table_name, column_name, description)` table
is available to SELECT. It supplies authoritative human-readable documentation
of the current column meanings and business conventions, without SQL examples,
reference answers or question-family labels. Reading documentation consumes a
normal SELECT. Catalog/data observations, the question, executed tool results,
and subsequent binary feedback are legal experience.

Four generator choices vary the order/refund currency unit (cents or dollars),
the meaning of a missing order amount (zero or unreported), profile multiplicity
(single current record or historical snapshots), and current-profile selection
(the designated flag or greatest revision). Unreported amounts remain absent
from monetary averages/totals; counts and unit counts still include the order.
When flag selection is authoritative, greatest revision can be wrong. When
revision selection is authoritative, the flag can be wrong. Profile-row IDs
are distinct from customer references. All customers have exactly one valid
current profile, and every order resolves to a customer.

Gross order value is normalized unit amount times quantity. Net value subtracts
the sum of that order's refunds. Joining raw event tables can multiply both
order values and refund counts. Delivery is any delivered shipment; latest
shipment day is the greatest shipment day. Multiple refund and shipment records
provide observable evidence for the join/aggregation hazards. The catalog makes
these semantic distinctions identifiable; this benchmark does not ask a learner
to infer an unknowable unit convention from numerically ambiguous rows.

These fixtures measure learning to implement and reuse documented relations.
They do not establish discovery of undocumented business semantics, learning
outside SQL, or open-ended representation growth. The evaluator has a finite
question generator; it does not expose that generator as a learner feature
basis. All four relations are visible in the initial schema, so an agent may
choose to explore a later-needed relation early and pay for that exploration.

## Stream and split definitions

All ordinary questions use fresh rows. In `reuse`, names and conventions persist
through the stream. In `nonreuse`, every question uses independently generated
names and a new convention combination; it controls stable schema-specific
reuse, but does not eliminate transferable SQL knowledge. In `near_match`, the
first eight questions use the original schema conventions. At question nine,
all four convention choices flip while physical names persist, and the question
contains a migration notice. Subsequent documentation reflects the new state.
This is an announced-drift challenge, outside a stationary admission theorem.

Questions 1–8 practice monetary normalization/NULL handling, quantity filtering,
current profiles, customer joins and refund events. Questions 9–16 require new
compositions such as net amounts by current profile, nested customer aggregates,
ratios and conditional counts. Questions 17–24 add shipment-event compositions.
The final panel combines the middle-block questions with delivered-order and
multiple-refund restrictions that never occur together in an ordinary target.
Its rows are fresh and its final memory must remain frozen.

`old_panel` contains **eight fixed fresh datasets** with the same questions,
physical schemas and original conventions as ordinary questions 1–8. Its data
seeds are distinct from every ordinary and final case. A harness must compare
its selected post-learning checkpoint and final checkpoint on the same fixed
old-panel fixtures, without training, memory updates or model-visible evaluation
feedback. This measures retained old-task competence on unseen rows; memorizing
ordinary scalar answers cannot solve it. The final compositional panel is
separate. The harness, not this module, owns checkpoint freezing and exclusion
of panel feedback from learning.

Development and heldout generator splits use disjoint combinations of the four
convention bits: even parity in development, odd parity in heldout. Both values
of every individual bit occur in both splits; all sixteen combinations exist
across the generator. Thus the split withholds combinations, not just row seeds.
The 16 post-warm question templates also differ across these splits after
literal normalization. The first eight primitive practice questions are shared.
The final restriction composes the relevant split's middle-block templates.
These are prespecified synthetic splits, not evidence of native benchmark
performance. Constructing or evaluating heldout streams requires the caller's
separately frozen experimental protocol.

## Composition evidence

Reference SQL uses a common CTE rendering containing some relations unnecessary
for individual targets. Its hash is **not** evidence of semantic novelty.
`SemanticRecipe` instead records the final SELECT's normalized operator tokens
and only the dependency trees demanded by its referenced semantic measures.
Literal strings and numbers are replaced by placeholders; random physical names
never enter the recipe. Required relations, practiced subskills and a normalized
fingerprint are evaluator-only metadata.

For example, a gross-total target requires the orders relation and its monetary
amount interpretation. Its recipe omits refund/profile/shipment CTEs. A net
amount target filtered by current customer region requires monetary order
values, refund aggregation and current-profile selection/join. The nested
SELECT, aggregate grain and filter-column identities remain in the normalized
program. A North-to-South literal change has the same fingerprint. A newly
introduced subtraction, grouped maximum, or cross-order existence condition
changes the program.

The dependency annotations use the generator's referential and unique-current
profile invariants. They describe the question's minimal semantic calculation;
they are not a general SQL optimizer, an automatic proof that two arbitrary SQL
queries differ, or observations available to a learner. Tests require each
middle-block development target to have a new normalized fingerprint and at
least two earlier-practiced required subskills, and check that development and
heldout post-warm program structures are disjoint without constructing heldout
data. Independent review of these finite mappings remains necessary.

A target's new required composition establishes only opportunity for transfer.
To show learned transfer, the experiment still needs successful actual learner
SQL, trace-grounded learned fragments, provenance of invoked fragments on these
new targets, total resource accounting, ablations and strong memory baselines.
A metadata label or correct hidden reference query supplies none of that result.

## Execution bounds and authority

The database exists only in SQLite memory. Setup creates tables and inserts
fixture rows; then extensions are disabled, `query_only` is enabled,
`trusted_schema` is disabled, and a deny-by-default SQLite authorizer accepts
SELECT, reads of the five known tables, and a fixed set of ordinary pure SQL
scalar/aggregate/window functions. Writes, DDL, PRAGMA (including table-valued
PRAGMA), ATTACH/DETACH, transactions, schema metadata, extension/file functions,
random functions and recursive CTE execution are denied. No SQL-supplied path
is opened, and there is no filesystem, network, shell or external-service tool.

Every accepted query attempt, including malformed, denied, parameter-invalid,
failed and interrupted calls, consumes one of the eight slots. Requests after
exhaustion execute nothing. A result has at most 50 rows, at most 4,096 UTF-8
bytes per text cell and 65,536 payload bytes overall; larger row sets return
only the first 50 rows with `truncated=True`. Oversize cells/byte payloads,
BLOBs and non-finite numeric results return an error. SQL is at most 16,384
UTF-8 bytes and accepts at most 128 bounded named parameters.

SQLite additionally caps record length, expression depth, columns and compound
SELECTs. A progress handler checks every 100 VM instructions and interrupts at
200,000 instructions or 0.25 seconds; elapsed time is also checked after result
materialization. The instruction counter has 100-instruction granularity, and
this is a bounded cooperative SQLite budget rather than an OS real-time deadline.
`select_attempts`, `query_seconds`, `vm_steps` and `setup_seconds` expose actual
local accounting to the harness. Model inference, tool serialization, proposal,
retrieval, checking, reflection and harness work must be added by the experiment.

## Verification scope

`tests/test_sql_env_v8.py` exercises development fixtures only, including
independent Python target calculations versus executable reference SQL,
immutable public boundaries, bound literal injection attempts, denied writes
and file/extension operations, row/byte/VM/time/attempt caps, malformed answers,
replay, schema changes and composition fingerprints. Static split-definition
checks inspect templates and conventions without constructing heldout datasets.
Passing these tests establishes the local fixture/interface contracts; it does
not establish an accuracy, interaction-efficiency or continual-learning result.
