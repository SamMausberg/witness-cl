#!/usr/bin/env python3
"""Posthoc final-query scalar diagnostics; never changes qualification scores."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from witness_cl.sql_env_v9 import make_stream, open_episode


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def final_query_scalar(trace):
    """Only the final recorded query; no fallback to a favorable earlier query."""
    if not trace["queries"]:
        return None
    query = trace["queries"][-1]
    if (
        query["error"] is not None
        or query["truncated"] is not False
        or len(query["columns"]) != 1
        or len(query["rows"]) != 1
        or len(query["rows"][0]) != 1
    ):
        return None
    value = query["rows"][0][0]
    return value if type(value) in (int, float) and math.isfinite(value) else None


def diagnose(directory):
    directory = Path(directory)
    frozen = json.loads((directory / "freeze.json").read_text())
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["status"] == "running":
        raise ValueError("qualification is still running")
    if manifest["freeze_sha256"] != sha(directory / "freeze.json") or manifest["raw_sha256"] != sha(
        directory / "episodes.jsonl"
    ):
        raise ValueError("qualification input hashes differ from final manifest")
    for name in ("src/witness_cl/sql_env_v8.py", "src/witness_cl/sql_env_v9.py"):
        if frozen["source_sha256"][name] != sha(ROOT / name):
            raise ValueError("diagnostic evaluator differs from executed evaluator")
    rows = [json.loads(s) for s in (directory / "episodes.jsonl").read_text().splitlines()]
    details = []
    for row in rows:
        scalar = final_query_scalar(row)
        scalar_correct = False
        if scalar is not None:
            spec = make_stream(row["seed"], "reuse", split="development").ordinary[
                row["episode_index"]
            ]
            with open_episode(spec, allow_learning_checks=False) as session:
                scalar_correct = session.answer(scalar).reward == 1
        details.append(
            {
                "seed": row["seed"],
                "episode_index": row["episode_index"],
                "family": "warm" if row["episode_index"] < 8 else "composition",
                "observed_answer": row["answer"],
                "observed_answer_correct": row["reward"] == 1,
                "final_query_scalar": scalar,
                "final_query_scalar_available": scalar is not None,
                "final_query_scalar_correct": scalar_correct,
            }
        )
    groups = []
    for seed in frozen["seeds"]:
        for family in ("warm", "composition"):
            selected = [r for r in details if r["seed"] == seed and r["family"] == family]
            groups.append(
                {
                    "seed": seed,
                    "family": family,
                    "n": len(selected),
                    "observed_answer_correct": sum(r["observed_answer_correct"] for r in selected),
                    "final_query_scalar_available": sum(
                        r["final_query_scalar_available"] for r in selected
                    ),
                    "final_query_scalar_correct": sum(
                        r["final_query_scalar_correct"] for r in selected
                    ),
                    "wrong_answer_with_correct_final_scalar": sum(
                        not r["observed_answer_correct"] and r["final_query_scalar_correct"]
                        for r in selected
                    ),
                }
            )
    return {
        "kind": "posthoc_final_query_scalar_diagnostic",
        "model_calls": 0,
        "input_directory": str(directory),
        "freeze_sha256": manifest["freeze_sha256"],
        "raw_sha256": manifest["raw_sha256"],
        "manifest_sha256": sha(directory / "manifest.json"),
        "diagnostic_source_sha256": sha(__file__),
        "observed_qualified": manifest["qualified"],
        "groups": groups,
        "episodes": details,
        "scope": "Final recorded query only, if complete finite 1x1 numeric. Evaluator scoring is posthoc; observed gates unchanged. This neither predicts a new interface nor establishes causal model dependence.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    for directory in args.directories:
        if args.out.resolve().is_relative_to(directory.resolve()):
            parser.error("diagnostics must be written outside immutable qualification directories")
    result = {"qualification_runs": [diagnose(directory) for directory in args.directories]}
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            [
                {k: r[k] for k in ("observed_qualified", "groups")}
                for r in result["qualification_runs"]
            ]
        )
    )


if __name__ == "__main__":
    main()
