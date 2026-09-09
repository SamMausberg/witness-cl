# v9 mechanism review

The final warm run admitted two SQL memories: one dependent scalar-count witness
and one witness whose outer query ignored the proposed relation. Neither memory
was used on a later task. No composition, rebinding, retention, or interaction
saving was demonstrated. The three invocations below remain separate evidence.

## Finalized invocation: prospective-92001

This independent read-only review covers the saved invocation in
`artifacts/v9/prospective-92001`, whose manifest finalized as `failed` after
22.557856418 seconds and two episode records. It does not pool later experiments
or treat the intended 144-episode schedule as completed. The raw file hashes
match the finalized manifest. No model calls, learner reruns, counterfactual SQL
executions, held-out tasks, or frozen-source changes were made for this first-invocation review.

**No executable abstraction was proposed, admitted, or tested in this invocation.**
The run stopped during the first insight reflection, before the first fragment
arm episode. It supplies no evidence for or against future abstraction transfer,
changed bindings, new outer compositions, retention, or interaction savings.

## What actually happened

| Saved record | Observed execution | Final state |
|---|---|---|
| `92001-reuse-full_history.jsonl`, line 1; ordinary episode 0 | Paid catalog read, then direct aggregate SQL; returned and answered 9097.5, with correct feedback | `completed`; one own episode retained |
| `92001-reuse-insights.jsonl`, line 1; ordinary episode 0 | The same two paid queries and correct answer | `backend_or_runtime_failure` during reflection; no insight update retained |

Both arms executed the following second query against the current rows:

```sql
SELECT SUM(c_rxifxj * c_ycybrt / 100.0) FROM r_efkxvj
```

This is a nonzero result obtained through the real tool interface, with quantity
multiplication and monetary conversion. It is ordinary direct SQL rather than
learned executable reuse. There is no relation entry or entry digest to attribute
the answer to. A single correct total also does not establish correctness for
averages, missing-value conventions, joins, or subsequent tasks.

The insight reflection's recorded generation attempt failed with
`HTTP Error 400: Bad Request`. Its usage is unavailable. The six successful
solve calls have reported usage; the manifest records seven generation attempts,
8,956 known tokens, and one call with unknown usage. Therefore 8,956 is not a
verified complete token total. The reflection failure did not invalidate the
already delivered correct answer, but it prevented the memory update and ended
the run. Neither the warm competence gate nor any evaluation panel completed.

## Mechanism evidence

| Required evidence | Observed |
|---|---:|
| Fragment-arm episode records | 0 |
| Model-generated relation proposals | 0 |
| Accepted reconstruction witnesses | 0 |
| Learned relation entries | 0 |
| `USE` or `COMPOSE` actions | 0 |
| Applicability guard executions | 0 |
| Changed bindings tested | 0 |
| New outer compositions tested | 0 |
| Answers depending on a learned relation | 0 |

There are consequently no accepted constant-answer or unused-CTE traps to
classify. Their absence from an unstarted fragment arm is not evidence that the
admission method prevents them. Finite reconstruction witnesses would still
require inspection of later dependence, binding changes, and fresh compositions
before being described as useful abstraction learning.

## Exact evidence identifiers

SQL hashes are SHA-256 of the recorded SQL's UTF-8 bytes, without normalization.

| Item | SHA-256 |
|---|---|
| `SELECT * FROM catalog`, attempt 1 in both records | `7b0d6be00f32e7caca5678087bcfab1bd36e5138e398900f50335a03c9a909ef` |
| Direct aggregate above, attempt 2 in both records | `faf353c428ac215da56f7c11b64561b8ddf374271ed7a4ac79462d7e378b45b6` |
| Full-history raw file | `750cf0ae75aff5b2c0e428a8bc7607522d67a312d76a17db4fec85ce0c8346b3` |
| Insight raw file | `59db688b76a935667ca21ffa2155755932c6c8ce7ce396e5216ef758ac27b7f5` |

The full-history snapshot contains one history episode and one observation event;
the insight snapshot contains no insights or observation events because its
reflection failed before `finish`. Both snapshots have zero executable entries.
The finalized manifest reports unchanged frozen sources and client configuration,
incomplete required records/resources, unverified total usage, and
`warm_qualified: false`. These are execution-status facts, not a failed accuracy
comparison between the methods.

## Finalized follow-up: prospective-json-92002

This separate invocation used fresh development seed 92002 and the existing
JSON-object response mode for all arms and calls, with the strict host validators
unchanged. Its manifest finalized as `failed` after 311.410566230 seconds and
seven records: two full-history, two insight, and three fragment episodes. The
fragment arm's third episode read the catalog, then its next solve call timed
out. The later `PORTABLE_PROTOCOL.md` records that the coordinator
intentionally stopped this invocation after seeing malformed text-memory updates;
the pending request timed out during owned-server shutdown. Its preflight reported 1,476 input tokens and reserved at most 2,048 output
tokens; actual usage is unavailable. The manifest reports 40,721 known tokens,
23 generation attempts, and one unknown-usage call. The warm gate and all
retention/composition panels remain incomplete.

There are **two rejected relation proposals, one charged unsuccessful
reconstruction, and zero accepted entries**. No `USE`, `COMPOSE`, applicability
check, changed binding, or new outer composition ran. Every fragment snapshot
has an empty entry library. Both completed fragment answers were obtained using
ordinary SQL and cannot be attributed to executable memory.

### Proposal 1: incorrect relation scope and binding semantics

Evidence: `92002-reuse-fragments.jsonl`, line 1, ordinary episode 0. The source
query returned the correct gross total 9819.25. The proposal selected source
query index 1 and catalog guard index 0 (both indexes are zero-based):

```sql
WITH order_values AS (
  SELECT c_kwtpdn * c_qtzyyx AS gross_value
  FROM r_wbtckz
  WHERE c_whiirk = :order_status
)
SELECT SUM(gross_value) AS total_gross_order_value FROM order_values
```

Its witness parameter was `{"order_status":null}` and its outer query was:

```sql
SELECT SUM(gross_value) AS total_gross_order_value FROM order_values
```

The host exposes the proposed relation under `reused`. `order_values` is local
to the proposed inner SQL and is unavailable to this outer query. The actual
third SELECT was the post-answer reconstruction and returned
`no such table: order_values`; admission was rejected. This is an observed
execution failure, not a hypothetical counterexample, and its SELECT cost is
already part of the learner trace.

Static inspection also finds that the proposed relation has already collapsed
the order rows into a single aggregate and does not expose `gross_value` under
that name. In addition, equality against the supplied SQL NULL binding cannot
select matching rows. Under the fixed exact-type fragment compiler, a hole
learned from a NULL witness accepts NULL again; it cannot subsequently take a
text status such as `confirmed`. This proposal therefore supplies no useful
changed-binding evidence. None of these observations was used to repair or
rescore the recorded attempt.

### Proposal 2: row factorization proposed, outer relation unused

Evidence: `92002-reuse-fragments.jsonl`, line 2, ordinary episode 1. The ordinary
query `AVG(COALESCE(c_kwtpdn, 0) * c_qtzyyx)` returned the correct value 287.3125.
The reflection proposed a structurally different per-order relation:

```sql
SELECT c_criepb AS order_id,
       COALESCE(c_kwtpdn, 0) * c_qtzyyx AS gross_value
FROM r_wbtckz
```

The description identifies per-order gross values and missing-value handling.
This is evidence that the model proposed a row-level factorization of its own
successful scalar query. Both parameter objects are empty, so it provides no
literal holes to rebind.

The actual reflection is enclosed in a Markdown JSON fence. The strict proposal
JSON parser rejects it with `Expecting value: line 1 column 1 (char 0)` before a
reconstruction SELECT. For inspection only, this review read the JSON inside
the fence; it did not change the trace, run a corrected proposal, or admit it.
The proposed outer SQL begins:

```sql
WITH gross_orders AS (
  SELECT c_criepb AS order_id,
         COALESCE(c_kwtpdn, 0) * c_qtzyyx AS gross_value
  FROM r_wbtckz
)
SELECT AVG(gross_value) AS average_gross_order_value FROM gross_orders
```

It repeats the physical-table computation and never references `reused`.
Consequently the proposed outer computation does not depend on the learned
relation. It also begins with `WITH`, whereas the fixed composition interface
requires its outer statement to begin with `SELECT`. These are static defects
in a rejected proposal; no passing unused-CTE witness occurred in this run.

### Evidence limits and exact identifiers

The two proposal SQL strings are structurally different from the previously
executed ordinary SQL. Neither became a reusable executable entry. This
invocation demonstrates attempts at synthesis and a host rejection of an invalid
reconstruction. It does not demonstrate successful abstraction learning,
relation-dependent answers, rebinding, novel composition, or reduced interaction.
There is no entry digest or successful guard outcome to report. No independent
counterfactual SQL was necessary or executed for this second invocation.

Hashes below refer to exact recorded UTF-8 strings. Proposal 2's SQL fields are
identified by auditor-only inspection of the fenced response; its complete
reflection hash preserves that fence.

| Evidence | SHA-256 |
|---|---|
| Proposal 1 complete reflection | `51ad9cdf4e57ad4d8de3d92f6368d3a2af1fe6395756b676dbc9cdd777cab480` |
| Proposal 1 relation SQL | `67c4e1c445258595c027a145578da75a13b0e6b0af1d173e4cf994774f569004` |
| Proposal 1 outer SQL | `e328419f0cbc3dbfe72f1d6f451aff119f72fea50b0bc3421b4f94fcaed0d509` |
| Proposal 1 charged reconstruction SQL | `c713050c7f3037fa498aa6d8d2ceaed8b343ea7b226ba5edf11d972ef346537e` |
| Proposal 2 complete fenced reflection | `312ba859c0eae843f63c76e1c169898f3d75519558b63bb7ecb7849781ea8858` |
| Proposal 2 relation SQL | `5e3857c893e21fa0071cf0cc2a8d18ecdd1a2d72b8078d478ebe7bf64179223b` |
| Proposal 2 outer SQL | `0e4cfe556089061a66ab2e6eefdcf8c40359f066f5ddd23ff747d7f2461ad7ef` |
| Fragment raw file | `2895b39b2cd5884da2740ff13ee99b551acdb1c92d3220bde2ac6fc30edd3016` |
| Full-history raw file | `9451388f37e6a81af1d5210f25228466de1fc37948bced62a4b350421cd64103` |
| Insight raw file | `55e89c4ce28f38908cbedb05ab692f6780faed079df33cbf634bf819ed9fc69b` |

All three raw hashes match this invocation's finalized manifest. Its source and
client configuration checks report unchanged; incomplete records and unknown
usage prevent treating this as a completed comparison. The two invocations
above remain separate evidence records.

## Final attempt: prospective-portable-92003

The final manifest is `competence_gate_failed`, with 24 completed warm records
and no later phases. Full history scored 8/8, evolving text context 6/8, and
fragments 7/8. The protocol required every arm to score at least 7/8 before
continuing. Therefore the stop was the specified competence decision, with no
old-before, old-after, or final-composition evaluation. Source/client checks are
unchanged and resource accounting is complete for this invocation: 78 generation
calls, 155,686 tokens, and 401.027218141 seconds. These are development results
on one warm stream, not a population comparison.

| Final warm arm | Correct | SELECT attempts, including learning checks |
|---|---:|---:|
| Full history | 8/8 | 9 |
| Evolving text context | 6/8 | 14 |
| Checked executable memories | 7/8 | 22 |

The fragment learner made seven proposal calls, one after each correct answer.
Five proposals were rejected and two were admitted after finite reconstruction.
Six paid reconstruction SELECTs ran: four failed and two matched their source
answers. The invalid guard index below was rejected before SQL execution. No
`USE`, `COMPOSE`, later applicability guard, or changed binding executed.

| Fragment raw line / ordinary index | Recorded proposal outcome | Mechanism interpretation |
|---|---|---|
| 1 / 0 | Reconstruction: `no such table: calculation_result` | Scalar gross query plus alias and `WHERE 1=1`; superficial text change, wrong outer relation name |
| 2 / 1 | Incorrect ordinary answer; no proposal | No synthesis evidence |
| 3 / 2 | Reconstruction: `no such table: reusable_cte` | Text status hole could express a filter, but the outer uses the wrong relation name |
| 4 / 3 | Unobserved guard index 2, with only indexes 0–1 available | Provenance rejection; proposed query also drops the North filter and uses an unexposed outer column |
| 5 / 4 | Reconstruction returned NULL | Region parameter includes literal quote characters: `"'North'"`; it matches no North rows |
| 6 / 5 | Reconstruction returned NULL | Refund identifier equality is bound to NULL; the typed NULL hole cannot later take an integer identifier |
| 7 / 6 | Accepted; reconstructed 22 | A scalar count actually used by the outer, with an all-or-nothing parameter |
| 8 / 7 | Accepted; reconstructed 1350.25 | The outer independently recomputes the answer and ignores the learned CTE |

### Accepted entry A: dependent scalar count, limited abstraction

Source: fragment raw line 7, ordinary index 6; source query index 1; catalog guard
index 0; verification query index 2. Stored fragment digest:
`c289afb85c7e005f5ce63fa8211924cd11046db7b9aa95c3e505d4b2b06d58fb`.

```sql
SELECT COUNT(DISTINCT o.c_qxunbx) AS distinct_refunded_orders
FROM r_pvmdrq o
INNER JOIN r_ayzuqt ref ON o.c_qxunbx = ref.c_ijepqu
WHERE :has_refunds IS TRUE
```

Its integer witness is `{"has_refunds":1}`. The outer is:

```sql
SELECT SUM(distinct_refunded_orders) AS total FROM reused
```

The model has wrapped its previous count with an alias and an integer truth
predicate. The relation returns one count, not refunded-order IDs as its
description suggests. The predicate contains no row field: zero disables all
joined rows, while nonzero integers preserve all joined rows. It is not a
parameterized refund threshold or a choice between refunded and unrefunded
orders. No learner binding change was tested.

The observed reconstruction does depend on the scalar relation. The separate
offline audit below confirms that changing or emptying its output changes the
outer answer. This is stronger than a witness with an unused CTE, but it remains
a single scalar-query template and does not expose the rows or join keys needed
to demonstrate the proposed later compositions.

The fixed generator also creates 32 orders, with `order_id % 3` refund records
for each; exactly 22 orders therefore have refunds regardless of the sampled
refund amounts. This follows from `sql_env_v8.py` lines 444–458, not an additional
learner evaluation. The query still reads data; its answer's invariance within
this generator makes a repeated 22 on fresh sampled rows a weak generalization
check.

### Accepted entry B: witness does not depend on the learned relation

Source: fragment raw line 8, ordinary index 7; source query index 1; catalog guard
index 0; verification query index 2. Stored fragment digest:
`2f5ad9a3f25b485d0b3945e08a62ab4627af688ace2f5efc89bf9f9183c2ee4c`.

The stored SQL groups Gold-tier order values, then immediately sums them into a
single `total_gross` scalar. Its text witness is `{"tier":"Gold"}`. The
reconstruction's outer query separately reads the orders and profiles tables,
repeats the Gold calculation, and never names `reused`. Its separate outer
`tier` binding is also `Gold`.

Thus the matching 1350.25 does not test the learned relation's result. It is an
actual accepted unused-CTE witness, even though both inner and outer contain
plausible SQL. The stored relation's description promises per-order values and
flexible outer aggregation, but the stored output has already collapsed those
rows. Its tier hole represents a meaningful filter in the SQL; no actual learner
rebinding or later use occurred.

A separate offline standalone execution of the stored SQL does return 1350.25
on this same training fixture. The evidence therefore does **not** establish
that the stored SQL is invalid. It establishes that the paid admission witness
was independent of it and could not establish the claimed relation correctness
or generalization.

### Offline dependence probes: audit evidence only

`experiments/audit_mechanism_v9.py` constructs a new private in-memory database
for each of 11 bounded SQL probes using only already observed development seed
92003, ordinary cases 6 and 7. It shares the frozen data generator and fragment
compiler, but executes through an independent read-only SQLite connection with
its own narrow authorizer. It makes no model call, supplies no learner feedback,
alters no saved memory or answer, and adds no learner SELECT charge. These are
causal inspection probes of the saved training programs, not transfer or
retention tests. The canonical receipt is
`artifacts/v9/mechanism-counterfactuals.json`.

| Offline probe | Entry A outer result | Entry B outer result |
|---|---:|---:|
| Replay saved reconstruction | 22 | 1350.25 |
| Replace `reused` with an empty relation | NULL | 1350.25 |
| Replace `reused` with a scalar sentinel −777 | −777 | 1350.25 |
| Remove the learned CTE entirely | Not needed | 1350.25 |
| Change only inner binding | `has_refunds=0`: 0; `has_refunds=2`: 22 | `tier=Silver`, outer still Gold: 1350.25 |
| Execute stored relation alone on original witness | Not needed | 1350.25 |

The first entry was retrieved into the next episode's prefix, but that episode
used ordinary SQL rather than `USE` or `COMPOSE`. The second entry was admitted
after the final warm answer and received no subsequent question. Absence of
reuse here is an absence of demonstrated transfer; the stopped run did not
exercise the intended fresh composition or retention schedule.


### Evolving-text failures: observed omissions, without causal attribution

In `92003-reuse-insights.jsonl`, raw line 2 (ordinary index 1), the first
solve prompt retained the preceding total-gross SQL, units and quantity
meaning, but omitted the catalog's instruction that NULL unit amounts mean
zero and must remain in monetary averages. The original paid catalog response
at raw line 1 explicitly contains that convention. The executed SQL was
`SELECT AVG(c_wizede * c_rpfuqr / 100.0) AS avg_gross_value FROM r_pvmdrq`;
it omitted `COALESCE` on unit amounts and returned the incorrect
280.2857142857143. No catalog reread occurred in this episode. The reflection
after this failure speculated about several definitions while still failing
to recover the observed NULL rule.

At raw line 5 (ordinary index 4), the first solve prompt retained six notes
about the immediately preceding North-region customer count. It no longer
contained the earlier unit conversion, quantity rule or exact order/customer
key mapping. The executed query joined profile customer reference
`r_taimnx.c_pydjtz` to order identifier `r_pvmdrq.c_qxunbx`; the catalog instead
identifies `r_pvmdrq.c_vwqjnv` as the matching order customer reference. It also
summed raw `c_wizede` values without multiplying quantity or converting cents
to dollars, producing the incorrect 50975. Again, no catalog reread occurred.

These are concrete omissions and SQL errors in this evolving-memory
implementation. They do not establish that compression alone caused the
errors: the solver could have re-read documentation, and no intervention
restored those notes under otherwise matched conditions. The comparison
therefore motivates a stronger qualified text control while preserving the
recorded 6/8 result.

### Final-attempt evidence identifiers

All hashes below are SHA-256. SQL hashes use exact recorded UTF-8 text.

| Fragment raw line / index | Proposed relation SQL hash |
|---|---|
| 1 / 0 | `7e23d641ee04d8b768b814454b28aaa5b520e39fc654ec647b6f936deed29dc4` |
| 3 / 2 | `fc9f60a7b7670c88441360e641693f7b9dcd8bde2f733a366239fa8ca950f538` |
| 4 / 3 | `aadae1809eb85ec291057aebf415677587558c64780fb3b7cd02d6391dd198c8` |
| 5 / 4 | `55ad7b1440ccbca20b10d0757ed4ad4c7c4054a1edcc4bdeb3018b77d036390c` |
| 6 / 5 | `acbfeef5e3d3a01608fdfcdbab98b8c40a8aff3785c1db460679c9307e4019b0` |
| 7 / 6, entry A | `fa77ed55980e9a8ae2f823ba9ab7ec050ffebaead5f47cfe4bec6f90493cbb9f` |
| 8 / 7, entry B | `c7dc51711ac0b93b81a9ac1dad548ccbb108ca6bfe7154496ba4b3494c63771c` |

| Additional evidence | SHA-256 |
|---|---|
| Entry A outer SQL | `b9ffe27364f8d0d4126d38814311adeeccad54879aa30d641a877cd9cda980e7` |
| Entry A provenance | `1e5537894571dc33272e8b6411a42aa156e5e7c6f01fcc2e7e86f7f98e6eec78` |
| Entry B outer SQL | `de9c08ef6fb10aa8dae925b963e2319288bd33b54a8f00c67058178f226830e1` |
| Entry B provenance | `bf5cd0f973853f74b51afbbe1b32a537d510ba991aa72db4c048b0366535b578` |
| Fragment raw file | `5bee415eb4354963e8d929dc26efd74d0294e71f41fe61d858ddee8c42891e9f` |
| Full-history raw file | `251ba6dda1f36ce257b1f3adf065f4b37234a8153cb4c1e0442bfe563d974b60` |
| Insight raw file | `fef41c1ee513741bbd1d3e1273617c8610e14eac6586ea3fab3366f6118d7572` |
| Canonical offline audit source | `7a1b0e2eae85546564753ece391239dc942ff1219be69b5e8c35010c357dd5ea` |
| Canonical offline audit receipt | `5946fc28fc0861a887ba5c3e48d38792188adaaec8368e773a428880c0fa9739` |

All final raw hashes match the finalized manifest, and the offline receipt's
source/raw hashes match their files. The final run provides two finite
admissions, including one witness with no dependence on its proposed relation.
It does not demonstrate useful executable-abstraction reuse on a new task,
changed-binding transfer, a new outer composition, preservation of old behavior,
or an interaction reduction against the controls. Those claims remain open.
