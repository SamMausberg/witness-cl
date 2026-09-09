"""Online neural proposals behind exact reset-continuation checks.

No offline dataset and no evaluator labels are consumed. The neural model is
updated once per executed episode and has no authority to issue certificates.
Public reward objectives are not hidden environment-state or regime labels.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from .latent import LatentSpace, Program, Trace, Comparison, compare, validate_program, possible_traces


class OnlineProposer:
    def __init__(self, programs: tuple[Program, ...], rewards: tuple[tuple[int, ...], ...],
                 actions: int, *, seed: int = 0, hidden: int = 16, lr: float = .025):
        if not programs or not rewards or hidden < 1 or not math.isfinite(lr) or lr <= 0:
            raise ValueError('valid nonempty program/objective library required')
        self.programs, self.rewards, self.actions, self.lr = programs, rewards, actions, lr
        self.horizon = programs[0].horizon
        self.visits = np.zeros((len(rewards), len(programs)), dtype=np.int64)
        self.features = np.zeros((len(rewards), len(programs), len(rewards)+self.horizon*actions))
        for g in range(len(rewards)):
            for j, program in enumerate(programs):
                self.features[g, j, g] = 1.
                for t, row in enumerate(program.levels):
                    for a in range(actions):
                        self.features[g, j, len(rewards)+t*actions+a] = row.count(a)/len(row)
        rng = np.random.default_rng(seed)
        self.w1 = rng.normal(0, .15, (self.features.shape[-1], hidden))
        self.b1 = np.zeros(hidden)
        self.w2 = rng.normal(0, .15, hidden)
        self.b2 = 0.
        self.updates = 0

    def scores(self, goal: int) -> np.ndarray:
        hidden = np.tanh(self.features[goal] @ self.w1 + self.b1)
        return hidden @ self.w2 + self.b2

    def rank(self, goal: int, *, trainable: bool = True) -> list[int]:
        predicted = self.scores(goal) if trainable else np.zeros(len(self.programs))
        score = predicted + .75/np.sqrt(1+self.visits[goal])
        return sorted(range(len(self.programs)), key=lambda j: (-float(score[j]), j))

    def observe(self, goal: int, program: int, reward: int, *, trainable: bool = True) -> None:
        if not 0 <= goal < len(self.rewards) or not 0 <= program < len(self.programs):
            raise ValueError('invalid training index')
        scale = max(abs(r) for r in self.rewards[goal]) * self.horizon
        if type(reward) is not int or abs(reward) > scale:
            raise ValueError('reward outside declared range')
        self.visits[goal, program] += 1
        if not trainable:
            return
        x = self.features[goal, program]
        h = np.tanh(x @ self.w1 + self.b1)
        target = reward/max(1, scale)
        error = float(h @ self.w2 + self.b2-target)
        # All derivatives refer to the same pre-update parameters.
        dh = error*self.w2*(1-h*h)
        self.w2 -= self.lr*error*h
        self.b2 -= self.lr*error
        self.w1 -= self.lr*np.outer(x, dh)
        self.b1 -= self.lr*dh
        self.updates += 1

    @property
    def parameter_bytes(self) -> int:
        return self.w1.nbytes+self.b1.nbytes+self.w2.nbytes+8


@dataclass(frozen=True)
class EpisodeTicket:
    index: int
    goal: int
    program: int
    incumbent: int
    debit: int
    generation: int
    era: int


class LatentAgent:
    """Integrated bounded-class learner; freezes each chosen program for the episode.

    All reward objectives are protected separately; the public goal selects the
    requested utility, not a hidden environment regime. Candidate ordering affects
    learning and cost, but cannot override checking. Risk debits are never refunded.
    """
    def __init__(self, space: LatentSpace, programs: tuple[Program, ...],
                 rewards: tuple[tuple[int, ...], ...], *, budget: int = 0,
                 seed: int = 0, trainable: bool = True, max_nodes: int = 100000,
                 proposals: int | None = None, informative_probes: bool = True):
        if not programs or len(set(programs)) != len(programs) or not rewards:
            raise ValueError('nonempty unique immutable program library required')
        for p in programs:
            validate_program(p, space.actions, space.outputs)
            if p.horizon != programs[0].horizon:
                raise ValueError('all programs require the same horizon')
        if any(len(r) != space.outputs or any(type(x) is not int for x in r) for r in rewards):
            raise ValueError('integer public objective for every output required')
        if type(budget) is not int or budget < 0 or max_nodes < 1:
            raise ValueError('nonnegative risk budget and positive node cap required')
        if proposals is not None and (type(proposals) is not int or proposals < 1):
            raise ValueError('positive candidate count required')
        self.space, self.programs, self.rewards = space, programs, rewards
        self.budget, self.spent, self.max_nodes, self.proposals = budget, 0, max_nodes, proposals
        self.trainable = trainable
        self.informative_probes = informative_probes
        self.proposer = OnlineProposer(programs, rewards, space.actions, seed=seed)
        self.incumbents = [0]*len(rewards)
        self.pending: EpisodeTicket | None = None
        self.episodes = self.era = 0
        self.comparisons = self.nodes = self.unknown = self.promotions = 0
        self.certificates: list[tuple[int, int, int, int, int]] = []
        self.era_history: list[dict] = []

    def choose(self, goal: int) -> EpisodeTicket:
        if self.pending is not None:
            raise RuntimeError('outstanding episode must finish before choosing another')
        if type(goal) is not int or not 0 <= goal < len(self.rewards):
            raise ValueError('invalid public objective')
        if self.space.complete and not self.space.partials:
            self.pending=EpisodeTicket(self.episodes,goal,0,0,0,self.space.generation,self.era)
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
        # Strict guaranteed improvement preferred; ties preserve incumbent.
        admitted = [(j,c) for j,c in checked if c.admits and c.lower > 0]
        if admitted:
            j,c = max(admitted, key=lambda jc: (jc[1].lower, -rank.index(jc[0])))
            self.incumbents[goal] = j
            self.promotions += 1
            self.certificates.append((self.episodes,goal,baseline,j,c.lower))
            chosen, debit = j, 0
        else:
            chosen, debit = baseline, 0
            # A whole-episode probe needs a known worst-case deficit before use.
            # Unknown searches, inconsistent classes, and stale generations abstain.
            feasible=[]
            for j,c in checked:
                if c.status == 'exact' and c.upper > 0:
                    d = max(0, -c.lower)
                    if self.spent+d <= self.budget:
                        if not self.informative_probes:
                            chosen,debit=j,d
                            break
                        outcomes=possible_traces(self.space,self.programs[j],max_nodes=self.max_nodes)
                        self.nodes+=outcomes.nodes
                        self.unknown+=outcomes.status=='unknown'
                        if outcomes.status=='exact' and len(outcomes.traces)>1:
                            feasible.append((d,-len(outcomes.traces),-c.upper,rank.index(j),j))
            if feasible:
                debit,_,_,_,chosen=min(feasible)
        self.spent += debit
        self.pending = EpisodeTicket(self.episodes,goal,chosen,self.incumbents[goal],
                                     debit,self.space.generation,self.era)
        return self.pending

    def observe(self, ticket: EpisodeTicket, trace: Trace) -> None:
        if ticket is not self.pending or ticket.era != self.era or ticket.generation != self.space.generation:
            raise ValueError('foreign, stale, or already used episode ticket')
        self.space._validate(trace)
        program = self.programs[ticket.program]
        if len(trace) != program.horizon:
            raise ValueError('full episode trace required')
        index = 0
        for t,(action,output) in enumerate(trace):
            if program.levels[t][index] != action:
                raise ValueError('feedback action does not match committed program')
            index = index*program.outputs+output
        reward = sum(self.rewards[ticket.goal][output] for _,output in trace)
        self.space.observe(trace)
        self.proposer.observe(ticket.goal,ticket.program,reward,trainable=self.trainable)
        self.pending = None
        self.episodes += 1

    def register(self, program: Program) -> int:
        """Append a typed candidate without changing old policies, IDs or world class."""
        if self.pending is not None:
            raise RuntimeError('new programs become visible only at episode boundaries')
        validate_program(program,self.space.actions,self.space.outputs)
        if program.horizon!=self.programs[0].horizon:
            raise ValueError('new program horizon mismatch')
        if program in self.programs:
            return self.programs.index(program)
        if len(self.programs)>=1024:
            raise ValueError('reference candidate registry cap exceeded')
        new_programs=self.programs+(program,)
        old=self.proposer
        new=OnlineProposer(new_programs,self.rewards,self.space.actions,hidden=len(old.b1),lr=old.lr)
        new.w1=old.w1.copy();new.b1=old.b1.copy();new.w2=old.w2.copy();new.b2=old.b2
        new.visits[:,:len(self.programs)]=old.visits
        new.updates=old.updates
        self.programs=new_programs;self.proposer=new
        return len(self.programs)-1

    def expand(self, states: int) -> None:
        if self.pending is not None:
            raise RuntimeError('cannot change model contract during an episode')
        self.space.expand(states)
        self.era_history.append({'era':self.era,'spent':self.spent,'incumbents':list(self.incumbents)})
        self.era += 1
        self.incumbents = [0]*len(self.rewards)
        self.spent = 0
        # Archived programs and learned proposer retained, old certificates NOT inherited.
