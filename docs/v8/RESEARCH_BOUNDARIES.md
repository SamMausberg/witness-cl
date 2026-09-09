# Version8 execution boundaries

The user authorized continued implementation, proofs, experiments and private
Git updates, and explicitly requested safe work. This phase performs bounded
local inference with a small official frozen model and synthetic databases.
The model receives text and emits JSON data. It cannot execute Python, commands,
network requests, filesystem access, training code, tools outside the fixed SQL
interface, or changes to its own admission rules. Model weights remain frozen.

The server binds only to authenticated127.0.0.1:18084, with UI/agent tools disabled
and offline inference. A transient local key is never exported to research logs
or Git. Downloaded weights and server runtime remain outside the research repo.
The server is stopped after the active experiments. No background automation,
paid compute, external deployment or external messaging is authorized here.

SQLite fixtures are constructed by trusted evaluator code, then restricted to
bounded read-only SELECTs through query-only mode, an allowlist authorizer and
row/byte/VM/time limits. Prepared literal bindings cannot introduce SQL syntax.
Learned SQL is still untrusted and is checked by the same fixed executor as
ordinary model-generated SQL. This is a text-model capability boundary, not
sandboxing for hostile Python code with process introspection.

All v7 frozen source and artifacts are preserved. Version8 uses additive modules,
a separate Lean audit and new experiment paths. Completed and partial model runs
remain immutable. Model failures and negative outcomes are retained. The central
research claim is not assumed true, and conditional compilation proofs must not
be presented as evidence of general continual learning or alignment.
