# Formalization status

The v5 audit successfully kernel-checked **51 theorem declarations with Lean
4.19.0**: the 50 inherited statements and one general history-aliasing obstruction.
The original build failed on two uses of the reserved binder name `protected`
and on one Boolean inequality simplification. The repair renames the binders and
adds the missing Boolean equality fact; it does not weaken any statement.

Run the build and complete axiom audit from the repository root:

```bash
python3 formal/audit.py --output artifacts/v5
```

`lake` must be on PATH, installed at `~/.elan/bin/lake`, or specified with `LAKE`.
The pinned version is in `lean-toolchain`; there are no external Lean package
dependencies. A direct build is also available:

```bash
cd formal
lake build
```

The audit compiles the library, inventories every project theorem, executes
`#print axioms` for all of them, checks that none is missing, and rejects
placeholders, custom source axioms, or dependencies outside Lean's standard
`propext`, `Classical.choice`, and `Quot.sound` axioms. In the recorded build,
24 theorems have no axioms; 27 use `propext`, 11 use `Quot.sound`, and 2 use
`Classical.choice` (these counts overlap). No theorem depends on `sorryAx`.

Exact compiler output, the complete axiom inventory, and source hashes are in
`artifacts/v5/formal-{build,axioms,version}.txt` and `formal-audit.json`. The
initial inherited-source failure is preserved in `formal-initial-build.txt`.
These logs supersede the historical v1-v4 inability to run Lean, not the old
versions' claim boundaries. See `docs/v5/FORMAL.md` for the precise scope.

The proofs certify conditional abstract algebra: retaining the true model,
checking all live models, and preserving already acquired values. They do not
establish that the Python DFS produces its claimed complete cover, that real
tasks satisfy the finite deterministic reset contract, or that the trainer,
C++, CUDA, noisy feedback, or an LLM is correct. Kernel acceptance does not
establish practical continual-learning progress or a stateful benchmark win.
