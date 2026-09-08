# Witness-CL v0.4: claim ledger

## What changed from the uploaded v3

The uploaded v3 began from an explicit list of possible worlds and complete observable state. Version 4 starts from only a declared finite state bound, action/output alphabets, true resets, public reward functions, and executed action/output traces. It infers an exact set of compatible hidden transducers, represented as a union of partial tables. This removes supplied world tables and hidden state observations. It does not remove the structural model-class prior or justify that prior for language agents.

The integrated loop now combines this hidden-model inference, an online trainable proposer, immutable proposed programs, exact paired-continuation checking, and prepaid informative probes. The neural network can change arbitrarily without acquiring admission authority. Public reward objectives select separate incumbents; these objective labels are not secret environment or regime IDs. The primary study keeps dynamics stationary.

An exact residual-program DAG closes genuinely identical paired suffixes without evaluating their unknown transitions. Full dictionary-key equality, rather than unchecked fingerprints, determines equality. This optimization helps shared-suffix CPU cases but slows unrelated programs. No GPU speedup or globally faster algorithm is claimed.

## Evidence ledger

| Claim | Status | Evidence and qualification |
|---|---|---|
| Learns hidden dynamics from executed traces without supplied world tables | Implemented and tested | `latent.py`; exact completion checks on small exhaustive classes. A valid state bound, alphabets, deterministic dynamics and reset semantics are still supplied. |
| Preserves previously admitted reset return under arbitrary proposer updates | Conditional written proof; tested | Truth must remain in the covered class; policies are frozen; comparisons must finish exactly. Not a general proof that the trainable network does not forget. |
| Bounds every completed-episode prefix deficit by a non-refundable risk budget | Conditional written proof; tested | Relative to the declared initial anchor within one stationary, realizable era. Episodes can lose reward and goals can change publicly. |
| Informative probes improve this controller | Executed narrow support | 100 fresh seeds: mean gain 0.0567 over unguided B64; maximum observed prefix deficit 4 rather than 40. No universal VOI guarantee. |
| Neural updates matter | Small executed effect | B64 training vs no-training mean gain 0.0142 per episode. This does not establish neural scaling or substantial transfer. |
| Beats strong full-history planning | Refuted in this experiment | B16 trails by 0.03708 reward/episode, paired 95% interval [-0.05528, -0.01888], while late-A return ties. |
| Wins stateful language-agent benchmarks | Not tested | No CL-Bench, AgentCL, OSWorld, or local model service run. |
| Lean verified | Not established | 50 declarations, including 11 new attempts. No compiler ran; proof scripts and actual failed build log are included. |
| Bounded total memory or polynomial-time learning | Not established | Raw evidence grows; partial covers and program trees can grow exponentially. |
| Novel algorithmic combination | Unestablished | Dynamic shielding, predictive state representations, conservative exploration, DeepSPI, evolving skill libraries and harness evolution are close antecedents. |

## What remains unsolved

The important unsolved step is not storing another kind of memory. It is learning a sufficient, affordable predictive representation from realistic traces and feedback, then using it to improve a deployed agent at equal total cost without erasing valuable behavior. Our exact finite learner is a falsifiable mechanism for that step, not its scalable solution.

The strongest empirical failure is average-return inferiority to a simple exact full-history planner. The planner also has a smaller worst observed prefix deficit, 2 versus 4; the favorable risk comparison is against our unguided ablation, not this stronger baseline. The strongest theoretical vulnerability is model-class coverage: consistency with observed data cannot prove the state bound or rule out hidden drift. Wrong bounds and unannounced drift can produce false assurance before a contradiction is observed. Those are implemented counterexamples, not merely caveats.

The primary no-regression theorem is about reset value for declared public objectives in a stationary deterministic class. It does not imply all-state improvement, safe irreversible actions, correct routing under hidden regimes, transfer to untested objectives, or lifelong retention at fixed storage. The separate v3 noise and neural-isolation branches are retained but not advertised as integrated v4 guarantees.

## Prior work and continuity

Original uploaded commit: `eda6e0167b209dafbad00a73bb338fbd68250796`. The Git history is retained. The original v3 paper is archived under `paper/v3/`; v3 results remain under `artifacts/v3/`. They are historical results, not new v4 execution. Prepared for Samuel Mausberg as an AI-assisted draft requiring author review and independent replication.
