"""Exact, bounded latent transducer learning from executed reset traces.

The learner is NOT given an environment model, hidden state, or regime ID.
It is given a deterministic stationary K-state contract, finite alphabets,
and a reset-to-state-0 contract. Each partial table denotes ALL its completions.
No best-fit model, truncated beam, or incomplete search can issue a certificate.
"""
from __future__ import annotations
from dataclasses import dataclass
from itertools import product
from typing import Iterator

Edge = tuple[int, int]  # next hidden state, observed output symbol
Table = tuple[Edge | None, ...]
Trace = tuple[tuple[int, int], ...]  # executed action, observed output

@dataclass(frozen=True)
class Machine:
    states: int
    actions: int
    outputs: int
    table: tuple[Edge, ...]

    def __post_init__(self) -> None:
        if any(type(x) is not int or x < 1 for x in (self.states, self.actions, self.outputs)):
            raise ValueError('positive alphabet and state sizes required')
        if not isinstance(self.table, tuple) or len(self.table) != self.states * self.actions:
            raise ValueError('immutable full transition table required')
        if any(not isinstance(e, tuple) or len(e) != 2 or
               any(type(v) is not int for v in e) or
               not 0 <= e[0] < self.states or not 0 <= e[1] < self.outputs for e in self.table):
            raise ValueError('invalid transition')

    def run(self, word: tuple[int, ...]) -> Trace:
        state = 0
        out = []
        for action in word:
            if type(action) is not int or not 0 <= action < self.actions:
                raise ValueError('invalid action')
            state, symbol = self.table[state * self.actions + action]
            out.append((action, symbol))
        return tuple(out)

@dataclass(frozen=True)
class Program:
    """Immutable fixed-horizon observation-contingent program.

    The node index is a base-O breadth-first output-history index. All histories,
    including currently unreachable ones, have specified actions. No model state
    or evaluator-only information is passed to a program.
    """
    outputs: int
    levels: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        if type(self.outputs) is not int or self.outputs < 1 or not self.levels:
            raise ValueError('nonempty finite program required')
        if not isinstance(self.levels, tuple) or any(not isinstance(row, tuple) or
                len(row) != self.outputs ** t or any(type(a) is not int or a < 0 for a in row)
                for t, row in enumerate(self.levels)):
            raise ValueError('invalid immutable history tree')
        if len(self.levels) > 12 or sum(map(len, self.levels)) > 100000:
            raise ValueError('program exceeds reference size limit')

    @classmethod
    def word(cls, word: tuple[int, ...], outputs: int) -> Program:
        if type(outputs) is not int or outputs<1 or not isinstance(word,tuple) or not 1<=len(word)<=12:
            raise ValueError('bounded immutable action word required')
        if sum(outputs**t for t in range(len(word)))>100000:
            raise ValueError('program exceeds node cap before allocation')
        return cls(outputs, tuple((a,) * outputs ** t for t, a in enumerate(word)))

    @property
    def horizon(self) -> int:
        return len(self.levels)

    def suffix(self, t: int, index: int) -> tuple[tuple[int, ...], ...]:
        # Descendants of a history occupy contiguous intervals at each depth.
        return tuple(self.levels[d][index * self.outputs ** (d-t):
                    (index+1) * self.outputs ** (d-t)] for d in range(t, self.horizon))

    def rollout(self, machine: Machine) -> Trace:
        validate_program(self, machine.actions, machine.outputs)
        state = index = 0
        out = []
        for t in range(self.horizon):
            action = self.levels[t][index]
            state, symbol = machine.table[state * machine.actions + action]
            out.append((action, symbol))
            index = index * self.outputs + symbol
        return tuple(out)


def validate_program(p: Program, actions: int, outputs: int) -> None:
    if p.outputs != outputs or any(a >= actions for row in p.levels for a in row):
        raise ValueError('program alphabet mismatch')


def extend(table: Table, slot: int, edge: Edge) -> Table:
    return table[:slot] + (edge,) + table[slot+1:]


class SearchLimit(RuntimeError):
    pass


class LatentSpace:
    """A union of partial tables whose completion set is exactly trace consistency.

    Overflow stores the raw observation but marks the class incomplete. It NEVER
    silently drops hypotheses. Expansion replays all raw traces transactionally.
    Symmetry-related state numberings are retained; they are not separate worlds
    for statistical purposes. No probability or entropy is assigned to counts.
    """
    def __init__(self, states: int, actions: int, outputs: int, *, max_partials: int = 100000):
        if any(type(x) is not int or x < 1 for x in (states, actions, outputs, max_partials)):
            raise ValueError('positive integer sizes required')
        if states*actions>4096 or outputs>256:
            raise ValueError('reference alphabet/table resource cap exceeded')
        self.states, self.actions, self.outputs = states, actions, outputs
        self.max_partials = max_partials
        self.partials: tuple[Table, ...] = ((None,) * (states * actions),)
        self.history: list[Trace] = []
        self.complete = True
        self.generation = 0
        self.fit_branches = 0

    def _validate(self, trace: Trace) -> None:
        if not isinstance(trace, tuple) or any(not isinstance(e, tuple) or len(e) != 2 or
            any(type(v) is not int for v in e) or not 0 <= e[0] < self.actions or
            not 0 <= e[1] < self.outputs for e in trace):
            raise ValueError('immutable legal action/output trace required')

    def _fit(self, trace: Trace) -> tuple[Table, ...]:
        reached = {(p, 0) for p in self.partials}
        for action, output in trace:
            next_reached = set()
            for table, state in reached:
                slot = state * self.actions + action
                edge = table[slot]
                if edge is not None:
                    if edge[1] == output:
                        next_reached.add((table, edge[0]))
                else:
                    for target in range(self.states):
                        self.fit_branches += 1
                        next_reached.add((extend(table, slot, (target, output)), target))
                if len(next_reached) > self.max_partials:
                    raise SearchLimit('latent evidence frontier exceeded cap')
            reached = next_reached
        return tuple(sorted({p for p, _ in reached}, key=repr))

    def observe(self, trace: Trace) -> None:
        self._validate(trace)
        self.history.append(trace)
        self.generation += 1
        if not self.complete:
            return
        try:
            self.partials = self._fit(trace)
        except SearchLimit:
            self.complete = False

    def expand(self, states: int) -> None:
        if type(states) is not int or states <= self.states:
            raise ValueError('expansion requires a strictly larger state bound')
        staged = LatentSpace(states, self.actions, self.outputs, max_partials=self.max_partials)
        for trace in self.history:
            staged.observe(trace)
        self.states, self.partials, self.complete = staged.states, staged.partials, staged.complete
        self.fit_branches += staged.fit_branches
        self.generation += 1

    def contains(self, m: Machine) -> bool:
        if (m.states, m.actions, m.outputs) != (self.states, self.actions, self.outputs):
            return False
        if not self.complete:
            raise RuntimeError('incomplete evidence search is not a membership oracle')
        return any(all(e is None or e == v for e, v in zip(p, m.table)) for p in self.partials)

    def representative(self) -> Machine:
        if not self.complete or not self.partials:
            raise RuntimeError('no complete nonempty model class')
        return Machine(self.states, self.actions, self.outputs,
                       tuple(e if e is not None else (0, 0) for e in self.partials[0]))

    def completions(self) -> Iterator[Machine]:
        """Small-case exhaustive oracle only; duplicates removed."""
        if not self.complete:
            raise RuntimeError('cannot enumerate an incomplete frontier')
        seen = set()
        for p in self.partials:
            slots = [i for i, e in enumerate(p) if e is None]
            for choices in product(tuple(product(range(self.states), range(self.outputs))), repeat=len(slots)):
                table = list(p)
                for i, edge in zip(slots, choices):
                    table[i] = edge
                key = tuple(table)
                if key not in seen:
                    seen.add(key)
                    yield Machine(self.states, self.actions, self.outputs, key)


@dataclass(frozen=True)
class Comparison:
    status: str  # exact, unknown, inconsistent
    lower: int | None
    upper: int | None
    witness: Machine | None  # an actual model attaining the lower bound
    nodes: int
    leaves: int
    closed_suffixes: int
    generation: int

    @property
    def admits(self) -> bool:
        return self.status == 'exact' and self.lower is not None and self.lower >= 0


def residual_ids(candidate: Program, incumbent: Program) -> tuple[tuple[tuple[int, ...], ...], tuple[tuple[int, ...], ...]]:
    """Exact pair-local hash-consing of continuation programs, with collision checks.

    Dictionary keys are full (action, child-ID...) tuples. Python hash collisions
    cannot identify unequal keys. No shapes-only or environment-dependent cache.
    Returns O(1) equality IDs; construction cost is included in compare timing.
    """
    if candidate.horizon != incumbent.horizon or candidate.outputs != incumbent.outputs:
        raise ValueError('paired program dimensions disagree')
    intern: dict[tuple[int, ...], int] = {}
    result=[]
    for p in (candidate,incumbent):
        child=(0,)*(p.outputs**p.horizon)
        levels=[]
        for row in reversed(p.levels):
            ids=[]
            for i,a in enumerate(row):
                key=(a,)+child[i*p.outputs:(i+1)*p.outputs]
                if key not in intern:intern[key]=len(intern)+1
                ids.append(intern[key])
            child=tuple(ids);levels.append(child)
        result.append(tuple(reversed(levels)))
    return result[0],result[1]


def compare(space: LatentSpace, candidate: Program, incumbent: Program,
            rewards: tuple[int, ...], *, max_nodes: int = 100000,
            close_suffixes: bool = True) -> Comparison:
    """Exact min/max of candidate minus incumbent, sharing one hypothetical world.

    Only transition slots visited by the paired programs are expanded. A common
    hidden state AND identical residual program closes the suffix without reading
    any more edges. Incomplete computation returns UNKNOWN, never a partial bound.
    """
    for p in (candidate, incumbent):
        validate_program(p, space.actions, space.outputs)
    if candidate.horizon != incumbent.horizon or len(rewards) != space.outputs or any(
        type(r) is not int for r in rewards) or type(max_nodes) is not int or max_nodes < 1:
        raise ValueError('equal horizons, integer rewards and positive node limit required')
    generation = space.generation
    if not space.complete:
        return Comparison('unknown', None, None, None, 0, 0, 0, generation)
    if not space.partials:
        return Comparison('inconsistent', None, None, None, 0, 0, 0, generation)
    if close_suffixes and candidate == incumbent:
        return Comparison('exact', 0, 0, space.representative(), 1, 1, 1, generation)
    codes = residual_ids(candidate,incumbent) if close_suffixes else None
    nodes = leaves = closed = 0
    lower = upper = None
    witness = None

    def tick() -> None:
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes:
            raise SearchLimit('paired continuation search exceeded cap')

    def edge_choices(table: Table, state: int, action: int):
        slot = state * space.actions + action
        if table[slot] is not None:
            yield table, table[slot]
        else:
            for target in range(space.states):
                for output in range(space.outputs):
                    edge = (target, output)
                    yield extend(table, slot, edge), edge

    def finish(table: Table, difference: int, is_closed: bool) -> None:
        nonlocal leaves, closed, lower, upper, witness
        leaves += 1
        closed += int(is_closed)
        if lower is None or difference < lower:
            lower = difference
            witness = Machine(space.states, space.actions, space.outputs,
                              tuple(e if e is not None else (0, 0) for e in table))
        upper = difference if upper is None else max(upper, difference)

    def visit(table: Table, t: int, cs: int, bs: int, ci: int, bi: int, difference: int):
        tick()
        if t == candidate.horizon:
            finish(table, difference, False)
            return
        if close_suffixes and cs == bs and codes[0][t][ci] == codes[1][t][bi]:
            finish(table, difference, True)
            return
        ca, ba = candidate.levels[t][ci], incumbent.levels[t][bi]
        for tc, (cn, co) in edge_choices(table, cs, ca):
            for tb, (bn, bo) in edge_choices(tc, bs, ba):
                visit(tb, t+1, cn, bn, ci*space.outputs+co, bi*space.outputs+bo,
                      difference + rewards[co] - rewards[bo])
    try:
        for table in space.partials:
            visit(table, 0, 0, 0, 0, 0, 0)
    except SearchLimit:
        return Comparison('unknown', None, None, None, nodes, leaves, closed, generation)
    return Comparison('exact', lower, upper, witness, nodes, leaves, closed, generation)


def value(m: Machine, p: Program, rewards: tuple[int, ...]) -> int:
    return sum(rewards[o] for _, o in p.rollout(m))

@dataclass(frozen=True)
class OutcomeSet:
    status: str
    traces: frozenset[Trace]
    nodes: int


def possible_traces(space: LatentSpace, program: Program, *, max_nodes: int = 100000) -> OutcomeSet:
    """Observable experiment outcomes, not counts of arbitrary latent numberings.

    Two different possible traces imply every outcome removes at least one
    behavioral possibility. This does NOT quantify expected value of information.
    Unknown searches return no trustworthy outcome count.
    """
    validate_program(program,space.actions,space.outputs)
    if type(max_nodes) is not int or max_nodes<1:raise ValueError('positive search cap required')
    if not space.complete:return OutcomeSet('unknown',frozenset(),0)
    if not space.partials:return OutcomeSet('inconsistent',frozenset(),0)
    outcomes=set();nodes=0
    def visit(table,state,index,t,trace):
        nonlocal nodes
        nodes+=1
        if nodes>max_nodes:raise SearchLimit('outcome enumeration exceeded cap')
        if t==program.horizon:
            outcomes.add(trace);return
        action=program.levels[t][index];slot=state*space.actions+action
        choices=(table[slot],) if table[slot] is not None else product(range(space.states),range(space.outputs))
        for edge in choices:
            updated=table if table[slot] is not None else extend(table,slot,edge)
            state2,output=edge
            visit(updated,state2,index*space.outputs+output,t+1,trace+((action,output),))
    try:
        for table in space.partials:visit(table,0,0,0,())
    except SearchLimit:return OutcomeSet('unknown',frozenset(),nodes)
    return OutcomeSet('exact',frozenset(outcomes),nodes)
