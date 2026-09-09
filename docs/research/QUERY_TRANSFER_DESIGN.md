# Source-derived computation memory: research design in progress

This is a new research phase authorized by the user's review on 9 September
2026. The completed v10 development evidence is preserved at Git checkpoint
`38d7597`; its exhausted protocol is closed. This document is a design, not a
pre-run freeze, positive result, or authorization to reinterpret those pilots.
The manuscript remains a draft until the mechanism has useful evidence.

## Single question

When an agent derives a reusable relational computation from its own successful
SQL, does executing that computation improve later correctness or deployment
cost beyond retrieving **the identical derived SQL as text**?

The previous study leaves this unanswered. Five admitted relations had no later
execution through the intended interface. Old numeric guards rejected programs
when fresh rows changed the old answer. Raw-history and evidence agents also
repeated stale numeric answers. A second warning is weak: the evidence prompt
already said that numeric results concerned old rows. Long hidden reasoning
also exhausted generation limits before producing actions; solver competence
and time accounting require a separate check.

## Candidate mechanism

Deterministically factor supported successful scalar aggregate SQL into a
standalone row relation and its original outer computation. Preserve its joins,
predicates, expressions, NULL behavior and fixed numeric semantic constants.
Unsupported syntax causes an explicit abstention. Captured string comparison
literals can form typed bindings; this does not authorize dropping a predicate
or calling every new binding semantically valid. Actual reconstruction is
charged against the source episode's remaining SELECT allowance.

The new outer program is a bounded structured relational AST. Host code emits
all table references from selected immutable view IDs, not arbitrary model SQL.
This avoids the observed CTE-shadowing bypass. It does not prove the learned
view's intended meaning or force the new answer to use its derived columns.
The compiler is an engineering contract; ordinary query factoring and SQL
capability boundaries are not claimed as novel mathematical ideas.

The first mechanism study will use independent fixed-schema, fixed-convention
streams. Every arm is explicitly told that contract; rows change each episode.
Checking unchanged schema is local, and an old numeric answer is never a guard.
Undocumented semantic drift is outside this contract. A later drift experiment
must charge current metadata checks or provide the same public contract stamp
to every arm; it cannot silently give only the program arm a trusted oracle.

All arms must answer from a current SQL execution using the same host-resolved
interface. This removes direct stale-number submission as a confound. It does
not establish query relevance: a current query can still return a copied
constant. No backbone training or offline retraining is proposed here.

## Controls and attribution

The planned controls are full history, a SQL-only archive retaining exact query
text and feedback without old numeric output rows, the same derived views as
text, and compiled views. The last two must receive the same view SQL, binding
schema, column information and acquisition observations. Code generation and
checking costs must be charged to both. An execution advantage cannot be
attributed to extra refactoring information withheld from the text control.

A common legally obtained source prefix can be forked into the memory arms to
isolate acquisition quality. If used, its complete deployment cost is charged
to every counterfactual arm while actual physical expenditure is also reported.
This causal design is distinct from four independent end-to-end deployments.
The final protocol must choose and state the design before new outcome data.

## Falsification and important counterexamples

The primary mechanism event requires a correct answer on fresh data, a changed
binding or a genuinely different outer operation, and a contribution from a
learned computation. Emptying a view alone is insufficient: SELECT-* followed
by complete recomputation can pass that test. Replace derived measure columns
with zero or NULL while preserving the raw columns and rows, then check whether
the fixed outer computation and host-resolved answer change. Report this
execution-path intervention separately from a full agent rerun without memory.

Source correctness is weaker than representation correctness even without
finite-sample error. SUM(x) and SUM(COALESCE(x,0)) can agree while their induced
AVG computations differ. COUNT(DISTINCT customer) can hide duplicate historical
profiles that cause a later join to multiply orders. New AVG and JOIN questions
must expose these cases. A constrained program can also return a memorized
constant conditional on nonemptiness and pass an empty-view intervention.

Reject a useful execution claim if compiled views do not improve over the
identical-view text control at stated accuracy and full cost, if derived-column
interventions reveal raw-column recomputation, or if supported extraction and
later use are too rare. A recurring negative mechanism across independent
streams is a valid outcome. No admission count or elementary theorem count can
substitute for that result.

## Required experimental discipline

First qualify the fixed backbone separately on warm and composition questions.
Freeze implementation, interface, model revision, decoding, source extraction,
retrieval, memory policy, seeds, task distribution and resource limits before
the mechanism study. Preserve every seed and failure. Reserve time and tokens
for old-before, old-after and final panels before spending on online updates;
complete schedules are needed for retention comparisons. Repeated episode rows
are not independent replications. A small multi-stream study is not sufficient
for a two-percentage-point lifetime no-forgetting claim.
