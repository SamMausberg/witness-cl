from fractions import Fraction as Q
import random
import pytest
from witness_cl.continuation import (Model,Policy,ModelBank,ContractAgent,Transition,
    value,optimal,rollout,improve,certify)
from witness_cl.coupling import coupled,independent,closed_contract
from witness_cl.likelihood import LikelihoodBank


def random_model(seed,H=4,S=4,A=3):
    rng=random.Random(seed)
    ns=tuple(tuple(tuple(rng.randrange(S) for _ in range(A)) for _ in range(S)) for _ in range(H))
    rw=tuple(tuple(tuple(rng.randrange(-3,8) for _ in range(A)) for _ in range(S)) for _ in range(H))
    return Model(ns,rw)

@pytest.mark.parametrize('seed',range(30))
def test_full_horizon_improvement(seed):
    ms=[random_model(seed*3+i) for i in range(3)]
    base=Policy(((0,)*4,)*4)
    bank=ModelBank(ms)
    c,cert=improve(bank,base)
    cert.validate(bank,base,c)
    for m in ms:
        assert all(y>=x for vx,vy in zip(value(m,base),value(m,c)) for x,y in zip(vx,vy))
        assert all(y>=x for vx,vy in zip(value(m,c),value(m,optimal(m))) for x,y in zip(vx,vy))

@pytest.mark.parametrize('seed',range(30))
def test_realized_regret_budget_every_prefix(seed):
    ms=[random_model(seed*4+i,H=3,S=3,A=2) for i in range(4)]
    base=Policy(((0,)*3,)*3)
    agent=ContractAgent(ms,base,budget=20)
    truth=ms[seed%4]
    regret=0
    previous=base
    for t in range(12):
        state=(t+seed)%3
        choice=agent.choose(t,state)
        assert all(y>=x for vx,vy in zip(value(truth,previous),value(truth,choice.incumbent)) for x,y in zip(vx,vy))
        previous=choice.incumbent
        events=rollout(truth,choice.policy,state,t)
        regret+=value(truth,base)[0][state]-sum(e.reward for e in events)
        assert regret<=agent.spent<=20
        agent.observe(choice,events)
        assert truth in agent.bank.live
        assert all(y>=x for vx,vy in zip(value(truth,base),value(truth,choice.incumbent)) for x,y in zip(vx,vy))


def test_delayed_harm_rejected_despite_immediate_gain():
    m=Model((((0,1),(1,1)),((0,0),(1,1))),(((0,5),(0,0)),((10,10),(0,0))))
    base=Policy(((0,0),(0,0)))
    bad=Policy(((1,0),(0,0)))
    assert m.reward[0][0][1]>m.reward[0][0][0]
    assert value(m,bad)[0][0]<value(m,base)[0][0]
    with pytest.raises(ValueError):
        certify(ModelBank([m]),base,bad)


def test_growth_invalidates_certificate_and_replays_discarded_history():
    m=Model((((0,0),),),(((1,2),),))
    other=Model((((0,0),),),(((1,0),),))
    base=Policy(((0,),))
    bank=ModelBank([m])
    bank.observe(rollout(m,base,0,0))
    c,cert=improve(bank,base)
    assert c.actions==((1,),)
    bank.add([other])
    with pytest.raises(ValueError):
        cert.validate(bank,base,c)
    with pytest.raises(ValueError):
        certify(bank,base,c)
    incompatible=Model((((0,0),),),(((9,2),),))
    bank.add([incompatible])
    assert incompatible not in bank.live


def test_empty_bank_not_vacuously_safe():
    m=random_model(3)
    b=Policy(((0,)*4,)*4)
    bank=ModelBank([m])
    bank.observe([Transition(0,0,0,0,999,0)])
    with pytest.raises(ValueError):
        improve(bank,b)


def test_budget_zero_can_prevent_all_learning():
    good=Model((((0,0),),),(((5,10),),))
    bad=Model((((0,0),),),(((5,0),),))
    agent=ContractAgent([good,bad],Policy(((0,),)),0)
    for t in range(10):
        choice=agent.choose(t,0)
        assert choice.policy.actions==((0,),)
        agent.observe(choice,rollout(good,choice.policy,0,t))
    assert len(agent.bank.live)==2
    # Explicit risk allowance enables identification, then zero-debit improvement.
    agent=ContractAgent([good,bad],Policy(((0,),)),5)
    choice=agent.choose(0,0)
    assert choice.policy.actions==((1,),) and choice.debit==5
    agent.observe(choice,rollout(good,choice.policy,0,0))
    choice=agent.choose(1,0)
    assert choice.policy.actions==((1,),) and choice.debit==0


def test_atomic_rejection_and_immutable_inputs():
    ns=[[[0,0]]]; rw=[[[1,2]]]
    m=Model(ns,rw); ns[0][0][0]=999; rw[0][0][0]=999
    assert m.next_state[0][0][0]==0 and m.reward[0][0][0]==1
    bank=ModelBank([m])
    with pytest.raises(ValueError):
        bank.observe([Transition(0,0,0,0,1,0),Transition(0,0,0,0,1,0)])
    assert not bank.history and bank.generation==0
    with pytest.raises(ValueError):
        bank.add([m])
    assert bank.models==(m,)


def test_foreign_ticket_and_mid_episode_expansion():
    m=random_model(5)
    b=Policy(((0,)*4,)*4)
    a=ContractAgent([m],b,0)
    ticket=a.choose(0,0)
    with pytest.raises(ValueError): a.choose(1,0)
    seq=rollout(m,ticket.policy,0,0)
    with pytest.raises(ValueError): a.observe(ticket,seq[:-1])
    a.bank.add([random_model(6)])
    with pytest.raises(ValueError): a.observe(ticket,seq)


def test_hidden_controller_memory_not_discarded():
    def env(s,a,u): return s+int(a),int(a)
    def base(s,m,t): return (0,0)
    def candidate(s,m,t): return (int(m>0),m+1)
    tape=(0,)*6
    result=coupled(env,base,candidate,0,0,0,tape)
    assert result.baseline==independent(env,base,0,0,tape)
    assert result.candidate==independent(env,candidate,0,0,tape)
    assert result.shared_transitions==1 and result.first_divergence==1
    assert result.environment_calls==11 and result.controller_calls==12

@pytest.mark.parametrize('seed',range(20))
def test_coupling_independent_parity(seed):
    rng=random.Random(seed)
    tape=tuple(rng.randrange(3) for _ in range(30))
    def env(s,a,u): return ((s+a+u)%7,(s*a+u)%5)
    def base(s,m,t): return ((s+m)%3,(m+1)%4)
    def cand(s,m,t): return ((s+m+(t%5==0))%3,(m+2)%4)
    result=coupled(env,base,cand,0,0,0,tape)
    assert result.baseline==independent(env,base,0,0,tape)
    assert result.candidate==independent(env,cand,0,0,tape)
    assert result.environment_calls==60-result.shared_transitions


def test_closed_protected_domain_not_just_local_agreement():
    base=lambda s,u: ((s+1)%3,0)
    cand=lambda s,u: ((s+1)%3,int(s==2))
    assert not closed_contract([0],[0],base,cand) # Same now, not closed.
    assert not closed_contract([0,1,2],[0],base,cand)
    assert closed_contract([0,1,2],[0],base,base)
    with pytest.raises(ValueError): closed_contract([],[0],base,base)


def test_likelihood_noise_does_not_hard_eliminate():
    b=LikelihoodBank([Q(1,2),Q(1,2)],Q(1,20))
    for outcome in [1,1,0,1,1,1,0,1]*8:
        b.observe_probabilities([Q(9,10) if outcome else Q(1,10),Q(1,10) if outcome else Q(9,10)])
    assert b.live==(0,)
    assert b.likelihood[0]>0 and b.likelihood[1]>0


def test_likelihood_fixed_horizon_evalue_expectation_exact():
    # Enumerate all binary histories; E_true[Lmix/Ltrue] = 1 exactly.
    import itertools
    total=Q(0)
    for xs in itertools.product([0,1],repeat=6):
        b=LikelihoodBank([Q(1,3),Q(2,3)])
        prob=Q(1)
        for x in xs:
            p=Q(3,4) if x else Q(1,4)
            prob*=p
            b.observe_probabilities([p,Q(1,4) if x else Q(3,4)])
        total+=prob*b.ratio(0)
    assert total==1


def test_likelihood_atomic_validation():
    b=LikelihoodBank([Q(1,2),Q(1,2)])
    for p in [[Q(0),Q(0)],[Q(2),Q(0)],[Q(1)]]:
        with pytest.raises(ValueError): b.observe_probabilities(p)
    assert b.steps==0 and b.likelihood==(1,1)


def test_hidden_drift_can_harm_before_detection():
    good=Model((((0,0),),),(((5,10),),))
    bad=Model((((0,0),),),(((5,0),),))
    agent=ContractAgent([good,bad],Policy(((0,),)),5)
    c=agent.choose(0,0);agent.observe(c,rollout(good,c.policy,0,0))
    assert bad not in agent.bank.live
    c=agent.choose(1,0)
    assert c.debit==0 and c.policy.actions==((1,),)
    events=rollout(bad,c.policy,0,1)
    assert sum(e.reward for e in events)<value(bad,agent.anchor)[0][0]
    agent.observe(c,events)
    assert not agent.bank.live
    with pytest.raises(ValueError): agent.choose(2,0)


def test_average_gain_does_not_protect_a_subgroup():
    m=Model((((0,0),(1,1)),),(((5,0),(5,20)),))
    base=Policy(((0,0),));c=Policy(((1,1),))
    assert sum(value(m,c)[0])>sum(value(m,base)[0])
    assert value(m,c)[0][0]<value(m,base)[0][0]
    with pytest.raises(ValueError): certify(ModelBank([m]),base,c)
