# Training, inference and algorithm choices

## Primary: online compilation, frozen neural parameters

Let θ remain fixed after deployment. After each authorized feedback event,
update an external version space and its witness set. These are learned states:
they change how the system responds to unseen inputs. No optimizer pass over a
predeployment dataset, sleep phase, or separate offline retraining run is needed.
Calling this training-free means no parameter training, not no learning or compute.

At inference, route by trusted observable environment metadata, check the public
version and dependencies, and use a cached or newly unanimous contract only
inside its exact domain. Otherwise fall back to the original model with retained
evidence. The implementation's default non-model fallback is majority vote, which
supports the finite mistake bound. Replacing it with an LLM removes that bound.

The optional local-model experiment compares raw ICL, Witness with full-history
fallback, and Witness with only the witness evidence supplied to fallback. Exact
witness equivalence preserves a symbolic hypothesis set; it does NOT prove that
a finite LLM acts identically on the shorter prompt. That is a separate measured
ablation. Full prompt histories and usage are logged so input savings are audited.

## True online updates as a baseline

`online_ridge.py` implements per-scope recursive least squares. It accepts a
feature vector and an actual scalar target observed after the episode. Its state
is an inverse regularized Gram matrix and coefficient vector, updated once per
example. Tests compare it to the batch ridge solution to numerical tolerance.
Separate public scopes have separate states. This is standard regression, not a
new neural learning algorithm or a theorem of within-scope zero forgetting.

For a future neural extension, freeze the backbone and previous adapters, allocate
a scoped residual adapter, and update only it using authorized real labels or
verified outcome gradients. Distillation from a conditionally certified rule is
valid only within that rule's assumptions. Never convert a failed action into a
fabricated correct label. A frozen prior adapter retains its parameters but a
changed router can still stop using it; test behavioral retention separately.
This neural extension is not implemented or benchmarked in this release.

## Proposed real-domain compiler

Candidate grammars should target repeated operations such as a versioned API
argument convention, a numeric unit conversion, a schema projection, or a pure
validated transformation. The shipped grammar is intentionally just affine
modular arithmetic. Extending to SQL, arbitrary code or hidden dynamics requires
a task adapter, evidence extractor, and sound domain semantics, not renaming a
natural-language summary a certificate.

An LLM can propose programs or abstractions, but finite samples from it do not
cover all possible targets. Exact admission requires a declared exhaustive class
or an independently sound verifier of the particular property. Everything else
is empirical and enters the fresh-audit branch. Program search, checking and
routing belong in the cost budget. Effectful tools must stay behind the original
permission boundary, never inside generated executable memory.

## Scalable implementation hypothesis

A bitset over a small grammar makes elimination vectorizable. Precomputed output
signatures amortize recurring finite-domain queries; compiled total programs can
avoid model calls. A content-addressed immutable skill store and explicit public
version keys provide inexpensive dependency invalidation. None of this implies
new information beyond the history. If induction is already cheap, full ICL
prefix caching is excellent, or most queries never fit a reusable contract, the
compiler may lose once its overhead is counted. No GPU speedup is asserted.
