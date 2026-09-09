# A bounded relational representation experiment

This phase tests a narrower useful question: can experience-linked feature reuse
reduce the cost or observations required to learn related numerical reports?
The environment executes real SQLite queries, but its data and reports are
synthetic. No language model, deployed agent, external service, or paid compute
is involved. Small numerical least-squares updates are the online training in
this phase. They use scalar targets delivered after ordinary answer attempts;
they do not modify any language-model weights.

The implemented module is `src/witness_cl/relational_v7.py`. Its learner does not
receive a true world table, a reference SQL query, a report formula, a generator
seed, an evaluator database connection, or a hidden regime identifier. This
removes the supplied exact latent-model cover from the previous experiment. It
does not remove the structural assumption of a hand-designed typed feature
grammar or turn the experiment into general representation learning.

## Data and execution boundary

`make_context(seed)` creates an evaluator-owned `SQLiteContext`. There are up to
40 rows in `items(id,group_id,x0,x1,x2,x3)` and up to eight rows in
`groups(id,w0,w1)`. Generated item values are symmetric integers in `[-3,3]`;
group weights are in `[-2,2]`. The evaluator seed controls a fresh database and
is not included in any learner observation. Database setup time is reported
separately from queries.

`context.observe()` performs exactly two fixed SELECT queries, one for each
public table. It returns an immutable `Observation` containing those two raw
result tables, their join through the visible foreign keys, and query count/time.
Joined rows contain six values `(x0,x1,x2,x3,w0,w1)`. Every arm receives identical
measurement results; this primary experiment does not test adaptive query
selection. Retaining a measured row permits later local feature calculation.
Reading additional historical database contents would constitute another
observation and is not permitted by the learner API.

The evaluator computes `context.answer(spec)` independently using an actual
SQLite JOIN and SUM. Its gold specification contains one or two monomial terms
and bounded integer coefficients. Only the resulting scalar is later supplied
to `Learner.observe(report, observation, target)`. The module cannot itself
attest that a caller waited for a real answer attempt; the harness must enforce
that chronology and keep audit targets out of these calls.

The database is in memory. Extension loading is disabled, `query_only` is on,
and a SQLite authorizer allows only SELECT, reads from the two fixed tables, and
SUM/COALESCE. Other functions, PRAGMA changes, writes hidden behind WITH, schema
reads, ATTACH, and DDL are rejected. A progress callback runs at each SQLite VM
instruction and interrupts at a finite step or cooperative elapsed limit.
Result row/byte limits also apply. Failed executed queries still count and take
time. These restrictions bound a local deterministic measurement/evaluation
interface; they are not an operating-system sandbox for arbitrary Python code.
No learner program contains SQL or an executable callback.

## Representation and learner modes

A feature is a typed monomial with six nonnegative exponents and total degree at
most three. Its value is the sum of that monomial across joined rows. Degree
zero gives the row count. The primitive grammar has 84 possible features;
initial growing representations contain only count and six linear sums.
Features such as `sum(x0*x1)` or `sum(x2*w0)` are absent from that initial library
and can be added after observing a residual error. This is bounded feature
construction/selection over a declared grammar, not discovery of new operators.

`Learner` supports four modes:

| Mode | Features and update rule | Reuse boundary |
|---|---|---|
| `grow_reuse` | Fit current features; on a nonzero residual, score at most 16 candidates, add at most one feature, then refit | Previously promoted nonlinear features come first in candidate search |
| `grow_no_reuse` | Same initial basis, candidate quota, fitting, growth trigger, and width cap | Candidate order comes only from the rotating typed grammar |
| `full_ridge` | All 84 features from the beginning; scaled ridge fit to retained own feedback | No shared feature bank |
| `full_history_sparse` | All 84 features available; orthogonal matching pursuit with at most three selected terms and refits | No shared feature bank |

Growing representations have at most 12 features per report. A candidate is
considered only after there are at least two more examples than current
features and the residual exceeds a fixed numerical tolerance. Candidate
columns are projected off the existing design before residual correlation is
scored. The feature search quota is exposed as `search_candidates`; setting it
to 84 permits an ablation against a full candidate sweep. Reuse's specific
hypothesis concerns proposal-search efficiency: it cannot supply information
outside the common primitive grammar or the report's own feedback.

The bank holds at most 32 typed nonlinear features. `on_promotion(report,policy)`
accepts only a frozen proposal previously issued for that report and updates the
bank only in `grow_reuse`. It receives no audit examples, audit targets, or
reference formula. Merely creating a promising proposal cannot populate the
bank. Promotion therefore communicates a coarse selection event; it is not
zero information. The statistical procedure must account for this adaptive
proposal process when interpreting later audit results.

Reports use public opaque tokens and have separate numerical states. This is
explicit task identity, not latent context discovery. A same-token change of
semantics, an unseen schema, or incorrect dispatch remains a separate problem.
The feature bank is shared syntax; coefficients are fit independently from each
report's own feedback. Previously returned policies are immutable tuple-based
feature/coefficient snapshots with content digests. New training or bank updates
cannot alter their predictions. Byte immutability alone does not establish
population retention or correct routing; the harness separately evaluates fresh
old-report contexts and controls promotion.

## Limits, caching, and cost accounting

The default history window is 64 examples per report. The implementation permits
up to 256 so a companion full-history control can retain all of its ordinary
examples when a report has fewer than 256 encounters. A mode named
`full_history_sparse` still operates only on the configured retained history;
it must not be called a lifetime-history control when its window actually evicts
examples. No more than 32 public reports are registered.

Each retained observation lazily caches a feature value after it is first
computed. A later refit reuses that numerical value; it does not rerun SQLite or
recompute all old row monomials. The full-feature controls therefore receive
this cache optimization as well as the growing arms. Evicted observations and
their cached feature vectors are removed. Cost counters distinguish first
feature extraction, row-feature evaluations, repeated numerical fits and matrix
sizes, residual scoring, time, history/cache payload, and frozen proposal bytes.
Counters for payload bytes exclude Python object overhead; the harness should
also measure peak process or traced memory.

`max_candidate_features` and `max_fits` are separate finite limits, each at most
128. The shipped grammar has only 84 distinct features. Strong OMP can score the
same remaining features across three stages, so the number of scalar candidate
scores can exceed 128; those repeated scores are recorded rather than silently
ignored. Every mode has at most three numerical fits per ordinary update under
the default algorithms. Its largest design matrices are bounded by the history
window and 84 features. These are implementation size limits, not an assertion
of equal compute between arms. The harness must charge actual measured costs.

`FrozenPolicy.predict_with_cost(observation)` returns a prediction and the number
of evaluated row-feature pairs. A policy prediction has no mutable counters;
pure `predict` callers must time and account for their own executions. Proposals
can be serialized to ordinary data and reconstructed without an ndarray alias.
Nonfinite/excessive coefficients are rejected. If bounded candidate generation
or fitting fails, valid real feedback remains stored, a failure is counted, and
the previous frozen proposal is retained. No fit failure issues a certificate.

## Validation and falsifiers

Focused tests compare every one of the 84 Python feature meanings to independent
SQLite joined aggregates across four generated databases. They also check two
term reports, authorizer restrictions, VM/time/result caps, feedback API fields,
frozen serialization, promotion-only bank updates, resource bounds, and cache
reuse. Development mechanism checks recover an interaction absent from the
initial feature library; full sparse and sufficiently observed full ridge
controls are tested to recover realizable reports as well.

The degree limit is real. On the complete four-bit sign cube, fourth-degree
parity is orthogonal to every degree-at-most-three monomial. An actual quartic
SQLite report therefore supplies a concrete misspecification diagnostic that
none of the 84-feature learners can represent exactly. Noisy feedback is also
accepted only as numerical data; the learner never calls its fitted output a
certificate. Such tests do not expand the declared gold-generator family or
prove robustness to arbitrary distribution shifts.

The proposal-efficiency hypothesis fails if its transfer gain disappears against
full-feature ridge, full-history sparse search, or the no-reuse grower once
measurement, feature extraction, fitting, inference, storage, and fresh-audit
costs are counted. If public report identity is required for retention, the
claim must remain conditional on that identity. A successful local report study
would still not show open-ended deployed self-improvement, solve forgetting
under hidden drift, establish native CL-Bench superiority, or guarantee
alignment. Those are unresolved claims, not conclusions of this module.
