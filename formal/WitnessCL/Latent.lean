/-
Witness-CL v0.4 logical lemmas, kernel-checked with Lean 4.19.0 in the v5 audit.
Only Std is used. No Python/refinement or probabilistic calibration claim.
-/
import Std
import WitnessCL.Continuation

universe u v w
namespace WitnessCL.V4

def Completes {I : Type u} {V : Type v} (m : I → V) (cube : I → Option V) : Prop :=
  ∀ i v, cube i = some v → m i = v

def Assign {I : Type u} {V : Type v} [DecidableEq I]
    (cube : I → Option V) (slot : I) (v : V) : I → Option V :=
  fun i => if i = slot then some v else cube i

/-- Splitting an unread slot retains a branch for every total completion. -/
theorem split_cover {I : Type u} {V : Type v} [DecidableEq I]
    (m : I → V) (cube : I → Option V) (slot : I) (empty : cube slot = none) :
    Completes m cube ↔ ∃ v, Completes m (Assign cube slot v) := by
  constructor
  · intro old
    refine ⟨m slot, ?_⟩
    intro i v h
    by_cases same : i = slot
    · subst i
      simp [Assign] at h
      exact h
    · simp [Assign, same] at h
      exact old i v h
  · rintro ⟨v, filled⟩
    intro i w h
    by_cases same : i = slot
    · subst i
      simp [empty] at h
    · apply filled i w
      simp [Assign, same, h]

/-- A chosen filled branch is a subset of the original unknown-slot cube. -/
theorem assigned_refines {I : Type u} {V : Type v} [DecidableEq I]
    (m : I → V) (cube : I → Option V) (slot : I) (v : V)
    (empty : cube slot = none) (new : Completes m (Assign cube slot v)) :
    Completes m cube := by
  exact (split_cover m cube slot empty).mpr ⟨v, new⟩

/-- Evidence must constrain every completion, not merely a fitted representative. -/
theorem exact_evidence_intersection {M : Type u} {C : Type v}
    (old : C → Prop) (denotes : C → M → Prop) (consistent : M → Prop)
    (covered : ∀ m, consistent m ↔ ∃ c, old c ∧ denotes c m)
    (feedback : M → Prop) (m : M) :
    consistent m ∧ feedback m ↔ ∃ c, old c ∧ denotes c m ∧ feedback m := by
  constructor
  · rintro ⟨hc, hf⟩
    obtain ⟨c, ho, hd⟩ := (covered m).mp hc
    exact ⟨c, ho, hd, hf⟩
  · rintro ⟨c, ho, hd, hf⟩
    exact ⟨(covered m).mpr ⟨c, ho, hd⟩, hf⟩

/-- A branch cover with sound leaf bounds suffices for a global bound. -/
theorem covered_lower_bound {M : Type u} {L : Type v}
    (live : M → Prop) (leaf : L → M → Prop) (delta : M → Int) (bound : Int)
    (cover : ∀ m, live m → ∃ l, leaf l m)
    (checked : ∀ l m, leaf l m → bound ≤ delta m) :
    ∀ m, live m → bound ≤ delta m := by
  intro m hm
  obtain ⟨l, hl⟩ := cover m hm
  exact checked l m hl

/-- Nonnegative return differences protect truth membership independent of proposer. -/
theorem guarded_update {M : Type u}
    (live : M → Prop) (truth : M) (base candidate : M → Int)
    (retained : live truth)
    (checked : ∀ m, live m → 0 ≤ candidate m - base m) :
    base truth ≤ candidate truth := by
  have h := checked truth retained
  omega

/-- Adaptively changing which proposal is checked cannot weaken a universal test. -/
theorem arbitrary_proposer {M : Type u} {P : Type v}
    (live : M → Prop) (truth : M) (base : M → Int) (value : P → M → Int)
    (retained : live truth) (proposal : P)
    (admitted : ∀ m, live m → base m ≤ value proposal m) :
    base truth ≤ value proposal truth := by
  exact admitted truth retained

/-- Previously acquired value is protected through successive admitted updates. -/
theorem retained_chain (v : Nat → Int) (step : ∀ n, v n ≤ v (n+1)) :
    ∀ n, v 0 ≤ v n := by
  intro n
  induction n with
  | zero => omega
  | succ n ih =>
      have h := step n
      omega

/-- Observable disagreement guarantees one discarded behavioral alternative. -/
theorem informative_probe_removes {M : Type u} {O : Type v}
    (live : M → Prop) (output : M → O) (a b : M)
    (ha : live a) (hb : live b) (different : output a ≠ output b) (observed : O) :
    ∃ m, live m ∧ output m ≠ observed := by
  by_cases same : output a = observed
  · refine ⟨b, hb, ?_⟩
    intro equal
    apply different
    exact same.trans equal.symm
  · exact ⟨a, ha, same⟩

def CurrentObs (_ : Bool) : Nat := 0

def NextObs : Bool → Nat
  | false => 0
  | true => 1

/-- Equal current observations do not imply equal next-step observations. -/
theorem hidden_state_alias_counterexample :
    ∃ s t : Bool, CurrentObs s = CurrentObs t ∧ NextObs s ≠ NextObs t := by
  refine ⟨false, true, ?_⟩
  decide

/-- Debit validity plus a budget protects every completed reset-episode prefix. -/
theorem reset_prefix_budget (xs : List (Int × Int)) (B : Int)
    (pointwise : ∀ p ∈ xs, p.1 ≤ p.2)
    (within : WitnessCL.V3.SumSecond xs ≤ B) :
    WitnessCL.V3.SumFirst xs ≤ B := by
  exact WitnessCL.V3.debit_budget xs B pointwise within

/-- New candidate classes require new checks; shrinking does not. -/
theorem shrinking_retains {M : Type u} (old new : M → Prop) (ok : M → Prop)
    (sub : ∀ m, new m → old m) (checked : ∀ m, old m → ok m) :
    ∀ m, new m → ok m := by
  intro m hm
  exact checked m (sub m hm)

#print axioms split_cover
#print axioms covered_lower_bound
#print axioms arbitrary_proposer
#print axioms informative_probe_removes
end WitnessCL.V4
