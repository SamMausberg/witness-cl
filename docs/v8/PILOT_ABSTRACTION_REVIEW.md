# Independent review of the frozen v8 abstraction pilot

The pilot produced **no admitted executable abstraction and no USE or COMPOSE
action**. All six arms failed the warm competence check with 0/8 correct. The
result is a failure of the frozen model/interface configuration to meet the
study's prerequisites. It does not establish the central discovery, transfer,
interaction-efficiency or retention claim, and it is not a competent comparison
from which to conclude that executable abstraction learning is impossible.

## Evidence and completion

This review reads the completed `artifacts/v8/development/` records for development
seed 90000 in the reusable condition. All 288 assigned arm-episodes are present,
48 per arm. The manifest records 690.126634 seconds against the 1,800-second cap,
`required_records_complete: true`, and unchanged executed source. The reviewer
independently matched all six JSONL file hashes to the manifest and all seven
frozen source hashes to both the pre-pilot receipt and current files. No source,
model configuration, result, or Git state was changed during this review. The
reviewer made no model call and constructed no held-out fixture.

Every episode ended with a finite ANSWER and status `completed`. That status
means the operational exchange completed; it does not mean the answer was
correct. The independent saved-data replay is a separate receipt produced by
the replay reviewer; this document interprets the actual program-learning and
competence evidence, rather than authenticating original model execution.

## Actual competence

| Arm | Warm | New middle compositions | Later relation/operation tasks | Fresh old: before to after | Final new compositions |
|---|---:|---:|---:|---:|---:|
| `full_history` | 0/8 | 0/8 | 0/8 | 0/8 to 0/8 | 1/8 |
| `verbatim` | 0/8 | 1/8 | 0/8 | 0/8 to 0/8 | 2/8 |
| `insights` | 0/8 | 0/8 | 0/8 | 0/8 to 0/8 | 2/8 |
| `fragments` | 0/8 | 1/8 | 0/8 | 0/8 to 0/8 | 2/8 |
| `fragments_unchecked` | 0/8 | 1/8 | 0/8 | 0/8 to 0/8 | 2/8 |
| `stateless` | 0/8 | 0/8 | 0/8 | 0/8 to 0/8 | 2/8 |

Each question block contains eight items from one correlated stream. The
mandatory full-history and evolving-insight warm threshold was 6/8; both scored
0/8. The proposed learner's fresh-old-before competence threshold also failed.
All arms scored 0/8 both before and after later learning on the old panel.
An unchanged zero score does not demonstrate preservation of useful competence.

There were **14 correct scalar answers among 288 episodes; all 14 answers were
zero**. Six correct answers used no SELECT at all. Other correct zeros followed
queries yielding NULL, empty rows or zero counts; one stateless final case
followed seven malformed actions.
The numeric grades remain part of the frozen outcome record. They cannot be
promoted into evidence of executable abstraction transfer.

No arm queried the documentation catalog anywhere in the full run. The first
full-history and stateless query was

```sql
SELECT SUM(c_ppmenc) FROM r_uufsfa WHERE c_ppmenc IS NOT NULL
```

It returned 284375, which was submitted as the answer. The gross-value target
was 7817.75 dollars and requires the documented quantity and unit conventions.
The query ran successfully but computed the wrong quantity. This is a concrete
solver-interpretation failure, rather than an SQL executor failure.

The first insight update also misread the delivered evidence: its conversation
contains `correctness_feedback: 0.0`, yet the saved reflection says the zero
answer was considered correct. The text is an observed erroneous memory update,
not a statement that the feedback actually marked that answer correct. These
examples are in line 1 of the corresponding full-history, stateless and insights
JSONL files.

## Abstraction admissions and actual transfer

Both executable-memory arms have the same relevant ledger:

| Evidence item | Checked fragments | Unchecked fragments |
|---|---:|---:|
| Model proposal responses | 1 | 1 |
| Rejected proposals | 1 | 1 |
| Executed reconstruction checks | 0 | 0 |
| Admitted relation entries | 0 | 0 |
| Applicability checks | 0 | 0 |
| USE actions | 0 | 0 |
| COMPOSE actions | 0 | 0 |
| Changed-binding learned uses | 0 | 0 |
| Correct new compositions using a learned relation | 0 | 0 |

The one proposal per arm follows ordinary index 11 (the twelfth ordinary
question), asking for the number of current Gold-tier customers with a confirmed
order of positive net value. Each model submitted zero with no observed query;
that particular target was zero. Each then proposed source index 0 and guard
index 0 despite the eligible query list being empty. The host rejected the
proposal before any learning SELECT or library mutation. The saved reason is
`charged queries must fit the shared episode SELECT cap`; here the relevant
failure is the absence of any charged source witness, not exhaustion of the
eight-query allowance. Both full records are at JSONL line 20.

The proposal also visibly supplied an unused `filter` binding and an outer
query over the physical table rather than `reused`. Those are additional
structural deficiencies visible in the text, not reasons reached by the run's
first rejection. This reviewer did not execute or repair that candidate.

The fragment arms' two correct final answers do not repair this missing
mechanism. One followed an ordinary query returning NULL; the other was a
zero answer without any query. The learned libraries were empty throughout,
so neither can be an executable-memory use, a rebinding, or composition of an
acquired relation. There is no accepted constant or ignored-CTE proposal to
exclude post hoc: every claimed transfer count is already zero. The broader
constant/unused-CTE concern remains a tested limitation of the finite admission
criterion, not an observed successful discovery in this pilot.

## Empty-prefix differences: descriptive evidence only

Before the first task, every arm had empty learned state. Their full model
inputs nevertheless differed because several methods display a labeled empty
memory message. The common system instructions, actual task and model settings
were shared.

| Initial input variant | First prompt tokens | First action |
|---|---:|---|
| Full history / stateless: no memory message | 576 | Query a guessed raw amount sum |
| Verbatim: `Prior verbatim episodes ... []` | 591 | Query a guessed raw amount sum |
| Insights: `Evolving insight memory ... []` | 592 | ANSWER 0 |
| Both fragment arms: `Learned executable memories ... []` | 591 | ANSWER 0 |

These different actions coincide with the different complete inputs. No
empty-prefix ablation or repeated controlled comparison was run. The observation
does not identify the prefix as the cause, quantify its effect, or isolate
backbone capacity, quantization, greedy decoding, schema constraints or prompt
wording. Any future comparison should examine this nuisance difference before
attributing an early divergence to learned memory.

## Costs do not establish the requested efficiency

| Arm | All SELECT attempts | Model generation calls | Total model tokens |
|---|---:|---:|---:|
| `full_history` | 52 | 100 | 624,827 |
| `verbatim` | 85 | 133 | 163,293 |
| `insights` | 11 | 83 | 66,038 |
| `fragments` | 30 | 79 | 62,895 |
| `fragments_unchecked` | 30 | 79 | 62,895 |
| `stateless` | 99 | 147 | 158,503 |

The totals are 307 SELECT attempts, 621 generation calls and 1,138,451 model
tokens across all 288 episodes. These include panels and learning reflections.
Neither fragment arm incurred a reconstruction, guard or fragment execution
because no candidate reached that stage. Their lower raw SELECT counts are
therefore not measurements of reduced exploration through reusable programs.
Accuracy and baseline competence remain necessary conditions. Comparing only
correct episodes or quoting the raw query difference as an abstraction saving
would mischaracterize the run.

Even after repairing solver competence, a capable full-history SQL agent can
sometimes answer a fresh question in one SELECT. Checked reuse requires its
guard and its execution, in addition to amortized synthesis costs. A shared
solver repair alone cannot remove this interaction floor. A future efficiency
claim needs a real reduction in other necessary exploration, not a weaker
baseline or an after-the-fact change from SELECT cost to prompt tokens.

## Concrete future shared-solver protocol, not an implemented repair

The next useful development step is a separately frozen **shared solver
competence test before evaluating memory advantages**. It should make three
changes explicit and apply them equally to all arms:

1. Make documentation acquisition an explicit paid step when the available
   evidence does not establish the meaning of the current schema. Prior legally
   observed documentation may support reuse; do not supply oracle SQL or task
   labels and do not silently add free catalog results.
2. Define binary feedback unambiguously, for example a Boolean `correct` plus a
   short statement that a false value means the submitted answer was incorrect.
   Require the reflection to retain that meaning rather than treating a
   completed exchange as a successful task.
3. Freeze a small public-development competence check, including nonzero targets,
   before any transfer interpretation. Preserve all failed attempts and require
   the declared history, insight and old-task competence thresholds before
   continuing to a claim-bearing comparison. Record an empty-prefix ablation
   separately if it is used to select revised wrapper wording.

These are untested changes, not a diagnosis that a prompt edit will make this
4B setup adequate. Model/decoding alternatives would also require their own
measured, versioned test. Any new development study must preserve this negative
run and fit an explicitly declared resource plan; it cannot silently restart
the frozen pilot clock or use held-out outcomes for tuning. Demonstrated fresh
rebinding/composition, causal dependence on the learned relation, strong-control
accuracy and statistically supported retention would still remain separate
obligations after competence is established.
