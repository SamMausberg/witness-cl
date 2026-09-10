"""Regression for cross-process SQLGlot lineage traversal presentation order."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_audit_campaign_mechanism import campaign_records as fixture_campaign_records
from tools.audit_campaign_mechanism import audit_records
from tools.campaign_fast_report import canonical, normalized_census, validate_census

campaign_records = fixture_campaign_records


def test_actual_lineage_varies_across_hash_seeds_but_graph_content_is_identical():
    program = '''
import json
from tools.audit_campaign_mechanism import resolve_measure_lineage
from witness_cl.source_views import lift_source
schema = "CREATE TABLE amounts(gross REAL, discount REAL, quantity REAL);"
sql = "WITH x AS (SELECT (gross-discount)*quantity AS value FROM amounts) SELECT SUM(value) FROM x"
view = lift_source(sql, {}, schema, "Sum adjusted amounts")
proof = resolve_measure_lineage(view, "m0", schema)
assert proof["computed_from_physical_columns"]
print(json.dumps({"events":[{"lineage":{"m0":proof}}]}))
'''
    values = [json.loads(subprocess.run([sys.executable, "-c", program],
              cwd=Path(__file__).resolve().parents[1], env={**os.environ, "PYTHONHASHSEED": str(seed)},
              check=True, capture_output=True, text=True).stdout) for seed in (1, 2, 3, 4)]
    # This is the failure mode observed in the first positive real census:
    # sorted dictionary keys alone do not stabilize graph traversal lists.
    assert len({canonical(value) for value in values}) > 1
    assert len({canonical(normalized_census(value)) for value in values}) == 1


def test_complete_positive_census_keeps_every_event_when_normalizing_order(campaign_records):
    original = audit_records(campaign_records)
    assert original["structural_event_count"] == 6
    changed = deepcopy(original)
    for event in changed["events"] + changed["first_five"]:
        for proof in event["lineage"].values():
            proof["nodes"].reverse()
            for node in proof["nodes"]:
                node["children"].reverse()
        for intervention in event["interventions"]:
            intervention["elapsed_seconds"] += 100
    result = validate_census(original, json.loads(json.dumps(changed)))
    assert result["identical_after_declared_normalization"]
    assert not result["classification_or_eligibility_changes"]
    assert original["events"] != changed["events"]
    assert len(normalized_census(changed)["events"]) == len(original["events"])


@pytest.mark.parametrize("mutation", ["expression", "edge", "duplicate", "count", "event", "ordered_program"])
def test_normalization_rejects_proof_criterion_or_ordered_expression_changes(mutation):
    original = {"events": [{"lineage": {"m0": {"nodes": [
        {"name": "m0", "expression": "a-b", "children": ["a", "b"]},
        {"name": "a", "expression": "table_a", "children": []},
        {"name": "b", "expression": "table_b", "children": []}]}},
        "program": {"args": ["a", "b"]}, "qualifying_event": True}], "qualifying_event_count": 1}
    changed = deepcopy(original)
    nodes = changed["events"][0]["lineage"]["m0"]["nodes"]
    if mutation == "expression":
        nodes[0]["expression"] = "b-a"
    elif mutation == "edge":
        nodes[0]["children"] = ["a", "a"]
    elif mutation == "duplicate":
        nodes.append(deepcopy(nodes[1]))
    elif mutation == "count":
        changed["qualifying_event_count"] = 0
    elif mutation == "event":
        changed["events"] = []
    else:
        changed["events"][0]["program"]["args"].reverse()
    with pytest.raises(ValueError, match="differs beyond"):
        validate_census(original, changed)
