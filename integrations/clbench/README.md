# Native CL-Bench integration foundation

This optional adapter runs the **actual upstream ICL implementation** with an injected structured transport and an immutable ledger of normally observed feedback. It does not implement a native Witness learning policy; its exact certification result is always `UNKNOWN`. The no-op ledger is not presented as benchmark progress.

The checked source is [pgasawa/continual-learning-bench at 5f8c50e](https://github.com/pgasawa/continual-learning-bench/tree/5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26). `load_native` rejects a different HEAD or modified tracked source. It imports upstream under a distinct module namespace without editing its files or adding heavy dependencies to the default Witness package.

Create an isolated Python 3.13+ environment and install `requirements-native.txt`. The transitive package versions used for the included execution are recorded in `requirements-native.lock`. From the Witness repository root:

```bash
WITNESS_CLBENCH_UPSTREAM=/path/to/continual-learning-bench \
  /path/to/native-venv/bin/python -m pytest tests/test_clbench_core.py tests/test_clbench_native.py -q
/path/to/native-venv/bin/python -m integrations.clbench.smoke \
  --upstream /path/to/continual-learning-bench \
  --output integrations/clbench/native_contract_manifest.json
```

The smoke executes native `ICLSystem`, `DatabaseExploration`, and `run_task` on a tiny locally constructed SQLite fixture with a scripted transport. It checks prompt/action/outcome parity with an unmodified upstream ICL control. It uses no model endpoint, benchmark database, or official questions. The manifest explicitly labels fixture outcomes as **not benchmark scores**. Default tests exercise dependency-free ledger contracts; native tests visibly skip unless an upstream checkout and optional runtime are selected.

For programmatic real-model integration:

```python
from integrations.clbench.native import load_native, make_bridge

api = load_native('/path/to/pinned-upstream')
system = make_bridge(api, transport=my_structured_transport, model='exact-model-id',
                     max_tokens=8192, reserve_tokens=512)
# task must be built by the evaluator, with an official pinned schedule and data.
result = api.interface.run_task(task, system, show_progress=False)
```

A transport implements `complete(messages=..., response_schema=...) -> ModelReply` and `reset()`. Every reply supplies at least one `CallUsage`, preserving unknown measurements as `None`; retries must each be reported. Known failed-call usage can be supplied through `TransportFailure`. There is no bundled live model transport and no automatic CLI system discovery. The real transport must have isolated/resettable state and accurate token/cost accounting before benchmark use. `parallel_safe=False` is deliberate.

`make_bridge` inherits upstream `respond`, truncation, and feedback formatting. It forwards only visible messages and the response schema to the transport. It preserves terminal observations between instances and resets all learned state between independent runs, or between instances for the stateless control. Undrained usage survives reset so accounting is not silently erased. Feedback is delivered through `observe`; `Query.feedback` is not consumed a second time.

See [the native boundary audit](../../docs/v5/NATIVE_BENCHMARK.md) for the permitted feedback, scoring semantics, pin, current execution status, and what remains needed for a native learning experiment.
