"""Receipt lifecycle tests use authored SQL, never count as model evidence."""
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from witness_cl.delayed_memory import (
    CompatibilityScope, DelayedMemory, DelayedRegistry, Witness,
    normalized_template, reconstruct_bound,
)
from witness_cl.query_memory import digest
from witness_cl.source_views import lift_source


SCHEMA = "CREATE TABLE amounts(amount INTEGER, tier TEXT);"
CATALOG = {"columns": ["table_name", "column_name", "description"],
           "rows": [["amounts", "amount", "Dollars; NULL means zero"]],
           "error": None, "truncated": False}


def view(tier="Gold", *, multiplier=2.0, outer=0):
    return lift_source(
        f"SELECT COALESCE(SUM(amount * {multiplier}),0) + :offset "
        f"FROM amounts WHERE tier='{tier}'",
        {"offset": outer}, SCHEMA, "Total dollars by tier")


def scope(catalog=CATALOG):
    return CompatibilityScope.from_observation(SCHEMA, catalog)


def witness(v, index=0, answer=6):
    return Witness(f"episode-{index}", index, answer, digest({"source": index}),
                   digest({"check": index}), digest({"empty": index}),
                   tuple(sorted(v.params.items())))


def test_template_preserves_code_wrapper_and_outer_constants_but_not_typed_row_values():
    assert view().key != view("Silver").key
    assert normalized_template(view()) == normalized_template(view("Silver"))
    assert normalized_template(view()) != normalized_template(view(multiplier=3.0))
    assert normalized_template(view()) != normalized_template(view(outer=5))


def test_delayed_state_machine_requires_independent_later_changed_binding_and_output():
    registry = DelayedRegistry()
    original, changed = view(), view("Silver")
    entry = registry.add(original, scope(), witness(original))
    assert entry.state == "provisional"
    assert registry.selected("total", scope(), 1) == []
    assert registry.matching(changed, scope(), 0) is None
    assert registry.matching(original, scope(), 1) is None
    assert registry.matching(changed, scope(), 1) == entry
    with pytest.raises(ValueError, match="changed binding and output"):
        registry.corroborate(entry.key, changed, scope(), witness(changed, 1, 6))
    with pytest.raises(ValueError, match="changed binding and output"):
        registry.corroborate(entry.key, changed, scope(), witness(changed, 0, 20))
    promoted = registry.corroborate(entry.key, changed, scope(), witness(changed, 1, 20))
    assert promoted.state == "corroborated" and promoted.view is original
    assert promoted.source == entry.source and entry.corroboration is None
    assert registry.selected("total", scope(), 1) == []
    assert registry.selected("total", scope(), 2) == [promoted]
    with pytest.raises(FrozenInstanceError):
        promoted.corroboration = None


def test_corroboration_does_not_allow_changed_code_or_scope_or_foreign_witness():
    registry = DelayedRegistry()
    original = view()
    entry = registry.add(original, scope(), witness(original))
    wrong = view("Silver", multiplier=3.0)
    changed_scope = replace(scope(), catalog_sha256=digest("changed conventions"))
    for candidate, candidate_scope, candidate_witness in [
        (wrong, scope(), witness(wrong, 1, 20)),
        (view("Silver"), changed_scope, witness(view("Silver"), 1, 20)),
        (view("Silver"), scope(), witness(original, 1, 20)),
    ]:
        with pytest.raises(ValueError):
            registry.corroborate(entry.key, candidate, candidate_scope, candidate_witness)
    assert registry.entries == [entry]


def test_scope_uses_complete_public_catalog_and_preserves_duplicates():
    reverse = {**CATALOG, "rows": list(reversed(CATALOG["rows"]))}
    assert scope(reverse) == scope()
    assert scope({**CATALOG, "rows": CATALOG["rows"] * 2}) != scope()
    for malformed in ({**CATALOG, "truncated": True}, {**CATALOG, "error": "timeout"},
                      {**CATALOG, "rows": []}, {**CATALOG, "rows": [["a", "b", 1]]}):
        with pytest.raises(ValueError):
            scope(malformed)


def test_original_wrapper_is_preserved_under_typed_rebinding():
    original = view(outer=5)
    changed = view("Silver", outer=5)
    sql, params = reconstruct_bound(original, dict(changed.params))
    assert sql == original.reconstruction_sql
    assert params["offset"] == 5
    assert params["sv_text_0"] == "Silver"
    assert original.params["sv_text_0"] == "Gold"
    for bindings in ({}, {"sv_text_0": 4}, {"sv_text_0": "Silver", "offset": 99}):
        with pytest.raises(ValueError):
            reconstruct_bound(original, bindings)


def test_snapshot_round_trip_preserves_full_provenance_and_detects_tampering():
    memory = DelayedMemory()
    original, changed = view(), view("Silver")
    entry = memory.registry.add(original, scope(), witness(original))
    memory.registry.corroborate(entry.key, changed, scope(), witness(changed, 1, 20))
    memory.ordinary_count = 2
    snapshot = json.loads(json.dumps(memory.snapshot()))
    restored = DelayedMemory.from_snapshot(snapshot)
    assert restored.state_digest() == memory.state_digest()
    assert restored.registry.entries == memory.registry.entries
    snapshot["registry"]["entries"][0]["corroboration"]["answer"] = 6
    with pytest.raises(ValueError):
        DelayedMemory.from_snapshot(snapshot)


def test_immediate_ablation_is_explicit_and_delayed_without_paid_scope_cannot_retrieve():
    memory = DelayedMemory("immediate")
    original = view()
    entry = memory.registry.add(original, scope(), witness(original))
    assert memory.registry.selected("total", scope(), 1, immediate=True) == [entry]
    assert memory.prefix("total", SCHEMA)[1] == []
    assert memory.prefix_for_episode("total", SCHEMA, scope(), 1)[1] == [original]
