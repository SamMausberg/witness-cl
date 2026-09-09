# Prespecified analysis and stage execution

The independent replication unit is one newly generated stream. Questions,
old-panel repetitions and model calls within it are not independent samples.
The three main agents start empty and learn independently on the same stream.
Frozen panels clone the appropriate checkpoint and cannot update it. Before and
after old panels use the same 64 fixtures and paired decoding seeds.

For each stream let D denote delayed memory and C a control (full history or
official ACE). The five contrasts are future accuracy D−C for each control,
0.8×total_tokens(C)−total_tokens(D) for each control, and delayed old_after minus
old_before accuracy. Total tokens include all scheduled phases, learning calls,
reflection, failed calls with known usage and model-visible check observations.
SQL calls, retained bytes and physical time are also reported separately.

Each endpoint uses a one-sided paired-stream t lower bound at alpha .01.
Accuracy bounds use max(observed paired SD, .10). Token contrasts use
max(observed paired SD, .10×mean control tokens). The first four lower bounds
must exceed zero; the retention bound must exceed −.02. All five must pass for
the full headline. This is conservative familywise level .05 inference under
the stated normal/large-sample approximation, not a universal guarantee. A
constant observed retention difference does not produce a zero-width interval.

The sizing study contains exactly 32 prospectively assigned streams. Planning
slack relative to the null is [.05, .05, .10, .10, .02], with token contrasts
normalized by the corresponding control mean. Use the observed normalized
paired SD or .10, whichever is larger. Choose at least 48 streams and increase
N until noncentral-t power is at least .96 for every endpoint. Then simulate
100,000 joint trials (seed 271828), using pilot correlations, these conservative
marginal SDs, and the actual five-test rule. The one-sided 95% binomial Monte
Carlo lower bound on joint success must exceed .80. Otherwise increase N by
ceil(N/20) and repeat; never reduce the analytical N. Preserve every simulation
attempt. These are forecasts under a multivariate normal planning model.

The stage registry is `configs/campaign_sequence.json`. Both qualification
schedules freeze before either begins. Every qualification cell completes even
if an earlier accuracy threshold fails. Development and sizing require complete
successful qualification. Before sizing, development must contain at least five
real audited delayed mechanism events across three distinct streams. Confirmation
additionally binds the complete sizing, power and development receipts and
freezes exactly the assigned N before generation. Its seeds are disjoint from
every observed prerequisite. It completes all assigned streams regardless of
interim answers. Incomplete panels, uncertain calls, source changes or unknown
token usage prevent the complete positive claim; they are never filled by a
replacement seed or a fabricated failure score.

Stable/drift diagnostics pair 64 fresh streams with the same physical names,
row-generation seeds and arms; the migration changes documented conventions.
Report each arm's future-accuracy change (drift minus stable) and the
delayed-minus-control difference of those changes. Report negative, zero and
positive effects. Nonreuse diagnostics contain 32 fresh streams and report
delayed-minus-control accuracy. These comparisons use descriptive two-sided
95% paired-stream t intervals without multiplicity adjustment and are explicitly
separate from the five primary tests. They run even after a negative main result.
Native five-permutation results describe the original fixed databases and do
not supply independent new-database replication.

The durable launcher is:

```bash
.venv/bin/python tools/campaign_sequence.py \
  --out artifacts/campaign/dense-v2 \
  --plan configs/campaign_sequence_dense_v2.json \
  --runtime-config configs/campaign_runtime_dense.json \
  --runtime-receipt artifacts/campaign/runtime-dense/server.json \
  --key-file /home/ubuntu/.local/share/witness-cl/campaign-dense/runtime/server.key \
  --through diagnostics
```

Each study executes its own copied sources, checks the environment and serving
runtime, journals calls before sending them, and independently replays completed
records on resume. The launcher writes stage logs and `sequence-status.json`.
Restarting the same command resumes the same schedule. Unknown invocations stop
without silent retries. Native, matched-evidence and relation-deletion runs have
separate launchers and receipts; the main stage launcher does not claim they ran.
