# GH200 development runtime

This setup serves frozen open weights locally. It does not train the model, and
successful setup does not establish SQL competence, learning, or non-forgetting.
The separately frozen [development protocol](PROTOCOL.md) defines those checks.

## Observed hardware

The September 9, 2026 inventory identifies one NVIDIA GH200, CUDA compute
capability 9.0, on Linux aarch64. `nvidia-smi` reports **97,871 MiB (95.58 GiB)**
of GPU-visible device memory; **“GH200 480GB” is its product name, not a VRAM
measurement**. The initial inventory found no GPU processes and no locally
cached GGUF/safetensors in the inspected home, cache, and `/opt` directories.

Linux reports about 525.68 GiB of system-addressable memory, split across a
431.18 GiB NUMA node with CPUs and a 94.50 GiB memory-only NUMA node. The
memory-only node is consistent with GH200's CPU-addressable HBM. **Do not add
Linux `MemTotal` to `nvidia-smi` memory totals:** these interfaces can describe
overlapping physical memory. The saved inventory includes every NUMA memory
and CPU list, allowing a reader to inspect that interpretation.

The installed driver is 580.105.08; `nvidia-smi` advertises compatibility with
CUDA 13.0, while the actual compiler and installed PyTorch use CUDA 12.8.
The system Python is 3.10.12, below this repository's declared minimum.
Repository validation uses the local Python 3.12 environment. The server is a
native aarch64 CUDA build and does not depend on a Python CUDA wheel.

## Pinned inference configuration

| Item | Configuration |
|---|---|
| Model | Official `Qwen/Qwen3-32B-GGUF`, Q8_0, 34,817,718,912 bytes |
| Publisher revision | `938a7432affaec9157f883a87164e2646ae17555` |
| Weight SHA-256 | `2c50eb8aad05047dbf24fa014eb621adf552e14176cabe0c5db4ef38c91e2169` |
| Backend | llama.cpp `91f6a6cf361385700bbe15981f0f39909df77498` |
| Build | CUDA enabled, `CMAKE_CUDA_ARCHITECTURES=90`, release, 16 compilation workers |
| Server | `127.0.0.1:18084`, one sequence, all layers on GPU, Flash Attention |
| Context | 65,536 tokens, YaRN factor 2, original context 32,768 |
| Lifetime | At most 7,200 seconds per launch; study has a separate smaller budget |
| Alias | `witness-v10-qwen3-32b-q8` |

The model's native context is 32,768 tokens. The 65,536-token setting uses
the publisher's documented YaRN extension; it does not establish equal
quality at all context lengths. Long-context performance must be measured.
The loaded GGUF reports `n_ctx_train=40960`, which differs from the model card;
the explicit `yarn_original_context=32768` follows the publisher's documented
extension recipe. The backend's context warning is retained in the server log.
The publisher recommends distinct sampled settings for thinking and
non-thinking inference. Exact study decoding is recorded in its protocol.
Model and usage identities are checked on each response. Sources:
[publisher model card](https://huggingface.co/Qwen/Qwen3-32B-GGUF),
[pinned weight record](https://huggingface.co/Qwen/Qwen3-32B-GGUF/blob/938a7432affaec9157f883a87164e2646ae17555/Qwen3-32B-Q8_0.gguf),
[llama.cpp build instructions](https://github.com/ggml-org/llama.cpp/blob/91f6a6cf361385700bbe15981f0f39909df77498/docs/build.md).

The larger model, Linux/CUDA backend, context extension, and experiment
changes differ from v9. A cross-version score difference cannot isolate the
effect of the memory algorithm. Arms within the new study share the runtime.

## Reproduction

Keep weights, compilation output, and the local server key outside Git. The
default cache is `~/.local/share/witness-cl`; `--cache` can select another path.
The downloader makes at most 12 concurrent exact HTTP range requests, accepts
only the expected total size and SHA-256, and has a 1,500-second deadline.

```bash
.venv/bin/python tools/gh200_runtime.py inventory
.venv/bin/python tools/gh200_runtime.py download
git clone https://github.com/ggml-org/llama.cpp ~/.local/share/witness-cl/llama.cpp
git -C ~/.local/share/witness-cl/llama.cpp checkout 91f6a6cf361385700bbe15981f0f39909df77498
cmake -S ~/.local/share/witness-cl/llama.cpp -B ~/.local/share/witness-cl/llama.cpp/build \
  -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=90 -DCMAKE_BUILD_TYPE=Release \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_CURL=OFF
cmake --build ~/.local/share/witness-cl/llama.cpp/build --target llama-server -j 16
.venv/bin/python tools/gh200_runtime.py verify
.venv/bin/python tools/gh200_runtime.py serve
```

`serve` verifies model bytes, checks a clean pinned backend checkout, hashes
the binary, creates an owner-only local API-key file, and records the command
and device inventory. It binds explicitly to loopback, disables the web UI and
context shifting, and clears inherited `LLAMA_ARG_*` overrides. The key value
is never stored in repository artifacts. Interrupting the launcher terminates
its child server; the deadline also terminates that child.

In another terminal, run the generic transport smoke:

```bash
.venv/bin/python tools/gh200_runtime.py smoke
.venv/bin/python -m pytest -q tests/test_gh200_runtime.py
```

The smoke makes exactly two bounded calls: an arithmetic JSON answer with
thinking enabled, and a generic reflection with thinking disabled. It checks
the existing client's exact token-preflight endpoint, usage accounting,
model-alias check, and portable-schema path. It receives no benchmark questions
or evaluator answers. Its tokens and time are setup costs recorded separately.
Specify a fresh `--receipt artifacts/v10/runtime-<attempt>.json` when repeating
any action whose previous receipt must remain part of the research history.

The observed smoke passed both calls in **4.106 seconds**, using **339 tokens**
(76 prompt and 263 generated) with no unknown usage. The arithmetic call's
backend timing reports 65.44 generated tokens per second. This is a tiny
transport measurement, not representative task throughput. During the smoke,
`nvidia-smi` reported 49,682 MiB used and the server socket bound only to
`127.0.0.1:18084`.

## Evidence

The runtime config is [`configs/v10_gh200_runtime.json`](../../configs/v10_gh200_runtime.json).
Machine-readable receipts and build/download logs are in
[`artifacts/v10`](../../artifacts/v10). The initial single-stream download was
interrupted after measured throughput proved inadequate; its log is retained.
The parallel attempt independently downloads and verifies the whole file.
It completed download and SHA verification in 232.51 seconds. An early server
launch attempted before the verified filename existed failed before starting
a child process; its diagnostic log is also retained.
Transport smoke and study measurements are separate artifacts. Runtime
preconditions have 11 offline tests, including same-size corrupt model bytes,
truncation, non-loopback hosts, and invalid resource ceilings.
