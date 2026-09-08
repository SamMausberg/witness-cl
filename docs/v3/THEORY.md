# Witness-CL v0.3: continuation contracts

Author: Samuel Mausberg. AI-assisted research draft, 8 September 2026.

## Status and scope

This revision extends v0.2, rather than replacing its results. The integrated new
controller is a finite-family deterministic, finite-horizon online learner. It
learns from actual executed transitions. It does not receive counterfactual
observations. It can enumerate the **supplied** environment family for planning.
This is a strong structural assumption, not environment discovery from language.

The statements below have handwritten proofs and executable regression checks.
The Lean sources are attempts: no compiler is available in this environment and
installation attempts failed. Tests are not Lean verification. The noise filter,
neural modules, and paired simulator are separately tested components, not one
fully integrated general LLM agent.

## 1. Precisely what is being protected

Evidence retention means raw observations are not silently erased or reinterpreted.
Representational retention means an archived function's parameters and input
construction are unchanged. Incumbent retention means later certified policies
perform at least as well as earlier certified policies under a specified actual
world. Deployment retention additionally includes router decisions and exploratory
executions. The latter cannot be inferred from the former three.

Let M be a finite family of stationary deterministic environments. Each has
horizon H, states S, actions A, transition T_m(t,s,a), and bounded integer reward
r_m(t,s,a). The stage is observable; the hidden environment index is not given to
the learner. Environments reset at episode boundaries. All future-relevant state
is included in s. Let b_0 be an immutable baseline and let V_m^p(t,s) be the full
remaining return under policy p, with V_m^p(H,s)=0.

The exact-feedback consistency set C_n contains precisely those m that agree
with every actually observed transition. If the true environment m* is initially
in M, observation filtering retains it. This is induction on the observation
sequence. If a proposed new model is added, replay every old transition for that
model. A constraint redundant on the old class need not be redundant on the
expanded one. If C_n is empty, refuse certification; universal quantification
over an empty family must not be interpreted as a valid deployment proof.

## 2. Closed continuation equivalence

Represent a whole system transition by F(z,u)=(z',o), where z contains environment
state, controller state, selected module, normalized inputs, permissions, and any
internal random state not supplied on the exogenous tape u. Let P be a protected
domain. Suppose for every z in P and every admissible u:

    F_old(z,u) = F_new(z,u), and the common successor belongs to P.

Then every finite output trace and the final state agree from every protected
initial z under a shared input tape. Proof: induction on tape length. The first
transition agrees; forward closure supplies the induction hypothesis for the
remaining tape. `closed_continuations_equal` states this in Lean.

Closure is essential. Two policies can emit the same current action, update their
internal memories differently, and disagree at the next step. Agreement at one
observation also fails when the common successor leaves the protected domain.
Both counterexamples are executed. Equality of a hash is only an engineering
identity check; the theorem assumes equality of complete semantic state, not
collision-free or complete hashing by fiat.

For stochastic systems this yields pathwise equality under a valid coupling,
therefore equality in distribution. It does not authorize cloning external tools
or manipulating a live world into the counterfactual state.

## 3. Full-horizon local improvement

For an incumbent b, compute its value in each currently plausible model. Define

    A_m,b(t,s,a) = r_m(t,s,a) + V_m^b(t+1,T_m(t,s,a)) - V_m^b(t,s).

A candidate c is admissible when A_m,b(t,s,c(t,s)) >= 0 for **every** live model,
time, and state. The incumbent action is always admissible by its Bellman
identity. Among admissible actions, the reference picks the largest summed
advantage, using a stable incumbent-preserving tie break. This objective is only
a heuristic for speed of improvement; safety uses the minimum over models.

Theorem. Every such c satisfies V_m^c(t,s) >= V_m^b(t,s) for every plausible m,t,s.
Proof: backward induction. Terminal values agree. At an earlier state,

    V_m^c(t,s)
      = r_m(t,s,c) + V_m^c(t+1,T_m(t,s,c))
      >= r_m(t,s,c) + V_m^b(t+1,T_m(t,s,c))
      >= V_m^b(t,s).

This is classical policy-improvement reasoning, not a claim of new Bellman
algebra. `bellman_improvement` attempts this exact deterministic induction in
Lean, with remaining-horizon indexing. There is no formal refinement map from
Python's stage-indexed arrays to this abstraction yet.

The all-state condition is stronger than an average-return test and prevents
trading a protected minority state's value for a majority gain. It is sufficient,
not necessary. Joint changes can improve total return even when one action has
negative advantage relative to the old continuation. Those changes need a more
expressive certificate, not a claim that the theorem proves their failure.

### Retaining improvements, not only the original baseline

Evidence contraction preserves a universal obligation. Therefore the algorithm
starts each improvement round from the **previous certified incumbent**, not
from b_0. Repeating the comparison gives a pointwise nondecreasing sequence of
incumbent values for every surviving true model. Re-optimizing from b_0 alone
would guarantee only a baseline floor and could forget previously acquired gains.
The final tests check this invariant across every simulated update.

A class expansion with new plausible models starts a new, explicitly marked trust
era and rechecks from b_0. Earlier certificates are not inherited on a larger
class. Behavior can change relative to a previous incumbent at that boundary.
The monotone-incumbent claim is therefore restricted to a stationary,
truth-retaining, class-contracting era. Detection of hidden change cannot prevent
the first harmful action. The regression test demonstrates exactly that failure.

## 4. Paying for exploration before receiving its outcome

A certified policy may provide no identifying information. For a proposed complete
episode policy p at observed initial state s_n, define

    D_n = max(0, max_{m in C_n} [V_m^{b_n}(0,s_n)-V_m^p(0,s_n)]).

Only run it when total prior debits plus D_n do not exceed budget B. Debit before
execution. Do not refund a trial merely because its realized outcome was good.
The reference ranks feasible trials by worst-case model elimination, then
optimistic gain and lower debit. It evaluates predicted trajectories for each
model and counts these as planning work, never as observed feedback.

Theorem. Within a stationary realizable era with episodic resets and deterministic
rewards, at every completed episode prefix N,

    sum_{n<=N} [V_{m*}^{b_0}(0,s_n)-R_n] <= sum_{n<=N} D_n <= B.

Proof: incumbent improvement gives V^{b_0} <= V^{b_n}; truth membership gives
V^{b_n}-V^p <= D_n; deterministic execution gives R_n=V^p. Add the inequalities.
This proof does not require independently drawn initial states. It DOES require
the baseline comparison to begin at the same actual initial state, and the reset
assumption prevents experimental actions from changing unaccounted later starts.
For environments with cross-episode carryover, the comparator is not the baseline's
counterfactual lifelong trajectory and this displayed bound must not be advertised
as such. Include continuation value, prove regeneration, or use a different theorem.

The integer debit arithmetic is formalized abstractly in `debit_budget`. This
budget is a cumulative reward-deficit bound under the assumptions, not a ban on
individual adverse actions, irreversible harm, or malicious input.

### Why zero risk can block improvement

Two unknown worlds give the baseline action reward 5 in both. A trial gives 10 in
one and 0 in the other. Baseline observations are identical. A deterministic
algorithm required never to lose relative to baseline in either world cannot
try the second action and cannot improve in the favorable world. For randomized
policies, a trial probability p>0 incurs expected deficit 5p in the bad world;
zero expected deficit again forces p=0. A risk budget, informative safe action,
trusted side information, or a simulator is needed. This is an assumption-level
obstruction, not a reason to stop researching the problem.

## 5. Noise-aware evidence without deleting a truth after one failure

For a FIXED finite family of probabilistic conditional outcome models, choose
positive prior weights pi_m before any observation. Let

    L_m,n = product_{i<=n} P_m(observed outcome_i | past_i, chosen action_i),
    L_mix,n = sum_m pi_m L_m,n,
    E_m,n = L_mix,n / L_m,n.

Under true m, each likelihood ratio is a nonnegative supermartingale, with
martingale equality under appropriate common support. Predictable adaptive
actions do not invalidate the conditional likelihood argument. Mixtures preserve
this property. Ville's inequality therefore yields

    P_m(ever E_m,n >= 1/delta) <= delta.

Keep models with E_m,n < 1/delta. The actual true model is retained at every time
with probability at least 1-delta. This is standard likelihood/e-process logic,
not a novel concentration inequality. `likelihood.py` uses exact Fraction
arithmetic; tests enumerate all binary histories of length six and verify the
likelihood-ratio expectation is exactly one in a common-support example.

Important boundaries: the result assumes correctly specified conditional outcome
probabilities, not a fitted neural model's uncalibrated score. A model generated
from old data cannot be inserted with retroactive likelihood credit. Priors and
models must be fixed in advance or a fresh audit epoch/valid adaptive construction
is necessary. The integrated deterministic ContractAgent is NOT silently upgraded
to noisy control by this separately tested filter. A stochastic controller would
need expected transition backup, valid model coverage, and a martingale allowance
for realized-return deviations; the deterministic debit bound cannot be reused.

## 6. Approximate abstraction: a testable route beyond enumerated worlds

Proposed extension, not implemented. Learn a typed abstract transition model from
raw episodes, with certified reward error <= epsilon_r and transition total-
variation error <= epsilon_p uniformly over every reachable state-action pair.
Both true and abstract rewards are in [0,Rmax]. For any fixed policy and remaining horizon h,

    |V_true - V_abstract| <= h epsilon_r + Rmax epsilon_p h(h-1)/2 = E_h.

Proof: inductively bound reward error by epsilon_r, next-value error by E_{h-1},
and expectation error by epsilon_p times next-value span, at most
(h-1)Rmax. Summing the recurrence proves the expression. Thus an abstract
candidate-minus-baseline improvement exceeding 2E_h is sufficient for actual
improvement. To select a policy adaptively, the error envelope must hold uniformly
for all relevant policies or all corresponding state-action pairs.

A fitted model with small training error does NOT supply this envelope. Alias two
states with different downstream consequences and the guarantee fails. The
proposed learning mechanism is counterexample-guided abstraction refinement:
retain raw transition witnesses, split abstract states when outcomes conflict,
version the old abstraction, and recertify affected continuations. This is a
concrete research hypothesis, not an assertion that arbitrary language-agent
worlds admit small identifiable abstractions. Kill it when coverage is too weak
to admit any useful patch or the abstraction explodes to raw-history size.

## 7. Learning new features without overwriting old ones

V0.2's residual W(I-UU^T)phi protects an old feature span but cannot learn when
that span fills the feature dimension. The new component instead trains a new
feature map and head in an isolated module and freezes its bytes at registration.
Old public-schema dispatch and old input construction never change. For every
input routed to an old module, its function is unchanged. Combined with a closed
continuation contract, the entire protected trace is unchanged.

This is architectural isolation, related to progressive neural networks. It is
not a novel answer to forgetting in fixed-size neural networks. Storage grows
with modules. The executed neural diagnostic uses exact binary outcomes from the
chosen action, with two exhaustive actions. Success and the chosen action reveal
the correct binary target. This inference is invalid with noisy feedback or more
than two actions without additional supervision. Public scope indicators are
available to all compared learners. The neural branch is not integrated into the
stateful controller and does not establish transfer for pretrained LLMs.

Exact arbitrary old recall also has a storage limit: after N independent binary
facts, a system answering every possible old-fact query must distinguish 2^N
histories, requiring at least N bits of state. Bounded active memory can coexist
with an archive; uniformly bounded total memory cannot preserve unlimited
independent information exactly.

## 8. Coupled execution and operation counts

Both controllers advance their own internal memories on every step. The simulator
shares ONE environment transition precisely when states and actions agree under
the same noise-tape element. Otherwise it executes both continuations. It may
share later transitions after actual state reconvergence, but it never assumes an
unexamined suffix is equal. With H steps and L actual shared transitions, calls
are 2H-L versus 2H for independent execution. Controller calls remain 2H.
Hashes, state copies, tool isolation, screening, and all generated candidates
must be charged in real deployments.

This reduces simulated environment calls only. If generation dominates total
latency, the saving can be negligible. The reference uses pure functions; no
native codebase/database/CL-Bench environment was cloned or run here.
