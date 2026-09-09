"""Decision-directed, prior-free exploration of the existing finite latent class.

This reference deliberately enumerates completions: it is a CPU mechanism test,
not a scalable learner. It never receives the evaluator's true world. Minimax
regret uses maxima/minima, so duplicate state labels cannot change its score.
The original exact checker alone admits policies and prices every risky probe.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
from itertools import islice
import numpy as np
from .latent import LatentSpace, Program, Trace, Comparison, compare
from .latent_agent import LatentAgent, EpisodeTicket


@dataclass(frozen=True)
class DecisionProfile:
    status: str
    traces: tuple[tuple[Trace, ...], ...]
    # Per behavioral world, program, then public goal. Immutable integer payload.
    returns: tuple[tuple[tuple[int, ...], ...], ...]
    labelled_models: int
    model_rollouts: int


def decision_profile(space: LatentSpace, programs: tuple[Program, ...],
                     rewards: tuple[tuple[int, ...], ...], *, max_models: int = 4096) -> DecisionProfile:
    if type(max_models) is not int or max_models < 1:
        raise ValueError('positive exact-model cap required')
    if not programs or not rewards:
        raise ValueError('nonempty program and objective libraries required')
    if not space.complete:
        return DecisionProfile('unknown', (), (), 0, 0)
    if not space.partials:
        return DecisionProfile('inconsistent', (), (), 0, 0)
    # The extra element detects overflow; never use a truncated model list.
    models = list(islice(space.completions(), max_models + 1))
    if len(models) > max_models:
        return DecisionProfile('unknown', (), (), len(models), 0)
    profiles = {}
    for model in models:
        traces = tuple(p.rollout(model) for p in programs)
        if traces not in profiles:
            profiles[traces] = tuple(tuple(sum(r[o] for _, o in tr) for r in rewards)
                                     for tr in traces)
    return DecisionProfile('exact', tuple(profiles), tuple(profiles.values()),
                           len(models), len(models) * len(programs))


def minimax_regret_sum(returns: np.ndarray) -> int:
    """Sum over goals of min_p max_M [max_q V(M,q,g) - V(M,p,g)]."""
    a = np.asarray(returns)
    if a.ndim != 3 or not all(a.shape) or not np.issubdtype(a.dtype, np.integer):
        raise ValueError('nonempty integral world/program/goal return tensor required')
    # Experiments use rewards 0 and 2. Object integers avoid silent overflow for
    # externally supplied integer reward magnitudes.
    a = a.astype(object)
    regret = a.max(axis=1, keepdims=True) - a
    return int(regret.max(axis=0).min(axis=0).sum())


def guaranteed_regret_reductions(profile: DecisionProfile) -> tuple[int, ...]:
    """Guaranteed decrease after observing each program's actual reset trace.

    This is a reduction in a decision-uncertainty functional, not a guaranteed
    reward gain, posterior entropy, or a probability of discovering a skill.
    """
    if profile.status != 'exact' or not profile.returns:
        raise ValueError('complete nonempty decision profile required')
    a = np.asarray(profile.returns, dtype=object)
    # Convert to platform integer only if every value fits; minimax arithmetic
    # itself uses Python integers regardless of the storage type.
    # Internal profiles contain Python ints; np object validation is bypassed here
    # using the same exact expression in a small private helper.
    def regret(rows):
        b = a[rows]
        return int((b.max(axis=1, keepdims=True) - b).max(axis=0).min(axis=0).sum())
    initial = regret(list(range(len(a))))
    gains = []
    for program in range(len(profile.traces[0])):
        cells: dict[Trace, list[int]] = {}
        for world, traces in enumerate(profile.traces):
            cells.setdefault(traces[program], []).append(world)
        gains.append(initial - max(regret(rows) for rows in cells.values()))
    return tuple(gains)


class DecisionDirectedAgent(LatentAgent):
    """B16 v4 admission/debits, with a changed experiment-selection rule only.

    Among feasible probes with positive guaranteed regret reduction, maximize
    reduction/(1+debit), then minimize debit, maximize possible current gain, and
    use proposer rank. Zero score abstains. The incumbent can be a free probe.
    All public goals have equal weight; no future goal schedule is supplied.
    """
    def __init__(self, *args, max_models: int = 4096, **kwargs):
        super().__init__(*args, **kwargs)
        if type(max_models) is not int or max_models < 1:
            raise ValueError('positive exact-model cap required')
        self.max_models = max_models
        self.profile_builds = self.profile_cache_hits = self.model_rollouts = 0
        self.labelled_models_enumerated = self.max_behavioral_profiles = 0
        self.last_information_gain = 0
        self._profile_key = self._profile = None

    def _get_profile(self) -> DecisionProfile:
        # Full immutable keys, no unchecked digest; repeats can reuse the result.
        key = (self.space.states, self.space.actions, self.space.outputs,
               self.space.complete, self.space.partials, self.programs, self.rewards)
        if key == self._profile_key:
            self.profile_cache_hits += 1
            return self._profile
        p = decision_profile(self.space, self.programs, self.rewards, max_models=self.max_models)
        self.profile_builds += 1
        self.model_rollouts += p.model_rollouts
        self.labelled_models_enumerated += p.labelled_models
        self.max_behavioral_profiles = max(self.max_behavioral_profiles, len(p.traces))
        self._profile_key, self._profile = key, p
        return p

    def choose(self, goal: int) -> EpisodeTicket:
        if self.pending is not None:
            raise RuntimeError('outstanding episode must finish before choosing another')
        if type(goal) is not int or not 0 <= goal < len(self.rewards):
            raise ValueError('invalid public objective')
        self.last_information_gain = 0
        if self.space.complete and not self.space.partials:
            self.pending = EpisodeTicket(self.episodes, goal, 0, 0, 0, self.space.generation, self.era)
            return self.pending
        baseline = self.incumbents[goal]
        rank = self.proposer.rank(goal, trainable=self.trainable)
        if self.proposals is not None:
            rank = rank[:self.proposals]
        checked: list[tuple[int, Comparison]] = []
        for j in rank:
            if j == baseline:
                continue
            c = compare(self.space, self.programs[j], self.programs[baseline],
                        self.rewards[goal], max_nodes=self.max_nodes)
            self.comparisons += 1
            self.nodes += c.nodes
            self.unknown += c.status == 'unknown'
            checked.append((j, c))
        admitted = [(j, c) for j, c in checked if c.admits and c.lower > 0]
        chosen, debit = baseline, 0
        if admitted:
            j, c = max(admitted, key=lambda jc: (jc[1].lower, -rank.index(jc[0])))
            self.incumbents[goal] = j
            self.promotions += 1
            self.certificates.append((self.episodes, goal, baseline, j, c.lower))
            chosen = j
        else:
            profile = self._get_profile()
            self.unknown += profile.status == 'unknown'
            if profile.status == 'exact':
                gains = guaranteed_regret_reductions(profile)
                # Identical-policy comparison is exact on this complete class.
                options = [(baseline, 0, 0)]
                for j, c in checked:
                    if c.status == 'exact':
                        d = max(0, -c.lower)
                        if self.spent + d <= self.budget:
                            options.append((j, d, c.upper))
                scored = [(Fraction(gains[j], 1 + d), -d, upper,
                           -rank.index(j) if j in rank else -len(rank), j, d)
                          for j, d, upper in options if gains[j] > 0]
                if scored:
                    _, _, _, _, chosen, debit = max(scored)
                    self.last_information_gain = gains[chosen]
        self.spent += debit
        self.pending = EpisodeTicket(self.episodes, goal, chosen, self.incumbents[goal],
                                     debit, self.space.generation, self.era)
        return self.pending
