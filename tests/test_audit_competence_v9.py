"""Small mutation checks for saved diagnostic replay; no server or model runs."""
from copy import deepcopy
import hashlib
import json

import pytest

from experiments import competence_v9 as runner
from experiments.audit_competence_v9 import audit_directory
from witness_cl.model_v9 import LocalInferenceV9


@pytest.fixture
def diagnostic(tmp_path, monkeypatch):
    class OfflineClient(LocalInferenceV9):
        def _post(self, path, body, timeout):
            if path.endswith('/input_tokens'):
                return {'input_tokens': 10}
            if len(body['messages']) == 2:
                content = {'action': 'QUERY', 'sql': 'SELECT COUNT(*) FROM catalog', 'params': {}}
            else:
                result = json.loads(body['messages'][-1]['content'])['tool_result']
                content = {'action': 'ANSWER', 'value': result['rows'][0][0]}
            return {'model': body['model'], 'usage': {'prompt_tokens': 10, 'completion_tokens': 6, 'total_tokens': 16},
                    'choices': [{'message': {'content': json.dumps(content), 'reasoning_content': None}, 'finish_reason': 'stop'}]}
        def complete(self, *args, **kwargs):
            content = super().complete(*args, **kwargs)
            kwargs['records'][-1]['test_double'] = True
            return content
    monkeypatch.setattr(runner, 'LocalInferenceV9', OfflineClient)
    key = tmp_path/'offline-key'; key.write_text('offline-test-no-authority')
    out = tmp_path/'diagnostic'
    runner.run(out, key, 'offline-v9', 'evidence', 92000)
    return out


def read(directory):
    return (json.loads((directory/'manifest.json').read_text()),
            [json.loads(line) for line in (directory/'episodes.jsonl').read_text().splitlines()])


def write(directory, manifest, rows):
    raw = ''.join(json.dumps(row, separators=(',', ':'))+'\n' for row in rows)
    (directory/'episodes.jsonl').write_text(raw)
    manifest['raw_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    (directory/'manifest.json').write_text(json.dumps(manifest))


def test_full_offline_grid_replays_with_known_cost_without_model_claim(diagnostic):
    report = audit_directory(diagnostic)
    assert report['status'] == 'passed' and report['complete_warm_grid']
    assert report['checked']['episodes'] == 8 and report['checked']['select_attempts'] == 8
    assert report['recorded_budget']['calls'] == 16
    assert report['recorded_budget']['total_tokens'] == 256
    assert report['checked']['test_double_calls'] == 16
    assert not report['competence_threshold_met'] and not report['claim_confirmed']


@pytest.mark.parametrize('change', ['sql_result', 'prompt', 'config', 'cost', 'attempt', 'feedback', 'source'])
def test_rehashed_corruptions_fail_independent_replay(diagnostic, change):
    manifest, rows = read(diagnostic)
    if change == 'sql_result':
        rows[0]['queries'][0]['rows'][0][0] += 1
    elif change == 'prompt':
        rows[0]['model_calls'][0]['messages'][-1]['content'] += '\nHidden reference answer: 123'
    elif change == 'config':
        rows[0]['model_calls'][0]['request_config']['chat_template_kwargs']['enable_thinking'] = True
    elif change == 'cost':
        manifest['budget']['completion_tokens'] += 1
    elif change == 'attempt':
        rows[0]['queries'][0]['attempt'] = True
    elif change == 'feedback':
        rows[0]['feedback']['correct'] = not rows[0]['feedback']['correct']
    else:
        manifest['source_sha256']['src/witness_cl/model_v9.py'] = '0'*64
    write(diagnostic, manifest, rows)
    report = audit_directory(diagnostic)
    assert report['status'] == 'failed' and report['failures']
    assert not report['competence_threshold_met']


def test_selected_subset_is_consistent_but_never_a_complete_warm_screen(diagnostic):
    manifest, rows = read(diagnostic)
    rows = rows[:4]
    manifest.update(indices=list(range(4)), n=4, correct=sum(r['reward'] for r in rows))
    calls = [c for row in rows for c in row['model_calls']]
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        manifest['budget'][field] = sum(c['usage'][field] for c in calls)
    manifest['budget']['calls'] = len(calls)
    for field in ('tokenization_seconds', 'inference_seconds'):
        manifest['budget'][field] = sum(c[field] for c in calls)
    write(diagnostic, manifest, rows)
    report = audit_directory(diagnostic)
    assert report['status'] == 'passed'
    assert not report['complete_warm_grid'] and not report['competence_threshold_met']


def make_interactive(directory):
    from experiments import competence_interactive_v9 as interactive
    from experiments.audit_competence_v9 import ROOT, sha
    manifest, rows = read(directory)
    del manifest['source_sha256']['experiments/competence_v9.py']
    manifest['source_sha256']['experiments/competence_interactive_v9.py'] = sha(ROOT/'experiments/competence_interactive_v9.py')
    for row in rows:
        for call in row['model_calls']:
            call['messages'][0]['content'] = interactive.V9_SYSTEM
    write(directory, manifest, rows)


def test_interactive_protocol_uses_exact_standalone_public_prompt(diagnostic):
    make_interactive(diagnostic)
    report = audit_directory(diagnostic)
    assert report['status'] == 'passed'
    assert report['protocol_source'] == 'experiments/competence_interactive_v9.py'


@pytest.mark.parametrize('mutation', ['prompt_mismatch', 'source_config'])
def test_interactive_prompt_cannot_be_swapped_or_relabelled_as_original(diagnostic, mutation):
    from experiments.audit_competence_v9 import ROOT, sha
    make_interactive(diagnostic)
    manifest, rows = read(diagnostic)
    if mutation == 'prompt_mismatch':
        rows[0]['model_calls'][0]['messages'][0]['content'] = runner.V9_SYSTEM
    else:
        del manifest['source_sha256']['experiments/competence_interactive_v9.py']
        manifest['source_sha256']['experiments/competence_v9.py'] = sha(ROOT/'experiments/competence_v9.py')
    write(diagnostic, manifest, rows)
    report = audit_directory(diagnostic)
    assert report['status'] == 'failed' and not report['competence_threshold_met']
    assert any('prompt differs' in entry['message'] for entry in report['failures'])
