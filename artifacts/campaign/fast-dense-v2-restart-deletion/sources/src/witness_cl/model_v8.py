"""Measured, bounded local inference. The model has no tool authority."""
from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import json
import math
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


class BudgetStop(RuntimeError):
    """A declared resource ceiling was reached before another model call."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('redirects are forbidden')


@dataclass
class InferenceBudget:
    max_total_tokens: int = 300_000
    max_calls: int = 320
    deadline: float = float('inf')
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    tokenization_seconds: float = 0.
    inference_seconds: float = 0.
    unknown_usage_calls: int = 0

    def __post_init__(self):
        for name in ('max_total_tokens', 'max_calls'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError('positive exact integer budget limit required: ' + name)
        for name in ('total_tokens', 'prompt_tokens', 'completion_tokens', 'calls', 'unknown_usage_calls'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError('nonnegative exact integer budget counter required: ' + name)
        if (type(self.deadline) not in (int, float) or math.isnan(self.deadline)
                or self.deadline <= 0):
            raise ValueError('positive monotonic deadline or positive infinity required')

    def check(self, input_tokens: int, reserved_output: int):
        if (type(input_tokens) is not int or input_tokens < 0
                or type(reserved_output) is not int or reserved_output < 1):
            raise ValueError('nonnegative input and positive reserved output token counts required')
        if time.monotonic() >= self.deadline:
            raise BudgetStop('wall_time_ceiling')
        if self.calls >= self.max_calls:
            raise BudgetStop('model_call_ceiling')
        if self.total_tokens + input_tokens + reserved_output > self.max_total_tokens:
            raise BudgetStop('model_token_ceiling')

    def to_dict(self):
        return {k: v for k, v in vars(self).items() if k != 'deadline'}


class LocalInference:
    """Exact backend token preflight, complete usage, no retries or truncation.

    A failed request is charged as attempted with unknown usage and aborts the
    comparison. Model output is always data; the harness interprets a fixed API.
    """
    def __init__(self, *, endpoint='http://127.0.0.1:18084',
                 model='witness-v8-qwen3-4b-q8', key_file: str | Path,
                 context_tokens=32768, max_output=384, timeout=90.):
        url = urlparse(endpoint)
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or
            url.username or url.password or url.path or url.query or url.fragment):
            raise ValueError('only an explicit loopback HTTP endpoint is allowed')
        if (type(context_tokens) is not int or type(max_output) is not int
                or context_tokens <= max_output or max_output < 1
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0
                or type(model) is not str or not model.strip()):
            raise ValueError('invalid model limits')
        self.endpoint, self.model = endpoint, model
        self.context_tokens, self.max_output, self.timeout = context_tokens, max_output, timeout
        self._key = Path(key_file).read_text().strip()
        if not self._key:
            raise ValueError('missing local server credential')
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _post(self, path, payload, timeout):
        raw = json.dumps(payload, allow_nan=False, separators=(',', ':')).encode()
        req = Request(self.endpoint + path, data=raw,
                      headers={'Content-Type': 'application/json',
                               'Authorization': 'Bearer ' + self._key})
        with self.opener.open(req, timeout=timeout) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise RuntimeError('oversized backend reply')
        return json.loads(raw)

    def complete(self, messages: list[dict[str, str]], budget: InferenceBudget,
                 *, phase: str, records: list[dict], output_tokens: int | None = None,
                 response_schema: dict | None = None):
        limit = self.max_output if output_tokens is None else output_tokens
        if type(limit) is not int or not 1 <= limit <= self.max_output:
            raise ValueError('invalid per-call output allowance')
        budget.check(0, limit)
        # Audit records and both requests freeze the same complete conversation.
        # Later caller appends cannot rewrite the apparent earlier model input.
        frozen_messages = deepcopy(messages)
        body = {'model': self.model, 'messages': frozen_messages,
                'temperature': 0., 'seed': 42, 'max_tokens': limit,
                'cache_prompt': False, 'stream': False,
                'response_format': {'type': 'json_object'},
                'chat_template_kwargs': {'enable_thinking': False}}
        if response_schema is not None:
            body['response_format']['schema'] = deepcopy(response_schema)
        record = {'phase': phase, 'messages': deepcopy(frozen_messages), 'preflight_tokens': None,
                  'max_output_tokens': limit, 'tokenization_seconds': 0.,
                  'status': 'preflight_attempted', 'generation_attempted': False, 'usage': None,
                  'response_schema': deepcopy(response_schema)}
        records.append(record)
        token_start = time.monotonic()
        try:
            count = self._post('/v1/chat/completions/input_tokens', body,
                               min(self.timeout, max(.001, budget.deadline - time.monotonic())))
            prompt = count.get('input_tokens') if isinstance(count, dict) else None
            if type(prompt) is not int or prompt < 0:
                raise RuntimeError('token preflight did not return an exact count')
            record['preflight_tokens'] = prompt
            if prompt + limit > self.context_tokens:
                raise BudgetStop('full_context_ceiling_no_truncation')
            budget.check(prompt, limit)
        except Exception as exc:
            record.update(status='preflight_failed', error_type=type(exc).__name__)
            if isinstance(exc, BudgetStop):
                record['stop_reason'] = str(exc)
            raise
        finally:
            token_seconds = time.monotonic() - token_start
            budget.tokenization_seconds += token_seconds
            record['tokenization_seconds'] = token_seconds
        record.update(status='attempted', generation_attempted=True)
        budget.calls += 1
        start = time.monotonic()
        try:
            response = self._post('/v1/chat/completions', body,
                                 min(self.timeout, max(.001, budget.deadline - time.monotonic())))
            record['response_model'] = response.get('model')
            usage = response.get('usage', {})
            counts = [usage.get(x) for x in ('prompt_tokens', 'completion_tokens', 'total_tokens')]
            if (any(type(x) is not int or x < 0 for x in counts) or
                counts[2] != counts[0] + counts[1]):
                raise RuntimeError('missing or inconsistent usage; abort comparison')
            budget.prompt_tokens += counts[0]
            budget.completion_tokens += counts[1]
            budget.total_tokens += counts[2]
            record['usage'] = deepcopy(usage)
            # Backend can have additional special tokens. Never claim full history
            # if its actual prompt was shorter than the exact template preflight.
            if counts[0] < prompt or counts[0] + counts[1] > self.context_tokens:
                raise RuntimeError('backend prompt/token accounting mismatch')
            if counts[1] > limit:
                raise RuntimeError('backend exceeded per-call output cap')
            if budget.total_tokens > budget.max_total_tokens:
                raise RuntimeError('backend exceeded reserved token budget')
            if record['response_model'] != self.model:
                raise RuntimeError('backend model identity mismatch')
            choice = response['choices'][0]
            content = choice['message']['content']
            if not isinstance(content, str):
                raise RuntimeError('non-text model reply')
            record.update(status='completed', content=content,
                          finish_reason=choice.get('finish_reason'),
                          backend_timings=response.get('timings'))
            return content
        except Exception as exc:
            record.update(status='failed', error_type=type(exc).__name__)
            if record['usage'] is None:
                budget.unknown_usage_calls += 1
            raise
        finally:
            seconds = time.monotonic() - start
            budget.inference_seconds += seconds
            record['inference_seconds'] = seconds
