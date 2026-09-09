#!/usr/bin/env python3
"""Execute a frozen collection plan after an already running development job.

This process never changes a learner or retries a failed command. Scientific
gates, receipt recovery, and all model calls remain in the existing runners.
Completion means collection and reporting finished, not that a claim passed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from witness_cl.campaign_io import canonical, read, save, sha, study_lock


def utc():
    return datetime.now(timezone.utc).isoformat()


def validate_plan(plan):
    if plan.get("schema_version") != 1:
        raise ValueError("collection plan schema must be 1")
    if not Path(plan["cwd"]).is_absolute():
        raise ValueError("absolute working directory required")
    inputs = plan.get("source_inputs")
    if (not isinstance(inputs, list) or not inputs or len(inputs) != len(set(inputs))
            or any(not isinstance(value, str) or not Path(value).is_absolute() for value in inputs)):
        raise ValueError("explicit distinct absolute source inputs required")
    adopted = plan["adopt_sequence"]
    if (not Path(adopted["directory"]).is_absolute()
            or adopted["through"] != "development"
            or type(adopted["pid"]) is not int or adopted["pid"] <= 0):
        raise ValueError("identified development sequence required")
    names = set()
    if not plan["commands"]:
        raise ValueError("at least one fixed command required")
    for command in plan["commands"]:
        name, argv = command["name"], command["argv"]
        if (not isinstance(name, str) or not name or Path(name).name != name
                or name in {".", ".."} or name in names):
            raise ValueError("unique simple command names required")
        names.add(name)
        if (not isinstance(argv, list) or not argv
                or any(not isinstance(value, str) or not value or "\0" in value for value in argv)
                or not Path(argv[0]).is_absolute()):
            raise ValueError("commands require an argv list and absolute executable; no shell")
        for value in argv:
            if value.endswith(".py"):
                path = Path(value)
                if not path.is_absolute():
                    path = Path(plan["cwd"]) / path
                if str(path.resolve()) not in inputs or not path.is_file():
                    raise ValueError("Python entrypoints must be frozen present source inputs before supervision")
    return plan


def source_hashes(plan):
    # Explicit inputs never grow when a command creates a result or freeze.
    # The collection-plan author includes imported source closures here. Study
    # freezes already exist; each runner also checks copied sources before calls.
    paths = {Path(__file__).resolve(), *(Path(value) for value in plan["source_inputs"])}
    if any(path.suffix == ".key" or not path.is_file() for path in paths):
        raise ValueError("source inputs must exist and must not be credential files")
    return {str(path): sha(path) for path in sorted(paths)}


def process_identity(pid, *, proc_root=Path("/proc")):
    directory = Path(proc_root) / str(pid)
    try:
        stat = (directory / "stat").read_text().rsplit(")", 1)[1].split()
        command = (directory / "cmdline").read_bytes()
    except FileNotFoundError:
        return None
    return {"pid": pid, "start_ticks": stat[19],
            "command_sha256": hashlib.sha256(command).hexdigest()}


class Supervisor:
    def __init__(self, out, plan_path):
        self.out = Path(out).resolve()
        self.plan_path = Path(plan_path).resolve()
        self.plan = validate_plan(read(self.plan_path))
        self.out.mkdir(parents=True, exist_ok=True)
        binding = self.out / "collection-plan.json"
        if binding.exists():
            self.bound = read(binding)
            if (self.bound["plan"] != self.plan
                    or self.bound["source_sha256"] != source_hashes(self.plan)):
                raise ValueError("collection plan or launcher sources changed; preserve original run")
        else:
            adopted = self.plan["adopt_sequence"]
            state = read(Path(adopted["directory"]) / "sequence-status.json")
            if state.get("pid") != adopted["pid"] or state.get("through") != adopted["through"]:
                raise ValueError("adopted main sequence identity differs")
            self.bound = {"plan": self.plan, "created_utc": utc(),
                          "source_sha256": source_hashes(self.plan),
                          "adopted_process": process_identity(adopted["pid"])}
            save(binding, self.bound)

    def adopt_state(self):
        adopted = self.plan["adopt_sequence"]
        state = read(Path(adopted["directory"]) / "sequence-status.json")
        if state.get("pid") != adopted["pid"] or state.get("through") != adopted["through"]:
            raise ValueError("adopted main sequence was replaced")
        if state["status"] == "completed_through_requested_stage":
            return "complete"
        if state["status"] != "running":
            raise ValueError("adopted development stopped: " + str(state.get("error", state["status"])))
        actual = process_identity(adopted["pid"])
        if actual is None or actual != self.bound["adopted_process"]:
            raise ValueError("adopted development process disappeared or changed before completion")
        return "running"

    def invoke(self, command):
        if source_hashes(self.plan) != self.bound["source_sha256"]:
            raise ValueError("collection launcher sources changed")
        name = command["name"]
        receipt = {"command": command, "started_utc": utc(), "status": "running"}
        path = self.out / "commands" / (name + ".json")
        path.parent.mkdir(exist_ok=True)
        save(path, receipt)
        print(canonical({"stage": name, "status": "starting", "utc": utc()}), flush=True)
        with (path.parent / (name + ".log")).open("a") as log:
            result = subprocess.run(command["argv"], cwd=self.plan["cwd"],
                                    stdout=log, stderr=subprocess.STDOUT,
                                    env={**os.environ, "PYTHONUNBUFFERED": "1"})
        receipt.update(returncode=result.returncode, finished_utc=utc(),
                       status="completed" if result.returncode == 0 else "failed")
        save(path, receipt)
        if result.returncode:
            raise RuntimeError(f"{name} stopped with exit code {result.returncode}; no automatic retry")
        print(canonical({"stage": name, "status": "completed", "utc": utc()}), flush=True)

    def handoff_complete(self):
        path = self.out / "development-handoff.json"
        adopted = self.plan["adopt_sequence"]
        binding_hash = sha(self.out / "collection-plan.json")
        if path.exists():
            receipt = read(path)
            state = receipt["completed_sequence_status"]
            if (receipt["plan_sha256"] != binding_hash or state.get("pid") != adopted["pid"]
                    or state.get("through") != adopted["through"]
                    or state.get("status") != "completed_through_requested_stage"):
                raise ValueError("durable development handoff identity differs")
            return True
        if self.adopt_state() != "complete":
            return False
        state = read(Path(adopted["directory"]) / "sequence-status.json")
        if (state.get("pid") != adopted["pid"] or state.get("through") != adopted["through"]
                or state.get("status") != "completed_through_requested_stage"):
            raise ValueError("adopted sequence changed during handoff")
        save(path, {"plan_sha256": binding_hash, "recorded_utc": utc(),
                    "completed_sequence_status": state})
        return True

    def run(self, *, poll_seconds=30):
        if not 1 <= poll_seconds <= 60:
            raise ValueError("poll interval must be between 1 and 60 seconds")
        state = {"pid": os.getpid(), "started_utc": utc(), "status": "waiting_for_development",
                 "plan_sha256": sha(self.out / "collection-plan.json"),
                 "research_claim_established": False}
        save(self.out / "status.json", state)
        try:
            while not self.handoff_complete():
                time.sleep(poll_seconds)
            for command in self.plan["commands"]:
                path = self.out / "commands" / (command["name"] + ".json")
                if path.exists():
                    previous = read(path)
                    if previous["command"] != command:
                        raise ValueError("recorded command identity differs")
                    if previous["status"] == "completed":
                        continue
                    raise ValueError("prior command did not finish; inspect its receipts before a new supervised run")
                state.update(status="running", stage=command["name"])
                save(self.out / "status.json", state)
                self.invoke(command)
            state["status"] = "collection_complete_scientific_review_required"
        except BaseException as exc:
            state.update(status="stopped", error_type=type(exc).__name__, error=str(exc)[:1500])
            raise
        finally:
            state["finished_utc"] = utc()
            save(self.out / "status.json", state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with study_lock(args.out):
        Supervisor(args.out, args.plan).run()


if __name__ == "__main__":
    main()
