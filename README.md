# Witness-CL

**Counterexample-preserving online skill compilation. Research prototype, not a benchmark winner.**

Learn reusable deterministic rules from deployment feedback, preserve a sufficient
set of counterexamples, and distinguish conditional logical certificates from
statistical evidence for broader skills. The foundation model need not be retrained.

**Status, 8 September 2026:** executable Python reference; CPU mechanism and
failure experiments; unit/property-style tests; an optional local-LLM runner;
a two-column LaTeX research draft. No LLM or public-benchmark result has been
produced. Lean proof sources were attempted but could not be kernel-checked
because Lean was unavailable. See [claim boundaries](docs/CLAIMS.md).

## Run

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test,analysis]'
make test
make experiment
make audit-power
make paper
# Requires the separately installed pinned Lean compiler:
make formal
```

The core algorithm uses only the Python standard library. NumPy is used by the
optional recursive least-squares baseline and audit-power diagnostic.
`artifacts/environment.json` records the actual environment, not a claimed lockfile.

## What is implemented

`src/witness_cl/core.py` maintains a complete finite hypothesis class per **public**
environment/version, eliminates hypotheses using binary success feedback, stores
only informative observations in an active witness set, and caches unanimous
predictions. An empty class is quarantined. `audit.py` implements a fresh-episode,
exact-rational paired e-process with candidate-wise error allocation and stale
incumbent rejection. It is a primitive, not an integrated production auditor.

`programs.py` provides a tiny typed, total, non-executable-input DSL for affine
maps modulo an integer. `ledger.py` provides a single-writer hash-linked log,
not authentication against a full rewrite. `online_ridge.py` is an established
online-update control requiring actual scalar labels, not invented labels.

## What the measurements say

The executed synthetic study uses 20 seeds, 384 episodes, four public scopes,
five scenarios, and six symbolic methods. The incremental method and unbounded
full-history symbolic induction have identical accuracy. On stationary affine
streams both score 94.17% overall and 100% in the late half. Full lookup scores
78.12% overall. This is **not evidence of beating LLM ICL**.

The exact path fails under deliberately hidden drift and a misspecified class.
In the nonlinear stress test its late reward is 14.09%, versus 68.12% for full
lookup, and it emits four wrong conditional certificates per seed before
quarantine. These are published counterexamples, not excluded runs.

For the stationary case, an average 29.4 retained witness observations represents
all 384 feedback records relative to the fixed hypothesis class. The source
also retains the full history, so total persistent storage is not constant.

Results and raw episode records: [artifacts/synthetic](artifacts/synthetic/).
The audit-power simulation separately demonstrates the cost of fresh evidence.

## Optional model experiment

Run a user-chosen chat-completions server and supply its exact model identifier:

```bash
PYTHONPATH=src python experiments/llm_synthetic.py \
  --base-url http://127.0.0.1:8000/v1 --model YOUR_SERVED_MODEL_ID \
  --arms raw_full_icl witness witness_condensed \
  --out artifacts/local_model_run.jsonl
```

This runner is synthetic, not CL-Bench. It logs complete prompts, responses,
reported token usage, and errors. Remote calls require `--allow-remote` and are
never made automatically. Context overflow aborts instead of silently truncating
an arm named full ICL. Invalid structured outputs are scored as invalid actions.
The model-service protocol has mock tests, not an executed provider integration.

## Reading order

[Paper](paper/main.pdf), [theory](docs/THEORY.md), [evaluation and kill criteria](docs/EVALUATION.md),
[training/inference](docs/TRAINING_INFERENCE.md), [safety](docs/SAFETY.md),
[prior work](docs/RELATED_WORK.md), [upstream integration boundary](integrations/README.md),
and [Lean status](formal/README.md).

The research claim to test is whether preserving decision-discriminating evidence,
then compiling only justified behavior, improves the reward/cost/retention frontier
of real continual agents. The individual ingredients are established. Novelty of
the combination and public-benchmark effectiveness remain unestablished.

MIT license. Paper author line: Samuel Mausberg. AI-assisted draft; author review
and independent replication are required before submission.
