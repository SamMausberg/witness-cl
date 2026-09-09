#!/usr/bin/env python3
"""Prospectively frozen development study of evidence-preserving executable memory.

All memories start empty and share a frozen solver prompt and decoding policy.
Only --stage full requests the transfer schedule. Qualification is a competence
check, never a confirmed interaction-saving or noninferiority result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path

from witness_cl.abstraction_v8 import (
    proposal_messages,
)
from witness_cl.actions_v9 import parse_action
from witness_cl.discovery_repair_v9 import run_discovery_repair
from witness_cl.evidence_memory import ARMS, EvidenceMemory
from witness_cl.fragments_v8 import FragmentError
from witness_cl.memory_v8 import ACTION_SCHEMA, canonical
from witness_cl.model_v8 import BudgetStop, InferenceBudget
from witness_cl.model_v9 import DecodingV9
from witness_cl.model_v9_compatible import LocalInferenceV9Compatible
from witness_cl.sql_env_v9 import evaluator_metadata, make_stream, open_episode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from experiments.competence_interactive_v9 import V9_SYSTEM

MAX_ACTIONS = 10
SOURCE_FILES = (
    "src/witness_cl/sql_env_v8.py",
    "src/witness_cl/sql_env_v9.py",
    "src/witness_cl/fragments_v8.py",
    "src/witness_cl/memory_v8.py",
    "src/witness_cl/model_v8.py",
    "src/witness_cl/abstraction_v8.py",
    "src/witness_cl/memory_v9.py",
    "src/witness_cl/model_v9.py",
    "src/witness_cl/actions_v9.py",
    "experiments/competence_interactive_v9.py",
    "src/witness_cl/evidence_memory.py",
    "src/witness_cl/discovery_repair_v9.py",
    "src/witness_cl/model_v9_compatible.py",
    "experiments/stateful_sql.py",
    "docs/v10/PROTOCOL.md",
)
_COUNTERS = (
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "calls",
    "tokenization_seconds",
    "inference_seconds",
    "unknown_usage_calls",
)


def _text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_hashes():
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in SOURCE_FILES
    }


def _check_output_caps(client, solve, reflection):
    if any(
        type(value) is not int or not 1 <= value <= 8192
        for value in (solve, reflection)
    ):
        raise ValueError("solve and reflection caps must be exact integers in 1..8192")
    if max(solve, reflection) > client.max_output:
        raise ValueError("client output ceiling is below the shared per-call caps")


def _proposal_messages_v9(trace):
    messages = proposal_messages(trace)
    payload = json.loads(messages[1]["content"])
    reward = payload.pop("feedback_reward")
    payload["correct"] = reward == 1.0
    payload["feedback_meaning"] = (
        "Correct on this episode only; no hidden answer is supplied."
    )
    messages[1]["content"] = canonical(payload)
    return messages


@dataclass(frozen=True)
class ResourceLimitsV9:
    """Caps for this invocation; callers subtract prior diagnostics before use."""

    wall_seconds: float = 1800.0
    ordinary_tokens: int = 500000
    panel_tokens: int = 500000
    ordinary_calls: int = 280
    panel_calls: int = 260
    total_tokens: int = 3000000
    total_calls: int = 1620
    solve_output_tokens: int = 2048
    reflection_output_tokens: int = 4096

    def __post_init__(self):
        if (
            type(self.wall_seconds) not in (int, float)
            or not math.isfinite(self.wall_seconds)
            or not 0 < self.wall_seconds <= 1800
        ):
            raise ValueError("wall_seconds must be positive and at most 1800")
        for name in (
            "ordinary_tokens",
            "panel_tokens",
            "ordinary_calls",
            "panel_calls",
            "total_tokens",
            "total_calls",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(
                    "positive exact integer resource cap required: " + name
                )
        for name in ("solve_output_tokens", "reflection_output_tokens"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 8192:
                raise ValueError("per-call output cap must be in 1..8192: " + name)


DEFAULT_LIMITS = ResourceLimitsV9()


class _CombinedBudget:
    """Charge each attempt to its arm/phase and the shared run exactly once."""

    def __init__(self, local, total):
        object.__setattr__(self, "_local", local)
        object.__setattr__(self, "_total", total)

    def check(self, input_tokens, reserved_output):
        self._local.check(input_tokens, reserved_output)
        self._total.check(input_tokens, reserved_output)

    def __getattr__(self, name):
        if name == "deadline":
            return min(self._local.deadline, self._total.deadline)
        if name == "max_total_tokens":
            # LocalInference validates actual usage after charging. Expose the
            # tighter remaining shared allowance for that post-response check.
            return min(
                self._local.max_total_tokens,
                self._local.total_tokens
                + self._total.max_total_tokens
                - self._total.total_tokens,
            )
        return getattr(self._local, name)

    def __setattr__(self, name, value):
        if name not in _COUNTERS:
            raise AttributeError("only measured budget counters may change")
        previous = getattr(self._local, name)
        setattr(self._local, name, value)
        setattr(self._total, name, getattr(self._total, name) + value - previous)


class _SharedBudgetClient:
    def __init__(self, client, total):
        self.client, self.total = client, total

    @property
    def max_output(self):
        return self.client.max_output

    def complete(self, messages, budget, **kwargs):
        return self.client.complete(
            messages, _CombinedBudget(budget, self.total), **kwargs
        )


def execute_episode(
    spec,
    memory,
    client,
    budget,
    *,
    phase,
    learn,
    solve_output_tokens=2048,
    reflection_output_tokens=4096,
):
    """Only public question/schema and actual observations reach the model."""
    if not isinstance(memory, EvidenceMemory):
        raise ValueError("evidence memory with a shared solver prompt is required")
    if type(learn) is not bool or phase not in (
        "ordinary",
        "old_before",
        "old_after",
        "final",
    ):
        raise ValueError("explicit learning flag and declared phase required")
    if learn and phase != "ordinary":
        raise ValueError("evaluation panels must remain frozen")
    _check_output_caps(client, solve_output_tokens, reflection_output_tokens)
    start = time.monotonic()
    before = memory.digest()
    trace = {
        "phase": phase,
        "question": None,
        "schema": None,
        "queries": [],
        "model_calls": [],
        "actions": [],
        "answer": None,
        "reward": 0.0,
        "status": "running",
        "before_memory_digest": before,
        "system_prompt_sha256": _text_hash(memory.system_prompt),
        "learn": learn,
    }
    conversation = []
    setup_start = time.monotonic()
    with open_episode(spec, allow_learning_checks=learn) as session:
        trace["setup_seconds"] = time.monotonic() - setup_start
        public = session.public
        trace.update(question=public.question, schema=public.schema)
        prefix, selected = memory.prefix(public.question)
        trace["retrieved_entry_digests"] = [e.fragment().digest for e in selected]
        trace["retrieved_provenance"] = [e.provenance for e in selected]
        conversation.append(
            {
                "role": "user",
                "content": canonical(
                    {
                        "question": public.question,
                        "schema": public.schema,
                        "remaining_selects": public.max_selects,
                    }
                ),
            }
        )

        def query(sql, params, purpose, *, learning_check=False):
            result = session.query(sql, params, learning_check=learning_check)
            row = {
                "sql": sql,
                "params": params,
                "purpose": purpose,
                "learning_check": learning_check,
                **asdict(result),
            }
            trace["queries"].append(row)
            return row

        def feedback(row, detail=None):
            msg = {
                "tool_result": {
                    k: row[k] for k in ("columns", "rows", "error", "truncated")
                },
                "remaining_selects": public.max_selects - session.select_attempts,
            }
            if detail is not None:
                msg["memory_check"] = detail
            conversation.append({"role": "user", "content": canonical(msg)})

        try:
            answered = False
            for _ in range(MAX_ACTIONS):
                content = client.complete(
                    prefix + conversation,
                    budget,
                    phase=phase + ":solve",
                    records=trace["model_calls"],
                    output_tokens=solve_output_tokens,
                    response_schema=ACTION_SCHEMA,
                )
                conversation.append({"role": "assistant", "content": content})
                try:
                    action = parse_action(content)
                except (ValueError, TypeError, FragmentError) as exc:
                    trace["actions"].append({"kind": "invalid", "error": str(exc)})
                    if session.select_attempts < public.max_selects:
                        row = query("", {}, "invalid_model_action")
                        feedback(row, "Invalid action format: " + str(exc))
                    else:
                        conversation.append(
                            {
                                "role": "user",
                                "content": "Invalid action. No SELECTs remain. Submit a finite numeric ANSWER.",
                            }
                        )
                    continue
                trace["actions"].append(deepcopy(action))
                if action["action"] == "ANSWER":
                    trace["answer"] = action["value"]
                    trace["reward"] = session.answer(action["value"]).reward
                    answered = True
                    break
                if session.select_attempts >= public.max_selects:
                    # No uncharged query executes. This call was still billed.
                    conversation.append(
                        {
                            "role": "user",
                            "content": "No SELECTs remain. Submit ANSWER using only observed evidence.",
                        }
                    )
                    continue
                if action["action"] == "QUERY":
                    feedback(query(action["sql"], action["params"], "ordinary_query"))
                    continue
                try:
                    entry = selected[action["entry"]]
                    fragment = entry.fragment()
                    if action["action"] == "USE":
                        request = fragment.compile(action["params"])
                    else:
                        request = fragment.compose(
                            action["outer_sql"],
                            action["outer_params"],
                            alias="reused",
                            bindings=action["params"],
                        )
                    if memory.arm == "fragments":
                        guard = entry.guard_fragment().original_prepared_query
                        observed = query(
                            guard.sql, guard.parameters, "applicability_check"
                        )
                        actual = {
                            k: observed[k] for k in ("columns", "rows", "truncated")
                        }
                        passed = (
                            observed["error"] is None
                            and canonical(actual) == entry.expected
                        )
                        trace["actions"][-1]["guard_passed"] = passed
                        if not passed:
                            feedback(
                                observed,
                                "Witnessed applicability rows do not match. This use was rejected; solve from current observations.",
                            )
                            continue
                        if session.select_attempts >= public.max_selects:
                            feedback(
                                observed,
                                "Applicability matched, but no SELECT allowance remains to execute the fragment.",
                            )
                            continue
                    trace["actions"][-1]["executed_fragment_digest"] = fragment.digest
                    feedback(
                        query(
                            request.sql,
                            request.parameters,
                            "fragment_composition"
                            if action["action"] == "COMPOSE"
                            else "fragment_use",
                        )
                    )
                except (IndexError, ValueError, TypeError, FragmentError) as exc:
                    feedback(
                        query("", {}, "invalid_memory_action"),
                        "Invalid memory use: " + str(exc),
                    )
            if not answered:
                trace["reward"] = session.answer(None).reward
                trace["status"] = "no_valid_answer"
            else:
                trace["status"] = "completed"
            # This is the only ordinary target feedback: correctness, no gold.
            trace["feedback"] = {
                "correct": trace["reward"] == 1.0,
                "meaning": "Correct on this episode only."
                if trace["reward"] == 1.0
                else "The submitted answer was INCORRECT.",
            }
            conversation.append(
                {"role": "user", "content": canonical(trace["feedback"])}
            )
            if learn:
                synthesizing = memory.arm in ("fragments", "fragments_unchecked")
                reflection_text = None
                if synthesizing:
                    repair = run_discovery_repair(
                        trace,
                        memory,
                        client,
                        budget,
                        session,
                        allow_learning=True,
                        output_tokens=reflection_output_tokens,
                    )
                    repair.pop("prototype_only", None)
                    repair["implementation"] = "v9_bounded_repair_integrated_v10"
                    trace["discovery_repair"] = repair
                    if repair["status"] == "budget_stop":
                        raise BudgetStop(repair.get("reason", "discovery_budget_stop"))
                    if repair["status"] in (
                        "model_failure",
                        "query_failure",
                        "evidence_changed",
                        "session_rejected",
                    ):
                        raise RuntimeError("discovery failed: " + repair["status"])

                if trace["status"] == "completed":
                    memory.finish(trace, conversation, reflection_text)

        except BudgetStop as exc:
            trace.update(status="resource_stop", stop_reason=str(exc))
        except Exception as exc:
            trace.update(
                status="backend_or_runtime_failure",
                error_type=type(exc).__name__,
                error=str(exc)[:256],
            )
        finally:
            trace.update(
                select_attempts=session.select_attempts,
                query_seconds=session.query_seconds,
                vm_steps=session.vm_steps,
            )
    after = memory.digest()
    if not learn and after != before:
        raise AssertionError("evaluation panel mutated learned memory")
    trace.update(
        after_memory_digest=after,
        elapsed_seconds=time.monotonic() - start,
        memory_bytes=memory.memory_bytes(),
        memory_snapshot=memory.snapshot(),
    )
    # This field is evaluator-only and added after the interaction is complete.
    trace["evaluator"] = evaluator_metadata(spec)
    return trace


def write_json(path, payload):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def _schedule(stream, stage):
    schedule = [("ordinary", i, spec) for i, spec in enumerate(stream.ordinary[:8])]
    if stage == "full":
        schedule += [("old_before", i, spec) for i, spec in enumerate(stream.old_panel)]
        schedule += [
            ("ordinary", i + 8, spec) for i, spec in enumerate(stream.ordinary[8:])
        ]
        schedule += [("old_after", i, spec) for i, spec in enumerate(stream.old_panel)]
        schedule += [("final", i, spec) for i, spec in enumerate(stream.final_panel)]
    return schedule


def _warm_result(traces, minimum):
    warm = [
        row for row in traces if row["phase"] == "ordinary" and row["episode_index"] < 8
    ]
    complete = (
        len(warm) == 8
        and sorted(row["episode_index"] for row in warm) == list(range(8))
        and all(
            row["status"] in ("completed", "no_valid_answer")
            and not row.get("reflection_stop")
            for row in warm
        )
    )
    correct = sum(row["reward"] == 1.0 for row in warm)
    return {
        "complete": complete,
        "correct": correct,
        "n": len(warm),
        "minimum_correct": minimum,
        "meets_warm_accuracy_gate": complete and correct >= minimum,
    }


class _QualificationStop(RuntimeError):
    pass


def run_study(
    out: Path,
    client,
    *,
    stage="qualification",
    system_prompt=V9_SYSTEM,
    seeds=(94000,),
    conditions=("reuse",),
    arms=("full_history", "evidence", "fragments"),
    limits=DEFAULT_LIMITS,
    minimum_warm_correct=7,
    gate_after_warm=True,
    stop_after=None,
):
    """Run a new development study; never resume or overwrite artifacts.

    Limits describe this invocation's remaining allowance. A development
    controller must deduct prior diagnostics before calling. A selected full
    run continues with the same warm memories; qualification never promotes.
    """
    if stage not in ("qualification", "full"):
        raise ValueError("stage must explicitly select qualification or full")
    if not isinstance(limits, ResourceLimitsV9):
        raise ValueError("ResourceLimitsV9 configuration required")
    if (
        type(minimum_warm_correct) is not int
        or not 1 <= minimum_warm_correct <= 8
        or type(gate_after_warm) is not bool
    ):
        raise ValueError("exact warm threshold and Boolean gate setting required")
    if stop_after is not None and (type(stop_after) is not int or stop_after < 1):
        raise ValueError("debug stop must be a positive exact integer")
    if (
        not seeds
        or len(set(seeds)) != len(seeds)
        or any(type(seed) is not int or not 94000 <= seed <= 94003 for seed in seeds)
        or not conditions
        or len(set(conditions)) != len(conditions)
        or any(
            condition not in ("reuse", "nonreuse", "near_match")
            for condition in conditions
        )
        or len(seeds) * len(conditions) > 4
    ):
        raise ValueError(
            "at most four unique development streams using seeds 94000..94003 are allowed"
        )
    if not arms or len(set(arms)) != len(arms) or any(arm not in ARMS for arm in arms):
        raise ValueError("unique known memory arms required")
    EvidenceMemory(arms[0], system_prompt)
    _check_output_caps(
        client, limits.solve_output_tokens, limits.reflection_output_tokens
    )
    out = Path(out)
    if out.exists():
        raise FileExistsError(
            "completed and partial runs are immutable; use a new directory"
        )
    started = time.monotonic()
    deadline = started + limits.wall_seconds
    source_before = source_hashes()
    client_config = {
        "model": client.model,
        "context_tokens": client.context_tokens,
        "max_output": client.max_output,
        "response_mode": client.response_mode,
        "endpoint": client.endpoint,
        "timeout": client.timeout,
        "decoding": deepcopy(client.decoding.to_dict()),
    }
    expected = {
        "ordinary": 8 if stage == "qualification" else 24,
        "old_before": 0 if stage == "qualification" else 8,
        "old_after": 0 if stage == "qualification" else 8,
        "final": 0 if stage == "qualification" else 8,
    }
    manifest = {
        "version": 10,
        "kind": "evidence_preserving_bounded_repair_development",
        "status": "running",
        "stage": stage,
        "seeds": list(seeds),
        "conditions": list(conditions),
        "arms": list(arms),
        "limits": asdict(limits),
        "resource_scope": "this invocation; prior diagnostics must be deducted by caller",
        "minimum_warm_correct": minimum_warm_correct,
        "gate_after_warm": gate_after_warm,
        "system_prompt": system_prompt,
        "system_prompt_sha256": _text_hash(system_prompt),
        "client_config": client_config,
        "source_sha256": source_before,
        "max_selects_per_question": 8,
        "max_actions_per_question": MAX_ACTIONS,
        "ordinary_query_contract": "bounded_actions_v9_exact_sql_and_params_to_read_only_sqlite",
        "required_phase_counts_per_arm_stream": expected,
        "started_unix": time.time(),
        "stop_after_debug": stop_after,
        "native_benchmark": False,
        "claim_confirmed": False,
        "timing_includes": "source freeze, setup, tokenization, inference, reflection, learning checks, panels and incremental export; model loading is external",
    }
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "manifest.json", manifest)
    total = InferenceBudget(
        max_total_tokens=limits.total_tokens,
        max_calls=limits.total_calls,
        deadline=deadline,
    )
    paired_client = _SharedBudgetClient(client, total)
    count = 0
    active_runs = []
    aggregate = []
    try:
        for seed in seeds:
            for condition in conditions:
                stream = make_stream(seed, condition, split="development")
                memories = {arm: EvidenceMemory(arm, system_prompt) for arm in arms}
                ordinary = {
                    arm: InferenceBudget(
                        max_total_tokens=limits.ordinary_tokens,
                        max_calls=limits.ordinary_calls,
                        deadline=deadline,
                    )
                    for arm in arms
                }
                panels = {
                    arm: InferenceBudget(
                        max_total_tokens=limits.panel_tokens,
                        max_calls=limits.panel_calls,
                        deadline=deadline,
                    )
                    for arm in arms
                }
                rows = {arm: [] for arm in arms}
                active_runs.append((seed, condition, memories, ordinary, panels, rows))
                for step, (phase, index, episode) in enumerate(
                    _schedule(stream, stage)
                ):
                    if step == 8 and stage == "full" and gate_after_warm:
                        if not all(
                            _warm_result(rows[arm], minimum_warm_correct)[
                                "meets_warm_accuracy_gate"
                            ]
                            for arm in arms
                        ):
                            raise _QualificationStop(
                                "one or more configured arms missed the warm competence gate"
                            )
                    offset = step % len(arms)
                    order = tuple(arms[offset:]) + tuple(arms[:offset])
                    for arm in order:
                        if time.monotonic() >= deadline:
                            raise BudgetStop("global_study_wall_ceiling")
                        if memories[arm].system_prompt != system_prompt:
                            raise RuntimeError(
                                "shared solver prompt changed during the run"
                            )
                        budget = ordinary[arm] if phase == "ordinary" else panels[arm]
                        trace = execute_episode(
                            episode,
                            memories[arm],
                            paired_client,
                            budget,
                            phase=phase,
                            learn=phase == "ordinary",
                            solve_output_tokens=limits.solve_output_tokens,
                            reflection_output_tokens=limits.reflection_output_tokens,
                        )
                        trace.update(
                            seed=seed, condition=condition, arm=arm, episode_index=index
                        )
                        with (out / f"{seed}-{condition}-{arm}.jsonl").open(
                            "a", encoding="utf-8"
                        ) as handle:
                            handle.write(canonical(trace) + "\n")
                        rows[arm].append(trace)
                        count += 1
                        print(
                            canonical(
                                {
                                    "episode": count,
                                    "seed": seed,
                                    "condition": condition,
                                    "arm": arm,
                                    "phase": phase,
                                    "index": index,
                                    "reward": trace["reward"],
                                    "selects": trace["select_attempts"],
                                    "status": trace["status"],
                                    "elapsed_seconds": round(
                                        time.monotonic() - started, 2
                                    ),
                                }
                            ),
                            flush=True,
                        )
                        if trace["status"] == "backend_or_runtime_failure":
                            raise RuntimeError(
                                "backend/runtime failure; all remaining runs stopped"
                            )
                        if trace["status"] == "resource_stop" or trace.get(
                            "reflection_stop"
                        ):
                            raise BudgetStop(
                                trace.get("stop_reason")
                                or trace.get("reflection_stop")
                                or "episode_resource_stop"
                            )
                        if stop_after is not None and count >= stop_after:
                            raise BudgetStop("explicit_debug_stop")
        manifest["status"] = "completed"
    except Exception as exc:
        status = (
            "competence_gate_failed"
            if isinstance(exc, _QualificationStop)
            else "stopped"
            if isinstance(exc, BudgetStop)
            else "failed"
        )
        manifest.update(
            status=status,
            failure={"type": type(exc).__name__, "reason": str(exc)[:512]},
        )
    finally:
        all_traces = []
        for run_seed, run_condition, memories, ordinary, panels, rows in active_runs:
            for arm in arms:
                traces = rows[arm]
                all_traces.extend(traces)
                grouped = {
                    phase: [trace for trace in traces if trace["phase"] == phase]
                    for phase in ("ordinary", "old_before", "old_after", "final")
                }
                aggregate.append(
                    {
                        "seed": run_seed,
                        "condition": run_condition,
                        "arm": arm,
                        "ordinary_budget": ordinary[arm].to_dict(),
                        "panel_budget": panels[arm].to_dict(),
                        "memory": memories[arm].snapshot(),
                        "warm": _warm_result(traces, minimum_warm_correct),
                        "phase_counts": {
                            phase: len(items) for phase, items in grouped.items()
                        },
                        "phase_reward": {
                            phase: sum(trace["reward"] for trace in items) / len(items)
                            if items
                            else None
                            for phase, items in grouped.items()
                        },
                        "phase_selects": {
                            phase: sum(trace["select_attempts"] for trace in items)
                            for phase, items in grouped.items()
                        },
                        "phase_failures": {
                            phase: sum(
                                trace["status"] != "completed" for trace in items
                            )
                            for phase, items in grouped.items()
                        },
                    }
                )
        calls = [call for trace in all_traces for call in trace["model_calls"]]
        simulated = any(call.get("test_double") is True for call in calls)
        generated = [call for call in calls if call.get("generation_attempted") is True]
        known_usage = all(
            isinstance(call.get("usage"), dict)
            and all(
                type(call["usage"].get(key)) is int and call["usage"][key] >= 0
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            )
            and call["usage"]["prompt_tokens"] + call["usage"]["completion_tokens"]
            == call["usage"]["total_tokens"]
            for call in generated
        )
        usage_verified = (
            known_usage
            and len(generated) == total.calls
            and all(
                sum(call["usage"][key] for call in generated) == getattr(total, key)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            )
        )
        resources_ok = (
            manifest["status"] not in ("stopped", "failed")
            and total.unknown_usage_calls == 0
            and usage_verified
            and not any(
                trace["status"] in ("resource_stop", "backend_or_runtime_failure")
                or trace.get("reflection_stop")
                for trace in all_traces
            )
        )
        complete = (
            len(aggregate) == len(seeds) * len(conditions) * len(arms)
            and all(row["phase_counts"] == expected for row in aggregate)
            and resources_ok
        )
        after = source_hashes()
        client_after = {
            "model": client.model,
            "context_tokens": client.context_tokens,
            "max_output": client.max_output,
            "response_mode": client.response_mode,
            "endpoint": client.endpoint,
            "timeout": client.timeout,
            "decoding": client.decoding.to_dict(),
        }
        manifest.update(
            completed_episode_records=count,
            source_sha256_after=after,
            source_unchanged=source_before == after,
            client_config_unchanged=client_after == client_config,
            total_budget=total.to_dict(),
            contains_test_double_calls=simulated,
            usage_verified=usage_verified,
            required_records_complete=complete,
            resources_complete=resources_ok,
            raw_sha256={
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(out.glob("*.jsonl"))
            },
        )
        if not manifest["source_unchanged"] or not manifest["client_config_unchanged"]:
            manifest.update(
                status="invalidated",
                invalidation="executed_source_or_client_configuration_changed",
            )
        elif manifest["status"] == "completed" and not complete:
            manifest.update(
                status="incomplete",
                incomplete_reason="missing_required_records_or_resource_stops",
            )
        manifest["warm_qualified"] = (
            manifest["status"] == "completed"
            and complete
            and not simulated
            and all(row["warm"]["meets_warm_accuracy_gate"] for row in aggregate)
        )
        write_json(out / "summary.json", aggregate)
        manifest["summary_sha256"] = hashlib.sha256(
            (out / "summary.json").read_bytes()
        ).hexdigest()
        manifest["elapsed_seconds"] = time.monotonic() - started
        manifest["wall_cap_satisfied"] = (
            manifest["elapsed_seconds"] <= limits.wall_seconds
        )
        if not manifest["wall_cap_satisfied"]:
            manifest.update(
                status="stopped",
                resources_complete=False,
                required_records_complete=False,
                warm_qualified=False,
                failure={
                    "type": "BudgetStop",
                    "reason": "global_wall_ceiling_including_export",
                },
            )
        write_json(out / "manifest.json", manifest)
    return manifest


run_pilot = run_study


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:18085")
    parser.add_argument(
        "--stage", choices=("qualification", "full"), default="qualification"
    )
    parser.add_argument("--system-prompt-file", type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=[94000])
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=("reuse", "nonreuse", "near_match"),
        default=["reuse"],
    )
    parser.add_argument(
        "--arms",
        nargs="+",
        choices=ARMS,
        default=["full_history", "evidence", "fragments"],
    )
    parser.add_argument("--minimum-warm-correct", type=int, default=7)
    parser.add_argument("--no-warm-gate", action="store_true")
    parser.add_argument("--stop-after", type=int)
    for field in (
        "ordinary_tokens",
        "panel_tokens",
        "ordinary_calls",
        "panel_calls",
        "total_tokens",
        "total_calls",
        "solve_output_tokens",
        "reflection_output_tokens",
    ):
        parser.add_argument(
            "--" + field.replace("_", "-"),
            type=int,
            default=getattr(DEFAULT_LIMITS, field),
        )
    parser.add_argument(
        "--wall-seconds", type=float, default=DEFAULT_LIMITS.wall_seconds
    )
    parser.add_argument("--context-tokens", type=int, default=65536)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--response-mode", choices=("schema", "json"), default="schema")
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--min-p", type=float, default=0.0)
    parser.add_argument("--presence-penalty", type=float, default=1.5)
    parser.add_argument("--decoding-seed", type=int, default=42)
    parser.add_argument("--no-thinking", action="store_true")
    args = parser.parse_args()
    limits = ResourceLimitsV9(
        **{
            field: getattr(args, field)
            for field in ResourceLimitsV9.__dataclass_fields__
        }
    )
    decoding = DecodingV9(
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        min_p=args.min_p,
        presence_penalty=args.presence_penalty,
        seed=args.decoding_seed,
        thinking=not args.no_thinking,
    )
    client = LocalInferenceV9Compatible(
        endpoint=args.endpoint,
        model=args.model,
        key_file=args.key_file,
        context_tokens=args.context_tokens,
        max_output=max(limits.solve_output_tokens, limits.reflection_output_tokens),
        timeout=args.timeout,
        decoding=decoding,
        response_mode=args.response_mode,
    )
    system = (
        args.system_prompt_file.read_text(encoding="utf-8")
        if args.system_prompt_file
        else V9_SYSTEM
    )
    result = run_study(
        args.out,
        client,
        stage=args.stage,
        system_prompt=system,
        seeds=tuple(args.seeds),
        conditions=tuple(args.conditions),
        arms=tuple(args.arms),
        limits=limits,
        minimum_warm_correct=args.minimum_warm_correct,
        gate_after_warm=not args.no_warm_gate,
        stop_after=args.stop_after,
    )
    print(
        json.dumps(
            {
                key: result.get(key)
                for key in (
                    "status",
                    "warm_qualified",
                    "failure",
                    "completed_episode_records",
                    "elapsed_seconds",
                )
            },
            indent=2,
        )
    )
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
