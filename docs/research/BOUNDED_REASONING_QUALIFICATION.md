# Bounded-thinking SQL qualification

This is one additional adaptive development qualification authorized after the
complete non-thinking qualification failed. That earlier run, its original
tool and its audit are preserved at Git checkpoint
`6ccacb3`; it is not replaced or silently rerun. This attempt is not a
confirmatory comparison of decoding policies: the policy was selected after
examining failures, and fresh seeds change the fixtures.

Keep the same pinned official Qwen3-32B Q8_0 GGUF and llama.cpp binary, shared
`V9_SYSTEM`, native `ACTION_SCHEMA`, public SQLite observations and cold
`full_history` state. Each episode starts empty and uses `learn=False`.
Only the client policy changes: `enable_thinking=true`, temperature 0.6,
top-p 0.95, top-k 20, min-p 0, presence penalty 1.5, sampling seed 42,
`reasoning_budget_tokens=1024` and `max_tokens=4096`. These thinking sampling
settings follow the [official GGUF card](https://huggingface.co/Qwen/Qwen3-32B-GGUF).
The new `LocalInferenceBoundedReasoning` adapter inserts the exact budget into
both token preflight and generation, records the actual wire configuration for
each, and retains original host schema, usage, context and alias checks.
The runtime retains a single slot, 65,536-token context and 120-second HTTP
timeout. There is no HTTP retry, context truncation or host editing of model
output. No reasoning-budget message is inserted.

The native sampler forces the closing thinking tag after the threshold,
with an allowance for completing a partial UTF-8 sequence. Closure tokens and
final JSON count toward the same 4,096-token output ceiling. The threshold
is per thinking block rather than a separate free token allowance. The local
[source inspection and native sampler tests](REASONING_BUDGET.md) establish
the implementation path. They do not establish this candidate's SQL accuracy
or guarantee a well-formed final answer before its output cap.

Run development reuse streams **95102 and 95103**, in that order, ordinary
episodes **0--15** for each: **32 episodes total**. Preserve the frozen
executor's eight-SELECT allowance, ten-action maximum and malformed-action
handling. All 32 must run regardless of correctness unless infrastructure,
unknown usage, source/configuration integrity or declared resources stop the
invocation. No memory learning, reflection, retained qualification examples,
gold answers or evaluator metadata enter model inputs. Full evaluator data is
appended only after the corresponding interaction.

The measured invocation is capped at **2,700 seconds, 1,500,000 known
prompt-plus-completion tokens and 384 generation calls**. Preflight reserves
the whole 4,096-token output allowance for each call. Unknown usage stops the
run and remains explicitly unknown. Every attempted call and partial episode
is retained; missing episodes are never replaced. Setup and native unit-test
costs are separate. There is no further model candidate in this protocol.

The unchanged gate requires **at least 7/8 warm and 6/8 composition correct
on each seed**, all 32 recorded, full usage and unchanged source/configuration.
Report all four cells and all costs. A resource stop means incomplete
qualification; a complete below-threshold run means this candidate failed.
Passing establishes competence only on these finite development fixtures.
It does not pre-qualify a new answer interface, memory mechanism, shipping
questions, retention claim or confirmatory population claim.

Write an independent `freeze.json` containing the full prompt, source hashes,
client policy including the native reasoning budget, model/backend/runtime
receipt, seed schedule, thresholds and caps before the first generation.
Results belong in `artifacts/query_transfer/reasoning-qualification/`.
The offline audit must validate both wire payloads and their prompt digests,
all costs and cold memory state, independently re-execute SQL, and reenact
completed call sequences through the frozen executor without network access.

```bash
.venv/bin/python tools/qualify_sql_solver.py freeze --bounded-reasoning \
  --out artifacts/query_transfer/reasoning-qualification \
  --runtime-receipt artifacts/query_transfer/runtime-serve.json
.venv/bin/python tools/qualify_sql_solver.py run --bounded-reasoning \
  --out artifacts/query_transfer/reasoning-qualification \
  --key-file ~/.local/share/witness-cl/runtime/server.key
.venv/bin/python tools/qualify_sql_solver.py audit --bounded-reasoning \
  --out artifacts/query_transfer/reasoning-qualification
```

To replay the earlier non-thinking run, extract checkpoint `6ccacb3` into a
temporary directory, use that directory's `tools/qualify_sql_solver.py audit`,
and pass the absolute original qualification directory. The interpreter must
have this repository's dependencies; clear inherited `PYTHONPATH` so imports
come from the extracted source. Do not use the extended current source to
pretend it is the original frozen tool.
