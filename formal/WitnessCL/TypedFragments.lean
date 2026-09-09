/-
Typed prepared-query fragments. Arbitrary SQL chunks are transported as data;
this is a proof of the request compiler, not a formalization of SQLite parsing,
authorization, operational semantics, or the truth of learned domain rules.
-/
import Std

namespace WitnessCL.TypedFragments

inductive ScalarType where
  | integer | text | null | real
  deriving DecidableEq, Repr

/-- Real values are transported as exact binary64 bits; finiteness is checked
by the Python boundary, not inferred from this denotation-preserving theorem. -/
inductive Scalar : ScalarType → Type where
  | integer : Int → Scalar .integer
  | text : String → Scalar .text
  | null : Scalar .null
  | real : UInt64 → Scalar .real
  deriving Repr

inductive Argument (kind : ScalarType) where
  | literal : Scalar kind → Argument kind
  | hole : String → Argument kind

abbrev Assignment := (kind : ScalarType) → String → Scalar kind
abbrev Substitution := (kind : ScalarType) → String → Argument kind

def evalArgument (assignment : Assignment) : Argument kind → Scalar kind
  | .literal value => value
  | .hole name => assignment kind name

def substituteArgument (substitution : Substitution) : Argument kind → Argument kind
  | .literal value => .literal value
  | .hole name => substitution kind name

def substitutedAssignment (substitution : Substitution) (assignment : Assignment) : Assignment :=
  fun kind name => evalArgument assignment (substitution kind name)

/-- The slot name is output syntax. The argument supplies its typed value.
No value, including a text value containing SQL, is concatenated into SQL text. -/
inductive Fragment where
  | text : String → Fragment
  | parameter : (kind : ScalarType) → String → Argument kind → Fragment
  | append : Fragment → Fragment → Fragment

structure Parameter where
  kind : ScalarType
  name : String
  value : Scalar kind

structure Request where
  sql : String
  parameters : List Parameter

def combine (left right : Request) : Request :=
  ⟨left.sql ++ right.sql, left.parameters ++ right.parameters⟩

/-- Parameter occurrences retain source order. Repeated occurrences have the
same value under the well-typed named environment. Python passes the equivalent
deduplicated name map, checked by the executable correspondence tests. -/
def compile (assignment : Assignment) : Fragment → Request
  | .text value => ⟨value, []⟩
  | .parameter kind name argument =>
      ⟨":" ++ name, [⟨kind, name, evalArgument assignment argument⟩]⟩
  | .append left right => combine (compile assignment left) (compile assignment right)

def substitute (substitution : Substitution) : Fragment → Fragment
  | .text value => .text value
  | .parameter kind name argument => .parameter kind name (substituteArgument substitution argument)
  | .append left right => .append (substitute substitution left) (substitute substitution right)

def bindWitness (witness : Assignment) (fragment : Fragment) : Fragment :=
  substitute (fun kind name => .literal (witness kind name)) fragment

/-- Namespace only output parameter nodes. Chunks, including quoted colons,
are never searched or replaced during composition. -/
def rename (names : String → String) : Fragment → Fragment
  | .text value => .text value
  | .parameter kind name argument => .parameter kind (names name) argument
  | .append left right => .append (rename names left) (rename names right)

def parameterValues (request : Request) : List ((kind : ScalarType) × Scalar kind) :=
  request.parameters.map fun parameter => ⟨parameter.kind, parameter.value⟩

/-- The alias and SQL are already validated by the Python boundary. The two
namespace maps must be fresh for SQLite's shared prepared-parameter namespace. -/
def compose (alias : String) (innerNames outerNames : String → String)
    (inner outer : Fragment) : Fragment :=
  .append (.text ("WITH \"" ++ alias ++ "\" AS ("))
    (.append (rename innerNames inner)
      (.append (.text ") ") (rename outerNames outer)))

theorem argument_substitution_correct (substitution : Substitution) (assignment : Assignment)
    (argument : Argument kind) :
    evalArgument assignment (substituteArgument substitution argument) =
      evalArgument (substitutedAssignment substitution assignment) argument := by
  cases argument <;> rfl

/-- A structural substitution theorem for all fragments and all typed values,
not an equality inferred from a finite collection of observed query answers. -/
theorem compilation_substitution_correct (substitution : Substitution) (assignment : Assignment)
    (fragment : Fragment) :
    compile assignment (substitute substitution fragment) =
      compile (substitutedAssignment substitution assignment) fragment := by
  induction fragment with
  | text value => rfl
  | parameter kind name argument =>
      simp only [substitute, compile, argument_substitution_correct]
  | append left right leftIH rightIH =>
      simp only [substitute, compile, leftIH, rightIH]

/-- Replaying the original witness produces exactly the original request.
Other assignments cannot change the literals already captured in that witness. -/
theorem witness_request_exact (witness later : Assignment) (fragment : Fragment) :
    compile later (bindWitness witness fragment) = compile witness fragment := by
  simpa [bindWitness, substitutedAssignment, evalArgument] using
    compilation_substitution_correct (fun kind name => .literal (witness kind name)) later fragment

/-- Binding contents cannot inject SQL syntax through a typed parameter. -/
theorem sql_independent_of_values (first second : Assignment) (fragment : Fragment) :
    (compile first fragment).sql = (compile second fragment).sql := by
  induction fragment with
  | text value => rfl
  | parameter kind name argument => rfl
  | append left right leftIH rightIH => simp [compile, combine, leftIH, rightIH]

theorem renaming_preserves_parameter_values (names : String → String)
    (assignment : Assignment) (fragment : Fragment) :
    parameterValues (compile assignment (rename names fragment)) =
      parameterValues (compile assignment fragment) := by
  induction fragment with
  | text value => rfl
  | parameter kind name argument => rfl
  | append left right leftIH rightIH =>
      simp only [rename, compile, parameterValues, combine, List.map_append] at *
      rw [leftIH, rightIH]

/-- Composition is exactly the explicit CTE expansion and occurrence bindings.
It does not assert that an arbitrary outer SELECT asks the intended question. -/
theorem composition_expansion_exact (alias : String) (innerNames outerNames : String → String)
    (assignment : Assignment) (inner outer : Fragment) :
    compile assignment (compose alias innerNames outerNames inner outer) =
      ⟨"WITH \"" ++ alias ++ "\" AS (" ++
        ((compile assignment (rename innerNames inner)).sql ++
          (") " ++ (compile assignment (rename outerNames outer)).sql)),
       (compile assignment (rename innerNames inner)).parameters ++
          (compile assignment (rename outerNames outer)).parameters⟩ := by
  simp [compose, compile, combine]

/-- Same fixed executor, database, request and binding imply the same result.
SQLite behavior itself is intentionally not an axiom of this theorem. -/
theorem witness_executor_result_exact (executor : Request → Database → Result)
    (database : Database) (witness later : Assignment) (fragment : Fragment) :
    executor (compile later (bindWitness witness fragment)) database =
      executor (compile witness fragment) database := by
  rw [witness_request_exact]

/-- The modeled capability is a read request; it provides no write operation.
Real SQLite enforcement is a separate authorizer/transaction boundary. -/
def readOnlyRun (executor : Request → Database → Result) (request : Request)
    (database : Database) : Database × Result := (database, executor request database)

theorem readOnlyRun_preserves_database (executor : Request → Database → Result)
    (request : Request) (database : Database) :
    (readOnlyRun executor request database).1 = database := by
  rfl

/-- A rejected, unavailable or failed check/candidate uses the ordinary answer. -/
def guarded (check : Option Bool) (attempt : Option Answer) (ordinary : Answer) : Answer :=
  match check, attempt with
  | some true, some answer => answer
  | _, _ => ordinary

theorem failed_guard_uses_fallback (attempt : Option Answer) (ordinary : Answer)
    (check : Option Bool) (rejected : check ≠ some true) :
    guarded check attempt ordinary = ordinary := by
  cases check with
  | none => rfl
  | some value => cases value <;> simp_all [guarded]

/-- Retention needs correctness on every protected accepted execution, not
merely agreement on earlier observed cases. -/
theorem conditional_pointwise_retention (check : State → Option Bool)
    (attempt : State → Option Answer) (ordinary : State → Answer)
    (accepted_correct : ∀ state answer,
      check state = some true → attempt state = some answer → answer = ordinary state) :
    ∀ state, guarded (check state) (attempt state) (ordinary state) = ordinary state := by
  intro state
  cases hc : check state with
  | none => simp [guarded, hc]
  | some value =>
      cases value with
      | false => simp [guarded, hc]
      | true =>
          cases ha : attempt state with
          | none => simp [guarded, hc, ha]
          | some answer => simpa [guarded, hc, ha] using accepted_correct state answer hc ha

/-- Seeing a zero-valued price cannot identify cents versus dollars. Two
different semantic scales produce the same permitted observation. -/
theorem zero_observation_cannot_identify_units :
    ¬ ∃ infer : Int → Int, ∀ scale : Int, scale = 1 ∨ scale = 100 → infer (scale * 0) = scale := by
  rintro ⟨infer, correct⟩
  have one := correct 1 (Or.inl rfl)
  have hundred := correct 100 (Or.inr rfl)
  simp only [Int.mul_zero] at one hundred
  omega

/-- A visible guard that still passes after an unobserved unit change does
not protect the first changed answer; fallback is not invoked on that path. -/
theorem passing_guard_drift_counterexample :
    (1 : Int) * 0 = 100 * 0 ∧
    guarded (some true) (some ((1 : Int) * 1)) (100 * 1) = 1 ∧
    guarded (some true) (some ((1 : Int) * 1)) (100 * 1) ≠ 100 * 1 := by
  decide

end WitnessCL.TypedFragments
