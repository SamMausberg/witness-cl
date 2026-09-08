import pytest
import numpy as np
from witness_cl.continuation import Model,Policy,value
from witness_cl.vector_contract import packed_advantages

@pytest.mark.parametrize('seed',range(20))
def test_exact_scalar_vector_parity(seed):
    rng=np.random.default_rng(seed);H,S,A=5,7,3
    models=tuple(Model(rng.integers(0,S,(H,S,A)).tolist(),rng.integers(-9,20,(H,S,A)).tolist()) for _ in range(8))
    base=Policy(rng.integers(0,A,(H,S)).tolist())
    v,lower=packed_advantages(models,base)
    assert all(v[i].tolist()==[list(row) for row in value(m,base)] for i,m in enumerate(models))
    for t in range(H):
        for s in range(S):
            for a in range(A):
                expected=min(m.reward[t][s][a]+int(v[i,t+1,m.next_state[t][s][a]])-int(v[i,t,s]) for i,m in enumerate(models))
                assert int(lower[t,s,a])==expected


def test_overflow_refused():
    m=Model([[[0]]],[[[2**63-1]]])
    with pytest.raises(OverflowError): packed_advantages((m,),Policy(((0,),)))
    assert value(m,Policy(((0,),)))[0][0]==2**63-1
