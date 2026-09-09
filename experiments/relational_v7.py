"""Preregistered local SQLite feature-transfer experiment and query-budget control.

Only ordinary feedback trains the numerical learner. Frozen policy audits and
feedback-free evaluation use disjoint context namespaces. Nothing is deployed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from itertools import combinations_with_replacement
import json
import os
from pathlib import Path
import platform
import random
import statistics
import time
import traceback

from witness_cl.relational_v7 import (
    FrozenPolicy, INITIAL_FEATURES, Learner, make_context,
)
from witness_cl.statistical_gate_v7 import PairedBettingGate

ROOT = Path(__file__).resolve().parents[1]
METHODS = (
    'audited_grow_reuse', 'audited_grow_no_reuse', 'audited_full_history_sparse',
    'ungated_full_history_sparse', 'ungated_full_ridge', 'audited_grow_full84',
)
HOLDOUT_SEEDS = tuple(range(81000, 81016))
COST_CATEGORIES = ('ordinary', 'audit', 'snapshot', 'final')


@dataclass(frozen=True)
class Config:
    warm_rounds: int = 24
    novel_rounds: int = 24
    retention_rounds: int = 8
    snapshot_contexts: int = 16
    final_contexts: int = 32
    total_select_budget: int = 4096
    ordinary_guard: int = 2048
    matched_history: int = 64
    budget_history: int = 256
    candidate_every: int = 4
    candidate_minimum: int = 4
    training_accuracy_minimum: float = .75
    alpha_total: float = .05
    max_pairs: int = 64
    max_audits: int = 1024
    reward_tolerance: float = 1e-6

    def __post_init__(self):
        nonnegative = ('warm_rounds', 'novel_rounds', 'retention_rounds',
                       'snapshot_contexts', 'final_contexts')
        positive = ('total_select_budget', 'ordinary_guard', 'matched_history',
                    'budget_history', 'candidate_every', 'candidate_minimum',
                    'max_pairs', 'max_audits')
        for name in nonnegative + positive:
            value = getattr(self, name)
            if type(value) is not int or value < (0 if name in nonnegative else 1):
                raise ValueError('invalid nonnegative/positive integer config: ' + name)
        if not 0 <= self.training_accuracy_minimum <= 1 or self.reward_tolerance <= 0:
            raise ValueError('invalid accuracy/tolerance configuration')
        if self.total_select_budget < self.final_reserve:
            raise ValueError('total SELECT budget cannot cover reserved final panel')

    @property
    def matched_episodes(self):
        return 4 * (self.warm_rounds + self.novel_rounds + self.retention_rounds)

    @property
    def final_reserve(self):
        return 8 * self.final_contexts * 3


def default_config():
    return asdict(Config())


def seed_for(*parts):
    encoded = json.dumps(parts, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    return int.from_bytes(hashlib.sha256(encoded).digest(), 'big')


def _mono(indices):
    return tuple(indices.count(i) for i in range(6))


def reports_for(run_seed):
    """Evaluator-owned rules; callers pass only the opaque ID to Learner."""
    rng = random.Random(run_seed)
    cross = tuple(_mono((i, j)) for i in range(4) for j in (4, 5))
    warm = rng.sample(cross, 4)
    cubics = tuple(_mono((i, j, k)) for i, j in combinations_with_replacement(range(4), 2)
                   for k in (4, 5))
    unshared = rng.sample(cubics, 2)
    specs = [((m, 1),) for m in warm]
    specs += [((warm[0], 1), (warm[1], 1)), ((warm[2], 1), (warm[3], 1))]
    specs += [((m, 1),) for m in unshared]
    return tuple(dict(index=i, public_id='report_' + format(seed_for(run_seed, i), '064x')[:24],
                      kind='warm' if i < 4 else ('shared_novel' if i < 6 else 'unshared_novel'),
                      spec=spec) for i, spec in enumerate(specs))


def stream_at(cursor, config):
    warm_end = 4 * config.warm_rounds
    novel_end = warm_end + 4 * config.novel_rounds
    if cursor < warm_end:
        return cursor % 4, 'warm'
    if cursor < novel_end:
        return 4 + (cursor - warm_end) % 4, 'novel'
    if cursor < config.matched_episodes:
        return (cursor - novel_end) % 4, 'retention'
    return (cursor - config.matched_episodes) % 8, 'revisit'


def correct(prediction, target, tolerance=1e-6):
    return int(abs(prediction - target) <= tolerance * (1 + abs(target)))


def _empty_cost():
    return dict(contexts=0, measurement_selects=0, gold_selects=0, select_executions=0,
                measurement_seconds=0.0, gold_seconds=0.0, setup_seconds=0.0,
                wall_seconds=0.0, cpu_seconds=0.0, prediction_seconds=0.0,
                row_feature_evaluations=0)


def _plus(left, right):
    for key, value in right.items():
        left[key] += value


class Harness:
    """An evaluator/driver around a learner, never supplied to the learner."""
    def __init__(self, run_seed, method, protocol, config=None):
        if method not in METHODS or protocol not in ('matched', 'budget'):
            raise ValueError('unknown method/protocol')
        if type(run_seed) is not int:
            raise ValueError('integer run seed required')
        self.seed, self.method, self.protocol = run_seed, method, protocol
        self.config = config or Config()
        self.reports = reports_for(run_seed)
        self.audited = method.startswith('audited_')
        mode = method.removeprefix('audited_').removeprefix('ungated_')
        if mode == 'grow_full84':
            mode = 'grow_reuse'
        history = self.config.matched_history if protocol == 'matched' else self.config.budget_history
        self.learner = Learner(mode, max_history=history,
                               search_candidates=84 if method.endswith('full84') else 16)
        self.gate = PairedBettingGate(self.config.alpha_total, max_pairs=self.config.max_pairs,
                                      max_audits=self.config.max_audits) if self.audited else None
        initial = FrozenPolicy(INITIAL_FEATURES, (0.0,) * len(INITIAL_FEATURES))
        self.incumbents = {r['public_id']: initial for r in self.reports}
        self.registry = {initial.digest: initial.to_dict()}
        self.ordinary, self.audits, self.promotions = [], [], []
        self.evaluations = dict(after_warm=[], after_novel=[], final=[])
        self.costs = {category: _empty_cost() for category in COST_CATEGORIES}
        self.exposures = {r['public_id']: 0 for r in self.reports}
        self.histories = {r['public_id']: [] for r in self.reports}
        self.context_seeds = {category: set() for category in COST_CATEGORIES}
        self.criterion_seconds = 0.0
        self.criterion_row_features = 0
        self.installed_invariant_checks = 0
        self.status, self.error = 'running', None
        self.stage = 'construction'
        self.started_wall, self.started_cpu = time.perf_counter(), time.process_time()

    @property
    def work_selects(self):
        return self.costs['ordinary']['select_executions'] + self.costs['audit']['select_executions']

    @property
    def work_remaining(self):
        if self.protocol != 'budget':
            return None
        return self.config.total_select_budget - self.config.final_reserve - self.work_selects

    def _register(self, policy):
        existing = self.registry.setdefault(policy.digest, policy.to_dict())
        if existing != policy.to_dict():
            raise AssertionError('policy digest collision or changed frozen policy')

    def _execute(self, report, context_seed, policies, category):
        """Run actual queries and preserve attempted cost on every return path."""
        if category == 'audit':
            if any(context_seed in seeds for seeds in self.context_seeds.values()):
                raise AssertionError('audit context reused another stream or previous audit')
        elif category != 'snapshot':
            if any(context_seed in seeds for seeds in self.context_seeds.values()):
                raise AssertionError('ordinary/final context namespace collision')
        else:
            if any(context_seed in self.context_seeds[name] for name in ('ordinary', 'audit', 'final')):
                raise AssertionError('retention context reused a learning/audit/final context')
        self.context_seeds[category].add(context_seed)
        record = dict(context_seed=context_seed, predictions=[], rewards=[], target=None,
                      policy_digests=[p.digest for p in policies], error=None)
        observations, ctx = [], None
        cost = _empty_cost()
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            ctx = make_context(context_seed)
            cost['contexts'] = 1
            for policy in policies:
                observation = ctx.observe()
                if observations and observation.rows != observations[0].rows:
                    raise AssertionError('paired read-only measurements differ')
                observations.append(observation)
                started = time.perf_counter()
                try:
                    prediction = policy.predict(observation)
                finally:
                    cost['prediction_seconds'] += time.perf_counter() - started
                    cost['row_feature_evaluations'] += len(policy.features) * len(observation.rows)
                record['predictions'].append(prediction)
            record['target'] = ctx.answer(report['spec'])
            record['rewards'] = [correct(p, record['target'], self.config.reward_tolerance)
                                 for p in record['predictions']]
        except Exception as exc:
            record['error'] = dict(type=type(exc).__name__, message=str(exc))
        finally:
            if ctx is not None:
                cost.update(measurement_selects=ctx.query_count, gold_selects=ctx.answer_query_count,
                            select_executions=ctx.query_count + ctx.answer_query_count,
                            measurement_seconds=ctx.query_seconds, gold_seconds=ctx.answer_query_seconds,
                            setup_seconds=ctx.setup_seconds)
                ctx.close()
            cost['wall_seconds'], cost['cpu_seconds'] = time.perf_counter() - wall, time.process_time() - cpu
            _plus(self.costs[category], cost)
            record['costs'] = cost
        if record['error'] is None and cost['select_executions'] != 2 * len(policies) + 1:
            record['error'] = dict(type='AccountingError', message='actual SELECT count differs from protocol')
        if self.work_remaining is not None and self.work_remaining < 0:
            record['error'] = dict(type='BudgetError', message='work SELECT budget exceeded')
        return record, (observations[0] if observations else None)

    @staticmethod
    def _require_success(record):
        if record['error'] is not None:
            raise RuntimeError('context execution failed: ' + json.dumps(record['error']))

    def _install(self, report_id, candidate, *, episode, admission, audit_index=None):
        others = {key: policy.digest for key, policy in self.incumbents.items() if key != report_id}
        previous = self.incumbents[report_id].digest
        self.learner.on_promotion(report_id, candidate)
        self.incumbents[report_id] = candidate
        after = {key: policy.digest for key, policy in self.incumbents.items() if key != report_id}
        if after != others:
            raise AssertionError('installation mutated another report policy')
        self.installed_invariant_checks += 1
        self.promotions.append(dict(episode=episode, report_id=report_id, prior_digest=previous,
                                    candidate_digest=candidate.digest, admission=admission,
                                    audit_index=audit_index, other_policy_digests=after))

    def _criterion(self, report_id, candidate, incumbent):
        started = time.perf_counter()
        row_features = candidate_correct = incumbent_correct = 0
        history = self.histories[report_id]
        try:
            for observation, target in history:
                candidate_correct += correct(candidate.predict(observation), target,
                                             self.config.reward_tolerance)
                incumbent_correct += correct(incumbent.predict(observation), target,
                                             self.config.reward_tolerance)
                row_features += (len(candidate.features) + len(incumbent.features)) * len(observation.rows)
            count = len(history)
            eligible = (candidate_correct >= self.config.training_accuracy_minimum * count
                        and candidate_correct >= incumbent_correct + 1)
            return dict(history_count=count, candidate_correct=candidate_correct,
                        incumbent_correct=incumbent_correct, eligible=eligible,
                        row_feature_evaluations=row_features,
                        wall_seconds=time.perf_counter() - started)
        finally:
            self.criterion_seconds += time.perf_counter() - started
            self.criterion_row_features += row_features

    def _audit(self, report, candidate, incumbent, episode, criterion):
        report_id = report['public_id']
        if self.gate.started_audits >= self.config.max_audits:
            return dict(status='skipped_audit_cap')
        candidate_digest, incumbent_digest = candidate.digest, incumbent.digest
        self._register(candidate)
        self._register(incumbent)
        token = self.gate.start(candidate_digest, incumbent_digest, report_id)
        updates_before = self.learner.metrics['updates']
        history_counts_before = {key: len(value) for key, value in self.histories.items()}
        audit = dict(episode=episode, report_id=report_id, candidate_digest=candidate_digest,
                     incumbent_digest=incumbent_digest, criterion=criterion,
                     token=asdict(token), pairs=[], learner_updates_before=updates_before,
                     status='collecting')
        self.audits.append(audit)
        try:
            for pair_index in range(self.config.max_pairs):
                if self.work_remaining is not None and self.work_remaining < 5:
                    self.gate.finish_inconclusive(token)
                    audit['stop_reason'] = 'remaining_select_budget_below_five'
                    break
                if candidate.digest != token.candidate_digest or incumbent.digest != token.incumbent_digest:
                    raise AssertionError('audit policy changed after freezing')
                context_seed = seed_for(self.seed, self.method, self.protocol, report_id, token.audit_index,
                                        pair_index, 'audit')
                pair, _ = self._execute(report, context_seed, (candidate, incumbent), 'audit')
                pair['pair_index'] = pair_index
                audit['pairs'].append(pair)
                self._require_success(pair)
                result = self.gate.observe_pair(
                    token, pair['rewards'][0], pair['rewards'][1], 'audit-' + str(context_seed),
                    candidate_digest=candidate.digest, incumbent_digest=incumbent.digest, scope=report_id)
                pair['gate_prefix'] = asdict(result)
                if result.status != 'collecting':
                    break
        finally:
            if self.gate.active_token is token:
                self.gate.finish_inconclusive(token)
                audit.setdefault('stop_reason', 'execution_exit_or_pair_cap')
            result = self.gate.result(token)
            audit['result'], audit['status'] = asdict(result), result.status
            audit['learner_updates_after'] = self.learner.metrics['updates']
            if updates_before != self.learner.metrics['updates'] or history_counts_before != {
                    key: len(value) for key, value in self.histories.items()}:
                raise AssertionError('audit feedback entered numerical training/history')
        if result.status == 'accepted':
            if self.incumbents[report_id].digest != incumbent_digest:
                raise AssertionError('incumbent changed during audit')
            self._install(report_id, candidate, episode=episode, admission='paired_gate',
                          audit_index=token.audit_index)
        return dict(status=result.status, audit_index=token.audit_index, pairs=result.pairs)

    def ordinary_episode(self, cursor):
        if self.work_remaining is not None and self.work_remaining < 3:
            return False
        report_index, phase = stream_at(cursor, self.config)
        report = self.reports[report_index]
        report_id = report['public_id']
        installed = self.incumbents[report_id]
        record = dict(episode=cursor, report_id=report_id, report_index=report_index,
                      report_kind=report['kind'], phase=phase,
                      report_exposure=self.exposures[report_id] + 1,
                      installed_digest=installed.digest, status='started', feedback_recorded=False)
        self.ordinary.append(record)
        self.stage = 'ordinary_execution'
        execution, observation = self._execute(
            report, seed_for(self.seed, cursor, 'ordinary'), (installed,), 'ordinary')
        record.update(execution)
        self._require_success(record)
        record['prediction'], record['reward'] = record['predictions'][0], record['rewards'][0]
        record['observation'] = observation.to_dict()
        self.stage = 'ordinary_training'
        self.learner.observe(report_id, observation, record['target'])
        record['feedback_recorded'] = True
        self.histories[report_id].append((observation, record['target']))
        if len(self.histories[report_id]) > self.learner.max_history:
            self.histories[report_id].pop(0)
        self.exposures[report_id] += 1
        record['learner_updates'] = self.learner.metrics['updates']
        candidate = self.learner.propose(report_id)
        self._register(candidate)
        record['candidate_digest'] = candidate.digest
        if not self.audited:
            self._install(report_id, candidate, episode=cursor, admission='ordinary_ungated')
        elif (self.exposures[report_id] >= self.config.candidate_minimum
              and self.exposures[report_id] % self.config.candidate_every == 0):
            self.stage = 'training_criterion'
            criterion = self._criterion(report_id, candidate, installed)
            record['criterion'] = criterion
            if criterion['eligible']:
                self.stage = 'paired_audit'
                record['audit'] = self._audit(report, candidate, installed, cursor, criterion)
        record['incumbent_after_digest'] = self.incumbents[report_id].digest
        record['bank_size'] = len(self.learner.bank)
        record['status'] = 'complete'
        return True

    def _panel(self, label, count, reports, namespace):
        rows = self.evaluations[label]
        updates_before = self.learner.metrics['updates']
        installed_before = {key: policy.digest for key, policy in self.incumbents.items()}
        category = 'final' if label == 'final' else 'snapshot'
        for report in reports:
            policy = self.incumbents[report['public_id']]
            for index in range(count):
                record = dict(report_id=report['public_id'], report_index=report['index'],
                              report_kind=report['kind'], panel=label, context_index=index,
                              installed_digest=policy.digest,
                              ordinary_exposures=self.exposures[report['public_id']])
                rows.append(record)
                execution, _ = self._execute(
                    report, seed_for(self.seed, report['public_id'], index, namespace),
                    (policy,), category)
                record.update(execution)
                self._require_success(record)
                record['prediction'], record['reward'] = record['predictions'][0], record['rewards'][0]
        if updates_before != self.learner.metrics['updates'] or installed_before != {
                key: policy.digest for key, policy in self.incumbents.items()}:
            raise AssertionError('feedback-free panel changed learner or incumbent')

    def run(self, *, episode_limit=None):
        """Optional finite prefix is a test/pilot override recorded in raw output."""
        limit = self.config.matched_episodes if self.protocol == 'matched' else self.config.ordinary_guard
        if episode_limit is not None:
            if type(episode_limit) is not int or episode_limit < 0:
                raise ValueError('nonnegative finite episode limit required')
            limit = min(limit, episode_limit)
        try:
            warm_end = 4 * self.config.warm_rounds
            novel_end = warm_end + 4 * self.config.novel_rounds
            for cursor in range(limit):
                if not self.ordinary_episode(cursor):
                    break
                if self.protocol == 'matched' and cursor + 1 in (warm_end, novel_end):
                    label = 'after_warm' if cursor + 1 == warm_end else 'after_novel'
                    self.stage = label
                    self._panel(label, self.config.snapshot_contexts, self.reports[:4], 'retention-snapshot')
            self.stage = 'final_panel'
            self._panel('final', self.config.final_contexts, self.reports, 'final')
            actual_final = self.costs['final']['select_executions']
            if actual_final != self.config.final_reserve:
                raise AssertionError('reserved panel SELECT count differs from actual count')
            if self.protocol == 'budget' and self.work_selects + actual_final > self.config.total_select_budget:
                raise AssertionError('total SELECT budget exceeded')
            self.status = 'complete'
        except Exception as exc:
            self.status = 'failed'
            self.error = dict(stage=self.stage, type=type(exc).__name__, message=str(exc),
                              traceback=traceback.format_exc())
        return self.result(episode_limit=episode_limit)

    def result(self, *, episode_limit=None):
        total_cost = _empty_cost()
        for cost in self.costs.values():
            _plus(total_cost, cost)
        successful = [r for r in self.ordinary if 'reward' in r]
        feedback_episodes = sum(r['feedback_recorded'] for r in self.ordinary)
        def score(rows):
            values = [row['reward'] for row in rows if 'reward' in row]
            return statistics.mean(values) if values else None
        shared = [r for r in successful if r['report_kind'] == 'shared_novel' and r['report_exposure'] <= 24]
        first8 = [r for r in shared if r['report_exposure'] <= 8]
        final_by_report = {r['public_id']: score([row for row in self.evaluations['final']
                                                  if row['report_id'] == r['public_id']])
                           for r in self.reports}
        values = [value for value in final_by_report.values() if value is not None]
        summary = dict(seed=self.seed, method=self.method, protocol=self.protocol, status=self.status,
                       shared_novel_first24_reward=score(shared), shared_novel_first8_reward=score(first8),
                       unshared_novel_reward=score([r for r in successful if r['report_kind'] == 'unshared_novel']),
                       warm_reward=score([r for r in successful if r['phase'] == 'warm']),
                       retention_reward=score([r for r in successful if r['phase'] == 'retention']),
                       ordinary_reward=score(successful), final_macro_reward=statistics.mean(values) if values else None,
                       after_warm_old_reward=score(self.evaluations['after_warm']),
                       after_novel_old_reward=score(self.evaluations['after_novel']),
                       ordinary_episodes=feedback_episodes, ordinary_scored_predictions=len(successful),
                       ordinary_attempts=len(self.ordinary),
                       audit_pairs=sum(len(a['pairs']) for a in self.audits), started_audits=len(self.audits),
                       accepted_audits=sum(a['status'] == 'accepted' for a in self.audits),
                       promotions=len(self.promotions), work_select_executions=self.work_selects,
                       total_select_executions=total_cost['select_executions'],
                       per_report_exposures=dict(self.exposures), per_report_final_reward=final_by_report,
                       unreached_reports=[key for key, value in self.exposures.items() if value == 0],
                       history_evictions=self.learner.metrics['history_evictions'],
                       installed_other_policy_checks=self.installed_invariant_checks,
                       training_criterion_seconds=self.criterion_seconds,
                       training_criterion_row_feature_evaluations=self.criterion_row_features,
                       total_wall_seconds=time.perf_counter() - self.started_wall,
                       total_cpu_seconds=time.process_time() - self.started_cpu)
        return dict(format_version=1, seed=self.seed, method=self.method, protocol=self.protocol,
                    status=self.status, error=self.error, config=asdict(self.config),
                    test_episode_limit=episode_limit,
                    reports=list(self.reports), ordinary=self.ordinary, audits=self.audits,
                    evaluations=self.evaluations, promotions=self.promotions,
                    policy_registry=self.registry,
                    incumbents={key: policy.digest for key, policy in self.incumbents.items()},
                    gate_snapshot=self.gate.snapshot() if self.gate else None,
                    learner=dict(mode=self.learner.mode, max_history=self.learner.max_history,
                                 search_candidates=self.learner.search_candidates,
                                 metrics=dict(self.learner.metrics), bank=self.learner.bank,
                                 feature_events=self.learner.feature_events,
                                 reports={r['public_id']: self.learner.report_summary(r['public_id'])
                                          for r in self.reports}),
                    costs=dict(by_category=self.costs, total=total_cost,
                               budget_definition='Post-setup SELECT attempts including scoring; setup SQL excluded and setup time reported.'),
                    summary=summary)


def run_arm(run_seed, method, protocol, *, config=None, episode_limit=None):
    return Harness(run_seed, method, protocol, config).run(episode_limit=episode_limit)


def source_files():
    return (
        'src/witness_cl/relational_v7.py', 'src/witness_cl/statistical_gate_v7.py',
        'experiments/relational_v7.py', 'tests/test_experiment_v7.py',
        'docs/v7/EVALUATION.md', 'docs/v7/GATE.md', 'docs/v7/FORMAL.md',
    )


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files()}


def validate_freeze(freeze, seeds, methods, protocols, config):
    """Validate before constructing any context or creating output evidence."""
    current = source_hashes()
    untouched = any(seed in HOLDOUT_SEEDS for seed in seeds)
    if untouched and freeze is None:
        raise ValueError('untouched evaluation seeds require --freeze')
    if freeze is None:
        return current, None
    frozen = json.loads(Path(freeze).read_text())
    for field, actual in (('seeds', list(seeds)), ('methods', list(methods)),
                          ('protocols', list(protocols)), ('config', asdict(config))):
        if frozen.get(field) != actual:
            raise ValueError('run differs from frozen ' + field)
    hashes = frozen.get('source_sha256')
    if type(hashes) is not dict or not set(current).issubset(hashes):
        raise ValueError('freeze omits required source inputs')
    for name, digest in hashes.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('invalid frozen source path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('source drift after freeze: ' + name)
    if untouched and (tuple(seeds) != HOLDOUT_SEEDS or tuple(methods) != METHODS
                      or tuple(protocols) != ('matched', 'budget') or config != Config()):
        raise ValueError('holdout must use all sixteen seeds, six arms, both protocols and default configuration')
    return hashes, hashlib.sha256(Path(freeze).read_bytes()).hexdigest()


def run_experiment(seeds, protocols, out, *, methods=METHODS, config=None, freeze=None):
    config = config or Config()
    seeds, protocols, methods = tuple(seeds), tuple(protocols), tuple(methods)
    if (not seeds or len(set(seeds)) != len(seeds) or any(type(seed) is not int for seed in seeds)
            or not methods or len(set(methods)) != len(methods) or any(m not in METHODS for m in methods)
            or not protocols or len(set(protocols)) != len(protocols)
            or any(p not in ('matched', 'budget') for p in protocols)):
        raise ValueError('nonempty unique legal seed/method/protocol lists required')
    hashes, freeze_hash = validate_freeze(freeze, seeds, methods, protocols, config)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    manifest = dict(format_version=1, status='running', seeds=list(seeds), methods=list(methods),
                    protocols=list(protocols), config=asdict(config), source_sha256=hashes,
                    freeze_sha256=freeze_hash, started_at_utc=datetime.now(timezone.utc).isoformat(),
                    python=platform.python_version(), platform=platform.platform(),
                    blas_thread_environment={key: os.environ.get(key) for key in
                        ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS')},
                    budget_definition='Post-setup SELECT attempts; DDL/INSERT/PRAGMA/commit excluded; setup timed separately.')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    summaries = []
    failed = False
    try:
        for protocol in protocols:
            for seed in seeds:
                for method in methods:
                    result = run_arm(seed, method, protocol, config=config)
                    filename = f'{protocol}-{seed}-{method}.json'
                    (out / filename).write_text(json.dumps(result, separators=(',', ':'), allow_nan=False) + '\n')
                    summaries.append(dict(result['summary'], raw_file=filename))
                    if result['status'] != 'complete':
                        failed = True
        # Retain every seed-level result. Cross-seed inference is a separate analysis.
        groups = []
        for protocol in protocols:
            for method in methods:
                rows = [r for r in summaries if r['protocol'] == protocol and r['method'] == method]
                means = {}
                for field in ('shared_novel_first24_reward', 'shared_novel_first8_reward',
                              'unshared_novel_reward', 'warm_reward', 'retention_reward',
                              'ordinary_reward', 'final_macro_reward', 'total_select_executions',
                              'total_wall_seconds', 'audit_pairs', 'ordinary_episodes'):
                    vals = [r[field] for r in rows if r[field] is not None]
                    means[field] = (statistics.mean(vals) if vals else None) if all(
                        r['status'] == 'complete' for r in rows) else None
                groups.append(dict(protocol=protocol, method=method, runs=len(rows),
                                   failed_runs=sum(r['status'] != 'complete' for r in rows), means=means))
        (out / 'aggregates.json').write_text(json.dumps(dict(runs=summaries, groups=groups), indent=2) + '\n')
        for name, digest in hashes.items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                raise RuntimeError('source changed during experiment: ' + name)
        manifest['status'] = 'failed' if failed else 'complete'
    except Exception:
        manifest['status'] = 'failed'
        manifest['error'] = traceback.format_exc()
        raise
    finally:
        manifest['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest['status'] == 'complete'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', nargs='+', type=int, required=True)
    parser.add_argument('--protocol', choices=('matched', 'budget', 'both'), default='both')
    parser.add_argument('--methods', nargs='+', choices=METHODS, default=METHODS)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--freeze', type=Path)
    args = parser.parse_args()
    if any(os.environ.get(key) != '1' for key in
           ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS')):
        parser.error('set OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 before launch')
    protocols = ('matched', 'budget') if args.protocol == 'both' else (args.protocol,)
    return 0 if run_experiment(args.seeds, protocols, args.out, methods=args.methods, freeze=args.freeze) else 1


if __name__ == '__main__':
    raise SystemExit(main())
