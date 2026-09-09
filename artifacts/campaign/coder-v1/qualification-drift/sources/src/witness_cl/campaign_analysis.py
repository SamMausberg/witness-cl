"""Prespecified stream-level contrasts and prospective power, not model results."""

from __future__ import annotations

import math
import numpy as np
from scipy.stats import beta, nct, norm, t

ALPHA = 0.01
ENDPOINT_POWER = 0.96
CONTROLS = ("full_history", "ace")
ENDPOINT_NAMES = (
    "accuracy_full_history",
    "accuracy_ace",
    "tokens_full_history",
    "tokens_ace",
    "retention",
)
PLANNING_SLACK = np.asarray([0.05, 0.05, 0.10, 0.10, 0.02])


def _numbers(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("at least two finite independent stream values required")
    return values


def lower_bound(values, *, variance_floor=0.0):
    values = _numbers(values)
    sd = float(values.std(ddof=1))
    effective_sd = max(sd, variance_floor)
    return {
        "n": len(values),
        "mean": float(values.mean()),
        "sd": sd,
        "effective_sd": effective_sd,
        "lower": float(
            values.mean()
            - t.ppf(1 - ALPHA, len(values) - 1) * effective_sd / math.sqrt(len(values))
        ),
        "one_sided_alpha": ALPHA,
        "method": "paired_stream_t_with_prespecified_sd_floor",
    }


def contrasts(rows):
    if not rows or len({r["seed"] for r in rows}) != len(rows):
        raise ValueError("unique independent stream rows required")
    result, scales = [], []
    for row in rows:
        if row.get("complete") is not True:
            raise ValueError("incomplete assigned stream cannot enter confirmatory analysis")
        arms = row["arms"]
        d = arms["delayed"]
        result.append(
            [
                *(d["future_accuracy"] - arms[a]["future_accuracy"] for a in CONTROLS),
                *(0.8 * arms[a]["total_tokens"] - d["total_tokens"] for a in CONTROLS),
                d["old_after_accuracy"] - d["old_before_accuracy"],
            ]
        )
    values = np.asarray(result, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("finite complete measurements required")
    scales = np.asarray(
        [1.0, 1.0, *(np.mean([r["arms"][a]["total_tokens"] for r in rows]) for a in CONTROLS), 1.0]
    )
    if (scales <= 0).any():
        raise ValueError("positive known control token totals required")
    return values, scales


def analyze(rows, *, frozen_n):
    if type(frozen_n) is not int or frozen_n < 2 or len(rows) != frozen_n:
        raise ValueError("all and exactly the prespecified independent streams required")
    values, scales = contrasts(rows)
    endpoints = {}
    for j, name in enumerate(ENDPOINT_NAMES):
        endpoint = lower_bound(values[:, j], variance_floor=0.10 * scales[j])
        endpoint["null_boundary"] = -0.02 if name == "retention" else 0.0
        endpoint["passed"] = endpoint["lower"] > endpoint["null_boundary"]
        endpoints[name] = endpoint
    for a in CONTROLS:
        den = sum(r["arms"][a]["total_tokens"] for r in rows)
        endpoints["tokens_" + a]["aggregate_token_ratio"] = (
            sum(r["arms"]["delayed"]["total_tokens"] for r in rows) / den
        )
    return {
        "unit": "independent_stream",
        "n": len(rows),
        "familywise_alpha": 0.05,
        "all_five_pass": all(x["passed"] for x in endpoints.values()),
        "endpoints": endpoints,
        "scope": "normal/large-sample paired-stream inference; no universal retention theorem",
    }


def size_study(rows, *, minimum_n=48):
    if len(rows) != 32:
        raise ValueError("exactly the 32 prespecified sizing streams are required")
    values, scales = contrasts(rows)
    sd = np.maximum(values.std(axis=0, ddof=1) / scales, 0.10)
    n = minimum_n

    def powers(count):
        return nct.sf(t.ppf(1 - ALPHA, count - 1), count - 1, np.sqrt(count) * PLANNING_SLACK / sd)

    while np.min(powers(n)) < ENDPOINT_POWER:
        n += 1
    return {
        "streams": n,
        "normalized_paired_sd": sd.tolist(),
        "planning_slack": PLANNING_SLACK.tolist(),
        "endpoint_power": powers(n).tolist(),
        "joint_power_union_lower": float(1 - np.sum(1 - powers(n))),
        "normal_coefficient": float((norm.ppf(1 - ALPHA) + norm.ppf(ENDPOINT_POWER)) ** 2),
        "minimum_n": minimum_n,
        "pilot_n": 32,
        "endpoints": list(ENDPOINT_NAMES),
        "status": "prospective_normal_model_planning_not_power_guarantee",
    }


def joint_power_simulation(rows, n, *, trials=100000, seed=271828, batch_size=256):
    """Simulate the exact five-test rule under the declared normal planning model.

    Pilot correlations supply dependence; conservative marginal SD floors supply
    scale. Zero-variance pilot columns use independent dependence assumptions.
    This does not turn a normal-model forecast into a distribution-free guarantee.
    """
    values, scales = contrasts(rows)
    standardized = values / scales
    raw_sd = standardized.std(axis=0, ddof=1)
    sd = np.maximum(raw_sd, 0.10)
    covariance = np.cov(standardized, rowvar=False)
    correlation = np.eye(5)
    for i in range(5):
        for j in range(i):
            if raw_sd[i] > 0 and raw_sd[j] > 0:
                correlation[i, j] = correlation[j, i] = covariance[i, j] / (raw_sd[i] * raw_sd[j])
    # Numerical roundoff can leave a nearly singular sample correlation matrix.
    eig, vec = np.linalg.eigh(correlation)
    correlation = (vec * np.maximum(eig, 1e-12)) @ vec.T
    norm_diag = np.sqrt(np.diag(correlation))
    correlation /= np.outer(norm_diag, norm_diag)
    factor = np.linalg.cholesky(correlation) * sd[:, None]
    rng = np.random.default_rng(seed)
    successes = 0
    critical = t.ppf(1 - ALPHA, n - 1)
    for start in range(0, trials, batch_size):
        count = min(batch_size, trials - start)
        sample = rng.standard_normal((count, n, 5)) @ factor.T
        means = sample.mean(axis=1) + PLANNING_SLACK
        observed_sd = np.maximum(sample.std(axis=1, ddof=1), 0.10)
        successes += int(np.all(means - critical * observed_sd / np.sqrt(n) > 0, axis=1).sum())
    lower = float(beta.ppf(0.05, successes, trials - successes + 1)) if successes else 0.0
    return {
        "streams": n,
        "trials": trials,
        "seed": seed,
        "joint_successes": successes,
        "joint_power_estimate": successes / trials,
        "one_sided_95_mc_lower": lower,
        "planning_correlation": correlation.tolist(),
        "normalized_sd": sd.tolist(),
        "planning_distribution": "multivariate_normal",
    }


def descriptive_interval(values):
    """Two-sided exploratory paired-stream interval, separate from the headline."""
    values = _numbers(values)
    mean = float(values.mean())
    radius = float(t.ppf(0.975, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values)))
    return {"n": len(values), "mean": mean, "lower": mean - radius, "upper": mean + radius,
            "confidence": 0.95, "method": "exploratory_stream_t_no_multiplicity_adjustment"}


def diagnose(rows, *, conditions):
    """Preserve positive, zero and negative drift effects under paired seeds."""
    if conditions not in (["reuse", "drift"], ["nonreuse"]):
        raise ValueError("paired stable/drift or nonreuse diagnostics required")
    expected_n = 64 if conditions == ["reuse", "drift"] else 32
    if len(rows) != expected_n or len({row["seed"] for row in rows}) != expected_n:
        raise ValueError("all prespecified independent diagnostic streams required")
    for row in rows:
        if row.get("complete") is not True or set(row["conditions"]) != set(conditions):
            raise ValueError("complete paired diagnostic conditions required")
        for condition in conditions:
            contrasts([{"seed": row["seed"], "complete": True, "arms": row["conditions"][condition]}])
    arms = (*CONTROLS, "delayed")
    output = {"unit": "independent_stream", "n": expected_n, "conditions": conditions,
              "confirmatory_headline_test": False, "by_condition": {}}
    for condition in conditions:
        output["by_condition"][condition] = {
            arm: {metric: descriptive_interval([row["conditions"][condition][arm][metric] for row in rows])
                  for metric in ("future_accuracy", "total_tokens", "old_before_accuracy", "old_after_accuracy")}
            for arm in arms}
    if conditions == ["reuse", "drift"]:
        changes = {arm: [row["conditions"]["drift"][arm]["future_accuracy"]
                         - row["conditions"]["reuse"][arm]["future_accuracy"] for row in rows]
                   for arm in arms}
        output["drift_minus_stable"] = {arm: descriptive_interval(values) for arm, values in changes.items()}
        output["delayed_minus_control_drift_change"] = {
            arm: descriptive_interval(np.asarray(changes["delayed"]) - changes[arm]) for arm in CONTROLS}
    else:
        output["delayed_minus_control_future_accuracy"] = {
            arm: descriptive_interval([row["conditions"]["nonreuse"]["delayed"]["future_accuracy"]
                                       - row["conditions"]["nonreuse"][arm]["future_accuracy"] for row in rows])
            for arm in CONTROLS}
    return output
