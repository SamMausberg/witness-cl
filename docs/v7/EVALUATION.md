# Version 7 preregistered evaluation

This protocol is written before development outcomes and frozen with executable
source hashes before the untouched evaluation seeds. It is a research protocol,
not a guarantee that its success targets will be met. v6 data remain archived.

## Question, mechanism, and interpretation

Can a bounded library of learned numerical features improve online transfer when
candidate changes require fresh statistical evidence, and does the gain survive
charging the audit queries? No finite list of possible worlds is supplied. The
learner does receive a substantial prior: a common grammar of all 84 monomials of
total degree at most three in six visible numeric fields. This is feature
selection and numerical composition inside a supplied grammar, not arbitrary
representation discovery, online LLM training, autonomous SQL synthesis, or a
native agent benchmark. The public report identifier is authentic and stable;
routing and task identity are given rather than inferred.

Each fresh context is an actual in-memory SQLite database with two related
tables. Values, row counts, SQL work, feature work, history and policy sizes are
bounded. Two fixed SELECT measurements produce the learner's immutable visible
observation. The evaluator computes the scalar target with an independent SQL
JOIN/SUM. It reveals that target only after an ordinary prediction. Reward is
one exactly when absolute prediction error is at most `1e-6*(1+abs(target))`,
and zero otherwise. Own earlier ordinary observations and targets are legal
training data. Gold report definitions, seeds and hidden relationship labels are
never learner inputs. No candidate controls SQL, permissions or reward code.

## Streams and arms

Development seeds are 80000 through 80003. Untouched evaluation seeds are 81000
through 81015. A seed selects four distinct pairwise products `x_i*w_j` from
eight possibilities as four warm report rules. Two new reports respectively
sum warm features 0+1 and 2+3. Two further new reports use distinct degree-three
products `x_i*x_j*w_k`, with repeated x factors allowed. Report IDs are opaque
hashes. Rules do not drift within a stream.

The ordinary stream consists of four warm reports in round-robin order for
24 observations each (96 total), then the four novel reports likewise for
24 each (96), then the four old reports for eight each (32): 224 predictions
made before receiving their targets. A longer stream cycles through all eight
reports thereafter. Ordinary context seeds are deterministic hashes of run seed
and ordinary cursor, independent of arm. Audit seeds use a distinct namespace
including arm, protocol, report, audit index and pair number. Final and retention panels
have their own namespaces and no learner feedback.

| Arm | Fitting / search | Installation |
|---|---|---|
| audited_grow_reuse | Starts with count and six linear features; adds at most five grammar features, scoring at most 16 candidates per update; promoted bank comes first | Fresh paired gate |
| audited_grow_no_reuse | Same caps; no bank priority | Fresh paired gate |
| audited_grow_full84 | Same growth procedure and bank; up to 84 candidates | Fresh paired gate |
| audited_full_history_sparse | Three-step matching pursuit over all 84 features using its entire legal history | Fresh paired gate |
| ungated_full_history_sparse | Same full-history sparse learner | Every ordinary proposal |
| ungated_full_ridge | All 84 features with scaled least squares and ridge penalty 1e-10 | Every ordinary proposal |

Feature values already extracted from an observation are cached for every arm.
Costs include extraction, subsequent fitting and scoring, training-criterion
prediction, deployed prediction, audit prediction, SQL execution, database setup
and storage. Numeric payload bytes are not process resident memory. CPU timings
are descriptive on this machine and do not establish hardware-independent speed.
All BLAS pools are restricted to one thread. No hyperparameter is selected on
untouched streams. The all-zero initial policy supplies a fixed anchor; no claim
that this is a strong baseline is intended.

## Promotion protocol

One gate is retained across all reports in an arm/run. It spends
`alpha_j=.05/(j*(j+1))` for every started audit, with no refund. This is a per-run
error budget, not a simultaneous .05 guarantee across all benchmark runs/arms.
A candidate is considered every four own ordinary observations, starting at
four, only if its accuracy on that report's own ordinary history is at least
.75 and exceeds incumbent history accuracy by at least one example. This
criterion can overfit training history; it is not admission evidence.

Freeze complete candidate and incumbent feature/weight tuples and hashes before
starting the audit. Execute both on fresh equivalent read-only contexts. The
fixed bet is .5 on their binary reward difference, and admission requires wealth
at least `1/alpha_j` with an exact rational crossing guard. Cap at 64 pairs;
inconclusive candidates leave the incumbent unchanged. Each accepted promotion
can change only its public report's incumbent, and bank additions contain only
its promoted feature syntax. Other installed hashes must remain unchanged.
Audit observations and labels never enter numerical fitting or candidate history.
They may affect subsequent behavior only through the accept/inconclusive result
and the resulting bank. This adaptive use requires every later audit to be fresh.

Under the stated conditional sampling assumptions this is a standard
supermartingale test and a summable-error composition argument. The probability
argument is documented, not Lean proved. The deterministic Lean accounting layer
states how actual erroneous promotions and tolerance spending bound expected
retention. Neither component establishes pointwise future-task protection,
robustness to drift, or alignment. Per-update tolerance is zero.

## Matched ordinary examples

Every arm makes exactly 224 ordinary predictions and receives the same ordinary
contexts and targets. History cap is 64 per report, exceeding all exposures.
Fresh old-report panels use 16 contexts/report immediately after warm training
and after novel training, with identical panel seeds at both checkpoints.
These are not training data. Score a final panel of 32 fresh contexts for each
of eight reports. Charge every evaluation execution in the matched cost report.
These arms share ordinary examples; their actual total query costs can differ.

The primary transfer estimand is each seed's mean prequential reward on the two
shared novel reports across their first 24 exposures, with paired differences
between audited_grow_reuse and audited_grow_no_reuse. The first eight exposures
are a predeclared negative control: bank search cannot yet affect installation.
Also report novel unshared and warm reward, old-report retention, total ordinary
reward, final-panel reward, promotions, audit pairs, cost and feature discoveries.
Matching old-report digests through novel training is structural retention under
fixed routing; it is not evidence of a learned routing or statistical discovery.

## Equal query-budget companion

Each arm gets 4096 **post-setup SELECT executions**, including its final panel.
Reserve `8*32*3=768` for the feedback-free final panel; at most 3328 remain for
ordinary examples and audits. Ordinary execution uses two measurement SELECTs
and one gold SELECT, costing three. A pair executes two measurement SELECTs per
policy plus one shared gold SELECT, costing five. This sharing is possible
because the read-only database and gold task are identical for both policies.
Count actual attempts even on failure, and log setup separately. DDL, INSERTs,
PRAGMAs and commit are outside this named SELECT budget; setup time remains a
reported cost. This is query matching, not equal wall time or equal all-resource
compute.

Ungated methods can spend saved audit queries on additional ordinary feedback
from the same stream prefix. No arm skips ahead to reach a later phase. Stop a
partial audit inconclusive if fewer than five queries remain, and start no
ordinary example with fewer than three. The final panel still scores all reports,
including unvisited ones using their initial policy. Report exposures and report
reach explicitly. Cap ordinary episodes at 2048 as an engineering guard; the
query budget binds before that cap. All methods use history cap 256 per report,
large enough to retain every possible ordinary example in this protocol. There
are no intermediate retention panels in this companion. Final score is the
macro-average across its eight equally weighted reports.

## Inference and kill criteria

Independent streams, not individual contexts, are the statistical replicates.
Report seed-level paired means with two-sided Student t intervals at nominal
95 percent. The first comparison above is the sole primary transfer comparison;
all other intervals and control rankings are descriptive, without a familywise
significance claim. Preserve all development and evaluation raw records, policy
versions, gate journals, context seeds and source/configuration hashes. Report
failures rather than replacing seeds or discarding difficult runs.

The transfer hypothesis needs at least .05 mean reward gain and a positive paired
lower interval over no reuse. The practical control set is fixed in advance: audited_full_history_sparse,
ungated_full_history_sparse and ungated_full_ridge. A practical usefulness claim
needs at least .05 final-panel gain and a positive paired lower interval against
each of those three controls at the 4096 SELECT ceiling, plus no detected
old-policy mutation. This conjunction tests dominance of the fixed control set;
all three paired comparisons are retained. Naming the best observed control is
descriptive and does not select a new primary comparison. Failure of either gate is a failed hypothesis at this scale. Winning
only against a deliberately bounded search is insufficient. Costlier learning
may still teach us a mechanism, but it is not the requested stateful benchmark
win. If sparse full-history recovery solves the task sooner, retain that result.

Noise, outside-grammar degree-four parity and hidden-drift counterexamples are
mechanism/boundary tests, separate from the primary streams. Their success or
failure must not be relabeled as held-out benchmark performance. A native
fixed-backbone comparison with full-history ICL remains required for the larger
problem, with model inference, reset and audit cost measured before scaling.
