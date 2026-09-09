"""Fresh Lean provenance, audit failure modes, and an executable SQL limitation.

SQLite examples instantiate the counterexample; they do not prove that Python
or SQLite refines Lean or measure a model's probability of producing bad SQL.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

from witness_cl.fragments_v8 import Fragment


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts/v10"


@pytest.fixture(scope="module")
def audit_module():
    # audit_v10 imports the frozen sibling audit.py; keep the import path local
    # to module initialization instead of changing the repository packaging.
    spec = importlib.util.spec_from_file_location(
        "witness_formal_audit_v10", ROOT / "formal/audit_v10.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "formal"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_current_source_build_kernel_inventory_and_regenerated_fixtures():
    report = json.loads((ARTIFACTS / "formal-audit.json").read_text())
    assert report["passed"] and report["pinned_toolchain_verified"]
    assert report["build_exit_code"] == report["audit_exit_code"] == 0
    assert report["theorem_count"] == len(report["theorem_axioms"]) == 90
    assert report["new_theorem_count"] == 1
    assert report["kernel_theorem_count"] == len(report["kernel_theorem_axioms"]) == 234
    assert report["kernel_inventory_complete"]
    assert set(report["theorem_axioms"]) <= set(report["kernel_theorem_axioms"])
    assert not report["source_placeholder_or_custom_axiom_tokens"]
    assert not report["kernel_custom_axioms"]
    assert not report["unexpected_unsafe_axioms"]
    assert not report["unexpected_axioms"]
    assert len(report["kernel_unsafe_specializations"]) == 6
    for source, digest in {**report["source_sha256"], **report["build_input_sha256"]}.items():
        assert hashlib.sha256((ROOT / "formal" / source).read_bytes()).hexdigest() == digest, source
    for source, digest in report["runtime_source_sha256"].items():
        assert hashlib.sha256((ROOT / source).read_bytes()).hexdigest() == digest, source
    assert (
        hashlib.sha256((ARTIFACTS / "formal-kernel-audit.lean").read_bytes()).hexdigest()
        == (report["kernel_audit_source_sha256"])
    )
    assert "WitnessCL.Intervention" in report["built_modules"]
    for key in ("executable_fixture", "statistical_fixture", "fragment_fixture"):
        fixture = report[key]
        path = ARTIFACTS / fixture["path"]
        assert fixture["exit_code"] == 0 and fixture["matches_archived_fixture"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == fixture["sha256"]
        assert path.read_bytes() == (ROOT / fixture["archived_reference"]).read_bytes()
        assert len(path.read_text().splitlines()) == fixture["line_count"]


def test_audit_rejects_frozen_output_and_symlink_alias(audit_module, tmp_path):
    for version in range(1, 10):
        with pytest.raises(ValueError, match="frozen"):
            audit_module.checked_output(ROOT / f"artifacts/v{version}/new", ROOT)
    alias = tmp_path / "alias"
    alias.symlink_to(ROOT / "artifacts/v8", target_is_directory=True)
    with pytest.raises(ValueError, match="frozen"):
        audit_module.checked_output(alias / "nested", ROOT)
    assert audit_module.checked_output(ROOT / "artifacts/v10/fresh", ROOT) == (
        ROOT / "artifacts/v10/fresh"
    )


@pytest.mark.parametrize(
    "extra",
    [
        "WITNESSCL_AXIOM WitnessCL.Hidden\n",
        "WITNESSCL_UNSAFE_AXIOM WitnessCL.UnexpectedUnsafe\n",
        "WITNESSCL_THEOREM WitnessCL.MissingDependencies\n",
        "WITNESSCL_THEOREM WitnessCL.Example\n",  # Duplicate inventory entry.
    ],
)
def test_kernel_audit_rejects_uncovered_or_unapproved_declarations(audit_module, extra):
    valid = (
        "WITNESSCL_THEOREM WitnessCL.Example\n'WitnessCL.Example' does not depend on any axioms\n"
    )
    assert audit_module.parse_kernel_audit(valid, ["WitnessCL.Example"])["axiom_audit_passed"]
    assert not audit_module.parse_kernel_audit(valid + extra, ["WitnessCL.Example"])[
        "axiom_audit_passed"
    ]


@pytest.mark.parametrize("dependency", ["sorryAx", "Lean.ofReduceBool", "WitnessCL.Custom"])
def test_kernel_audit_rejects_nonstandard_proof_dependencies(audit_module, dependency):
    output = (
        "WITNESSCL_THEOREM WitnessCL.Example\n"
        f"'WitnessCL.Example' depends on axioms: [{dependency}]\n"
    )
    result = audit_module.parse_kernel_audit(output, ["WitnessCL.Example"])
    assert not result["axiom_audit_passed"]
    assert result["unexpected_axioms"] == [dependency]


def test_kernel_audit_requires_every_authored_theorem(audit_module):
    output = (
        "WITNESSCL_THEOREM WitnessCL.Example\n'WitnessCL.Example' does not depend on any axioms\n"
    )
    assert not audit_module.parse_kernel_audit(output, ["WitnessCL.Unbuilt"])["axiom_audit_passed"]


@pytest.mark.parametrize("witnesses", [[], [0], [1, 2, 3], [0, 3, 3, 9]])
def test_relation_dependence_and_reconstruction_can_hold_while_sql_transfer_fails(witnesses):
    # The intended answer is always one. Even a real aggregate over the relation
    # can overfit its finite source contexts and remain intervention-sensitive.
    observed = ",".join(str(value) for value in witnesses)
    relation = f"SELECT CASE WHEN :context IN ({observed}) THEN 1 ELSE 2 END AS answer"
    wrapper = "SELECT COALESCE(SUM(answer),0) FROM reused"
    fitted = Fragment.from_query(relation, {"context": 0})
    emptied = Fragment.from_query("SELECT * FROM (" + relation + ") WHERE 0", {"context": 0})
    fresh = sum(witnesses) + 1
    assert fresh not in witnesses
    with sqlite3.connect(":memory:") as database:

        def answer(fragment, context):
            request = fragment.compose(wrapper, {}, alias="reused", bindings={"context": context})
            return database.execute(request.sql, request.parameters).fetchone()[0]

        for context in witnesses:
            assert answer(fitted, context) == 1
            assert answer(emptied, context) == 0
        assert answer(fitted, fresh) == 2  # Wrong despite dependence at this context too.
        assert answer(emptied, fresh) == 0
