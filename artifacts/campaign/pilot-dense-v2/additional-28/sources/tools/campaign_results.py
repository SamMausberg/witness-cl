#!/usr/bin/env python3
"""Derive paired-stream analysis exclusively from complete audited campaign data."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from witness_cl.campaign_analysis import analyze, size_study, joint_power_simulation, diagnose
from witness_cl.campaign_io import read, save, sha, canonical
from tools.campaign import artifact_digest


def audited_study(directory):
    directory = Path(directory)
    frozen = read(directory / "freeze.json")
    summary = read(directory / "summary.json")
    audit = read(directory / "audit.json")
    if (
        audit.get("consistent") is not True
        or audit.get("complete") is not True
        or audit.get("freeze_sha256") != sha(directory / "freeze.json")
        or audit.get("summary_sha256") != sha(directory / "summary.json")
        or audit.get("records_sha256") != artifact_digest(directory / "episodes")
        or audit.get("journals_sha256") != artifact_digest(directory / "calls")
        or audit.get("cost", {}).get("unknown_usage_calls") != 0
    ):
        raise ValueError("complete audit bound to current artifacts required")
    if frozen["contains_test_double_calls"]:
        raise ValueError("scripted software tests are not experimental measurements")
    if set(frozen["arms"]) != {
        "full_history",
        "ace",
        "delayed",
    }:
        raise ValueError("the three primary arms are required")
    if not summary["complete"] or summary["cost"]["unknown_usage_calls"]:
        raise ValueError("all phases and complete measured costs are required")
    return frozen, summary


def arm_metrics(summary, seed, condition):
    expected = {"ordinary": 24, "old_before": 64, "old_after": 64, "final": 32}
    arms = {}
    for arm in ("full_history", "ace", "delayed"):
        selected = [g for g in summary["groups"] if g["seed"] == seed and g["arm"] == arm
                    and g["condition"] == condition]
        if len(selected) != 1:
            raise ValueError("missing or duplicated paired arm")
        group = selected[0]
        if any(group["phases"][p]["n"] != n for p, n in expected.items()):
            raise ValueError("missing planned panel records")
        arms[arm] = {
            "future_accuracy": group["phases"]["final"]["correct"] / 32,
            "old_before_accuracy": group["phases"]["old_before"]["correct"] / 64,
            "old_after_accuracy": group["phases"]["old_after"]["correct"] / 64,
            "total_tokens": group["cost"]["total_tokens"],
        }
    return arms


def stream_metrics(directory):
    frozen, summary = audited_study(directory)
    if frozen["conditions"] != ["reuse"]:
        raise ValueError("the primary paired-reuse study is required")
    rows = []
    for seed in frozen["seeds"]:
        arms = arm_metrics(summary, seed, "reuse")
        rows.append({"seed": seed, "complete": True, "arms": arms})
    return frozen, rows


def process(directory, command):
    directory = Path(directory)
    if command == "diagnose":
        frozen, summary = audited_study(directory)
        if frozen["kind"] != "diagnostic":
            raise ValueError("only separately frozen diagnostic streams may enter diagnostics")
        rows = [{"seed": seed, "complete": True, "conditions": {
            condition: arm_metrics(summary, seed, condition) for condition in frozen["conditions"]}}
            for seed in frozen["seeds"]]
        result = diagnose(rows, conditions=frozen["conditions"])
        filename = "diagnostic-analysis.json"
    elif command == "size":
        frozen, rows = stream_metrics(directory)
        if frozen["kind"] != "sizing":
            raise ValueError("only the designated32-stream pilot may size confirmation")
        result = size_study(rows)
        attempts = []
        while True:
            simulation = joint_power_simulation(rows, result["streams"])
            attempts.append(simulation)
            if simulation["one_sided_95_mc_lower"] > 0.80:
                break
            result["streams"] += max(1, (result["streams"] + 19) // 20)
        result["joint_power_simulations"] = attempts
        filename = "power.json"
    else:
        frozen, rows = stream_metrics(directory)
        if frozen["kind"] != "confirmation":
            raise ValueError("development outcomes cannot confirm the claim")
        result = analyze(rows, frozen_n=len(frozen["seeds"]))
        filename = "analysis.json"
    result.update(
        freeze_sha256=sha(directory / "freeze.json"),
        audit_sha256=sha(directory / "audit.json"),
        summary_sha256=sha(directory / "summary.json"),
        analysis_source_sha256=sha(ROOT / "src/witness_cl/campaign_analysis.py"),
    )
    save(directory / filename, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("size", "analyze", "diagnose"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(canonical(process(args.out, args.command)))


if __name__ == "__main__":
    main()
