# Formalization status

There are **50 theorem attempts**: 13 in `Core.lean`, 16 in `Refinement.lean`,
10 in `Continuation.lean`, and 11 in `Latent.lean`. None was kernel-checked here.
The actual `make formal` command fails because `lake` is absent; official
release retrieval also failed. Logs are in `artifacts/v4/lean-build.txt` and
`lean-status.txt`. No success is implied by `#print axioms` in unexecuted source,
absence of placeholders, or Python/C++ tests.

The v4 file attempts partial-table split coverage, refinement, evidence
intersection, covered lower bounds, guarded updates, arbitrary proposal
selection, incumbent chains, informative elimination, observation aliasing,
budget lifting and shrinking-class preservation. See `docs/v4/THEORY.md` for
written arguments and the actual scope. The archive retains the v1-v3 lemmas.

These abstractions do not establish that the Python DFS implements its cover,
that a real task satisfies a finite-state contract, or that the floating-point
trainer, C++, CUDA, noisy evidence or an LLM's semantics are correct. A future
successful Lean build would verify the declared abstract lemmas, not those
missing refinements. Until the pinned Lean 4.19.0 compiler accepts the files,
even syntax and tactic correctness remain unestablished.

```bash
cd formal
lake build
```

CI attempts this command on a toolchain-enabled machine without an allow-failure
setting. No successful CI run was observed for this release.
