# Next test: learned tool facts and reusable query fragments

Research proposal, not an implemented learner, executed benchmark, novelty claim,
or authorization for an external action. Primary sources checked 8 September
2026. This direction remains conditional on the frozen v7 result: if exhaustive
sparse fitting matches or beats reuse after costs, retain that result and stop
optimizing the monomial example as evidence for the larger problem.

## The next bottleneck

v7 replaces enumeration of possible worlds with numerical fitting, but supplies
the complete 84-feature grammar, two fixed measurements of the complete tables,
exact scalar target feedback and authentic report dispatch. Reuse changes which
features are searched first. It cannot show that an agent learns which tool call
to make, what an unfamiliar schema means, or when a stored fact applies.

The next bounded hypothesis is: **experience can produce compact schema facts and
parameterized query fragments that save more future tool and inference work than
it costs to discover, check and retrieve them, while preserving answer accuracy.**
An example is learning from actual query results that one product group stores
prices in cents while another uses dollars, then applying that fact to a new
aggregation. A second is learning which join key avoids duplicate rows, then
reusing the join in a different question. The task must contain evidence that
makes such a fact identifiable; no procedure can recover a semantic distinction
that leaves every permitted observation identical.

This is a test of useful learned structure with bounded resources. It does not
require expanding the learner's action permissions or claiming unconstrained
self-improvement.

## Relevant existing methods

| Primary source | What it already supplies | Consequence for this proposal |
|---|---|---|
| [DreamCoder, Ellis et al., PLDI 2021](https://arxiv.org/abs/2006.08381) | Program synthesis with a learned abstraction library and a learned search guide, using wake/sleep cycles. | Learning compositional symbolic libraries is established. Our proposal must distinguish online task evidence, costs and downstream transfer; calling a library new is insufficient. |
| [Stitch, Bowers et al., POPL 2023](https://arxiv.org/abs/2211.16605) | Corpus-guided top-down synthesis of abstractions from programs, evaluated for library compression and search resources. Its [official implementation](https://github.com/mlb2251/stitch) is an available antecedent to inspect. | Use an established compression baseline. Compressing past traces is a candidate-generation objective; it does not by itself prove future usefulness or query correctness. |
| [ExpeL, Zhao et al., AAAI 2024](https://ojs.aaai.org/index.php/AAAI/article/view/29936) | Natural-language insights extracted from experience and retrieved alongside prior experiences without updating model weights. | A concise fact memory needs comparison with ordinary insight extraction and retrieval, not only with a stateless model. |
| [CL-Bench, Asawa et al., 2026](https://arxiv.org/html/2606.05661v1) | Stateful versus stateless evaluation, inference cost reporting, and a native database exploration task with schema conventions and drift. The paper reports strong simple ICL controls. | A same-backbone full-history ICL comparison is required. Synthetic regression gains do not establish native benchmark gains. |
| [AgentCL, Shu et al., 2026](https://arxiv.org/html/2606.02461v1) | Controlled compositional versus naive streams, a frozen second pass, and held-out tasks to separate transfer, stability and generalization. Memory construction excludes ground-truth guidance. | Include non-reuse and held-out controls. A gold-reward admission signal would change its permitted information, so the present statistical gate cannot simply be inserted into the native protocol. |

These are bounded source checks, not an exhaustive search proving novelty or a
claim about today's best method.

## Concrete candidate mechanism

Store each discovered entry as immutable data with five fields: its proposed
fact or typed query fragment; the visible observations supporting it; an explicit
applicability predicate; a counterexample or conflicting observation when one is
found; and the measured cost of testing it. Do not store a fabricated certainty
label. A fact inferred from one group is not automatically valid for every group.

The proposal generator may use only completed, legally observable episodes.
Compress repeated successful query structure into fragments with typed holes for
tables, columns, filters and aggregation parameters. Preserve source observations
so retrieval can distinguish a witnessed equality from an extrapolated rule.
The application predicate uses visible schema and data checks, not evaluator
family IDs. Initially permit at most 16 entries, 32 syntax nodes per fragment,
two retrieved entries per question and one additional applicability SELECT per
retrieved entry. These are proposed engineering limits to freeze before testing;
they are not theoretically optimal.

A fixed interpreter executes the typed fragment through a restricted read-only
SQL interface. It rejects unsupported syntax before execution and applies the
same statement, row and execution limits to every arm. Text memories remain
untrusted data rather than instructions. A mismatch or failed applicability
check falls back to the ordinary solver; its additional query and model calls
are charged. A check based on a few examples is an empirical guard, not a proof
of SQL semantics. No fragment can alter permissions, evaluator feedback, the
interpreter or its own admission procedure.

Start with a synthetic development environment whose hidden conventions include
join multiplicity, nullable fields, units and schema renamings, and whose surface
names are independently randomized. Construct held-out questions by composing
previously observed relations; also include new relations that old fragments
cannot solve. Keep generator definitions and expected answers evaluator-only.
Explicitly document every primitive and finite cap; generating new compositions
within this language still does not establish open-ended representation growth.

## One falsifiable experiment before scaling

Use the same frozen backbone, decoding settings, initial instructions and tool
interface for five stateful controls: complete legal-history ICL, bounded
verbatim-episode retrieval, concise natural-language insights, learned typed
fragments, and the same fragments with their applicability checks disabled.
Include a stateless run to quantify the value of experience. All arms receive
the same legal observations and feedback rules. Complete history must actually
fit the chosen context ceiling; otherwise name the truncation/compression rule
and include its cost instead of claiming full history.

First run a small development-only cost pilot. Predeclare a cap of four streams
of 24 ordinary questions per arm, six arms total, eight tool SELECT attempts per
question and 30 minutes total wall time. Count proposals, extraction, reflection,
retrieval, checks and failed attempts inside each arm's total model-token and
wall-time ceilings; reserve the same final evaluation allowance for every arm.
If those ceilings cannot support the comparison, report the pilot as a cost
failure rather than silently increasing them. No model run is performed by this
document. Exact backend/token limits must be set from measured local capability
before execution, and paid or remote resources require their own existing
project authorization.

Freeze the mechanism after development. Evaluate independent held-out streams
with three prespecified conditions: reusable structure, a shuffled/non-reuse
control, and misleading near matches whose applicability changes. Split by
hidden convention and query-template composition, not just fresh table rows.
Keep a separate old-task panel and a frozen final-memory panel. A deliberate
schema-drift condition is a robustness challenge, outside the stationary gate
claim. Its first unexpected failure cannot be retroactively protected.

Choose one primary comparison in advance: typed fragments versus full-history
ICL on future ordinary reward at a fixed total resource ceiling. Require a mean
gain of at least .05 and a positive paired 95 percent lower interval across
independent streams. Also require old-task accuracy loss below a prespecified
.02 margin with an appropriate paired uncertainty bound. These are proposed
research targets, not established tolerable losses. Determine the confirmatory
stream count from development variance and an explicit power calculation; four
development streams do not constitute a decisive benchmark result. Report all
other control comparisons without silently selecting a favorable primary arm.

A resource claim additionally needs measured cost to include the entire learning
system. Report reward versus total model tokens, SELECTs and wall time separately;
equal tool counts do not imply equal computation. Count the memory payload,
retained raw traces, proposal cache and journals. A compact prompt with an
unbounded backing archive is not a constant-memory learner.

The mechanism fails this test if gains disappear under total-cost matching, if
verbatim history or sparse exact recovery is as effective at lower cost, if
reuse appears only with leaked family labels, or if entry removal/shuffling does
not change the alleged transfer benefit. Compression alone is not success.

## Statistical admission and native benchmark compatibility

Keep the representation question separate from the cost of statistical
admission. The [fixed half-bet power counterexample](GATE.md) proves that a policy
with positive mean gain can still have low eventual admission probability.
A future gate should compare a prespecified convex mixture containing smaller
bets, or predictable variance-sensitive bets, while preserving the same fresh
sampling and lifetime error accounting. This is established bounded-mean betting
machinery, not a new learning algorithm. See [Waudby-Smith and Ramdas](https://doi.org/10.1093/jrsssb/qkad009).

Evaluate such gates in a separate resettable local track where fresh audit tasks
and authoritative labels are actually available and every execution is charged.
Report the fraction of candidates that remain inconclusive, selection-to-use
latency and the opportunity cost of the queries. Do not transfer its confidence
statement to a native benchmark that cannot provide these audit samples.

For external validity, the first native target is CL-Bench's Database Exploration
on a pinned release. The [paper's Appendix A.4](https://arxiv.org/html/2606.05661v1#A4)
describes 40 questions, schema/data conventions, a migration after question 20,
and reward incorporating query use and correctness. Preserve the actual task,
feedback visibility, schedule, query limits and score; freeze the memory adapter
before seeing evaluation answers. Report it explicitly as a native domain
subset, not an aggregate benchmark win. Its drift makes a stationary promotion
theorem insufficient. Replay of a fixed finite task panel is not unlimited
fresh audit data.

AgentCL can later test composition and irrelevant-memory interference, but its
[no-ground-truth memory construction rule](https://arxiv.org/html/2606.02461v1#S3.SS1)
must be respected. If evaluator labels influence which memory is accepted, that
is an augmented-feedback experiment and must be named separately. A native run
can use only permitted observations and operational checks, with no claim that
the current supervised admission guarantee accompanies it.

None of these future experiments is evidence that deployment-time continual
learning, unlimited retention or alignment has been solved. A successful result
would establish a narrower and useful fact: a specified representation learned
from permitted experience improves later tool work against strong history
controls after its full cost is paid.
