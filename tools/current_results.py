#!/usr/bin/env python3
"""Generate current development tables and curves from complete saved receipts.

Runs remain separate: the second uses an adaptively revised solver and memory.
No confidence interval is computed from a selected single stream.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from tools.replay_study import validate_envelope

LABELS = {
    "full_history": "Full history",
    "evidence": "Exact evidence",
    "fragments": "Checked programs",
}


def memory_diagnostics(traces):
    """Describe distinct observable stages without inferring answer causality."""
    actions = [action for trace in traces for action in trace["actions"]]
    queries = [query for trace in traces for query in trace["queries"]]
    zero_sql_answers = [
        trace for trace in traces if trace["select_attempts"] == 0 and trace["answer"] is not None
    ]
    return {
        "attempted_use_actions": sum(action.get("action") == "USE" for action in actions),
        "attempted_compose_actions": sum(action.get("action") == "COMPOSE" for action in actions),
        "applicability_check_queries": sum(
            query["purpose"] == "applicability_check" for query in queries
        ),
        "rejected_guard_actions": sum(action.get("guard_passed") is False for action in actions),
        "guard_only_memory_actions": sum(
            "guard_passed" in action and "executed_fragment_digest" not in action
            for action in actions
        ),
        "executed_memory_actions": sum("executed_fragment_digest" in action for action in actions),
        "correct_episodes_with_guard_queries_without_fragment_execution": sum(
            trace["reward"] == 1
            and any(q["purpose"] == "applicability_check" for q in trace["queries"])
            and not any("executed_fragment_digest" in a for a in trace["actions"])
            for trace in traces
        ),
        "zero_sql_answers": len(zero_sql_answers),
        "zero_sql_correct_answers": sum(trace["reward"] == 1 for trace in zero_sql_answers),
        "attempted_memory_action_scope": "parsed USE/COMPOSE requests; malformed replies excluded",
        "executed_memory_action_scope": "proposed relation execution only; excludes guard-only queries and does not measure all memory influence",
        "guard_answer_causal_dependence_established": False,
    }


def summarize(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["status"] == "running":
        raise ValueError("cannot publish a live run as a completed result")
    if manifest["status"] not in (
        "completed",
        "competence_gate_failed",
        "stopped",
        "failed",
        "incomplete",
    ):
        raise ValueError("unsupported final run status")
    elapsed = manifest["elapsed_seconds"]
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("invalid recorded elapsed time")
    if (
        not manifest["source_unchanged"]
        or not manifest["client_config_unchanged"]
        or manifest["source_sha256_after"] != manifest["source_sha256"]
    ):
        raise ValueError("cannot publish a run whose frozen source/configuration changed")
    if {p.name for p in directory.glob("*.jsonl")} != set(manifest["raw_sha256"]):
        raise ValueError("raw file inventory mismatch")
    if (
        hashlib.sha256((directory / "summary.json").read_bytes()).hexdigest()
        != manifest["summary_sha256"]
    ):
        raise ValueError("summary hash mismatch")
    groups = []
    all_calls = []
    for name, digest in manifest["raw_sha256"].items():
        path = directory / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("raw hash mismatch")
        traces = [json.loads(line) for line in path.read_text().splitlines()]
        if not traces:
            continue
        calls = [
            call
            for trace in traces
            for call in trace["model_calls"]
            if call.get("generation_attempted")
        ]
        all_calls.extend(calls)
        warm = [
            trace for trace in traces if trace["phase"] == "ordinary" and trace["episode_index"] < 8
        ]
        phases = {}
        for phase in ("ordinary", "old_before", "old_after", "final"):
            rows = [trace for trace in traces if trace["phase"] == phase]
            phases[phase] = {
                "n": len(rows),
                "correct": sum(trace["reward"] == 1 for trace in rows),
                **memory_diagnostics(rows),
            }
        groups.append(
            {
                "arm": traces[0]["arm"],
                "seed": traces[0]["seed"],
                "condition": traces[0]["condition"],
                "warm_n": len(warm),
                "warm_correct": sum(trace["reward"] == 1 for trace in warm),
                "warm_rewards": [trace["reward"] for trace in warm],
                "phases": phases,
                "episodes": len(traces),
                "selects": sum(trace["select_attempts"] for trace in traces),
                "calls": len(calls),
                "cost_scope": "all recorded phases, including partial episodes and learning checks",
                "warm_costs": {
                    "selects": sum(trace["select_attempts"] for trace in warm),
                    "calls": sum(
                        call.get("generation_attempted") is True
                        for trace in warm
                        for call in trace["model_calls"]
                    ),
                    "known_tokens": sum(
                        call["usage"]["total_tokens"]
                        for trace in warm
                        for call in trace["model_calls"]
                        if call.get("generation_attempted") is True
                        and call.get("usage") is not None
                    ),
                },
                "known_tokens": sum(
                    call["usage"]["total_tokens"] for call in calls if call.get("usage")
                ),
                "unknown_usage_calls": sum(call.get("usage") is None for call in calls),
                "admissions": sum(
                    trace.get("discovery_repair", {}).get("status") == "admitted"
                    for trace in traces
                ),
                **memory_diagnostics(traces),
                "final_memory_bytes": traces[-1]["memory_bytes"],
                "active_memory_bytes": traces[-1]["memory_snapshot"]["active_memory_bytes"],
                "eviction_events": sum(
                    event.get("kind") == "fifo_eviction"
                    for event in traces[-1]["memory_snapshot"]["events"]
                ),
            }
        )
    known = sum(call["usage"]["total_tokens"] for call in all_calls if call.get("usage"))
    if (
        known != manifest["total_budget"]["total_tokens"]
        or len(all_calls) != manifest["total_budget"]["calls"]
    ):
        raise ValueError("global resource ledger mismatch")
    # Validate the summary, paired schedule, all local/global counters and native
    # request configuration. This checks internal receipts, not model execution
    # or current-working-tree equality to an earlier frozen learner revision.
    envelope = validate_envelope(directory, manifest)
    unknown = sum(call.get("usage") is None for call in all_calls)
    return {
        "directory": str(
            directory.relative_to(ROOT) if directory.is_relative_to(ROOT) else directory
        ),
        "status": manifest["status"],
        "seed": manifest["seeds"][0] if len(manifest["seeds"]) == 1 else None,
        "seeds": manifest["seeds"],
        "conditions": manifest["conditions"],
        "elapsed_seconds": manifest["elapsed_seconds"],
        "manifest_sha256": hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest(),
        "known_tokens": known,
        "calls": len(all_calls),
        "unknown_usage_calls": unknown,
        "known_prompt_tokens": sum(
            call["usage"]["prompt_tokens"] for call in all_calls if call.get("usage") is not None
        ),
        "known_completion_tokens": sum(
            call["usage"]["completion_tokens"]
            for call in all_calls
            if call.get("usage") is not None
        ),
        "token_total_complete": unknown == 0,
        "unknown_token_count": None if unknown else 0,
        "required_records_complete": manifest["required_records_complete"],
        "source_unchanged": manifest["source_unchanged"],
        "usage_verified": manifest["usage_verified"],
        "receipt_consistency": envelope,
        "cost_scope": "all recorded phases, including partial episodes and learning checks",
        "accuracy_scope": "warm_n/warm_correct cover only the first eight ordinary questions; phases reported separately",
        "groups": sorted(
            groups, key=lambda row: (row["seed"], row["condition"], list(LABELS).index(row["arm"]))
        ),
    }


def render(runs, output, paper_output=None):
    if not runs:
        raise ValueError("at least one finalized run is required")
    if len({run["directory"] for run in runs}) != len(runs):
        raise ValueError("duplicate run would double-count resource costs")
    output = Path(output)
    paper_output = ROOT / "paper" if paper_output is None else Path(paper_output)
    output.mkdir(parents=True, exist_ok=True)
    paper_output.mkdir(parents=True, exist_ok=True)
    result = {
        "native_benchmark": False,
        "confirmatory": False,
        "studies": runs,
        "total_calls": sum(run["calls"] for run in runs),
        "total_known_tokens": sum(run["known_tokens"] for run in runs),
        "unknown_usage_calls": sum(run["unknown_usage_calls"] for run in runs),
        "total_study_seconds": sum(run["elapsed_seconds"] for run in runs),
        "setup_usage_scope": "runtime-smoke.json is separate; no task episodes used in setup",
        "aggregate_scope": "resource expenditure only; adaptive streams have no pooled accuracy or significance estimate",
        "reporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    table = [
        r"\begin{tabular}{llrrrrrr}",
        r"\toprule",
        r"Stream & Method & Episodes & Warm & All SELECTs & All calls & Known tokens & Admitted\\",
        r"\midrule",
    ]
    for run in runs:
        for row in run["groups"]:
            table.append(
                f"{row['seed']} & {LABELS[row['arm']]} & {row['episodes']} & {row['warm_correct']}/{row['warm_n']} & "
                f"{row['selects']:,} & {row['calls']:,} & {row['known_tokens']:,} & {row['admissions']}"
                + r"\\"
            )
    table += [r"\bottomrule", r"\end{tabular}"]
    table += [
        r"\par\smallskip{\footnotesize Costs cover all recorded phases; the Warm column covers only the first eight ordinary questions. Known tokens exclude unmeasured usage.}"
    ]
    (paper_output / "gh200_table.tex").write_text("\n".join(table) + "\n")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "pdf.fonttype": 42})
    panels = [
        {
            "seed": seed,
            "condition": condition,
            "groups": [
                row
                for row in run["groups"]
                if row["seed"] == seed and row["condition"] == condition
            ],
        }
        for run in runs
        for seed in run["seeds"]
        for condition in run["conditions"]
        if any(row["seed"] == seed and row["condition"] == condition for row in run["groups"])
    ]
    if not panels:
        raise ValueError("no recorded episode is available to plot")
    figure, axes = plt.subplots(1, len(panels), figsize=(3.4 * len(panels), 2.5), squeeze=False)
    styles = {
        "full_history": ("#2a5674", "o", "-"),
        "evidence": ("#a34b19", "s", "--"),
        "fragments": ("#48794b", "^", ":"),
    }
    for axis, run in zip(axes[0], panels):
        for row in run["groups"]:
            rewards = row["warm_rewards"]
            x = np.arange(1, len(rewards) + 1)
            color, marker, line = styles[row["arm"]]
            axis.plot(
                x,
                np.cumsum(rewards) / x,
                color=color,
                marker=marker,
                linestyle=line,
                markersize=4,
                label=LABELS[row["arm"]],
            )
        axis.axhline(7 / 8, color="0.65", linestyle=":", linewidth=0.8)
        axis.set(
            title=f"Development stream {run['seed']} ({run['condition']})",
            xlabel="Warm questions seen",
            ylim=(-0.04, 1.04),
            xticks=range(1, 9),
        )
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="y", alpha=0.15)
    axes[0, 0].set_ylabel("Cumulative warm accuracy")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(
        handles, labels, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.03)
    )
    figure.tight_layout(rect=(0, 0.08, 1, 1))
    for extension in ("pdf", "png"):
        figure.savefig(paper_output / f"gh200_warm.{extension}", dpi=220, bbox_inches="tight")
    plt.close(figure)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/v10")
    parser.add_argument("--paper-output", type=Path, default=ROOT / "paper")
    args = parser.parse_args()
    result = render(
        [summarize(path.resolve()) for path in args.directories], args.output, args.paper_output
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("total_calls", "total_known_tokens", "total_study_seconds")
            }
        )
    )


if __name__ == "__main__":
    main()
