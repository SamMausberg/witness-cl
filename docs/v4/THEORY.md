# Conditional theory for latent continuation learning

These are written mathematical arguments. The Lean file contains abstract proof attempts, not a kernel-checked refinement of Python.

## Contract

The environment is a stationary deterministic transducer with at most K states, known finite action alphabet A and output alphabet O. All episodes reset to the same designated state, labelled zero. The learner receives only executed action/output traces, not latent states or transition tables. The true world can be embedded in the declared K-state class, possibly with unreachable padding states. Rewards are a known bounded integer function r_g of output for each declared public objective g. Horizon H is finite.

A policy is an immutable, complete tree mapping output histories of length t to its action at time t. Time, the requested objective, and output history are observable. A tree is not allowed to branch on a hidden state. The experiments use a restricted open-loop library; the checker supports general trees.

Let C_n be all complete K-state tables whose runs agree with every executed trace before episode n. Let V_m(p,g) be the H-step return from the true reset of table m. It is a counterfactual mathematical quantity, not an observed training label. Only the reward of the executed policy enters online training.

## Exact partial-table cover

A partial table c leaves some transitions undefined and denotes every complete table agreeing with its assigned edges. Initially the all-undefined table covers the whole declared class. To condition on one observed pair (a,o), maintain a branch's possible hidden state. If its required edge is defined, retain it exactly when its output equals o. If undefined, branch over all K successor states while fixing its output to o. Retain branch end states while processing the trace; merge duplicate table/state pairs. At episode end, discard the end state because the next episode resets, and deduplicate tables.

Induction over the trace proves both directions of equality between the union of completions and the data-consistent class. Every true completion has its actual successor branch; no retained completion can disagree with an output used to constrain its visited edge. Unvisited edges remain universally quantified. Different partials may overlap, which affects work but not the correctness of min/max extrema. A branch cap invalidates completeness. The implementation returns UNKNOWN and never certifies a truncated cover.

A minimum-size fitted automaton is not interchangeable with this cover. It can omit a still-compatible larger automaton, and observed agreement cannot repair the universal claim. Increasing K requires replay of every stored trace and rechecking from the anchor in a new era. Adding candidate programs alone does not enlarge the world class.

## Paired continuation checking

For candidate p and current incumbent b, define L = min over m in C_n of [V_m(p,g) - V_m(b,g)] and U as the corresponding maximum. Run both programs in the same symbolic table, initially at reset zero. Assign an unknown edge only when one of the programs first reads it, branching over all K times |O| possibilities. Share assignments between both executions. Accumulate their reward difference.

At horizon H the difference is exact for every completion of that branch. A branch can close earlier when both executions have the same hidden state, time, and remaining observation-contingent program. Their subsequent actions, outputs, states and rewards then coincide by induction, for any completion of unread edges. Equal current output, equal shapes or equal total returns so far are not sufficient. Exact pair-local residual IDs are obtained by interning full tuples (action, child IDs); unequal keys are never equated merely because hashes collide.

Every completion follows at least one terminal branch, and every terminal branch denotes compatible completions with its recorded difference. Therefore the extrema of leaf differences are exactly L and U. Filling unread edges arbitrarily yields a compatible complete witness attaining L. Reaching the node cap returns UNKNOWN without a bound; an empty compatible class returns INCONSISTENT rather than accepting vacuously.

Worst-case expansion remains exponential: along a paired path at most u = min(K|A|, 2H) different unknown edges are read, yielding up to (K|O|)^u assignments per partial table, with horizon and cover overhead. Constructing full policy trees also costs O(sum from t=0 to H-1 of |O|^t). Prefix sharing is conditional computation avoidance, not a polynomial guarantee.

## Incumbent retention independent of the proposer

Assume the true table remains in C_n. If a completed check has L >= 0, then substituting the true table into the universal inequality yields V_true(p,g) >= V_true(b,g). Replacing b by p and repeating proves a nondecreasing chain of reset values separately for every declared objective. The implementation promotes only strict improvements, L > 0; ties retain the existing incumbent.

The proposer may use neural updates, random changes, an LLM, or an adversarial sequence. The proof does not constrain how it selects p. It requires only immutable executable semantics for p, exact checking and retention of the relevant incumbent. This is behavioral preservation behind a gate, not a theorem about absence of interference inside the neural parameters. An unchecked routing change or objective change is outside the theorem.

Contracting C_n preserves earlier universal certificates. Enlarging or replacing it does not. If an environment silently changes, a previously valid certificate may become false before any distinguishing feedback arrives. The recorded drift counterexample has old certified gain +2 and new true difference -2.

## Exploration deficit

Before executing a non-admitted probe p_n, debit d_n = max(0, max over m in C_n of [V_m(b_n,g_n) - V_m(p_n,g_n)]). Choose it only if the sum of debits including d_n is at most B. Never refund a debit after favorable feedback. An ordinary incumbent execution and an admitted improvement cost zero debit.

For each completed episode, the initial anchor value is at most the current incumbent value, which is at most the executed probe return plus d_n. Hence, for every completed prefix N,

    sum(n <= N) [V_true(b_0,g_n) - R_n] <= sum(n <= N) d_n <= B.

This is an anchor-relative cumulative deficit bound in each realizable stationary era, not an instantaneous regret bound, monotone realized reward, high-probability statement, or irreversible-action safety theorem. Era restarts reset the anchor and ledger; no global bound across arbitrarily many restarts is claimed.

## Informative probes

For each feasible probe, enumerate its distinct observable action/output traces over C_n. If there are at least two, every realized outcome excludes at least one currently compatible behavioral alternative. Proof: two differing possible traces cannot both equal the observed trace. One corresponding world is therefore eliminated. This is enough to reject guaranteed-uninformative experiments, not to quantify expected information gain or maximize long-term learning.

The controller orders feasible informative probes by smallest debit, largest number of distinct traces, largest optimistic return difference, then proposer rank. Counts refer to observable outcomes, not arbitrary hidden-state labelings. They are not probabilities or Shannon entropy. The finite class admits at most |C_0|-1 strictly informative elimination events, but this exponential upper bound is not a useful sample-complexity result and does not ensure sufficient budget or optimal identification.

## Necessary failure examples

A safe anchor can give identical feedback in two worlds where the only informative action has opposite reward effects. A zero-risk controller cannot both protect the anchor in the unfavorable world and guarantee discovery of the favorable one. This illustrates a tradeoff rather than ruling out the research target. An underspecified state bound can make two actions appear equivalent even when a larger compatible machine separates their future returns. Finally, equal current outputs can hide different successor behavior. The tests explicitly cover these hazards and empty/incomplete model classes.

## Formal map

`formal/WitnessCL/Latent.lean` attempts split-cover, refinement, evidence intersection, covered bounds, guarded update, arbitrary proposer, retention chains, informative elimination, observation aliasing, budget lifting and shrinking-class preservation. Eleven declarations are new; 50 exist across the repository. The numeric policy interpreter, recursive search cover, resource caps, Python floating-point trainer, C++ translation and native task semantics are not formalized end to end. No Lean compiler executed in this environment.
