"""Evaluator-only streams for prospective delayed-corroboration experiments.

No reference SQL, recipe, family, binding, seed or expected answer is a learner
input. Fresh rows are unconditional draws, including empty/degenerate outcomes.
The Python oracle and SQLite reference are independently implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

from .sql_env_v8 import (
    EpisodeSpec,
    PublicEpisode,
    SemanticRecipe,
    _Convention,
    _base_sql,
    _convention,
    _names,
    _seed,
    _world,
)

VERSION = "delayed-stream-1"
FAMILIES = (
    ("gross", "channel", "web", "store"),
    ("gross", "region", "North", "South"),
    ("gross", "tier", "Gold", "Silver"),
    ("net", "region", "North", "South"),
    ("net", "tier", "Gold", "Silver"),
    ("net", "channel", "web", "store"),
    ("gross", "status", "confirmed", "cancelled"),
    ("net", "status", "confirmed", "cancelled"),
)
CONDITIONS = ("reuse", "drift", "nonreuse")
SPLITS = ("development", "sizing", "confirmation", "diagnostic")
OPERATIONS = {
    "sum": ("total", "SUM({v})"),
    "mean": ("average", "AVG({v})"),
    "max": ("largest", "MAX({v})"),
    "min": ("smallest", "MIN({v})"),
    "range": ("range (largest minus smallest)", "MAX({v})-MIN({v})"),
    "variance": ("population variance", "AVG({v}*{v})-AVG({v})*AVG({v})"),
    "mean_square": ("mean squared", "AVG({v}*{v})"),
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class CampaignStream:
    ordinary: tuple[EpisodeSpec, ...]
    old_panel: tuple[EpisodeSpec, ...]
    final_panel: tuple[EpisodeSpec, ...]
    seed: int
    split: str
    condition: str


def oracle(values, operation):
    values = [x for x in values if x is not None]
    if not values:
        return 0.0
    if operation == "sum":
        return math.fsum(values)
    if operation == "mean":
        return math.fsum(values) / len(values)
    if operation == "max":
        return max(values)
    if operation == "min":
        return min(values)
    if operation == "range":
        return max(values) - min(values)
    if operation == "mean_square":
        return math.fsum(x * x for x in values) / len(values)
    if operation == "variance":
        mean = math.fsum(values) / len(values)
        return math.fsum((x - mean) ** 2 for x in values) / len(values)
    raise ValueError("unknown operation")


def make_episode(seed, split, condition, phase, index, *, old_replicates=8):
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("nonnegative 63-bit stream seed required")
    if split not in SPLITS or condition not in CONDITIONS:
        raise ValueError("unknown split or condition")
    if phase not in ("ordinary", "old_before", "old_after", "final"):
        raise ValueError("unknown phase")
    if type(old_replicates) is not int or old_replicates < 1:
        raise ValueError("positive old-panel replication count required")
    if type(index) is not int or not 0 <= index < (
        24 if phase == "ordinary" else 32 if phase == "final" else 8 * old_replicates
    ):
        raise ValueError("episode index outside declared schedule")
    family = index % 8
    measure, field, initial, changed = FAMILIES[family]
    old = phase in ("old_before", "old_after")
    cohort = "old" if old else phase
    block = index // 8
    binding = initial if old or (phase == "ordinary" and block == 0) else changed
    if phase == "ordinary":
        operation = (
            "sum" if block < 2 else ("mean" if split in ("development", "sizing") else "min")
        )
    elif old:
        operation = "sum"
    else:
        # Different outer-expression sets in development and confirmation.
        operations = (
            ("mean", "max", "variance", "mean_square")
            if split in ("development", "sizing")
            else ("min", "max", "range", "variance")
        )
        operation = operations[block]
        binding = (initial, changed)[block % 2]
    convention_split = "heldout" if split == "confirmation" else "development"
    names_seed = _seed(seed, "campaign_names")
    conventions = _convention(_seed(seed, "campaign_conventions"), convention_split)
    drifted = condition == "drift" and not old and (phase == "final" or index >= 8)
    if drifted:
        conventions = _Convention(*(not x for x in vars(conventions).values()))
    if condition == "nonreuse":
        # Old probes retain the corresponding initial episode's vocabulary.
        source_index = family if old else index
        names_seed = _seed(seed, "campaign_names", cohort if not old else "ordinary", source_index)
        conventions = _convention(
            _seed(seed, "campaign_conventions", source_index), convention_split
        )
    names = _names(names_seed)
    data_seed = _seed(seed, "campaign_rows", cohort, index)
    tables, lines, _ = _world(data_seed, names, conventions)
    values = [r[measure] for r in lines if r[field] == binding]
    expected = float(oracle(values, operation))
    expression = OPERATIONS[operation][1].format(v=measure)
    reference = _base_sql(names, conventions) + (
        f"SELECT COALESCE({expression},0) FROM lines WHERE {field}='{binding}'"
    )
    scope = {
        "channel": f"orders placed through the {binding} channel",
        "region": f"orders for customers currently in the {binding} region",
        "tier": f"orders for customers currently in the {binding} tier",
        "status": f"orders with status {binding}",
    }[field]
    description = f"What is the {OPERATIONS[operation][0]} {measure} order value among {scope}?"
    if measure == "net":
        description += (
            " Net order value is gross order value minus the sum of that order's refunds."
        )
    if operation == "variance":
        description += " Use the population denominator, not a sample correction."
    description += (
        " Gross order value is unit amount times quantity. Follow the catalog's units,"
        " NULL and current-profile conventions. Return one finite number without rounding;"
        " an empty or undefined aggregate is zero."
    )
    if condition == "drift" and phase == "ordinary" and index == 8:
        description = (
            "The warehouse has migrated; consult its current catalog before reuse. " + description
        )
    definition = {
        "family": family,
        "measure": measure,
        "filter": field,
        "binding": binding,
        "operation": operation,
    }
    recipe = SemanticRecipe(
        normalized_query=(operation, measure, field, "<binding>"),
        dependencies=(),
        required_relations=(measure,),
        required_subskills=(measure, field),
        fingerprint=digest(definition),
    )
    metadata = {
        "generator": VERSION,
        "seed": seed,
        "split": split,
        "condition": condition,
        "phase": phase,
        "index": index,
        "cohort": cohort,
        "data_seed": data_seed,
        "names_seed": names_seed,
        "data_sha256": digest([(t.name, t.columns, t.rows) for t in tables]),
        "definition": definition,
        "drifted": drifted,
        "old_replicates": old_replicates,
    }
    return EpisodeSpec(
        PublicEpisode(description, "\n".join(t.ddl for t in tables)),
        tables,
        expected,
        reference,
        recipe,
        tuple(metadata.items()),
    )


def make_stream(seed, condition="reuse", split="development", *, old_replicates=8):
    def panel(phase, count):
        return tuple(
            make_episode(seed, split, condition, phase, i, old_replicates=old_replicates)
            for i in range(count)
        )

    return CampaignStream(
        panel("ordinary", 24),
        panel("old_before", 8 * old_replicates),
        panel("final", 32),
        seed,
        split,
        condition,
    )


def schedule(*, old_replicates=8, stage="complete"):
    if stage == "qualification":
        return [("ordinary", i) for i in range(24)] + [("final", i) for i in range(8)]
    if stage != "complete":
        raise ValueError("unknown campaign stage")
    return (
        [("ordinary", i) for i in range(8)]
        + [("old_before", i) for i in range(8 * old_replicates)]
        + [("ordinary", i) for i in range(8, 24)]
        + [("old_after", i) for i in range(8 * old_replicates)]
        + [("final", i) for i in range(32)]
    )
