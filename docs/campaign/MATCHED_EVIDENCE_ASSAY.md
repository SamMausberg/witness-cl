# Matched-evidence causal assay

This separate diagnostic fixes four development streams and 64 later diagnostic
streams before generation. Reserved stream seeds are 102000–102003 for
development and 300000–300063 for the later diagnostic, separate from the main
campaign's registry. It uses only the new `campaign_env` diagnostic generator;
no historical fixture, benchmark answer, or reference SQL enters a learner prompt.

Each stream has one full-history donor. It solves 24 ordinary episodes, observes
terminal correctness, and runs the existing deterministic reconstruction and
empty-relation checks in the **same live session**, within the original eight
SELECT allowance. The donor never receives an executable relation. Every direct
query and every check, including its bindings and exact numeric result, is
explicitly exposed to the donor and retained in the common evidence prefix.

At checkpoints 8, 16, and 24, four frozen forks solve eight probes each:

- `sql_archive_extra_evidence`: all exact direct SQL, observations, and feedback.
- `view_text`: that same prefix and the eligible derived relation SQL as text.
- `immediate`: that same prefix and executable provisional or corroborated views.
- `delayed`: that same prefix and executable corroborated views.

The text and delayed view payloads are byte-identical. All forks receive the same
observed source statements and every extra direct check observation; merely
assigning the checks' costs to a control is insufficient. No fork updates memory.
There is no silent evidence truncation: the frozen context limit remains a hard
resource limit and a failure is retained. The normal registry count and retrieval
byte bounds apply to donor acquisition.

The three probe blocks are fresh-row final blocks 0, 1, and 2 under the same
stream schema and conventions. They use the diagnostic generator's min, max,
and range outer operations. Their fixture hashes and order are fixed at freeze.
Model randomness is paired across fork arms, and fixed rotation balances their
execution order. Probe results never affect future donor queries or memory.

Each logical fork pays the complete donor prefix plus its own probe calls and
SELECTs. Physical accounting records the donor once. Checkpoint logical costs
overlap and must not be summed as though they were separate physical runs.
The primary full-campaign accuracy, token-saving, and noninferiority claims are
not established by this assay.

`tools/campaign_assay.py` provides `freeze`, `run`, `resume`, `audit`, and `report`.
The exact source snapshot, fixture hashes, client settings and runtime receipt
are fixed before generation. Per-call pending journals precede requests. Only
fully recorded successful responses can reconstruct an interrupted episode;
unknown, pending, and failed invocations are retained without automatic retry.
Offline audit reconstructs every donor and immutable fork from recorded calls,
checks the memory and evidence chains, and re-executes every SQL statement.
Real generation must run the immutable `sources/tools/campaign_assay.py` copied
inside its study output, with `--out` pointing to that output.

## Agent relation-deletion diagnostic

`deletion-freeze --source-study PATH --out NEW_PATH` requires a complete primary
campaign with an offline replay audit bound to all its current records and call
journals. It selects **every** structural mechanism event using
`prepare_deletion_cases`, not only the five examples used for exposition. Its
complete case list, source-study hashes, original correct answers, memories and
paired sampling seeds are frozen before any ablation response is observed.

`deletion-run` and `deletion-resume` rerun each original episode with only the
target registry relation removed. All original direct SQL evidence remains;
rewriting that SQL and staying correct is an informative negative ablation.
The generator, fresh-row snapshot, nonce, decoding and sampling seed match the
original episode. Learning is disabled, and no ablation feedback reaches the
source campaign. Unknown or failed invocations prevent automatic retry.

`deletion-audit` replays every completed rerun without model calls. Reports show
answer flips, correctness despite deletion, failures and all additional physical
inference costs, alongside the original campaign's acquisition/evaluation cost.
This is a conditional causal diagnostic on the frozen event census, not an
independent-stream population estimate. Scripted software cases remain marked.
