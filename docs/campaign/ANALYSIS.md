# Provisional analysis record; confirmation held

**Latest time-budget amendment:** the original pilot is paused at 161/17,664
episodes. The [separate two-stream diagnostic](TIME_BUDGET_AMENDMENT.md) has a
prospective 240-episode assignment and a fixed 2026-09-10 00:43 UTC reporting
deadline. It completed all 240 episodes; the [results](BOUNDED_RESULTS.md) show
a ceiling in all three arms, one saved-program mechanism event, and zero answer
flips in one actual deletion rerun. It cannot calibrate the original retention
variance or establish noninferiority.
The equations below and the 32-stream assignment remain uncompleted proposals.

**Earlier 2026-09-09 amendment:** the execution target was the complete
[32-stream pilot](../../artifacts/campaign/pilot-dense-v2/manifest.json), comprising
the four previously assigned streams and 28 newly frozen streams. Report its full
mechanism census, future-operation ceiling rates, paired retention variance and
full costs before sizing or auxiliary collection. The two-point margin remains
unchanged; the .10 retention floor below is a sensitivity assumption under review.
No 419-stream confirmation has been authorized for automatic execution.

The equations and commands below preserve the earlier proposal and implemented
analysis for review. They are not the current launch instructions. The floor
appears in inference, sizing and joint simulation; any replacement must revise
and freeze all three consistently. A confirmation population different from the
pilot's operations or convention combinations requires matching calibration.
See the [amended plan](PLAN.md). Do not infer independent observations from rows.

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

The original pilot supervisor command below is paused; do not start another
supervisor or resume it during the separate time-budget diagnostic:

```bash
.venv/bin/python artifacts/campaign/pilot-dense-v2/report-sources/tools/campaign_supervisor.py \
  --out artifacts/campaign/pilot-dense-v2/supervisor \
  --plan artifacts/campaign/pilot-dense-v2/collection-plan.json
```

It adopts the already running four-stream block, then executes the copied
28-stream runner, complete replay audit and mechanism census. The final offline
report combines exactly those 32 independently assigned streams. The supervisor
binds an explicit source closure and preserves a durable handoff receipt; later
commands do not repeat completed stages. A failed command stops without an
automatic retry or replacement stream.

Each study checks its copied source, environment and serving runtime, journals
calls before sending them and replays completed records on recovery. There is no
confirmation or auxiliary command in the pilot collection plan. The old
`campaign_sequence --through diagnostics` proposal is held pending the complete
pilot report and revised prospective sizing. Its previously frozen sources remain
available as provenance; they are not the current collection instruction.
