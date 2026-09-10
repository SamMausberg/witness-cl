# New-interface backbone qualification

The first new-interface qualification used the official-pinned Qwen3-Coder-30B-A3B
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

## Closed candidate 1 and candidate 2

The coder-v1 runs froze at 2026-09-09 21:29:34 UTC and completed by 21:33:46 UTC.
Reuse scored 33/64, drift 39/64. Both failed the unchanged gate. Their independent
audits replayed all 128 episodes; 155 calls used 325,588 measured tokens with no
unknown usage. Preserve `artifacts/campaign/coder-v1` and its copied sources.
No development, sizing or confirmation streams were consumed by this candidate.

Candidate 2 uses the official-pinned dense Qwen3.6-27B model in text-only BF16
inference. Its separately recorded source revision, conversion, runtime and
decoding will be frozen before generation. A shared response-policy revision
requires a brief planning field before the action for every arm; ACE retains
its official reasoning/citation/action envelope. The plan asks the model to
check relevant public catalog conventions. It provides no reference SQL,
computed answer, oracle annotations or alternative evidence to any arm.

The motivation is recorded development evidence: candidate 1 repeatedly omitted
documented monetary conversion, NULL handling and correct aggregation. Both
candidate changes are disclosed together; qualification does not estimate their
separate effects. It evaluates the proposed fixed backbone and interface.

Freeze both fresh candidate-2 runs before either begins: reuse seeds 100200 and
100201, drift seeds 100202 and 100203. The 32 cold episodes per seed, four cell
thresholds, five actions, eight SELECTs, 4,096 output tokens and full-schedule
completion rules are unchanged. Candidate-2 later-stage seeds are recorded in
`configs/campaign_sequence_dense_v2.json`. No threshold, seed or failed outcome
from candidate 1 is replaced. A native or main gain remains unestablished.

The candidate-2 schedules froze at 2026-09-09 21:47:26.967276 UTC (reuse) and
21:47:27.131950 UTC (drift), before either model run. Reuse completed and passed
replay at 21:58:52 UTC; drift completed and
passed replay at 22:10:22 UTC. Every qualification cell scored 8/8: 64/64 per
condition, 128/128 in total. Their 131 calls consumed 339,668 measured tokens
with no unknown usage. These are cold solver-competence results, not stateful
transfer, retention, cost savings or native benchmark results.

The runner subsequently froze development at 22:10:22.299041 UTC on seeds
101100–101103, with all three arms and 2,208 assigned episodes. This was the first block of
the original 32-stream pilot. The subsequent two-hour amendment stopped that
pilot at 161/17,664 completed episodes. The separately frozen diagnostic
completed 240/240 episodes; see [its results](BOUNDED_RESULTS.md). The original
source copy retains this document as it existed at freeze. Later reporting
changes do not change its learner, generator, prompts or schedule.
