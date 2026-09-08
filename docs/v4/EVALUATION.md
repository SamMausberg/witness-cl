# Falsifiable evaluation plan

## Executed evidence

Development used 20 seeds, indices 0 through 19. A first seven-arm pilot produced 6,720 episodes and exposed repeated uninformative probes. The revised eight-arm development run produced 7,680 episodes. A local protocol file was written before the first held-out run on 100 seeds, indices 10000 through 10099. This is a local freeze, not an externally timestamped preregistration.

The final held-out run contains 38,400 episode rows: eight arms, 100 independently seeded hidden transducers, 48 episodes each, horizon four. The declared and true class is K=2, two actions, two outputs, 256 labelled transition tables. There are 19 distinct development tables and 81 distinct held-out tables, with six tables in both sets. Fresh random seeds are not disjoint held-out worlds or evidence for broad out-of-distribution transfer. Worlds are sampled with replacement from the same finite distribution.

A-B-A changes only the public reward function. It does not change the hidden transition model. The strongest comparator performs exact optimistic planning over all models consistent with its own full history and is not an LLM ICL agent. All methods have the same executed environment horizon, but total compute is not matched. Per-episode evaluator oracles are never fed to the learner. The weak last-output comparator is diagnostic, not a claim about state-of-the-art recurrent models.

Primary metric: prequential mean reward over all 48 episodes, paired by seed. Secondary: last-eight-episode A return, worst completed-prefix anchor deficit, incumbent violations, spent risk, state-cover size, update count, and mechanics runtime. The held-out objective diagnostic in raw JSON is not a credible new-domain transfer result: its reward weights preserve the original A output ordering. It is not used as a headline claim.

After the first held-out run, exact residual DAG IDs replaced repeated subtree comparisons and typed proposal registration was added. No held-out controller-selection rule was tuned. The complete primary run was repeated with final code. `holdout_audit.json` verifies identical reward, action/program, deficit, risk and cover-size rows for all 38,400 entries. Recorded timing and search counters can change. The original freeze hashes are retained.

## Most decisive result

The guided B16/B64 controller matches full-history planning on late-A return but is worse on mean return: -0.037083 reward per episode, paired-seed 95% t interval [-0.055284, -0.018883]. The central benchmark-superiority hypothesis is not supported by this mechanism study. The planner also has lower observed worst prefix deficit, 2 rather than 4. Guided B64 improves over the unguided ablation by 0.056667 [0.029805, 0.083528] and its observed worst prefix deficit falls from 40 to 4. Training adds only 0.014167 [0.007394, 0.020940] relative to the untrained B64 proposer. These secondary comparisons are descriptive, not multiplicity-corrected confirmatory findings.

## Next study, not executed

Run a staged native evaluation without passing environment internals, secret regimes, benchmark answers or evaluator counterfactuals to the agent. Start with one deterministic tool environment whose action/output schema and reset semantics are explicit. Then use at least three compatible CL-Bench domains and AgentCL's controlled, naive and held-out streams. Preserve the original task metric and episode schedule. An adapter that discretizes arbitrary text is not enough: its predictive sufficiency and state-bound coverage are hypotheses requiring independent tests.

Use the same fixed backbone, action permissions, prompt access, generation parameters, seeds and token ceiling for raw-history ICL, ACE/MemProbe where supported, an evolving-harness baseline, Witness without a checker, Witness without online training, and the full method. Include a learned-world point-estimate ablation and an oracle-representation upper bound. The oracle arm is diagnostic only. Count proposal generation, online gradient steps, validation, evidence storage, retrieval, environment rollouts, resets and retries in both token and wall-time budgets. No uncharged overnight replay or meta-search is allowed.

Freeze choices on development streams. Pair at least 20 test seeds per domain; use task-native schedules rather than artificially forcing 48 episodes. Report per-domain effects and paired uncertainty, not only a pooled mean. Repeat previous skills before and after new ones under both known objectives and hidden irrelevant-history distractors. Shadow evaluation must not change the learner's history or labels.

A concrete research target, not a measured result: at least five percentage points of task-native normalized learning gain over the strongest cost-matched baseline, with a positive lower 95% paired confidence bound, and no protected old-task success loss larger than two percentage points. Where native metrics are not percentages, predeclare equivalent thresholds using the benchmark normalization rather than converting arbitrary rewards after seeing results.

## Kill criteria

Reject the scalable continuation hypothesis if no valid small abstraction survives held-out continuation tests, if unmodelled behavior repeatedly invalidates certificates, or if bounded exact checks return UNKNOWN on over 90% of candidate changes across the selected native tasks. Reject the systems rationale if aggregate end-to-end wall-time/energy cost exceeds the strongest baseline without a compensating predeclared gain. Reject the learning claim if improvements disappear when token counts, proposal sampling and evaluator calls are matched. Reject retention claims if route changes, hidden drift, or compressed evidence make earlier certified behaviors fail beyond the declared margin.

The neural-proposer claim should be reduced or removed if a count-based ordering matches it once candidate-check budgets are equalized. The current small measured neural gain already argues against selling this as a major new training algorithm. The open-loop toy study does not resolve that question.

## Resource plan

The full included simulator/test suite runs on CPU and needs neither model weights nor API keys. For native experiments, use one GH200-class accelerator for a fixed local backbone, a multicore host with Docker for environment isolation, and sufficient host memory/disk to retain full traces and model versions. Exact required model memory depends on the chosen backbone and serving configuration; no model fit or throughput has been measured here.

Begin with a 100-episode native pilot and measure actual generated/input tokens, model throughput, environment time, checker throughput, peak host/GPU memory and storage growth. Budget the larger study from measured costs: total inference time is charged input/prefill work plus generated-token work at measured concurrency, plus non-overlapped environment/checker/training time. Do not turn a guessed tokens/second figure into an advertised GPU-hour result. Main symbolic scaling axes are K in {2,4,8,16}, horizon in {4,8,16}, number of outputs, and evidence length. The current explicit-tree implementation caps H at 12; H=16 requires a DAG-policy representation and new tests before that arm exists.

## Systems path

Optimize only after profiling. A reasonable next implementation uses structure-of-arrays partial transitions, exact residual DAG IDs, work queues grouped by time and unresolved slot, and deterministic min/max reductions. Preserve full equality checks or collision-resolving keys, checked reward accumulation, and cap-induced UNKNOWN. CPU parallelism is the first candidate because tiny irregular branches can cost more to launch than to check on a GPU. Caching may reuse a proof only for the same immutable programs, objective, reset contract and a descendant evidence class; enlarging the class invalidates it. None of this GPU path is implemented or timed in v4.
