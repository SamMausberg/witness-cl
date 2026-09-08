# Falsifiable evaluation protocol

This is an unexecuted external evaluation plan, not a report of native benchmark
results. Freeze this protocol and the implementation before examining test scores.

## Primary hypothesis

Experience can be compiled into small, typed, continuation-aware skills that
improve future task performance at equal total inference and adaptation cost,
relative to strong raw-history ICL. A certificate that forces fallback on almost
every episode is safe but does not support this performance hypothesis.

Two independent tracks avoid requiring simulator access the benchmark does not
provide. In a legally cloneable read-only environment, run paired full
continuations from the same snapshot and explicitly advance both controller
memories. In a non-cloneable environment, do not fabricate counterfactual data:
use fresh randomized prospective trials with logged assignment probabilities,
episode-level return, and a separately specified trial-loss constraint. V0.2's
local one-step audit is not a full-continuation substitute. Learned-model
certificates form a third, strictly conditional track until uniform error
coverage has been validated.

## Native benchmark arms

Use CL-Bench's six published domains and AgentCL's controlled, naive, and held-out
streams. Use J-TTL as a repeated-game secondary test. Pin repository commit,
schedule, dependencies, backbone weights/revision, tokenizer, system prompt,
context budget, decoding parameters, tools, and all search/adaptation budgets.
Use at least two frozen backbones, chosen before test inspection and kept identical
across paired arms. An open-weight backbone on the intended GH200 and one
independently implemented/model-family backbone are useful robustness conditions.
No particular current model is asserted to be the best choice by this release.

Mandatory arms are stateless; raw-history ICL; ICL with a scratchpad; the benchmark's
ACE and Mem0 implementations; MemProbe where supported; an EvoTest/TTHE-style
harness-search baseline where protocol-compatible; v0.2; and v0.3. Match not just
prompt length but total solver, proposer, judge, replay, model-fit, validation,
training, and simulator costs. Add an equal-wall-time comparison. Do not quietly
allow the proposed method extra failed candidates or hidden test access.

Ablate full-horizon checking to immediate gain; incumbent carry-forward to anchor
restart; complete controller state to environment-only state; raw evidence to
compressed-only evidence; budgeted to unbudgeted exploration; public versus
inferred scope; frozen modules versus replay and near-parameter-matched shared
models. Randomize stream order and include A-B-A recurrence, rare protected
contexts, delayed harm, hidden regime changes, misleading observations, and
long horizons. A trusted task ID must not be provided only to our method.

## Metrics and statistical unit

Use the native gain definition from each benchmark, never substitute rising raw
reward on an easier schedule. Also report prequential reward/area under the
learning curve, held-out forward transfer, backward transfer, worst protected
scope regression, old-task recovery delay, cost, latency quantiles, all stored
bytes, and the fraction of proposed/useful changes admitted. Unit of resampling
is an independent environment/stream seed, not individual correlated episodes.

Start with 20 paired independent seeds per domain and backbone when the protocol
allows it. A six-domain, two-backbone, seven-arm, 64-episode design is 107,520
agent episodes before extra candidates and additional baselines. These are
planning counts, not a claim that all native schedules have 64 episodes.
Run a power pilot on separate development instances. If twenty seeds cannot
resolve the preregistered effect, report uncertainty or increase the seed count
based on the pilot, not on which treatment currently looks better.

Primary practical target: at least five percentage points higher native learning
gain, with a positive paired 95% confidence lower bound against the strongest
cost-matched applicable baseline in the pooled prespecified analysis, positive
point estimates on at least four of six CL-Bench domains, and no prespecified
protected domain regression beyond two percentage points. These thresholds are
research choices, not theoretical guarantees. Report per-domain results even if
the pooled target is met. Use simultaneous intervals or correction for claims
across domains; do not treat a nonsignificant loss as equivalence.

## Concrete extension: counterexample-guided abstraction

The next algorithm learns a typed abstract state from schema and raw transition
witnesses, proposes a skill, and splits states when different continuation
consequences were aliased. Each abstraction and skill is immutable once archived.
A patch is usable only if its predicted margin exceeds twice a uniform value
error envelope, or if a valid prospective full-episode audit independently admits
it. The finite-horizon envelope is derived in THEORY.md. Do not estimate a valid
coverage probability by the training fit itself.

First test on generated relational/navigation environments where the exact world
is known to the evaluator but not the learner. Vary state aliasing, horizon,
reward sparsity, latent grammar depth, and model misspecification independently.
Compare supplied models, learned abstractions, full-history planning, and a
retrieval-plus-LLM baseline. Use held-out composition and A-B-A recurrence, not
just repeats. Measure whether small abstractions emerge and whether coverage
remains valid after adaptive proposal selection. This is the most important
missing empirical bridge before a native LLM claim.

## Kill criteria

Reject the proposed benchmark advantage if equal-cost raw-history ICL or the
strongest applicable harness/memory baseline matches or beats v0.3 within a
prespecified practical-equivalence interval, or if the primary gain threshold
fails. The current finite-world experiment already rejects a claim of superior
late reward over its full-history model-based control.

Reject the abstraction mechanism if its honest error margins exclude over 90% of
otherwise useful proposals, if its state count grows approximately with raw
history rather than reusable structure, or if a held-out aliasing case violates a
claimed guarantee. Reject a learning advantage that disappears when a privileged
scope/latent-family label is removed. Reject the systems speed claim if warm
end-to-end profiling does not beat the scalar/full-history pipeline after all
packing, fitting, cache management, and launch costs. Immediately stop an exact
correctness claim on any reproducible mismatch.

## Resource envelope

The included deterministic and neural mechanism tests need CPU, Python 3.11+,
NumPy, pytest, and a C++17 compiler. Native CL-Bench currently documents Python
3.13+, uv, and Docker. The source was inspected, not installed or executed here.

A single GH200 is a proposed first open-model execution target, not hardware used
for these results. Check the selected model's actual weights, context/KV,
activation, optimizer, frozen-module, and archive footprint against that specific
machine before scheduling. Include CPU memory and disk, not only VRAM. A read-only
container workspace is needed per paired environment branch where cloning is
permitted. Network APIs or external side effects are not magically cloneable.

Budget using measured pilot quantities: total input/output/generated-candidate
tokens divided by sustained serving throughput, plus simulator and online-training
wall time and synchronization. For illustration only, 107,520 episodes at 20,000
processed tokens per episode is 2.1504 billion tokens before extra candidates.
Report actual GPU-hours and provider charges after execution. No actual native
run duration, provider price, or GH200 speed is forecast as an observed result.

## Upstream interface inspection

Read on 8 September 2026 through the connected GitHub tool:
- pgasawa/continual-learning-bench README.md, blob
  5eb8fea83793bad7f95da9c3a09f2c8f138715eb.
- src/systems/icl/system.py, blob
  bf60ce2441fbe48f38d76bc3a1636ae64893f66a.

The interface exposes respond(Query), observe(Observation), reset(), usage events,
and artifact export. It does NOT expose the finite family or complete simulator
state required by ContractAgent. A correct native adapter must obtain a legal
state/feedback abstraction and honor the benchmark's reset/retention rules. No
such completed adapter is claimed. The older llm_synthetic runner is not one.
