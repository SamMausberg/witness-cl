# Formalization status

**Source attempt, not kernel-checked in the authoring environment.** Lean/lake
were absent and downloading the official toolchain was blocked. The build attempt
and environment status are recorded in `../artifacts/lean-status.txt`.

With Lean installed, run `cd formal && lake build`. The pinned toolchain is
`leanprover/lean4:v4.19.0`; no mathlib dependency or network package is required
once that compiler is installed. CI is configured but has not run here.

`WitnessCL/Core.lean` contains proof terms for truth preservation, soundness of
unanimous certificates, preservation under nonempty refinement, equivalence of
certificates for equal version sets, persistence of redundant constraints,
sequential refinement, and isolation of other public scopes. It includes a
minimal incompatible-worlds lemma.

The e-process probability result, finite-class witness cardinality bound,
affine identification proof, Python implementation refinement, model-class
realizability, and end-to-end LLM safety are **not formally verified**. They must
not be advertised as Lean-proved. Abstract predicates model total deterministic
hypotheses, not floating-point neural networks or arbitrary Python programs.

No custom axiom, `sorry`, or `admit` is supplied. This is an inspection fact, not
a substitute for compilation. `#print axioms` statements make successful future
checks auditable; standard Lean logical axioms must not be confused with new
unproved assumptions added by an author.
