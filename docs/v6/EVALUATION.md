# Bounded two-probe evaluation protocol

This protocol is recorded before the v6 benchmark outcomes. It is a local protocol freeze, not external preregistration. The prior 256-table binary world family is development data and will not be relabeled as a fresh holdout.

## Primary question

Does conventional bounded depth-two, observation-contingent probing improve mean future reward over a cheap informative-zero-loss selector when both retain the same fixed exact admission and nonrefundable risk checks? Positive information gain is not itself a reward guarantee. Primary outcome is per-stream mean reward over all episodes, including exploration. The primary contrast is depth-two minus the cheap selector, with paired Student t intervals over independent generated streams. Other contrasts and diagnostic families are exploratory.

## Class, observations and schedule

Use K=2 hidden states, A=2 actions, O=3 outputs, and all eight open-loop action words of horizon three. The common initial class is all 1,296 labelled deterministic transducers, represented by the normal undefined partial table. The agent sees only its actual action/output traces, not the sampled true table. Two declared public objectives have reward vectors (0,1,2) and (2,1,0); the 24-episode schedule is eight A, eight B, eight A. Future schedule and evaluator counterfactuals are never model inputs. The horizon reward is between zero and six. Risk budget is B16 throughout a stationary era.

Development seeds are 60000–60007. The initially planned holdout is 61000–61039, using the same fixed selector implementations and all episodes. Seeds sample with replacement; report exact table overlap and do not claim disjoint-world/domain generalization. The third observable symbol differs from the earlier binary experiment, but the same finite-model structural assumptions remain strong prior knowledge.

## Arms and resource measurements

Compare depth-two probing, the cheap informative-zero-loss rule, and a same-engine risk-budgeted optimistic rule. All three use identical class/program/reward inputs and final checker authority. Every neural ranker, including the preserved-v4 control, is frozen (`trainable=False`); visit counters still update. This phase tests symbolic evidence acquisition and selection, not weight adaptation. Also include preserved v4 and unbounded full-history optimism as diagnostic controls. The latter lacks the risk restriction and is an evaluator-side algorithmic comparator, never a policy granted external execution authority.

For bounded agents, use at most 2,000,000 audited Python line events and a cooperative one-second planning deadline per decision, plus the declared model/node caps. This counts completion iteration, duplicate generation, profile work and comparison/search operations as documented by the implementation. A common ceiling is not equal realized computation, and line events are not FLOPs. Report actual construction, planning and observation/update times separately; do not call a win under unequal measured cost an iso-compute result. A resource sweep at 25,000 and 250,000 line-event ceilings is exploratory and runs only on development fixtures/streams unless frozen separately.

Count total episode reward, final/late-A reward, incumbent violations, completed-prefix anchor deficit, actual risk debit, exact/UNKNOWN fraction, planning time, update time, completed hypotheses, duplicate attempts and work events. Evaluator-only audits replay actual traces and rewards, check every protected value and every guarded prefix, and measure model coverage where feasible. Archive failures/timeouts and refuse to overwrite completed result directories.

## Mechanism and negative controls

1. The known four-world two-bit parity class: reach return 10 at B0 by learning from two free probes, without any earlier loss. All four worlds must pass. The cheap rule is an essential comparator; solving the example alone does not justify lookahead.
2. Three hidden bits with parity decisions: depth two can still miss complementary information that needs three probes. This is a depth-limit stress test, not a surprise theorem.
3. No action-dependent reward: show wasted planning cost when no improvement is possible.
4. Tiny work/time caps, incomplete/empty covers, stale feedback and failed search: assert no unchecked admission, no imaginary evidence, and no partial state mutation.

## Falsifiers and interpretation

Any false admission, incumbent regression, exceeded risk budget, or leakage of evaluator-only evidence under the stated valid contract invalidates the implementation claim and stops the run. Failure on two-bit complementarity kills the claim that the new selector addresses the motivating failure. If the primary lower paired interval is not positive, the hoped-for reward benefit is unsupported; a negative interval is evidence against it. If the cheap rule matches or exceeds reward with lower actual computation, reject the efficiency claim even when depth two passes its mechanism test. A native continual-learning or general alignment claim remains unsupported regardless of these outcomes.
