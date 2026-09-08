"""Real-model integration smoke study, not a native benchmark or powered trial.

Both model arms use the same frozen model and public prompt schema, one call per
completed episode. They receive their own executed traces. Witness additionally
has an exact finite-class checker, whose CPU cost is recorded, not matched away.
The static Witness arm distinguishes model integration from model contribution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import time

from witness_cl.latent import LatentSpace, Machine, Program
from witness_cl.latent_agent import LatentAgent
from witness_cl.latent_proposals import parse_program
from witness_cl.llm_client import LocalChatClient

SYSTEM = ('Choose a four-step program to maximize total objective reward in an unknown '
          'deterministic two-state machine. Each episode resets to the same hidden state. '
          'Learn from the executed traces; dynamics stay fixed when objectives change. '
          'Return only JSON {"word":[a,a,a,a]} with actions 0 or 1. '
          'No explanations, markdown, extra keys, or invented observations.')
ARMS = ('raw_history', 'checked_history', 'checked_static')
REWARDS = ((0, 2), (2, 0))


def visible_payload(history, goal):
    """Explicit learner boundary: no seed, machine table, or evaluator labels."""
    return {'actions': [0, 1], 'observations': [0, 1], 'horizon': 4,
            'known_upper_hidden_states': 2, 'reset': True, 'stationary': True,
            'objective_rewards': REWARDS[goal], 'executed_traces': history}


def parse_or_anchor(text):
    """Malformed model output consumes its call and executes a declared anchor."""
    try:
        value = parse_program(text, actions=2, outputs=2, horizon=4)
        return value, None
    except ValueError as exc:
        return Program.word((0, 0, 0, 0), 2), str(exc)


def run(client, out, *, seeds=(41000,), episodes=12):
    if episodes < 3 or episodes % 3:
        raise ValueError('episodes must be a positive multiple of three, at least three')
    if out.exists():
        raise FileExistsError('preserve prior pilot outputs; choose a new directory')
    out.mkdir(parents=True)
    manifest = {'status': 'running', 'native_benchmark': False,
                'purpose': 'integration smoke, not a powered or iso-compute comparison',
                'seeds': list(seeds), 'episodes': episodes, 'arms': ARMS,
                'model': client.model, 'temperature': 0, 'max_tokens': client.max_tokens,
                'prompt': SYSTEM, 'risk_budget': 16, 'goal_schedule': 'A-B-A equal blocks',
                'invalid_output': 'raw: count rejection and execute 0000; checked: skip registration, use existing checked controller; no retry',
                'time_started_unix': time.time(),
                'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    rows = []
    with (out / 'episodes.jsonl').open('x') as stream:
        try:
            for seed in seeds:
                rng = random.Random(seed)
                world = Machine(2, 2, 2, tuple((rng.randrange(2), rng.randrange(2)) for _ in range(4)))
                initial = (Program.word((0, 0, 0, 0), 2), Program.word((1, 1, 1, 1), 2))
                agents = {arm: LatentAgent(LatentSpace(2, 2, 2), initial, REWARDS,
                                          budget=16, seed=seed) for arm in ARMS if arm != 'raw_history'}
                histories = {arm: [] for arm in ARMS}
                # Rotate arm order by episode; do not batch one arm under a colder server.
                for episode in range(episodes):
                    goal = 1 if episodes // 3 <= episode < 2 * episodes // 3 else 0
                    order = ARMS[episode % 3:] + ARMS[:episode % 3]
                    for arm in order:
                        start = time.perf_counter()
                        proposal = rejection = usage = None
                        model_seconds = 0.
                        candidate = initial[0]
                        if arm != 'checked_static':
                            completion = client.complete(SYSTEM, json.dumps(visible_payload(histories[arm], goal)))
                            proposal, usage, model_seconds = completion.content, completion.usage, completion.seconds
                            candidate, rejection = parse_or_anchor(proposal)
                        checker_start = time.perf_counter()
                        if arm == 'raw_history':
                            chosen = candidate
                            ticket = None
                        else:
                            agent = agents[arm]
                            if arm != 'checked_static' and rejection is None:
                                agent.register(candidate)
                            ticket = agent.choose(goal)
                            chosen = agent.programs[ticket.program]
                        checker_seconds = time.perf_counter() - checker_start
                        trace = chosen.rollout(world)  # Evaluator-owned; only trace is returned.
                        reward = sum(REWARDS[goal][o] for _, o in trace)
                        update_start = time.perf_counter()
                        if ticket is not None:
                            agents[arm].observe(ticket, trace)
                        update_seconds = time.perf_counter() - update_start
                        histories[arm].append(trace)
                        row = {'seed': seed, 'episode': episode, 'arm': arm, 'goal': goal,
                               'reward': reward, 'trace': trace, 'proposal': proposal,
                               'proposal_rejection': rejection, 'usage': usage,
                               'model_seconds': model_seconds, 'checker_seconds': checker_seconds,
                               'update_seconds': update_seconds, 'total_seconds': time.perf_counter() - start,
                               'spent': agents[arm].spent if ticket is not None else None,
                               'proposal_executed': candidate == chosen if proposal is not None and rejection is None else None,
                               'model_call': arm != 'checked_static'}
                        stream.write(json.dumps(row) + '\n'); stream.flush(); rows.append(row)
                        print(seed, episode, arm, reward, f'{row["total_seconds"]:.2f}s', flush=True)
        except Exception as exc:
            manifest.update(status='failed', failure_type=type(exc).__name__,
                            failure='model or experiment failure; see execution log', completed_rows=len(rows))
            (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            raise
    summary = {}
    for arm in ARMS:
        selected = [r for r in rows if r['arm'] == arm]
        summary[arm] = {'episodes': len(selected),
                        'mean_return': sum(r['reward'] for r in selected) / len(selected),
                        'model_calls': sum(r['model_call'] for r in selected),
                        'invalid_outputs': sum(r['proposal_rejection'] is not None for r in selected),
                        'model_seconds': sum(r['model_seconds'] for r in selected),
                        'checker_seconds': sum(r['checker_seconds'] for r in selected),
                        'update_seconds': sum(r['update_seconds'] for r in selected),
                        'prompt_tokens': sum((r['usage'] or {}).get('prompt_tokens', 0) for r in selected),
                        'completion_tokens': sum((r['usage'] or {}).get('completion_tokens', 0) for r in selected),
                        'usage_missing': sum(r['model_call'] and any(type((r['usage'] or {}).get(k)) is not int or (r['usage'] or {}).get(k, -1) < 0 for k in ('prompt_tokens', 'completion_tokens')) for r in selected)}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    manifest.update(status='complete', completed_rows=len(rows), time_finished_unix=time.time())
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:18082/v1')
    parser.add_argument('--model', required=True)
    parser.add_argument('--episodes', type=int, default=12)
    parser.add_argument('--seeds', type=int, nargs='+', default=[41000])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    client = LocalChatClient(args.base_url, args.model, max_tokens=96, timeout=120)
    run(client, args.out, seeds=args.seeds, episodes=args.episodes)
