# Recorded v0.2 results

These are seeded CPU mechanism experiments. They are not language-model or native public-benchmark results. All percentages below are mean late-half rewards unless stated otherwise.

## Arithmetic: original learner versus recovery and reuse

| Scenario | Original | Reset only | Archive reuse |
|---|---:|---:|---:|
| stationary | 100.00% | 100.00% | 100.00% |
| novel inputs | 100.00% | 100.00% | 100.00% |
| hidden shift | 14.49% | 96.19% | 96.19% |
| misspecified | 10.06% | 100.00% | 100.00% |
| recurring | 14.04% | 84.02% | 97.70% |
| rapid switch | 14.16% | 17.60% | 22.48% |
| noisy feedback | 14.49% | 47.62% | 65.18% |

20 seeds, 512 episodes, identical generated task streams for the three methods. The old implementation is rerun on these new streams; numbers differ from v0.1 because the experimental streams differ. Rewards are scored using actual success; the noisy setting flips the feedback supplied to learners, not the evaluator score.

## Schema-derived relational programs

| Scenario | Full-grammar replay | Reset only | Archive reuse |
|---|---:|---:|---:|
| stationary net | 100.00% | 100.00% | 100.00% |
| recurring recipes | 0.29% | 63.59% | 97.45% |
| out of grammar | 0.08% | 0.10% | 0.05% |

20 seeds, 384 episodes. Fresh databases each episode; public schema only. The grammar and in-grammar mechanisms were deliberately co-designed, while task evaluation is coded independently. This does not demonstrate unrestricted semantic discovery. Full-grammar replay is better overall on the stationary task (95.64% versus 92.36%), while pooling incompatible regimes defeats it on recurrence.

## Actual integrated one-outcome system

| Scenario | Method | Overall reward | Late reward |
|---|---|---:|---:|
| stationary | audited_live | 89.05% | 100.00% |
| stationary | ungated_proposer | 94.37% | 100.00% |
| recurring | audited_live | 75.44% | 84.20% |
| recurring | ungated_proposer | 86.92% | 88.83% |

The agent sees only the selected action and its observed outcome. Auditing costs reward; do not attribute the higher ungated scores to the audited system. Twenty seeds and 512 episodes per configuration.

## Shared relational execution

| Rows | Direct Python median (ms) | Shared cube median (ms) | Ratio |
|---|---:|---:|---:|
| 32 | 0.479895 | 0.129626 | 3.70 |
| 512 | 7.623820 | 0.611038 | 12.48 |
| 8192 | 113.284888 | 6.709610 | 16.88 |

64 plans, two fixed warmup repetitions, changing data and alternating order. Compared only against the direct Python interpreter. This primitive is not yet wired into the reported learner timing, and neither a vectorized database engine nor GPU execution was measured.

## Admission and training

The 4,000-replication power study exposes an information problem, not a promise of universally short tests. At a 2,048-opportunity cap, diffuse +0.05 paired gains pass in 27.00% of simulations. A sparse +0.05 global gain with 0.10 gate frequency and +0.50 conditional gain passes in 100% of these simulations. Dense and screened versions of that same sparse process have identical wealth paths; screening reduces mean extra rollouts from 344.31 to 34.46. Total rollout reduction is about 1.82-fold, not tenfold.

Online projected residual learning protects a fixed span. At rank four in 24 dimensions, new-task mean squared error falls from 25.07 to 4.23 and mean maximum protected drift is approximately 2.02e-16. Full-rank protection prevents learning. No neural model was trained.

## Verification and interpretation

146 Python tests and 432 compiled C++ oracle cases pass. All 29 Lean theorem attempts remain unverified because the toolchain is unavailable. CUDA sources were not compiled or run. Raw episode files and per-seed aggregates are retained, including every failure setting. Mathematical statements are conditional handwritten proofs, not formal software-refinement guarantees.
