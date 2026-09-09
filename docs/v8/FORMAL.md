# Typed prepared-query fragments: proof and runtime boundary

The new Lean layer proves that capturing and substituting typed parameters
preserves the exact prepared request for a witnessed query. It also proves that
structural composition produces its stated CTE expansion. It does **not** prove
that a newly composed query answers the intended question, that experience
identifies an unknown database convention, or that a passing empirical guard
prevents a first failure after drift.

This is an implementation contract for the fragment compiler. Whether learned
fragments improve future interaction cost and accuracy is a separate empirical
hypothesis. The module does not establish the larger continual-learning claim.

## Runtime representation

`src/witness_cl/fragments_v8.py` stores immutable `Text` and typed `Hole` nodes,
the exact proposed SQL, and its named bindings. In the current learner the model
may propose a **new relation** after a correct ordinary episode. A wrapper over
that relation must actually reconstruct a prior successful scalar query's answer
on the same database. This post-answer check consumes the remaining shared
SELECT allowance, and admission records its executed request and result. The
compiler cannot authenticate the evidence or judge the intended semantics; the
learner and saved-data replay enforce the recorded admission requirements.

A *compiler witness* is the captured assignment whose exact prepared request is
preserved by substitution. A *learning witness* is the successful scalar query
and the separately executed relation-plus-wrapper reconstruction. The Lean
compiler theorem does not prove equivalence between the newly proposed relation
and the original successful scalar SQL. Agreement of the two scalar results is
checked on one own database, not proved for every database or future binding.

SQL chunks may contain arbitrary supported SQLite expressions, joins, CTEs and
aggregations. The representation has no enumerated monomial feature library or
hidden task identifiers. Its normal SQL syntax and visible schema still supply
a programming language and an inductive bias. Named parameterization is supplied
in the proposed query. A new relation and a matching reconstruction witness are
evidence of a checked program proposal, not proof of a newly discovered semantic
rule or its future usefulness.

The parameter lexer preserves quoted strings and identifiers, including escaped
single quotes, double quotes, backticks and bracket identifiers. It recognizes
ASCII `:named` parameters only outside quotes. It rejects comments, statement
separators, alternate parameter styles, unterminated quotes, unsupported names,
unused bindings and missing bindings. Unicode continuation of an ASCII parameter
is rejected because SQLite would otherwise recognize a different parameter name.
This lexer is not a SQL semantic parser or authority checker.

Bindings have exact integer, real, text or null types. Booleans, nonfinite reals,
integers outside signed int64 and unsupported values are rejected. Rebinding must
preserve all names and exact types; a null hole remains null. Text is passed as a
SQLite binding, never inserted into SQL syntax. Finite float bits and signed zero
are preserved by the Python representation. The Lean transport type represents
binary64 values as exact 64-bit payloads; Python enforces their finiteness.

`compile()` reconstructs the original SQL bytes and witnessed bindings exactly.
`compose()` captures inner and outer values separately, renames only their hole
nodes into disjoint `wcl_inner_*` and `wcl_outer_*` namespaces, and emits:

```sql
WITH "alias" AS (<inner SELECT>) <outer SELECT>
```

This supports one learned inner fragment and a newly supplied outer query. It
does not implement arbitrary multi-fragment composition or prove the wrapper's
semantic intent. The alias must be an ASCII identifier and is quoted in output.
Identical original parameter names may carry different values in the two scopes.
Colons inside quoted text are never renamed.

Each stored template is limited to **32 Text/Hole nodes** and 4,096 UTF-8 SQL
bytes. These are fragment AST nodes, not SQLite expression AST nodes; a complex
parameter-free SQL expression is one `Text` node. Stored and compiled payloads
are limited to 8,192 UTF-8 JSON bytes. A composite retains the per-component node
checks and must meet the final SQL-byte and payload caps. The learner separately
enforces the 16-entry and retrieval-count budgets and charges compilation-related
retrieval/check work. Serialized records include type metadata and a SHA-256
digest; strict rebuilding checks their consistency. A digest is not evidence of
an authenticated source or a correct domain fact.

The module never opens a database or executes SQL. Every compiled request must
use the same restricted `session.query(sql, parameters)` executor as an ordinary
query. A prefix-valid `WITH ... DELETE ...` is deliberately an example of SQL
that the parameter lexer cannot authorize: SQLite's read-only boundary must
reject it. A text fragment has no operation for changing that boundary.

## Universal Lean statements

`formal/WitnessCL/TypedFragments.lean` adds 12 checked statements:

| Contract | What is established |
|---|---|
| Typed substitution | Argument substitution and fragment substitution commute with the fixed compiler under the correspondingly substituted assignment. |
| Witness preservation | Binding an observed assignment into a fragment yields exactly its original SQL request and parameter values under any later assignment. |
| Parameter separation | Changing bound values cannot change SQL text; renaming parameter nodes preserves the sequence of transported values. |
| Composition | Compilation of the fragment composition equals the explicit CTE SQL and concatenated parameter occurrences. |
| Fixed executor | Identical witnessed requests given to the same executor and database have identical results, by equality. No SQLite semantic behavior is postulated. |
| Read capability | The modeled read-only interface returns the supplied database state unchanged. Actual SQLite authorization and state preservation are runtime obligations. |
| Guard and retention | A failed or unavailable guard returns the ordinary answer. Pointwise retention follows if every accepted protected execution already produces the ordinary answer. |
| Identifiability and drift | A zero-valued observation cannot identify scale 1 versus scale 100. A still-passing empirical check can accept answer 1 after the correct answer changes to 100. |

The compiler's Lean parameter list records every occurrence. Python supplies
the equivalent deduplicated named binding map. Repeated names have consistent
types and values after Python's lexical/type checks. The finite correspondence
suite checks that boundary explicitly. Lean's substitution theorem is universal
over its fragment AST, while validation of the Python lexer, deduplication,
UTF-8 handling, SQLite parameter lookup and namespace construction is executable
testing rather than a machine-checked refinement proof of Python or SQLite.

The guard result is conditional and concerns an abstract answer-level operator,
not a refinement proof of the model-driven fallback loop. The actual agent
receives guard feedback and resumes solving with a changed prompt and reduced
SELECT allowance. Its later answer need not equal an ordinary solver's answer
without that check. The theorem supplies the ordinary answer as an argument;
it does not prove that the runtime can recover that answer under its budget.
Observed agreement does not supply the acceptance premise. If the check passes
and the candidate returns a wrong answer,
fallback is not invoked on that execution. An unchanged old policy also cannot
force the database, question interpretation or distribution to remain unchanged.

## Executable correspondence and audit

The pinned Lean 4.19.0 build checks **89 accumulated theorems**, including the
12 new statements. The audit finds no proof placeholders, custom source axioms
or unexpected dependencies. It inventories standard Lean logical axioms rather
than treating them as missing proof obligations.

`formal/FragmentFixture.lean` emits 36 cases across four query structures, three
integer values and three text values, plus a header and a guard counterexample.
The cases include repeated parameters, quoted colons, null, exact binary64 0.5,
apostrophes and SQL-shaped hostile text. Each case records original, captured,
rebound and composed requests. `tests/test_typed_fragments_v8.py` independently
compares those requests with Python and executes them on ephemeral SQLite
databases. It also checks new aggregate composition against its explicit query,
namespace collisions, malformed inputs, strict payload readback, immutability,
caps and the external read-only boundary.

This finite fixture is a correspondence check, not exhaustive verification of
every SQLite query or the complete Python runtime. The guard counterexample is
a proved limitation, not a test of model learning or a sampled benchmark result.

Reproduce from the repository root:

```sh
python3 formal/audit_v8.py --output artifacts/v8
python3 -m pytest -q tests/test_typed_fragments_v8.py tests/test_statistical_bridge_v7.py
```

The audit records source/runtime hashes, build output, an axiom inventory and
the fixture in `artifacts/v8/formal-*`. It builds the new module directly and
uses an additive audit import. **Every frozen v7 file is preserved**, including
`formal/WitnessCL.lean`, `formal/lakefile.toml`, `formal/audit.py` and the v7
artifacts. The original v7 provenance test remains exact. Run the archived v7
audit command at its frozen revision; the v8 wrapper is the audit entrypoint
for the extended module collection.

No probabilistic betting theorem is added here. The v7 statistical assumptions
and fixed-bet power limitation are unchanged. A finite weighted-mixture algebra
lemma alone would not formalize conditional sampling, the supermartingale law,
Ville's inequality or the implementation's fresh-evidence boundary; it would
add little to this stage's primary compiler contract.
