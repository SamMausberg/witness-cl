import json
import pytest
from witness_cl.ledger import Ledger
from witness_cl.types import Scope, Feedback
from witness_cl.programs import AffineMod, affine_class
from witness_cl.core import WitnessAgent

@pytest.mark.parametrize("payload", [
    {"op":"shell","cmd":"echo not-executed"},
    {"op":"affine_mod","a":1,"b":0,"modulus":7,"import":"os"},
    {"op":"affine_mod","a":True,"b":0,"modulus":7},
    {"op":"affine_mod","a":1,"b":0,"modulus":1},
    {"op":"affine_mod","a":"__import__('os')","b":0,"modulus":7},
])
def test_dsl_rejects_nonlanguage_programs(payload):
    with pytest.raises((ValueError,TypeError)):
        AffineMod.parse(payload)

def test_dsl_roundtrip():
    p=AffineMod(2,3,7)
    assert AffineMod.parse(p.to_json()) == p

def test_evidence_roundtrip_rebuilds_learner(tmp_path):
    log=Ledger(tmp_path/"events.jsonl")
    agent=WitnessAgent(affine_class(7))
    scope=Scope("repo")
    for t,x in enumerate([0,1]):
        e=Feedback(t,scope,x,(3*x+2)%7,True)
        agent.observe(e); log.append(e)
    loaded=Ledger(log.path)
    assert loaded.check_head(log.head)
    restored=WitnessAgent(affine_class(7))
    for e in loaded.events: restored.observe(e)
    for x in range(7):
        a,b=agent.decide(scope,x),restored.decide(scope,x)
        assert (a.action,a.certified)==(b.action,b.certified)

def test_log_detects_partial_tampering(tmp_path):
    path=tmp_path/"events.jsonl"
    log=Ledger(path)
    log.append(Feedback(0,Scope("s"),0,0,True))
    row=json.loads(path.read_text()); row["event"]["success"]=False
    path.write_text(json.dumps(row)+"\n")
    with pytest.raises(ValueError): Ledger(path)

def test_wrong_trusted_head_rejected(tmp_path):
    log=Ledger(tmp_path/"events.jsonl")
    assert not log.check_head("attacker-head")

def test_no_untrusted_string_feedback():
    with pytest.raises(TypeError): Feedback(0,Scope("s"),0,0,"True")
