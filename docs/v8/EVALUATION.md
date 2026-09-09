# Version8: testing experience-derived executable abstractions

Status: development protocol, written before this version's first task-model run.
Two transport-only preflights (plain JSON, then constrained JSON) are recorded separately. This protocol does not
assert that the user's requested research claim has been demonstrated.

## Claim and obligations

The target is an online agent that discovers reusable executable abstractions
from its own experience, applies them to genuinely new compositions without task
IDs or an enumerated semantic feature catalogue, requires substantially fewer
interactions than strong full-history and evolving-memory controls, and preserves
previously learned behavior. Each part is a separate empirical obligation.

An interaction is an attempted SELECT submitted to the environment, including
invalid queries, operational checks and fragment executions. Model calls/tokens,
wall time and storage are additional costs, reported separately. Savings in
prompt tokens alone will not count as fewer environment interactions. All arms
can issue arbitrary permitted compositional SQLite SELECTs. Consequently, a
competent full-history solver may already answer with one SELECT; a checked
fragment needs a check plus its execution and cannot beat that lower bound. Such
a result falsifies this mechanism's interaction-efficiency claim in this domain.

The supplied prior is standard SQLite SELECT syntax, a typed literal-hole
compiler and fixed resource caps. There is no enumerated feature dictionary or
preloaded semantic SQL library. Templates are proposed from that arm's own successful episode traces, then a
charged reconstruction query must match an observed scalar that produced its
confirmed answer. Source, guard, proposal and executed-check provenance are retained. Correctness
feedback confirms the episode answer, not the general semantics of every query.
A query template whose literal arguments never vary is closer to stored code
than demonstrated abstraction. Evidence must separately show changed bindings
and composition into a new outer query, with correct resulting answers.

Only the natural question, visible DDL schema, own SELECT results, own actions
and delivered binary correctness feedback enter the learner. Hidden seeds,
phase/index labels, condition names, reference SQL and answers never enter its
prompt or retrieval. Intrinsic library-entry indexes identify stored programs,
not tasks. Retrieval scores overlap between visible question text and stored
content. The evaluator's metadata is appended to raw artifacts only after the
interaction. This Python interface is not an OS sandbox against arbitrary
host-process introspection; the model returns text, not Python code.

## Environment and composition

Each stream has24 ordinary questions: eight warm questions, eight new
compositions, then eight more complex questions. Fresh bounded table rows prevent
answer caching. The catalog is ordinary queryable data documenting identifiable
schema conventions, including units, missing values, profile multiplicity and
current-row selection. Orders, profiles, refunds and shipments have randomized
surface names. A finite task generator is an evaluator construction, not a
learner-side feature library. Source access by the reference implementation is
not a claim that the foundation model has never seen similar SQL problems.

`reuse` retains conventions; `nonreuse` changes names/conventions independently;
`near_match` provides a visible migration notice and changes conventions while
retaining misleadingly similar names. Development and held-out streams split by
convention combinations and compositional templates. Novel composition must be
verified from evaluator-only required semantic operations/relations and distinct
operator structure, not just different literals/rows or raw SQL hashes containing
unused CTEs. A successful learned use must also be traced to its own earlier
observations. The late shipment tasks introduce a new relation and are reported
separately from recombinations of already practiced relations.

Eight old questions retain their initial instructions, schema and conventions
but use independently generated rows not used for ordinary learning. This fixed
fresh-old panel is evaluated with memory frozen after warm learning and again after all later
learning; neither evaluation updates memory. Eight final questions use a frozen
final memory and novel compositions. Query observations inside a panel episode
are local to that episode. The evaluator never sends gold answers.

## Shared model and six controls

The cost pilot uses the official Qwen/Qwen3-4B-GGUF Q8_0 weights at model-repository
commit `bc640142c66e1fdd12af0bd68f40445458f3869b`. The file SHA256 is
`8c2f07f26af9747e41988551106f149b03eb9b5cb6df636027b6bf6278473300`.
The existing llama.cpp build is pinned to
`fe2adf0e722f30f5295fdec8a0f1dc788f7498bc`. Native context is32768 tokens, one
server slot, thinking disabled, greedy temperature0 with seed42, schema-constrained JSON output (also validated by the fixed parser),
384 output tokens per solve and1024 per reflection. This deterministic choice
is an experimental setting, not the model card's recommended sampling recipe.
All model calls are measured, requests are not retried or silently truncated,
and failed/unknown usage prevents a valid resource comparison. Exact backend
tokenization preflights every request; its time is counted. Prompt KV reuse is
disabled, and arm order rotates by scheduled question.

The six arms share the same initial solving instructions and model:

1. `full_history`: every prior ordinary question/action/result/feedback retained
   verbatim. If it cannot fit, the run is a context-feasibility failure, not a
   full-history result obtained through undisclosed truncation.
2. `verbatim`: two prior complete episodes retrieved by content overlap from its
   complete own-episode archive. The backing archive counts toward storage.
3. `insights`: the model revises up to16 natural-language insights after every
   ordinary episode, using its previous insights and the complete current trace.
   Reflection is charged. This is an evolving-insight control, not a reproduction
   or claimed best tuning of ExpeL/ACE or another published system.
4. `fragments`: after a correct ordinary episode, one charged model reflection
   may synthesize one new generalized SQL relation, typed literal holes and an
   outer query reconstructing its own observed successful scalar answer. The
   reconstruction must execute on the same database and match that scalar before
   admission, comparing one finite numeric cell with tolerance1e-6(1+|answer|);
   matching column labels or bitwise float equality is not required for this
   reconstruction. It spends one of the episode's remaining eight SELECT attempts.
   A guard is selected from complete own observations. Up to16 immutable entries
   are stored; at most two are retrieved. Parameters
   are typed literal holes, not executable identifiers. USE executes a template;
   COMPOSE embeds it as a `reused` CTE beneath a model-generated outer SELECT.
   A fresh execution of the stored guard must match its complete witnessed result
   before each use. Failure returns actual evidence and permits ordinary solving.
5. `fragments_unchecked`: the same construction and execution with guard checks
   disabled, isolating their cost and robustness effect.
6. `stateless`: no cross-episode information.

Fragment structure is bounded by32 Text/Hole parts and4096 SQL bytes; Text chunks
may contain many SQL syntax nodes. This is not a32-node parsed-SQL AST limit.
The total active memory cap is65536 bytes; natural-language insights have16
entries of at most512 characters. Full-history/retrieval raw retention caps at
1500000 bytes. All payloads, retained raw state and provenance journals count.
Research-only exported audit logs are separately sized and cannot be retrieved
by the learner. FIFO eviction is explicit and can cause forgetting.

## Cost pilot, freeze and stopping

The development pilot starts with seed90000 in the reusable condition and all
six arms. It has24 ordinary questions plus eight old-before, eight old-after and
eight final questions: at most288 arm-episodes. At most four development streams
may be run under this protocol; this is a ceiling, not permission to exceed the
30-minute total pilot wall ceiling. The clock includes task setup, all model
calls, extraction, retrieval, checks, panels and incremental trace export.
Model download/load and both transport preflights are separately reported setup.

Each arm/stream reserves500000 total model tokens and280 calls for ordinary
learning, plus500000 tokens and260 calls for panels. Each episode permits at
most eight SELECT attempts and ten model action calls; malformed actions consume
a charged attempt. Exhaustion without an answer is an explicit failure, not a
fabricated guess. Post-answer reconstruction never changes the scored answer,
uses the same SELECT authority available to every ordinary learner, and shares
the same lifetime eight-attempt cap. It is disabled on evaluation panels. A failed,
malformed or budget-skipped proposal leaves existing memory unchanged; there is
no uncharged retry. Only pre-proposal observations are eligible witnesses. One
matching reconstruction can accept a constant-answer program, so finite admission
alone does not count as discovered transfer. Later changed arguments and correct
new composition must supply that evidence. Unused ordinary allocations do not erase the equal reserved
panel allowance. Global wall exhaustion ends the pilot and preserves partial
traces. Partial rows do not count as a complete primary comparison. Unknown
backend costs, context exhaustion, runtime failure, source changes during the
run, or missing panel records prevent confirmatory interpretation.

Before any held-out model run, freeze all source, prompts, backend settings,
analysis and the complete evaluation plan. A reasonable development competence
threshold is at least.75 warm accuracy for both full-history and evolving-insight
controls, at least .75 fresh-old-before accuracy for the proposed learner,
and correctly traced parameter reuse/composition for the proposed method. Low
initial competence cannot satisfy preservation merely by remaining low. Some
fixture counts are invariant despite fresh rows, so report absolute old-panel
competence and the constant-count items separately. Failure is a model/mechanism feasibility result; it cannot support a
strong-baseline superiority claim. No tuning is allowed on held-out outcomes.

## Confirmatory decision rule (not executable authorization to scale)

Use independently generated streams, not individual correlated questions, as
replication units. Both full-history and evolving insights are mandatory primary
controls. For each control require the one-sided simultaneous upper confidence
bound for mean `Q_fragments - .75 Q_control` to be below zero, and the one-sided
lower bound for accuracy difference to exceed-.02. Require the proposed arm's
old-after minus old-before accuracy lower bound to exceed-.02. Include failures
in accuracy and do not compare query costs only among solved tasks. Equal total
resource ceilings must be reported; source/model cost changes invalidate a
matched comparison. Report every comparison and condition.

There are at least five required endpoints (two query savings, two accuracy,
one retention). Predeclare familywise alpha.05 (for example Bonferroni one-sided
.01 endpoints), power and sample size from development variability before any
confirmatory runs. Four development streams cannot establish these margins.
For illustration, approximate90% power for a.02 margin requires about326 streams
when paired SD=.1, or82 at SD=.05; these are planning calculations, not observed
variance. Even zero observed regressions in a few correlated questions does not
prove2% retention. Scaling requires a concrete feasible resource plan; do not
silently raise the pilot cap or present a small pilot as the requested result.

Lean proves exact request expansion/binding and conditional fallback identities.
It does not prove successful discovery, lower sample complexity, semantic
correctness for new arguments, old-task retention under eviction, SQLite's
implementation, model quality, general alignment or arbitrary future behavior.
