#!/usr/bin/env python3
"""Bounded real-model pilot of experience-derived executable SQL abstractions.

A pilot is a feasibility/competence test, never a powered claim of25% savings
and2% noninferiority. Frozen evaluation panels never update any memory.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import traceback

from witness_cl.fragments_v8 import Fragment, FragmentError
from witness_cl.abstraction_v8 import (PROPOSAL_SCHEMA, proposal_messages, prepare_proposal, admit_verified)
from witness_cl.memory_v8 import ARMS, ACTION_SCHEMA, reflection_schema, ExperienceMemory, parse_action, canonical
from witness_cl.model_v8 import BudgetStop, InferenceBudget, LocalInference
from witness_cl.sql_env_v8 import make_stream, open_episode, evaluator_metadata

MAX_ACTIONS = 10
ORDINARY_TOKEN_CAP = 500_000
PANEL_TOKEN_CAP = 500_000
ORDINARY_CALL_CAP = 280
PANEL_CALL_CAP = 260
SOURCE_FILES = ('src/witness_cl/sql_env_v8.py', 'src/witness_cl/fragments_v8.py',
                'src/witness_cl/memory_v8.py', 'src/witness_cl/model_v8.py', 'src/witness_cl/abstraction_v8.py',
                'experiments/sql_abstractions_v8.py', 'docs/v8/EVALUATION.md')


def source_hashes():
    root = Path(__file__).resolve().parents[1]
    return {f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in SOURCE_FILES}


def execute_episode(spec, memory, client, budget, *, phase, learn):
    """Only public question/schema and actual observations reach the model."""
    start = time.monotonic()
    before = memory.digest()
    trace = {'phase': phase, 'question': None, 'schema': None,
             'queries': [], 'model_calls': [], 'actions': [], 'answer': None,
             'reward': 0., 'status': 'running', 'before_memory_digest': before}
    conversation = []
    setup_start = time.monotonic()
    with open_episode(spec, allow_learning_checks=learn) as session:
        trace['setup_seconds'] = time.monotonic() - setup_start
        public = session.public
        trace.update(question=public.question, schema=public.schema)
        prefix, selected = memory.prefix(public.question)
        trace['retrieved_entry_digests'] = [e.fragment().digest for e in selected]
        trace['retrieved_provenance'] = [e.provenance for e in selected]
        conversation.append({'role': 'user', 'content': canonical({
            'question': public.question, 'schema': public.schema,
            'remaining_selects': public.max_selects})})

        def query(sql, params, purpose, *, learning_check=False):
            result = session.query(sql, params, learning_check=learning_check)
            row = {'sql': sql, 'params': params, 'purpose': purpose, 'learning_check': learning_check, **asdict(result)}
            trace['queries'].append(row)
            return row

        def feedback(row, detail=None):
            msg = {'tool_result': {k: row[k] for k in ('columns', 'rows', 'error', 'truncated')},
                   'remaining_selects': public.max_selects - session.select_attempts}
            if detail is not None:
                msg['memory_check'] = detail
            conversation.append({'role': 'user', 'content': canonical(msg)})

        try:
            answered = False
            for _ in range(MAX_ACTIONS):
                content = client.complete(prefix + conversation, budget, phase=phase + ':solve',
                                          records=trace['model_calls'], output_tokens=384, response_schema=ACTION_SCHEMA)
                conversation.append({'role': 'assistant', 'content': content})
                try:
                    action = parse_action(content)
                except (ValueError, TypeError, FragmentError) as exc:
                    trace['actions'].append({'kind': 'invalid', 'error': str(exc)})
                    if session.select_attempts < public.max_selects:
                        row = query('', {}, 'invalid_model_action')
                        feedback(row, 'Invalid action format: ' + str(exc))
                    else:
                        conversation.append({'role': 'user', 'content': 'Invalid action. No SELECTs remain. Submit a finite numeric ANSWER.'})
                    continue
                trace['actions'].append(deepcopy(action))
                if action['action'] == 'ANSWER':
                    trace['answer'] = action['value']
                    trace['reward'] = session.answer(action['value']).reward
                    answered = True
                    break
                if session.select_attempts >= public.max_selects:
                    # No uncharged query executes. This call was still billed.
                    conversation.append({'role': 'user', 'content': 'No SELECTs remain. Submit ANSWER using only observed evidence.'})
                    continue
                if action['action'] == 'QUERY':
                    request = Fragment.from_query(action['sql'], action['params']).original_prepared_query
                    feedback(query(request.sql, request.parameters, 'ordinary_query'))
                    continue
                try:
                    entry = selected[action['entry']]
                    fragment = entry.fragment()
                    if action['action'] == 'USE':
                        request = fragment.compile(action['params'])
                    else:
                        request = fragment.compose(action['outer_sql'], action['outer_params'],
                                                   alias='reused', bindings=action['params'])
                    if memory.arm == 'fragments':
                        guard = entry.guard_fragment().original_prepared_query
                        observed = query(guard.sql, guard.parameters, 'applicability_check')
                        actual = {k: observed[k] for k in ('columns', 'rows', 'truncated')}
                        passed = observed['error'] is None and canonical(actual) == entry.expected
                        trace['actions'][-1]['guard_passed'] = passed
                        if not passed:
                            feedback(observed, 'Witnessed applicability rows do not match. This use was rejected; solve from current observations.')
                            continue
                        if session.select_attempts >= public.max_selects:
                            feedback(observed, 'Applicability matched, but no SELECT allowance remains to execute the fragment.')
                            continue
                    trace['actions'][-1]['executed_fragment_digest'] = fragment.digest
                    feedback(query(request.sql, request.parameters, 'fragment_composition' if action['action'] == 'COMPOSE' else 'fragment_use'))
                except (IndexError, ValueError, TypeError, FragmentError) as exc:
                    feedback(query('', {}, 'invalid_memory_action'), 'Invalid memory use: ' + str(exc))
            if not answered:
                trace['reward'] = session.answer(None).reward
                trace['status'] = 'no_valid_answer'
            else:
                trace['status'] = 'completed'
            # This is the only ordinary target feedback: correctness, no gold.
            conversation.append({'role': 'user', 'content': canonical({'correctness_feedback': trace['reward']})})
            if learn:
                synthesizing = memory.arm in ('fragments', 'fragments_unchecked')
                reflection = (proposal_messages(trace) if synthesizing and trace['reward'] == 1.
                              and session.select_attempts < public.max_selects else
                              None if synthesizing else memory.reflection(trace, conversation))
                reflection_text = None
                if reflection is not None:
                    try:
                        reflection_text = client.complete(reflection, budget,
                                                          phase=phase + ':reflection', records=trace['model_calls'],
                                                          output_tokens=1024,
                                                          response_schema=PROPOSAL_SCHEMA if synthesizing else reflection_schema(memory.arm))
                    except BudgetStop as exc:
                        trace['reflection_stop'] = str(exc)
                if synthesizing and reflection_text is not None:
                    trace['abstraction_proposal'] = {'status': 'proposed'}
                    try:
                        proposal = prepare_proposal(reflection_text, trace)
                        if proposal is None:
                            trace['abstraction_proposal']['status'] = 'abstained'
                        else:
                            index = len(trace['queries'])
                            trace['abstraction_proposal'].update(model_fields=json.loads(proposal.model_fields),
                                                                eligible_query_count=index)
                            check = query(proposal.request.sql, proposal.request.parameters,
                                          'abstraction_reconstruction', learning_check=True)
                            entry = admit_verified(memory, proposal, trace, index)
                            trace['abstraction_proposal'].update(status='accepted', fragment_digest=entry.fragment().digest,
                                                                verification_query_index=index)
                    except (ValueError, TypeError, KeyError, FragmentError) as exc:
                        trace['abstraction_proposal'].update(status='rejected', reason=str(exc))
                        memory.events.append({'kind': 'rejected_abstraction', 'reason': str(exc)})
                memory.finish(trace, conversation, None if synthesizing else reflection_text)

        except BudgetStop as exc:
            trace.update(status='resource_stop', stop_reason=str(exc))
        except Exception as exc:
            trace.update(status='backend_or_runtime_failure', error_type=type(exc).__name__,
                         error=str(exc)[:256])
        finally:
            trace.update(select_attempts=session.select_attempts,
                         query_seconds=session.query_seconds, vm_steps=session.vm_steps)
    after = memory.digest()
    if not learn and after != before:
        raise AssertionError('evaluation panel mutated learned memory')
    trace.update(after_memory_digest=after, elapsed_seconds=time.monotonic() - start,
                 memory_bytes=memory.memory_bytes(), memory_snapshot=memory.snapshot())
    # This field is evaluator-only and added after the interaction is complete.
    trace['evaluator'] = evaluator_metadata(spec)
    return trace


def write_json(path, payload):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def run_pilot(out: Path, client, *, seeds=(90000,), conditions=('reuse',), wall_seconds=1800,
              arms=ARMS, stop_after=None):
    if (not seeds or len(set(seeds)) != len(seeds) or any(type(s) is not int or not 90000 <= s <= 90003 for s in seeds)
            or not conditions or len(set(conditions)) != len(conditions)
            or any(c not in ('reuse', 'nonreuse', 'near_match') for c in conditions)):
        raise ValueError('unique declared development seeds90000..90003 and conditions required')
    if out.exists():
        raise FileExistsError('completed and partial studies are immutable; use a new directory')
    if not 0 < wall_seconds <= 1800 or len(seeds) * len(conditions) > 4:
        raise ValueError('pilot permits at most four streams and1800 wall seconds')
    if not arms or len(set(arms)) != len(arms) or any(a not in ARMS for a in arms):
        raise ValueError('invalid arms')
    out.mkdir(parents=True)
    started = time.monotonic()
    deadline = started + wall_seconds
    manifest = {'version': 8, 'kind': 'development_cost_and_competence_pilot',
                'status': 'running', 'seeds': list(seeds), 'conditions': list(conditions),
                'arms': list(arms), 'ordinary_questions': 24, 'old_panel_questions': 8,
                'final_panel_questions': 8, 'wall_seconds_cap': wall_seconds,
                'ordinary_token_cap_per_arm_stream': ORDINARY_TOKEN_CAP,
                'panel_token_cap_per_arm_stream': PANEL_TOKEN_CAP,
                'max_selects_per_question': 8, 'max_actions_per_question': MAX_ACTIONS,
                'solve_output_tokens': 384, 'reflection_output_tokens': 1024,
                'model': client.model, 'context_tokens': client.context_tokens,
                'source_sha256': source_hashes(), 'native_benchmark': False,
                'claim_confirmed': False, 'started_unix': time.time(),
                'timing_includes': 'all pilot setup, model tokenization/inference, extraction, checks, evaluation and incremental export; model load separately',
                'stop_after_debug': stop_after}
    write_json(out / 'manifest.json', manifest)
    count = 0
    failure = None
    aggregate = []
    active_runs = []
    try:
        for seed in seeds:
            for condition in conditions:
                spec = make_stream(seed, condition, split='development')
                memories = {a: ExperienceMemory(a) for a in arms}
                ordinary = {a: InferenceBudget(max_total_tokens=ORDINARY_TOKEN_CAP, max_calls=ORDINARY_CALL_CAP,
                                               deadline=deadline) for a in arms}
                panels = {a: InferenceBudget(max_total_tokens=PANEL_TOKEN_CAP, max_calls=PANEL_CALL_CAP,
                                             deadline=deadline) for a in arms}
                ordinary_stopped = set()
                schedule = [('ordinary', i, s) for i, s in enumerate(spec.ordinary[:8])]
                schedule += [('old_before', i, s) for i, s in enumerate(spec.old_panel)]
                schedule += [('ordinary', i + 8, s) for i, s in enumerate(spec.ordinary[8:])]
                schedule += [('old_after', i, s) for i, s in enumerate(spec.old_panel)]
                schedule += [('final', i, s) for i, s in enumerate(spec.final_panel)]
                rows = {a: [] for a in arms}
                active_runs.append((seed, condition, memories, ordinary, panels, rows))
                for step, (phase, index, episode) in enumerate(schedule):
                    offset = step % len(arms)
                    order = arms[offset:] + arms[:offset]
                    for arm in order:
                        if time.monotonic() >= deadline:
                            raise BudgetStop('global_pilot_wall_ceiling')
                        if phase == 'ordinary' and arm in ordinary_stopped:
                            continue
                        budget = ordinary[arm] if phase == 'ordinary' else panels[arm]
                        trace = execute_episode(episode, memories[arm], client, budget,
                                                phase=phase, learn=phase == 'ordinary')
                        trace.update(seed=seed, condition=condition, arm=arm, episode_index=index)
                        path = out / f'{seed}-{condition}-{arm}.jsonl'
                        with path.open('a') as handle:
                            handle.write(canonical(trace) + '\n')
                        rows[arm].append(trace)
                        count += 1
                        print(canonical({'episode': count, 'seed': seed, 'condition': condition,
                                         'arm': arm, 'phase': phase, 'index': index,
                                         'reward': trace['reward'], 'selects': trace['select_attempts'],
                                         'status': trace['status'], 'elapsed': round(time.monotonic()-started, 2)}), flush=True)
                        if trace['status'] == 'backend_or_runtime_failure':
                            raise RuntimeError('backend/runtime failure; all remaining runs stopped')
                        if trace['status'] == 'resource_stop' and phase == 'ordinary':
                            ordinary_stopped.add(arm)
                        if stop_after is not None and count >= stop_after:
                            raise BudgetStop('explicit_debug_stop')
        manifest['status'] = 'completed'
    except Exception as exc:
        failure = {'type': type(exc).__name__, 'reason': str(exc)[:512]}
        manifest['status'] = 'stopped' if isinstance(exc, BudgetStop) else 'failed'
        manifest['failure'] = failure
    finally:
        for run_seed, run_condition, memories, ordinary, panels, rows in active_runs:
            for arm in arms:
                grouped = {p: [t for t in rows[arm] if t['phase'] == p]
                           for p in ('ordinary', 'old_before', 'old_after', 'final')}
                aggregate.append({'seed': run_seed, 'condition': run_condition, 'arm': arm,
                                  'ordinary_budget': ordinary[arm].to_dict(), 'panel_budget': panels[arm].to_dict(),
                                  'memory': memories[arm].snapshot(),
                                  'phase_counts': {p: len(ts) for p, ts in grouped.items()},
                                  'phase_reward': {p: sum(t['reward'] for t in ts) / len(ts) if ts else None
                                                   for p, ts in grouped.items()},
                                  'phase_selects': {p: sum(t['select_attempts'] for t in ts) for p, ts in grouped.items()},
                                  'phase_failures': {p: sum(t['status'] != 'completed' for t in ts) for p, ts in grouped.items()}})
        manifest.update(elapsed_seconds=time.monotonic()-started, completed_episode_records=count,
                        source_unchanged=source_hashes() == manifest['source_sha256'],
                        raw_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.jsonl'))})
        expected = {'ordinary': 24, 'old_before': 8, 'old_after': 8, 'final': 8}
        panel_complete = len(aggregate) == len(seeds)*len(conditions)*len(arms) and all(
            row['phase_counts'] == expected for row in aggregate)
        any_stops = any(t['status'] in ('resource_stop', 'backend_or_runtime_failure')
                        for _, _, _, _, _, rows in active_runs for ts in rows.values() for t in ts)
        manifest['required_records_complete'] = panel_complete and not any_stops
        if not manifest['source_unchanged']:
            manifest.update(status='invalidated', invalidation='executed_source_changed_during_run')
        elif manifest['status'] == 'completed' and not manifest['required_records_complete']:
            manifest.update(status='incomplete', incomplete_reason='missing_required_records_or_resource_stops')
        write_json(out / 'manifest.json', manifest)
        write_json(out / 'summary.json', aggregate)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--seeds', nargs='+', type=int, default=[90000])
    parser.add_argument('--conditions', nargs='+', choices=['reuse','nonreuse','near_match'], default=['reuse'])
    parser.add_argument('--wall-seconds', type=int, default=1800)
    parser.add_argument('--arms', nargs='+', choices=ARMS, default=list(ARMS))
    parser.add_argument('--stop-after', type=int)
    args = parser.parse_args()
    client = LocalInference(key_file=args.key_file, max_output=1024)
    result = run_pilot(args.out, client, seeds=tuple(args.seeds), conditions=tuple(args.conditions),
                       wall_seconds=args.wall_seconds, arms=tuple(args.arms), stop_after=args.stop_after)
    print(json.dumps({k: result.get(k) for k in ('status','failure','completed_episode_records','elapsed_seconds')}, indent=2))
    return 0 if result['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
