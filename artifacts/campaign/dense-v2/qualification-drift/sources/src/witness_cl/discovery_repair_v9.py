"""Unintegrated, bounded feedback-guided repair of proposed SQL relations.

The trusted caller supplies a correct completed ordinary trace and the same
answered, still-open session with learning checks enabled. Only the original
ordinary observations may be selected as source/guard witnesses. Failed checks
remain charged observations and may inform repair, but never become witnesses.

This prototype is not imported by any frozen experiment runner. Its traces do
not establish empirical discovery or generalization; one admitted relation is
still supported by only one own observed answer and one empty-relation
intervention on that same database, not a proof of generalization.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import time

from .abstraction_v8 import (PROPOSAL_PROMPT, PROPOSAL_SCHEMA, prepare_proposal,
                             admit_verified, equal_scalar, finite_scalar)
from .fragments_v8 import Fragment, FragmentError
from .memory_v8 import canonical, json_object
from .model_v8 import BudgetStop

MAX_REPAIR_ATTEMPTS = 3
MAX_SELECTS = 8
_FRAME_FIELDS = ('phase', 'question', 'schema', 'answer', 'reward', 'status')
_VISIBLE_QUERY_FIELDS = ('sql', 'params', 'columns', 'rows', 'error', 'truncated',
                         'attempt', 'purpose', 'learning_check')
REPAIR_PROMPT = PROPOSAL_PROMPT + '''
You may repair an earlier proposal using the actual host error or reconstruction
observation in repair_feedback. The relation is exposed to outer_sql only as the
CTE named reused; outer_sql must refer to reused. This is the structural API,
not a suggested domain query. Do not assume another alias exists.
The queries list is the fixed original ordinary witness prefix. source_index and
guard_index must refer only to that list. Queries shown in repair_feedback are
post-answer checks and are never eligible new source or guard witnesses. Keep
the original confirmed answer and observations fixed. Return the same proposal
JSON format, or null to stop. Each executed reconstruction spends a remaining
SELECT, including errors; the host allows at most three proposal attempts. After a
matching reconstruction, the host also charges a query that empties the proposed
relation while preserving its columns and re-evaluates the same outer SQL. If
the complete outer result does not change, this instance has not shown that
the proposed relation contributes and no entry is admitted.'''


def _frame(trace):
    return {key: deepcopy(trace[key]) for key in _FRAME_FIELDS}


def _visible(row):
    return {key: deepcopy(row[key]) for key in _VISIBLE_QUERY_FIELDS if key in row}


def _digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def run_discovery_repair(trace, memory, client, budget, session, *, allow_learning,
                         max_attempts=MAX_REPAIR_ATTEMPTS, output_tokens=4096):
    """Try at most three model proposals, charging real checks to ``session``.

    Actual model receipts append to ``trace['model_calls']`` and charged checks
    append to ``trace['queries']``. The return value contains the bounded repair
    journal and incremental costs; the caller must retain and account for it.
    Each session permits only one invocation after eligibility succeeds, including
    null proposals or compiler-only failures. Previous learning checks are also
    ineligible as an original prefix.
    A candidate needs two remaining SELECTs: reconstruction and intervention.
    All proposal calls use ``ordinary:reflection`` so a caller's fixed reflection
    decoding policy applies identically. No model output is repaired by the host.
    """
    if type(allow_learning) is not bool:
        raise ValueError('allow_learning must be an explicit Boolean')
    if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_REPAIR_ATTEMPTS:
        raise ValueError('one to three proposal attempts are permitted')
    if type(output_tokens) is not int or not 1 <= output_tokens <= 8192:
        raise ValueError('bounded positive proposal output allowance required')
    if output_tokens > client.max_output:
        raise ValueError('proposal allowance exceeds the client output ceiling')

    started = time.monotonic()
    select_start = session.select_attempts
    query_start, vm_start = session.query_seconds, session.vm_steps
    model_start = len(trace.get('model_calls', []))
    calls_start = budget.calls
    memory_before = memory.digest()
    attempts = []
    original_digest = None

    def finish(status, reason=None, entry=None):
        result = {
            'prototype_only': True, 'status': status, 'attempts': deepcopy(attempts),
            'original_evidence_digest': original_digest,
            'select_attempts_before': select_start, 'select_attempts_after': session.select_attempts,
            'new_select_attempts': session.select_attempts - select_start,
            'model_records_added': len(trace.get('model_calls', [])) - model_start,
            'inference_calls_added': budget.calls - calls_start,
            'query_seconds_added': session.query_seconds - query_start,
            'vm_steps_added': session.vm_steps - vm_start,
            'elapsed_seconds': time.monotonic() - started,
            'memory_digest_before': memory_before, 'memory_digest_after': memory.digest(),
        }
        if reason is not None:
            result['reason'] = str(reason)[:512]
        if entry is not None:
            result['admitted_fragment_digest'] = entry.fragment().digest
            result['admitted_provenance'] = entry.provenance
        return result

    # No learning operation, model call, query, or memory update on panels.
    if not allow_learning or trace.get('phase') != 'ordinary':
        return finish('not_learning')
    if (memory.arm not in ('fragments', 'fragments_unchecked')
            or trace.get('status') != 'completed'
            or type(trace.get('reward')) not in (int, float) or trace['reward'] != 1.):
        return finish('not_eligible', 'a correct completed own ordinary episode is required')
    if session.closed or not session.answered:
        return finish('session_unavailable', 'same answered, open ordinary session required')
    if getattr(session, '_discovery_repair_v9_started', False):
        return finish('already_attempted', 'this session already began its bounded repair operation')
    if (trace.get('question') != session.public.question or trace.get('schema') != session.public.schema):
        return finish('not_eligible', 'trace does not match the current public question and schema')
    queries = trace.get('queries')
    if (not isinstance(queries, list) or not 1 <= len(queries) <= MAX_SELECTS
            or len(queries) != session.select_attempts
            or any(not isinstance(row, dict) or type(row.get('attempt')) is not int
                   or row['attempt'] != i + 1 or row.get('learning_check') is not False
                   for i, row in enumerate(queries))):
        return finish('not_eligible', 'a complete original ordinary prefix with no prior learning checks is required')
    if 'model_calls' not in trace:
        trace['model_calls'] = []
    if not isinstance(trace['model_calls'], list):
        raise ValueError('model_calls must be a trace list')
    # Keep the attempt ceiling on the physical episode, even when all responses
    # abstain or fail compilation without spending a SELECT. This private marker
    # is not an observation and never enters the model-visible evidence.
    session._discovery_repair_v9_started = True

    original_frame = _frame(trace)
    original_queries = deepcopy(queries)
    original_count = len(original_queries)
    observed_prefix = deepcopy(original_queries)
    original_digest = _digest({'frame': original_frame, 'queries': original_queries})
    feedback = []

    def evidence_unchanged():
        return (canonical(_frame(trace)) == canonical(original_frame)
                and canonical(trace['queries']) == canonical(observed_prefix)
                and len(trace['queries']) == session.select_attempts
                and memory.digest() == memory_before)

    for index in range(max_attempts):
        if not evidence_unchanged():
            return finish('evidence_changed', 'the fixed episode or observed query prefix was modified')
        if session.closed or not session.answered:
            return finish('session_unavailable')
        if min(MAX_SELECTS, session.public.max_selects) - session.select_attempts < 2:
            return finish('select_cap', 'two SELECTs are required for reconstruction and intervention')
        try:
            # Enforce caller-local and shared limits before another proposal;
            # a final permitted proposal may still use its reserved SQL check.
            budget.check(0, output_tokens)
        except BudgetStop as exc:
            return finish('budget_stop', exc)
        if budget.unknown_usage_calls:
            return finish('model_failure', 'prior inference usage is unknown')
        payload = {
            'question': original_frame['question'], 'schema': original_frame['schema'],
            'queries': [_visible(row) for row in original_queries],
            'answer': original_frame['answer'], 'correct': True,
            'remaining_learning_selects': min(MAX_SELECTS, session.public.max_selects) - session.select_attempts,
            'original_query_count': original_count,
            'repair_feedback': deepcopy(feedback),
        }
        messages = [{'role': 'system', 'content': REPAIR_PROMPT},
                    {'role': 'user', 'content': canonical(payload)}]
        attempt = {'attempt': index + 1, 'status': 'model_attempt'}
        attempts.append(attempt)
        try:
            text = client.complete(messages, budget, phase='ordinary:reflection',
                                   records=trace['model_calls'], output_tokens=output_tokens,
                                   response_schema=PROPOSAL_SCHEMA)
        except BudgetStop as exc:
            attempt.update(status='budget_stop', error=str(exc)[:512])
            return finish('budget_stop', exc)
        except Exception as exc:
            attempt.update(status='model_failure', error_type=type(exc).__name__, error=str(exc)[:512])
            return finish('model_failure', exc)
        attempt['proposal_text'] = text
        if not evidence_unchanged():
            return finish('evidence_changed', 'original evidence or previous checks changed during the proposal')
        if time.monotonic() >= budget.deadline:
            return finish('budget_stop', 'wall_time_ceiling')
        try:
            parsed = json_object(text)
            fields = parsed.get('proposal')
            if isinstance(fields, dict):
                for name in ('source_index', 'guard_index'):
                    if type(fields.get(name)) is not int or not 0 <= fields[name] < original_count:
                        raise ValueError(name + ' must refer to the original ordinary witness prefix')
            # Existing validation freezes the *current* charged prefix. Prior
            # checks remain in that prefix, but the checks above make them
            # ineligible as selected source or applicability observations.
            proposal = prepare_proposal(text, trace)
        except (ValueError, TypeError, KeyError, FragmentError) as exc:
            attempt.update(status='proposal_rejected', error=str(exc)[:512])
            feedback.append(deepcopy(attempt))
            continue
        if proposal is None:
            attempt['status'] = 'abstained'
            return finish('abstained')
        if session.closed or not session.answered:
            return finish('session_unavailable')
        if session.select_attempts >= min(MAX_SELECTS, session.public.max_selects):
            return finish('select_cap')
        if not evidence_unchanged():
            return finish('evidence_changed')
        verification_index = len(trace['queries'])
        try:
            result = session.query(proposal.request.sql, proposal.request.parameters, learning_check=True)
        except Exception as exc:
            attempt.update(status='query_failure', error_type=type(exc).__name__, error=str(exc)[:512])
            return finish('query_failure', exc)
        row = {'sql': proposal.request.sql, 'params': deepcopy(proposal.request.parameters),
               'purpose': 'abstraction_reconstruction', 'learning_check': True, **asdict(result)}
        attempt['reconstruction'] = _visible(row)
        if result.attempt != verification_index + 1 or session.select_attempts != verification_index + 1:
            # Closed/disabled/cap responses do not represent an executed SELECT.
            attempt['status'] = 'session_rejected'
            return finish('session_rejected', result.error)
        trace['queries'].append(row)
        observed_prefix.append(deepcopy(row))
        attempt['verification_query_index'] = verification_index
        if not evidence_unchanged():
            return finish('evidence_changed')
        if time.monotonic() >= budget.deadline:
            return finish('budget_stop', 'wall_time_ceiling')
        try:
            # Validate admission against the exact one-check extension before
            # the intervention extends the trace again. Real memory is untouched.
            staged = deepcopy(memory)
            entry = admit_verified(staged, proposal, trace, verification_index)
        except (ValueError, TypeError, KeyError, FragmentError) as exc:
            attempt.update(status='reconstruction_rejected', error=str(exc)[:512])
            feedback.append(deepcopy(attempt))
            continue
        try:
            fields = json_object(proposal.model_fields)
            base = proposal.fragment.original_prepared_query
            empty = Fragment.from_query('SELECT * FROM (' + base.sql + ') WHERE 0', base.parameters)
            intervention = empty.compose(fields['outer_sql'], fields['outer_params'], alias='reused')
        except (ValueError, TypeError, KeyError, FragmentError) as exc:
            attempt.update(status='intervention_compile_rejected', error=str(exc)[:512])
            feedback.append(deepcopy(attempt))
            continue
        if not evidence_unchanged():
            return finish('evidence_changed')
        if session.closed or not session.answered:
            return finish('session_unavailable')
        if session.select_attempts >= min(MAX_SELECTS, session.public.max_selects):
            return finish('select_cap')
        if time.monotonic() >= budget.deadline:
            return finish('budget_stop', 'wall_time_ceiling')
        intervention_index = len(trace['queries'])
        try:
            probed = session.query(intervention.sql, intervention.parameters, learning_check=True)
        except Exception as exc:
            attempt.update(status='query_failure', error_type=type(exc).__name__, error=str(exc)[:512])
            return finish('query_failure', exc)
        probe = {'sql': intervention.sql, 'params': deepcopy(intervention.parameters),
                 'purpose': 'abstraction_empty_relation_probe', 'learning_check': True, **asdict(probed)}
        attempt['intervention'] = _visible(probe)
        if probed.attempt != intervention_index + 1 or session.select_attempts != intervention_index + 1:
            attempt['status'] = 'session_rejected'
            return finish('session_rejected', probed.error)
        trace['queries'].append(probe)
        observed_prefix.append(deepcopy(probe))
        attempt['intervention_query_index'] = intervention_index
        if not evidence_unchanged():
            return finish('evidence_changed')
        if time.monotonic() >= budget.deadline:
            return finish('budget_stop', 'wall_time_ceiling')
        rejection = None
        if probe['error'] is not None or probe['truncated'] is not False:
            rejection = 'empty-relation intervention must return a complete successful observation'
        elif canonical(probe['columns']) != canonical(row['columns']):
            rejection = 'empty-relation intervention changed the outer result columns'
        elif canonical(probe['rows']) == canonical(row['rows']):
            rejection = 'outer result was unchanged when the proposed relation was emptied'
        elif (len(probe['rows']) == 1 and len(probe['rows'][0]) == 1
              and finite_scalar(probe['rows'][0][0])
              and equal_scalar(probe['rows'][0][0], row['rows'][0][0])):
            rejection = 'outer result was unchanged within the scalar comparison tolerance'
        if rejection is not None:
            attempt.update(status='dependence_rejected', error=rejection)
            feedback.append(deepcopy(attempt))
            continue
        # NULL or no rows are legitimate changed complete results. This event
        # binds the new evidence to the staged admission without claiming that
        # a one-instance intervention proves the relation's intended meaning.
        probe_digest = _digest(probe)
        staged.events.append({'kind': 'abstraction_empty_relation_checked',
                              'fragment_digest': entry.fragment().digest,
                              'original_evidence_digest': original_digest,
                              'reconstruction_query_index': verification_index,
                              'intervention_query_index': intervention_index,
                              'intervention_digest': probe_digest,
                              'scope': 'one_observed_outer_result_changed_under_empty_relation'})
        while staged.peak_memory_bytes < staged.memory_bytes():
            staged.peak_memory_bytes = staged.memory_bytes()
        if not evidence_unchanged():
            return finish('evidence_changed')
        memory.entries, memory.events, memory.peak_memory_bytes = (staged.entries, staged.events,
                                                                 staged.peak_memory_bytes)
        attempt.update(status='admitted', intervention_digest=probe_digest)
        return finish('admitted', entry=entry)
    return finish('attempt_cap')
