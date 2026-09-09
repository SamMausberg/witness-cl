/-
A finite-data limitation of relation-dependence checks. This is an abstract
counterexample, not SQLite semantics, a probabilistic learning lower bound, or
a claim that the particular fitted function is produced by the deployed model.
-/
import Std

namespace WitnessCL.Intervention

/-- Reference answers are constantly one. Keeping the proposed relation returns
one on witnessed contexts and two elsewhere; emptying it returns zero. Thus the
output depends on the relation even when its answer is wrong. -/
def fittedAnswer (witnesses : List Nat) (context : Nat) (relationPresent : Bool) : Nat :=
  if relationPresent then (if context ∈ witnesses then 1 else 2) else 0

/-- Every finite witness collection admits a candidate that reconstructs every
reference answer and passes the empty-relation dependence test at every witness,
yet fails on a fresh context while still passing the same dependence test there.
The constructive fresh context is one plus the sum of all witnessed contexts.
No guarantee of transfer follows from these checks alone without restrictions
on the candidate class, the environment, or the evaluation distribution. -/
theorem finite_reconstruction_and_dependence_do_not_imply_transfer
    (witnesses : List Nat) :
    ∃ fresh : Nat, fresh ∉ witnesses ∧
      (∀ context ∈ witnesses,
        fittedAnswer witnesses context true = 1 ∧
        fittedAnswer witnesses context false = 0 ∧
        fittedAnswer witnesses context true ≠ fittedAnswer witnesses context false) ∧
      fittedAnswer witnesses fresh true ≠ 1 ∧
      fittedAnswer witnesses fresh true ≠ fittedAnswer witnesses fresh false := by
  have bounded : ∀ context ∈ witnesses, context ≤ witnesses.sum := by
    induction witnesses with
    | nil => simp
    | cons head tail ih =>
        intro context member
        simp only [List.mem_cons] at member
        simp only [List.sum_cons]
        rcases member with equal | member
        · omega
        · have bound := ih context member
          omega
  have fresh : witnesses.sum + 1 ∉ witnesses := by
    intro member
    have bound := bounded (witnesses.sum + 1) member
    omega
  refine ⟨witnesses.sum + 1, fresh, ?_, ?_, ?_⟩
  · intro context member
    simp [fittedAnswer, member]
  · simp [fittedAnswer, fresh]
  · simp [fittedAnswer, fresh]

end WitnessCL.Intervention
