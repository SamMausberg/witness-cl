# Direct antecedents for the two-probe experiment

Primary sources checked 8 September 2026. This is a focused comparison, not an
exhaustive novelty search or a state-of-the-art ranking. The broader native
continual-learning comparison remains in [v5/LITERATURE.md](../v5/LITERATURE.md).

| Established approach | Relationship to the proposed mechanism | Boundary for this experiment |
|---|---|---|
| Kaelbling, Littman and Cassandra, *Planning and acting in partially observable stochastic domains*, Artificial Intelligence 101 (1998), 99–134. [Publisher](https://www.sciencedirect.com/science/article/pii/S000437029800023X), [author copy](https://www.cassandra.org/arc/papers/aij98.pdf). | Belief-state planning and observation-contingent policy trees are established. Enumerating a first probe and a different second probe for each observation is a short policy-tree search. | A two-step lookahead on a known finite class does not introduce the general idea of learning by planning over information states. Exact planning scales poorly; a tiny finite instance is not evidence of realistic representation learning. |
| Silver and Veness, *Monte-Carlo Planning in Large POMDPs*, NeurIPS 2010. [Original paper](https://papers.nips.cc/paper_files/paper/2010/file/edfbe1afcf9246bb0d40eb4d8027d90f-Paper.pdf). | POMCP combines sampled belief updates with Monte Carlo tree search using a simulator. It is a direct scalable-search antecedent to explicit completion enumeration. | Sampling does not certify a worst-case lower bound over every compatible model. It can guide proposals here only if the separate exact admission boundary remains effective. |
| Guez, Silver and Dayan, *Efficient Bayes-Adaptive Reinforcement Learning using Sample-Based Search*, NeurIPS 2012. [Author paper](https://arxiv.org/abs/1205.3109). | Bayes-adaptive planning already values how actions improve later decisions while trading exploration against exploitation. Lazy model sampling reduces costly inference inside a search tree. | The Bayesian objective and assumptions differ from this finite prior-free worst-case probe score. Neither total search efficiency nor persistent behavior retention follows by analogy. |
| Golovin and Krause, *Adaptive Submodularity: Theory and Applications in Active Learning and Stochastic Optimization*, JAIR 42 (2011), 427–486. [Author manuscript, corrected v5](https://arxiv.org/abs/1003.3967v5). | Adaptive diminishing returns can justify efficient greedy acquisition. The XOR example instead has zero initial marginal decision improvement and positive improvement after another observation. | The immediate-regret objective used here does not inherit adaptive-submodular guarantees. The manuscript records a 2017 correction to its coverage result; this project asserts no approximation factor from that theorem. |
| Golovin, Krause and Ray, *Near-Optimal Bayesian Active Learning with Noisy Observations*, NeurIPS 2010. [Original paper](https://papers.nips.cc/paper_files/paper/2010/file/1e6e0a04d20f50967c64dac2d639a577-Paper.pdf). | EC² cuts weighted edges between hypotheses in different decision classes. It need not wait for an immediate improvement in achievable decision reward before choosing a useful test. | This is a strong cheap control for complementary information. The original Bayesian expected-cost objective differs from a worst-outcome pair-count adaptation; its theorem must not be attributed to the adaptation. |
| Javdani, Chen, Karbasi, Krause and Bagnell, *Near Optimal Bayesian Active Learning for Decision Making*, AISTATS 2014. [Author paper](https://arxiv.org/abs/1402.5886). | Hyperedge cutting addresses decision identification when acceptable decision regions overlap. This matters when several programs tie for the best return in one model. | Arbitrarily assigning tied models to a single optimal-action class changes the problem. Any simpler pair-count control must declare its tie handling and should not be named as an exact HEC reproduction. |

## Inference for v6

The defensible claim to test is narrow: bounded two-probe search can repair the
specific one-step minimax-regret plateau under the existing exact safety contract.
The policy-tree concept, nonmyopic information value, and decision-directed
experimental design already have strong antecedents. A positive XOR result
establishes a repair; it does not establish a new general continual-learning
algorithm, better native memory, or safety of an LLM's learned objectives.

The two-bit construction also suggests a cheaper competing explanation. Classify
each model by which final payoff action is optimal. Observing one bit leaves the
best attainable worst-case payoff unchanged, but it eliminates some pairs with
opposite optimal actions. An edge-cutting score can therefore select the first
free probe with one-step search. This deduction follows from the finite XOR
construction; it is not a claim of an executed EC² experiment. The next comparison
should retain a model-count control and add explicitly defined decision-edge
cutting before attributing any result to greater planning depth.

## Falsifiable limits and fair accounting

A three-bit parity task has useful three-probe information while every B0-feasible plan of one or
two probes has zero decision-regret reduction. A depth-two selector that refuses all
zero-score probes therefore still stalls. Generalizing to more bits produces the
same obstruction at B0 for any fixed depth. A learned shortcut would need independent
evidence that its abstraction is adequate; assuming the hidden parity structure
is already such a shortcut.

Compare methods with identical available model classes, programs, rewards,
feedback, incumbent initialization, and environment interaction budgets. Charge
completion enumeration before deduplication, all program rollouts needed to
construct profiles, branch comparisons, and utility evaluations. Report wall
time as well as these operation counts. Test equal-return cases where learning
has no value, large redundant model covers, search-cap exhaustion, goal changes,
and observed contradictions. Expected plan debit is not sufficient: each
reachable observation branch must satisfy the remaining prepaid loss budget.
