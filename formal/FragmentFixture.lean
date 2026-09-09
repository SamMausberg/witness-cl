/- Prepared-request compiler correspondence; no database or model is run. -/
import WitnessCL.TypedFragments
import Lean

open WitnessCL.TypedFragments

private def row (fields : List (String × Lean.Json)) : IO Unit :=
  IO.println (Lean.Json.mkObj fields).compress

private def scalarJson : Scalar kind → Lean.Json
  | .integer value => Lean.toJson value
  | .text value => Lean.toJson value
  | .null => Lean.Json.null
  | .real bits => Lean.Json.mkObj [("binary64_bits", Lean.toJson bits.toNat)]

private def kindName : ScalarType → String
  | .integer => "integer"
  | .text => "text"
  | .null => "null"
  | .real => "real"

private def requestJson (request : Request) : Lean.Json :=
  Lean.Json.mkObj [("sql", Lean.toJson request.sql),
    ("parameters", Lean.toJson (request.parameters.map fun p =>
      Lean.Json.mkObj [("name", Lean.toJson p.name), ("kind", Lean.toJson (kindName p.kind)),
        ("value", scalarJson p.value)]))]

private def assignment (amount : Int) (label : String) : Assignment
  | .integer, _ => .integer amount
  | .text, _ => .text label
  | .null, _ => .null
  | .real, _ => .real 4602678819172646912 -- exact bits of binary64 0.5

private def param (kind : ScalarType) (name : String) : Fragment :=
  .parameter kind name (.hole name)

private def source : Nat → Fragment
  | 0 => .append (.text "SELECT ") (.append (param .integer "amount")
      (.append (.text " AS amount, ") (.append (param .text "label") (.text " AS label"))))
  | 1 => .append (.text "SELECT ") (.append (param .integer "amount")
      (.append (.text " + ") (.append (param .integer "amount")
        (.append (.text " AS amount, ':label' AS literal, ")
          (.append (param .text "label") (.text " AS label"))))))
  | 2 => .append (.text "SELECT ") (.append (param .real "real")
      (.append (.text " AS amount, ") (.append (param .null "nil")
        (.append (.text " AS missing, ") (.append (param .text "label") (.text " AS label"))))))
  | _ => .append (.text "SELECT ':label'';--' AS literal, ")
      (.append (param .integer "amount") (.append (.text " AS amount, ")
        (.append (param .text "label") (.text " AS label"))))

private def innerNames (id : Nat) (name : String) : String :=
  if id == 2 then
    if name == "label" then "wcl_inner_0" else
      if name == "nil" then "wcl_inner_1" else "wcl_inner_2"
  else if name == "amount" then "wcl_inner_0" else "wcl_inner_1"

private def outer : Fragment :=
  .append (.text "SELECT amount + ")
    (.append (param .integer "amount") (.text " AS combined FROM saved"))

def main : IO Unit := do
  row [("kind", Lean.toJson "header"), ("schema", Lean.toJson "witness-cl-typed-fragments-v1"),
    ("source_count", Lean.toJson (4 : Nat)), ("amounts", Lean.toJson ([-2, 0, 7] : List Int)),
    ("labels", Lean.toJson ["plain", "O'Reilly", ":amount'); DROP TABLE sentinel; --"])]
  for id in List.range 4 do
    for amount in ([-2, 0, 7] : List Int) do
      for label in ["plain", "O'Reilly", ":amount'); DROP TABLE sentinel; --"] do
        let witness := assignment amount label
        let later := assignment 999 "changed"
        let fragment := source id
        let expanded := bindWitness witness fragment
        let composite := compose "saved" (innerNames id) (fun _ => "wcl_outer_0")
          expanded (bindWitness (assignment 3 "outer") outer)
        row [("kind", Lean.toJson "request"), ("source_id", Lean.toJson id),
          ("amount", Lean.toJson amount), ("label", Lean.toJson label),
          ("original", requestJson (compile witness fragment)),
          ("expanded", requestJson (compile later expanded)),
          ("changed", requestJson (compile later fragment)),
          ("composition", requestJson (compile later composite))]
  row [("kind", Lean.toJson "guard_counterexample"),
    ("observed_amount", Lean.toJson (0 : Int)), ("possible_scales", Lean.toJson ([1, 100] : List Int)),
    ("future_amount", Lean.toJson (1 : Int)), ("guard", Lean.toJson true),
    ("guarded_answer", Lean.toJson (guarded (some true) (some (1 : Int)) 100)),
    ("ordinary_answer", Lean.toJson (100 : Int)),
    ("rejected_answer", Lean.toJson (guarded (some false) (some (1 : Int)) 100))]
