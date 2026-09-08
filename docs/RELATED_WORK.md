# Prior work and novelty boundary

Reviewed through 8 September 2026. Sources below are original papers, author
pages or official benchmark code. The review identifies close work; it cannot
certify global novelty or an up-to-date universal state-of-the-art ranking.

| Approach | Established contribution | Boundary relevant to Witness-CL |
|---|---|---|
| Raw full-history ICL, CL-Bench | Strong empirical online-learning control | Prompt capacity, evidence use and compute remain practical constraints; no proof that compression is intrinsically superior |
| ACE | Evolving structured playbooks, online and offline adaptation | Successful feedback-guided context evolution is prior art; structured notes alone are not conditional logical certificates |
| AgentCL / MemProbe | Controlled compositional streams; interaction, insight and skill memories; consolidation checks | Essential transfer benchmark/control; judge quality is not the same as fresh measured policy improvement |
| Voyager | Persistent executable skill library and experience-driven improvement | Rules as code, persistent skills and no-gradient improvement are not new |
| EvoTest and TTHE | Evolve the agent system/harness at test time | Closest whole-agent competitors; execution-proxy selection does not by itself supply a retention theorem |
| ALMA | Meta-learns executable memory designs | Learning the memory architecture is prior art; predeployment meta-training does not itself violate a no-offline-retraining-after-deployment constraint |
| User as Code | Executable typed memory and append-only evidence | Ledger plus code is not a novel claim |
| Decision-Aware Memory Cards | Decision-oriented ranking and typed compressed evidence | Explicitly counterfactual-inspired rather than randomized causal identification in the reviewed version |
| KWIK / version-space learning | Abstaining while uncertain, truthful prediction under assumptions | Main logical mechanism is established; do not sell it as a new theory of intelligence |
| Program sketching and representative-example synthesis | Inductive synthesis, counterexamples, selecting sufficient examples | Witness selection and preservation relative to a program class have substantial prior art |
| Conservative contextual bandits / sequential inference | Baseline-relative learning and time-uniform evidence | Baseline protection and e-process mathematics are established, not invented here |
| EWC, GEM, progressive networks and test-time training | Parameter regularization, replay constraints, isolation or online updates | Important alternatives; frozen weights/columns preserve parameters, not automatically whole-agent behavior |

The proposed research contribution is a specific **operational combination**:
preserve the decision-discriminating evidence relative to a declared model class,
compile total scoped programs when justified, retain explicit uncertainty and
counterexamples, and use independent fresh-episode evidence for broader full
system changes. The submission-worthy contribution, if it exists, must be a
nontrivial real-task compiler/learning mechanism and a measured reward-cost-retention
improvement. A collection of old ingredients and a toy experiment is not enough.

## Primary references

CL-Bench: https://arxiv.org/abs/2606.05661

AgentCL: https://arxiv.org/abs/2606.02461

ACE: https://arxiv.org/abs/2510.04618

Voyager: https://arxiv.org/abs/2305.16291

EvoTest: https://arxiv.org/abs/2510.13220

TTHE: https://arxiv.org/abs/2607.08124

ALMA: https://arxiv.org/abs/2602.07755

User as Code: https://arxiv.org/abs/2606.16707

Decision-Aware Memory Cards, v3, 4 September 2026: https://arxiv.org/abs/2606.08151

KWIK: https://doi.org/10.1145/1390156.1390228

Program sketching: https://doi.org/10.1007/s10009-012-0249-7

Representative examples: https://proceedings.mlr.press/v80/pu18b.html

Conservative contextual linear bandits: https://arxiv.org/abs/1611.06426

Time-uniform confidence sequences: https://arxiv.org/abs/1810.08240

EWC: https://arxiv.org/abs/1612.00796

GEM: https://arxiv.org/abs/1706.08840

Progressive networks: https://arxiv.org/abs/1606.04671

End-to-end test-time training: https://arxiv.org/abs/2512.23675
