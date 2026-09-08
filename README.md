# Witness-CL

**Evidence-preserving skill growth, local auditing, and retention under recurrence.**

Research prototype, version 0.2.0. **146 Python tests and 432 C++ cases pass.**
The nine-page [paper](paper/main.pdf), [mathematical notes](docs/v2/THEORY.md),
[claim boundaries](docs/v2/RESEARCH_STATUS.md), and [recorded results](artifacts/v2/RESULTS.md)
separate measured behavior from assumptions and hypotheses.

No native CL-Bench/AgentCL or language-model experiment was run. The 29 Lean
attempts are **not kernel-checked**. CUDA sources are **not compiled or timed**.
This is not a benchmark-win or unrestricted no-forgetting claim.

## What changed

The learner can grow its typed rule class, replay earlier evidence correctly,
recover after unannounced changes, and reuse preserved old rules. It also learns
schema-derived read-only aggregation programs. A separate integrated agent freezes
candidate changes and uses randomized, actually observed outcomes to audit them
before promotion. Fixed-feature online residual learning protects a specified
span exactly in real arithmetic. Shared relational aggregates and packed evidence
kernels target execution cost rather than expensive prompt accumulation.

On the new 20-seed arithmetic streams, hidden-change late reward rises from
14.49% for the original algorithm to 96.19%; class-misspecification recovery rises
from 10.06% to 100%. Relational recurrence reaches 97.45% late reward versus
63.59% for reset-only learning. These are symbolic mechanism tests, **not ICL
results**. The audited agent pays an additional learning cost, and rapid change,
noisy feedback, and unsupported operators remain published failure cases.

## Reproduce

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test,analysis]'
make test
make cpp-check
make refine       # Reruns all new experiments and replaces their recorded outputs.
make paper        # Uses recorded JSON; requires pdflatex and the packages in main.tex.
```

`make experiment` and `make audit-power` reproduce the original version's separate
experiments. `make formal` needs the pinned Lean toolchain. `make cuda-check` needs
a CUDA-capable SM90 machine, nvcc, and Compute Sanitizer. The latter two commands
were not successfully executed here. See [execution contracts](docs/v2/EXECUTION.md).

## Code map

| Location | Role |
|---|---|
| `src/witness_cl/adaptive.py`, `relational.py` | Replay-safe class growth, recurrence, public-schema plans, aggregate cube |
| `system.py`, `local_audit.py` | Integrated one-outcome learner; local and randomized admission |
| `tracking.py`, `protected.py` | Separate fixed-archive bandit and projected-training controls |
| `kernels/` | Executed C++ oracle; unexecuted CUDA filtering and consensus drafts |
| `formal/`, `docs/v2/` | Attempted Lean formalization; written proofs and explicit limits |
| `artifacts/v2/`, `experiments/` | 348,160 new raw episode records, seeded scripts, power and timing data |

The cube is an independently measured CPU primitive, not yet wired into the
online learner's reported timing. It is faster than the direct Python interpreter
in the recorded test, not a measured GPU or database-engine speedup. The neural,
soft-router, and multistep branches are not unified into a general LLM agent.

The original optional `experiments/llm_synthetic.py` runner is retained. It supports
an explicitly configured local chat-completions server; it is not a native
CL-Bench adapter, and no model-service call was executed. The original paper and
results remain under `paper/v1/` and `artifacts/synthetic/`.

## Attribution and safety

Prepared as an AI-assisted research draft for Samuel Mausberg. Author review,
independent proof checking, and external replication remain necessary. Algorithms
build on version-space elimination, program synthesis, fixed-share experts,
sequential inference, and orthogonal learning. [References](paper/references.bib)
credit those foundations; novelty of the combination is not established.

Only pure, read-only policies are used in the integrated experiments. Admission
is not a guarantee that experimental treatments cannot harm individual episodes.
Do not use the prototype to authorize irreversible actions. MIT license.
