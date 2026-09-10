# Historical evidence and cleanup

The current manuscript is [paper/main.tex](../paper/main.tex) and
[paper/main.pdf](../paper/main.pdf). Earlier theory and experimental results are
consolidated in the companion [technical report](../paper/technical_report.pdf)
and [historical evidence index](v10/HISTORICAL_EVIDENCE.md).

Superseded paper/v1–v7 copies, old root paper fragments, and older docs/v2–v7
narratives were removed in an earlier cleanup. They are recoverable from Git
revision `88b0a1b7c093c21135489a3e5cbbda3bb0634536`.

The publication cleanup also removes 17 superseded narrative and planning files
from docs/v8, docs/v9, and docs/research. Their exact contents and original links
remain available at Git revision
[`be751d907126ccf753c45bf9adf3eb227b5ee646`](https://github.com/SamMausberg/witness-cl/tree/be751d907126ccf753c45bf9adf3eb227b5ee646/docs).
The removed files are the v8 environment, composition, evaluation-review,
pilot-review, next-step, boundary and result narratives; v9 action-parser,
audit, development-plan, experiment-design, interaction, runtime and solver
narratives; and the earlier query-transfer design and runtime plan.

The following documents remain at their exact paths and bytes because they
support replay, source or validation hashes, or the documented proof boundary:

- `docs/v6/EVALUATION.md` and `docs/v6/RESEARCH_BOUNDARIES.md`.
- `docs/v7/EVALUATION.md`, `FORMAL.md`, `GATE.md`, `REPRESENTATION.md`, and
  `RESEARCH_BOUNDARIES.md`.
- `docs/v8/EVALUATION.md` and `docs/v8/FORMAL.md`.
- `docs/v9/STREAM_PROTOCOL.md`, `JSON_REPAIR_PROTOCOL.md`, `PORTABLE_PROTOCOL.md`,
  `RESULTS.md`, `MECHANISM_REVIEW.md`, and `DISCOVERY_REPAIR_PROTOTYPE.md`.
- The earlier solver-qualification protocols, their results, and the runtime
  inspection referenced by the bounded-thinking protocol in `docs/research/`.

Original numerical data, source freezes, implementation dependencies, regression
tests, and Lean contracts are retained. Archived documents may refer to removed
paper editions: read those documents at their original revision for intact links.
No prior result is converted into evidence for the current algorithm.

The SQLite security correction changed two v9 source files. Old source-bound
replays therefore use the exact recorded source tree:

```bash
python tools/replay_legacy.py --output artifacts/v10/legacy-replay.json
```

The helper requires Git history containing the recorded revision, extracts it
to a temporary directory, runs only saved-data audits, and records its actual
Python and SQLite runtime. It does not reconstruct the historical OS, model
backend, hardware or clocks. Use a full Git clone (`fetch-depth: 0` in CI).
Do not edit old freeze hashes to accommodate a changed implementation.
