"""Append-only trainable modules with trusted public-scope dispatch.

New feature maps can be trained without modifying old modules. This trades
memory growth for retention; it does not solve latent-context recognition. The
caller must freeze input construction and use an authentic schema/version key.
No torch dependency is needed for the small float64 neural reference.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import numpy as np


def _immutable(a):
    a=np.array(a,dtype=np.float64,copy=True)
    # A bytes-backed ndarray cannot be made writable again by a caller.
    return np.frombuffer(a.tobytes(),dtype=np.float64).reshape(a.shape)

@dataclass(frozen=True)
class FrozenNetwork:
    w:np.ndarray
    b:np.ndarray
    v:np.ndarray
    c:np.ndarray
    def __post_init__(self):
        for key in ('w','b','v','c'):
            object.__setattr__(self,key,_immutable(getattr(self,key)))
    def predict(self,x):
        return np.tanh(np.asarray(x)@self.w+self.b)@self.v+self.c
    @property
    def key(self):
        h=hashlib.sha256()
        for x in (self.w,self.b,self.v,self.c):
            h.update(str(x.shape).encode());h.update(x.tobytes())
        return h.hexdigest()

class OnlineNetwork:
    def __init__(self,inputs:int,hidden:int,seed:int):
        rng=np.random.default_rng(seed)
        self.w=rng.normal(0,.4,(inputs,hidden));self.b=np.zeros(hidden)
        self.v=rng.normal(0,.1,hidden);self.c=np.zeros(())
        self.updates=0
    def predict(self,x):
        return np.tanh(np.asarray(x)@self.w+self.b)@self.v+self.c
    def update_from_feedback(self,x,action:int,success:bool,lr:float=.03):
        # With two exhaustive actions and exact success, own outcome identifies
        # the desired binary decision. This inference is invalid with noise.
        if action not in (0,1) or type(success) is not bool:
            raise ValueError('exact binary-action feedback required')
        y=action if success else 1-action
        x=np.asarray(x,dtype=np.float64)
        if x.shape!=(self.w.shape[0],) or not np.all(np.isfinite(x)) or not np.isfinite(lr) or lr<=0:
            raise ValueError('finite feature vector and positive learning rate required')
        h=np.tanh(x@self.w+self.b)
        z=float(h@self.v+self.c)
        prob=1/(1+np.exp(-np.clip(z,-40,40)))
        d=prob-y
        dh=d*self.v*(1-h*h)
        self.v-=lr*d*h;self.c-=lr*d
        self.w-=lr*np.outer(x,dh);self.b-=lr*dh
        self.updates+=1
    def freeze(self): return FrozenNetwork(self.w,self.b,self.v,self.c)

class ModuleArchive:
    def __init__(self):
        self._versions={}
        self._scope={}
    def register(self,scope:str,snapshot:FrozenNetwork):
        if not scope or scope in self._scope:
            raise ValueError('new public scope required; old dispatch cannot be overwritten')
        # Copy bytes even from another immutable snapshot: no caller alias.
        copy=FrozenNetwork(snapshot.w,snapshot.b,snapshot.v,snapshot.c)
        self._versions.setdefault(copy.key,copy)
        self._scope[scope]=copy.key
        return copy.key
    def predict(self,scope:str,x):
        if scope not in self._scope:
            raise KeyError('unknown schema/version: explicit fallback required')
        return self._versions[self._scope[scope]].predict(x)
    @property
    def parameter_bytes(self):
        return sum(sum(a.nbytes for a in (m.w,m.b,m.v,m.c)) for m in self._versions.values())
