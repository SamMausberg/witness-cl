# Witness-CL

**Evidence-preserving learning from executed episodes, with explicit assumptions and falsifiable results.**

Version 0.6.0 · [Paper](paper/main.pdf) · [Results](docs/v6/RESULTS.md) · [Formal bridge](docs/v6/FORMAL.md) · [Next study](docs/v6/NEXT_STEPS.md)

This private research repository continues `Witness_CL_v4.bundle`, preserving its history, release tags, original results and archived papers. It learns compatible finite hidden models from executed traces and checks immutable programs before changing protected incumbents. The contract requires a valid finite class, stationary deterministic dynamics, public reward functions and genuine resets.

**The general continual-learning problem remains open.** The new bounded two-probe selector gains **0.39375 reward per episode** over a cheap informative zero-loss rule on the frozen 40-stream holdout (paired 95% interval **[0.15845, 0.62905]**). It still loses **0.19479** to bounded optimism and uses **8.88×** the cheap rule's measured planning time. Shared budget ceilings do not equal matched actual risk or computation.

All three new selectors repair the two-bit complementary-probe example at B0. Three-bit parity at B0 already defeats depth two, while the cheap rule succeeds. The mechanism is useful evidence about a failure, not a general solution or a novelty claim for belief-state planning.

**503 standard Python tests pass**, with eight optional native-environment tests skipped in the ordinary runtime. The C++ reference/sanitizer checks pass. **Lean 4.19.0 checks 63 statements**, including an executable transducer/history-filter bridge, with no custom axioms or placeholders. Finite differential tests compare 262,144 Python/Lean filter membership decisions; they do not prove the optimized Python implementation generally.

The v6 study records **8,640 benchmark episodes** plus 180 mechanism-control episodes. Independent saved-data replay checks **7,680 final-protocol episodes and 6,144 guarded prefixes**, with zero detected contract violations. The earlier development run remains preserved separately. All ranker weights are frozen in this phase; there are no new LLM calls, deployments or paid compute. The requested Codex automation was removed and no replacement was created. [Scope](docs/v6/RESEARCH_BOUNDARIES.md)

## Reproduce

```bash
python3 -m pip install -e '.[test,analysis]'
make formal
make test
make cpp-check
make paper
PYTHONPATH=src python3 experiments/audit_v6.py \
  artifacts/v6/development-corrected artifacts/v6/holdout \
  artifacts/v6/work-25000 artifacts/v6/work-250000 \
  --out /tmp/witness-v6-audit.json
```

`make formal` builds the source-hashed theorem/axiom audit and executable fixture using pinned Lean 4.19.0. `LAKE` can specify its launcher. `make paper` requires pdfLaTeX and regenerates tables/plots from recorded data. Native integration has its own pinned dependencies and CI job; see [its README](integrations/clbench/README.md).

For a fresh development run, use an unused output directory:

```bash
PYTHONPATH=src python3 experiments/probe_v6.py \
  --seed-offset 70000 --seeds 8 --out artifacts/new-development-run
```

Completed experiment directories cannot be overwritten. Holdout execution additionally checks an explicit source/configuration freeze. New seeds from the same finite class do not establish new-domain generalization. Planning deadlines are cooperative Python limits, not operating-system isolation or hard real-time guarantees.

## Repository map

| Path | Purpose |
|---|---|
| `src/witness_cl/latent.py`, `latent_agent.py` | Exact finite learner, checker, optional online ranker and nonrefundable ledger |
| `src/witness_cl/probe_v6.py` | Bounded depth-two, free-information and optimistic selectors |
| `experiments/probe_v6.py`, `audit_v6.py` | Frozen experiment and independent raw-data replay |
| `tests/` | Mechanism, failure/cap, semantics and deliberate-tampering checks |
| `formal/` | 63 checked statements and executable interpreter/filter fixtures |
| `artifacts/v6/` | Raw data, source/configuration freeze, proofs, costs and validation logs |
| `docs/v6/` | Algorithms, primary-source antecedents, results and precise claim boundaries |
| `paper/` | Current LaTeX/TikZ paper, PDF, figures and generated tables |
| `paper/v5/`, `artifacts/v5/`, `docs/v5/` | Preserved prior paper, rejected hypotheses and actual local-inference pilots |

The prior v5 probe rule and its post-hoc repair remain below strong controls. Its 72,192 CPU episodes and 120 actual local-model calls are preserved; they are not relabeled as v6 results or native CL-Bench/AgentCL performance. No public benchmark win, universal no-forgetting, bounded lifelong memory or general alignment guarantee is claimed.

MIT software license retained. AI-assisted research draft prepared for Samuel Mausberg; author review and independent replication remain necessary.
