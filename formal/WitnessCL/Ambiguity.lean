/-
Witness-CL v0.5: an information obstruction for deterministic decisions.
The history value must include every observation and memory available to the
policy. This does not model randomized expected-return or noisy-history bounds.
-/
import Std

universe u v w
namespace WitnessCL.V5

/-- If two worlds yield the same available history, and every strict gain in one
world would lose value in the other, a decision safe in the latter cannot gain
in the former. The result concerns the current information state, not every
future state after a potentially informative experiment. -/
theorem safe_policy_cannot_gain_under_aliasing
    {M : Type u} {History : Type v} {Action : Type w}
    (history : M → History) (policy : History → Action)
    (value : M → Action → Int) (incumbent : Action) (adverse favorable : M)
    (aliased : history adverse = history favorable)
    (conflict : ∀ a, value favorable incumbent < value favorable a →
      value adverse a < value adverse incumbent)
    (safe : value adverse incumbent ≤ value adverse (policy (history adverse))) :
    value favorable (policy (history favorable)) ≤ value favorable incumbent := by
  have noGain : ¬ value favorable incumbent < value favorable (policy (history favorable)) := by
    intro gain
    have loss := conflict (policy (history favorable)) gain
    rw [← aliased] at loss
    omega
  omega

#print axioms safe_policy_cannot_gain_under_aliasing
end WitnessCL.V5
