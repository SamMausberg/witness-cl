# Independent v8 evaluation review

Status: protocol, source and offline regression review before examining model
outcomes. No held-out dataset was constructed or held-out outcome inspected by
this reviewer; the fixed split definitions were inspected as source. No model
was loaded or called by this reviewer. v7 inputs and artifacts remain unchanged.

The proposed study can test a bounded version of the user's claim. It cannot
establish that claim merely by producing executable fragments or beating a
stateless model. The necessary evidence is transfer to unseen compositions,
causal use of experience, strong same-backbone memory controls, reduced total
interaction, and measured retention. The four-stream, 30-minute development cap
is suitable for engineering and cost triage; it is not automatically a powered
confirmatory study.

## Operational meaning of the claim

| Claim component | Required observable evidence | What does not suffice |
|---|---|---|
| Discovers from its own experience | Each proposed abstraction records the completed visible episodes that caused its creation. Removing those experiences changes the memory or its downstream benefit. Hidden conventions are sampled per stream and inferable through permitted observations. | A supplied correct query, evaluator formula, known latent map, or a useful rule already present in the initial prompt. |
| Reusable executable abstraction | A model-produced parameterized SQL expression or fragment is reused in more than one context, with arguments or composition changing. The execution log records expanded SQL and dependencies. | A natural-language claim that reuse occurred; a cached scalar answer; renaming a complete solved query without exposing reusable structure. |
| Genuinely new compositional task | The target requires combining at least two previously encountered relations or operations in a target relational/SQL structure absent from prior solved questions. Evaluator-only normalized structures and dependency records establish this before scoring. | New table rows, different numeric literals, or a renamed version of an already solved complete query. |
| No task-ID routing | The learner and memory selector see the question, permitted schema/results, and own history. They receive no evaluator seed, family, phase, report label, or oracle applicability tag. | Replacing a report label with an opaque hash while keeping a separate policy or rule table for each label. |
| No enumerated feature catalogue | The initial interface supplies ordinary SQL syntax and declared resource/operation restrictions, but no finite list of target features, ready-made semantic abstractions, or all candidate query meanings. | Replacing 84 monomials with another pre-enumerated library that already contains every needed abstraction. |
| Less interaction at preserved accuracy | Every actual SELECT attempt inside exploration, applicability checking and fragment execution is charged, including failures; answer quality is simultaneously tested. | Counting a multi-query macro as one interaction, reporting only successful episodes, or gaining speed by answering incorrectly or abstaining. |
| Preserves prior behavior | Compare the same learner's frozen memory after old-task learning and after subsequent learning on paired, feedback-free old-task panels. Prespecify the old scopes. | No observed failure on a handful of examples, unchanged memory bytes, or comparison only with another method's final score. |

SQL is still a grammar, and finite execution limits still impose a bounded
language. The defensible claim is absence of a pre-enumerated semantic feature
catalogue, not absence of all syntactic priors. A SQL column named `customer_id`
is an ordinary visible identifier; it is not an illicit task label. Question
content may legitimately determine retrieval. The restriction concerns externally
supplied regime labels or evaluator knowledge that solves applicability for the
learner.

Compositional splits need stronger evidence than fresh random rows. SCAN provides
a primary example of how apparently similar test sets can distinguish ordinary
recombination from systematic transfer. AgentCL similarly controls task
relationships and separates online transfer, frozen-memory stability and held-out
performance. These motivate the split requirements above; they do not validate
our proposed SQL benchmark. [Lake and Baroni, 2018](https://proceedings.mlr.press/v80/lake18a.html),
[Shu et al., 2026](https://arxiv.org/html/2606.02461v1).

## Six-arm comparison and information parity

Keep one frozen backbone, tokenizer, quantization, chat template, decoding rule,
output cap and context ceiling across full-history ICL, evolving insights,
episodic retrieval, checked executable fragments, unchecked executable fragments,
and stateless inference. These must be actual model methods. A hand-coded exact
solver is useful as a diagnostic ceiling, but cannot replace the requested
language-model baselines.

Full-history ICL receives all of its legally visible prior interaction text with
no silent truncation. It retains general SQL ability, including joins, CTEs,
aggregation and composing earlier solutions in the prompt. Evolving insights
must really update its memory from experience with the same backbone; record
its update calls and tokens. Retrieval must have a declared, reasonable indexing
and selection method, its own complete legal backing archive, and measured
retrieval/storage costs. Do not force a baseline to re-explore facts that its
history already supplies. If full history exceeds the context cap, record an
incomplete pilot; a truncation policy is a different, explicitly named baseline.

The fragment controls receive no free semantic labels, gold answers, schema
facts or extra model reasoning. Any entry creation, checking, correction,
reflection or retrieval model call belongs to its total cost. An unchecked
fragment control disables the learned applicability check while preserving the
fixed read-only SQL authority boundary. It does not grant arbitrary code or
write permission. All arms may use the same expressive SQL language.

A memory-reset diagnostic and a fragment-removal/shuffling diagnostic should
show whether earlier experience and the learned fragments cause the claimed
benefit. A gain that survives destruction of the alleged useful representation
requires a different explanation. These are mechanism diagnostics with their
own reserved cost, not extra free attempts on the primary holdout.

CL-Bench's stateful/stateless metric and reported strength of simple ICL make
these controls necessary. ExpeL already learns and retrieves natural-language
insights from experience; DreamCoder and Stitch already learn symbolic
libraries. The proposal's contribution therefore needs evidence about online
transfer and paid-for interaction savings. It cannot be the existence of
memory or library induction alone. [Asawa et al., 2026](https://arxiv.org/html/2606.05661v1),
[Zhao et al., 2024](https://ojs.aaai.org/index.php/AAAI/article/view/29936),
[Ellis et al., 2021](https://arxiv.org/abs/2006.08381),
[Bowers et al., 2023](https://arxiv.org/abs/2211.16605).

## Primary contrasts and simultaneous uncertainty

Freeze the primary control set before evaluation. At minimum it contains
full-history ICL and evolving insights; report retrieval as an additional strong
control and include it in the decision set if the claim is dominance over all
three. Stateless and unchecked-fragment comparisons do not replace these.

For independent stream `s`, let `Q_A,s` and `Q_B,s` be the mean charged query cost
on the prespecified new-composition questions for fragments and baseline B.
Use all assigned questions, with a fixed eight-query failure cost for an
incorrect, malformed, timed-out or unfinished answer. Also report raw attempted
queries separately. Correct zero-query answers are legitimate; incorrect early
answers must not create artificial savings. All checks and expanded fragment
SELECTs count inside the eight-query allowance.

A claim of **at least 25 percent fewer interactions** requires the paired
contrast

`C_B,s = Q_A,s - 0.75 * Q_B,s`

to have a simultaneous upper confidence bound below zero. This avoids unstable
ratios when a baseline uses few queries. A point estimate of 25 percent savings
and a confidence interval excluding only zero savings establish a weaker
statement; label it that way if that is the chosen test.

For the same tasks, let `A_A,s` and `A_B,s` denote answer accuracy. Require the
paired accuracy contrast `A_A,s - A_B,s` to have a simultaneous lower bound
above `-0.02`, if two percentage points is the frozen accuracy margin. The
retention contrast is the fragment learner's final old-panel accuracy minus its
own post-learning old-panel accuracy. Its lower bound must also exceed `-0.02`.
Panels use equivalent starting instances and frozen memory; no panel feedback
or memory updates are permitted. If preservation is claimed for each old scope,
include each scope as its own endpoint rather than hiding a regression in an
average over unrelated tasks. Mean noninferiority still does not imply pointwise
preservation or alignment. Report the proposed learner's absolute old-before
and old-after accuracy as well. A learner that never mastered the old scopes
can pass a no-forgetting contrast vacuously; a confirmatory claim needs a
preregistered nontrivial old-before competence requirement.

Use streams as the replication unit for generalization across independently
sampled hidden conventions. Repeated questions from one learned stream are not
independent streams. Pair conditions on the same stream/question schedules,
rotate arm order, and reserve the same evaluation allowance. Prespecify a finite
family of `M` cost, accuracy and retention contrasts. One transparent simultaneous
procedure assigns one-sided error `.05/M` to each confidence bound. The report
must identify the interval method and its assumptions. A normal or Student-t
interval is an approximation for these bounded, possibly skewed stream means;
with four streams it cannot be described as exact coverage. A valid bounded
finite-sample alternative may simply remain too wide to decide.

The whole claim needs every required endpoint and structural condition to pass.
Retain failed and incomplete streams. Do not select the easiest successful arms,
questions or contexts after the fact. A missing or too-wide bound yields an
inconclusive claim, not noninferiority. Development seeds begin at 90000;
confirmatory seeds at 91000 remain untouched until source, prompts, memory
policies, model identity, split definitions and analysis are frozen.

## Power and the 30-minute development ceiling

The prior cap is at most four development streams, 24 ordinary questions per
arm, six arms and eight SELECT attempts per question, with at most 30 minutes
for the whole pilot. This is an upper bound of 576 ordinary answers and 4,608
ordinary SELECT attempts, before separately reserved panels and diagnostics.
Those reservations, extraction and model inference must still fit the same
whole-pilot wall-time limit. A stage that cannot finish must retain a partial
record and terminate; another output directory is not permission to restart the
clock. Do not read the confirmatory seeds to recover a failed development run.

At the maximum 576 ordinary answers, the wall budget allows only 3.125 seconds
per answer before memory updates, additional model turns and final panels. If
a question averages three model turns, that is roughly one second per turn
before overhead. A single four-second average turn already exceeds the cap at
one turn per answer. Measure short and nearly full-history prompts in the
cost/competence pilot; do not extrapolate only from its first tiny prompt.

The two-percentage-point retention margin is particularly demanding. For an
illustration, with zero regressions in `n` genuinely independent paired
Bernoulli trials, the one-sided upper bound on regression probability is
`1 - a**(1/n)`. With `a=.01` (five equally allocated endpoints), at least 228
independent trials are required to put that bound below `.02`. This illustration
is not permission to treat correlated questions as independent, and it is a
conservative regression-probability guarantee rather than the exact planned
mean-difference interval. Four streams cannot establish the same statement by
reporting no observed regression.

An approximate planning calculation is

`n ≈ ((z_(1-.05/M) + z_.8) * sigma / slack)**2`,

where `sigma` is the standard deviation of paired stream contrasts and `slack`
is the true mean's distance from the tested boundary. For five endpoints and
retention difference zero versus margin `.02`, this is approximately 251 streams
when `sigma=.10`, or 63 when `sigma=.05`. These normal approximations are planning
examples, not guaranteed required counts; development variance from four streams
is itself uncertain. A true interaction reduction exactly at the 25 percent
boundary cannot reliably give a confidence bound strictly beyond that boundary;
power planning needs a positive excess effect, not just the threshold itself.

If the pilot cannot provide adequate baseline competence or affordable inference,
report that limitation and stop this protocol. If it succeeds operationally,
freeze a separate powered confirmatory design using its variance and cost data.
Do not silently enlarge the 30-minute pilot or label development comparisons as
confirmation of the central claim.

## Read-only local-model inspection

The LM Studio catalog contained two generative GGUF entries, both third-party
modified Qwen derivatives, plus a Nomic embedding model. Their main GGUF files
were approximately 12.07 GB and 21.17 GB, with separate vision adapters. The
machine reported an RTX 5070 Ti with 16,303 MiB total and about 4,167 MiB in use
at inspection. These are point-in-time catalog/hardware facts, not measurements
of v8 inference or guarantees of fit at long context.

The existing LM Studio default context setting was 8,192. Its selected GGUF
backend was `llama.cpp-win-x86_64-nvidia-cuda12-avx2` version `2.33.0`. No CLI
catalog command was invoked because LM Studio's documentation says invoking
`lms` can automatically start the application when it is not running. Catalog
JSON and file sizes were read directly; no credentials or conversation logs were
read. [LM Studio process/CLI documentation](https://lmstudio.ai/docs/app/basics/lmstudio-vs-llmster-vs-lms).

The coordinator selected the official `Qwen/Qwen3-4B-GGUF` Q8_0 file for a
bounded pilot rather than either installed modified model. The publisher's file
page independently reports SHA-256
`8c2f07f26af9747e41988551106f149b03eb9b5cb6df636027b6bf6278473300`.
The source identity and downloaded hash must be recorded before execution.
[Publisher file record](https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/main/Qwen3-4B-Q8_0.gguf).

The model card gives 32,768 native context tokens and supports non-thinking
mode. The implemented pilot fixes 384 output tokens per solve and 1,024 per
reflection, and explicitly disables thinking in the actual chat-template
request. Its decoding configuration must remain frozen. The card's non-thinking
recommendation is temperature
`.7`, top-p `.8`, top-k `20`, min-p `0`, presence penalty `1.5`; any alternative
requires its own stated development competence check. A publisher model card
is not an alignment guarantee. [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-GGUF).

This 4B backbone is a reasonable candidate for testing cost and interfaces under
fixed read-only authority. It is not evidence of a strong frontier solver. A
prerequisite development accuracy of at least `.75` on the declared baseline
checks can reject an obviously inadequate setup; it does not prove optimal
prompting or benchmark leadership. Full-history versus evolving-memory remains
a genuine same-backbone comparison only if both implementations are competent
and receive the same legal information and inference limits.

Use strict JSON-schema output validation and a fixed SQL interpreter that grants
only the permitted bounded SELECT operations. Invalid outputs consume their
budget; they do not get free repairs or trigger arbitrary tools. Freeze model
weights, prompts and runtime identity. No policy can edit its tool permissions,
reward function or evaluator. These operational restrictions support the bounded
research run; they do not prove that the model is intrinsically aligned.


## Source and offline regression review

The local boundary consists of the SQL environment, immutable typed fragment
compiler, six experience-memory policies, bounded local inference client and
pilot harness. The first source-review pass ran the original four v8 test files
together: **232 tests passed** in 3.08 seconds. The subsequent synthesis extension
was independently reviewed and received **96 additional tests**, all passing in
3.12 seconds, including execution through the actual harness with a scripted
model client. These counts describe those review passes, not a claim that the
final combined suite has already passed. They are implementation results, not
model competence, transfer, efficiency or retention results. Test fixtures use
development data or symbolic template definitions and make no inference calls.

The harness builds model messages from the public question/schema, selected own
memories and actual query observations. Evaluator metadata is appended after
the completed interaction. A canary regression check confirms that this data
does not enter the recorded prompts or retained full history. The independent
memory tests cover atomic admission from actually observed successful queries,
complete guard witnesses, strict action parsing and immutable prompt records.
The synthesis extension additionally checks that new proposed relations
reconstruct a confirmed own numeric answer through a real charged SELECT,
binding admission to the immutable pre-proposal witness prefix.
These are checks on the supported text/action interface, not a claim of process
isolation against arbitrary Python execution.

Every submitted query is recorded with its attempt number. Invalid actions and
invalid memory requests consume an attempt, each applicability check consumes
one, and fragment expansion consumes another. A synthesis reconstruction after
the scored answer uses the same remaining eight-attempt allowance and counts
toward the episode's interaction cost. Its failure cannot revise that answer.
A guard using the last available
attempt cannot execute its fragment. Failed checks return their actual observed
rows and allow ordinary solving within the remaining allowance. Panel execution
does not call reflection or memory admission, and verifies that the complete
memory digest is unchanged. The fresh old panel uses fixed independent rows
under the original questions/schema/conventions at both checkpoints, reducing
direct replay of ordinary training answers. Some generated quantities remain
structurally constant: the number of orders with refund records is always 22,
and nonhistorical profiles have four North-region customers. Fresh rows alone
therefore do not establish fresh scalar answers for every old question.

Model requests explicitly target authenticated loopback HTTP, disable
environment proxies and redirects, freeze copied message contents and preflight
the complete rendered prompt with the actual backend. Generation attempts,
preflight failures, returned model identity, token usage and timing are recorded.
Unknown generation usage aborts the comparison; it is not recorded as zero.
Known over-limit usage is charged before the failure is raised. Complete
serialized learner storage includes histories, fragment witnesses, provenance
and event journals; the active-payload byte cap is reported separately. These
byte counts describe serialization, not Python heap or GPU memory consumption.

The pilot rejects duplicate or undeclared development seeds/conditions and
refuses an existing output directory. Missing required episode counts or
resource stops prevent a completed comparison. A changed executed-source hash
invalidates the run. No-answer episodes remain explicit scored failures; they
are not silently removed. Stopping at a declared budget does not authorize a
restart or additional held-out evaluation.

The environment's novelty record normalizes literals in its finite reference
query tails and expands the measures actually demanded by each target. It
correctly omits unused reference CTEs and includes the final panel's explicit
delivery/refund restrictions. This provides an auditable target construction;
it is **not** a general semantic canonicalizer or proof that any pair of SQL
queries has different meaning. The benchmark must therefore accompany distinct
fingerprints with the concrete dependency/composition argument, and report the
new shipment-relation block separately from recombination of practiced skills.

The review found and resolved bookkeeping/boundary defects before source freeze:
implicit HTTP proxies, missing output-cap enforcement, mutable audit messages,
unrecorded failed preflights, partial fragment admission, truncated guard
witnesses, omitted retained-state bytes, literal-specific template duplication,
reserved-seed acceptance and overly broad completion status. The compiler also
now rejects non-ASCII continuation of its ASCII parameter names and accurately
labels its 32-part limit as Text/Hole chunks, not parsed SQL AST nodes. None of
these fixes supplies evidence for the research claim; the bounded model pilot
must still satisfy the competence and mechanism prerequisites above.


## Synthesis extension: a stronger mechanism, still a finite witness

The active fragment algorithm now asks the model to propose a new SQL relation
and an outer query that reconstructs one of its own observed, confirmed scalar
answers. This can factor a relation out of a previously executed aggregation;
it is not limited to selecting an unchanged query from a list. The original
selection-based memory helper remains only as a legacy unit-level contract.
The active harness performs the new reconstruction procedure.

A proposal identifies source and guard indexes in its fixed pre-proposal query
prefix. The source must have exactly one finite numeric cell matching the
already confirmed answer. After preparation, the host executes the composed
candidate as one read-only learning check on the same database, using the same
remaining SELECT allowance. Admission verifies the exact request, contiguous
charged attempt number and immutable original witness prefix. It compares the
returned scalar with the witnessed number using the environment's numeric
tolerance; this is not equality of result-column labels or bitwise floating
point equality. The guard is separately retained as its complete observed
columns/rows and checked exactly on later guarded use.

The model cannot add approval flags, replace the host witness or create an entry
through malformed proposal fields. Failed preparation or reconstruction leaves
previous library entries intact; failed reconstruction still costs one SELECT.
A full solve budget skips synthesis, and a failed update cannot change the
already scored answer. Source, verification and guard indexes plus the complete
observed trace hash provide provenance. Admission updates serialized storage
and the peak counter, and applies the same explicit FIFO limits.

Crucially, a cached constant can reconstruct one answer, and an outer query may
ignore its proposed CTE. The tests deliberately exhibit both cases. A stored
constant also fails the same old question on fresh rows. The host therefore
labels admission only `one_own_observed_answer_only`; new SQL text and witness
acceptance cannot be counted as proven abstraction, semantic validity or
compositional transfer. Even a syntactic reference to `reused` is insufficient:
reading a constant or unused projected value need not causally contribute to the
answer. The model study still needs observed useful parameter changes, a novel
outer composition, correct fresh answers and a removal/rebinding diagnostic
supporting the claimed dependence on the learned relation.
