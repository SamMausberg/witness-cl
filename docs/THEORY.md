> Historical v0.1 document. Current claims and extensions are in [docs/v2](v2/RESEARCH_STATUS.md).

# Mathematical scope

## Operational setting

An episode supplies a public scope/version s, input x, action opportunity a, and
trusted feedback after the action. The complete system has frozen parameters
θ and evolving deployment state S_t. No offline training stage occurs between
episodes; online state computation is counted. The strict reference uses a fixed
finite class H_s of deterministic total functions X -> A, exact binary success,
and a stationary target h*_s belonging to H_s. Scope identifiers are observable
metadata, not hidden task IDs supplied by an evaluator.

Define C_e(h) iff (h(x_e)=a_e) is equivalent to success_e. Set
V_0=H and V_t={h in V_(t-1): C_t(h)}. The model receives its action and success,
not the unobserved correct label after a failure.

## Theorem 1: truth and persistent contracts

Assume h* is in H and all observed feedback agrees with h*. Then h* is in V_t
for every t, by induction. Every update is a subset operation. If V_t is
nonempty and all h in V_t give y at x, then h*(x)=y. Since V_(t+1) is a nonempty
subset, the same unanimous prediction persists. Thus the domain of conditionally
certified predictions never shrinks inside an unchanged scope.

This theorem concerns the certified sub-policy. It neither guarantees that an
uncertified fallback improves nor that every episode reward is nondecreasing.
Changing the class, noise model, extractor, public version, or dependencies is
outside the invariant and requires a new admission argument.

## Theorem 2: exact witness condensation

Retain feedback e_t in W iff V_t is strictly smaller than V_(t-1). Replay only
W from H. The result is exactly V_t: a discarded constraint was true for every
live hypothesis at arrival and remains redundant on every subsequent subset.
Induction gives full-history equivalence, including the empty-set case.

Every retained event removes at least one hypothesis not previously removed,
so |W_t| <= |H|-|V_t|. Under realizability, |W_t| <= |H|-1. This is not a minimum
cardinality witness algorithm. A retained witness can become retrospectively
redundant; optional minimization must preserve the version set and charge its cost.
The witness-size statement counts observations, not bits of arbitrary programs.
The raw audit history is retained separately and grows with time.

## Theorem 3: a finite mistake bound for the symbolic voting policy

Let k=|A|>=2 and m=|H|. At every uncertified decision choose a most frequent
prediction among V_t. A mistaken prediction removes at least |V_t|/k hypotheses.
Successful decisions cannot increase the set. After M mistakes,
1 <= |V_t| <= m(1-1/k)^M. Therefore
M <= ln(m)/[-ln(1-1/k)]. Sum this bound over stable public scopes.

This is a standard elimination-style argument, not a newly invented learning
bound. It does NOT apply to the optional LLM fallback, which can select an action
not supported by any hypothesis, nor to hidden drift or a misspecified class.
Repeated informative evidence is needed for complete identification. There is
no guarantee that arbitrary input sequences identify every parameter.

## Corollary: affine transfer

For prime p, let h_(a,b)(x)=a*x+b mod p. Two successes at distinct inputs x1,x2
identify (a,b) uniquely: the nonzero difference x2-x1 is invertible in F_p, so
a=(y2-y1)/(x2-x1), b=y1-a*x1. Thus outputs at other inputs follow without storing
those answers. Two arbitrary feedback events need not be successes or identifying.
The simulator does not provide these successful examples for free.

## Theorem 4: fresh paired admission

At candidate birth freeze candidate policy, incumbent policy, scope and all
behavioral dependencies. Assign a never-reused global index j and
δ_j=δ/[j(j+1)]. After birth observe fresh paired episode reward differences
D_i=R_i(candidate)-R_i(incumbent) in [-1,1]. Require under the null that
E[D_i | F_(i-1)] <= 0. With fixed nonnegative stakes λ in [0,1], define
M_(λ,n)=product_(i<=n)(1+λD_i). Each factor is nonnegative, and
E[M_(λ,n)|F_(n-1)] <= M_(λ,n-1). The average E_n of these products is therefore
a nonnegative supermartingale starting at one. Ville's inequality bounds
P(sup_n E_n >= 1/δ_j) <= δ_j. Summing over adaptively proposed null candidates
is valid because each guarantee holds conditionally on its pre-audit history;
sum_(j>=1) δ/[j(j+1)]=δ.

This controls ever admitting a candidate satisfying the null conditional-mean
condition. A stationary iid scope gives the simpler interpretation that no
nonpositive-mean candidate is admitted, with probability at least 1-δ. An
arbitrary future distribution can change after admission, so the conclusion
does not certify future drift, each individual case, or safety beyond the reward.
There is no new probability theorem claimed; the contribution to test is its
operational use with explicit episode provenance and full-system snapshots.

A candidate admitted against an obsolete comparator can be worse than the
current incumbent. `can_promote` therefore requires the current baseline hash
to equal the audit's baseline hash. Hashes must be computed by the trusted harness.
Indices must remain unique across processes, retries, restarts, scopes and model
search. The low-level Python class is not a durable global allocator.

## No counterfactual oracle

A saved trajectory gives feedback for executed actions only. Paired evaluation
requires two honest simulator forks from a fresh initial state, a real sandbox,
or a randomized live experiment. Both rollouts and all audit interactions count.
In a non-cloneable environment use randomized assignment with known propensity,
and derive the appropriate bounded difference estimator and test. That extension
is proposed, not implemented. Never score an unexecuted action from privileged
benchmark labels or expose evaluator-only feedback to the learner.

## Conditional expected-retention corollary

If every accepted change replaces only its publicly guarded scope, each scoped
reward distribution stays stationary, every comparator is the current incumbent,
and all valid tests share the global δ allocation, then on the no-false-admission
event each accepted scope's expected reward increases and untouched scopes'
policies are unchanged. This is a distributional claim under assumptions, not
per-episode monotonicity or universal continual-learning safety. It does not
inherit validity from a frozen backbone alone.

## Boundaries that cannot be removed by bookkeeping

Two indistinguishable worlds have baseline action reward 1/2. A new action gives
1 in one world and 0 in the other. Before informative feedback, any positive
probability of trying it lowers expected reward in the second world. Requiring
no degradation in both worlds forces zero probability of trying it; without
other information there is then no improvement in the first. This separates
safe information gathering from impossible unconditional guarantees.

For retention, N independent bits allow 2^N histories. A deterministic persistent
state with fewer than 2^N distinguishable states must merge two histories that
differ at some queried bit. It cannot answer all subsequent bit queries exactly
in both histories. Thus arbitrary exact retention needs at least N bits of total
persistent state, unless external storage or structured/compressible histories
are allowed. The result does not forbid bounded active context with growing disk.

## Lean boundary

Logical core source is in `formal/WitnessCL/Core.lean`. It was not compiled in
this environment. Probability, the witness cardinality and mistake bounds,
affine field algebra, and refinement to the Python runtime remain handwritten
mathematics plus tests, not machine-checked theorems.
