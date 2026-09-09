"""Official ACE roles over the native observable-only CL-Bench interface."""
from __future__ import annotations

from copy import deepcopy
import json
import time

from witness_cl.ace_memory import ACEMemory, generator_schema
from .core import CallUsage, ExperienceLedger, ModelReply, TransportFailure


class LocalClientTransport:
    """Use the same measured local client and budget as the custom SQL runner."""

    def __init__(self, client, budget, *, output_tokens=4096):
        self.client, self.budget = client, budget
        self.output_tokens = output_tokens
        self.records = []

    def reset(self):
        # The local client uses visible messages with cache_prompt=False and has no memory.
        # Retain accounting across resets; the runner owns its budget and archive.
        pass

    def _usage(self, records):
        result = []
        for record in records:
            if not record.get("generation_attempted"):
                continue
            usage = record.get("usage") or {}
            result.append(CallUsage(
                model=self.client.model, input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"), provider="local_llama_cpp",
            ))
        return tuple(result)

    def complete(self, *, messages, response_schema):
        return self.complete_phase(messages=messages, response_schema=response_schema,
                                   phase="native:solve")

    def complete_phase(self, *, messages, response_schema, phase):
        start = len(self.records)
        try:
            raw = self.client.complete(
                messages, self.budget, phase=phase, records=self.records,
                response_schema=response_schema, output_tokens=self.output_tokens,
            )
        except Exception as exc:
            raise TransportFailure(str(exc), self._usage(self.records[start:])) from exc
        return ModelReply(raw, self._usage(self.records[start:]))


def accounted_call(api, owner, transport, *, messages, schema, phase):
    """Record every attempt, including failed/parsing calls, exactly once."""
    started = time.monotonic()
    def record(usage, failed):
        for index, item in enumerate(usage):
            owner.record_usage_event(api.usage.UsageEvent(
                call_type=phase, model=item.model, provider=item.provider,
                input_tokens=item.input_tokens, output_tokens=item.output_tokens,
                total_tokens=item.total_tokens, cached_input_tokens=item.cached_input_tokens,
                cost_usd=item.cost_usd, response_id=item.response_id,
                metadata={"failed": failed, "transport_wall_seconds":
                          time.monotonic() - started if index == 0 else 0.0},
            ))
    try:
        if hasattr(transport, "complete_phase"):
            reply = transport.complete_phase(messages=deepcopy(messages),
                response_schema=deepcopy(schema), phase=phase)
        else:
            reply = transport.complete(messages=deepcopy(messages), response_schema=deepcopy(schema))
        if not isinstance(reply, ModelReply):
            raise TypeError("native transport must return ModelReply")
    except Exception as exc:
        usage = exc.usage if isinstance(exc, TransportFailure) else ()
        record(usage or (CallUsage(owner.model),), True)
        raise
    record(reply.usage, False)
    return reply.action if isinstance(reply.action, str) else json.dumps(reply.action)


def make_ace(api, *, transport, model, max_playbook_bytes=65536,
             playbook_token_budget=16384, name="witness_ace"):
    """Native ACE with unchanged official ADD/counter primitives and role prompts.

Domain adaptations: nested native action schema, no query/observation metadata,
and the declared shared memory/token caps. No hidden reference answers are read.
"""
    class NativeACE(api.interface.ContinualLearningSystem):
        supports_baseline = True
        parallel_safe = False

        def __init__(self):
            self.model = model
            self._name = name
            self.memory = ACEMemory(max_playbook_bytes=max_playbook_bytes,
                                    playbook_token_budget=playbook_token_budget)
            self.experience = ExperienceLedger()
            self.conversation = []
            self.question = ""
            self.last_answer = None

        @property
        def name(self):
            return self._name

        def respond(self, query):
            if self.experience.pending:
                raise RuntimeError("native feedback must precede next respond")
            if not self.conversation:
                self.question = query.prompt
            self.conversation.append({"role": "user", "content": query.prompt})
            schema = query.response_schema.model_json_schema()
            raw = accounted_call(api, self, transport,
                messages=self.memory.generator_messages(query.prompt, self.conversation, schema),
                schema=generator_schema(schema), phase="native:ace:solve")
            payload = self.memory.decode_generator(raw)
            action = query.response_schema.model_validate(payload)
            rendered = action.model_dump_json()
            self.conversation.append({"role": "assistant", "content": rendered})
            self.last_answer = payload.get("content")
            self.experience.begin(prompt=query.prompt, action_json=rendered,
                                  response_schema=schema, instance_id=query.instance_id)
            return api.interface.Response(action, metadata={"system_type": self.name,
                "ace_upstream_commit": self.memory.snapshot()["upstream_commit"]})

        def observe(self, observation, next_query=None):
            terminal = api.interface.observation_marks_instance_complete(observation)
            self.experience.observe(content=observation.content, instance_complete=terminal)
            self.conversation.append({"role": "user", "content": observation.content})
            if terminal:
                self.memory.stage_episode(question=self.question, answer=self.last_answer,
                    conversation=self.conversation, feedback=observation.content)
                self.memory.update_with(lambda messages, role: accounted_call(
                    api, self, transport, messages=messages, schema={"type": "object"},
                    phase="native:ace:" + role + ":reflection"))
                self.conversation = []

        def reset(self):
            self.memory.reset()
            self.experience.reset()
            self.conversation = []
            self.question = ""
            self.last_answer = None
            transport.reset()

        def get_run_artifacts(self):
            return {"artifact_type": "native_ace", "memory": self.memory.snapshot(),
                    "experience": self.experience.to_jsonable(),
                    "upstream_source": "official_ace_not_clbench_modified_merger",
                    "public_boundary": "prompt_schema_observation_content_only"}

    return NativeACE()
