# Historical evidence and cleanup

The current manuscript lives only in `paper/main.tex` and `paper/main.pdf`.
Superseded paper/v1–v7 copies, old root paper fragments, and docs/v2–v7 narrative
versions were removed to make the current research easier to navigate. They are
recoverable from Git revision `88b0a1b7c093c21135489a3e5cbbda3bb0634536`.

Seven source-hashed v6/v7 protocol documents remain because replay depends on
their exact paths and bytes. Original numerical data, source freezes, implementation dependencies, regression
tests and Lean contracts are retained. Archived documents may refer to removed
paper editions: read those documents at their original revision for intact links.
No prior result is converted into evidence for the new algorithm.

The current SQLite security correction intentionally changes two v9 source
files. Consequently, old source-bound replays must use the exact old source tree:

```bash
python tools/replay_legacy.py --output artifacts/v10/legacy-replay.json
```

The helper requires Git history containing the recorded revision, extracts it
to a temporary directory, runs only saved-data audits, and records its actual
Python and SQLite runtime. It does not claim to reconstruct the historical OS,
model backend, hardware or clocks. Use a full Git clone (`fetch-depth: 0` in CI).
Do not edit old freeze hashes to accommodate a changed implementation.
