"""Native adapter wire contracts; no model or network calls."""

from copy import deepcopy

import pytest

from witness_cl.model_bounded_reasoning import LocalInferenceBoundedReasoning
from witness_cl.model_v8 import InferenceBudget
from witness_cl.model_v9 import DecodingV9
from witness_cl.model_v9_compatible import LocalInferenceV9Compatible


def client(tmp_path, **kwargs):
    key = tmp_path / "test.key"
    key.write_text("explicit-offline-test-key")
    return LocalInferenceBoundedReasoning(
        key_file=key,
        max_output=4096,
        context_tokens=65536,
        reasoning_budget_tokens=1024,
        decoding=DecodingV9(thinking=True),
        **kwargs,
    )


def transport(seen, *, fail_generation=False):
    def post(self, path, body, timeout):
        seen.append((path, deepcopy(body)))
        if path.endswith("input_tokens"):
            return {"input_tokens": 11}
        if fail_generation:
            raise TimeoutError("explicit offline transport failure")
        return {
            "model": self.model,
            "usage": {"prompt_tokens": 11, "completion_tokens": 17, "total_tokens": 28},
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"value": 95}',
                        "reasoning_content": "a short calculation",
                    },
                }
            ],
        }

    return post


def complete(c, **kwargs):
    records, budget = [], InferenceBudget()
    value = c.complete(
        [{"role": "user", "content": "37+58"}],
        budget,
        phase=kwargs.pop("phase", "generic:solve"),
        records=records,
        response_schema={
            "type": "object",
            "properties": {"value": {"type": "number"}},
            "required": ["value"],
        },
        **kwargs,
    )
    return value, records, budget


def test_exact_same_native_budget_and_payload_on_preflight_and_generation(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(LocalInferenceV9Compatible, "_post", transport(seen))
    c = client(tmp_path)
    value, records, budget = complete(c, output_tokens=4096)
    assert value == '{"value": 95}'
    assert len(seen) == 2 and seen[0][1] == seen[1][1]
    assert seen[0][1]["reasoning_budget_tokens"] == 1024
    record = records[0]
    assert record["native_reasoning_budget_tokens"] == 1024
    assert record["request_config"] == record["native_wire_requests"][0]["request_config"]
    assert (
        record["native_wire_requests"][0]["request_config"]
        == record["native_wire_requests"][1]["request_config"]
    )
    assert budget.total_tokens == 28 and budget.completion_tokens == 17
    assert record["reasoning_content"] == "a short calculation"


def test_failed_generation_retains_actual_wire_and_unknown_usage(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(LocalInferenceV9Compatible, "_post", transport(seen, fail_generation=True))
    c, records, budget = client(tmp_path), [], InferenceBudget()
    with pytest.raises(TimeoutError):
        c.complete(
            [{"role": "user", "content": "test"}],
            budget,
            phase="generic:solve",
            records=records,
            output_tokens=4096,
        )
    assert budget.calls == 1 and budget.unknown_usage_calls == 1
    assert len(records[0]["native_wire_requests"]) == 2
    assert records[0]["request_config"]["reasoning_budget_tokens"] == 1024
    assert c._request_lock.acquire(blocking=False)
    c._request_lock.release()


def test_reflection_stays_nonthinking_and_does_not_mutate_solver_decoding(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(LocalInferenceV9Compatible, "_post", transport(seen))
    c = client(tmp_path)
    _, records, _ = complete(c, phase="ordinary:reflection", output_tokens=128)
    assert all(x[1]["chat_template_kwargs"]["enable_thinking"] is False for x in seen)
    assert records[0]["decoding"]["thinking"] is False
    assert c.decoding.thinking is True


@pytest.mark.parametrize("value", [True, -1, 1.5, 8193])
def test_invalid_native_budget_rejected_before_transport(tmp_path, value):
    with pytest.raises(ValueError, match="exact integer"):
        LocalInferenceBoundedReasoning(reasoning_budget_tokens=value, key_file=tmp_path / "absent")


def test_output_headroom_and_concurrent_client_use_are_explicit(tmp_path):
    c = client(tmp_path)
    with pytest.raises(ValueError, match="room"):
        complete(c, output_tokens=1024)
    c._request_lock.acquire()
    with pytest.raises(RuntimeError, match="separate clients"):
        complete(c, output_tokens=4096)
    c._request_lock.release()
