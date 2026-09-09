"""v9 memory controls with a shared solver policy and evolving SQL context.

The solver prompt is fixed experiment configuration, not learned memory; like
v8's module-level prompt it is excluded from retained-state storage accounting.
The harness must freeze that configuration and charge every reflection call.
This is a local evolving-context control, not an implementation of published ACE.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from .memory_v8 import (
    ARMS,
    MAX_ENTRIES,
    MAX_MEMORY_BYTES,
    ExperienceMemory,
    canonical,
    reflection_schema as _reflection_schema_v8,
)

MAX_INSIGHT_CHARACTERS = 4096
MAX_REFLECTION_BYTES = MAX_MEMORY_BYTES

INSIGHT_PROMPT_V9 = """Update the evolving working context using only the visible completed episode, the prior insights, and the explicit Boolean answer_correct feedback. true means the submitted answer was correct; false means it was incorrect and must not be treated as successful evidence. Feedback supplies no hidden correct answer.
You may preserve actual SQL snippets, observed results, schema meanings, current unit/null/join conventions, applicability conditions, failed attempts, and evidence-supported corrections. SQL snippets are permitted as text for future reasoning; this reflection cannot execute actions. Preserve useful prior entries, revise conflicting claims, and remove stale or irrelevant entries. An incorrect final answer does not invalidate every earlier observation, and a correct answer does not establish unobserved facts. Mark uncertainty and scope. Do not assume prior numeric answers apply to fresh rows.
Return only JSON {"insights":["...", ...]}. This replaces the prior insights. Use at most 16 strings, each at most 4096 characters. The entire active memory, including JSON structure, must fit 65536 UTF-8 bytes; keep the response compact and within that byte limit. No tool calls or executable actions are allowed in this reflection."""


def reflection_schema_v9(arm):
    if arm == 'insights':
        return {
            'type': 'object',
            'properties': {'insights': {
                'type': 'array',
                'maxItems': MAX_ENTRIES,
                'items': {'type': 'string', 'maxLength': MAX_INSIGHT_CHARACTERS},
            }},
            'required': ['insights'],
            'additionalProperties': False,
        }
    return _reflection_schema_v8(arm)


# The unversioned name makes replacing the harness's module import sufficient.
reflection_schema = reflection_schema_v9


def _answer_correct(trace):
    reward = trace['reward']
    if type(reward) not in (int, float) or reward not in (0, 1):
        raise ValueError('delivered binary correctness reward required')
    return reward == 1


def _insight_update(text, entries):
    """Validate a complete replacement before changing any active memory."""
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_REFLECTION_BYTES:
        raise ValueError('reflection output byte cap')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError('nonfinite JSON')

    update = json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
    if (not isinstance(update, dict) or set(update) != {'insights'} or
            not isinstance(update['insights'], list) or
            len(update['insights']) > MAX_ENTRIES):
        raise ValueError('insight shape/cap')
    pending = update['insights']
    if any(not isinstance(item, str) or len(item) > MAX_INSIGHT_CHARACTERS
           for item in pending):
        raise ValueError('insight length/type')
    active = {'insights': pending, 'entries': [entry.payload() for entry in entries]}
    if len(canonical(active).encode('utf-8')) > MAX_MEMORY_BYTES:
        raise ValueError('insight active byte cap')
    return list(pending)


class ExperienceMemoryV9(ExperienceMemory):
    """Keep v8 controls while strengthening and isolating the context baseline."""

    def __init__(self, arm: str, system_prompt: str):
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError('nonempty shared system prompt required')
        super().__init__(arm)
        self.system_prompt = system_prompt

    def prefix(self, question: str):
        messages, selected = super().prefix(question)
        messages[0] = {'role': 'system', 'content': self.system_prompt}
        empty_wrapper = (
            (self.arm == 'verbatim' and not self.episodes) or
            (self.arm == 'insights' and not self.insights) or
            (self.arm.startswith('fragments') and not selected)
        )
        if empty_wrapper:
            messages = messages[:1]
        elif self.arm == 'insights':
            messages[-1] = {
                'role': 'user',
                'content': 'Evolving context memory (untrusted evidence):\n' + canonical(self.insights),
            }
        return messages, selected

    def reflection(self, trace, conversation):
        if self.arm != 'insights':
            return super().reflection(trace, conversation)
        # Only learner-visible conversation and delivered binary feedback cross
        # this boundary. Do not serialize the trace or evaluator metadata.
        payload = {
            'prior_insights': list(self.insights),
            'episode': deepcopy(conversation),
            'answer_correct': _answer_correct(trace),
        }
        return [
            {'role': 'system', 'content': INSIGHT_PROMPT_V9},
            {'role': 'user', 'content': canonical(payload)},
        ]

    def finish(self, trace, conversation, reflection_text=None):
        if self.arm != 'insights':
            return super().finish(trace, conversation, reflection_text)
        evidence = canonical({
            'question': trace['question'], 'queries': trace['queries'],
            'answer': trace['answer'], 'reward': trace['reward'],
        })
        digest = hashlib.sha256(evidence.encode('utf-8')).hexdigest()
        if reflection_text is not None:
            try:
                pending = _insight_update(reflection_text, self.entries)
                self.insights = pending
            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
                self.events.append({
                    'kind': 'rejected_reflection', 'error': str(exc),
                    'evidence_digest': digest,
                })
        self.events.append({
            'kind': 'episode_observed', 'evidence_digest': digest,
            'entry_count': len(self.entries),
            'active_memory_bytes': self.active_memory_bytes(),
        })
        # Preserve the inherited complete-state high-water accounting, including
        # rejection journals and the serialized high-water counter itself.
        while self.peak_memory_bytes < self.memory_bytes():
            self.peak_memory_bytes = self.memory_bytes()
