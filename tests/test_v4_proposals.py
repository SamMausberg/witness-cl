import json
import numpy as np
import pytest
from witness_cl.latent import Program,LatentSpace,Machine
from witness_cl.latent_agent import LatentAgent
from witness_cl.latent_proposals import parse_program

@pytest.mark.parametrize('text',[
    '{"word":[0,1]}','{"levels":[[0],[1,0]]}'
])
def test_valid_untrusted_proposals(text):
    p=parse_program(text,actions=2,outputs=2,horizon=2)
    assert isinstance(p,Program)

@pytest.mark.parametrize('text',[
    '{"word":[0,1],"certified":true}', '{"word":[true,1]}', '{"word":[0,2]}',
    '{"word":[0,-1]}','{"word":[0]}','{"word":[0,1],"word":[1,0]}',
    '{"levels":[[0],[1]]}','[0,1]','__import__("os").system("anything")',
    '{"code":"return 0"}', '{"word":[0,1],"levels":[[0],[0,0]]}',
    '{"word":[0.0,1]}'
])
def test_reject_untrusted_programs(text):
    with pytest.raises(ValueError):parse_program(text,actions=2,outputs=2,horizon=2)


def test_new_program_preserves_incumbent_ids_scores_and_evidence():
    a=LatentAgent(LatentSpace(2,2,2),(Program.word((0,0),2),),((0,1),))
    t=a.choose(0);m=Machine(2,2,2,((0,1),(1,0),(1,0),(0,1)))
    a.observe(t,a.programs[t.program].rollout(m))
    weights=a.proposer.w1.copy();scores=a.proposer.scores(0).copy();partials=a.space.partials
    old_history=tuple(a.space.history);g=a.space.generation
    assert a.register(Program.word((1,0),2))==1
    np.testing.assert_array_equal(a.proposer.w1,weights)
    # Batched BLAS shapes can change rounding; proposal scores are not a bitwise contract.
    np.testing.assert_allclose(a.proposer.scores(0)[:1],scores,rtol=0,atol=1e-14)
    assert a.incumbents==[0] and a.space.partials==partials and tuple(a.space.history)==old_history and a.space.generation==g
    assert a.register(Program.word((1,0),2))==1


def test_contradictory_feedback_forces_anchor_not_latest_patch():
    a=LatentAgent(LatentSpace(1,2,2),(Program.word((0,0),2),Program.word((1,1),2)),((0,1),))
    a.incumbents[0]=1
    a.space.observe(((0,0),(0,1)))
    t=a.choose(0)
    assert t.program==0 and not a.space.partials
