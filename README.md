# Witness-CL

[Paper](paper/main.pdf) · [Research status](docs/v10/RESULTS.md) · [Proof scope](docs/v10/FORMAL.md) · [Experiment protocol](docs/v10/PROTOCOL.md)

An auditable research implementation of online executable memory. A deployed
SQL agent preserves exact observations, proposes parameterized relations from
its own successful episodes, and checks each proposal by reconstruction and an
empty-relation intervention. Learning happens between episodes without updating
backbone weights. Every model request, check, retry and memory eviction is logged.

**The broad problem remains open.** Historical experiments establish conditional
retention and restricted within-family transfer, but no competitive benchmark
result or general no-forgetting. The final GH200 development stream passes its
warm gate, admits five programs, and reaches its time limit before the retention
panels; no proposed relation is executed on a later question. A cached guard
query supplied the correct current scalar in one old-task episode. The linked research status reports all failures,
costs and unknown usage. A checked program alone does not establish transfer.

## Install and verify

Python 3.11+ is required; the tested development environment uses Python 3.12.
Use a **full Git clone**, because historical regression tests and replay extract
the recorded source checkpoints. A downloaded source ZIP or a shallow checkout
without those commits cannot run those checks. Existing shallow clones can fetch
the missing history with `git fetch --unshallow`.

```bash
git clone https://github.com/SamMausberg/witness-cl.git
cd witness-cl
```

With [uv](https://docs.astral.sh/uv/), install the locked environment:

```bash
uv sync --locked --extra test --extra analysis --extra dev
make test PYTHON=.venv/bin/python
make lint
make formal PYTHON=.venv/bin/python
make paper PYTHON=.venv/bin/python
```

Alternatively, create a virtual environment and run
`python -m pip install -e '.[test,analysis,dev]'`; this installs compatible versions
without enforcing `uv.lock`. Lean uses the exact toolchain in
`formal/lean-toolchain`; install the official `elan` launcher first. Building the
paper requires TeX Live with LaTeX extras, recommended fonts, and BibTeX. Linux
package setup and the GH200 CUDA runtime are described in
[hardware reproduction](docs/v10/HARDWARE.md). Tests and saved-data replay do not
call a model. Native upstream benchmark-interface tests require their separately
pinned dependencies and checkout; they are not benchmark scores.

## Run a new experiment

[The frozen protocol](docs/v10/PROTOCOL.md) specifies shared controls, fresh seeds,
resource limits, learning-disabled evaluation panels, and stopping rules.
[The runtime tool](tools/gh200_runtime.py) serves a pinned CUDA backend and verifies
model hashes. Models and temporary server keys live outside the repository.
The GH200 exposes 97,871 MiB of GPU-visible memory; its marketed 480GB name is
not its VRAM capacity.

```bash
.venv/bin/python experiments/stateful_sql.py --help
.venv/bin/python tools/replay_at_revision.py artifacts/v10/development-94000 \
  --revision 11be4c4e740f57607167cef4b89e0d2680222808 \
  --freeze artifacts/v10/pre-run-freeze.json --output /tmp/witness-replay.json
```

Each run uses a new output directory and freezes executed sources before the
first call. A competence failure stops transfer evaluation. Historical costs at
unequal accuracy are descriptive, not efficiency wins. Follow-up experiments
need a separately recorded protocol; no result is overwritten or selected away.

## Repository map

| Path | Purpose |
|---|---|
| `src/witness_cl/evidence_memory.py` | Current exact-evidence control and learner memory |
| `experiments/stateful_sql.py` | Current online discovery, inference, budgets and panels |
| `formal/` | Pinned Lean statements, executable fixtures and dependency audit |
| `tests/` | Behavioral, isolation, accounting and regression checks |
| `paper/` | One current manuscript, bibliography and PDF |
| `docs/v10/` | Current protocol, results, research boundaries and hardware |
| `artifacts/` | Original measurements, failed attempts and verification receipts |
| `integrations/clbench/` | Pinned native interface integration, not a benchmark result |

Superseded paper editions and redundant older narrative documentation were removed from
the working tree. [Historical provenance](docs/ARCHIVE.md) identifies their exact
Git revision. Numbered implementation modules and original data remain where
current tests, proofs and replay depend on them. They are not separate supported
product releases.

MIT software. Downloaded models have their own licenses. Research manuscript;
author review and independent replication remain necessary before publication.
