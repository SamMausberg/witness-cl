from copy import deepcopy
import pytest
from witness_cl.campaign_analysis import analyze, size_study, joint_power_simulation, diagnose


def rows(n):
    return [
        {
            "seed": i,
            "complete": True,
            "arms": {
                "full_history": {"future_accuracy": 0.6, "total_tokens": 10000},
                "ace": {"future_accuracy": 0.65, "total_tokens": 9000},
                "delayed": {
                    "future_accuracy": 0.8,
                    "total_tokens": 6000,
                    "old_before_accuracy": 0.9,
                    "old_after_accuracy": 0.9,
                },
            },
        }
        for i in range(n)
    ]


def test_joint_power_requires_retention_sized_sample():
    result = size_study(rows(32))
    assert result["streams"] == 419
    assert min(result["endpoint_power"]) >= 0.96
    assert result["joint_power_union_lower"] >= 0.8


def test_five_endpoints_must_all_pass_and_zero_variance_not_exact_retention():
    result = analyze(rows(419), frozen_n=419)
    assert result["all_five_pass"]
    assert -0.02 < result["endpoints"]["retention"]["lower"] < 0
    bad = rows(419)
    for row in bad:
        row["arms"]["delayed"]["old_after_accuracy"] = 0.87
    assert not analyze(bad, frozen_n=419)["all_five_pass"]


def test_missing_or_duplicated_stream_cannot_be_selected_away():
    data = rows(419)
    data[0]["complete"] = False
    with pytest.raises(ValueError):
        analyze(data, frozen_n=419)
    with pytest.raises(ValueError):
        analyze(rows(418), frozen_n=419)
    data = rows(419)
    data[1] = deepcopy(data[0])
    with pytest.raises(ValueError):
        analyze(data, frozen_n=419)


def test_token_contrast_uses_all_costs_against_both_controls():
    data = rows(419)
    for row in data:
        row["arms"]["ace"]["total_tokens"] = 7000
    result = analyze(data, frozen_n=419)
    assert result["endpoints"]["tokens_full_history"]["passed"]
    assert not result["endpoints"]["tokens_ace"]["passed"]


def test_joint_simulation_handles_zero_pilot_variance_without_nan():
    result = joint_power_simulation(rows(32), 419, trials=1000)
    assert result["trials"] == 1000
    assert 0 < result["one_sided_95_mc_lower"] < result["joint_power_estimate"] < 1


def test_drift_diagnostic_preserves_checked_library_degradation():
    data = []
    for row in rows(64):
        stable = deepcopy(row["arms"])
        for arm in ("full_history", "ace"):
            stable[arm].update(old_before_accuracy=0.9, old_after_accuracy=0.9)
        drift = deepcopy(stable)
        drift["delayed"]["future_accuracy"] -= 0.25
        data.append({"seed": row["seed"], "complete": True,
                     "conditions": {"reuse": stable, "drift": drift}})
    result = diagnose(data, conditions=["reuse", "drift"])
    assert result["drift_minus_stable"]["delayed"]["mean"] == -0.25
    assert result["delayed_minus_control_drift_change"]["full_history"]["upper"] < 0
    assert result["confirmatory_headline_test"] is False
    with pytest.raises(ValueError, match="all prespecified"):
        diagnose(data[:-1], conditions=["reuse", "drift"])
