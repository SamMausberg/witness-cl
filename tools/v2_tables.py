from pathlib import Path
import json,statistics as st
ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts/v2';PAPER=ROOT/'paper'

def table(name,header,rows,fmt):
    text=['\\begin{tabular}{'+fmt+'}',r'\toprule',header+r' \\',r'\midrule']
    text.extend(' & '.join(str(v) for v in row)+r' \\' for row in rows)
    text.extend([r'\bottomrule',r'\end{tabular}'])
    (PAPER/name).write_text('\n'.join(text)+'\n')

ar=json.loads((ART/'arithmetic.json').read_text())
rows=[]
labels={'stationary':'Stationary','novel_inputs':'Unseen inputs','hidden_shift':'Hidden change','misspecified':'Class misspec.','recurring':'Recurring','rapid_switch':'Rapid switching','noisy_feedback':'Noisy feedback'}
for mode,label in labels.items():
    vals=[]
    for method in ['v1_original','v2_reset_only','v2_recurring']:
        row=next(r for r in ar if r['mode']==mode and r['method']==method)
        vals.append(f"{100*row['late_reward']:.2f}")
    rows.append([label,*vals])
table('v2_arithmetic.tex','Scenario & v0.1 & Reset & Reuse',rows,'lrrr')

rs=json.loads((ART/'relational.json').read_text());rows=[]
for mode,label in [('stationary_net','Stationary net'),('recurring_recipes','Recurring recipes'),('out_of_grammar','Unsupported op.')]:
    vals=[]
    for method in ['full_grammar_replay','adaptive_reset_only','adaptive_recurring']:
        r=next(r for r in rs if r['mode']==mode and r['method']==method)
        vals.append(f"{100*r['late_reward']:.2f}")
    rows.append([label,*vals])
table('v2_relational.tex','Scenario & Replay & Reset & Reuse',rows,'lrrr')

inte=json.loads((ART/'integrated.json').read_text())['summary'];rows=[]
for r in inte:
    rows.append([r['mode'].title(),'Audited' if r['method']=='audited_live' else 'Ungated',f"{100*r['reward']:.2f}",f"{100*r['late_reward']:.2f}"])
table('v2_integrated.tex','Scenario & Method & Overall & Late',rows,'llrr')

rs=json.loads((ART/'cube_bench.json').read_text());rows=[]
for r in rs:rows.append([r['rows'],f"{r['naive_median_ms']:.3f}",f"{r['cube_median_ms']:.3f}",f"{r['reference_speed_ratio']:.2f}"])
table('v2_kernel.tex','Rows & Direct (ms) & Cube (ms) & Ratio',rows,'rrrr')

rs=json.loads((ART/'training.json').read_text());rows=[]
for rank in [0,4,12,24]:
    subset=[r for r in rs if r['rank']==rank]
    def avg(k):return st.mean(r[k] for r in subset)
    rows.append([rank,f"{avg('protected_mse'):.3f}",f"{avg('irreducible_population_mse'):.3f}",f"{avg('protected_max_drift'):.1e}"])
table('v2_training.tex','Rank & New MSE & Optimum & Drift',rows,'rrrr')

rs=json.loads((ART/'audit_power.json').read_text());rows=[]
for case,label in [('diffuse_gain','Diffuse +.05'),('sparse_local_gain','Local +.05'),('sparse_null','Local null')]:
    for n in [128,512,2048]:
        r=next(r for r in rs if r['case']==case and r['horizon']==n)
        rows.append([label,n,f"{100*r['admission_rate']:.2f}",f"{r['dense_mean_extra_rollouts']:.1f}",f"{r['screened_mean_extra_rollouts']:.1f}"])
table('v2_audit.tex','Case & Cap & Pass (\\%) & Dense & Local',rows,'lrrrr')
print('Six v0.2 tables regenerated from recorded data.')
