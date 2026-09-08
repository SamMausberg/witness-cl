# Decision-directed probes: local protocol frozen before execution

## Question and algorithm

V4 selects probes by low certified debit and many possible observable traces. Two possible traces establish that some behavioral uncertainty will be removed, but this need not resolve any decision. V5 tests a prior-free, decision-directed alternative while retaining the original exact admission checker and nonrefundable B16 ledger.

For the current trace-consistent model class C, finite frozen program library P, and public reward goal g, define R_g(C) = min_p max_M [max_q V_M(q,g) - V_M(p,g)]. Define S(C) as the sum of these regrets over the two public goals. For a probe p, let C_tau be the compatible class after its actual observable trace tau. Its score numerator is G(p,C) = S(C) - max_tau S(C_tau). Subset monotonicity implies G >= 0. The score is a guaranteed reduction of this uncertainty functional; it is **not** a guaranteed reward improvement or a value of information under a probability model.

When no strictly improving policy is certifiable, select a feasible probe with G > 0 maximizing G/(1+d), where d is the exact certified worst-case debit relative to the current objective's incumbent. Break ties by smaller d, larger possible current reward improvement, and the original proposer order. Include the incumbent as a possible free probe. If every G is zero or exact enumeration exceeds 4,096 models, execute the incumbent. Pure information probes may have no possible immediate upside; their complete debit is still prepaid. All public goals receive equal weight. The algorithm is not given the future goal schedule.

The implementation enumerates the same models compatible with executed traces and deduplicates them by their complete observable trace vector across P. Minima and maxima are invariant to duplicate worlds and latent-state relabelings. No evaluator world, reward counterfactual, hidden state, or hidden regime is provided to the learner. A cache uses complete immutable class/program/objective keys, with exact equality. This enumeration is exponential and is a deliberate small-case oracle implementation, not a proposed scalable inference path.

## Frozen comparisons and data splits

Use four arms: unchanged v4 neural B16; v5 decision B16; v5 decision B16 without neural updates; unchanged exact full-history optimistic planner. The planner's original mean-value tie-break over labelled models is preserved. Each arm observes only its own executed traces and gets identical episode/action permissions. Total computation is measured but **not matched**.

Pilot: seeds 20000 through 20019. Holdout: seeds 30000 through 30099. Both use the same fixed rule above; do not modify it based on pilot outcomes. Each seed generates one uniform labelled two-state binary-action binary-output stationary transducer, with replacement. Fresh seed ranges are not disjoint worlds. There are 48 episodes of horizon four and the original A-B-A public utility schedule. Every action, including exploration, counts in the primary mean return. No offline model training or paid compute occurs.

Primary: paired-seed all-episode mean return, v5 versus v4. Strong-baseline comparison: v5 versus full-history optimism. Secondary: last-eight A return, completed-prefix anchor deficit, incumbent violations, actual risk spending, mechanics wall time, exact checker nodes, hypothetical model rollouts, and behavioral profile sizes. Report paired Student t 95% intervals as descriptive; do not claim multiplicity-adjusted confirmation. Also preserve every per-seed and per-episode result.

Kill the current probe-selection hypothesis if heldout mean gain versus v4 has a nonpositive lower confidence bound, or if any retention/budget invariant fails under realizability. Reject a benchmark-superiority interpretation unless the lower interval versus the full-history planner is positive; even that would concern only this toy class, and unequal compute would still prevent a cost-matched claim. If uncertainty contracts but return does not improve, the chosen functional is not an adequate reward-directed exploration criterion.

## Results

The frozen hypothesis failed. The heldout run contains 19,200 rows (four arms, 100 seeds, 48 episodes); the pilot adds 3,840 rows. Independent replay checked every actual trace/reward and all 17,280 guarded episode prefixes across both splits. All remained within the prepaid B16 ledger. No incumbent regression was reported; separate executable trajectory tests verify the retention invariant.

| Heldout arm | Mean reward/episode | Last-eight A | Largest prefix deficit | Mean mechanics seconds/48 episodes |
|---|---:|---:|---:|---:|
| v4_B16 | 5.921667 | 5.80 | 4 | 0.03586 |
| v5_decision_B16 | 5.827083 | 5.72 | 10 | 0.06804 |
| v5_decision_untrained_B16 | 5.860000 | 5.80 | 10 | 0.06451 |
| full_history_optimistic | 5.944583 | 5.80 | 4 | 0.04656 |

The primary paired mean difference, v5 minus v4, is -0.094583 reward/episode, with descriptive 95% interval [-0.169152, -0.020014]. Against full-history optimism it is -0.117500 [-0.191823, -0.043177]. Both refute the hoped-for improvement in this run. V5 costs 1.898 times v4 mechanics time and 1.461 times the planner time. These are local small-CPU measurements and are not normalized systems benchmarks. Exact checker nodes and enumerated model rollouts are separate work counters, not interchangeable FLOPs.

V5's 20 pilot seeds produced 20 distinct labelled tables; 100 heldout seeds produced 85. Ten tables occur in both v5 splits. The v5 heldout tables also overlap seven v4 development tables and 22 v4 heldout tables. This is an independent-seed, same-finite-distribution study, not disjoint-world generalization. The primary algorithm and driver hashes match their local pre-execution freeze. `protocol_frozen.md` preserves the exact original protocol text. Machine-readable results and provenance are in `paper_summary.json`, `audit.json`, and `manifest.json`.

## Diagnosed obstruction and separate successor

Three heldout seeds (30000, 30013, 30090) lose late-A reward. The saved `plateau_diagnostic.json` shows a specific obstruction: S(C) is zero and every probe score G is zero, but the incumbent remains suboptimal in the actual world. S(C)=0 only says a single common optimum exists in the current library. It does not say that the stored incumbent is that optimum. A strict-positive-lower-bound promotion rule can fail to install it when some compatible worlds make it tie the incumbent.

The smallest reproducer needs one state, two one-step actions, and output rewards (0,1). After observing anchor action 0 emit 0, action 1 may emit either 0 or 1. Action 1 is optimal in every compatible world, so minimax regret is zero; its paired improvement interval against the anchor is [0,1]. Frozen v5 neither strictly promotes it nor probes it. If the true output is 1, it continues earning zero despite an exactly certified non-regressing alternative.

A separately named `WeakDominanceClosureAgent` closes only this plateau: if v5 selects its incumbent with no information gain, no debit, and no new promotion, permit an exact nonnegative-lower-bound candidate with positive upper bound. Prefer larger lower bound, then upper bound, then proposer order. This was designed **after** inspecting the failed holdout. Its exhaustive 256-table diagnostic is post-hoc development, not confirmatory validation and not a replacement for the rejected primary result. Exact weak dominance preserves the conditional monotone-retention induction; it does not promise strictly higher realized reward.

The successor diagnostic covers all 256 labelled tables with one proposer initialization per table (seed equals table index), 48 episodes, and four arms: 49,152 episode rows. Mean returns are v4 6.261230, frozen v5 6.198730, weak closure 6.253255, and full-history 6.295410. Closure improves 10 tables and worsens zero against frozen v5, raising mean return by 0.054525 and repairing four late-A failures. It still trails both v4 and full history, retains a maximum prefix deficit of 10, and costs more computation. All 36,864 guarded episode prefixes satisfy B16 and no incumbent regression occurs. These exhaustive finite-population descriptions have no sampling confidence interval and do not generalize over neural initializations or beyond this toy class.

The separate complementarity counterexample in `PROBE_COUNTEREXAMPLE.md` is a stronger remaining limitation. A free probe with G=0 can unlock a second free probe with G>0. Both the frozen one-step selector and weak-dominance closure can still fail there. A concrete next candidate is bounded depth-two contingent probe planning with exact per-branch debit accounting, evaluated first on this counterexample and then on fresh larger-class streams. Kill it if it cannot solve the explicit two-free-probe instance, if any branch violates the debit invariant, or if charged compute eliminates its return advantage against the original v4 and full-history baselines. The small finite diagnostic needs only CPU; larger classes first need measured limits on completion generation and outcome branching. `max_models` caps distinct yielded completions, not duplicate-generation work inside the iterator, and therefore is not an execution-time bound.

## Reproduction

Run `PYTHONPATH=src python3 experiments/latent_v5.py --seed-offset 20000 --seeds 20 --out artifacts/v5/experiment/pilot`, then the same command with offset 30000, 100 seeds, and the `holdout` output. Use `PYTHONPATH=src python3 experiments/audit_v5.py` to independently replay reward/trace/ledger arithmetic. `python3 -m pytest tests/test_v5_decision.py tests/test_v5_successor.py -q` checks the original mechanism, explicit plateau, and successor retention/budgets. The successor's separate development run is `PYTHONPATH=src python3 experiments/latent_v5_successor.py`.
