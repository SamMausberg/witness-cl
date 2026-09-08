# Executable semantics bridge (v6)

## Established result

The Lean 4.19.0 kernel checks 63 project theorem declarations: the prior 51 and
12 new statements in `formal/WitnessCL/Executable.lean`. The full inventory has
no placeholders, custom source axioms, `sorryAx`, or unexpected dependencies.
The only admitted dependencies are Lean's standard `propext`, `Quot.sound`, and
`Classical.choice`; 24 statements are axiom-free. The new module uses neither
`Classical.choice` nor an assumed oracle for consistency.

The new executable semantics defines a total deterministic transition table
from finite states and actions to finite successor states and output symbols.
`runFrom` actually executes an action list, preserving the final state and every
observed `(action, output)` pair. `run` begins each episode at reset state zero.
`traceMatches`, `filterTrace`, and `filterHistory` compute consistency using this
interpreter and equality of complete observable traces.

The proofs establish that:

- Execution records exactly the supplied actions and composes over action-word
  concatenation, including the correct intermediate hidden state.
- A machine survives one trace if and only if it was in the input list and its
  execution reproduces that trace.
- A machine survives a history if and only if it was in the input list and
  reproduces every recorded reset episode.
- When history is constructed by running a member machine, that machine remains
  in the filtered list. The theorem constructs consistency from execution; it
  does not assume an uninterpreted `consistent` predicate.
- Sequential history filtering equals filtering the concatenated history;
  survivors are a subset of the original list; contradictory evidence eliminates
  an incompatible machine.

`filterHistory_retains_executed_truth` and
`executed_history_characterization` are the main proof-to-runtime improvement.
Neither theorem is a performance or alignment claim.

## Executable differential evidence

`formal/ExecutableFixture.lean` compiles into `witness_fixture`. It enumerates
all 256 labelled deterministic machines with two states, two actions, and two
output symbols. Its edge code is `2 * successor_state + output`, with four
row-major transition slots encoded as base-four digits.

The executable records 7,936 executions: all 31 binary words of lengths zero
through four on every machine. It also applies the proved `filterHistory`
function to four cumulative reset-history prefixes per possible true machine,
using action words `01`, `10`, `0011`, and `1100`. This produces 1,024 survivor
lists. The JSONL artifact has 8,961 rows including its schema header.

Five passing tests in `tests/test_formal_v6.py` verify artifact/source hashes,
exhaustive finite coverage, interpreter correspondence, partial-table filter
correspondence, and the corrupted-feedback boundary. Specifically:

- Every Python `Machine.run` result matches its Lean trace and every final state
  matches the Lean execution.
- All 7,680 nonempty words also match `Program.word(...).rollout(...)`.
- On every history prefix, all 256 Python `LatentSpace.contains` answers match
  Lean's explicit survivor list: 262,144 membership comparisons. Every actual
  generating machine remains present.
- Two opposite outputs on the same one-action reset episode empty the Python
  version space. Corrupted feedback can remove the actual model, as the exact
  deterministic theorem assumptions predict.

These are bounded differential tests, not a Lean proof of Python equivalence.
The exact theorem inventory, source hashes, build logs, executable fixture hash,
and raw JSONL are in `artifacts/v6/formal-*`.

## Reproduction

From the repository root, with the pinned Lean toolchain installed:

```bash
python3 formal/audit.py --output artifacts/v6
python3 -m pytest tests/test_formal_v6.py -q
```

The audit builds both the library and the executable, checks every theorem's
axioms, and regenerates the fixture. `LAKE` can specify the local Lake binary.
The audit requires no external Lean packages and the executable has no network,
filesystem mutation, subprocess, deployment, or model-training behavior. It only
prints bounded deterministic JSON records.

## Boundaries and remaining obligations

Truth preservation requires a stationary deterministic transition table,
correct feedback, reliable reset to state zero, and initial inclusion of the
true machine. The type-level finite alphabets rule out malformed edges in Lean;
Python validates its separate representation dynamically. The finite machine
class remains an explicit environmental assumption, not an inferred guarantee.

The Lean proofs cover exhaustive list filtering and fixed action words. They do
not prove correctness of the optimized Python partial-table DFS, adaptive
observation-contingent `Program` execution, lower-bound comparisons, experiment
planning, pruning, resource-limit handling, serialization, C++/CUDA, or an LLM.
The differential tests check the DFS and word-program bridge only on the stated
small family. Their success cannot justify a universal runtime claim or a
stateful benchmark win.

The next useful formal step is a refinement proof that each Python-style partial
table denotes exactly its total completions and that a trace-fitting transition
preserves precisely the execution-consistent completions. An error in that
refinement, or one small-machine differential disagreement, would invalidate the
corresponding runtime certificate claim. Real deployment would additionally
need independent evidence for reset, stationarity, feedback fidelity, and the
candidate policy/environment boundary; this work does not establish alignment
or rule out all misalignment risks.
