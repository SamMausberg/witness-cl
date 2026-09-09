"""Audits for a frozen local replacement and non-cloneable randomized episodes.

No model-generated counterfactual reward is used. Gates and centers must be
fixed/predictable before reward; a gate passed here is NOT verified by this API.
"""
from __future__ import annotations
from fractions import Fraction as Q
from .audit import AuditSpec,PairedAudit

class ScreenedAudit:
    def __init__(self,spec:AuditSpec,guard_hash:str):
        if not guard_hash:
            raise ValueError('frozen guard identity required')
        self.audit=PairedAudit(spec)
        self.guard_hash=guard_hash
        self.screened=0
        self.forks=0
        self.last_episode=spec.born_after_episode

    def observe(self,*,episode:int,guard_hash:str,inside:bool,
                candidate_reward:Q|int|None=None,baseline_reward:Q|int|None=None)->None:
        if guard_hash!=self.guard_hash or episode<=self.last_episode:
            raise ValueError('changed guard or stale observation')
        if inside:
            if candidate_reward is None or baseline_reward is None:
                raise ValueError('inside the gate both actually observed rewards are required')
            s=self.audit.spec
            self.audit.observe(episode=episode,scope=s.scope,candidate_hash=s.candidate_hash,
                               baseline_hash=s.baseline_hash,candidate_reward=candidate_reward,
                               baseline_reward=baseline_reward)
            self.forks+=1
        elif candidate_reward is not None:
            raise ValueError('outside the gate no hypothetical candidate reward may be supplied')
        self.screened+=1
        self.last_episode=episode

class RandomizedAudit:
    """Fresh treatment coin; only the executed policy's reward is observed.

    For a fixed center c=1/2 and e in [p_min,1-p_min], Z equals
    (A/e-(1-A)/(1-e))*(R-1/2), has E[Z]=mean benefit, and |Z|<=B=1/(2p_min).
    Constant B is important: context-dependent scaling can change the estimand.
    The caller must really randomize before outcomes and avoid carryover effects.
    """
    stakes=PairedAudit.stakes
    def __init__(self,spec:AuditSpec,p_min:Q=Q(1,2)):
        if not isinstance(p_min,Q) or not 0<p_min<=Q(1,2):
            raise ValueError('p_min must be an exact Fraction in (0,1/2]')
        self.spec=spec
        self.p_min=p_min
        self.bound=1/(2*p_min)
        self.capitals=[Q(1) for _ in self.stakes]
        self.last_episode=spec.born_after_episode
        self.passed=False
        self.samples=0

    @property
    def e_value(self)->Q:
        return sum(self.capitals,Q(0))/len(self.capitals)

    def observe(self,*,episode:int,candidate_hash:str,baseline_hash:str,
                treatment:bool,propensity:Q,reward:Q|int)->None:
        if episode<=self.last_episode:
            raise ValueError('stale or proposal observation')
        if (candidate_hash,baseline_hash)!=(self.spec.candidate_hash,self.spec.baseline_hash):
            raise ValueError('policy snapshot changed')
        if not isinstance(propensity,Q) or not self.p_min<=propensity<=1-self.p_min:
            raise ValueError('invalid logged treatment propensity')
        if not isinstance(reward,(Q,int)) or not 0<=reward<=1:
            raise ValueError('reward must be exact and in [0,1]')
        coeff=1/propensity if treatment else -1/(1-propensity)
        z=coeff*(Q(reward)-Q(1,2))
        value=z/self.bound
        assert -1<=value<=1
        self.capitals=[w*(1+lam*value) for w,lam in zip(self.capitals,self.stakes)]
        self.passed|=self.e_value>=1/self.spec.allocated_delta
        self.last_episode=episode
        self.samples+=1

    def can_promote(self,current_baseline_hash:str)->bool:
        return self.passed and current_baseline_hash==self.spec.baseline_hash

class PredictablePairedAudit(PairedAudit):
    """Mixture including small stakes and a predictable variance-scaled component.

    The adaptive stake uses preceding differences only. Sparse zero-padding
    leaves both sufficient statistics and wealth unchanged. This is standard
    predictable betting, not a new probability result.
    """
    stakes=(Q(1,64),Q(1,32),Q(1,16),Q(1,8),Q(1,4),Q(1,2),Q(3,4),Q(1))
    def __init__(self,spec:AuditSpec):
        super().__init__(spec)
        self.adaptive_capital=Q(1)
        self.sum_d=Q(0)
        self.sum_d2=Q(8)

    @property
    def e_value(self)->Q:
        return (sum(self.capitals,Q(0))+self.adaptive_capital)/(len(self.capitals)+1)

    def observe(self,**kwargs)->None:
        stake=min(Q(9,10),max(Q(0),self.sum_d/self.sum_d2))
        # Parent checks chronology, rewards and identities before any mutation.
        was_passed=self.passed
        super().observe(**kwargs)
        d=self.differences[-1]
        self.adaptive_capital*=1+stake*d
        self.sum_d+=d
        self.sum_d2+=d*d
        self.passed=was_passed or self.e_value>=1/self.spec.allocated_delta
