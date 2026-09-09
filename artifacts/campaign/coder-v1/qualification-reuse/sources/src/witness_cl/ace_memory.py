"""Online ACE at an explicit, accounted tool-environment boundary.

Prompts and ADD/counter primitives are vendored from official ACE, commit
82709de050e1db6e6ef2f07bcb0393560b94992a (Apache-2.0). This adapter changes
only the action envelope, observable feedback boundary and resource limits.
The optional upstream bullet analyzer is disabled. It does not replace the
playbook with a summary or implement the upstream merger's unsupported edits.
"""
from __future__ import annotations

from copy import deepcopy
import contextlib
import io
import json

from .query_memory import canonical, digest
from ._vendor.ace.playbook_utils import (
    apply_curator_operations, extract_json_from_text, extract_playbook_bullets,
    get_playbook_stats, parse_playbook_line, update_bullet_counts,
)
from ._vendor.ace.prompts.generator import GENERATOR_PROMPT
from ._vendor.ace.prompts.reflector import REFLECTOR_PROMPT_NO_GT
from ._vendor.ace.prompts.curator import CURATOR_PROMPT_NO_GT

ACE_COMMIT = "82709de050e1db6e6ef2f07bcb0393560b94992a"
EMPTY_PLAYBOOK = "\n\n".join("## " + section for section in (
    "STRATEGIES & INSIGHTS", "FORMULAS & CALCULATIONS", "CODE SNIPPETS & TEMPLATES",
    "COMMON MISTAKES TO AVOID", "PROBLEM-SOLVING HEURISTICS",
    "CONTEXT CLUES & INDICATORS", "OTHERS",
))
JSON_SCHEMA = {"type": "object"}


class ACEUpdateRejected(ValueError):
    """A measured curator response failed host validation; the stream can continue."""


def generator_schema(action_schema):
    return {
        "type": "object", "properties": {
            "reasoning": {"type": "string"},
            "bullet_ids": {"type": "array", "items": {"type": "string"}},
            "final_answer": deepcopy(action_schema),
        }, "required": ["reasoning", "bullet_ids", "final_answer"],
        "additionalProperties": False,
    }


def visible_conversation(conversation):
    """Copy the actual public messages, never the surrounding evaluator trace."""
    result = []
    for message in conversation:
        if not isinstance(message, dict) or message.get("role") not in {
                "system", "user", "assistant", "tool"}:
            raise ValueError("public conversation message required")
        if not isinstance(message.get("content"), str):
            raise ValueError("public message content must be text")
        result.append({"role": message["role"], "content": message["content"]})
    return result


class ACEMemory:
    arm = "ace"
    generator_schema = staticmethod(generator_schema)

    def __init__(self, *, max_playbook_bytes=65536, playbook_token_budget=16384):
        if type(max_playbook_bytes) is not int or max_playbook_bytes < len(EMPTY_PLAYBOOK):
            raise ValueError("playbook byte budget is too small")
        if type(playbook_token_budget) is not int or playbook_token_budget < 1:
            raise ValueError("positive playbook token budget required")
        self.max_playbook_bytes = max_playbook_bytes
        self.playbook_token_budget = playbook_token_budget
        self.reset()

    def reset(self):
        self.playbook = EMPTY_PLAYBOOK
        self.next_id = 1
        self.updates = 0
        self.events = []
        self.pending = None
        self.used_ids = []
        self.generator_records = []

    def active_payload(self):
        return {"playbook": self.playbook}

    def active_bytes(self):
        return len(canonical(self.active_payload()).encode())

    def snapshot(self):
        return deepcopy({
            "arm": self.arm, "upstream_commit": ACE_COMMIT,
            "active": self.active_payload(), "next_id": self.next_id,
            "updates": self.updates, "events": self.events, "pending": self.pending,
            "used_ids": self.used_ids, "generator_records": self.generator_records,
            "active_bytes": self.active_bytes(), "analyzer": False,
            "max_playbook_bytes": self.max_playbook_bytes,
            "playbook_token_budget": self.playbook_token_budget,
        })

    def state_digest(self):
        return digest(self.snapshot())

    @classmethod
    def from_snapshot(cls, snapshot):
        if snapshot.get("arm") != "ace" or snapshot.get("upstream_commit") != ACE_COMMIT:
            raise ValueError("ACE snapshot algorithm identity mismatch")
        memory = cls(max_playbook_bytes=snapshot["max_playbook_bytes"],
                     playbook_token_budget=snapshot["playbook_token_budget"])
        memory.playbook = snapshot["active"]["playbook"]
        for name in ("next_id", "updates", "events", "pending",
                     "used_ids", "generator_records"):
            setattr(memory, name, deepcopy(snapshot[name]))
        if memory.snapshot() != snapshot:
            raise ValueError("ACE snapshot failed exact round-trip validation")
        return memory

    def prefix(self, question, schema=None):
        # Compatibility only: faithful ACE runs also call generator_messages.
        return [{"role": "user", "content": "ACE playbook:\n" + self.playbook}], []

    def selected(self, question, schema=None):
        return []

    def generator_messages(self, question, conversation, action_schema):
        context = canonical(visible_conversation(conversation))
        adapted_question = question + (
            "\nThis is one tool interaction. The final_answer field must be a JSON "
            "object matching this action schema, rather than an answer string:\n"
            + canonical(action_schema)
        )
        prompt = GENERATOR_PROMPT.format(self.playbook, "(empty)", adapted_question, context)
        return [{"role": "user", "content": prompt}]

    def decode_generator(self, text):
        payload = extract_json_from_text(text)
        if not isinstance(payload, dict) or not isinstance(payload.get("final_answer"), dict):
            raise ValueError("ACE generator requires an action object in final_answer")
        ids = payload.get("bullet_ids", [])
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            raise ValueError("ACE bullet_ids must be a string list")
        known = {p["id"] for line in self.playbook.splitlines()
                 if (p := parse_playbook_line(line))}
        cited = list(dict.fromkeys(x for x in ids if x in known))
        self.used_ids = list(dict.fromkeys(self.used_ids + cited))
        self.generator_records.append({"response": text, "bullet_ids": cited})
        return deepcopy(payload["final_answer"])

    def finish(self, trace, conversation):
        """Stage one completed public episode. Caller must then run update()."""
        if self.pending is not None:
            raise RuntimeError("previous ACE episode still awaits accounted update")
        if not trace.get("learn") or trace.get("phase") != "ordinary":
            raise ValueError("only ordinary learning episodes can update ACE")
        feedback = trace.get("feedback", {}).get("correct")
        if type(feedback) is not bool:
            raise ValueError("delivered Boolean correctness feedback required")
        self.stage_episode(
            question=trace["question"], answer=trace.get("answer"),
            conversation=conversation, feedback=canonical({"correct": feedback}),
        )

    def stage_episode(self, *, question, answer, conversation, feedback):
        if self.pending is not None:
            raise RuntimeError("previous ACE episode still awaits accounted update")
        if not isinstance(question, str) or not isinstance(feedback, str):
            raise ValueError("observed question and feedback must be text")
        self.pending = {
            "question": question, "answer": deepcopy(answer),
            "conversation": visible_conversation(conversation), "feedback": feedback,
            "generator_records": deepcopy(self.generator_records),
            "bullet_ids": list(self.used_ids),
        }
        self.used_ids.clear()
        self.generator_records.clear()

    def update(self, client, budget, records, *, output_tokens=4096):
        """Run two separately charged calls on the shared local client interface."""
        def complete(messages, role):
            return client.complete(messages, budget, phase="ace:" + role + ":reflection",
                                   records=records, output_tokens=output_tokens,
                                   response_schema=JSON_SCHEMA)
        return self.update_with(complete)

    def update_with(self, complete):
        """Transport adapter hook: complete(messages, role) must account each call."""
        if self.pending is None:
            raise RuntimeError("no completed ACE episode staged")
        episode = deepcopy(self.pending)
        event = {"event": "ace_update", "episode_sha256": digest(episode),
                 "playbook_before": self.playbook, "status": "started"}
        self.events.append(event)
        try:
            used = extract_playbook_bullets(self.playbook, episode["bullet_ids"])
            prompt = REFLECTOR_PROMPT_NO_GT.format(
                episode["question"], canonical({"conversation": episode["conversation"],
                    "generator_outputs": episode["generator_records"]}),
                canonical(episode["answer"]), episode["feedback"], used,
            )
            reflection = complete([{"role": "user", "content": prompt}], "reflector")
            event["reflection"] = reflection
            # Upstream JSON-mode reflector uses json.loads, with [] on decode failure.
            try:
                tags = json.loads(reflection).get("bullet_tags", [])
            except (json.JSONDecodeError, AttributeError):
                tags = []
            allowed = set(episode["bullet_ids"])
            tags = [tag for tag in tags if isinstance(tag, dict)
                    and (tag.get("id") or tag.get("bullet")) in allowed
                    and tag.get("tag") in {"helpful", "harmful", "neutral"}] if isinstance(tags, list) else []
            if tags:
                self.playbook = update_bullet_counts(self.playbook, tags)
            self.updates += 1
            prompt = CURATOR_PROMPT_NO_GT.format(
                current_step=self.updates, total_samples=self.updates,
                token_budget=self.playbook_token_budget,
                playbook_stats=json.dumps(get_playbook_stats(self.playbook), indent=2),
                recent_reflection=reflection, current_playbook=self.playbook,
                question_context=episode["question"],
            )
            response = complete([{"role": "user", "content": prompt}], "curator")
            event["curator"] = response
            proposal = extract_json_from_text(response)
            if not isinstance(proposal, dict) or not isinstance(proposal.get("reasoning"), str):
                raise ACEUpdateRejected("ACE curator requires reasoning and operations")
            operations = proposal.get("operations")
            if not isinstance(operations, list):
                raise ACEUpdateRejected("ACE curator operations must be a list")
            for operation in operations:
                if not isinstance(operation, dict) or operation.get("type") not in {
                        "ADD", "UPDATE", "MERGE", "DELETE", "CREATE_META"}:
                    raise ACEUpdateRejected("invalid ACE operation")
                if operation["type"] == "ADD" and (
                        not isinstance(operation.get("section"), str)
                        or not isinstance(operation.get("content"), str)):
                    raise ACEUpdateRejected("ACE ADD requires section and content strings")
            # Preserve exact official ADD-only merging, including unsupported-operation no-ops.
            with contextlib.redirect_stdout(io.StringIO()):
                updated, next_id = apply_curator_operations(self.playbook, operations, self.next_id)
            if len(canonical({"playbook": updated}).encode()) > self.max_playbook_bytes:
                raise ACEUpdateRejected("ACE playbook byte ceiling exceeded; update rejected")
            self.playbook, self.next_id = updated, next_id
            event.update(status="completed", operations=deepcopy(operations))
        except ACEUpdateRejected as exc:
            event.update(status="rejected", error_type=type(exc).__name__, error=str(exc),
                         counters_retained=True)
        except Exception as exc:
            event.update(status="failed", error_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            event["playbook_after"] = self.playbook
            self.pending = None
        return deepcopy(event)
