"""v8 evaluator oracle parity, information separation and bounded SQL authority."""
from dataclasses import FrozenInstanceError, asdict, fields
import math

import pytest

from witness_cl.sql_env_v8 import (
    CONDITIONS, Feedback, MAX_ROWS, MAX_SELECTS, PublicEpisode, QueryResult,
    _COMPOSITIONS, _SHIPPING, _Convention, _answer_recipe, _convention,
    _names, _world, evaluator_expected, evaluator_metadata, evaluator_sql,
    make_stream, open_episode,
)


@pytest.fixture(scope='module')
def stream():
    return make_stream(90000, 'reuse')


@pytest.mark.parametrize('condition', CONDITIONS)
@pytest.mark.parametrize('seed', [90000, 90001, 90002, 90003])
def test_development_gold_selects_match_independent_python_oracle(condition, seed):
    # Development fixtures only: no learned-policy or holdout run.
    stream = make_stream(seed, condition)
    for spec in stream.ordinary + stream.old_panel + stream.final_panel:
        with open_episode(spec) as episode:
            result = episode.query(evaluator_sql(spec))
            assert result.error is None, (evaluator_metadata(spec), result.error)
            assert len(result.rows) == len(result.rows[0]) == 1
            assert result.rows[0][0] == pytest.approx(evaluator_expected(spec), abs=1e-9)
            assert episode.answer(result.rows[0][0]).reward == 1.0
            assert episode.select_attempts == 1
            assert episode.setup_seconds >= 0


def test_public_boundary_contains_no_evaluator_ids_or_targets(stream):
    assert {f.name for f in fields(PublicEpisode)} == {'question','schema','max_selects'}
    assert {f.name for f in fields(Feedback)} == {'reward'}
    assert {f.name for f in fields(QueryResult)} == {'columns','rows','error','attempt','truncated'}
    with open_episode(stream.ordinary[0]) as episode:
        visible = str(asdict(episode.public))
        for forbidden in ('90000', 'names_seed', 'data_seed', 'template=', 'phase=', 'gold_sql', 'expected', ':memory:'):
            assert forbidden not in visible
        with pytest.raises(FrozenInstanceError):
            episode.public.question = 'changed'
        result = episode.query('SELECT * FROM catalog')
        assert result.error is None and 0 < len(result.rows) <= MAX_ROWS
        assert all(type(r) is tuple for r in result.rows)
        with pytest.raises(FrozenInstanceError):
            result.rows = ()
        assert episode.answer(0).reward in (0.0,1.0)


def test_catalog_identifies_all_semantic_conventions_without_answer_sql(stream):
    with open_episode(stream.ordinary[0]) as episode:
        text = ' '.join(str(r) for r in episode.query('SELECT * FROM catalog').rows)
        for concept in ('NULL', 'refund', 'current', 'revision', 'shipment', 'dollars'):
            assert concept in text
        assert 'SELECT' not in text
        assert 'gross value minus' in text
        assert 'Aggregate per order' in text


def test_named_bound_literals_and_free_nonrecursive_sql(stream):
    with open_episode(stream.ordinary[0]) as episode:
        literal = "North'; DROP TABLE catalog; --"
        result = episode.query('WITH supplied AS (SELECT :x AS value) SELECT value, length(value) FROM supplied', {'x':literal})
        assert result.error is None and result.rows == ((literal,len(literal)),)
        assert episode.query('SELECT COUNT(*) FROM catalog').error is None
        assert episode.query('SELECT :x / :y', {'x':4,'y':2.0}).rows == ((2.0,),)


@pytest.mark.parametrize('sql', [
    'DELETE FROM catalog',
    'WITH x AS (SELECT 1) DELETE FROM catalog',
    "UPDATE catalog SET description='changed'",
    'CREATE TABLE injected (value INTEGER)',
    'PRAGMA query_only=OFF',
    "ATTACH DATABASE '/tmp/forbidden-v8.sqlite' AS external",
    'DETACH DATABASE main',
    'BEGIN TRANSACTION',
    "SELECT load_extension('forbidden')",
    "SELECT readfile('/etc/passwd')",
    "SELECT writefile('/tmp/forbidden-v8','x')",
    'SELECT * FROM sqlite_master',
    'SELECT * FROM sqlite_schema',
    "SELECT * FROM pragma_table_info('catalog')",
    'SELECT randomblob(100)',
    'SELECT random()',
    'WITH RECURSIVE counter(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM counter WHERE x<10) SELECT * FROM counter',
    'SELECT 1; SELECT 2',
    'EXPLAIN SELECT * FROM catalog',
])
def test_denied_actions_are_charged_and_do_not_change_data(stream, sql):
    with open_episode(stream.ordinary[0]) as episode:
        before = episode.query('SELECT * FROM catalog')
        result = episode.query(sql)
        after = episode.query('SELECT * FROM catalog')
        assert result.error is not None, sql
        assert result.attempt == 2 and episode.select_attempts == 3
        assert before.rows == after.rows


@pytest.mark.parametrize('parameters', [
    {'x':True}, {'x':float('nan')}, {'x':float('inf')}, {'x':2**100},
    {'x':[]}, {'x':b'bytes'}, {'x':'a'*4097}, {'bad-key':1}, {'':1}, [(1,2)],
])
def test_parameter_validation_is_bounded_and_charged(stream, parameters):
    with open_episode(stream.ordinary[0]) as episode:
        result = episode.query('SELECT :x', parameters)
        assert result.error is not None and result.attempt == 1
        assert episode.query('SELECT 1').rows == ((1,),)


def test_invalid_sql_and_exhausted_budget_do_not_allow_extra_execution(stream):
    with open_episode(stream.ordinary[0]) as episode:
        for sql in (None, '', 'SELECT '+('1 '*9000), '-- comment only', 'SELECT absent', 'SELECT :missing', 'SELECT 1/0', 'SELECT 2'):
            episode.query(sql)
        assert episode.select_attempts == MAX_SELECTS
        blocked = episode.query('SELECT 3')
        assert blocked.rows == () and 'budget exhausted' in blocked.error
        assert blocked.attempt == MAX_SELECTS and episode.select_attempts == MAX_SELECTS
        assert episode.answer(evaluator_expected(stream.ordinary[0])).reward == 1


def test_result_row_byte_blob_and_finite_limits(stream):
    with open_episode(stream.ordinary[0]) as episode:
        result = episode.query('SELECT a.table_name FROM catalog a CROSS JOIN catalog b')
        assert result.error is None and result.truncated and len(result.rows) == MAX_ROWS
        assert episode.query("SELECT printf('%5000s','x')").error is not None
        assert episode.query("SELECT x'CAFE'").error is not None
        assert episode.query('SELECT 1e999').error is not None
        assert episode.query("SELECT printf('%4000s','x') FROM catalog").error is not None


@pytest.mark.parametrize('limits', [{'max_vm_steps':100}, {'max_query_seconds':1e-12}])
def test_sql_execution_budget_interrupts_and_preserves_connection(stream, limits):
    with open_episode(stream.ordinary[0], **limits) as episode:
        result = episode.query('SELECT COUNT(*) FROM catalog a CROSS JOIN catalog b CROSS JOIN catalog c CROSS JOIN catalog d')
        assert result.error is not None and result.attempt == 1
        assert episode.query_seconds > 0
        assert episode.answer(0).reward in (0,1)


@pytest.mark.parametrize('value', [None, True, '1', [], math.nan, math.inf, 2**10000], ids=['null','boolean','text','list','nan','infinity','oversize_integer'])
def test_invalid_answers_are_terminal_zero_reward_without_gold_feedback(stream, value):
    with open_episode(stream.ordinary[0]) as episode:
        assert episode.answer(value) == Feedback(0.0)
        assert episode.query('SELECT 1').error == 'episode is closed for queries'
        with pytest.raises(RuntimeError, match='one answer'):
            episode.answer(evaluator_expected(stream.ordinary[0]))


def test_closed_session_cannot_be_used(stream):
    episode = open_episode(stream.ordinary[0])
    episode.close()
    episode.close()
    assert episode.query('SELECT 1').error
    with pytest.raises(RuntimeError):
        episode.answer(1)


def test_streams_replay_exactly_and_old_panel_is_frozen(stream):
    assert make_stream(90000,'reuse') == stream
    assert len(stream.ordinary) == 24
    assert len(stream.old_panel) == len(stream.final_panel) == 8
    for old, ordinary in zip(stream.old_panel,stream.ordinary[:8]):
        assert old._public == ordinary._public
        assert old._tables != ordinary._tables
        assert evaluator_metadata(old)['data_seed'] != evaluator_metadata(ordinary)['data_seed']
        assert evaluator_metadata(old)['convention'] == evaluator_metadata(ordinary)['convention']
        assert evaluator_metadata(old)['panel'] == 'old'
    assert stream.ordinary[0]._tables != stream.ordinary[1]._tables
    assert stream.ordinary[0]._public.schema == stream.ordinary[1]._public.schema
    assert all('at least two refund records' in e._public.question for e in stream.final_panel)
    assert not any('Restrict the calculation' in e._public.question for e in stream.ordinary)


def test_nonreuse_renames_and_near_match_changes_visible_semantics():
    nonreuse = make_stream(90000,'nonreuse')
    assert len({e._public.schema for e in nonreuse.ordinary}) == 24
    near = make_stream(90000,'near_match')
    first, changed = near.ordinary[0], near.ordinary[8]
    assert first._public.schema == changed._public.schema
    assert first._tables[0].rows != changed._tables[0].rows
    a,b = evaluator_metadata(first)['convention'],evaluator_metadata(changed)['convention']
    assert all(x != y for x,y in zip(a,b))
    assert 'migrated' in changed._public.question
    assert 'migrated' not in first._public.question


def test_split_definition_has_disjoint_combinations_and_postwarm_templates():
    # Inspect generator definitions only; no heldout stream or policy is run.
    seen = {split:{_convention(seed,split) for seed in range(100)} for split in ('development','heldout')}
    assert len(seen['development']) == len(seen['heldout']) == 8
    assert not seen['development'] & seen['heldout']
    for field in fields(_Convention):
        assert {getattr(c,field.name) for c in seen['development']} == {False,True}
        assert {getattr(c,field.name) for c in seen['heldout']} == {False,True}
    dev = {k for k,q in _COMPOSITIONS['development']+_SHIPPING['development']}
    held = {k for k,q in _COMPOSITIONS['heldout']+_SHIPPING['heldout']}
    assert len(dev) == len(held) == 16 and not dev & held


def test_surface_names_are_independent_of_conventions():
    n = _names(90000)
    assert len(n) == len(set(n.values()))
    a = _world(90000,n,_Convention(False,False,True,False))[0]
    b = _world(90000,n,_Convention(True,True,False,True))[0]
    assert tuple(t.ddl for t in a) == tuple(t.ddl for t in b)
    assert a[0].rows != b[0].rows


def test_current_profile_rule_and_null_semantics_have_identifiable_effect():
    n = _names(90000)
    c = _Convention(False,False,True,False)
    tables,lines,current = _world(90000,n,c)
    other_tables,other_lines,other_current = _world(90000,n,_Convention(False,True,True,True))
    assert current != other_current
    assert any(r['gross'] is None for r in lines)
    assert all(r['gross'] is not None for r in other_lines)
    assert tables[0].rows != other_tables[0].rows
    assert _answer_recipe('mean_gross',lines,current)[0] != _answer_recipe('mean_gross',other_lines,other_current)[0]


def test_raw_join_multiplication_is_observable_and_reference_avoids_it(stream):
    spec = stream.ordinary[0]
    n = _names(evaluator_metadata(spec)['names_seed'])
    with open_episode(spec) as episode:
        correct = episode.query(f'SELECT COUNT(*) FROM {n["orders"]}').rows[0][0]
        multiplied = episode.query(f'SELECT COUNT(*) FROM {n["orders"]} o JOIN {n["refunds"]} r ON r.{n["roid"]}=o.{n["oid"]} JOIN {n["shipments"]} s ON s.{n["soid"]}=o.{n["oid"]}').rows[0][0]
        assert correct == 32 and multiplied != correct


@pytest.mark.parametrize('args', [(-1,'reuse'), (True,'reuse'), (2**63,'reuse'), (1,'unknown'), (1,'reuse','unknown')])
def test_generator_rejects_invalid_config(args):
    with pytest.raises(ValueError):
        make_stream(*args)


def test_minimal_recipes_omit_unused_gold_ctes_and_are_evaluator_only(stream):
    from witness_cl.sql_env_v8 import evaluator_recipe
    gross = evaluator_recipe(stream.ordinary[0])
    assert gross.required_relations == ('orders',)
    assert gross.required_subskills == ('order_amount',)
    assert 'refund_totals' in evaluator_sql(stream.ordinary[0])
    assert 'refund_totals' not in str(gross)
    assert evaluator_recipe(stream.ordinary[3]).required_relations == ('profiles',)
    net = evaluator_recipe(stream.ordinary[8])
    assert net.required_relations == ('orders','profiles','refunds')
    assert {'order_amount','profile_current','refund_events'} <= set(net.required_subskills)
    assert 'semantic_recipe' in evaluator_metadata(stream.ordinary[8])
    assert 'semantic_recipe' not in asdict(stream.ordinary[8]._public)


def test_postwarm_development_recipes_are_novel_compositions_of_practiced_skills(stream):
    from witness_cl.sql_env_v8 import evaluator_recipe
    warm = [evaluator_recipe(e) for e in stream.ordinary[:8]]
    prior = {r.fingerprint for r in warm}
    skills = {s for r in warm for s in r.required_subskills}
    for spec in stream.ordinary[8:16]:
        recipe = evaluator_recipe(spec)
        assert recipe.fingerprint not in prior
        assert len(set(recipe.required_subskills) & skills) >= 2
        assert len(recipe.required_relations) >= 2
        prior.add(recipe.fingerprint)
    ordinary = {evaluator_recipe(e).fingerprint for e in stream.ordinary}
    for spec in stream.final_panel:
        recipe = evaluator_recipe(spec)
        assert recipe.fingerprint not in ordinary
        assert {'shipments','refunds'} <= set(recipe.required_relations)


def test_recipe_fingerprints_ignore_literal_changes_but_preserve_composition():
    from witness_cl.sql_env_v8 import _semantic_recipe
    a = _semantic_recipe("SELECT SUM(gross) FROM lines WHERE region='North'")
    b = _semantic_recipe("SELECT SUM(gross) FROM lines WHERE region='South'")
    c = _semantic_recipe("SELECT SUM(net) FROM lines WHERE region='North'")
    d = _semantic_recipe("SELECT SUM(net) FROM lines WHERE region='North' AND cid IN (SELECT cid FROM lines WHERE status='confirmed')")
    assert a.fingerprint == b.fingerprint
    assert len({a.fingerprint,c.fingerprint,d.fingerprint}) == 3


def test_postwarm_split_structure_is_disjoint_not_only_new_literals():
    from witness_cl.sql_env_v8 import _semantic_recipe
    # Render fixed template definitions using empty symbolic scaffolding. This
    # constructs no heldout dataset/stream and evaluates no learner or gold case.
    structures = {}
    for split in ('development','heldout'):
        structures[split] = {_semantic_recipe(_answer_recipe(kind, [], {})[1]).fingerprint
                             for kind,question in _COMPOSITIONS[split]+_SHIPPING[split]}
    assert len(structures['development']) == len(structures['heldout']) == 16
    assert not structures['development'] & structures['heldout']


def test_learning_checks_require_capability_answer_phase_and_explicit_flag(stream):
    with open_episode(stream.ordinary[0]) as panel:
        panel.answer(0)
        result = panel.query('SELECT 1', learning_check=True)
        assert result.error == 'learning checks are not enabled'
        assert panel.select_attempts == 0
    with open_episode(stream.ordinary[0], allow_learning_checks=True) as episode:
        early = episode.query('SELECT 1', learning_check=True)
        assert early.error == 'learning checks require an answered episode'
        assert episode.select_attempts == 0
        assert episode.query('SELECT 1').rows == ((1,),)
        reward = episode.answer(0)
        assert episode.query('SELECT 2').error == 'episode is closed for queries'
        checked = episode.query('SELECT :x', {'x':2}, learning_check=True)
        assert checked.rows == ((2,),) and checked.attempt == 2
        assert episode.select_attempts == 2
        assert reward == Feedback(0.0)
        with pytest.raises(RuntimeError, match='one answer'):
            episode.answer(evaluator_expected(stream.ordinary[0]))
        episode.close()
        assert episode.query('SELECT 3', learning_check=True).error == 'episode is closed for queries'


def test_learning_checks_share_the_lifetime_eight_attempt_budget(stream):
    with open_episode(stream.ordinary[0], allow_learning_checks=True) as episode:
        for _ in range(7):
            assert episode.query('SELECT 1').error is None
        episode.answer(evaluator_expected(stream.ordinary[0]))
        assert episode.query('SELECT 2', learning_check=True).attempt == 8
        exhausted = episode.query('SELECT 3', learning_check=True)
        assert exhausted.error == 'SELECT attempt budget exhausted'
        assert exhausted.rows == () and episode.select_attempts == 8


@pytest.mark.parametrize('sql', [
    'DELETE FROM catalog', 'PRAGMA query_only=OFF',
    "ATTACH DATABASE '/tmp/forbidden-v8.sqlite' AS external",
    "SELECT readfile('/etc/passwd')", "SELECT load_extension('forbidden')",
    'SELECT * FROM sqlite_master',
])
def test_learning_checks_have_identical_read_only_authority(stream, sql):
    with open_episode(stream.ordinary[0], allow_learning_checks=True) as episode:
        before = episode.query('SELECT * FROM catalog')
        original_feedback = episode.answer(0)
        denied = episode.query(sql, learning_check=True)
        after = episode.query('SELECT * FROM catalog', learning_check=True)
        assert denied.error is not None and denied.attempt == 2
        assert before.rows == after.rows and episode.select_attempts == 3
        assert original_feedback == Feedback(0.0)


def test_learning_checks_keep_row_bytes_parameters_and_time_caps(stream):
    with open_episode(stream.ordinary[0], allow_learning_checks=True) as episode:
        episode.answer(0)
        rows = episode.query('SELECT a.table_name FROM catalog a CROSS JOIN catalog b', learning_check=True)
        assert rows.error is None and rows.truncated and len(rows.rows) == 50
        assert episode.query("SELECT printf('%5000s','x')", learning_check=True).error
        assert episode.query('SELECT :x', {'x':True}, learning_check=True).error
        assert episode.select_attempts == 3
    with open_episode(stream.ordinary[0], allow_learning_checks=True, max_vm_steps=100) as episode:
        episode.answer(0)
        result = episode.query('SELECT COUNT(*) FROM catalog a CROSS JOIN catalog b CROSS JOIN catalog c', learning_check=True)
        assert result.error is not None and result.attempt == 1


@pytest.mark.parametrize('value', [None,1,'true'])
def test_learning_capabilities_require_explicit_booleans(stream, value):
    with pytest.raises(ValueError, match='explicit boolean'):
        open_episode(stream.ordinary[0], allow_learning_checks=value)
    with open_episode(stream.ordinary[0], allow_learning_checks=True) as episode:
        episode.answer(0)
        assert episode.query('SELECT 1', learning_check=value).error == 'learning_check must be an explicit boolean'
        assert episode.select_attempts == 0
