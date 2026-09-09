#!/usr/bin/env python3
"""Independent saved-data replay for frozen v9 local development streams.

No model request, runner import, EpisodeSession query, or heldout episode is used.
SQL is replayed on independently constructed SQLite connections. Environment
fixtures, action parsing, memory and compiler definitions are shared frozen code;
this is consistency evidence, not authentication or an independent learner.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
from experiments.audit_sql_abstractions_v8 import (
    AuditError, Budget, SQLiteReplay, FUNCTIONS, TERMINAL, require, exact, finite,
    integer, read_json, sha, verified_scalar, scalar_equal, verify_entries,
)
from witness_cl.fragments_v8 import Fragment, FragmentError
from witness_cl.abstraction_v8 import PROPOSAL_SCHEMA, proposal_messages, prepare_proposal, admit_verified
from witness_cl.memory_v8 import ARMS, ACTION_SCHEMA, canonical
from witness_cl.memory_v9 import ExperienceMemoryV9, reflection_schema_v9
from witness_cl.actions_v9 import parse_action
from witness_cl.sql_env_v9 import make_stream, evaluator_metadata

SOURCE_FILES = (
    'src/witness_cl/sql_env_v8.py', 'src/witness_cl/sql_env_v9.py',
    'src/witness_cl/fragments_v8.py', 'src/witness_cl/memory_v8.py',
    'src/witness_cl/model_v8.py', 'src/witness_cl/abstraction_v8.py',
    'src/witness_cl/memory_v9.py', 'src/witness_cl/model_v9.py',
    'src/witness_cl/actions_v9.py', 'experiments/competence_interactive_v9.py',
    'experiments/sql_abstractions_v9.py',
)
PORTABLE_SOURCE_FILES = (*SOURCE_FILES, 'src/witness_cl/model_v9_compatible.py', 'experiments/portable_stream_v9.py')
WIRE_SCHEMA_POLICY = 'host_checks_large_string_bounds_v1'
PHASES = ('ordinary', 'old_before', 'old_after', 'final')
COUNTERS = ('total_tokens', 'prompt_tokens', 'completion_tokens', 'calls',
            'tokenization_seconds', 'inference_seconds', 'unknown_usage_calls')


class SQLiteReplayV9(SQLiteReplay):
    def __init__(self, spec):
        super().__init__(spec)
        try:
            self.db.set_authorizer(None)
            modules = frozenset(row[0].casefold() for row in self.db.execute('PRAGMA module_list')) | {
                'json_each', 'json_tree', 'jsonb_each', 'jsonb_tree',
            }
            tables = {table.name for table in spec._tables}
            def authorize(action, first, second, database, source):
                if action == sqlite3.SQLITE_SELECT:
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_FUNCTION and (second or '').lower() in FUNCTIONS:
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_READ:
                    if first in tables and (database == 'main' or database is None and second == ''):
                        return sqlite3.SQLITE_OK
                    # Only constructor-owned physical tables exist. SQLite's
                    # anonymous reads of derived relations are distinguishable
                    # from every registered virtual module in this connection.
                    if isinstance(first, str) and first and second == '' and database is None:
                        name = first.casefold()
                        if not name.startswith(('sqlite_', 'pragma_')) and name not in modules:
                            return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            self.db.set_authorizer(authorize)
        except Exception:
            self.close()
            raise


class ChargedBudget:
    """Two independent ledgers, checked and charged in global execution order."""
    def __init__(self, local, total):
        self.local, self.total = local, total

    def add(self, field, value):
        for ledger in (self.local, self.total):
            setattr(ledger, field, getattr(ledger, field) + value)

    def can_reserve(self, prompt, output):
        return all(b.calls < b.max_calls and b.total_tokens + prompt + output <= b.max_total_tokens
                   for b in (self.local, self.total))

    def before_unrecorded_stop(self, reason, output_limit):
        if reason == 'model_call_ceiling':
            require(any(b.calls >= b.max_calls for b in (self.local, self.total)), 'unjustified model-call ceiling')
        elif reason == 'model_token_ceiling':
            require(any(b.total_tokens + output_limit > b.max_total_tokens for b in (self.local, self.total)),
                    'unjustified token ceiling before a recorded preflight')
        else:
            require(reason == 'wall_time_ceiling', 'unverifiable unrecorded resource stop: ' + str(reason))


def portable_wire_schema(value):
    """Independent normalization of the declared transport-only schema repair."""
    if type(value) is list:
        return [portable_wire_schema(item) for item in value]
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            if key != 'maxLength' or type(item) is not int or item <= 2000:
                result[key] = portable_wire_schema(item)
        return result
    return deepcopy(value)


def check_call(record, expected_messages, phase, schema, budget, manifest, counts, protocol_issues):
    config = manifest['client_config']
    output = manifest['limits']['reflection_output_tokens' if phase.endswith(':reflection') else 'solve_output_tokens']
    exact(record.get('messages'), expected_messages, 'model prompt is not its exact legal own-history input')
    require(record.get('phase') == phase, 'model call phase/order mismatch')
    require(type(record.get('max_output_tokens')) is int and record['max_output_tokens'] == output,
            'per-call output cap changed')
    portable = set(manifest['source_sha256']) == set(PORTABLE_SOURCE_FILES)
    expected_decoding = deepcopy(config['decoding'])
    if portable:
        require(config['response_mode'] == 'schema', 'portable transport requires schema mode')
        require(record.get('wire_schema_policy') == WIRE_SCHEMA_POLICY, 'portable wire policy differs')
        require(record.get('reflection_thinking') is False, 'portable reflection-thinking policy differs')
        if phase.endswith(':reflection'):
            expected_decoding['thinking'] = False
        exact(record.get('host_response_schema'), schema, 'portable host validation schema differs')
        schema = portable_wire_schema(schema)
    else:
        require(not any(key in record for key in ('wire_schema_policy', 'host_response_schema', 'reflection_thinking')),
                'undeclared portable transport')
    simulated = record.get('test_double') is True
    if simulated:
        counts['test_double_calls'] += 1
    legacy_stub = simulated and not any(key in record for key in ('response_mode', 'request_config', 'decoding'))
    if legacy_stub:
        # Old explicit offline fixtures lack transport receipts. They can never
        # become eligible model/resource evidence. Fully shaped simulated
        # receipts must meet exactly the same request contract as real records.
        expected_schema = schema
    else:
        expected_schema = schema if config['response_mode'] == 'schema' else None
        exact(record.get('decoding'), expected_decoding, 'per-call decoding changed')
        require(record.get('response_mode') == config['response_mode'], 'response mode changed')
        expected_body = {'model': config['model'], **{k: v for k, v in expected_decoding.items() if k != 'thinking'},
                         'max_tokens': output, 'cache_prompt': False, 'stream': False,
                         'response_format': {'type': 'json_object'},
                         'chat_template_kwargs': {'enable_thinking': expected_decoding['thinking']}}
        if expected_schema is not None:
            expected_body['response_format']['schema'] = expected_schema
        exact(record.get('request_config'), expected_body, 'effective request differs from frozen common client')
    exact(record.get('response_schema'), expected_schema, 'model response schema differs from frozen interface')
    require(budget.can_reserve(0, output), 'recorded preflight began after local/shared initial allowance exhaustion')
    counts['recorded_model_calls'] += 1
    budget.add('tokenization_seconds', finite(record.get('tokenization_seconds'), 'tokenization time'))
    status = record.get('status')
    require(status in ('completed', 'failed', 'preflight_failed'), 'unfinished or unknown model call status')
    prompt = record.get('preflight_tokens')
    if prompt is not None:
        integer(prompt, 'preflight tokens')
    attempted = record.get('generation_attempted')
    require(type(attempted) is bool, 'generation-attempt flag must be Boolean')
    if status == 'preflight_failed':
        require(not attempted and record.get('usage') is None, 'preflight failure contains generated usage')
        require(finite(record.get('inference_seconds', 0.), 'inference time') == 0., 'preflight failure contains generation time')
        if record.get('error_type') == 'BudgetStop':
            reason = record.get('stop_reason')
            if reason == 'full_context_ceiling_no_truncation':
                require(prompt is not None and prompt + output > config['context_tokens'], 'unjustified full-context stop')
            elif reason == 'model_token_ceiling':
                require(prompt is not None and any(b.total_tokens + prompt + output > b.max_total_tokens
                        for b in (budget.local, budget.total)), 'unjustified token preflight stop')
            elif reason == 'model_call_ceiling':
                require(any(b.calls >= b.max_calls for b in (budget.local, budget.total)), 'unjustified call preflight stop')
            else:
                require(reason == 'wall_time_ceiling', 'unknown preflight resource stop')
            counts['resource_stop_calls'] += 1
            return 'budget', reason
        require(type(record.get('error_type')) is str, 'missing preflight failure type')
        return 'runtime', record['error_type']
    require(attempted and prompt is not None, 'generation lacks completed preflight')
    require(prompt + output <= config['context_tokens'], 'generation began with overflowing context')
    require(budget.can_reserve(prompt, output), 'generation began beyond local/shared reservation allowance')
    budget.add('calls', 1)
    budget.add('inference_seconds', finite(record.get('inference_seconds'), 'inference time'))
    counts['generation_attempts'] += 1
    usage = record.get('usage')
    if usage is None:
        require(status == 'failed', 'completed call has unknown token usage')
        budget.add('unknown_usage_calls', 1)
        counts['unknown_usage_calls'] += 1
        counts['unknown_usage_reserved_tokens'] += prompt + output
    else:
        require(type(usage) is dict, 'invalid token usage object')
        p, c, total = [integer(usage.get(k), k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')]
        require(total == p + c, 'token usage sum mismatch')
        for field, value in (('prompt_tokens', p), ('completion_tokens', c), ('total_tokens', total)):
            budget.add(field, value)
            counts['known_' + field] += value
        violations = []
        if p < prompt or p + c > config['context_tokens']:
            violations.append('backend prompt/token accounting mismatch')
        if c > output or any(b.total_tokens > b.max_total_tokens for b in (budget.local, budget.total)):
            violations.append('backend exceeded reserved token allowance')
        if violations:
            require(status == 'failed', 'completed call violates frozen token/context limits')
            protocol_issues.extend(violations)
    if record.get('response_model') != config['model']:
        require(status == 'failed', 'completed response has a different model alias')
        if record.get('response_model') is not None:
            protocol_issues.append('failed backend response has a different model alias')
    if status == 'failed':
        require(type(record.get('error_type')) is str, 'failed call missing error type')
        return 'runtime', record['error_type']
    require(usage is not None and type(record.get('content')) is str, 'completed call lacks content/usage')
    if not simulated:
        require(type(record.get('content_was_null')) is bool, 'missing null-content receipt')
        require(not record['content_was_null'] or record['content'] == '', 'null content became an invented answer')
        require(record.get('reasoning_content') is None or type(record['reasoning_content']) is str,
                'invalid reasoning output receipt')
        counts['calls_with_reasoning_output'] += int(bool(record.get('reasoning_content')))
    return 'completed', record['content']


def proposal_messages_v9(trace):
    messages = proposal_messages(trace)
    payload = json.loads(messages[1]['content'])
    reward = payload.pop('feedback_reward')
    payload['correct'] = reward == 1.
    payload['feedback_meaning'] = 'Correct on this episode only; no hidden answer is supplied.'
    messages[1]['content'] = canonical(payload)
    return messages

def check_episode(trace, spec, memory, budget, manifest, counts, evidence, protocol_issues):
    require(trace.get('status') in TERMINAL, 'unknown or unfinished episode status')
    phase = trace['phase']
    learn = phase == 'ordinary'
    require(trace.get('learn') is learn, 'learning capability differs from scheduled phase')
    require(trace.get('system_prompt_sha256') == manifest['system_prompt_sha256'], 'episode shared prompt changed')
    exact(trace.get('evaluator'), evaluator_metadata(spec), 'raw evaluator fixture metadata differs')
    require(trace.get('question') == spec._public.question and trace.get('schema') == spec._public.schema,
            'public question/schema differs from generated fixture')
    require(trace.get('before_memory_digest') == memory.digest(), 'before-memory digest mismatch')
    prefix, selected = memory.prefix(spec._public.question)
    exact(trace.get('retrieved_entry_digests'), [e.fragment().digest for e in selected], 'retrieved entries differ')
    exact(trace.get('retrieved_provenance'), [e.provenance for e in selected], 'retrieved evidence provenance differs')
    verify_entries(memory, evidence)
    conversation = [{'role': 'user', 'content': canonical({
        'question': spec._public.question, 'schema': spec._public.schema, 'remaining_selects': 8})}]
    records = trace['model_calls']
    queries = trace['queries']
    require(type(records) is list and type(queries) is list, 'missing call/query arrays')
    require(len(queries) <= 8, 'query ledger exceeds SELECT allowance')
    call_index = query_index = 0
    actions = []
    submitted = None
    answered = False
    terminal = None
    failure_detail = None
    reflection_stop = None
    abstraction = None
    db = SQLiteReplayV9(spec)

    def consume_query(sql, params, purpose, *, learning_check=False):
        nonlocal query_index
        require(query_index < len(queries), 'missing charged query record')
        record = queries[query_index]
        require(set(record) == {'sql', 'params', 'purpose', 'learning_check', 'columns', 'rows', 'error', 'attempt', 'truncated'},
                'query row has missing or covert extra fields')
        require(type(record['learning_check']) is bool and record['learning_check'] is learning_check,
                'post-answer learning-check capability differs from the legal execution phase')
        require(not learning_check or learn and answered, 'learning SELECT occurred outside a completed ordinary answer')
        exact([record['sql'], record['params'], record['purpose']], [sql, params, purpose],
              'recorded SQL/parameters/purpose differ from compiled model action')
        query_index += 1
        integer(record['attempt'], 'query attempt', minimum=1)
        require(record['attempt'] == query_index, 'query attempts are missing, duplicated or reordered')
        actual = db.query(sql, params)
        observed = {k: record[k] for k in ('columns', 'rows', 'error', 'truncated')}
        if canonical(actual) != canonical(observed) and record['error'] in ('interrupted', 'query time limit exceeded'):
            exact([record['columns'], record['rows'], record['truncated']], [[], [], False],
                  'time-limited query retained an unreturned answer')
            counts['timing_dependent_errors_unverified'] += 1
        else:
            exact(actual, observed, 'independent SQLite result/error differs from saved query')
            counts['independently_replayed_queries'] += 1
        counts['select_attempts'] += 1
        counts['query_errors'] += int(record['error'] is not None)
        return record

    def feedback(record, detail=None):
        payload = {'tool_result': {k: record[k] for k in ('columns', 'rows', 'error', 'truncated')},
                   'remaining_selects': 8 - query_index}
        if detail is not None:
            payload['memory_check'] = detail
        conversation.append({'role': 'user', 'content': canonical(payload)})

    def next_call(messages, suffix, schema):
        nonlocal call_index
        if call_index == len(records):
            reason = trace.get('reflection_stop') if suffix == 'reflection' else trace.get('stop_reason')
            require(type(reason) is str, 'missing model call without a recorded resource stop')
            budget.before_unrecorded_stop(reason, manifest['limits']['reflection_output_tokens' if suffix == 'reflection' else 'solve_output_tokens'])
            return 'budget', reason
        record = records[call_index]
        call_index += 1
        return check_call(record, messages, phase + ':' + suffix, schema,
                          budget, manifest, counts, protocol_issues)

    try:
        for _ in range(10):
            outcome, content = next_call(prefix + conversation, 'solve', ACTION_SCHEMA)
            if outcome != 'completed':
                terminal = 'resource_stop' if outcome == 'budget' else 'backend_or_runtime_failure'
                failure_detail = content
                break
            conversation.append({'role': 'assistant', 'content': content})
            try:
                action = parse_action(content)
            except (ValueError, TypeError, FragmentError) as exc:
                actions.append({'kind': 'invalid', 'error': str(exc)})
                if query_index < 8:
                    feedback(consume_query('', {}, 'invalid_model_action'), 'Invalid action format: ' + str(exc))
                else:
                    conversation.append({'role': 'user', 'content': 'Invalid action. No SELECTs remain. Submit a finite numeric ANSWER.'})
                continue
            action = deepcopy(action)
            actions.append(action)
            if action['action'] == 'ANSWER':
                submitted, answered = action['value'], True
                break
            if query_index >= 8:
                conversation.append({'role': 'user', 'content': 'No SELECTs remain. Submit ANSWER using only observed evidence.'})
                continue
            if action['action'] == 'QUERY':
                feedback(consume_query(action['sql'], action['params'], 'ordinary_query'))
                continue
            try:
                entry = selected[action['entry']]
                fragment = entry.fragment()
                request = fragment.compile(action['params']) if action['action'] == 'USE' else fragment.compose(
                    action['outer_sql'], action['outer_params'], alias='reused', bindings=action['params'])
            except (IndexError, ValueError, TypeError, FragmentError) as exc:
                feedback(consume_query('', {}, 'invalid_memory_action'), 'Invalid memory use: ' + str(exc))
                continue
            if memory.arm == 'fragments':
                guard = entry.guard_fragment().original_prepared_query
                observed = consume_query(guard.sql, guard.parameters, 'applicability_check')
                actual = {k: observed[k] for k in ('columns', 'rows', 'truncated')}
                passed = observed['error'] is None and canonical(actual) == entry.expected
                action['guard_passed'] = passed
                counts['applicability_checks'] += 1
                counts['failed_applicability_checks'] += int(not passed)
                if not passed:
                    feedback(observed, 'Witnessed applicability rows do not match. This use was rejected; solve from current observations.')
                    continue
                if query_index >= 8:
                    feedback(observed, 'Applicability matched, but no SELECT allowance remains to execute the fragment.')
                    continue
            action['executed_fragment_digest'] = fragment.digest
            feedback(consume_query(request.sql, request.parameters,
                                   'fragment_composition' if action['action'] == 'COMPOSE' else 'fragment_use'))
            counts['executed_fragments'] += 1
            counts['executed_compositions'] += int(action['action'] == 'COMPOSE')
            counts['changed_binding_uses'] += int(canonical(action['params']) != canonical(fragment.compile().parameters))
        exact(trace['actions'], actions, 'saved action ledger differs from model outputs and guard decisions')
        exact(trace['answer'], submitted, 'saved answer was not the returned model ANSWER')
        reward = float(answered and abs(submitted - spec._expected) <= 1e-6 * (1 + abs(spec._expected)))
        exact(trace['reward'], reward, 'correctness feedback differs from evaluator answer')
        if terminal is None:
            terminal = 'completed' if answered else 'no_valid_answer'
            correct_feedback = {'correct': reward == 1., 'meaning': 'Correct on this episode only.' if reward == 1. else 'The submitted answer was INCORRECT.'}
            exact(trace.get('feedback'), correct_feedback, 'Boolean correctness feedback differs')
            conversation.append({'role': 'user', 'content': canonical(correct_feedback)})
            if learn:
                # Reflection cannot see the later verification query or its
                # result: reconstruct the exact prefix visible at proposal time.
                legal_trace = {**trace, 'status': terminal, 'queries': deepcopy(queries[:query_index])}
                legal_trace.pop('evaluator', None)
                legal_trace.pop('abstraction_proposal', None)
                synthesizing = memory.arm in ('fragments', 'fragments_unchecked')
                reflection = (proposal_messages_v9(legal_trace) if synthesizing and reward == 1. and query_index < 8
                              else None if synthesizing else memory.reflection(legal_trace, conversation))
                text = None
                if reflection is not None:
                    schema = PROPOSAL_SCHEMA if synthesizing else reflection_schema_v9(memory.arm)
                    outcome, content = next_call(reflection, 'reflection', schema)
                    if outcome == 'completed':
                        text = content
                    elif outcome == 'budget':
                        reflection_stop = content
                    else:
                        terminal, failure_detail = 'backend_or_runtime_failure', content
                if terminal != 'backend_or_runtime_failure':
                    if synthesizing and text is not None:
                        abstraction = {'status': 'proposed'}
                        try:
                            proposal = prepare_proposal(text, legal_trace)
                            if proposal is None:
                                abstraction['status'] = 'abstained'
                            else:
                                index = query_index
                                abstraction.update(model_fields=json.loads(proposal.model_fields),
                                                   eligible_query_count=index)
                                consume_query(proposal.request.sql, proposal.request.parameters,
                                              'abstraction_reconstruction', learning_check=True)
                                counts['reconstruction_selects'] += 1
                                legal_trace['queries'] = deepcopy(queries[:query_index])
                                entry = admit_verified(memory, proposal, legal_trace, index)
                                abstraction.update(status='accepted', fragment_digest=entry.fragment().digest,
                                                   verification_query_index=index)
                                counts['accepted_reconstruction_witnesses'] += 1
                        except AuditError:
                            raise
                        except (ValueError, TypeError, KeyError, FragmentError) as exc:
                            abstraction.update(status='rejected', reason=str(exc))
                            memory.events.append({'kind': 'rejected_abstraction', 'reason': str(exc)})
                    try:
                        memory.finish(trace, conversation, None if synthesizing else text)
                    except (ValueError, TypeError, KeyError, FragmentError) as exc:
                        terminal, failure_detail = 'backend_or_runtime_failure', type(exc).__name__
        require(trace['status'] == terminal, 'episode status hides a failed/stopped/completed path')
        if terminal == 'resource_stop':
            require(trace.get('stop_reason') == failure_detail, 'episode resource-stop reason mismatch')
        if terminal == 'backend_or_runtime_failure':
            require(trace.get('error_type') == failure_detail, 'episode backend/runtime error type mismatch')
        exact(trace.get('reflection_stop'), reflection_stop, 'reflection stop was omitted or invented')
        exact(trace.get('abstraction_proposal'), abstraction, 'saved abstraction proposal/admission differs from its actual model output and check')
        require(call_index == len(records) and query_index == len(queries), 'unused extra calls or query records')
        integer(trace['select_attempts'], 'SELECT total')
        require(trace['select_attempts'] == query_index, 'SELECT total differs from charged execution ledger')
        integer(trace['vm_steps'], 'VM steps')
        require(trace['vm_steps'] <= query_index * 200_000, 'reported VM steps exceed bounded executions')
        setup = finite(trace['setup_seconds'], 'setup seconds')
        elapsed = finite(trace['elapsed_seconds'], 'episode elapsed seconds')
        query_seconds = finite(trace['query_seconds'], 'query seconds')
        model_seconds = sum(finite(call.get('tokenization_seconds'), 'tokenization time') +
                            finite(call.get('inference_seconds', 0.), 'inference time') for call in records)
        require(elapsed + 1e-6 >= setup + query_seconds + model_seconds,
                'episode timing excludes recorded setup/query/model time')
        if reward == 1. and learn:
            digest = hashlib.sha256(canonical({k: trace[k] for k in ('question', 'queries', 'answer', 'reward')}).encode()).hexdigest()
            evidence[digest] = trace
        verify_entries(memory, evidence)
        require(trace['after_memory_digest'] == memory.digest(), 'after-memory digest mismatch')
        exact(trace['memory_snapshot'], memory.snapshot(), 'saved memory differs from reconstructed own experience')
        require(trace['memory_bytes'] == memory.memory_bytes(), 'memory byte count mismatch')
        if not learn:
            require(trace['before_memory_digest'] == trace['after_memory_digest'], 'evaluation modified learned memory')
        counts['episodes'] += 1
        counts['correct_episodes'] += int(reward == 1.)
        counts['resource_stopped_episodes'] += int(terminal == 'resource_stop')
        counts['runtime_failed_episodes'] += int(terminal == 'backend_or_runtime_failure')
        counts['unanswered_episodes'] += int(terminal == 'no_valid_answer')
    finally:
        db.close()



def schedule(stage):
    result = [('ordinary', i) for i in range(8)]
    if stage == 'full':
        result += [('old_before', i) for i in range(8)]
        result += [('ordinary', i) for i in range(8, 24)]
        result += [('old_after', i) for i in range(8)]
        result += [('final', i) for i in range(8)]
    return result


def warm_result(rows, minimum):
    warm = [row for row in rows if row['phase'] == 'ordinary' and row['episode_index'] < 8]
    complete = len(warm) == 8 and sorted(row['episode_index'] for row in warm) == list(range(8)) and all(
        row['status'] in ('completed', 'no_valid_answer') and not row.get('reflection_stop') for row in warm)
    correct = sum(row['reward'] == 1. for row in warm)
    return {'complete': complete, 'correct': correct, 'n': len(warm), 'minimum_correct': minimum,
            'meets_warm_accuracy_gate': complete and correct >= minimum}


def measured_equal(observed, expected, name):
    """Exact discrete accounting; tolerate only arithmetic rounding of durations."""
    require(type(observed) is dict and set(observed) == set(expected), name + ' fields differ')
    for field, value in expected.items():
        if field.endswith('_seconds'):
            actual = finite(observed[field], name + ':' + field)
            require(math.isclose(actual, value, rel_tol=1e-10, abs_tol=1e-7), name + ':' + field + ' differs')
        else:
            exact(observed[field], value, name + ':' + field + ' differs')


def validate_manifest(manifest):
    require(manifest.get('version') == 9 and manifest.get('kind') == 'development_memory_qualification_and_transfer',
            'only v9 development stream artifacts are accepted')
    require(manifest.get('status') in ('completed', 'competence_gate_failed', 'stopped', 'failed', 'incomplete'),
            'run is unfinished or source-invalidated')
    require(manifest.get('native_benchmark') is False and manifest.get('claim_confirmed') is False,
            'development record asserts a native benchmark or confirmed claim')
    require(manifest.get('stage') in ('qualification', 'full'), 'unknown run stage')
    for field in ('seeds', 'conditions', 'arms'):
        values = manifest.get(field)
        require(type(values) is list and values and len(set(values)) == len(values), 'invalid manifest ' + field)
    require(all(type(seed) is int and 92000 <= seed <= 92003 for seed in manifest['seeds']), 'undeclared/heldout seed')
    require(set(manifest['conditions']) <= {'reuse', 'nonreuse', 'near_match'}, 'unknown condition')
    require(set(manifest['arms']) <= set(ARMS), 'unknown memory arm')
    require(len(manifest['seeds']) * len(manifest['conditions']) <= 4, 'development stream cap exceeded')
    require(type(manifest.get('minimum_warm_correct')) is int and 1 <= manifest['minimum_warm_correct'] <= 8,
            'invalid warm competence threshold')
    require(type(manifest.get('gate_after_warm')) is bool, 'warm gate setting must be Boolean')
    require(manifest.get('max_selects_per_question') == 8 and manifest.get('max_actions_per_question') == 10,
            'interaction limits differ')
    require(manifest.get('ordinary_query_contract') == 'bounded_actions_v9_exact_sql_and_params_to_read_only_sqlite',
            'ordinary action contract differs')
    expected = dict.fromkeys(PHASES, 8)
    expected['ordinary'] = 24
    if manifest['stage'] == 'qualification':
        expected = {'ordinary': 8, 'old_before': 0, 'old_after': 0, 'final': 0}
    exact(manifest.get('required_phase_counts_per_arm_stream'), expected, 'phase counts differ from selected stage')
    limits = manifest.get('limits')
    require(type(limits) is dict and set(limits) == {'wall_seconds', 'ordinary_tokens', 'panel_tokens', 'ordinary_calls',
            'panel_calls', 'total_tokens', 'total_calls', 'solve_output_tokens', 'reflection_output_tokens'},
            'missing/substituted resource limits')
    require(0 < finite(limits['wall_seconds'], 'wall cap') <= 1800, 'run wall cap exceeds development limit')
    for name in limits:
        if name != 'wall_seconds':
            integer(limits[name], name, minimum=1)
    require(max(limits['solve_output_tokens'], limits['reflection_output_tokens']) <= 8192, 'per-call cap exceeds interface')
    config = manifest.get('client_config')
    require(type(config) is dict and set(config) == {'model', 'context_tokens', 'max_output', 'response_mode',
            'endpoint', 'timeout', 'decoding'}, 'missing/substituted client configuration')
    require(type(config['model']) is str and config['model'], 'missing model alias')
    integer(config['context_tokens'], 'context tokens', minimum=1025)
    integer(config['max_output'], 'client output cap', minimum=max(limits['solve_output_tokens'], limits['reflection_output_tokens']))
    require(config['response_mode'] in ('schema', 'json'), 'unknown response mode')
    require(type(config['endpoint']) is str and config['endpoint'].startswith('http://127.0.0.1:'), 'non-loopback model endpoint')
    finite(config['timeout'], 'client timeout', minimum=.001)
    decoding = config['decoding']
    require(type(decoding) is dict and set(decoding) == {'temperature', 'top_p', 'top_k', 'min_p',
            'presence_penalty', 'seed', 'thinking'}, 'missing decoding configuration')
    for field, low, high in (('temperature', 0, 2), ('top_p', 0, 1), ('min_p', 0, 1), ('presence_penalty', -2, 2)):
        require(type(decoding[field]) in (int, float) and math.isfinite(decoding[field]) and low <= decoding[field] <= high,
                'invalid decoding ' + field)
    require(decoding['top_p'] > 0, 'top_p must be positive')
    integer(decoding['top_k'], 'top_k')
    require(type(decoding['seed']) is int and 0 <= decoding['seed'] < 2**32, 'invalid sampling seed')
    require(type(decoding['thinking']) is bool, 'thinking must be Boolean')
    require(type(manifest.get('system_prompt')) is str and manifest['system_prompt'].strip(), 'missing common solver prompt')
    require(hashlib.sha256(manifest['system_prompt'].encode()).hexdigest() == manifest.get('system_prompt_sha256'),
            'shared solver prompt hash differs')
    if manifest.get('stop_after_debug') is not None:
        integer(manifest['stop_after_debug'], 'debug stop', minimum=1)


def check_freeze(manifest, freeze_path, report):
    if freeze_path is None:
        return
    frozen = read_json(Path(freeze_path).read_text())
    exact(frozen.get('source_sha256'), manifest['source_sha256'], 'external source freeze differs')
    report['checked_freeze_sha256'] = sha(freeze_path)
    if 'seeds' in frozen:
        for field in ('client_config', 'system_prompt_sha256', 'limits', 'seeds', 'conditions', 'arms',
                      'stage', 'minimum_warm_correct', 'gate_after_warm'):
            exact(frozen.get(field), manifest[field], 'external freeze differs: ' + field)
        return
    # The actual prospective freeze includes a pinned human-readable protocol
    # and server receipt. Its declared configuration is checked explicitly here.
    exact(manifest['seeds'], [frozen.get('seed')], 'prospective stream seed differs')
    exact(manifest['conditions'], [frozen.get('condition')], 'prospective condition differs')
    for field in ('stage', 'arms', 'minimum_warm_correct', 'gate_after_warm'):
        exact(frozen.get(field), manifest[field], 'external freeze differs: ' + field)
    require(frozen.get('claim_confirmed') is False and type(frozen.get('task_model_calls_for_this_stream_before_freeze')) is int
            and frozen['task_model_calls_for_this_stream_before_freeze'] == 0, 'stream was not prospectively frozen')
    support = frozen.get('support_sha256')
    required = {'docs/v9/STREAM_PROTOCOL.md', 'artifacts/v9/model-9b-provenance.json',
                'artifacts/v9/server-9b-64k-process.json', 'artifacts/v9/diagnostics/replay-all.json',
                'artifacts/v9/prepilot-pytest.xml', 'artifacts/v9/prepilot-v9-pytest.xml'}
    require(type(support) is dict and required <= set(support), 'incomplete prospective support freeze')
    for name, digest in support.items():
        path = (ROOT / name).resolve()
        require(path.is_relative_to(ROOT) and path.is_file() and sha(path) == digest, 'support freeze drift: ' + name)
    report['checked_support_sha256'] = support
    config = manifest['client_config']
    portable = set(manifest['source_sha256']) == set(PORTABLE_SOURCE_FILES)
    process_path = frozen.get('server_process_receipt') if portable else 'artifacts/v9/server-9b-64k-process.json'
    require(type(process_path) is str and process_path in support, 'selected server process receipt is not frozen')
    process = read_json((ROOT / process_path).read_text())
    args = process['args']
    require(config['model'] == args[args.index('--alias') + 1], 'server alias differs')
    require(config['context_tokens'] == int(args[args.index('--ctx-size') + 1]) == 65536, 'server/client context differs')
    require(args[args.index('--reasoning-budget') + 1] == ('-1' if portable else '1536'), 'server reasoning budget differs')
    if portable:
        require(frozen.get('wire_schema_policy') == WIRE_SCHEMA_POLICY, 'portable wire policy is not prospectively frozen')
        require(frozen.get('reflection_thinking') is False, 'portable reflection policy is not prospectively frozen')
        require(frozen.get('response_mode') == 'schema', 'portable freeze changed response mode')
    exact(config['decoding'], {'temperature': .6, 'top_p': .95, 'top_k': 20, 'min_p': 0.,
                              'presence_penalty': 1.5, 'seed': 42, 'thinking': True}, 'prospective decoding differs')
    require(config['response_mode'] == frozen.get('response_mode', 'schema'), 'prospective response mode differs')
    if config['response_mode'] == 'json':
        require('docs/v9/JSON_REPAIR_PROTOCOL.md' in support and 'artifacts/v9/budget-before-json-stream.json' in support,
                'JSON repair lacks its own prospective protocol/budget receipt')
    require(config['max_output'] == 4096 and config['endpoint'] == 'http://127.0.0.1:18085' and config['timeout'] == 120.,
            'prospective transport/output configuration differs')
    require(manifest['limits']['wall_seconds'] == 1800, 'prospective wall limit differs')
    exact({k: v for k, v in manifest['limits'].items() if k != 'wall_seconds'},
          {'ordinary_tokens': 1000000, 'panel_tokens': 1000000,
           'ordinary_calls': 280, 'panel_calls': 260, 'total_tokens': 3000000, 'total_calls': 1200,
           'solve_output_tokens': 2048, 'reflection_output_tokens': 4096}, 'prospective resource limits differ')
    tree = ast.parse((ROOT / 'experiments/competence_interactive_v9.py').read_text())
    prompt = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == 'EVIDENCE_INSTRUCTIONS' for target in node.targets))
    require(manifest['system_prompt'] == prompt, 'prospective solver prompt differs from frozen source')
    provenance = read_json((ROOT / 'artifacts/v9/model-9b-provenance.json').read_text())
    require(provenance.get('hash_verified') is True and provenance.get('weights_modified_by_this_study') is False,
            'model provenance does not assert verified unmodified weights')
    report['model_provenance_sha256'] = support['artifacts/v9/model-9b-provenance.json']
    report['original_sqlite_version'] = frozen.get('sqlite_version')


def audit_directory(directory, *, freeze_path=None):
    directory = Path(directory).resolve()
    counts, failures, protocol_issues = Counter(), [], []
    raw_hashes = {}
    report = {'status': 'failed', 'directory': str(directory), 'claim_confirmed': False,
              'scope': 'independent SQLite replay, exact saved legal prompts, own-memory transitions and chronological shared-budget consistency',
              'auditor_source_sha256': sha(__file__),
              'auditor_dependencies_sha256': {'experiments/audit_sql_abstractions_v8.py': sha(ROOT / 'experiments/audit_sql_abstractions_v8.py')},
              'pilot_completeness': 'unverified', 'required_records_complete': False,
              'planned_records_complete': False, 'known_usage_complete': False,
              'sqlite_outcomes_complete': False, 'resource_comparison_complete': False,
              'limitations': [
                  'Fixture generation, action parser, compiler and memory definitions are shared frozen code; SQL connections and checks are independent.',
                  'Does not authenticate original execution, backend tokenization or token counts, model weights, or recorded timing.',
                  'Unknown failed generation usage remains unknown; any reservation figure is a protocol allowance, not measured usage.',
                  'A single correlated development stream cannot confirm statistical superiority, noninferiority or interaction savings.',
                  'Nonreproducible machine-specific SQL timeout errors are unverified and exclude resource comparison eligibility.',
              ]}
    try:
        manifest = read_json((directory / 'manifest.json').read_text())
        summary = read_json((directory / 'summary.json').read_text())
        validate_manifest(manifest)
        report.update(manifest_sha256=sha(directory / 'manifest.json'), summary_sha256=sha(directory / 'summary.json'),
                      manifest_status=manifest['status'], checked_source_sha256=manifest['source_sha256'])
        require(manifest.get('summary_sha256') == report['summary_sha256'], 'summary digest differs')
        require(set(manifest['source_sha256']) in (set(SOURCE_FILES), set(PORTABLE_SOURCE_FILES)),
                'incomplete/substituted executed source freeze')
        for source, digest in manifest['source_sha256'].items():
            require(sha(ROOT / source) == digest, 'frozen executed source drift: ' + source)
        exact(manifest.get('source_sha256_after'), manifest['source_sha256'], 'source after-run map differs')
        require(manifest.get('source_unchanged') is True and manifest.get('client_config_unchanged') is True,
                'source/client configuration changed during the run')
        for name in ('fragments_v8', 'memory_v8', 'memory_v9', 'abstraction_v8', 'actions_v9', 'sql_env_v8', 'sql_env_v9'):
            require(Path(sys.modules['witness_cl.' + name].__file__).resolve() == ROOT / 'src/witness_cl' / (name + '.py'),
                    'unrelated package module imported: ' + name)
        check_freeze(manifest, freeze_path, report)
        file_rows = {}
        for path in sorted(directory.glob('*.jsonl')):
            raw_hashes[path.name] = sha(path)
            file_rows[path.name] = [read_json(line) for line in path.read_text().splitlines() if line.strip()]
            require(file_rows[path.name], 'empty raw file outside incremental exporter contract')
        exact(manifest.get('raw_sha256'), raw_hashes, 'raw file hash map differs')
        limits = manifest['limits']
        total = Budget(max_calls=limits['total_calls'], max_total_tokens=limits['total_tokens'])
        states, consumed = {}, Counter()
        count, stopped = 0, None
        oracle_cache = set()
        all_rows = []
        for seed in manifest['seeds']:
            if stopped:
                break
            for condition in manifest['conditions']:
                if stopped:
                    break
                stream = make_stream(seed, condition, split='development')
                for arm in manifest['arms']:
                    key = (seed, condition, arm)
                    states[key] = {'memory': ExperienceMemoryV9(arm, manifest['system_prompt']), 'rows': [], 'evidence': {},
                                   'ordinary': Budget(max_calls=limits['ordinary_calls'], max_total_tokens=limits['ordinary_tokens']),
                                   'panel': Budget(max_calls=limits['panel_calls'], max_total_tokens=limits['panel_tokens'])}
                for step, (phase, index) in enumerate(schedule(manifest['stage'])):
                    if step == 8 and manifest['stage'] == 'full' and manifest['gate_after_warm']:
                        if not all(warm_result(states[(seed, condition, arm)]['rows'], manifest['minimum_warm_correct'])['meets_warm_accuracy_gate']
                                   for arm in manifest['arms']):
                            stopped = ('competence_gate_failed', 'one or more configured arms missed the warm competence gate')
                            break
                    offset = step % len(manifest['arms'])
                    order = manifest['arms'][offset:] + manifest['arms'][:offset]
                    for arm in order:
                        key = (seed, condition, arm)
                        state = states[key]
                        filename = f'{seed}-{condition}-{arm}.jsonl'
                        available = file_rows.get(filename, [])
                        if consumed[filename] == len(available):
                            reason = manifest.get('failure', {}).get('reason')
                            require(manifest['status'] == 'stopped' and reason in (
                                'global_study_wall_ceiling', 'global_wall_ceiling_including_export'),
                                'missing raw episode is not a legal global termination')
                            protocol_issues.append('wall-stop timing is recorded but original deadline cannot be authenticated')
                            stopped = ('stopped', reason)
                            break
                        row = available[consumed[filename]]
                        exact([row.get(k) for k in ('seed', 'condition', 'arm', 'phase', 'episode_index')],
                              [seed, condition, arm, phase, index], 'raw row violates scheduled identity/order')
                        spec = (stream.ordinary[index] if phase == 'ordinary' else stream.final_panel[index]
                                if phase == 'final' else stream.old_panel[index])
                        reference_key = (seed, condition, 'old' if phase.startswith('old_') else phase, index)
                        if reference_key not in oracle_cache:
                            db = SQLiteReplayV9(spec)
                            try:
                                actual = db.query(spec._gold_sql, {})
                                require(actual['error'] is None and scalar_equal(verified_scalar(actual), spec._expected),
                                        'independent SQLite reference disagrees with Python evaluator')
                            finally:
                                db.close()
                            oracle_cache.add(reference_key)
                        before_counts = counts.copy()
                        check_episode(row, spec, state['memory'], ChargedBudget(state['ordinary' if phase == 'ordinary' else 'panel'], total),
                                      manifest, counts, state['evidence'], protocol_issues)
                        state.setdefault('counts', Counter()).update(counts - before_counts)
                        state['rows'].append(row)
                        all_rows.append(row)
                        consumed[filename] += 1
                        count += 1
                        if row['status'] == 'backend_or_runtime_failure':
                            stopped = ('failed', 'backend/runtime failure; all remaining runs stopped')
                        elif row['status'] == 'resource_stop' or row.get('reflection_stop'):
                            stopped = ('stopped', row.get('stop_reason') or row.get('reflection_stop'))
                        elif manifest.get('stop_after_debug') is not None and count >= manifest['stop_after_debug']:
                            stopped = ('stopped', 'explicit_debug_stop')
                        if stopped:
                            break
                    if stopped:
                        break
        require(all(consumed[name] == len(rows) for name, rows in file_rows.items()),
                'raw rows occur after the global stop or outside the declared schedule')
        require(type(manifest.get('completed_episode_records')) is int and manifest['completed_episode_records'] == count,
                'completed record count differs')
        elapsed = finite(manifest.get('elapsed_seconds'), 'run elapsed seconds')
        require(elapsed + 1e-6 >= sum(row['elapsed_seconds'] for row in all_rows), 'run time excludes recorded episodes')
        wall_ok = elapsed <= limits['wall_seconds']
        require(manifest.get('wall_cap_satisfied') is wall_ok, 'wall-cap satisfaction flag differs')
        if not wall_ok:
            protocol_issues.append('recorded run elapsed time exceeds the declared wall cap including export')
            expected_status, expected_reason = 'stopped', 'global_wall_ceiling_including_export'
        else:
            expected_status, expected_reason = stopped if stopped else ('completed', None)
        require(manifest['status'] == expected_status, 'manifest status hides or invents global termination')
        if expected_reason is None:
            require('failure' not in manifest, 'completed run retains an unexplained failure')
        else:
            failure_type = '_QualificationStop' if expected_status == 'competence_gate_failed' else 'RuntimeError' if expected_status == 'failed' else 'BudgetStop'
            exact(manifest.get('failure'), {'type': failure_type, 'reason': expected_reason}, 'global failure reason differs')
        require(type(summary) is list and len(summary) == len(states), 'summary omits or adds initialized arm streams')
        arm_reports = []
        for record, (key, state) in zip(summary, states.items()):
            rows = state['rows']
            seed, condition, arm = key
            grouped = {phase: [row for row in rows if row['phase'] == phase] for phase in PHASES}
            expected_summary = {
                'seed': seed, 'condition': condition, 'arm': arm,
                'memory': state['memory'].snapshot(), 'warm': warm_result(rows, manifest['minimum_warm_correct']),
                'phase_counts': {phase: len(items) for phase, items in grouped.items()},
                'phase_reward': {phase: sum(row['reward'] for row in items) / len(items) if items else None for phase, items in grouped.items()},
                'phase_selects': {phase: sum(row['select_attempts'] for row in items) for phase, items in grouped.items()},
                'phase_failures': {phase: sum(row['status'] != 'completed' for row in items) for phase, items in grouped.items()},
            }
            require(type(record) is dict and set(record) == set(expected_summary) | {'ordinary_budget', 'panel_budget'}, 'summary fields differ')
            for field, value in expected_summary.items():
                exact(record[field], value, 'arm summary differs: ' + field)
            for budget_name, state_name in (('ordinary_budget', 'ordinary'), ('panel_budget', 'panel')):
                measured_equal(record[budget_name], asdict(state[state_name]), budget_name)
            paired = len(grouped['old_before']) == len(grouped['old_after']) == 8
            retention = None
            if paired:
                exact([row['evaluator'] for row in grouped['old_before']], [row['evaluator'] for row in grouped['old_after']],
                      'old-before and old-after probes differ')
                retention = {
                    'before_correct': sum(row['reward'] == 1. for row in grouped['old_before']),
                    'after_correct': sum(row['reward'] == 1. for row in grouped['old_after']),
                    'correct_to_incorrect': sum(a['reward'] == 1. and b['reward'] == 0. for a, b in zip(grouped['old_before'], grouped['old_after'])),
                    'incorrect_to_correct': sum(a['reward'] == 0. and b['reward'] == 1. for a, b in zip(grouped['old_before'], grouped['old_after'])),
                    'paired_n': 8,
                }
            cost_groups = {**grouped,
                'warm_ordinary': [row for row in grouped['ordinary'] if row['episode_index'] < 8],
                'later_ordinary': [row for row in grouped['ordinary'] if row['episode_index'] >= 8]}
            phase_costs = {}
            for name, items in cost_groups.items():
                calls = [call for row in items for call in row['model_calls']]
                generated = [call for call in calls if call['generation_attempted']]
                phase_costs[name] = {
                    'n': len(items), 'correct': sum(row['reward'] == 1. for row in items),
                    'select_attempts': sum(row['select_attempts'] for row in items),
                    'generation_attempts': len(generated),
                    'reflection_attempts': sum(call['phase'].endswith(':reflection') for call in generated),
                    'known_total_tokens': sum(call['usage']['total_tokens'] for call in generated if call['usage'] is not None),
                    'unknown_usage_calls': sum(call['usage'] is None for call in generated),
                    'episode_seconds': sum(row['elapsed_seconds'] for row in items),
                    'query_seconds': sum(row['query_seconds'] for row in items),
                }
            arm_reports.append({**{k: expected_summary[k] for k in ('seed', 'condition', 'arm', 'warm', 'phase_counts', 'phase_reward', 'phase_selects', 'phase_failures')},
                'ordinary_budget': asdict(state['ordinary']), 'panel_budget': asdict(state['panel']),
                'observed_retention': retention, 'phase_costs': phase_costs, 'final_memory_bytes': state['memory'].memory_bytes(),
                'accepted_entries_retained': len(state['memory'].entries), 'counts': dict(state.get('counts', {})),
                'episode_seconds': sum(row['elapsed_seconds'] for row in rows),
                'query_seconds': sum(row['query_seconds'] for row in rows)})
        measured_equal(manifest.get('total_budget'), asdict(total), 'shared total budget')
        known = total.unknown_usage_calls == 0
        simulated = counts['test_double_calls'] > 0
        require(manifest.get('usage_verified') is known, 'usage completeness flag hides unknown attempts')
        require(manifest.get('contains_test_double_calls') is simulated, 'simulated-call flag differs')
        resources = manifest['status'] not in ('stopped', 'failed') and known and not any(
            row['status'] in ('resource_stop', 'backend_or_runtime_failure') or row.get('reflection_stop') for row in all_rows)
        planned = len(states) == len(manifest['seeds']) * len(manifest['conditions']) * len(manifest['arms']) and all(
            row['phase_counts'] == manifest['required_phase_counts_per_arm_stream'] for row in summary)
        complete = planned and resources
        require(manifest.get('resources_complete') is resources, 'resource completeness flag differs')
        require(manifest.get('required_records_complete') is complete, 'required-record completeness flag differs')
        qualified = manifest['status'] == 'completed' and complete and not simulated and all(row['warm']['meets_warm_accuracy_gate'] for row in summary)
        require(manifest.get('warm_qualified') is qualified, 'warm qualification flag differs')
        sqlite_complete = counts['timing_dependent_errors_unverified'] == 0
        report.update(status='passed', planned_records_complete=planned, required_records_complete=complete,
                      pilot_completeness='complete' if complete else 'partial', known_usage_complete=known,
                      sqlite_outcomes_complete=sqlite_complete,
                      resource_comparison_complete=bool(complete and resources and sqlite_complete and not simulated
                                                        and not protocol_issues and freeze_path is not None),
                      warm_qualified=qualified, stream_results=arm_reports, total_budget=asdict(total),
                      elapsed_seconds=elapsed, wall_cap_satisfied=wall_ok, independent_reference_cases=len(oracle_cache),
                      response_mode=manifest['client_config']['response_mode'])
    except (AuditError, OSError, ValueError, TypeError, KeyError, IndexError, StopIteration, OverflowError) as exc:
        failures.append(type(exc).__name__ + ': ' + str(exc))
    report.update(raw_sha256=raw_hashes, counts=dict(counts), failures=failures,
                  protocol_issues=list(dict.fromkeys(protocol_issues)))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit_directory(args.directory, freeze_path=args.freeze)
    output = json.dumps(result, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
    print(output, end='')
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
