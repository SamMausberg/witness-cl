"""Regenerate v5 paper tables and scientific plots from immutable episode data."""
from pathlib import Path
import csv
import gzip
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'artifacts/v5/experiment/holdout'
PAPER = ROOT / 'paper'
NAMES = {'v4_B16': 'Witness v4, B16', 'v5_decision_B16': 'Regret probes, B16',
         'v5_decision_untrained_B16': 'Regret probes, no training',
         'full_history_optimistic': 'Full-history planner'}


def main():
    summary = json.loads((BASE / 'summary.json').read_text())
    lines = [r'\begin{tabular}{lrrrr}', r'\toprule',
             r'System & Mean return & Late A & Max. deficit & Seconds/stream \\', r'\midrule']
    for row in summary['aggregates']:
        lines.append(f"{NAMES[row['method']]} & {row['mean_return']:.4f} & {row['late_A']:.4f} & "
                     f"{row['max_worst_prefix_deficit']} & {row['seconds']:.4f}" + r' \\')
    lines += [r'\bottomrule', r'\end{tabular}']
    (PAPER / 'v5_results.tex').write_text('\n'.join(lines) + '\n')
    with gzip.open(BASE / 'episodes.csv.gz', 'rt') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == summary['episode_rows']
    methods = ['v4_B16', 'v5_decision_B16', 'full_history_optimistic']
    seeds = sorted({int(r['seed']) for r in rows})
    episodes = summary['episodes']
    arrays = {m: np.zeros((len(seeds), episodes)) for m in methods}
    seen = set()
    for row in rows:
        key = (int(row['seed']), row['method'], int(row['episode']))
        assert key not in seen; seen.add(key)
        if row['method'] in methods:
            arrays[row['method']][seeds.index(int(row['seed'])), int(row['episode'])] = int(row['reward'])
    for row in summary['aggregates']:
        vals = [int(r['reward']) for r in rows if r['method'] == row['method']]
        assert abs(np.mean(vals) - row['mean_return']) < 1e-12
    figure_dir = PAPER / 'figures'; figure_dir.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False,
                         'pdf.fonttype': 42, 'ps.fonttype': 42})
    fig, axes = plt.subplots(1, 2, figsize=(7.05, 2.65), constrained_layout=True)
    colors = ['#323232', '#ad3939', '#377292']
    with (ROOT / 'artifacts/v5/learning_curve.csv').open('w') as f:
        writer = csv.writer(f, lineterminator='\n');writer.writerow(['episode', *methods])
        means = {m: np.cumsum(a, axis=1).mean(axis=0) / np.arange(1, episodes + 1) for m,a in arrays.items()}
        for t in range(episodes): writer.writerow([t+1, *[means[m][t] for m in methods]])
    for m,c in zip(methods,colors):
        axes[0].plot(np.arange(1,episodes+1), means[m], label=NAMES[m], color=c, linewidth=1.6)
    axes[0].axvline(16.5,color='#cccccc',linewidth=.7); axes[0].axvline(32.5,color='#cccccc',linewidth=.7)
    axes[0].set(xlabel='Completed episodes (A / B / A)', ylabel='Cumulative mean return')
    axes[0].legend(frameon=False, fontsize=7, loc='lower right')
    delta = arrays['v5_decision_B16'].mean(axis=1) - arrays['v4_B16'].mean(axis=1)
    order = np.argsort(delta, kind='stable')
    axes[1].scatter(np.arange(1,len(seeds)+1),delta[order],s=12,color=colors[1])
    axes[1].axhline(0,color='#777777',linewidth=.7)
    axes[1].set(xlabel='Independent seeds, sorted by difference',ylabel='Mean reward difference: v5 minus v4')
    fig.savefig(figure_dir/'v5_learning.pdf');fig.savefig(figure_dir/'v5_learning.png',dpi=180);plt.close(fig)
    with (ROOT/'artifacts/v5/paired_differences.csv').open('w') as f:
        writer=csv.writer(f, lineterminator='\n');writer.writerow(['seed','v5_minus_v4_mean_reward'])
        writer.writerows(zip(seeds,delta))
    print('v5 tables/plot regenerated; raw episode counts and aggregate means validated.')

if __name__ == '__main__': main()
