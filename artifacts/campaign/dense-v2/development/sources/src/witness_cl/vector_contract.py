"""Vectorized CPU continuation primitive; exact checked int64 domain.

This reduces interpreter overhead. It does not establish GPU or LLM throughput.
Use the scalar arbitrary-precision integer reference for overflow-domain inputs.
"""
from __future__ import annotations
import numpy as np
from .continuation import Model,Policy,validate_policy

def packed_advantages(models:tuple[Model,...],base:Policy):
    if not models or any(m.shape!=models[0].shape for m in models):
        raise ValueError('nonempty common-shape family required')
    H,S,A=models[0].shape
    for m in models: validate_policy(m,base)
    bound=max(abs(x) for m in models for t in m.reward for row in t for x in row)
    if bound*(2*H+1)>np.iinfo(np.int64).max:
        raise OverflowError('int64 accumulation unsafe; use scalar reference')
    ns=np.array([m.next_state for m in models],dtype=np.int64)
    r=np.array([m.reward for m in models],dtype=np.int64)
    actions=np.array(base.actions,dtype=np.int64)
    M=len(models)
    v=np.zeros((M,H+1,S),dtype=np.int64)
    mi=np.arange(M)[:,None]
    si=np.arange(S)[None,:]
    for t in reversed(range(H)):
        act=np.broadcast_to(actions[t],(M,S))
        dest=ns[:,t][mi,si,act]
        v[:,t]=r[:,t][mi,si,act]+v[:,t+1][mi,dest]
    adv=np.empty((M,H,S,A),dtype=np.int64)
    for t in range(H):
        adv[:,t]=r[:,t]+v[:,t+1][np.arange(M)[:,None,None],ns[:,t]]-v[:,t,:,None]
    return v,adv.min(axis=0)
