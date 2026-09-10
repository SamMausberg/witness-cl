"""Integrated one-step continual agent: propose online, randomize, audit, promote.

Read-only pure policies only. No unexecuted outcome is supplied to the learner.
Experimental treatment can degrade an episode; admission is not an exploration
safety guarantee. No LLM integration or irreversible-action authorization here.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction as Q
import random
from typing import Any,Iterable
from .adaptive import Rule,Observation,RecurringAgent
from .audit import AuditSpec
from .local_audit import RandomizedAudit
from .types import Scope

@dataclass(frozen=True)
class SystemTicket:
    episode:int
    x:Any
    action:Any
    baseline_action:Any
    inside:bool
    treatment:bool
    audit_index:int|None

class ContinualSystem:
    def __init__(self,tiers:Iterable[Iterable[Rule]],baseline:Rule,*,seed:int=0,delta:Q=Q(1,20)):
        self.proposer=RecurringAgent(tiers)
        self.baseline=baseline
        self.registry={baseline.key:baseline}
        self.rng=random.Random(seed)
        self.delta=delta
        self.audit:RandomizedAudit|None=None
        self.candidate:Rule|None=None
        self.next_index=1
        self.pending:SystemTicket|None=None
        self.last_episode=-1
        self.promotions=[]
        self.audit_episodes=0
        self.cancelled=0

    def decide(self,episode:int,x:Any)->SystemTicket:
        if self.pending is not None or episode<=self.last_episode:
            raise ValueError('one chronological outstanding decision is allowed')
        b=self.baseline(x)
        inside=self.candidate is not None and self.candidate(x)!=b
        treatment=inside and self.rng.random()<.5
        action=self.candidate(x) if treatment else b
        ticket=SystemTicket(episode,x,action,b,inside,treatment,
                            self.audit.spec.index if self.audit else None)
        self.pending=ticket
        return ticket

    def observe(self,ticket:SystemTicket,success:bool)->None:
        if ticket!=self.pending:
            raise ValueError('stale/foreign system decision')
        # Retire a comparison on a detected evidence-epoch change. Undetected
        # drift can still invalidate a stationary deployment interpretation.
        previous_epoch=self.proposer.epoch
        self.proposer.observe(Observation(ticket.episode,ticket.x,ticket.action,success))
        epoch_changed=self.proposer.epoch!=previous_epoch
        if self.audit is not None and (epoch_changed or self.candidate.key not in {r.key for r in self.proposer.space.live}):
            self.audit=None;self.candidate=None;self.cancelled+=1
        if self.audit is not None and ticket.inside:
            self.audit.observe(episode=ticket.episode,candidate_hash=self.candidate.key,
                baseline_hash=self.baseline.key,treatment=ticket.treatment,
                propensity=Q(1,2),reward=int(success))
            self.audit_episodes+=1
            if self.audit.can_promote(self.baseline.key):
                self.baseline=self.candidate
                self.registry.setdefault(self.baseline.key,self.baseline)
                self.promotions.append((ticket.episode,self.baseline.key,self.audit.spec.index))
                self.audit=None;self.candidate=None
        if self.audit is None:
            alternatives=[r for r in self.proposer.space.live if r.key!=self.baseline.key]
            if alternatives:
                # A provisional experiment is allowed before identification. Without
                # this, observing only an uninformative baseline can deadlock learning.
                rule=max(alternatives,key=lambda r:self.proposer.prior[r.key])
                self.candidate=rule
                spec=AuditSpec(self.next_index,ticket.episode,Scope('one-step',f'epoch-{self.proposer.epoch}'),
                               rule.key,self.baseline.key,self.delta)
                self.audit=RandomizedAudit(spec)
                self.next_index+=1
        self.pending=None
        self.last_episode=ticket.episode
