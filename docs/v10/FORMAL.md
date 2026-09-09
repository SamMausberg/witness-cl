# What the current Lean build establishes

On 2026-09-09 the GH200 host compiled every current module with
`leanprover/lean4:v4.19.0`: Lean 4.19.0, `aarch64-unknown-linux-gnu`, commit
`6caaee842e94`, Release. The result is **90 authored theorem statements**, of
which 89 are unchanged from v8 and one is the finite-witness limitation below.
The exact inventory and source hashes are in
[`artifacts/v10/formal-audit.json`](../../artifacts/v10/formal-audit.json).
The count measures verification scope, not mathematical novelty or impact.

The v10 audit explicitly builds all nine `WitnessCL/` modules and the frozen
top-level library, then builds both native fixture executables. The source
inventory is checked against an independent enumeration of Lean's imported
environment by each declaration's defining module. It audits **234 theorem
constants**, including generated equations and private helpers, using Lean's
`collectAxioms` operation (the operation behind `#print axioms`). All 90 authored
statements occur in that inventory; every enumerated theorem has a dependency
record. This catches proof declarations that a source regex might miss.

The proof dependencies are limited to `propext`, `Quot.sound`, and
`Classical.choice`. **27 authored statements are axiom-free.** No source
placeholder, custom logical axiom, `sorryAx`, or unexpected dependency appears.
The standard axioms are explicitly allowed, not hidden as discharged goals.
The kernel, the pinned standard library, and the integrity of the local
toolchain remain trusted. This is not an independently verified Lean compiler.

The imported environment also contains six **unsafe specialization declarations**
generated for native runtime helpers (`List.mapTR`, `List.filterTR`, `List.sum`,
and list equality). Their `AxiomVal.isUnsafe` flags and exact names are separately
inventoried. The audit accepts only the six recorded names and rejects a theorem
dependency on any of them. They are not logical premises of any checked theorem.
Reporting only a source scan would omit this distinction between the imported
environment and proof dependencies.

## Finite reconstruction and dependence still do not establish transfer

[`WitnessCL/Intervention.lean`](../../formal/WitnessCL/Intervention.lean) proves
`finite_reconstruction_and_dependence_do_not_imply_transfer`.
For every finite list of natural-number contexts W, define the intended answer
to be 1 everywhere. A candidate returns 1 when its relation is present and the
context belongs to W, returns 2 when its relation is present elsewhere, and
returns 0 when the relation is emptied. Choose the fresh context as
`1 + sum(W)`, which exceeds every member of W. The theorem establishes:

- The fresh context is absent from every finite witness list, including the
  empty list and lists with duplicates.
- At every witness, the candidate gives the correct answer 1 and the
  empty-relation intervention changes that answer to 0.
- At the fresh context the candidate gives the wrong answer 2, and emptying
  the relation still changes its answer to 0.

The constructive proof uses a list-sum bound and evaluation of the stated
function. It requires no probabilistic assumptions. This is an elementary
finite-data obstruction, not a novel generalization lower bound or evidence
that the deployed model will produce this specific candidate. It concerns
unrestricted candidate functions over an infinite context domain; a restricted
class, complete finite domain coverage, or distributional assumptions can change
the conclusion.

`tests/test_formal_v10.py` instantiates the same pattern with actual SQLite SQL
and the existing typed fragment compiler: the relation contains a CASE expression
and the wrapper really aggregates its rows. Four finite witness sets pass
reconstruction and empty-relation dependence checks but fail on the constructed
fresh context. These are executable examples of the limitation, not a Lean
refinement proof of the SQL implementation or measured model failures.

The practical implication is narrow. Empty-relation probes can reject the
observed unused-CTE failure. Passing that probe does not justify a claim of
generalization, abstraction quality, causal necessity in every context, or
retention. Fresh-data evaluation, counterfactual bindings, task controls, and
cost-matched baselines remain necessary empirical tests.

## Existing contracts and their unresolved boundary

| Established in Lean | What remains outside the proof |
|---|---|
| Truth retention under consistent filtering, reset execution, and an initially included true machine | Real feedback integrity, stationarity, reset reliability, and Python implementation refinement |
| Accounting for finite-population returns and accepted promotion chains | Conditional sampling, fresh-evidence enforcement, the supermartingale property, Ville's inequality, and statistical power |
| Typed substitution, captured-request equality, value/text separation, and exact CTE expansion | Python lexical parsing, namespace freshness, named-parameter deduplication, Unicode handling, and SQLite operational semantics |
| State preservation by an explicitly read-only mathematical interface | Runtime SQLite authorization, virtual tables, transaction behavior, and process isolation |
| Pointwise retention if every accepted candidate already agrees with the ordinary answer | Establishing that premise from finite observations, and recovering the ordinary answer after spending runtime budget on a guard |
| Finite reconstruction and relation dependence do not imply transfer | The frequency of such errors in a trained model and the effectiveness of further admission tests |

In particular, identical requests have identical results only under the same
fixed executor function and database. An unchanged policy or stored request
does not make a changing environment stationary. The runtime fallback may
receive a changed prompt and less query budget than the ordinary solver; the
abstract guard theorem assumes the ordinary answer is already available.
The detailed compiler/runtime distinction remains in
[`docs/v8/FORMAL.md`](../v8/FORMAL.md).

## Reproduction and preserved evidence

From the repository root, with Python 3.11+ and the pinned Lean toolchain:

```sh
python3 formal/audit_v10.py --output artifacts/v10
python3 -m pytest -q tests/test_formal_v10.py tests/test_formal_v6.py \
  tests/test_statistical_bridge_v7.py tests/test_typed_fragments_v8.py
```

The audit finds `lake` on PATH or under `~/.elan/bin`; `LAKE` can override it.
It verifies Lean's version, records all source/build hashes and build output,
emits its exact kernel-audit source, and regenerates all three fixture families.
Output paths resolving inside `artifacts/v1` through `artifacts/v9`, including
symlink aliases, are rejected. Previous Lean modules, fixtures, top-level
imports, Lake configuration, audits, and archived evidence remain byte-for-byte
unchanged. The frozen import intentionally omits additive modules, so a bare
`lake build WitnessCL` is insufficient to reproduce the current audit.

| Fresh output | Records, including headers | Archived reference | Result |
|---|---:|---|---|
| `formal-runtime.jsonl` | 8,961 | v6 interpreter/filter fixture | Exact byte match |
| `formal-statistical.jsonl` | 2,917 | v7 accounting fixture | Exact byte match |
| `formal-fragments.jsonl` | 38 | v8 request/guard fixture | Exact byte match |

The selected correspondence and audit suite passes **89 tests**. It checks the
fresh receipt against current sources, archived fixtures against their frozen
sources, and malformed audit records against the failure conditions. The
interpreter fixture covers 7,936 traces, 7,680 nonempty word programs and 262,144
filter decisions. The fragment fixture has 36 request cases plus a header and
guard counterexample. These exhaustive finite subdomains and sampled SQL
examples do not close the Python/SQLite refinement gap.
