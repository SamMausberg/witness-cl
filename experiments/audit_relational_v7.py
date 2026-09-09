"""Independently replay saved v7 relational evidence using only the standard library.

No learner, gate, experiment runner, or supplied policy evaluator is imported.
The verifier reconstructs visible data, executes its own gold SQL, evaluates
serialized numerical policies, and replays exact audit capital and alpha spend.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
from functools import lru_cache
import gzip
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import random
import sqlite3
import statistics


class ReplayFailure(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReplayFailure(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value, description):
    require(type(value) in (int, float) and math.isfinite(value), description)
    return float(value)


def close(actual, expected, description, *, tolerance=1e-11):
    actual, expected = _finite(actual, description), _finite(expected, description)
    require(abs(actual - expected) <= tolerance * (1 + abs(expected)),
            f'{description}: recorded={actual!r}, replay={expected!r}')


def typed_mono(value):
    require(type(value) in (tuple, list) and len(value) == 6,
            'six-exponent monomial required')
    require(all(type(v) is int and v >= 0 for v in value) and sum(value) <= 3,
            'monomial outside frozen degree-three grammar')
    return tuple(value)


def checked_policy(serialized, expected_digest=None):
    require(type(serialized) is dict and set(serialized) == {'features', 'coefficients'},
            'serialized policy fields differ from frozen contract')
    features, coefficients = serialized['features'], serialized['coefficients']
    require(type(features) in (list, tuple) and type(coefficients) in (list, tuple)
            and 1 <= len(features) <= 84 and len(features) == len(coefficients),
            'invalid serialized policy dimensions')
    monos = tuple(typed_mono(m) for m in features)
    require(len(set(monos)) == len(monos), 'duplicated policy feature')
    for coefficient in coefficients:
        require(abs(_finite(coefficient, 'nonfinite policy coefficient')) <= 1e12,
                'coefficient exceeds frozen magnitude cap')
    digest = hashlib.sha256(canonical(serialized)).hexdigest()
    if expected_digest is not None:
        require(digest == expected_digest, 'serialized policy digest mismatch')
    return monos, tuple(float(c) for c in coefficients), digest


def replay_prediction(serialized, rows, *, expected_digest=None):
    features, coefficients, _ = checked_policy(serialized, expected_digest)
    values = []
    for exponents in features:
        value = sum(math.prod(cell ** exponent for cell, exponent in zip(row, exponents))
                    for row in rows)
        values.append(value)
    prediction = math.fsum(c * v for c, v in zip(coefficients, values))
    require(math.isfinite(prediction), 'nonfinite replayed prediction')
    return prediction


def replay_reward(prediction, target):
    prediction = _finite(prediction, 'nonfinite prediction')
    target = _finite(target, 'nonfinite target')
    return int(abs(prediction - target) <= 1e-6 * (1 + abs(target)))


@lru_cache(maxsize=1024)
def reconstructed_context(seed):
    require(type(seed) is int, 'context seed must be an integer')
    rng = random.Random(seed)
    number_groups = rng.randint(3, 8)
    groups = tuple((j, rng.randint(-2, 2), rng.randint(-2, 2)) for j in range(number_groups))
    number_items = rng.randint(12, 40)
    items = tuple((j, rng.randrange(number_groups), *(rng.randint(-3, 3) for _ in range(4)))
                  for j in range(number_items))
    weights = {row[0]: row[1:] for row in groups}
    joined = tuple(item[2:] + weights[item[1]] for item in items)
    return items, groups, joined


def verify_observation(record, seed):
    require(type(record) is dict, 'visible observation missing')
    items, groups, joined = reconstructed_context(seed)
    for name, expected in (('items', items), ('groups', groups), ('rows', joined)):
        supplied = record.get(name)
        require(type(supplied) in (list, tuple)
                and all(type(row) in (list, tuple) for row in supplied),
                f'malformed visible {name}')
        require(tuple(tuple(row) for row in supplied) == expected,
                f'visible {name} differ from independently regenerated context')
    require(record.get('query_count') == 2 and type(record.get('query_count')) is int,
            'observation did not charge exactly two SELECT measurements')
    require(_finite(record.get('query_seconds'), 'invalid measured query duration') >= 0,
            'negative measured query duration')
    return joined


def _recipe_key(recipe):
    require(type(recipe) in (tuple, list) and 1 <= len(recipe) <= 2,
            'gold recipe requires one or two terms')
    result = []
    for term in recipe:
        require(type(term) in (tuple, list) and len(term) == 2, 'invalid gold term')
        mono, coefficient = typed_mono(term[0]), term[1]
        require(type(coefficient) is int and 0 < abs(coefficient) <= 10,
                'invalid gold coefficient')
        result.append((mono, coefficient))
    return tuple(result)


@lru_cache(maxsize=2048)
def _gold_sql_cached(seed, recipe):
    items, groups, _ = reconstructed_context(seed)
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE groups (id INTEGER PRIMARY KEY, w0 INTEGER, w1 INTEGER)')
        db.execute('CREATE TABLE items (id INTEGER, group_id INTEGER, x0 INTEGER, x1 INTEGER, x2 INTEGER, x3 INTEGER)')
        db.executemany('INSERT INTO groups VALUES (?,?,?)', groups)
        db.executemany('INSERT INTO items VALUES (?,?,?,?,?,?)', items)
        db.execute('PRAGMA query_only=ON')
        expressions = []
        names = ('i.x0', 'i.x1', 'i.x2', 'i.x3', 'g.w0', 'g.w1')
        for powers, coefficient in recipe:
            factors = [column for column, power in zip(names, powers) for _ in range(power)]
            expressions.append(f'({coefficient} * ({" * ".join(factors) if factors else "1"}))')
        sql = ('SELECT COALESCE(SUM(' + ' + '.join(expressions) + '), 0) '
               'FROM items AS i INNER JOIN groups AS g ON g.id = i.group_id')
        target = db.execute(sql).fetchone()[0]
    return float(target)


def replay_gold(seed, recipe):
    return _gold_sql_cached(seed, _recipe_key(recipe))


def replay_gate(snapshot):
    """Validate every journal prefix without importing the implementation gate."""
    require(type(snapshot) is dict, 'gate snapshot missing')
    require(snapshot.get('format_version') == 1, 'unsupported gate snapshot version')
    config = snapshot.get('config')
    require(type(config) is dict and set(config) == {'alpha_total', 'max_pairs', 'max_audits'},
            'gate config fields changed')
    alpha_float = _finite(config['alpha_total'], 'nonfinite gate alpha')
    require(0 < alpha_float < 1, 'invalid gate alpha')
    require(type(config['max_pairs']) is int and 1 <= config['max_pairs'] <= 64,
            'invalid gate pair cap')
    require(type(config['max_audits']) is int and 1 <= config['max_audits'] <= 4096,
            'invalid gate audit cap')
    alpha_total = Fraction.from_float(alpha_float)
    gate_id = snapshot.get('gate_id')
    require(type(gate_id) is str and 0 < len(gate_id) <= 256, 'invalid gate identity')
    head = hashlib.sha256(canonical({'format': 'witness-cl-paired-gate-v7',
                                    'gate_id': gate_id, 'config': config})).hexdigest()
    events = snapshot.get('events')
    require(type(events) is list and len(events) <= config['max_audits'] * (config['max_pairs'] + 2),
            'invalid or excessive gate journal')
    audits, prefixes, used_samples = [], {}, set()
    allocation = Fraction(0)
    active = None
    for event_number, event in enumerate(events):
        require(type(event) is dict and type(event.get('audit_index')) is int,
                'malformed gate event')
        kind, index = event.get('kind'), event['audit_index']
        if kind == 'start':
            require(active is None or active['status'] != 'collecting', 'new audit replaced collecting audit')
            require(index == len(audits) + 1 and index <= config['max_audits'], 'audit counter reset or skipped')
            require(set(event) == {'kind', 'audit_index', 'candidate_digest', 'incumbent_digest',
                                  'scope', 'allocated_alpha_exact'}, 'start event fields changed')
            for name in ('candidate_digest', 'incumbent_digest', 'scope'):
                require(type(event[name]) is str and 0 < len(event[name]) <= 256, 'invalid frozen audit identity')
            alpha = alpha_total / (index * (index + 1))
            require(event['allocated_alpha_exact'] == str(alpha), 'audit alpha differs from permanent schedule')
            allocation += alpha
            active = {'index': index, 'candidate_digest': event['candidate_digest'],
                      'incumbent_digest': event['incumbent_digest'], 'scope': event['scope'],
                      'alpha': alpha, 'capital': Fraction(1), 'log_wealth': 0.0,
                      'log_threshold': -math.log(float(alpha)), 'pairs': 0, 'status': 'collecting',
                      'start_event': event_number, 'samples': []}
            audits.append(active)
        elif kind == 'pair':
            require(active is not None and active['index'] == index and active['status'] == 'collecting',
                    'pair attached to stale, unstarted, or terminal audit')
            require(set(event) == {'kind', 'audit_index', 'sample_id', 'candidate_reward',
                                  'incumbent_reward', 'status'}, 'pair event fields changed')
            sample_id = event['sample_id']
            require(type(sample_id) is str and 0 < len(sample_id) <= 512 and sample_id not in used_samples,
                    'duplicate or invalid audit sample ID')
            candidate = _finite(event['candidate_reward'], 'invalid candidate reward')
            incumbent = _finite(event['incumbent_reward'], 'invalid incumbent reward')
            require(0 <= candidate <= 1 and 0 <= incumbent <= 1, 'gate reward outside unit interval')
            difference = Fraction.from_float(candidate) - Fraction.from_float(incumbent)
            active['capital'] *= 1 + difference / 2
            active['log_wealth'] += math.log1p((candidate - incumbent) / 2)
            active['pairs'] += 1
            require(active['pairs'] <= config['max_pairs'], 'audit exceeds pair cap')
            accepted = (active['capital'] * active['alpha'] >= 1
                        and active['log_wealth'] >= active['log_threshold'])
            expected_status = ('accepted' if accepted else
                               ('inconclusive' if active['pairs'] == config['max_pairs'] else 'collecting'))
            require(event['status'] == expected_status, 'saved acceptance/status does not match independent wealth')
            active['status'] = expected_status
            used_samples.add(sample_id)
            active['samples'].append(sample_id)
            prefixes[sample_id] = {name: active[name] for name in (
                'index', 'candidate_digest', 'incumbent_digest', 'scope', 'alpha',
                'capital', 'log_wealth', 'log_threshold', 'pairs', 'status')}
            prefixes[sample_id].update(candidate_reward=candidate, incumbent_reward=incumbent)
        elif kind == 'finish_inconclusive':
            require(set(event) == {'kind', 'audit_index'}, 'finish event fields changed')
            require(active is not None and active['index'] == index and active['status'] == 'collecting',
                    'invalid early audit finish')
            active['status'] = 'inconclusive'
        else:
            raise ReplayFailure('unknown gate journal event')
        require(allocation == alpha_total * len(audits) / (len(audits) + 1) and allocation <= alpha_total,
                'alpha refunded or total allocation exceeded at a journal prefix')
        head = hashlib.sha256(bytes.fromhex(head) + canonical(event)).hexdigest()
        if kind == 'pair':
            prefixes[sample_id]['journal_hash'] = head
        if active is not None:
            active['last_journal_hash'] = head
    require(snapshot.get('started_audits') == len(audits), 'saved audit counter differs from journal')
    require(snapshot.get('allocated_alpha_total_exact') == str(allocation), 'saved permanent alpha total differs')
    require(snapshot.get('journal_hash') == head, 'gate journal hash-chain mismatch')
    return {'audits': audits, 'prefixes': prefixes, 'sample_ids': used_samples,
            'allocated_alpha_exact': allocation, 'journal_hash': head,
            'checked_events': len(events)}


METHODS = ('audited_grow_reuse', 'audited_grow_no_reuse', 'audited_full_history_sparse',
           'ungated_full_history_sparse', 'ungated_full_ridge', 'audited_grow_full84')
COST_FIELDS = ('contexts', 'measurement_selects', 'gold_selects', 'select_executions',
               'measurement_seconds', 'gold_seconds', 'setup_seconds', 'wall_seconds',
               'cpu_seconds', 'prediction_seconds', 'row_feature_evaluations')
COUNT_FIELDS = ('contexts', 'measurement_selects', 'gold_selects', 'select_executions',
                'row_feature_evaluations')


def reference_seed(*parts):
    return int.from_bytes(hashlib.sha256(canonical(parts)).digest(), 'big')


def reference_reports(run_seed):
    from itertools import combinations_with_replacement
    def exponent(indices):
        return tuple(indices.count(i) for i in range(6))
    rng = random.Random(run_seed)
    cross = [exponent((i, j)) for i in range(4) for j in (4, 5)]
    selected = rng.sample(cross, 4)
    cubic = [exponent((i, j, k)) for i, j in combinations_with_replacement(range(4), 2)
             for k in (4, 5)]
    extras = rng.sample(cubic, 2)
    recipes = [((m, 1),) for m in selected]
    recipes.extend((((selected[0], 1), (selected[1], 1)),
                    ((selected[2], 1), (selected[3], 1))))
    recipes.extend(((m, 1),) for m in extras)
    return [dict(index=i, public_id='report_' + format(reference_seed(run_seed, i), '064x')[:24],
                 kind='warm' if i < 4 else ('shared_novel' if i < 6 else 'unshared_novel'),
                 spec=recipe) for i, recipe in enumerate(recipes)]


def _stream_position(cursor, config):
    warm_end = 4 * config['warm_rounds']
    novel_end = warm_end + 4 * config['novel_rounds']
    matched_end = novel_end + 4 * config['retention_rounds']
    if cursor < warm_end:
        return cursor % 4, 'warm'
    if cursor < novel_end:
        return 4 + (cursor - warm_end) % 4, 'novel'
    if cursor < matched_end:
        return (cursor - novel_end) % 4, 'retention'
    return (cursor - matched_end) % 8, 'revisit'


def _mean(values):
    values = list(values)
    return statistics.mean(values) if values else None


def _same_mean(actual, expected, name):
    if expected is None:
        require(actual is None, f'{name} should be unknown for an empty sample')
    else:
        close(actual, expected, name)


def _initial_policy():
    features = [[0]*6]
    for j in range(6):
        feature = [0]*6
        feature[j] = 1
        features.append(feature)
    return {'features': features, 'coefficients': [0.0]*7}


def _check_gate_result(saved, replay, *, journal_hash=None):
    require(type(saved) is dict, 'missing saved gate result')
    for field, reference in (('status', replay['status']), ('audit_index', replay['index']),
                             ('candidate_digest', replay['candidate_digest']),
                             ('incumbent_digest', replay['incumbent_digest']),
                             ('scope', replay['scope']), ('pairs', replay['pairs']),
                             ('allocated_alpha_exact', str(replay['alpha']))):
        require(saved.get(field) == reference, 'gate result mismatch: ' + field)
    close(saved.get('allocated_alpha'), float(replay['alpha']), 'gate alpha float report')
    close(saved.get('log_wealth'), replay['log_wealth'], 'gate log wealth')
    close(saved.get('log_threshold'), replay['log_threshold'], 'gate log threshold')
    require(saved.get('journal_hash') == (journal_hash or replay['journal_hash']),
            'gate result references a different journal prefix')


def audit_stream(raw, *, expected_config=None):
    """Replay one complete raw stream; errors are explicit even under Python -O."""
    require(type(raw) is dict and raw.get('format_version') == 1, 'invalid raw run format')
    require(raw.get('status') == 'complete' and raw.get('error') is None, 'raw run is incomplete or failed')
    config = raw.get('config')
    require(type(config) is dict, 'run config absent')
    if expected_config is not None:
        require(config == expected_config, 'raw config differs from run manifest')
    seed, method, protocol = raw.get('seed'), raw.get('method'), raw.get('protocol')
    require(type(seed) is int and method in METHODS and protocol in ('matched', 'budget'),
            'invalid raw run identity')
    require(config.get('reward_tolerance') == 1e-6, 'reward tolerance differs from frozen v7 contract')
    for field in ('warm_rounds', 'novel_rounds', 'retention_rounds', 'snapshot_contexts', 'final_contexts'):
        require(type(config.get(field)) is int and config[field] >= 0, 'invalid phase/panel bound')
    for field in ('total_select_budget', 'ordinary_guard', 'matched_history', 'budget_history',
                  'candidate_every', 'candidate_minimum', 'max_pairs', 'max_audits'):
        require(type(config.get(field)) is int and config[field] > 0, 'invalid positive run bound')
    audited = method.startswith('audited_')
    reports = reference_reports(seed)
    require(canonical(raw.get('reports')) == canonical(reports), 'report identities/recipes differ from frozen generator')
    report_ids = [report['public_id'] for report in reports]
    recipes = {report['public_id']: report['spec'] for report in reports}
    registry = raw.get('policy_registry')
    require(type(registry) is dict and len(registry) <= 65536, 'invalid or excessive policy registry')
    for digest, policy in registry.items():
        checked_policy(policy, digest)
    initial = _initial_policy()
    initial_digest = hashlib.sha256(canonical(initial)).hexdigest()
    require(initial_digest in registry and registry[initial_digest] == initial,
            'initial zero policy changed or omitted')
    installed = {report_id: initial_digest for report_id in report_ids}
    histories = {report_id: [] for report_id in report_ids}
    exposures = {report_id: 0 for report_id in report_ids}
    last_candidates = {report_id: initial_digest for report_id in report_ids}
    history_limit = config['matched_history'] if protocol == 'matched' else config['budget_history']
    require(1 <= history_limit <= 256, 'retained history exceeds bounded contract')
    ordinary, audits, promotions = raw.get('ordinary'), raw.get('audits'), raw.get('promotions')
    evaluations = raw.get('evaluations')
    require(all(type(rows) is list for rows in (ordinary, audits, promotions)), 'missing raw episode/audit/promotion lists')
    require(type(evaluations) is dict and set(evaluations) == {'after_warm', 'after_novel', 'final'}
            and all(type(rows) is list for rows in evaluations.values()), 'invalid feedback-free panels')
    require(len(ordinary) <= config['ordinary_guard'] or protocol == 'matched', 'ordinary engineering guard exceeded')
    if audited:
        gate = replay_gate(raw.get('gate_snapshot'))
        require(raw['gate_snapshot']['config'] == {name: config[name] for name in ('alpha_total', 'max_pairs', 'max_audits')},
                'gate configuration differs from run')
        require(len(gate['audits']) == len(audits), 'raw audits differ from permanent gate starts')
    else:
        require(raw.get('gate_snapshot') is None and not audits, 'ungated control contains hidden gate/audits')
        gate = {'audits': [], 'prefixes': {}, 'sample_ids': set(), 'checked_events': 0}
    counted = {category: {name: 0 for name in COST_FIELDS}
               for category in ('ordinary', 'audit', 'snapshot', 'final')}
    used = {category: set() for category in counted}
    checked = Counter()
    work = 0
    reserve = 8 * config['final_contexts'] * 3
    require(reserve <= config['total_select_budget'], 'final panel reserve exceeds query budget')
    work_cap = config['total_select_budget'] - reserve
    audit_cursor = promotion_cursor = 0
    criterion_row_features = 0
    seen_pair_ids = set()
    panel_done = set()

    def execute(record, report_id, digest_list, expected_seed, category, *, visible=False):
        nonlocal work
        require(record.get('error') is None, 'recorded context execution failed')
        require(record.get('context_seed') == expected_seed, 'context seed differs from declared namespace')
        require(record.get('policy_digests') == digest_list, 'executed policies differ from frozen identities')
        require(all(d in registry for d in digest_list), 'executed policy missing from registry')
        if category == 'snapshot':
            require(all(expected_seed not in used[c] for c in ('ordinary', 'audit', 'final')),
                    'retention panel overlaps learning/audit/final data')
        else:
            require(all(expected_seed not in seeds for seeds in used.values()),
                    'context reused across fresh execution namespaces')
        used[category].add(expected_seed)
        rows = (verify_observation(record.get('observation'), expected_seed) if visible
                else reconstructed_context(expected_seed)[2])
        target = replay_gold(expected_seed, recipes[report_id])
        close(record.get('target'), target, 'recorded gold target differs from independent SQL', tolerance=0)
        predictions = record.get('predictions')
        rewards = record.get('rewards')
        require(type(predictions) is list and type(rewards) is list
                and len(predictions) == len(digest_list) == len(rewards), 'prediction/reward arity differs')
        for i, digest in enumerate(digest_list):
            prediction = replay_prediction(registry[digest], rows, expected_digest=digest)
            close(predictions[i], prediction, 'serialized policy prediction mismatch')
            require(type(rewards[i]) is int and rewards[i] == replay_reward(prediction, target),
                    'saved reward differs from independently executed answer')
        if len(digest_list) == 1:
            close(record.get('prediction'), predictions[0], 'scalar prediction alias differs')
            require(type(record.get('reward')) is int and record['reward'] == rewards[0],
                    'scalar reward alias differs')
        cost = record.get('costs')
        require(type(cost) is dict and set(cost) == set(COST_FIELDS), 'execution cost fields changed')
        expected_counts = {'contexts': 1, 'measurement_selects': 2*len(digest_list),
                           'gold_selects': 1, 'select_executions': 2*len(digest_list)+1,
                           'row_feature_evaluations': len(rows)*sum(len(registry[d]['features']) for d in digest_list)}
        for name, expected in expected_counts.items():
            require(type(cost[name]) is int and cost[name] == expected, 'actual query/prediction counter mismatch: ' + name)
        for name in COST_FIELDS:
            require(_finite(cost[name], 'invalid execution cost') >= 0, 'negative execution cost')
            counted[category][name] += cost[name]
        if category in ('ordinary', 'audit'):
            work += cost['select_executions']
            if protocol == 'budget':
                require(work <= work_cap, 'query budget breached at an ordinary/audit prefix')
                checked['budget_prefixes'] += 1
        checked[category + '_contexts'] += 1
        checked['policy_predictions'] += len(digest_list)
        checked['select_executions'] += cost['select_executions']
        return rows, target

    def install(episode, report_id, candidate, admission, audit_index):
        nonlocal promotion_cursor
        require(promotion_cursor < len(promotions), 'authorized installation missing from promotion log')
        event = promotions[promotion_cursor]
        promotion_cursor += 1
        for name, expected in (('episode', episode), ('report_id', report_id),
                               ('prior_digest', installed[report_id]), ('candidate_digest', candidate),
                               ('admission', admission), ('audit_index', audit_index)):
            require(event.get(name) == expected, 'promotion identity/authorization mismatch: ' + name)
        others = {report: digest for report, digest in installed.items() if report != report_id}
        require(event.get('other_policy_digests') == others, 'promotion changed another public report identity')
        installed[report_id] = candidate
        checked['promotions'] += 1
        checked['other_report_invariants'] += 1

    def panel(label, count, active_reports, namespace):
        panel_done.add(label)
        records = evaluations[label]
        require(len(records) == len(active_reports)*count, 'evaluation panel length differs from protocol')
        cursor = 0
        for report in active_reports:
            report_id = report['public_id']
            for index in range(count):
                record = records[cursor]
                cursor += 1
                for name, expected in (('report_id', report_id), ('report_index', report['index']),
                                       ('report_kind', report['kind']), ('panel', label),
                                       ('context_index', index), ('installed_digest', installed[report_id]),
                                       ('ordinary_exposures', exposures[report_id])):
                    require(record.get(name) == expected, 'feedback-free panel identity differs: ' + name)
                execute(record, report_id, [installed[report_id]],
                        reference_seed(seed, report_id, index, namespace),
                        'final' if label == 'final' else 'snapshot')

    for cursor, record in enumerate(ordinary):
        require(type(record) is dict and record.get('status') == 'complete'
                and record.get('feedback_recorded') is True, 'ordinary prediction/feedback is incomplete')
        index, phase = _stream_position(cursor, config)
        report = reports[index]
        report_id = report['public_id']
        for name, expected in (('episode', cursor), ('report_id', report_id), ('report_index', index),
                               ('report_kind', report['kind']), ('phase', phase),
                               ('report_exposure', exposures[report_id]+1), ('installed_digest', installed[report_id])):
            require(record.get(name) == expected, 'ordinary stream skips/reorders input or policy: ' + name)
        if protocol == 'budget':
            require(work_cap-work >= 3, 'ordinary episode started without three reserved queries')
        rows, target = execute(record, report_id, [installed[report_id]],
                               reference_seed(seed, cursor, 'ordinary'), 'ordinary', visible=True)
        exposures[report_id] += 1
        histories[report_id].append((rows, target))
        if len(histories[report_id]) > history_limit:
            histories[report_id].pop(0)
        require(type(record.get('learner_updates')) is int and record['learner_updates'] == cursor+1,
                'history update counter includes nonordinary evidence or skips own feedback')
        candidate = record.get('candidate_digest')
        require(candidate in registry, 'post-feedback candidate missing from registry')
        last_candidates[report_id] = candidate
        incumbent = installed[report_id]
        if not audited:
            require('criterion' not in record and 'audit' not in record, 'ungated arm performed undisclosed gate selection')
            install(cursor, report_id, candidate, 'ordinary_ungated', None)
        else:
            due = (exposures[report_id] >= config['candidate_minimum']
                   and exposures[report_id] % config['candidate_every'] == 0)
            require(('criterion' in record) == due, 'candidate schedule differs from protocol')
            if due:
                history = histories[report_id]
                candidate_correct = sum(replay_reward(replay_prediction(registry[candidate], values), y)
                                        for values, y in history)
                incumbent_correct = sum(replay_reward(replay_prediction(registry[incumbent], values), y)
                                        for values, y in history)
                eligible = (candidate_correct >= config['training_accuracy_minimum']*len(history)
                            and candidate_correct >= incumbent_correct+1)
                row_work = sum(len(values) for values, _ in history)*(len(registry[candidate]['features'])
                                                                    + len(registry[incumbent]['features']))
                criterion_row_features += row_work
                criterion = record['criterion']
                for name, expected in (('history_count', len(history)), ('candidate_correct', candidate_correct),
                                       ('incumbent_correct', incumbent_correct), ('eligible', eligible),
                                       ('row_feature_evaluations', row_work)):
                    require(criterion.get(name) == expected, 'own-history criterion replay differs: ' + name)
                require(_finite(criterion.get('wall_seconds'), 'invalid criterion time') >= 0, 'negative criterion time')
                if eligible and audit_cursor < config['max_audits']:
                    require(audit_cursor < len(audits), 'eligible charged audit missing')
                    audit = audits[audit_cursor]
                    replay = gate['audits'][audit_cursor]
                    audit_cursor += 1
                    for name, expected in (('episode', cursor), ('report_id', report_id),
                                           ('candidate_digest', candidate), ('incumbent_digest', incumbent)):
                        require(audit.get(name) == expected, 'audit frozen identities differ: ' + name)
                    require(audit.get('criterion') == criterion, 'audit criterion changed after selection')
                    token = audit.get('token')
                    require(type(token) is dict and token == {
                        'gate_id': raw['gate_snapshot']['gate_id'], 'audit_index': audit_cursor,
                        'candidate_digest': candidate, 'incumbent_digest': incumbent, 'scope': report_id},
                        'raw token differs from permanent gate identity')
                    require(replay['candidate_digest'] == candidate and replay['incumbent_digest'] == incumbent
                            and replay['scope'] == report_id, 'journal audit identities differ from actual execution')
                    require(audit.get('learner_updates_before') == cursor+1
                            and audit.get('learner_updates_after') == cursor+1,
                            'audit data updated numerical learner')
                    pairs = audit.get('pairs')
                    require(type(pairs) is list and len(pairs) == replay['pairs'], 'audit pair count differs from journal')
                    for pair_index, pair in enumerate(pairs):
                        require(pair.get('pair_index') == pair_index, 'audit pair index reused or skipped')
                        if protocol == 'budget':
                            require(work_cap-work >= 5, 'audit pair started without five remaining queries')
                        context_seed = reference_seed(seed, method, protocol, report_id, audit_cursor, pair_index, 'audit')
                        execute(pair, report_id, [candidate, incumbent], context_seed, 'audit')
                        sample_id = 'audit-' + str(context_seed)
                        require(sample_id not in seen_pair_ids, 'raw audit sample ID reused')
                        seen_pair_ids.add(sample_id)
                        require(sample_id in gate['prefixes'], 'executed pair omitted from gate journal')
                        prefix = gate['prefixes'][sample_id]
                        require(prefix['index'] == audit_cursor and prefix['pairs'] == pair_index+1,
                                'pair journal order differs from executed pair order')
                        require(pair['rewards'] == [prefix['candidate_reward'], prefix['incumbent_reward']],
                                'gate rewards differ from actual replayed policy outcomes')
                        _check_gate_result(pair.get('gate_prefix'), prefix)
                        checked['gate_prefixes'] += 1
                    require(audit.get('status') == replay['status'], 'audit final status differs from replay')
                    _check_gate_result(audit.get('result'), replay, journal_hash=replay['last_journal_hash'])
                    require(record.get('audit') == {'status': replay['status'], 'audit_index': audit_cursor,
                                                   'pairs': replay['pairs']}, 'ordinary audit reference differs')
                    if replay['status'] == 'accepted':
                        install(cursor, report_id, candidate, 'paired_gate', audit_cursor)
                    elif replay['pairs'] < config['max_pairs']:
                        require(protocol == 'budget' and work_cap-work < 5,
                                'complete run ended an audit early outside the query stopping rule')
                elif eligible:
                    require(record.get('audit') == {'status': 'skipped_audit_cap'}, 'audit cap bypassed/reset')
                else:
                    require('audit' not in record, 'ineligible training candidate received audit data')
            else:
                require('audit' not in record, 'unscheduled candidate received audit data')
        require(record.get('incumbent_after_digest') == installed[report_id],
                'incumbent changed without a matching authorized promotion')
        if protocol == 'matched':
            warm_end = 4*config['warm_rounds']
            novel_end = warm_end+4*config['novel_rounds']
            if cursor+1 in (warm_end, novel_end):
                label = 'after_warm' if cursor+1 == warm_end else 'after_novel'
                panel(label, config['snapshot_contexts'], reports[:4], 'retention-snapshot')

    require(audit_cursor == len(audits) and promotion_cursor == len(promotions),
            'audit or promotion event exists outside ordinary chronology')
    require(seen_pair_ids == gate['sample_ids'], 'gate contains nonexecuted audit evidence')
    for label in ('after_warm', 'after_novel'):
        if label not in panel_done:
            require(not evaluations[label], 'extra panel executed outside protocol checkpoint')
    panel('final', config['final_contexts'], reports, 'final')
    limit = (4*(config['warm_rounds']+config['novel_rounds']+config['retention_rounds'])
             if protocol == 'matched' else config['ordinary_guard'])
    if raw.get('test_episode_limit') is not None:
        require(type(raw['test_episode_limit']) is int and raw['test_episode_limit'] >= 0, 'invalid test prefix limit')
        limit = min(limit, raw['test_episode_limit'])
    require(len(ordinary) <= limit, 'ordinary stream exceeded declared prefix')
    if protocol == 'matched':
        require(len(ordinary) == limit, 'matched ordinary stream truncated')
    elif len(ordinary) < limit:
        require(work_cap-work < 3, 'budget arm stopped with another ordinary episode affordable')
    require(counted['final']['select_executions'] == reserve, 'reserved final panel was not fully charged')
    if protocol == 'budget':
        require(counted['snapshot']['select_executions'] == 0, 'query-budget arm used uncharged intermediate panels')
        require(work+reserve <= config['total_select_budget'], 'query companion exceeds total 4096-style ceiling')
    require(raw.get('incumbents') == installed, 'final installed policy table differs from promotion replay')
    learner = raw.get('learner')
    require(type(learner) is dict and learner.get('max_history') == history_limit, 'learner history bound differs')
    metrics = learner.get('metrics')
    require(type(metrics) is dict and metrics.get('updates') == len(ordinary),
            'numerical updates include audit/evaluation feedback')
    expected_evictions = sum(max(0, count-history_limit) for count in exposures.values())
    require(metrics.get('history_evictions') == expected_evictions, 'history eviction counter differs from own evidence')
    learner_reports = learner.get('reports')
    require(type(learner_reports) is dict and set(learner_reports) == set(report_ids), 'learner report registry differs')
    for report_id in report_ids:
        state = learner_reports[report_id]
        require(state.get('updates') == exposures[report_id]
                and state.get('history') == min(exposures[report_id], history_limit),
                'per-report history contains nonordinary evidence')
        if exposures[report_id]:
            require(state.get('policy_digest') == last_candidates[report_id], 'learner proposal changed after final feedback')
    require(0 <= metrics.get('fits', -1) <= 3*len(ordinary), 'fit work counter exceeds algorithm bound')
    require(0 <= metrics.get('feature_evaluations', -1) <= 84*len(ordinary), 'feature cache extraction counter exceeds bound')
    costs = raw.get('costs')
    require(type(costs) is dict and set(costs.get('by_category', {})) == set(counted), 'cost categories differ')
    for category, totals in counted.items():
        for name, value in totals.items():
            if name in COUNT_FIELDS:
                require(costs['by_category'][category].get(name) == value, 'category cost counter differs: '+category+'/'+name)
            else:
                close(costs['by_category'][category].get(name), value, 'category timing aggregation differs')
    for name in COST_FIELDS:
        expected = sum(counted[c][name] for c in counted)
        if name in COUNT_FIELDS:
            require(costs.get('total', {}).get(name) == expected, 'total execution counter differs: '+name)
        else:
            close(costs.get('total', {}).get(name), expected, 'total timing aggregation differs')
    summary = raw.get('summary')
    require(type(summary) is dict, 'raw summary absent')
    for name, expected in (('seed', seed), ('method', method), ('protocol', protocol), ('status', 'complete'),
                           ('ordinary_episodes', len(ordinary)), ('ordinary_attempts', len(ordinary)),
                           ('ordinary_scored_predictions', len(ordinary)),
                           ('audit_pairs', len(seen_pair_ids)), ('started_audits', len(audits)),
                           ('accepted_audits', sum(a['status'] == 'accepted' for a in audits)),
                           ('promotions', len(promotions)), ('work_select_executions', work),
                           ('total_select_executions', checked['select_executions']),
                           ('per_report_exposures', exposures), ('history_evictions', expected_evictions),
                           ('installed_other_policy_checks', len(promotions)),
                           ('training_criterion_row_feature_evaluations', criterion_row_features),
                           ('unreached_reports', [r for r in report_ids if not exposures[r]])):
        require(summary.get(name) == expected, 'summary count/identity mismatch: '+name)
    shared = [r for r in ordinary if r['report_kind'] == 'shared_novel' and r['report_exposure'] <= 24]
    final_by_report = {r: _mean(row['reward'] for row in evaluations['final'] if row['report_id'] == r)
                       for r in report_ids}
    for name, expected in (
        ('shared_novel_first24_reward', _mean(r['reward'] for r in shared)),
        ('shared_novel_first8_reward', _mean(r['reward'] for r in shared if r['report_exposure'] <= 8)),
        ('unshared_novel_reward', _mean(r['reward'] for r in ordinary if r['report_kind'] == 'unshared_novel')),
        ('warm_reward', _mean(r['reward'] for r in ordinary if r['phase'] == 'warm')),
        ('retention_reward', _mean(r['reward'] for r in ordinary if r['phase'] == 'retention')),
        ('ordinary_reward', _mean(r['reward'] for r in ordinary)),
        ('final_macro_reward', _mean(v for v in final_by_report.values() if v is not None)),
        ('after_warm_old_reward', _mean(r['reward'] for r in evaluations['after_warm'])),
        ('after_novel_old_reward', _mean(r['reward'] for r in evaluations['after_novel'])),
    ):
        _same_mean(summary.get(name), expected, 'summary '+name)
    require(set(summary.get('per_report_final_reward', {})) == set(final_by_report), 'per-report panel summary keys differ')
    for report_id, expected in final_by_report.items():
        _same_mean(summary['per_report_final_reward'][report_id], expected, 'per-report final reward')
    checked['streams'] = 1
    checked['policy_versions'] = len(registry)
    checked['gate_events'] = gate['checked_events']
    checked['started_audits'] = len(audits)
    return {'checked': dict(checked), 'summary': summary, 'context_namespaces': used,
            'audit_sample_ids': seen_pair_ids, 'stream': (protocol, seed, method)}


def _verify_sources(manifest, repository, freeze_path=None):
    repository = Path(repository).resolve()
    hashes = manifest.get('source_sha256')
    required = {'src/witness_cl/relational_v7.py', 'src/witness_cl/statistical_gate_v7.py',
                'experiments/relational_v7.py', 'tests/test_experiment_v7.py',
                'docs/v7/EVALUATION.md', 'docs/v7/GATE.md', 'docs/v7/FORMAL.md'}
    require(type(hashes) is dict and required.issubset(hashes), 'manifest omits required source freeze inputs')
    for name, digest in hashes.items():
        require(type(name) is str and not Path(name).is_absolute(), 'invalid frozen source path')
        path = (repository / name).resolve()
        require(path.is_relative_to(repository) and path.is_file(), 'frozen source escapes repository or is missing')
        require(type(digest) is str and len(digest) == 64 and sha256_file(path) == digest,
                'source differs from execution freeze: ' + name)
    frozen_hash = manifest.get('freeze_sha256')
    if frozen_hash is not None:
        require(freeze_path is not None, 'a recorded source freeze requires its file for verification')
        path = Path(freeze_path)
        require(path.is_file() and sha256_file(path) == frozen_hash, 'freeze file digest mismatch')
        frozen = json.loads(path.read_text())
        for name in ('seeds', 'methods', 'protocols', 'config', 'source_sha256'):
            require(frozen.get(name) == manifest.get(name), 'manifest differs from frozen ' + name)
    if any(seed in range(81000, 81016) for seed in manifest['seeds']):
        require(frozen_hash is not None, 'untouched evaluation omitted a source/config freeze')
        require(manifest['seeds'] == list(range(81000, 81016)) and tuple(manifest['methods']) == METHODS
                and manifest['protocols'] == ['matched', 'budget'], 'holdout stream/arm selection differs from freeze')
        require(manifest['config'].get('total_select_budget') == 4096
                and manifest['config'].get('final_contexts') == 32, 'holdout query-budget protocol changed')
    return len(hashes)


def audit_directory(directory, *, freeze_path=None, repository=None):
    directory = Path(directory).resolve()
    repository = Path(repository or Path(__file__).resolve().parents[1]).resolve()
    manifest_path, aggregate_path = directory/'manifest.json', directory/'aggregates.json'
    require(manifest_path.is_file() and aggregate_path.is_file(), 'run manifest or aggregates are missing')
    manifest, aggregate = json.loads(manifest_path.read_text()), json.loads(aggregate_path.read_text())
    require(manifest.get('format_version') == 1 and manifest.get('status') == 'complete',
            'run manifest is not complete')
    for name, allowed in (('methods', METHODS), ('protocols', ('matched', 'budget'))):
        values = manifest.get(name)
        require(type(values) is list and values and len(set(values)) == len(values)
                and all(v in allowed for v in values), 'manifest has invalid '+name)
    seeds = manifest.get('seeds')
    require(type(seeds) is list and seeds and all(type(s) is int for s in seeds)
            and len(set(seeds)) == len(seeds), 'manifest seed list is invalid')
    if manifest.get('freeze_sha256') is not None and freeze_path is None:
        candidate = directory.parent/'freeze.json'
        if candidate.is_file():
            freeze_path = candidate
    source_count = _verify_sources(manifest, repository, freeze_path)
    require(all(manifest.get('blas_thread_environment', {}).get(name) == '1'
                for name in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS')),
            'execution did not record the required one-thread BLAS configuration')
    expected_files = {f'{protocol}-{seed}-{method}.json': (protocol, seed, method)
                      for protocol in manifest['protocols'] for seed in seeds for method in manifest['methods']}
    recorded_runs = aggregate.get('runs')
    require(type(recorded_runs) is list and len(recorded_runs) == len(expected_files),
            'aggregate run count differs from manifest')
    require(all(type(row) is dict and row.get('raw_file') in expected_files for row in recorded_runs),
            'aggregate references an unexpected raw stream')
    require(len({row['raw_file'] for row in recorded_runs}) == len(expected_files),
            'aggregate repeats or omits raw stream')
    aggregate_rows = {row['raw_file']: row for row in recorded_runs}
    actual_raw = {path.name for protocol in ('matched', 'budget') for path in directory.glob(protocol+'-*.json')}
    require(actual_raw == set(expected_files), 'raw stream files differ from manifest Cartesian product')
    counts = Counter()
    counts['source_files'] = source_count
    failures, summaries, raw_hashes = [], [], {}
    global_context_category, global_audit_ids = {}, set()
    for filename, identity in expected_files.items():
        try:
            path = directory/filename
            require(path.stat().st_size <= 512*1024*1024, 'raw stream exceeds replay memory limit')
            raw = json.loads(path.read_text())
            require(raw.get('test_episode_limit') is None, 'production directory contains a test-truncated run')
            result = audit_stream(raw, expected_config=manifest['config'])
            require(result['stream'] == identity, 'raw filename and stream identity differ')
            require(aggregate_rows[filename] == dict(result['summary'], raw_file=filename),
                    'aggregate seed-level row differs from independently verified raw summary')
            for category, contexts in result['context_namespaces'].items():
                for context in contexts:
                    previous = global_context_category.get(context)
                    require(previous is None or (previous == category and category != 'audit'),
                            'audit sample reused or context namespaces overlap across runs')
                    global_context_category[context] = category
            require(not global_audit_ids.intersection(result['audit_sample_ids']),
                    'audit sample ID reused across independent gate runs')
            global_audit_ids.update(result['audit_sample_ids'])
            counts.update(result['checked'])
            summaries.append(result['summary'])
            raw_hashes[filename] = sha256_file(path)
        except (ReplayFailure, KeyError, TypeError, ValueError, IndexError, OSError) as exc:
            failures.append({'file': filename, 'error': str(exc)})
    if not failures:
        groups = aggregate.get('groups')
        require(type(groups) is list and len(groups) == len(manifest['protocols'])*len(manifest['methods']),
                'aggregate group count differs from manifest')
        seen_groups = set()
        for group in groups:
            identity = group.get('protocol'), group.get('method')
            require(identity not in seen_groups and identity[0] in manifest['protocols']
                    and identity[1] in manifest['methods'], 'duplicate or unknown aggregate group')
            seen_groups.add(identity)
            rows = [row for row in summaries if (row['protocol'], row['method']) == identity]
            require(group.get('runs') == len(rows) and group.get('failed_runs') == 0,
                    'aggregate group hides a failed or missing run')
            for field in ('shared_novel_first24_reward', 'shared_novel_first8_reward',
                          'unshared_novel_reward', 'warm_reward', 'retention_reward',
                          'ordinary_reward', 'final_macro_reward', 'total_select_executions',
                          'total_wall_seconds', 'audit_pairs', 'ordinary_episodes'):
                _same_mean(group.get('means', {}).get(field), _mean(r[field] for r in rows if r[field] is not None),
                           'aggregate group mean '+field)
    return {'status': 'passed' if not failures else 'failed',
            'scope': 'independent saved-data replay; no learner, gate, or runner imported',
            'directory': str(directory), 'checked': dict(counts), 'failures': failures,
            'unique_audit_sample_ids': len(global_audit_ids),
            'manifest_sha256': sha256_file(manifest_path), 'aggregates_sha256': sha256_file(aggregate_path),
            'raw_files_sha256': hashlib.sha256(canonical(raw_hashes)).hexdigest(),
            'raw_sha256': raw_hashes,
            'source_sha256': sha256_file(__file__),
            'replay_source_sha256': sha256_file(__file__),
            'checked_freeze_sha256': manifest.get('freeze_sha256'),
            'checked_source_sha256': dict(manifest['source_sha256']),
            'checked_source_map_sha256': hashlib.sha256(canonical(manifest['source_sha256'])).hexdigest(),
            'checked_config_sha256': hashlib.sha256(canonical(manifest['config'])).hexdigest(),
            'limits': 'Verifies saved consistency, outcomes, and accounting; does not authenticate original execution or independently measure reported runtime.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+', type=Path)
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    results = []
    for directory in args.directories:
        try:
            result = audit_directory(directory, freeze_path=args.freeze)
        except (ReplayFailure, KeyError, TypeError, ValueError, IndexError, OSError) as exc:
            result = {'status': 'failed', 'directory': str(directory), 'checked': {},
                      'failures': [{'error': str(exc)}], 'raw_sha256': {},
                      'source_sha256': sha256_file(__file__), 'replay_source_sha256': sha256_file(__file__)}
        results.append(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, allow_nan=False)+'\n')
    print(json.dumps([{'directory': r['directory'], 'status': r['status'], 'checked': r['checked'],
                      'failures': r['failures']} for r in results], indent=2))
    return int(any(r['status'] != 'passed' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
