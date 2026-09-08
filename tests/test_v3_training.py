import numpy as np
import pytest
from witness_cl.versioned_training import OnlineNetwork,ModuleArchive

@pytest.mark.parametrize('seed',range(10))
def test_frozen_modules_and_dispatch_do_not_change(seed):
    n=OnlineNetwork(3,10,seed);a=ModuleArchive()
    rng=np.random.default_rng(seed);x=rng.normal(size=(30,3))
    frozen=n.freeze();key=a.register('schema-v1',frozen);before=a.predict('schema-v1',x).copy()
    for _ in range(50):
        f=rng.normal(size=3);action=int(n.predict(f)>=0)
        n.update_from_feedback(f,action,bool(action==int(f[0]>0)))
    a.register('schema-v2',n.freeze())
    assert np.array_equal(a.predict('schema-v1',x),before)
    assert frozen.key==key
    with pytest.raises(ValueError): frozen.w.setflags(write=True)
    with pytest.raises(ValueError): a.register('schema-v1',n.freeze())
    with pytest.raises(KeyError): a.predict('unknown',x)


def test_learns_from_own_feedback():
    n=OnlineNetwork(2,16,0);rng=np.random.default_rng(0)
    for _ in range(1200):
        x=rng.normal(size=2);a=int(n.predict(x)>=0)
        n.update_from_feedback(x,a,bool(a==int(x.sum()>0)))
    x=rng.normal(size=(1000,2))
    assert np.mean((n.predict(x)>=0)==(x.sum(axis=1)>0))>.95
