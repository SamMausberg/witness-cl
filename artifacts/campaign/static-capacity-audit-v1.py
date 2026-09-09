"""Offline capacity accounting; deliberately no learner execution or model request."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone
import statistics
import sys
ROOT = Path.cwd()
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from witness_cl.campaign_io import canonical, read, save, sha
from witness_cl.query_memory import QueryMemory, _view_payload
from witness_cl.delayed_memory import DelayedMemory
from witness_cl.source_views import lift_source, UnsupportedSource

LIMIT = 65536

def nbytes(value):
    return len(canonical(value).encode())

def is_doc(record):
    return 'text_rows' in record

def record_stats(records, views=()):
    docs = [record for record in records if is_doc(record)]
    sql = [record for record in records if not is_doc(record)]
    contents = {canonical([record['columns'], record['text_rows']]) for record in docs}
    row_payloads = {canonical(record['text_rows']) for record in docs}
    return {
        'payload_bytes': nbytes({'prior_sql_and_feedback': records, 'source_derived_views': list(views)}),
        'records': len(records), 'catalog_records': len(docs), 'query_records': len(sql),
        'distinct_catalog_contents': len(contents),
        'catalog_record_json_bytes': sum(nbytes(record) for record in docs),
        'sql_record_json_bytes': sum(nbytes(record) for record in sql),
        'sql_text_bytes': sum(len(record['sql'].encode()) for record in sql),
        'catalog_text_rows_json_bytes': sum(nbytes(record['text_rows']) for record in docs),
        'redundant_catalog_text_rows_json_bytes': sum(nbytes(record['text_rows']) for record in docs) - sum(len(text.encode()) for text in row_payloads),
        'view_payload_json_bytes': nbytes(list(views)),
    }

def dedup_key(record, schema):
    if is_doc(record):
        return canonical(['catalog_content', schema, record['columns'], record['text_rows']])
    return canonical(['query', record])

def replay_capacity(records, views=(), content_dedup=False):
    kept = []
    timeline = []
    drops = []
    key_map = {}
    for row in records:
        trace = row['trace']
        item_memory = QueryMemory('sql_archive')
        fixture_trace = deepcopy(trace)
        fixture_trace['learn'] = True
        # These recorded cold outputs are static inputs, not a counterfactual
        # model policy. There are no relation admissions or scoring changes.
        item_memory.finish(fixture_trace, trace['conversation'])
        for record in item_memory.evidence:
            key = dedup_key(record, trace['schema']) if content_dedup else canonical(record)
            kept = [(old_key, old, original_index) for old_key, old, original_index in kept if old_key != key]
            kept.append((key, deepcopy(record), row['index']))
            while nbytes({'prior_sql_and_feedback': [old for _, old, _ in kept],
                          'source_derived_views': list(views)}) > LIMIT:
                _, removed, original_index = kept.pop(0)
                drops.append({'evicted_after_episode': row['index'], 'source_episode': original_index,
                              'kind': 'catalog' if is_doc(removed) else 'sql'})
        timeline.append({'ordinary_episode': row['index'], **record_stats([old for _, old, _ in kept], views)})
    result = record_stats([old for _, old, _ in kept], views)
    result.update(first_capacity_eviction_after_episode=drops[0]['evicted_after_episode'] if drops else None,
                  capacity_evictions=len(drops),
                  retained_sql_episode_indices=sorted({i for _, old, i in kept if not is_doc(old)}),
                  retained_initial_eight_sql_episode_indices=sorted({i for _, old, i in kept if not is_doc(old) and i < 8}),
                  eviction_counts=dict(Counter(item['kind'] for item in drops)),
                  timeline=timeline)
    return result

result = {
    'kind': 'static_memory_capacity_audit', 'created_utc': datetime.now(timezone.utc).isoformat(),
    'limits': {'compact_active_payload_bytes': LIMIT, 'context_tokens': LIMIT, 'output_reservation_tokens': 4096},
    'scope': 'Replay previously measured cold v1 SQL/conversations only as static capacity fixtures. No model generation, no inferred stateful outcomes, no actual delayed relation admissions, no edited frozen learner.',
    'model_calls': 0, 'source_modules_sha256': {},
    'dedup_hypothesis': 'Within the same observed public schema, deduplicate direct catalog projections by exact returned columns and text_rows, retaining the most recent original evidence record and preserving all original raw receipts. Ordinary SQL records keep current exact-record deduplication.',
    'reserve_hypothesis': 'Zero learned views, and separately a conservative four-largest payload reserve drawn from liftable correct terminal SQL in the saved cold stream; these are never claimed to be admitted or corroborated relations.',
    'streams': [],
}
base = ROOT / 'artifacts/campaign/coder-v1'
for relative in ('src/witness_cl/query_memory.py', 'src/witness_cl/delayed_memory.py', 'src/witness_cl/source_views.py'):
    expected = read(base / 'qualification-reuse/freeze.json')['source_sha256'][relative]
    assert sha(ROOT / relative) == expected
    result['source_modules_sha256'][relative] = expected
for condition in ('reuse', 'drift'):
    directory = base / ('qualification-' + condition)
    frozen = read(directory / 'freeze.json')
    for seed in frozen['seeds']:
        records = [read(directory / 'episodes' / f'{seed}-{condition}-ordinary-{index:03d}-full_history.json') for index in range(24)]
        paths = [directory / 'episodes' / (record['key'] + '.json') for record in records]
        unbounded = []
        views = {}
        unsupported = []
        history = QueryMemory('full_history')
        for record in records:
            trace = deepcopy(record['trace'])
            trace['learn'] = True
            memory = QueryMemory('sql_archive')
            memory.finish(trace, trace['conversation'])
            for evidence in memory.evidence:
                unbounded = [old for old in unbounded if canonical(old) != canonical(evidence)]
                unbounded.append(evidence)
            history.finish(trace, trace['conversation'])
            if trace['reward'] == 1:
                terminal = trace['queries'][trace['answer_query_index']]
                try:
                    view = lift_source(terminal['sql'], terminal['params'], trace['schema'], trace['question'])
                except (UnsupportedSource, ValueError) as exc:
                    unsupported.append(type(exc).__name__)
                else:
                    views[view.key] = _view_payload(view)
        reserve = sorted(views.values(), key=nbytes, reverse=True)[:4]
        row = {
            'seed': seed, 'condition': condition, 'ordinary_records': 24,
            'record_sha256': {path.name: sha(path) for path in paths},
            'unbounded_current_evidence': record_stats(unbounded),
            'empty_registry_current_policy': replay_capacity(records),
            'empty_registry_catalog_dedup_hypothesis': replay_capacity(records, content_dedup=True),
            'four_source_payload_reserve_current_policy': replay_capacity(records, reserve),
            'four_source_payload_reserve_catalog_dedup_hypothesis': replay_capacity(records, reserve, True),
            'source_payload_reserve': {'candidate_count': len(views), 'unsupported_correct_queries': len(unsupported),
                                      'reserved_views': len(reserve), 'json_bytes': nbytes(reserve),
                                      'keys': [view['view'] for view in reserve]},
            'full_history_static_conversation': {'active_bytes': history.active_bytes(),
                'messages': sum(len(episode) for episode in history.history),
                'content_bytes': sum(len(message['content'].encode()) for episode in history.history for message in episode)},
        }
        result['streams'].append(row)

# Only lengths and already measured token counts are read from the running v2
# qualification. This does not request tokenization or generation.
directory = ROOT / 'artifacts/campaign/dense-v2/qualification-reuse'
paths = sorted((directory / 'episodes').glob('*.json'))
observations = []
calibrations = []
for path in paths:
    row = read(path)
    if row['phase'] != 'ordinary':
        continue
    trace = row['trace']
    calls = trace['model_calls']
    if not calls or any(call.get('usage') is None or call.get('status') != 'completed' for call in calls):
        continue
    first = calls[0]
    prompt_bytes = sum(len(message['content'].encode()) for message in first['messages'])
    calibrations.append(first['preflight_tokens'] / prompt_bytes)
    observations.append({
        'key': row['key'], 'record_sha256': sha(path),
        'calls': len(calls),
        'measured_completion_tokens': sum(call['usage']['completion_tokens'] for call in calls),
        'hidden_reasoning_characters': sum(len(call.get('reasoning_content') or '') for call in calls),
        'rationale_characters': sum(len(action.get('rationale') or '') for action in trace['actions']),
        'public_history_content_bytes': sum(len(message['content'].encode()) for message in trace['conversation'] if message['role'] != 'assistant'),
        'assistant_history_content_bytes': sum(len(message['content'].encode()) for message in trace['conversation'] if message['role'] == 'assistant'),
        'history_messages': len(trace['conversation']),
        'cold_first_prompt_tokens': first['preflight_tokens'],
    })
if observations:
    scenarios = {}
    for aggregation, select in (('observed_mean', statistics.mean), ('observed_maximum_repeated', max)):
        public = select(row['public_history_content_bytes'] for row in observations)
        completion = select(row['measured_completion_tokens'] for row in observations)
        messages = select(row['history_messages'] for row in observations)
        cold = max(row['cold_first_prompt_tokens'] for row in observations)
        scenarios[aggregation] = {
            'episodes_extrapolated': 24,
            'completion_tokens_per_episode': completion,
            'public_content_bytes_per_episode': public,
            'history_messages_per_episode': messages,
            'estimates': {
                label: {'estimated_next_prompt_tokens': round(cold + 24 * (public * ratio + completion + 12 * messages)),
                        'including_reserved_4096_output_tokens': round(cold + 24 * (public * ratio + completion + 12 * messages) + 4096)}
                for label, ratio in (
                    ('observed_cold_prompt_density', statistics.mean(calibrations)),
                    ('public_text_one_token_per_three_bytes', 1 / 3),
                    ('public_text_one_token_per_two_bytes', 1 / 2))
            },
        }
    result['v2_full_history_length_projection'] = {
        'scope': 'Length extrapolation from this explicit saved prefix, not actual full-history prompt tokenization or predicted model behavior. Public-text density and 12 role/framing tokens per message are approximations. Completion usage is conservatively reused as visible assistant token count; hidden reasoning, if nonzero, would weaken this interpretation.',
        'records_observed': len(observations), 'observations': observations,
        'cold_prompt_token_per_content_byte_range': [min(calibrations), max(calibrations)],
        'scenarios': scenarios,
        'not_a_context_fit_guarantee': True,
        'protocol_extreme': 'Five 4096-token completions in each of 24 episodes alone exceed the 65536 context; current full-history policy must stop on exact preflight overflow, never truncate.',
    }
else:
    result['v2_full_history_length_projection'] = {'status': 'no complete ordinary v2 receipts yet'}
destination = ROOT / 'artifacts/campaign/static-capacity-audit-v1.json'
if destination.exists():
    raise ValueError('capacity report already exists')
result['analysis_script_sha256'] = sha(__file__)
save(destination, result)
print({'report': str(destination)})
for row in result['streams']:
    a=row['empty_registry_current_policy']; b=row['empty_registry_catalog_dedup_hypothesis']
    c=row['four_source_payload_reserve_current_policy']; d=row['four_source_payload_reserve_catalog_dedup_hypothesis']
    print({'seed':row['seed'],'condition':row['condition'],
           'current': {k:a[k] for k in ('payload_bytes','catalog_records','query_records','redundant_catalog_text_rows_json_bytes','first_capacity_eviction_after_episode','capacity_evictions','retained_initial_eight_sql_episode_indices')},
           'dedup':{k:b[k] for k in ('payload_bytes','catalog_records','query_records','capacity_evictions')},
           'reserve_bytes':row['source_payload_reserve']['json_bytes'],
           'reserved_current_sql':c['query_records'],'reserved_current_drops':c['capacity_evictions'],
           'reserved_dedup_bytes':d['payload_bytes'],'reserved_dedup_drops':d['capacity_evictions'],
           'history_content_bytes':row['full_history_static_conversation']['content_bytes']})
print('v2_length_projection', {key:value for key,value in result['v2_full_history_length_projection'].items() if key != 'observations'})
