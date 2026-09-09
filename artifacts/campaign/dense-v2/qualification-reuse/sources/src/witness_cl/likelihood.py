"""Anytime plausible-model filtering for a FIXED finite probabilistic family.

For a true member m, mixture_likelihood / likelihood_m is a nonnegative
supermartingale under predictable actions. Rejecting at 1/delta controls ever
rejecting the truth. A model suggested after observing data cannot be appended
with retroactive likelihood credit. This reference intentionally forbids births.
"""
from __future__ import annotations
from fractions import Fraction as Q
from typing import Iterable

class LikelihoodBank:
    def __init__(self, prior: Iterable[Q], delta: Q=Q(1,20)):
        self.prior=tuple(Q(p) for p in prior)
        self.delta=Q(delta)
        if not self.prior or any(p<=0 for p in self.prior) or sum(self.prior)!=1:
            raise ValueError('strictly positive normalized prior required')
        if not 0<self.delta<1:
            raise ValueError('delta must lie strictly between zero and one')
        self.likelihood=tuple(Q(1) for _ in self.prior)
        self.steps=0

    def observe_probabilities(self, probabilities: Iterable[Q]) -> None:
        """Probabilities assigned to the ONE observed outcome by frozen models.

        Correct conditional model probabilities and predictable action/context
        selection are semantic obligations of the caller, not checked here.
        """
        probs=tuple(Q(p) for p in probabilities)
        if len(probs)!=len(self.prior) or any(not 0<=p<=1 for p in probs):
            raise ValueError('one valid likelihood per fixed model required')
        new=tuple(a*b for a,b in zip(self.likelihood,probs))
        if not any(new):
            raise ValueError('every model assigns zero probability: contradiction')
        self.likelihood=new
        self.steps+=1

    @property
    def mixture(self) -> Q:
        return sum((p*l for p,l in zip(self.prior,self.likelihood)),Q(0))

    @property
    def live(self) -> tuple[int,...]:
        # Strict acceptance of models not yet crossing the rejection threshold.
        return tuple(i for i,l in enumerate(self.likelihood) if l and self.mixture*self.delta<l)

    def ratio(self, model: int) -> Q|None:
        l=self.likelihood[model]
        return self.mixture/l if l else None
