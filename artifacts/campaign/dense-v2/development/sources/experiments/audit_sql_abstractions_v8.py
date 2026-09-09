#!/usr/bin/env python3
"""Read-only replay of saved v8 development pilots; no inference or holdout.

SQL executes on independently constructed SQLite connections, without importing
the runner or EpisodeSession. Prompt/memory reconstruction deliberately shares
the frozen Fragment/ExperienceMemory definitions: it is not an independent
implementation of those algorithms. Receipts establish saved consistency, not
authenticated execution, exact backend tokenization or original timing.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
# Direct script execution must use this checked-out package, not an unrelated
# installed copy. Imported-module origins are checked alongside source hashes.
sys.path.insert(0, str(ROOT / "src"))

from witness_cl.fragments_v8 import Fragment, FragmentError
from witness_cl.abstraction_v8 import PROPOSAL_SCHEMA, proposal_messages, prepare_proposal, admit_verified
from witness_cl.memory_v8 import (
    ACTION_SCHEMA, ARMS, ExperienceMemory, canonical, parse_action, reflection_schema,
)
from witness_cl.sql_env_v8 import make_stream, evaluator_metadata

SOURCE_FILES = (
    'src/witness_cl/sql_env_v8.py', 'src/witness_cl/fragments_v8.py',
    'src/witness_cl/memory_v8.py', 'src/witness_cl/model_v8.py', 'src/witness_cl/abstraction_v8.py',
    'experiments/sql_abstractions_v8.py', 'docs/v8/EVALUATION.md',
)
PHASE_COUNTS = {'ordinary': 24, 'old_before': 8, 'old_after': 8, 'final': 8}
TERMINAL = {'completed', 'no_valid_answer', 'resource_stop', 'backend_or_runtime_failure'}
FUNCTIONS = frozenset('abs avg char coalesce concat concat_ws count format glob hex ifnull iif instr '
                     'length like lower ltrim max min nullif printf quote replace round rtrim sign '
                     'substr substring sum total trim typeof unicode upper row_number rank dense_rank '
                     'percent_rank cume_dist first_value last_value lag lead nth_value ntile'.split())


class AuditError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AuditError(message)


def exact(first, second, message):
    require(canonical(first) == canonical(second), message)


def finite(value, name, *, minimum=0):
    require(type(value) in (int, float) and math.isfinite(value) and value >= minimum,
            name + ' must be a finite nonnegative number')
    return value


def integer(value, name, *, minimum=0):
    require(type(value) is int and value >= minimum, name + ' must be an exact integer')
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def read_json(text):
    return json.loads(text, object_pairs_hook=_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(AuditError('nonfinite JSON')))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SQLiteReplay:
    """Own connection, limits and authorizer; never uses the runtime query API."""
    def __init__(self, spec):
        self.db = sqlite3.connect(':memory:')
        self.db.enable_load_extension(False)
        for category, limit in ((sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16384),
                                (sqlite3.SQLITE_LIMIT_LENGTH, 65536),
                                (sqlite3.SQLITE_LIMIT_COLUMN, 128),
                                (sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 64),
                                (sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 16),
                                (sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 128)):
            self.db.setlimit(category, limit)
        for table in spec._tables:
            self.db.execute(table.ddl)
            self.db.executemany(f'INSERT INTO "{table.name}" VALUES (' +
                                ','.join('?' for _ in table.columns) + ')', table.rows)
        self.db.commit()
        self.db.execute('PRAGMA query_only=ON')
        self.db.execute('PRAGMA trusted_schema=OFF')
        tables = {t.name for t in spec._tables}

        def authorize(action, first, second, database, source):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ and first in tables and (
                    database == 'main' or database is None and second == ''):
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (second or '').lower() in FUNCTIONS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        self.db.set_authorizer(authorize)

    def close(self):
        self.db.close()

    def query(self, sql, parameters):
        steps = 0
        started = time.monotonic()

        def progress():
            nonlocal steps
            steps += 100
            # Deterministic VM cap matches the experiment. A wider emergency
            # wall cap avoids reproducing machine-specific .25-second races.
            return int(steps >= 200_000 or time.monotonic() - started > 2.)

        try:
            if type(sql) is not str or len(sql.encode('utf-8')) > 16384:
                raise ValueError('SQL must be UTF-8 text of at most 16384 bytes')
            stripped = re.sub(r'\A(?:\s|--[^\n]*(?:\n|$)|/\*.*?\*/)*', '', sql, flags=re.S)
            if not re.match(r'(?i)(SELECT|WITH)\b', stripped):
                raise ValueError('only one SELECT or nonrecursive WITH SELECT is permitted')
            params = {} if parameters is None else parameters
            if (type(params) is not dict or len(params) > 128 or
                    any(type(k) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', k)
                        for k in params) or
                    any(type(v) not in (int, float, str, type(None)) or
                        type(v) is float and not math.isfinite(v) or
                        type(v) is int and not -(2**63) <= v < 2**63 or
                        type(v) is str and len(v.encode('utf-8')) > 4096 for v in params.values())):
                raise ValueError('bounded named scalar literal parameters required')
            self.db.set_progress_handler(progress, 100)
            cursor = self.db.execute(sql, params)
            if cursor.description is None:
                raise ValueError('a SELECT result is required')
            columns = [c[0] for c in cursor.description]
            fetched = cursor.fetchmany(51)
            rows = [list(r) for r in fetched[:50]]
            size = sum(len(c.encode('utf-8')) for c in columns)
            for row in rows:
                for value in row:
                    if type(value) not in (int, float, str, type(None)):
                        raise ValueError('only numeric, text and NULL result cells are permitted')
                    if type(value) is float and not math.isfinite(value):
                        raise ValueError('non-finite result cells are not permitted')
                    cell_size = len(value.encode('utf-8')) if type(value) is str else 8
                    if cell_size > 4096:
                        raise ValueError('result cell byte limit exceeded')
                    size += cell_size
            if size > 65536:
                raise ValueError('result byte limit exceeded')
            return {'columns': columns, 'rows': rows, 'error': None, 'truncated': len(fetched) > 50}
        except (sqlite3.Error, ValueError, OverflowError) as exc:
            return {'columns': [], 'rows': [], 'error': str(exc)[:256], 'truncated': False}
        finally:
            self.db.set_progress_handler(None, 0)


@dataclass
class Budget:
    max_calls: int
    max_total_tokens: int = 500_000
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    tokenization_seconds: float = 0.
    inference_seconds: float = 0.
    unknown_usage_calls: int = 0

    def before_unrecorded_stop(self, reason, output_limit):
        if reason == 'model_call_ceiling':
            require(self.calls >= self.max_calls, 'unjustified model-call ceiling')
        elif reason == 'model_token_ceiling':
            require(self.total_tokens + output_limit > self.max_total_tokens,
                    'unjustified token ceiling before a recorded preflight')
        else:
            require(reason == 'wall_time_ceiling', 'unverifiable unrecorded resource stop: ' + str(reason))


def check_call(record, expected_messages, phase, schema, budget, manifest, counts, protocol_issues):
    exact(record.get('messages'), expected_messages, 'model prompt is not its exact legal own-history input')
    require(record.get('phase') == phase, 'model call phase/order mismatch')
    exact(record.get('response_schema'), schema, 'model response schema differs from frozen interface')
    output = 1024 if phase.endswith(':reflection') else 384
    require(record.get('max_output_tokens') == output, 'per-call output cap changed')
    counts['recorded_model_calls'] += 1
    budget.tokenization_seconds += finite(record.get('tokenization_seconds'), 'tokenization time')
    status = record.get('status')
    require(status in ('completed', 'failed', 'preflight_failed'), 'unfinished or unknown model call status')
    if record.get('test_double'):
        counts['test_double_calls'] += 1
    prompt = record.get('preflight_tokens')
    if prompt is not None:
        integer(prompt, 'preflight tokens')
    attempted = record.get('generation_attempted')
    require(type(attempted) is bool, 'generation-attempt flag must be Boolean')
    if status == 'preflight_failed':
        require(not attempted and record.get('usage') is None, 'preflight failure contains generated usage')
        if record.get('error_type') == 'BudgetStop':
            reason = record.get('stop_reason')
            if reason == 'full_context_ceiling_no_truncation':
                require(prompt is not None and prompt + output > manifest['context_tokens'],
                        'context stop without overflowing full prompt')
            elif reason == 'model_token_ceiling':
                require(prompt is not None and budget.total_tokens + prompt + output > budget.max_total_tokens,
                        'token preflight stop without exceeding ceiling')
            elif reason == 'model_call_ceiling':
                require(budget.calls >= budget.max_calls, 'call preflight stop without exceeding ceiling')
            else:
                require(reason == 'wall_time_ceiling', 'unknown preflight resource stop')
            counts['resource_stop_calls'] += 1
            return 'budget', reason
        require(type(record.get('error_type')) is str, 'missing preflight failure type')
        return 'runtime', record['error_type']
    require(attempted and prompt is not None, 'generation lacks completed preflight')
    require(budget.calls < budget.max_calls, 'generation started beyond model-call ceiling')
    require(prompt + output <= manifest['context_tokens'], 'generation started with overflowing full prompt')
    require(budget.total_tokens + prompt + output <= budget.max_total_tokens,
            'generation started without reserved token allowance')
    budget.calls += 1
    counts['generation_attempts'] += 1
    budget.inference_seconds += finite(record.get('inference_seconds'), 'inference time')
    usage = record.get('usage')
    if usage is None:
        require(status == 'failed', 'completed model call has unknown token usage')
        budget.unknown_usage_calls += 1
        counts['unknown_usage_calls'] += 1
    else:
        require(type(usage) is dict, 'invalid token usage object')
        p, c, total = [integer(usage.get(key), key) for key in
                       ('prompt_tokens', 'completion_tokens', 'total_tokens')]
        require(total == p + c, 'token usage sum mismatch')
        budget.prompt_tokens += p
        budget.completion_tokens += c
        budget.total_tokens += total
        counts['known_prompt_tokens'] += p
        counts['known_completion_tokens'] += c
        counts['known_total_tokens'] += total
        violations = []
        if p < prompt or p + c > manifest['context_tokens']:
            violations.append('backend prompt/token accounting mismatch')
        if c > output or budget.total_tokens > budget.max_total_tokens:
            violations.append('backend exceeded reserved token allowance')
        if violations:
            require(status == 'failed', 'completed call violates frozen token/context limits')
            protocol_issues.extend(violations)
    if record.get('response_model') != manifest['model']:
        require(status == 'failed', 'completed response has a different model alias')
        if record.get('response_model') is not None:
            protocol_issues.append('failed backend response has a different model alias')
    if status == 'failed':
        require(type(record.get('error_type')) is str, 'failed call is missing its error type')
        return 'runtime', record['error_type']
    require(usage is not None and type(record.get('content')) is str, 'completed call lacks content/usage')
    return 'completed', record['content']


def verified_scalar(record):
    require(record['error'] is None and record['truncated'] is False and
            len(record['rows']) == 1 and len(record['rows'][0]) == 1,
            'reconstruction witness is not one complete numeric cell')
    value = record['rows'][0][0]
    require(type(value) in (int, float) and math.isfinite(value), 'nonfinite/nonnumeric reconstruction witness')
    return value


def scalar_equal(first, second):
    return abs(first - second) <= 1e-6 * (1 + abs(second))


def verify_entries(memory, evidence):
    """Independently link learned code, old evidence and its actual reconstruction.

    The relation need not be copied from a past query. It must be the exact
    model-proposed program whose charged wrapper reproduced an own confirmed
    scalar answer, with an independently observed applicability guard.
    """
    for entry in memory.entries:
        require(entry.provenance in evidence, 'entry has no own prior correct-episode provenance')
        episode = evidence[entry.provenance]
        require(episode['reward'] == 1. and episode['phase'] == 'ordinary',
                'entry derives from an incorrect or evaluation episode')
        proposal = episode.get('abstraction_proposal', {})
        require(proposal.get('status') == 'accepted', 'entry lacks accepted observed reconstruction')
        fields = proposal['model_fields']
        count = integer(proposal['eligible_query_count'], 'eligible query count', minimum=1)
        index = proposal['verification_query_index']
        require(type(index) is int and index == count and len(episode['queries']) == count + 1,
                'proposal verification is not immediately after the frozen witness prefix')
        require(all(type(fields[k]) is int and 0 <= fields[k] < count for k in ('source_index', 'guard_index')),
                'proposal references unavailable or future evidence')
        source = episode['queries'][fields['source_index']]
        guard = episode['queries'][fields['guard_index']]
        check = episode['queries'][index]
        value = verified_scalar(source)
        require(scalar_equal(value, episode['answer']), 'proposal source is not the own confirmed scalar answer')
        candidate = Fragment.from_query(fields['sql'], fields['params'])
        wrapper = candidate.compose(fields['outer_sql'], fields['outer_params'], alias='reused')
        exact([check['sql'], check['params'], check['purpose'], check['learning_check']],
              [wrapper.sql, wrapper.parameters, 'abstraction_reconstruction', True],
              'accepted entry has no exact charged reconstruction request')
        require(scalar_equal(verified_scalar(check), value), 'accepted entry did not reconstruct its own observed answer')
        require(guard['error'] is None and guard['truncated'] is False and guard['learning_check'] is False,
                'entry guard lacks a complete pre-proposal observation')
        exact(candidate.to_dict(), json.loads(entry.source), 'entry differs from the proposed relation')
        exact(Fragment.from_query(guard['sql'], guard['params']).to_dict(), json.loads(entry.guard),
              'entry guard is not the prior observed SQL/bindings')
        exact({k: guard[k] for k in ('columns', 'rows', 'truncated')}, json.loads(entry.expected),
              'entry guard expectation is not its observed result')
        require(entry.description == fields['description'] and candidate.digest == proposal['fragment_digest'],
                'entry metadata differs from accepted proposal')


def check_episode(trace, spec, memory, budget, manifest, counts, evidence, protocol_issues):
    require(trace.get('status') in TERMINAL, 'unknown or unfinished episode status')
    phase = trace['phase']
    learn = phase == 'ordinary'
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
    db = SQLiteReplay(spec)

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
            budget.before_unrecorded_stop(reason, 1024 if suffix == 'reflection' else 384)
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
                request = Fragment.from_query(action['sql'], action['params']).original_prepared_query
                feedback(consume_query(request.sql, request.parameters, 'ordinary_query'))
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
            conversation.append({'role': 'user', 'content': canonical({'correctness_feedback': reward})})
            if learn:
                # Reflection cannot see the later verification query or its
                # result: reconstruct the exact prefix visible at proposal time.
                legal_trace = {**trace, 'status': terminal, 'queries': deepcopy(queries[:query_index])}
                legal_trace.pop('evaluator', None)
                legal_trace.pop('abstraction_proposal', None)
                synthesizing = memory.arm in ('fragments', 'fragments_unchecked')
                reflection = (proposal_messages(legal_trace) if synthesizing and reward == 1. and query_index < 8
                              else None if synthesizing else memory.reflection(legal_trace, conversation))
                text = None
                if reflection is not None:
                    schema = PROPOSAL_SCHEMA if synthesizing else reflection_schema(memory.arm)
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


def schedule():
    return ([('ordinary', i) for i in range(8)] + [('old_before', i) for i in range(8)] +
            [('ordinary', i) for i in range(8, 24)] + [('old_after', i) for i in range(8)] +
            [('final', i) for i in range(8)])


def validate_manifest(manifest):
    require(manifest.get('version') == 8 and manifest.get('kind') == 'development_cost_and_competence_pilot',
            'only v8 development pilot artifacts are accepted')
    require(manifest.get('native_benchmark') is False and manifest.get('claim_confirmed') is False,
            'development artifact asserts a native or confirmed claim')
    require(manifest.get('status') in ('completed', 'stopped', 'failed', 'incomplete', 'invalidated'),
            'pilot is not finalized')
    for field in ('seeds', 'conditions', 'arms'):
        values = manifest.get(field)
        require(type(values) is list and values and len(values) == len(set(values)), 'invalid manifest ' + field)
    require(all(type(s) is int and 90000 <= s <= 90003 for s in manifest['seeds']), 'no holdout or undeclared seed allowed')
    require(set(manifest['conditions']) <= {'reuse', 'nonreuse', 'near_match'}, 'unknown pilot condition')
    require(set(manifest['arms']) <= set(ARMS), 'unknown pilot arm')
    require(len(manifest['seeds']) * len(manifest['conditions']) <= 4, 'pilot stream cap exceeded')
    require(0 < finite(manifest['wall_seconds_cap'], 'wall cap') <= 1800, 'pilot wall cap exceeded')
    for name, expected in {'ordinary_questions': 24, 'old_panel_questions': 8, 'final_panel_questions': 8,
                           'max_selects_per_question': 8, 'max_actions_per_question': 10,
                           'ordinary_token_cap_per_arm_stream': 500_000,
                           'panel_token_cap_per_arm_stream': 500_000,
                           'solve_output_tokens': 384, 'reflection_output_tokens': 1024}.items():
        require(type(manifest.get(name)) is int and manifest[name] == expected, 'frozen pilot cap differs: ' + name)
    require(type(manifest.get('model')) is str and bool(manifest['model']), 'missing model identity')
    integer(manifest['context_tokens'], 'context tokens', minimum=1025)


def audit_directory(directory, *, freeze_path=None):
    directory = Path(directory).resolve()
    counts = Counter()
    failures, protocol_issues = [], []
    raw_hashes = {}
    report = {'status': 'failed', 'directory': str(directory),
              'scope': 'saved-data consistency, independent SQLite outcomes, shared-code prompt/memory reconstruction',
              'auditor_source_sha256': sha(__file__), 'claim_confirmed': False,
              'pilot_completeness': 'unverified', 'planned_records_complete': False,
              'required_records_complete': False, 'known_usage_complete': False,
              'sqlite_outcomes_complete': False, 'resource_comparison_complete': False,
              'limitations': [
                  'Uses frozen environment generation and learner memory/compiler definitions; no runner or model client imported.',
                  'Does not authenticate original execution, backend token counts, model weights or reported runtime.',
                  'A development pilot cannot establish the requested interaction/accuracy/retention claim.',
                  'Machine-specific SQL timeouts that cannot be reproduced are reported separately, never treated as verified results.',
              ]}
    try:
        manifest_path, summary_path = directory / 'manifest.json', directory / 'summary.json'
        manifest = read_json(manifest_path.read_text())
        summary = read_json(summary_path.read_text())
        validate_manifest(manifest)
        report.update(manifest_sha256=sha(manifest_path), summary_sha256=sha(summary_path),
                      manifest_status=manifest['status'], checked_source_sha256=manifest['source_sha256'])
        for module_name in ('fragments_v8', 'memory_v8', 'abstraction_v8', 'sql_env_v8'):
            module = sys.modules['witness_cl.' + module_name]
            require(Path(module.__file__).resolve() == ROOT / 'src/witness_cl' / (module_name + '.py'),
                    'replay imported an unrelated package module: ' + module_name)
        require(set(manifest['source_sha256']) == set(SOURCE_FILES), 'incomplete or substituted frozen source map')
        for source, digest in manifest['source_sha256'].items():
            require(sha(ROOT / source) == digest, 'frozen source drift: ' + source)
        require(manifest.get('source_unchanged') is True, 'executed source was changed during the pilot')
        if freeze_path is not None:
            freeze_path = Path(freeze_path)
            frozen = read_json(freeze_path.read_text())
            exact(frozen.get('source_sha256'), manifest['source_sha256'], 'external freeze differs: source_sha256')
            if 'development_seeds' in frozen:
                for frozen_field, manifest_field in [('development_seeds', 'seeds'), ('conditions', 'conditions'),
                                                      ('arms', 'arms'), ('wall_seconds_cap', 'wall_seconds_cap')]:
                    exact(frozen.get(frozen_field), manifest[manifest_field], 'external freeze differs: ' + frozen_field)
                require(frozen.get('claim_confirmed') is False and
                        type(frozen.get('ordinary_model_task_calls_before_freeze')) is int and
                        frozen['ordinary_model_task_calls_before_freeze'] == 0,
                        'development source receipt is not a pre-task unconfirmed freeze')
                provenance_path = freeze_path.parent / 'model-provenance.json'
                require(sha(provenance_path) == frozen.get('model_provenance_sha256'),
                        'model provenance differs from source receipt')
                provenance = read_json(provenance_path.read_text())
                require(provenance.get('server_alias') == manifest['model'] and
                        provenance.get('context_tokens') == manifest['context_tokens'],
                        'model/context differ from recorded prepilot provenance')
                report['checked_model_provenance_sha256'] = sha(provenance_path)
            else:
                for field in ('seeds', 'conditions', 'arms', 'model', 'context_tokens'):
                    exact(frozen.get(field), manifest[field], 'external freeze differs: ' + field)
            report['checked_freeze_sha256'] = sha(freeze_path)
        groups = [(s, c) for s in manifest['seeds'] for c in manifest['conditions']]
        names = {f'{s}-{c}-{a}.jsonl': (s, c, a) for s, c in groups for a in manifest['arms']}
        require(type(manifest.get('raw_sha256')) is dict, 'missing finalized raw hash map')
        files = {p.name: p for p in directory.glob('*.jsonl')}
        require(set(files) == set(manifest['raw_sha256']) and set(files) <= set(names), 'raw file/hash/name grid mismatch')
        runs = {identity: [] for identity in names.values()}
        for filename, path in files.items():
            raw_hashes[filename] = sha(path)
            require(raw_hashes[filename] == manifest['raw_sha256'][filename], 'raw digest mismatch: ' + filename)
            with path.open() as handle:
                for line in handle:
                    require(line.endswith('\n') and len(line.encode()) <= 32_000_000, 'truncated or oversized raw record')
                    trace = read_json(line)
                    require(type(trace) is dict, 'raw record is not an object')
                    exact([trace.get(k) for k in ('seed', 'condition', 'arm')], names[filename], 'raw record belongs to another run')
                    runs[names[filename]].append(trace)
        require(sum(map(len, runs.values())) == manifest['completed_episode_records'], 'manifest record count mismatch')
        require(type(summary) is list, 'summary must be an array')
        summary_map = {}
        for row in summary:
            identity = tuple(row.get(k) for k in ('seed', 'condition', 'arm'))
            require(identity in runs and identity not in summary_map, 'unknown or duplicate summary group')
            summary_map[identity] = row
        active_groups = []
        for s, c in groups:
            present = [(s, c, a) in summary_map for a in manifest['arms']]
            require(not any(present) or all(present), 'partial arm grid in active group summary')
            if all(present):
                active_groups.append((s, c))
        require(active_groups == groups[:len(active_groups)], 'active groups are not a declared prefix')
        require(all(not rows or identity[:2] in active_groups for identity, rows in runs.items()), 'raw records omitted from summary')
        # Recover the deterministic global round-robin schedule from per-arm
        # files. Only explicit ordinary resource stops may skip future episodes.
        consumed = Counter()
        missing = False
        runtime_aborted = False
        wall_aborted = False
        for s, c in groups:
            stopped = set()
            for step, (phase, index) in enumerate(schedule()):
                offset = step % len(manifest['arms'])
                order = manifest['arms'][offset:] + manifest['arms'][:offset]
                for arm in order:
                    if phase == 'ordinary' and arm in stopped:
                        continue
                    key = (s, c, arm)
                    rows = runs[key]
                    cursor = consumed[key]
                    if cursor == len(rows):
                        missing = True
                        continue
                    require(not wall_aborted, 'records continue after a reported global wall stop')
                    require(not missing and not runtime_aborted, 'records continue after an unexplained missing/failed scheduled episode')
                    row = rows[cursor]
                    exact([row.get('phase'), row.get('episode_index')], [phase, index], 'phase grid is missing, duplicated or reordered')
                    consumed[key] += 1
                    if row['status'] == 'resource_stop' and phase == 'ordinary':
                        stopped.add(arm)
                    if row['status'] == 'backend_or_runtime_failure':
                        runtime_aborted = True
                    if row.get('stop_reason') == 'wall_time_ceiling' or row.get('reflection_stop') == 'wall_time_ceiling':
                        wall_aborted = True
                        counts['reported_wall_stops'] += 1
        require(all(consumed[key] == len(rows) for key, rows in runs.items()), 'unconsumed scheduled records')
        oracle_cache = {}
        for s, c in active_groups:
            stream = make_stream(s, c, split='development')
            for arm in manifest['arms']:
                key = (s, c, arm)
                memory = ExperienceMemory(arm)
                ordinary, panel = Budget(280), Budget(260)
                evidence = {}
                for trace in runs[key]:
                    phase, index = trace['phase'], trace['episode_index']
                    spec = (stream.ordinary if phase == 'ordinary' else
                            stream.final_panel if phase == 'final' else stream.old_panel)[index]
                    oracle_key = (s, c, phase, index)
                    if oracle_key not in oracle_cache:
                        oracle = SQLiteReplay(spec)
                        try:
                            result = oracle.query(spec._gold_sql, {})
                            require(result['error'] is None and len(result['rows']) == 1 and
                                    len(result['rows'][0]) == 1 and
                                    abs(result['rows'][0][0] - spec._expected) <= 1e-9,
                                    'independent SQLite reference disagrees with Python evaluator oracle')
                        finally:
                            oracle.close()
                        oracle_cache[oracle_key] = True
                    check_episode(trace, spec, memory, ordinary if phase == 'ordinary' else panel,
                                  manifest, counts, evidence, protocol_issues)
                aggregate = summary_map[key]
                exact(aggregate['memory'], memory.snapshot(), 'summary memory differs from final reconstructed state')
                for label, budget in [('ordinary_budget', ordinary), ('panel_budget', panel)]:
                    saved = aggregate[label]
                    require(set(saved) == set(vars(budget)), 'budget summary fields are missing or extra')
                    for field, value in vars(budget).items():
                        if field.endswith('_seconds'):
                            require(math.isclose(finite(saved[field], field), value, rel_tol=1e-10, abs_tol=1e-9),
                                    'summary timing total differs: ' + field)
                        else:
                            require(type(saved[field]) is int and saved[field] == value, 'summary budget counter differs: ' + field)
                by_phase = {phase: [r for r in runs[key] if r['phase'] == phase] for phase in PHASE_COUNTS}
                exact(aggregate['phase_counts'], {p: len(rows) for p, rows in by_phase.items()}, 'summary phase counts differ')
                exact(aggregate['phase_selects'], {p: sum(r['select_attempts'] for r in rows) for p, rows in by_phase.items()},
                      'summary SELECT totals differ')
                exact(aggregate['phase_failures'], {p: sum(r['status'] != 'completed' for r in rows) for p, rows in by_phase.items()},
                      'summary failure totals differ')
                exact(aggregate['phase_reward'], {p: sum(r['reward'] for r in rows)/len(rows) if rows else None
                                                  for p, rows in by_phase.items()}, 'summary reward means differ')
        planned_complete = len(summary_map) == len(names) and all(
            row['phase_counts'] == PHASE_COUNTS for row in summary_map.values())
        stopped_episodes = counts['resource_stopped_episodes'] + counts['runtime_failed_episodes']
        required_complete = planned_complete and not stopped_episodes
        require(manifest.get('required_records_complete') is required_complete, 'manifest completeness claim differs from saved grid/stops')
        if manifest['status'] == 'completed':
            require(required_complete, 'completed pilot lacks required records')
        if manifest['status'] == 'incomplete':
            require(not required_complete, 'incomplete manifest has a complete unstopped grid')
        elapsed = finite(manifest['elapsed_seconds'], 'pilot elapsed seconds')
        require(elapsed + 1e-5 >= sum(r['elapsed_seconds'] for rows in runs.values() for r in rows),
                'pilot elapsed time excludes recorded episode time')
        wall_cap_respected = elapsed <= manifest['wall_seconds_cap']
        if not wall_cap_respected:
            protocol_issues.append('recorded pilot elapsed time exceeds declared wall ceiling')
        if counts['reported_wall_stops'] and elapsed < manifest['wall_seconds_cap']:
            protocol_issues.append('reported global wall stop precedes declared elapsed ceiling; wall evidence is unverifiable')
        report.update(status='passed', wall_cap_respected=wall_cap_respected, planned_records_complete=planned_complete,
                      required_records_complete=required_complete,
                      pilot_completeness='complete' if required_complete and manifest['status'] == 'completed' else 'partial',
                      known_usage_complete=counts['unknown_usage_calls'] == 0,
                      sqlite_outcomes_complete=counts['timing_dependent_errors_unverified'] == 0,
                      full_six_arm_grid=set(manifest['arms']) == set(ARMS),
                      resource_comparison_complete=(required_complete and manifest['status'] == 'completed'
                          and set(manifest['arms']) == set(ARMS) and counts['unknown_usage_calls'] == 0
                          and counts['test_double_calls'] == 0 and not protocol_issues
                          and counts['timing_dependent_errors_unverified'] == 0),
                      independent_reference_cases=len(oracle_cache))
    except (AuditError, ValueError, TypeError, KeyError, IndexError, OSError, OverflowError) as exc:
        failures.append({'type': type(exc).__name__, 'message': str(exc)[:1024]})
    report.update(checked=dict(counts), failures=failures, protocol_issues=sorted(set(protocol_issues)),
                  raw_sha256=raw_hashes)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+', type=Path)
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    reports = [audit_directory(directory, freeze_path=args.freeze) for directory in args.directories]
    rendered = json.dumps(reports, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end='')
    return 0 if all(report['status'] == 'passed' for report in reports) else 1


if __name__ == '__main__':
    raise SystemExit(main())
