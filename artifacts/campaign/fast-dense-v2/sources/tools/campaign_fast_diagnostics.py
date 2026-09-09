"""Offline arithmetic for the complete separate 240-record descriptive study.

Call only after replay and real-model receipt validation. No generation,
retention inference, variance transport, efficacy decision, or sizing occurs.
"""

from collections import Counter
import statistics

from tools.campaign import sampling_seed
from tools.campaign_pilot_report import lifecycle_funnel
from tools.publish_campaign import no_test_double

SEEDS = (101300, 101301)
ARMS = ("full_history", "ace", "delayed")
OLD = (0, 3, 4, 6)
FINAL = {0: "mean", 3: "mean", 9: "max", 12: "max", 18: "variance",
         23: "variance", 29: "mean_square", 30: "mean_square"}
PHASES = {"ordinary": tuple(range(24)), "old_before": OLD, "old_after": OLD,
          "final": tuple(FINAL)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def moments(values):
    require(len(values) == 2, "exactly two independent stream contrasts required")
    return {"streams": 2, "values": values, "mean": statistics.mean(values),
            "sample_variance": statistics.variance(values), "sample_standard_deviation": statistics.stdev(values),
            "variance_degrees_of_freedom": 1, "descriptive_only": True}


def describe_complete(records, events):
    no_test_double(records)
    no_test_double(events)
    positions = {(row["seed"], row["arm"], row["phase"], row["index"]): row for row in records}
    expected = {(seed, arm, phase, index) for seed in SEEDS for arm in ARMS
                for phase, indices in PHASES.items() for index in indices}
    require(len(records) == 240 and len(positions) == 240 and set(positions) == expected,
            "all and exactly the 240 assigned observations are required")
    for row in records:
        trace = row["trace"]
        require(row["condition"] == "reuse" and trace["status"] in {"completed", "no_valid_answer"}
                and type(trace["reward"]) in (int, float) and trace["reward"] in (0, 1),
                "complete real binary outcomes required")
    for event in events:
        key = tuple(event[name] for name in ("seed", "arm", "phase", "index"))
        require(key in positions and event["condition"] == "reuse"
                and type(event["qualifying_event"]) is bool,
                "mechanism event does not belong to this complete study")
    rows, pairs = [], []
    for seed in SEEDS:
        for arm in ARMS:
            selected = [positions[(seed, arm, phase, index)] for phase, indices in PHASES.items()
                        for index in indices]
            relevant_events = [event for event in events if event["seed"] == seed and event["arm"] == arm]
            counts = Counter()
            for index in OLD:
                before, after = (positions[(seed, arm, phase, index)] for phase in ("old_before", "old_after"))
                bt, at = before["trace"], after["trace"]
                require(before["sampling_seed"] == after["sampling_seed"]
                        == sampling_seed(seed, "old_before", index), "old paired decoding seed differs")
                require(bt["question"] == at["question"] and bt["schema"] == at["schema"],
                        "old paired public task differs")
                for name in ("data_sha256", "data_seed", "definition", "generator", "split", "seed", "condition"):
                    require(bt["evaluator"][name] == at["evaluator"][name], "old paired fixture differs")
                b, a = int(bt["reward"]), int(at["reward"])
                state = {(0, 0): "both_wrong", (0, 1): "wrong_to_correct",
                         (1, 0): "correct_to_wrong", (1, 1): "both_correct"}[(b, a)]
                counts[state] += 1
                pairs.append({"seed": seed, "arm": arm, "index": index,
                              "data_sha256": bt["evaluator"]["data_sha256"],
                              "sampling_seed": before["sampling_seed"], "before_correct": b,
                              "after_correct": a, "after_minus_before": a - b, "pair_state": state})
            future = []
            for operation in ("mean", "max", "variance", "mean_square"):
                indices = [index for index, name in FINAL.items() if name == operation]
                selected_final = [positions[(seed, arm, "final", index)] for index in indices]
                require(all(row["trace"]["evaluator"]["definition"]["operation"] == operation
                            for row in selected_final), "frozen final operation label differs")
                correct = sum(row["trace"]["reward"] == 1 for row in selected_final)
                future.append({"operation": operation, "indices": indices, "n": 2,
                               "correct": correct, "accuracy": correct / 2})
            before_correct = counts["both_correct"] + counts["correct_to_wrong"]
            after_correct = counts["both_correct"] + counts["wrong_to_correct"]
            rows.append({"seed": seed, "arm": arm,
                "lifecycle_funnel": lifecycle_funnel(selected, relevant_events),
                "qualifying_events": sum(event["qualifying_event"] for event in relevant_events),
                "future": {"n": 8, "correct": sum(row["correct"] for row in future),
                           "accuracy": sum(row["correct"] for row in future) / 8, "by_outer_operation": future},
                "retention": {"paired_n": 4, "before_correct": before_correct, "after_correct": after_correct,
                    "after_minus_before": (after_correct - before_correct) / 4,
                    "discordant_pairs": counts["wrong_to_correct"] + counts["correct_to_wrong"],
                    **{name: counts[name] for name in ("both_wrong", "both_correct", "wrong_to_correct", "correct_to_wrong")}}})
    by_arm = {}
    for arm in ARMS:
        selected = [row for row in rows if row["arm"] == arm]
        operations = {}
        for operation in ("mean", "max", "variance", "mean_square"):
            correct = sum(item["correct"] for row in selected for item in row["future"]["by_outer_operation"]
                          if item["operation"] == operation)
            operations[operation] = {"n": 4, "correct": correct, "accuracy": correct / 4}
        correct = sum(row["future"]["correct"] for row in selected)
        by_arm[arm] = {"streams": 2,
            "future": {"n": 16, "correct": correct, "accuracy": correct / 16,
                       "remaining_observed_error_rate": 1 - correct / 16, "by_outer_operation": operations},
            "retention": {"paired_n": 8,
                "stream_contrasts": moments([row["retention"]["after_minus_before"] for row in selected])},
            "lifecycle_funnel": {name: sum(row["lifecycle_funnel"][name] for row in selected) for name in (
                "own_source_admissions", "later_corroborations", "ever_eligible_relations", "retrieved_relations",
                "executed_relations", "qualifying_chains", "evicted_relations")},
            "qualifying_events": sum(row["qualifying_events"] for row in selected)}
    return {"kind": "complete_fast_study_descriptive_diagnostics", "complete_records": 240,
            "model_calls_made": 0, "stream_metrics": rows, "retention_pairs": pairs, "by_arm": by_arm,
            "retention_scope": "Four paired probes per stream; two stream contrasts with variance df=1. Inadequate for two-point noninferiority or calibrating 64-probe retention variance.",
            "variance_units": "squared accuracy proportions; stream contrast granularity is 0.25",
            "zero_variance_scope": "Observed zero variance does not establish zero population variance.",
            "inference_or_sizing_performed": False, "original_32_stream_pilot_completed": False}
