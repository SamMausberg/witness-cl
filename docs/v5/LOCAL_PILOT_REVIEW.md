# Independent review of the local model pilot

The completed runs support a local inference integration smoke test. They do
not establish native stateful benchmark superiority, a powered comparison,
equal computation, or improvement of the local language model's weights.

This review inspected `experiments/local_pilot_v5.py`, its contract tests,
the local model client, the proposal parser, and the existing controller paths.
It read the two compact completed manifests and summaries. It also executed an
isolated three-episode mock reproducer for malformed completions and empty
usage objects. It did not rerun the real model pilot or change its frozen code.
The executed runner was preserved as
`artifacts/v5/local-pilot-executed-source.py`; its SHA-256 is
`c69ec2cc12d0e9c6ae63dc0eedbb45a4fc6f0d95900aa06d430cee669c572921`.

## Recorded execution

| Run | Environments | Rows across three arms | Calls per model arm | Raw mean | Checked mean | Fixed-library checked mean |
|---|---|---:|---:|---:|---:|---:|
| Initial | Seed 41000 | 36 | 12 | 5.3333 | 5.3333 | 5.3333 |
| Exploratory extension | Seeds 41001-41004 | 144 | 48 | 3.9583 | 5.5417 | 5.0000 |

Both manifests report completion and the same source hash, model alias,
96-token limit, and 12-episode A-B-A schedule. There are 120 completed model
calls in total and zero rejected outputs in either run. The summaries report
16,925 prompt tokens and 720 completion tokens per model arm across both runs.
The third arm makes no model calls. These are reported server token counts.

Seed 41000 is action-independent for the evaluated horizon and therefore
uninformative about policy quality; its equal scores must remain in the record.
The four-seed extension is explicitly exploratory and followed inspection of
that initial result. The five environments, not the 60 episodes per arm, are the
replication units. There is no basis here for a powered superiority claim or a
claim about a native agent benchmark.

## Learner boundaries and comparison scope

The visible payload contains legal actions/observations, the horizon, the
public deterministic reset/state-bound contract, the current reward map, and
that arm's own executed action/output traces. It contains no evaluator table,
seed, counterfactual returns, or another arm's observations. Conditioning on all
past trace outputs under the new current reward map is legitimate under the
stationary dynamics/public reward contract. The model client sends that history
without client-side truncation, retries, or model substitution.

Both model arms make one call per completed episode with the same prompt schema
and frozen local model. Arm order rotates by episode, which reduces a simple
fixed-order latency bias without establishing controlled timing or equal total
compute. Checker and update times are recorded separately. The hybrid arm also
has an explicit finite-model search, admission rule, persistent candidate
library, and auxiliary online proposer updates. Its difference from raw history
is therefore the whole hybrid controller, not memory storage alone.

`checked_static` means a fixed two-program library and no language-model calls.
It still uses the default trainable `OnlineProposer`, which receives an update
after each executed episode. It is not a no-training or no-memory control.
Comparison with this arm is useful for seeing whether model-generated candidate
programs change the hybrid's behavior, but five environments cannot establish
robust model contribution.

## Confirmed edge cases in the archived executed source

1. **The rejection policy in the manifest is inaccurate for the checked arm.**
   The manifest says a malformed completion executes `0000`. The raw arm does
   execute that replacement. The checked arm skips registration and then lets
   its existing controller choose a program, which can be different. An isolated
   all-invalid mock with seed 1 produced checked actions `1111`, `0000`, `1111`
   in its three episodes. The original tests checked the parser replacement and
   rejection counts but not this executed checked-arm behavior. Future metadata
   should state the two distinct rejection policies; preserving the frozen
   execution does not require changing the algorithm.
2. **`proposal_executed` can count a rejected response as executed.** After a
   parser rejection, `candidate` is already the anchor replacement. Comparing
   this replacement with the chosen program marks invalid raw completions as
   executed proposals. The field should be false or unknown when rejection is
   non-null if used to measure valid model-proposal execution. Current summaries
   do not aggregate this field.
3. **Missing token fields can be reported as zero known usage.** An empty usage
   dictionary is accepted by the client; summary aggregation defaults its
   absent token fields to zero and increments `usage_missing` only for `None`.
   The isolated mock returned `{}` for every call and produced
   `usage_missing=0`. Missing prompt/completion fields should be counted as
   unknown individually. The completed real runs report nonzero complete token
   totals, so this mock edge case does not change their recorded totals.

These three cases have been corrected for future runs: the manifest names each
arm's rejection behavior, rejected outputs receive `proposal_executed=null`,
and empty or partial usage objects increment `usage_missing`. The corrected
runner SHA-256 is
`0646c36c5f73dd35ac961a19c2fb3c24f03dfb0bc79ccfbed9e3a7d875f5c8ca`.
All five current pilot contract tests pass, including an adversarial test that
checks both the existing-controller fallback and missing-usage accounting.
The two real pilot manifests retain the original executed hash and outputs.

All 120 completed real calls returned valid proposals and complete reported
usage, so these edge cases do not change their rewards or token totals. The review found no evidence of fabricated
model calls or evaluator-table leakage. That is a conclusion about the inspected
paths and recorded summaries, not a comprehensive runtime proof.

Model-request failures abort the run and preserve already completed rows rather
than scoring invented responses. Failed or incomplete runs would still require
separate attempted-call accounting if total operational cost were reported;
completed-episode counts alone would not include an unsuccessful final request.
The recorded pilots are complete, so that limitation is not exercised here.

## Reproducibility and interpretation limits

The runner records its own source hash and a model alias. A complete reproducible
research package also needs the repository revision, exact model/quantization
identity, server build and launch settings, and hardware context from the
separate execution records. A model alias alone does not identify weights.
This review does not certify server-side truncation settings, model identity,
latency stability, or backend inference correctness.

Neither a twelve-episode A-B-A schedule nor successful inference calls establish
long-run learning without forgetting. The formal guarantees elsewhere concern
conditional reset-value admission and ledger arithmetic. Actual language-model
quality, the realism of the finite class, scaling cost, and transferable
continual-learning progress remain separate experimental questions.
