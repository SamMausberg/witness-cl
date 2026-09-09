# Bounded-thinking qualification result

The candidate **failed** the unchanged gate requiring 7/8 warm and 6/8
composition answers correct on each seed. All 32 episodes completed; there
was no resource censoring or unknown usage. The separate
[protocol](BOUNDED_REASONING_QUALIFICATION.md) and source checkpoint `1715f5b`
precede the first model call.

| Seed | Family | Observed answers correct | Required | Final-query scalar correct |
|---|---|---:|---:|---:|
| 95102 | Warm | 5/8 | 7/8 | 6/8 |
| 95102 | Composition | 5/8 | 6/8 | 7/8 |
| 95103 | Warm | 8/8 | 7/8 | 8/8 |
| 95103 | Composition | 7/8 | 6/8 | 7/8 |

The last column is a posthoc diagnostic using only the final recorded query
when its result is complete, finite, numeric and exactly one row by one column.
All 32 final queries met that shape in this run. The diagnostic independently
scores that recorded scalar against the episode evaluator. It changes neither
the observed answers nor the qualification gate, and it does not predict how
a new interface would select SQL.

Three misses had correct final scalar results followed by rounded answers:
seed 95102 episodes 1, 9 and 10. Other misses were semantic. Episode 4 subtracted
refunds when asked for gross value; episode 6 guessed a table's meaning without
reading the catalog. Even replacing the three rounded answers after the fact
would leave seed 95102's warm block below its gate. Such replacement is not
performed in any reported qualification score.

The full invocation took **1,289.475 seconds (21.49 minutes)**, with **104
generation calls** and **226,490 known tokens**: 147,612 prompt and 78,878
generated. All 104 responses ended with `finish_reason=stop`; none exhausted
the 4,096-token output limit. There were 72 SQL attempts, including four query
errors. Setup is separate. Each recorded preflight and generation request
carried the same `reasoning_budget_tokens=1024`; forced closing tokens, when
used, consume the ordinary output allowance. The API receipts do not separately
count forced-closure events.

The offline audit passed all 32 conversation replays and independently
re-executed all 72 SQL attempts. A separate wrapper replayed the exact
checkpoint, first checking every frozen source hash and rejecting nonfinite
artifact numbers or non-integer ledger counters. It made no network calls and
did not rewrite raw artifacts. The wrapper also verifies the earlier
non-thinking qualification at checkpoint `6ccacb3`.

```bash
.venv/bin/python tools/replay_qualification_at_revision.py \
  artifacts/query_transfer/qualification --revision 6ccacb3 \
  --output /tmp/nonthinking-replay.json
.venv/bin/python tools/replay_qualification_at_revision.py \
  artifacts/query_transfer/reasoning-qualification --revision 1715f5b \
  --output /tmp/bounded-replay.json
.venv/bin/python tools/diagnose_sql_qualification.py \
  artifacts/query_transfer/qualification \
  artifacts/query_transfer/reasoning-qualification \
  --out /tmp/solver-scalar-diagnostics.json
```

The [raw run](../../artifacts/query_transfer/reasoning-qualification/),
[checkpoint replay](../../artifacts/query_transfer/reasoning-qualification-checkpoint-replay.json)
and [diagnostics for both policies](../../artifacts/query_transfer/solver-scalar-diagnostics.json)
are retained. The next interface or memory experiment must carry its own
qualification status. Both cold policies failed their complete gate; their
different development seeds and adaptive selection preclude a controlled
claim about the causal effect of reasoning or pooled significance.
