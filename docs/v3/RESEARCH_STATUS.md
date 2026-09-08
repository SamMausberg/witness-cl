# Research status and claim ledger

Samuel Mausberg, 8 September 2026. Revision 0.3.0 extends the uploaded v0.2 Git
history. This document, the new paper, and current code supersede the v0.2
front-page description; historical results remain in their original folders.

## What changed, and what did not

The new integrated controller moves beyond v0.2's one-step patch audit to
finite-horizon policy comparisons. It retains every observed transition, checks
all surviving supplied models, keeps the previous certified incumbent rather than
restarting from the original baseline, and pays worst-case exploration deficits
before deployment. Expansion of the plausible model family invalidates old
certificates and starts a separately marked trust era. Separate components cover
noise-aware evidence, immutable learned feature modules, and paired simulation.

The underlying Bellman theorem, version-space filtering, conservative exploration,
likelihood-ratio inference, and frozen-module isolation have substantial prior
art. We do not claim to have invented them. The proposed research contribution is
a continuation-aware compilation and admission discipline, with explicit evidence,
state, version, scope, and exploration accounting, and a falsifiable attempt to
learn compact sufficient abstractions. Novelty of that combination has not been
established by a complete literature review or a successful benchmark result.

| Claim | Evidence in this release | Boundary |
|---|---|---|
| A certified candidate improves every surviving world's all-state full-horizon return | Backward-induction proof; exact scalar and vector tests; Lean attempt | Supplied finite deterministic family, complete observable state, correct rewards |
| Earlier incumbent gains are retained | Transitivity proof and update-by-update tests | Truth-retaining contracting era; class expansion can reset to the anchor |
| Cumulative exploration deficit is at most B at every completed prefix | Algebraic proof; randomized executions | Stationary realizable deterministic world, real episode resets; not a lifetime counterfactual under cross-episode carryover |
| Equal closed full-system transitions preserve future behavior | Inductive proof, hidden-controller-state counterexamples | Every future-relevant state component and permitted input must be included |
| A noisy fixed-family likelihood filter retains truth with probability at least 1-delta uniformly in time | Standard likelihood-supermartingale argument, exact arithmetic tests, 1,000 trials | Correct fixed conditional models; not integrated stochastic control |
| Frozen learned modules retain their old functions | Immutable bytes; exact output tests; 20-seed feature-learning experiment | Trusted public scope and unchanged input construction; growing storage |
| Coupled simulation reduces environment calls | 200 paired-rollout parity checks and call counts | Pure simulator only; controller calls are unchanged |
| A general LLM learns safely without forgetting and beats ICL | Not established | No native benchmark, real model-service, or GPU run |
| Lean has verified the theory | Not established | 39 theorem declarations are uncompiled attempts |
| CUDA improves serving throughput | Not established | CUDA source is an uncompiled draft; cold CPU packing shows essentially no gain |

## Results that weaken the proposal

The B=4 controller exactly matches a strong full-history model-based baseline's
late return on all twenty seeds in both new domains. It does not beat that
baseline. Immediate-reward greedy control fails badly in delayed damage, but that
alone is not a meaningful state-of-the-art comparison. A zero budget also prevents
some beneficial learning. The certified controller is slower than the simple
model-based baseline on these tiny CPU examples. Environment-model enumeration
and pre-execution planning are expensive and rely on supplied structure.

In the neural diagnostic, online replay cuts mean forgetting to 2.65 percentage
points. Versioning reduces measured forgetting and old-logit drift to zero, but
late current-task accuracy is 95.43% versus 96.23% for replay, with a growing
module archive and an explicitly supplied scope identity. There is no free
plasticity-stability improvement demonstrated here.

The covariance, residual-training, recurrence, and local-audit experiments in v0.2
remain separate. The newer neural/noise/coupling components are not silently
presented as a single working language-agent system.

## Unsolved central question

Can a deployed language agent infer sufficiently compact, identifiable,
future-relevant state and useful reusable programs from its own legally available
experience, certify or validly audit their effects cheaply enough, and improve
transfer at equal total cost without unacceptable regression? The missing
abstraction, feedback, safe exploration, routing, and cost requirements are the
substance of the remaining research. Restricting to finite supplied worlds makes
these assumptions testable; it does not solve their acquisition.

## Attribution

The bibliography records primary sources consulted through 8 September 2026.
The June CL-Bench report motivates the comparison with ICL. AgentCL provides
controlled transfer streams. EvoTest, ACE, ALMA, TTHE, and Decision-Aware Memory
Cards are important adaptive harness/memory comparators. SPIBB, conservative MDP exploration, and DeepSPI (arXiv:2510.12312,
ICLR 2026) constrain novelty claims. DeepSPI already addresses online safe policy
improvement with learned world models and representations; our finite-family
result is not a first theorem for that broader topic. Progressive networks constrain claims
about module isolation. No comparison against those implementations was executed.
