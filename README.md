# Witness-CL

**The requested online-abstraction claim is not established.** Version 0.8 implements an agent that can propose executable SQL relations from its own successful experience, but its frozen model pilot failed the prerequisite competence test: all six arms scored **0/8 on warm questions**, and neither fragment arm admitted or reused an abstraction.

Version 0.8.0 · [Paper](paper/main.pdf) · [Results](docs/v8/RESULTS.md) · [Frozen protocol](docs/v8/EVALUATION.md) · [Compiler proof boundary](docs/v8/FORMAL.md)

The complete development pilot contains **288 arm-episodes**, **621 real local-model calls**, **1,138,451 tokens**, and **307 SELECT attempts**, completing in **690.13 seconds**. Independent replay passes for every record. Only **14 answers are correct, all zero**; all old-task panels score **0/8 before and after**. Zero observed regression here does not establish preservation of a useful capability. The full-history and evolving-insight implementations did not qualify as competent controls. There is no strong-baseline superiority, heldout result or native benchmark performance claim.

The model is official Qwen3-4B Q8_0 on an authenticated local llama.cpp server, with pinned weights, source and settings. The failure belongs to this model/interface configuration; it does not establish that stronger models or revised shared solving instructions would fail. The server has been stopped. [Model provenance](artifacts/v8/model-provenance.json) · [Runtime cleanup](artifacts/v8/runtime-cleanup.json)

The implementation supplies natural-language questions, opaque schemas and a queryable documentation catalog. The learner receives no task IDs, gold answers or enumerated semantic feature library. After a correct ordinary episode, it may propose a new parameterized relation and an outer SELECT that reconstructs its own observed scalar answer. The check must execute within the same eight-SELECT allowance before admission. Later content retrieval supports checked use or composition with a new outer query. A constant-answer reconstruction is insufficient evidence of transfer. [Abstraction review](docs/v8/PILOT_ABSTRACTION_REVIEW.md)

**1,063 Python tests pass**, with eight optional skips; C++ reference and sanitizer checks pass. [Validation ledger](artifacts/v8/validation.json)

**Lean 4.19.0 checks 89 statements**, including 12 new typed-fragment statements. These establish exact prepared-request compilation, binding and composition properties, plus explicitly modeled conditional identities and counterexamples. They do not prove that the runtime discovers abstractions, solves new tasks, saves interaction, or retains behavior. Runtime guard rejection returns feedback and consumes budget, so the abstract answer-level fallback identity is not an unconditional runtime retention guarantee. [Formal audit](artifacts/v8/formal-audit.json)

## Reproduce saved-data checks

```bash
python3 -m pip install -e '.[test,analysis]'
make test
make formal
make cpp-check
PYTHONPATH=src python3 experiments/audit_sql_abstractions_v8.py \
  artifacts/v8/development --freeze artifacts/v8/prepilot-freeze.json \
  --output artifacts/v8/development-replay.json
make paper
```

The saved-data audit invokes no model. It independently replays actual SQL and reconstructs prompts, provenance, memory, phase schedules, usage and costs. It shares compiler/admission/memory definitions, and it does not cryptographically authenticate original inference. Paper generation rejects stale source, data or replay receipts, incomplete grids and unknown usage. CI also checks the pinned native CL-Bench interface in its separate dependency environment; that job is an interface test, not a benchmark result.

A new pilot requires the model server specified in the provenance record, a secret key file outside the repository, and an unused output directory. The frozen harness accepts only development seeds 90000–90003. The first protocol has a total 30-minute model-pilot ceiling, and cannot establish the confirmatory margins from one stream. Existing studies cannot be overwritten. Any revised solver/model protocol needs a new source and evaluation freeze. No recurring research automation is active.

## Evidence and implementation

| Path | Purpose |
|---|---|
| `src/witness_cl/sql_env_v8.py` | Bounded read-only SQLite, public schema/catalog, fresh instances and evaluator-only target recipes |
| `src/witness_cl/fragments_v8.py` | Immutable typed text/hole compiler, strict bindings and CTE composition |
| `src/witness_cl/abstraction_v8.py` | Own-experience proposal, charged reconstruction and admission provenance |
| `src/witness_cl/memory_v8.py`, `model_v8.py` | Six memory arms and measured authenticated loopback inference |
| `experiments/sql_abstractions_v8.py` | Frozen actual-model pilot with reserved panel resources |
| `experiments/audit_sql_abstractions_v8.py` | Saved-data replay and cost/completeness checks |
| `tools/v8_results.py` | Descriptive single-stream reporting; no unsupported confidence interval |
| `formal/WitnessCL/TypedFragments.lean` | New compiler contracts and limitation counterexamples |
| `artifacts/v8/`, `docs/v8/` | Raw traces, source receipts, proof/test evidence and independent reviews |
| `paper/main.tex`, `paper/main.pdf` | Current professional LaTeX report and PDF |

The [environment review](docs/v8/PILOT_ENVIRONMENT_REVIEW.md) distinguishes genuine target recombination opportunities from actual acquisition. Seven of eight fresh-old targets change; refunded-order count remains structurally 22. A future heldout protocol must use disjoint numeric seeds because the split label alone does not ensure independent data seeds. The [next decision](docs/v8/NEXT_STEP.md) addresses shared solver competence before scaling the memory comparison.

## Preserved earlier research

This private repository continues `Witness_CL_v4.bundle` and preserves its Git history and release tags. In the [archived v7 study](docs/v7/RESULTS.md), a supplied-grammar numerical learner gained +0.12240 reward from reuse on shared-novel questions, but lost the common-SELECT-budget final comparison to simple full-history controls (47.44% versus 100%). That result does not demonstrate discovered SQL abstractions. Its [paper](paper/v7/main.pdf), [source freeze](artifacts/v7/freeze.json), raw evidence and earlier archives remain unchanged.

MIT software license. AI-assisted research draft; author review and independent replication remain necessary before publication.
