# Execution and engineering contract

## Reproduce local results

```
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test,analysis]'
make test
make cpp-check
make continuation-study
make neural-study
make continuation-diagnostics
make paper
```

The study commands overwrite their own v3 JSON and logs; timing will vary. Seeds,
per-seed metrics, and the 17,920 controller episodes are included. Neural feedback
examples are reproducible from fixed seeds, not archived as raw individual rows.
The old `make refine` and `make experiment` targets retain v2/v1 reproduction.
`make formal` requires the pinned Lean 4.19.0 toolchain. It failed here because
`lake` is absent. `make cuda-check` tests older CUDA components only and needs
appropriate NVIDIA hardware. The new CUDA continuation draft has no executed
host binding and is not covered by that target.

## Files and integration boundaries

The integrated deterministic agent is `continuation.py`. Inputs are immutable
integer model/policy tables and actual observed trajectories. Model generation,
complete state construction, and real tools are outside it. `coupling.py`,
`likelihood.py`, `versioned_training.py`, and `vector_contract.py` are independently
tested components. In particular, the stochastic filter and neural module learner
are not integrated into ContractAgent. Calling their independent tests a working
LLM system would be inaccurate.

A planning rollout of a supplied model is not an observed environment outcome.
The reference counts those planning calls separately. Truth values are used by
the experiment evaluator, not passed as extra labels to the online agent.
Immutable content fingerprints support cache invalidation, not cryptographic
proofs of truthful environment state. Observed contradictions invalidate the
realizability assumption; a hidden drift can cause harm before its first witness.

## Complexity and data movement

For M plausible models, H stages, S states, A actions, one value backup is
O(MHS), and one all-action advantage pass is O(MHSA), with dense model storage
O(MHSA). The reference constructs model-optimal policies plus archived candidates. With K
unique candidates, information scoring costs O(KMH); recomputing their all-state
values costs O(KMHS), before policy construction and trajectory grouping. K can
grow with the archive rather than remaining bounded by M. Repeated conservative
policy improvement can add passes. This is not a sublinear planning result. Evidence
storage grows with observations; new models replay all retained observations.

The NumPy path packs tables and evaluates exact int64 lower advantages. Overflow
is rejected using a conservative magnitude bound, rather than silently wrapping.
Its cold end-to-end timing includes packing. At M=64 it is slightly slower than
the scalar Python path in the recorded run. Treat that result as evidence against
claiming a current speedup.

The C++ reference uses 128-bit intermediates and checked int64 output. The CUDA
draft proposes one 256-thread block per (stage,state,action), reduces model-wise
advantages, and emits lower bounds. It assumes a pinned model/value snapshot,
valid index ranges, a positive model count, and the documented integer bound.
It has NOT been compiled, run under sanitizers, or benchmarked on a GPU.

A plausible optimization is immutable device-resident tables, generation-indexed
value caches, compact live-model indices, and asynchronous prefetch for modules.
Only invalidate affected dependencies, but never keep a certificate when its
baseline, model family, encoder, router, or complete state contract changes.
Benchmark both cold and warm paths; a warm-cache primitive speedup is not an
end-to-end agent speedup. Before GPU optimization, profile whether model
construction, LLM inference, simulator calls, or safety admission dominates.

## Safety scope

Experiments use pure finite simulators and numeric classification. Do not connect
this prototype to irreversible actions, production databases, payments, or
self-modifying infrastructure. Proposed skills must not change their evaluator,
permissions, cost ledger, immutable history, or protected scope map. Sandbox read
access and treat tool output as untrusted data. Audit loss budgets quantify reward
under explicit models, not privacy, malicious instructions, or catastrophic risk.
