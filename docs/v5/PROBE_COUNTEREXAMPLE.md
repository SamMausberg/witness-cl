# Complementary safe probes defeat the one-probe score

The frozen v5 rule can stop learning even when two observations would enable a
strict improvement at zero exploration loss. This is a concrete failure of
exploration completeness. It does not violate the admission or debit guarantees,
and the failed frozen holdout is retained unchanged.

## Four-world construction

There are four possible stationary deterministic one-state worlds, indexed by
bits `(a,b)`. The model class is explicitly restricted to these four worlds.
Every episode contains one action. All five programs below are available from
the start. The anchor and both bit probes return 5 in every world; the probes
also reveal their respective bits. A decision returns 10 if it selects the
correct parity and 0 otherwise.

| World | Anchor | Probe first bit | Probe second bit | Choose even | Choose odd |
|---|---:|---|---|---:|---:|
| `(0,0)` | 5 | 5; reveals 0 | 5; reveals 0 | 10 | 0 |
| `(0,1)` | 5 | 5; reveals 0 | 5; reveals 1 | 0 | 10 |
| `(1,0)` | 5 | 5; reveals 1 | 5; reveals 0 | 0 | 10 |
| `(1,1)` | 5 | 5; reveals 1 | 5; reveals 1 | 10 | 0 |

Use risk budget zero. The known output reward vector is `(5,5,5,0,10)`;
separate output symbols encode the two bit observations without changing their
reward. This stays within the existing deterministic trace and reward semantics.
It is a valid finite-class input, but it is not the unconstrained initial
model class used by the two-state benchmark. The bit correlation is part of the
specified class, not information the controller infers without evidence.

## Written argument and executed result

For the full class, the best fixed robust decision is the anchor or either
probe. Each has worst-case regret 5; either parity decision has worst-case
regret 10. Thus the minimax regret is 5. Learning only `a`, or only `b`, leaves
both parities possible, so the minimax regret remains 5 after every possible
single bit-probe outcome. The initial guaranteed regret reductions are
`(0,0,0,5,5)` for anchor, first probe, second probe, even, and odd respectively.

The two parity decisions each require a worst-case debit of 5 and are infeasible.
Both bit probes have exact difference zero against the anchor, but the v5
selection rule rejects their zero immediate information score. It executes the
anchor, whose feedback is identical in all four worlds. The class remains the
same, so the same reasoning applies at every subsequent episode regardless of
proposer updates. The rule can therefore stay at return 5 forever.

An alternative controller executes the first bit probe and then the second.
Each has exact lower and upper return difference zero against the anchor.
After the first probe, the second probe's guaranteed reduction is 5. After both,
the parity is known, and the appropriate decision has a certified improvement
of 5. No risk debit is needed. The first probe is useful through its interaction
with a later experiment, although its one-probe score is zero.

The executable diagnostic runs four unchanged anchor episodes, then evaluates
the alternative zero-loss sequence in a separate learner state. It records the
exact comparison bounds, retained model counts, score changes, and final +5
certificate in `artifacts/v5/formal-probe-counterexample.json`. Reproduce it:

```bash
PYTHONPATH=src python3 artifacts/v5/formal-probe-counterexample.py
```

This is an executed finite counterexample plus a written induction argument,
not an additional Lean theorem. It was found after the v5 rule and holdout were
frozen. It must not be presented as a pre-registered test or as evidence that
any revised selector already wins a benchmark.

## Consequence for the next hypothesis

A positive one-probe guaranteed regret reduction is sufficient to reduce the
chosen uncertainty functional, but is not necessary for a useful safe
experiment. A successor could permit informative zero-loss transitions or
search over two-probe plans, checking each contingent episode against its
current incumbent and preserving the existing nonrefundable ledger. The
minimum mechanism test is that it selects a first safe bit probe here and
subsequently reaches a certified return of 10 in every one of the four worlds.
Failure kills that successor's claim to address this diagnosis. Passing it
would establish only this mechanism; scaling, out-of-distribution performance,
and useful training remain separate questions. Multi-step search also creates
additional computation and stopping-rule costs that must be reported.
