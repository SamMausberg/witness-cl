/-
Witness-CL v0.2 logical lemmas, kernel-checked with Lean 4.19.0 in the v5 audit.
No placeholders or custom axioms. These results do not formalize probability,
real-matrix projection, interpreter semantics, or the Python/CUDA implementation.
-/
import WitnessCL.Core
import Std

universe u v w
namespace WitnessCL.V2

def Replay {H : Type u} (base : H → Prop) (events : List (H → Prop)) : H → Prop :=
  fun h => base h ∧ ∀ c ∈ events, c h

def Union {H : Type u} (a b : H → Prop) : H → Prop := fun h => a h ∨ b h

theorem growth_replays_every_event {H : Type u} {a b : H → Prop}
    {events : List (H → Prop)} {h : H}
    (live : Replay (Union a b) events h) : ∀ c ∈ events, c h := by
  exact live.2

theorem growth_decomposition {H : Type u} (a b : H → Prop)
    (events : List (H → Prop)) (h : H) :
    Replay (Union a b) events h ↔ Replay a events h ∨ Replay b events h := by
  constructor
  · intro hh
    cases hh.1 with
    | inl ha => exact Or.inl ⟨ha, hh.2⟩
    | inr hb => exact Or.inr ⟨hb, hh.2⟩
  · intro hh
    cases hh with
    | inl ha => exact ⟨Or.inl ha.1, ha.2⟩
    | inr hb => exact ⟨Or.inr hb.1, hb.2⟩

theorem old_survivors_survive_class_growth {H : Type u} {a b : H → Prop}
    {events : List (H → Prop)} {h : H} (old : Replay a events h) :
    Replay (Union a b) events h := by
  exact ⟨Or.inl old.1, old.2⟩

theorem expanded_survivor_truth {H : Type u} {a b : H → Prop}
    {events : List (H → Prop)} {truth : H} (member : a truth ∨ b truth)
    (consistent : ∀ c ∈ events, c truth) : Replay (Union a b) events truth := by
  exact ⟨member, consistent⟩

/-- One discarded observation can become essential when a new rule is introduced. -/
theorem witness_growth_counterexample :
    (∀ h : Bool, h = false → h = false) ∧
    Replay (fun _ : Bool => True) [] true ∧
    ¬ Replay (fun _ : Bool => True) [fun h => h = false] true := by
  constructor
  · intro h hh; exact hh
  · constructor
    · constructor
      · trivial
      · intro c hc; cases hc
    · intro hh
      have bad : true = false := hh.2 (fun h => h = false) (by simp)
      cases bad

def Patch {X : Type u} {Y : Type v} (guard : X → Bool)
    (base candidate : X → Y) : X → Y :=
  fun x => if guard x then candidate x else base x

theorem patch_outside {X : Type u} {Y : Type v}
    (guard : X → Bool) (base candidate : X → Y) (x : X)
    (outside : guard x = false) : Patch guard base candidate x = base x := by
  simp [Patch, outside]

theorem patch_inside {X : Type u} {Y : Type v}
    (guard : X → Bool) (base candidate : X → Y) (x : X)
    (inside : guard x = true) : Patch guard base candidate x = candidate x := by
  simp [Patch, inside]

theorem protected_domain_unchanged {X : Type u} {Y : Type v}
    (protectedDomain : X → Prop) (guard : X → Bool) (base candidate : X → Y)
    (separate : ∀ x, protectedDomain x → guard x = false) :
    ∀ x, protectedDomain x → Patch guard base candidate x = base x := by
  intro x hx
  exact patch_outside guard base candidate x (separate x hx)

theorem multiple_patches_preserve_outside {X : Type u} {Y : Type v}
    (g₁ g₂ : X → Bool) (base c₁ c₂ : X → Y) (x : X)
    (h₁ : g₁ x = false) (h₂ : g₂ x = false) :
    Patch g₂ (Patch g₁ base c₁) c₂ x = base x := by
  simp [Patch, h₁, h₂]

def Disagreement {X : Type u} {Y : Type v} [DecidableEq Y]
    (base candidate : X → Y) (x : X) : Bool := decide (base x ≠ candidate x)

theorem disagreement_patch_is_candidate {X : Type u} {Y : Type v} [DecidableEq Y]
    (base candidate : X → Y) (x : X) :
    Patch (Disagreement base candidate) base candidate x = candidate x := by
  by_cases same : base x = candidate x
  · simp [Patch, Disagreement, same]
  · simp [Patch, Disagreement, same]

theorem archive_output_unchanged {Key : Type u} [DecidableEq Key]
    {X : Type v} {Y : Type w} (archive : Key → X → Y)
    (newKey oldKey : Key) (newRule : X → Y) (x : X)
    (different : oldKey ≠ newKey) :
    WitnessCL.Update archive newKey newRule oldKey x = archive oldKey x := by
  simp [WitnessCL.Update, different]

def AddResidual {X : Type u} (base residual : X → Int) (x : X) : Int :=
  base x + residual x

theorem annihilated_residual_preserves_output {X : Type u}
    (base residual : X → Int) (x : X) (zero : residual x = 0) :
    AddResidual base residual x = base x := by
  simp [AddResidual, zero]

theorem residual_preserves_protected_domain {X : Type u}
    (protectedDomain : X → Prop) (base residual : X → Int)
    (annihilates : ∀ x, protectedDomain x → residual x = 0) :
    ∀ x, protectedDomain x → AddResidual base residual x = base x := by
  intro x hx
  exact annihilated_residual_preserves_output base residual x (annihilates x hx)

/-- Algebraic reason that zero differences do not change multiplicative wealth. -/
theorem zero_difference_is_neutral (capital stake : Int) :
    capital * (1 + stake * 0) = capital := by
  simp

def Multiply : Int → List Int → Int
  | w, [] => w
  | w, f :: fs => Multiply (w * f) fs

theorem inserting_neutral_factor (w : Int) (fs : List Int) :
    Multiply w (1 :: fs) = Multiply w fs := by
  simp [Multiply]

theorem filter_one_factors (fs : List Int) (w : Int) :
    Multiply w (fs.filter (fun f => f != 1)) = Multiply w fs := by
  induction fs generalizing w with
  | nil => rfl
  | cons f fs ih =>
    by_cases hf : f = 1
    · subst f
      simpa [Multiply] using ih w
    · have hne : (f != 1) = true := by simpa using hf
      simpa [List.filter, hne, Multiply] using ih (w * f)

#print axioms growth_decomposition
#print axioms witness_growth_counterexample
#print axioms protected_domain_unchanged
#print axioms archive_output_unchanged
#print axioms residual_preserves_protected_domain
#print axioms filter_one_factors
end WitnessCL.V2
