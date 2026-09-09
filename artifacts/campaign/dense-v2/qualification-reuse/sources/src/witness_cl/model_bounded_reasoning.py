"""Native reasoning cutoff with exact preflight and generation wire receipts."""

from copy import deepcopy
import hashlib
import json
import threading

from .model_v9_compatible import LocalInferenceV9Compatible


class LocalInferenceBoundedReasoning(LocalInferenceV9Compatible):
    """The native sampler closes thinking; the host never edits generated text.

    One instance permits one active call because the inherited reflection path
    temporarily changes decoding. Reasoning and forced closure consume the same
    measured completion allowance as final content.
    """

    def __init__(self, *, reasoning_budget_tokens, **kwargs):
        if type(reasoning_budget_tokens) is not int or not 0 <= reasoning_budget_tokens <= 8192:
            raise ValueError("native reasoning budget must be an exact integer in 0..8192")
        super().__init__(**kwargs)
        if reasoning_budget_tokens >= self.max_output:
            raise ValueError("total output allowance must leave room after reasoning")
        self._reasoning_budget_tokens = reasoning_budget_tokens
        self._request_lock = threading.Lock()
        self._wire_requests = None

    @property
    def reasoning_budget_tokens(self):
        return self._reasoning_budget_tokens

    def _post(self, path, payload, timeout):
        if self._wire_requests is None:
            raise RuntimeError("native transport requires an active measured completion")
        if path not in ("/v1/chat/completions/input_tokens", "/v1/chat/completions"):
            raise ValueError("unexpected native generation endpoint")
        body = deepcopy(payload)
        if "reasoning_budget_tokens" in body:
            raise ValueError("reasoning budget must have one frozen source")
        body["reasoning_budget_tokens"] = self.reasoning_budget_tokens
        encoded_messages = json.dumps(
            body["messages"], allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode()
        self._wire_requests.append(
            {
                "path": path,
                "request_config": deepcopy({k: v for k, v in body.items() if k != "messages"}),
                "messages_sha256": hashlib.sha256(encoded_messages).hexdigest(),
            }
        )
        return super()._post(path, body, timeout)

    def complete(
        self, messages, budget, *, phase, records, output_tokens=None, response_schema=None
    ):
        limit = self.max_output if output_tokens is None else output_tokens
        if (
            self.decoding.thinking
            and not phase.endswith(":reflection")
            and limit <= self.reasoning_budget_tokens
        ):
            raise ValueError("per-call output allowance must leave room after reasoning")
        if not self._request_lock.acquire(blocking=False):
            raise RuntimeError("use separate clients for simultaneous model requests")
        start = len(records)
        self._wire_requests = []
        frozen_budget = self.reasoning_budget_tokens
        try:
            return super().complete(
                messages,
                budget,
                phase=phase,
                records=records,
                output_tokens=output_tokens,
                response_schema=response_schema,
            )
        finally:
            for record in records[start:]:
                record["native_reasoning_budget_tokens"] = frozen_budget
                record["request_config"]["reasoning_budget_tokens"] = frozen_budget
                record["native_wire_requests"] = deepcopy(self._wire_requests)
            self._wire_requests = None
            self._request_lock.release()
