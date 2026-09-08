/-
Executable finite transducer semantics and evidence filtering. These definitions
compute transitions and traces; the filtering proofs do not assume an opaque
consistency oracle. State zero is the reset state. Finite alphabets exclude
illegal transitions and actions by construction. No stochastic or drift model.
-/
import Std

namespace WitnessCL.Executable

/-- A total deterministic table over finite state, action, and output sets. -/
structure Machine (states actions outputs : Nat) where
  table : Fin states → Fin actions → Fin states × Fin outputs

abbrev Trace (actions outputs : Nat) := List (Fin actions × Fin outputs)

/-- Execute every action and retain both the final state and observable trace. -/
def runFrom (m : Machine states actions outputs) :
    Fin states → List (Fin actions) → Fin states × Trace actions outputs
  | s, [] => (s, [])
  | s, a :: word =>
    let edge := m.table s a
    let rest := runFrom m edge.1 word
    (rest.1, (a, edge.2) :: rest.2)

/-- Each episode resets to state zero; at least one state is required. -/
def run (m : Machine (states + 1) actions outputs) (word : List (Fin actions)) :
    Trace actions outputs := (runFrom m 0 word).2

def traceMatches (m : Machine (states + 1) actions outputs)
    (trace : Trace actions outputs) : Bool :=
  decide (run m (trace.map Prod.fst) = trace)

def filterTrace (models : List (Machine (states + 1) actions outputs))
    (trace : Trace actions outputs) : List (Machine (states + 1) actions outputs) :=
  models.filter (fun m => traceMatches m trace)

def filterHistory (models : List (Machine (states + 1) actions outputs)) :
    List (Trace actions outputs) → List (Machine (states + 1) actions outputs)
  | [] => models
  | trace :: history => filterHistory (filterTrace models trace) history

theorem runFrom_actions (m : Machine states actions outputs)
    (word : List (Fin actions)) (s : Fin states) :
    (runFrom m s word).2.map Prod.fst = word := by
  induction word generalizing s with
  | nil => rfl
  | cons a word ih => simp [runFrom, ih]

theorem run_actions (m : Machine (states + 1) actions outputs)
    (word : List (Fin actions)) : (run m word).map Prod.fst = word := by
  exact runFrom_actions m word 0

theorem runFrom_append (m : Machine states actions outputs)
    (left right : List (Fin actions)) (s : Fin states) :
    runFrom m s (left ++ right) =
      let first := runFrom m s left
      let last := runFrom m first.1 right
      (last.1, first.2 ++ last.2) := by
  induction left generalizing s with
  | nil => simp [runFrom]
  | cons a left ih => simp [runFrom, ih]

theorem traceMatches_iff (m : Machine (states + 1) actions outputs)
    (trace : Trace actions outputs) :
    traceMatches m trace = true ↔ run m (trace.map Prod.fst) = trace := by
  simp [traceMatches]

theorem mem_filterTrace_iff (models : List (Machine (states + 1) actions outputs))
    (m : Machine (states + 1) actions outputs) (trace : Trace actions outputs) :
    m ∈ filterTrace models trace ↔ m ∈ models ∧ run m (trace.map Prod.fst) = trace := by
  simp [filterTrace, traceMatches]

theorem filterTrace_retains_executed_truth
    (models : List (Machine (states + 1) actions outputs))
    (truth : Machine (states + 1) actions outputs) (word : List (Fin actions))
    (member : truth ∈ models) : truth ∈ filterTrace models (run truth word) := by
  rw [mem_filterTrace_iff]
  exact ⟨member, by rw [run_actions]⟩

theorem mem_filterHistory_iff (history : List (Trace actions outputs))
    (models : List (Machine (states + 1) actions outputs))
    (m : Machine (states + 1) actions outputs) :
    m ∈ filterHistory models history ↔
      m ∈ models ∧ ∀ trace ∈ history, run m (trace.map Prod.fst) = trace := by
  induction history generalizing models with
  | nil => simp [filterHistory]
  | cons trace history ih =>
    simp only [filterHistory, ih, mem_filterTrace_iff, List.mem_cons, forall_eq_or_imp]
    constructor
    · rintro ⟨⟨member, head⟩, tail⟩
      exact ⟨member, head, tail⟩
    · rintro ⟨member, head, tail⟩
      exact ⟨⟨member, head⟩, tail⟩

/-- Direct execution, rather than a consistency premise, supplies all evidence. -/
theorem filterHistory_retains_executed_truth
    (models : List (Machine (states + 1) actions outputs))
    (truth : Machine (states + 1) actions outputs) (words : List (List (Fin actions)))
    (member : truth ∈ models) :
    truth ∈ filterHistory models (words.map (run truth)) := by
  rw [mem_filterHistory_iff]
  refine ⟨member, ?_⟩
  intro trace htrace
  obtain ⟨word, _, rfl⟩ := List.mem_map.mp htrace
  rw [run_actions]

/-- Every surviving machine reproduces every supplied actual episode. -/
theorem executed_history_characterization
    (models : List (Machine (states + 1) actions outputs))
    (truth candidate : Machine (states + 1) actions outputs)
    (words : List (List (Fin actions))) :
    candidate ∈ filterHistory models (words.map (run truth)) ↔
      candidate ∈ models ∧ ∀ word ∈ words, run candidate word = run truth word := by
  rw [mem_filterHistory_iff]
  constructor
  · rintro ⟨member, matched⟩
    refine ⟨member, ?_⟩
    intro word hword
    have h := matched (run truth word) (List.mem_map.mpr ⟨word, hword, rfl⟩)
    simpa [run_actions] using h
  · rintro ⟨member, matched⟩
    refine ⟨member, ?_⟩
    intro trace htrace
    obtain ⟨word, hword, rfl⟩ := List.mem_map.mp htrace
    simpa [run_actions] using matched word hword

theorem filterHistory_subset (models : List (Machine (states + 1) actions outputs))
    (history : List (Trace actions outputs)) (m : Machine (states + 1) actions outputs)
    (member : m ∈ filterHistory models history) : m ∈ models := by
  exact (mem_filterHistory_iff history models m).mp member |>.1

theorem filterHistory_append (models : List (Machine (states + 1) actions outputs))
    (left right : List (Trace actions outputs)) :
    filterHistory models (left ++ right) = filterHistory (filterHistory models left) right := by
  induction left generalizing models with
  | nil => rfl
  | cons trace left ih => simp only [List.cons_append, filterHistory, ih]

/-- A contradictory trace really eliminates a model; this is also the noise limit. -/
theorem incompatible_evidence_eliminates
    (models : List (Machine (states + 1) actions outputs))
    (m : Machine (states + 1) actions outputs) (trace : Trace actions outputs)
    (different : run m (trace.map Prod.fst) ≠ trace) :
    m ∉ filterTrace models trace := by
  intro member
  exact different ((mem_filterTrace_iff models m trace).mp member).2

end WitnessCL.Executable
