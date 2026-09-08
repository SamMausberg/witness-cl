# Recorded v0.3 results

All experiments below were executed on CPU. No real LLM, native public benchmark, or GPU experiment was run. Values are regenerated from JSON by `tools/v3_tables.py`.

## Stateful finite-world experiment

20 independent seeds, 64 episodes, two domains, seven arms: **17,920 full episode rows** in `episodes.csv.gz`. Early is the first 8 episodes; late is the last 16. Reward units are native sums, not percentages. Worst deficit is the largest cumulative anchor-relative deficit over all completed prefixes and seeds. Parentheses give sample standard deviation over seed-level means.

| Domain | Method | Early | Late | Worst deficit |
|---|---|---:|---:|---:|
| delayed_damage | Frozen anchor | 8.750 (0.000) | 8.750 (0.000) | 0 |
| compositional_navigation | Frozen anchor | 6.250 (0.000) | 6.250 (0.000) | 0 |
| delayed_damage | Immediate-reward greedy | 8.150 (1.382) | 8.150 (1.382) | 133 |
| compositional_navigation | Immediate-reward greedy | 9.312 (0.333) | 9.312 (0.333) | 0 |
| delayed_damage | Full-history optimistic | 12.869 (0.718) | 13.137 (0.620) | 2 |
| compositional_navigation | Full-history optimistic | 11.012 (0.557) | 11.262 (0.433) | 0 |
| delayed_damage | Uniform explore then plan | 10.900 (1.494) | 13.137 (0.620) | 19 |
| compositional_navigation | Uniform explore then plan | 10.131 (0.699) | 11.262 (0.433) | 4 |
| delayed_damage | Continuation, B=0 | 12.275 (0.484) | 12.562 (0.628) | 0 |
| compositional_navigation | Continuation, B=0 | 10.925 (0.406) | 11.262 (0.433) | 0 |
| delayed_damage | Continuation, B=4 | 12.850 (0.698) | 13.137 (0.620) | 2 |
| compositional_navigation | Continuation, B=4 | 11.000 (0.507) | 11.262 (0.433) | 0 |
| delayed_damage | Continuation, B=16 | 12.806 (0.698) | 13.137 (0.620) | 2 |
| compositional_navigation | Continuation, B=16 | 11.006 (0.494) | 11.262 (0.433) | 0 |

**Negative result:** B=4 has exactly the same late return as full-history optimistic planning on each seed in both domains. This is not an ICL comparison. B=0 gives a tighter safety restriction at a learning cost in delayed damage. The finite-family controller requires far more planning than the simple baseline.

## Online learned-feature diagnostic

20 seeds, 3 public scopes, 1,600 own-feedback interactions per scope, 4 arms: 384,000 interactions. Per-seed summaries and deterministic generation seeds are retained; individual neural feedback rows are not archived. Early/late accuracy is averaged across scopes (first 100/last 200 examples per scope). Forgetting is acquired held-out accuracy minus later held-out accuracy, averaged over old-scope checkpoints. All methods see the same public scope tag.

| Method | Early accuracy % | Late accuracy % | Mean forgetting, pp | Parameter bytes | Updates/seed |
|---|---:|---:|---:|---:|---:|
| Shared, equal width | 64.72 | 96.13 | 47.09 | 1352 | 4800 |
| Shared, near-matched parameters | 68.88 | 96.26 | 44.58 | 4040 | 4800 |
| Shared, online replay | 70.03 | 96.23 | 2.65 | 4040 | 9599 |
| Immutable learned modules | 74.87 | 95.43 | 0.00 | 4056 | 4800 |

The shared 72-hidden-unit model uses 4,040 parameter bytes; three frozen 24-hidden-unit modules use 4,056 bytes, a 16-byte difference. Replay adds 10,752 payload bytes, excluding Python object overhead, and roughly doubles updates. Versioning has exact zero measured old-logit drift, but slightly lower late current-task accuracy. This is not LLM fine-tuning or latent task routing.

## Independent diagnostics

Noise: 12/1000 sequences ever excluded the true model at nominal delta=0.05. Hard deletion excluded truth in 997/1000. Each sequence has 64 outcomes with 10% noise. This finite experiment is not proof of the nominal coverage guarantee.

Coupling: exact independent-rollout parity in 200 tests; mean environment calls 39.405 versus 64, a 38.43% reduction. Controller calls remain 64. No end-to-end LLM speedup is implied.

Cold CPU packing (median of 7 calls, H=6, S=32, A=4; values plus packing included):

| Models | Scalar milliseconds | Packed milliseconds |
|---:|---:|---:|
| 4 | 0.885 | 0.809 |
| 16 | 2.792 | 2.725 |
| 64 | 9.830 | 10.024 |

Packing yields essentially no material end-to-end gain in these tests. At 64 models it is slightly slower. The CUDA draft is uncompiled and untimed.

## Validation

271 Python tests pass; 432 legacy C++ cases and 200 new randomized C++ cases plus an overflow check pass. Lean compilation failed because the toolchain is unavailable. All 39 Lean declarations are attempts, not verified theorems. Tests do not prove implementation refinement or numerical correctness for arbitrary deployment.
