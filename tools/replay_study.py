#!/usr/bin/env python3
"""Offline same-runner transcript replay plus independently executed SQL.

This checks recorded input legality, state transitions and measured usage totals.
It does not authenticate weights, backend token counts, clocks or generalization.
No network or model calls are made. A failed/incomplete record is never silently
promoted to a replayed completion.
"""

import argparse
from datetime import datetime
import hashlib
import json
import math
import re
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from experiments import stateful_sql as study
from experiments.audit_sql_abstractions_v9 import SQLiteReplayV9
from witness_cl.evidence_memory import EvidenceMemory
from witness_cl.abstraction_v8 import PROPOSAL_SCHEMA, finite_scalar, equal_scalar
from witness_cl.fragments_v8 import Fragment
from witness_cl.memory_v8 import ACTION_SCHEMA, canonical
from witness_cl.model_v8 import InferenceBudget
from witness_cl.model_v9_compatible import portable_schema, WIRE_SCHEMA_POLICY


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def semantic(value):
    # Wall timings and VM steps depend on the SQLite build and machine. Their
    # original receipts remain untouched and are not authenticated by this replay.
    excluded = {
        "elapsed_seconds",
        "setup_seconds",
        "query_seconds",
        "vm_steps",
        "query_seconds_added",
        "vm_steps_added",
    }
    if isinstance(value, dict):
        return {key: semantic(item) for key, item in value.items() if key not in excluded}
    if isinstance(value, (tuple, list)):
        return [semantic(item) for item in value]
    return value


def outer_structure(sql):
    """A syntactic diagnostic only: normalize whitespace, case, and literal holes.

    It does not decide SQL equivalence. Quoted identifiers remain exact; literal
    strings/numbers lose their values, and named bindings are alpha-renamed.
    """
    tokens = re.findall(
        r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^]]*\]|"
        r":[A-Za-z_][A-Za-z_0-9]*|[A-Za-z_][A-Za-z_0-9]*|"
        r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\S",
        sql,
    )
    parameters = {}
    result = []
    for token in tokens:
        if token.startswith("'"):
            result.append("<text_literal>")
        elif token.startswith(":"):
            if token not in parameters:
                parameters[token] = len(parameters)
            result.append(":parameter_" + str(parameters[token]))
        elif token[0].isdigit() or (token.startswith(".") and len(token) > 1):
            result.append("<numeric_literal>")
        elif token[0] in '"`[':
            result.append(token)
        else:
            result.append(token.casefold())
    return result


def validate_call(call, trace, manifest):
    """Check receipts against the declared runtime, including failed attempts."""
    phase = call["phase"]
    require(phase in (trace["phase"] + ":solve", "ordinary:reflection"), "invalid call phase")
    if phase.endswith(":reflection"):
        require(
            trace["phase"] == "ordinary" and trace["arm"] == "fragments",
            "reflection outside the executable ordinary arm",
        )
    cap = manifest["limits"][
        "reflection_output_tokens" if phase.endswith(":reflection") else "solve_output_tokens"
    ]
    require(type(call.get("generation_attempted")) is bool, "missing attempted-generation flag")
    usage = call.get("usage")
    if usage is not None:
        require(call["generation_attempted"], "usage on an unattempted generation")
        require(
            isinstance(usage, dict)
            and all(
                type(usage.get(k)) is int and usage[k] >= 0
                for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            ),
            "invalid usage",
        )
        require(
            usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"],
            "inconsistent usage",
        )
        require(usage["completion_tokens"] <= cap, "completion exceeds frozen output allowance")
        require(
            usage["total_tokens"] <= manifest["client_config"]["context_tokens"],
            "call exceeds frozen context",
        )
    if call["status"] == "completed":
        require(call["generation_attempted"] and usage is not None, "completed call lacks usage")
        require(isinstance(call.get("content"), str), "completed call lacks final text")
    for key in ("tokenization_seconds", "inference_seconds"):
        value = call.get(key, 0.0)
        require(
            type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "invalid nonnegative call duration",
        )
    # Marked fixture calls deliberately lack backend receipts. This exception
    # requires the explicit test backbone and is exposed in the final report.
    if call.get("test_double") is True:
        require(
            manifest["client_config"]["model"] == "explicit-offline-test-double",
            "test-double marker on a real backbone",
        )
        require(manifest["contains_test_double_calls"] is True, "unreported test-double call")
        return
    cfg = manifest["client_config"]
    require(cfg["response_mode"] == "schema", "portable client requires schema mode")
    require(call["max_output_tokens"] == cap, "changed output allowance")
    expected_host = PROPOSAL_SCHEMA if phase.endswith(":reflection") else ACTION_SCHEMA
    require(
        canonical(call["host_response_schema"]) == canonical(expected_host), "changed host schema"
    )
    wire = portable_schema(expected_host)
    require(canonical(call["response_schema"]) == canonical(wire), "changed wire schema")
    require(call["wire_schema_policy"] == WIRE_SCHEMA_POLICY, "changed schema transport policy")
    decoding = deepcopy(cfg["decoding"])
    if phase.endswith(":reflection"):
        decoding["thinking"] = False
    require(call["decoding"] == decoding, "decoding differs from frozen client configuration")
    request = {
        "model": cfg["model"],
        **{k: v for k, v in decoding.items() if k != "thinking"},
        "max_tokens": cap,
        "cache_prompt": False,
        "stream": False,
        "response_format": {"type": "json_object", "schema": wire},
        "chat_template_kwargs": {"enable_thinking": decoding["thinking"]},
    }
    require(
        canonical(call["request_config"]) == canonical(request),
        "request differs from frozen client configuration",
    )
    if call["generation_attempted"]:
        preflight = call["preflight_tokens"]
        require(type(preflight) is int and preflight >= 0, "invalid preflight count")
        require(preflight + cap <= cfg["context_tokens"], "preflight exceeds frozen context")
        if usage is not None:
            require(usage["prompt_tokens"] >= preflight, "prompt shorter than preflight")
            require(call.get("response_model") == cfg["model"], "response model identity mismatch")


def receipt_budget(traces, kind, manifest):
    result = InferenceBudget(
        max_total_tokens=manifest["limits"][kind + "_tokens"],
        max_calls=manifest["limits"][kind + "_calls"],
    ).to_dict()
    for trace in traces:
        if (trace["phase"] == "ordinary") != (kind == "ordinary"):
            continue
        for call in trace["model_calls"]:
            for key in ("tokenization_seconds", "inference_seconds"):
                result[key] += call.get(key, 0.0)
            if call["generation_attempted"]:
                result["calls"] += 1
                if call.get("usage") is None:
                    result["unknown_usage_calls"] += 1
                else:
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        result[key] += call["usage"][key]
    return result


def same_budget(actual, expected):
    require(set(actual) == set(expected), "budget counter inventory mismatch")
    for key, value in expected.items():
        if key.endswith("_seconds"):
            require(
                math.isclose(actual[key], value, rel_tol=1e-10, abs_tol=1e-8),
                "budget timing sum mismatch: " + key,
            )
        else:
            require(
                type(actual[key]) is int and actual[key] == value, "budget counter mismatch: " + key
            )


def validate_envelope(directory, manifest, freeze=None):
    """Recompute summaries and schedule instead of trusting rebound hashes."""
    require(manifest["status"] != "running", "run has no final receipt yet")
    require(manifest["stage"] in ("qualification", "full"), "invalid stage")
    require(
        manifest["arms"]
        and len(set(manifest["arms"])) == len(manifest["arms"])
        and set(manifest["arms"]) <= set(study.ARMS),
        "invalid configured arms",
    )
    expected_counts = {
        "ordinary": 8 if manifest["stage"] == "qualification" else 24,
        "old_before": 0 if manifest["stage"] == "qualification" else 8,
        "old_after": 0 if manifest["stage"] == "qualification" else 8,
        "final": 0 if manifest["stage"] == "qualification" else 8,
    }
    require(
        manifest["required_phase_counts_per_arm_stream"] == expected_counts,
        "declared schedule counts differ from runner",
    )
    require(
        manifest["system_prompt_sha256"] == study._text_hash(manifest["system_prompt"]),
        "system prompt hash mismatch",
    )
    planned = [
        (seed, condition, arm)
        for seed in manifest["seeds"]
        for condition in manifest["conditions"]
        for arm in manifest["arms"]
    ]
    require(len(set(planned)) == len(planned) and planned, "duplicate or empty configured streams")
    names = {
        f"{seed}-{condition}-{arm}.jsonl": (seed, condition, arm)
        for seed, condition, arm in planned
    }
    paths = {p.name: p for p in directory.glob("*.jsonl")}
    require(set(paths) <= set(names), "raw file outside configured arms/streams")
    traces_by_key = {key: [] for key in planned}
    for name, path in paths.items():
        traces = [json.loads(line) for line in path.read_text().splitlines()]
        require(bool(traces), "empty raw file is not a completed arm")
        traces_by_key[names[name]] = traces
        for trace in traces:
            require(
                (trace["seed"], trace["condition"], trace["arm"]) == names[name],
                "raw filename and stream metadata disagree",
            )
            for call in trace["model_calls"]:
                validate_call(call, trace, manifest)
    summary = json.loads((directory / "summary.json").read_text())
    require(isinstance(summary, list) and len(summary) <= len(planned), "invalid summary inventory")
    summary_keys = [(row["seed"], row["condition"], row["arm"]) for row in summary]
    require(
        summary_keys == planned[: len(summary)] and len(summary) % len(manifest["arms"]) == 0,
        "summary is not a prefix of complete configured arm groups",
    )
    require(
        all(key in summary_keys for key, traces in traces_by_key.items() if traces),
        "raw stream omitted from summary",
    )
    total = InferenceBudget(
        max_total_tokens=manifest["limits"]["total_tokens"],
        max_calls=manifest["limits"]["total_calls"],
    ).to_dict()
    for row, key in zip(summary, summary_keys):
        traces = traces_by_key[key]
        groups = {
            phase: [trace for trace in traces if trace["phase"] == phase]
            for phase in expected_counts
        }
        expected = {
            "seed": key[0],
            "condition": key[1],
            "arm": key[2],
            "memory": traces[-1]["memory_snapshot"]
            if traces
            else EvidenceMemory(key[2], manifest["system_prompt"]).snapshot(),
            "warm": study._warm_result(traces, manifest["minimum_warm_correct"]),
            "phase_counts": {phase: len(items) for phase, items in groups.items()},
            "phase_reward": {
                phase: sum(t["reward"] for t in items) / len(items) if items else None
                for phase, items in groups.items()
            },
            "phase_selects": {
                phase: sum(t["select_attempts"] for t in items) for phase, items in groups.items()
            },
            "phase_failures": {
                phase: sum(t["status"] != "completed" for t in items)
                for phase, items in groups.items()
            },
        }
        require(
            canonical({k: row[k] for k in expected}) == canonical(expected),
            "summary differs from raw episode receipts",
        )
        for kind in ("ordinary", "panel"):
            budget = receipt_budget(traces, kind, manifest)
            same_budget(row[kind + "_budget"], budget)
            for counter in study._COUNTERS:
                total[counter] += budget[counter]
            require(budget["calls"] <= budget["max_calls"], "arm call ceiling exceeded")
            require(
                budget["total_tokens"] <= budget["max_total_tokens"], "arm token ceiling exceeded"
            )
    same_budget(manifest["total_budget"], total)
    require(total["calls"] <= total["max_calls"], "global call ceiling exceeded")
    require(total["total_tokens"] <= total["max_total_tokens"], "global token ceiling exceeded")
    scheduled = []
    for seed in manifest["seeds"]:
        for condition in manifest["conditions"]:
            stream = study.make_stream(seed, condition, split="development")
            for step, (phase, index, _) in enumerate(study._schedule(stream, manifest["stage"])):
                arms = manifest["arms"]
                offset = step % len(arms)
                for arm in arms[offset:] + arms[:offset]:
                    scheduled.append(((seed, condition, arm), phase, index))
    count = sum(len(traces) for traces in traces_by_key.values())
    require(count == manifest["completed_episode_records"], "manifest episode count mismatch")
    require(count <= len(scheduled), "extra scheduled records")
    cursors = {key: 0 for key in planned}
    last = None
    for key, phase, index in scheduled[:count]:
        require(cursors[key] < len(traces_by_key[key]), "missing arm or hole in paired schedule")
        trace = traces_by_key[key][cursors[key]]
        cursors[key] += 1
        require(
            (trace["phase"], trace["episode_index"]) == (phase, index), "paired schedule mismatch"
        )
        if last is not None:
            require(
                last["status"] in ("completed", "no_valid_answer")
                and all(c["status"] == "completed" for c in last["model_calls"]),
                "run continued after a failed call or episode",
            )
        last = trace
    all_traces = [trace for traces in traces_by_key.values() for trace in traces]
    complete_calls = all(c["status"] == "completed" for t in all_traces for c in t["model_calls"])
    complete_episodes = all(
        t["status"] in ("completed", "no_valid_answer") and not t.get("reflection_stop")
        for t in all_traces
    )
    actual_complete = (
        count == len(scheduled)
        and complete_calls
        and complete_episodes
        and total["unknown_usage_calls"] == 0
    )
    if manifest["required_records_complete"] or manifest["status"] == "completed":
        require(actual_complete and set(paths) == set(names), "incomplete study claims completion")
    generated = [c for t in all_traces for c in t["model_calls"] if c["generation_attempted"]]
    require(
        manifest["usage_verified"] == all(c.get("usage") is not None for c in generated),
        "usage-verification flag mismatch",
    )
    simulated = any(c.get("test_double") is True for t in all_traces for c in t["model_calls"])
    require(manifest["contains_test_double_calls"] == simulated, "test-double scope mismatch")
    if manifest["warm_qualified"]:
        require(
            manifest["status"] == "completed"
            and actual_complete
            and not simulated
            and all(row["warm"]["meets_warm_accuracy_gate"] for row in summary),
            "invalid warm qualification claim",
        )
    if manifest["status"] == "competence_gate_failed":
        require(
            manifest["stage"] == "full"
            and manifest["gate_after_warm"]
            and len(summary) >= len(manifest["arms"]),
            "invalid competence-stop claim",
        )
        current = summary[-len(manifest["arms"]) :]
        require(
            all(
                row["warm"]["complete"]
                and row["phase_counts"]
                == {"ordinary": 8, "old_before": 0, "old_after": 0, "final": 0}
                for row in current
            )
            and not all(row["warm"]["meets_warm_accuracy_gate"] for row in current),
            "competence gate did not fail at the declared boundary",
        )
    if freeze is not None:
        frozen = json.loads(Path(freeze).read_text())
        for key in ("source_sha256", "system_prompt", "seeds", "arms"):
            require(frozen[key] == manifest[key], "pre-run freeze mismatch: " + key)
        for key in ("conditions", "stage", "client_config"):
            if key in frozen:
                require(frozen[key] == manifest[key], "pre-run freeze mismatch: " + key)
        for key, value in frozen["limits"].items():
            require(manifest["limits"][key] == value, "pre-run limit mismatch: " + key)
        if "runtime_config" in frozen:
            runtime = frozen["runtime_config"]
            require(
                runtime["model"]["alias"] == manifest["client_config"]["model"],
                "frozen runtime model mismatch",
            )
            require(
                runtime["server"]["context_tokens"] == manifest["client_config"]["context_tokens"],
                "frozen context mismatch",
            )
            endpoint = f"http://{runtime['server']['host']}:{runtime['server']['port']}"
            require(endpoint == manifest["client_config"]["endpoint"], "frozen endpoint mismatch")
        require(
            datetime.fromisoformat(frozen["created_utc"]).timestamp() <= manifest["started_unix"],
            "freeze postdates the declared run start",
        )
    return {
        "planned_records": len(scheduled),
        "saved_records": count,
        "required_records_complete": actual_complete,
        "contains_test_double_calls": simulated,
        "pre_run_freeze_sha256": sha(freeze) if freeze is not None else None,
    }


class RecordedClient:
    def __init__(self, calls, max_output):
        self.calls = deepcopy(calls)
        self.max_output = max_output
        self.index = 0
        self.errors = []

    def complete(self, messages, budget, *, phase, records, output_tokens, response_schema):
        try:
            require(self.index < len(self.calls), "unrecorded model request")
            record = self.calls[self.index]
            self.index += 1
            require(
                canonical(messages) == canonical(record["messages"]),
                "illegal or changed model input",
            )
            require(phase == record["phase"], "changed call phase")
            schema = record.get("host_response_schema", record["response_schema"])
            require(
                canonical(schema) == canonical(response_schema),
                "changed response schema",
            )
            require(
                record.get("max_output_tokens", output_tokens) == output_tokens,
                "changed output limit",
            )
            require(
                record["status"] == "completed",
                "failed model request cannot be reenacted as completed",
            )
            usage = record["usage"]
            require(
                all(
                    type(usage.get(key)) is int and usage[key] >= 0
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                ),
                "invalid usage",
            )
            require(
                usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"],
                "inconsistent usage",
            )
            budget.check(record.get("preflight_tokens", usage["prompt_tokens"]), output_tokens)
            budget.calls += 1
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                setattr(budget, field, getattr(budget, field) + usage[field])
            for field in ("tokenization_seconds", "inference_seconds"):
                setattr(budget, field, getattr(budget, field) + record.get(field, 0.0))
            records.append(deepcopy(record))
            return record["content"]
        except Exception as error:
            self.errors.append(str(error))
            raise


def audit(directory, freeze=None):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    require(manifest["version"] == 10, "current study manifest required")
    require(
        manifest["source_sha256"] == study.source_hashes(),
        "executed sources differ from freeze",
    )
    require(
        manifest["source_sha256_after"] == manifest["source_sha256"],
        "source changed during run",
    )
    require(
        sha(directory / "summary.json") == manifest["summary_sha256"],
        "summary hash mismatch",
    )
    require(
        {p.name for p in directory.glob("*.jsonl")} == set(manifest["raw_sha256"]),
        "raw file inventory mismatch",
    )
    for name, digest in manifest["raw_sha256"].items():
        require(sha(directory / name) == digest, "raw hash mismatch: " + name)
    envelope = validate_envelope(directory, manifest, freeze)
    report = {
        "kind": "same_runner_replay_and_independent_sql",
        "network_calls": 0,
        "native_benchmark": False,
        "population_claim": False,
        "records_replayed": 0,
        "sql_replayed": 0,
        "partial_records": [],
        "fresh_use_interventions": [],
        "per_arm": {},
        "schedule": envelope,
        "auditor_sha256": sha(__file__),
    }
    totals = {key: 0 for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens")}
    for path in sorted(directory.glob("*.jsonl")):
        traces = [json.loads(line) for line in path.read_text().splitlines()]
        if not traces:
            continue
        first = traces[0]
        memory = EvidenceMemory(first["arm"], manifest["system_prompt"])
        stream = study.make_stream(first["seed"], first["condition"], split="development")
        schedule = study._schedule(stream, manifest["stage"])
        require(len(traces) <= len(schedule), "extra scheduled records")
        budgets = {
            kind: InferenceBudget(
                max_total_tokens=manifest["limits"][kind + "_tokens"],
                max_calls=manifest["limits"][kind + "_calls"],
            )
            for kind in ("ordinary", "panel")
        }
        stats = {
            "records": 0,
            "correct": 0,
            "selects": 0,
            "admitted": 0,
            "executed_uses": 0,
            "executed_on_correct_episode": 0,
            "observational_answer_support": 0,
            "tokens": 0,
        }
        admission_context = {}
        for trace, (phase, index, spec) in zip(traces, schedule):
            require(
                (trace["phase"], trace["episode_index"]) == (phase, index),
                "schedule mismatch",
            )
            require(
                (trace["arm"], trace["seed"], trace["condition"])
                == (first["arm"], first["seed"], first["condition"]),
                "mixed stream",
            )
            for call in trace["model_calls"]:
                if call.get("generation_attempted"):
                    totals["calls"] += 1
                    if call.get("usage") is not None:
                        for key in (
                            "prompt_tokens",
                            "completion_tokens",
                            "total_tokens",
                        ):
                            totals[key] += call["usage"][key]
                        stats["tokens"] += call["usage"]["total_tokens"]
            replay = SQLiteReplayV9(spec)
            try:
                for query in trace["queries"]:
                    observed = replay.query(query["sql"], query["params"])
                    expected = {
                        key: query[key] for key in ("columns", "rows", "error", "truncated")
                    }
                    require(
                        canonical(observed) == canonical(expected),
                        "SQL replay mismatch",
                    )
                    report["sql_replayed"] += 1
                # Offline interventions never reach the learner or its resource ledger.
                available = {entry.fragment().digest: entry for entry in memory.entries}
                query_cursor = 0
                for action_index, action in enumerate(trace["actions"]):
                    digest = action.get("executed_fragment_digest")
                    if digest is None:
                        continue
                    stats["executed_uses"] += 1
                    stats["executed_on_correct_episode"] += int(trace["reward"] == 1.0)
                    entry = available[digest]
                    acquisition = admission_context.get(entry.provenance)
                    require(acquisition is not None, "use has no replayed admission context")
                    fragment = entry.fragment()
                    request = fragment.compile(action["params"])
                    empty = Fragment.from_query(
                        "SELECT * FROM (" + request.sql + ") WHERE 0",
                        request.parameters,
                    )
                    outer = action.get("outer_sql", "SELECT * FROM reused")
                    outer_params = action.get("outer_params", {})
                    actual = fragment.compose(
                        outer, outer_params, alias="reused", bindings=action["params"]
                    )
                    # Match each use to its actual learner query, in order. USE
                    # compiles directly; COMPOSE wraps the relation as a CTE.
                    learner_request = request if action["action"] == "USE" else actual
                    query_index = next(
                        (
                            i
                            for i in range(query_cursor, len(trace["queries"]))
                            if trace["queries"][i]["purpose"]
                            in ("fragment_use", "fragment_composition")
                            and trace["queries"][i]["learning_check"] is False
                            and trace["queries"][i]["sql"] == learner_request.sql
                            and canonical(trace["queries"][i]["params"])
                            == canonical(learner_request.parameters)
                        ),
                        None,
                    )
                    require(
                        query_index is not None, "executed use has no corresponding learner query"
                    )
                    query_cursor = query_index + 1
                    intervention = empty.compose(outer, outer_params, alias="reused")
                    actual_result = replay.query(actual.sql, actual.parameters)
                    empty_result = replay.query(intervention.sql, intervention.parameters)
                    complete = all(
                        row["error"] is None and not row["truncated"]
                        for row in (actual_result, empty_result)
                    )
                    learner_result = trace["queries"][query_index]
                    scalar_matches = (
                        learner_result["error"] is None
                        and not learner_result["truncated"]
                        and len(learner_result["rows"]) == 1
                        and len(learner_result["rows"][0]) == 1
                        and finite_scalar(learner_result["rows"][0][0])
                        and finite_scalar(trace["answer"])
                        and equal_scalar(learner_result["rows"][0][0], trace["answer"])
                    )
                    later_queries = sum(
                        q["learning_check"] is False for q in trace["queries"][query_index + 1 :]
                    )
                    next_answer = (
                        action_index + 1 < len(trace["actions"])
                        and trace["actions"][action_index + 1].get("action") == "ANSWER"
                    )
                    supported = (
                        trace["reward"] == 1.0
                        and scalar_matches
                        and later_queries == 0
                        and next_answer
                    )
                    stats["observational_answer_support"] += int(supported)
                    different = complete and canonical(actual_result["rows"]) != canonical(
                        empty_result["rows"]
                    )
                    if (
                        different
                        and len(actual_result["rows"]) == len(empty_result["rows"]) == 1
                        and len(actual_result["rows"][0]) == len(empty_result["rows"][0]) == 1
                        and finite_scalar(actual_result["rows"][0][0])
                        and finite_scalar(empty_result["rows"][0][0])
                    ):
                        different = not equal_scalar(
                            actual_result["rows"][0][0], empty_result["rows"][0][0]
                        )
                    report["fresh_use_interventions"].append(
                        {
                            "arm": trace["arm"],
                            "phase": phase,
                            "episode_index": index,
                            "fragment_digest": digest,
                            "executed_on_correct_episode": trace["reward"] == 1.0,
                            "learner_query_index": query_index,
                            "scalar_matches_final_answer": bool(scalar_matches),
                            "later_ordinary_queries": later_queries,
                            "next_action_is_answer": next_answer,
                            "observational_answer_support": bool(supported),
                            "model_answer_causal_dependence_established": False,
                            "changed_binding": canonical(action["params"])
                            != canonical(fragment.original_prepared_query.parameters),
                            "action": action["action"],
                            "outer_sql": outer,
                            "admission_outer_sql": acquisition["outer_sql"],
                            "admission_episode_index": acquisition["episode_index"],
                            "new_outer_structure": (
                                action["action"] == "COMPOSE"
                                and outer_structure(outer)
                                != outer_structure(acquisition["outer_sql"])
                            ),
                            "outer_structure_scope": "syntactic difference after whitespace/case/literal normalization; SQL inequivalence unproved",
                            "instance_dependent": different,
                            "actual_result": actual_result,
                            "empty_result": empty_result,
                            "auditor_selects": 2,
                            "learner_observations_added": 0,
                        }
                    )
            finally:
                replay.close()
            stats["records"] += 1
            stats["correct"] += int(trace["reward"] == 1.0)
            stats["selects"] += trace["select_attempts"]
            stats["admitted"] += int(trace.get("discovery_repair", {}).get("status") == "admitted")
            if trace["status"] not in ("completed", "no_valid_answer") or any(
                call["status"] != "completed" for call in trace["model_calls"]
            ):
                report["partial_records"].append(
                    {"file": path.name, "index": index, "phase": phase}
                )
                require(
                    trace is traces[-1],
                    "records continued after a non-replayable failure",
                )
                continue
            client = RecordedClient(trace["model_calls"], manifest["client_config"]["max_output"])
            reenacted = study.execute_episode(
                spec,
                memory,
                client,
                budgets["ordinary" if phase == "ordinary" else "panel"],
                phase=phase,
                learn=phase == "ordinary",
                solve_output_tokens=manifest["limits"]["solve_output_tokens"],
                reflection_output_tokens=manifest["limits"]["reflection_output_tokens"],
            )
            require(not client.errors, "transcript mismatch: " + str(client.errors))
            require(client.index == len(client.calls), "unused recorded model calls")
            expected = {key: trace[key] for key in reenacted}
            require(
                canonical(semantic(reenacted)) == canonical(semantic(expected)),
                "episode/state replay mismatch",
            )
            report["records_replayed"] += 1
            discovery = trace.get("discovery_repair", {})
            if discovery.get("status") == "admitted":
                admitted = [
                    attempt for attempt in discovery["attempts"] if attempt["status"] == "admitted"
                ]
                require(len(admitted) == 1, "admission has no unique accepted proposal")
                proposal = json.loads(admitted[0]["proposal_text"])["proposal"]
                admission_context[discovery["admitted_provenance"]] = {
                    "outer_sql": proposal["outer_sql"],
                    "episode_index": trace["episode_index"],
                }
        report["per_arm"][path.stem] = stats
    for key, value in totals.items():
        require(value == manifest["total_budget"][key], "global ledger mismatch: " + key)
    report["recorded_totals"] = totals
    report["status"] = (
        "partial"
        if (report["partial_records"] or not envelope["required_records_complete"])
        else "passed"
    )
    report["saved_completed_transcripts_replayed"] = True
    report["study_status"] = manifest["status"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--freeze", type=Path, help="Independent pre-run receipt to bind")
    args = parser.parse_args()
    report = audit(args.directory, args.freeze)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "records_replayed", "sql_replayed")}))


if __name__ == "__main__":
    main()
