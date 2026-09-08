# Execution and GH200 plan

## Reference paths implemented now

The compact archive and one-step learner run on the CPU. `relational.cube_evaluate`
shares row scans among typed plans using an exact nullable-Boolean aggregate cube.
The CPU benchmark changes row values each repetition, alternates execution order,
drops only two prespecified warmup repetitions, and records all raw times. It
compares against the Python direct interpreter, not a vectorized database engine
or a production LLM server. The current recurrent learner's timings do not silently
include this factorization: the cube is a separately validated bulk primitive.

`kernels/reference.hpp` is an independent C++ packed-mask oracle. Its 432 random
shape/tail/idempotence cases compiled with g++ and passed locally. Python tests
cover empty sets, negative values, partial words, honest growth replay, and
agreement with the relational/SQLite semantics.

## CUDA source, explicitly uncompiled

`witness_ops.cu` implements word filtering with one warp per 32 rules, warp
ballots, per-word min/max/count, and a second per-scope reduction. Separate query
consensus avoids reusing an observed input's predictions for a future query.
Outputs are validity-tagged, so an empty class never creates a certificate.
`cuda_test.cu` includes empty sets, INT_MIN/INT_MAX, different batch sizes and
ragged hypothesis tails. CUDA compilation and sanitizer runs are not recorded
successes. No CUDA device or nvcc was available during this revision.

Predictions/actions in the shipped mask kernel are int32; Boolean feedback is
uint8 and masks uint32. Signed int64 relational results require a checked range
before this path, a future int64 specialization, or CPU fallback. Do not truncate.

No tensor cores are needed for exact mask logic. The main streaming term is 4BH
bytes for a precomputed int32 prediction table, plus masks, summaries and outputs;
this is a data-size expression, NOT a measured bandwidth or speedup bound. A
plan's prediction generation can dominate. The aggregate-cube kernel should
produce grouped int64 sums once per snapshot, then assemble many plan outputs.
For large numbers of flags the cube grows exponentially and must be disabled.

For small H/B, avoid GPU launch and CPU/GPU synchronization entirely. Dispatch
only after timing both complete paths. Do not compare a hot, precomputed GPU
prediction table to a CPU path that still performs the interpreter work.

## Lifetime and graph invariants

Bind every scratch/result buffer to its request owner, snapshot/content epoch,
schema/grammar digest, full rule ordering, evidence generation, input/query,
feedback ID, precision, device, and stream dependency. Shape equality is not a
valid content identity. No shape-only data cache is included. Replaying a graph
requires updated data and correct dependencies; masks cannot be inherited from a
previous request. Raw evidence on host memory is not free to migrate to device.
The caller owns per-invocation buffers and synchronization. Candidate updates and
class growth cannot race an audit of a supposedly frozen snapshot.

## Run on GH200

```
make test
make cpp-check
make -C kernels cuda-check
```

The CUDA target compiles for sm_90, executes differential checks, then runs
compute-sanitizer memcheck and racecheck. Follow it with explicit multistream,
CUDA-graph capture/replay, changing-content, and allocation-reuse tests before
production use. Those lifecycle tests remain a required integration step, not
an included claim of production readiness.

Profile independent batches B in {1,8,32,128} and H in {32,256,4096,65536}, with
CPU resident, device resident, and transferred evidence separately. Measure
prediction construction, filter, consensus, end-to-end wall time, bytes moved,
active memory and total archive storage. Compare direct NumPy/C++, the current
cube, and a real database engine; use no device frequency or memory-bandwidth
claim without collecting it on the actual machine.

Projected trainable residuals should initially use existing matrix multiplication
operators and low-rank basis products, not an invented dense custom kernel.
Gather/scatter cost and feature computation must be charged. The foundation model
stays frozen in the primary path. GH200 LLM serving and public-benchmark execution
are not validated by CPU microbenchmarks.

Official references: NVIDIA CUDA Programming Guide, Hopper Tuning Guide, CUDA
Best Practices Guide, and PTX ISA. The paper bibliography gives their canonical
sources, consulted 8 September 2026.
