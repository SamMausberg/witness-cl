# Witness-CL v9 development results

The review's central objection was correct: v8 never established a competent solver, so it could not test useful abstraction learning. This phase makes measurable progress on that prerequisite and exposes two concrete memory defects. **The original discovery, transfer, efficiency and retention claim remains unproven.**

## What changed and what ran

We preserved v8's source and results. Seven adaptive diagnostics on development seed 92000 tested the original interface, explicit evidence instructions, decoding, a larger pinned model, and a live tool-interaction instruction. All four 4B configurations scored 0/8. The selected Qwen3.5-9B Q8_0 configuration with explicit interaction and thinking scored **7/8**, after the two nonthinking 9B diagnostics scored 1/8 and 0/8. Several factors changed across diagnostics; this is not an isolated causal estimate of model size or reasoning.

The implementation also fixes two real interface defects: ordinary SQL no longer inherits the stored-fragment lexer's restrictions on valid comments/terminal semicolons, and the SQLite authorizer permits anonymous reads of derived relations while retaining physical-table, function and virtual-module restrictions. A correct current-profile CTE in the diagnostic had been denied by the old authorizer; its original failure remains in the diagnostic score.

Three separate, prospectively frozen stream attempts followed on fresh development seeds. The first stopped at a native schema-generation error; the second was intentionally stopped after malformed memory responses and a forced reasoning cutoff. Both are retained, including unavailable usage. The final adapter removes unsupported large string bounds only from the native wire schema, retains the original host validation, disables the native forced reasoning cutoff, and applies the same nonthinking reflection policy to every memory arm. It does not edit model responses or SQL. Each attempt has its own immutable protocol, source/configuration freeze, raw traces and independent replay.

## Final fresh warm block: seed 92003

| Method | Correct / 8 | SELECT attempts | Model calls | Total tokens | Retained bytes |
|---|---:|---:|---:|---:|---:|
| Full legal history | 8 | 9 | 17 | 50,178 | 15,467 |
| Evolving SQL-capable text | 6 | 14 | 30 | 55,808 | 2,425 |
| Checked executable memory | 7 | 22 | 31 | 49,700 | 9,943 |

These are unequal-accuracy descriptive results, not an efficiency comparison at matched accuracy. All three arms started empty and had the same solver, public observations, context ceiling and per-episode SELECT limit. Evolving text was allowed 16 entries of up to 4096 characters and a 64 KiB active-memory cap; it could retain SQL. Its errors and omissions are actual weaknesses of this implementation, not evidence against the strongest possible evolving-memory baseline.

The two text failures expose specific lost information. Its average query omitted the documented NULL-as-zero rule after the previous summary dropped that convention. Before the North-region gross question, its memory contained mainly the latest customer-count notes; the query joined customer IDs to order IDs and summed raw unit amounts without quantity multiplication or conversion to dollars. These traces motivate preserving exact observed documentation and working SQL, but do not isolate memory compression as the sole cause of failure.

The declared threshold was at least 7/8 in **every** arm before continuing. Evolving text failed, so the harness stopped after 24 of 144 planned records. No old-task, post-warm composition or final transfer panel ran. Retention, heldout generalization, population significance and interaction savings are therefore untested. The score 7/8 for executable memory is ordinary SQL-solving accuracy: **zero USE or COMPOSE actions occurred**.

## What the learner actually discovered

Seven proposal calls produced six paid reconstruction attempts and two accepted finite witnesses. Five proposals failed on relation scope, an invalid observation index, or binding semantics. In particular, the outer query repeatedly addressed an invented alias instead of the host's `reused` relation. A string binding contained literal SQL quotes, and a NULL binding was used as an equality filter.

The two admissions do not establish reusable abstraction learning:

- The refunded-order program returns a scalar count. Emptying its relation changes its outer result from 22 to NULL, so this particular wrapper depends on it. Its integer parameter merely turns all joined rows on or off. The target count is structurally 22 in this generator, and the learner never changed that binding.
- The Gold-tier program also returns a scalar. Its reconstruction wrapper duplicates the physical-table computation and ignores `reused`. Deleting, emptying, replacing, or changing the inner binding leaves 1350.25 unchanged. The stored SQL separately returns the training answer, but the paid admission witness did not test its contribution.

These are offline auditor interventions on saved development fixtures: 11 separate SQL executions, zero model calls and zero new learner observations. They do not change any score, memory or recorded learner cost. See [mechanism review](MECHANISM_REVIEW.md) and [exact probes](../../artifacts/v9/mechanism-counterfactuals.json).

## Concrete repair implemented after the run

`discovery_repair_v9.py` is an **unintegrated prototype, tested offline only**. It gives the model actual failed-candidate feedback for at most three proposals while keeping the original successful episode and its source/guard observations fixed. Every reconstruction or dependence probe spends the remaining episode SELECT allowance. A candidate is staged, then tested with an empty learned relation; admission requires a complete changed outer result. An unused relation is rejected rather than counted as successful discovery. Failed repairs never become new source witnesses. Frozen evaluation panels cannot invoke learning.

This check is deliberately conservative. A useful relation can legitimately yield the same result when emptied on one fixture; such a candidate is rejected. Passing one intervention still does not prove useful parameterization, semantic correctness, new composition or retention. This prototype has not been tested with a real model and contributes no empirical successes to the table.

## Cost and evidence ledger

All seven diagnostics and all three stream attempts comprise 89 saved episode records and 244 generation requests. Known usage totals **366,795 tokens**; two failed requests lack actual usage. Their declared input/output reservations add at most 9,109 tokens, giving a protocol-based total upper bound of **375,904**, not a measured exact total. Measured experiment elapsed time is **1,104.03 seconds (18.40 minutes)**, excluding separately recorded model download/load. All remain within the declared 45-minute, 4M-token and 1,600-request development ceilings.

The final stream's 155,686 tokens are fully observed. All three main saved-data replays and all diagnostic replays pass consistency checks. Passing an audit does not turn an incomplete stream into a completed comparison or independently authenticate model weights, backend token counts or clocks. The owned model server was stopped and its temporary authentication key removed.

## Next experiment and decision rule

1. Qualify the shared solver **and** a text-memory control on new, disjoint development streams. Let the text control preserve exact observed documentation and successful SQL within its declared cap; measure whether this resolves its two warm errors. Do not supply target formulas or weaken its prompt to favor executable memory.
2. Integrate the bounded repair prototype only after an independent source freeze. Require an observed row-level relation, a meaningful changed literal binding and a fresh outer operation, with answers dependent on the retrieved program. Reject unused-CTE and constant-answer demonstrations.
3. Run frozen old/new panels only after every control meets the competence gate. Log discovery, guards, retries, SQL, calls, tokens and memory separately; require complete per-arm resources and multiple disjoint streams before a statistical claim.
4. Reconsider the efficiency target before scaling. A competent full-history SQL solver can answer with one SELECT, while this checked-use path costs a guard plus execution, at least two. SQL interaction savings are implausible on those cases without enough baseline exploration to offset that overhead. A token or latency advantage would be a different, separately measured claim.

The strongest next milestone is a traceable, useful learned relation that survives fresh rebinding and composition against competent controls. More abstract proof statements would not substitute for that evidence.
