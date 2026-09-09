# v9 runtime review and implemented diagnostic support

This review inspects the immutable v8 pilot and source, then separates observed
interface failures from hypotheses about model capability. It ran no model or
heldout task. The coordinator runs the separately recorded v9 development
experiments. All seven frozen v8 inputs remain unchanged.

## Findings supported by the v8 record

- The 48 warm arm-episodes produced 90 model calls including reflections. None
  ended with `finish_reason=length`. Warm 0/8 is therefore not explained by the
  384-token output ceiling truncating these particular responses.
- No ordinary query ledger entry across the six arms references `catalog`.
  Schema shape alone cannot identify the randomized columns' business meaning.
  History and stateless instead sum a guessed numeric column; both fragment
  arms immediately submit zero on every warm question. These are observed
  action choices, not proof that the output grammar caused those choices.
- Of 141 recorded query errors, 103 result from invalid-action accounting:
  42 statement-separator rejections, 38 unused-binding rejections and 23
  incomplete JSON replies. The incomplete replies occur after warm learning.
  In verbatim warm question 5, the same query containing a quoted literal plus
  an unused `value` binding repeats seven times without repair.
- Numeric feedback is easy to misinterpret in the existing representation.
  The first insight reflection explicitly calls `correctness_feedback:0.0`
  success. The learner then retains that incorrect conclusion. This is a
  concrete failed interpretation, not an inverted evaluator reward.
- Empty memory creates different input text in different arms. Therefore their
  first prompts are not identical. The first-action differences do not isolate
  the causal effect of memory, model capacity, prompting or decoding.
- The original transport preflight returned positional `?` bindings despite
  asking for named bindings. The schema preflight returned a quoted literal
  with an empty binding map. The latter is executable, but neither preflight
  demonstrated correct named-parameter use or database-question competence.

The saved execution/usage audit passes. No warm context exhaustion, unknown
usage, hidden retry, evaluator-target exposure or incorrect scalar grading was
found. The harness does not execute model-generated Python or shell commands.

## Backend checks

The inspected local llama.cpp checkout is exactly
`fe2adf0e722f30f5295fdec8a0f1dc788f7498bc`, matching v8 provenance. Its
`tools/server/server-common.cpp` consumes `response_format.schema` under
`json_object` and explicitly parses Boolean
`chat_template_kwargs.enable_thinking`. There is no static evidence that those
request fields were ignored. This does not independently authenticate every
runtime kernel or generated response.

The publisher recommends non-greedy Qwen3 decoding: non-thinking temperature
0.7, top-p 0.8, top-k 20, min-p 0 and presence penalty 1.5; thinking uses
0.6/0.95/20/0/1.5. V8 fixed temperature zero. Treat revised settings as an
empirical diagnostic, not a guaranteed repair. The card also recommends
excluding reasoning text from historical assistant turns.
[Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-GGUF#best-practices).

## Implemented v9 support

`src/witness_cl/model_v9.py` adds immutable `DecodingV9` and
`LocalInferenceV9`, without changing v8. The constructor accepts configurable
decoding, `response_mode="schema"` or `"json"`, and a maximum output allowance.
Each `complete` call may request a smaller allowance. Both backend endpoints
receive copies of the same frozen effective request, including template
arguments and the actual response format. Per-call records include that
configuration, final content, optional backend reasoning, finish reason and
all returned usage. Credentials are never recorded.

Reasoning-only responses with null final content become an empty model action;
all known tokens remain charged. The client does not retry them. It preserves
full-prompt preflight, context checks, reserved output, shared token/call limits,
unknown-usage accounting and model-alias checks. Eighteen focused offline tests
cover these invariants, including mutation between preflight and generation.

`experiments/audit_competence_v9.py` independently replays the diagnostic SQL,
checks the Python reference answer, reconstructs every legal model input and
action, validates effective configuration and frozen hashes, and recomputes
budget/timing aggregates. A subset or partial run cannot pass the eight-question
competence screen. Nine offline mutation tests cover the principal rejection
paths. Replay does not authenticate execution, model weights, exact backend
tokenization or original timing.

All four completed 4B diagnostic variants independently replayed without issues:

| Variant | Correct | Model calls | Total tokens | SELECT attempts | Recorded seconds |
|---|---:|---:|---:|---:|---:|
| Original greedy prompt | 0/8 | 16 | 10,438 | 8 | 7.172 |
| Explicit-evidence greedy prompt | 0/8 | 17 | 13,985 | 9 | 7.175 |
| Explicit-evidence sampled | 0/8 | 18 | 14,957 | 10 | 8.850 |
| Explicit-evidence thinking | 0/8 | 14 | 25,706 | 6 | 139.205 |

The thinking variant contains 14 nonempty recorded reasoning outputs. Thus
thinking was not silently disabled, but this run still did not solve the warm
questions. Its saved reasoning repeatedly treats the task as a static question:
it recognizes the need for catalog data yet says it cannot execute a query.
The first answer is the example value 123.5 from the action instructions.
This is direct evidence of an interaction-contract misunderstanding in the
model's output, although it does not identify a unique causal source. Clearer instructions, the sampled setting and this bounded reasoning
setting did not establish competence in these attempts. These are adaptive
development diagnostics, not new six-arm results or evidence for the main
learning claim. The replay receipt is
`artifacts/v9/diagnostics/replay-4b.json`.

## Minimal next engineering decisions

1. Keep the actual decoding/model diagnostics bounded and preserve every
   attempted configuration. Establish correct fresh-data SQL solving before
   measuring memory advantage. A passing eight-case development screen is a
   prerequisite, not statistical confirmation.
2. Use explicit Boolean correctness plus plain-language outcome in both full
   history and reflection. Present structured observations directly rather than
   deeply escaped conversation JSON when adapting the shared solver. An empty
   memory should add the same input as other empty memories.
3. State the temporal tool contract explicitly: a returned QUERY object is
   executed immediately, and the next message contains actual database rows;
   the model does have live database access through that action. If this still
   fails, test a common host-issued `SELECT * FROM catalog` bootstrap. Count its SELECT and
   result tokens for every affected arm. Label it supplied exploration policy;
   it is not learned discovery. Do not provide target SQL or evaluator answers.
4. The new `actions_v9.py` ordinary-query parser now passes SQL and typed
   bindings unchanged to the existing bounded SQLite executor. This accepts
   SQLite-supported trailing semicolons, comments and extra unused bindings
   without silently rewriting anything. Writes and multiple statements still
   fail at the charged executor. Stored-fragment validation remains strict.
   Its 42 focused offline cases pass; runner integration is a separate decision.
   See `ACTION_PARSER.md` for the exact boundary.
5. Keep fragment construction separate from basic competence. A correct
   observed scalar may license a proposal and charged reconstruction, but the
   later result must actually depend on the earlier learned relation under
   changed arguments or a new outer operation. Immediate zero answers provide
   no source-query witness. All memory controls must receive the same shared
   solver and inference changes.

Reasoning, model load, failed actions, repairs, documentation reads, reflections
and checks remain measured costs. A lower bill with incorrect answers does not
establish an interaction advantage.
