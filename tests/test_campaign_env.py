"""Independent evaluator checks, never solver traces or model outcomes."""

from witness_cl.campaign_env import make_episode, make_stream, schedule
from witness_cl.sql_env_v9 import open_episode


def test_every_reference_matches_independent_python_oracle():
    for split in ("development", "confirmation"):
        for condition in ("reuse", "drift", "nonreuse"):
            for phase, index in schedule(old_replicates=1):
                spec = make_episode(812391, split, condition, phase, index, old_replicates=1)
                with open_episode(spec) as session:
                    result = session.query(spec._gold_sql)
                    assert result.error is None
                    assert session.answer(result.rows[0][0]).reward == 1.0


def test_delayed_opportunities_have_distinct_bindings_rows_and_later_operations():
    stream = make_stream(817281)
    for family in range(8):
        a, b, c = [dict(stream.ordinary[i]._metadata) for i in (family, family + 8, family + 16)]
        assert a["definition"]["binding"] != b["definition"]["binding"]
        assert a["definition"]["operation"] == b["definition"]["operation"]
        assert c["definition"]["operation"] != a["definition"]["operation"]
        assert len({a["data_sha256"], b["data_sha256"], c["data_sha256"]}) == 3


def test_paired_old_panels_reproduce_same_hidden_data_and_questions():
    for i in (0, 17, 63):
        before = make_episode(827182, "confirmation", "drift", "old_before", i)
        after = make_episode(827182, "confirmation", "drift", "old_after", i)
        assert before._public == after._public
        assert before._tables == after._tables
        assert before._expected == after._expected


def test_drift_is_public_same_schema_and_stable_pair_reuses_world_randomness():
    a = make_episode(827182, "diagnostic", "reuse", "ordinary", 8)
    b = make_episode(827182, "diagnostic", "drift", "ordinary", 8)
    assert a._public.schema == b._public.schema
    assert "migrated" in b._public.question
    assert a._tables[0].rows != b._tables[0].rows
    assert dict(a._metadata)["data_seed"] == dict(b._metadata)["data_seed"]


def test_main_schedule_is_complete_and_sources_not_visible():
    assert len(schedule()) == 184
    spec = make_episode(921291, "confirmation", "reuse", "final", 0)
    public = vars(spec._public)
    assert set(public) == {"question", "schema", "max_selects"}
    assert spec._gold_sql not in str(public)
