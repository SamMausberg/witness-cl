# Lean verification audit

On 2026-09-08, Lean 4.19.0 accepted all 50 inherited theorem statements after
three proof-script repairs. A new general history-aliasing obstruction brings
the total to 51. This is a completed formal verification milestone for the
abstract statements; it is not an end-to-end verification of Witness-CL.

## Reproduction and evidence

From the repository root, run `python3 formal/audit.py --output artifacts/v5`.
Set `LAKE` if the installed launcher is not on PATH or at `~/.elan/bin/lake`.
The script runs the pinned compiler, builds all imported modules, then issues
`#print axioms` for every source theorem. It fails on a compiler failure, a
missing theorem, source placeholders/custom axioms, or an unexpected dependency.
It records source SHA-256 hashes to tie the report to the checked files.

| Module | Theorems | What is established |
|---|---:|---|
| `Core.lean` | 13 | Predicate intersection/refinement, conditional truth preservation, unanimous-certificate soundness, scope isolation, elementary incompatible-world obstruction. |
| `Refinement.lean` | 16 | Replay under class growth, guarded patch behavior, archive isolation, zero-residual preservation, neutral multiplicative factors. |
| `Continuation.lean` | 10 | Equality of closed deterministic continuations, finite-horizon Bellman comparison, substitution of the true model, arithmetic debit composition, a two-action safety/gain obstruction. |
| `Latent.lean` | 11 | Abstract partial-table splitting, conditional cover bounds, guarded updates, monotone incumbent chains, informative disagreement, aliasing and budget examples. |
| `Ambiguity.lean` | 1 | General deterministic history-aliasing obstruction for safety versus strict gain. |

`artifacts/v5/formal-build.txt` records a successful build, and
`formal-axioms.txt` lists all 51 axiom reports. `formal-audit.json` reports
24 axiom-free theorems; 27 use propositional extensionality (`propext`),
11 use quotient soundness (`Quot.sound`), and 2 use classical choice
(`Classical.choice`). Counts overlap. These are standard Lean foundational
axioms. There are no custom axioms and no final `sorryAx` dependencies.

The initial failure is preserved in `formal-initial-build.txt`. Two v2 lemmas
used `protected`, a Lean keyword, as a binder; this is now `protectedDomain`.
`filter_one_factors` now explicitly proves `(f != 1) = true` from `f ≠ 1`.
These repairs change no logical hypothesis or conclusion. Compiler recovery
inserted `sorryAx` into the initially failed elaboration; the final complete
audit rejects it and reports none.

## Interpretation of the new obstruction

Let two possible worlds yield exactly the same history available to a
deterministic policy. Include controller memory and all available observations
in that history. Suppose every action that strictly improves on the incumbent
in the favorable world has lower value than the incumbent in the adverse world.
If the policy is safe in the adverse world, it cannot strictly improve in the
favorable one. The proof substitutes the identical policy action into the
conflicting value inequalities and derives a contradiction.

This generalizes the inherited Boolean example. It explains why perfect
retention plus guaranteed discovery cannot be promised for every observationally
ambiguous environment. It does not show that safe information gathering is
impossible when a distinguishing safe probe exists, or that progress remains
impossible after histories diverge. Randomized expected-return policies,
stochastic feedback, and statistical confidence bounds are outside the theorem.
The statement is an elementary information obstruction, not a claim of a new
learning-theoretic lower bound.

## Gaps between lemmas and implementation

`split_cover` proves that an unknown table slot can be split over its values
without losing a completion. It does not prove that `LatentSpace._fit`
enumerates the right state/output branches, deduplicates soundly, or handles
resource limits correctly. `exact_evidence_intersection` assumes a correct
existing cover; it does not induct over the Python trace-fitting procedure.
`covered_lower_bound` assumes complete coverage and sound leaf bounds. Neither
the Python paired search nor its residual-program interning has been connected
to those assumptions by a proved refinement.

`closed_continuations_equal` requires equality of complete successor states and
outputs, plus closure of the predicate. Equality of visible output alone does
not discharge that hypothesis. `bellman_improvement` assumes the advantage
inequality at every state and remaining horizon. The checker uses a different
reset-return comparison; the Bellman lemma does not automatically verify it.

`guarded_update`, `arbitrary_proposer`, and `retained_chain` certify substitution
and inequality composition once the true model is retained and a universal
comparison is valid. They do not prove that truth belongs to the configured
model class, that the live class is nonempty, or that the running controller
actually obeys those obligations. Preservation applies to the specified value
function and reference state, not arbitrary tasks, all neural representations,
or the realized return of every exploratory episode.

`reset_prefix_budget` composes already-valid integer deficit bounds. It does not
prove that runtime tickets, probe selection, ledger updates, era restarts, or
feedback validation implement those premises. The conditional bound concerns
completed reset-episode prefixes in one stationary realizable era. It does not
cover unbounded task drift, undeclared changes in reward/reset semantics, irreversible side effects, or
arbitrary execution failures.

The floating-point online proposer, candidate-generation quality, C++ and CUDA
implementations, probabilistic calibration, native benchmark adapters, and LLM
semantics remain unverified by Lean. Python/exhaustive/C++ tests provide separate
finite experimental evidence; they do not discharge universal proof obligations.
The highest-value next formal task is a proved finite policy interpreter and
trace-cover update with executable extraction and differential tests against
the Python implementation, followed by the paired checker and resource-cap
semantics. More high-level inequality lemmas would not close that gap.
