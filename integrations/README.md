# Public benchmark integration boundary

No official CL-Bench or AgentCL result is included. The synthetic LLM runner is
not a task adapter. The original task prose supplied no usable prior-work link.

The inspected upstream repository is `pgasawa/continual-learning-bench`.
On 2026-09-08 its README required Python >=3.13, uv and Docker for containerized
tasks. Its ICL implementation imports `ContinualLearningSystem`, `Query`,
`Observation`, and `Response` from `src/interface.py`, registers `icl`, and exposes
`respond(query)` and `reset()`. `respond` consumes `query.prompt` and
`query.response_schema`, returns a structured `Response`, and records usage.
The inspected file is `src/systems/icl/system.py`, blob SHA
`bf60ce2441fbe48f38d76bc3a1636ae64893f66a`. This is a file pin, not a whole-repository
commit pin. Revalidate the interface and freeze the full commit before integration.

The upstream initial smoke command in its README was:

```bash
clbench run exploitable_poker --schedule quick_test --system icl
```

A real Witness integration must map each task's actual observables and legal
feedback to typed constraints or empirical candidate evaluation. It must never
read a scoring answer as if the agent observed it. Register a new system rather
than modify the ICL control. Reset all learned state between independent runs,
not between episodes in the same rollout. Keep task snapshots, model IDs,
provider settings, inherited context behavior and all costs in the manifest.

Before declaring support, pass native schema/usage tests, a no-op parity test
against the exact upstream ICL system, a scope/version identity test, and an
explicit feedback-access audit. These steps are deliberately not represented by
an empty adapter that silently falls back and claims compatibility.

Primary documentation:
https://github.com/pgasawa/continual-learning-bench
https://continual-learning-bench.com/docs/contributing-systems/
https://continual-learning-bench.com/docs/metrics/
