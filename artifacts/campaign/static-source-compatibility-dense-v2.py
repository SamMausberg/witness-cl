"""Static saved-source diagnostics. No model call, learner run, or policy change."""
from pathlib import Path
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import sys
ROOT = Path.cwd()
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
import sqlglot
from sqlglot import exp
from witness_cl.campaign_io import read, save, sha, canonical
from witness_cl.campaign_env import make_episode
from witness_cl.delayed_memory import CompatibilityScope, normalized_template, reconstruct_bound
from witness_cl.query_memory import digest
from witness_cl.source_views import lift_source
from witness_cl.relational_program import compile_program
from tools.audit_campaign_mechanism import scalar, correct, resolve_measure_lineage, _AuditView
from experiments.audit_sql_abstractions_v9 import SQLiteReplayV9

OUT = ROOT / 'artifacts/campaign/dense-v2/qualification-reuse'
frozen, summary, audited = [read(OUT / name) for name in ('freeze.json', 'summary.json', 'audit.json')]
assert summary['complete'] and audited['complete'] and audited['consistent'] and summary['qualified']
assert audited['freeze_sha256'] == sha(OUT / 'freeze.json')
assert audited['summary_sha256'] == sha(OUT / 'summary.json')

def template_payload(view):
    value = {'sql': view.sql, 'binding_types': {k: type(v).__name__ for k,v in sorted(view.params.items())},
             'columns': view.columns, 'lineage': view.lineage, 'column_origins': view.column_origins,
             'measure_columns': view.measure_columns, 'reconstruction_sql': view.reconstruction_sql,
             'outer_bindings': {k:v for k,v in view.reconstruction_params.items() if k not in view.params}}
    assert digest(value) == normalized_template(view)
    return value

def inner_join_canonical(text):
    tree = sqlglot.parse_one(text, read='sqlite')
    for join in tree.find_all(exp.Join):
        if join.args.get('kind') == 'INNER' and not join.args.get('side') and not join.args.get('method'):
            join.set('kind', None)
    return tree.sql(dialect='sqlite')

def inner_join_only_payload(view):
    result = deepcopy(template_payload(view))
    for key in ('sql', 'reconstruction_sql'):
        result[key] = inner_join_canonical(result[key])
    return result

def features(view):
    source = sqlglot.parse_one(view.source_sql, read='sqlite')
    outer = sqlglot.parse_one(view.reconstruction_sql, read='sqlite').expressions[0]
    return {
        'source_table_aliases': sorted(node.name for node in source.find_all(exp.TableAlias)),
        'source_ctes': sum(1 for _ in source.find_all(exp.CTE)),
        'source_subqueries': sum(1 for _ in source.find_all(exp.Subquery)),
        'source_joins': sum(1 for _ in source.find_all(exp.Join)),
        'source_cases': sum(1 for _ in source.find_all(exp.Case)),
        'outer_coalesces': sum(1 for _ in outer.find_all(exp.Coalesce)),
        'outer_sums': sum(1 for _ in outer.find_all(exp.Sum)),
        'outer_divisions': sum(1 for _ in outer.find_all(exp.Div)),
        'measure_lineage': dict(view.lineage),
        'bindings': dict(view.params),
    }

def spec_for(record):
    return make_episode(record['seed'], frozen['split'], record['condition'], record['phase'],
                        record['index'], old_replicates=frozen['old_replicates'])

def query(record, sql, params):
    replay = SQLiteReplayV9(spec_for(record))
    try:
        output = replay.query(sql, params)
    finally:
        replay.close()
    return {'sql': sql, 'params': params, 'result': output, 'scalar': scalar(output)}

def check_source(record, view, bindings):
    checked = query(record, *reconstruct_bound(view, bindings))
    emptied = query(record, *reconstruct_bound(view, bindings, empty=True))
    answer = record['trace']['answer']
    matches = checked['scalar']['status'] == 'numeric' and correct(checked['scalar']['value'], answer)
    dependent = emptied['scalar']['status'] == 'null' or (
        emptied['scalar']['status'] == 'numeric' and not correct(emptied['scalar']['value'], answer))
    return {'reconstruction': checked, 'empty_relation': emptied,
            'matches_independently_recorded_current_answer': matches,
            'empty_relation_changes_answer': dependent,
            'two_checks_fit_original_remaining_select_allowance': 8 - record['trace']['select_attempts'] >= 2}

def compose_mean(view, bindings):
    """Reference-authored outer operation only; source relation stays unchanged."""
    outer = sqlglot.parse_one(view.reconstruction_sql, read='sqlite').expressions[0]
    aggregates = []
    binary = {exp.Add: 'add', exp.Sub: 'sub', exp.Mul: 'mul', exp.Div: 'div', exp.Mod: 'mod'}
    def convert(node):
        if isinstance(node, (exp.Alias, exp.Paren)):
            return convert(node.this)
        if isinstance(node, exp.Sum):
            if not isinstance(node.this, exp.Column) or node.this.name not in view.columns:
                raise ValueError('unsupported reconstructed SUM argument')
            name = 'aggregate_' + str(len(aggregates))
            aggregates.append({'name': name, 'op': 'avg', 'expr': {'op': 'col', 'name': node.this.name}})
            return {'op': 'col', 'name': name}
        if isinstance(node, exp.Coalesce):
            return {'op': 'coalesce', 'args': [convert(node.this)] + [convert(x) for x in node.expressions]}
        if isinstance(node, exp.Literal):
            value = node.this if node.is_string else float(node.this) if any(c in node.this.lower() for c in '.e') else int(node.this)
            return {'op': 'lit', 'value': value}
        if isinstance(node, exp.Null):
            return {'op': 'lit', 'value': None}
        if isinstance(node, exp.Placeholder):
            return {'op': 'lit', 'value': view.reconstruction_params[node.name]}
        if type(node) in binary:
            return {'op': binary[type(node)], 'left': convert(node.this), 'right': convert(node.expression)}
        raise ValueError('unsupported outer expression: ' + node.key)
    answer = convert(outer)
    if not aggregates:
        raise ValueError('no source SUM to replace by AVG')
    return {'op': 'project', 'input': {'op': 'group',
        'input': {'op': 'scan', 'view': view.key, 'bindings': bindings},
        'keys': [], 'aggregates': aggregates},
        'columns': [{'name': 'answer', 'expr': {'op': 'coalesce',
            'args': [answer, {'op': 'lit', 'value': 0}]}}]}

result = {
    'kind': 'static_cold_source_compatibility_diagnostic',
    'created_utc': datetime.now(timezone.utc).isoformat(),
    'study': str(OUT.relative_to(ROOT)),
    'study_sha256': {name: sha(OUT/name) for name in ('freeze.json', 'summary.json', 'audit.json')},
    'scope': 'Saved full-history cold outputs are static source fixtures. All relations, rebinding checks and outer programs in this report are offline diagnostic constructions, never actual admissions, corroborations or model-executed COMPOSE events.',
    'pairing': 'The evaluator ordinary index identifies eight fixed t to t+8 source pairs and later t+16/final probes. This scheduling metadata is used only by this diagnostic, never by the live learner.',
    'model_calls': 0, 'actual_stateful_mechanism_events': 0,
    'source_modules_sha256': {}, 'records': [], 'planned_pairs': [], 'fresh_row_probes': [],
}
for relative in ('src/witness_cl/delayed_memory.py','src/witness_cl/source_views.py',
                 'src/witness_cl/relational_program.py','src/witness_cl/campaign_env.py',
                 'tools/audit_campaign_mechanism.py'):
    assert sha(ROOT/relative) == frozen['source_sha256'][relative]
    result['source_modules_sha256'][relative] = sha(ROOT/relative)
saved = {}
templates = defaultdict(list)
for seed in frozen['seeds']:
    for phase, indices in (('ordinary', range(24)), ('final', range(8))):
        for index in indices:
            path = OUT/'episodes'/f'{seed}-reuse-{phase}-{index:03d}-full_history.json'
            record = read(path); trace = record['trace']
            assert not trace['learn'] and trace['before_memory_digest'] == trace['after_memory_digest']
            terminal = trace['queries'][trace['answer_query_index']]
            report = {'key': record['key'], 'record_sha256': sha(path), 'seed': seed, 'phase': phase,
                      'index': index, 'correct': trace['reward'] == 1,
                      'original_model_calls': len(trace['model_calls']), 'original_selects': trace['select_attempts'],
                      'source_sql': terminal['sql'], 'source_params': terminal['params']}
            try:
                view = lift_source(terminal['sql'], terminal['params'], trace['schema'], trace['question'])
                compile_program({'op':'scan','view':view.key},[view])
                scope = CompatibilityScope.from_observation(trace['schema'],trace['queries'][0])
                checks = check_source(record, view, dict(view.params))
                report.update(lifted=True, view=view.to_dict(), template=normalized_template(view),
                              scope=asdict(scope), reconstruction_checks=checks, features=features(view))
                templates[(seed, report['template'])].append(record['key'])
            except Exception as exc:
                view = None
                report.update(lifted=False, error_type=type(exc).__name__, error=str(exc))
            result['records'].append(report)
            saved[(seed,phase,index)] = (record, view, report)
for seed in frozen['seeds']:
    for index in range(8):
        initial, a, ar = saved[(seed,'ordinary',index)]
        later, b, br = saved[(seed,'ordinary',index+8)]
        pair = {'seed': seed, 'initial_index': index, 'later_index': index+8,
                'initial_key': initial['key'], 'later_key': later['key'],
                'both_direct_answers_correct': ar['correct'] and br['correct'],
                'both_sources_lifted': a is not None and b is not None}
        if a is not None and b is not None:
            pa,pb=template_payload(a),template_payload(b)
            fields=[key for key in pa if canonical(pa[key]) != canonical(pb[key])]
            row_fields=[key for key in pa if key not in ('reconstruction_sql','outer_bindings')]
            typed = {k:type(v).__name__ for k,v in a.params.items()} == {k:type(v).__name__ for k,v in b.params.items()}
            changed = canonical(a.params) != canonical(b.params)
            exact = normalized_template(a) == normalized_template(b)
            fa,fb=features(a),features(b)
            pair.update(exact_template_identity=exact, differing_template_fields=fields,
                row_payload_exact_ignoring_reconstruction=all(canonical(pa[k])==canonical(pb[k]) for k in row_fields),
                same_public_scope=ar['scope']==br['scope'], same_typed_binding_holes=typed,
                changed_binding_values=changed, changed_recorded_numeric_answer=initial['trace']['answer']!=later['trace']['answer'],
                source_binding_holes=dict(a.params), later_binding_holes=dict(b.params),
                source_question_binding_exposed=initial['trace']['evaluator']['definition']['binding'] in a.params.values(),
                inner_join_keyword_normalization_alone_would_match=canonical(inner_join_only_payload(a))==canonical(inner_join_only_payload(b)),
                source_table_alias_tokens_changed=fa['source_table_aliases']!=fb['source_table_aliases'],
                syntax_feature_differences={k:[fa[k],fb[k]] for k in ('source_ctes','source_subqueries','source_joins','source_cases','outer_coalesces','outer_sums','outer_divisions') if fa[k]!=fb[k]})
            if typed and changed:
                pair['unchanged_source_check_ignoring_template_gate'] = check_source(later,a,dict(b.params))
            else:
                pair['unchanged_source_check_ignoring_template_gate'] = {'status':'incompatible_or_unchanged_binding_holes'}
            checks=pair['unchanged_source_check_ignoring_template_gate']
            pair['current_runtime_corroboration_conditions_satisfied_on_cold_fixtures'] = bool(
                exact and typed and changed and pair['same_public_scope']
                and pair['changed_recorded_numeric_answer']
                and checks.get('matches_independently_recorded_current_answer')
                and checks.get('empty_relation_changes_answer')
                and checks.get('two_checks_fit_original_remaining_select_allowance')
                and ar['reconstruction_checks']['matches_independently_recorded_current_answer']
                and ar['reconstruction_checks']['empty_relation_changes_answer'])
        result['planned_pairs'].append(pair)
        for phase,target_index in (('ordinary',index+16),('final',index)):
            target, _, tr = saved[(seed,phase,target_index)]
            probe = {'seed':seed, 'initial_index':index,'target_key':target['key'],
                     'source_key':initial['key'],'target_phase':phase,
                     'current_cold_fixture_template_gate_passed':pair.get('current_runtime_corroboration_conditions_satisfied_on_cold_fixtures',False),
                     'program_authorship':'offline diagnostic source-wrapper SUM-to-AVG translation; not model generated',
                     'fresh_vs_source_and_changed_binding_fixture':len({row['trace']['evaluator']['data_sha256'] for row in (initial,later,target)})==3,
                     'actual_stateful_mechanism_event':False}
            if a is None:
                probe.update(status='source_not_lifted')
            else:
                target_binding=target['trace']['evaluator']['definition']['binding']
                source_binding=initial['trace']['evaluator']['definition']['binding']
                bindings=dict(a.params)
                if len(bindings)==1 and all(type(v) is str for v in bindings.values()):
                    bindings={name:target_binding for name in bindings}
                elif target_binding != source_binding:
                    probe.update(status='source_has_no_rebindable_hole_for_target')
                    result['fresh_row_probes'].append(probe)
                    continue
                try:
                    program=compose_mean(a,bindings)
                    built=compile_program(program,[a])
                    output=query(target,built.prepared.sql,built.prepared.parameters)
                    expected=spec_for(target)._expected
                    success=output['scalar']['status']=='numeric' and correct(output['scalar']['value'],expected)
                    empty_view=_AuditView(a.key,'SELECT * FROM ('+a.sql+') AS static_empty WHERE 0',
                                          dict(a.params),a.columns,a.measure_columns)
                    empty=compile_program(program,[empty_view])
                    deleted=query(target,empty.prepared.sql,empty.prepared.parameters)
                    overrides={a.key:{column:0 for column in a.measure_columns}}
                    changed=compile_program(program,[a],measure_overrides=overrides)
                    replaced=query(target,changed.prepared.sql,changed.prepared.parameters)
                    probe.update(status='compiled_and_replayed',bindings=bindings,program=program,
                         original_source_view_key=a.key, source_sql_sha256=digest(a.sql),
                         result=output,correct=success, empty_relation_result=deleted,
                         empty_relation_wrong=not correct(deleted['scalar']['value'],expected),
                         zero_measure_result=replaced,zero_measure_wrong=not correct(replaced['scalar']['value'],expected),
                         lineage={column:resolve_measure_lineage(a,column,target['trace']['schema']) for column in a.measure_columns})
                except Exception as exc:
                    probe.update(status='unsupported_diagnostic_translation',error_type=type(exc).__name__,error=str(exc))
            result['fresh_row_probes'].append(probe)
result['template_groups']=[{'seed':seed,'template':template,'record_keys':keys} for (seed,template),keys in templates.items()]
pairs=result['planned_pairs']; probes=result['fresh_row_probes']
result['counts']={
    'cold_records':len(result['records']),
    'correct_cold_answers':sum(row['correct'] for row in result['records']),
    'lifted_and_compiler_supported':sum(row['lifted'] for row in result['records']),
    'own_reconstruction_and_empty_check_pass':sum(row.get('reconstruction_checks',{}).get('matches_independently_recorded_current_answer',False) and row.get('reconstruction_checks',{}).get('empty_relation_changes_answer',False) for row in result['records']),
    'distinct_templates_per_seed':{str(seed):sum(key[0]==seed for key in templates) for seed in frozen['seeds']},
    'planned_pairs':len(pairs),
    'exact_template_pairs':sum(row.get('exact_template_identity',False) for row in pairs),
    'row_payload_exact_but_wrapper_differs':sum(row.get('row_payload_exact_ignoring_reconstruction',False) and not row.get('exact_template_identity',False) for row in pairs),
    'inner_join_keyword_normalization_alone_pairs':sum(row.get('inner_join_keyword_normalization_alone_would_match',False) and not row.get('exact_template_identity',False) for row in pairs),
    'pairs_with_changed_alias_tokens':sum(row.get('source_table_alias_tokens_changed',False) for row in pairs),
    'initial_sources_without_exposed_question_binding':sum(not row.get('source_question_binding_exposed',False) for row in pairs),
    'unchanged_source_reconstructs_later_answer_ignoring_template_gate':sum(row.get('unchanged_source_check_ignoring_template_gate',{}).get('matches_independently_recorded_current_answer',False) and row.get('unchanged_source_check_ignoring_template_gate',{}).get('empty_relation_changes_answer',False) for row in pairs),
    'current_runtime_corroboration_conditions_on_cold_fixtures':sum(row.get('current_runtime_corroboration_conditions_satisfied_on_cold_fixtures',False) for row in pairs),
    'fresh_row_diagnostic_probes':len(probes),
    'fresh_row_correct_source_compositions':sum(row.get('correct',False) for row in probes),
    'fresh_row_correct_with_empty_and_zero_measure_flips':sum(row.get('correct',False) and row.get('empty_relation_wrong',False) and row.get('zero_measure_wrong',False) for row in probes),
    'fresh_row_probe_statuses':dict(Counter(row['status'] for row in probes)),
    'actual_stateful_mechanism_events':0,
}
result['interpretation']=[
    'Cold competence does not establish exact-template reuse. Actual stateful development may stabilize SQL through its visible own prior evidence; this report predicts no stateful outcomes.',
    'Numerical rebinding checks after bypassing a syntax gate are explicitly hypothetical. No registry is modified and no checked alternative is supplied to a model.',
    'SQL-equivalent spellings can be missed by the deliberate identity gate; semantic equivalence is not inferred from alias changes or successful checks on these finite rows.',
    'Source-bound arithmetic and predicates are retained in fresh-row program probes. Failure to expose a row binding cannot be repaired by these probes.',
]
destination=ROOT/'artifacts/campaign/static-source-compatibility-dense-v2.json'
if destination.exists():
    raise ValueError('diagnostic report already exists')
result['analysis_script_sha256']=sha(__file__)
save(destination,result)
print(result['counts'])
print('differing_fields',dict(Counter(field for pair in pairs for field in pair.get('differing_template_fields',[]))))
print('future_failures',[(row['target_key'],row['status'],row.get('result',{}).get('scalar')) for row in probes if not row.get('correct')])
