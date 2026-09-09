#!/usr/bin/env python3
"""Durable stage launcher for the accepted campaign; all numerical gates stay upstream.

Both qualification schedules freeze before either executes. Each subsequent
stage is frozen only after complete, audited prerequisites. The launcher never
changes a learner, substitutes a stream, or interprets an early favorable score.
Native and matched-history assays use their separate domain-specific launchers.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from witness_cl.campaign_io import canonical, read, save, sha, study_lock

STAGES = ("qualification", "development", "sizing", "confirmation", "diagnostics")


def utc():
    return datetime.now(timezone.utc).isoformat()


def seeds_for(job, *, confirmation_n=None):
    if "seeds" in job:
        values = job["seeds"]
    else:
        count = job["streams"]
        if count == "from_audited_sizing_power":
            count = confirmation_n
        if type(count) is not int or count < 1:
            raise ValueError("positive fixed stream count required")
        values = list(range(job["seed_start"], job["seed_start"] + count))
    if not values or len(set(values)) != len(values) or any(type(s) is not int or s < 0 for s in values):
        raise ValueError("distinct nonnegative integer stream seeds required")
    return values


def validate_plan(plan, *, confirmation_n=None):
    if plan["schema_version"] != 1 or len(plan["qualification"]) != 2:
        raise ValueError("two prospectively assigned qualification studies required")
    jobs = [*plan["qualification"], plan["development"], plan["sizing"], *plan["diagnostics"]]
    if confirmation_n is not None:
        jobs.append(plan["confirmation"])
    if len({job["name"] for job in jobs}) != len(jobs):
        raise ValueError("unique stage directory names required")
    seen = set()
    for job in jobs:
        if Path(job["name"]).name != job["name"] or job["name"] in {".", ".."}:
            raise ValueError("stage names must be simple directory names")
        seeds = set(seeds_for(job, confirmation_n=confirmation_n))
        if seen & seeds:
            raise ValueError("observational stages cannot share stream seeds")
        seen |= seeds
    assay = plan["separate_assay"]
    for prefix in ("", "development_"):
        values = set(range(assay[prefix + "seed_start"], assay[prefix + "seed_start"] + assay[prefix + "streams"]))
        if values & seen:
            raise ValueError("matched-history assay streams overlap main stages")
        seen |= values
    if plan["sizing"]["streams"] != 32 or plan["arms"] != ["full_history", "ace", "delayed"]:
        raise ValueError("accepted sizing and primary arms are fixed")
    return plan


class Sequence:
    def __init__(self, out, plan_path, runtime_config, runtime_receipt, key_file, *, python=None):
        self.out = Path(out).resolve()
        self.plan_path = Path(plan_path).resolve()
        self.plan = validate_plan(read(self.plan_path))
        self.runtime_config = Path(runtime_config).resolve()
        self.runtime_receipt = Path(runtime_receipt).resolve()
        self.key_file = Path(key_file).resolve()
        self.python = str(Path(python or sys.executable).absolute())
        self.out.mkdir(parents=True, exist_ok=True)
        frozen_plan = self.out / "sequence.json"
        if frozen_plan.exists():
            if read(frozen_plan)["plan"] != self.plan:
                raise ValueError("sequence plan changed; preserve this campaign and use a new output directory")
        else:
            save(frozen_plan, {"plan": self.plan, "plan_sha256": sha(self.plan_path),
                               "created_utc": utc(), "launcher_sha256": sha(Path(__file__)),
                               "scope": "stage/seed registry; each study separately freezes its actual solver and data"})

    def invoke(self, script, arguments, log_name):
        logfile = self.out / "stage-logs" / (log_name + ".log")
        logfile.parent.mkdir(exist_ok=True)
        command = [self.python, "-u", str(script), *map(str, arguments)]
        # Credentials are passed only as a file path and are never read or logged.
        print(canonical({"time": utc(), "stage": log_name, "status": "starting"}), flush=True)
        with logfile.open("a") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True,
                           env={**os.environ, "PYTHONUNBUFFERED": "1"})
        print(canonical({"time": utc(), "stage": log_name, "status": "completed"}), flush=True)

    def freeze(self, job, kind, *, confirmation_n=None):
        directory = self.out / job["name"]
        seeds = seeds_for(job, confirmation_n=confirmation_n)
        arms = ["full_history"] if kind == "qualification" else self.plan["arms"]
        if (directory / "freeze.json").exists():
            frozen = read(directory / "freeze.json")
            if any(frozen[key] != value for key, value in {
                "kind": kind, "seeds": seeds, "arms": arms, "conditions": job["conditions"],
            }.items()):
                raise ValueError("existing study differs from the frozen stage schedule")
            return directory
        args = ["freeze", "--out", directory, "--kind", kind, "--seeds", *seeds,
                "--arms", *arms, "--conditions", *job["conditions"],
                "--runtime-config", self.runtime_config, "--runtime-receipt", self.runtime_receipt,
                "--key-file", self.key_file]
        if kind in {"development", "sizing", "confirmation"}:
            args += ["--qualification-report", *[self.out / job["name"] for job in self.plan["qualification"]]]
        if kind == "confirmation":
            args += ["--power-report", self.out / self.plan["sizing"]["name"] / "power.json",
                     "--development-report", self.out / self.plan["development"]["name"]]
        self.invoke(ROOT / "tools/campaign.py", args, job["name"] + "-freeze")
        return directory

    def execute(self, directory, *, mechanism=False):
        script = directory / "sources/tools/campaign.py"
        self.invoke(script, ["resume", "--out", directory, "--key-file", self.key_file], directory.name + "-run")
        self.invoke(script, ["audit", "--out", directory], directory.name + "-audit")
        summary = read(directory / "summary.json")
        audited = read(directory / "audit.json")
        if not summary["complete"] or not audited["complete"] or not audited["consistent"]:
            raise ValueError("incomplete stage cannot advance")
        if summary["cost"]["unknown_usage_calls"]:
            raise ValueError("unknown usage cannot advance")
        if mechanism:
            self.invoke(script, ["mechanism", "--out", directory], directory.name + "-mechanism")
        return summary

    def run(self, through):
        if through not in STAGES:
            raise ValueError("unknown terminal stage")
        # Both freezes precede every qualification model call, including after restart.
        directories = [self.freeze(job, "qualification") for job in self.plan["qualification"]]
        qualifications = [self.execute(directory) for directory in directories]
        if not all(report["qualified"] for report in qualifications):
            raise ValueError("completed qualification failed; preserve all outcomes and revise development explicitly")
        if through == "qualification":
            return
        development = self.freeze(self.plan["development"], "development")
        self.execute(development, mechanism=True)
        if through == "development":
            return
        mechanism = read(development / "audit-mechanism.json")
        events = [event for event in mechanism["events"] if event["qualifying_event"]]
        if len(events) < 5 or len({event["seed"] for event in events}) < 3:
            raise ValueError("mechanism development gate failed; do not spend sizing or confirmation streams")
        sizing = self.freeze(self.plan["sizing"], "sizing")
        self.execute(sizing, mechanism=True)
        self.invoke(sizing / "sources/tools/campaign_results.py", ["size", "--out", sizing], "sizing-power")
        if through == "sizing":
            return
        n = read(sizing / "power.json")["streams"]
        validate_plan(self.plan, confirmation_n=n)
        confirmation = self.freeze(self.plan["confirmation"], "confirmation", confirmation_n=n)
        self.execute(confirmation, mechanism=True)
        self.invoke(confirmation / "sources/tools/campaign_results.py", ["analyze", "--out", confirmation], "confirmation-analysis")
        if through == "confirmation":
            return
        # Diagnostics run even when one or more confirmatory endpoints fail.
        for job in self.plan["diagnostics"]:
            directory = self.freeze(job, "diagnostic")
            self.execute(directory, mechanism=True)
            self.invoke(directory / "sources/tools/campaign_results.py", ["diagnose", "--out", directory],
                        directory.name + "-analysis")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=ROOT / "configs/campaign_sequence.json")
    parser.add_argument("--runtime-config", type=Path, default=ROOT / "configs/campaign_runtime.json")
    parser.add_argument("--runtime-receipt", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--through", choices=STAGES, default="development")
    args = parser.parse_args()
    sequence = Sequence(args.out, args.plan, args.runtime_config, args.runtime_receipt, args.key_file)
    with study_lock(sequence.out):
        status = {"started_utc": utc(), "through": args.through, "pid": os.getpid(), "status": "running"}
        save(sequence.out / "sequence-status.json", status)
        try:
            sequence.run(args.through)
        except BaseException as exc:
            status.update(status="stopped", error_type=type(exc).__name__, error=str(exc)[:1000])
            raise
        else:
            status["status"] = "completed_through_requested_stage"
        finally:
            status["finished_utc"] = utc()
            save(sequence.out / "sequence-status.json", status)


if __name__ == "__main__":
    main()
