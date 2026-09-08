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

Pending execution. Source hashes and raw outputs will be saved under `artifacts/v5/experiment/`.
