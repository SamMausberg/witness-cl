# Non-thinking SQL qualification result

The candidate **failed** its fixed competence gate. All 32 cold episodes ran;
none was censored by token, call, wall or infrastructure limits. The
[protocol](SOLVER_QUALIFICATION.md) was independently frozen before generation.
This qualification used no cross-episode learning or memory.

| Development seed | Warm correct | Required | Composition correct | Required |
|---|---:|---:|---:|---:|
| 95100 | 3/8 | 7/8 | 0/8 | 6/8 |
| 95101 | 5/8 | 7/8 | 1/8 | 6/8 |

The complete invocation took 277.247 seconds, with 181 generation calls,
336,279 prompt tokens and 9,547 generated tokens: 345,826 known tokens total.
Unknown usage was zero. Setup and model loading are separate. All 181 native
responses ended with `finish_reason=stop`; none contained a nonempty reasoning
field. There were 147 SQL attempts, including six query errors. These are
descriptive development results; the changed seeds and cold-state protocol
prevent interpreting the difference from v10 as a controlled speed comparison.

Removing thinking eliminated the observed reasoning truncation in this run,
but the solver frequently selected the wrong formula, mishandled profile or
refund relations, or applied the wrong NULL convention. For example, seed
95100 episode 2 computed monetary gross value when asked for units. Episode 1
used `AVG(amount * quantity)` although NULL amounts were explicitly zero and
had to remain in the average; its final answer was also rounded. Independent
posthoc scoring found **no wrong final answers whose last complete scalar tool
result was correct**. Directly returning that last scalar would therefore rescue
none of these recorded failures. This diagnostic does not predict the behavior
of a newly prompted or restructured answer interface.

The offline audit reconstructed all 32 completed conversations through the
frozen executor and independently re-executed all 147 SQL attempts. It checked
the pre-call freeze, unchanged source/client configuration, exact native
request schema and decoding, cold memory state and raw-call accounting. These
checks establish reproducibility of the saved evaluation, not external
validation of the model's competence.

The [raw traces, freeze, manifest, summary and audit](../../artifacts/query_transfer/qualification/)
and [posthoc diagnostics](../../artifacts/query_transfer/qualification-diagnostics.json)
are retained. The candidate cannot support a mechanism-study claim under this
gate. Any next solver policy requires a fresh protocol and development data;
these observations remain reported.
