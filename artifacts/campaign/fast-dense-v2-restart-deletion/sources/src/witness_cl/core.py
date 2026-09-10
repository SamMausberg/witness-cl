from __future__ import annotations
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from .programs import Program, space_digest
from .types import Scope, Feedback, Decision

Fallback = Callable[[Scope, int], int]

@dataclass(frozen=True)
class Certificate:
    scope: Scope
    x: int
    action: int
    generation: int
    space_hash: str
    assumption: str = "stationary deterministic target belongs to the complete supplied class"

class VersionSpace:
    """Exact elimination from binary success feedback, not from hidden correct labels.

    A certificate is conditional on realizability and trustworthy exact feedback.
    Unanimity of a sampled LLM candidate pool does NOT justify that assumption.
    """
    def __init__(self, programs: Iterable[Program]):
        self._live = tuple(programs)
        if not self._live or len({p.key for p in self._live}) != len(self._live):
            raise ValueError("a nonempty class with unique program keys is required")
        self.initial = self._live
        self.witnesses: list[Feedback] = []
        self.generation = 0
        self.quarantined = False
        self.last_episode = -1
        self.evaluations = 0

    @property
    def live(self) -> tuple[Program, ...]:
        return self._live

    def reconstruct_from_witnesses(self) -> tuple[Program, ...]:
        """Verification utility, not a free inference operation.

        Each retained constraint eliminated at least one previously live program.
        All discarded constraints were redundant at arrival and remain redundant
        under contraction. This reproduces the live set, including an empty set.
        """
        return tuple(p for p in self.initial if all(
            ((p(f.x) == f.action) == f.success) for f in self.witnesses))

    def predictions(self, x: int) -> Counter[int]:
        self.evaluations += len(self._live)
        return Counter(p(x) for p in self._live)

    def consensus(self, x: int) -> int | None:
        if self.quarantined or not self._live:
            return None  # Empty-set unanimity must never produce a certificate.
        counts = self.predictions(x)
        return next(iter(counts)) if len(counts) == 1 else None

    def majority(self, x: int) -> int:
        counts = self.predictions(x)
        if not counts:
            raise ValueError("quarantined/empty model has no prediction")
        # Same deterministic tie breaking in replay and incremental baselines.
        return min(counts, key=lambda a: (-counts[a], a))

    def observe(self, fb: Feedback) -> None:
        if fb.episode <= self.last_episode:
            raise ValueError("feedback must be strictly chronological within a scope")
        self.last_episode = fb.episode
        if self.quarantined:
            return  # No silent reset, automatic reuse, or false re-certification.
        self.evaluations += len(self._live)
        previous_count = len(self._live)
        self._live = tuple(p for p in self._live if ((p(fb.x) == fb.action) == fb.success))
        if len(self._live) < previous_count:
            self.witnesses.append(fb)
        self.generation += 1
        if not self._live:
            self.quarantined = True

class WitnessAgent:
    """Scoped, incremental reference learner; pure predictions never change environment state."""
    def __init__(self, programs: Iterable[Program], fallback: Fallback | None = None):
        self.programs = tuple(programs)
        if not self.programs:
            raise ValueError("empty program class")
        self.spaces: dict[Scope, VersionSpace] = {}
        self.fallback = fallback
        self._certificates: dict[tuple[Scope, int], Certificate] = {}
        self._history: list[Feedback] = []
        self._last_episode = -1

    def space(self, scope: Scope) -> VersionSpace:
        if scope not in self.spaces:
            self.spaces[scope] = VersionSpace(self.programs)
        return self.spaces[scope]

    @property
    def history(self) -> tuple[Feedback, ...]:
        return tuple(self._history)

    def decide(self, scope: Scope, x: int) -> Decision:
        vs = self.space(scope)
        if vs.quarantined:
            action = self.fallback(scope, x) if self.fallback is not None else 0
            return Decision(action, False, "quarantine_fallback", 0)
        key = (scope, x)
        old = self._certificates.get(key)
        if old is not None:
            return Decision(old.action, True, "persistent_certificate", len(vs.live))
        answer = vs.consensus(x)
        if answer is not None:
            self._certificates[key] = Certificate(scope, x, answer, vs.generation, space_digest(vs.live))
            return Decision(answer, True, "unanimous_contract", len(vs.live))
        if self.fallback is not None:
            action, why = self.fallback(scope, x), "external_fallback"
        else:
            action, why = vs.majority(x), "uncertified_majority"
        return Decision(action, False, why, len(vs.live))

    def observe(self, fb: Feedback) -> None:
        if fb.episode <= self._last_episode:
            raise ValueError("global episode IDs must be unique and increasing")
        self.space(fb.scope).observe(fb)
        self._history.append(fb)
        self._last_episode = fb.episode
        if self.space(fb.scope).quarantined:
            self._certificates = {k: c for k, c in self._certificates.items() if k[0] != fb.scope}

    def certificate(self, scope: Scope, x: int) -> Certificate | None:
        return self._certificates.get((scope, x))

    def revoke_scope(self, scope: Scope) -> None:
        """Fail closed. Relearning needs a distinct externally justified scope/version."""
        vs = self.space(scope)
        vs.quarantined = True
        self._certificates = {k: c for k, c in self._certificates.items() if k[0] != scope}
