# Native CL-Bench boundary and integration evidence

Checked against upstream commit `5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26` on 8 September 2026. [Pinned original source](https://github.com/pgasawa/continual-learning-bench/tree/5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26).

## Implemented scope

`integrations/clbench/native.py` loads the actual pinned source without modifying it and uses upstream `ICLSystem` as the execution engine. Its injected transport receives only messages and the native JSON schema. The bridge adds immutable action/observation records and explicit `UNKNOWN` certification metadata. It does not inject its audit ledger into the model, learn a native predictive representation, or claim the database task satisfies v4's finite deterministic contract.

The independent control is the unchanged upstream ICL class with the same injected transport. Tests compare visible history, actions, FIFO truncation, and usage across repeated interactions. Additional tests execute the real upstream runner and database task on a synthetic two-question SQLite fixture; they exercise SQL result observations, terminal feedback, scoring, and the stateless reset path. These are native *contract executions*, not executions of the official benchmark dataset or real-model measurements. The runnable smoke manifest records source hashes and package versions. No model server is contacted by these tests.

## Information and lifecycle boundary

| Native surface | What the bridge uses | Reason |
|---|---|---|
| `Query.prompt` | Passed through upstream ICL | This is the task's actual visible instruction and can include its native migration notice. |
| `Query.response_schema` | Passed as JSON schema; reply validated with its actual Pydantic class | Preserves the required `QUERY`/`ANSWER` structure without accepting executable Python from a proposer. |
| `Query.instance_id` | Opaque audit field only | It never enters the model prompt or chooses a skill. |
| `Query.metadata` | Not forwarded or stored | Database metadata contains a host database path; direct access would bypass the normal tool interface. |
| `Query.feedback` | Not consumed | At this pin, the actual ICL implementation takes feedback through `observe`; duplicating it changes the control. |
| `Observation.content` | Preserved as native `FEEDBACK: ...` in history, and verbatim in the ledger | This is the delivered post-action evidence. Blank feedback is recorded in the ledger but adds no ICL message. |
| `Observation.instance_complete` | Native boundary helper, including only its legacy metadata flag | Determines audit episode boundaries; it does not clear stateful history. Other observation metadata is excluded. |
| `TaskStepResult.instance_outcome`, `task.evaluate()`, internal question dictionaries | Evaluator side only | Scores, reference data, and hidden counterfactuals do not enter the model except when the task explicitly releases content through its normal observation. |

The normal order is task query → system response → task step → system observation. A stateful run retains history between completed instances. An independent run resets the system; the stateless comparison additionally resets at instance boundaries. Pending feedback and ledger entries are cleared on reset. Usage already incurred is retained until the runner consumes it, matching upstream accounting behavior.

## Exact database feedback audit

At this pin, `DatabaseExploration._handle_answer` reveals the correct answer through `Observation.content` after an incorrect answer, a timeout, or exhausted query budget. This is **legal post-action supervision supplied by the native task**, and both bridge and ICL retain it. The adapter must not remove it from only one arm or advertise the task as label-free. Although `task.py` supplies `ground_truth_sql` as a formatting argument, the actual `prompts.py` templates do not interpolate it: reference SQL is not released in terminal feedback at this pin. Tests exercise that distinction.

Ordinary SQL results also arrive as `Observation.content`. Question records contain the reference answer and SQL before execution, but reading those directly is not permitted agent evidence. The bridge receives no task object and does not open `Query.metadata['db_path']`. This is an information-flow boundary in the adapter, not an OS sandbox against a malicious transport; a real deployment needs process isolation to enforce host filesystem separation.

The default database schedule includes a generic visible notice that schema or contents may have changed at the migration boundary. It does not supply the hidden transformation or a true finite-state label. Preserve that notice. Do not describe the official task as wholly unannounced drift, and do not replace it with an easier oracle regime ID.

For a correct answer, native reward is `1 - exploratory_queries / query_budget`; the final `ANSWER` is not an exploratory query. Failure receives full-budget regret and reward zero. The two-question fixture deliberately exercises one correct answer after one query and one incorrect answer. Its numeric outcomes validate the scoring interface only. Official gain still requires the same system's stateless baseline on corresponding native instances; the fixture does not estimate that learning gain.

## What remains unresolved

The bridge supplies a controlled native baseline and feedback ledger. It deliberately has no admission path for exact native Witness certificates. Hidden-state coverage, deterministic resets, stationarity, finite output alphabets, scoped reusable rules, and their verification cost remain unestablished for native Database Exploration. A truthful native learning submission needs an implemented adaptation rule, a live transport with measured usage, official data/schedule pins, and paired prequential experiments. The v5 research agenda specifies those falsifiers.

Full-context behavior here means native visible history with FIFO truncation and injected transport. It does not claim parity with provider-specific hidden reasoning/state APIs. Native tests use the same deterministic offline token estimator on both arms to make fixture execution independent of tokenizer downloads. A real-model run must restore native/tokenizer or provider-measured accounting and freeze the actual serving configuration; fixture token estimates are not inference measurements.

The optional Python 3.13 runtime and pinned dependencies are separate from the default Witness test suite. `requirements-native.lock` records the executed environment, while `native_contract_manifest.json` records the native fixture execution and source hashes. This evidence is stronger than a mock interface test and weaker than a benchmark result. No official CL-Bench or AgentCL win is claimed.
