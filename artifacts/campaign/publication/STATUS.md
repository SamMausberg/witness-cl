# Campaign status

This is a deterministic snapshot of saved local receipts, not a live process monitor.
Partial runs have no published outcome estimates. Complete negative results remain visible.

Input snapshot SHA256: `bcd8c010571b22d63618f431da9bef945d39a3b1b434ae9201dec219ad3e5d9d`.

| Study | Class | Status | Saved records | Decision |
|---|---|---|---:|---|
| coder-v1 / qualification-drift | qualification | complete | 64/64 | Qualification fails |
| coder-v1 / qualification-reuse | qualification | complete | 64/64 | Qualification fails |
| dense-v2 / development | development | incomplete | 61/2208 | Awaiting the complete frozen schedule; no outcome estimates published. |
| dense-v2 / qualification-drift | qualification | complete | 64/64 | Qualification passes |
| dense-v2 / qualification-reuse | qualification | complete | 64/64 | Qualification passes |
| pilot-dense-v2 / additional-28 | development | incomplete | unknown/15456 | Awaiting the complete frozen schedule; no outcome estimates published. |

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
{"completed_records":61,"planned_records":2208,"started_utc":"2026-09-09T22:10:54.754263+00:00","status":"running"}
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

## pilot-dense-v2 / additional-28

Source: `artifacts/campaign/pilot-dense-v2/additional-28`.

Reason: Awaiting the complete frozen schedule; no outcome estimates published.

## Separate runtime setup calls

These generic transport checks are outside the study comparisons. Unknown usage is retained.

| Receipt | Status | Calls | Known token subtotal | Unknown-usage calls |
|---|---|---:|---:|---:|
| artifacts/campaign/runtime/smoke-initial.json | failed | 1 | 0 | 1 |
| artifacts/campaign/runtime/smoke-window65536.json | passed | 2 | 104 | 0 |
| artifacts/campaign/runtime-dense/smoke.json | passed | 2 | 112 | 0 |

Full source, summary, analysis and raw-receipt inventory hashes are retained in status.json.
No model calls, publication actions or remote writes are performed by this report builder.
