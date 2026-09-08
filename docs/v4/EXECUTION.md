# Reproduction and execution boundaries

## CPU reference

```bash
python -m pip install -e '.[test,analysis]'
make test
make cpp-check
make latent-study
make latent-heldout
make latent-diagnostics
make holdout-audit
make paper
```

`make paper` rebuilds the professional two-column LaTeX draft and TikZ diagram from recorded result tables. It does not execute new experiments. `make latent-heldout` overwrites the recorded held-out run; copy artifacts first when preserving an immutable release. The included audit compares final controller behavior to the preserved pre-backend run. Exact timings are not portable. Python 3.11 or newer is sufficient for this reference; the external CL-Bench README inspected in this session requires Python 3.13 or newer plus its own dependencies and Docker.

## Formal proof attempts

```bash
make formal
```

The pinned toolchain is in `formal/lean-toolchain`. The actual local command failed because `lake` is not installed. Attempts to retrieve the official release failed. `artifacts/v4/lean-build.txt` and `lean-status.txt` record this. All 50 declarations remain uncompiled attempts, including 11 new latent-learning declarations. There are no new `sorry` or `admit` placeholders, but their absence is not a correctness guarantee. The CI job invokes Lean without an allow-failure setting; a future successful CI run is required before any proof claim is upgraded.

## Optional local LLM proposer, not executed

```bash
PYTHONPATH=src python experiments/latent_llm.py --help
PYTHONPATH=src python experiments/latent_llm.py --model YOUR_LOCAL_MODEL_ID
```

This driver asks a local chat-completions service for bounded JSON action words or observation-contingent trees and runs the synthetic transducer protocol. It is not a native CL-Bench adapter. It does not start or install a model server and was not run against a real model in this environment. Remote endpoints require an explicit option. Its parser is tested; actual model execution, token economics and model capability are unmeasured.

Candidate text is untrusted. The accepted JSON schema cannot contain code, rewards, certificates or arbitrary extra fields. Duplicate keys, Boolean actions, oversized trees and invalid actions are rejected. Only executed environment outputs create evidence. A proposed program is immutable within its episode. This narrows data-plane mistakes but does not sandbox arbitrary Python process mutation or prove that a remote environment's feedback is honest. Use a separate authenticated environment channel in any native extension.

## Recorded checks

355 Python tests passed in the final suite. The new C++ reference passes 400 paired observation-tree cases plus a bounded-reward rejection under undefined-behavior sanitization. It checks numeric complete-machine rollout equivalence, not the symbolic cover algorithm. The legacy suite also passes 632 C++ cases plus an overflow check. No new CUDA kernel exists, and historical CUDA drafts remain uncompiled and unmeasured.

The symbolic comparisons and cover updates are checked against exhaustive enumeration on small classes. Search-limit tests ensure UNKNOWN cannot admit. Empty-model tests ensure INCONSISTENT cannot certify. Wrong-state-bound and hidden-drift examples explicitly demonstrate failure outside the contract. The online trainer has a finite-difference gradient test. An independent 1,200-episode diagnostic overwrites proposer parameters arbitrarily while the external contract remains enforced.

The parameter-byte metric covers the small neural weights only. Trace and partial-table payload bytes exclude Python object overhead, features, visit arrays, archive versions, policy trees, intermediate search state and candidate logs. They are not total RAM or a bounded-memory claim. Raw traces grow with episodes.

## Repository lineage

The release is a local Git repository derived from the uploaded bundle, not a remotely published GitHub repository. The downloadable bundle preserves historical commits; the ZIP contains the working source, tests, recorded results, formal attempts and compiled paper. MIT licensing is retained. No private credentials, model weights or font files are included.
