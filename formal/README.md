# Formalization status

The current audit on the GH200 host uses pinned **Lean 4.19.0, aarch64**, and
checks **90 authored theorem statements**. Its independent kernel inventory
audits all **234 project theorem constants**, including generated equations and
private helper proofs. Generated constants are not additional research results.
All dependencies are among Lean's standard `propext`, `Quot.sound`, and
`Classical.choice`; 27 authored statements are axiom-free. No source proof
placeholders, custom logical axioms, or unexpected proof dependencies were found.

The new statement proves a limitation: every finite set of contexts permits a
candidate that reconstructs all witnessed answers and changes when its relation
is emptied, yet fails at a fresh context while remaining intervention-sensitive.
Dependence does not establish semantic transfer. This is an elementary
counterexample, not a new learning lower bound.

```bash
python3 formal/audit_v10.py --output artifacts/v10
python3 -m pytest -q tests/test_formal_v10.py tests/test_formal_v6.py \
  tests/test_statistical_bridge_v7.py tests/test_typed_fragments_v8.py
```

Use Python 3.11+; `LAKE` may specify a non-PATH executable. The audit locates
`~/.elan/bin/lake` automatically and verifies the pinned compiler version. It
builds every module explicitly, since the frozen top-level import excludes the
additive v8 and v10 modules. The old audit entrypoints are archival and must be
run at their original revisions. The v10 command rejects output inside v1-v9.

All three executable fixtures were regenerated and match their archived bytes:
8,961 interpreter/filter records, 2,917 statistical-accounting records, and 38
typed-fragment records (these counts include headers). The correspondence tests
remain finite checks, not proofs of Python or SQLite. Lean's six unsafe compiler
specialization declarations are listed separately and none is a theorem premise.

See [the current scope and reproduction record](../docs/v10/FORMAL.md) and
[the typed compiler boundary](../docs/v8/FORMAL.md). Compiler equality does not
prove query intent; the read-only model does not prove SQLite authorization;
and conditional retention does not prove a budgeted model can recover the
ordinary answer. No theorem establishes benchmark improvement, universal
non-forgetting, or safe learning under unrestricted drift.
