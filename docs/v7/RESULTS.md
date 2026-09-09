# Version 7 results

All numbers below use the frozen 16-stream evaluation; development is separate.

The primary reuse difference is **+0.12240** reward, with a paired 95 percent interval **[0.03158, 0.21321]**. The predeclared transfer target is **met**.

The requirement to beat every fixed simple control at the 4096-SELECT budget is **not met**. A query ceiling is not equal wall time or equal all-resource computation.

## Matched protocol

| Method | Shared first24 | Ordinary reward | Final macro | Ordinary examples | Audit pairs | SELECTs | Run sec |
|---|---:|---:|---:|---:|---:|---:|---:|
| Grow + reuse, audited | 0.1745 | 0.4330 | 0.6807 | 224.0 | 613.2 | 4889.9 | 1.360 |
| Grow, no reuse, audited | 0.0521 | 0.4509 | 0.7344 | 224.0 | 623.1 | 4939.3 | 1.378 |
| Sparse history, audited | 0.5130 | 0.7919 | 1.0000 | 224.0 | 123.4 | 2440.9 | 0.872 |
| Sparse history, ungated | 0.5469 | 0.8491 | 1.0000 | 224.0 | 0.0 | 1824.0 | 0.744 |
| Full ridge, ungated | 0.0026 | 0.0017 | 0.0000 | 224.0 | 0.0 | 1824.0 | 1.836 |
| Grow all 84, audited | 0.0729 | 0.4914 | 0.7876 | 224.0 | 631.4 | 4981.2 | 1.424 |

## Budget protocol

| Method | Shared first24 | Ordinary reward | Final macro | Ordinary examples | Audit pairs | SELECTs | Run sec |
|---|---:|---:|---:|---:|---:|---:|---:|
| Grow + reuse, audited | 0.0145 | 0.3438 | 0.4744 | 138.1 | 582.6 | 4095.3 | 0.982 |
| Grow, no reuse, audited | 0.0136 | 0.3391 | 0.4744 | 139.8 | 581.6 | 4095.1 | 0.986 |
| Sparse history, audited | 0.5130 | 0.9484 | 1.0000 | 903.6 | 123.2 | 4094.8 | 3.196 |
| Sparse history, ungated | 0.5469 | 0.9695 | 1.0000 | 1109.0 | 0.0 | 4095.0 | 3.484 |
| Full ridge, ungated | 0.0026 | 0.3915 | 1.0000 | 1109.0 | 0.0 | 4095.0 | 7.588 |
| Grow all 84, audited | 0.0152 | 0.3711 | 0.5117 | 136.6 | 583.4 | 4095.1 | 1.019 |

## Prespecified paired effects

| Protocol / outcome | Reuse minus control | Mean | 95 percent interval |
|---|---|---:|---:|
| matched / shared_novel_first24_reward | Grow, no reuse, audited | +0.12240 | [0.03158, 0.21321] |
| matched / shared_novel_first8_reward | Grow, no reuse, audited | +0.00000 | [0.00000, 0.00000] |
| budget / final_macro_reward | Sparse history, audited | -0.52563 | [-0.55610, -0.49517] |
| budget / final_macro_reward | Sparse history, ungated | -0.52563 | [-0.55610, -0.49517] |
| budget / final_macro_reward | Full ridge, ungated | -0.52563 | [-0.55610, -0.49517] |
| matched / shared_novel_first24_reward | Grow all 84, audited | +0.10156 | [-0.00929, 0.21242] |
| matched / shared_novel_first24_reward | Sparse history, audited | -0.33854 | [-0.45835, -0.21874] |
| matched / shared_novel_first24_reward | Sparse history, ungated | -0.37240 | [-0.48910, -0.25569] |

## Actual cost and reach

The following companion costs average complete arm/runs. SQL setup is outside the named SELECT budget but its time is included in measured run time. Run timers exclude harness construction and final JSON export; whole-grid elapsed time is reported separately. Feature work includes prediction and training-screening work separately in analysis.json; fitting uses cached past features. Numeric and serialized storage below omit Python object overhead and do not measure peak process RAM.

| Method | Setup sec | Fit/update sec | Peak history+cache KiB | Serialized gate KiB | Policy registry KiB | Unreached reports | Exposures R0..R7 |
|---|---:|---:|---:|---:|---:|---:|---|
| Grow + reuse, audited | 0.136 | 0.011/0.063 | 380.4 | 116.8 | 50.0 | 0.00 | 24.0, 24.0, 24.0, 24.0, 10.7, 10.5, 10.5, 10.4 |
| Grow, no reuse, audited | 0.136 | 0.011/0.071 | 388.6 | 116.7 | 50.7 | 0.00 | 24.0, 24.0, 24.0, 24.0, 11.2, 10.9, 10.9, 10.7 |
| Sparse history, audited | 0.192 | 0.048/1.681 | 2918.8 | 26.5 | 29.8 | 0.00 | 117.3, 117.3, 117.2, 116.9, 108.9, 108.8, 108.6, 108.6 |
| Sparse history, ungated | 0.207 | 0.059/2.206 | 3579.4 | 0.0 | 32.3 | 0.00 | 143.0, 143.0, 143.0, 143.0, 135.0, 134.0, 134.0, 134.0 |
| Full ridge, ungated | 0.216 | 0.803/2.959 | 3579.4 | 0.0 | 3374.3 | 0.00 | 143.0, 143.0, 143.0, 143.0, 135.0, 134.0, 134.0, 134.0 |
| Grow all 84, audited | 0.135 | 0.011/0.111 | 403.8 | 117.0 | 48.6 | 0.00 | 24.0, 24.0, 24.0, 24.0, 10.6, 10.2, 10.0, 9.8 |

## Evaluator-only feature diagnostic

At the end of matched training, 34.4% of shared novel reports have all their true monomials in the reuse learner's selected feature set; 71.9% reach the twelve-feature cap. This descriptive diagnostic compares saved features with hidden evaluator recipes after execution; it never supplies a learner with those recipes. Feature membership alone is not a correctness certificate. Irreversible early feature choices can use up the growth allowance before useful components are selected.


The holdout contains 192 arm/runs, 78,081 ordinary episodes, 61,790 paired audits and 61,440 panel contexts (727,513 post-setup SELECT executions). Whole-grid elapsed time, including artifact export, is 6.24 minutes.

Matched old-report panels changed 0 policy/prediction entries during novel learning. This is structural retention under authentic fixed report dispatch, not learned routing or a pointwise statistical guarantee.

Intervals use independent seed-level differences. Only the declared first24 comparison is primary; all secondary estimates and rankings are retained. The practical decision requires dominance of the entire fixed three-control set. A point estimate above .05 plus a lower bound above zero supports positive gain, not a 95 percent guarantee that the gain exceeds .05. Partial or failed runs are rejected by the analysis instead of silently averaged.

The supplied 84-feature grammar, exact scalar supervision, complete-table measurements and stationary authentic scopes remain strong assumptions. These results do not establish native CL-Bench/AgentCL superiority, open-ended representation discovery, unrestricted no-forgetting or alignment.
