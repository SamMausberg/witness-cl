/- Deterministic differential oracle; no inputs, network, or environment actions. -/
import WitnessCL.Executable
import Lean

open WitnessCL.Executable

private def binary (n : Nat) : Fin 2 := ⟨n % 2, Nat.mod_lt _ (by decide)⟩

/-- All 4^4 labelled binary transducers, in row-major least-significant-digit order. -/
private def machine (id : Nat) : Machine 2 2 2 :=
  ⟨fun state action =>
    let digit := id / 4 ^ (state.val * 2 + action.val) % 4
    (binary (digit / 2), binary digit)⟩

private def machineId (m : Machine 2 2 2) : Nat :=
  ((List.range 4).map fun slot =>
    let edge := m.table (binary (slot / 2)) (binary slot)
    (edge.1.val * 2 + edge.2.val) * 4 ^ slot).sum

private def wordsOfLength : Nat → List (List (Fin 2))
  | 0 => [[]]
  | n + 1 => (wordsOfLength n).flatMap (fun word => [word ++ [0], word ++ [1]])

private def jsonTrace (trace : Trace 2 2) : Lean.Json :=
  Lean.toJson (trace.map fun event => [event.1.val, event.2.val])

private def row (fields : List (String × Lean.Json)) : IO Unit :=
  IO.println (Lean.Json.mkObj fields).compress

/-- Machine.run/action-word and filterHistory fixtures; bounded exhaustive small case. -/
def main : IO Unit := do
  row [("kind", Lean.toJson "header"), ("schema", Lean.toJson "witness-cl-executable-v1"),
       ("states", Lean.toJson (2 : Nat)), ("actions", Lean.toJson (2 : Nat)),
       ("outputs", Lean.toJson (2 : Nat)), ("machines", Lean.toJson (256 : Nat)),
       ("max_word_length", Lean.toJson (4 : Nat))]
  let models := (List.range 256).map machine
  let words := (List.range 5).flatMap wordsOfLength
  let probeWords : List (List (Fin 2)) := [[0, 1], [1, 0], [0, 0, 1, 1], [1, 1, 0, 0]]
  for id in List.range 256 do
    let truth := machine id
    for word in words do
      let result := runFrom truth 0 word
      row [("kind", Lean.toJson "trace"), ("machine", Lean.toJson id),
           ("word", Lean.toJson (word.map Fin.val)),
           ("final_state", Lean.toJson result.1.val), ("trace", jsonTrace result.2)]
    for count in [1, 2, 3, 4] do
      let evidence := (probeWords.take count).map (run truth)
      let survivors := filterHistory models evidence
      row [("kind", Lean.toJson "filter"), ("truth", Lean.toJson id),
           ("history", Lean.Json.arr (evidence.map jsonTrace).toArray),
           ("survivors", Lean.toJson (survivors.map machineId))]
