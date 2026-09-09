The 32-stream pilot estimates mechanism frequency, future-accuracy headroom and
retention variability for its **development generator**. The recommended default
for subsequent confirmation is fresh independent streams from that same
generator, with the learner and analysis frozen before confirmation. The final
choice follows the complete pilot. The older out-of-distribution confirmation
template is held: it has not been frozen or launched and needs separate
calibration before supporting an out-of-distribution claim.

The [pilot manifest](../../artifacts/campaign/pilot-dense-v2/manifest.json)
assigns all four existing development streams, 101100–101103, plus the 28 new
streams 101104–101131. The extension froze at
2026-09-09T22:19:33.638790+00:00. Its manifest records 29 preexisting episode
records when the amendment was made. These are all 32 assigned streams, including
negative results; no outcome-based exclusion, replacement, or favorable subset
is permitted. This is a disclosed extension of the original four-stream
development study, not a claim that all 32 were assigned before any observation.
The frozen generator and learner remain unchanged.

The following comparison is static source inspection. It is not a measured
ceiling, an empirical variance estimate, a mechanism event, or a confirmation
power calculation. The [calculator](../../artifacts/campaign/static-pilot-distribution.py)
verifies both studies' frozen source inventories, compares their inspected
generator/analysis/policy identities, and imports the frozen generator only to
inspect synthetic local fixtures. It makes no model calls and reads no episode
outcomes. Its [report](../../artifacts/campaign/static-pilot-distribution.json)
binds the manifest, freezes, calculator and relevant source hashes.

```bash
.venv/bin/python artifacts/campaign/static-pilot-distribution.py \
  > /tmp/static-pilot-distribution.json
cmp /tmp/static-pilot-distribution.json \
  artifacts/campaign/static-pilot-distribution.json
```

The operation mapping comes from
[campaign_env.py](../../src/witness_cl/campaign_env.py); the table gives counts
per stream. VARIANCE is population variance and MEAN_SQUARE is the mean of
squared values.

| Scheduled block | Cold qualification | Full development/pilot and legacy sizing | Held OOD confirmation template |
| --- | --- | --- | --- |
| Ordinary 0–7 | 8 SUM, initial binding | 8 SUM, initial binding | 8 SUM, initial binding |
| Ordinary 8–15 | 8 SUM, changed binding | 8 SUM, changed binding | 8 SUM, changed binding |
| Ordinary 16–23 | 8 MEAN, changed binding | 8 MEAN, changed binding | 8 MIN, changed binding |
| Final 0–7 | 8 MEAN, initial binding | 8 MEAN, initial binding | 8 MIN, initial binding |
| Final 8–15 | Absent | 8 MAX, changed binding | 8 MAX, changed binding |
| Final 16–23 | Absent | 8 VARIANCE, initial binding | 8 RANGE, initial binding |
| Final 24–31 | Absent | 8 MEAN_SQUARE, changed binding | 8 VARIANCE, changed binding |
| Old panels | Absent | 64 SUM before and 64 after, initial binding | 64 SUM before and 64 after, initial binding |

Qualification resets memory for every episode. Its perfect cold SUM/MEAN result
therefore establishes neither full future-panel competence nor stateful gain.
Full streams place the first old panel after ordinary episode 7 and the second
after episode 23. Both old panels use the same 64 fixtures and paired decoding
seeds; their memory checkpoints differ.

There is also a convention shift. `_convention` in
[sql_env_v8.py](../../src/witness_cl/sql_env_v8.py) chooses four Boolean settings
in the order `cents`, `null_is_zero`, `history`, `current_by_flag`. Development,
pilot, legacy sizing and diagnostic splits use the eight even-parity
combinations; the held confirmation template uses the eight odd-parity
combinations. Each individual setting takes both values in both classes, but
the joint combinations are disjoint. Diagnostics currently combine the OOD
operation set with development conventions. The drift condition complements
all four bits after the migration, preserving parity because there are four
bits; this does not make the convention supports identical across splits.

Changing only the final operation list would leave the ordinary MEAN-to-MIN
shift and convention shift unresolved. A new final panel evaluated from saved
development checkpoints would measure operation capability under those
development histories; it would not calibrate a complete OOD stream. If OOD
generalization is pursued later, prospectively assign new full bridge streams
with the target conventions, ordinary tasks and final tasks, mark those streams
as exposed development data, and retain separate untouched confirmation seeds.
Nothing in this note authorizes an additional collection or changes the pilot.

For the completed pilot, report each arm's full 32-question future accuracy and
its breakdown by operation and family, together with the complete audited
mechanism census even when zero. Report control headroom `1 − accuracy` and
paired delayed-minus-control differences. A five-point improvement is
arithmetically unavailable when the corresponding control accuracy exceeds
95%, even if delayed memory is perfect. That diagnostic applies to the pilot
distribution; it does not estimate the held template's ceiling.

For retention, keep the paired probe transitions. Let `B_ij` and `A_ij` be
before/after correctness for old probe `j` in stream `i`. Then
`d_ij = A_ij − B_ij` and `D_i = sum_j(d_ij) / 64`. Report each stream's
right-to-wrong and wrong-to-right counts, total discordance, and net `D_i`.
Balanced regressions and recoveries can produce a zero net change. Estimate
the across-stream sample SD from the 32 values `D_i`, with standard error
`SD(D) / sqrt(32)`. The 2,048 paired probes are nested measurements, not 2,048
independent stream replicates. This applies the paired-difference construction
at the declared replication level. [NIST paired observations](https://www.itl.nist.gov/div898/handbook/prc/section3/prc311.htm)

The existing `.10` SD floor is a protocol choice. In the frozen
[campaign_analysis.py](../../src/witness_cl/campaign_analysis.py), it appears in
four locations: `analyze` line 80, `size_study` line 103,
`joint_power_simulation` line 137 for simulated population SD, and line 157 for
each simulated test's estimated SD. The freeze also records `analysis.sd_floor`.
Lowering only a sizing input would leave the actual test unchanged. Any future
revision must consistently freeze the planning rule, actual test and joint
simulation before confirmation; the two-point margin and positive endpoint
thresholds remain unchanged.

An explicit candidate for that later decision is to estimate retention SD from
the independent pilot stream differences and use a one-sided uncertainty bound
for planning. Under the existing approximate-normal model, the 95% upper SD
bound is `U = S_D * sqrt(31 / chi2_quantile(.05, 31))`, approximately
`1.268 * S_D`. A matching future test could use
`max(confirmation sample SD, U)`. This is a proposed analysis revision, not the
currently frozen rule. Normal-based SD bounds are sensitive to nonnormality;
whole-stream bootstrap sensitivity analysis is useful when the pilot contains
enough variation. [NIST SD confidence limits](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/sdconfli.htm)

If all stream differences are identical, a degenerate bootstrap or zero normal
SD estimate does not establish zero population variance. Predefine the handling
of this case before confirmation, using an explicit conservative guard or a
bounded variance-sensitive interval and documenting its assumptions. Empirical
Bernstein bounds retain an additive uncertainty term when observed variance is
zero. [Maurer and Pontil, Theorem 4](https://www.cs.mcgill.ca/~colt2009/papers/012.pdf)
The pilot's finite 64-probe measurement noise is part of its observed stream
variance and should not be subtracted when confirmation uses the same panel
size. A forecast based on these measurements transfers most directly to fresh
streams with the same generator, panel design and frozen learner.
