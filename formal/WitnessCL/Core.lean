/-
Witness-CL logical core. Kernel-checked with Lean 4.19.0 during the v5 audit.
No placeholders or custom axioms. The probability theorem, cardinality bound,
and Python refinement are NOT formalized. See formal/README.md for audit scope.
-/
import Std

universe u v w
namespace WitnessCL

abbrev Space (H : Type u) := H → Prop

def Refines {H : Type u} (W V : Space H) : Prop := ∀ h, W h → V h

def Step {H : Type u} (V C : Space H) : Space H := fun h => V h ∧ C h

def Certified {H : Type u} {X : Type v} {Y : Type w}
    (V : Space H) (eval : H → X → Y) (x : X) (a : Y) : Prop :=
  (∃ h, V h) ∧ ∀ h, V h → eval h x = a

def Consistent {H : Type u} {X : Type v} {Y : Type w}
    (eval : H → X → Y) (x : X) (a : Y) (success : Prop) : Space H :=
  fun h => (eval h x = a ↔ success)

theorem step_refines {H : Type u} (V C : Space H) : Refines (Step V C) V := by
  intro h hh
  exact hh.1

theorem truth_survives {H : Type u} {V C : Space H} {truth : H}
    (inV : V truth) (consistent : C truth) : Step V C truth := by
  exact ⟨inV, consistent⟩

theorem truthful_feedback_preserves {H : Type u} {X : Type v} {Y : Type w}
    (eval : H → X → Y) (V : Space H) (truth : H) (x : X) (a : Y)
    (success : Prop) (inV : V truth) (correct : eval truth x = a ↔ success) :
    Step V (Consistent eval x a success) truth := by
  exact ⟨inV, correct⟩

theorem certified_sound {H : Type u} {X : Type v} {Y : Type w}
    {V : Space H} {eval : H → X → Y} {x : X} {a : Y} {truth : H}
    (inV : V truth) (cert : Certified V eval x a) : eval truth x = a := by
  exact cert.2 truth inV

theorem certified_under_refinement {H : Type u} {X : Type v} {Y : Type w}
    {V W : Space H} {eval : H → X → Y} {x : X} {a : Y}
    (sub : Refines W V) (nonempty : ∃ h, W h)
    (cert : Certified V eval x a) : Certified W eval x a := by
  constructor
  · exact nonempty
  · intro h hh
    exact cert.2 h (sub h hh)

theorem empty_not_certified {H : Type u} {X : Type v} {Y : Type w}
    (eval : H → X → Y) (x : X) (a : Y) :
    ¬ Certified (fun _ : H => False) eval x a := by
  intro cert
  obtain ⟨h, hh⟩ := cert.1
  exact hh

/-- Equal live sets imply equal certificates. This is the semantic compression contract. -/
theorem equivalent_certificates {H : Type u} {X : Type v} {Y : Type w}
    {V W : Space H} (equiv : ∀ h, V h ↔ W h) (eval : H → X → Y) (x : X) (a : Y) :
    Certified V eval x a ↔ Certified W eval x a := by
  constructor
  · intro cert
    constructor
    · obtain ⟨h, hh⟩ := cert.1
      exact ⟨h, (equiv h).mp hh⟩
    · intro h hh
      exact cert.2 h ((equiv h).mpr hh)
  · intro cert
    constructor
    · obtain ⟨h, hh⟩ := cert.1
      exact ⟨h, (equiv h).mpr hh⟩
    · intro h hh
      exact cert.2 h ((equiv h).mp hh)

theorem redundant_constraint {H : Type u} {V C : Space H}
    (redundant : ∀ h, V h → C h) : ∀ h, Step V C h ↔ V h := by
  intro h
  constructor
  · intro hh; exact hh.1
  · intro hh; exact ⟨hh, redundant h hh⟩

/-- Once redundant, an observation stays redundant as the version space contracts. -/
theorem redundancy_persists {H : Type u} {V W C : Space H}
    (sub : Refines W V) (redundant : ∀ h, V h → C h) : ∀ h, W h → C h := by
  intro h hh
  exact redundant h (sub h hh)

def Fold {H : Type u} : Space H → List (Space H) → Space H
  | V, [] => V
  | V, C :: cs => Fold (Step V C) cs

theorem fold_refines {H : Type u} (cs : List (Space H)) (V : Space H) :
    Refines (Fold V cs) V := by
  induction cs generalizing V with
  | nil => intro h hh; exact hh
  | cons C cs ih =>
      intro h hh
      exact (ih (Step V C) h hh).1

theorem fold_truth {H : Type u} (cs : List (Space H)) (V : Space H) (truth : H)
    (inV : V truth) (consistent : ∀ C ∈ cs, C truth) : Fold V cs truth := by
  induction cs generalizing V with
  | nil => exact inV
  | cons C cs ih =>
      apply ih (Step V C)
      · exact ⟨inV, consistent C (by simp)⟩
      · intro D hD
        exact consistent D (by simp [hD])

def Update {S : Type u} [DecidableEq S] {A : Type v}
    (state : S → A) (key : S) (value : A) : S → A :=
  fun query => if query = key then value else state query

theorem other_scope_unchanged {S : Type u} [DecidableEq S] {A : Type v}
    (state : S → A) (key query : S) (value : A) (different : query ≠ key) :
    Update state key value query = state query := by
  simp [Update, different]

/-- Indistinguishable states cannot support one answer correct in both incompatible worlds. -/
theorem incompatible_worlds {Y : Type u} {a left right : Y}
    (different : left ≠ right) : ¬ (a = left ∧ a = right) := by
  intro both
  exact different (both.1.symm.trans both.2)

#print axioms certified_sound
#print axioms certified_under_refinement
#print axioms equivalent_certificates
#print axioms fold_truth
#print axioms other_scope_unchanged
end WitnessCL
