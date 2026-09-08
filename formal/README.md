# Formalization status

There are **39 theorem attempts**: 13 in `Core.lean`, 16 in `Refinement.lean`,
and 10 in `Continuation.lean`. They are **not kernel-checked**. `make formal`
failed because `lake` is absent; an official-toolchain download attempt failed
because networking was unavailable. Logs are in `artifacts/v3/lean-build.txt`
and `lean-install-attempt.txt`. No success is implied by `#print axioms` in
unexecuted source or by the Python/C++ test results.

The new deterministic theory covers closed continuation equality, full-horizon
Bellman improvement, truth membership, shrinking obligations, deficit addition,
zero-risk obstruction, a delayed-reward counterexample, and incumbent ordering.
There are no intended proof placeholders or newly assumed axioms. Until the
pinned Lean 4.19.0 compiler accepts the files, even syntax/tactic correctness is
not established. A successful build should also save every printed axiom list.

These abstractions do not verify Python, stage-indexed table refinement,
floating point, CUDA, likelihood probability theory, learned abstraction error
coverage, or an LLM's actual semantics. See `docs/v3/THEORY.md` for the handwritten
statements and missing bridges.

```
cd formal
lake build
```

CI attempts this command on a toolchain-enabled machine. No CI success from this
revision was observed in the authoring environment.
