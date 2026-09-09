"""Fixed-share EXP4-style routing with only the selected action's loss.

Established online-learning machinery, not a new regret theorem. Implemented
for a fixed immutable archive and a known finite action alphabet. Structural
retention of experts does not imply a correct router or no per-episode regret.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np

@dataclass(frozen=True)
class RoutingTicket:
    round: int
    action: int
    propensity: float
    predictions: tuple[int,...]

class FixedShareRouter:
    def __init__(self, experts: int, actions: int, *, eta: float=.1,
                 share: float=.01, exploration: float=.02, seed: int=0):
        if experts<1 or actions<2 or eta<=0 or not 0<share<1 or not 0<exploration<1:
            raise ValueError('invalid router parameters')
        self.experts,self.actions=experts,actions
        self.eta,self.share,self.exploration=eta,share,exploration
        self.weights=np.full(experts,1/experts,dtype=np.float64)
        self.rng=np.random.default_rng(seed)
        self.round=0
        self.pending: RoutingTicket | None=None

    def choose(self,predictions: list[int] | tuple[int,...]) -> RoutingTicket:
        if self.pending is not None:
            raise RuntimeError('the preceding action has not received feedback')
        if len(predictions)!=self.experts or any(not 0<=a<self.actions for a in predictions):
            raise ValueError('invalid expert predictions')
        q=np.bincount(predictions,weights=self.weights,minlength=self.actions)
        p=(1-self.exploration)*q+self.exploration/self.actions
        p/=p.sum()
        action=int(self.rng.choice(self.actions,p=p))
        ticket=RoutingTicket(self.round,action,float(p[action]),tuple(predictions))
        self.pending=ticket
        return ticket

    def observe(self,ticket: RoutingTicket,loss: float) -> None:
        if self.pending is None or ticket!=self.pending:
            raise ValueError('stale or foreign routing ticket')
        if not math.isfinite(loss) or not 0<=loss<=1:
            raise ValueError('loss must be in [0,1]')
        estimates=np.asarray([loss/ticket.propensity if a==ticket.action else 0
                              for a in ticket.predictions],dtype=np.float64)
        logw=np.log(self.weights)-self.eta*estimates
        logw-=logw.max()
        unnormalized=np.exp(logw)
        posterior=unnormalized/unnormalized.sum()
        self.weights=(1-self.share)*posterior+self.share/self.experts
        self.round+=1
        self.pending=None

    def expected_regret_bound(self,horizon:int,switches:int) -> float:
        if horizon<1 or not 0<=switches<horizon:
            raise ValueError('invalid comparator schedule')
        B=(math.log(self.experts)+switches*math.log(self.experts/self.share)+
           (horizon-1-switches)*(-math.log1p(-self.share)))
        return (B/self.eta+self.eta*self.actions*horizon/(2*(1-self.exploration))+
                self.exploration*horizon)
