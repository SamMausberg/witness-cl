# Witness-CL

**Version0.8 implementation checkpoint:** a local SQL abstraction-discovery agent, six legal-history/memory controls, charged reconstruction checks, fresh old-task panels, and89 Lean statements are implemented. The development cost pilot has not yet run. The research claim is unestablished. See the [v8 protocol](docs/v8/EVALUATION.md), [compiler proof boundary](docs/v8/FORMAL.md), and [composition audit](docs/v8/COMPOSITION_AUDIT.md). The v7 study below and its [archived paper](paper/v7/main.pdf) remain unchanged.

**Online learning from executed experience, with explicit retention assumptions and falsifiable results.**

Version 0.7.0 · [Paper](paper/main.pdf) · [Results](docs/v7/RESULTS.md) · [Protocol](docs/v7/EVALUATION.md) · [Formal bridge](docs/v7/FORMAL.md) · [Next experiment](docs/v7/NEXT_STEP.md)

This private research repository continues `Witness_CL_v4.bundle`, preserving its Git history, release tags, original results and archived papers. Version 7 learns small numerical predictors from its own ordinary SQLite observations and subsequent scalar feedback. It selects reusable features from a supplied 84-monomial grammar, then tests frozen changes on fresh paired instances. No list of possible hidden worlds is given.

**The general continual-learning problem remains open.** On 16 untouched streams, audited feature reuse changes shared-novel reward by **+0.12240** relative to no reuse (nominal paired 95% Student interval **[0.03158, 0.21321]**). The predeclared transfer target is **met**. At the common 4096-SELECT ceiling, its final-panel score is **47.44%**, versus **100.00%** for ungated sparse full-history learning and **100.00%** for full ridge. The requirement to beat every fixed simple control is **not met**. SELECT matching is not equal CPU time or equal all-resource computation. [Interpretation and failure mechanism](docs/v7/INTERPRETATION.md)

The new mechanism removes hidden-world enumeration from this experiment, but gives the learner complete small-table observations, a fixed feature grammar, exact scalar supervision and authentic report IDs. Reuse changes candidate search order. It does not learn task identity, synthesize arbitrary SQL or demonstrate native LLM benchmark superiority. Other reports retain identical installed policies during novel learning; that is structural retention under fixed routing.

**656 standard Python tests pass**, with eight optional native-environment tests skipped in the ordinary runtime. The C++ reference/sanitizer checks pass. **Lean 4.19.0 checks 77 statements**, including 14 new finite-population promotion-accounting results; no custom source axioms, placeholders or unexpected dependencies appear. Its probability argument is **not Lean proved**. Independent finite fixtures check 8,748 historical bounds, and saved-data replay verifies the actual experiment's predictions, journals, policy transitions and query accounting.

A separate power counterexample matters: the fixed half-bet can have eventual admission probability below .159 for a policy with positive .1 mean gain, even with unlimited samples. Correct false-acceptance control alone does not make useful learning affordable. [Gate and counterexample](docs/v7/GATE.md)

The holdout records **78,081 ordinary episodes**, **61,790 audit pairs**, and **61,440 panel contexts**. All 192 arm/runs passed independent replay. Four development streams remain separate. Small scalar weights are fitted online; this phase uses no new LLM calls, deployment or paid compute. The requested Codex background automation remains removed. [Execution boundaries](docs/v7/RESEARCH_BOUNDARIES.md)

## Reproduce

```bash
python3 -m pip install -e '.[test,analysis]'
make formal
make test
make cpp-check
PYTHONPATH=src python3 experiments/audit_relational_v7.py \
  artifacts/v7/holdout --freeze artifacts/v7/freeze.json \
  --out artifacts/v7/holdout-replay.json
make paper
```

The paper analysis requires a passing independent replay tied to the exact raw files, manifest, freeze and current frozen source. It rejects partial runs and missing evaluation panels. `make formal` uses pinned Lean 4.19.0; `LAKE` may specify its launcher. `make paper` needs pdfLaTeX and regenerates statistics and figures from saved results. Native integration has separate pinned dependencies and a CI job; see [its README](integrations/clbench/README.md).

For a new development reproduction, choose an unused directory:

```bash
make relational-development V7_OUT=artifacts/v7/new-development
```

The evaluation freeze is committed before the untouched run. Replaying that exact frozen configuration into an unused directory is supported:

```bash
make relational-heldout V7_OUT=artifacts/v7/new-holdout
```

Completed experiment directories cannot be overwritten. Audit that new directory before analysis. Changing frozen inputs requires a new study and a new source/protocol record; it cannot silently update this evidence. Dependency versions are recorded in [environment.json](artifacts/v7/environment.json).

Each ordinary instance costs three post-setup SELECTs and each pair costs five, including authoritative scoring. The 4096-SELECT companion reserves 768 for the final panel; controls spend saved audit queries on more ordinary feedback. Setup SQL is outside this named budget, with setup time reported separately. Per-run timing excludes initial harness construction and final artifact export; whole-grid elapsed time includes that surrounding work. Numeric and serialized payload sizes do not measure process RAM.

## Repository map

| Path | Purpose |
|---|---|
| `src/witness_cl/relational_v7.py` | Read-only SQLite measurements, bounded online fitting and feature-bank reuse |
| `src/witness_cl/statistical_gate_v7.py` | Fresh paired betting tests, immutable identities and permanent error spending |
| `experiments/relational_v7.py` | Frozen six-arm matched-example and SELECT-budget protocols |
| `experiments/audit_relational_v7.py` | Independent standard-library replay, including own SQL and policy evaluation |
| `tools/freeze_v7.py`, `tools/v7_results.py` | Development-gated source freeze and stream-level analysis |
| `formal/` | 77 checked statements and executable finite fixtures |
| `artifacts/v7/`, `docs/v7/` | Raw data, freeze, replay receipts, costs, validation and claim boundaries |
| `paper/` | Current professional LaTeX/TikZ paper, PDF and generated figures |
| `paper/v6/`, `artifacts/v6/`, `docs/v6/` | Preserved earlier planning experiment and negative comparisons |

Earlier versions' local-model pilots and benchmark integrations remain archived; they are not relabeled as new native CL-Bench or AgentCL performance. The next proposed test learns schema facts and query fragments under each benchmark's permitted feedback rules. Gold-guided admission would be an augmented-feedback track, not native AgentCL memory construction.

MIT software license retained. AI-assisted research draft for Samuel Mausberg; author review and independent replication remain necessary.
