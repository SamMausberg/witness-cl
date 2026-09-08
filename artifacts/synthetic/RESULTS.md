# Executed synthetic mechanism check

These are symbolic CPU controls, not language-model or CL-Bench results.

| Scenario | Method | Reward | Late reward | Certified fraction | Wrong certificates / seed |
|---|---|---:|---:|---:|---:|
| interleaved | stateless | 14.61% | 14.64% | 0.00% | 0.00 |
| interleaved | window_replay_24 | 52.84% | 53.28% | 38.37% | 0.00 |
| interleaved | lookup_bounded_24 | 25.56% | 25.47% | 0.00% | 0.00 |
| interleaved | lookup_full | 78.12% | 98.26% | 0.00% | 0.00 |
| interleaved | full_replay_induction | 94.17% | 100.00% | 92.34% | 0.00 |
| interleaved | witness | 94.17% | 100.00% | 92.34% | 0.00 |
| novel_inputs | stateless | 15.18% | 13.26% | 0.00% | 0.00 |
| novel_inputs | window_replay_24 | 51.68% | 50.05% | 38.26% | 0.00 |
| novel_inputs | lookup_bounded_24 | 41.56% | 29.82% | 0.00% | 0.00 |
| novel_inputs | lookup_full | 78.19% | 68.72% | 0.00% | 0.00 |
| novel_inputs | full_replay_induction | 93.83% | 100.00% | 91.99% | 0.00 |
| novel_inputs | witness | 93.83% | 100.00% | 91.99% | 0.00 |
| public_shift | stateless | 15.29% | 15.99% | 0.00% | 0.00 |
| public_shift | window_replay_24 | 51.50% | 50.60% | 37.33% | 0.00 |
| public_shift | lookup_bounded_24 | 26.20% | 26.74% | 0.00% | 0.00 |
| public_shift | lookup_full | 58.33% | 58.67% | 0.00% | 0.00 |
| public_shift | full_replay_induction | 88.27% | 88.20% | 84.66% | 0.00 |
| public_shift | witness | 88.27% | 88.20% | 84.66% | 0.00 |
| hidden_shift | stateless | 15.29% | 15.99% | 0.00% | 0.00 |
| hidden_shift | window_replay_24 | 51.50% | 50.60% | 37.33% | 0.00 |
| hidden_shift | lookup_bounded_24 | 26.20% | 26.74% | 0.00% | 0.00 |
| hidden_shift | lookup_full | 42.89% | 27.79% | 0.00% | 0.00 |
| hidden_shift | full_replay_induction | 52.12% | 15.91% | 43.55% | 4.00 |
| hidden_shift | witness | 52.12% | 15.91% | 43.55% | 4.00 |
| misspecified | stateless | 15.77% | 14.43% | 0.00% | 0.00 |
| misspecified | window_replay_24 | 37.99% | 22.68% | 27.30% | 10.90 |
| misspecified | lookup_bounded_24 | 40.89% | 28.46% | 0.00% | 0.00 |
| misspecified | lookup_full | 77.89% | 68.12% | 0.00% | 0.00 |
| misspecified | full_replay_induction | 50.87% | 14.09% | 43.03% | 4.00 |
| misspecified | witness | 50.87% | 14.09% | 43.03% | 4.00 |
