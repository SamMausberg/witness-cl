"""Online residual learning with a frozen feature extractor and protected subspace.

Exact arithmetic: updates annihilate the span of protected rows. Float64 code
only approximates that algebra; measure residuals. This is not universal retention
or novel linear algebra, and preserving a full-rank span leaves zero capacity.
"""
from __future__ import annotations
import numpy as np

class ProtectedResidual:
    def __init__(self,base_weights:np.ndarray,protected_features:np.ndarray,*,rtol:float=1e-12):
        base=np.array(base_weights,dtype=np.float64,copy=True)
        anchors=np.array(protected_features,dtype=np.float64,copy=True)
        if base.ndim!=1 or anchors.ndim!=2 or anchors.shape[1]!=base.size:
            raise ValueError('base [d] and protected [n,d] required')
        if not np.isfinite(base).all() or not np.isfinite(anchors).all() or rtol<0:
            raise ValueError('finite arrays and nonnegative tolerance required')
        self.base=base
        self.base.flags.writeable=False
        self.anchors=anchors
        if anchors.shape[0]:
            _,s,vh=np.linalg.svd(anchors,full_matrices=False)
            rank=int(np.sum(s>rtol*s[0])) if s.size and s[0]>0 else 0
            self.basis=vh[:rank].T.copy()
        else:
            rank=0
            self.basis=np.empty((base.size,0))
        self.anchors.flags.writeable=False
        self.basis.flags.writeable=False
        self.rank=rank
        self.residual=np.zeros_like(base)
        self.updates=0

    def project(self,x:np.ndarray)->np.ndarray:
        value=np.asarray(x,dtype=np.float64)
        if value.shape[-1]!=self.base.size or not np.isfinite(value).all():
            raise ValueError('invalid feature vector')
        return value-(value@self.basis)@self.basis.T

    def predict(self,x:np.ndarray)->np.ndarray:
        value=np.asarray(x,dtype=np.float64)
        return value@self.base+self.project(value)@self.residual

    def update(self,x:np.ndarray,target:float,learning_rate:float=.05)->None:
        value=np.asarray(x,dtype=np.float64)
        if value.shape!=self.base.shape or not np.isfinite(target) or learning_rate<=0:
            raise ValueError('one finite labeled example and positive learning rate required')
        feature=self.project(value)
        error=float(self.predict(value))-target
        self.residual-=learning_rate*error*feature
        self.updates+=1

    def protected_drift(self)->float:
        if not len(self.anchors):
            return 0.0
        return float(np.max(np.abs(self.predict(self.anchors)-self.anchors@self.base)))
