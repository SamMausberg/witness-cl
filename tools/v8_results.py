"""Build descriptive v8 pilot tables only from an independently replayed grid.

One development stream cannot support stream-level significance or the target
continual-learning claim. Resource-complete is not competence-qualified. Hash
checks bind saved receipts to their inputs; they do not authenticate execution.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = {'full_history': 'Full history', 'verbatim': 'Retrieved episodes',
          'insights': 'Evolving insights', 'fragments': 'Checked fragments',
          'fragments_unchecked': 'Unchecked fragments', 'stateless': 'Stateless'}
SOURCE_FILES = frozenset((
    'src/witness_cl/sql_env_v8.py', 'src/witness_cl/fragments_v8.py',
    'src/witness_cl/memory_v8.py', 'src/witness_cl/model_v8.py',
    'src/witness_cl/abstraction_v8.py', 'experiments/sql_abstractions_v8.py',
    'docs/v8/EVALUATION.md',
))
PHASE_COUNTS = {'ordinary': 24, 'old_before': 8, 'old_after': 8, 'final': 8}
SCHEDULE = ([('ordinary', i) for i in range(8)]
            + [('old_before', i) for i in range(8)]
            + [('ordinary', i) for i in range(8, 24)]
            + [('old_after', i) for i in range(8)]
            + [('final', i) for i in range(8)])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, name):
    require(type(value) is int and value >= 0, name + ' must be a nonnegative integer')
    return value


def finite(value, name):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            name + ' must be finite and nonnegative')
    return value


def read_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('nonfinite JSON value: ' + value)
    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_rows(rows):
    """Fail closed even when a caller bypasses load_verified for summarization."""
    require(set(rows) == set(LABELS), 'all six arms required')
    identities = set()
    for arm, entries in rows.items():
        require(type(entries) is list and len(entries) == len(SCHEDULE),
                'six complete eight-item phases required')
        for trace, (phase, index) in zip(entries, SCHEDULE):
            require(trace.get('arm') == arm, 'raw record arm identity changed')
            require(type(trace.get('episode_index')) is int
                    and (trace.get('phase'), trace['episode_index']) == (phase, index),
                    'phase grid is missing, duplicated, reordered or unknown')
            identities.add((trace.get('seed'), trace.get('condition')))
            require(trace.get('status') in ('completed', 'no_valid_answer'),
                    'unfinished, unknown or resource-stopped episode')
            require(type(trace.get('reward')) in (int, float) and trace['reward'] in (0, 1),
                    'binary finite reward required')
            attempts = integer(trace.get('select_attempts'), 'SELECT attempts')
            require(type(trace.get('queries')) is list and attempts == len(trace['queries']) <= 8,
                    'SELECT total differs from the bounded query ledger')
            for attempt, query in enumerate(trace['queries'], 1):
                require(type(query.get('attempt')) is int and query['attempt'] == attempt,
                        'query attempt ledger is missing or reordered')
            for name in ('query_seconds', 'elapsed_seconds'):
                finite(trace.get(name), name)
            memory = trace.get('memory_snapshot')
            require(type(memory) is dict, 'missing memory snapshot')
            current = integer(trace.get('memory_bytes'), 'retained memory bytes')
            require(integer(memory.get('memory_bytes'), 'snapshot memory bytes') == current,
                    'snapshot current storage differs from recorded retained storage')
            integer(memory.get('peak_memory_bytes'), 'snapshot peak storage')
            integer(memory.get('active_memory_bytes'), 'snapshot active storage')
            calls = trace.get('model_calls')
            require(type(calls) is list, 'missing model-call ledger')
            for call in calls:
                attempted = call.get('generation_attempted')
                require(type(attempted) is bool, 'unknown generation-attempt flag')
                require(not call.get('test_double'), 'test-double calls are not an inference comparison')
                finite(call.get('tokenization_seconds'), 'tokenization seconds')
                if attempted:
                    usage = call.get('usage')
                    require(type(usage) is dict, 'unknown generation usage cannot be omitted from totals')
                    values = [integer(usage.get(k), k) for k in
                              ('prompt_tokens', 'completion_tokens', 'total_tokens')]
                    require(values[2] == values[0] + values[1], 'inconsistent token usage')
                    require(call.get('status') == 'completed', 'failed or unfinished generation')
                    finite(call.get('inference_seconds'), 'inference seconds')
                else:
                    require(call.get('status') == 'preflight_failed'
                            and call.get('error_type') == 'BudgetStop'
                            and call.get('usage') is None,
                            'non-generated call is not an accounted preflight-only budget stop')
                    require(call.get('inference_seconds', 0) == 0,
                            'non-generated call contains inference time')
    require(len(identities) == 1, 'this descriptive report requires exactly one stream')


def load_verified(root=ROOT):
    root = Path(root)
    study = root / 'artifacts/v8/development'
    audit_path = root / 'artifacts/v8/development-replay.json'
    receipts = read_json(audit_path.read_text())
    require(type(receipts) is list and len(receipts) == 1 and type(receipts[0]) is dict,
            'exactly one independent replay receipt required')
    audit = receipts[0]
    manifest = read_json((study / 'manifest.json').read_text())
    summary = read_json((study / 'summary.json').read_text())
    freeze = read_json((root / 'artifacts/v8/prepilot-freeze.json').read_text())
    require(audit.get('status') == 'passed' and audit.get('pilot_completeness') == 'complete'
            and all(audit.get(k) is True for k in (
                'resource_comparison_complete', 'planned_records_complete',
                'required_records_complete', 'known_usage_complete',
                'sqlite_outcomes_complete', 'full_six_arm_grid', 'wall_cap_respected')),
            'complete independently replayed resource accounting required')
    require(audit.get('failures') == [] and audit.get('protocol_issues') == [],
            'replay contains unresolved failures or protocol issues')
    checked = audit.get('checked', {})
    require(all(integer(checked.get(k, 0), k) == 0 for k in (
        'unknown_usage_calls', 'test_double_calls', 'resource_stopped_episodes',
        'runtime_failed_episodes', 'timing_dependent_errors_unverified')),
        'unknown, simulated, stopped or unverifiable records cannot form a comparison')
    require(manifest.get('status') == audit.get('manifest_status') == 'completed'
            and manifest.get('source_unchanged') is True
            and manifest.get('required_records_complete') is True,
            'completed unchanged manifest required')
    for key, path in [('manifest_sha256', study / 'manifest.json'),
                      ('summary_sha256', study / 'summary.json'),
                      ('checked_freeze_sha256', root / 'artifacts/v8/prepilot-freeze.json'),
                      ('auditor_source_sha256', root / 'experiments/audit_sql_abstractions_v8.py'),
                      ('checked_model_provenance_sha256', root / 'artifacts/v8/model-provenance.json')]:
        require(audit.get(key) == sha(path), 'stale audit: ' + key)
    source_map = audit.get('checked_source_sha256')
    require(type(source_map) is dict and set(source_map) == SOURCE_FILES
            and source_map == manifest.get('source_sha256') == freeze.get('source_sha256'),
            'incomplete or inconsistent frozen source hash maps')
    require(freeze.get('model_provenance_sha256') == audit['checked_model_provenance_sha256'],
            'model provenance differs from frozen receipt')
    for path, expected in source_map.items():
        require(sha(root / path) == expected, 'changed executed source: ' + path)
    seeds, conditions, arms = (manifest.get(k) for k in ('seeds', 'conditions', 'arms'))
    require(type(seeds) is list and len(seeds) == 1 and type(seeds[0]) is int
            and 90000 <= seeds[0] <= 90003
            and type(conditions) is list and len(conditions) == 1
            and conditions[0] in ('reuse', 'nonreuse', 'near_match')
            and type(arms) is list and len(arms) == 6 and set(arms) == set(LABELS),
            'exactly one declared development stream with six arms required')
    expected_files = {f'{seeds[0]}-{conditions[0]}-{arm}.jsonl' for arm in LABELS}
    raw_map = audit.get('raw_sha256')
    require(type(raw_map) is dict and set(raw_map) == expected_files
            and raw_map == manifest.get('raw_sha256')
            and {p.name for p in study.glob('*.jsonl')} == expected_files,
            'raw file/hash/name grid changed')
    rows = {}
    for arm in LABELS:
        name = f'{seeds[0]}-{conditions[0]}-{arm}.jsonl'
        require(sha(study / name) == raw_map[name], 'raw records changed: ' + name)
        lines = (study / name).read_text().splitlines(keepends=True)
        require(all(line.endswith('\n') for line in lines), 'truncated raw record')
        entries = [read_json(line) for line in lines]
        require(all([t.get('seed'), t.get('condition'), t.get('arm')]
                    == [seeds[0], conditions[0], arm] for t in entries),
                'raw record belongs to another run')
        rows[arm] = entries
    validate_rows(rows)
    require(integer(manifest.get('completed_episode_records'), 'manifest record count') == 288,
            'incomplete manifest record total')
    require(type(summary) is list and len(summary) == 6, 'six complete summary groups required')
    summary_map = {}
    for row in summary:
        arm = row.get('arm')
        require(arm in LABELS and arm not in summary_map
                and row.get('seed') == seeds[0] and row.get('condition') == conditions[0],
                'unknown or duplicate summary group')
        require(row.get('phase_counts') == PHASE_COUNTS, 'incomplete summary phase counts')
        require(row.get('memory') == rows[arm][-1]['memory_snapshot'],
                'final summary memory differs from the last raw snapshot')
        for name in ('ordinary_budget', 'panel_budget'):
            require(integer(row[name].get('unknown_usage_calls'), 'summary unknown usage') == 0,
                    'summary contains unknown usage')
        summary_map[arm] = row
    finite(manifest.get('elapsed_seconds'), 'pilot elapsed seconds')
    return manifest, audit, rows


def summarize(rows):
    validate_rows(rows)
    records = []
    for arm in LABELS:
        ts = rows[arm]
        phases = {'warm': [t for t in ts if t['phase']=='ordinary' and t['episode_index']<8],
                  'middle': [t for t in ts if t['phase']=='ordinary' and 8<=t['episode_index']<16],
                  'late': [t for t in ts if t['phase']=='ordinary' and t['episode_index']>=16]}
        phases.update({phase:[t for t in ts if t['phase']==phase] for phase in ('old_before','old_after','final')})
        calls = [c for t in ts for c in t['model_calls']]
        generated = [c for c in calls if c['generation_attempted']]
        outcomes = {p:{'correct':int(sum(t['reward'] for t in rr)), 'n':len(rr),
                       'selects':sum(t['select_attempts'] for t in rr)} for p,rr in phases.items()}
        statuses = Counter(t.get('abstraction_proposal',{}).get('status') for t in ts)
        actions = Counter(a.get('action', a.get('kind')) for t in ts for a in t['actions'])
        records.append({'arm':arm,'phases':outcomes,'selects':sum(t['select_attempts'] for t in ts),
                        'model_calls':len(generated), 'tokenization_calls':len(calls),
                        'preflight_only_calls':len(calls)-len(generated),
                        'prompt_tokens':sum(c['usage']['prompt_tokens'] for c in generated),
                        'completion_tokens':sum(c['usage']['completion_tokens'] for c in generated),
                        'model_seconds':sum(c.get('inference_seconds',0)+c['tokenization_seconds'] for c in calls),
                        'query_seconds':sum(t['query_seconds'] for t in ts),
                        'episode_seconds':sum(t['elapsed_seconds'] for t in ts),
                        'peak_memory_bytes':max(max(t['memory_bytes'], t['memory_snapshot']['peak_memory_bytes']) for t in ts),
                        'peak_active_memory_bytes':max(t['memory_snapshot']['active_memory_bytes'] for t in ts),
                        'last_memory_bytes':ts[-1]['memory_bytes'],
                        'accepted_reconstruction_witnesses':statuses['accepted'],
                        'rejected_proposals':statuses['rejected'],'use_actions':actions['USE'],
                        'compose_actions':actions['COMPOSE'],
                        'executed_fragments':sum('executed_fragment_digest' in a for t in ts for a in t['actions']),
                        'zero_query_correct':sum(t['reward']==1 and not t['queries'] for t in ts),
                        'zero_answers':sum(t['answer']==0 for t in ts),
                        'catalog_queries':sum('catalog' in q['sql'].lower() for t in ts for q in t['queries']),
                        'sql_errors':sum(q['error'] is not None for t in ts for q in t['queries']),
                        'actions':dict(actions),
                        'old_constant_item_before':phases['old_before'][6]['reward'],
                        'old_constant_item_after':phases['old_after'][6]['reward']})
    return records


def main():
    manifest, audit, rows = load_verified()
    records = summarize(rows)
    arm = {r['arm']:r for r in records}
    qualification = (all(arm[a]['phases']['warm']['correct']>=6 for a in ('full_history','insights'))
                     and arm['fragments']['phases']['old_before']['correct']>=6)
    payload = {'kind':'single_development_stream_descriptive_report','claim_confirmed':False,
               'competence_thresholds_met':qualification,'stream_count':1,
               'elapsed_seconds':manifest['elapsed_seconds'], 'rows':records,
               'source_manifest_sha256':sha(ROOT/'artifacts/v8/development/manifest.json'),
               'source_replay_sha256':sha(ROOT/'artifacts/v8/development-replay.json'),
               'analysis_source_sha256':sha(Path(__file__)),
               'confidence_intervals':'not estimated from a single correlated stream',
               'storage_measure':'serialized retained learner state including journals; not Python heap, process RSS or model memory',
               'catalog_query_count_method':'case-insensitive SQL text mention, not an SQL AST classification'}
    (ROOT/'artifacts/v8/results.json').write_text(json.dumps(payload,indent=2)+'\n')
    tab=[r'\begin{tabular}{lrrrrrr}',r'\toprule',
         r'Arm & Warm & Middle & Late & Old pre & Old post & Final \\',r'\midrule']
    for r in records:
        tab.append(LABELS[r['arm']]+' & '+' & '.join(str(r['phases'][p]['correct'])+'/8' for p in ('warm','middle','late','old_before','old_after','final'))+r' \\')
    tab += [r'\bottomrule',r'\end{tabular}']
    (ROOT/'paper/v8_accuracy.tex').write_text('\n'.join(tab)+'\n')
    tab=[r'\begin{tabular}{lrrrrrr}',r'\toprule',
         r'Arm & SELECTs & Calls & Input tok. & Output tok. & Model s & Peak KiB \\',r'\midrule']
    for r in records:
        tab.append(LABELS[r['arm']]+' & '+f"{r['selects']} & {r['model_calls']} & {r['prompt_tokens']:,} & {r['completion_tokens']:,} & {r['model_seconds']:.1f} & {r['peak_memory_bytes']/1024:.1f}"+r' \\')
    tab += [r'\bottomrule',r'\end{tabular}']
    (ROOT/'paper/v8_costs.tex').write_text('\n'.join(tab)+'\n')
    print(json.dumps({'elapsed_seconds':manifest['elapsed_seconds'],'competence_thresholds_met':qualification,
                      'all_selects':sum(r['selects'] for r in records),
                      'all_calls':sum(r['model_calls'] for r in records),
                      'all_tokens':sum(r['prompt_tokens']+r['completion_tokens'] for r in records),
                      'accepted_witnesses':sum(r['accepted_reconstruction_witnesses'] for r in records)}))


if __name__=='__main__':
    main()
