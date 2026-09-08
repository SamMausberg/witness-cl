# Evaluation contract and kill criteria

This is a proposed protocol, not an externally registered preregistration.
Freeze it, model IDs, code commits and budgets before the public-benchmark run.
The completed synthetic experiment was a development diagnostic; it is not
held-out evidence of the new research hypothesis.

## Primary falsifiable question

Does counterexample-preserving compilation improve real stateful reward and
reuse compared with the strongest matched-backbone memory/harness baseline,
without worsening retention, when all inference, induction, audit and storage
costs are counted?

The proposed success target is at least +5 percentage points of aggregate
normalized reward over the best preregistered baseline, positive gains on at
least four of six native CL-Bench tasks, and a paired 95% interval excluding
zero. This is a research target, not a predicted result. Report official native
reward and gain separately. Do not rename a normalized score as task accuracy.

For retention, freeze an authorized held-out probe distribution for each learned
public scope. Evaluate snapshot reward on it after later scopes are learned;
never use those probe rewards for memory updates or candidate selection. Report
maximum drop, mean backward transfer and worst-family degradation, not only
aggregate reward. A proposed noninferiority tolerance is one percentage point
of normalized reward with a prespecified one-sided interval and multiplicity
control. The exact branch must also have zero incorrect contracts whenever its
stated assumptions hold. Hidden-change scenarios are separate stress tests.

## Baselines and controls

Use a fixed model checkpoint/API version per comparison and implement upstream
systems rather than similarly named heuristics: raw full-history ICL with native
truncation accounting, Mem0, ACE, MemProbe/AgentCL, and TTHE or EvoTest. Run the
exact branch and the combined exact-plus-empirical design separately. Add
an online scoped-update baseline only when the feedback truly supplies labels.

Ablate witness condensation, negative feedback, scope/version guards, fresh-audit
admission, and certificate reuse. Include an unbounded full-history symbolic
induction control to verify equal information on mechanistic tasks. Match the
hypothesis grammar across inductive controls. A stronger supplied grammar is
extra prior knowledge and must be counted as such, not called learned discovery.

Use at least two model scales/backbones, ten or more paired run seeds when
feasible, and disjoint environment generators or held-out task families.
Estimate power from a separate pilot. Ten seeds alone does not guarantee power.
Use paired bootstrap over independent environment runs, not over correlated
episodes as though they were iid samples. Choose thresholds without seeing the
held-out results. Preserve failed, invalid, timeout and refused attempts.

## Budget regimes

Report both iso-feedback and iso-total-cost comparisons. The first holds real
learning opportunities fixed. The second also counts drafting, replay, all audit
forks, model tokens, latency, indexing and CPU/GPU compute. Offline preloading of
answers, hidden benchmark labels, free replay environments, or additional model
calls for just one method invalidate the main claim.

Track cumulative native reward, official gain, area under the learning curve,
forward transfer to new inputs/compositions, protected-scope retention,
certificate coverage/errors, time to useful skill, audit power/false admissions,
input/output tokens, billed cost if actually available, p50/p95 latency, model
calls, total persistent bytes, and active working bytes. Report Pareto curves
rather than hide tradeoffs in an arbitrary scalar utility.

## Resource plan

The committed CPU experiment ran without a GPU or external model. The optional
model-facing pilot needs one already-served model and the Python client. A
single suitable GPU, including the GH200 targeted in the surrounding project,
can host a modest frozen model; actual fit depends on parameters, precision,
context and KV allocation. A rough BF16 weight budget is 2P bytes for P parameters,
plus KV cache, activations and runtime overhead. This is not a measured fit or
throughput promise. No online gradient storage is needed for the primary method.

Start with one model, raw ICL/Witness/Witness-condensed, four seeds and short
synthetic streams. Then integrate three real task families before committing
resources to the complete comparison. Use Docker where the upstream task needs
it. Model/API charges are not estimated here because no provider or budget was
selected. Calibration requires actual endpoint throughput and token usage.

For a full evaluation, let M be model count, A be arm count, R be run count and
S the sum of episode lengths across native task schedules. Stateful plus matching
stateless evaluation costs approximately 2*M*A*R*S episode-agent evaluations,
before audit forks and ablations. For M=2, A=7 and R=10 this is 280*S, not a small
single run. Save a dry-run manifest of S from the pinned upstream schedules.

## Explicit rejection decisions

| Result | Decision |
|---|---|
| No matched-budget advantage over full-history ICL | Reject the principal benchmark claim, even if naive retrieval is beaten |
| Gains vanish on unseen inputs or compositions | Classify as memorization, not reusable skill learning |
| Out-of-class/hidden-shift performance remains worse than lookup or ICL | Reject the current routing/abstraction for general deployment |
| Most useful candidates cannot pass before their relevance horizon | Reject the empirical audit branch for that task regime |
| Average gains hide unacceptable old-scope regressions | Reject the no-forgetting interpretation |
| A sampled LLM candidate pool is advertised as a complete class | Reject the logical certificate claim |
| Extra audits, labels or simulator calls explain the win | Report a resource tradeoff, not matched-budget improvement |
| Lean build fails or formal assumptions do not match runtime | Mark the formal claim unverified; do not publish it as checked |

The delivered hidden-drift and misspecification results already reject any
unconditional version of the present exact-only system. A combined architecture
must fix the measured weakness or publish it as a negative result.
