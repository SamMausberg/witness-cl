"""Integer-only CPU oracle for the planned CUDA evidence/consensus kernel."""
from __future__ import annotations
import numpy as np

def update_reference(live:np.ndarray,predictions:np.ndarray,actions:np.ndarray,
                     success:np.ndarray)->tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
    live=np.asarray(live,dtype=bool)
    preds=np.asarray(predictions)
    actions=np.asarray(actions)
    success=np.asarray(success,dtype=bool)
    if live.ndim!=2 or preds.shape!=live.shape or actions.shape!=(live.shape[0],) or success.shape!=actions.shape:
        raise ValueError('expected live/predictions [B,H], actions/success [B]')
    if not np.issubdtype(preds.dtype,np.integer) or not np.issubdtype(actions.dtype,np.integer):
        raise ValueError('integer outputs required')
    active=live & ((preds==actions[:,None])==success[:,None])
    counts=active.sum(axis=1)
    changed=np.any(active!=live,axis=1)
    consensus=np.zeros(live.shape[0],dtype=np.int64)
    unanimous=np.zeros(live.shape[0],dtype=bool)
    for b in range(live.shape[0]):
        ys=preds[b,active[b]]
        if len(ys) and np.all(ys==ys[0]):
            unanimous[b]=True
            consensus[b]=ys[0]
    # Zero in consensus is never meaningful unless unanimous[b] is true.
    return active,changed,unanimous,consensus

def pack_rows(bits:np.ndarray)->np.ndarray:
    bits=np.asarray(bits,dtype=bool)
    if bits.ndim!=2:
        raise ValueError('matrix required')
    b,h=bits.shape
    packed=np.zeros((b,(h+31)//32),dtype=np.uint32)
    for j in range(h):
        packed[:,j//32]|=bits[:,j].astype(np.uint32)<<np.uint32(j%32)
    return packed

def unpack_rows(packed:np.ndarray,hypotheses:int)->np.ndarray:
    packed=np.asarray(packed,dtype=np.uint32)
    if hypotheses<0 or packed.ndim!=2 or packed.shape[1]!=(hypotheses+31)//32:
        raise ValueError('invalid packed matrix')
    return np.stack([((packed[:,j//32]>>np.uint32(j%32))&1).astype(bool)
                     for j in range(hypotheses)],axis=1) if hypotheses else np.empty((len(packed),0),bool)
