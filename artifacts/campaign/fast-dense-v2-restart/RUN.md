# Separate two-stream descriptive diagnostic

The complete assignment is 240 episodes: two independent streams, three arms,
24 learning episodes and 16 probes per stream and arm. The seeds are 101302 and
101303. `freeze.json`, its digest and `schedule.json` were written before the
first call. The exact executed code is under `sources/`.

This study follows the explicit two-hour amendment in
`docs/campaign/TIME_BUDGET_AMENDMENT.md`. Its fixed last-call-start time is
2026-09-10 00:37 UTC; the reporting deadline is 00:43 UTC. It does not complete
the original 32-stream pilot or establish any confirmatory endpoint. An
incomplete assignment keeps its full denominator and cannot supply comparative
outcome estimates.

`launch.json` records the detached runner. The original reduced-study freeze
in `../fast-dense-v2/` made no calls: its launch rejected a missing serving
process. That freeze and failure log remain intact. This study binds the
replacement process, with identical model bytes, backend and runtime settings,
in `../runtime-dense-restart/`.

Collection completed all 240 episodes and passed independent prompt/SQL replay.
The total is 353 calls and 4,251,272 measured tokens, with no unknown usage.
Every arm scored 80/80 overall and 16/16 final. One qualifying fixed-program
chain was found. The separately frozen sibling deletion study completed its
one eligible rerun: the answer remained correct using direct SQL (zero flips).
See the [bounded results](../../../docs/campaign/BOUNDED_RESULTS.md).

The original frozen `report` command failed because SQLGlot traversed the same
lineage graph in different node/child orders across processes. The original
failure is preserved in `report.log`; no frozen code or raw records were changed.
A separate correction at `../fast-dense-v2-restart-offline-report-v1/` sorts only
lineage node/child presentation (retaining expressions, edges and multiplicity)
and excludes offline timing fields already excluded by the original reporter.
Its manifest binds the unchanged inputs, correction source and report outputs.
Eight regression tests cover cross-process traversal and rejection of substantive
mutations. The corrected report replays all 240 records without model calls.

To reproduce into a fresh scratch output without overwriting archived audits,
run from the repository root in the locked Python environment:

```bash
witness_report_tmp="$(mktemp -d)"
.venv/bin/python artifacts/campaign/fast-dense-v2-restart-offline-report-v1/campaign_fast_report.py \
  --source-study artifacts/campaign/fast-dense-v2-restart \
  --out "$witness_report_tmp/report"
```

`audit.json` records the original full prompt/SQL replay and exact costs;
`audit-mechanism.json` contains the full chronological and fixed-program census.
The corrected `report.json` retains all six stream/arm rows, paired old outcomes,
final operation breakdowns and lifecycle counts. The actual agent deletion
result and independent replay are in `../fast-dense-v2-restart-deletion/`.
Drift, matched-extra-evidence and native model measurements remain uncollected.
