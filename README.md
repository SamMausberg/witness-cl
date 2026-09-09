# Witness-CL

[Paper](paper/main.pdf) · [Campaign status](artifacts/campaign/publication/STATUS.md) · [Campaign protocol](docs/campaign/PLAN.md) · [Historical results](docs/v10/RESULTS.md)

A **Stage 1 registered-report manuscript** and auditable research implementation
of online executable memory. A SQL agent
derives a parameterized relation from its own correct query, corroborates it on
a later changed binding, and can then execute it inside a new computation.
Learning happens between episodes without updating backbone weights. Every model
request, learning check and memory transition is recorded.

**The confirmatory result is not established.** The delayed lifecycle, faithful
online ACE adapter, native CL-Bench learning interface, durable campaign runner,
matched-evidence/deletion assays and paired-stream analysis are implemented. Scripted
mechanism tests are not model results. The new campaign requires future accuracy
superiority and at least 20% fewer total tokens against both full history and ACE,
plus before/after old-task noninferiority within two percentage points.
The earlier development studies and failed solver qualifications remain intact;
their admission counts do not establish transfer.

The first new-interface candidate completed both frozen cold qualifications:
33/64 on reuse and 39/64 on drift. Both failed their unchanged passing rules;
all 155 calls and 325,588 tokens are retained and independently replayed. A
separate dense-model and common-planning candidate passed both qualifications at
64/64, using 131 calls and 339,668 measured tokens with no unknown usage. Its
four-stream development block is running; it is now the first block of a frozen
32-stream pilot with 28 additional independent streams, totaling 17,664 episodes.
The full mechanism census, future-panel ceiling and measured retention variance
must be reported before auxiliary collection or confirmation sizing. See the
[pilot registry](artifacts/campaign/pilot-dense-v2/manifest.json) and
[qualification record](docs/campaign/QUALIFICATION.md). The main
paper has 10 pages; unrelated earlier work is in the [technical report](paper/technical_report.pdf).

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

The [current campaign plan](docs/campaign/PLAN.md) specifies the complete 32-stream
pilot and holds confirmation until its census, ceiling and variance are reviewed.
See [ACE and native integration](docs/campaign/ACE_NATIVE.md)
for the upstream pins and documented adaptations.

```bash
.venv/bin/python tools/campaign.py --help
.venv/bin/python tools/campaign_runtime.py --help
.venv/bin/python tools/campaign_results.py --help
.venv/bin/python tools/campaign_sequence.py --help
.venv/bin/python tools/campaign_pilot_report.py --help
.venv/bin/python tools/campaign_supervisor.py --help
.venv/bin/python tools/campaign_assay.py --help
.venv/bin/python tools/native_campaign.py --help
.venv/bin/python tools/publish_campaign.py
```

Each campaign freeze retains the exact executed sources under its output directory.
Run and replay that copy when continuing a frozen study. Successful recorded calls
can be replayed without another generation; uncertain calls remain explicitly
unresolved. Confirmation cannot be inferred from a development or qualification run.
The [analysis record](docs/campaign/ANALYSIS.md) preserves the provisional five-test
design. Its blanket .10 retention SD floor implies roughly 419 streams and is
under review, not an automatic launch instruction. The two-point margin remains
unchanged pending measured pilot variance and a revised prospective power freeze.
Missing outcomes and unknown usage cannot be silently discarded. Frozen-source
replay works even as the working tree evolves.

### Historical reproduction

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
| `src/witness_cl/delayed_memory.py` | Provisional relations, later corroboration, immutable provenance |
| `experiments/delayed_sql.py` | Common current-query interface and charged learning checks |
| `tools/campaign.py` | Source freezing, complete schedules, durable calls, recovery and replay |
| `tools/campaign_sequence.py` | Disjoint seed registry and audited progression between stages |
| `tools/campaign_assay.py` | Matched-history evidence controls and relation-deletion reruns |
| `tools/publish_campaign.py` | Tables and status from complete audited artifacts, including negatives |
| `src/witness_cl/ace_memory.py` | Official-pinned Generator/Reflector/Curator baseline |
| `formal/` | Pinned Lean statements, executable fixtures and dependency audit |
| `tests/` | Behavioral, isolation, accounting and regression checks |
| `paper/` | Current manuscript, technical report, bibliography and PDFs |
| `docs/campaign/` | Current protocol, analysis and integration contracts |
| `docs/v10/` | Historical protocol, results, research boundaries and hardware |
| `artifacts/` | Original measurements, failed attempts and verification receipts |
| `integrations/clbench/` | Pinned native ICL, ACE and delayed-memory adapters |

Superseded paper editions and redundant older narrative documentation were removed from
the working tree. [Historical provenance](docs/ARCHIVE.md) identifies their exact
Git revision. Numbered implementation modules and original data remain where
current tests, proofs and replay depend on them. They are not separate supported
product releases.

MIT software. Downloaded models have their own licenses. Research manuscript;
author review and independent replication remain necessary before publication.
