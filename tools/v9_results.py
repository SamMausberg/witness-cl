#!/usr/bin/env python3
"""Descriptive v9 report from frozen, replayed attempts; no inference or pooling."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTICS = ('4b-original','4b-evidence','4b-sampled','4b-thinking',
               '9b-evidence','9b-interactive','9b-interactive-thinking')
ATTEMPTS = (('prospective-92001','prepilot-freeze.json'),
            ('prospective-json-92002','prepilot-json-freeze.json'),
            ('prospective-portable-92003','prepilot-portable-freeze.json'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text())

def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, name, minimum=0):
    require(type(value) is int and value >= minimum, name + ' must be an exact nonnegative integer')
    return value


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def checked_costs(rows, budget):
    """Reconcile measured usage and retain failed-request reservations separately."""
    calls, unknown, prompt, completion, reservation = [], [], 0, 0, 0
    for row in rows:
        for call in row['model_calls']:
            require(type(call.get('generation_attempted')) is bool, 'missing generation-attempt flag')
            if not call['generation_attempted']:
                require(call.get('usage') is None, 'non-generation call has token usage')
                continue
            calls.append(call)
            usage = call.get('usage')
            if usage is None:
                require(call.get('status') == 'failed', 'successful generation has unknown usage')
                unknown.append(call)
                reservation += integer(call.get('preflight_tokens'), 'unknown preflight tokens')
                reservation += integer(call.get('max_output_tokens'), 'unknown output reservation', 1)
            else:
                require(type(usage) is dict, 'invalid measured usage')
                p = integer(usage.get('prompt_tokens'), 'prompt tokens')
                c = integer(usage.get('completion_tokens'), 'completion tokens')
                t = integer(usage.get('total_tokens'), 'total tokens')
                require(t == p + c, 'usage components do not sum to total')
                prompt += p
                completion += c
    expected = {'calls': len(calls), 'prompt_tokens': prompt, 'completion_tokens': completion,
                'total_tokens': prompt + completion, 'unknown_usage_calls': len(unknown)}
    for name, value in expected.items():
        require(integer(budget.get(name), 'budget ' + name) == value, 'budget disagrees with raw ' + name)
    return {'calls': len(calls), 'known_tokens': prompt + completion,
            'unknown_calls': len(unknown), 'unknown_reservation': reservation}


def receipt_directory(receipt, suffix):
    directory = receipt.get('directory')
    require(type(directory) is str and tuple(Path(directory).parts[-len(suffix):]) == tuple(suffix),
            'replay receipt belongs to a different artifact directory')


def checked_diagnostic_receipts():
    receipts = read(ROOT/'artifacts/v9/diagnostics/replay-all.json')
    require(type(receipts) is list and len(receipts) == len(DIAGNOSTICS), 'diagnostic replay roster is incomplete')
    found = {}
    for receipt in receipts:
        name = Path(receipt.get('directory', '')).name
        require(name in DIAGNOSTICS and name not in found, 'duplicate or unexpected diagnostic replay')
        receipt_directory(receipt, ('artifacts', 'v9', 'diagnostics', name))
        found[name] = receipt
    require(set(found) == set(DIAGNOSTICS), 'diagnostic replay roster differs')
    return found


def checked_diagnostic(name, receipt):
    d = ROOT/'artifacts/v9/diagnostics'/name
    m = read(d/'manifest.json')
    receipt_directory(receipt, ('artifacts', 'v9', 'diagnostics', name))
    require(receipt.get('status') == 'passed' and receipt.get('failures') == [], 'diagnostic replay did not pass')
    require(receipt.get('manifest_sha256') == sha(d/'manifest.json'), 'diagnostic manifest is not the replayed manifest')
    raw_hash = sha(d/'episodes.jsonl')
    require(receipt.get('raw_sha256') == m.get('raw_sha256') == raw_hash, 'diagnostic raw/replay binding differs')
    require(receipt.get('auditor_source_sha256') == sha(ROOT/'experiments/audit_competence_v9.py'), 'diagnostic auditor source changed')
    require(receipt.get('checked_source_sha256') == m.get('source_sha256'), 'diagnostic source map differs from replay')
    for path, h in m['source_sha256'].items():
        require(sha(ROOT/path) == h, 'diagnostic executed source changed: ' + path)
    require(m.get('status') == receipt.get('manifest_status') == 'completed' and m.get('source_unchanged') is True,
            'diagnostic was not completed with unchanged sources')
    require(receipt.get('recorded_budget') == m['budget'], 'diagnostic budget differs from replay')
    require(receipt.get('elapsed_seconds') == m['elapsed_seconds'], 'diagnostic duration differs from replay')
    rows = read_lines(d/'episodes.jsonl')
    require(all(type(r.get('reward')) in (int, float) and r['reward'] in (0, 1) for r in rows), 'invalid diagnostic correctness reward')
    correct = sum(r['reward'] == 1 for r in rows)
    require(integer(m['n'], 'diagnostic n') == len(rows) == receipt['checked']['episodes'] == 8,
            'diagnostic warm grid differs from replay')
    require(m['correct'] == correct == receipt['checked']['correct_episodes'], 'diagnostic score differs from replay')
    require(receipt.get('complete_warm_grid') is True, 'diagnostic warm grid is incomplete')
    costs = checked_costs(rows, m['budget'])
    require(receipt.get('known_usage_complete') is (costs['unknown_calls'] == 0), 'diagnostic usage status differs')
    return dict(name=name, correct=correct, n=len(rows), calls=costs['calls'], tokens=costs['known_tokens'],
                unknown_calls=costs['unknown_calls'], unknown_reservation=costs['unknown_reservation'],
                seconds=m['elapsed_seconds'], manifest_sha256=sha(d/'manifest.json'), raw_sha256=raw_hash)


def checked_attempt(name, freeze_name):
    base = ROOT/'artifacts/v9'; d = base/name
    m, a, f = read(d/'manifest.json'), read(base/(name+'-replay.json')), read(base/freeze_name)
    receipt_directory(a, ('artifacts', 'v9', name))
    require(m['status'] != 'running' and a.get('status') == 'passed' and a.get('failures') == [], 'attempt replay did not pass')
    require(a.get('manifest_sha256') == sha(d/'manifest.json'), 'attempt manifest differs from replay')
    require(a.get('manifest_status') == m['status'], 'attempt status differs from replay')
    require(a.get('summary_sha256') == m.get('summary_sha256') == sha(d/'summary.json'), 'attempt summary differs from replay')
    require(a.get('checked_freeze_sha256') == sha(base/freeze_name), 'attempt external freeze differs from replay')
    require(a.get('auditor_source_sha256') == sha(ROOT/'experiments/audit_sql_abstractions_v9.py'), 'attempt auditor changed')
    dependencies = a.get('auditor_dependencies_sha256')
    require(type(dependencies) is dict and set(dependencies) == {'experiments/audit_sql_abstractions_v8.py'},
            'attempt replay helper inventory missing or substituted')
    for path, h in dependencies.items():
        require(sha(ROOT/path) == h, 'attempt replay helper changed')
    require(a.get('checked_source_sha256') == m.get('source_sha256') == f['source_sha256'], 'attempt source maps differ')
    require(a.get('checked_support_sha256') == f['support_sha256'], 'attempt support receipt map differs')
    for path, h in {**f['source_sha256'], **f['support_sha256']}.items():
        require(sha(ROOT/path) == h, 'attempt frozen source/support changed: ' + path)
    require(a.get('raw_sha256') == m['raw_sha256'], 'attempt raw map differs from replay')
    require({p.name for p in d.glob('*.jsonl')} == set(m['raw_sha256']), 'unlisted/missing attempt raw file')
    rows = []
    for filename, h in m['raw_sha256'].items():
        require(Path(filename).name == filename and sha(d/filename) == h, 'attempt raw hash differs')
        rows.extend(read_lines(d/filename))
    costs = checked_costs(rows, m['total_budget'])
    require(a.get('known_usage_complete') is (costs['unknown_calls'] == 0), 'attempt known-usage status differs from replay')
    require(a['counts'].get('generation_attempts', 0) == costs['calls'] and
            a['counts'].get('known_total_tokens', 0) == costs['known_tokens'] and
            a['counts'].get('unknown_usage_calls', 0) == costs['unknown_calls'] and
            a['counts'].get('unknown_usage_reserved_tokens', 0) == costs['unknown_reservation'],
            'attempt replay cost counters differ from raw calls')
    require(a.get('total_budget') == m['total_budget'], 'attempt total budget differs from replay')
    require(a.get('elapsed_seconds') == m['elapsed_seconds'], 'attempt duration differs from replay')
    require(type(m.get('warm_qualified')) is bool and a.get('warm_qualified') is m['warm_qualified'],
            'attempt competence status differs from replay')
    require(type(m.get('required_records_complete')) is bool and
            a.get('required_records_complete') is m['required_records_complete'],
            'attempt completion status differs from replay')
    require(all(type(r.get('reward')) in (int, float) and r['reward'] in (0, 1) for r in rows),
            'invalid attempt correctness reward')
    require(integer(a['counts'].get('episodes'), 'replayed episode count') == len(rows) and
            integer(a['counts'].get('correct_episodes'), 'replayed correct count') == sum(r['reward'] for r in rows),
            'attempt episode counts differ from replay')
    return dict(name=name, status=m['status'], records=len(rows),
                correct=sum(r['reward'] for r in rows), **costs,
                selects=sum(r['select_attempts'] for r in rows), seconds=m['elapsed_seconds'],
                warm_qualified=m['warm_qualified'], complete=m['required_records_complete'],
                manifest_sha256=sha(d/'manifest.json'), replay_sha256=sha(base/(name+'-replay.json')),
                arms=read(d/'summary.json'), rows=rows)

def main():
    base = ROOT/'artifacts/v9'
    diagnostic_receipts = checked_diagnostic_receipts()
    diagnostics = [checked_diagnostic(name, diagnostic_receipts[name]) for name in DIAGNOSTICS]
    attempts = [checked_attempt(*item) for item in ATTEMPTS]
    last = attempts[-1]; final_arms = []
    for arm in last['arms']:
        rows = [r for r in last['rows'] if r['arm'] == arm['arm']]
        final_arms.append(dict(arm=arm['arm'], correct=arm['warm']['correct'], n=arm['warm']['n'],
            selects=sum(r['select_attempts'] for r in rows), calls=sum(len([c for c in r['model_calls'] if c['generation_attempted']]) for r in rows),
            tokens=arm['ordinary_budget']['total_tokens']+arm['panel_budget']['total_tokens'],
            model_seconds=arm['ordinary_budget']['inference_seconds']+arm['panel_budget']['inference_seconds'],
            retained_bytes=arm['memory']['memory_bytes'],
            admissions=sum(e['kind']=='abstraction_reconstructed' for e in arm['memory']['events']),
            proposals=sum(c['phase'].endswith(':reflection') for r in rows for c in r['model_calls']) if arm['arm']=='fragments' else 0,
            reconstructions=sum(q['purpose']=='abstraction_reconstruction' for r in rows for q in r['queries']),
            use_actions=sum(a.get('action') in ('USE','COMPOSE') for r in rows for a in r['actions']),
            guard_checks=sum(q['purpose']=='applicability_check' for r in rows for q in r['queries'])))
    total_known = sum(d['tokens'] for d in diagnostics)+sum(a['known_tokens'] for a in attempts)
    unknown = sum(d['unknown_calls'] for d in diagnostics)+sum(a['unknown_calls'] for a in attempts)
    reservation = sum(d['unknown_reservation'] for d in diagnostics)+sum(a['unknown_reservation'] for a in attempts)
    totals = dict(episodes=sum(d['n'] for d in diagnostics)+sum(a['records'] for a in attempts),
                  calls=sum(d['calls'] for d in diagnostics)+sum(a['calls'] for a in attempts),
                  known_tokens=total_known, unknown_calls=unknown, unknown_reservation=reservation,
                  token_upper_bound=total_known+reservation,
                  token_allowance_including_unknown_reservations=total_known+reservation,
                  unknown_cost_interpretation='Unknown reservations are protocol allowances, not measured backend usage; token_upper_bound is a legacy name for this allowance.',
                  seconds=sum(d['seconds'] for d in diagnostics)+sum(a['seconds'] for a in attempts))
    require(totals['seconds'] <= 2700 and totals['calls'] <= 1600 and totals['token_allowance_including_unknown_reservations'] <= 4000000,
            'aggregate declared development allowance exceeded')
    result=dict(claim_confirmed=False, diagnostics=diagnostics,
                diagnostic_replay_sha256=sha(base/'diagnostics/replay-all.json'),
                attempts=[{k:v for k,v in a.items() if k not in ('rows','arms')} for a in attempts],
                final_arms=final_arms, totals=totals,
                inference='Descriptive development evidence only; no population confidence interval or complete transfer comparison.')
    (base/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    names={'4b-original':'4B original','4b-evidence':'4B evidence','4b-sampled':'4B sampled',
           '4b-thinking':'4B thinking','9b-evidence':'9B evidence','9b-interactive':'9B live',
           '9b-interactive-thinking':'9B live + thinking'}
    lines=[r'\begin{table}[t]\centering\small\setlength{\tabcolsep}{4pt}',r'\caption{All adaptive solver diagnostics on development seed 92000.}',r'\begin{tabular}{lrrr}\toprule Setting & Correct & Calls & Tokens \\ \midrule']
    lines += [f"{names[d['name']]} & {d['correct']}/8 & {d['calls']} & {d['tokens']:,} \\\\" for d in diagnostics]
    lines += [r'\bottomrule\end{tabular}\end{table}']
    (ROOT/'paper/v9_diagnostics.tex').write_text('\n'.join(lines)+'\n')
    names={'full_history':'Full history','insights':'Evolving text','fragments':'Checked programs'}
    lines=[r'\begin{table}[t]\centering\small\setlength{\tabcolsep}{4pt}',r'\caption{Final fresh development warm block. Accuracy and costs are shown separately; these are not matched-accuracy efficiency results.}',r'\begin{tabular}{lrrrr}\toprule Method & Correct & SELECTs & Calls & Tokens \\ \midrule']
    lines += [f"{names[a['arm']]} & {a['correct']}/{a['n']} & {a['selects']} & {a['calls']} & {a['tokens']:,} \\\\" for a in final_arms]
    lines += [r'\bottomrule\end{tabular}\end{table}']
    (ROOT/'paper/v9_warm.tex').write_text('\n'.join(lines)+'\n')
    print(json.dumps(result,indent=2))

if __name__ == '__main__':main()
