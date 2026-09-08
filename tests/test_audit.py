from fractions import Fraction as Q
from itertools import product
import pytest
from witness_cl.audit import AuditSpec, PairedAudit
from witness_cl.types import Scope

S = Scope("frozen-scope")
def audit():
    return PairedAudit(AuditSpec(1, 4, S, "candidate-v1", "baseline-v1"))
def add(a, t, d):
    a.observe(episode=t, scope=S, candidate_hash="candidate-v1", baseline_hash="baseline-v1",
              candidate_reward=max(d, 0), baseline_reward=max(-d, 0))

def test_positive_fresh_evidence_passes():
    a = audit()
    for t in range(5, 20):
        add(a, t, 1)
    assert a.passed and a.e_value >= 1/a.spec.allocated_delta

def test_ties_are_not_evidence_of_positive_gain():
    a = audit()
    for t in range(5, 50):
        add(a, t, 0)
    assert a.e_value == 1 and not a.passed

def test_losses_do_not_pass():
    a = audit()
    for t in range(5, 30):
        add(a, t, -1)
    assert not a.passed and a.e_value < 1

def test_proposal_episode_is_not_an_audit_case():
    with pytest.raises(ValueError):
        add(audit(), 4, 1)

def test_duplicate_audit_case_rejected():
    a = audit()
    add(a, 5, 1)
    with pytest.raises(ValueError):
        add(a, 5, 1)

@pytest.mark.parametrize("field,value", [("scope",Scope("different")),
    ("candidate_hash","candidate-v2"),("baseline_hash","baseline-v2")])
def test_changed_system_invalidates_comparison(field,value):
    kwargs=dict(episode=5, scope=S, candidate_hash="candidate-v1",baseline_hash="baseline-v1",
                candidate_reward=1,baseline_reward=0)
    kwargs[field]=value
    with pytest.raises(ValueError):
        audit().observe(**kwargs)

def test_invalidated_audit_cannot_keep_admission():
    a=audit()
    for t in range(5,20): add(a,t,1)
    a.invalidate()
    assert not a.passed
    with pytest.raises(ValueError): add(a,20,1)

def test_rational_reference_rejects_float_rewards():
    with pytest.raises(TypeError):
        audit().observe(episode=5,scope=S,candidate_hash="candidate-v1",baseline_hash="baseline-v1",
                        candidate_reward=0.7,baseline_reward=0.2)

def test_global_failure_allocation_has_bounded_partial_sum():
    total=sum((AuditSpec(j,0,S,"p","b").allocated_delta for j in range(1,101)), Q(0))
    assert total == Q(1,20)*Q(100,101)

def test_exhaustive_fair_coin_null_optional_stopping_small_horizon():
    # A finite exhaustive check, NOT a proof of the unbounded-time theorem.
    crossings=0
    for outcomes in product([-1,1], repeat=10):
        a=audit()
        for t,d in enumerate(outcomes,5): add(a,t,d)
        crossings += a.passed
    assert Q(crossings,2**10) <= audit().spec.allocated_delta

def test_hoeffding_zero_samples():
    assert audit().hoeffding_lcb() == -1


def test_stale_incumbent_cannot_be_promoted_against():
    spec=AuditSpec(index=1,born_after_episode=-1,scope=Scope("A"),candidate_hash="c",baseline_hash="b")
    audit=PairedAudit(spec)
    for t in range(30):
        audit.observe(episode=t,scope=spec.scope,candidate_hash="c",baseline_hash="b",candidate_reward=1,baseline_reward=0)
    assert audit.can_promote(scope=spec.scope,candidate_hash="c",current_baseline_hash="b")
    assert not audit.can_promote(scope=spec.scope,candidate_hash="c",current_baseline_hash="new-b")
