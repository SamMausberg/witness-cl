"""Generate paper numbers from executed artifacts, never from manually typed results."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
rows=json.loads((ROOT/'artifacts/synthetic/summary.json').read_text())['rows']
by={(r['mode'],r['method']):r for r in rows}
names={'interleaved':'Stationary interleaving','novel_inputs':'Previously unseen inputs',
       'public_shift':'Public version change','hidden_shift':'Hidden rule change',
       'misspecified':'Misspecified class'}
lines=[r'\begin{tabular}{lrrrrrr}',r'\toprule',
 r'& \multicolumn{3}{c}{Overall reward (\%)} & \multicolumn{2}{c}{Late-half reward (\%)} & \\',
 r'\cmidrule(lr){2-4}\cmidrule(lr){5-6}',
 r'Scenario & Window & Lookup & Witness / full replay & Witness & Lookup & Wrong certs. \\',r'\midrule']
for mode,label in names.items():
 w=by[mode,'witness'];b=by[mode,'lookup_full'];c=by[mode,'window_replay_24'];ci=w['reward_ci95_seed_bootstrap']
 lines.append(f"{label} & {100*c['reward']:.2f} & {100*b['reward']:.2f} & {100*w['reward']:.2f} [{100*ci[0]:.2f}, {100*ci[1]:.2f}] & {100*w['late_reward']:.2f} & {100*b['late_reward']:.2f} & {w['wrong_certificates']:.1f} "+r'\\')
lines.extend([r'\bottomrule',r'\end{tabular}'])
(ROOT/'paper/results_table.tex').write_text('\n'.join(lines)+'\n')
audit=json.loads((ROOT/'artifacts/audit_power.json').read_text())['rows']
a=[r'\begin{tabular}{rrrr}',r'\toprule',r'True gain & By 128 & By 512 & By 2,048 \\',r'\midrule']
for r in audit:
 a.append(f"{100*r['true_mean_difference']:+.0f} pp & {100*r['pass_by_128']:.2f}\\% & {100*r['pass_by_512']:.2f}\\% & {100*r['pass_by_2048']:.2f}\\% "+r'\\')
a.extend([r'\bottomrule',r'\end{tabular}']);(ROOT/'paper/audit_table.tex').write_text('\n'.join(a)+'\n')
w=by['interleaved','witness'];b=by['interleaved','full_replay_induction']
macros={"WitnessCount":f"{w['active_witnesses']:.1f}","WitnessOps":f"{w['hypothesis_evaluations']:,.1f}",
        "ReplayOps":f"{b['hypothesis_evaluations']:,.1f}","OpRatio":f"{b['hypothesis_evaluations']/w['hypothesis_evaluations']:.2f}",
        "WitnessRatio":f"{384/w['active_witnesses']:.2f}"}
(ROOT/'paper/numbers.tex').write_text('\n'.join('\\newcommand{\\'+k+'}{'+v+'}' for k,v in macros.items())+'\n')
print('Paper tables generated from stored execution artifacts.')
