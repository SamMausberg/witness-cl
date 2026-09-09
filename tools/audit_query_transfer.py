#!/usr/bin/env python3
"""Independent SQLite replay and local mechanism diagnostics; no model calls.

This per-episode audit does not establish prior own admission, fresh data, legal
memory selection, source freezing, or whole-run accounting. Those require the
runner's complete ledger. Counterfactual results are evaluator-only diagnostics
and must never be appended to learner observations or used for online admission.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

import sqlglot
from sqlglot import exp

from experiments.audit_sql_abstractions_v9 import SQLiteReplayV9
from witness_cl.relational_program import ProgramError, compile_program
from witness_cl.source_views import SourceView, UnsupportedSource, lift_source, reconstruct
from witness_cl.sql_env_v9 import make_stream

RESULT_FIELDS = ('columns', 'rows', 'error', 'truncated')


class AuditError(ValueError):
    """A saved trace is inconsistent with its fixture, source, AST, or execution."""

    def __init__(self, message):
        super().__init__(message)
        self.diagnostic = {'consistent': False, 'diagnostic_sql': [], 'diagnostic_sql_calls': 0}


def _require(condition, message):
    if not condition:
        raise AuditError(message)


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise AuditError('invalid finite JSON payload') from exc


def _exact(first, second, label):
    _require(_canonical(first) == _canonical(second), label + ' mismatch')


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _scalar(result):
    if result['error'] is not None:
        return {'status': 'error', 'value': None}
    if result['truncated']:
        return {'status': 'truncated', 'value': None}
    rows = result['rows']
    if len(rows) != 1 or len(rows[0]) != 1:
        return {'status': 'nonscalar', 'value': None}
    value = rows[0][0]
    if value is None:
        return {'status': 'null', 'value': None}
    return {'status': 'numeric' if _finite(value) else 'nonnumeric', 'value': value}


def _correct(value, expected):
    return _finite(value) and abs(value - expected) <= 1e-6 * (1 + abs(expected))


def _changed(actual, counterfactual):
    """Exact value comparison and task-scale tolerance, never decimal rounding."""
    if counterfactual['status'] == 'numeric':
        other = counterfactual['value']
        return actual != other, abs(actual - other) > 1e-6 * (1 + abs(actual))
    if counterfactual['status'] == 'null':
        return True, True
    # Execution errors and truncated/nonscalar results are inconclusive.
    return None, None


def _source_aggregate_ops(view):
    root = sqlglot.parse_one(view.source_sql, read='sqlite')
    return sorted({node.key for node in root.expressions[0].find_all(exp.AggFunc)})


def _program_operations(program):
    aggregates, joins, grouped_keys, group_count = set(), 0, 0, 0

    def visit(node):
        nonlocal joins, grouped_keys, group_count
        if isinstance(node, dict):
            if node.get('op') == 'group':
                group_count += 1
                grouped_keys += int(bool(node['keys']))
                aggregates.update(item['op'] for item in node['aggregates'])
            elif node.get('op') == 'join':
                joins += 1
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(program)
    return {'aggregate_ops': sorted(aggregates), 'join_nodes': joins,
            'groups_with_keys': grouped_keys, 'group_nodes': group_count}


def _has_column(expression_sql):
    return sqlglot.parse_one('SELECT ' + expression_sql, read='sqlite').find(exp.Column) is not None


def _load_views(trace):
    _require(type(trace.get('selected_views')) is list, 'selected view list is required')
    views = []
    for payload in trace['selected_views']:
        try:
            view = SourceView.from_dict(payload)
            regenerated = lift_source(view.source_sql, view.source_params, trace['schema'], view.question)
        except (UnsupportedSource, ValueError, TypeError, KeyError) as exc:
            raise AuditError('invalid selected source view') from exc
        _exact(view.to_dict(), regenerated.to_dict(), 'source-derived view regeneration')
        views.append(view)
    _require(len({v.key for v in views}) == len(views), 'duplicate selected source keys')
    return views


def _compiled_metadata(compiled):
    return {'sql': compiled.prepared.sql, 'params': compiled.prepared.parameters,
            'used_views': list(compiled.used_views),
            'measure_references': list(compiled.measure_references),
            'source_uses': [asdict(use) for use in compiled.source_uses]}


def audit_episode(trace, spec):
    """Replay recorded requests and diagnose a correct terminal PROGRAM locally.

    Raises AuditError on any stored-data/compiler/execution mismatch. A returned
    local candidate still has freshness_status=requires_whole_run_provenance and
    primary_candidate=None. The caller must separately establish earlier own
    admission, a fresh evaluation fixture, and every frozen protocol condition.
    """
    _require(type(trace) is dict, 'trace object is required')
    _exact(trace.get('question'), spec._public.question, 'public question')
    _exact(trace.get('schema'), spec._public.schema, 'public schema')
    _require(type(trace.get('actions')) is list and type(trace.get('queries')) is list,
             'actions and query records are required')
    _require(type(trace.get('learn')) is bool, 'explicit learning flag is required')
    for query in trace['queries']:
        _require(type(query) is dict and set(RESULT_FIELDS + (
            'sql', 'params', 'attempt', 'purpose', 'learning_check', 'terminal_requested', 'terminal')) <= query.keys(),
            'incomplete query record')
        _require(all(type(query[k]) is bool for k in ('learning_check', 'terminal_requested', 'terminal')),
                 'query control flags must be Boolean')
    views = _load_views(trace)
    view_map = {view.key: view for view in views}
    ordinary = [(i, q) for i, q in enumerate(trace['queries']) if not q.get('learning_check')]
    _require(len(ordinary) == len(trace['actions']), 'action/query cardinality mismatch')
    _require(len(trace['queries']) <= 8, 'recorded query cap exceeded')
    compiled_actions = {}
    for action_index, (action, (query_index, query)) in enumerate(zip(trace['actions'], ordinary)):
        _require(type(action) is dict and type(query) is dict, 'invalid action/query object')
        if 'invalid' in action:
            _exact(query['sql'], '', 'invalid action SQL')
            _exact(query['params'], {}, 'invalid action bindings')
            _require(query.get('purpose') == 'invalid_action', 'invalid action purpose mismatch')
            continue
        _require(type(action.get('answer')) is bool, 'action answer must be Boolean')
        if action.get('action') == 'QUERY':
            _exact(query.get('terminal_requested'), action['answer'], 'terminal request')
            _exact(query['sql'], action.get('sql'), 'QUERY source SQL')
            _exact(query['params'], action.get('params'), 'QUERY source bindings')
            _require(query.get('purpose') == 'ordinary', 'QUERY purpose mismatch')
        elif action.get('action') == 'PROGRAM':
            if query.get('purpose') == 'unavailable_action':
                _exact(query['sql'], '', 'unavailable PROGRAM SQL')
                _exact(query['params'], {}, 'unavailable PROGRAM bindings')
                _require(trace.get('memory', {}).get('arm') != 'view_program',
                         'PROGRAM was available to this arm')
                continue
            try:
                compiled = compile_program(action['program'], views)
            except (ProgramError, ValueError, TypeError, KeyError, RecursionError):
                _require(query.get('purpose') == 'invalid_program', 'valid PROGRAM metadata missing')
                _exact(query['sql'], '', 'invalid PROGRAM SQL')
                _exact(query['params'], {}, 'invalid PROGRAM bindings')
                _require('compiled' not in action, 'invalid PROGRAM contains compiled metadata')
                continue
            _require(query.get('purpose') == 'program', 'PROGRAM purpose mismatch')
            _require(trace.get('memory', {}).get('arm') == 'view_program', 'PROGRAM unavailable to this arm')
            _exact(query.get('terminal_requested'), action['answer'], 'terminal request')
            expected = _compiled_metadata(compiled)
            _require(type(action.get('compiled')) is dict, 'compiled PROGRAM metadata is required')
            for name, value in expected.items():
                _exact(action['compiled'].get(name), value, 'compiled PROGRAM ' + name)
            _exact(query['sql'], compiled.prepared.sql, 'executed PROGRAM SQL')
            _exact(query['params'], compiled.prepared.parameters, 'executed PROGRAM bindings')
            compiled_actions[action_index] = compiled
        else:
            raise AuditError('unsupported recorded action')
        _require(query_index < len(trace['queries']), 'invalid query index')

    terminal_indices = [i for i, q in enumerate(trace['queries']) if q.get('terminal') is True]
    _require(len(terminal_indices) <= 1, 'multiple terminal query records')
    terminal_index = terminal_indices[0] if terminal_indices else None
    if terminal_index is not None:
        _exact(trace.get('answer_query_index'), terminal_index, 'terminal query index')
        action_index = trace.get('answer_action_index')
        _require(type(action_index) is int and 0 <= action_index < len(ordinary),
                 'invalid terminal action index')
        _require(ordinary[action_index][0] == terminal_index, 'terminal action/query mismatch')
        _require(trace['actions'][action_index].get('answer') is True, 'unrequested terminal answer')
        _require(all(q.get('learning_check') is True for q in trace['queries'][terminal_index + 1:]),
                 'ordinary SQL executed after the terminal answer')

    admission = trace.get('admission')
    if admission and 'view' in admission:
        _require(terminal_index is not None, 'admission without terminal source')
        _require(trace['actions'][trace['answer_action_index']].get('action') == 'QUERY',
                 'only a direct QUERY can create a source view')
        source = trace['queries'][terminal_index]
        try:
            view = SourceView.from_dict(admission['view'])
            regenerated = lift_source(source['sql'], source['params'], trace['schema'], trace['question'])
        except (UnsupportedSource, ValueError, TypeError, KeyError) as exc:
            raise AuditError('invalid admission view') from exc
        _exact(view.to_dict(), regenerated.to_dict(), 'admission source reconstruction')
        _exact(admission.get('source_query_index'), terminal_index, 'admission source index')
        for q in trace['queries']:
            if q.get('purpose') in {'source_reconstruction', 'empty_relation_check'}:
                sql, params = reconstruct(view, empty=q['purpose'] == 'empty_relation_check')
                _exact(q['sql'], sql, 'admission check SQL')
                _exact(q['params'], params, 'admission check bindings')

    diagnostic = {
        'consistent': False, 'trace_status': trace.get('status'), 'recorded_queries': len(trace['queries']),
        'terminal_program': False, 'correct': False, 'actual_answer': None,
        'freshness_status': 'requires_whole_run_provenance',
        'prior_own_admission_verified': False, 'whole_run_provenance_verified': False,
        'primary_candidate': None, 'local_candidate_pending_provenance': False,
        'interventions': [], 'diagnostic_sql': [],
        'scope': 'Per-episode consistency and local contribution only; no population or normalization claim.',
        'counterfactuals_are_learner_observations': False,
        'sql_replay_wall_cap_seconds': 2.0,
        'runtime_sql_wall_cap_reproduced': False,
        'operation_novelty_scope': 'Syntactic AST comparison; not equivalence or causal attribution of each new operator.',
        'diagnostic_cost_scope': 'Replayed and intervened SELECT requests; fixture setup is timed separately.',
    }
    setup_started = time.perf_counter()
    replay = SQLiteReplayV9(spec)
    diagnostic['diagnostic_setup_seconds'] = time.perf_counter() - setup_started
    replayed = []

    def execute(sql, params, kind, **metadata):
        started = time.perf_counter()
        result = replay.query(sql, params)
        diagnostic['diagnostic_sql'].append({
            'ordinal': len(diagnostic['diagnostic_sql']) + 1, 'kind': kind,
            'sql': sql, 'params': params, 'result': result,
            'elapsed_seconds': time.perf_counter() - started,
            'learner_observation': False, **metadata})
        return result

    try:
        for index, query in enumerate(trace['queries']):
            _exact(query.get('attempt'), index + 1, 'charged SELECT attempt')
            if query.get('learning_check'):
                _require(trace['learn'] and trace.get('phase') == 'ordinary',
                         'learning check outside a learning episode')
                _require(terminal_index is not None and index > terminal_index,
                         'learning check precedes the terminal answer')
            result = execute(query['sql'], query['params'], 'recorded_replay', query_index=index)
            _exact({k: query.get(k) for k in RESULT_FIELDS}, result, 'SQLite replay result')
            replayed.append(result)
        _exact(trace.get('select_attempts'), len(trace['queries']), 'SELECT count')
        if terminal_index is None:
            _exact(trace.get('answer'), None, 'absent terminal answer')
            _exact(trace.get('reward'), 0.0, 'absent terminal reward')
            _require(trace.get('status') != 'completed', 'completed trace lacks a terminal answer')
        else:
            actual = _scalar(replayed[terminal_index])
            _require(actual['status'] == 'numeric', 'terminal result is not a finite numeric scalar')
            _exact(trace.get('answer'), actual['value'], 'exact host-emitted numeric answer')
            correct = _correct(actual['value'], spec._expected)
            _exact(trace.get('reward'), float(correct), 'terminal correctness')
            diagnostic.update(actual_answer=actual['value'], correct=correct)
            if 'feedback' in trace:
                _exact(trace['feedback'], {'correct': correct}, 'terminal feedback')
            if admission and admission.get('status') in {
                    'admitted', 'reconstruction_rejected', 'dependence_rejected'}:
                checks = [(q, replayed[i]) for i, q in enumerate(trace['queries']) if q['learning_check']]
                needed = 1 if admission['status'] == 'reconstruction_rejected' else 2
                _require(len(checks) == needed, 'admission check cardinality mismatch')
                _require(checks[0][0]['purpose'] == 'source_reconstruction', 'first admission check is not reconstruction')
                reconstruction_value = _scalar(checks[0][1])
                matched = (reconstruction_value['status'] == 'numeric'
                           and _correct(reconstruction_value['value'], actual['value']))
                if needed == 1:
                    _require(not matched, 'matching reconstruction was labeled rejected')
                else:
                    _require(matched and correct, 'admission requires a correct reconstructed answer')
                    _require(checks[1][0]['purpose'] == 'empty_relation_check', 'second admission check is not emptying')
                    empty_value = _scalar(checks[1][1])
                    dependent = (empty_value['status'] == 'numeric'
                                 and not _correct(empty_value['value'], actual['value']))
                    _require((admission['status'] == 'admitted') == dependent,
                             'admission dependence decision mismatch')
            terminal_action = trace['answer_action_index']
            if terminal_action in compiled_actions:
                diagnostic['terminal_program'] = True
                compiled = compiled_actions[terminal_action]
                program = trace['actions'][terminal_action]['program']
                ops = _program_operations(program)
                diagnostic['program_operations'] = ops
                diagnostic['structural_measure_references'] = list(compiled.measure_references)
                uses = {}
                for use in compiled.source_uses:
                    uses.setdefault(use.view_key, []).append(dict(use.bindings))
                for key in compiled.used_views:
                    view = view_map[key]
                    source_ops = _source_aggregate_ops(view)
                    novel_aggregates = sorted(set(ops['aggregate_ops']) - set(source_ops))
                    changed_bindings = any(_canonical(p) != _canonical(view.params) for p in uses[key])
                    new_operation = bool(novel_aggregates or ops['join_nodes']
                                         or ops['groups_with_keys'] or ops['group_nodes'] > 1)
                    for column in view.measure_columns:
                        origin = view.column_origins[column]
                        has_column = _has_column(view.lineage[column])
                        for replacement in (0, None):
                            compilation_error = None
                            try:
                                counter = compile_program(program, views, measure_overrides={key: {column: replacement}})
                            except ProgramError as exc:
                                compilation_error = str(exc)
                                result = {'columns': [], 'rows': [], 'truncated': False,
                                          'error': 'intervention compilation failed: ' + str(exc)}
                            else:
                                result = execute(counter.prepared.sql, counter.prepared.parameters,
                                                 'measure_intervention', view_key=key, column=column,
                                                 replacement=replacement)
                            counter_scalar = _scalar(result)
                            changed_exact, changed_tolerance = _changed(actual['value'], counter_scalar)
                            prerequisites = (correct and origin == 'scalar_expression' and has_column
                                             and (changed_bindings or new_operation))
                            entry = {
                                'view_key': key, 'column': column, 'origin': origin,
                                'lineage': view.lineage[column], 'has_column_dependency': has_column,
                                'structurally_referenced': (key, column) in compiled.measure_references,
                                'replacement': replacement, 'counterfactual_scalar': counter_scalar,
                                'intervention_compilation_error': compilation_error,
                                'output_changed_exact': changed_exact,
                                'output_changed_at_task_tolerance': changed_tolerance,
                                'changed_bindings': changed_bindings, 'source_bindings': dict(view.params),
                                'executed_bindings': uses[key], 'source_aggregate_ops': source_ops,
                                'new_aggregate_ops': novel_aggregates,
                                'new_join_or_group_operation': bool(ops['join_nodes'] or ops['groups_with_keys']
                                                                     or ops['group_nodes'] > 1),
                                'new_operation_or_binding': changed_bindings or new_operation,
                                'local_candidate_exact_pending_provenance': bool(prerequisites and changed_exact),
                                'local_candidate_pending_provenance': bool(prerequisites and changed_tolerance),
                            }
                            diagnostic['interventions'].append(entry)
                diagnostic['local_candidate_pending_provenance'] = any(
                    x['local_candidate_pending_provenance'] for x in diagnostic['interventions'])
        diagnostic['consistent'] = True
    except AuditError as exc:
        exc.diagnostic = diagnostic
        raise
    finally:
        replay.close()
        diagnostic['diagnostic_sql_calls'] = len(diagnostic['diagnostic_sql'])
        diagnostic['diagnostic_sql_seconds'] = sum(x['elapsed_seconds'] for x in diagnostic['diagnostic_sql'])
        diagnostic['replay_sql_calls'] = sum(x['kind'] == 'recorded_replay' for x in diagnostic['diagnostic_sql'])
        diagnostic['intervention_sql_calls'] = sum(x['kind'] == 'measure_intervention' for x in diagnostic['diagnostic_sql'])
    return diagnostic


def fixture_for_trace(trace):
    """Resolve explicit panel-local coordinates; never infer a split or seed."""
    for field in ('seed', 'condition', 'replay_split', 'phase', 'episode_index'):
        _require(field in trace, 'missing replay coordinate: ' + field)
    stream = make_stream(trace['seed'], trace['condition'], trace['replay_split'])
    phase = trace['phase']
    panels = {'ordinary': stream.ordinary, 'transfer': stream.ordinary, 'old_before': stream.old_panel,
              'old_after': stream.old_panel, 'final': stream.final_panel}
    _require(phase in panels, 'unknown replay phase')
    index = trace['episode_index']
    _require(type(index) is int and 0 <= index < len(panels[phase]), 'invalid panel-local episode index')
    return panels[phase][index]


def _read_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(AuditError('nonfinite JSON')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path, help='JSONL saved episode traces with explicit replay coordinates')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = [_read_json(line) for line in args.trace.read_text().splitlines() if line.strip()]
    reports = []
    failed = False
    for trace in records:
        try:
            reports.append(audit_episode(trace, fixture_for_trace(trace)))
        except AuditError as exc:
            failed = True
            reports.append({**exc.diagnostic, 'audit_error': str(exc)})
    payload = {'scope': 'Per-episode diagnostic; whole-run provenance is not verified.',
               'episodes': reports, 'diagnostic_sql_calls': sum(r['diagnostic_sql_calls'] for r in reports)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
