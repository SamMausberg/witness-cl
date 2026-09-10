# Contributing

Use Python 3.11 or newer and the locked dependencies in `uv.lock`. The development
environment is installed with `uv sync --locked --extra test --extra analysis --extra dev`.
Use a full Git clone: historical regression checks require the recorded source
commits, including when current learner code differs from an earlier experiment.
Run `make test PYTHON=.venv/bin/python` and `make lint` for Python changes,
`make formal PYTHON=.venv/bin/python` for proof changes, and `make paper` for the
manuscript. The native benchmark interface has a separate Python 3.13 environment.

Keep data, interpretation and conjecture distinct. A change to a solver, prompt,
memory, budget, environment or protocol requires a new source freeze and fresh
development output directory. Preserve every attempted run, including failed
and interrupted ones. Never adjust historical hashes to make changed code appear
to have generated old evidence. Use exact-revision replay for archived studies.

Tests must mark scripted clients as test doubles. Their perfect scores verify
execution paths, not model performance. Benchmark scores require the native
benchmark, qualified controls and complete cost receipts. Report prompt tokens,
completion tokens, calls, tool queries and retained state separately. An admission
or unchanged stored program is not proof of transfer or behavioral retention.

The current experiment entrypoint is `experiments/delayed_sql.py`, managed by
`tools/campaign.py`; `experiments/stateful_sql.py` and numbered
modules remain as implementation dependencies and historical regression fixtures.
Avoid changing them merely to restyle archived code. The current manuscript lives
in `paper/main.tex`, and its factual claims should link to artifacts or primary
sources. The companion historical report lives in `paper/technical_report.tex`
and builds with `make technical-report`. Generated tables must come from
validated measurements.
