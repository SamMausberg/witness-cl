"""The diagnostic cannot cherry-pick earlier scalars or impute missing values."""

from copy import deepcopy

import pytest

from tools.diagnose_sql_qualification import final_query_scalar


def scalar(value=0):
    return {"columns": ["answer"], "rows": [[value]], "error": None, "truncated": False}


def test_zero_is_a_present_numeric_result_and_no_queries_is_missing():
    assert final_query_scalar({"queries": [scalar()]}) == 0
    assert final_query_scalar({"queries": []}) is None


@pytest.mark.parametrize("value", [None, True, "7", float("nan"), float("inf")])
def test_non_numeric_or_nonfinite_result_is_not_a_scalar(value):
    assert final_query_scalar({"queries": [scalar(value)]}) is None


@pytest.mark.parametrize(
    "update",
    [
        {"error": "failed"},
        {"truncated": True},
        {"rows": []},
        {"rows": [[1], [2]]},
        {"columns": ["a", "b"], "rows": [[1, 2]]},
    ],
)
def test_final_invalid_query_does_not_fall_back_to_earlier_favorable_result(update):
    final = deepcopy(scalar(7))
    final.update(update)
    assert final_query_scalar({"queries": [scalar(100), final]}) is None
