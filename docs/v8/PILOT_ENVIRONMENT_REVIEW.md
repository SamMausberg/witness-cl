# Bounded review of the v8 pilot environment

This review concerns the frozen six-arm development pilot, seed 90000 in the
`reuse` condition. It constructs that fixture once, reads the generator and
protocol, and inspects evaluator-owned target values. It invokes no model,
constructs no heldout stream, runs no additional stream sweep, and changes no
frozen source. It does not assess the live pilot's still-incomplete model scores.

Environment source SHA-256:
`8199b4714cd3460157a3acb81dcbf0581bd540129dd5c230db7a609cd2155a6d`.
The audit values below are not legal learner input or memory content.

## Fresh old-panel targets: seven change, one is structural

Every old-panel case has the same public question, physical CREATE schema and
convention combination as its matching warm case. All eight databases differ,
and all 40 ordinary/old/final data seeds within this stream are distinct. The
actual convention is cents, NULL-as-zero, historical profiles, and authoritative
current flags.

| Warm/old item | Target meaning | Warm target | Fresh-old target | Equality |
| --- | --- | ---: | ---: | --- |
| 1 | Total gross order value | 7817.75 | 5773.0 | Different |
| 2 | Mean gross order value | 269.5703125 | 251.1640625 | Different |
| 3 | Units on confirmed orders | 24 | 30 | Different |
| 4 | Current North-region customers | 2 | 3 | Different |
| 5 | Gross value for current North customers | 1116.75 | 2356.5 | Different |
| 6 | Monetary total of all refunds | 2820.5 | 2381.5 | Different |
| 7 | Number of orders with refund records | 22 | 22 | Structurally constant |
| 8 | Gross value for current Gold customers | 4383.25 | 3243.25 | Different |

Item 7 is not an accidental equality. The generator uses order IDs 1 through 32
and gives order `oid` exactly `oid % 3` refund records. Exactly ten IDs are
multiples of three, so `32 - 10 = 22` orders have a refund record in every
fixture, regardless of fresh monetary values, schema names or conventions.
Fresh row generation therefore does not make this item's answer informative
about retained database-query competence. A previously correct scalar can be
replayed successfully on this item.

A second structural limitation follows directly from the source: without
historical profiles, each customer has its single profile at revision index
zero, and region alternates across customer IDs 1 through 8. North-customer
count is then always four. That limitation does **not** explain item 4 in this
pilot: its historical profiles produce the observed change from two to three.
No other stream was generated to establish this conditional source property.

Thus the frozen fresh-old panel defeats replay of the correct warm scalar on
seven of these eight items. A hypothetical policy that merely repeats every
correct warm target would score 1/8 on this old panel. That is a useful concrete
anti-caching witness, not a universal assertion that fresh rows prevent all
cached-answer successes or that every target in the generator varies.

Report the declared eight-item retention endpoint and the constant item
separately. A seven-variable-item diagnostic can clarify competence, but silently
dropping item 7 from the frozen primary endpoint after observing results would
change the experiment. The same fixed old fixtures must be used before and
after later learning, with no memory updates or model-visible panel feedback.
Absolute old-panel competence matters as well as its change.

## Split validity and its limits

The source assigns the four convention bits to disjoint sets: development uses
even-parity combinations, heldout uses odd-parity combinations. Each split
contains both values of every individual convention. The parity restriction
means the four bits are not independently sampled within a split; it deliberately
withholds combinations of individually available concepts. This is a valid
synthetic combination split, not evidence about arbitrary unseen schemas or
business domains.

Post-warm development and heldout target definitions are also distinct after
literal normalization. The earlier static program-structure checks inspected
the definitions with empty scaffolding, not heldout data. Warm primitive
questions and the overall four-relation domain are shared across splits. The
heldout empirical difficulty and any learned-policy generalization remain
unknown.

One harness obligation is important: the table-name and data-seed derivations
do not include the split label. A caller reusing the same numeric seed across
development and heldout would therefore reuse the name seed and data seed,
even though the convention combination and post-warm template differ. Calling
`split='heldout'` alone does not enforce independent experimental fixtures.
Before any future confirmatory run, predeclare disjoint heldout seeds and
verify that no development seed is reused. This is a protocol requirement,
not a request to generate, inspect or run heldout data now.

The current pilot contains only `reuse`. It cannot supply measured robustness
under `nonreuse` or `near_match`, and it cannot establish the confirmatory split
claim. In the generator, nonreuse removes stable schema-specific names and
conventions while retaining the broader SQL/domain concepts. Near-match drift
is announced and changes conventions; it is not unannounced or stationary
retention evidence.

## Composition taxonomy: opportunity, not acquisition

All eight middle targets (questions 9–16) require only the coarse relation-level
subskills previously required in the warm block. Their target programs are new
relative to the warm programs: net values under current profiles and status,
refund/gross ratios, positive-net customer counts, differences of conditional
means, gross shares, conditional refund counts and grouped customer extrema.
Seven involve orders, profiles and refunds; the gross-share target requires
orders and profiles. This supports the claim that the **task construction**
offers recombination opportunities beyond new rows or literal substitutions.

It does not establish that an actual learner acquired or used these components.
Required earlier semantics are evaluator annotations. A warm answer may have
been wrong or guessed; a correct scalar query may reveal no reusable relation
at the required grain. For example, a total of all refund amounts does not by
itself establish that a memory contains a correct per-order refund relation.
Program fingerprints are normalized target syntax plus manual dependencies,
not a general proof of semantic inequivalence between arbitrary SQL programs.

Question 17 introduces shipment delivery. Question 18 first requires latest
shipment timing and lag, despite sharing the coarse `shipment_events` label.
These are new relation/operation learning tasks. The full late block is reported
separately from the warm-to-middle recombination claim. The final panel combines
middle calculations with shipment and multiple-refund restrictions; success
there still requires observed use of frozen learned memory.

A synthesized query matching one witnessed result establishes sample
consistency only. Changed parameter values, correct novel outer composition,
pre-target trace provenance and causal dependence on the learned relation are
separate evidence requirements. A constant-answer program or unused `reused`
CTE can otherwise imitate discovery or composition. The fixture taxonomy alone
cannot establish the user's requested online-abstraction result.

## Qualification of baselines and retained competence

The frozen [evaluation protocol](EVALUATION.md) requires, before considering a
heldout model run:

- At least 0.75 warm accuracy for **both** full-history and evolving-insight
  controls: at least six correct answers out of eight for each control.
- At least 0.75 fresh-old-before accuracy for the proposed learner: at least six
  correct answers out of eight before further learning.
- Correctly traced parameter reuse and new composition for the proposed method.

These conditions must be checked on complete relevant panels. Partial warm or
old panels do not qualify the controls or proposed learner, and missing records
must not be treated as successes. A learner remaining at low accuracy does not
establish preservation of useful competence. The fixed 22-count item contributes
one answer, so report its contribution when describing absolute competence.

This is an operational minimum for the particular same-backbone full-history
and evolving-insight implementations. Passing six of eight is not evidence of
state-of-the-art baselines, mastery of SQL, or a population accuracy guarantee.
Failing the threshold makes this a model/mechanism feasibility result rather
than evidence of superiority over strong controls. The eight-task retention
panel and a single development stream cannot establish a two-percentage-point
noninferiority margin or the required simultaneous uncertainty bounds.

For interaction efficiency, a competent full-history solver may already use one
SELECT. Checked reuse adds a fresh guard plus execution, and synthesis checks,
failures and fallback also count. The arithmetic and routing qualifications in
[the composition audit](COMPOSITION_AUDIT.md) remain applicable. Neither fixture
novelty, library compression, a smaller prompt nor an isolated successful model
answer establishes the claimed resource advantage.
