from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
from math import log, sqrt
from .types import Scope

Q = Fraction

@dataclass(frozen=True)
class AuditSpec:
    index: int
    born_after_episode: int
    scope: Scope
    candidate_hash: str
    baseline_hash: str
    delta: Q = Q(1, 20)

    def __post_init__(self) -> None:
        if self.index < 1 or self.born_after_episode < -1:
            raise ValueError("invalid registration index or birth episode")
        if not 0 < self.delta < 1:
            raise ValueError("delta must lie in (0,1)")
        if not self.candidate_hash or not self.baseline_hash:
            raise ValueError("both frozen system identities are required")

    @property
    def allocated_delta(self) -> Q:
        return self.delta / (self.index * (self.index + 1))

class PairedAudit:
    """Exact-rational mixture betting test for fresh paired episode reward differences.

    Statistical assumptions are NOT checked by Python: both systems are frozen,
    feedback is trustworthy, and null conditional mean difference is <= 0.
    For a stationary scope this tests its mean benefit, not pointwise safety.
    A global coordinator must assign unique monotonically increasing indices.
    """
    stakes = (Q(1, 10), Q(1, 4), Q(1, 2), Q(3, 4), Q(1))

    def __init__(self, spec: AuditSpec):
        self.spec = spec
        self.capitals = [Q(1) for _ in self.stakes]
        self.differences: list[Q] = []
        self.last_episode = spec.born_after_episode
        self.passed = False
        self.invalidated = False

    @property
    def e_value(self) -> Q:
        return sum(self.capitals, Q(0)) / len(self.capitals)

    def observe(self, *, episode: int, scope: Scope, candidate_hash: str,
                baseline_hash: str, candidate_reward: Q | int,
                baseline_reward: Q | int) -> None:
        if self.invalidated:
            raise ValueError("audit invalidated; register a new frozen comparison")
        if episode <= self.last_episode:
            raise ValueError("proposal data, reused audit cases, and reversed time are forbidden")
        if (scope, candidate_hash, baseline_hash) != (
                self.spec.scope, self.spec.candidate_hash, self.spec.baseline_hash):
            raise ValueError("scope or frozen system changed; restart with a new index")
        # Do not silently import floating-point rounding into the exact reference.
        if not isinstance(candidate_reward, (Q, int)) or not isinstance(baseline_reward, (Q, int)):
            raise TypeError("use integer or Fraction rewards")
        rp, rb = Q(candidate_reward), Q(baseline_reward)
        if not (0 <= rp <= 1 and 0 <= rb <= 1):
            raise ValueError("normalize rewards to [0,1] before registering an audit")
        d = rp - rb
        self.capitals = [w * (1 + lam * d) for w, lam in zip(self.capitals, self.stakes)]
        self.differences.append(d)
        self.last_episode = episode
        self.passed |= self.e_value >= 1 / self.spec.allocated_delta

    def can_promote(self, *, scope: Scope, candidate_hash: str,
                    current_baseline_hash: str) -> bool:
        """Prevent promotion against an incumbent that changed during the audit.

        The enclosing harness must compute these identities from the actual full
        snapshots, not merely accept identities supplied by a candidate model.
        """
        return (self.passed and not self.invalidated and
                scope == self.spec.scope and candidate_hash == self.spec.candidate_hash and
                current_baseline_hash == self.spec.baseline_hash)

    def invalidate(self) -> None:
        self.invalidated = True
        self.passed = False

    def hoeffding_lcb(self) -> float:
        """A simpler, looser independent cross-check, not the admission rule.

        Union allocation over candidate index j and sample count n. Sound as a
        fixed-mean confidence sequence under the stated bounded/iid assumptions.
        """
        n = len(self.differences)
        if not n:
            return -1.0
        error = float(self.spec.allocated_delta) / (n * (n + 1))
        radius = sqrt(2 * log(1 / error) / n)
        return max(-1.0, float(sum(self.differences) / n) - radius)
