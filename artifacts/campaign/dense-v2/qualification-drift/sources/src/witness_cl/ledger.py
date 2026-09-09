from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from .types import Feedback, Scope

ZERO = "0" * 64

def _digest(previous: str, event: dict) -> str:
    payload = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256((previous + "\n" + payload).encode()).hexdigest()

class Ledger:
    """Single-writer hash-linked evidence log. Not authentication or a concurrent database.

    An attacker who can rewrite the entire log can recompute its hashes. Keep an
    independently trusted head digest for tamper evidence. Raw user text is never
    parsed into trusted Feedback by this class.
    """
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[Feedback] = []
        self.head = ZERO
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        previous, last = ZERO, -1
        with self.path.open(encoding="utf8") as f:
            for lineno, line in enumerate(f, 1):
                row = json.loads(line)
                if set(row) != {"previous", "event", "hash"}:
                    raise ValueError(f"invalid record at line {lineno}")
                if row["previous"] != previous or row["hash"] != _digest(previous, row["event"]):
                    raise ValueError(f"broken hash chain at line {lineno}")
                raw = dict(row["event"])
                raw["scope"] = Scope(**raw["scope"])
                fb = Feedback(**raw)
                if fb.episode <= last:
                    raise ValueError("nonchronological evidence")
                self.events.append(fb)
                previous, last = row["hash"], fb.episode
        self.head = previous

    def append(self, event: Feedback) -> None:
        if self.events and event.episode <= self.events[-1].episode:
            raise ValueError("duplicate or stale feedback")
        data = asdict(event)
        digest = _digest(self.head, data)
        row = {"previous": self.head, "event": data, "hash": digest}
        with self.path.open("a", encoding="utf8") as f:
            f.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.head = digest
        self.events.append(event)

    def check_head(self, trusted_head: str) -> bool:
        return self.head == trusted_head
