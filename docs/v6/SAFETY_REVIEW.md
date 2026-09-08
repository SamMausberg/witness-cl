# Independent bounded-planner and experiment review

Review completed 8 September 2026. This is a correctness and research-scope review
of the local finite simulator. It is not a deployment security audit, a proof of
Python correctness, or a general alignment certificate.

## Verified review evidence

The independent file `tests/test_probe_v6_review.py` passes 36 tests. Four test
cases implement an evaluation-only decision-edge diagnostic; the remaining cases
check planning and experiment boundaries. The standalone command is
`python3 -m pytest -q tests/test_probe_v6_review.py`.

| Boundary | Independent evidence | Interpretation |
|---|---|---|
| Hypothetical planning does not create experience | Snapshots compare the model cover, raw history, generation, incumbent, risk ledger, proposal weights/visits, certificates, and counters before and after pure planning. | Planning is pure on the tested valid inputs. Only ticket-matched executed simulator traces are observed. |
| Failure before commitment cannot authorize a change | Interrupt immediately before a completed promotion; inject ranker exceptions, `KeyboardInterrupt`, and a final-check exception after preliminary positive comparisons. | Tested failure paths preserve evidence, learned state and incumbent; no partial certificate or debit is committed. Unexpected exceptions propagate. |
| Instrumentation is restored | An existing `sys.settrace` hook is preserved after successful planning and injected failures for all three bounded agents. | The current thread's tracing hook is restored. This is not a concurrency or operating-system isolation guarantee. |
| Work includes expensive evidence construction | A duplicated cover exhausts the global work budget despite few distinct models; a one-model duplicate profile loop is separately interrupted; ordinary profile construction is also charged. | Deduplication and profile work do not escape solely because they happen before a distinct-model yield. Work units remain audited Python line events. |
| Per-branch loss is prepaid | Independently recompute each reported continuation's exact lower bound in the corresponding observation cell. Test budgets 0, 1, 2, 3 and 5 with paid parity probes across every world. | A two-probe plan needs enough budget for both actions on each branch. Only the actually executed action is charged now; each later action is freshly planned and checked. |
| Old plans do not determine a later goal's action | After actual feedback and a public-goal change, verify the new ticket uses the new generation and matches a fresh plan. | The planner exposes an immutable diagnostic plan and executes only its first action; it does not install an unchecked continuation. |
| Frozen experiment population and resources remain fixed | A JSON round trip of the exact configuration reaches the execution boundary; altered seed offset, seed count, work cap, time cap and phase are rejected before experiment compute. | Source hashes alone were insufficient; the corrected preflight checks the declared configuration too. |

The implementation colleague separately added source-filename portability tests
for the line meter. The reviewed fix canonicalizes filenames before testing
whether frames belong to `witness_cl`, so relative paths and symlinked checkout
paths cannot silently disable the meter. These tests belong to the implementation
suite and are not included in the independent count above.

## Harness findings and disposition

Inspection of `experiments/probe_v6.py` found no hidden-world table, future goal
schedule, evaluator-only counterfactual, or independent audit outcome passed to
the bounded learners. The common finite state/alphabet/reward contract and program
library are supplied openly. Actual action/output traces are their only new
model evidence. Every arm explicitly freezes proposal-weight training, and the
evaluator checks that no neural update occurred.

The evaluator independently enumerates the finite universe and filters it by
executed traces. It compares the runtime cover against that replay after every
episode, checks protected incumbents over every replay-compatible world, and
checks actual prefix reward deficits against spent risk. The unbounded
full-history diagnostic computes from its own permitted history, not the true
world table. Evaluator preparation and audit runtime are separate from agent
construction, planning and update runtime.

Two concrete review findings were corrected before the holdout freeze:

1. The original risk audit checked the current spend and episode debit but did
   not independently accumulate every announced debit. It now requires
   `agent.spent == cumulative_debit`, detecting a refunded or reused budget.
2. The original freeze checked source hashes but permitted changed run resources
   or population. It now verifies the full declared holdout configuration. The
   JSON list/tuple representation of method names is normalized consistently.

The paired-summary helper assumes unique, matched seed/method records. The
harness produces one completed record for every planned seed and method and
raises on incomplete runs, so this assumption holds for its generated summaries.
The same sampled table can occur at different seeds; the protocol reports table
duplication and uses descriptive paired intervals over generated streams rather
than claiming disjoint-domain generalization. Multiple secondary contrasts are
not multiplicity-adjusted.

## Residual limitations

No unsafe admission was found under the tested finite contract. The theorem and
checks still depend on a realizable, stationary model class, authentic feedback,
correct reset semantics, fixed typed programs, and the supplied reward vectors.
An exact finite regret or reward bound does not cover misalignment, privacy,
physical consequences, or safety properties absent from that reward contract.
A positive reward budget explicitly permits some simulated reward loss.

Work caps count Python events inside the implementation. Native C operations,
allocator behavior and operating-system scheduling are not bounded by that count;
the elapsed deadline is cooperative. Agent construction and actual evidence
updates are measured separately and are not claimed to be limited by the planning
meter. There is no hostile-code sandbox or hard real-time guarantee.

The reference assumes one trusted caller. It does not synchronize arbitrary
concurrent mutation of its mutable space, library, incumbent, budget or ranker.
An external Python caller can replace methods or mutate internals; that is outside
the typed simulated learner's authority and this review's safety claim. Production
execution would need a stronger process and immutable-state boundary.

UNKNOWN or INCONSISTENT planning does not establish that a previously installed
incumbent remains safe after hidden drift. The current fallback still executes an
incumbent simulator program. An irreversible deployment would need an independent
validated safe action or a real halt/abstention mechanism. This experiment grants
no such deployment authority.
