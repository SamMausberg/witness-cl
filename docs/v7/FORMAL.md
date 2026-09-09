# Finite-population promotion accounting (v7)

## Checked result

Lean 4.19.0 checks 77 project theorem declarations: the prior 63 and 14 new
statements in `formal/WitnessCL/StatisticalBridge.lean`. The complete axiom audit
passes with no placeholders, custom source axioms, `sorryAx`, or unexpected
dependencies. Only Lean's standard `propext`, `Quot.sound`, and `Classical.choice`
appear; the new module uses no `Classical.choice`.

The new result replaces the *world-class premise of this accounting layer*
with an explicit finite-context return functional. It does not establish that a
statistical audit gate is valid, nor replace every assumption elsewhere in the
project. Each `Version C B` contains exactly `C` integer returns in `0..B` for a
frozen policy on the same declared context population. `total` computes their
sum. For `C > 0`, its uniform expected return is exactly `total / C`.

For each accepted promotion from `old` to `candidate`, the Boolean `failed` is
computed from actual population totals:

```
failed(old, candidate, tolerance) =
    (total(candidate) + tolerance < total(old)).
```

This is the underlying erroneous-promotion event, not an observed audit rejection
or a test statistic. The learner need not know its value. In this proof, the
return vectors supply the actual finite-population values against which an audit
would be assessed. There is no assumed complete class of latent transition
models and no uninterpreted consistency oracle.

For every finite accepted promotion history, the main theorem proves

```
initial_total <= final_total + sum(tolerances) + C * B * failed_promotions.
```

Dividing by the positive fixed context count yields

```
initial_expected_return <= final_expected_return
                          + sum(tolerances) / C
                          + B * failed_promotions.
```

Tolerances in the implementation are in **population-total units**. A tolerance
in per-context expected-return units must be scaled accordingly. If returns are
further normalized by `B > 0`, divide every quantity by `C * B`.

## Historical versions and tolerance accumulation

`historical_version_bound` applies the same inequality to the suffix after any
chosen historical version. The proof establishes final-version composition,
tolerance-sum composition, and failure-count composition over concatenated
histories, so selecting a history prefix identifies any earlier incumbent.

`historical_no_failure_bound` removes the failure penalty when the complete
history has zero failed promotions. `historical_no_forgetting` additionally
requires zero accumulated tolerance after the historical version. It then
proves that the final uniform population value is at least that historical
value. These are deterministic statements for every finite history, independent
of how candidates were selected or how many rejected audits occurred between
accepted promotions.

Nonzero tolerances are not free. The formalized example family includes totals
`4 -> 3 -> 2`, each promotion allowed tolerance 1. Neither promotion fails, but
the original total loses 2. Protecting an overall tolerance requires an explicit
bound on the accumulated tolerances; a constant per-promotion tolerance does not
supply an unlimited no-forgetting guarantee.

The checked `context_regression_counterexample` also shows that `[1, 1]` and
`[0, 2]` have equal uniform population return although context zero regresses.
Under a later distribution concentrated on that context, expected return also
regresses. No theorem here turns average performance into pointwise protection
or transfers it to a changed context distribution.

## Executable evidence

`formal/StatisticalFixture.lean` compiles into `statistical_fixture` and emits
all 2,916 two-promotion chains of two-context return vectors in `0..2`, with
per-promotion tolerances in `0..1`. There are nine possible frozen versions.
The output includes the actually computed population totals, failure Booleans,
suffix tolerance/failure counts, and bounds against all three historical
positions. Its JSONL artifact has 2,917 rows including the schema header.

Six tests in `tests/test_statistical_bridge_v7.py` verify exact source/fixture
provenance, exhaustive coverage, Python/Lean totals and failure-event agreement,
all 8,748 historical bounds, the context/distribution counterexample, and
accumulation of permitted tolerances. Together with the five archived v6
executable tests, the targeted run passes all 11 tests. This is a finite
executable correspondence check, not a proof of a Python statistical procedure.

Reproduce from the repository root:

```bash
python3 formal/audit.py --output artifacts/v7
python3 -m pytest tests/test_statistical_bridge_v7.py tests/test_formal_v6.py -q
```

The audit builds both executable fixtures and inventories every theorem's axioms.
Exact build output, complete axiom declarations, source hashes, raw fixture,
and test records are in `artifacts/v7/formal-*`.

The archived v6 Lean modules, fixture source, and artifact hashes remain exact.
Its provenance test now stores the original import/target configuration, verifies
that stored text against the original archive hashes, and permits only additive
imports or build targets through structured comparison. This narrowly allows the
v7 module/fixture to coexist without rewriting v6 evidence or silently dropping
any v6 import or target.

## Probability and operational obligations not proved

No probability space, concentration inequality, e-process, optional-stopping
argument, adaptive union bound, sampling implementation, or confidence level is
formalized in this module. A claim such as "all accepted promotions are valid
with probability at least 1-delta" requires a separate justified statistical
argument and an implementation satisfying it. The deterministic theorem only
supplies the consequence of the resulting promotion-failure events.

For fresh paired audits, the outstanding statistical obligations include freezing
both compared versions before collecting their audit data, controlling the
conditional sampling law given all previous audit and training history,
respecting the bounded-return assumptions, and allocating a genuinely summable
error budget across adaptive tests. Reusing an audit sample to select the next
candidate is not automatically covered by a fresh-data argument. Checking a
confidence bound after many observations requires actual anytime validity, not
repeated use of a fixed-sample claim.

The return vectors must also correspond to the declared frozen policies and the
same context population. Lean checks their sizes, bounds, and arithmetic; it does
not authenticate evaluation, prove a policy is frozen, enforce reset, isolate a
SQLite database, or verify an LLM/backend. The zero-context type is allowed by the
arithmetic definitions, but interpreting its total as a uniform expectation
requires `C > 0`.

There is no deployment, arbitrary policy execution, model training, or network
operation in either Lean fixture. The new bridge does not prove practical
continual-learning gains, statistical power at affordable cost, robustness to
drift, or alignment. Its contribution is a checked statement of exactly how
promotion errors and tolerance spending affect historical population values.
