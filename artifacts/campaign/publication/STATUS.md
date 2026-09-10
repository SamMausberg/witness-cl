# Campaign status

This is a deterministic snapshot of saved local receipts, not a live process monitor.
Partial runs have no published outcome estimates. Complete negative results remain visible.

Input snapshot SHA256: `6816101c2f6ba941e02bd008cb5e6d58d55c1afe2ddb89e288fb234f651a719d`.

| Study | Class | Status | Saved records | Decision |
|---|---|---|---:|---|
| coder-v1 / qualification-drift | qualification | complete | 64/64 | Qualification fails |
| coder-v1 / qualification-reuse | qualification | complete | 64/64 | Qualification fails |
| dense-v2 / development | development | incomplete | 161/2208 | Awaiting the complete frozen schedule; no outcome estimates published. |
| dense-v2 / qualification-drift | qualification | complete | 64/64 | Qualification passes |
| dense-v2 / qualification-reuse | qualification | complete | 64/64 | Qualification passes |
| fast-dense-v2 | descriptive_fast_240_v1 | incomplete | 0/240 | Awaiting the complete frozen schedule; no outcome estimates published. |
| fast-dense-v2-restart | descriptive_fast_240_v1 | complete | 240/240 | Descriptive only |
| fast-dense-v2-restart-deletion | agent_deletion | complete | 1/1 | Descriptive only |
| pilot-dense-v2 / additional-28 | development | incomplete | 0/15456 | Awaiting the complete frozen schedule; no outcome estimates published. |

## coder-v1 / qualification-drift

Source: `artifacts/campaign/coder-v1/qualification-drift`.

Complete physical usage: 82 calls, 173,049 measured tokens.

Descriptive outcomes (complete studies only):

| Condition | Checkpoint | Arm | Streams | Final/probe correct | Tokens |
|---|---:|---|---:|---:|---:|
| drift | — | full_history | 2 | 10/16 | 173049 |

Every qualification cell:

| Seed | Arm | Family | Correct | Required | Pass |
|---:|---|---|---:|---:|---|
| 100102 | full_history | warm | 4/8 | 7 | False |
| 100102 | full_history | binding | 2/8 | 6 | False |
| 100102 | full_history | new_outer | 6/8 | 6 | True |
| 100102 | full_history | future | 4/8 | 6 | False |
| 100103 | full_history | warm | 4/8 | 7 | False |
| 100103 | full_history | binding | 6/8 | 6 | True |
| 100103 | full_history | new_outer | 7/8 | 6 | True |
| 100103 | full_history | future | 6/8 | 6 | True |

## coder-v1 / qualification-reuse

Source: `artifacts/campaign/coder-v1/qualification-reuse`.

Complete physical usage: 73 calls, 152,539 measured tokens.

Descriptive outcomes (complete studies only):

| Condition | Checkpoint | Arm | Streams | Final/probe correct | Tokens |
|---|---:|---|---:|---:|---:|
| reuse | — | full_history | 2 | 6/16 | 152539 |

Every qualification cell:

| Seed | Arm | Family | Correct | Required | Pass |
|---:|---|---|---:|---:|---|
| 100100 | full_history | warm | 4/8 | 7 | False |
| 100100 | full_history | binding | 5/8 | 6 | False |
| 100100 | full_history | new_outer | 0/8 | 6 | False |
| 100100 | full_history | future | 1/8 | 6 | False |
| 100101 | full_history | warm | 6/8 | 7 | False |
| 100101 | full_history | binding | 6/8 | 6 | True |
| 100101 | full_history | new_outer | 6/8 | 6 | True |
| 100101 | full_history | future | 5/8 | 6 | False |

## dense-v2 / development

Source: `artifacts/campaign/dense-v2/development`.

Reason: Awaiting the complete frozen schedule; no outcome estimates published.

Saved progress (not an audited outcome estimate):
```json
{"completed_records":161,"planned_records":2208,"progress_source":"contiguous_frozen_schedule_prefix","saved_records":161,"started_utc":"2026-09-09T22:10:54.754263+00:00","status":"running","stopped_attempt_records":0}
```

## dense-v2 / qualification-drift

Source: `artifacts/campaign/dense-v2/qualification-drift`.

Complete physical usage: 67 calls, 174,119 measured tokens.

Descriptive outcomes (complete studies only):

| Condition | Checkpoint | Arm | Streams | Final/probe correct | Tokens |
|---|---:|---|---:|---:|---:|
| drift | — | full_history | 2 | 16/16 | 174119 |

Every qualification cell:

| Seed | Arm | Family | Correct | Required | Pass |
|---:|---|---|---:|---:|---|
| 100202 | full_history | warm | 8/8 | 7 | True |
| 100202 | full_history | binding | 8/8 | 6 | True |
| 100202 | full_history | new_outer | 8/8 | 6 | True |
| 100202 | full_history | future | 8/8 | 6 | True |
| 100203 | full_history | warm | 8/8 | 7 | True |
| 100203 | full_history | binding | 8/8 | 6 | True |
| 100203 | full_history | new_outer | 8/8 | 6 | True |
| 100203 | full_history | future | 8/8 | 6 | True |

## dense-v2 / qualification-reuse

Source: `artifacts/campaign/dense-v2/qualification-reuse`.

Complete physical usage: 64 calls, 165,549 measured tokens.

Descriptive outcomes (complete studies only):

| Condition | Checkpoint | Arm | Streams | Final/probe correct | Tokens |
|---|---:|---|---:|---:|---:|
| reuse | — | full_history | 2 | 16/16 | 165549 |

Every qualification cell:

| Seed | Arm | Family | Correct | Required | Pass |
|---:|---|---|---:|---:|---|
| 100200 | full_history | warm | 8/8 | 7 | True |
| 100200 | full_history | binding | 8/8 | 6 | True |
| 100200 | full_history | new_outer | 8/8 | 6 | True |
| 100200 | full_history | future | 8/8 | 6 | True |
| 100201 | full_history | warm | 8/8 | 7 | True |
| 100201 | full_history | binding | 8/8 | 6 | True |
| 100201 | full_history | new_outer | 8/8 | 6 | True |
| 100201 | full_history | future | 8/8 | 6 | True |

## fast-dense-v2

Source: `artifacts/campaign/fast-dense-v2`.

Reason: Awaiting the complete frozen schedule; no outcome estimates published.

Inference scope: Two-stream descriptive diagnostic; accuracy superiority, two-point retention noninferiority and original pilot completion are not established.

Saved progress (not an audited outcome estimate):
```json
{"completed_records":0,"planned_records":240,"progress_source":"contiguous_frozen_schedule_prefix","saved_records":0,"stopped_attempt_records":0}
```

## fast-dense-v2-restart

Source: `artifacts/campaign/fast-dense-v2-restart`.

Inference scope: Two-stream descriptive diagnostic; accuracy superiority, two-point retention noninferiority and original pilot completion are not established.

Complete physical usage: 353 calls, 4,251,272 measured tokens.

Descriptive outcomes (complete studies only):

| Condition | Checkpoint | Arm | Streams | Final/probe correct | Tokens |
|---|---:|---|---:|---:|---:|
| reuse | — | ace | 2 | 16/16 | 625254 |
| reuse | — | delayed | 2 | 16/16 | 1347094 |
| reuse | — | full_history | 2 | 16/16 | 2278924 |

Qualifying fixed-program events: 1. Agent deletion reruns: **not established by this audit**.

The first five events in frozen record order (all events are in status.json):
```json
{"agent_deletion_rerun":"not_performed_by_this_offline_auditor","arm":"delayed","changed_corroboration_bindings":true,"complete_chronological_chain":true,"computed_measure_flips_to_wrong":true,"condition":"reuse","corroboration":{"data_sha256":"e67a45b11573c1642940f8362cc97c1fead2c43312abc675717c58fc35d6fcda","episode_id":"008d8946e23a779a1110306c","record_index":11,"record_ordinal":165,"test_double_calls":0,"unknown_usage_calls":0},"empty_relation_flips_to_wrong":true,"entry_key":"2ac61c52139b46cf0603c419a0c44405c26bc8cfdf32400eca16bd36358573e4","episode_id":"38951e5678392467042e7f34","execution_bindings":[{"sv_text_0":"North"}],"index":3,"interventions":[{"answer_wrong":true,"elapsed_seconds":0.004316904000006616,"kind":"empty_relation","learner_observation":false,"params":{"wcl_program_0_scan_0_0":"North"},"result":{"columns":["answer"],"error":null,"rows":[[null]],"truncated":false},"sql":"WITH \"wcl_program_0_relation_0\" AS (SELECT * FROM (SELECT \"o\".\"c_vracnj\" AS \"c0\", \"o\".\"c_nysqat\" AS \"c1\", \"o\".\"c_jnqbsy\" AS \"c2\", \"o\".\"c_bnwrus\" AS \"c3\", \"o\".\"c_qvdfnp\" AS \"c4\", \"o\".\"c_nxpehr\" AS \"c5\", \"o\".\"c_njrvnt\" AS \"c6\", \"p\".\"c_ayunwh\" AS \"c7\", \"p\".\"c_rvmczc\" AS \"c8\", \"p\".\"c_zjsbtp\" AS \"c9\", \"p\".\"c_rtscxq\" AS \"c10\", \"p\".\"c_ctmiqh\" AS \"c11\", \"p\".\"c_tpnzix\" AS \"c12\", \"refs\".\"c_bpiywr\" AS \"c13\", \"refs\".\"total_refunds\" AS \"c14\", \"o\".\"c_jnqbsy\" * \"o\".\"c_bnwrus\" - COALESCE(\"refs\".\"total_refunds\", 0) AS \"m0\" FROM \"r_tiwwww\" AS \"o\" INNER JOIN \"r_fzayqu\" AS \"p\" ON \"o\".\"c_nysqat\" = \"p\".\"c_rvmczc\" LEFT JOIN (SELECT \"r_asismm\".\"c_bpiywr\" AS \"c_bpiywr\", SUM(\"r_asismm\".\"c_xfjbdw\") AS \"total_refunds\" FROM \"r_asismm\" AS \"r_asismm\" GROUP BY \"r_asismm\".\"c_bpiywr\") AS \"refs\" ON \"o\".\"c_vracnj\" = \"refs\".\"c_bpiywr\" WHERE \"p\".\"c_tpnzix\" = 1 AND \"p\".\"c_zjsbtp\" = :wcl_program_0_scan_0_0 AND NOT \"o\".\"c_jnqbsy\" IS NULL) AS audit_empty WHERE 0), \"wcl_program_0_relation_1\" AS (SELECT AVG(\"i\".\"m0\") AS \"answer\" FROM \"wcl_program_0_relation_0\" AS \"i\") SELECT \"output\".\"answer\" FROM \"wcl_program_0_relation_1\" AS \"output\"","status":"null","view_key":"96c82b9d6b0039edb2ea57497d20d8679cf0e84786cb43e32eb77de4b1563fa7"},{"answer_wrong":true,"column":"m0","elapsed_seconds":0.00420944700090331,"kind":"measure_override","learner_observation":false,"params":{"wcl_program_0_scan_0_0":"North"},"replacement":0,"result":{"columns":["answer"],"error":null,"rows":[[0.0]],"truncated":false},"sql":"WITH \"wcl_program_0_relation_0\" AS (SELECT \"o\".\"c_vracnj\" AS \"c0\", \"o\".\"c_nysqat\" AS \"c1\", \"o\".\"c_jnqbsy\" AS \"c2\", \"o\".\"c_bnwrus\" AS \"c3\", \"o\".\"c_qvdfnp\" AS \"c4\", \"o\".\"c_nxpehr\" AS \"c5\", \"o\".\"c_njrvnt\" AS \"c6\", \"p\".\"c_ayunwh\" AS \"c7\", \"p\".\"c_rvmczc\" AS \"c8\", \"p\".\"c_zjsbtp\" AS \"c9\", \"p\".\"c_rtscxq\" AS \"c10\", \"p\".\"c_ctmiqh\" AS \"c11\", \"p\".\"c_tpnzix\" AS \"c12\", \"refs\".\"c_bpiywr\" AS \"c13\", \"refs\".\"total_refunds\" AS \"c14\", \"o\".\"c_jnqbsy\" * \"o\".\"c_bnwrus\" - COALESCE(\"refs\".\"total_refunds\", 0) AS \"m0\" FROM \"r_tiwwww\" AS \"o\" INNER JOIN \"r_fzayqu\" AS \"p\" ON \"o\".\"c_nysqat\" = \"p\".\"c_rvmczc\" LEFT JOIN (SELECT \"r_asismm\".\"c_bpiywr\" AS \"c_bpiywr\", SUM(\"r_asismm\".\"c_xfjbdw\") AS \"total_refunds\" FROM \"r_asismm\" AS \"r_asismm\" GROUP BY \"r_asismm\".\"c_bpiywr\") AS \"refs\" ON \"o\".\"c_vracnj\" = \"refs\".\"c_bpiywr\" WHERE \"p\".\"c_tpnzix\" = 1 AND \"p\".\"c_zjsbtp\" = :wcl_program_0_scan_0_0 AND NOT \"o\".\"c_jnqbsy\" IS NULL), \"wcl_program_0_relation_1\" AS (SELECT \"s\".\"c0\" AS \"c0\", \"s\".\"c1\" AS \"c1\", \"s\".\"c2\" AS \"c2\", \"s\".\"c3\" AS \"c3\", \"s\".\"c4\" AS \"c4\", \"s\".\"c5\" AS \"c5\", \"s\".\"c6\" AS \"c6\", \"s\".\"c7\" AS \"c7\", \"s\".\"c8\" AS \"c8\", \"s\".\"c9\" AS \"c9\", \"s\".\"c10\" AS \"c10\", \"s\".\"c11\" AS \"c11\", \"s\".\"c12\" AS \"c12\", \"s\".\"c13\" AS \"c13\", \"s\".\"c14\" AS \"c14\", 0 AS \"m0\" FROM \"wcl_program_0_relation_0\" AS \"s\"), \"wcl_program_0_relation_2\" AS (SELECT AVG(\"i\".\"m0\") AS \"answer\" FROM \"wcl_program_0_relation_1\" AS \"i\") SELECT \"output\".\"answer\" FROM \"wcl_program_0_relation_2\" AS \"output\"","status":"numeric","view_key":"96c82b9d6b0039edb2ea57497d20d8679cf0e84786cb43e32eb77de4b1563fa7"},{"answer_wrong":true,"column":"m0","elapsed_seconds":0.004131589997996343,"kind":"measure_override","learner_observation":false,"params":{"wcl_program_0_scan_0_0":"North"},"replacement":null,"result":{"columns":["answer"],"error":null,"rows":[[null]],"truncated":false},"sql":"WITH \"wcl_program_0_relation_0\" AS (SELECT \"o\".\"c_vracnj\" AS \"c0\", \"o\".\"c_nysqat\" AS \"c1\", \"o\".\"c_jnqbsy\" AS \"c2\", \"o\".\"c_bnwrus\" AS \"c3\", \"o\".\"c_qvdfnp\" AS \"c4\", \"o\".\"c_nxpehr\" AS \"c5\", \"o\".\"c_njrvnt\" AS \"c6\", \"p\".\"c_ayunwh\" AS \"c7\", \"p\".\"c_rvmczc\" AS \"c8\", \"p\".\"c_zjsbtp\" AS \"c9\", \"p\".\"c_rtscxq\" AS \"c10\", \"p\".\"c_ctmiqh\" AS \"c11\", \"p\".\"c_tpnzix\" AS \"c12\", \"refs\".\"c_bpiywr\" AS \"c13\", \"refs\".\"total_refunds\" AS \"c14\", \"o\".\"c_jnqbsy\" * \"o\".\"c_bnwrus\" - COALESCE(\"refs\".\"total_refunds\", 0) AS \"m0\" FROM \"r_tiwwww\" AS \"o\" INNER JOIN \"r_fzayqu\" AS \"p\" ON \"o\".\"c_nysqat\" = \"p\".\"c_rvmczc\" LEFT JOIN (SELECT \"r_asismm\".\"c_bpiywr\" AS \"c_bpiywr\", SUM(\"r_asismm\".\"c_xfjbdw\") AS \"total_refunds\" FROM \"r_asismm\" AS \"r_asismm\" GROUP BY \"r_asismm\".\"c_bpiywr\") AS \"refs\" ON \"o\".\"c_vracnj\" = \"refs\".\"c_bpiywr\" WHERE \"p\".\"c_tpnzix\" = 1 AND \"p\".\"c_zjsbtp\" = :wcl_program_0_scan_0_0 AND NOT \"o\".\"c_jnqbsy\" IS NULL), \"wcl_program_0_relation_1\" AS (SELECT \"s\".\"c0\" AS \"c0\", \"s\".\"c1\" AS \"c1\", \"s\".\"c2\" AS \"c2\", \"s\".\"c3\" AS \"c3\", \"s\".\"c4\" AS \"c4\", \"s\".\"c5\" AS \"c5\", \"s\".\"c6\" AS \"c6\", \"s\".\"c7\" AS \"c7\", \"s\".\"c8\" AS \"c8\", \"s\".\"c9\" AS \"c9\", \"s\".\"c10\" AS \"c10\", \"s\".\"c11\" AS \"c11\", \"s\".\"c12\" AS \"c12\", \"s\".\"c13\" AS \"c13\", \"s\".\"c14\" AS \"c14\", NULL AS \"m0\" FROM \"wcl_program_0_relation_0\" AS \"s\"), \"wcl_program_0_relation_2\" AS (SELECT AVG(\"i\".\"m0\") AS \"answer\" FROM \"wcl_program_0_relation_1\" AS \"i\") SELECT \"output\".\"answer\" FROM \"wcl_program_0_relation_2\" AS \"output\"","status":"null","view_key":"96c82b9d6b0039edb2ea57497d20d8679cf0e84786cb43e32eb77de4b1563fa7"}],"lineage":{"m0":{"column":"m0","computed_from_physical_columns":true,"nodes":[{"children":["refs.total_refunds","\"o\".\"c_bnwrus\"","\"o\".\"c_jnqbsy\""],"expression":"\"o\".\"c_jnqbsy\" * \"o\".\"c_bnwrus\" - COALESCE(\"refs\".\"total_refunds\", 0) AS \"m0\"","name":"m0"},{"children":["\"r_asismm\".\"c_xfjbdw\""],"expression":"SUM(\"r_asismm\".\"c_xfjbdw\") AS \"total_refunds\"","name":"refs.total_refunds"},{"children":[],"expression":"\"r_asismm\" AS \"r_asismm\"","name":"\"r_asismm\".\"c_xfjbdw\""},{"children":[],"expression":"\"r_tiwwww\" AS \"o\"","name":"\"o\".\"c_bnwrus\""},{"children":[],"expression":"\"r_tiwwww\" AS \"o\"","name":"\"o\".\"c_jnqbsy\""}],"physical_columns":[["r_asismm","c_xfjbdw"],["r_tiwwww","c_bnwrus"],["r_tiwwww","c_jnqbsy"]],"recorded_origin":"scalar_expression","scope":"Resolved SQL dataflow only; no semantic-equivalence or meaning proof.","status":"resolved_computation"}},"new_aggregate_operations":["avg"],"new_outer_operation":true,"phase":"final","program_operations":{"aggregates":["avg"],"groups":1,"groups_with_keys":0,"joins":0},"qualifying_event":true,"record_ordinal":219,"seed":101303,"source":{"data_sha256":"c0f73f73e3ee81c64cf37442ed0ddc7a84ede7b9a7c75a24d6c44c2b565f7770","episode_id":"f0186fda0b95296a2b7a4561","record_index":3,"record_ordinal":129,"test_double_calls":0,"unknown_usage_calls":0},"source_operations":["sum"],"structural_mechanism_event":true,"test_double_calls":0,"three_fresh_data_snapshots":true,"unknown_usage_calls":0,"view_key":"96c82b9d6b0039edb2ea57497d20d8679cf0e84786cb43e32eb77de4b1563fa7"}
```

## fast-dense-v2-restart-deletion

Source: `artifacts/campaign/fast-dense-v2-restart-deletion`.

Complete physical usage: 1 calls, 18,777 measured tokens.

Agent relation deletion: 0/1 answers flip to wrong; 1 remain correct despite deletion.

Every eligible case was frozen before rerunning. Original direct SQL evidence remains; rerun feedback does not reach the source campaign. These are conditional event counts, not independent-stream estimates.

Original acquisition/evaluation cost (separate from these additional reruns): 4251272 tokens.

## pilot-dense-v2 / additional-28

Source: `artifacts/campaign/pilot-dense-v2/additional-28`.

Reason: Awaiting the complete frozen schedule; no outcome estimates published.

Saved progress (not an audited outcome estimate):
```json
{"completed_records":0,"planned_records":15456,"progress_source":"contiguous_frozen_schedule_prefix","saved_records":0,"stopped_attempt_records":0}
```

## Separate runtime setup calls

These generic transport checks are outside the study comparisons. Unknown usage is retained.

| Receipt | Status | Calls | Known token subtotal | Unknown-usage calls |
|---|---|---:|---:|---:|
| artifacts/campaign/runtime/smoke-initial.json | failed | 1 | 0 | 1 |
| artifacts/campaign/runtime/smoke-window65536.json | passed | 2 | 104 | 0 |
| artifacts/campaign/runtime-dense/smoke.json | passed | 2 | 112 | 0 |

Full source, summary, analysis and raw-receipt inventory hashes are retained in status.json.
No model calls, publication actions or remote writes are performed by this report builder.
