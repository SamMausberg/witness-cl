# Witness-CL

**Continuation-aware online learning with explicit retention and exploration contracts.**

Version 0.3.0. [Paper](paper/main.pdf) · [Theory](docs/v3/THEORY.md) ·
[Results](artifacts/v3/RESULTS.md) · [Claim boundaries](docs/v3/RESEARCH_STATUS.md) ·
[Evaluation plan](docs/v3/EVALUATION.md)

**271 Python tests pass. 632 C++ cases plus an overflow check pass.**
The finite-world controller improves online and bounds exploration deficits under
explicit assumptions. On 17,920 new synthetic episodes it matches, but does not
beat, a strong full-history model-based baseline's late return. This baseline is
not an LLM or raw-history ICL. A separate online neural experiment measures zero
old-function drift with immutable modules, growing storage, and trusted scope IDs.

**No native CL-Bench, AgentCL, or LLM-service experiment was run. The 39 Lean
theorem attempts are not kernel-checked. CUDA drafts are not compiled or timed.**
No general no-forgetting solution, benchmark win, or established novelty is claimed.

## Reproduce

```bash
python -m pip install -e '.[test,analysis]'
make test
make cpp-check
make continuation-study
make neural-study
make continuation-diagnostics
make paper
```

`make formal` needs the pinned Lean toolchain. See [execution](docs/v3/EXECUTION.md).
The main paper uses professional two-column LaTeX with TikZ. Recorded data are
included; `make paper` does not rerun experiments. MIT licensed.

## Repository map

| Path | Purpose |
|---|---|
| `src/witness_cl/continuation.py` | Integrated finite-family learner, full-horizon checks, versioning, risk debits |
| `coupling.py`, `likelihood.py`, `versioned_training.py` | Separately tested simulator sharing, noisy evidence, learned-feature isolation |
| `kernels/`, `vector_contract.py` | Executed scalar/C++ references; uncompiled CUDA continuation draft |
| `formal/`, `docs/v3/` | 39 Lean attempts, written proofs, limitations and falsifiable next experiments |
| `artifacts/v3/`, `experiments/` | Raw controller episodes, per-seed results, test logs, negative results |

This extends the uploaded v0.2 history, including replay-safe skill growth,
recurrence, and local audits. Historical results and drafts remain in
`artifacts/v2/`, `paper/v2/`, and the earlier Git commits. They are not new v3 runs.
The noise, neural, and coupling branches are not yet one general language agent.

Prepared as an AI-assisted research draft for Samuel Mausberg. Classical policy
improvement, conservative exploration, sequential inference, and progressive
architectures are credited in [the bibliography](paper/references.bib). Review,
independent proof checking, and external replication remain necessary.
