# Historical evidence retained in the consolidated paper

This is a read-only claim audit of the v1-v7 artifacts and original manuscripts
at Git revision `88b0a1b7c093c21135489a3e5cbbda3bb0634536`. Values below are
copied or recomputed from saved per-seed summaries; no experiment was rerun for
this document. Original manuscripts remain accessible with, for example,
`git show 88b0a1b:paper/v3/main.tex`. These historical CPU experiments are
separate from current GH200 measurements and the later language-model pilots.

## The strongest useful early findings

### v1: witness compression preserves a fixed symbolic learner, including its failures

[`artifacts/synthetic/summary.json`](../../artifacts/synthetic/summary.json)
contains 20-seed, 384-episode comparisons on four public scopes over modular
arithmetic. Witness and full-replay induction have identical recorded reward
on every reported scenario. In the interleaved setting both obtain 94.1667%
overall and 100% late reward, while mean hypothesis evaluations are 2,340.9
for witnesses versus 78,146.15 for replay. Witnesses average 29.4 active
constraints. These are symbolic hypothesis evaluations, not tokens, real-agent
inference latency, or a new neural learning result.

The failures are part of the finding. Under hidden shifts, both methods have
15.9115% late reward and four wrong certificates per seed; under misspecification
they have 14.0885% late reward and four wrong certificates per seed. Thus
compression does not repair an incorrect or nonstationary hypothesis class.
The useful mechanism is preservation of a sufficient constraint set for a
fixed class, not superiority over a full-history learner.

The current checked contracts are `WitnessCL.equivalent_certificates`,
`redundant_constraint`, `redundancy_persists`, `fold_truth`, and
`certified_sound` in [`Core.lean`](../../formal/WitnessCL/Core.lean).
`WitnessCL.V2.witness_growth_counterexample` and `growth_decomposition` in
[`Refinement.lean`](../../formal/WitnessCL/Refinement.lean) explain the correction
needed when the class grows: constraints redundant for the old class can exclude
new candidates, so old raw evidence must be replayed. The raw archive grows;
small active witness storage is not bounded lifetime storage. The Lean core
does not prove the empirical search-cost reduction or a finite-cardinality bound.

### v2: fixed-feature protection has an explicit capacity cost

[`artifacts/v2/training.json`](../../artifacts/v2/training.json) stores 20 seeds
at each of four protected ranks in 24 dimensions. The table contains means
computed from those saved rows, not a new run.

| Protected rank | Initial new-task MSE | Final protected MSE | Mean maximum protected drift |
|---:|---:|---:|---:|
| 0 | 25.06985 | approximately 5.28e-15 | 0 |
| 4 | 25.06985 | 4.22598 | 2.01575e-16 |
| 12 | 25.06985 | 12.95825 | 3.81639e-16 |
| 24 | 25.06985 | 25.06985 | 0 |

The unconstrained comparator reaches approximately 5.28e-15 MSE but its mean
maximum protected drift is 1.39088 at rank four and 2.34639 at rank 24. The
protected rank-four fit is therefore a real stability/plasticity tradeoff,
not simultaneous unrestricted fitting and retention. Full-rank protection
eliminates the ability to fit the new task.

The algorithm freezes features phi and the old predictor, then adds
`W (I - U U^T) phi(x)` for an orthonormal protected basis U. An input whose
feature lies in the protected span has zero residual in exact arithmetic.
For isotropic features, the unlearnable target component has population squared
error `||U^T d*||^2`; finite-sample fitted MSE need not equal that population
optimum. Implementation uses float64 SVD and online SGD. This is linear
fixed-feature learning, not a trained neural encoder or LLM adaptation.

`WitnessCL.V2.annihilated_residual_preserves_output` and
`residual_preserves_protected_domain` prove the abstract implication that a
zero residual preserves an integer-valued output. They do **not** formalize
matrix projection, SVD, floating-point error, SGD convergence, or the entire
linear-algebra statement in the original paper. The projection calculation is
an elementary handwritten argument. It ceases to apply unchanged when the
encoder, input construction, protected set, or routing changes.

### v3: learned immutable modules retain outputs when the task identity is supplied

[`artifacts/v3/versioned_training.json`](../../artifacts/v3/versioned_training.json)
contains 80 per-seed summaries for four arms and 20 seeds. Each arm receives
three public scopes, 1,600 sequential interactions per scope, and two real
input coordinates plus a three-way scope tag. The aggregate interaction count
is 384,000 across all arms and seeds. There are 512 independent test inputs per
scope, reused at the corresponding before/after checkpoints. Training is online
with no intervening offline phase. Exact binary success feedback for a binary
action reveals the correct binary label; this is substantially more informative
than general sparse agent feedback.

| Method | Early accuracy | Late accuracy | Mean forgetting | Parameter bytes | Online updates/seed | Replay payload bytes |
|---|---:|---:|---:|---:|---:|---:|
| Shared, 24 hidden units | 64.7167% | 96.1333% | 47.0898 pp | 1,352 | 4,800 | 0 |
| Shared, 72 hidden units | 68.8833% | 96.2583% | 44.5833 pp | 4,040 | 4,800 | 0 |
| Shared 72 units + reservoir replay | 70.0333% | 96.2333% | 2.64974 pp | 4,040 | 9,599 | 10,752 |
| Three immutable 24-unit modules | 74.8667% | 95.4333% | 0 | 4,056 | 4,800 | 0 |

Early/late accuracy averages the first 100/last 200 examples across scopes.
Forgetting is acquired held-out accuracy minus later held-out accuracy,
averaged over old-scope checkpoints. Immutable modules also have zero measured
old-logit drift. The near-matched shared network uses only 16 fewer parameter
bytes, so a comparison against the narrower naive shared network is not the
only control. Reservoir replay has capacity 256 and nearly doubles updates.
Reported storage omits Python object overhead and is not peak process memory.

The immutable method has 0.8 percentage points lower late accuracy than replay
(95.4333% versus 96.2333%). Authentic scope IDs, unchanged preprocessing and
direct dispatch select each old frozen module. The result does not establish
latent task recognition, fixed-total-capacity lifelong learning, or reuse of
learned representations across tasks. Individual neural feedback rows were not
archived; generation seeds, source, and per-seed summaries were retained.

The relevant abstract Lean statement is
`WitnessCL.V2.archive_output_unchanged`: replacing an entry at a different key
does not alter the old keyed function. `WitnessCL.other_scope_unchanged` is
the underlying update identity. Neither statement proves the floating-point
network implementation, learned routing, or training dynamics. This diagnostic
is useful evidence that online training and exact stored-function retention can
coexist under supplied task boundaries, while exposing the conditions that the
later open-ended SQL agent must replace.

### Inference and audit costs: keep the denominators and comparison engine visible

[`artifacts/v2/cube_bench.json`](../../artifacts/v2/cube_bench.json) compares 64
relational plans evaluated by a direct Python interpreter with a shared cube
implementation. At 32, 512, and 8,192 rows, median direct/shared times are
0.479895/0.129626 ms, 7.623821/0.611038 ms, and 113.284889/6.709610 ms.
The corresponding ratios are 3.70, 12.48, and 16.88. These are CPU primitive
measurements against direct Python, not comparisons with an optimized database
engine, GPU timings, or measured end-to-end learner acceleration.

The subsequent [`artifacts/v3/diagnostics.json`](../../artifacts/v3/diagnostics.json)
and archived v3 result ledger report essentially no cold end-to-end benefit from
packed continuation evaluation at the tested shapes: at 64 models scalar
9.830 ms versus packed 10.024 ms. Exact shared-prefix simulation matches the
independent reference on 200 cases and reduces mean environment calls from 64
to 39.405, while controller calls remain 64. The late-divergence construction
favors sharing. A reduction in simulator work is not a measured LLM speedup.

The same `diagnostics.json` includes a separate noisy-evidence experiment:
1,000 independent sequences of 64 observations, a 10% noise rate, and nominal
delta 0.05. The likelihood-based filter ever excludes the actual model in
12 sequences (1.2%); hard elimination loses it in 997 (99.7%). This directly
demonstrates the fragility of treating noisy feedback as exact contradiction
in that correctly specified finite family. It does not prove nominal coverage
or validate a neural probability model. The noisy filter is a separate tested
component, not an implemented stochastic extension of the deterministic agent.

[`artifacts/v2/audit_power.json`](../../artifacts/v2/audit_power.json) contains
4,000 replications per case and cap. At 2,048 opportunities, the diffuse +0.05
gain passes in 27% of simulations, while a sparse process with the same global
gain, gate frequency 0.1 and conditional gain 0.5 passes in 100%. For that sparse
case, screening exact-zero paired differences preserves the same audit wealth
path and reduces extra rollouts from 344.307 to 34.45625, but total rollouts only
from 688.614 to 378.76325 (about 1.818 times). Claiming tenfold total savings or
new statistical information from discarded zeros would be incorrect.

The checked `zero_difference_is_neutral` and `filter_one_factors` are algebraic
identities. They do not formalize sequential testing. In stateful systems,
matching current actions is insufficient to justify a shared continuation:
`WitnessCL.V3.closed_continuations_equal` additionally requires equality of the
complete successor state and forward closure of the protected domain. Controller
memory, tools, preprocessing, and random state must be included in that state.

## v4-v6 evaluation corrections and conclusions that must survive consolidation

| Study | Supported result | Boundary that must accompany it |
|---|---|---|
| v3 continuation | B=4 has exactly the full-history planner's late return on each seed in both domains; B=0 has smaller admissible exploration budget | No return superiority over that strong symbolic control; additional planning is costly. It is not an LLM raw-history comparison. |
| v4 primary | Witness B16 minus full-history mean return -0.0370833, paired 95% interval [-0.0552839, -0.0188827] | The primary result is negative. New random seeds are not necessarily new transition worlds. |
| v5 primary | Decision-guided B16 minus v4 B16 mean return -0.0945833, interval [-0.1691523, -0.0200143] | The proposal's main hypothesis is rejected; post-hoc plateau diagnostics are not confirmatory repair outcomes. |
| v6 primary | Depth two minus informative zero-loss control +0.39375, interval [0.1584505, 0.6290495] | Planning costs 8.8784 times as much; depth two loses 0.19479 to same-engine bounded optimism and spends more realized risk than the zero-loss control. |

Sources are [`v3/continuation.json`](../../artifacts/v3/continuation.json),
[`v4/heldout/latent_summary.json`](../../artifacts/v4/heldout/latent_summary.json),
[`v5/experiment/paper_summary.json`](../../artifacts/v5/experiment/paper_summary.json),
and [`v6/results-derived.json`](../../artifacts/v6/results-derived.json), with the
full v6 contrast table in the archived `docs/v6/RESULTS.md`. These intervals
use seed-level contrasts; correlated episode rows are not independent replicates.

The supplied-model v3 continuation study has 17,920 episode rows:
20 seeds × two domains × seven arms × 64 episodes. Its `late` endpoint is the
final 16 episodes. In the delayed-damage domain, the B=4 controller and
full-history optimistic planner both have mean late return 13.1375, with an
identically zero paired late difference across seeds; B=0 has late return
12.5625. Both B=4 and full history have maximum completed-prefix anchor-relative
deficit two across all seeds; B=0 has zero and immediate-reward greedy has 133.
The compositional-navigation late value also ties at 11.2625 for B=4 and full
history. These native summed rewards are not accuracy percentages. The
controller incurs additional planning work, so the result is conditional
protection with a cost, not a gain over that full-history control. Unlike v4-v6,
this study supplies the finite model family and observes complete states.

The overlap records prevent a stronger generalization claim. The
[`v4 holdout audit`](../../artifacts/v4/holdout_audit.json) finds 81 unique held-out
labelled tables, 19 unique development tables, and six shared tables in a class
of 256. After the first holdout, an exact residual DAG and stricter JSON input
checks were added. The audit compares all 38,400 rows and finds selected
behavioral fields identical; timing and search fields are not an unchanged
pre-freeze measurement. It records no holdout controller tuning.

The [`v5 audit`](../../artifacts/v5/experiment/audit.json) finds 85 unique held-out
tables, ten shared with the pilot, seven shared with v4 development and 22 with
v4 holdout. This is documented sampling overlap, not evidence by itself that
labels were leaked. It does rule out describing these studies as disjoint-world
or new-family generalization.

The v6 sample has 40 distinct held-out tables, eight development tables and
zero observed overlap. The protocol sampled with replacement and did not
guarantee world disjointness. Initial development preceded branch-score and
meter-path fixes; the final source/configuration freeze preceded holdout and
no post-holdout selector tuning is reported. The
[`final replay`](../../artifacts/v6/replay-audit.json) covers 7,680 episodes,
including all 4,800 held-out rows, rather than all 8,640 saved rows. The 960
initial-development rows lack the additional saved incumbent fields and are
not silently included in that verification claim.

The deterministic safety mechanism checks every compatible world, retains truth
under stationary reset-generated evidence, and reserves exploration loss before
executing a trial. Useful checked identifiers are `WitnessCL.V3.bellman_improvement`,
`plausible_member_improves`, `obligation_survives_shrinking`, `debit_budget`, and
`WitnessCL.V4.arbitrary_proposer`, `covered_lower_bound`, `reset_prefix_budget`.
These statements protect the specified reset values or completed-prefix deficit
under their premises; they do not prove safety during arbitrary intermediate
actions, hidden drift, or a wrongly specified class. `safe_policy_cannot_gain_under_aliasing`
in [`Ambiguity.lean`](../../formal/WitnessCL/Ambiguity.lean) makes the opposing
information constraint explicit.

## v7: positive within-family transfer, weak competitive performance, conditional statistics

[`artifacts/v7/analysis.json`](../../artifacts/v7/analysis.json) and
[`holdout/aggregates.json`](../../artifacts/v7/holdout/aggregates.json) support the
primary 16-seed reuse contrast: +0.12240 reward over the no-reuse growing learner
on the first 24 shared-novel examples, with paired interval [0.03158, 0.21321].
The first-eight contrast is exactly zero. The corresponding reward levels are
0.174479 for reuse, 0.052083 for no reuse, and 0.513021 for audited sparse
full-history learning. At the 4,096-SELECT budget, reuse's final macro reward
is 0.474365 versus 1.0 for each of the three fixed controls. The complete
competitive objective is not met. A point estimate above 0.05 and interval
lower bound above zero do not establish a 95% lower bound of 0.05.

Authentic report IDs, a supplied 84-monomial grammar, exact scalar supervision,
complete-table observations and stationary scopes remain strong assumptions.
Unchanged old-report policies and predictions establish structural retention
under authentic fixed dispatch; they do not demonstrate learned routing or
statistical pointwise retention. The later SQL language-model pilot must not
inherit these positive metrics as if it executed the same mechanism.

The handwritten statistical argument freezes candidate, incumbent, scope and
reward before collecting fresh paired differences D in [-1,1]. Its wealth is
`E_t = product(1 + D_i/2)` and comparison j uses alpha_j = alpha/[j(j+1)].
For **each null comparison**, the required conditional premise is
`E[D_t | all prior selection, training and audit information] <= 0`.
Nonnegative factors make the process a supermartingale; Ville's inequality
and the summable allocation bound the probability of any false admission by
alpha. Fresh independent draws from the same stationary scope distribution
supply the link to fixed-policy future mean return. Bounded samples, immutable
comparisons, genuine sampling freshness and permanent spending for abandoned
tests are required. Sample IDs and hashes alone do not establish those premises.
The alpha=0.05 allocation applies per gate/run, not to every arm/seed jointly.

The fixed bet has a consequential power defect. For D=+1 with probability .55
and -1 otherwise, the true mean is +0.1 but expected log growth is negative.
The square-root wealth is itself a supermartingale under that positive-mean
alternative, giving eventual acceptance probability at most sqrt(alpha_j),
below 0.159 for the first audit. Even unlimited samples do not repair this
particular test's poor power. With the actual 64-pair cap and constant difference,
the first comparison needs d approximately 0.118664 or larger to cross. These
are elementary analytical calculations in the original v7 manuscript, not
Lean-proved probability results or measured model gains.

The actual Lean bridge is deterministic. In
[`StatisticalBridge.lean`](../../formal/WitnessCL/StatisticalBridge.lean),
`promotion_chain_bound` proves
`initial_total <= final_total + sum(tolerances) + C*B*failed_promotions`.
`failed` means an actual population-value loss beyond tolerance, not an audit
rejection. `historical_version_bound` applies this to any historical suffix.
`historical_no_forgetting` requires zero actual failed promotions and zero
accumulated tolerance. Positive C is required to divide totals into uniform
population expectations. Average preservation permits context regression,
as `context_regression_counterexample` shows with [1,1] and [0,2]. Fixed
per-promotion tolerances also accumulate; 4 to 3 to 2 loses two with tolerance
one each. Lean does not establish the probability space, supermartingale,
sampling implementation, Ville's inequality, or the claimed confidence level.

## Wording to retire, rather than carry into the final paper

The original v1-v4 release records said Lean was unavailable. The repaired
accumulated declarations were first kernel-checked during v5 and are checked
again in v10. The consolidated paper should report the **current** verified
scope without claiming the original unsuccessful builds had passed.

No early result establishes native CL-Bench or AgentCL superiority. Symbolic
full-history planning is not LLM in-context learning. The v2 residual diagnostic
is not neural training; v3's tiny neural module study is not foundation-model
fine-tuning. Retention of a keyed immutable function is not retention under
learned or drifting routing. Primitive speed ratios are not end-to-end inference
speedups. Zero measured regression is not unconditional safety, and a positive
contrast against a weak control does not supersede the stronger negative
comparisons retained above.
