# v0.4 executed results

executed CPU synthetic mechanism study; no LLM/native benchmark.

100 fresh seeds, 48 episodes, eight systems, 38,400 episode rows. The hidden table is stationary; the public objective follows A-B-A. Episode rewards range from 0 to 8. “Late A” averages the last eight episodes. Deficit is the worst completed-episode prefix relative to the same fixed anchor, maximized across seeds.

| System | Mean return | Late A | Maximum prefix deficit |
|---|---:|---:|---:|
| Fixed anchor | 3.9267 | 3.7800 | 0 |
| Full-history planner | 6.3729 | 6.4800 | 2 |
| Last-output model | 6.0275 | 6.1450 | 52 |
| Witness, B=0 | 6.2354 | 6.4000 | 0 |
| Witness, B=16 | 6.3358 | 6.4800 | 4 |
| Witness, B=64 | 6.3358 | 6.4800 | 4 |
| No neural training, B=64 | 6.3217 | 6.4800 | 4 |
| Unguided probes, B=64 | 6.2792 | 6.4800 | 40 |

## Primary paired comparison

Witness B16 minus full-history planner: -0.03708333 reward per episode, paired-seed 95% t interval [-0.05528394, -0.01888272]. This is a negative result on prequential mean return, not benchmark superiority.

## Scope and proof status

Zero incumbent regressions were observed in the realizable deterministic study. This protects reset values for the two declared objectives, not all deployed actions, hidden drift, or arbitrary natural-language tasks. The full-history planner is symbolic and is not raw-history LLM ICL.

355 Python tests pass. An additional 400 C++ paired-program cases plus a reward-range rejection pass under UBSan; 632 legacy C++ cases plus an overflow check also pass. Fifty Lean declarations are attempts, none kernel-checked in this environment. No native CL-Bench/AgentCL, local LLM inference, or new GPU kernel was executed.

See `holdout_audit.json`, `latent_diagnostics.json`, raw compressed episode files, and `docs/v4/` for provenance and boundaries.
