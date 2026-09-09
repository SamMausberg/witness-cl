# Runtime feasibility at the original pilot pause

The unchanged serial executor projects **71.9 hours** for the original **17,664 episodes**, using timing from its **161 recorded episodes**. A two-hour completion would require **36.0 times** the measured end-to-end rate. This extrapolation is operational evidence, not a guaranteed full-study duration.

The original assignment remains incomplete: **17,503 episodes are unexecuted**. All **178 call journals** match their episode receipts, with no pending or orphan calls and no unknown token usage. The pause was recorded at 2026-09-09T22:50:19.187098+00:00.

| Arm | Phase | Episodes | Calls | Prompt tokens | Generated tokens | Episode seconds | Decode seconds | Prefill seconds |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| ace | old_before | 45 | 46 | 135,679 | 44,358 | 837.32 | 803.44 | 26.75 |
| ace | ordinary | 8 | 24 | 69,065 | 14,575 | 279.99 | 264.04 | 13.70 |
| delayed | old_before | 46 | 46 | 515,301 | 21,761 | 507.25 | 399.56 | 101.03 |
| delayed | ordinary | 8 | 8 | 48,539 | 3,913 | 81.73 | 71.24 | 9.59 |
| full_history | old_before | 46 | 46 | 730,489 | 22,232 | 563.24 | 409.66 | 145.11 |
| full_history | ordinary | 8 | 8 | 65,024 | 4,245 | 91.31 | 77.49 | 12.81 |

The prefix averages 14.66 seconds, 9,715 prompt tokens and 690 generated tokens per episode. Backend throughput is 54.8 generated tokens per decode second and 5,062 prompt tokens per prefill second. Prefill alone extrapolates to 9.4 hours at this workload and rate.

**Limits:** These are early-prefix timings, comprising initial learning and old-before probes only. They do not estimate accuracy, retention or mechanism effects. Later contexts and generations may be longer. Summed episode durations omit startup, auditing and scheduling gaps. No speculative batching speedup is assumed. These observations cannot guarantee the duration or completion of the separate 240-episode diagnostic.

The [machine-readable receipt](time-budget-feasibility.json) binds the [pause receipt](pilot-dense-v2/time-budget-amendment-pause.json), source freeze, schedule and both raw JSON directories by SHA-256. No model calls or raw-source changes were made.

To reproduce the timing aggregation and verify the bound directories, run from the repository root:

```python
import collections, hashlib, json
from pathlib import Path
r = json.loads(Path("artifacts/campaign/time-budget-feasibility.json").read_text())
s = Path(r["source_binding"]["study"])
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(p):
    h = {str(f.relative_to(p)): sha(f) for f in sorted(p.rglob("*.json"))}
    return hashlib.sha256(json.dumps(h, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
b = r["source_binding"]
assert sha(Path(b["pause_receipt"])) == b["pause_receipt_sha256"]
assert digest(s / "episodes") == b["episodes_sha256"]
assert digest(s / "calls") == b["journals_sha256"]
g = collections.defaultdict(collections.Counter)
for f in sorted((s / "episodes").glob("*.json")):
    e = json.loads(f.read_text()); t = e["trace"]; a = g[e["arm"], e["phase"]]
    a["episodes"] += 1; a["episode_elapsed_seconds"] += t["elapsed_seconds"]
    for i, c in enumerate(t["model_calls"]):
        assert json.loads((s / "calls" / e["key"] / f"{i:03d}.json").read_text()) == {"calls": [c], "state": "recorded"}
        a["calls"] += 1
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"): a[k] += c["usage"][k]
        for k in ("inference_seconds", "tokenization_seconds"): a[k] += c[k]
        a["decode_seconds"] += c["backend_timings"]["predicted_ms"] / 1000
        a["prefill_seconds"] += c["backend_timings"]["prompt_ms"] / 1000
assert [{"arm": k[0], "phase": k[1], **v} for k, v in sorted(g.items())] == r["per_arm_phase"]
print(json.dumps(r["naive_linear_extrapolation"], indent=2))
```
