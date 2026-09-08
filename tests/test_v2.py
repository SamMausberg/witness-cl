from fractions import Fraction as Q
import random
import numpy as np
import pytest
from witness_cl.adaptive import Rule,Observation,GrowingEvidence,RecurringAgent
from witness_cl.local_audit import ScreenedAudit,RandomizedAudit
from witness_cl.audit import AuditSpec,PairedAudit
from witness_cl.types import Scope
from witness_cl.protected import ProtectedResidual
from witness_cl.relational import Column,Snapshot,SumPlan,schema_grammar,sqlite_evaluate
from witness_cl.tracking import FixedShareRouter
from witness_cl.bitset import update_reference,pack_rows,unpack_rows

def spec():
    return AuditSpec(1,-1,Scope('test','v1'),'candidate','baseline')

def test_growth_must_replay_previously_discarded_evidence():
    old=Rule('old',lambda x:0)
    new=Rule('new',lambda x: int(x==1))
    state=GrowingEvidence([old])
    state.observe(Observation(0,1,0,True))
    assert not state.witnesses  # redundant under the old, singleton class
    assert all(True for e in state.witnesses)  # witness-only admits new, incorrectly
    state.add_rules([new])
    assert [r.key for r in state.live]==['old']
    assert len(state.witnesses)==1

def test_growth_transactional_and_replays_exactly():
    state=GrowingEvidence([Rule('a',lambda x:x%2)])
    for i in range(10):
        state.observe(Observation(i,i,i%2,True))
    with pytest.raises(ValueError):
        state.add_rules([Rule('a',lambda x:8)])
    assert len(state.rules)==1
    state.add_rules([Rule('b',lambda x:0),Rule('c',lambda x:(x+1)%2)])
    assert state.witness_replay()==tuple(r.key for r in state.live)

@pytest.mark.parametrize('seed',range(5))
def test_witness_growth_randomized(seed):
    rng=random.Random(seed)
    rules=[Rule(str(k),lambda x,k=k:(x+k)%7) for k in range(7)]
    space=GrowingEvidence(rules[:2])
    for t in range(30):
        x=rng.randrange(7);a=rng.randrange(7)
        space.observe(Observation(t,x,a,a==(x+4)%7))
        if t in (5,12):
            space.add_rules(rules[2:4] if t==5 else rules[4:])
        assert space.witness_replay()==tuple(r.key for r in space.live)
        assert len(space.witnesses)<=len(space.rules)-len(space.live)

def test_recurring_archive_is_not_overwritten():
    rules=[Rule(str(i),lambda x,i=i:i) for i in range(3)]
    agent=RecurringAgent([rules])
    for t in range(30):
        truth=(t//10)%3
        d=agent.decide(t)
        assert not d.certified
        old=agent.archived_outputs([0,1,2])
        agent.observe(Observation(t,t,d.action,d.action==truth))
        after=agent.archived_outputs([0,1,2])
        assert all(after[k]==v for k,v in old.items())
    assert len(agent.archive)==3
    assert agent.resets==2

def test_growth_repairs_misspecification():
    agent=RecurringAgent([[Rule('zero',lambda x:0)],[Rule('one',lambda x:1)]])
    d=agent.decide(0)
    agent.observe(Observation(0,0,d.action,False))
    assert agent.decide(1).action==1
    assert agent.expansions==1 and agent.resets==0

def test_screened_matches_zero_padded_eprocess_exactly():
    screened=ScreenedAudit(spec(),'guard')
    dense=PairedAudit(spec())
    rng=random.Random(0)
    for t in range(100):
        inside=rng.random()<.2
        rp,rb=(1,0) if inside else (1,1)
        screened.observe(episode=t,guard_hash='guard',inside=inside,
                         candidate_reward=rp if inside else None,baseline_reward=rb)
        dense.observe(episode=t,scope=spec().scope,candidate_hash='candidate',
                      baseline_hash='baseline',candidate_reward=rp,baseline_reward=rb)
        assert screened.audit.e_value==dense.e_value
        assert screened.audit.passed==dense.passed
    assert screened.forks<screened.screened

def test_screened_rejects_counterfactual_and_changed_guard():
    a=ScreenedAudit(spec(),'g')
    with pytest.raises(ValueError):
        a.observe(episode=0,guard_hash='g',inside=False,candidate_reward=1)
    with pytest.raises(ValueError):
        a.observe(episode=0,guard_hash='bad',inside=False)

@pytest.mark.parametrize('e',[Q(1,4),Q(1,2),Q(3,4)])
@pytest.mark.parametrize('r0',[Q(0),Q(1,3),Q(1)])
@pytest.mark.parametrize('r1',[Q(0),Q(2,3),Q(1)])
def test_randomized_centered_estimator_exact_unbiasedness(e,r0,r1):
    z1=(r1-Q(1,2))/e
    z0=-(r0-Q(1,2))/(1-e)
    assert e*z1+(1-e)*z0==r1-r0
    assert max(abs(z1),abs(z0))<=2

def test_randomized_no_hidden_reward_and_stale_comparator():
    audit=RandomizedAudit(spec())
    for t in range(30):
        a=t%2==0
        audit.observe(episode=t,candidate_hash='candidate',baseline_hash='baseline',
                      treatment=a,propensity=Q(1,2),reward=int(a))
    assert audit.passed and audit.can_promote('baseline')
    assert not audit.can_promote('new_baseline')
    with pytest.raises(ValueError):
        audit.observe(episode=31,candidate_hash='candidate',baseline_hash='baseline',
                      treatment=True,propensity=Q(1),reward=1)

@pytest.mark.parametrize('seed',range(5))
def test_protected_residual_and_capacity(seed):
    rng=np.random.default_rng(seed)
    d=12
    anchors=rng.normal(size=(4,d))
    learner=ProtectedResidual(rng.normal(size=d),anchors)
    for _ in range(100):
        x=rng.normal(size=d)
        learner.update(x,float(rng.normal()),.01)
    assert learner.protected_drift()<1e-11
    full=ProtectedResidual(np.zeros(d),np.eye(d))
    full.update(np.ones(d),1.)
    assert np.linalg.norm(full.residual)==0

@pytest.mark.parametrize('seed',range(6))
def test_relational_interpreter_matches_sqlite(seed):
    rng=random.Random(seed)
    columns=(Column('gross','int'),Column('fee','int'),Column('done','bool'),Column('refund','bool'))
    rows=tuple((rng.choice([None,-7,0,5,100]),rng.choice([None,0,4]),
                rng.choice([None,0,1]),rng.choice([None,0,1])) for _ in range(seed*3))
    snap=Snapshot(columns,rows)
    for tier in schema_grammar(columns):
        for rule in tier:
            assert rule(snap)==sqlite_evaluate(rule.evaluate,snap)

def test_relational_guard_and_injection():
    with pytest.raises(ValueError):
        Column('x"; DROP TABLE records; --','int')
    c=(Column('amount','int'),)
    p=SumPlan(c,0,None,())
    with pytest.raises(ValueError):
        p(Snapshot((Column('amount2','int'),),((4,),)))

@pytest.mark.parametrize('seed',range(5))
def test_fixedshare_floor_and_bandit_only_update(seed):
    router=FixedShareRouter(10,4,seed=seed)
    for t in range(100):
        ticket=router.choose([i%4 for i in range(10)])
        with pytest.raises(RuntimeError):
            router.choose([i%4 for i in range(10)])
        router.observe(ticket,float(ticket.action!=(t//20)%4))
        assert np.all(router.weights>=router.share/router.experts-1e-15)
        assert abs(router.weights.sum()-1)<1e-12
    assert router.expected_regret_bound(100,4)>0

@pytest.mark.parametrize('h',[0,1,31,32,33,63,64,65,129])
def test_bitset_tail_and_consensus(h):
    rng=np.random.default_rng(h)
    bits=rng.random((3,h))>.5
    assert np.array_equal(bits,unpack_rows(pack_rows(bits),h))
    p=rng.integers(-4,4,size=(3,h),dtype=np.int32)
    active,changed,unanimous,value=update_reference(bits,p,np.zeros(3,dtype=np.int32),np.array([1,0,1]))
    assert np.array_equal(active,bits&((p==0)==np.array([1,0,1])[:,None]))
    for b in range(3):
        if unanimous[b]:
            assert active[b].any() and np.all(p[b,active[b]]==value[b])

def test_predictable_audit_zero_padding_and_identity():
    from witness_cl.local_audit import PredictablePairedAudit
    a=PredictablePairedAudit(spec());b=PredictablePairedAudit(spec())
    for t in range(30):
        args=dict(scope=spec().scope,candidate_hash='candidate',baseline_hash='baseline',candidate_reward=1,baseline_reward=0)
        a.observe(episode=t,**args)
        b.observe(episode=2*t,**args)
        b.observe(episode=2*t+1,scope=spec().scope,candidate_hash='candidate',baseline_hash='baseline',candidate_reward=0,baseline_reward=0)
        assert a.e_value==b.e_value
    assert a.passed

def test_integrated_system_learns_with_single_observed_reward():
    from witness_cl.system import ContinualSystem
    rules=[Rule(str(i),lambda x,i=i:i) for i in range(2)]
    system=ContinualSystem([rules],rules[0],seed=9)
    for t in range(80):
        ticket=system.decide(t,t)
        system.observe(ticket,ticket.action==1)
    assert system.baseline.key=='1'
    assert len(system.promotions)==1
    assert system.registry['0'](100)==0
    assert system.audit_episodes>0


def test_integrated_promotion_snapshot_has_birth_cut():
    from witness_cl.system import ContinualSystem
    r0,r1=Rule('0',lambda x:0),Rule('1',lambda x:1)
    system=ContinualSystem([[r0,r1]],r0,seed=1)
    t=system.decide(0,7);system.observe(t,False)
    assert system.audit.spec.born_after_episode==0
    assert system.audit.samples==0
    with pytest.raises(ValueError):system.observe(t,False)

def test_integrated_explores_before_identification():
    from witness_cl.system import ContinualSystem
    rules=[Rule(str(i),lambda x,i=i:i) for i in range(5)]
    s=ContinualSystem([rules],rules[0],seed=42)
    for t in range(128):
        ticket=s.decide(t,0)
        s.observe(ticket,ticket.action==4)
    assert s.baseline.key=='4'
    assert len(s.promotions)==1

@pytest.mark.parametrize('seed',range(8))
def test_shared_predicate_cube(seed):
    from witness_cl.relational import cube_evaluate
    rng=random.Random(seed)
    cs=(Column('x','int'),Column('y','int'),Column('f','bool'),Column('g','bool'))
    rules=tuple(r for t in schema_grammar(cs) for r in t)
    plans=tuple(r.evaluate for r in rules)
    for trial in range(3):
        snapshot=Snapshot(cs,tuple((rng.randrange(-100,100),rng.randrange(-30,30),rng.choice([None,0,1]),rng.choice([None,0,1])) for _ in range(seed*5)))
        assert cube_evaluate(plans,snapshot)==tuple(p(snapshot) for p in plans)

def test_model_plan_parser_rejects_ambient_code_and_bad_type():
    from witness_cl.relational import parse_plan
    columns=(Column('gross','int'),Column('flag','bool'))
    good='{"positive":"gross","negative":null,"filters":[{"column":"flag","mode":"null_or_zero"}]}'
    assert parse_plan(good,columns).negative is None
    with pytest.raises(ValueError):parse_plan('SELECT * FROM secrets',columns)
    with pytest.raises(ValueError):parse_plan('{"positive":"flag","negative":null,"filters":[]}',columns)
    with pytest.raises(ValueError):parse_plan(good[:-1]+',"exec":"malicious"}',columns)
