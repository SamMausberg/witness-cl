# v9 shared-solver diagnosis

The first repair should target acquisition and interpretation of legal evidence.
The v8 warm failure is not explained by running out of output tokens: **all 82
warm solve calls ended with `finish_reason: stop`, and the longest completion
was 57 tokens under the 384-token allowance**. This document proposes bounded
development diagnostics, not verified repairs. It makes no model call, uses no
held-out fixture and changes none of the seven frozen v8 inputs.

## Observed failures and untested explanations

| Saved evidence | Supported diagnosis | Not established |
|---|---|---|
| Every arm scores 0/8 warm; no catalog query occurs anywhere in the full run. | The solver never acquires the available documentation. | Whether capacity, prompting, decoding or output constraints caused the omission. |
| Full-history/stateless warm line 1 sums `c_ppmenc`, returns 284375, while gross value is 7817.75 dollars. | The query executes but ignores documented quantity/unit semantics. | That SQL execution, hardware, or the token budget is defective. |
| Checked/unchecked warm lines 1–8 each answer zero with no SELECT. | Empty-memory agents terminate without observing the current data. | That an empty prefix necessarily causes this behavior. |
| Insight line 1 calls feedback zero a correct result; later reflections repeat this interpretation. | Failure feedback is misunderstood and copied into memory. | That all evolving-memory algorithms are ineffective. |
| Verbatim warm line 5 repeats an unused-binding error seven times; each completion ends naturally at 36 tokens. | Error feedback does not trigger a useful correction. | That a larger output cap alone would repair it. |

Evidence files are `artifacts/v8/development/90000-reuse-<arm>.jsonl`.
All initial learned states are empty, but their messages differ: no wrapper for
full history/stateless (576 prompt tokens), empty verbatim wrapper (591), empty
insight wrapper (592), or empty executable wrapper (591). Their first actions
differ. This is a nuisance difference worth testing, not an isolated causal
result from the existing run.

## Proposed shared instruction text

The following is a candidate common solver instruction, followed by the same
permitted action definitions for every method:

> Answer the current question from observed evidence. Randomized identifiers and
> column positions do not establish business meaning. If your visible evidence
> does not explain the relevant columns and conventions, your next action must
> read the queryable catalog. You can use `SELECT * FROM catalog` with empty
> parameters; this costs one SELECT. Previously observed documentation can be
> reused when it still applies. Do not re-read it solely because an episode ended.
>
> Use the documentation to identify the requested quantity, its units, missing
> values, row grain and join relationships. Write a direct SELECT or WITH query
> using those meanings. Return the observed scalar, or a calculation supported
> by the returned rows. Unknown meaning or absent observations do not imply zero.
> Zero is justified by observed data or a supported invariant, not uncertainty.
>
> When a query fails, read the error and change the invalid part. Do not repeat
> the same failed SQL/parameters unchanged. Every attempt remains charged.
> Parameter keys must exactly match the named holes actually used in the SQL.
>
> A completed exchange can still have an incorrect answer. `correct: false`
> means the submitted answer was wrong; `correct: true` means it was correct on
> this episode only. Neither outcome proves the general correctness of a query.

The host should render already available binary feedback unambiguously, for
example `{"correct":false,"meaning":"The submitted answer was incorrect."}`.
This adds no gold number or evaluator formula. All arms must receive the same
feedback semantics. Reflections should preserve the observed outcome and avoid
turning an error into a claimed success.

The catalog query is an acquisition example, not a supplied business solution.
It must execute and count if issued. Do not inject its rows into a model prompt
for free. Do not force a fresh lookup when full history already contains valid
documentation; such a restriction would weaken that control. Direct joins,
CTEs and independent SQL composition remain available to all arms.

## Ranked bounded development ablations

1. **Shared evidence-acquisition protocol.** Compare the frozen v8 instruction
   with the candidate common instruction on the same declared new development
   warm stream, initially using a stateless solver so evolving memory does not
   conceal the acquisition failure. Keep weights, greedy non-thinking decoding,
   JSON action schema and 384-token solve cap fixed. Bound this comparison to
   eight warm questions per variant, the same eight SELECTs/ten actions per
   question, and a declared wall/token cap. Score catalog acquisition, correct
   nonzero answers, binding-error recovery and raw costs. This is a protocol
   package feasibility comparison; it does not isolate each sentence's effect.

2. **Interface/feedback representation diagnostics.** On fixed development
   inputs, compare an omitted empty-memory message with the exact empty wrapper
   while holding everything else constant. Separately compare numeric-zero
   feedback with the explicit false label on the same completed own episodes.
   Cap each diagnostic at eight paired inputs: at most 32 generation calls
   across both comparisons, with no retries. The first checks action selection;
   the second checks whether reflections accurately say the answer was wrong.
   A first-action test alone is not a task-accuracy result. Any subsequently
   executed queries remain charged. Do not use these diagnostics to supply
   another arm's hidden experience in the main study.

3. **Bounded deliberation after documentation is available.** Only if acquisition
   succeeds but semantic SQL remains wrong, compare direct JSON action output
   with a short visible evidence-check step followed by the same JSON action.
   One concrete ceiling is 256 tokens for the check plus 768 for the action,
   with both calls and all tokens/time charged. Use eight matched development
   questions and preserve the SQL authority boundary. This tests added planning
   under a changed interface/budget; it is not a clean test of output length or
   a claim that the larger configuration costs the same. Do not simultaneously
   change backbone, sampling and memory policy.

These are ceilings for separately declared experiments, not an instruction to
run every branch. The coordinator should freeze their combined resource budget
and stop an unpromising branch rather than repeat until it passes.

## Constraints and the qualification decision

The v8 `oneOf` schema permits QUERY, ANSWER, USE and COMPOSE. Valid QUERY actions
were produced, so the schema did not simply disable SQL. It can still influence
branch selection, and a finite output cap can truncate a long JSON string.
Neither possibility explains the observed short, naturally terminated warm
answers by itself. Removing constraints altogether is not an evidence-backed
first repair; strict parsing and the fixed SQL executor should remain.

Greedy decoding and disabled thinking are experimental settings, not demonstrated
optimal settings for this model. Switching to sampling or enabling native
thinking changes variance, token accounting and possibly the chat-template
interaction with constrained output. Such a comparison needs its own frozen
configuration and repeated-seed policy; one favorable sample is not qualification.

For v9, require **at least 7/8 warm answers correct separately for full-history
and evolving-insight controls**, plus at least 7/8 on the proposed learner's
fresh old-before panel before claiming useful retention. Audit the individual
nonzero tasks and successful documentation/feedback use; an aggregate composed
of cached or default-zero answers is insufficient. These small checks are
engineering gates, not statistical proof of population competence. Do not pool
arms to pass the gate or weaken it after seeing results.

Only then attempt actual abstraction admission and fresh rebinding/composition.
A competent direct solver may already use one SELECT, whereas checked fragment
reuse needs a guard and execution. Solver qualification therefore cannot by
itself establish that the interaction-saving hypothesis is attainable. Measure
that floor before scaling, while preserving the stronger baseline's full SQL
and legal-history capabilities.
