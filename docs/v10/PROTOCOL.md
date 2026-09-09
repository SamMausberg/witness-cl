# GH200 development protocol

This is a new development study authorized by the September 9, 2026 research
request. It does not extend or reopen the exhausted v9 protocol. All earlier
attempts remain evidence, including failures. New development seeds are
94000–94003; 93000-series prospective heldout seeds remain unused. Only 94000 is
scheduled now. Any subsequent adaptive attempt requires a separately recorded
protocol and freeze; no silent retry, replacement seed or selected-best result.

## Question and implementation

Can bounded feedback-guided repair admit a relation that subsequently contributes
to correct changed-binding or new-composition answers, against competent controls?
The three arms are `full_history`, `evidence`, and `fragments`. All start empty,
use the same backbone, public solver instruction, model context and decoding.
The last two share a deterministic exact evidence shelf. It keeps complete,
successful ordinary SQL observations irrespective of final-answer correctness,
and records confirmed successful answers as episode-specific receipts. No model
rewrites these records. Exact duplicate observations are refreshed. Oldest items
are evicted to a joint 65,536-byte cap for shelf and executable entries; journals
are included separately in total serialized storage. No hidden labels, evaluator
answers or failed post-answer checks enter the evidence shelf.

The executable arm integrates the v9 bounded repair implementation: at most three
model proposals per successful ordinary episode, immutable original evidence,
charged reconstruction and charged empty-relation intervention, with admission
only when the complete outer result changes. Both checks use the original eight
SELECT allowance. Failed checks can inform repair but cannot become source or
guard witnesses. Reuse still costs an applicability query followed by execution.
Emptying tests instance-level dependence, not semantic correctness. No training
of backbone weights occurs; online state changes are the evidence shelf and
executable library. Pretraining is an external prior, not a contribution here.

## Schedule, endpoints and stopping

The three arms run paired on the same reuse stream, with rotating arm order.
Eight warm questions precede an eight-item frozen old panel, 16 further ordinary
questions, the same frozen old panel, and eight frozen final questions: 48 per
arm, 144 planned records. Continue beyond warm only if every arm scores at least
7/8 and all required calls have valid resource receipts. A failure stops the
entire schedule and is reported as a competence failure, never a transfer score.
Panels cannot learn or alter stored memory. All outcomes, including malformed
actions, unsuccessful proposals and incomplete schedules, are retained.

Primary development endpoint: at least one admitted relation contributes to a
correct fresh answer under a changed literal binding or new outer operation.
Offline auditor interventions on the fresh fixture must show output dependence;
such probes are diagnostic cost, never free learner observations. Count changed
binding and composition separately. A solver merely copying SQL from text does
not count as an executed-memory success. Even this endpoint is only a mechanism
demonstration, not evidence of population improvement.

Report per-arm accuracy, SELECTs, model calls, prompt/completion tokens, elapsed
time, active/total memory and every eviction. Compare costs at achieved accuracy;
unequal-accuracy raw totals are descriptive. A direct query can cost one SELECT
where guarded reuse costs at least two, so no SQL-saving claim is prespecified.
Zero correctly executed reuse kills this implementation's mechanism claim on
this stream. Worse old-panel performance rejects empirical non-forgetting on the
tested panel. A single stream cannot establish population noninferiority.

## Compute and provenance

One NVIDIA GH200, approximately 96 GiB device memory (the marketed 480GB name is
not its VRAM). Use official Qwen3-32B GGUF Q8_0 and a pinned CUDA llama.cpp build;
model revisions, content hashes, build flags, context extension and measured
hardware are recorded in the runtime receipt. Loading/download/build are separate
from model-study time. Model identifiers are not performance measurements.

For the scheduled run: 1,800 seconds including incremental export, at most
2,000,000 total model tokens, 1,000 generation attempts, and 1,000,000 tokens per
arm per ordinary/panel budget. Ordinary/panel calls cap at 280/260 per arm.
Each solve generates at most 2,048 tokens; each proposal at most 4,096. Solver
thinking is enabled; proposals use the same recorded nonthinking transport policy
as v9. Temperature .6, top-p .95, top-k 20, min-p 0, presence penalty 1.5, model
sampling seed 42. Native reasoning cutoff is disabled. Context is 65,536 tokens;
any positional scaling beyond the model's native context is explicitly recorded.
No model calls occur outside this schedule except a labeled, generic runtime
smoke test whose usage is separate. The loopback server has authentication and no
built-in tools. Missing usage, runtime failure, source drift or budget exhaustion
stops the run. Partial receipts remain; unknown usage is never imputed as zero.

The runner hashes all executed source modules and this protocol before the first
episode, records model configuration, and rechecks hashes on completion. Raw
traces and summary hashes are saved. A separately written pre-run receipt binds
the protocol, runtime receipt and source inventory before any study call.

## What a later confirmatory study would require

Freeze the implementation after development; qualify the controls independently;
use at least 32 disjoint streams for a first power pilot, then determine stream
count from paired variance without selecting a favorable endpoint. Test reuse,
nonreuse and near-match/drift conditions. Predeclare a 2 percentage-point
old-task noninferiority margin and an accuracy-conditioned token or latency
endpoint, account for all acquisition costs, and correct any joint endpoint
testing. Treat each stream, not each correlated episode, as a sampling unit.
Use native CL-Bench and a stateful transfer benchmark with the same raw-history
and evidence controls before any general deployed-learning claim. Bootstrap or
confidence bounds do not compensate for a selected development stream.
