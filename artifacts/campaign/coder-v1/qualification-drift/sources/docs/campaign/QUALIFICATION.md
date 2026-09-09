# New-interface backbone qualification

This prospective qualification uses the official-pinned Qwen3-Coder-30B-A3B
Instruct BF16 runtime. The previous bounded-reasoning Qwen3-32B attempt is complete:
32 episodes, 25 correct, 104 calls, 226,490 measured tokens and no unknown usage.
It failed its frozen per-seed gate and remains independently replayable.

Freeze two separate new-interface runs before either begins. Reuse qualification
uses development seeds 100100 and 100101. Drift qualification uses 100102 and
100103. Each has 32 cold episodes per seed: eight initial questions, eight changed
bindings, eight new outer computations, and eight fresh future questions. All
64 episodes per run must finish regardless of their answers. State is empty at
every episode; no example or answer is retained for a later task.

Each seed requires at least 7/8 initial answers and 6/8 in each other cell. Use
the common current-execution interface and charged current catalog. Every episode
has five model actions, eight SELECTs and at most 4,096 output tokens per call.
The fixed nonthinking decoding, 65,536 context, model/backend hashes, environment,
source files and schedule must appear in each pre-call freeze. The campaign runner
reserves complete episode allowances; there is no short campaign wall deadline.
Unknown usage, source mismatch or infrastructure failure leaves an incomplete run.

Qualification is development evidence. It cannot establish a learned mechanism,
retention or a comparison with ACE. Native generation, online memory development,
sizing and confirmation each require their own frozen schedule. Failed candidates
are preserved, and another policy requires a separately documented development
revision rather than relaxed thresholds or replacement episodes.
