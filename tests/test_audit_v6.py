"""Tamper tests for saved-data replay; no agent, planner or experiment is run."""
from __future__ import annotations

import copy
import csv
import gzip
from itertools import product
import json

import pytest

from experiments.audit_v6 import audit
from witness_cl.latent import Machine, Program


@pytest.fixture(scope="module")
def valid_evidence():
    programs = tuple(Program.word(word, 3) for word in product(range(2), repeat=3))
    # Reset outputs are zero in the actual world. At the start, 001 can lose at
    # most two reward units against 000 because only their final action differs.
    world = Machine(2, 2, 3, ((0, 0),) * 4)
    universe = tuple(Machine(2, 2, 3, table)
                     for table in product(tuple(product(range(2), range(3))), repeat=4))
    compatible = universe
    rows = []
    for episode, chosen in enumerate((1, 0)):
        trace = programs[chosen].rollout(world)
        compatible = tuple(m for m in compatible if programs[chosen].rollout(m) == trace)
        rows.append(dict(seed=61000, method="optimistic_B16", episode=episode,
                         goal=0, program=chosen, trace=json.dumps(trace), reward=0, anchor=0,
                         prefix_deficit=0, guarded="True", incumbents_before="[0, 0]",
                         incumbents_after="[0, 0]", debit=2 if episode == 0 else 0,
                         spent=2, status="exact", compatible_models=len(compatible),
                         plan_lower=-2 if episode == 0 else 0,
                         plan_upper=2 if episode == 0 else 0))
    summary = dict(episode_rows=2, seeds=1, episodes=2, methods=["optimistic_B16"],
                   worlds_evaluator_only=[dict(seed=61000, table=world.table)],
                   per_seed=[dict(seed=61000, method="optimistic_B16", mean_return=0.0)])
    return summary, rows


def write_evidence(directory, summary, rows):
    directory.mkdir()
    (directory / "summary.json").write_text(json.dumps(summary))
    with gzip.open(directory / "episodes.csv.gz", "wt", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return directory


def test_valid_independent_small_transcript_passes_saved_data_replay(tmp_path, valid_evidence):
    summary, rows = valid_evidence
    result = audit(write_evidence(tmp_path / "valid", summary, rows))
    assert result["violations"] == 0
    assert result["guarded_prefixes"] == 2 and result["episodes"] == 2


@pytest.mark.parametrize("tamper", [
    "refunded_ledger", "altered_reward", "false_promotion", "insufficient_debit",
    "altered_trace", "wrong_coverage", "wrong_prefix", "unknown_changes_action",
    "negative_program", "guard_flag_bypass",
])
def test_saved_data_replay_rejects_tampered_transcript(tmp_path, valid_evidence, tamper):
    summary, original = valid_evidence
    rows = copy.deepcopy(original)
    if tamper == "refunded_ledger":
        rows[1]["spent"] = 0
    elif tamper == "altered_reward":
        rows[0]["reward"] = 1
    elif tamper == "false_promotion":
        rows[0]["incumbents_after"] = "[1, 0]"
    elif tamper == "insufficient_debit":
        rows[0]["debit"] = rows[0]["spent"] = rows[1]["spent"] = 1
    elif tamper == "altered_trace":
        rows[0]["trace"] = "[[0, 0], [0, 0], [1, 1]]"
    elif tamper == "wrong_coverage":
        rows[1]["compatible_models"] += 1
    elif tamper == "wrong_prefix":
        rows[1]["prefix_deficit"] = -1
    elif tamper == "unknown_changes_action":
        rows[0]["status"] = "unknown"
    elif tamper == "negative_program":
        # -7 indexes the same program as 1 in Python, but is not a legal program ID.
        rows[0]["program"] = -7
    elif tamper == "guard_flag_bypass":
        rows[1]["guarded"] = "False"
        rows[1]["spent"] = 0
    with pytest.raises((AssertionError, ValueError)):
        audit(write_evidence(tmp_path / tamper, summary, rows))
