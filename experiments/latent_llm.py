"""Optional real-model proposal experiment over the hidden-state diagnostic.

No run is claimed without a real local chat-completions service. Not a native
CL-Bench adapter. The model sees public contracts and executed traces, never the
hidden table, oracle actions, or evaluator-only returns.
"""
from __future__ import annotations
import argparse,json,random
from pathlib import Path
from witness_cl.latent import Machine,Program,LatentSpace
from witness_cl.latent_agent import LatentAgent
from witness_cl.latent_proposals import parse_program
from witness_cl.llm_client import LocalChatClient


def main(args):
    client=LocalChatClient(args.base_url,args.model,allow_remote=args.allow_remote,max_tokens=256)
    rng=random.Random(args.seed)
    evaluator_world=Machine(2,2,2,tuple((rng.randrange(2),rng.randrange(2)) for _ in range(4)))
    programs=(Program.word((0,0,0,0),2),Program.word((1,1,1,1),2))
    agent=LatentAgent(LatentSpace(2,2,2),programs,((0,2),(2,0)),budget=16,seed=args.seed)
    log=[]
    for episode in range(args.episodes):
        goal=episode%2
        # Full history, no undisclosed truncation. Caller must provision the context budget.
        payload={'actions':[0,1],'observations':[0,1],'horizon':4,'known_upper_hidden_states':2,
                 'reset':True,'stationary':True,'objective_rewards':agent.rewards[goal],
                 'executed_traces':agent.space.history}
        completion=client.complete('Propose a reusable four-step control program. Return JSON only: '
            '{"word":[a,a,a,a]} or {"levels":[[a],[a,a],[a,a,a,a],[a,a,a,a,a,a,a,a]]}. '
            'Actions are 0 or 1. Levels branch on the observed binary output history. '
            'Do not assert safety, fabricate feedback, or supply executable source code.',json.dumps(payload))
        rejection=None
        try:
            candidate=parse_program(completion.content,actions=2,outputs=2,horizon=4)
            agent.register(candidate)
        except ValueError as e:rejection=str(e)
        ticket=agent.choose(goal)
        trace=agent.programs[ticket.program].rollout(evaluator_world)
        reward=sum(agent.rewards[goal][o] for _,o in trace)
        agent.observe(ticket,trace)
        log.append({'episode':episode,'goal':goal,'reward':reward,'spent':agent.spent,
                    'trace':trace,'proposal':completion.content,'proposal_rejection':rejection,
                    'model_seconds':completion.seconds,'model_usage':completion.usage})
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps({'status':'actual local-model run','model':args.model,'seed':args.seed,
                         'native_benchmark':False,'episodes':log},indent=2)+'\n')
    print(args.out)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:8000/v1')
    p.add_argument('--model',required=True);p.add_argument('--allow-remote',action='store_true')
    p.add_argument('--episodes',type=int,default=48);p.add_argument('--seed',type=int,default=10000)
    p.add_argument('--out',type=Path,default=Path('artifacts/v4/llm_run.json'))
    args=p.parse_args()
    if args.episodes<1:raise ValueError('positive episode count required')
    main(args)
