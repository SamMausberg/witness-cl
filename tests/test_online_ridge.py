import pytest
np=pytest.importorskip("numpy")
from witness_cl.online_ridge import OnlineRidge

def test_online_updates_equal_regularized_batch_solution():
    rng=np.random.default_rng(13)
    x=rng.normal(size=(50,5)); y=rng.normal(size=50)
    learner=OnlineRidge(5,regularization=2.0)
    for xi,yi in zip(x,y): learner.observe(xi,target=float(yi))
    expected=np.linalg.solve(x.T@x+2*np.eye(5),x.T@y)
    np.testing.assert_allclose(learner.weights,expected,rtol=1e-10,atol=1e-10)

def test_distinct_online_modules_do_not_interfere():
    a,b=OnlineRidge(3),OnlineRidge(3)
    a.observe([1,2,3],target=1)
    frozen=a.weights.copy()
    for t in range(10): b.observe([1,t,1],target=float(t))
    np.testing.assert_array_equal(a.weights,frozen)

def test_binary_failure_does_not_invent_a_label():
    with pytest.raises(ValueError): OnlineRidge(2).observe([1,1],target=None)
