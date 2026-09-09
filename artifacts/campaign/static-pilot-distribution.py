"""Static frozen-generator comparison; no model calls or empirical power estimate.

Run from the repository root with its locked Python environment. The only task
fixtures constructed are synthetic local inspection fixtures; no learner runs.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path,
        default=Path("artifacts/campaign/pilot-dense-v2/manifest.json"),
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    studies = []
    reference = None
    selected = (
        "src/witness_cl/campaign_env.py",
        "src/witness_cl/sql_env_v8.py",
        "src/witness_cl/campaign_analysis.py",
        "tools/campaign.py",
    )
    for study in manifest["studies"]:
        directory = Path(study["path"])
        freeze_path = directory / "freeze.json"
        freeze = json.loads(freeze_path.read_text())
        if freeze["seeds"] != study["seeds"]:
            raise ValueError("study assignment differs from pilot manifest")
        sources = directory / "sources"
        for name, expected in freeze["source_sha256"].items():
            if sha256(sources / name) != expected:
                raise ValueError(f"frozen source mismatch: {sources / name}")
        hashes = {name: freeze["source_sha256"][name] for name in selected}
        policy = {key: freeze[key] for key in (
            "split", "conditions", "arms", "old_replicates", "limits", "client_config",
            "cold_start_each_episode", "sampling_seed_policy",
        )}
        identity = {"hashes": hashes, "policy": policy}
        if reference is not None and identity != reference:
            raise ValueError("pilot studies differ in inspected generator, analysis or policy")
        reference = identity
        studies.append({
            "path": str(directory), "freeze_sha256": sha256(freeze_path),
            "created_utc": freeze["created_utc"], "seeds": freeze["seeds"],
            "source_sha256": hashes,
        })
    all_seeds = [seed for study in studies for seed in study["seeds"]]
    if sorted(all_seeds) != sorted(manifest["expected_seeds"]) or len(set(all_seeds)) != 32:
        raise ValueError("exactly the 32 assigned unique pilot streams are required")

    # Import the verified frozen generator; avoid even bytecode writes there.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(sources / "src"))
    from witness_cl.campaign_env import FAMILIES, make_episode, schedule
    from witness_cl.sql_env_v8 import _Convention, _convention, evaluator_metadata

    distributions = {}
    for label, split, stage in (
        ("cold_qualification", "development", "qualification"),
        ("full_development", "development", "complete"),
        ("legacy_sizing", "sizing", "complete"),
        ("unlaunched_ood_confirmation_template", "confirmation", "complete"),
        ("unlaunched_diagnostic_template", "diagnostic", "complete"),
    ):
        phase_operations = {}
        blocks = {}
        for phase, index in schedule(stage=stage):
            definition = evaluator_metadata(make_episode(0, split, "reuse", phase, index))["definition"]
            operation = definition["operation"]
            phase_operations.setdefault(phase, Counter())[operation] += 1
            if phase in ("ordinary", "final") and index % 8 == 0:
                family = FAMILIES[definition["family"]]
                binding = "initial" if definition["binding"] == family[2] else "changed"
                blocks[f"{phase}_{index:02d}_{index + 7:02d}"] = {
                    "operation": operation, "binding": binding,
                }
        convention_split = "heldout" if split == "confirmation" else "development"
        combinations = sorted({
            tuple(vars(_convention(seed, convention_split)).values()) for seed in range(512)
        })
        expected_parity = int(convention_split == "heldout")
        if len(combinations) != 8 or any(sum(bits) % 2 != expected_parity for bits in combinations):
            raise ValueError("unexpected convention support")
        distributions[label] = {
            "split": split, "stage": stage,
            "phase_operation_counts": phase_operations, "blocks": blocks,
            "convention_parity": expected_parity, "convention_combinations": combinations,
        }
    analysis_name = "src/witness_cl/campaign_analysis.py"
    floor_lines = [
        {"line": number, "text": line.strip()}
        for number, line in enumerate((sources / analysis_name).read_text().splitlines(), 1)
        if "0.10" in line and ("maximum(" in line or "variance_floor=" in line)
    ]
    def distribution_identity(name):
        return {key: value for key, value in distributions[name].items() if key != "split"}

    report = {
        "kind": "static_frozen_distribution_inspection",
        "model_calls": 0, "observed_outcomes_used": 0,
        "scope": "No pilot ceiling, variance, mechanism frequency or confirmation power is estimated.",
        "calculator_sha256": sha256(Path(__file__)),
        "pilot_manifest_sha256": sha256(args.manifest),
        "studies": studies, "convention_bit_order": list(_Convention.__dataclass_fields__),
        "distributions": distributions,
        "retention_floor_source": {"path": analysis_name, "locations": floor_lines},
        "pilot_matches_legacy_sizing_distribution": (
            distribution_identity("full_development") == distribution_identity("legacy_sizing")
        ),
        "pilot_matches_unlaunched_ood_confirmation_distribution": (
            distribution_identity("full_development")
            == distribution_identity("unlaunched_ood_confirmation_template")
        ),
        "recommendation": "After the complete pilot, default to fresh independent streams from the same generator; any OOD claim needs separate calibration.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
