# Bounded statistical promotion gate

`src/witness_cl/statistical_gate_v7.py` implements a conventional one-sided
paired-reward betting test. It does not enumerate hidden models and does not
prove alignment, per-task safety, or general no-forgetting. The direct antecedents
and statistical assumptions are in [RELATED_WORK.md](RELATED_WORK.md).

## API and contract

```python
from witness_cl.statistical_gate_v7 import PairedBettingGate

gate = PairedBettingGate(alpha_total=0.05, max_pairs=64, max_audits=1024)
token = gate.start(candidate_digest, incumbent_digest, public_scope)
result = gate.observe_pair(
    token, candidate_reward, incumbent_reward, fresh_sample_id,
    candidate_digest=candidate_digest,
    incumbent_digest=incumbent_digest,
    scope=public_scope,
)
```

`start` freezes immutable, opaque string identifiers for the candidate, incumbent
and scope. It allocates error probability immediately. Only one audit can be
active. Every observation must name that audit and a globally unused sample ID;
optional identity keywords bind the observation record to the same identities.
A token with a different candidate, incumbent or scope is rejected. Omitting
those keywords leaves actual execution identity to the trusted caller.

Rewards must be finite Python `int` or `float` values in `[0,1]`; booleans,
strings, out-of-range values and NaNs are rejected. `observe_pair` returns an
immutable `GateResult` with status `collecting`, `accepted` or `inconclusive`,
pair count, allocated alpha, log wealth, log threshold and current journal head.
After a terminal result the token cannot consume more samples. `result(token)`
reads its result; its journal field is the current global gate head.
`finish_inconclusive(token)` allows early abandonment without an error-budget
refund. It does not mean that the candidate is worse.

Invalid starts, identities, rewards and duplicate/stale observations leave the
existing gate state unchanged. A successful new start permanently spends its
allocation, even if no pair is subsequently observed. The implementation bounds
one audit at 64 pairs and the gate at a configured number of audits, with a hard
maximum of 4,096. Reaching that cap does not automatically reset the accounting.
These are ordinary input/state checks, not a hostile-Python or process sandbox.

## Statistical statement

The candidate and incumbent must be fixed before their fresh audit data. For
pair `t`, define `D_t = candidate_reward_t - incumbent_reward_t` in `[-1,1]`.
With the fixed predictable bet `lambda=1/2`,

`E_t = product_(i=1..t) (1 + D_i/2)`, and `E_0=1`.

Under the null `E[D_t | all earlier information] <= 0` for every audit pair,
all factors are nonnegative and

`E[E_t | earlier information] <= E_(t-1)`.

Ville's maximal inequality therefore gives
`P(exists t: E_t >= 1/alpha_j) <= alpha_j` for each valid audit. At audit index
`j`, the implementation uses

`alpha_j = alpha_total / (j*(j+1))`.

The allocation is over *all* started audits, including repeated candidates and
multiple scopes. After `J` audits the total allocation is exactly
`alpha_total * J/(J+1)`, less than `alpha_total`. Conditional validity for each
fresh audit and a union bound control the probability of any false acceptance
across this adaptive audit sequence. Each protected scope must receive its own
charged audit; an accepted test in one scope does not protect another scope.

The implementation records `sum(log1p(D_i/2))` and compares it to
`log(1/alpha_j)`. It additionally maintains exact rational capital for the
represented reward values and requires its threshold crossing too. This second
check prevents upward floating-point rounding from authorizing an acceptance;
it may conservatively defer a boundary case. Alpha accounting uses the exact
rational value of the configured Python float.

For acceptance to mean positive *future scoped policy value*, sufficient
conditions are a candidate and reference frozen independently of the audit
outcomes, fresh independent draws from a stationary scope distribution, valid
pairing/reset, bounded authenticated rewards and no audit-data contamination.
Then the conditional mean is their fixed scoped value difference. Without such
a fixed estimand, rejection of an always-nonpositive conditional-mean null does
not certify the latest candidate or its performance tomorrow. Arbitrary drift,
changed routing/state, and a newly edited policy invalidate that interpretation.
This gate has zero tolerance and tests strict positive mean improvement; it
cannot demonstrate improvement when all paired differences are exactly zero.

The module cannot infer whether different IDs denote genuinely fresh cases,
whether policy digests cover all behavior-changing state, whether copies share
equivalent initial conditions, or whether the supplied reward is authoritative.
Those properties belong to the execution/evaluation protocol. Renaming reused
samples does not make them fresh. A baseline run must not contaminate the
candidate run or vice versa. No confidence statistic grants permission to run
an otherwise unauthorized action.

## Persistence and its authority boundary

`snapshot()` returns a JSON-compatible event journal without writing any files.
`PairedBettingGate.from_snapshot(snapshot)` validates and replays starts, paired
observations and early finishes. It preserves the audit counter, permanent alpha
allocations, used sample IDs and any active frozen token. After restoration,
`active_token` gives the canonical token for continuation.

An optional `minimum_started_audits` and/or `expected_journal_hash` can be supplied
from trusted external state to reject rollback. The unkeyed hash chain detects
an inconsistent partial edit; it cannot authenticate reward origin or stop
someone rewriting the entire checkpoint and trusted head. A stale but internally
consistent checkpoint cannot be recognized without an external monotone counter
or trusted head. Persistence must be durable before further authoritative use;
this module does not implement atomic files, crash recovery or concurrency.
Constructing a new gate instead of restoring the old one is not permission to
reset a lifetime false-acceptance claim.

## Power, computation and verification

The fixed half-bet and 64-pair cap are deliberately limited. At the default
`alpha_total=0.05`, the first audit receives `alpha_1=0.025`. Even a perfectly
constant positive difference `d` needs

`(1+d/2)^64 >= 40`, equivalently `d >= 0.118664` (approximately).

Thus constant five- or ten-percentage-point differences cannot pass the first
audit within 64 pairs. A constant difference of 0.2 needs 39 pairs; perfect wins
need ten. Later audits receive smaller alpha and can need more evidence.
`constant_difference_min_pairs` computes this exact zero-variance diagnostic;
it is not a stochastic power or sample-complexity guarantee. An inconclusive
result under this cap can reflect inadequate power rather than a failed learned
representation.

A positive mean alone does not give this fixed bet positive long-run growth.
For independent pairs with `D=+1` with probability `.55` and `D=-1` otherwise,
the mean gain is `.1`, but

`E[log(1+D/2)] = .55*log(1.5)+.45*log(.5) = -0.08891...`.

By the strong law, its log capital divided by the pair count converges to this
negative value, so capital tends to zero almost surely. There can still be early
crossings. In fact,

`E[sqrt(1+D/2)] = .55*sqrt(1.5)+.45*sqrt(.5) = 0.99181... < 1`.

Thus the square root of capital is a nonnegative supermartingale **under this
positive alternative**. Ville's inequality gives eventual acceptance probability
at most `sqrt(alpha_j)`: below `.159` at the first default audit, even without
the 64-pair cap. This proves a consistency limitation of this fixed wager; it
does not refute its null-error validity. A prespecified bet of `.1` has positive
expected log growth on this same alternative. A later design should compare
predictable variance-sensitive bets or a fixed convex mixture containing small
bets, as in the [bounded-mean betting literature](https://doi.org/10.1093/jrsssb/qkad009).
Those alternatives require separate implementation, tests and a new frozen
protocol. They do not remove the finite budget or multiple-audit cost.

The current relational task often produces exact policies against a weak zero
anchor, with fewer cancelling wins and losses. Its empirical results therefore
cannot establish generally affordable statistical promotion of noisy policies.

The test file `tests/test_statistical_gate_v7.py` passes 52 tests. It checks frozen
identity, transactional invalid input, nonrefundable alpha, global sample reuse,
stale tokens, exact-capital protection against a deliberately corrupted floating
statistic, checkpoint continuation/rollback, and altered-journal rejection.
The analytic positive-mean power counterexample above is checked directly.
A finite null test enumerates all 256 length-eight symmetric `D_t in {-1,+1}`
paths. With per-audit alpha 0.1, the probability of crossing at any prefix is
exactly `1/64`, below the allocation. This bounded enumeration checks the
implementation on that distribution; the general conditional validity argument
above relies on the stated assumptions and standard probability theorem.

Every paired execution, rejected candidate and validation step must be charged
in the research experiment. The gate does not make online auditing free or
remove the need to compare against simpler learned-rule and history baselines.
