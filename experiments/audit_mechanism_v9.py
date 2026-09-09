#!/usr/bin/env python3
"""Bounded, offline causal SQL probes of the two saved v9 warm admissions.

This never runs a learner/model, repairs a proposal, modifies a saved trace,
constructs a held-out stream, or adds observations to learner memory. All probes
use new private in-memory databases for the already observed development cases.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from witness_cl.fragments_v8 import Fragment
from witness_cl.sql_env_v8 import make_stream

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'artifacts/v9/prospective-portable-92003/92003-reuse-fragments.jsonl'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def private_select(spec, sql, params):
    """Independent connection/execution, sharing only the frozen data generator."""
    started = time.perf_counter()
    with closing(sqlite3.connect(':memory:')) as db:
        db.enable_load_extension(False)
        for table in spec._tables:
            db.execute(table.ddl)
            marks = ','.join('?' for _ in table.columns)
            db.executemany(f'INSERT INTO {table.name} VALUES ({marks})', table.rows)
        db.commit()
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        tables = frozenset(table.name for table in spec._tables)
        transient = frozenset(('reused', 'gold_orders'))
        reads = []

        def authorize(action, first, second, database, source):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (second or '').lower() in {'count', 'sum'}:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ:
                reads.append([first, second, database, source])
                if ((first in tables and database == 'main') or
                        (first in tables | transient and second == '' and database is None)):
                    return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        steps = 0
        deadline = time.perf_counter() + 1.0

        def progress():
            nonlocal steps
            steps += 100
            return int(steps >= 200000 or time.perf_counter() >= deadline)

        db.set_authorizer(authorize)
        db.set_progress_handler(progress, 100)
        cursor = db.execute(sql, params)
        columns = [description[0] for description in cursor.description]
        rows = [list(row) for row in cursor.fetchmany(51)]
        if len(rows) > 50:
            raise RuntimeError('offline audit result exceeded its row cap')
        db.set_progress_handler(None, 0)
    return {'columns': columns, 'rows': rows, 'physical_and_transient_reads': reads,
            'elapsed_seconds': time.perf_counter() - started, 'vm_steps_callback_floor': steps}


def audit(out: Path):
    if out.exists():
        raise FileExistsError('an existing offline audit receipt is immutable')
    raw_bytes = RAW.read_bytes()
    rows = [json.loads(line) for line in raw_bytes.decode().splitlines()]
    stream = make_stream(92003, 'reuse', split='development')
    evidence = []
    for index in (6, 7):
        matches = [row for row in rows if row['phase'] == 'ordinary' and row['episode_index'] == index]
        if len(matches) != 1:
            raise ValueError('exact saved warm admission required')
        trace = matches[0]
        proposal = trace['abstraction_proposal']
        if proposal['status'] != 'accepted':
            raise ValueError('recorded acceptance required')
        fields = proposal['model_fields']
        fragment = Fragment.from_query(fields['sql'], fields['params'])
        if fragment.digest != proposal['fragment_digest']:
            raise ValueError('saved fragment digest mismatch')
        original = trace['queries'][proposal['verification_query_index']]
        spec = stream.ordinary[index]
        cases = []

        def run(label, sql, params, interpretation):
            case = {'label': label, 'sql': sql, 'params': params,
                    'sql_sha256': sha(sql), 'interpretation': interpretation,
                    **private_select(spec, sql, params)}
            cases.append(case)
            return case

        def composed(label, inner_sql, inner_params, interpretation):
            candidate = Fragment.from_query(inner_sql, inner_params)
            request = candidate.compose(fields['outer_sql'], fields['outer_params'], alias='reused')
            return run(label, request.sql, request.parameters, interpretation)

        base = run('saved_reconstruction', original['sql'], original['params'],
                   'Offline replay of the recorded paid reconstruction; not a new learner observation.')
        if (base['rows'] != original['rows'] or base['columns'] != original['columns']):
            raise AssertionError('offline reconstruction does not match saved observations')

        if index == 6:
            empty = composed('empty_reused', 'SELECT NULL AS distinct_refunded_orders WHERE 0', {},
                             'Replace the relation with no rows, preserving its output column.')
            sentinel = composed('sentinel_reused', 'SELECT -777 AS distinct_refunded_orders', {},
                                'Replace the relation value with a sentinel to test outer dependence.')
            off = composed('inner_binding_zero', fields['sql'], {'has_refunds': 0},
                           'Audit-only integer binding change; it disables every joined row.')
            nonzero = composed('inner_binding_two', fields['sql'], {'has_refunds': 2},
                               'Audit-only nonzero integer change; IS TRUE still retains every joined row.')
            if not (base['rows'] == [[22]] and empty['rows'] == [[None]] and
                    sentinel['rows'] == [[-777]] and off['rows'] == [[0]] and nonzero['rows'] == [[22]]):
                raise AssertionError('unexpected refunded-count dependence probe')
            conclusion = ('The outer query depends on the scalar relation. The integer hole is an '
                          'all-or-nothing truth gate, not a row-level refund criterion. These binding '
                          'probes are offline audit actions; the learner never changed the binding.')
        else:
            omitted = run('remove_reused_cte', fields['outer_sql'], fields['outer_params'],
                          'Delete the learned CTE entirely; execute only the recorded outer query.')
            empty = composed('empty_reused', 'SELECT NULL AS total_gross WHERE 0', {},
                             'Replace the learned relation with no rows.')
            sentinel = composed('sentinel_reused', 'SELECT -777 AS total_gross', {},
                                'Replace the learned relation value with a sentinel.')
            silver = composed('change_only_inner_binding', fields['sql'], {'tier': 'Silver'},
                              'Change only the learned relation binding; keep the outer Gold binding fixed.')
            standalone = run('standalone_learned_relation', fields['sql'], fields['params'],
                             'Separate offline execution of the stored SQL on its own Gold training fixture.')
            if any(case['rows'] != [[1350.25]] for case in (base, omitted, empty, sentinel, silver, standalone)):
                raise AssertionError('unexpected Gold witness independence probe')
            conclusion = ('The accepted reconstruction is independent of reused on this fixture: '
                          'deleting, emptying, replacing, or rebinding that CTE leaves the result unchanged. '
                          'Standalone stored SQL also produces the training answer in a separate offline '
                          'probe, but the paid learner witness did not establish that dependence or test '
                          'generalization. The stored SQL returns a scalar, not per-order rows.')

        evidence.append({'raw_line': rows.index(trace) + 1, 'episode_index': index,
                         'fragment_digest': fragment.digest, 'relation_sql_sha256': sha(fields['sql']),
                         'outer_sql_sha256': sha(fields['outer_sql']),
                         'source_query_index': fields['source_index'], 'guard_query_index': fields['guard_index'],
                         'recorded_entry_provenance': next(entry['provenance'] for entry in trace['memory_snapshot']['entries']
                             if entry['source']['sha256'] == fragment.digest),
                         'cases': cases, 'conclusion': conclusion})
    result = {
        'kind': 'offline_warm_relation_dependence_audit',
        'scope': 'Only saved development seed 92003 ordinary episodes 6 and 7, fresh private DB per probe.',
        'learner_model_calls': 0, 'learner_sql_calls_added': 0,
        'offline_sql_executions': sum(len(item['cases']) for item in evidence),
        'no_learner_feedback_memory_or_score_changed': True,
        'not_a_transfer_or_retention_evaluation': True,
        'sqlite_version': sqlite3.sqlite_version,
        'raw_file': str(RAW.relative_to(ROOT)),
        'raw_sha256': hashlib.sha256(raw_bytes).hexdigest(),
        'audit_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'data_generator_sha256': hashlib.sha256((ROOT/'src/witness_cl/sql_env_v8.py').read_bytes()).hexdigest(),
        'fragment_compiler_sha256': hashlib.sha256((ROOT/'src/witness_cl/fragments_v8.py').read_bytes()).hexdigest(),
        'evidence': evidence,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'artifacts/v9/mechanism-counterfactuals.json')
    args = parser.parse_args()
    result = audit(args.out)
    print(json.dumps({'output': str(args.out), 'offline_sql_executions': result['offline_sql_executions'],
                      'learner_model_calls': 0, 'admissions_inspected': len(result['evidence'])}))
