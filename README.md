# Witness-CL

Version 0.9.0 · [Development paper](paper/v9_development.pdf) · [Results and next experiment](docs/v9/RESULTS.md) · [Mechanism review](docs/v9/MECHANISM_REVIEW.md)

**Solver competence improved; the original online-abstraction claim remains unproven.** The selected 9B diagnostic reaches **7/8** after the v8 configuration scored 0/8. On the final fresh development warm block, full history scores **8/8**, evolving SQL-capable text **6/8**, and executable memory **7/8**. The declared all-arm 7/8 gate stops the run before transfer or retention panels.

| Final warm method | Correct / 8 | SELECTs | Model calls | Tokens |
|---|---:|---:|---:|---:|
| Full history | 8 | 9 | 17 | 50,178 |
| Evolving text | 6 | 14 | 30 | 55,808 |
| Checked programs | 7 | 22 | 31 | 49,700 |

Seven proposals yield two finite admissions, but **zero USE/COMPOSE actions**. An offline intervention finds that one admission's reconstruction ignores the learned relation entirely. Two admissions therefore do not demonstrate reusable abstraction learning, interaction savings or preserved behavior. These unequal-accuracy warm costs are not a matched-accuracy efficiency result.

The phase fixes ordinary-SQL parsing, derived-relation authorization and native schema/reasoning compatibility. A separate **offline-tested, unintegrated repair prototype** allows up to three feedback-guided proposals, preserves original evidence, charges all checks, and requires an empty-relation intervention to change the reconstruction result before admission. It has not been tested with a real model. [Repair implementation](src/witness_cl/discovery_repair_v9.py)

All seven adaptive diagnostics and three separately frozen follow-ups are preserved: **89 records, 244 generation requests, 366,795 known tokens**, two unknown-usage failures, and **18.40 minutes** of measured experiment time. Reserved bounds for the two failures give a total token upper bound of 375,904. No heldout, population-significance or native benchmark result is claimed. [Generated ledger](artifacts/v9/results.json) · [Model provenance](artifacts/v9/model-9b-provenance.json) · [Runtime cleanup](artifacts/v9/runtime-cleanup.json)

## Reproduce saved-data checks

```bash
python3 -m pip install -e '.[test,analysis]'
make test
make v9-audit
make paper-v9
```

These commands invoke no model. Replay checks actual SQL, legal prompts, memory transitions, costs, source/configuration freezes and incomplete schedules. It does not authenticate the original model or backend token counts. CI separately verifies the preserved Lean contracts, C++ references and pinned native CL-Bench interface; an interface test is not a benchmark run. [Audit boundary](docs/v9/AUDIT.md)

The final portable protocol declared this phase's last model attempt. Any new study needs a new source/protocol freeze and fresh disjoint seeds. No research automation is active. Full implementation/test evidence is recorded in [v9 validation](artifacts/v9/validation.json).

## Preserved v8 evidence

The [v8 paper](paper/main.pdf), [results](docs/v8/RESULTS.md), frozen execution inputs and 288-episode negative pilot remain unchanged. Its 89 Lean statements establish typed compilation properties and explicitly modeled conditional results, not discovery, generalization or unconditional runtime retention. [Proof boundary](docs/v8/FORMAL.md)

## Preserved earlier research

This private repository continues `Witness_CL_v4.bundle` and preserves its Git history and release tags. In the [archived v7 study](docs/v7/RESULTS.md), a supplied-grammar numerical learner gained +0.12240 reward from reuse on shared-novel questions, but lost the common-SELECT-budget final comparison to simple full-history controls (47.44% versus 100%). That result does not demonstrate discovered SQL abstractions. Its [paper](paper/v7/main.pdf), [source freeze](artifacts/v7/freeze.json), raw evidence and earlier archives remain unchanged.

MIT software license. AI-assisted research draft; author review and independent replication remain necessary before publication.
