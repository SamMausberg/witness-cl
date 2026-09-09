# Saved-data replay for v9

`experiments/audit_sql_abstractions_v9.py` checks a finalized qualification or full development stream against its saved manifest, raw file hashes, summary hash, current frozen execution sources, and an optional external pre-run freeze. It never calls a model or imports the study runner. The actual prospective freezes also bind the support files, model provenance receipt, server configuration and declared common solver configuration.

The auditor constructs its own SQLite connections from evaluator fixtures and independently reproduces each recorded SELECT result or error. Its authorizer preserves the fixed physical table and function allowlists while permitting SQLite's anonymous reads of derived relations; registered virtual modules and SQLite/pragma internals remain denied. It also executes the reference SQL and compares it with the environment's Python answer. SQL wall-time errors that cannot be reproduced are explicitly unverified.

Replay follows the exact rotated order of arms within each scheduled episode. Both the arm/phase budget and the global shared budget must permit every recorded preflight and generation. All model attempts, known prompt/completion usage, unknown failed usage, tokenization, inference, guards, failed actions, post-answer reconstruction and panel calls remain accounted for. Unknown usage is never changed to zero. The reported reservation for such a failure is an allowance under the protocol, not measured backend usage.

The exact legal prompt is reconstructed from only that arm's own prior state, the public question/schema, and observations delivered so far. Boolean correctness feedback is checked against the independently reproduced answer. Ordinary SQL and parameter dictionaries must equal the actual model action, including valid comments, trailing semicolons and unused bindings. The effective model request must match the frozen response mode, per-phase decoding, output cap, schema policy and common model alias. JSON mode still has host-side action/reflection validation; its backend response schema is absent.

The portable attempt has a separate 13-source inventory and an explicit frozen policy. Its recorded host schema must equal the original interface, while an independently implemented normalization removes only integer `maxLength` bounds above 2000 from the wire schema. Every other schema field is preserved. Solve calls retain the common thinking setting; every reflection/proposal call has thinking disabled, as declared before that attempt. The effective decoding and request body are checked per phase. The original client configuration must be restored by finalization. Its selected server process receipt must be frozen and declare reasoning budget `-1`; per-call solve/reflection output ceilings remain enforced.

Accepted abstractions must retain the model's exact proposed relation, an own prior completed guard, an own confirmed scalar source, and the exact next charged reconstruction query. The proposal prompt may not contain its future reconstruction result. Retrieval, applicability decisions, compilation, memory transitions, evidence provenance and complete retained state are replayed. Evaluation panels must preserve learned memory. Warm gating, global stops, required record counts and summary costs are checked rather than inferred from available rows.

This is saved consistency evidence. Environment generation, action parsing, learner memory and compiler definitions are shared frozen code. Replay does not authenticate original execution, model weights, backend tokenization/token counts or the original machine's clock. The receipt records the auditor and helper source hashes. Simulated test calls remain explicitly ineligible for model/resource comparison even when every consistency check passes. A passed replay cannot confirm the research claim, and a partial or failed stream cannot become a complete comparison. One correlated development stream supplies no population confidence interval.

Example:

```sh
python3 experiments/audit_sql_abstractions_v9.py artifacts/v9/prospective-92001 \
  --freeze artifacts/v9/prepilot-freeze.json \
  --output artifacts/v9/prospective-92001-replay.json
```
