# v8 development composition audit

This audit establishes a concrete opportunity for compositional transfer in the
synthetic fixtures. It does not establish that the model learned an abstraction,
used one successfully, saved interactions or retained competence. No task-model
inference, heldout dataset construction or heldout evaluation was performed for
this audit. The development checks use seeds 90000–90003 and the three declared
conditions. Source and tests are local; this is not external peer review.

Audited environment source SHA-256: `8199b4714cd3460157a3acb81dcbf0581bd540129dd5c230db7a609cd2155a6d`.
The post-answer learning-check addition changes execution authority only through
an explicit evaluator capability; it does not change the question, data,
convention, reference-answer or panel fixtures audited here.

## What the recipe evidence means

The complete reference SQL is unsuitable for a novelty audit: its common CTE
renderer includes profile, refund and shipment calculations even when a target
does not use them. `evaluator_recipe(spec)` instead records the target SELECT
structure and manually expands the semantic measures actually referenced by
that target. It replaces numeric and string literals, preserves filter-column
identities, operators, grouping and nested SELECTs, and excludes unused renderer
CTEs. Physical table/column names do not enter these fingerprints.

For example, the first gross-total target is annotated with only the order
amount calculation. The first net-by-current-region target adds refund
aggregation, current-profile selection and a customer join. Changing North to
South alone leaves the fingerprint unchanged. The dependency trees are hidden
from the learner, along with the target SQL, scalar answer, condition, phase,
seed and target-template name.

These are **literal-normalized target syntax plus manually expanded measure
dependencies**, not semantic canonical forms. Equivalent programs can use
DISTINCT versus GROUP BY, reorder conditions, or eliminate joins using fixture
invariants and receive different syntax hashes. Some dependency annotations are
conservative rather than mathematically minimal: the all-refund total could be
computed directly from refund rows given the guaranteed references. Hash
inequality alone therefore does not prove semantic novelty. The finite
calculation arguments below accompany the fingerprints. A separate source
review found the mappings suitable for these finite reference tails and
confirmed this limitation; it was not a general SQL equivalence proof.

## Warm experience and the eight recombination targets

The warm questions require the following relation-level concepts:

| Warm question | Required concept practiced |
| --- | --- |
| 1, gross total | Interpret order monetary amounts, currency units, NULL handling and quantities. |
| 2, mean gross | Use the same amount interpretation inside an average. |
| 3, confirmed units | Filter order status and count quantities. |
| 4, current North customers | Select the current customer profile under the documented rule. |
| 5, current North gross | Combine order amounts with the current customer profile. |
| 6, all refunds | Interpret monetary refund events. |
| 7, refunded order count | Distinguish orders from repeated refund events. |
| 8, current Gold gross | Combine order amounts with the current profile tier. |

Each of questions 9–16 has a normalized target program absent from all preceding
warm targets, uses at least two of those practiced relation-level concepts, and
has no newly required coarse subskill according to the evaluator annotations.
All 96 middle-block cases across the 12 development streams satisfy the
known-subskill and warm-program novelty checks. The programs are also distinct
from earlier middle-block targets within a stream.

| Question | New calculation | Earlier required components |
| --- | --- | --- |
| 9 | Confirmed net value by current region | Order amounts, status, current profiles, refund events. |
| 10 | Mean net value by current tier | Order amounts, current profiles, refund events. |
| 11 | Refunded percentage of reportable gross by current region | Amount/NULL interpretation, current profiles, refund events. |
| 12 | Distinct customers with a positive-net confirmed order | Order amounts, status, customer references/current profiles, refund events. |
| 13 | Difference of regional mean net values | Order amounts, current profiles, refund events. |
| 14 | Current-tier share of confirmed gross value | Order amounts, status, current profiles. |
| 15 | Mean refund-event count on refunded orders by region | Order identity, current profiles, repeated refund events. |
| 16 | Largest per-customer total net value in the current tier | Order amounts, customer identity/current profiles, refund events. |

The new subtraction, ratio, grouped extremum, conditional count or combination
of filters is part of the target composition. This check does not pretend that
every complete new operator program was previously practiced. Nor does being
required by an earlier question prove that a learner acquired the component:
the learner may have failed, guessed, or used a different calculation.

In particular, warm scalar queries do not force the learner to discover a
reusable relation at the correct row grain. Summing all refund events and
counting refunded orders do not by themselves demonstrate that its memory
contains a correct per-order refund relation. Successful trace provenance and
actual later generalized use must supply that missing empirical evidence.

The pure recombination interpretation applies most directly to `reuse`. In
`nonreuse`, names/conventions change, so stable schema-specific applicability is
absent even though SQL concepts remain transferable. In `near_match`, question
9 follows an announced convention change; previously stored facts can be wrong.
Those conditions test interference/applicability and drift and must not be
pooled into a claim of unchanged old-convention reuse.

## The late relation block and final panel

Questions 17–24 belong to the declared new-relation block and are reported
separately from the warm-to-middle recombination comparison.

| Question | Audit classification |
| --- | --- |
| 17, delivered net by current region | Introduces shipment delivery semantics: a new required relation. Exclude from a pure recombination-of-practiced-relations claim. |
| 18, mean latest-shipment lag | First requires greatest shipment day and subtraction of order day. The coarse `shipment_events` label hides this additional new temporal operation. Exclude from that claim as well. |
| 19, customers with two delivered orders | Can recombine delivery semantics required at 17 with customer counting/profile concepts. |
| 20, undelivered net by current tier | Can recombine delivery state, net value and current profiles. |
| 21, delivered share of confirmed units | Can recombine delivery state, status and quantities. |
| 22, refunds on delivered orders by region | Can recombine delivery state, current profiles and refund events. |
| 23, refund-event counts on delivered orders | Can recombine delivery state, order identity and refund events. |
| 24, largest customer delivered net total | Can recombine delivery state with grouped net value. |

Although 19–24 present sequential opportunities for recombination, the entire
late block stays separate from the prespecified warm-only transfer block. Their
actual successful use still depends on whether the learner acquired the
preceding delivery concepts. All relations are visible from the initial schema;
an agent may also choose to explore shipments early and pay the corresponding
cost. The fixture chronology records required target semantics, not every
optional observation the agent might make.

Every final-panel target combines a middle-block calculation with the joint
restriction to delivered orders having at least two refund records. Each has a
new normalized target program relative to the complete ordinary stream, uses
only coarse relation subskills previously required there, and requires shipment
and refund information. Evaluation uses frozen final memory; this is a transfer
opportunity, not an observed success result.

Static definition checks also confirm disjoint normalized post-warm program
structures between the development and heldout generators, beyond new literal
values. These checks render template definitions with empty symbolic scaffolding
and construct no heldout rows or streams. Earlier literal-only overlaps were
removed during development before any heldout data construction. The actual
heldout empirical outcome remains unknown.

## Fresh old-task retention witness

For development seed 90000 in `reuse`, compare ordinary question 1 with old-panel
question 1:

| Property | Ordinary fixture | Frozen fresh-old fixture |
| --- | --- | --- |
| Public question | Identical | Identical |
| Public CREATE schema | Identical | Identical |
| Convention combination | Identical | Identical |
| Data seed, evaluator only | `17576258401725558450` | `8785590465067322064` |
| Correct gross total, evaluator only | `7817.75` | `5773.0` |

The tables differ. Repeating the ordinary scalar answer therefore fails on this
old-panel case despite identical public instructions and schema. The same fixed
fresh-old fixtures must be used at both retention checkpoints, with no memory
updates or model-visible evaluation feedback. The harness records unchanged
memory digests for non-learning panel episodes. All 40 fixture data seeds within
each of the 12 audited development streams are distinct.

This is a concrete obstruction to simple answer caching, not proof that every
panel target differs from its training answer, nor evidence that the learner
preserved competence. Preservation still requires measured before/after scores
and the prespecified uncertainty bound. The two scalar values above are audit
metadata and must never enter a learner prompt or memory.

## Interaction-cost limitation

A competent full-history solver can express a complete answer as one permitted
SELECT after it understands the stable schema. The existence of two datasets
with the same public question/schema but different targets also shows why no
zero-query strategy can always answer both correctly from those public fields
alone. This does not claim that every individual task requires a query: a model
can occasionally guess a correct scalar, including zero.

One successful checked USE or COMPOSE currently costs at least two SELECT
attempts: its fresh applicability check and its execution. The post-answer
synthesis/reconstruction check, failed attempts and fallback queries add costs;
they cannot produce negative interaction costs. A one-SELECT full-history
solver is therefore a serious lower-bound obstruction to checked-execution
savings in this domain.

Conditionally, if every evaluated question uses exactly one successful checked
fragment and no other query, the mean fragment cost is at least 2. To obtain a
strict 25% reduction, `Q_fragments - .75 Q_control < 0`, the control must average
strictly more than `2/.75 = 8/3`, about 2.667 SELECT attempts per question. Learning
and fallback costs raise the required control cost further. This is a best-case
arithmetic threshold, not a prediction that a strong control actually uses that
many queries or that the full stream has this routing pattern.

The fragment arm also retains ordinary QUERY access and may choose not to
execute a checked fragment. Consequently, 2 is not a universal lower bound on
that arm's every episode. An apparent saving obtained through direct QUERY calls
must be analyzed from the actual traces; it does not by itself demonstrate
savings from checked executable reuse. Query costs, proposal/check costs, model
calls/tokens, wall time and storage remain separate reported quantities. A
shorter prompt or a compressed library alone cannot satisfy the interaction
claim.

## What remains unproved by this audit

A candidate reconstructed from one witnessed query result is only
sample-consistent. It may encode a scalar, generalize incorrectly, or be unused
inside an outer query. A recorded COMPOSE action alone is insufficient because
SQLite can ignore an unreferenced CTE. The observed answer must depend on the
learned relation, with successful changed arguments and genuinely new outer
composition, and with provenance predating the target. Guard success is also an
empirical equality check, not a universal semantic guarantee.

The requested research result therefore still requires successful ordinary
experience; genuine generalized fragment construction; causal later use on the
new targets; controls or ablations that distinguish stored-code copying from
useful abstraction; fully charged costs; strong full-history and evolving-memory
competence; and retained old-task behavior with the stated statistical margins.
This file supplies none of those empirical outcomes. It records the fixture and
interface checks needed before assessing them.

Verification at this checkpoint: `PYTHONPATH=src python3 -m pytest -q
tests/test_sql_env_v8.py` passed 83 tests, including 480 development
Python-oracle/reference-SQL comparisons, immutable boundaries, SQL authority and
execution limits, split/program checks, fresh-old panels, and post-answer
learning-check phase/capability/budget isolation. No model result is inferred
from those tests.
