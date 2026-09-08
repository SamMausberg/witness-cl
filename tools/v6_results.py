"""Derive v6 tables and a static scientific figure from preserved raw summaries."""
from pathlib import Path
import hashlib
import json
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import t

ROOT=Path(__file__).resolve().parents[1]


def main():
    hold=ROOT/'artifacts/v6/holdout/summary.json'
    result=json.loads(hold.read_text())
    dev=json.loads((ROOT/'artifacts/v6/development-corrected/summary.json').read_text())
    stats={r['method']:r for r in result['aggregates']}
    a=stats['depth_two_B16']; b=stats['informative_zero_loss_B16']
    c=result['paired'][0]
    tables=lambda x:{tuple(map(tuple,r['table'])) for r in x['worlds_evaluator_only']}
    h,d=tables(result),tables(dev)
    derived=dict(holdout_source_sha256=hashlib.sha256(hold.read_bytes()).hexdigest(),
        primary=c,planning_ratio=a['planning_seconds']/b['planning_seconds'],
        total_learner_ratio=(a['planning_seconds']+a['update_seconds']+a['construction_seconds'])/(b['planning_seconds']+b['update_seconds']+b['construction_seconds']),
        holdout_unique_tables=len(h),development_unique_tables=len(d),overlap_unique_tables=len(h & d),
        holdout_streams_matching_development=sum(tuple(map(tuple,r['table'])) in d for r in result['worlds_evaluator_only']))
    (ROOT/'artifacts/v6/results-derived.json').write_text(json.dumps(derived,indent=2)+'\n')
    names={'depth_two_B16':'Depth two','informative_zero_loss_B16':'Free info.','optimistic_B16':'Bounded opt.',
           'v4_frozen_ranker_B16':'V4 frozen','full_history_optimistic':'Full history'}
    lines=[r'\begin{table}[t]',r'\centering\small\setlength{\tabcolsep}{4.5pt}',r'\begin{tabular}{lrrrr}',r'\toprule',
           r'Method & Return & Plan s & Unknown & Max debt\\',r'\midrule']
    for name,r in stats.items():
        unknown=f"{100*r['unknown_decisions']/24:.1f}\\%" if name in list(stats)[:3] else r'---'
        lines.append(f"{names[name]} & {r['mean_return']:.3f} & {r['planning_seconds']:.3f} & {unknown} & {r['max_worst_prefix_deficit']:.0f}\\\\")
    lines += [r'\bottomrule',r'\end{tabular}',r'\caption{Frozen v6 holdout: mean episode return, total planning seconds per 24-episode stream, and maximum completed-prefix anchor deficit. Only the first three arms share line metering and the one-second ceiling. Full-history optimism has no risk ledger. All ranker weights stay frozen. Timing includes measurement overhead.}',r'\label{tab:v6}',r'\end{table}']
    lo,hi=c['ci95_paired_t']
    lines += [f"The primary mean difference is ${c['mean_difference']:+.5f}$ reward per episode, with paired 95\\% Student interval $[{lo:+.5f},{hi:+.5f}]$ over 40 independent streams. The depth-two selector uses {derived['planning_ratio']:.2f}$\\times$ the cheap control's measured planning time. The holdout contains {len(h)} distinct tables; {derived['holdout_streams_matching_development']} streams match a development table ({len(h & d)} distinct overlapping tables). This is same-family validation, not new-domain generalization."]
    lines += [r'\begin{figure}[t]',r'\centering',r'\includegraphics[width=\columnwidth]{figures/v6_reward_cost.pdf}',
              r'\caption{Reward and measured planning cost for the three commonly metered v6 arms. Reward intervals are marginal 95\% Student intervals across streams; the primary analysis uses paired differences. Common ceilings do not imply equal realized computation.}',r'\label{fig:v6cost}',r'\end{figure}']
    (ROOT/'paper/v6_results.tex').write_text('\n'.join(lines)+'\n')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    fig,axes=plt.subplots(1,2,figsize=(6.5,2.45),layout='constrained')
    methods=list(stats)[:3];labels=['Depth two','Free info.','Optimism'];colors=['#275e83','#1c8565','#be6c28']
    means=[];errors=[]
    for method in methods:
        values=[r['mean_return'] for r in result['per_seed'] if r['method']==method]
        means.append(statistics.mean(values));errors.append(float(t.ppf(.975,len(values)-1))*statistics.stdev(values)/len(values)**.5)
    axes[0].bar(labels,means,yerr=errors,capsize=3,color=colors,width=.65)
    axes[0].set(ylabel='Mean reward / episode',ylim=(0,6),title='All exploration costs included')
    axes[1].bar(labels,[stats[m]['planning_seconds'] for m in methods],color=colors,width=.65)
    axes[1].set(ylabel='Planning seconds / stream',title='Measured cost, common caps')
    for ax in axes:ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.savefig(ROOT/'paper/figures/v6_reward_cost.pdf');fig.savefig(ROOT/'paper/figures/v6_reward_cost.png',dpi=180)
    print(json.dumps(derived,indent=2))


if __name__=='__main__':main()
