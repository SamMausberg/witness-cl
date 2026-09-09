/- Bounded deterministic v7 accounting fixture, with no sampling or deployment. -/
import WitnessCL.StatisticalBridge
import Lean

open WitnessCL.StatisticalBridge

private def ternary (n : Nat) : Fin 3 := ⟨n % 3, Nat.mod_lt _ (by decide)⟩

private def version (id : Nat) : Version 2 2 :=
  ⟨[ternary id, ternary (id / 3)], by rfl⟩

private def row (fields : List (String × Lean.Json)) : IO Unit :=
  IO.println (Lean.Json.mkObj fields).compress

/-- All two-promotion chains of two-context returns in 0..2 and tolerances 0..1. -/
def main : IO Unit := do
  row [("kind", Lean.toJson "header"), ("schema", Lean.toJson "witness-cl-statistical-bridge-v1"),
       ("contexts", Lean.toJson (2 : Nat)), ("bound", Lean.toJson (2 : Nat)),
       ("versions", Lean.toJson (9 : Nat)), ("promotions", Lean.toJson (2 : Nat))]
  for i in List.range 9 do
    for j in List.range 9 do
      for k in List.range 9 do
        for e₁ in List.range 2 do
          for e₂ in List.range 2 do
            let initial := version i
            let middle := version j
            let last := version k
            let history : List (Promotion 2 2) := [(e₁, middle), (e₂, last)]
            let suffix : List (Promotion 2 2) := [(e₂, last)]
            let finalTotal := total (finalVersion initial history)
            let suffixTolerances := [toleranceSum history, toleranceSum suffix, 0]
            let suffixFailures := [failureCount initial history, failureCount middle suffix, 0]
            row [("kind", Lean.toJson "chain"), ("versions", Lean.toJson [i, j, k]),
                 ("returns", Lean.toJson ([initial, middle, last].map fun v => v.returns.map Fin.val)),
                 ("totals", Lean.toJson ([initial, middle, last].map total)),
                 ("tolerances", Lean.toJson [e₁, e₂]),
                 ("failed", Lean.toJson [failed initial middle e₁, failed middle last e₂]),
                 ("final_total", Lean.toJson finalTotal),
                 ("suffix_tolerances", Lean.toJson suffixTolerances),
                 ("suffix_failures", Lean.toJson suffixFailures),
                 ("historical_bounds", Lean.toJson
                   (List.zipWith (fun e bad => finalTotal + e + 4 * bad)
                     suffixTolerances suffixFailures))]
