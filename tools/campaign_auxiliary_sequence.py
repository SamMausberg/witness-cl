#!/usr/bin/env python3
"""Run the prospectively assigned auxiliary studies using their frozen launchers.

Order: assay-development, development-deletion, native, assay-diagnostic,
deletion. Both main qualifications must pass before any auxiliary generation.
Development deletion uses the complete main development census. The last two
stages require complete audited main confirmation, regardless of its outcome.
No assigned stream, native permutation, or eligible deletion case is dropped.

--describe prints the exact prospective plan without writing, freezing, checking
an endpoint, importing native data, or generating. Native Python, upstream, and
asset paths are explicit and persist in the sequence receipt for recovery.
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

from tools import campaign, campaign_assay, native_campaign
from tools.campaign_sequence import seeds_for, validate_plan
from witness_cl.campaign_io import canonical, read, save, sha, study_lock

STAGES = ("assay-development", "development-deletion", "native", "assay-diagnostic", "deletion")


def utc():
    return datetime.now(timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_auxiliary_plan(plan):
    validate_plan(plan)
    assay = plan["separate_assay"]
    require(assay == {"development_seed_start": 102000, "development_streams": 4,
                     "seed_start": 300000, "streams": 64, "probes_per_checkpoint": 8},
            "auxiliary CLI must implement the exact reserved four/64-stream assay plan")
    require(plan["native"] == {"permutations": list(range(5)), "benchmark_seed": 42,
                               "questions_per_permutation": 40},
            "native default five-by-forty schedule is fixed")
    return plan


def known_cost(cost):
    require(isinstance(cost, dict), "missing measured cost ledger")
    require(all(cost.get(key, 0) == 0 for key in
                ("unknown_usage_calls", "potential_generation_calls", "uncertain_invocations")),
            "unknown or uncertain usage cannot advance the auxiliary sequence")
    for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens"):
        require(type(cost.get(key)) is int and cost[key] >= 0, "invalid measured cost ledger")
    require(cost["prompt_tokens"] + cost["completion_tokens"] == cost["total_tokens"],
            "token costs do not reconcile")


class AuxiliarySequence:
    def __init__(self, out, main_out, plan_path, runtime_config, runtime_receipt, key_file,
                 *, native_python, upstream, assets, runtime_cache, python=None):
        self.out = Path(out).resolve()
        self.main_out = Path(main_out).resolve()
        self.plan_path = Path(plan_path).resolve()
        self.plan = validate_auxiliary_plan(read(self.plan_path))
        self.runtime_config = Path(runtime_config).resolve()
        self.runtime_receipt = Path(runtime_receipt).resolve()
        self.key_file = Path(key_file).resolve()
        # Preserve the interpreter symlink: resolving a venv's python would lose
        # the venv prefix and silently select its base interpreter environment.
        self.python = str(Path(python or sys.executable).absolute())
        self.native_python = str(Path(native_python).absolute())
        self.upstream = Path(upstream).resolve()
        self.assets = Path(assets).resolve()
        self.runtime_cache = Path(runtime_cache).resolve()
        require(self.out != self.main_out and self.main_out not in self.out.parents,
                "auxiliary output must be separate from the main sequence directory")
        require(self.out not in self.main_out.parents,
                "auxiliary output cannot contain the main sequence directory")

    def prospective(self):
        stages = []
        for name in STAGES:
            entry = {"name": name, "output": str(self.out / name)}
            if name.startswith("assay-"):
                kind = "development" if name == "assay-development" else "diagnostic"
                seeds = campaign_assay.default_seeds(kind)
                entry.update(kind=kind, seeds=seeds, arms=list(campaign_assay.ARMS),
                             checkpoints=list(campaign_assay.CHECKPOINTS), probes_per_checkpoint=8,
                             donor_episodes_per_stream=24, probe_episodes_per_stream=96,
                             planned_records=120 * len(seeds), learn_in_probes=False,
                             gate="qualified" if kind == "development" else "complete_confirmation")
            elif name == "native":
                entry.update(gate="qualified_and_complete_development_deletion",
                             task="database_exploration", variant="schema_drift", schedule="default",
                             benchmark_seed=42, permutations=list(range(5)), questions_per_permutation=40,
                             query_budget=15, arms=list(native_campaign.ARMS),
                             jobs=native_campaign.planned_runs(), planned_questions=800,
                             upstream_commit=native_campaign.UPSTREAM_COMMIT,
                             dataset=native_campaign.DATASET, dataset_revision=native_campaign.REVISION,
                             asset_hashes=native_campaign.ASSETS,
                             recovery="completed native runs only; partial runs remain incomplete")
            else:
                source_kind = "development" if name == "development-deletion" else "confirmation"
                entry.update(gate="complete_" + source_kind,
                             source_study=str(self.main_out / self.plan[source_kind]["name"]),
                             planned_cases="entire structural-event census of the complete source study",
                             zero_cases="valid completed diagnostic; no deletion effect estimate",
                             selection="all eligible events; no truncation, ranking, or success selection",
                             learn=False, feedback_to_source=False)
            stages.append(entry)
        return {
            "schema_version": 1, "main_out": str(self.main_out), "out": str(self.out),
            "main_plan": self.plan, "plan_path": str(self.plan_path), "plan_sha256": sha(self.plan_path),
            "runtime": {"config": str(self.runtime_config), "config_sha256": sha(self.runtime_config),
                        "receipt": str(self.runtime_receipt), "receipt_sha256": sha(self.runtime_receipt),
                        "cache": str(self.runtime_cache), "key_file": str(self.key_file)},
            "environments": {"python": self.python, "native_python": self.native_python,
                             "native_upstream": str(self.upstream), "native_assets": str(self.assets)},
            "launchers_sha256": {name: sha(ROOT / name) for name in (
                "tools/campaign_auxiliary_sequence.py", "tools/campaign_sequence.py",
                "tools/campaign_assay.py", "tools/native_campaign.py")},
            "stages": stages,
            "stopping": "complete every assigned schedule; stop only integrity/runtime/resource failures",
            "outcome_gates": "only the prespecified main qualification gate; no auxiliary efficacy gate",
            "confirmation_outcome": "positive and negative complete confirmation both permit diagnostics",
            "recovery": "reuse exact freezes and recorded calls; no uncharged retries or stream substitution",
            "native_contact": "report native reward and stateful gain; delayed mechanism requires observed executions",
        }

    def register(self):
        prospective = self.prospective()
        path = self.out / "auxiliary-sequence.json"
        if path.exists():
            require(read(path)["prospective"] == prospective,
                    "auxiliary plan, paths, runtime receipts, or launcher sources changed")
        else:
            require(not self.out.exists() or not any(path.name != "invocation.lock" for path in self.out.iterdir()),
                    "unregistered auxiliary output is not empty")
            save(path, {"created_utc": utc(), "prospective": prospective})

    def require_main(self, kind):
        require(read(self.main_out / "sequence.json")["plan"] == self.plan,
                "main sequence does not match the prospective auxiliary plan")
        jobs = self.plan["qualification"] if kind == "qualification" else [self.plan[kind]]
        config, receipt = read(self.runtime_config), read(self.runtime_receipt)
        require(receipt.get("config") == config and receipt.get("model_sha256"),
                "runtime receipt differs from the prescribed model")
        learner = campaign._learner_identity({"source_sha256": campaign.source_inventory()})
        bindings = []
        for job in jobs:
            directory = self.main_out / job["name"]
            frozen = read(directory / "freeze.json")
            client = frozen["client_config"]
            expected = {"model": config["model"]["alias"], "decoding": config["decoding"],
                        "endpoint": "http://{host}:{port}".format(**config["server"]),
                        "context_tokens": config["server"]["context_tokens"],
                        "max_output": 4096, "timeout": 180.0, "response_mode": "schema"}
            require(all(client.get(key) == value for key, value in expected.items()),
                    "prerequisite client differs from the prescribed runtime")
            _, frozen, summary, audit, files = campaign._study_evidence(
                directory, kinds={kind}, client_config=client, learner_hashes=learner,
                model_identity={"runtime_config": config, "model_sha256": receipt["model_sha256"]})
            n = len(frozen["seeds"]) if kind == "confirmation" else None
            if n is not None:
                require(n >= 48, "complete confirmation requires at least48 independent streams")
                validate_plan(self.plan, confirmation_n=n)
            expected_arms = ["full_history"] if kind == "qualification" else self.plan["arms"]
            require(frozen["seeds"] == seeds_for(job, confirmation_n=n)
                    and frozen["arms"] == expected_arms and frozen["conditions"] == job["conditions"]
                    and frozen["old_replicates"] == 8,
                    "prerequisite study differs from the assigned main schedule")
            schedule = campaign.planned_records(frozen)
            require(read(directory / "schedule.json") == schedule
                    and len(schedule) == frozen["planned_records"]
                    and audit.get("records_replayed") == len(schedule) and audit.get("network_calls") == 0,
                    "prerequisite audit must replay its complete assigned schedule without model calls")
            known_cost(audit["cost"])
            if kind == "qualification":
                require(summary.get("qualified") is True, "completed main qualification did not pass")
            bindings.append({"directory": str(directory), "kind": kind,
                             "hashes": {name: sha(path) for name, path in files.items()},
                             "records_sha256": audit["records_sha256"],
                             "journals_sha256": audit["journals_sha256"]})
        # Confirmation efficacy and deletion flip counts are deliberately absent
        # from all gates. A complete negative study remains assigned evidence.
        save(self.out / "prerequisites" / (kind + ".json"), {"studies": bindings})

    def invoke(self, script, arguments, log_name, *, native=False):
        command = [self.native_python if native else self.python, "-u", str(script),
                   *map(str, arguments)]
        directory = self.out / "invocations"
        directory.mkdir(exist_ok=True)
        ordinal = len(list(directory.glob("*.json")))
        receipt_path = directory / f"{ordinal:04d}-{log_name}.json"
        receipt = {"started_utc": utc(), "command": command, "status": "started", "pid": os.getpid()}
        save(receipt_path, receipt)
        log_path = self.out / "stage-logs" / (log_name + ".log")
        log_path.parent.mkdir(exist_ok=True)
        print(canonical({"time": utc(), "stage": log_name, "status": "starting"}), flush=True)
        try:
            with log_path.open("a") as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                               check=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
        except BaseException as exc:
            receipt.update(status="stopped", error_type=type(exc).__name__)
            raise
        else:
            receipt["status"] = "completed"
        finally:
            receipt["finished_utc"] = utc()
            save(receipt_path, receipt)
        print(canonical({"time": utc(), "stage": log_name, "status": "completed"}), flush=True)

    def freeze(self, stage):
        directory = self.out / stage
        if not (directory / "freeze.json").exists():
            require(not directory.exists(), "partial freeze retained; do not overwrite or silently refreeze")
            if stage == "native":
                args = ["freeze", "--output", directory, "--upstream", self.upstream,
                        "--assets", self.assets, "--runtime-config", self.runtime_config,
                        "--runtime-cache", self.runtime_cache, "--runtime-receipt", self.runtime_receipt,
                        "--key-file", self.key_file]
                self.invoke(ROOT / "tools/native_campaign.py", args, stage + "-freeze", native=True)
            else:
                if stage.startswith("assay-"):
                    kind = "development" if stage == "assay-development" else "diagnostic"
                    args = ["freeze", "--out", directory, "--kind", kind,
                            "--runtime-config", self.runtime_config, "--runtime-receipt", self.runtime_receipt,
                            "--key-file", self.key_file]
                else:
                    kind = "development" if stage == "development-deletion" else "confirmation"
                    args = ["deletion-freeze", "--out", directory, "--source-study",
                            self.main_out / self.plan[kind]["name"]]
                self.invoke(ROOT / "tools/campaign_assay.py", args, stage + "-freeze")
        self.check_stage_freeze(stage)
        return directory

    def check_stage_freeze(self, stage):
        directory = self.out / stage
        frozen = read(directory / "freeze.json")
        require(read(directory / "freeze.sha256.json") == {"sha256": sha(directory / "freeze.json")},
                "stage freeze digest mismatch")
        require(frozen.get("contains_test_double_calls") is False
                and frozen.get("runtime_config") == read(self.runtime_config),
                "auxiliary study differs from the assigned real runtime")
        sources = frozen["sources" if stage == "native" else "source_sha256"]
        require(all(sha(directory / "sources" / name) == expected for name, expected in sources.items()),
                "auxiliary immutable source copy changed")
        if stage == "native":
            runtime = read(self.runtime_receipt)
            health = frozen.get("runtime_environment", {})
            require(health.get("model_sha256") == runtime.get("model_sha256")
                    and health.get("backend") == runtime.get("backend")
                    and health.get("conversion_sha256") == runtime.get("conversion_receipt_sha256"),
                    "native model bytes or backend differ from the auxiliary runtime receipt")
            require(frozen.get("jobs") == native_campaign.planned_runs()
                    and frozen.get("arms") == list(native_campaign.ARMS)
                    and frozen.get("upstream") == str(self.upstream)
                    and frozen.get("upstream_commit") == native_campaign.UPSTREAM_COMMIT
                    and frozen.get("dataset_revision") == native_campaign.REVISION,
                    "native freeze differs from assigned default jobs or pinned upstream")
            require(frozen.get("task") == {"name": "database_exploration", "schedule": "default",
                    "variant": "schema_drift", "seed": 42, "runs": 5, "questions_per_run": 40,
                    "query_budget": 15, "mode": "permute", "default_schedule_unmodified": True},
                    "native task settings differ from unchanged default")
            for name, expected in native_campaign.ASSETS.items():
                actual = frozen["assets"][name]
                require(actual["sha256"] == expected["sha256"] and actual["bytes"] == expected["bytes"]
                        and Path(actual["path"]).resolve() == (self.assets / name).resolve(),
                        "native assets differ from the prescribed dataset")
        else:
            require(frozen.get("runtime_receipt") == read(self.runtime_receipt),
                    "stage runtime receipt differs from auxiliary registry")
            if stage.startswith("assay-"):
                kind = "development" if stage == "assay-development" else "diagnostic"
                require(frozen.get("experiment") == campaign_assay.VERSION and frozen.get("kind") == kind
                        and frozen.get("seeds") == campaign_assay.default_seeds(kind)
                        and frozen.get("arms") == list(campaign_assay.ARMS)
                        and frozen.get("checkpoints") == [8, 16, 24] and frozen.get("probes_per_checkpoint") == 8
                        and frozen.get("planned_records") == 120 * len(campaign_assay.default_seeds(kind)),
                        "assay freeze differs from the complete assigned donor/probe schedule")
            else:
                kind = "development" if stage == "development-deletion" else "confirmation"
                source = self.main_out / self.plan[kind]["name"]
                require(frozen.get("experiment") == "agent_relation_deletion_v1"
                        and frozen.get("source_study") == str(source)
                        and frozen.get("source_freeze_sha256") == sha(source / "freeze.json")
                        and frozen.get("source_audit_sha256") == sha(source / "audit.json")
                        and frozen.get("source_records_sha256") == campaign.artifact_digest(source / "episodes")
                        and frozen.get("source_journals_sha256") == campaign.artifact_digest(source / "calls")
                        and frozen.get("learn") is False and frozen.get("feedback_to_original_campaign") is False,
                        "deletion freeze differs from the prospectively assigned complete parent study")
                cases = read(directory / "cases.json")
                expected, selection = campaign_assay.all_deletion_cases(campaign.load_records(source))
                require(cases == expected and frozen.get("planned_cases") == len(expected)
                        and read(directory / "mechanism-selection.json") == selection,
                        "deletion must include the entire parent structural-event census, including zero")
        return frozen

    def execute(self, stage, directory):
        # No --max-runs or --max-new-records: every assigned unit must finish.
        if stage == "native":
            script = directory / "sources/tools/native_campaign.py"
            self.invoke(script, ["resume", "--output", directory, "--runtime-cache", self.runtime_cache,
                        "--runtime-receipt", self.runtime_receipt, "--key-file", self.key_file], stage + "-run", native=True)
            self.invoke(script, ["audit", "--output", directory, "--replay"], stage + "-audit", native=True)
        else:
            script = directory / "sources/tools/campaign_assay.py"
            prefix = "" if stage.startswith("assay-") else "deletion-"
            self.invoke(script, [prefix + "resume", "--out", directory, "--key-file", self.key_file], stage + "-run")
            self.invoke(script, [prefix + "audit", "--out", directory], stage + "-audit")
        return self.completed(stage)

    def completed(self, stage):
        directory = self.out / stage
        frozen, audit = read(directory / "freeze.json"), read(directory / "audit.json")
        require(audit.get("freeze_sha256") == sha(directory / "freeze.json")
                and audit.get("model_calls_made") == 0, "stage audit is stale or made model calls")
        if stage == "native":
            report = read(directory / "report.json")
            require(audit.get("all_complete_and_passed") is True and audit.get("model_free_replay") is True
                    and audit.get("report_sha256") == sha(directory / "report.json")
                    and audit.get("contains_test_double_calls") is False
                    and report.get("status") == "completed" and len(report.get("runs", [])) == 20,
                    "all twenty native runs require complete model-free replay")
            expected = {job["key"]: sha(directory / "runs" / job["key"] / "result.json")
                        for job in frozen["jobs"]}
            require(audit.get("result_sha256") == expected, "native replay does not bind every current result")
            for job in frozen["jobs"]:
                result_path = directory / "runs" / job["key"] / "result.json"
                calls = native_campaign.journal_calls(result_path.parent / "calls")
                native_campaign.validate_calls(calls, frozen)
                require(calls == read(result_path)["calls"], "native call journals changed after replay")
            for row in report["runs"]:
                known_cost(row)
        else:
            report = read(directory / "summary.json")
            require(report.get("complete") is True and audit.get("consistent") is True
                    and audit.get("complete") is True and audit.get("summary_sha256") == sha(directory / "summary.json"),
                    "complete consistent auxiliary audit required")
            for field, name in (("records_sha256", "episodes"), ("journals_sha256", "calls")):
                require(audit.get(field) == campaign.artifact_digest(directory / name), "auxiliary audit raw receipts changed")
            if stage.startswith("assay-"):
                require(audit.get("records_replayed") == frozen["planned_records"]
                        and report.get("records") == frozen["planned_records"], "assigned assay schedule is incomplete")
                known_cost(report["physical_cost"])
            else:
                require(audit.get("cases_replayed") == frozen["planned_cases"]
                        and report.get("completed_cases") == frozen["planned_cases"], "deletion census is incomplete")
                known_cost(report["physical_diagnostic_cost"])
        return {"directory": str(directory), "complete": True,
                "freeze_sha256": sha(directory / "freeze.json"), "audit_sha256": sha(directory / "audit.json"),
                "report_sha256": sha(directory / ("report.json" if stage == "native" else "summary.json"))}

    def run(self, through):
        require(through in STAGES, "unknown terminal auxiliary stage")
        self.require_main("qualification")
        completed = []
        for stage in STAGES[:STAGES.index(through) + 1]:
            if stage == "development-deletion":
                self.require_main("development")
            elif stage == "assay-diagnostic":
                self.require_main("confirmation")
            directory = self.freeze(stage)
            audit_path = directory / "audit.json"
            audit_complete = (read(audit_path).get("all_complete_and_passed" if stage == "native" else "complete")
                              is True) if audit_path.exists() else False
            # Completed stages are verified from their bound receipts and never
            # rerun merely because a later --through target was requested.
            result = self.completed(stage) if audit_complete else self.execute(stage, directory)
            completed.append({"stage": stage, **result})
            save(self.out / "summary.json", {
                "status": "completed_through_requested_stage" if stage == through else "running",
                "through": through, "completed_stages": completed,
                "native_environment": self.prospective()["environments"],
                "runtime": self.prospective()["runtime"],
                "outcome_stopping": False, "no_primary_claim": True,
            })


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--out", type=Path, required=True)
    value.add_argument("--main-out", type=Path, required=True)
    value.add_argument("--plan", type=Path, default=ROOT / "configs/campaign_sequence_dense_v2.json")
    value.add_argument("--runtime-config", type=Path, required=True)
    value.add_argument("--runtime-receipt", type=Path, required=True)
    value.add_argument("--runtime-cache", type=Path, required=True)
    value.add_argument("--key-file", type=Path, required=True)
    value.add_argument("--native-python", type=Path, required=True)
    value.add_argument("--upstream", type=Path, required=True)
    value.add_argument("--assets", type=Path, required=True)
    value.add_argument("--through", choices=STAGES, default="assay-development")
    value.add_argument("--describe", action="store_true", help="print prospective plan without writes or model calls")
    return value


def main():
    args = parser().parse_args()
    sequence = AuxiliarySequence(args.out, args.main_out, args.plan, args.runtime_config,
        args.runtime_receipt, args.key_file, native_python=args.native_python, upstream=args.upstream,
        assets=args.assets, runtime_cache=args.runtime_cache)
    if args.describe:
        print(canonical({"through": args.through, "prospective": sequence.prospective()}))
        return
    sequence.out.mkdir(parents=True, exist_ok=True)
    with study_lock(sequence.out):
        sequence.register()
        status = {"started_utc": utc(), "through": args.through, "pid": os.getpid(), "status": "running"}
        save(sequence.out / "auxiliary-sequence-status.json", status)
        try:
            sequence.run(args.through)
        except BaseException as exc:
            status.update(status="stopped", error_type=type(exc).__name__, error=str(exc)[:1000])
            raise
        else:
            status["status"] = "completed_through_requested_stage"
        finally:
            status["finished_utc"] = utc()
            save(sequence.out / "auxiliary-sequence-status.json", status)


if __name__ == "__main__":
    main()
