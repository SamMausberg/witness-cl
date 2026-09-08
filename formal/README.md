# Formalization status

Lean 4.19.0 checks **63 theorem declarations**: the prior 51 abstract statements and 12 new executable-semantics statements. The new interpreter and history filter construct truth retention from actual executions. See [v6 scope and reproduction](../docs/v6/FORMAL.md).

```bash
python3 formal/audit.py --output artifacts/v6
python3 -m pytest tests/test_formal_v6.py -q
```

The audit builds the library and fixture executable, inventories all declarations, and rejects placeholders, custom source axioms and unexpected dependencies. The only dependencies are standard Lean `propext`, `Quot.sound`, and `Classical.choice`; 24 statements are axiom-free. The prior failure/repair logs remain in `artifacts/v5/`.

The executable fixture covers all 256 binary two-state machines. Differential tests compare 7,936 interpreter traces, 7,680 nonempty word programs, and 262,144 filter membership decisions against Python. These finite checks are not a general Python refinement proof. Reliable reset, stationary deterministic transitions, genuine feedback, and initial inclusion of the true machine remain assumptions. No proof establishes general alignment or a benchmark win.
