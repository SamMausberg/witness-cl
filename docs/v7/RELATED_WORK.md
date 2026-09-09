# Model-free promotion from fresh, paired experience

Primary sources checked 8 September 2026. This document records the antecedent
and assumption audit written before v7 implementation. It is not an exhaustive
novelty search or benchmark ranking. Its proposed designs remain a dated
research record: the final implemented study is specified in
[EVALUATION.md](EVALUATION.md), the gate in [GATE.md](GATE.md), and the checked
arithmetic result in [FORMAL.md](FORMAL.md). In particular, the 512-pair pilot
sketch below was superseded by the final 64-pair, fixed-half-bet protocol. Do not
read the earlier sketch as a description of the executed experiment.

The strongest relevant starting point is established high-confidence policy
improvement combined with modern sequential inference. It removes the need to
enumerate possible hidden worlds, but replaces exact universal claims with
statistical statements about explicitly defined performance distributions.
Learning a useful representation cheaply enough to improve later tool use is
still the research problem. A confidence test alone supplies no representation
and need not produce any improvement.

## Direct antecedents and theorem boundaries

| Primary approach | Precise relevant contract | Boundary for our proposed use |
|---|---|---|
| Thomas, Theocharous and Ghavamzadeh, **High Confidence Policy Improvement**, ICML 2015. [Original paper](https://proceedings.mlr.press/v37/thomas15.pdf), [author erratum](https://people.cs.umass.edu/~pthomas/papers/Thomas2015bErrata.pdf). | Candidate construction and safety testing are separated. With the concentration-inequality version, the probability of returning a policy below a specified expected-return threshold is bounded by the chosen error level. The setting assumes stationary trajectory generation and bounded normalized returns; off-policy estimates use recorded behavior policies. | This directly precedes repeated guarded policy promotion. Its bootstrap and t-test variants do not have the same finite-sample guarantee. The 2017 erratum corrects the repeated-test error bound to `min(1, k*delta)`; a per-candidate confidence level is not a lifetime guarantee. |
| Howard, Ramdas, McAuliffe and Sekhon, **Time-uniform, nonparametric, nonasymptotic confidence sequences**, Annals of Statistics 2021. [Author manuscript](https://arxiv.org/html/1810.08240v8). | Theorem 4 assumes adapted observations in a known bounded interval and a bounded predictable prediction sequence. An empirical-Bernstein boundary covers the average conditional expectation at all times, with the stated two-sided error allocation. A common fixed mean is not required for that result. | Optional stopping can be valid. Under arbitrary drift the target is the average conditional mean so far; it is not the final candidate's future performance or the instantaneous current mean. |
| Waudby-Smith and Ramdas, **Estimating means of bounded random variables by betting**, JRSS B 86 (2024), 1–27; online publication 2023. [Published paper](https://doi.org/10.1093/jrsssb/qkad009), [author manuscript](https://arxiv.org/html/2010.09686v6). | Nonnegative test supermartingales and Ville's inequality give time-uniform confidence sets. The standard fixed-mean setting has bounded observations with the specified constant conditional mean. Bets must be predictable: the next outcome cannot be used to choose its own wager. | Variance-adaptive betting and fixed mixtures are strong, cheap controls for paired reward differences. Reusing data after choosing a new candidate from those same outcomes is a separate selection problem; sequential validity alone does not license it. |
| Waudby-Smith, Wu, Ramdas, Karampatziakis and Mineiro, **Anytime-valid off-policy inference for contextual bandits**, ACM/IMS Journal of Data Science 2024. [Original manuscript](https://arxiv.org/pdf/2210.10768). | Theorem 1 allows predictable changing logging policies and constant conditional target value; later results cover time-varying average conditional value. Rewards are bounded in the main setting. Target actions require support under the known logging probabilities, though importance ratios need not have a known uniform upper bound. Predictable reward models can reduce variance. | This is a direct model-free alternative when both policies cannot be executed. Deterministic logging often lacks support for a different policy. Its full counterfactual interpretation also requires the stated exogeneity conditions; action-dependent state evolution cannot be silently treated as contextual-bandit data. |
| Wu, Shariff, Lattimore and Szepesvari, **Conservative Bandits**, ICML 2016. [Original paper](https://proceedings.mlr.press/v48/wu16.pdf). | Theorem 2 considers fixed stochastic arms with means in `[0,1]`, sub-Gaussian noise and valid simultaneous confidence bounds. Conservative UCB maintains `sum_s mu[action_s] >= (1-eta)*mu0*t` at every prefix with high probability. The initial algorithm knows baseline mean `mu0`; Section 3.5 treats its estimation. | This is a cumulative constraint on selected-arm means, not a pathwise lower bound on every realized reward. It is not the v6 fixed nonrefundable debit contract. Moving learned policies and changing scopes need additional analysis rather than renaming them fixed arms. |
| Dwork, Feldman, Hardt, Pitassi, Reingold and Roth, **Generalization in Adaptive Data Analysis and Holdout Reuse**, 2015. [Original manuscript](https://arxiv.org/pdf/1506.02629). | Thresholdout's Theorem 25 assumes an i.i.d. holdout, bounded queries, the prescribed noise/threshold parameters, sufficient sample size, and a finite overfitting budget. Its accuracy statement applies while that budget remains. The analyst accesses holdout information through the controlled mechanism. | A fixed hidden test set does not remain valid merely because it is called a holdout. Repeated exact scores, traces or failure examples can leak it. For cheap local tools, fresh paired episodes are a simpler first control than implementing this additional mechanism. |

These methods are established antecedents, not a claim that any one is currently
best on the proposed tool task. Direct paired execution is especially attractive
when fresh local instances and genuine state copies are cheap: it avoids
importance-weight variance and the missing-support problem. It requires those
copies and sampling conditions to be real.

## An elementary conditional promotion claim

The following is a proposed specialization of standard test-supermartingale
reasoning, not a new theorem family or a Lean-checked result.

At candidate index `j`, freeze the full candidate `p_j`, incumbent `b_j`, reward
normalization, and protected scope `s` before looking at that candidate's audit
outcomes. The freeze includes routing, retrieval, adapters, prompts and any
persistent state that can change behavior. Sampling a task and then choosing the
candidate with knowledge of that task is not the same protocol.

Draw fresh paired tasks from the declared scope distribution. Execute candidate
and incumbent from equivalent independent copies of the same starting instance;
use fresh randomness or a valid common-randomness coupling. Record the normalized
difference `D_t = R_t(p_j) - R_t(b_j)` in `[-1,1]`. No effect from the first rollout
may change the second rollout's initial conditions. Pairing reduces variance only
when the coupling actually makes the outcomes positively correlated; it is not
itself an independence proof.

For a declared tolerated mean loss `epsilon >= 0`, set

`X_t = (D_t + epsilon)/(1 + epsilon)`.

Choose `lambda_t` in `[0,1]` using only information available before this pair's
outcome, and set `E_0=1`,

`E_t = E_(t-1) * (1 + lambda_t * X_t)`.

Under the null condition
`E[D_t | history before pair t] <= -epsilon` for every pair, `X_t >= -1`, so the
factors are nonnegative and

`E[E_t | history] <= E_(t-1)`.

Consequently Ville's inequality bounds the probability that `E_t` ever reaches
`1/alpha_js` by `alpha_js`. A fixed convex mixture of such betting processes is
also valid; choosing whichever process looks best after observing outcomes
without accounting for that choice is not.

For the desired *fixed policy-value* interpretation, a sufficient assumption is
that audit tasks are freshly and independently sampled from a stationary scope
distribution, conditional on everything that selected the frozen candidate and
incumbent. Then the pair's conditional mean is their fixed scope value
difference `Delta_js`, and crossing the threshold rejects
`Delta_js <= -epsilon`. With `epsilon=0`, this is evidence of positive mean
improvement. Equal policies generally provide no evidence for rejecting equality;
failure to reject does not mean the candidate is worse.

For an unlimited adaptive sequence of candidates and a fixed list of `K`
protected scopes, one simple allocation is

`alpha_js = alpha / (K * j * (j+1))`, for `j=1,2,...`.

Conditional validity for each frozen comparison and a union bound give lifetime
probability at most `alpha` of ever promoting a candidate that violates one of
its tested scope constraints. The candidate must pass every required scope test.
The allocation persists across rejected candidates and restarts of the software;
resetting the bookkeeping resets the claim. New scopes require their own
summable allocation. Scope sampling may be adaptive when the choice precedes the
sample and preserves the needed conditional sampling law.

This statement protects scoped *means* with a specified error probability. It
neither protects each individual task nor implies an unchanged failure tail.
Separate bounded harm or failure indicators can be tested, with their own error
allocation. Positive noninferiority margins also accumulate if each update may
lose `epsilon` to its immediate predecessor. Use a declared total tolerance with
summable per-update margins, or a fixed protected reference; say explicitly which
competence that reference protects. Mean safety does not imply alignment.

Arbitrary hidden drift breaks the fixed future-value interpretation. A confidence
sequence for historical average conditional value can remain mathematically
valid while tomorrow's candidate is bad. Detecting drift after an error does not
retroactively protect that error. Changed candidates or environments begin new
valid comparisons; their old wealth cannot be carried forward as if the estimand
were unchanged.

## Earlier falsifiable practical suggestion (superseded protocol sketch)

**Hypothesis, not an executed result:** learn compact, typed rules from past
successful and failed local tool traces, freeze a proposed rule library, and use
fresh paired execution to decide whether it should replace the incumbent. Test
whether the learned representation improves future task return enough to pay for
its training, retrieval and audit costs. The statistical gate is a known method;
any contribution must lie in useful transfer and its measured cost.

A first task family can use real local SQLite or similarly deterministic,
resettable tools on fresh generated instances. The learner receives ordinary
tool observations and permitted scored feedback, without a list of possible
hidden worlds or an evaluator-supplied latent mapping. A rule might encode a
validated query transformation, output-schema relation or reusable tool sequence;
its applicability and correctness are empirical claims to test. Fixed tool
permissions and reward computation stay outside the learned representation.

Compare the proposed learner against a full legal-history solver, a simple exact
memoization/rule table, the same proposals with a fixed-sample confidence test,
and the same proposals with a standard betting gate. An oracle or generator
truth, if used to measure a ceiling, stays evaluator-only. Include a no-learning
control and paired versus unpaired audits. Charge both members of every pair,
all rejected candidates, training, retrieval, repeated tests, scope checks and
wall time. Report future online reward and untouched final evaluation reward
separately; do not silently turn audit queries into free training examples.

For a bounded CPU pilot, cap each proposed comparison at 512 pairs per protected
scope and each run at four proposed candidates over three scopes: at most 6,144
pairs or 12,288 tool executions before final evaluation. This is an engineering
cap, not a promised statistical power calculation. First measure execution cost
on a small development sample; no paid API, accelerator or deployed action is
needed. If a scope is unchanged by an independently verified identical execution
path, state that structural argument separately rather than inventing statistical
evidence from identical predictions.

Predeclare one useful target, for example a five-percentage-point future reward
gain over the strongest simple control at the same total tool-call ceiling, with
a positive paired lower interval over independent streams. Treat the target as a
research choice, not an established suitable effect size. A final independent
old-scope evaluation checks the declared retention margin and must not train the
agent. Include poisoned proposal rules, rare regressions, reordered metadata,
invalid score provenance and a hidden-drift challenge; the last is explicitly
outside the stationary promotion theorem.

Kill the representation proposal if simple memoization matches it at lower cost,
if gains disappear after charging audits, or if the capped testing budget seldom
permits a useful promotion. Kill the implementation's claimed statistical
validity on any reproducible violation of its test protocol, such as outcome-
dependent bets, reuse under a changed candidate, or reset error spending. A
well-powered null simulation exceeding the allocated false-promotion rate is a
separate empirical falsifier. Kill any zero-forgetting headline if it hides
per-update tolerance accumulation, misses a protected scope, or treats a
historical-average confidence bound as a forecast after drift.

The central weak point is sample cost: a representation can be useful yet too
expensive to validate before the environment changes. Freezing the incumbent is
safe for the scoped claim but can make learning stall. Paired local execution is
therefore a tractable test of the approach, not evidence that real deployments
permit equivalent inexpensive trials.
