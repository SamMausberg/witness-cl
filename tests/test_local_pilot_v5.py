"""Contract tests for pilot isolation and real-call accounting, not model quality."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location('local_pilot', Path(__file__).parents[1] / 'experiments/local_pilot_v5.py')
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def test_visible_payload_has_no_evaluator_state():
    payload = pilot.visible_payload([((0, 1),)], 1)
    assert set(payload) == {'actions', 'observations', 'horizon', 'known_upper_hidden_states',
                            'reset', 'stationary', 'objective_rewards', 'executed_traces'}
    assert payload['executed_traces'] == [((0, 1),)]
    assert payload['objective_rewards'] == (2, 0)


def test_rejection_counts_call_and_anchor():
    program, error = pilot.parse_or_anchor('{"word":[true,0,0,0]}')
    assert error
    assert program == pilot.Program.word((0, 0, 0, 0), 2)


def test_mock_pilot_accounts_once_per_model_episode_and_preserves_outputs(tmp_path):
    class Client:
        model = 'mock-not-real'
        max_tokens = 96
        calls = 0
        def complete(self, system, user):
            self.calls += 1
            assert 'machine' not in json.loads(user)
            return SimpleNamespace(content='invalid', usage={'prompt_tokens': 7, 'completion_tokens': 2}, seconds=.1)
    client = Client()
    out = tmp_path / 'pilot'
    summary = pilot.run(client, out, seeds=(1,), episodes=3)
    assert client.calls == 6
    assert summary['raw_history']['invalid_outputs'] == 3
    assert summary['checked_history']['invalid_outputs'] == 3
    assert summary['checked_static']['model_calls'] == 0
    assert summary['raw_history']['prompt_tokens'] == 21
    assert json.loads((out / 'manifest.json').read_text())['status'] == 'complete'
    assert len((out / 'episodes.jsonl').read_text().splitlines()) == 9
    with pytest.raises(FileExistsError):
        pilot.run(client, out, episodes=3)


def test_failure_is_durable_not_fabricated_success(tmp_path):
    class Client:
        model = 'mock-failure'
        max_tokens = 96
        def complete(self, *args):
            raise RuntimeError('provider failure')
    out = tmp_path / 'failure'
    with pytest.raises(RuntimeError):
        pilot.run(Client(), out, episodes=3)
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['status'] == 'failed'
    assert manifest['completed_rows'] == 0
    assert not (out / 'summary.json').exists()


def test_incomplete_usage_is_flagged_and_rejections_are_not_proposal_execution(tmp_path):
    class Client:
        model = 'mock-incomplete-usage'
        max_tokens = 96
        def complete(self, *args):
            return SimpleNamespace(content='invalid', usage={}, seconds=.1)
    out = tmp_path / 'partial-usage'
    summary = pilot.run(Client(), out, seeds=(1,), episodes=3)
    assert summary['raw_history']['usage_missing'] == 3
    assert summary['checked_history']['usage_missing'] == 3
    rows = [json.loads(line) for line in (out / 'episodes.jsonl').read_text().splitlines()]
    assert all(r['proposal_executed'] is None for r in rows)
    raw = [r for r in rows if r['arm'] == 'raw_history']
    assert all(all(action == 0 for action, _ in r['trace']) for r in raw)
    checked = [r for r in rows if r['arm'] == 'checked_history']
    assert any(any(action == 1 for action, _ in r['trace']) for r in checked)
    assert 'skip registration' in json.loads((out / 'manifest.json').read_text())['invalid_output']
