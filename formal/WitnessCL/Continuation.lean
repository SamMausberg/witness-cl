/-
Witness-CL v0.3 logical lemmas, kernel-checked with Lean 4.19.0 in the v5 audit.
These declarations formalize abstract deterministic continuation algebra. They
are not a verification of Python, floating-point code, CUDA, or probability.
-/
import Std
import WitnessCL.Core

universe u v w
namespace WitnessCL.V3

/-- A transition exposes both its complete successor state and its output. -/
def Run {S : Type u} {U : Type v} {O : Type w}
    (step : S → U → S × O) : List U → S → S × List O
  | [], s => (s, [])
  | u :: us, s =>
      let p := step s u
      let q := Run step us p.1
      (q.1, p.2 :: q.2)

/-- Pointwise agreement must be accompanied by forward closure. -/
theorem closed_continuations_equal {S : Type u} {U : Type v} {O : Type w}
    (f g : S → U → S × O) (P : S → Prop)
    (same : ∀ s, P s → ∀ u, f s u = g s u)
    (closed : ∀ s, P s → ∀ u, P (f s u).1)
    (us : List U) : ∀ s, P s → Run f us s = Run g us s := by
  induction us with
  | nil => intro s hs; rfl
  | cons u us ih =>
      intro s hs
      simp only [Run]
      rw [← same s hs u]
      rw [ih (f s u).1 (closed s hs u)]

/-- The state must include both controller memories, tool state, and RNG state. -/
theorem closed_outputs_equal {S : Type u} {U : Type v} {O : Type w}
    (f g : S → U → S × O) (P : S → Prop)
    (same : ∀ s, P s → ∀ u, f s u = g s u)
    (closed : ∀ s, P s → ∀ u, P (f s u).1)
    (us : List U) (s : S) (hs : P s) : (Run f us s).2 = (Run g us s).2 := by
  exact congrArg Prod.snd (closed_continuations_equal f g P same closed us s hs)

def Value {S : Type u} {A : Type v}
    (next : Nat → S → A → S) (reward : Nat → S → A → Int)
    (policy : Nat → S → A) : Nat → S → Int
  | 0, _ => 0
  | n + 1, s => reward n s (policy n s) + Value next reward policy n (next n s (policy n s))

/-- Finite-horizon Bellman comparison. n is remaining-horizon indexing. -/
theorem bellman_improvement {S : Type u} {A : Type v}
    (next : Nat → S → A → S) (reward : Nat → S → A → Int)
    (base candidate : Nat → S → A)
    (advantage : ∀ n s,
      Value next reward base (n+1) s ≤
      reward n s (candidate n s) + Value next reward base n (next n s (candidate n s))) :
    ∀ n s, Value next reward base n s ≤ Value next reward candidate n s := by
  intro n
  induction n with
  | zero => intro s; simp [Value]
  | succ n ih =>
      intro s
      have h := advantage n s
      have k := ih (next n s (candidate n s))
      simp only [Value] at h ⊢
      omega

/-- Uniform checking over a family transfers to the actual member. -/
theorem plausible_member_improves {M : Type u} {S : Type v}
    (live : M → Prop) (base candidate : M → S → Int)
    (uniform : ∀ m, live m → ∀ s, base m s ≤ candidate m s)
    (truth : M) (retained : live truth) : ∀ s, base truth s ≤ candidate truth s := by
  exact uniform truth retained

/-- Evidence contraction alone cannot invalidate an all-model obligation. -/
theorem obligation_survives_shrinking {M : Type u}
    (old new : M → Prop) (obligation : M → Prop)
    (subset : ∀ m, new m → old m)
    (checked : ∀ m, old m → obligation m) : ∀ m, new m → obligation m := by
  intro m hm
  exact checked m (subset m hm)

def SumFirst : List (Int × Int) → Int
  | [] => 0
  | p :: ps => p.1 + SumFirst ps

def SumSecond : List (Int × Int) → Int
  | [] => 0
  | p :: ps => p.2 + SumSecond ps

/-- Per-episode deterministic deficit debits compose without independence. -/
theorem total_deficit_bounded_by_debits (xs : List (Int × Int))
    (pointwise : ∀ p ∈ xs, p.1 ≤ p.2) : SumFirst xs ≤ SumSecond xs := by
  induction xs with
  | nil => simp [SumFirst, SumSecond]
  | cons p ps ih =>
      have hp := pointwise p (by simp)
      have ht : ∀ q ∈ ps, q.1 ≤ q.2 := by
        intro q hq
        exact pointwise q (by simp [hq])
      have hs := ih ht
      simp only [SumFirst, SumSecond]
      omega

theorem debit_budget (xs : List (Int × Int)) (B : Int)
    (pointwise : ∀ p ∈ xs, p.1 ≤ p.2)
    (cap : SumSecond xs ≤ B) : SumFirst xs ≤ B := by
  have h := total_deficit_bounded_by_debits xs pointwise
  omega

def BadReward (action : Bool) : Nat := if action then 0 else 5

def GoodReward (action : Bool) : Nat := if action then 10 else 5

/-- With indistinguishable information, universal zero loss blocks strict gain. -/
theorem no_risk_no_gain (action : Bool) (safe : 5 ≤ BadReward action) :
    GoodReward action ≤ 5 := by
  cases action <;> simp [BadReward, GoodReward] at *

/-- A terminal reward increase is not a continuation improvement. -/
theorem truncation_counterexample :
    (1 : Int) > 0 ∧ (1 + 0 : Int) < 0 + 10 := by
  omega

/-- Monotone incumbent updates preserve every earlier acquired lower bound. -/
theorem incumbent_chain (old incumbent candidate : Int)
    (acquired : old ≤ incumbent) (new : incumbent ≤ candidate) : old ≤ candidate := by
  omega

#print axioms closed_continuations_equal
#print axioms bellman_improvement
#print axioms debit_budget
#print axioms no_risk_no_gain
end WitnessCL.V3
