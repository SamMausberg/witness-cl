# Witness-CL

**Learning latent continuations without trusting the proposer.**

Version 0.4.0. [Paper](paper/main.pdf) · [Results](artifacts/v4/RESULTS.md) ·
[Theory](docs/v4/THEORY.md) · [Claim boundaries](docs/v4/RESEARCH_STATUS.md) ·
[Evaluation plan](docs/v4/EVALUATION.md)

Learns compatible hidden-state models from executed traces, checks immutable
programs against a retained incumbent, and charges informative probes before
execution. Neural proposals train online but cannot bypass the checker. The
contract requires a valid finite state bound, stationary deterministic dynamics,
public rewards and true resets. No world table or hidden state is supplied.

**355 Python tests pass. 400 new and 632 legacy C++ cases pass, plus range checks.**
In 38,400 fresh-seed synthetic episodes, the method ties a strong full-history
planner's late return but has lower mean return. Informative probes improve the
controller's own ablation. This planner is not an LLM ICL baseline.

**No native CL-Bench, AgentCL, or real-model experiment ran. All 50 Lean theorem
declarations remain uncompiled attempts. No new GPU kernel or general
no-forgetting result is claimed.**

## Reproduce

```bash
python -m pip install -e '.[test,analysis]'
make test
make cpp-check
make latent-study
make latent-heldout
make latent-diagnostics
make holdout-audit
make paper
```

A small execution example is `PYTHONPATH=src python examples/latent_demo.py`.
`make formal` needs the pinned Lean toolchain. Paper generation needs pdfLaTeX,
not BibTeX; a strict renderer builds references from the included `.bib` file.
See [execution](docs/v4/EXECUTION.md) for actual run boundaries and the optional
unexecuted local-model driver.

## Repository map

| Path | Role |
|---|---|
| `src/witness_cl/latent.py` | Exact latent cover, paired bounds, residual DAG IDs, observable probe outcomes |
| `src/witness_cl/latent_agent.py` | Online proposer, immutable tickets, incumbents, risk ledger, capacity eras |
| `src/witness_cl/latent_proposals.py` | Bounded typed JSON candidates, no executable-code ingestion |
| `experiments/latent_*.py` | Reproducible mechanism study, diagnostics, optional local-model protocol |
| `tests/test_v4_*.py`, `kernels/latent_reference.cpp` | Exhaustive-oracle tests and independent numeric reference |
| `formal/WitnessCL/Latent.lean`, `docs/v4/` | Proof attempts, written arguments, failure cases and falsification plan |
| `artifacts/v4/`, `paper/` | Raw data, held-out parity audit, logs, paper PDF and LaTeX/TikZ sources |

The uploaded v3 Git history is retained. Its draft is archived in `paper/v3/`;
historical results remain in `artifacts/v3/` and earlier directories. The noise,
progressive-module and CUDA branches are not an integrated v4 language agent.
This is a local research repository, not a remotely published GitHub project.

MIT licensed. Prepared as an AI-assisted draft for Samuel Mausberg. Predictive
state representations, dynamic shielding, conservative exploration, DeepSPI,
evolving memory/harnesses, and versioned skill libraries are credited in the
[primary-source bibliography](paper/references.bib). Novelty and native benchmark
superiority remain unestablished.
