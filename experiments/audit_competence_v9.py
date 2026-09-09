#!/usr/bin/env python3
"""Bounded saved-data replay of v9 development diagnostics; never calls a model.

Independent SQLite connections execute recorded requests. Environment generation,
SQL action validation and public prompt constants are shared checked sources.
Receipts establish consistency, not authentic execution or backend tokenization.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from experiments.audit_sql_abstractions_v8 import (
    AuditError, Budget, SQLiteReplay, exact, finite, integer, read_json, require, sha,
)
from witness_cl.memory_v8 import SYSTEM, ACTION_SCHEMA, canonical, parse_action
from witness_cl.sql_env_v8 import make_stream, evaluator_metadata

SOURCES = (
    'experiments/competence_v9.py', 'src/witness_cl/model_v9.py',
    'src/witness_cl/model_v8.py', 'src/witness_cl/memory_v8.py',
    'src/witness_cl/fragments_v8.py', 'src/witness_cl/sql_env_v8.py',
)


PROTOCOL_SOURCES = ('experiments/competence_v9.py', 'experiments/competence_interactive_v9.py')
COMMON_SOURCES = SOURCES[1:]


def protocol_source(manifest):
    source_map = manifest.get('source_sha256')
    require(type(source_map) is dict, 'source map is not an object')
    protocols = [path for path in PROTOCOL_SOURCES if path in source_map]
    require(len(protocols) == 1, 'source map must identify exactly one whitelisted diagnostic protocol')
    protocol = protocols[0]
    require(set(source_map) == {protocol, *COMMON_SOURCES}, 'source map is incomplete/substituted')
    return protocol


def evidence_system(protocol):
    require(protocol in PROTOCOL_SOURCES, 'unrecognized diagnostic source')
    # Literal extraction reads the frozen prompt without executing the runner.
    module = ast.parse((ROOT / protocol).read_text())
    values = [ast.literal_eval(node.value) for node in module.body
              if isinstance(node, ast.Assign) and any(
                  isinstance(target, ast.Name) and target.id == 'EVIDENCE_INSTRUCTIONS'
                  for target in node.targets)]
    require(len(values) == 1 and isinstance(values[0], str), 'missing fixed public evidence prompt')
    return values[0] if protocol == PROTOCOL_SOURCES[1] else values[0] + SYSTEM[SYSTEM.index('Return one JSON object'):]


def expected_decoding(variant):
    if variant in ('original', 'evidence'):
        return dict(temperature=0., top_p=1., top_k=0, min_p=0., presence_penalty=0., seed=42, thinking=False)
    if variant == 'sampled':
        return dict(temperature=.7, top_p=.8, top_k=20, min_p=0., presence_penalty=1.5, seed=42, thinking=False)
    require(variant == 'thinking', 'unknown diagnostic variant')
    return dict(temperature=.6, top_p=.95, top_k=20, min_p=0., presence_penalty=1.5, seed=42, thinking=True)


def check_call(call, messages, manifest, budget, counts, issues):
    exact(call.get('messages'), messages, 'model prompt differs from exact legal public/own-history input')
    require(call.get('phase') == 'warm:solve', 'unexpected model phase')
    output = manifest['output_tokens']
    require(type(call.get('max_output_tokens')) is int and call['max_output_tokens'] == output,
            'per-call output allowance differs')
    exact(call.get('decoding'), manifest['decoding'], 'recorded decoding differs')
    require(call.get('response_mode') == 'schema', 'diagnostic changed constrained-output mode')
    exact(call.get('response_schema'), ACTION_SCHEMA, 'action response schema differs')
    config = {k: v for k, v in manifest['decoding'].items() if k != 'thinking'}
    config.update(model=manifest['model'], max_tokens=output, cache_prompt=False, stream=False,
                  response_format={'type': 'json_object', 'schema': ACTION_SCHEMA},
                  chat_template_kwargs={'enable_thinking': manifest['decoding']['thinking']})
    exact(call.get('request_config'), config, 'effective request configuration differs')
    counts['recorded_model_calls'] += 1
    budget.tokenization_seconds += finite(call.get('tokenization_seconds'), 'tokenization seconds')
    status = call.get('status')
    require(status in ('completed', 'failed', 'preflight_failed'), 'unfinished model call')
    require(type(call.get('generation_attempted')) is bool, 'generation attempt flag is not Boolean')
    if call.get('test_double'):
        counts['test_double_calls'] += 1
    prompt = call.get('preflight_tokens')
    if prompt is not None:
        integer(prompt, 'preflight tokens')
    if status == 'preflight_failed':
        require(not call['generation_attempted'] and call.get('usage') is None, 'preflight contains generated usage')
        require(type(call.get('error_type')) is str, 'preflight failure lacks error type')
        if call['error_type'] != 'BudgetStop':
            return 'runtime_failure', call['error_type']
        reason = call.get('stop_reason')
        if reason == 'full_context_ceiling_no_truncation':
            require(prompt is not None and prompt + output > 32768, 'unjustified context stop')
        elif reason == 'model_token_ceiling':
            require(prompt is not None and budget.total_tokens + prompt + output > budget.max_total_tokens,
                    'unjustified token stop')
        elif reason == 'model_call_ceiling':
            require(budget.calls >= budget.max_calls, 'unjustified call stop')
        else:
            require(reason == 'wall_time_ceiling', 'unknown preflight stop')
        return 'resource_stop', reason
    require(call['generation_attempted'] and prompt is not None, 'generation lacks completed preflight')
    require(budget.calls < budget.max_calls and prompt + output <= 32768 and
            budget.total_tokens + prompt + output <= budget.max_total_tokens, 'generation exceeds reservation')
    budget.calls += 1
    budget.inference_seconds += finite(call.get('inference_seconds'), 'inference seconds')
    usage = call.get('usage')
    if usage is None:
        require(status == 'failed', 'completed call has unknown usage')
        budget.unknown_usage_calls += 1
    else:
        p, c, total = [integer(usage.get(key), key) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')]
        require(total == p + c, 'token usage sum differs')
        budget.prompt_tokens += p; budget.completion_tokens += c; budget.total_tokens += total
        if p < prompt or p + c > 32768 or c > output or budget.total_tokens > budget.max_total_tokens:
            require(status == 'failed', 'completed backend call violates token bounds')
            issues.append('recorded backend token bounds violated')
    if call.get('response_model') != manifest['model']:
        require(status == 'failed', 'response model alias differs')
        if call.get('response_model') is not None:
            issues.append('failed response has a different model alias')
    if status == 'failed':
        require(type(call.get('error_type')) is str, 'failed call lacks error type')
        return 'runtime_failure', call['error_type']
    require(type(call.get('content')) is str and usage is not None, 'completed call lacks text/known usage')
    require(call.get('reasoning_content') is None or type(call['reasoning_content']) is str, 'invalid reasoning payload')
    require(type(call.get('content_was_null')) is bool, 'missing content-null provenance')
    require(not call['content_was_null'] or call['content'] == '', 'null final content was silently replaced')
    if call.get('finish_reason') == 'length':
        counts['length_stopped_calls'] += 1
    if call.get('reasoning_content'):
        counts['calls_with_reasoning'] += 1
    return 'completed', call['content']


def check_episode(row, spec, manifest, budget, counts, issues):
    exact([row.get('question'), row.get('schema')], [spec._public.question, spec._public.schema], 'public episode differs')
    exact(row.get('evaluator'), evaluator_metadata(spec), 'evaluator metadata differs')
    exact(row.get('reference_answer'), spec._expected, 'reference scalar differs')
    messages = [{'role': 'system', 'content': SYSTEM if manifest['variant'] == 'original' else evidence_system(protocol_source(manifest))},
                {'role': 'user', 'content': canonical({'question': spec._public.question,
                 'schema': spec._public.schema, 'remaining_selects': 8})}]
    calls, queries = row['model_calls'], row['queries']
    require(type(calls) is list and len(calls) <= 10 and type(queries) is list and len(queries) <= 8,
            'episode exceeds action/SELECT caps')
    expected_actions, query_cursor, answer = [], 0, None
    status, failure = 'no_answer', None
    before_seconds = budget.tokenization_seconds + budget.inference_seconds
    db = SQLiteReplay(spec)
    try:
        reference = db.query(spec._gold_sql, {})
        require(reference['error'] is None and len(reference['rows']) == 1 and len(reference['rows'][0]) == 1
                and abs(reference['rows'][0][0] - spec._expected) <= 1e-9, 'independent reference disagrees')
        counts['independent_reference_cases'] += 1
        def query(sql, params, purpose):
            nonlocal query_cursor
            require(query_cursor < len(queries), 'missing query ledger entry')
            saved = queries[query_cursor]; query_cursor += 1
            exact([saved.get('sql'), saved.get('params'), saved.get('purpose')], [sql, params, purpose],
                  'query does not follow its model action')
            require(type(saved.get('attempt')) is int and saved['attempt'] == query_cursor, 'query attempt counter differs')
            replay = db.query(sql, params)
            actual = {k: saved[k] for k in ('columns', 'rows', 'error', 'truncated')}
            if actual['error'] in ('interrupted', 'query time limit exceeded') and actual != replay:
                issues.append('machine-specific SQL timeout is not independently reproducible')
            else:
                exact(actual, replay, 'independent SQLite outcome differs')
            counts['select_attempts'] += 1
            counts['query_errors'] += int(saved['error'] is not None)
            return saved
        for i, call in enumerate(calls):
            call_status, content = check_call(call, messages, manifest, budget, counts, issues)
            if call_status != 'completed':
                status, failure = call_status, content
                require(i == len(calls)-1, 'model calls continue after a resource/runtime failure')
                break
            messages.append({'role': 'assistant', 'content': content})
            try:
                action = parse_action(content)
                if action['action'] not in ('QUERY', 'ANSWER'):
                    raise ValueError('no executable entry is available in this diagnostic')
            except (ValueError, TypeError, KeyError) as exc:
                expected_actions.append({'kind': 'invalid', 'error': str(exc)})
                if query_cursor < 8:
                    query('', {}, 'invalid_action')
                messages.append({'role': 'user', 'content': canonical({'action_error': str(exc), 'remaining_selects': 8-query_cursor})})
                continue
            expected_actions.append(action)
            if action['action'] == 'ANSWER':
                answer, status = action['value'], 'completed'
                require(i == len(calls)-1, 'model calls continue after the answer')
                break
            if query_cursor >= 8:
                messages.append({'role': 'user', 'content': 'No SELECTs remain. Submit a finite numeric ANSWER using observed evidence.'})
                continue
            saved = query(action['sql'], action['params'], 'ordinary_query')
            messages.append({'role': 'user', 'content': canonical({'tool_result': {k: saved[k] for k in ('columns', 'rows', 'error', 'truncated')},
                                                                  'remaining_selects': 8-query_cursor})})
        if status == 'no_answer' and len(calls) < 10:
            # A budget check can reject before a preflight record is appended.
            reason = row.get('error')
            require(row.get('status') == 'resource_stop', 'episode stopped without a terminal event')
            budget.before_unrecorded_stop(reason, manifest['output_tokens'])
            status, failure = 'resource_stop', reason
        exact(row.get('actions'), expected_actions, 'recorded actions differ from model outputs')
        require(query_cursor == len(queries), 'unconsumed query records')
        require(type(row.get('select_attempts')) is int and row['select_attempts'] == query_cursor, 'SELECT total differs')
        exact(row.get('answer'), answer, 'scored answer differs from submitted action')
        reward = float(answer is not None and abs(answer-spec._expected) <= 1e-6*(1+abs(spec._expected)))
        exact(row.get('reward'), reward, 'correctness differs from independent reference')
        require(row.get('status') == status, 'episode terminal status differs')
        if status in ('completed', 'no_answer'):
            exact(row.get('feedback'), {'correct': reward == 1., 'meaning': 'Correct on this episode only.' if reward == 1.
                  else 'The submitted answer was INCORRECT.'}, 'scalar feedback differs')
        elif status == 'resource_stop':
            require(row.get('error') == failure, 'resource stop reason differs')
        else:
            require(row.get('error_type') == failure, 'runtime failure type differs')
        elapsed = finite(row.get('elapsed_seconds'), 'episode elapsed seconds')
        query_seconds = finite(row.get('query_seconds'), 'query seconds')
        integer(row.get('vm_steps'), 'VM steps')
        require(elapsed + 1e-5 >= query_seconds + budget.tokenization_seconds + budget.inference_seconds - before_seconds,
                'episode timing excludes recorded query/model time')
        counts['episodes'] += 1
        counts['correct_episodes'] += int(reward)
        counts['noncompleted_episodes'] += int(status != 'completed')
    finally:
        db.close()


def audit_directory(directory):
    directory = Path(directory).resolve()
    counts, issues, failures = Counter(), [], []
    report = {'directory': str(directory), 'status': 'failed', 'claim_confirmed': False,
              'auditor_source_sha256': sha(__file__), 'complete_warm_grid': False,
              'competence_threshold_met': False,
              'limitations': ['Saved consistency does not authenticate execution, model weights, exact backend tokenization or timing.',
                'Environment, parser and public prompt definitions are shared source; SQLite execution is independently replayed.',
                'A development competence screen does not establish transfer, efficiency or retention.']}
    try:
        manifest = read_json((directory/'manifest.json').read_text())
        require(manifest.get('kind') == 'adaptive_development_competence_diagnostic', 'wrong diagnostic kind')
        require(manifest.get('status') in ('completed', 'incomplete'), 'diagnostic has not finalized')
        require(manifest.get('claim_confirmed') is False and manifest.get('feedback_used_for_learning') is False,
                'diagnostic claim/information boundary changed')
        seed = integer(manifest.get('seed'), 'seed')
        require(92000 <= seed <= 92003, 'seed outside declared development diagnostic range')
        indices = manifest.get('indices')
        require(type(indices) is list and indices and len(set(indices)) == len(indices) and
                all(type(i) is int and 0 <= i < 8 for i in indices), 'diagnostic indices are not unique warm cases')
        require(type(manifest.get('model')) is str and bool(manifest['model']), 'missing model identity')
        exact(manifest.get('decoding'), expected_decoding(manifest['variant']), 'manifest decoding differs from variant')
        output = 2048 if manifest['variant'] == 'thinking' else 384
        require(type(manifest.get('output_tokens')) is int and manifest['output_tokens'] == output, 'manifest output cap differs')
        exact([manifest.get('max_selects'), manifest.get('max_actions')], [8, 10], 'episode caps differ')
        wall = finite(manifest.get('wall_seconds'), 'wall cap')
        require(0 < wall <= 900, 'wall cap exceeds bounded diagnostic')
        protocol = protocol_source(manifest)
        for path in (protocol, *COMMON_SOURCES):
            require(sha(ROOT/path) == manifest['source_sha256'][path], 'source drift: ' + path)
        require(manifest.get('source_unchanged') is True, 'source changed during diagnostic')
        raw_path = directory/'episodes.jsonl'
        require(sha(raw_path) == manifest.get('raw_sha256'), 'raw digest differs')
        raw = raw_path.read_text()
        require(not raw or raw.endswith('\n'), 'truncated raw record')
        rows = [read_json(line) for line in raw.splitlines()]
        require(len(rows) <= len(indices) and len(rows) == manifest.get('n'), 'record count differs')
        budget = Budget(max_calls=100, max_total_tokens=400000)
        stream = make_stream(seed, 'reuse', split='development')
        stopped = False
        for index, row in zip(indices, rows):
            require(not stopped, 'diagnostic continues after terminal failure')
            exact([row.get(k) for k in ('index', 'variant', 'model', 'seed')],
                  [index, manifest['variant'], manifest['model'], seed], 'raw identity/order differs')
            check_episode(row, stream.ordinary[index], manifest, budget, counts, issues)
            stopped = row['status'] in ('runtime_failure', 'resource_stop')
        expected_status = 'completed' if len(rows) == len(indices) and not stopped else 'incomplete'
        require(manifest['status'] == expected_status, 'manifest completion differs')
        exact(manifest.get('correct'), sum(r['reward'] for r in rows), 'manifest score differs')
        saved = manifest.get('budget')
        require(type(saved) is dict and set(saved) == set(vars(budget)), 'budget fields differ')
        for field, expected in vars(budget).items():
            if field.endswith('_seconds'):
                require(math.isclose(finite(saved[field], field), expected, rel_tol=1e-10, abs_tol=1e-9), 'budget timing differs: ' + field)
            else:
                require(type(saved[field]) is int and saved[field] == expected, 'budget counter differs: ' + field)
        elapsed = finite(manifest.get('elapsed_seconds'), 'elapsed seconds')
        require(elapsed + 1e-5 >= sum(r['elapsed_seconds'] for r in rows), 'manifest time excludes recorded episodes')
        if elapsed > wall:
            issues.append('recorded elapsed time exceeds declared wall ceiling')
        complete = indices == list(range(8)) and len(rows) == 8 and all(r['status'] == 'completed' for r in rows)
        report.update(status='passed', protocol_source=protocol, manifest_status=manifest['status'], complete_warm_grid=complete,
                      competence_threshold_met=complete and counts['correct_episodes'] >= 6 and not issues
                          and budget.unknown_usage_calls == 0 and counts['test_double_calls'] == 0,
                      recorded_budget=vars(budget), elapsed_seconds=elapsed,
                      known_usage_complete=budget.unknown_usage_calls == 0,
                      manifest_sha256=sha(directory/'manifest.json'), raw_sha256=sha(raw_path),
                      checked_source_sha256=manifest['source_sha256'])
    except (AuditError, ValueError, TypeError, KeyError, IndexError, OSError, OverflowError) as exc:
        failures.append({'type': type(exc).__name__, 'message': str(exc)[:1024]})
    report.update(checked=dict(counts), failures=failures, protocol_issues=sorted(set(issues)))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    reports = [audit_directory(p) for p in args.directories]
    text = json.dumps(reports, indent=2, allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end='')
    return 0 if all(r['status'] == 'passed' for r in reports) else 1


if __name__ == '__main__':
    raise SystemExit(main())
