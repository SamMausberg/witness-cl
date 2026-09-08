# Bounded adaptive probes: v6 development mechanism

The v6 algorithms are conventional finite belief-state search and inexpensive
information-seeking controls. They are not a solution to continual learning or
an alignment guarantee. Their intended scope is the existing stationary,
deterministic finite-class contract with a known reset, integer public rewards,
and immutable finite action programs. No language model or model-weight training
is needed; the v6 evaluation sets `trainable=False` for every arm. The inherited
proposer may update visit counts from actual episode feedback.

## Algorithms and exact authority

`DepthTwoProbeAgent`, `InformativeZeroLossAgent`, and `OptimisticProbeAgent` in
`src/witness_cl/probe_v6.py` all implement `plan(goal)` and `choose(goal)` using the
unchanged `LatentAgent.observe` ticket validation and the unchanged `compare`
checker. `plan` returns a frozen `ProbePlan` without changing the evidence,
incumbents, risk ledger, proposer, or pending episode. `choose` commits a decision
only after the entire planning call has finished exactly. Every selected program
is checked again against the current incumbent in the current exact class before
that plan can return. The execution ticket fixes one existing program for the
whole episode. A foreign, stale, reused, incomplete, or action-mismatched feedback
ticket cannot update evidence. No simulated branch invokes `observe`.

All three arms first check the proposed library programs and prefer strict
certified improvements, then a weakly dominant program with some possible gain.
Thus every promotion has an exact nonnegative lower return difference. Ties in
both bounds do not replace an incumbent. Public objectives have separate
incumbents; a current-goal promotion changes only its own incumbent.

If no immediate promotion is available, depth-two search enumerates the whole
current model class without dropping hypotheses. For each feasible first probe,
it partitions models by the trace that probe would return. In each partition it
allows an affordable second probe, or stops. It jointly scores the terminal
regret and worst branch debit of these contingent choices. The functional is

\[
 R(C)=\sum_g\min_{p\in\mathcal P}\max_{M\in C}
       [\max_{q\in\mathcal P}V_g(M,q)-V_g(M,p)].
\]

The sum weights the declared public goals equally and uses the fixed program
library, not arbitrary optimal policies. Duplicate labelled worlds cannot alter
max/min values. For a first probe `p`, let `C_t` be each possible observed branch;
a contingent second-probe map has terminal score `max_t max_u R(C_{t,u})`,
with the second probe allowed to depend on `t`. The implementation enumerates
the finite set of possible global terminal-regret thresholds, choosing the
lowest-debit second option in each branch that meets the threshold. It then
scores the realized worst regret and worst debit across branches. This avoids
paying to reduce regret in a branch already below the global bottleneck. For
example, when branch A offers `(regret,debit)=(0,10)` or `(1,0)` and branch B
can only achieve `(5,0)`, the free option in A has the same global regret five
and saves ten debit. A targeted regression and exhaustive small-plan comparison
check this threshold optimization. Feasibility requires that the first debit
plus every selected branch's second debit fit the currently remaining budget. Both simulated probes are
checked against the current incumbent; it is kept fixed in this hypothetical
calculation. The first probe maximizes guaranteed reduction divided by one plus
worst-branch total debit. Ties prefer immediate reduction, then the number of
first outcomes, lower debit, possible current gain, and proposer order.

Only the first probe executes. The second-probe map in `ProbePlan.branches` is a
planning explanation, never a committed future action or an observation. After
real feedback, the next episode replans from scratch and rechecks the actual
incumbent and public goal. Consequently the two-step score is a property of the
hypothetical same-goal plan; changing future goals or a later cap failure does
not establish that its predicted terminal score will be realized. Debits are
paid per actual chosen episode and never refunded after favorable outcomes.

`InformativeZeroLossAgent` instead uses the original bounded `possible_traces`
search to choose a program with more than one possible trace and exact
nonnegative lower difference. This deliberately admits informative ties with
zero immediate regret reduction. It does not enumerate complete models or
compute minimax regret. `OptimisticProbeAgent` enumerates the same complete class
but chooses the affordable program with the largest possible current return,
then informativeness and lower debit. It remains risk-budgeted; it is not an
unconstrained optimizer that bypasses admission.

## Work and stopping contract

The constructors accept `max_work=2_000_000`, `max_seconds=1.0`,
`max_models=4096`, and the inherited per-check `max_nodes`. One scoped trace hook
counts Python source-line events throughout this package during planning. The
same hard work counter covers ranking's Python code, original comparison setup
and paired search, every raw completion attempt including duplicates, policy
rollouts, partitions, regret evaluation, and final admission checking. The model
cap is separate: overflowing it cannot turn a truncated class into a
certificate. The original trace hook is restored in `finally`, including on cap
failures and unexpected exceptions. The counter is a reproducible implementation
work measure, not FLOPs, hardware-independent compute, or equal wall time.

The elapsed limit is checked at each metered Python event. It is cooperative,
not an operating-system hard deadline: a C-backed tuple/hash operation or the
fixed-library ranker's numerical operation finishes before the next event.
`max_work` is the primary hard search bound. Construction of the learner,
execution of environment episodes, evidence updates, and measurement overhead
are outside this planning cap and must be timed separately. The event counter
also excludes its own bookkeeping and third-party library internals. Existing
finite input/program-size limits still apply.

Any exhausted work/model/node/deadline cap yields `unknown`, no partial bounds,
no promotion, zero debit, and the unchanged incumbent as the declared fallback.
An incomplete class likewise returns `unknown`; an empty complete class returns
`inconsistent`. These fallback actions do not assert a positive reward or a
sound world model. Existing certificate guarantees require that the supplied
class contains the actual world. Unexpected implementation exceptions propagate
without changing learner state; they are not evidence that an action is safe.

`last_plan` reports status and reason, work and elapsed time, raw completion
attempts and distinct labelled models, completed comparison node counts,
comparisons started, the chosen program, bounds, debit, and contingent branches.
A line cap interrupting a checker can omit that unfinished call's nodes from
`check_nodes`; the global line counter still includes its actual traced work.
Cumulative counters include `planning_work`, `planning_seconds`, `comparisons`,
`nodes`, `completion_attempts`, and `labelled_models_enumerated`. There is no
cross-episode plan cache and no automatic continuation outside the active task.

## Mechanism result and limits

The previously documented four-world two-bit parity construction is a
post-hoc development diagnostic. In all four worlds, each of the three v6 arms
executes two free bit probes and then the correct decision, producing returns
`5,5,10` at risk budget zero. The final policy has a checked gain of five over
the anchor. Both the cheap zero-loss control and bounded optimism also pass.
Passing therefore establishes only that this particular stall is repaired; it
does not support a superiority claim for depth-two search.

The first depth-two plan uses substantially more counted work than the cheap
control in this diagnostic. More seriously, an analogous three-bit parity class
already defeats depth two: any two free bit observations leave parity unknown,
so the rule again rejects every free first probe and stays at return five. The
cheap control takes three informative free probes and then obtains ten. This is
an executable counterexample to exploration completeness for the depth-two rule.
It rules out presenting bounded depth two as a general complementarity solution.

The conditional retention and ledger arguments carry over because original
checking remains authoritative. They do not establish that the implementation
is fully verified in Lean, that the assumed model class is realistic, that
training helps, that the reference scales, or that an open-ended deployed system
cannot become misaligned. No generated code, self-modification, privileged
actions, external interaction, new background task, or paid compute is part of
this phase. The empirical decision is whether additional search gives useful
reward relative to the stronger cheap controls at explicitly measured cost.
