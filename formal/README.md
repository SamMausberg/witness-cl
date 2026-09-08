# Formalization status

There are **29 theorem attempts**, 13 in `WitnessCL/Core.lean` and 16 in
`WitnessCL/Refinement.lean`. There are no proof placeholders or added axioms.
They are **not kernel-checked**. The command `make formal` failed because `lake`
was not installed; see `artifacts/v2/lean-build.txt`. An attempted official
Lean 4.19.0 binary download also failed. No successful Lean build is implied by
the Python/C++ tests or by `#print axioms` commands present in unexecuted source.

The new file covers class-growth replay, a witness-compression counterexample,
local patch noninterference, archival output identity, integer residual identity,
and algebraic removal of neutral factors. It does NOT prove probability theorems,
real orthogonal projection, regret bounds, SQL semantics, floating-point
correctness, Python refinement, or CUDA correctness.

To validate with the pinned compiler:

```
cd formal
lake build
```

The CI job attempts this build on a machine that can install the toolchain. Until
a successful log is obtained, do not describe these as verified Lean theorems.
