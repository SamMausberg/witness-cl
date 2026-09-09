"""Bounded, conventional belief-state probe search; no safety authority in search.

The immutable action library and original exact checker remain authoritative.
Only an executed, ticket-matched trace is observed. Planning runs transactionally
under one Python-line work cap, covering enumeration (including duplicate
completions), rollout, partitions, regret, and original checker implementation.
Elapsed limits are cooperative between Python operations, not real-time limits.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import product
import math
from pathlib import Path
import sys
import time

from .latent import LatentSpace, Machine, Program, Trace, compare, possible_traces
from .latent_agent import EpisodeTicket, LatentAgent


class _PlanningLimit(RuntimeError):
    pass


@dataclass(frozen=True)
class ProbePlan:
    status: str
    reason: str
    program: int
    incumbent: int
    debit: int
    promote: bool
    lower: int | None
    upper: int | None
    guaranteed_gain: int
    # First observed trace -> second program and its branch-local risk debit.
    branches: tuple[tuple[Trace, int, int], ...]
    generation: int
    era: int
    work: int
    elapsed_seconds: float
    completion_attempts: int
    labelled_models: int
    comparisons: int
    check_nodes: int


@dataclass(frozen=True)
class _Decision:
    program: int
    debit: int
    promote: bool
    lower: int
    upper: int
    gain: int = 0
    branches: tuple[tuple[Trace, int, int], ...] = ()


class _Meter:
    """Deterministic hard source-line event cap plus a cooperative time limit."""
    def __init__(self, max_work: int, max_seconds: float):
        self.max_work = max_work
        self.deadline = time.perf_counter() + max_seconds
        self.work = 0
        self.completion_attempts = self.labelled_models = 0
        self.comparisons = self.check_nodes = 0
        self.root = Path(__file__).resolve().parent
        self.scoped_files = {}

    def trace(self, frame, event, arg):
        # C-backed operations (e.g. tuple hashing or a fixed-library ranker dot
        # product) finish before the next event. This is not a FLOP or OS clock
        # limit. Input/library size caps and the work cap bound Python search.
        filename = frame.f_code.co_filename
        if filename not in self.scoped_files:
            resolved = Path(filename).resolve()
            self.scoped_files[filename] = resolved.is_relative_to(self.root)
        if not self.scoped_files[filename]:
            return None
        if event == 'line':
            if self.work >= self.max_work:
                raise _PlanningLimit('work cap')
            if time.perf_counter() >= self.deadline:
                raise _PlanningLimit('elapsed cap')
            self.work += 1
        return self.trace


def _checked(space, programs, rewards, candidate, baseline, max_nodes, meter):
    meter.comparisons += 1
    result = compare(space, programs[candidate], programs[baseline], rewards,
                     max_nodes=max_nodes)
    meter.check_nodes += result.nodes
    if result.status != 'exact':
        raise _PlanningLimit('checker ' + result.status)
    return result


def _threshold_choices(branch_alternatives):
    """Global regret/debit frontier, avoiding locally gratuitous branch debits.

    Alternatives are (terminal_regret, debit, rank, program). For each possible
    global regret threshold, choose the cheapest admissible alternative in every
    branch. Their realized regret is at most that threshold and their maximum
    debit is minimal among plans satisfying it. Thus every optimal score of the
    form (initial - max_regret)/(1 + first_debit + max_second_debit) is covered.
    """
    thresholds = sorted({alternative[0] for options in branch_alternatives
                         for alternative in options})
    for threshold in thresholds:
        selected = []
        for options in branch_alternatives:
            feasible = [a for a in options if a[0] <= threshold]
            if not feasible:
                break
            selected.append(min(feasible, key=lambda a: (a[1], a[0], a[2], a[3])))
        if len(selected) == len(branch_alternatives):
            yield max(a[0] for a in selected), max(a[1] for a in selected), tuple(selected)


class _Planning:
    """Ephemeral computation. No references are ever written back to evidence."""
    def __init__(self, agent, goal, meter):
        self.agent, self.goal, self.meter = agent, goal, meter
        self.baseline = agent.incumbents[goal]
        self.available = agent.budget - agent.spent
        # Ranking supplies only indices. Reject malformed proposals before any
        # index operation; a proposer cannot replace a program or a certificate.
        rank = agent.proposer.rank(goal, trainable=agent.trainable)
        if type(rank) not in (list, tuple) or len(rank) > len(agent.programs):
            raise _PlanningLimit('invalid proposals')
        if any(type(j) is not int or not 0 <= j < len(agent.programs) for j in rank):
            raise _PlanningLimit('invalid proposals')
        if len(set(rank)) != len(rank):
            raise _PlanningLimit('duplicate proposals')
        if agent.proposals is not None:
            rank = rank[:agent.proposals]
        self.rank = tuple(rank)
        self.options = self.rank if self.baseline in self.rank else self.rank + (self.baseline,)
        self.checked = {}
        for j in self.options:
            self.checked[j] = _checked(agent.space, agent.programs, agent.rewards[goal],
                                       j, self.baseline, agent.max_nodes, meter)

    def immediate(self):
        admissible = [(c.lower, c.upper, -i, j) for i, j in enumerate(self.options)
                      if (c := self.checked[j]).admits and c.upper > 0]
        if not admissible:
            return None
        lower, upper, _, j = max(admissible)
        return _Decision(j, 0, True, lower, upper)

    def final_check(self, decision):
        a = self.agent
        result = _checked(a.space, a.programs, a.rewards[self.goal], decision.program,
                          self.baseline, a.max_nodes, self.meter)
        debit = max(0, -result.lower)
        if debit > self.available or (decision.promote and not result.admits):
            raise _PlanningLimit('final authorization failed')
        return _Decision(decision.program, debit, decision.promote,
                         result.lower, result.upper, decision.gain, decision.branches)

    def cheap(self):
        immediate = self.immediate()
        if immediate is not None:
            return self.final_check(immediate)
        a = self.agent
        informative = []
        for i, j in enumerate(self.options):
            c = self.checked[j]
            # Deliberately allow informative ties; the frozen v5 score did not.
            if c.lower < 0:
                continue
            outcomes = possible_traces(a.space, a.programs[j], max_nodes=a.max_nodes)
            self.meter.check_nodes += outcomes.nodes
            if outcomes.status != 'exact':
                raise _PlanningLimit('outcome search ' + outcomes.status)
            if len(outcomes.traces) > 1:
                informative.append((len(outcomes.traces), -i, j))
        chosen = max(informative)[2] if informative else self.baseline
        c = self.checked[chosen]
        return self.final_check(_Decision(chosen, 0, False, c.lower, c.upper))

    def profile(self):
        a = self.agent
        seen = set()
        models, traces, values = [], [], []
        # Unlike islice(completions()), each duplicate enumeration is visible to
        # the outer line meter before any yield. No truncated profile is usable.
        edges = tuple(product(range(a.space.states), range(a.space.outputs)))
        for partial in a.space.partials:
            slots = tuple(i for i, edge in enumerate(partial) if edge is None)
            for choices in product(edges, repeat=len(slots)):
                self.meter.completion_attempts += 1
                table = list(partial)
                for slot, edge in zip(slots, choices):
                    table[slot] = edge
                key = tuple(table)
                if key in seen:
                    continue
                if len(models) >= a.max_models:
                    raise _PlanningLimit('distinct model cap')
                seen.add(key)
                model = Machine(a.space.states, a.space.actions, a.space.outputs, key)
                models.append(model)
                self.meter.labelled_models += 1
                observed = tuple(p.rollout(model) for p in a.programs)
                traces.append(observed)
                values.append(tuple(tuple(sum(r[o] for _, o in tr) for r in a.rewards)
                                    for tr in observed))
        if not models:
            raise _PlanningLimit('empty profile')
        self.models, self.traces, self.values = tuple(models), tuple(traces), tuple(values)
        self.regret_cache, self.partition_cache, self.comparison_cache = {}, {}, {}
        self.best_values = tuple(tuple(max(v[j][g] for j in range(len(a.programs)))
                                      for g in range(len(a.rewards))) for v in values)

    def regret(self, rows):
        if rows not in self.regret_cache:
            a = self.agent
            self.regret_cache[rows] = sum(
                min(max(self.best_values[m][g] - self.values[m][p][g] for m in rows)
                    for p in range(len(a.programs))) for g in range(len(a.rewards)))
        return self.regret_cache[rows]

    def partition(self, rows, program):
        key = rows, program
        if key not in self.partition_cache:
            cells = {}
            for m in rows:
                cells.setdefault(self.traces[m][program], []).append(m)
            self.partition_cache[key] = tuple((trace, tuple(group)) for trace, group in cells.items())
        return self.partition_cache[key]

    def branch_compare(self, rows, program):
        key = rows, program
        if key not in self.comparison_cache:
            a = self.agent
            branch = LatentSpace(a.space.states, a.space.actions, a.space.outputs,
                                 max_partials=a.space.max_partials)
            branch.partials = tuple(self.models[m].table for m in rows)
            branch.generation = a.space.generation
            self.comparison_cache[key] = _checked(branch, a.programs, a.rewards[self.goal],
                                                  program, self.baseline, a.max_nodes, self.meter)
        return self.comparison_cache[key]

    def depth_two(self):
        immediate = self.immediate()
        if immediate is not None:
            return self.final_check(immediate)
        self.profile()
        rows = tuple(range(len(self.models)))
        initial = self.regret(rows)
        scored = []
        for i, first in enumerate(self.options):
            first_check = self.checked[first]
            first_debit = max(0, -first_check.lower)
            if first_debit > self.available:
                continue
            first_cells = self.partition(rows, first)
            branch_alternatives = []
            for trace, cell in first_cells:
                # Stop is a real option; simulations cannot require a probe.
                alternatives = [(self.regret(cell), 0, -1, self.baseline)]
                for k, second in enumerate(self.options):
                    check = self.branch_compare(cell, second)
                    debit = max(0, -check.lower)
                    if first_debit + debit <= self.available:
                        worst = max(self.regret(leaf) for _, leaf in self.partition(cell, second))
                        alternatives.append((worst, debit, k, second))
                branch_alternatives.append(tuple(alternatives))
            immediate_gain = initial - max(self.regret(cell) for _, cell in first_cells)
            for worst, largest_second_debit, selected in _threshold_choices(branch_alternatives):
                gain = initial - worst
                total_debit = first_debit + largest_second_debit
                if gain > 0:
                    # Immediate reduction/informativeness avoid procrastinating
                    # on an equally good plan with the useful probe only later.
                    score = (Fraction(gain, 1 + total_debit), immediate_gain,
                             len(first_cells), -total_debit, first_check.upper, -i)
                    branches = tuple((trace, alternative[3], alternative[1])
                                     for (trace, _), alternative in zip(first_cells, selected))
                    decision = _Decision(first, first_debit, False, first_check.lower,
                                         first_check.upper, gain, branches)
                    scored.append((score, decision))
        if not scored:
            c = self.checked[self.baseline]
            return self.final_check(_Decision(self.baseline, 0, False, c.lower, c.upper))
        return self.final_check(max(scored, key=lambda item: item[0])[1])

    def optimistic(self):
        immediate = self.immediate()
        if immediate is not None:
            return self.final_check(immediate)
        self.profile()
        choices = []
        for i, j in enumerate(self.options):
            c = self.checked[j]
            debit = max(0, -c.lower)
            if debit <= self.available:
                best = max(v[j][self.goal] for v in self.values)
                # Observationally informative ties before rank order.
                distinct = len(set(traces[j] for traces in self.traces))
                choices.append(((best, distinct, -debit, -i), j))
        j = max(choices)[1]
        c = self.checked[j]
        return self.final_check(_Decision(j, max(0, -c.lower), False, c.lower, c.upper))


class _BoundedProbeAgent(LatentAgent):
    mode = 'cheap'

    def __init__(self, *args, max_work: int = 2_000_000, max_seconds: float = 1.0,
                 max_models: int = 4096, **kwargs):
        if type(max_work) is not int or max_work < 1:
            raise ValueError('positive integer global work cap required')
        if (type(max_seconds) not in (int, float) or not math.isfinite(max_seconds)
                or max_seconds <= 0):
            raise ValueError('positive finite elapsed limit required')
        if type(max_models) is not int or max_models < 1:
            raise ValueError('positive integer model cap required')
        super().__init__(*args, **kwargs)
        if (type(self.programs) is not tuple or type(self.rewards) is not tuple
                or any(type(p) is not Program for p in self.programs)
                or any(type(r) is not tuple for r in self.rewards)):
            raise ValueError('immutable fixed Program/objective tuples required')
        if type(self.max_nodes) is not int:
            raise ValueError('integer paired-check node cap required')
        self.max_work, self.max_seconds, self.max_models = max_work, max_seconds, max_models
        self.last_plan = None
        self.planning_work = self.planning_seconds = 0
        self.profile_builds = self.labelled_models_enumerated = 0
        self.completion_attempts = self.weak_promotions = 0

    def plan(self, goal: int) -> ProbePlan:
        """Pure with respect to agent state; UNKNOWN discards the entire plan."""
        if self.pending is not None:
            raise RuntimeError('outstanding episode must finish before planning')
        if type(goal) is not int or not 0 <= goal < len(self.rewards):
            raise ValueError('invalid public objective')
        baseline = self.incumbents[goal]
        generation, era = self.space.generation, self.era
        started = time.perf_counter()
        meter = _Meter(self.max_work, self.max_seconds)
        status, reason, decision = 'exact', 'completed', None
        previous_trace = sys.gettrace()
        try:
            if not self.space.complete:
                status, reason = 'unknown', 'incomplete class'
            elif not self.space.partials:
                status, reason = 'inconsistent', 'empty class'
            else:
                sys.settrace(meter.trace)
                planning = _Planning(self, goal, meter)
                decision = getattr(planning, self.mode)()
        except _PlanningLimit as exc:
            status, reason = 'unknown', str(exc)
        finally:
            sys.settrace(previous_trace)
        if self.space.generation != generation or self.era != era:
            status, reason, decision = 'unknown', 'stale plan', None
        if status != 'exact':
            decision = None
        return ProbePlan(status, reason, decision.program if decision else baseline,
                         baseline, decision.debit if decision else 0,
                         decision.promote if decision else False,
                         decision.lower if decision else None, decision.upper if decision else None,
                         decision.gain if decision else 0, decision.branches if decision else (),
                         generation, era, meter.work, time.perf_counter() - started,
                         meter.completion_attempts, meter.labelled_models,
                         meter.comparisons, meter.check_nodes)

    def choose(self, goal: int) -> EpisodeTicket:
        result = self.plan(goal)
        # No mutation occurs until the whole metered computation has returned.
        self.last_plan = result
        self.planning_work += result.work
        self.planning_seconds += result.elapsed_seconds
        self.comparisons += result.comparisons
        self.nodes += result.check_nodes
        self.unknown += result.status == 'unknown'
        self.profile_builds += result.completion_attempts > 0
        self.completion_attempts += result.completion_attempts
        self.labelled_models_enumerated += result.labelled_models
        if result.status == 'exact' and result.promote:
            self.incumbents[goal] = result.program
            self.promotions += 1
            self.weak_promotions += result.lower == 0
            self.certificates.append((self.episodes, goal, result.incumbent,
                                      result.program, result.lower))
        self.spent += result.debit
        self.pending = EpisodeTicket(self.episodes, goal, result.program, self.incumbents[goal],
                                     result.debit, self.space.generation, self.era)
        return self.pending

    def register(self, program: Program) -> int:
        if type(program) is not Program:
            raise ValueError('only immutable typed Program candidates are accepted')
        return super().register(program)


class DepthTwoProbeAgent(_BoundedProbeAgent):
    """Adaptive two-probe minimax-regret search; execute only the first probe."""
    mode = 'depth_two'


class InformativeZeroLossAgent(_BoundedProbeAgent):
    """Cheap strong control: weak dominance then informative zero-loss probes."""
    mode = 'cheap'


class OptimisticProbeAgent(_BoundedProbeAgent):
    """Same exact class, optimistic library return, original risk-budget checks."""
    mode = 'optimistic'
