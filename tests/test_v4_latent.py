from itertools import product
from dataclasses import replace
import random
import pytest
import numpy as np
from witness_cl.latent import Machine, Program, LatentSpace, compare, value
from witness_cl.latent_agent import LatentAgent, OnlineProposer


def all_machines(k=2,a=2,o=2):
    for table in product(tuple(product(range(k),range(o))),repeat=k*a):
        yield Machine(k,a,o,table)


def program(word=(0,1,0),o=2):
    return Program.word(word,o)


@pytest.mark.parametrize('seed',range(12))
def test_exact_trace_space_against_independent_enumeration(seed):
    rng=random.Random(seed)
    machines=list(all_machines())
    truth=rng.choice(machines)
    space=LatentSpace(2,2,2)
    traces=[]
    for _ in range(5):
        word=tuple(rng.randrange(2) for _ in range(4))
        trace=truth.run(word)
        traces.append(trace)
        space.observe(trace)
        direct={m for m in machines if all(m.run(tuple(a for a,_ in tr))==tr for tr in traces)}
        assert set(space.completions())==direct
        assert space.contains(truth)


@pytest.mark.parametrize('seed',range(16))
def test_symbolic_comparison_exact_extrema_and_counterexample(seed):
    rng=random.Random(seed)
    truth=rng.choice(list(all_machines()))
    space=LatentSpace(2,2,2)
    for _ in range(2):
        space.observe(truth.run(tuple(rng.randrange(2) for _ in range(3))))
    p=Program(2,tuple(tuple(rng.randrange(2) for _ in range(2**t)) for t in range(3)))
    b=Program(2,tuple(tuple(rng.randrange(2) for _ in range(2**t)) for t in range(3)))
    rewards=(-2,3)
    deltas=[value(m,p,rewards)-value(m,b,rewards) for m in space.completions()]
    for closure in (False,True):
        c=compare(space,p,b,rewards,close_suffixes=closure,max_nodes=1000000)
        assert c.status=='exact'
        assert (c.lower,c.upper)==(min(deltas),max(deltas))
        assert space.contains(c.witness)
        assert value(c.witness,p,rewards)-value(c.witness,b,rewards)==c.lower


def test_closed_suffix_skips_unread_edges_without_changing_result():
    s=LatentSpace(3,2,2)
    p=program((0,1,0,1,0))
    c=compare(s,p,p,(-1,1))
    assert c.status=='exact' and c.lower==c.upper==0
    assert c.nodes==1 and c.closed_suffixes==1
    assert compare(s,p,p,(-1,1),close_suffixes=False,max_nodes=1).status=='unknown'


def test_exhaustion_and_empty_class_never_certify():
    s=LatentSpace(2,2,2)
    assert compare(s,program((1,1,1)),program(),(-1,1),max_nodes=1).status=='unknown'
    s=LatentSpace(1,2,2)
    s.observe(((0,0),(0,1)))
    c=compare(s,program(),program(),(-1,1))
    assert c.status=='inconsistent' and not c.admits


def test_frontier_cap_records_raw_evidence_without_truncation_certificate():
    s=LatentSpace(2,2,2,max_partials=1)
    s.observe(((0,0),))
    assert len(s.history)==1 and not s.complete
    assert compare(s,program(),program(),(-1,1)).status=='unknown'
    with pytest.raises(RuntimeError):list(s.completions())


def test_expansion_replays_every_old_trace():
    s=LatentSpace(1,2,2)
    trace=((0,0),(0,1),(0,0))
    s.observe(trace)
    assert not s.partials
    s.expand(2)
    assert s.partials and s.history==[trace]
    assert all(m.run((0,0,0))==trace for m in s.completions())


def test_identical_current_outputs_do_not_justify_hidden_state_merge():
    m=Machine(2,2,2,((1,0),(0,0),(1,1),(0,0)))
    assert m.run((0,))[0][1]==m.run((1,))[0][1]
    assert m.run((0,0))[-1][1]!=m.run((1,0))[-1][1]
    s=LatentSpace(2,2,2)
    s.observe(m.run((0,0)))
    s.observe(m.run((1,0)))
    c=compare(s,program((1,0)),program((0,0)),(0,1))
    assert c.lower==c.upper==-1 and not c.admits


def test_wrong_state_bound_can_certify_wrongly_before_contradiction():
    # Under one state, observing 0->1 predicts repeated reward. Actual second step differs.
    true=Machine(2,2,2,((1,1),(0,0),(1,0),(0,0)))
    s=LatentSpace(1,2,2)
    s.observe(true.run((0,)))
    s.observe(true.run((1,)))
    c=compare(s,program((0,0)),program((1,0)),(0,1))
    assert c.admits and c.lower==1
    assert value(true,program((0,0)),(0,1))==value(true,program((1,0)),(0,1))
    # More severe example: 0 then 0 accumulates 1+(-2), while 1 then 0 earns 0+1.
    true3=Machine(2,2,3,((1,1),(0,0),(1,2),(0,0)))
    s3=LatentSpace(1,2,3)
    s3.observe(true3.run((0,)));s3.observe(true3.run((1,)))
    c3=compare(s3,program((0,0),3),program((1,0),3),(0,1,-2))
    assert c3.admits and value(true3,program((0,0),3),(0,1,-2)) < value(true3,program((1,0),3),(0,1,-2))


@pytest.mark.parametrize('seed',range(10))
def test_integrated_own_feedback_retention_and_budget(seed):
    rng=random.Random(seed)
    m=rng.choice(list(all_machines()))
    programs=tuple(program(word) for word in product(range(2),repeat=3))
    goals=((0,2),(2,0))
    a=LatentAgent(LatentSpace(2,2,2),programs,goals,budget=12,seed=seed)
    previous=[value(m,programs[0],r) for r in goals]
    deficit=0
    for n in range(20):
        g=n%2
        t=a.choose(g)
        current=[value(m,programs[j],r) for j,r in zip(a.incumbents,goals)]
        assert all(x>=y for x,y in zip(current,previous))
        previous=current
        reward=value(m,programs[t.program],goals[g])
        deficit+=value(m,programs[0],goals[g])-reward
        assert deficit<=a.spent<=12
        a.observe(t,programs[t.program].rollout(m))
        assert a.space.contains(m)
    assert a.proposer.updates==20


def test_feedback_tickets_and_expansion_invalidate_old_obligations():
    ps=(program((0,0)),program((1,1)))
    a=LatentAgent(LatentSpace(1,2,2),ps,((0,1),),budget=4)
    t=a.choose(0)
    with pytest.raises(RuntimeError):a.choose(0)
    with pytest.raises(ValueError):a.observe(replace(t),((0,0),(0,0)))
    with pytest.raises(ValueError):a.observe(t,((1,0),))
    trace=((ps[t.program].levels[0][0],0),(ps[t.program].levels[1][0],0))
    a.observe(t,trace)
    with pytest.raises(ValueError):a.observe(t,trace)
    a.expand(2)
    assert a.incumbents==[0] and a.era==1 and len(a.space.history)==1


def test_proposer_gradient_finite_difference_and_one_chosen_label():
    ps=(program((0,0)),program((1,1)))
    p=OnlineProposer(ps,((0,1),),2,seed=8,lr=.01)
    x=p.features[0,1]
    target=.5
    def loss():
        return .5*(np.tanh(x@p.w1+p.b1)@p.w2+p.b2-target)**2
    before=p.w1.copy();old=p.w1[0,0];eps=1e-5
    p.w1[0,0]=old+eps;lplus=loss()
    p.w1[0,0]=old-eps;lminus=loss()
    p.w1[0,0]=old
    numerical=(lplus-lminus)/(2*eps)
    p.observe(0,1,1)
    assert abs((before[0,0]-p.w1[0,0])/.01-numerical)<1e-8
    assert p.visits.tolist()==[[0,1]] and p.updates==1


@pytest.mark.parametrize('bad',[(0,2,2),(-1,2,2),(True,2,2)])
def test_invalid_dimensions(bad):
    with pytest.raises(ValueError):LatentSpace(*bad)


@pytest.mark.parametrize('seed',range(8))
def test_possible_observation_traces_not_latent_label_counts(seed):
    from witness_cl.latent import possible_traces
    rng=random.Random(seed);s=LatentSpace(2,2,2)
    truth=rng.choice(list(all_machines()))
    s.observe(truth.run((0,1)))
    p=program(tuple(rng.randrange(2) for _ in range(3)))
    exact={p.rollout(m) for m in s.completions()}
    result=possible_traces(s,p)
    assert result.status=='exact' and set(result.traces)==exact
    for trace in result.traces:
        before=set(s.completions())
        new=LatentSpace(2,2,2)
        for tr in s.history:new.observe(tr)
        new.observe(trace)
        if len(result.traces)>1:assert set(new.completions())<before


def test_outcome_search_exhaustion_has_no_usable_count():
    from witness_cl.latent import possible_traces
    result=possible_traces(LatentSpace(2,2,2),program(),max_nodes=1)
    assert result.status=='unknown' and not result.traces


@pytest.mark.parametrize('seed',range(10))
def test_residual_ids_exactly_match_structural_suffixes(seed):
    from witness_cl.latent import residual_ids
    rng=random.Random(seed)
    p=Program(2,tuple(tuple(rng.randrange(2) for _ in range(2**t)) for t in range(4)))
    b=Program(2,tuple(tuple(rng.randrange(2) for _ in range(2**t)) for t in range(4)))
    c,d=residual_ids(p,b)
    for t in range(4):
        for i in range(2**t):
            for j in range(2**t):
                assert (c[t][i]==d[t][j])==(p.suffix(t,i)==b.suffix(t,j))
