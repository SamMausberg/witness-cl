# Solver qualification and finite GH200 study

This is a prospective configuration proposal for the newly authorized research
phase. It is not a protocol freeze or an experimental result. No new model
generation was needed for this analysis. The v10 runs and their frozen sources
remain unchanged.

## What the completed traces establish

The 94001 run produced 66 of 144 planned episode records in 2,700.02 seconds.
For its 173 calls with valid usage, backend timings report 2,443.11 seconds of
generation and 234.08 seconds of prompt evaluation. One further attempted call
has unknown token usage; these timings therefore exclude its unreported backend
work. Thirty-four responses exhausted their 2,048-token allowance, consuming
69,632 generated tokens and 1,187.39 seconds of client inference time. These
failures were recorded; they must not be relabeled as successful native decoding.

The three executions of ordinary episode 10 alone consumed 954.10 seconds,
35.34% of the entire run. Twenty-six of their 29 responses ended at the output
limit with an empty final content field. Full history eventually emitted SQL
and a wrong answer: joining refund rows before summing order gross duplicated
the denominator. Evidence and fragments did not produce valid final answers.
This is both an inference-budget failure and evidence of a remaining semantic
failure. Disabling reasoning addresses the former; it does not establish that
the latter will disappear.

The complete trace-derived figures and input file hashes are in
[`runtime-analysis.json`](../../artifacts/query_transfer/runtime-analysis.json).

## Minimal candidate

Use the already cached, SHA-256-pinned Qwen3-32B Q8_0 model and pinned CUDA
llama.cpp build, one server slot, 65,536 tokens per request, unchanged YaRN
settings and full prompt accounting. The separate
[`query_transfer_runtime.json`](../../configs/query_transfer_runtime.json) changes the alias while retaining finite server lifetime, weights, quantization
and context.
It works with the existing runtime launcher; explicitly provide both `--config`
and a fresh query_transfer `--receipt` to avoid overwriting historical receipts.

Use `LocalInferenceV9Compatible` with `thinking=False`, temperature 0.7,
top-p 0.8, top-k 20, min-p 0 and presence penalty 1.5. These are the
[publisher's non-thinking settings](https://huggingface.co/Qwen/Qwen3-32B-GGUF).
Keep solve output allowance 2,048 and reflection allowance 4,096 initially;
changing the reasoning mode and introducing a much smaller output cap together
would obscure the diagnosis. Keep native structured decoding and all host
validation. Keep the shared public solver prompt, public SQLite tool interface,
exact feedback, and per-episode eight-SELECT limit.

This needs no native-pipeline rewrite. The existing client sends
`chat_template_kwargs.enable_thinking=false`; the pinned backend accepts its
`response_format={type: json_object, schema: ...}` and constructs the constrained
chat grammar. Native schema decoding controls final JSON shape, not SQL meaning.
The portable adapter removes only string `maxLength` values greater than 2,000
from the wire schema to avoid native grammar expansion; admission still checks
the original host bounds. No response text or SQL is repaired by that adapter.
The source paths are `src/witness_cl/model_v9.py`,
`src/witness_cl/model_v9_compatible.py`, and pinned llama.cpp
[`tools/server/server-common.cpp`](https://github.com/ggml-org/llama.cpp/blob/91f6a6cf361385700bbe15981f0f39909df77498/tools/server/server-common.cpp).

The selected [qualification protocol](SOLVER_QUALIFICATION.md) uses 32 cold
episodes: eight warm and eight refund/profile compositions on each of two fresh
development seeds. It requires 7/8 warm and 6/8 composition correct on each seed,
with no cross-episode state or qualification examples subsequently supplied to
the measured learner. Warm questions alone missed the observed failure. This
gate does not include shipping compositions and cannot establish competence on
that later family. During a measured memory run retain the gate on all arms,
because state can also harm an otherwise competent solver.

A possible future efficiency change is to terminate an episode on an
output-length finish or empty final reply rather than spending ten calls on
the same format failure. The selected qualification retains the existing
malformed-action behavior to isolate the decoding change. A new failure policy
requires a separate source revision and protocol; it must not alter historical
replay. Do not silently switch thinking modes after seeing a difficult question.

The candidate is killed if it misses the frozen competence threshold, if the
backend still spends output on an unfinished reasoning segment, or if measured
qualification cost cannot support the entire chosen retention schedule. Failure
means select a separately justified solver revision and new qualification; it
does not justify weakening the gate or removing failed templates.

## Resource planning and complete schedules

The previous median rates were 62.92 generated tokens/s and 2,702.05 prompt
tokens/s. These are observed one-slot rates with the former decoding policy,
not a benchmark of the proposed policy. Use conservative planning rates of
60 and 2,500 respectively. For one 144-record stream, the following are
explicit assumptions rather than measured forecasts; reflection counts include
failed attempts, and prompt tokens are charged on every call.

| Scenario | Solve calls/episode | Mean solve output | Mean solve prompt | Reflections; mean output/prompt | Estimated time | Known-token allocation |
|---|---:|---:|---:|---|---:|---:|
| Light | 2 | 100 | 4,000 | 48; 200/3,500 | 19.5 min | 1.36M |
| Planning | 3 | 180 | 6,000 | 72; 200/3,500 | 44.6 min | 2.94M |
| Heavy | 4 | 300 | 8,000 | 72; 387/5,000 | 88.9 min | 5.17M |

Time is `(all generated tokens / 60) + (all prompt tokens / 2500)`; add
measured tokenization, orchestration, validation, export and startup overhead.
For 32 cold qualification episodes with 2--4 solve calls each, these same
assumptions suggest about 3.5--17.5 minutes before overhead. Model startup and
weight hashing previously took roughly a minute and should remain setup cost.
Use qualification measurements to select a *new frozen complete schedule and
allocation before any mechanism-study answers are observed*. Two streams cost
twice these one-stream projections. The larger output ceilings imply a much
larger worst-case cost; the table is not a hard runtime guarantee.

A single global wall limit can censor later retention panels even if separate
panel token budgets exist. Prefer fixed complete independent streams with a
declared maximum number of model actions per episode and per-call output limit.
Reserve the full panel token/call allocation and choose a wall allowance from
qualification cost with explicit margin. A strict wall cap remains an emergency
stop: if reached, retain every record and report incomplete retention. There is
no deterministic completeness guarantee from an empirical throughput estimate.
Do not pool only completed seeds or omit slow arms. Do not pause a stream for
prompt edits or mutate its learner policy. The existing v10 runner enforces a
2,700-second maximum, so a longer allocation requires an explicitly versioned
runner or protocol extension, not an undocumented flag workaround.

## Concurrency

Keep qualification sequential. The pinned backend supports continuous batching
and explicit parallel slots. With non-unified KV and three slots, a total
`--ctx-size 196608 --parallel 3 --no-kv-unified` preserves 65,536 tokens per
slot. The existing launcher deliberately permits only one slot, so this would
need a separate validated launcher. The model has 64 layers, 8 KV heads and
128-dimensional heads: default f16 keys and values require 256 KiB/token, or
16 GiB per 65,536-token slot. Three slots require about 48 GiB of KV plus about
32.4 GiB of model-file storage and extra runtime buffers. This suggests a fit
within the observed 95.58 GiB device memory, but actual loaded allocation must
be checked before claiming it works. Linux unified-memory totals are not added
to that device-memory figure.

Multiple clients could run independent streams or paired arms while preserving
each learner's chronology. Do not share one `LocalInferenceV9Compatible`
instance: reflection temporarily mutates its decoding field. Do not share the
current mutable `_CombinedBudget` across threads without synchronization and
atomic reservations. Separate client instances, locked global accounting,
per-stream source freezes, complete logs and explicit batch settings would be
needed. Batched throughput and numerical behavior are unmeasured here. A
three-slot launch is therefore an optional later engineering experiment, not a
claimed speedup or a prerequisite for qualifying the minimal candidate.
