"""Configurable, measured local inference for the separate v9 development study.

The frozen v8 client remains unchanged. This subclass reuses only its validated
loopback transport and budget type; the effective request is frozen once per
call and identically supplied to tokenization and generation.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import time

from .model_v8 import BudgetStop, InferenceBudget, LocalInference


@dataclass(frozen=True)
class DecodingV9:
    temperature: float = .7
    top_p: float = .8
    top_k: int = 20
    min_p: float = 0.
    presence_penalty: float = 1.5
    seed: int = 42
    thinking: bool = False

    def __post_init__(self):
        for name, low, high, open_low in (
            ('temperature', 0., 2., False), ('top_p', 0., 1., True),
            ('min_p', 0., 1., False), ('presence_penalty', -2., 2., False),
        ):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or value < low or value > high or (open_low and value == low)):
                raise ValueError('invalid decoding value: ' + name)
        if type(self.top_k) is not int or self.top_k < 0:
            raise ValueError('top_k must be a nonnegative exact integer')
        if type(self.seed) is not int or not 0 <= self.seed <= 2**32 - 1:
            raise ValueError('seed must be an exact uint32 integer')
        if type(self.thinking) is not bool:
            raise ValueError('thinking must be an explicit boolean')

    def to_dict(self):
        return asdict(self)


class LocalInferenceV9(LocalInference):
    """No retries, truncation, uncharged reasoning, or credential logging.

    ``response_mode='schema'`` uses the supplied response schema; ``'json'``
    requests a JSON object without imposing the schema. Both modes leave final
    semantic/action validation to the fixed caller. ``max_output`` is the
    client-wide ceiling; each call may request a smaller ``output_tokens``.
    """
    def __init__(self, *, decoding: DecodingV9 | None = None,
                 response_mode: str = 'schema', **connection):
        if decoding is None:
            decoding = DecodingV9()
        if not isinstance(decoding, DecodingV9):
            raise ValueError('decoding must be a DecodingV9 configuration')
        if response_mode not in ('schema', 'json'):
            raise ValueError('response_mode must be schema or json')
        super().__init__(**connection)
        self.decoding = decoding
        self.response_mode = response_mode

    def complete(self, messages: list[dict[str, str]], budget: InferenceBudget,
                 *, phase: str, records: list[dict], output_tokens: int | None = None,
                 response_schema: dict | None = None):
        limit = self.max_output if output_tokens is None else output_tokens
        if type(limit) is not int or not 1 <= limit <= self.max_output:
            raise ValueError('invalid per-call output allowance')
        if response_schema is not None and not isinstance(response_schema, dict):
            raise ValueError('response schema must be an object or absent')
        budget.check(0, limit)
        decoding = self.decoding.to_dict()
        frozen_messages = deepcopy(messages)
        effective_schema = deepcopy(response_schema) if self.response_mode == 'schema' else None
        body = {
            'model': self.model, 'messages': frozen_messages,
            **{k: v for k, v in decoding.items() if k != 'thinking'},
            'max_tokens': limit, 'cache_prompt': False, 'stream': False,
            'response_format': {'type': 'json_object'},
            'chat_template_kwargs': {'enable_thinking': decoding['thinking']},
        }
        if effective_schema is not None:
            body['response_format']['schema'] = effective_schema
        record = {
            'phase': phase, 'messages': deepcopy(frozen_messages),
            'preflight_tokens': None, 'max_output_tokens': limit,
            'tokenization_seconds': 0., 'status': 'preflight_attempted',
            'generation_attempted': False, 'usage': None,
            'response_mode': self.response_mode,
            'response_schema': deepcopy(effective_schema),
            'decoding': deepcopy(decoding),
            'request_config': deepcopy({k: v for k, v in body.items() if k != 'messages'}),
            'reasoning_content': None,
        }
        records.append(record)
        token_start = time.monotonic()
        try:
            count = self._post('/v1/chat/completions/input_tokens', deepcopy(body),
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
            seconds = time.monotonic() - token_start
            budget.tokenization_seconds += seconds
            record['tokenization_seconds'] = seconds
        record.update(status='attempted', generation_attempted=True)
        budget.calls += 1
        start = time.monotonic()
        try:
            response = self._post('/v1/chat/completions', deepcopy(body),
                                  min(self.timeout, max(.001, budget.deadline - time.monotonic())))
            record['response_model'] = response.get('model')
            usage = response.get('usage', {})
            counts = [usage.get(x) for x in ('prompt_tokens', 'completion_tokens', 'total_tokens')]
            if (any(type(x) is not int or x < 0 for x in counts)
                    or counts[2] != counts[0] + counts[1]):
                raise RuntimeError('missing or inconsistent usage; abort comparison')
            budget.prompt_tokens += counts[0]
            budget.completion_tokens += counts[1]
            budget.total_tokens += counts[2]
            record['usage'] = deepcopy(usage)
            if counts[0] < prompt or counts[0] + counts[1] > self.context_tokens:
                raise RuntimeError('backend prompt/token accounting mismatch')
            if counts[1] > limit:
                raise RuntimeError('backend exceeded per-call output cap')
            if budget.total_tokens > budget.max_total_tokens:
                raise RuntimeError('backend exceeded reserved token budget')
            if record['response_model'] != self.model:
                raise RuntimeError('backend model identity mismatch')
            choice = response['choices'][0]
            message = choice['message']
            content = message.get('content')
            reasoning = message.get('reasoning_content')
            record.update(finish_reason=choice.get('finish_reason'),
                          reasoning_content=deepcopy(reasoning),
                          content_was_null=content is None,
                          backend_timings=deepcopy(response.get('timings')))
            # Some reasoning parsers return null final content when the output
            # allowance is consumed before a final answer. Usage was still real
            # and is already charged; the caller receives an empty action to
            # handle under its normal finite interaction policy.
            if content is None:
                content = ''
            if not isinstance(content, str):
                raise RuntimeError('non-text model reply')
            if reasoning is not None and not isinstance(reasoning, str):
                raise RuntimeError('non-text reasoning reply')
            record.update(status='completed', content=content)
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
