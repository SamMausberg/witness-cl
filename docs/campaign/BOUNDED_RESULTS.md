# Completed two-stream diagnostic

The separately frozen two-hour study completed all 240 assigned episodes on
2026-09-10. It is a descriptive diagnostic accompanying a Stage 1 registered-report
manuscript, not the original 32-stream pilot or a confirmatory experiment. Its
two independent stream seeds, 101302 and 101303, were frozen before generation.
All three arms learned independently on each stream. Probe checkpoints did not
learn. The [prospective amendment](TIME_BUDGET_AMENDMENT.md) specifies the complete
assignment and fixed deadline.

| Arm | Learning correct | Old before | Old after | Final correct | Model calls | Total tokens |
|---|---:|---:|---:|---:|---:|---:|
| Full history | 48/48 | 8/8 | 8/8 | 16/16 | 85 | 2,278,924 |
| Online ACE | 48/48 | 8/8 | 8/8 | 16/16 | 180 | 625,254 |
| Delayed memory | 48/48 | 8/8 | 8/8 | 16/16 | 88 | 1,347,094 |

The full assignment used 353 calls and 4,251,272 measured tokens, including
acquisition, reflection and checks, with zero unknown-usage calls. Delayed memory
used 40.9% fewer tokens than full history but 115.4% more than ACE. Every arm
answered every question correctly, including the final mean, maximum, population
variance and mean-square questions. There is no observed accuracy advantage.
These are aggregate descriptive comparisons over two streams, not significance
tests or population estimates. Four paired old probes per stream cannot calibrate
the original 64-instance panel or establish two-point noninferiority.

## Mechanism and actual deletion

The complete replay census found **one qualifying saved-program event** in the
two-stream assignment. The delayed arms recorded 36 own-source admissions,
12 later corroborations, 12 relations eligible and retrieved at least once,
three executed relations, and four evictions. Seed 101302 contributed zero
qualifying events; seed 101303 contributed one. In seed 101303, ordinary episode 3 supplied a SUM source
query; the relation was corroborated with a changed binding at ordinary episode
11, then composed with AVG on fresh rows at final episode 3. The archived event
contains admission, provenance, bindings, lineage, execution and SQL intervention
receipts. Emptying that relation makes the saved outer program wrong.

The [prospective deletion protocol](FAST_DELETION_PLAN.md) selected every eligible
event before any rerun: one case. Removing the relation while retaining the
original direct-query evidence caused **0/1 answers to flip to wrong**. The agent
used direct SQL and returned the correct answer, 322.67857142857144. This actual
rerun cost one additional call and 18,777 tokens, with no unknown usage. It did
not update the original campaign. Fixed-program dependence therefore did not
translate into an observed solver accuracy dependence in this case.

## Receipts and limits

The [source study](../../artifacts/campaign/fast-dense-v2-restart/summary.json),
[complete replay](../../artifacts/campaign/fast-dense-v2-restart/audit.json),
[full mechanism census](../../artifacts/campaign/fast-dense-v2-restart/audit-mechanism.json),
[deletion result](../../artifacts/campaign/fast-dense-v2-restart-deletion/summary.json)
and [deletion audit](../../artifacts/campaign/fast-dense-v2-restart-deletion/audit.json)
retain all records and exact costs. Replay makes no model calls. The
[reproduction instructions](../../artifacts/campaign/fast-dense-v2-restart/RUN.md)
also document the separately bound offline report correction for unordered
SQL-lineage traversal; the frozen generation sources and data are unchanged.

The original pilot remains incomplete at 161/17,664 episodes. An earlier reduced
freeze made zero calls because the serving process had disappeared; its failure
and the identical-runtime restart are retained. No prefix is substituted for a
complete outcome. The restarted model server and obsolete paused jobs were
stopped after collection; [cleanup](../../artifacts/campaign/time-budget-cleanup.json)
records verified process identities.

Matched extra direct queries, drift robustness and native CL-Bench model results
remain unmeasured. The five confirmatory endpoints remain unestablished. This
diagnostic supplies evidence against proceeding with the current ceiling-limited
accuracy comparison, and it exposes the cost of the checked library relative to
ACE. A revised task distribution and feasible retention calibration need a new
prospective protocol before further collection.
