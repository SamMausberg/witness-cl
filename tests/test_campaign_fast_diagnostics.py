"""In-memory arithmetic fixtures, never exported as empirical evidence."""

from copy import deepcopy

import pytest

from tools import campaign_fast_diagnostics as diagnostics


@pytest.fixture
def records():
    rows = []
    for seed in diagnostics.SEEDS:
        for arm in diagnostics.ARMS:
            for phase, indices in diagnostics.PHASES.items():
                for index in indices:
                    old = phase.startswith("old_")
                    correct = 1
                    if arm == "delayed" and index == 0:
                        if (seed == diagnostics.SEEDS[0] and phase == "old_before"
                                or seed == diagnostics.SEEDS[1] and phase == "old_after"):
                            correct = 0
                    cohort = "old" if old else phase
                    definition = {"operation": diagnostics.FINAL[index] if phase == "final" else "sum",
                                  "family": index % 8}
                    rows.append({"seed": seed, "condition": "reuse", "arm": arm, "phase": phase,
                        "index": index, "sampling_seed": diagnostics.sampling_seed(seed, phase, index),
                        "trace": {"status": "completed", "reward": correct, "question": f"{cohort}-{index}",
                                  "schema": "software arithmetic fixture",
                                  "evaluator": {"data_sha256": f"{seed}-{cohort}-{index}", "data_seed": index,
                                      "definition": definition, "generator": "software arithmetic fixture",
                                      "split": "development", "seed": seed, "condition": "reuse"}}})
    return rows


def test_exact_denominators_zero_funnel_and_two_stream_retention(records):
    result = diagnostics.describe_complete(records, [])
    assert len(result["stream_metrics"]) == 6
    assert len(result["retention_pairs"]) == 24
    delayed = result["by_arm"]["delayed"]
    assert delayed["future"]["n"] == delayed["future"]["correct"] == 16
    assert all(row["n"] == 4 for row in delayed["future"]["by_outer_operation"].values())
    assert all(value == 0 for value in delayed["lifecycle_funnel"].values())
    retention = delayed["retention"]["stream_contrasts"]
    assert retention["values"] == [0.25, -0.25]
    assert retention["sample_variance"] == 0.125
    assert retention["variance_degrees_of_freedom"] == 1
    assert not result["inference_or_sizing_performed"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "pair_seed", "operation", "test_double"])
def test_incomplete_or_invalid_observations_rejected(records, mutation):
    rows = deepcopy(records)
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1] = rows[-2]
    elif mutation == "pair_seed":
        next(row for row in rows if row["phase"] == "old_after")["sampling_seed"] += 1
    elif mutation == "operation":
        next(row for row in rows if row["phase"] == "final")["trace"]["evaluator"]["definition"]["operation"] = "min"
    else:
        rows[0]["trace"]["test_double"] = True
    with pytest.raises(ValueError):
        diagnostics.describe_complete(rows, [])
