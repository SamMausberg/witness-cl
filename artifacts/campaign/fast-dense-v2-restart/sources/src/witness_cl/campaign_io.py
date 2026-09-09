"""Durable model-call journals with explicit recovery, never silent retries."""

from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (canonical(value) + "\n").encode()
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read(path):
    return json.loads(Path(path).read_text())


@contextmanager
def study_lock(directory):
    """One runner/auditor may own a study at a time; no journal races."""
    with (Path(directory) / "invocation.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another invocation owns this study") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def usage(calls):
    result = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "unknown_usage_calls": 0,
        "potential_generation_calls": 0,
    }
    for call in calls:
        attempted = call.get("generation_attempted")
        if type(attempted) is not bool:
            raise ValueError("explicit Boolean generation-attempt receipt required")
        if attempted:
            result["calls"] += 1
            result["potential_generation_calls"] += call.get("attempt_uncertain") is True
            value = call.get("usage")
            if value is None:
                result["unknown_usage_calls"] += 1
                continue
            if any(
                type(value.get(k)) is not int or value[k] < 0
                for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            ):
                raise ValueError("invalid token receipt")
            if value["prompt_tokens"] + value["completion_tokens"] != value["total_tokens"]:
                raise ValueError("inconsistent token receipt")
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                result[key] += value[key]
        elif call.get("usage") is not None:
            raise ValueError("token usage without a generation attempt")
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        result["known_" + key] = result[key]
        if result["unknown_usage_calls"]:
            result[key] = None
    return result


def uncertain_receipt(*, messages, phase, output_tokens, response_schema, reason):
    return {
        "status": "failed", "generation_attempted": True, "attempt_uncertain": True,
        "usage": None, "messages": deepcopy(messages), "phase": phase,
        "max_output_tokens": output_tokens, "response_schema": deepcopy(response_schema),
        "host_response_schema": deepcopy(response_schema), "error_type": "UncertainCall",
        "error": reason,
    }


def journal_usage(directory):
    """Include interrupted requests that never reached an episode checkpoint."""
    calls = []
    for path in sorted(Path(directory).glob("*/*.json")):
        receipt = read(path)
        captured = receipt.get("calls", [])
        if not captured:
            captured = [uncertain_receipt(messages=[], phase=receipt.get("phase", "unknown"),
                         output_tokens=receipt.get("output_tokens", 0),
                         response_schema=receipt.get("response_schema"),
                         reason="durable request has no completion/usage receipt")]
        calls.extend(captured)
    return usage(calls)


class UncertainCall(RuntimeError):
    pass


class TranscriptMismatch(RuntimeError):
    pass


def replay_call(call, messages, budget, *, phase, records, output_tokens, response_schema):
    if call.get("status") != "completed" or call.get("usage") is None:
        records.append(deepcopy(call))
        cost = usage([call])
        for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens"):
            amount = cost[key] if key == "calls" else cost["known_" + key]
            setattr(budget, key, getattr(budget, key) + amount)
        budget.unknown_usage_calls += cost["unknown_usage_calls"]
        raise UncertainCall("pending or failed model call cannot be retried as if unseen")
    if canonical(call["messages"]) != canonical(messages) or call["phase"] != phase:
        raise TranscriptMismatch("recorded prompt or role differs during recovery")
    host = call.get("host_response_schema", call.get("response_schema"))
    if canonical(host) != canonical(response_schema):
        raise TranscriptMismatch("response schema differs during recovery")
    if call.get("max_output_tokens", output_tokens) != output_tokens:
        raise TranscriptMismatch("output allowance differs during recovery")
    cost = usage([call])
    if cost["unknown_usage_calls"]:
        raise UncertainCall("call lacks measured usage")
    budget.check(cost["prompt_tokens"], output_tokens)
    for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens"):
        setattr(budget, key, getattr(budget, key) + cost[key])
    for key in ("tokenization_seconds", "inference_seconds"):
        setattr(budget, key, getattr(budget, key, 0.0) + call.get(key, 0.0))
    records.append(deepcopy(call))
    return call["content"]


class RecordedClient:
    def __init__(self, calls):
        self.calls = deepcopy(calls)
        self.index = 0

    def complete(self, messages, budget, **kwargs):
        if self.index >= len(self.calls):
            raise TranscriptMismatch("replay requested an unrecorded call")
        call = self.calls[self.index]
        self.index += 1
        return replay_call(call, messages, budget, **kwargs)


class JournalClient:
    """One isolated episode. Existing successful calls replay without generation.

    A durable pending marker precedes the underlying client invocation. If a
    process dies during a request, recovery stops instead of repeating a possibly
    paid model call. Fully recorded calls can rebuild an interrupted episode.
    """

    def __init__(self, client, directory):
        self.client = client
        self.directory = Path(directory)
        self.index = 0
        self.directory.mkdir(parents=True, exist_ok=True)

    def complete(self, messages, budget, *, phase, records, output_tokens, response_schema=None):
        path = self.directory / f"{self.index:03d}.json"
        self.index += 1
        kwargs = dict(
            phase=phase,
            records=records,
            output_tokens=output_tokens,
            response_schema=response_schema,
        )
        if path.exists():
            receipt = read(path)
            if receipt.get("state") != "recorded" or len(receipt.get("calls", [])) != 1:
                recovered = receipt.get("calls") or [uncertain_receipt(
                    messages=messages, phase=phase, output_tokens=output_tokens,
                    response_schema=response_schema,
                    reason="pending invocation may have generated output; automatic retry prohibited")]
                records.extend(deepcopy(recovered))
                cost = usage(recovered)
                budget.calls += cost["calls"]
                budget.unknown_usage_calls += cost["unknown_usage_calls"]
                for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    setattr(budget, name, getattr(budget, name) + cost["known_" + name])
                raise UncertainCall("uncertain invocation retained; automatic retry prohibited")
            return replay_call(receipt["calls"][0], messages, budget, **kwargs)
        # A local exhausted budget is known not to invoke transport. Do this
        # before reserving the durable pending slot.
        budget.check(0, output_tokens)
        save(
            path,
            {
                "state": "pending",
                "phase": phase,
                "messages_sha256": hashlib.sha256(canonical(messages).encode()).hexdigest(),
                "output_tokens": output_tokens,
                "response_schema": response_schema,
            },
        )
        captured = []
        before_calls = budget.calls
        try:
            content = self.client.complete(
                messages,
                budget,
                phase=phase,
                records=captured,
                output_tokens=output_tokens,
                response_schema=response_schema,
            )
            if len(captured) != 1:
                raise UncertainCall("one invocation requires one complete measured call receipt")
            return content
        finally:
            # Even errors retain all available backend usage. A zero-record error
            # remains uncertain unless the caller can establish it was preflight.
            if not captured:
                captured.append(uncertain_receipt(
                    messages=messages, phase=phase, output_tokens=output_tokens,
                    response_schema=response_schema,
                    reason="client returned or raised without a measured call receipt"))
                budget.unknown_usage_calls += 1
                if budget.calls == before_calls:
                    budget.calls += 1
            state = "recorded" if len(captured) == 1 and not captured[0].get("attempt_uncertain") else "uncertain"
            save(path, {"state": state, "calls": captured})
            records.extend(captured)

    def all_calls_consumed(self):
        return {p.name for p in self.directory.glob("*.json")} == {
            f"{i:03d}.json" for i in range(self.index)
        }
