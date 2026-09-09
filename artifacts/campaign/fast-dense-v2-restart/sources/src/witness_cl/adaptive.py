"""Growing evidence classes and recurrence without hidden task/version identifiers.

No prediction from this module is a logical certificate. A finite generated
class need not contain the environment's true behavior, and drift is unannounced.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, Iterable

@dataclass(frozen=True)
class Rule:
    key: str
    evaluate: Callable[[Any], Any]
    def __call__(self, x: Any) -> Any:
        return self.evaluate(x)

@dataclass(frozen=True)
class Observation:
    episode: int
    x: Any
    action: Any
    success: bool

def agrees(rule: Rule, event: Observation) -> bool:
    return (rule(event.x) == event.action) == event.success

class GrowingEvidence:
    """Keep sufficient witnesses for *this* class; backfill new classes from raw data.

    Snapshots x and rule implementations must be immutable. The caller owns data
    provenance. add_rules is transactional and never silently accepts a candidate
    based only on a witness set computed for an older class.
    """
    def __init__(self, rules: Iterable[Rule]):
        self.rules = self._validate(tuple(rules))
        self.live = self.rules
        self.history: list[Observation] = []
        self.witnesses: list[Observation] = []
        self.evaluations = 0
        self.generation = 0

    @staticmethod
    def _validate(rules: tuple[Rule, ...]) -> tuple[Rule, ...]:
        if not rules or len({r.key for r in rules}) != len(rules):
            raise ValueError('nonempty uniquely keyed rule class required')
        return rules

    def observe(self, event: Observation) -> None:
        if self.history and event.episode <= self.history[-1].episode:
            raise ValueError('feedback must be fresh and chronological')
        # Evaluate before mutating state, so interpreter errors cannot half-commit.
        remaining = tuple(r for r in self.live if agrees(r, event))
        self.evaluations += len(self.live)
        self.history.append(event)
        if len(remaining) < len(self.live):
            self.witnesses.append(event)
        self.live = remaining
        self.generation += 1

    def add_rules(self, new_rules: Iterable[Rule]) -> None:
        additions = tuple(new_rules)
        if not additions:
            return
        combined = self._validate(self.rules + additions)
        staged = GrowingEvidence(combined)
        # This full replay is essential. It can be tiled, but cannot be skipped.
        for event in self.history:
            staged.observe(event)
        self.rules, self.live = staged.rules, staged.live
        self.witnesses = staged.witnesses
        self.evaluations += staged.evaluations
        self.generation += 1

    def witness_replay(self) -> tuple[str, ...]:
        return tuple(r.key for r in self.rules if all(agrees(r,e) for e in self.witnesses))

@dataclass(frozen=True)
class AdaptiveDecision:
    action: Any
    empirical_unanimity: bool
    candidates: int
    epoch: int
    reason: str
    certified: bool = False

class RecurringAgent:
    """Exact-feedback mechanism: grow on contradiction, then fork rather than erase.

    The archive influences the initial weights of a fresh inference epoch. It is
    never overwritten. There is no environment ID or change-point argument. The
    first contradicted action can be wrong; 'empirical_unanimity' is not a proof.
    Noisy rewards require the soft tracker in tracking.py, not elimination.
    """
    def __init__(self, tiers: Iterable[Iterable[Rule]], *, reuse: bool = True,
                 archive_mass: Fraction = Fraction(4,5)):
        self.tiers = tuple(tuple(t) for t in tiers)
        if not self.tiers or not all(self.tiers):
            raise ValueError('nonempty grammar tiers required')
        flat = tuple(r for t in self.tiers for r in t)
        GrowingEvidence._validate(flat)
        if not 0 <= archive_mass < 1:
            raise ValueError('archive mass must be in [0,1)')
        self.tier = 0
        self.space = GrowingEvidence(self.tiers[0])
        self.archive: dict[str, Rule] = {}
        self.reuse = reuse
        self.archive_mass = archive_mass
        self.prior: dict[str,Fraction] = {}
        self.epoch = 0
        self.resets = 0
        self.expansions = 0
        self.total_evaluations = 0
        self.last_episode = -1
        self.all_history: list[Observation] = []
        self.epoch_histories: list[tuple[Observation,...]] = []
        self._set_prior()

    def _set_prior(self) -> None:
        rules = self.space.rules
        remembered = [r for r in rules if r.key in self.archive] if self.reuse else []
        mass = self.archive_mass if remembered else Fraction(0)
        self.prior = {r.key: (1-mass)/len(rules) +
                      (mass/len(remembered) if remembered and r.key in self.archive else 0)
                      for r in rules}

    def decide(self, x: Any) -> AdaptiveDecision:
        if not self.space.live:
            raise RuntimeError('no surviving rule: caller must provide a fallback')
        votes: dict[Any,Fraction] = {}
        for r in self.space.live:
            y = r(x)
            votes[y] = votes.get(y,Fraction(0)) + self.prior[r.key]
        self.total_evaluations += len(self.space.live)
        # Stable ordering works for the homogeneous scalar output types in adapters.
        action = min(votes, key=lambda a: (-votes[a], a))
        return AdaptiveDecision(action,len(votes)==1,len(self.space.live),self.epoch,
                                'empirical_consensus' if len(votes)==1 else 'weighted_fallback')

    def observe(self, event: Observation) -> None:
        if event.episode <= self.last_episode:
            raise ValueError('global feedback must be fresh')
        self.last_episode = event.episode
        self.all_history.append(event)
        before = self.space.evaluations
        self.space.observe(event)
        self.total_evaluations += self.space.evaluations-before
        while not self.space.live and self.tier+1 < len(self.tiers):
            self.tier += 1
            before = self.space.evaluations
            self.space.add_rules(self.tiers[self.tier])
            self.total_evaluations += self.space.evaluations-before
            self.expansions += 1
            self._set_prior()
        if not self.space.live:
            # A contradiction is not evidence distinguishing drift from misspecification.
            # Save the old segment, restart from all known rules, charge the feedback.
            self.epoch_histories.append(tuple(self.space.history))
            self.epoch += 1
            self.resets += 1
            self.space = GrowingEvidence(self.space.rules)
            self._set_prior()
            self.space.observe(event)
            self.total_evaluations += self.space.evaluations
        if len(self.space.live)==1:
            rule = self.space.live[0]
            self.archive.setdefault(rule.key,rule)

    def archived_outputs(self, xs: Iterable[Any]) -> dict[str,tuple[Any,...]]:
        samples = tuple(xs)
        return {k:tuple(r(x) for x in samples) for k,r in self.archive.items()}
