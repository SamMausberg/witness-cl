"""Strict stream-level analysis of the frozen v7 SQLite experiment.

All inference uses one value per independent seed. Generated paper prose is
populated only after every predeclared holdout run has completed successfully.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import sys

import numpy as np
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parents[1]
SEEDS = tuple(range(81000, 81016))
METHODS = (
    'audited_grow_reuse', 'audited_grow_no_reuse', 'audited_full_history_sparse',
    'ungated_full_history_sparse', 'ungated_full_ridge', 'audited_grow_full84',
)
CONTROLS = ('audited_full_history_sparse', 'ungated_full_history_sparse', 'ungated_full_ridge')
LABELS = {
    'audited_grow_reuse': 'Grow + reuse, audited',
    'audited_grow_no_reuse': 'Grow, no reuse, audited',
    'audited_full_history_sparse': 'Sparse history, audited',
    'ungated_full_history_sparse': 'Sparse history, ungated',
    'ungated_full_ridge': 'Full ridge, ungated',
    'audited_grow_full84': 'Grow all 84, audited',
}


def interval(values):
    vals = [float(v) for v in values]
    if len(vals) < 2 or not np.isfinite(vals).all():
        raise ValueError('at least two finite independent stream values required')
    mean, sd = statistics.mean(vals), statistics.stdev(vals)
    half = float(student_t.ppf(.975, len(vals)-1)) * sd / len(vals)**.5
    return dict(n=len(vals), mean=mean, lower=mean-half, upper=mean+half,
                standard_deviation=sd, values=vals)


def mean(rows, field):
    vals = [r['summary'][field] for r in rows]
    if any(v is None for v in vals):
        return None
    return statistics.mean(vals)


def load_runs(directory, *, freeze_path=None, replay_path=None):
    directory = Path(directory).resolve()
    manifest_path=directory/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    freeze_path=Path(freeze_path or directory.parent/'freeze.json')
    replay_path=Path(replay_path or directory.parent/'holdout-replay.json')
    frozen=json.loads(freeze_path.read_text())
    if hashlib.sha256(freeze_path.read_bytes()).hexdigest()!=manifest.get('freeze_sha256'):
        raise ValueError('holdout freeze digest mismatch')
    for field in ('seeds','methods','protocols','config','source_sha256'):
        if frozen.get(field)!=manifest.get(field):
            raise ValueError('manifest differs from actual freeze: '+field)
    for name,digest in frozen['source_sha256'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('frozen source drift: '+name)
    receipts=json.loads(replay_path.read_text())
    if type(receipts) is not list:
        raise ValueError('independent replay receipt list required')
    matching=[r for r in receipts if Path(r.get('directory','')).resolve()==directory]
    if len(matching)!=1 or matching[0].get('status')!='passed' or matching[0].get('failures'):
        raise ValueError('one passing independent replay of this directory is required')
    replay=matching[0]
    if replay.get('checked_freeze_sha256')!=manifest.get('freeze_sha256') or replay.get('checked_source_sha256')!=manifest['source_sha256']:
        raise ValueError('independent replay checked a different freeze/source map')
    if replay.get('manifest_sha256')!=hashlib.sha256(manifest_path.read_bytes()).hexdigest():
        raise ValueError('independent replay names a different manifest')
    if replay.get('replay_source_sha256')!=hashlib.sha256((ROOT/'experiments/audit_relational_v7.py').read_bytes()).hexdigest():
        raise ValueError('independent replay source changed')
    if (manifest['status'] != 'complete' or tuple(manifest['seeds']) != SEEDS
            or tuple(manifest['methods']) != METHODS
            or tuple(manifest['protocols']) != ('matched', 'budget')
            or not manifest['freeze_sha256']):
        raise ValueError('complete exact frozen holdout required; partial/development data rejected')
    runs, hashes = {}, {}
    for protocol in ('matched', 'budget'):
        for seed in SEEDS:
            for method in METHODS:
                filename = f'{protocol}-{seed}-{method}.json'
                payload = (directory/filename).read_bytes()
                record = json.loads(payload)
                if (record['status'] != 'complete' or record['error'] is not None
                        or record['test_episode_limit'] is not None
                        or record['seed'] != seed or record['method'] != method
                        or record['protocol'] != protocol or record['config'] != manifest['config']):
                    raise ValueError('failed or inconsistent run: ' + filename)
                if record['learner']['metrics']['updates'] != len(record['ordinary']):
                    raise ValueError('nonordinary update count: ' + filename)
                if protocol == 'matched' and len(record['ordinary']) != 224:
                    raise ValueError('incomplete matched stream: ' + filename)
                if protocol == 'budget' and record['summary']['total_select_executions'] > 4096:
                    raise ValueError('budget exceeded: ' + filename)
                if record['summary']['history_evictions']:
                    raise ValueError('full history unexpectedly evicted: ' + filename)
                for label, expected_reports, count in (
                        ('after_warm',range(4),16),('after_novel',range(4),16),('final',range(8),32)):
                    panel=record['evaluations'][label]
                    if protocol=='budget' and label!='final':
                        if panel: raise ValueError('budget run has unexpected retention panels')
                        continue
                    keys=[(r['report_index'],r['context_index']) for r in panel]
                    expected_keys=[(i,j) for i in expected_reports for j in range(count)]
                    if keys!=expected_keys:
                        raise ValueError('missing, duplicated or reordered evaluation panel: '+filename+'/'+label)
                    if any(r['report_id']!=record['reports'][r['report_index']]['public_id'] for r in panel):
                        raise ValueError('evaluation panel report identity mismatch')
                if protocol=='matched':
                    for before,after in zip(record['evaluations']['after_warm'],record['evaluations']['after_novel']):
                        if any(before[k]!=after[k] for k in ('report_id','context_index','context_seed')):
                            raise ValueError('retention panels are not the same context grid')
                runs[(protocol, seed, method)] = record
                hashes[filename] = hashlib.sha256(payload).hexdigest()
    if replay.get('raw_sha256')!=hashes:
        raise ValueError('raw evidence differs from independently replayed files')
    return manifest, runs, hashes


def analyze(directory, *, freeze_path=None, replay_path=None):
    manifest, runs, hashes = load_runs(directory, freeze_path=freeze_path, replay_path=replay_path)
    effects = []
    for protocol, field, control in [
        ('matched', 'shared_novel_first24_reward', 'audited_grow_no_reuse'),
        ('matched', 'shared_novel_first8_reward', 'audited_grow_no_reuse'),
        *[('budget', 'final_macro_reward', m) for m in CONTROLS],
        ('matched', 'shared_novel_first24_reward', 'audited_grow_full84'),
        ('matched', 'shared_novel_first24_reward', 'audited_full_history_sparse'),
        ('matched', 'shared_novel_first24_reward', 'ungated_full_history_sparse'),
    ]:
        effect = interval([runs[(protocol, seed, METHODS[0])]['summary'][field]
                           - runs[(protocol, seed, control)]['summary'][field] for seed in SEEDS])
        effects.append(dict(protocol=protocol, field=field, control=control, **effect))
    groups = []
    for protocol in ('matched', 'budget'):
        for method in METHODS:
            rows = [runs[(protocol, seed, method)] for seed in SEEDS]
            fields = ('shared_novel_first24_reward', 'shared_novel_first8_reward',
                      'unshared_novel_reward', 'warm_reward', 'retention_reward',
                      'ordinary_reward', 'final_macro_reward', 'ordinary_episodes',
                      'audit_pairs', 'started_audits', 'accepted_audits',
                      'total_select_executions', 'total_wall_seconds', 'total_cpu_seconds',
                      'training_criterion_seconds')
            vals = {field: mean(rows, field) for field in fields}
            vals.update({name: statistics.mean(r['costs']['total'][name] for r in rows)
                         for name in ('setup_seconds', 'measurement_seconds', 'gold_seconds',
                                      'prediction_seconds', 'row_feature_evaluations')})
            vals.update({name: statistics.mean(r['learner']['metrics'][name] for r in rows)
                         for name in ('update_seconds', 'fit_seconds', 'feature_evaluations',
                                      'peak_history_bytes', 'feature_cache_bytes',
                                      'fit_matrix_elements', 'fit_failures')})
            vals['criterion_row_feature_evaluations'] = statistics.mean(
                r['summary']['training_criterion_row_feature_evaluations'] for r in rows)
            vals['serialized_gate_bytes'] = statistics.mean(
                len(json.dumps(r['gate_snapshot'], separators=(',', ':')).encode())
                if r['gate_snapshot'] is not None else 0 for r in rows)
            vals['serialized_policy_registry_bytes'] = statistics.mean(
                len(json.dumps(r['policy_registry'], separators=(',', ':')).encode()) for r in rows)
            vals['serialized_bank_bytes'] = statistics.mean(
                len(json.dumps(r['learner']['bank'], separators=(',', ':')).encode()) for r in rows)
            vals['unreached_reports'] = statistics.mean(len(r['summary']['unreached_reports']) for r in rows)
            vals['exposures_by_report_index'] = [statistics.mean(
                r['summary']['per_report_exposures'][r['reports'][i]['public_id']] for r in rows) for i in range(8)]
            vals['final_reward_by_report_index'] = [statistics.mean(
                r['summary']['per_report_final_reward'][r['reports'][i]['public_id']] for r in rows) for i in range(8)]
            vals['retention_panel_changed_predictions'] = sum(
                a['prediction'] != b['prediction'] or a['installed_digest'] != b['installed_digest']
                for r in rows for a,b in zip(r['evaluations']['after_warm'],r['evaluations']['after_novel']))
            vals['bank_origin_feature_additions'] = sum(
                e['source'] == 'promoted_bank' for r in rows for e in r['learner']['feature_events'])
            vals['shared_report_truth_feature_coverage'] = statistics.mean(
                all(mono in r['learner']['reports'][report['public_id']].get(
                    'active_features', r['learner']['reports'][report['public_id']]['features'])
                    for mono,_ in report['spec'])
                for r in rows for report in r['reports'][4:6])
            vals['shared_report_feature_cap_rate'] = statistics.mean(
                len(r['learner']['reports'][report['public_id']].get(
                    'active_features',r['learner']['reports'][report['public_id']]['features']))==12
                for r in rows for report in r['reports'][4:6])
            groups.append(dict(protocol=protocol, method=method, means=vals))
    primary = effects[0]
    practical = [e for e in effects if e['protocol']=='budget']
    retention_changes = sum(g['means']['retention_panel_changed_predictions'] for g in groups)
    verdict = dict(
        primary_transfer_passed=primary['mean'] >= .05 and primary['lower'] > 0,
        practical_dominance_passed=all(e['mean'] >= .05 and e['lower'] > 0 for e in practical)
                                  and retention_changes == 0,
        retention_panel_changes=retention_changes,
        note='Mean gains and positive paired lower intervals are both required; fixed control set, no post-hoc comparator selection.')
    return dict(format_version=1, holdout_directory=str(Path(directory).resolve().relative_to(ROOT)),
                freeze_sha256=manifest['freeze_sha256'], source_sha256=manifest['source_sha256'],
                raw_sha256=hashes, seeds=list(SEEDS), effects=effects, groups=groups, verdict=verdict,
                grid_elapsed_seconds=(datetime.fromisoformat(manifest['finished_at_utc'])-datetime.fromisoformat(manifest['started_at_utc'])).total_seconds(),
                counts=dict(runs=len(runs), ordinary_episodes=sum(len(r['ordinary']) for r in runs.values()),
                            audit_pairs=sum(sum(len(a['pairs']) for a in r['audits']) for r in runs.values()),
                            evaluation_contexts=sum(sum(len(v) for v in r['evaluations'].values()) for r in runs.values()),
                            select_executions=sum(r['summary']['total_select_executions'] for r in runs.values()))), runs


def fmt(value, places=4):
    return f'{value:.{places}f}'


def markdown(data):
    effect = data['effects'][0]
    verdict = data['verdict']
    lines = ['# Version 7 results', '',
             'All numbers below use the frozen 16-stream evaluation; development is separate.', '',
             f"The primary reuse difference is **{effect['mean']:+.5f}** reward, with a paired 95 percent interval "
             f"**[{effect['lower']:.5f}, {effect['upper']:.5f}]**. "
             f"The predeclared transfer target is **{'met' if verdict['primary_transfer_passed'] else 'not met'}**.", '',
             f"The requirement to beat every fixed simple control at the 4096-SELECT budget is "
             f"**{'met' if verdict['practical_dominance_passed'] else 'not met'}**. "
             'A query ceiling is not equal wall time or equal all-resource computation.', '']
    for protocol in ('matched','budget'):
        lines += [f'## {protocol.capitalize()} protocol', '',
                  '| Method | Shared first24 | Ordinary reward | Final macro | Ordinary examples | Audit pairs | SELECTs | Run sec |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|']
        for group in data['groups']:
            if group['protocol'] != protocol: continue
            m=group['means']; shared='unknown' if m['shared_novel_first24_reward'] is None else fmt(m['shared_novel_first24_reward'])
            lines.append(f"| {LABELS[group['method']]} | {shared} | {m['ordinary_reward']:.4f} | {m['final_macro_reward']:.4f} | "
                         f"{m['ordinary_episodes']:.1f} | {m['audit_pairs']:.1f} | {m['total_select_executions']:.1f} | {m['total_wall_seconds']:.3f} |")
        lines.append('')
    lines += ['## Prespecified paired effects', '', '| Protocol / outcome | Reuse minus control | Mean | 95 percent interval |',
              '|---|---|---:|---:|']
    for effect in data['effects']:
        lines.append(f"| {effect['protocol']} / {effect['field']} | {LABELS[effect['control']]} | {effect['mean']:+.5f} | [{effect['lower']:.5f}, {effect['upper']:.5f}] |")
    lines += ['', '## Actual cost and reach', '',
              'The following companion costs average complete arm/runs. SQL setup is outside the named SELECT budget but its time is included in measured run time. '
              'Run timers exclude harness construction and final JSON export; whole-grid elapsed time is reported separately. Feature work includes prediction and training-screening work separately in analysis.json; fitting uses cached past features. '
              'Numeric and serialized storage below omit Python object overhead and do not measure peak process RAM.', '',
              '| Method | Setup sec | Fit/update sec | Peak history+cache KiB | Serialized gate KiB | Policy registry KiB | Unreached reports | Exposures R0..R7 |',
              '|---|---:|---:|---:|---:|---:|---:|---|']
    for group in data['groups']:
        if group['protocol'] != 'budget': continue
        m=group['means']
        lines.append(f"| {LABELS[group['method']]} | {m['setup_seconds']:.3f} | {m['fit_seconds']:.3f}/{m['update_seconds']:.3f} | "
                     f"{m['peak_history_bytes']/1024:.1f} | {m['serialized_gate_bytes']/1024:.1f} | {m['serialized_policy_registry_bytes']/1024:.1f} | "
                     f"{m['unreached_reports']:.2f} | {', '.join(f'{x:.1f}' for x in m['exposures_by_report_index'])} |")
    mechanism=next(g['means'] for g in data['groups']
                   if g['protocol']=='matched' and g['method']=='audited_grow_reuse')
    lines += ['', '## Evaluator-only feature diagnostic', '',
              f"At the end of matched training, {mechanism['shared_report_truth_feature_coverage']:.1%} of shared novel reports "
              f"have all their true monomials in the reuse learner's selected feature set; "
              f"{mechanism['shared_report_feature_cap_rate']:.1%} reach the twelve-feature cap. "
              'This descriptive diagnostic compares saved features with hidden evaluator recipes after execution; '
              'it never supplies a learner with those recipes. Feature membership alone is not a correctness certificate. '
              'Irreversible early feature choices can use up the growth allowance before useful components are selected.', '']
    counts=data['counts']
    lines += ['', f"The holdout contains {counts['runs']} arm/runs, {counts['ordinary_episodes']:,} ordinary episodes, "
              f"{counts['audit_pairs']:,} paired audits and {counts['evaluation_contexts']:,} panel contexts "
              f"({counts['select_executions']:,} post-setup SELECT executions). Whole-grid elapsed time, including artifact export, is {data['grid_elapsed_seconds']/60:.2f} minutes.", '',
              f"Matched old-report panels changed {verdict['retention_panel_changes']} policy/prediction entries during novel learning. "
              'This is structural retention under authentic fixed report dispatch, not learned routing or a pointwise statistical guarantee.', '',
              'Intervals use independent seed-level differences. Only the declared first24 comparison is primary; all secondary estimates and rankings are retained. '
              'The practical decision requires dominance of the entire fixed three-control set. A point estimate above .05 plus a lower bound above zero supports positive gain, not a 95 percent guarantee that the gain exceeds .05. '
              'Partial or failed runs are rejected by the analysis instead of silently averaged.', '',
              'The supplied 84-feature grammar, exact scalar supervision, complete-table measurements and stationary authentic scopes remain strong assumptions. '
              'These results do not establish native CL-Bench/AgentCL superiority, open-ended representation discovery, unrestricted no-forgetting or alignment.', '']
    return '\n'.join(lines)


def paper(data):
    groups={(g['protocol'],g['method']):g['means'] for g in data['groups']}
    e=data['effects'][0]; practical=[v for v in data['effects'] if v['protocol']=='budget']
    lines=[r'\begin{table*}[t]',r'\centering\small',
           r'\caption{Frozen 16-stream evaluation. All values are means across streams. Shared is prequential reward on the first 24 examples of two shared novel reports. Final is the eight-report macro mean on fresh feedback-free panels. Matched arms each receive 224 ordinary examples; companion arms spend at most 4,096 post-setup SELECTs, including final evaluation. Run time covers fitting, screening, queries and setup; construction and final artifact export are outside that timer. Timing is descriptive on this machine.}',
           r'\label{tab:v7results}',r'\begin{tabular}{llrrrrrr}',r'\toprule',
           r'Protocol & Method & Shared & Final & Ordinary $n$ & Audit pairs & SELECTs & Run s \\',r'\midrule']
    for protocol in ('matched','budget'):
        for i,method in enumerate(METHODS):
            m=groups[protocol,method]
            shared='--' if m['shared_novel_first24_reward'] is None else fmt(m['shared_novel_first24_reward'],3)
            lines.append(f"{protocol.title() if i==0 else ''} & {LABELS[method]} & {shared} & {m['final_macro_reward']:.3f} & "
                         f"{m['ordinary_episodes']:.1f} & {m['audit_pairs']:.1f} & {m['total_select_executions']:.1f} & {m['total_wall_seconds']:.2f}"+r' \\')
        if protocol=='matched': lines.append(r'\midrule')
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table*}', '',
              f"The primary difference between audited reuse and no reuse is {e['mean']:+.5f} "
              f"reward (95\\% paired interval $[{e['lower']:.5f},{e['upper']:.5f}]$). "
              f"The predeclared five-point transfer target is {'met' if data['verdict']['primary_transfer_passed'] else 'not met'}. "
              'This comparison isolates a bounded search-order mechanism, not general representation learning.', '']
    for effect in practical:
        lines.append(f"At the common SELECT ceiling, reuse minus {LABELS[effect['control']].lower()} is "
                     f"{effect['mean']:+.5f} (95\\% interval $[{effect['lower']:.5f},{effect['upper']:.5f}]$).")
    lines += [f"The conjunction required for practical dominance is {'satisfied' if data['verdict']['practical_dominance_passed'] else 'not satisfied'}. "
              'All fixed comparisons are reported; the best observed control is not selected as a new hypothesis.', '',
              r'\begin{figure*}[t]',r'\centering',r'\includegraphics[width=.93\textwidth]{figures/v7_effects.pdf}',
              r'\caption{Seed-level paired differences (open points), their means and nominal 95\% Student intervals. The top row uses matched shared-novel prequential reward; the remaining rows use the equal-SELECT companion final-panel reward. Zero and the predeclared .05 target are shown. Contexts within a stream are not statistical replicates.}',r'\label{fig:v7effects}',r'\end{figure*}', '',
              f"Matched old-report panels show {data['verdict']['retention_panel_changes']} changed policy/prediction entries "
              'during novel learning. Those execution paths are unchanged by construction under fixed public dispatch. '
              'This supports the implementation invariant, not inferred task identity or arbitrary-distribution retention.', '']
    mechanism=groups['matched','audited_grow_reuse']
    lines += [f"An evaluator-only diagnostic finds all true component monomials in the final selected features "
              f"for {100*mechanism['shared_report_truth_feature_coverage']:.1f}\\% of shared novel reports, while "
              f"{100*mechanism['shared_report_feature_cap_rate']:.1f}\\% reach the twelve-feature cap. "
              'These hidden recipes are examined only after execution. Irreversible early feature additions can exhaust '
              'the cap with spurious choices; larger candidate search alone need not repair that failure. '
              'This is a diagnostic inference from the saved feature sets, not an additional confirmatory hypothesis.', '']
    c=data['counts']
    lines += [f"The holdout records {c['ordinary_episodes']:,} ordinary episodes, {c['audit_pairs']:,} audit pairs "
              f"and {c['evaluation_contexts']:,} panel contexts, totaling {c['select_executions']:,} post-setup SELECTs. "
              'Raw policy versions, observations, context seeds, gate journals and all failures are retained. '
              'The source/configuration freeze precedes these streams; four development streams remain separate.', '',
              r'\input{v7_validation.tex}', '']
    abstract = ('We study whether online feature reuse can justify its statistical admission cost without enumerating hidden worlds. '
                'Small numerical learners receive their own post-prediction scalar feedback from actual read-only SQLite queries; '
                'promoted feature syntax guides later search inside a supplied 84-monomial grammar. Frozen candidate policies '
                'face fresh paired betting tests with summable error spending. '
                f"On sixteen frozen streams, reuse changes shared-novel reward by {e['mean']:+.4f} relative to no reuse "
                f"(95\\% paired interval $[{e['lower']:.4f},{e['upper']:.4f}]$). "
                f"Its preregistered transfer target is {'met' if data['verdict']['primary_transfer_passed'] else 'not met'}, and "
                f"dominance over all three simple controls at 4,096 SELECTs is {'established at this scale' if data['verdict']['practical_dominance_passed'] else 'not established'}. "
                'Lean 4.19.0 checks 77 accumulated statements, including deterministic finite-population accounting for erroneous promotions; '
                'the statistical validity argument is not formalized. A positive-mean counterexample proves that the fixed large bet can have '
                'poor admission probability even with unlimited samples. Given report routing and unchanged old policies supply structural '
                'retention. The study tests feature-search reuse and its opportunity cost, not native LLM benchmark superiority, '
                'open-ended abstraction, universal no-forgetting or alignment.\n')
    return '\n'.join(lines), abstract


def plot(data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    effects = [data['effects'][0]] + [e for e in data['effects'] if e['protocol']=='budget']
    labels = ['Shared: reuse minus no reuse','Final: reuse minus audited sparse',
              'Final: reuse minus ungated sparse','Final: reuse minus ridge']
    fig,ax=plt.subplots(figsize=(9.5,3.2),layout='constrained')
    colors=['#245d87','#965927','#965927','#965927']
    for i,(effect,color) in enumerate(zip(effects,colors)):
        y=3-i
        jitter=np.linspace(-.12,.12,len(effect['values']))
        ax.scatter(effect['values'], y+jitter, s=22, facecolors='none', edgecolors=color,alpha=.65)
        ax.errorbar(effect['mean'],y,xerr=[[effect['mean']-effect['lower']],[effect['upper']-effect['mean']]],
                    fmt='o',color=color,capsize=4,lw=2)
    ax.axvline(0,color='#444444',lw=1)
    ax.axvline(.05,color='#888888',lw=1,ls='--')
    ax.set_yticks(range(4),labels[::-1]);ax.set_xlabel('Paired reward difference across independent streams')
    ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
    ax.spines[['top','right']].set_visible(False)
    (ROOT/'paper/figures').mkdir(exist_ok=True)
    fig.savefig(ROOT/'paper/figures/v7_effects.pdf')
    fig.savefig(ROOT/'paper/figures/v7_effects.png',dpi=180)
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--holdout',type=Path,default=ROOT/'artifacts/v7/holdout')
    parser.add_argument('--out',type=Path,default=ROOT/'artifacts/v7')
    parser.add_argument('--freeze',type=Path)
    parser.add_argument('--replay',type=Path)
    args=parser.parse_args()
    data,_=analyze(args.holdout,freeze_path=args.freeze,replay_path=args.replay)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'analysis.json').write_text(json.dumps(data,indent=2)+'\n')
    (ROOT/'docs/v7/RESULTS.md').write_text(markdown(data))
    result,abstract=paper(data)
    (ROOT/'paper/v7_results.tex').write_text(result)
    (ROOT/'paper/v7_abstract.tex').write_text(abstract)
    plot(data)
    print(json.dumps(dict(verdict=data['verdict'],effects=data['effects'][:5],counts=data['counts']),indent=2))

if __name__=='__main__': main()
