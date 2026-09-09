"""Tiny protocol fixtures only; never run the preregistered development/holdout."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3

import pytest

import experiments.relational_v7 as experiment
from witness_cl.relational_v7 import FrozenPolicy, SQLiteContext


TEST_SEED = 713


def tiny_config(**overrides):
    base = experiment.Config(warm_rounds=1, novel_rounds=1, retention_rounds=1,
                             snapshot_contexts=1, final_contexts=1)
    return replace(base, **overrides)


def true_fixture_policy(report):
    # Evaluator-only test fixture for isolated audit-protocol checks. The real
    # ordinary_episode path obtains every proposal only from learner.propose.
    return FrozenPolicy(tuple(m for m, _ in report['spec']),
                        tuple(float(c) for _, c in report['spec']))


def test_evaluator_report_generator_and_seed_namespaces():
    reports = experiment.reports_for(TEST_SEED)
    assert reports == experiment.reports_for(TEST_SEED)
    assert len({r['public_id'] for r in reports}) == 8
    assert all(r['public_id'].startswith('report_') and len(r['public_id']) == 31 for r in reports)
    warm = [r['spec'][0][0] for r in reports[:4]]
    assert len(set(warm)) == 4 and all(sum(m) == 2 for m in warm)
    assert reports[4]['spec'] == ((warm[0], 1), (warm[1], 1))
    assert reports[5]['spec'] == ((warm[2], 1), (warm[3], 1))
    assert all(sum(r['spec'][0][0]) == 3 for r in reports[6:])
    assert reports[6]['spec'] != reports[7]['spec']
    report = reports[0]['public_id']
    namespaces = [experiment.seed_for(TEST_SEED, 0, 'ordinary'),
                  experiment.seed_for(TEST_SEED, report, 0, 'final'),
                  experiment.seed_for(TEST_SEED, report, 0, 'retention-snapshot')]
    namespaces += [experiment.seed_for(TEST_SEED, 'audited_grow_reuse', protocol, report, 1, 0, 'audit')
                   for protocol in ('matched', 'budget')]
    assert len(set(namespaces)) == len(namespaces)


@pytest.mark.parametrize('method', ('audited_grow_reuse', 'ungated_full_history_sparse'))
def test_tiny_matched_stream_queries_prequential_order_and_panels(method):
    result = experiment.run_arm(TEST_SEED, method, 'matched', config=tiny_config())
    assert result['status'] == 'complete', result['error']
    assert result['summary']['ordinary_episodes'] == 12
    assert result['learner']['metrics']['updates'] == 12
    assert not result['audits']
    costs = result['costs']['by_category']
    assert costs['ordinary']['select_executions'] == 36
    assert costs['snapshot']['select_executions'] == 24
    assert costs['final']['select_executions'] == 24
    assert result['costs']['total']['select_executions'] == 84
    current = {r['public_id']: result['ordinary'][0]['installed_digest'] for r in result['reports']}
    by_episode = {p['episode']: p for p in result['promotions']}
    for row in result['ordinary']:
        assert row['installed_digest'] == current[row['report_id']]
        assert row['costs']['measurement_selects'] == 2 and row['costs']['gold_selects'] == 1
        assert row['learner_updates'] == row['episode'] + 1
        if row['report_exposure'] == 1:
            assert row['prediction'] == 0
        if row['episode'] in by_episode:
            current[row['report_id']] = by_episode[row['episode']]['candidate_digest']
    first = result['evaluations']['after_warm']
    second = result['evaluations']['after_novel']
    assert [(r['context_seed'], r['installed_digest'], r['prediction']) for r in first] == [
        (r['context_seed'], r['installed_digest'], r['prediction']) for r in second]
    ordinary_seeds = {r['context_seed'] for r in result['ordinary']}
    assert not ordinary_seeds.intersection(r['context_seed'] for r in result['evaluations']['final'])
    assert not ordinary_seeds.intersection(r['context_seed'] for r in first)


def test_shared_ordinary_stream_and_feedback_are_identical_across_arms():
    results = [experiment.run_arm(TEST_SEED, method, 'matched', config=tiny_config())
               for method in ('audited_grow_reuse', 'ungated_full_history_sparse')]
    def inputs(result):
        return [(r['episode'], r['report_id'], r['context_seed'], r['observation']['rows'], r['target'])
                for r in result['ordinary']]
    assert inputs(results[0]) == inputs(results[1])


def test_budget_reserves_panel_and_spends_saved_queries_on_ordinary_examples():
    config = tiny_config(total_select_budget=40, snapshot_contexts=0)
    result = experiment.run_arm(TEST_SEED, 'ungated_full_history_sparse', 'budget', config=config)
    assert result['status'] == 'complete', result['error']
    assert result['summary']['ordinary_episodes'] == 5
    assert result['summary']['work_select_executions'] == 15
    assert result['summary']['total_select_executions'] == 39 <= 40
    assert result['costs']['by_category']['final']['select_executions'] == 24
    assert result['costs']['by_category']['snapshot']['select_executions'] == 0
    assert result['learner']['max_history'] == 256
    assert result['summary']['unreached_reports']
    for row in result['evaluations']['final']:
        if row['ordinary_exposures'] == 0:
            assert row['prediction'] == 0
            assert row['report_id'] in result['summary']['unreached_reports']


@pytest.mark.parametrize('remaining', range(5))
def test_less_than_five_remaining_closes_audit_without_execution_or_training(remaining):
    config = tiny_config(total_select_budget=24 + remaining, snapshot_contexts=0)
    h = experiment.Harness(TEST_SEED, 'audited_grow_reuse', 'budget', config)
    report = h.reports[0]
    candidate = true_fixture_policy(report)
    incumbent = h.incumbents[report['public_id']]
    before = {key: policy.digest for key, policy in h.incumbents.items()}
    result = h._audit(report, candidate, incumbent, 0, {'eligible': True})
    assert result == {'status': 'inconclusive', 'audit_index': 1, 'pairs': 0}
    assert h.gate.started_audits == 1 and h.gate.allocated_alpha_total > 0
    assert h.work_selects == 0 and h.learner.metrics['updates'] == 0
    assert before == {key: policy.digest for key, policy in h.incumbents.items()}
    assert h.audits[0]['learner_updates_before'] == h.audits[0]['learner_updates_after'] == 0


def test_one_actual_pair_costs_five_then_budget_closes_audit():
    config = tiny_config(total_select_budget=30, snapshot_contexts=0)
    h = experiment.Harness(TEST_SEED, 'audited_grow_reuse', 'budget', config)
    report = h.reports[0]
    result = h._audit(report, true_fixture_policy(report), h.incumbents[report['public_id']],
                      0, {'eligible': True})
    assert result['status'] == 'inconclusive' and result['pairs'] == 1
    pair = h.audits[0]['pairs'][0]
    assert pair['costs']['measurement_selects'] == 4
    assert pair['costs']['gold_selects'] == 1
    assert pair['costs']['select_executions'] == h.work_selects == 5
    assert pair['gate_prefix']['pairs'] == 1
    assert h.learner.metrics['updates'] == 0
    assert h.audits[0]['stop_reason'] == 'remaining_select_budget_below_five'
    completed = h.run(episode_limit=0)
    assert completed['status'] == 'complete'
    assert completed['summary']['total_select_executions'] == 29 <= 30


def test_accepted_audit_freezes_and_installs_only_current_report_without_fitting(monkeypatch):
    h = experiment.Harness(TEST_SEED, 'audited_grow_reuse', 'matched', tiny_config())
    report = h.reports[0]
    candidate = true_fixture_policy(report)
    incumbent = h.incumbents[report['public_id']]
    other_before = {key: p.digest for key, p in h.incumbents.items() if key != report['public_id']}
    promoted = []
    monkeypatch.setattr(h.learner, 'on_promotion', lambda key, policy: promoted.append((key, policy.digest)))
    monkeypatch.setattr(h.learner, 'observe', lambda *args: pytest.fail('audit attempted numerical training'))
    outcome = h._audit(report, candidate, incumbent, 0, {'eligible': True})
    assert outcome['status'] == 'accepted'
    assert h.incumbents[report['public_id']].digest == candidate.digest
    assert promoted == [(report['public_id'], candidate.digest)]
    assert other_before == {key: p.digest for key, p in h.incumbents.items() if key != report['public_id']}
    assert h.learner.metrics['updates'] == 0
    for pair in h.audits[0]['pairs']:
        assert pair['policy_digests'] == [candidate.digest, incumbent.digest]
        assert pair['gate_prefix']['candidate_digest'] == candidate.digest
        assert pair['gate_prefix']['incumbent_digest'] == incumbent.digest
        assert pair['costs']['select_executions'] == 5


def test_failed_select_keeps_attempt_cost_and_closes_pending_audit(monkeypatch):
    original = SQLiteContext._query
    def measured_then_failed(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise sqlite3.OperationalError('injected after measured SELECT')
    monkeypatch.setattr(SQLiteContext, '_query', measured_then_failed)
    h = experiment.Harness(TEST_SEED, 'audited_grow_reuse', 'matched', tiny_config())
    report = h.reports[0]
    with pytest.raises(RuntimeError, match='context execution failed'):
        h._audit(report, true_fixture_policy(report), h.incumbents[report['public_id']],
                 0, {'eligible': True})
    assert h.audits[0]['status'] == 'inconclusive'
    assert h.gate.active_token is None and not h.promotions
    assert h.costs['audit']['measurement_selects'] == 1
    assert h.costs['audit']['gold_selects'] == 0
    assert len(h.audits[0]['pairs']) == 1 and h.audits[0]['pairs'][0]['error']
    assert h.learner.metrics['updates'] == 0


def test_run_failure_is_recorded_without_claiming_reserved_panel_completed(monkeypatch):
    def failure(*args, **kwargs):
        raise sqlite3.OperationalError('injected initial context failure')
    monkeypatch.setattr(experiment, 'make_context', failure)
    result = experiment.run_arm(TEST_SEED, 'audited_grow_reuse', 'budget', config=tiny_config())
    assert result['status'] == 'failed'
    assert result['error']['stage'] == 'ordinary_execution'
    assert result['summary']['ordinary_episodes'] == 0
    assert not result['evaluations']['final']
    assert result['ordinary'][0]['error']


def test_evaluation_seed_requires_complete_frozen_protocol_before_sampling(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(experiment, 'make_context', lambda seed: called.append(seed))
    with pytest.raises(ValueError, match='require --freeze'):
        experiment.run_experiment([81000], ['matched'], tmp_path / 'blocked')
    assert not called and not (tmp_path / 'blocked').exists()
    frozen = dict(seeds=[81000], methods=list(experiment.METHODS), protocols=['matched'],
                  config=experiment.default_config(), source_sha256=experiment.source_hashes())
    path = tmp_path / 'invalid-freeze.json'
    path.write_text(json.dumps(frozen))
    with pytest.raises(ValueError, match='all sixteen'):
        experiment.run_experiment([81000], ['matched'], tmp_path / 'blocked2', freeze=path)
    assert not called and not (tmp_path / 'blocked2').exists()


def test_raw_manifest_and_completed_directory_are_preserved(tmp_path):
    out = tmp_path / 'tiny-record'
    config = tiny_config(warm_rounds=0, novel_rounds=0, retention_rounds=0,
                         snapshot_contexts=0, final_contexts=1)
    assert experiment.run_experiment([TEST_SEED], ['matched'], out,
                                     methods=('ungated_full_history_sparse',), config=config)
    before = (out / 'manifest.json').read_bytes()
    manifest = json.loads(before)
    assert manifest['status'] == 'complete'
    raw = json.loads((out / f'matched-{TEST_SEED}-ungated_full_history_sparse.json').read_text())
    assert raw['summary']['ordinary_episodes'] == 0
    assert raw['summary']['total_select_executions'] == 24
    assert raw['policy_registry'] and len(raw['summary']['unreached_reports']) == 8
    with pytest.raises(FileExistsError):
        experiment.run_experiment([TEST_SEED], ['matched'], out,
                                  methods=('ungated_full_history_sparse',), config=config)
    assert (out / 'manifest.json').read_bytes() == before


def test_real_sqlite_vm_interrupt_is_charged_before_any_feedback(monkeypatch):
    original = experiment.make_context
    def constrained(seed):
        context = original(seed)
        context.max_vm_steps = 1
        return context
    monkeypatch.setattr(experiment, 'make_context', constrained)
    result = experiment.run_arm(TEST_SEED, 'audited_grow_reuse', 'budget', config=tiny_config())
    assert result['status'] == 'failed'
    assert result['costs']['by_category']['ordinary']['measurement_selects'] == 1
    assert result['costs']['by_category']['ordinary']['gold_selects'] == 0
    assert result['learner']['metrics']['updates'] == 0
    assert result['summary']['ordinary_episodes'] == 0
    assert not result['ordinary'][0]['feedback_recorded']
    assert result['ordinary'][0]['error']['type'] == 'OperationalError'
    assert result['costs']['total']['setup_seconds'] > 0


def test_failed_run_preserved_and_excluded_from_completed_aggregate_claim(tmp_path, monkeypatch):
    original = experiment.make_context
    def constrained(seed):
        context = original(seed)
        context.max_vm_steps = 1
        return context
    monkeypatch.setattr(experiment, 'make_context', constrained)
    out = tmp_path / 'failed-evidence'
    assert not experiment.run_experiment([TEST_SEED], ['matched'], out,
                                         methods=('audited_grow_reuse',), config=tiny_config())
    manifest = json.loads((out / 'manifest.json').read_text())
    aggregate = json.loads((out / 'aggregates.json').read_text())
    raw = json.loads((out / f'matched-{TEST_SEED}-audited_grow_reuse.json').read_text())
    assert manifest['status'] == raw['status'] == 'failed'
    assert aggregate['groups'][0]['failed_runs'] == 1
    assert all(value is None for value in aggregate['groups'][0]['means'].values())
    assert aggregate['runs'][0]['status'] == 'failed'
    assert raw['costs']['total']['select_executions'] == 1
