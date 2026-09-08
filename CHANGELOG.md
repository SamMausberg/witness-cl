# v0.4.0, 8 September 2026

Extends the uploaded v3 commit, retaining its history, paper, and results.

- Adds an evidence-complete partial-transducer learner using executed action/output traces, not supplied world tables or observed hidden states. A valid finite state bound, deterministic stationary dynamics, public rewards and true resets remain assumptions.
- Integrates mutable online neural proposals, immutable candidate programs, paired exact continuation bounds, non-refundable risk and informative probe selection.
- Adds exact residual-program DAG IDs, strict bounded JSON proposals, a local-model synthetic driver (not executed), and explicit UNKNOWN/INCONSISTENT behavior.
- Records 38,400 primary held-out episode rows, 7,680 revised development rows, 6,720 initial pilot rows and 1,200 proposer-overwrite stress episodes. Full-history planner mean return remains better; late return ties.
- Adds 84 passing Python tests for a total of 355, 400 new C++ cases plus a range check, and 11 Lean attempts for a total of 50. No Lean compiler or native LLM benchmark ran.
- Provides a new compiled two-column LaTeX/TikZ paper, theory, failure cases, cost-matched evaluation plan and a final-code behavioral parity audit.

# 0.3.0

Full-horizon finite-model policy improvement and pre-execution risk debits;
incumbent-preserving updates with explicit trust-era resets; independent
likelihood, learned-feature isolation, and exact paired-simulation components.
New synthetic studies, 271 total Python tests, 632 C++ cases plus overflow check,
and 39 uncompiled Lean theorem attempts. No native LLM or GPU result.

# Changelog

## 0.2.0 (2026-09-08)

Corrected the fixed-class witness assumption: adding hypotheses requires replay
of the raw epoch history, not only the previously sufficient witness subset.
Added typed relational plans with public schema guards, strict proposal parsing,
independent SQLite checks, and aggregate-cube evaluation. Added recurrence-aware
inference epochs without external change-point labels and immutable old rules.

Implemented a local paired audit, one-observed-outcome randomized audit, and an
integrated proposing/exploring/auditing/promoting read-only agent. Added separate
fixed-share routing and fixed-feature projected online training controls. Wrote
conditional recovery, admission, information-limit, projection, and execution
proofs, with 16 new unverified Lean attempts and concrete CUDA source drafts.

Published new positive and negative seeded CPU experiments, raw episode records,
audit-power measurements, C++ oracle checks, and a rewritten two-column paper.
No language-model, native-benchmark, CUDA, or successful Lean execution occurred.
Version 0.1 results and paper remain available for comparison.
