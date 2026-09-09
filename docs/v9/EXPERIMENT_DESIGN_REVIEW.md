# v0.9 design review: qualify acquisition before testing efficient reuse

Recommendation: make v0.9 a **competence-gated acquisition and computation-cost
feasibility study on the existing SQL task**, with unrestricted direct SQL for
the controls. Repair and qualify the shared solver, demonstrate a real
experience-to-relation-to-transfer chain, then compare total model-token cost
and measured latency at matched task competence. Continue recording the original
25% SELECT-saving criterion, and report its failure if competent direct solving
is already at the query floor.

This is an explicitly narrower proposed resource objective than the user's
original requirement of substantially fewer environment interactions. A token
or latency result must never be presented as satisfying that original
requirement. Declare the v0.9 objective before its task runs rather than changing
metrics after seeing outcomes. If the original SELECT criterion remains the
primary objective instead, the same competence/floor check should determine
whether to stop this mechanism in the current task family.

This file proposes an experiment. It changes no frozen v8 input, creates no
model or heldout run, and adds no formal theory. It uses the completed
[v8 result](../v8/RESULTS.md), its [next decision](../v8/NEXT_STEP.md), and the
current task/interface implementation.

## Why repeating the v8 comparison is not the next experiment

All six v8 arms scored 0/8 on warm questions. Both fragment methods admitted zero
relations and executed no USE or COMPOSE. All arms scored 0/8 on both old-task
panels. No arm inspected the documentation catalog during ordinary learning, and
an insight reflection interpreted failure feedback as success. Those results
show a failure of the frozen solver/configuration to acquire this task; they do
not isolate or test successful executable abstraction learning.

Full history consumed 52 SELECTs across 48 episodes, but only one answer was
correct, and that answer was zero. Its apparent proximity to one query per
episode is therefore not evidence of competent one-query solving. Conversely,
the checked method's 30 queries are not evidence of useful savings. No
interaction benefit should be extrapolated from these failed agents' counts.

## The SELECT floor and guard cost

After learning the schema conventions, a solver can write one direct SELECT
containing the required joins, grouped event totals and outer aggregate. Full
history and a good evolving context have exactly this capability. There is no
external result that must be observed between those subexpressions: SQLite can
compute the complete target in the same request.

The current checked USE/COMPOSE path consumes a guard SELECT and an execution
SELECT. One such use therefore costs at least two attempts before any failed
checks, fallback, or amortized synthesis/reconstruction. A competent direct
solver averaging one SELECT cannot be beaten by this path. A direct solver
using catalog discovery plus an answer query on every target would cost two;
that would still only tie the checked path before its additional learning costs.

For a simple best-case calculation, let a learned relation serve `m` later
questions, incur `L` additional acquisition/check SELECTs, and use one guard plus
one execution on each later question. Its average is at least `2 + L/m`.
A strict 25% saving requires the matched control to average more than
`(2 + L/m)/.75`. With no additional acquisition overhead, the threshold is
`8/3`, approximately 2.667 SELECTs. A control averaging three queries may leave
room for savings, but even modest acquisition overhead can remove that margin.
This arithmetic is conditional on that routing pattern; it is not a prediction
of a competent control's behavior.

The library arm can choose ordinary QUERY instead. Its average is consequently
not always bounded below by two. If it saves calls by directly copying or
re-expressing stored information into QUERY, inspect that evidence separately;
the result does not establish savings caused by checked execution.

Fusing a guard into an answer query, or caching it under a genuine public
stability contract, could remove an extra request. It would not create an
advantage over a one-query direct solver. Such a runtime change needs its own
implementation check and frozen protocol; neither a cached numerical output on
fresh data nor an assumed stationary convention is a valid guard. The control
must be allowed to exploit the same stability contract and ordinary SQL
expressiveness. Do not redesign the tool by banning joins, weakening history,
mandating repeated catalog reads, or restricting control query construction to
manufacture an interaction advantage.

## One concrete progression

Use a new declared development seed, disjoint from every earlier development
seed. Keep the current database semantics and 24-question schedule, including
the fixed fresh-old panel and final compositional panel. Preserve every v8
artifact. The v0.9 protocol should name its new solver, prompt, feedback and
memory implementations; it is not a reanalysis of v8.

Use three mandatory methods for the initial feasibility stream:

1. Complete legal-history context with direct SQL.
2. An evolving evidence-and-code context with direct SQL.
3. The proposed learned executable relations, with charged checks.

Run the common first eight ordinary questions, then the eight frozen fresh-old
questions. These 48 arm-episodes are the acquisition/competence gate and are
already part of the normal three-arm schedule; do not charge them again as an
unreported preliminary study. Continue the same memories through questions
9–24 and the old-after/final panels only if the gate passes. A complete stream
then has 144 arm-episodes. Missing later rows after a failed gate are an explicit
feasibility stop, not a complete comparison.

For this development feasibility version, retain at least the v8 minimums:
6/8 warm for both mandatory controls, 6/8 fresh-old-before for the proposed
learner, and positive evidence of executable acquisition. Also inspect the
proposed learner's warm score and each method's semantic errors; unchanged low
competence is not successful retention. Report the constant refunded-order
count separately rather than treating its correctness as evidence of monetary
or join understanding.

Before the first task call, freeze the chosen backend, decoding/reasoning
settings, context policy and all arm budgets. Use a total development wall
ceiling of at most 30 minutes for this feasibility pass, with model-token/call
ceilings set from measured local capability and shared across arms. Solver
calibration runs have their own declared disjoint seeds and consume the declared
development allowance; they are not invisible setup. If a qualified solver and
complete comparison cannot fit, report a cost/competence feasibility failure
instead of silently enlarging the ceilings.

This is one development progression, not a powered confirmatory study. One
successful stream is insufficient for population superiority or a two-point
retention margin. Do not scale to more streams merely because the first run is
incomplete or unfavorable.

## Shared solver qualification

The repairs should concern the shared ability to use permitted evidence, not a
privileged library route:

- Make success and failure feedback unambiguous, for example an explicit
  Boolean correctness field understood identically by solving and updating.
  Verify this with visible positive/negative feedback examples that reveal no
  task answers or database-specific implementation.
- Explain that unknown column meanings require permitted catalog/data evidence
  or applicable prior evidence. All methods may choose a catalog query; none
  receives free facts or an extra uncharged read. Do not force that query when
  a competent history-based solver already knows the conventions.
- Permit enough output and reasoning budget for a complete direct compositional
  query. The v8 384-token solve limit should not be assumed adequate for complex
  SQL. Choose the new common cap before running tasks, based on syntax/transport
  feasibility, rather than giving shorter library calls a favorable output cap.
- Give methods with empty experience the same neutral empty-state content
  wherever no treatment difference is yet necessary. The v8 first actions
  differed under different empty-memory prefixes; that confound deserves a
  controlled repair rather than an assumption that the model alone caused it.
- Count all reasoning, generation, tokenization, retrieval, reflection,
  reconstruction, failed attempts and fallback. No query result or expected
  answer may enter a prompt through evaluator metadata.

Passing six of eight is only a minimum screen. Inspect legal traces for actual
use of documented units/quantities, NULL handling, current-profile selection and
refund multiplicity on nonconstant questions. A correct scalar without that
trace can be a coincidence. A single convention combination does not qualify
the solver for all combination/drift conditions; state that scope explicitly.

## A stronger evolving-context control

Use an editable, evidence-linked playbook, not only short prose advice. It may
retain SQL snippets, parameter examples, schema facts, contradictions and links
to its own earlier query results. It may merge, delete and revise entries after
success or failure, retrieve relevant evidence, and generate any direct SQL
query at solving time. It receives the same update-model and retrieval budget
opportunities as the library method. Its full retained state and archive, not
just the selected prompt, count toward storage.

Match the active byte/token allowance to the proposed library. Do not constrain
this control to 16 tiny prose strings while giving executable entries much more
room for code and evidence. Keep complete-history input genuinely complete
within its frozen context ceiling; otherwise report a feasibility limit, not a
full-history result under undisclosed truncation.

Use one declared, operationally reasonable prompt-cache policy for every arm.
Report logical prompt tokens and observed latency separately: repeated input
length does not directly measure the computation performed if the backend
reuses cached prefixes. A token comparison with full history alone is especially
weak; the evolving evidence-and-code context is a mandatory comparison because
it can achieve compression and copy useful code without a registered executable
library.

This is a specified same-backbone control, not a claim to reproduce or surpass
any published state-of-the-art evolving-context algorithm. Keep its actual
prompt/update implementation available for inspection and tune the common
solver only on declared development data.

## What would count as acquisition and new reuse

Require an auditable temporal chain, not just a stored entry or COMPOSE counter:

1. The learner encounters relevant evidence and answers a nonconstant ordinary
   question correctly. The source query, returned rows and feedback precede
   the candidate proposal.
2. The model proposes a data-dependent relation with useful arguments and a
   charged reconstruction of an own witnessed answer. The program was not
   supplied as a predefined domain abstraction or copied from hidden target SQL.
3. Later fresh ordinary questions correctly use that relation with genuinely
   changed bindings and a new outer computation. The arguments must represent
   problem parameters, not simply carry a newly observed answer through an
   identity function. Record the original/proposed programs, binding values,
   expanded SQL, selected evidence and actual results.
4. The later answer demonstrably depends on the relation. An unused CTE, a
   constant program or an unrelated direct query does not qualify.

For example, a model-discovered per-order monetary relation scoped by customer
region could support a North aggregate and later a South refund/gross ratio.
That would combine changed bindings with a new computation over prior order,
profile and refund information. This is an evaluator-side illustration only;
do not install that exact relation or its implementation in the learner's
initial prompt. The model must actually discover it in its own traces.

At least one successful changed-binding reuse and one genuinely new outer
composition are necessary feasibility evidence. Prefer multiple nonconstant
later targets with different outputs, so a single scalar witness cannot carry
the claim. The eight middle questions provide opportunities, not a guarantee
that any earlier successful query acquired the right component or row grain.
Late shipment delivery and first-time shipment lag remain new-learning tasks,
reported separately from recombinations of warm components.

Use two bounded, charged development diagnostics on a frozen pre-target memory:
a matched entry-removal run, and a text-only projection containing the same
learned program/evidence but requiring ordinary QUERY execution. Give each
counterfactual the same task, backend, evidence privileges and resource ceiling;
freeze memory and suppress its feedback from learning. Inspect SQL data
dependence as well. Removing information and disabling executable reuse are
different interventions, so keep their conclusions separate.

A text-only control that solves equally well and cheaply falsifies the alleged
benefit of the executable mechanism even if the model discovered useful code.
A removal run alone can show the value of information while saying little about
execution. These diagnostics consume their own declared development budget and
are not additional free attempts on primary tasks. Do not use primary heldout
outcomes to choose which entries or diagnostic examples look favorable.

## Resource and retention endpoints

For the proposed narrower v0.9 question, predeclare total model tokens as the
main computation-cost endpoint and measured end-to-end/model latency as separate
outcomes, with answer accuracy and absolute/final old competence reported
alongside them. Include proposal and reconstruction work in the library's total.
Use the evolving context as well as complete history as mandatory controls.
Do not average only solved tasks or count failed attempts as free. Report the
original SELECT-saving endpoint separately under its original definition.

Retain the same fixed fresh-old contexts at both checkpoints and freeze memory
inside every panel. Report the eight-item result and the constant-count item's
contribution, and do not reinterpret 0/8 to 0/8 as preservation. The final panel
must have unseen composition/rows and use the final frozen memory.

A future confirmatory protocol still needs independent streams, disjoint
numeric seeds across development/heldout, convention/template splits, all
prespecified reuse/nonreuse/near-match conditions, multiplicity control and a
sample-size calculation grounded in observed development variability. The
split label alone does not make repeated numeric seeds independent in the
current generator. Neither one feasibility stream nor a few correct old-panel
answers establish the existing two-percentage-point noninferiority margins.

## Decision at the end of v0.9

A qualified solver plus genuine downstream relation use would repair the
central empirical absence in v8. If it also lowers fully charged token cost or
latency against both competent controls, that would support the explicitly
narrower computation-efficiency claim. It would still not establish fewer SQL
interactions when query counts do not improve.

If competent controls consistently reach one SELECT, retain the negative
interaction conclusion for this architecture/task rather than weakening those
controls. Pursuing the original interaction objective would then require a
separately justified task family with real sequential information dependencies,
where one observation determines what can legally or meaningfully be requested
next. Such a task must arise from a defensible domain/interface, apply equally
to all methods, and still be tested against evolving context that can cache
those dependencies. It is a later research direction, not a claimed solution
or a reason to expand this v0.9 implementation before acquisition is demonstrated.
