import Lean
import WitnessCL
import WitnessCL.Ambiguity
import WitnessCL.Continuation
import WitnessCL.Core
import WitnessCL.Executable
import WitnessCL.Intervention
import WitnessCL.Latent
import WitnessCL.Refinement
import WitnessCL.StatisticalBridge
import WitnessCL.TypedFragments
open Lean in
run_cmd do
  let env ← getEnv
  for (name, info) in env.constants.toList do
    let some moduleIndex := env.getModuleIdxFor? name | continue
    let moduleName := env.header.moduleNames[moduleIndex.toNat]!
    if moduleName.toString == "WitnessCL" || moduleName.toString.startsWith "WitnessCL." then
      match info with
      | .thmInfo _ =>
        let axioms ← collectAxioms name
        logInfo m!"WITNESSCL_THEOREM {name}"
        if axioms.isEmpty then
          logInfo m!"'{name}' does not depend on any axioms"
        else
          logInfo m!"'{name}' depends on axioms: {axioms.qsort Name.lt |>.toList}"
      | .axiomInfo value =>
        if value.isUnsafe then
          logInfo m!"WITNESSCL_UNSAFE_AXIOM {name}"
        else
          logInfo m!"WITNESSCL_AXIOM {name}"
      | _ => pure ()
