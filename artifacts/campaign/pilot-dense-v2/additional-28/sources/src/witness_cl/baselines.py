from __future__ import annotations
from collections import defaultdict, Counter
from .core import VersionSpace
from .types import Scope, Feedback, Decision
from .programs import Program

class Stateless:
    def decide(self, scope: Scope, x: int) -> Decision:
        return Decision(0, False, "stateless_constant", 0)
    def observe(self, fb: Feedback) -> None:
        pass

class ExactLookup:
    """Stores successful answers and exclusions at exactly the observed input."""
    def __init__(self, modulus: int, capacity: int | None = None):
        self.modulus = modulus
        self.capacity = capacity
        self.observations: list[Feedback] = []
    def decide(self, scope: Scope, x: int) -> Decision:
        possible = set(range(self.modulus))
        for fb in self.observations:
            if fb.scope == scope and fb.x == x:
                if fb.success:
                    possible &= {fb.action}
                else:
                    possible.discard(fb.action)
        return Decision(min(possible) if possible else 0, False, "exact_lookup", 0)
    def observe(self, fb: Feedback) -> None:
        self.observations.append(fb)
        if self.capacity is not None:
            self.observations = self.observations[-self.capacity:]

class FullReplayInduction:
    """Unbounded full-history symbolic control, NOT an LLM.

    Recomputes precisely the same version space and majority policy each time.
    Accuracy should equal Witness on stationary realizable streams. This checks
    that compilation gains are computational, not access to hidden information.
    """
    def __init__(self, programs: tuple[Program, ...]):
        self.programs = programs
        self.history: list[Feedback] = []
        self.evaluations = 0
    def decide(self, scope: Scope, x: int) -> Decision:
        vs = VersionSpace(self.programs)
        for fb in self.history:
            if fb.scope == scope:
                vs.observe(fb)
        answer = vs.consensus(x)
        if vs.quarantined:
            action, certified = 0, False
        elif answer is not None:
            action, certified = answer, True
        else:
            action, certified = vs.majority(x), False
        self.evaluations += vs.evaluations
        return Decision(action, certified, "full_replay_induction", len(vs.live))
    def observe(self, fb: Feedback) -> None:
        self.history.append(fb)

class WindowReplayInduction(FullReplayInduction):
    """Same induction algorithm as full replay, with a bounded global raw history.

    This is a symbolic context-window control, not a language-model result.
    """
    def __init__(self, programs: tuple[Program, ...], capacity: int = 24):
        super().__init__(programs)
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity

    def observe(self, fb: Feedback) -> None:
        super().observe(fb)
        self.history = self.history[-self.capacity:]
