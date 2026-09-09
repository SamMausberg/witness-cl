# Native bounded reasoning: local source inspection

The pinned llama.cpp build supports a native reasoning cutoff that preserves
the subsequent structured-output grammar. This is a source-level conclusion,
supported by its sampler unit tests; no new model generation has tested the
combined Qwen3, forced-cutoff and SQL-schema path yet.

## Request and sampler path

The chat endpoint accepts `reasoning_budget_tokens` (alias
`thinking_budget_tokens`). An explicit value overrides the server default
`--reasoning-budget`: `-1` is unrestricted, `0` forces immediate reasoning
closure, and a positive integer sets the reasoning-block threshold. Do not use
the shorter field `reasoning_budget` as a request parameter. The optional
`reasoning_budget_message` inserts text before closure; the minimal candidate
should leave it empty rather than introduce another prompt intervention.

The pinned
[`server-common.cpp`, lines 1365--1377](https://github.com/ggml-org/llama.cpp/blob/91f6a6cf361385700bbe15981f0f39909df77498/tools/server/server-common.cpp#L1365)
extracts the parameter, obtains the model template's detected thinking tags and
forwards both to the sampling layer. The sampler is initialized with generation
prefill tokens, so a `<think>` tag already placed by the Qwen template activates
the budget; see
[`sampling.cpp`, lines 310--323](https://github.com/ggml-org/llama.cpp/blob/91f6a6cf361385700bbe15981f0f39909df77498/common/sampling.cpp#L310).

After the threshold the sampler forces the closing sequence token by token by
masking all other logits to negative infinity. It first permits completion of a
partial UTF-8 sequence. Natural closure before the threshold is preserved.
The generic sampler can rearm on another thinking block, so this is not by
itself a global reasoning-token cap. The implementation and states are in
[`reasoning-budget.cpp`, lines 74--185](https://github.com/ggml-org/llama.cpp/blob/91f6a6cf361385700bbe15981f0f39909df77498/common/reasoning-budget.cpp#L74).
The header's phrase “passthrough forever” for DONE is stale: the implementation
and its multiple-block test explicitly support rearming.

## Structured decoding and usage

For this JSON-schema path the grammar is **not lazy**. The parser constructs
an optional reasoning section followed by the required JSON schema, and the
grammar remains applied during both stages. The allowed closing tag therefore
transitions into the constrained final response. This differs from the lazy
native-tool grammar path, where reasoning temporarily suppresses grammar
application and ending tokens are replayed to activate the trigger. See
[`chat-auto-parser-generator.cpp`, lines 82--99 and 135--170](https://github.com/ggml-org/llama.cpp/blob/91f6a6cf361385700bbe15981f0f39909df77498/common/chat-auto-parser-generator.cpp#L82)
and
[`sampling.cpp`, lines 450--497 and 631--646](https://github.com/ggml-org/llama.cpp/blob/91f6a6cf361385700bbe15981f0f39909df77498/common/sampling.cpp#L450).
The source supports the intended composition, but an actual bounded transport
smoke is still needed before asserting this exact model/template/backend
combination completes valid final JSON after forced closure.

Every sampled token, including a forced closing token, increments the ordinary
generation counter in
[`server-context.cpp`, lines 3855--3866](https://github.com/ggml-org/llama.cpp/blob/91f6a6cf361385700bbe15981f0f39909df77498/tools/server/server-context.cpp#L3855).
The OpenAI-compatible `completion_tokens` is exactly that counter, and
`total_tokens` adds prompt tokens;
[`server-task.cpp`, lines 365--371](https://github.com/ggml-org/llama.cpp/blob/91f6a6cf361385700bbe15981f0f39909df77498/tools/server/server-task.cpp#L365).
Reasoning, closure and final output share `max_tokens`. Thus a 1,024-token
reasoning threshold and 4,096 total output allowance leave roughly 3,000 tokens
for closure and final JSON for one block; this is headroom planning, not a
guarantee of semantic correctness or an exact 1,024-token reasoning maximum.

## Client work needed

The existing frozen `LocalInferenceV9` constructs its request explicitly and
does not expose this field. A new client adapter should inject one validated
`reasoning_budget_tokens` value into both the exact token-preflight request
and generation request. It must record that same additional field in each
wire-request receipt, freeze it in client configuration, preserve all existing
context/usage checks and expose it to the independent auditor. Adding the
field only in an HTTP override while retaining the old recorded request would
make the provenance inaccurate. Do not edit the already frozen client.

A future smoke can use a generic multi-step arithmetic problem with a very
small explicit reasoning threshold and a numeric JSON schema, retain raw
reasoning/final content and all usage, and verify a well-formed final object
plus the native timing/count consistency. It cannot prove SQL competence.
The next SQL qualification still requires a separately agreed protocol,
independent pre-call freeze, fresh seeds, unchanged thresholds and all failures.

## Executed native checks

After the completed non-thinking qualification, the pinned upstream
`tests/test-reasoning-budget.cpp` was compiled to a temporary binary against
the already built shared libraries. No backend source, shared library or
model-server binary was changed. **All 12 sampler tests and the UTF-8 boundary
checks passed**, with no weights loaded by the test and no model calls.
The tests cover natural closure, positive and zero budgets, forced tokens,
multiple blocks, multiple start/end sequences, cloning and manual forcing.
These are sampler checks, not an end-to-end grammar/model experiment. Logs,
source/library/binary hashes and the exact compile command are recorded in
[`reasoning-budget-validation.json`](../../artifacts/query_transfer/reasoning-budget-validation.json).
