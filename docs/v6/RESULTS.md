# v6 executed results and claim ledger

## Main result

The frozen 40-stream primary contrast favors depth-two probing over the informative zero-loss control: **+0.39375 reward per episode**, paired 95% Student interval **[+0.15845, +0.62905]**. Twelve streams favor depth two, eight favor the cheap rule, and twenty tie. This supports the narrow reward hypothesis on the declared finite family.

It does not support efficiency superiority. Depth two uses **8.878 times** the cheap rule's measured planning time (8.871 times total construction/planning/update time). It loses **0.19479** reward per episode to same-engine bounded optimism, interval **[-0.31761, -0.07198]**. Differences against frozen-ranker v4 and unbounded full-history optimism are **-0.19375** and **-0.23542**, respectively; their paired intervals also exclude zero, but these secondary comparisons are exploratory and not multiplicity-adjusted.

| Method | Mean reward | Late A | Planning seconds/stream | Mean spent risk | UNKNOWN decisions |
|---|---:|---:|---:|---:|---:|
| depth_two_B16 | 4.19688 | 4.375 | 8.3439 | 1.775 | 30.73% |
| informative_zero_loss_B16 | 3.80313 | 3.825 | 0.9398 | 0.000 | 0.00% |
| optimistic_B16 | 4.39167 | 4.475 | 1.5603 | 6.975 | 0.10% |
| v4_frozen_ranker_B16 | 4.39062 | 4.475 | 0.0101 | 4.675 | not metered |
| full_history_optimistic | 4.43229 | 4.475 | 0.0365 | unbounded | not metered |

The first three arms share the same work/time ceilings and fixed checker. The final two are unmetered diagnostic controls; their timing cannot be treated as an isolated algorithmic speedup. Full-history optimism is symbolic planning over its own history, not language-model ICL. No method receives true tables, future goal schedules or evaluator outputs. All ranker weights are frozen.

The shared B16 ceiling does not equal matched realized risk: depth two spends 1.775 on average, free information spends zero, and bounded optimism spends 6.975. Its reward gain over the free rule therefore does not isolate lookahead from willingness to pay for exploration. In this sample, depth two and the free rule never have a positive completed-prefix deficit relative to the anchor; bounded optimism's maximum is nine, within B16. This observed difference is not a new universal zero-loss theorem.

## Data and independent checks

The holdout consists of 4,800 episode records (40 seeds × 5 methods × 24 episodes) and 40 distinct sampled tables. None coincides with the eight development tables, although sampling allowed replacement and the protocol did not guarantee disjoint worlds. All data remain from the same small structural family, with no new-domain or native benchmark claim.

The complete v6 study retains 8,640 benchmark episodes: initial development, corrected development, holdout, and two development-only work sweeps. The initial development run preceded two independently found implementation corrections; its original hashes and outcomes remain visible. The corrected source/configuration freeze predates all held-out outcomes. No selector was retuned after the holdout.

Runtime audits compare the model cover against independently filtered exhaustive histories, check each changed incumbent over every compatible world, and track nonrefundable announced debits. An additional saved-data replay covers 7,680 final-protocol episodes and 6,144 guarded prefixes, including all 3,840 guarded holdout prefixes. It finds zero reward, trace, cover, incumbent, or ledger violations. The initial development rows lack the extra saved incumbent fields, so they are not included in this second replay count. Tampered-record tests verify that the independent checker rejects fabricated evidence and refunds.

Forty-eight separate mechanism streams contain 180 episodes. All three selectors obtain 5,5,10 on every two-bit parity world at B0. Depth two stalls at five on every three-bit world; the cheap rule reaches ten after three free probes. Equal-payoff controls confirm that extra search can consume computation without a possible reward gain. Decision-edge diagnostics also resolve two- and three-bit parity; they are explicitly not an EC2 reproduction or approximation guarantee.

## Computation-limit sweep

These are exploratory development outcomes on the same eight seeds, with unchanged one-second deadlines. They were declared before execution and did not alter the primary result.

| Work ceiling | Depth-two reward | Cheap reward | Bounded optimism reward | Depth-two UNKNOWN |
|---:|---:|---:|---:|---:|
| 25,000 | 3.68750 | 3.86458 | 4.00000 | 95.83% |
| 250,000 | 3.98438 | 3.86458 | 4.34896 | 43.75% |
| 2,000,000 | 4.05208 | 3.86458 | 4.38542 | 28.12% |

Smaller computation ceilings do not preserve the primary gain. Counts are audited package Python line events, not FLOPs. Planning wall time includes instrumentation and excludes separately measured construction, observation update and evaluator replay. The cooperative wall deadline can make exact/UNKNOWN outcomes depend on hardware and scheduling; there is no hard real-time or operating-system memory guarantee.

## Established, inferred, and proposed

**Established here:** the specified finite simulator retains truthful evidence, accepts guarded changes with no detected contract violation, repairs the two-bit mechanism, and produces the recorded reward/cost contrasts. Lean checks 63 statements, including the executable interpreter/filter bridge; exhaustive Python comparisons test 262,144 memberships. The optimized Python implementation is not generally proved in Lean.

**Inference:** deeper exact search is an unattractive efficiency choice on this family, given stronger cheaper bounded controls and the high fallback rate. This does not establish that all nonmyopic exploration is ineffective. The general deployed continual-learning and learned-abstraction problem remains open.

**Proposed, not executed:** carefully validated comparison reuse in the strongest cheap selector, tested against ordinary memoization and charged for every cache/ancestry operation. The [next-study document](NEXT_STEPS.md) specifies an experiment, resources, proof obligation and rejection criteria. No new background run is scheduled.

Reproduce the final evidence audit with `PYTHONPATH=src python3 experiments/audit_v6.py artifacts/v6/development-corrected artifacts/v6/holdout artifacts/v6/work-25000 artifacts/v6/work-250000 --out /tmp/witness-v6-audit.json`. Raw records, source/configuration manifests and derived result hashes are under `artifacts/v6/`.
