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

Once collection terminates, these commands replay and report the saved data
without calling the model. Run them from the repository root in the locked
Python environment:

```bash
.venv/bin/python artifacts/campaign/fast-dense-v2-restart/sources/tools/campaign_fast.py audit \
  --out artifacts/campaign/fast-dense-v2-restart
.venv/bin/python artifacts/campaign/fast-dense-v2-restart/sources/tools/campaign_fast.py mechanism \
  --out artifacts/campaign/fast-dense-v2-restart
.venv/bin/python artifacts/campaign/fast-dense-v2-restart/sources/tools/campaign_fast.py report \
  --out artifacts/campaign/fast-dense-v2-restart
```

`audit.json` checks replay and exact receipt accounting. `audit-mechanism.json`
contains the full chronological and fixed-program intervention census.
`report.json` and `REPORT.md` distinguish completeness from scientific success;
the JSON retains all six stream/arm rows, paired old observations and final
operation breakdowns. Scripted software tests are excluded from empirical
publication. No agent deletion rerun, drift comparison, matched-extra-evidence
comparison or native model benchmark is implied by these artifacts.
