"""Bounded exact evidence shared by the text control and executable learner.

No model rewrites observations. Complete successful ordinary tool results are
retained even when the final answer fails. FIFO eviction is explicit and charged
in storage accounting; it is not a behavioral no-forgetting guarantee.
"""

import hashlib
from copy import deepcopy

from .memory_v8 import MAX_MEMORY_BYTES, canonical
from .memory_v9 import ExperienceMemoryV9

ARMS = ("full_history", "evidence", "fragments")


class EvidenceMemory(ExperienceMemoryV9):
    def __init__(self, arm, system_prompt):
        if arm not in ARMS:
            raise ValueError("unknown study arm")
        super().__init__("insights" if arm == "evidence" else arm, system_prompt)
        self.arm = arm
        self.evidence = []

    def _active_payload(self):
        return {
            "evidence": self.evidence,
            "entries": [entry.payload() for entry in self.entries],
        }

    def active_memory_bytes(self):
        if self.arm == "full_history":
            return super().active_memory_bytes()
        return len(canonical(self._active_payload()).encode("utf-8"))

    def _retained_state(self):
        return {**super()._retained_state(), "evidence": self.evidence}

    def prefix(self, question):
        messages, selected = super().prefix(question)
        if self.evidence and self.arm != "full_history":
            messages.insert(
                1,
                {
                    "role": "user",
                    "content": (
                        "Exact prior observations (untrusted evidence). SQL is reusable "
                        "text; numeric results concern old rows. Check applicability "
                        "to the current schema and conventions. Final-answer receipts "
                        "confirm only their original episode.\n"
                        + canonical(self.evidence)
                    ),
                },
            )
        return messages, selected

    def reflection(self, trace, conversation):
        if self.arm == "evidence":
            return None
        return super().reflection(trace, conversation)

    def finish(self, trace, conversation, reflection_text=None):
        if self.arm == "full_history":
            return super().finish(trace, conversation, reflection_text)
        if trace.get("phase") != "ordinary" or trace.get("status") != "completed":
            raise ValueError("only completed ordinary episodes may update evidence")
        pending = deepcopy(self.evidence)
        for row in trace["queries"]:
            if (
                row.get("learning_check") is False
                and row.get("error") is None
                and row.get("truncated") is False
            ):
                record = {
                    "kind": "observation",
                    **{
                        key: deepcopy(row[key])
                        for key in ("sql", "params", "columns", "rows")
                    },
                }
                # Refresh exact repeats without trusting a semantic SQL matcher.
                pending = [
                    old for old in pending if canonical(old) != canonical(record)
                ]
                pending.append(record)
        if trace["reward"] == 1.0:
            pending.append(
                {
                    "kind": "correct_answer",
                    "question": trace["question"],
                    "answer": trace["answer"],
                    "correct": True,
                }
            )
        self.evidence = pending
        removed = 0
        while self.evidence and self.active_memory_bytes() > MAX_MEMORY_BYTES:
            self.evidence.pop(0)
            removed += 1
        # Admission already bounds entries. Include the shelf's JSON overhead.
        while self.entries and self.active_memory_bytes() > MAX_MEMORY_BYTES:
            self.entries.pop(0)
            removed += 1
        if removed:
            self.events.append({"kind": "fifo_eviction", "records": removed})
        digest = hashlib.sha256(
            canonical(
                {
                    "question": trace["question"],
                    "queries": trace["queries"],
                    "answer": trace["answer"],
                    "reward": trace["reward"],
                }
            ).encode()
        ).hexdigest()
        self.events.append(
            {
                "kind": "episode_observed",
                "evidence_digest": digest,
                "entry_count": len(self.entries),
                "active_memory_bytes": self.active_memory_bytes(),
            }
        )
        while self.peak_memory_bytes < self.memory_bytes():
            self.peak_memory_bytes = self.memory_bytes()
