# Witness-CL v0.2: precise guarantees and derivations

Status: handwritten mathematical arguments plus executable tests. There are 29
Lean theorem attempts across the old and new modules. None was kernel-checked in
the authoring environment. The Lean sources cover predicate/guard algebra, not the
probability, real linear algebra, SQL, or CUDA claims below.

## 1. Evidence-preserving representation growth

For rule class H and chronological observations E, let
V(H,E) = {h in H : every observed binary outcome agrees with h's chosen-action prediction}.
For a fixed H, retaining exactly the constraints that shrink V is sufficient,
with |W| <= |H| - |V|. No realizability is required for this equality.

When new rules G arrive, the correct state is V(H union G,E), NOT generally
V(H union G,W_H). Proof: distributivity gives
V(H union G,E) = V(H,E) union V(G,E).
Previously discarded constraints were known redundant only on H, not on G.
Concrete counterexample: H contains only a constant-zero rule and E contains a
successful zero prediction at x=1. W_H is empty. Adding a rule that outputs one
at x=1 is accepted by W_H and rejected by E. This regression is executed in tests.

Implementation: stage the enlarged class, replay the current inference epoch's
complete raw observations, recompute its witnesses, and atomically install the
result. A failed interpretation cannot half-commit. Old epochs remain archived;
observations from incompatible historical regimes are not pooled as one stationary
constraint system. This is evidence preservation, not a proof that a new grammar
contains the true environment rule. Resource-bounded grammar search can fail.

## 2. Recurrence-aware mistake accounting

Within one deterministic, realizable, unchanging epoch, give every rule h positive
prior mass pi(h), choose a maximum-mass predicted action, and delete rules
inconsistent with exact observed success. If K bounds the number of distinct
predicted actions, each mistake removes at least 1/K of surviving mass. Since the
true rule retains mass pi(h*), M mistakes imply
pi(h*) <= (1-1/K)^M, hence
M <= log(1/pi(h*)) / [-log(1-1/K)].
More precisely, with different K_t on mistake rounds,
sum_mistakes -log(1-1/K_t) <= log(1/pi(h*)).

A fresh-epoch prior is (1-beta)/|H| plus beta/|A| for archived rules A.
For a returning archived truth, pi(h*) >= beta/|A|. Therefore the recovery bound
depends on log(|A|/beta), rather than log(|H|/(1-beta)). This is a standard weighted
elimination bound applied to recurrence, not a new learning-theory result.

Change handling does not require hidden regime IDs. Contradiction grows the
representation if possible; otherwise it forks the inference epoch without
rewriting archived programs. If the *fixed final class* had uniquely identified
the old rule, its first wrong prediction after a change causes immediate
contradiction. Prior to that first disagreement, its predictions remain correct.
This gives at most one wrong action before recovery starts under that assumption.
It does NOT apply to arbitrary short regimes, noisy feedback, a still-ambiguous
class, or an expansion that invents a mixed-history explanation. Actual tests
include rapid-switch and noisy failures.

## 3. Soft routing when deletion is unsound

For a fixed archive of M policies over K actions, form q_t from normalized expert
weights; sample p_t=(1-gamma)q_t+gamma/K. Only the chosen action's loss ell_t(A_t)
is observed. Use unbiased estimated expert loss
hat ell_(t,i) = ell_t(A_t) * 1[a_(t,i)=A_t]/p_t(A_t).
Exponentially update with eta and mix alpha/M of total mass back into each expert.
All experts remain available with normalized weight at least alpha/M.

Against an expert sequence with S switches in T rounds, define
B = log M + S log(M/alpha) + (T-1-S) log(1/(1-alpha)).
Then the usual potential proof gives expected regret at most
B/eta + eta K T/[2(1-gamma)] + gamma T.

Proof details: interpret sharing as a Markov prior over expert sequences. The
comparator prior is at least (1/M)(alpha/M)^S(1-alpha)^(T-1-S), so its code length
is at most B. Use exp(-z) <= 1-z+z^2/2 for z>=0 and log(1+u)<=u in the mixture
potential. Summing yields estimated regret <= B/eta + (eta/2) sum_i,t q_i hat ell_i^2.
Conditional expectation of the latter round term equals
sum_a q_t(a) ell_t(a)^2 / p_t(a) <= K/(1-gamma).
The sampling mixture costs at most gamma per round relative to q_t. IPS gives
unbiased comparator losses. These inequalities hold for nonanticipating losses
with counterfactual actions defined for the same context.

This is an expectation bound, not a confidence bound, safe-exploration theorem,
or comparison against the counterfactual state trajectory of a reactive agent.
The implementation covers a fixed archive; its proof does not silently cover
adaptive births. Growing-archive routing needs a growing-expert bound or separately
charged epochs. For short dwell times the displayed bound can exceed T, which is
vacuous. This is reported in the experiments.

## 4. Local residual admission and protected behavior

For immutable deterministic one-step policies b,c and a frozen observable gate g,
let p(x)=c(x) on g(x)=1 and b(x) elsewhere. Outside g, p=b pointwise. If rewards
use the same input/environment randomness, D=R(p)-R(b)=0 outside g. With gate
probability rho and stationary contexts,
E[D] = rho E[D | g=1].
Thus testing conditional benefit on the gate is sufficient to establish positive
overall mean benefit when rho>0; protected inputs outside g require no statistical
retention test. Protected subgroups *inside* the gate do require separate tests or
exact obligations. Average improvement cannot protect every subgroup.

For a fresh paired difference D in [-1,1] and a predictable stake lambda in [0,1],
1+lambda D is nonnegative and has conditional mean at most one under the null
E[D | past]<=0. Products, fixed mixtures, and predictable stakes therefore support
an anytime-valid crossing test. Candidate j receives delta_j=delta/[j(j+1)].
Summing conditional false-admission probabilities controls ever accepting a null
candidate by delta, if IDs never repeat and every candidate/guard/comparator is
frozen before its audit data. An incumbent hash change invalidates promotion.

Skipping exact zeros leaves the product IDENTICAL. It saves redundant second
rollouts, not statistical evidence or calendar episodes. At N deployment
opportunities and n_g gated episodes, dense paired evaluation costs 2N rollouts;
screened evaluation costs N+n_g. The marginal extra rollout count falls from N
to n_g, about 1/rho, but total rollout savings cannot be called 1/rho. Screens,
policy-prefix evaluation, and simulator forks must also be charged.

For multistep agents, the valid extension is a coupled common-prefix execution
and a real fork at the first behavioral divergence, with both policies' full
internal states tracked. Agreement on the current action alone is NOT evidence
of equal future behavior. Only the one-step system is implemented here.

## 5. Live randomized auditing without a counterfactual oracle

Sample treatment A with logged e in [p_min,1-p_min], before observing its reward
R in [0,1]. With fixed c=1/2, define
Z=(A/e-(1-A)/(1-e))(R-c).
Conditional on the context and preassignment history, randomization gives
E[Z] = E[R(candidate)]-E[R(baseline)] and |Z|<=B=1/(2p_min).
Proof: the treatment term's expectation is E[R(candidate)]-c, and the control
term's expectation is E[R(baseline)]-c. Subtract and cancel c.
Use 1+lambda Z/B in the same betting test. At e=1/2, B=1.
The bound is CONSTANT across contexts: context-dependent normalization can change
the estimand and must not be substituted without a new argument.

The integrated system learns the proposer from every executed action's feedback,
freezes a provisional candidate even before unique identification, runs a live
randomized audit only on action disagreements, and promotes only on a passing
fresh comparison. Without provisional exploration, a baseline can produce no
information distinguishing alternatives. A regression test checks this deadlock.
Detections can retire an audit; the discarded audit cannot resume with its old
index or omit unfavorable observations and continue. A new proposal's birth cut
strictly excludes the observations that generated it. Experimental treatment can
hurt individual episodes; admission control does not make exploration risk-free.

## 6. The sample requirement is partly irreducible

Consider iid informative differences D in {-1,+1}, a null mean zero, and an
alternative mean mu>0. Let p=(1+mu)/2. A test with null admission <=a and alternative
power >=1-b, with 0<a<1-b<1, must satisfy
E_mu[N] * kl(p || 1/2) >= kl(1-b || a).
The proof is likelihood-ratio chain rule plus data processing to the final binary
admission decision; for a finite horizon pad an early stop with no information,
or use the standard integrable-stopping argument. Here
kl(p||1/2) = [(1+mu)log(1+mu)+(1-mu)log(1-mu)]/2 ~ mu^2/2.

At a=.025, b=.2 and mu=.05, the bound is 1963.79 expected informative observations.
A generic reliable 128-sample five-point test is therefore not available in this
high-variance setting. For a sparse residual with rho=.1 and conditional mu=.5,
the same global five-point gain requires at least 18.77 informative gated
observations, but waiting for gates still costs deployment opportunities. This
makes locality and outcome variance substantive algorithmic design variables.
It does not establish that every real agent improvement can be localized.

## 7. Online trainable residuals with an exact algebraic protected span

Freeze the feature extractor phi and prior predictor f. Let columns of U form an
orthonormal basis for the span of protected feature vectors and P=I-UU^T. Set
f_new(x)=f(x)+W P phi(x). For any protected feature in span(U), P phi(x)=0, so
f_new(x)=f(x) for EVERY W, not merely to first order in a gradient step.

With computed projection P_tilde and approximate protected coverage, output drift
is bounded by ||W|| * ||P_tilde phi(x)||. The shipped SVD/SGD code is float64 and
reports measured drift; it does not claim bitwise or real-arithmetic equality.
Changing phi, input construction, the router, or protected feature span invalidates
this argument. This is exact fixed-feature nullspace control, closely related to
established orthogonal-gradient methods, not a new neural-network theorem.

Capacity cost: if the protected span has rank d, P=0 and no residual learning is
possible. More precisely, for isotropic new-task features and desired linear
change d*, min_W E[(d*^T phi-WPphi)^2]=||U^T d*||^2. Orthogonal decomposition proves
this because the projection-span component cannot be changed and its complement
can be matched. Observable context-separated features or additional frozen
modules supply capacity; an unobservable conflicting context cannot be repaired
by this projection alone.

## 8. Shared relational statistics and exact masks

With F nullable Boolean fields, partition rows by a base-3 pattern in {NULL,0,1}^F.
For C numeric fields, store A[pattern,c]=sum coalesced values in that bucket.
Each typed filter f is a fixed set of patterns; its aggregate S[f,c] is the sum of
A over those patterns. A sum/difference recipe is S[f,c1]-S[f,c2]. Disjoint bucket
partition plus distributivity proves equality to the direct interpreter. The
SQLite parity oracle independently checks NULL/empty/negative-value semantics.

Directly interpreting H recipes costs O(H R(F+1)). Building and applying the cube
costs O(R(F+C)+P 3^F(F+C)+H), where P is the number of distinct filter signatures.
The cube itself uses O(3^F C) storage. The implemented filter cache additionally uses O(P C), and materialized outputs use O(H) storage. It is useful only for small F;
large cubes can be worse than direct evaluation. Snapshot bounds cap absolute
sums/differences well below signed int64 overflow. The int32 CUDA mask path needs
an additional checked int32 output bound; arbitrary int64 SQL sums cannot be cast.

For binary consistency mask C and old live bitmap L, the new bitmap is L AND C.
A nonempty result is unanimous iff the min and max of active query predictions
are equal. Warp ballots implement the conjunction and pack 32 hypotheses per
word. Per-word summaries reduce without FP rounding. The CPU C++ oracle and CUDA
sources are separate from the Lean predicate proof; no compiler refinement theorem
is claimed. Consensus for an observation is not a prediction for a future input:
new-input predictions must be computed and separately summarized.
