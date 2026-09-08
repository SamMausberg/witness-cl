# Witness-CL v0.5 research status

8 September 2026. The general continual-learning problem remains unsolved. This release makes the prior artifact verifiable, tests and rejects a new exploration rule, executes actual local-model inference, and builds a native benchmark integration foundation. It is a research checkpoint, not a benchmark-winning deployed learner.

## What is established here

| Result | Evidence | Boundary |
|---|---|---|
| Private repository and preserved lineage | `SamMausberg/witness-cl`; original main `c1d63a6`; v0.2.0/v0.4.0 tags retained | Private research, no public release/submission |
| 51 Lean statements checked with Lean 4.19.0 | `formal/audit.py`, source-hashed axiom/build artifacts | Abstract conditional lemmas, not proof of Python/runtime or model-class validity |
| All original Python and independent C++ checks reproduce | New v5 logs; original 355 Python tests and 1,032 C++ cases plus boundary checks | Finite testing does not establish universal correctness; no new CUDA kernel |
| Regret-directed probes fail the frozen test | 19,200 holdout rows; delta vs v4 -0.094583, 95% [-0.169152,-0.020014] | Same tiny distribution, unequal compute; no native result |
| Weak-dominance closure repairs an identified plateau | Post-hoc census of all 256 tables, 49,152 rows, ten improvements and no worsened table vs failed v5 | Still below v4/full-history; one initialization/schedule per table |
| Complementary information defeats the one-step rule | Executed four-world counterexample and written stall argument | Restricted finite class; no claim that depth-two search scales |
| Real local-model inference executes | 120 calls; five worlds; all outputs valid and all usage records complete | Exploratory smoke, frozen LLM weights, strong symbolic prior, no stateless/native control |

The primary, pilot, and successor CPU studies together contain 72,192 episode rows. Independent replay checks 54,144 guarded prefixes, all within B16. The 180 additional local-model/control episodes are separate: five seeds × three arms × twelve episodes, with 120 actual model calls. These counts are engineering evidence, not independent statistical sample sizes. The independent unit is a generated stream/world; exhaustive labelled tables also contain observational equivalences.

The integrated standard suite passes 401 tests, with eight explicit optional-runtime skips.
All eight native tests also pass in the separate Python 3.13 environment (20 native/core tests total, of which 12 overlap the standard suite).

## What was inferred and what failed

**Inference:** retaining an incumbent and retaining truth in a configured model class are insufficient to obtain efficient learning. The probe objective must capture useful multi-step information and the admission rule must allow non-regressing moves that only weakly improve across compatible worlds. This inference is supported by concrete counterexamples and failures, not by a new general optimality theorem.

**Rejected hypothesis:** maximizing one-step worst-outcome reduction in library-restricted minimax regret would improve v4's mean reward. The frozen trial gives lower reward, a larger observed prefix deficit, and about 1.90× measured mechanics time. It must remain rejected in the paper; later tuning does not replace it.

**Narrow positive result:** the separately designed weak-dominance closure repairs its diagnosed plateau while retaining exact conditional admission. It still fails the complementary free-probe construction and remains less effective than the stronger controls. It is not the deployed default or a recommended replacement for v4.

**Exploratory inference:** the local model can produce parseable, reusable programs and its checked arm can benefit from the symbolic controller. In four consecutive extension seeds, returns were 5.5417 checked, 3.9583 raw, and 5.0000 static-library. The initial seed had no action-dependent headroom and is retained. Five worlds and extra algorithmic machinery do not establish general memory superiority, LLM weight learning, or no forgetting.

## Precise open problem

Learn a representation from realistic, partial, potentially noisy experience that is sufficient to improve *future* decisions at affordable total cost, and preserve declared earlier behavior under explicitly stated environment and evaluation conditions. The representation cannot be supplied by an evaluator, validated by its own training fit alone, or silently assumed stable under hidden drift. Finite storage, approximate inference, changing objectives, and limited feedback constrain what can be guaranteed.

Uniform strict improvement with zero possible loss is impossible in observationally indistinguishable worlds whose improving actions have conflicting value. The new Lean lemma verifies a deterministic information-state form of this elementary obstruction. Nonzero risk budgets, informative safe probes, or stronger justified assumptions make narrower questions meaningful; they do not remove the need to measure reward and cost.

## Strongest controls and where existing approaches stop

The [primary-source audit](LITERATURE.md) compares twelve close approaches. Same-backbone raw-history ICL is essential, but the motivating CL-Bench paper does not show every memory method loses on every metric. ACE, MemProbe/AgentCL, ALMA, executable skill libraries, and evolving harnesses already demonstrate forms of adaptation. TTT-E2E is a serious weight-learning antecedent; Deep SPI, predictive state representations, dynamic shielding and conservative exploration are direct theoretical/algorithmic precedents. Their assumptions, evaluation protocols, and costs differ. No global novelty or current SOTA rank is claimed here.

Native benchmark reward, each system's own stateless gain, old-scope retention, and total compute must be reported separately. The symbolic full-history planner and the local raw-history word-program prompt are not the official CL-Bench ICL implementation.

## Delivered materials and next decision

[Experiment and provenance](EXPERIMENT.md), [formal audit](FORMAL.md), [complementarity counterexample](PROBE_COUNTEREXAMPLE.md), [local-pilot review](LOCAL_PILOT_REVIEW.md), [research agenda](RESEARCH_AGENDA.md), and [next steps](NEXT_STEPS.md) specify executed evidence and proposed tests. The compiled 11-page paper and LaTeX/TikZ/figure sources are in `paper/`; v4 is archived under `paper/v4/`.

The first phase assumed local compute with already available models and no paid API/GPU rental. No user decision is needed for the next CPU experiment or native adapter work. A larger model or paid benchmark budget is a later decision, after actual native pilot costs and the concrete run manifest are available.
