# Cold SQL backbone qualification

This is one newly authorized development qualification, selected after the
recorded 94000 and 94001 failures. It is neither a memory comparison nor a
confirmatory experiment. All prior failures remain reported. There is one
configuration, no adaptive retry, no selected-best seed and no altered gate.

The model is the existing pinned official Qwen3-32B Q8_0 GGUF, SHA-256
`2c50eb8aad05047dbf24fa014eb621adf552e14176cabe0c5db4ef38c91e2169`, served
by llama.cpp `91f6a6cf361385700bbe15981f0f39909df77498` on the local GH200.
The source and runtime are captured in an independent `freeze.json` before
the first generation. Runtime startup may follow this written protocol; its
receipt must exist before the freeze. Runtime config is
`configs/query_transfer_runtime.json`; weights and credentials remain outside
the repository. The runtime binds only `127.0.0.1:18084`.

Use `LocalInferenceV9Compatible` with native `ACTION_SCHEMA`, hard
`enable_thinking=false`, temperature 0.7, top-p 0.8, top-k 20, min-p 0,
presence penalty 1.5 and decoding seed 42. These sampled non-thinking
settings follow the [official GGUF model card](https://huggingface.co/Qwen/Qwen3-32B-GGUF).
The existing portable wire-schema transformation and original host checks
remain in place. Solve output allowance is 2,048, context 65,536, timeout
120 seconds per HTTP request, no context truncation and no HTTP retry.
This tests the existing native action pipeline; it does not pre-qualify a
subsequently changed answer interface.

Construct development reuse streams 95100 and 95101. In that order run ordinary
episodes 0 through 15 of each: 32 scheduled episodes. Every episode starts with
a fresh empty `full_history` memory, the exact current `V9_SYSTEM` from
`experiments/stateful_sql.py`, and `learn=False`. Only the public question,
schema, remaining SELECT allowance and real tool feedback enter the model
conversation. Hidden evaluator metadata is appended after the interaction.
Previous episodes, correct answers and qualification outcomes never enter a
later episode. Keep the frozen executor's eight-SELECT limit, ten-action maximum,
ANSWER/QUERY/USE/COMPOSE interface and existing malformed-action behavior.
No fragment discovery or reflection occurs. No solver prompt or learner source
is edited during this run.

Run all 32 regardless of observed correctness. Stop only for infrastructure,
source/configuration integrity failure, unknown usage or a declared resource
ceiling. The entire measured invocation has at most 2,700 seconds, 750,000
known prompt-plus-completion tokens and 384 generation calls. Exact backend
preflight reserves each call's full 2,048-token allowance. Call caps permit
all 32 ten-action episodes, but token/wall ceilings can still make the run
incomplete. Preserve every attempted call and partial episode, charge valid
usage, report unknown token amounts as unknown, and do not fill missing
outcomes. Setup/model loading is separate from measured qualification cost.

For each seed report warm episodes 0--7 and composition episodes 8--15
separately. Qualification requires **at least 7/8 warm and 6/8 composition
correct on each seed**, all 32 recorded, unchanged source/configuration and
complete usage. Any lower score fails this candidate. A resource stop leaves
qualification incomplete, never passed. Report all four cells and all costs;
do not pool them into a significance claim. Passing establishes competence on
these finite development fixtures only. Every subsequent mechanism study
still needs its own frozen policy, untouched independent streams and all-arm
warm checks.

The standalone runner exports raw traces, a final manifest and group summary.
Its offline auditor checks raw hashes, the pre-call freeze, source hashes,
exact native request configuration, complete call accounting, cold-state
invariance and independent SQL outcomes. Completed call sequences are also
reenacted through the frozen executor without network calls; this is a
same-runner reproducibility check, not independent evidence of model quality.
