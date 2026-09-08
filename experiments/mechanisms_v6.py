"""Small declared positive/negative controls; all neural weights stay frozen."""
import hashlib
import json
from itertools import product
from pathlib import Path
from witness_cl.latent import LatentSpace, Machine, Program, compare
from witness_cl.probe_v6 import DepthTwoProbeAgent, InformativeZeroLossAgent, OptimisticProbeAgent


def run(out):
    if out.exists():
        raise FileExistsError(out)
    cases=[]
    for bits in (2,3):
        programs=tuple(Program.word((i,),5) for i in range(bits+3))
        rewards=((5,5,5,0,10),)
        worlds=tuple(Machine(1,bits+3,5,tuple((0,o) for o in (0,*(1+b for b in bs),4-sum(bs)%2,3+sum(bs)%2)))
                     for bs in product(range(2),repeat=bits))
        cases.append((f'parity_{bits}',programs,rewards,worlds,bits+1))
    programs=tuple(Program.word((i,),2) for i in range(2))
    worlds=tuple(Machine(1,2,2,tuple((0,o) for o in os)) for os in product(range(2),repeat=2))
    cases.append(('no_reward_headroom',programs,((1,1),),worlds,4))
    records=[]
    for name,programs,rewards,worlds,episodes in cases:
        for world_index,world in enumerate(worlds):
            for arm in (DepthTwoProbeAgent,InformativeZeroLossAgent,OptimisticProbeAgent):
                space=LatentSpace(world.states,world.actions,world.outputs)
                space.partials=tuple(m.table for m in worlds)
                agent=arm(space,programs,rewards,budget=0,trainable=False,max_seconds=10)
                returns=[];plans=[]
                for _ in range(episodes):
                    old=agent.incumbents[0]
                    ticket=agent.choose(0);plan=agent.last_plan
                    assert plan.status=='exact' and agent.spent==0 and ticket.debit==0
                    assert compare(space,programs[ticket.program],programs[old],rewards[0]).admits
                    trace=programs[ticket.program].rollout(world)
                    returns.append(sum(rewards[0][o] for _,o in trace))
                    plans.append(dict(program=ticket.program,work=plan.work,seconds=plan.elapsed_seconds,
                                      guaranteed_gain=plan.guaranteed_gain))
                    agent.observe(ticket,trace)
                    assert space.contains(world) and agent.proposer.updates==0
                expected=([5]*4 if name=='parity_3' and arm is DepthTwoProbeAgent else
                          [5]*(episodes-1)+[10] if name.startswith('parity') else [1]*4)
                assert returns==expected
                records.append(dict(case=name,world=world_index,method=arm.__name__,returns=returns,
                                    plans=plans,spent=agent.spent,violations=0))
    result=dict(status='passed all declared mechanism and no-headroom controls',records=records,
                source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    (Path(__file__),Path('src/witness_cl/probe_v6.py'))})
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(f'{len(records)} mechanism streams passed')


if __name__=='__main__':
    run(Path('artifacts/v6/mechanisms.json'))
