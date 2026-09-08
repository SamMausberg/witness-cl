# Optimizing the branch regret/debit tradeoff

## Why independent branch minima fail

Fix a first experiment and the possible observed traces after that experiment.
Suppose one trace leads to branch A, whose second-experiment choices include
`(worst terminal regret, debit) = (0, 10)` and `(1, 0)`. Another trace leads to
branch B, whose best attainable regret is 5 at debit 0. Minimizing each branch's
regret independently chooses the expensive action in A. The overall worst regret
is still 5, because B determines the maximum. Choosing the free action in A
achieves the same global regret bound at lower worst-case debit.

Consequently, independent lexicographic minima of `(regret, debit)` need not
maximize the planner's score, `guaranteed regret reduction / (1 + total debit)`.
The issue is inefficient experiment selection; it does not invalidate an exact
per-episode debit certificate.

## Finite threshold procedure

For a fixed first experiment, let:

- `R0` be the initial sum of per-objective minimax regrets.
- `d0` be the exact worst-case debit charged for the first experiment.
- `I` index the nonempty first-observation branches.
- `A_i` contain the feasible second choices in branch `i`, including stopping.
- `r_i(a)` be the worst terminal regret after choice `a` in branch `i`.
- `d_i(a)` be its exact branch-local debit against the original incumbent.

A choice is locally feasible only if `d0 + d_i(a)` fits the available budget.
Stopping has debit zero and retains the branch's current regret. A contingent
plan selects one member of every `A_i`, yielding

```
R = max_i r_i(a_i)
D = d0 + max_i d_i(a_i)
score = (R0 - R) / (1 + D).
```

Enumerate the finite set of all attainable `r_i(a)` values as thresholds `T`.
For each threshold, in every branch choose a least-debit feasible option with
`r_i(a) <= T`. Discard thresholds for which any branch has no such option.
Compute the resulting *actual* `R` and `D`, and apply the planner's full score
and deterministic tie rules. Do not assume the resulting maximum regret equals
`T`: it can be strictly smaller.

## Completeness proof sketch

Consider any feasible contingent plan `p`, and write `T = R(p)`. Since the
nonempty branch set is finite, some chosen branch attains the maximum; therefore
`T` is among the enumerated thresholds.

At threshold `T`, every choice of `p` is available to its branch's minimization.
The threshold procedure returns a choice `q_i` satisfying

```
r_i(q_i) <= T
d_i(q_i) <= d_i(p_i).
```

Taking maxima gives `R(q) <= R(p)` and `D(q) <= D(p)`. For any plan with positive
gain, decreasing regret increases the numerator and decreasing debit reduces
the positive denominator. Hence `score(q) >= score(p)`. If the primary scores
are equal while the gain is positive, these inequalities force both aggregate
regret and debit to be equal. The planner's root-specific secondary scores are
constant for this fixed first experiment, so threshold enumeration cannot lose
a better regret/debit score through its branch choices.

Thus the threshold frontier contains a plan at least as good as every feasible
combination under this scoring rule. Selecting its maximum is sufficient; no
Cartesian product of all branch choices is required. With `K` total retained
branch alternatives and at most `K` distinct regret thresholds, a simple scan
per threshold costs `O(K^2)` selection operations after the alternatives have
been computed. Exact model enumeration and branch comparisons generally remain
the expensive part. The enclosing work limit still applies to frontier search.

This is a mathematical proof sketch, not an additional Lean-checked theorem.
Its assumptions and the implementation's sorting, maxima, indexing, and budget
checks must still be tested independently.

## What this does and does not optimize

The argument applies only to the supplied finite feasible alternatives for a
fixed first experiment. It does not establish global optimality when an earlier
immediate-promotion shortcut skips probe planning, a proposal cap excludes
programs, or the enclosing computation returns unknown. Comparing every admitted
first experiment extends the result to the computed finite two-step search,
subject to those restrictions.

The reward-regret objective is a library-relative decision uncertainty measure,
not realized reward improvement, expected information value, or a probability.
The debit is the conservative sum of the first experiment's worst-case loss and
the largest branch-local second loss. It need not equal the smallest possible
joint two-episode debit, because the two worst cases may occur in different
worlds. The optimization above is exact for this stated surrogate and budget
accounting convention.

Only the first experiment is executed. The second choices are hypothetical
plans; they are not observations or authority to spend later. A subsequent
actual episode must replan and pass a fresh exact comparison, especially if its
objective, incumbent, model class, or available budget has changed. The reported
two-step regret reduction therefore describes completing the contingent plan
under its assumptions. It is not a guarantee that the receding-horizon process
will realize that reduction within two episodes, nor a proof of continual
improvement, alignment, or robustness to incorrect feedback or drift.
