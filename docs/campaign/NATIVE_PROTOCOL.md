# Frozen native DatabaseExploration evaluation

This protocol evaluates the original CL-Bench DatabaseExploration default
schedule using its pinned implementation at
`5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26`. The scheduled experiment has five
permutations, `run_index=0..4`, using the benchmark's own permutation constructor
and seed 42. Each permutation contains the original 20 pre-migration questions
and original 20 post-migration questions. No question, answer, database,
migration behavior or reward computation is selected or changed based on model
outputs.

Each permutation runs four initially empty arms: upstream full-history ICL,
official ACE adapted to the common observable interface, stateful delayed
Witness, and the same Witness reset after every question. The execution order
rotates these four arms by permutation index. All 20 run identities, ordered
question IDs, code, configuration and dataset hashes must be frozen before the
first model generation. The runtime model/backbone/decoding come from the same
frozen campaign runtime configuration used by the main experiment.

The native question budget is unchanged at 15 QUERY actions. Correct answers
receive reward `1 - exploratory_queries / 15`; incorrect answers receive zero.
Native SQL retains its 10-second execution limit and 50-row display cap. The
pinned in-process native runner, also used by upstream `run_single`, does not
invoke the task's separate response-timeout helper hooks. This implementation
preserves that behavior. Its local HTTP request timeout is 180 seconds and
transport failures produce incomplete runs, never replacement reward scores.

Each model call has a 4,096-token output allowance, the frozen 65,536-token
context, and exact input/output token accounting. Each complete native run has
a ceiling of 2,000 model calls and 150 million total model tokens, with no
wall-clock deadline. The upstream ICL control retains its original FIFO context
policy and token calibration with a 5,120-token reserve. Truncation statistics
are reported in its native artifacts. Native ACE and Witness use the documented
65,536-byte persistent-memory budgets; their distinct learning operations are
fully charged. See `ACE_NATIVE.md` for adaptation details.

Native Witness receives no database handle or reference answer. Reconstruction
and deletion checks run as ordinary QUERY actions before a frozen pending
ANSWER; only subsequent delivered CORRECT feedback commits learning. Insufficient
remaining query slots skip admission. A changed-binding corroboration must occur
in a later episode; execution eligibility begins in a subsequent episode.
Public migration notices change eligibility scope. These native observations
provide empirical corroboration; native exact certification stays UNKNOWN.

## Dataset and model preparation

`tools/native_campaign.py fetch` fetches both official database assets outside
the repository at dataset revision
`a0cc57eeb9a54f01c0490a1b46cb705b4e05aa19`. Their expected lengths and SHA-256
hashes are constants in the runner. Existing mismatched files are not overwritten.
Freeze connects those verified assets to the upstream checkout's ignored data
paths. Reference questions and evaluator answers stay in the evaluator and trace
archive; the model input boundary contains only ordinary prompts, response
schemas and delivered observations.

Preparation and freeze make no model calls. Freeze requires a
verified campaign conversion receipt, running-server receipt, exact converted
model hash, backend binary and library hashes, exact process command, healthy
endpoint and matching model alias. This environment is bound into the freeze and
checked again before execution. Sources are copied into the study directory;
real generation must execute that immutable copy.

## Execution, recovery and auditing

Run in the optional Python 3.13 environment:

```bash
python tools/native_campaign.py fetch
python tools/native_campaign.py freeze --upstream /tmp/witness-clbench-native
python artifacts/campaign/native/sources/tools/native_campaign.py run --output artifacts/campaign/native --runtime-receipt artifacts/campaign/runtime/server.json
python artifacts/campaign/native/sources/tools/native_campaign.py resume --output artifacts/campaign/native --runtime-receipt artifacts/campaign/runtime/server.json
python artifacts/campaign/native/sources/tools/native_campaign.py audit --output artifacts/campaign/native --replay
python artifacts/campaign/native/sources/tools/native_campaign.py report --output artifacts/campaign/native
```

The native upstream runner and trace recorder execute every task interaction.
Before each model call, a durable pending journal record is written. Completion
stores the raw response, request configuration, role and usage. A native run is
committed only after all 40 outcomes, the full native trace, memory artifacts and
every model-call receipt are durable and consistent.

Resume operates at complete native run boundaries. It skips verified completed
runs and begins the next untouched frozen run. Any partial native run, failed
call or uncertain invocation is retained as incomplete and prevents automatic
retry. No already observed model answer is silently regenerated. A failed run
requires a separately justified recovery or a new prospectively frozen study;
it cannot be discarded from the original report. `--max-runs` pauses only after
the requested number of newly completed runs and does not alter the 20-run plan.

Audit checks frozen sources/data, complete ordered outcomes, all receipts and
costs. `audit --replay` rebuilds completed native runs from their recorded model
responses on fresh native task state, validates exact public actions/observations,
final memory and metrics, and makes no model requests. Replay wall time is not
counted as fresh inference and cannot replace the original measured receipt.
The audit binds the freeze, report and every completed result by SHA-256, checks
the frozen model request configuration, and rejects scripted calls.

## Reporting and decision boundary

Report reward, answer accuracy, exploratory QUERY count and all model tokens for
every arm/permutation, with incomplete runs shown explicitly. Stateful gain is
the paired stateful-minus-stateless Witness difference in native reward; also
report its accuracy counterpart. Preserve negative migration outcomes. Five
permutations share fixed databases and questions, so they do not establish the
main experiment's independent-stream population inference or a general
no-forgetting guarantee. This native result is external-domain contact under the
original task and scorer. Contract fixtures never count as native model results.
