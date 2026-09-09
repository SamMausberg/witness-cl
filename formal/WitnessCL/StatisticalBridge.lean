/-
Deterministic accounting for audited policy versions on a declared finite
uniform context population. Failure is defined from actual population returns,
not from a claimed statistical certificate. No probability, sampling theorem,
world-model class, or deployment semantics is assumed or proved here.
-/
import Std

namespace WitnessCL.StatisticalBridge

/-- One frozen version's bounded integer return on each declared context. -/
structure Version (contexts bound : Nat) where
  returns : List (Fin (bound + 1))
  length_eq : returns.length = contexts

/-- The numerator of uniform finite-population expected return. -/
def scoreList (returns : List (Fin (bound + 1))) : Nat :=
  (returns.map Fin.val).sum

def total (version : Version contexts bound) : Nat := scoreList version.returns

/-- Tolerance is in population-total units, not an unscaled probability. -/
abbrev Promotion (contexts bound : Nat) := Nat × Version contexts bound

/-- True exactly when the accepted new version loses more than its tolerance. -/
def failed (old candidate : Version contexts bound) (tolerance : Nat) : Bool :=
  decide (total candidate + tolerance < total old)

def failureDebit (old candidate : Version contexts bound) (tolerance : Nat) : Nat :=
  if failed old candidate tolerance then 1 else 0

def finalVersion (initial : Version contexts bound) :
    List (Promotion contexts bound) → Version contexts bound
  | [] => initial
  | (_, candidate) :: rest => finalVersion candidate rest

def toleranceSum : List (Promotion contexts bound) → Nat
  | [] => 0
  | (tolerance, _) :: rest => tolerance + toleranceSum rest

def failureCount (initial : Version contexts bound) : List (Promotion contexts bound) → Nat
  | [] => 0
  | (tolerance, candidate) :: rest =>
    failureDebit initial candidate tolerance + failureCount candidate rest

theorem scoreList_bounded (returns : List (Fin (bound + 1))) :
    scoreList returns ≤ returns.length * bound := by
  induction returns with
  | nil => simp [scoreList]
  | cons value rest ih =>
    have hv : value.val ≤ bound := by omega
    simp only [scoreList, List.map_cons, List.sum_cons, List.length_cons, Nat.succ_mul]
    simp only [scoreList] at ih
    omega

theorem total_bounded (version : Version contexts bound) :
    total version ≤ contexts * bound := by
  simpa [total, version.length_eq] using scoreList_bounded version.returns

theorem failed_iff (old candidate : Version contexts bound) (tolerance : Nat) :
    failed old candidate tolerance = true ↔ total candidate + tolerance < total old := by
  simp [failed]

theorem failureDebit_zero_iff (old candidate : Version contexts bound) (tolerance : Nat) :
    failureDebit old candidate tolerance = 0 ↔ total old ≤ total candidate + tolerance := by
  simp [failureDebit, failed]

/-- Even an erroneous promotion can lose at most the declared return range. -/
theorem one_promotion_bound (old candidate : Version contexts bound) (tolerance : Nat) :
    total old ≤ total candidate + tolerance +
      contexts * bound * failureDebit old candidate tolerance := by
  by_cases h : total candidate + tolerance < total old
  · have bounded := total_bounded old
    simp [failureDebit, failed, h]
    omega
  · have ordered : total old ≤ total candidate + tolerance := by omega
    simpa [failureDebit, failed, h] using ordered

/-- This holds for every finite accepted history, however candidates were chosen. -/
theorem promotion_chain_bound (initial : Version contexts bound)
    (history : List (Promotion contexts bound)) :
    total initial ≤ total (finalVersion initial history) + toleranceSum history +
      contexts * bound * failureCount initial history := by
  induction history generalizing initial with
  | nil => simp [finalVersion, toleranceSum, failureCount]
  | cons promotion rest ih =>
    obtain ⟨tolerance, candidate⟩ := promotion
    have one := one_promotion_bound initial candidate tolerance
    have tail := ih candidate
    simp only [finalVersion, toleranceSum, failureCount, Nat.mul_add]
    omega

theorem finalVersion_append (initial : Version contexts bound)
    (earlier suffix : List (Promotion contexts bound)) :
    finalVersion initial (earlier ++ suffix) = finalVersion (finalVersion initial earlier) suffix := by
  induction earlier generalizing initial with
  | nil => rfl
  | cons promotion rest ih =>
    obtain ⟨tolerance, candidate⟩ := promotion
    simp only [List.cons_append, finalVersion, ih]

theorem toleranceSum_append (earlier suffix : List (Promotion contexts bound)) :
    toleranceSum (earlier ++ suffix) = toleranceSum earlier + toleranceSum suffix := by
  induction earlier with
  | nil => simp [toleranceSum]
  | cons promotion rest ih =>
    obtain ⟨tolerance, candidate⟩ := promotion
    simp [toleranceSum, ih, Nat.add_assoc]

theorem failureCount_append (initial : Version contexts bound)
    (earlier suffix : List (Promotion contexts bound)) :
    failureCount initial (earlier ++ suffix) = failureCount initial earlier +
      failureCount (finalVersion initial earlier) suffix := by
  induction earlier generalizing initial with
  | nil => simp [failureCount, finalVersion]
  | cons promotion rest ih =>
    obtain ⟨tolerance, candidate⟩ := promotion
    simp [failureCount, finalVersion, ih, Nat.add_assoc]

/-- Any historical version is obtained by choosing a earlier of the history. -/
theorem historical_version_bound (initial : Version contexts bound)
    (earlier suffix : List (Promotion contexts bound)) :
    total (finalVersion initial earlier) ≤ total (finalVersion initial (earlier ++ suffix)) +
      toleranceSum suffix + contexts * bound * failureCount (finalVersion initial earlier) suffix := by
  rw [finalVersion_append]
  exact promotion_chain_bound (finalVersion initial earlier) suffix

theorem historical_no_failure_bound (initial : Version contexts bound)
    (earlier suffix : List (Promotion contexts bound))
    (no_failures : failureCount initial (earlier ++ suffix) = 0) :
    total (finalVersion initial earlier) ≤
      total (finalVersion initial (earlier ++ suffix)) + toleranceSum suffix := by
  have split := failureCount_append initial earlier suffix
  have clean : failureCount (finalVersion initial earlier) suffix = 0 := by omega
  simpa [clean] using historical_version_bound initial earlier suffix

/-- Zero tolerance and no failed promotions preserve every historical population value. -/
theorem historical_no_forgetting (initial : Version contexts bound)
    (earlier suffix : List (Promotion contexts bound))
    (no_failures : failureCount initial (earlier ++ suffix) = 0)
    (zero_tolerance : toleranceSum suffix = 0) :
    total (finalVersion initial earlier) ≤ total (finalVersion initial (earlier ++ suffix)) := by
  simpa [zero_tolerance] using historical_no_failure_bound initial earlier suffix no_failures

theorem historical_tolerance_budget (initial : Version contexts bound)
    (earlier suffix : List (Promotion contexts bound)) (budget : Nat)
    (within_budget : toleranceSum suffix ≤ budget) :
    total (finalVersion initial earlier) ≤ total (finalVersion initial (earlier ++ suffix)) +
      budget + contexts * bound * failureCount (finalVersion initial earlier) suffix := by
  have h := historical_version_bound initial earlier suffix
  omega

/-- Population-level non-regression permits a particular context to regress. -/
theorem context_regression_counterexample :
    scoreList ([0, 2] : List (Fin 3)) = scoreList ([1, 1] : List (Fin 3)) ∧
      (0 : Nat) < 1 := by
  decide

end WitnessCL.StatisticalBridge
