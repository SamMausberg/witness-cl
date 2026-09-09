# Final adaptive GH200 follow-up

The initial 94000 development stream is retained in full. During its warm block,
all three arms used SQLite integer division when converting integer currency
values, losing fractional amounts. Full history subsequently received explicit
failure feedback and corrected the arithmetic on a later question. The exact
evidence shelf retained successful SQL observations but discarded failed-answer
feedback; this is a control weakness, not evidence that exact memory is worse in
general. The final follow-up makes two explicit changes, not a causal ablation.

First, both shelf arms retain every completed episode's exact submitted answer
and Boolean correctness feedback. Correct SQL execution does not imply that the
query answers the question. Valid observations from a failed episode remain
available, now accompanied by the failure signal. The active 64 KiB cap, FIFO
policy, untrusted-evidence instruction and charged admission/reuse rules remain.
Second, every arm receives the same generic SQLite instruction: integer division
truncates; use REAL arithmetic when fractions are required. This supplies no
domain query, hidden answer, target formula or future episode. It is selected
after observing a development failure and cannot serve as heldout evidence.

Use fresh development seed 94001 with the same model, decoding, source-bound
environment, initial empty memories, rotating three-arm order, eight-SELECT cap,
and 48-episode-per-arm schedule. Every arm must reach 7/8 warm accuracy before
the frozen old/new panels proceed. No learning is allowed in those panels.
There is one follow-up only: retain its result whether positive, negative or
resource-limited, and stop model task experiments afterward. Seeds 94002–94003
and the 93000-series heldout seeds are not used in this phase.

The follow-up allows at most 2,700 seconds of model-study time, 3,000,000 total
tokens and 1,400 generation attempts, with the same 2,048-token solve and
4,096-token proposal limits. Per-arm ordinary/panel caps remain 1,000,000 tokens
and 280/260 calls. Initial plus follow-up measured study time is capped at 3,600
seconds, 4,000,000 tokens and 1,800 calls; the follow-up's actual allowance is the
minimum of its cap and the remaining aggregate allowance. Setup is separate.
Unknown usage stops the study and remains unknown in the ledger.

The repaired solver instruction, source hashes, exact limits, runtime startup
receipt, initial-run manifest hash and this protocol are bound in a separate
receipt before any follow-up task call. The initial learner's source is preserved
at Git checkpoint `11be4c4e740f57607167cef4b89e0d2680222808`; use
`tools/replay_at_revision.py` for its source-bound replay after the refinement.
Do not rewrite the initial source hashes or reinterpret its rows as follow-up
observations. The new runner includes both protocol files in its source inventory.

The same falsification endpoints apply: admissions alone do not count; require
correct executed reuse under new composition or changed bindings and an offline
dependence probe on the fresh fixture. Report all costs and final feedback,
including errors. A failed competence gate leaves transfer and retention
untested. One adaptively chosen stream cannot establish a benchmark win,
population improvement, noninferiority or universal no-forgetting.
