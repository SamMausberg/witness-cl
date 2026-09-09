"""Exact finite-tape coupling with separate controller memories.

This is a pure simulator contract, not an API for cloning a real-world tool.
Matching the current action permits one shared transition, never an unexamined
shared suffix. The two controller states must continue to advance separately.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Hashable, Iterable

State = Hashable
Memory = Hashable
Noise = Hashable
Controller = Callable[[State, Memory, int], tuple[Hashable, Memory]]
Dynamics = Callable[[State, Hashable, Noise], tuple[State, int]]

@dataclass(frozen=True)
class Step:
    state: State
    memory: Memory
    action: Hashable
    next_state: State
    next_memory: Memory
    reward: int

@dataclass(frozen=True)
class CoupledResult:
    baseline: tuple[Step,...]
    candidate: tuple[Step,...]
    environment_calls: int
    controller_calls: int
    shared_transitions: int
    first_divergence: int|None


def independent(dynamics: Dynamics, controller: Controller, state: State,
                memory: Memory, tape: Iterable[Noise]) -> tuple[Step,...]:
    out=[]
    for t,noise in enumerate(tape):
        a,nm=controller(state,memory,t)
        ns,r=dynamics(state,a,noise)
        out.append(Step(state,memory,a,ns,nm,r))
        state,memory=ns,nm
    return tuple(out)


def coupled(dynamics: Dynamics, baseline: Controller, candidate: Controller,
            state: State, baseline_memory: Memory, candidate_memory: Memory,
            tape: Iterable[Noise]) -> CoupledResult:
    bs=cs=state
    bm,cm=baseline_memory,candidate_memory
    bt,ct=[],[]
    calls=shared=0
    first=None
    for t,noise in enumerate(tape):
        ba,bn=baseline(bs,bm,t)
        ca,cn=candidate(cs,cm,t)
        if bs==cs and ba==ca:
            ns,r=dynamics(bs,ba,noise)
            bns=cns=ns
            br=cr=r
            calls+=1
            shared+=1
        else:
            bns,br=dynamics(bs,ba,noise)
            cns,cr=dynamics(cs,ca,noise)
            calls+=2
            if first is None:
                first=t
        bt.append(Step(bs,bm,ba,bns,bn,br))
        ct.append(Step(cs,cm,ca,cns,cn,cr))
        bs,bm,cs,cm=bns,bn,cns,cn
    return CoupledResult(tuple(bt),tuple(ct),calls,2*len(bt),shared,first)


def closed_contract(states: Iterable[State], noises: Iterable[Noise],
                    base: Callable[[State,Noise],tuple[State,Hashable]],
                    candidate: Callable[[State,Noise],tuple[State,Hashable]]) -> bool:
    """Exhaustive finite-domain check. State MUST include all future-relevant state."""
    protected=frozenset(states)
    if not protected:
        raise ValueError('nonempty protected domain required')
    noise=tuple(noises)
    if not noise:
        raise ValueError('nonempty exogenous alphabet required')
    for s in protected:
        for u in noise:
            bn,bo=base(s,u)
            cn,co=candidate(s,u)
            if bn!=cn or bo!=co or bn not in protected:
                return False
    return True
