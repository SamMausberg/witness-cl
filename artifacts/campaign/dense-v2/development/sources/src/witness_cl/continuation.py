"""Finite-horizon continuation contracts, not immediate-reward certificates.

All arithmetic in the deterministic reference is integer-exact. The environment
family is supplied, not discovered from unrestricted text. Contracts are sound
only when that stationary family contains the actual environment. Observed
transitions, never unexecuted rewards, update the bank. Enumerative model
rollouts are predictions used for planning, not empirical evaluation data.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable

Cube = tuple[tuple[tuple[int, ...], ...], ...]

def digest(obj: object) -> str:
    return sha256(json.dumps(obj, separators=(',', ':'), sort_keys=True).encode()).hexdigest()

@dataclass(frozen=True)
class Model:
    next_state: Cube
    reward: Cube
    name: str = ''

    def __post_init__(self) -> None:
        # Canonicalize so callers cannot mutate an allegedly frozen model via a list.
        for field in ('next_state', 'reward'):
            value = getattr(self, field)
            object.__setattr__(self, field, tuple(tuple(tuple(v for v in a) for a in s) for s in value))
        if not self.next_state or not self.next_state[0] or not self.next_state[0][0]:
            raise ValueError('nonempty H,S,A required')
        H, S, A = self.shape
        for arr in (self.next_state, self.reward):
            if len(arr) != H or any(len(t) != S for t in arr) or any(len(row) != A for t in arr for row in t):
                raise ValueError('rectangular model tensors with common shape required')
            if any(type(x) is not int for t in arr for row in t for x in row):
                raise TypeError('integer reference semantics required')
        if any(not 0 <= x < S for t in self.next_state for row in t for x in row):
            raise ValueError('next state outside model')

    @property
    def shape(self) -> tuple[int,int,int]:
        return len(self.next_state), len(self.next_state[0]), len(self.next_state[0][0])

    @property
    def key(self) -> str:
        return digest((self.next_state, self.reward))

@dataclass(frozen=True)
class Policy:
    actions: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'actions', tuple(tuple(row) for row in self.actions))
        if not self.actions or not self.actions[0] or any(len(r) != len(self.actions[0]) for r in self.actions):
            raise ValueError('nonempty rectangular policy required')
        if any(type(a) is not int or a < 0 for row in self.actions for a in row):
            raise ValueError('nonnegative integer actions required')

    @property
    def key(self) -> str:
        return digest(self.actions)

@dataclass(frozen=True)
class Transition:
    episode: int
    step: int
    state: int
    action: int
    reward: int
    next_state: int


def validate_policy(model: Model, policy: Policy) -> None:
    H,S,A = model.shape
    if len(policy.actions) != H or any(len(row) != S for row in policy.actions):
        raise ValueError('policy shape mismatch')
    if any(a >= A for row in policy.actions for a in row):
        raise ValueError('action outside model')


def value(model: Model, policy: Policy) -> tuple[tuple[int, ...], ...]:
    validate_policy(model, policy)
    H,S,_ = model.shape
    vals = [[0]*S for _ in range(H+1)]
    for t in reversed(range(H)):
        for s in range(S):
            a = policy.actions[t][s]
            vals[t][s] = model.reward[t][s][a] + vals[t+1][model.next_state[t][s][a]]
    return tuple(tuple(row) for row in vals)


def optimal(model: Model) -> Policy:
    H,S,A = model.shape
    vals, actions = [[0]*S for _ in range(H+1)], [[0]*S for _ in range(H)]
    for t in reversed(range(H)):
        for s in range(S):
            a = max(range(A), key=lambda a:(model.reward[t][s][a]+vals[t+1][model.next_state[t][s][a]],-a))
            actions[t][s] = a
            vals[t][s] = model.reward[t][s][a]+vals[t+1][model.next_state[t][s][a]]
    return Policy(tuple(tuple(row) for row in actions))


def rollout(model: Model, policy: Policy, state: int, episode: int) -> tuple[Transition, ...]:
    validate_policy(model, policy)
    H,S,_ = model.shape
    if type(state) is not int or not 0 <= state < S:
        raise ValueError('invalid initial state')
    events=[]
    for t in range(H):
        a=policy.actions[t][state]
        ns,r=model.next_state[t][state][a],model.reward[t][state][a]
        events.append(Transition(episode,t,state,a,r,ns))
        state=ns
    return tuple(events)


def outcome_signature(model: Model, policy: Policy, state: int) -> tuple:
    return tuple((e.step,e.state,e.action,e.reward,e.next_state) for e in rollout(model,policy,state,0))

class ModelBank:
    """Append-only evidence; shrinking live family; atomic, full-history expansion."""
    def __init__(self, models: Iterable[Model]):
        self.models=tuple(models)
        self._validate(self.models)
        self.live=self.models
        self.history: list[Transition]=[]
        self.generation=0
        self.evaluations=0

    @staticmethod
    def _validate(models: tuple[Model, ...]) -> None:
        if not models or len({m.key for m in models}) != len(models):
            raise ValueError('nonempty semantically distinct family required')
        if any(m.shape != models[0].shape for m in models):
            raise ValueError('common model shape required')

    @staticmethod
    def agrees(m: Model, e: Transition) -> bool:
        return m.reward[e.step][e.state][e.action] == e.reward and m.next_state[e.step][e.state][e.action] == e.next_state

    def observe(self, events: Iterable[Transition]) -> None:
        seq=tuple(events)
        H,S,A=self.models[0].shape
        last=(self.history[-1].episode,self.history[-1].step) if self.history else (-1,-1)
        for e in seq:
            if not isinstance(e, Transition) or any(type(x) is not int for x in (e.episode,e.step,e.state,e.action,e.reward,e.next_state)):
                raise TypeError('exact transition record required')
            if (e.episode,e.step) <= last or not 0 <= e.step < H or not 0 <= e.state < S or not 0 <= e.action < A or not 0 <= e.next_state < S:
                raise ValueError('invalid or stale transition')
            last=e.episode,e.step
        staged=tuple(m for m in self.live if all(self.agrees(m,e) for e in seq))
        self.evaluations += len(self.live)*len(seq) # Upper bound, including short-circuit omissions.
        self.history.extend(seq)
        self.live=staged
        self.generation+=1

    def add(self, models: Iterable[Model]) -> None:
        additions=tuple(models)
        if not additions:
            return
        combined=self.models+additions
        self._validate(combined)
        # Old evidence is not assumed redundant for newly introduced models.
        live=tuple(m for m in combined if all(self.agrees(m,e) for e in self.history))
        self.models,self.live=combined,live
        self.evaluations+=len(combined)*len(self.history)
        self.generation+=1

@dataclass(frozen=True)
class Contract:
    baseline: str
    candidate: str
    family: tuple[str, ...]
    generation: int
    min_advantage: int

    def validate(self, bank: ModelBank, base: Policy, candidate: Policy) -> None:
        if not bank.live:
            raise ValueError('empty family never constitutes a certificate')
        if self.baseline != base.key or self.candidate != candidate.key or self.generation != bank.generation or self.family != tuple(m.key for m in bank.live):
            raise ValueError('stale or foreign continuation contract')
        if self.min_advantage < 0:
            raise ValueError('negative Bellman lower bound')


def certify(bank: ModelBank, base: Policy, candidate: Policy) -> Contract:
    """Sufficient all-state condition; rejects some globally beneficial policies."""
    if not bank.live:
        raise ValueError('cannot certify under model contradiction')
    lower=None
    for m in bank.live:
        validate_policy(m,candidate)
        v=value(m,base)
        H,S,_=m.shape
        for t in range(H):
            for s in range(S):
                a=candidate.actions[t][s]
                d=m.reward[t][s][a]+v[t+1][m.next_state[t][s][a]]-v[t][s]
                lower=d if lower is None else min(lower,d)
    if lower is None or lower < 0:
        raise ValueError('candidate violates a continuation obligation')
    return Contract(base.key,candidate.key,tuple(m.key for m in bank.live),bank.generation,lower)


def improve(bank: ModelBank, base: Policy) -> tuple[Policy,Contract]:
    if not bank.live:
        raise ValueError('no live model: external fallback required')
    vals=[value(m,base) for m in bank.live]
    H,S,A=bank.live[0].shape
    actions=[list(row) for row in base.actions]
    for t in range(H):
        for s in range(S):
            options=[]
            for a in range(A):
                advantages=[m.reward[t][s][a]+v[t+1][m.next_state[t][s][a]]-v[t][s] for m,v in zip(bank.live,vals)]
                if min(advantages)>=0:
                    options.append((sum(advantages),int(a==base.actions[t][s]),-a,a))
            actions[t][s]=max(options)[-1]
    candidate=Policy(tuple(tuple(row) for row in actions))
    return candidate,certify(bank,base,candidate)

@dataclass(frozen=True)
class EpisodeChoice:
    episode: int
    state: int
    policy: Policy
    incumbent: Policy
    exploratory: bool
    debit: int
    family_size: int
    generation: int

class ContractAgent:
    """Online identification + robust improvement + finite exposure ledger.

    The fixed-anchor regret bound is deterministic for a stationary realizable
    finite family and episodic environment resets. Budget is in native reward
    units. It is NOT a safety proof for an unrestricted live environment.
    """
    def __init__(self, models: Iterable[Model], anchor: Policy, budget: int):
        if type(budget) is not int or budget < 0:
            raise ValueError('nonnegative integer budget required')
        self.bank=ModelBank(models)
        validate_policy(self.bank.models[0],anchor)
        self.anchor=self.incumbent=anchor
        self.budget=budget
        self.spent=0
        self.archive={anchor.key:anchor}
        self.pending: EpisodeChoice|None=None
        self.last_episode=-1
        self.planning_model_rollouts=0
        self.certified_family=frozenset(m.key for m in self.bank.live)
        self.trust_era=0

    def choose(self, episode: int, state: int) -> EpisodeChoice:
        if self.pending is not None or episode<=self.last_episode:
            raise ValueError('one fresh outstanding episode required')
        if not self.bank.live:
            raise ValueError('model contradicted: repair or explicit external fallback')
        H,S,_=self.bank.models[0].shape
        if not 0 <= state < S:
            raise ValueError('invalid state')
        # Shrinking a stationary plausible family preserves the incumbent's
        # earlier guarantees. Rebuilding from the anchor here would permit
        # forgetting of already acquired improvements.
        current_family=frozenset(m.key for m in self.bank.live)
        if current_family <= self.certified_family:
            incumbent=self.incumbent
        else:
            # Expansion changes the scope of the claim. Do not inherit an old
            # certificate on a larger family. Start an explicitly new trust era.
            incumbent=self.anchor
            self.trust_era+=1
        self.certified_family=current_family
        for _ in range(H):
            new,contract=improve(self.bank,incumbent)
            contract.validate(self.bank,incumbent,new)
            if new==incumbent:
                break
            incumbent=new
        self.incumbent=incumbent
        self.archive.setdefault(incumbent.key,incumbent)
        candidates={incumbent.key:incumbent}
        candidates.update({p.key:p for p in (optimal(m) for m in self.bank.live)})
        candidates.update(self.archive)
        chosen=incumbent
        debit=0
        best_score=(0,0,0)
        incumbent_vals={m.key:value(m,incumbent)[0][state] for m in self.bank.live}
        for p in candidates.values():
            returns=[value(m,p)[0][state] for m in self.bank.live]
            d=max(0,max(incumbent_vals[m.key]-v for m,v in zip(self.bank.live,returns)))
            if self.spent+d>self.budget:
                continue
            buckets:dict[tuple,int]={}
            for m in self.bank.live:
                sig=outcome_signature(m,p,state)
                buckets[sig]=buckets.get(sig,0)+1
                self.planning_model_rollouts+=1
            # Worst-case eliminated models, then optimistic gain, then low exposure.
            info=len(self.bank.live)-max(buckets.values())
            optimism=max(v-incumbent_vals[m.key] for m,v in zip(self.bank.live,returns))
            score=(info,optimism,-d)
            if info>0 and score>best_score:
                chosen,debit,best_score=p,d,score
        self.spent+=debit # Reserve before execution. No refunds from favorable outcomes.
        ticket=EpisodeChoice(episode,state,chosen,incumbent,chosen!=incumbent,debit,len(self.bank.live),self.bank.generation)
        self.pending=ticket
        return ticket

    def observe(self, choice: EpisodeChoice, events: Iterable[Transition]) -> None:
        if choice is not self.pending or choice.generation!=self.bank.generation:
            raise ValueError('stale/foreign episode choice')
        seq=tuple(events)
        H,_,_=self.bank.models[0].shape
        if len(seq)!=H:
            raise ValueError('complete episode required')
        state=choice.state
        for t,e in enumerate(seq):
            if e.episode!=choice.episode or e.step!=t or e.state!=state or e.action!=choice.policy.actions[t][state]:
                raise ValueError('trajectory is not the executed policy')
            state=e.next_state
        self.bank.observe(seq)
        self.pending=None
        self.last_episode=choice.episode
