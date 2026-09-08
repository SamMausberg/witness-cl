# Witness-CL

**Evidence-preserving online learning, with checked assumptions and falsifiable experiments.**

Version 0.5.0 · [Paper](paper/main.pdf) · [Research status](docs/v5/RESEARCH_STATUS.md) · [Results](docs/v5/EXPERIMENT.md) · [Next steps](docs/v5/NEXT_STEPS.md)

This private research repository continues `Witness_CL_v4.bundle`, preserving its history, release tags, original results, and archived paper. It learns finite hidden models from executed traces, trains an online proposal ranker, and checks immutable programs before changing protected incumbents. The contract requires a valid finite class, deterministic stationary dynamics, public rewards, and genuine resets.

**The general continual-learning problem remains open.** The new regret-directed probe rule loses to v4 and a strong symbolic full-history planner. A post-hoc weak-dominance repair fixes a diagnosed plateau but still trails both controls. Two individually uninformative free probes can be useful together; that counterexample motivates bounded adaptive probe planning.

**401 standard Python tests pass; eight additional native checks pass in the optional runtime.**

**51 Lean 4.19.0 theorem statements are checked**, with no custom axioms or proof placeholders. These are conditional abstract lemmas, not a verification of Python, neural training, or a deployed language agent. See the [formal audit](docs/v5/FORMAL.md).

The new CPU studies preserve **72,192 episode records**, including **54,144 audited guarded prefixes** within B16. Actual local-model pilots made **120 calls** across five worlds. Their exploratory results and all costs are recorded; they are not native CL-Bench or AgentCL performance. The full-history symbolic planner is not LLM ICL.

## Reproduce

```bash
python3 -m pip install -e '.[test,analysis]'
make test
make cpp-check
make formal
make paper
PYTHONPATH=src python3 experiments/audit_v5.py
```

`make formal` runs the source-hashed theorem/axiom audit with pinned Lean 4.19.0. It requires an installed toolchain; `LAKE` can specify its launcher. `make paper` requires pdfLaTeX and the standard packages imported by `paper/main.tex`. It regenerates tables and the scientific plot from recorded data, not new outcomes. Native integration has separate pinned dependencies and tests; see [its README](integrations/clbench/README.md).

To run a new CPU study without replacing recorded evidence, use a new output directory:

```bash
PYTHONPATH=src python3 experiments/latent_v5.py --seed-offset 50000 --seeds 20 --out artifacts/new-development-run
```

A fresh seed from the already exhaustively studied 256-table class is development data, not new-domain validation. Local-model reproduction requires the matching served model; the driver refuses to overwrite outputs and preserves failures. No model weights or credentials are bundled.

## Repository map

| Path | Purpose |
|---|---|
| `src/witness_cl/latent.py`, `latent_agent.py` | Preserved exact finite learner, checker, online ranker and budget ledger |
| `src/witness_cl/latent_v5*.py` | Frozen rejected probe rule and separate post-hoc repair |
| `experiments/`, `tests/` | Executed studies, independent replay audits, failure/cap/retention tests |
| `formal/` | 51 checked abstract theorems and a complete axiom audit |
| `integrations/clbench/` | Pinned native interface and feedback/usage boundary work |
| `artifacts/v5/` | Raw data, source hashes, actual inference outputs, logs and provenance |
| `docs/v5/` | Source-grounded literature, experiments, claim boundaries and continuation plan |
| `paper/` | Current 11-page LaTeX/TikZ paper, PDF, figure sources and data-backed tables |

The primary new held-out difference is **−0.09458 reward/episode versus v4**, paired 95% interval **[−0.16915, −0.02001]**, at about **1.90×** measured mechanics time. This is a rejected hypothesis. The original v4 negative comparison and every v5 outcome remain visible.

MIT software license retained. Prepared for Samuel Mausberg as an AI-assisted research draft requiring author review and independent replication. No public benchmark win, global novelty, bounded lifelong memory, or universal no-forgetting claim is made.
