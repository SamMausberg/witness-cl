# Current results and remaining research problem

Finalized 9 September 2026. These are two adaptive development streams on a custom SQL fixture, using official Qwen3-32B Q8_0 on a GH200. They are not native benchmark scores or confirmatory evidence. The [machine-readable results](../../artifacts/v10/results.json) retain each stream separately.

The initial stream stops at its failed competence gate after 24 completed warm episodes: full history 7/8, exact evidence 4/8, and checked programs 4/8. The revised stream passes that gate, then reaches its time limit with **65 completed episodes and one partial episode out of 144 planned records**. Neither the post-learning old panel nor the final panel is reached. Retention and the planned final transfer endpoint remain unmeasured.

The 65 finished episodes include two `no_valid_answer` failures scored zero; they are not all successful answers. The frozen manifest's `warm_qualified` field requires both the warm threshold and completion of the whole study, so it is false for this partial run. The actual competence gate passes, as shown by the scores and progression to the old panel. This overloaded field is not evidence that the later panels completed.

## Matched completed follow-up questions

| Method | Warm | Fresh old panel before further learning | Further ordinary questions 8–12 |
|---|---:|---:|---:|
| Full history | 8/8 | 6/8 | 4/5 |
| Exact evidence | 7/8 | 2/8 | 4/5 |
| Checked programs | 7/8 | 4/8 | 3/5 |

Indices are zero-based. Full history and exact evidence also finish ordinary question 13 correctly; the fragment arm times out on that question without an answer. That partial record is retained with its recorded zero reward and costs but is excluded from the matched completed comparison above. These small, adaptively selected panels do not provide independent-stream confidence intervals or establish a general ranking.

## Complete recorded expenditure

Costs below include every recorded phase, learning check, rejected proposal and partial episode. Warm accuracy must not be interpreted as the accuracy associated with all of these costs.

| Stream | Method | Saved records | SELECTs | Calls | Known tokens | Unknown-usage calls | Admissions |
|---|---|---:|---:|---:|---:|---:|---:|
| 94000 | Full history | 8 | 13 | 21 | 78,033 | 0 | 0 |
| 94000 | Exact evidence | 8 | 9 | 17 | 39,567 | 0 | 0 |
| 94000 | Checked programs | 8 | 17 | 23 | 49,424 | 0 | 2 |
| 94001 | Full history | 22 | 34 | 56 | 342,897 | 0 | 0 |
| 94001 | Exact evidence | 22 | 25 | 48 | 190,543 | 0 | 0 |
| 94001 | Checked programs | 22 | 51 | 70 | 247,317 | 1 | 5 |

Across the two streams, recorded expenditure is **235 calls, 947,781 known tokens, one call with unknown token usage, and 3,277.404 study seconds**. Token usage is incomplete and must not be reported as an exact total. The initial stream takes 577.380 seconds. The follow-up stops at its 2,700-second deadline; final export completes at 2,700.024 seconds, so its strict `wall_cap_satisfied` flag is false. The aggregate 3,600-second allowance is not exhausted. No further task-model attempts are made. Two generic transport checks (339 tokens) are accounted separately in the runtime smoke receipt.

The follow-up admits five relations, attempts one USE and one COMPOSE, and rejects both applicability guards. **No proposed relation is executed on a later question.** This does not exclude guard-only cached-query reuse or influence from visible program text. None of the active shelves reaches its FIFO cap, so this run cannot demonstrate empirical behavior under memory eviction.

Both pre-run source inventories remain unchanged. Source-bound replay reproduces all 24 completed initial transcripts and all 65 completed follow-up transcripts. Independent SQLite execution replays 39 and 110 SQL attempts, respectively. The final partial episode and missing schedule remain marked partial; replay consistency does not establish the authenticity of model execution, statistical validity or learning.

## Reproduce the analysis

Use a full Git clone and the locked environment described in the [README](../../README.md). These commands make no model calls:

```sh
.venv/bin/python tools/replay_at_revision.py artifacts/v10/development-94000 \
  --revision 11be4c4e740f57607167cef4b89e0d2680222808 \
  --freeze artifacts/v10/pre-run-freeze.json \
  --output artifacts/v10/replay-94000.json
.venv/bin/python tools/replay_study.py artifacts/v10/development-94001 \
  --freeze artifacts/v10/pre-followup-freeze.json \
  --output artifacts/v10/replay-94001.json
.venv/bin/python tools/current_results.py \
  artifacts/v10/development-94000 artifacts/v10/development-94001
```

The [initial protocol](PROTOCOL.md), [adaptive follow-up protocol](FOLLOWUP_PROTOCOL.md), [hardware record](HARDWARE.md), [initial replay](../../artifacts/v10/replay-94000.json), and [follow-up replay](../../artifacts/v10/replay-94001.json) specify the assumptions and boundaries.

## What is still unsolved

We have not demonstrated an agent that improves on independent stateful streams,
beats a competent full-history or modern memory baseline at matched resources,
and retains old-task performance. The current evidence does not establish a
native benchmark score or universal no-forgetting. Preserving an immutable
function is a different property from selecting it correctly, applying it to a
changed database, or answering a new question correctly.

The early experiments establish useful conditional results: compressed witnesses
preserve a fixed symbolic learner; projected updates protect a fixed feature
span at a capacity cost; separately routed immutable neural modules retain old
outputs with supplied task identities; and reset-based policy checks or
statistical promotion can protect specified values under their assumptions.
The stronger controls expose the limits. Replay substantially reduces neural
forgetting; full-history symbolic and sparse learners match or outperform later
witness variants; the growing v7 learner has positive within-family transfer but
loses badly on final reward. The consolidated paper retains these findings and
the sampling-overlap corrections. See [historical evidence](HISTORICAL_EVIDENCE.md).

The current SQL algorithm preserves exact observations and answer feedback,
proposes executable relations from its own successful queries, and admits them
only after charged reconstruction and an empty-relation intervention. Bounded
repair rejects several unused wrappers and sometimes repairs a proposal. These
checks establish behavior on the tested fixture. They do not identify the
intended relation or prove transfer. The new Lean counterexample explicitly
constructs a program that passes every finite witness and still fails on a fresh
input while remaining intervention-sensitive. See [formal scope](FORMAL.md).

## What the model traces reveal

**Observed.** The initial stream exposed SQLite integer division and a weak
feedback control: the shelf saved successful SQL observations but discarded
failed-answer feedback. The single final follow-up preserved every exact answer
and its Boolean correctness and gave all arms the same generic real-arithmetic
instruction. These are adaptive joint changes, not a causal ablation or heldout
confirmation.

**Observed.** On fresh-data questions, agents sometimes submitted a previous
numeric answer without executing SQL. Full history also did this. The interface
reuses a question and schema without an explicit database snapshot identifier;
freshness is latent until the agent queries. Attribution solely to the memory
representation would therefore be unsupported.

**Observed.** The fragment arm sometimes queries an old aggregate as its
applicability guard. A changed aggregate can block a useful relation. In follow-up
`old_before`, question 3, the guard returned a current count of 4 instead of its
stored value of 6; the agent then answered 4 correctly with that single SELECT.
This is guard-only reuse of a cached query. The reporter's
`executed_memory_actions` counts execution of the proposed relation only. It
cannot measure every influence of visible memory or cached queries on the
solver, and a matching answer alone does not establish causal dependence.

**Observed.** Several proposed outer queries recomputed the source from physical
tables while leaving the supplied relation unused. Reconstruction alone accepted
the numeric coincidence; the empty-relation intervention rejected these
proposals. Repair sometimes fixed this specific defect, but an accepted proposal
is not later useful composition. An attempted `JOIN ({sql})` wrapper was blocked
by its guard before execution and is not evidence of valid composition.

**Inference.** Applicability, freshness and answer grounding deserve separate
controls before a more elaborate memory system. An exact old aggregate is a poor
compatibility key: row changes can invalidate it without changing semantics,
while the same aggregate can hide semantic drift. This interpretation is
consistent with the traces but has not been isolated by a randomized ablation.

## Concrete next experiments and rejection rules

The [paper](../../paper/main.pdf) gives the algorithms, proof boundaries and
prospective endpoints. The following mechanisms remain **unimplemented
hypotheses**; they are not additional positive results of this release.

| Proposal | Test | Resources | Result that kills the practical claim |
|---|---|---|---|
| Current-execution answers | First expose a database snapshot identifier to every arm. Separately require the host to resolve an answer receipt from a numeric SQL result obtained in the current episode. Compare both with the existing interface on independent streams. | One GH200, pinned model, CPU SQLite; charge every extra query and token. Use a separate freeze and report errors and incomplete schedules. | The snapshot cue alone matches the benefit; receipts do not improve accuracy enough to repay their cost; or stale answers persist through constant queries. A current receipt never proves that the query answers the intended question. |
| Delayed corroboration of relations | Keep a relation provisional until a naturally encountered later correct query corroborates a changed binding and changed nondegenerate output. Evaluate new outer operations separately. Compare with exact evidence, full history, repaired programs and controls receiving the same extra observations. | One GH200 for bounded development; source and binding intervention replay on CPU; a SQL access boundary; separate development and confirmatory streams. | Exact evidence matches accuracy at lower total cost; gains disappear under interventions; useful later relation executions are rare; or checking costs erase subsequent savings. Two corroborations can still agree on a misleading proxy. |
| Stronger admission checks | Compare supported-fragment SQL equivalence or bounded counterexample checks with instance reconstruction. Replay counterexamples in SQLite and distinguish proof, counterexample, unsupported and timeout. | CPU solver budget plus the same model budget; accurate SQLite dialect, NULL, bag and arithmetic semantics. | Coverage is too small, counterexamples do not reproduce, or solver costs erase later gains. Source equivalence does not prove intent or usefulness under a new operation. |

A reasonable *prospective target*, requiring a new protocol, is a five-point
future-accuracy gain over the strongest qualified compact control, at most two
points of old-task loss, and a 20% token saving against full history at qualified
accuracy. These are separate endpoints. Complete independent streams, rather
than correlated episode rows, are the replication unit. With paired standard
deviation 0.10, 80% power and one-sided endpoint level 0.005, a normal planning
approximation gives roughly 47 streams for a five-point effect and 292 for a
two-point retention margin. These are assumptions for resource planning, not a
power guarantee. The present development streams cannot support that claim.

The strongest relevant published alternatives and their limits are mapped in
[related work](RELATED_WORK.md): full-context ICL, evolving text and workflow
memory, executable skill libraries, neural test-time adaptation, SQL equivalence
checking and statistical policy improvement. The repository does not pretend to
have reimplemented or defeated all of them.
