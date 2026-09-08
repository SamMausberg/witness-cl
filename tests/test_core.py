import random
import pytest
from witness_cl.core import VersionSpace, WitnessAgent
from witness_cl.programs import affine_class, AffineMod
from witness_cl.types import Scope, Feedback
from witness_cl.baselines import FullReplayInduction

@pytest.mark.parametrize("modulus", [2, 3, 5, 7])
def test_truth_never_eliminated_and_certificates_correct(modulus):
    programs = affine_class(modulus)
    scope = Scope("public-device")
    for truth in programs:
        vs = VersionSpace(programs)
        for t in range(3 * modulus * modulus):
            x = (3*t + t//modulus) % modulus
            action = vs.majority(x)
            before = {q: vs.consensus(q) for q in range(modulus)}
            vs.observe(Feedback(t, scope, x, action, action == truth(x)))
            assert truth in vs.live
            for q in range(modulus):
                answer = vs.consensus(q)
                if answer is not None:
                    assert answer == truth(q)
                if before[q] is not None:
                    assert answer == before[q]

@pytest.mark.parametrize("seed", range(8))
def test_full_replay_has_identical_actions(seed):
    rng = random.Random(seed)
    programs = affine_class(7)
    truth = [rng.choice(programs) for _ in range(3)]
    agent, replay = WitnessAgent(programs), FullReplayInduction(programs)
    for t in range(180):
        k, x = rng.randrange(3), rng.randrange(7)
        scope = Scope(str(k))
        a, b = agent.decide(scope, x), replay.decide(scope, x)
        assert (a.action, a.certified) == (b.action, b.certified)
        event = Feedback(t, scope, x, a.action, a.action == truth[k](x))
        agent.observe(event)
        replay.observe(event)

def test_two_successes_identify_affine_map_and_transfer():
    agent = WitnessAgent(affine_class(7))
    scope = Scope("repository-A")
    truth = AffineMod(3, 2, 7)
    for t, x in enumerate([0, 1]):
        agent.observe(Feedback(t, scope, x, truth(x), True))
    assert len(agent.space(scope).live) == 1
    for x in range(2, 7):
        result = agent.decide(scope, x)
        assert result.certified and result.action == truth(x)

def test_other_scope_update_is_exactly_noninterfering():
    agent = WitnessAgent(affine_class(7))
    a, b = Scope("A"), Scope("B")
    for t, x in enumerate([0, 1]):
        agent.observe(Feedback(t, a, x, (2*x+1)%7, True))
    decision = agent.decide(a, 5)
    state, cert = agent.space(a).live, agent.certificate(a, 5)
    for t in range(2, 40):
        x = t%7
        agent.observe(Feedback(t, b, x, (3*x+4)%7, True))
    assert agent.space(a).live == state
    assert agent.certificate(a, 5) == cert
    assert agent.decide(a, 5).action == decision.action

def test_empty_class_is_quarantined_not_vacuously_certified():
    agent = WitnessAgent(affine_class(3))
    scope = Scope("one")
    agent.observe(Feedback(0, scope, 0, 0, True))
    agent.observe(Feedback(1, scope, 0, 1, True))
    assert agent.space(scope).quarantined
    assert not agent.decide(scope, 0).certified
    agent.observe(Feedback(2, scope, 0, 0, True))
    assert not agent.decide(scope, 0).certified

def test_duplicate_episode_rejected():
    agent = WitnessAgent(affine_class(3))
    e = Feedback(0, Scope("one"), 0, 0, True)
    agent.observe(e)
    with pytest.raises(ValueError):
        agent.observe(e)

def test_hidden_shift_can_break_certificate_before_detection():
    agent = WitnessAgent(affine_class(7))
    scope = Scope("same-public-version")
    for t, x in enumerate([0,1]):
        agent.observe(Feedback(t, scope, x, x, True))
    # A formerly correct identity contract is NOT protected against hidden drift.
    d = agent.decide(scope, 4)
    new_truth = lambda x: (x+1)%7
    assert d.certified and d.action != new_truth(4)
    agent.observe(Feedback(2, scope, 4, d.action, False))
    assert agent.space(scope).quarantined
    assert not agent.decide(scope, 4).certified

def test_public_new_version_does_not_reuse_old_certificate():
    agent = WitnessAgent(affine_class(7))
    old, new = Scope("same", "1"), Scope("same", "2")
    for t, x in enumerate([0,1]):
        agent.observe(Feedback(t, old, x, x, True))
    assert agent.decide(old, 3).certified
    assert not agent.decide(new, 3).certified

def test_misspecification_can_pass_observations_then_fail():
    agent = WitnessAgent(affine_class(7))
    scope = Scope("nonlinear")
    for t, x in enumerate([0, 1]):
        agent.observe(Feedback(t, scope, x, x*x%7, True))
    d = agent.decide(scope, 2)
    assert d.certified and d.action != 4
    # This intentional counterexample is why the theorem explicitly requires realizability.

def test_revoke_scope_fails_closed():
    agent = WitnessAgent(affine_class(3))
    scope = Scope("A")
    for t,x in enumerate([0,1]):
        agent.observe(Feedback(t, scope, x, x, True))
    assert agent.decide(scope, 2).certified
    agent.revoke_scope(scope)
    assert not agent.decide(scope, 2).certified

@pytest.mark.parametrize("seed", range(8))
def test_witness_subset_reconstructs_full_history_and_size_bound(seed):
    rng = random.Random(seed)
    programs = affine_class(7)
    vs = VersionSpace(programs)
    truth = rng.choice(programs)
    full = []
    scope = Scope("compress")
    for t in range(100):
        x, a = rng.randrange(7), rng.randrange(7)
        fb = Feedback(t, scope, x, a, a == truth(x))
        full.append(fb)
        vs.observe(fb)
        expected = tuple(p for p in programs if all(
            ((p(e.x) == e.action) == e.success) for e in full))
        assert vs.live == expected == vs.reconstruct_from_witnesses()
        assert len(vs.witnesses) <= len(programs) - len(vs.live)
        assert len(vs.witnesses) <= len(programs) - 1


def test_witness_compression_also_reconstructs_contradiction():
    vs = VersionSpace(affine_class(3))
    scope = Scope("contradiction")
    vs.observe(Feedback(0, scope, 0, 0, True))
    vs.observe(Feedback(1, scope, 0, 1, True))
    assert vs.live == vs.reconstruct_from_witnesses() == ()
    assert len(vs.witnesses) <= 9


def test_large_window_replay_matches_full():
    from witness_cl.baselines import WindowReplayInduction
    a, b = FullReplayInduction(affine_class(3)), WindowReplayInduction(affine_class(3),100)
    scope = Scope("window")
    for t in range(30):
        da, db = a.decide(scope,t%3), b.decide(scope,t%3)
        assert da.action == db.action
        fb = Feedback(t,scope,t%3,da.action,da.action==(2*t+1)%3)
        a.observe(fb); b.observe(fb)
