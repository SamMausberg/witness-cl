# Replaying the frozen v9 evidence after a runtime safety fix

The current runtime explicitly handles SQLite JSON virtual tables that may be
registered lazily and absent from `PRAGMA module_list`. That safety fix changes
`sql_env_v9.py`, which was a hashed input to the old v9 pilots. Replaying those
pilots against changed source would violate their source provenance. Their
recorded outcomes, manifests, and original hashes remain archived unchanged.

`tools/replay_legacy.py` extracts exactly Git revision
`88b0a1b7c093c21135489a3e5cbbda3bb0634536` into a temporary directory and runs its
original `make v9-audit` target. Generated tables stay in that disposable tree.
The original four replay receipts are copied to `artifacts/v10/legacy/`; the
combined receipt records the source archive hash, actual command, interpreter,
SQLite version, platform, elapsed time, and full replay results. No model calls
are made and no old artifacts are replaced.

```sh
python3 tools/replay_legacy.py --output artifacts/v10/legacy-replay.json
```

This command requires a Git checkout containing the fixed historical commit.
Use a full clone, or fetch the missing history before replay; GitHub Actions
must use `actions/checkout` with `fetch-depth: 0`. A source ZIP or a shallow
checkout without that commit is insufficient. The command never accepts an
arbitrary revision or external archive. Git supplies the fixed trusted tree,
and Python's tar `data` filter checks extraction into the temporary directory.
See the [repository reproduction instructions](../../README.md).

The GH200 replay completed successfully on 2026-09-09 using Python 3.12 and
SQLite 3.53.1. All seven competence diagnostic records and all three prospective
stream replay groups passed their saved-data consistency audits. The first two
stream records remain failed partial runs; the portable stream still failed
its competence gate. Every audit retains `claim_confirmed: false`.

This restores **source-specific historical replay**, not historical hardware,
model generation, tokenization, or timing. The interpreter and SQLite are the
current versions and are identified in the receipt. Saved SQL and accounting
consistency does not authenticate original execution or turn a partial failed
pilot into evidence for transfer, efficiency, or retention. The historical
runtime is used only in the disposable replay; the current runtime retains its
SQLite safety repair.

The archived Makefile uses fixed `/tmp/witness-v9-*replay.json` names. Run this
helper once at a time. It copies only new or changed files, comparing file
identity and metadata before and after the invocation rather than relying on
agreement between filesystem and wall-clock resolution. It records missing or
unchanged receipts as a failure, avoiding stale-output success after
an interrupted run. The report, sibling log, receipt directory and each receipt
destination are all checked after resolving symlinks so that none can point
into frozen v1-v9 artifacts.
