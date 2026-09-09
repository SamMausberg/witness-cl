#!/usr/bin/env python3
"""Rebuild and audit every current Lean module without rewriting frozen evidence.

The source inventory counts authored theorems. The separate kernel inventory
also checks generated equations and private proof constants by defining module,
using the same Lean collectAxioms operation as #print axioms. Neither inventory
is a verification of Python, SQLite, or the probabilistic learning assumptions.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from audit import declarations, run


ALLOWED_AXIOMS = {"Classical.choice", "Quot.sound", "propext"}
PINNED_TOOLCHAIN = "leanprover/lean4:v4.19.0"
# Lean's native specialization pass represents these runtime helpers as unsafe
# axioms. They are not logical proof premises: collectAxioms below independently
# rejects a dependency on any of them. Inventory their exact names rather than
# allowing arbitrary unsafe declarations or silently dropping them.
EXPECTED_UNSAFE_SPECIALIZATIONS = {
    "List.filterTR.loop._at.WitnessCL.Executable.filterTrace._spec_1",
    "List.hasDecEq._at.WitnessCL.Executable.traceMatches._spec_2",
    "List.mapTR.loop._at.WitnessCL.Executable.traceMatches._spec_1",
    "List.mapTR.loop._at.WitnessCL.StatisticalBridge.scoreList._spec_1",
    "List.mapTR.loop._at.WitnessCL.TypedFragments.parameterValues._spec_1",
    "List.sum._at.WitnessCL.StatisticalBridge.scoreList._spec_2",
}


def checked_output(path: Path, root: Path) -> Path:
    """Resolve symlinks before rejecting any archived version directory."""
    output = path.resolve()
    for version in range(1, 10):
        archived = (root / "artifacts" / f"v{version}").resolve()
        if output.is_relative_to(archived):
            raise ValueError("v10 audit must not overwrite frozen v1-v9 artifacts")
    return output


def kernel_audit_source(modules: list[str]) -> str:
    return (
        "\n".join(["import Lean", *("import " + module for module in modules)])
        + """
open Lean in
run_cmd do
  let env ← getEnv
  for (name, info) in env.constants.toList do
    let some moduleIndex := env.getModuleIdxFor? name | continue
    let moduleName := env.header.moduleNames[moduleIndex.toNat]!
    if moduleName.toString == "WitnessCL" || moduleName.toString.startsWith "WitnessCL." then
      match info with
      | .thmInfo _ =>
        let axioms ← collectAxioms name
        logInfo m!"WITNESSCL_THEOREM {name}"
        if axioms.isEmpty then
          logInfo m!"'{name}' does not depend on any axioms"
        else
          logInfo m!"'{name}' depends on axioms: {axioms.qsort Name.lt |>.toList}"
      | .axiomInfo value =>
        if value.isUnsafe then
          logInfo m!"WITNESSCL_UNSAFE_AXIOM {name}"
        else
          logInfo m!"WITNESSCL_AXIOM {name}"
      | _ => pure ()
"""
    )


def parse_kernel_audit(stdout: str, authored: list[str]) -> dict:
    inventory = re.findall(r"^WITNESSCL_THEOREM (.+)$", stdout, re.M)
    custom = re.findall(r"^WITNESSCL_AXIOM (.+)$", stdout, re.M)
    unsafe = re.findall(r"^WITNESSCL_UNSAFE_AXIOM (.+)$", stdout, re.M)
    unexpected_unsafe = sorted(set(unsafe) - EXPECTED_UNSAFE_SPECIALIZATIONS)
    pattern = r"'([^']+)' (does not depend on any axioms|depends on axioms: \[([^\]]*)\])"
    parsed = {
        m[1]: [] if m[3] is None else [a.strip() for a in m[3].split(",")]
        for m in re.finditer(pattern, stdout)
    }
    unexpected = sorted({a for group in parsed.values() for a in group} - ALLOWED_AXIOMS)
    covered = (
        bool(inventory)
        and len(inventory) == len(set(inventory))
        and set(inventory) == set(parsed)
        and set(authored) <= set(parsed)
    )
    source_axioms = {name: parsed[name] for name in authored if name in parsed}
    return {
        "kernel_theorem_count": len(inventory),
        "kernel_theorem_axioms": dict(sorted(parsed.items())),
        "kernel_custom_axioms": custom,
        "kernel_unsafe_specializations": sorted(unsafe),
        "unexpected_unsafe_axioms": unexpected_unsafe,
        "kernel_inventory_complete": covered,
        "theorem_axioms": source_axioms,
        "unexpected_axioms": unexpected,
        "axiom_free_theorems": sum(not axioms for axioms in source_axioms.values()),
        "axiom_usage_counts": dict(
            sorted(Counter(a for group in source_axioms.values() for a in group).items())
        ),
        "axiom_audit_passed": covered and not custom and not unexpected and not unexpected_unsafe,
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/v10"))
    args = parser.parse_args()
    formal = Path(__file__).resolve().parent
    root = formal.parent
    try:
        output = checked_output(args.output, root)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    output.mkdir(parents=True, exist_ok=True)
    lake = os.environ.get("LAKE") or shutil.which("lake")
    if lake is None and (Path.home() / ".elan/bin/lake").is_file():
        lake = str(Path.home() / ".elan/bin/lake")
    if lake is None:
        raise SystemExit("Install the pinned toolchain or set LAKE.")

    by_file, hashes, forbidden = {}, {}, []
    files = sorted((formal / "WitnessCL").glob("*.lean"))
    modules = [
        "WitnessCL",
        *(str(p.relative_to(formal).with_suffix("")).replace("/", ".") for p in files),
    ]
    for file in files:
        names, bad = declarations(file.read_text())
        by_file[str(file.relative_to(formal))] = names
        hashes[str(file.relative_to(formal))] = digest(file)
        forbidden.extend(bad)
    names = [name for group in by_file.values() for name in group]
    if not names or len(names) != len(set(names)):
        raise SystemExit("Duplicate or empty authored theorem inventory.")

    inputs = [
        "WitnessCL.lean",
        "ExecutableFixture.lean",
        "StatisticalFixture.lean",
        "FragmentFixture.lean",
        "lakefile.toml",
        "lake-manifest.json",
        "lean-toolchain",
        "audit.py",
        "audit_v8.py",
        "audit_v10.py",
    ]
    # The legacy parser is intentionally retained for the frozen source layout.
    # Kernel enumeration below independently covers every project theorem,
    # including names that this source-level inventory does not recognize.
    for name in inputs:
        if name.endswith(".lean"):
            _, bad = declarations((formal / name).read_text())
            forbidden.extend(bad)
    version = run([lake, "env", "lean", "--version"], formal, output / "formal-version.txt")
    build = run(
        [lake, "build", *modules, "witness_fixture", "statistical_fixture"],
        formal,
        output / "formal-build.txt",
    )
    pinned = (formal / "lean-toolchain").read_text().strip() == PINNED_TOOLCHAIN and bool(
        re.search(r"Lean \(version 4\.19\.0,", version.stdout)
    )
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "abstract contracts and finite-witness limitation; no Python/SQLite refinement or learning guarantee",
        "toolchain": PINNED_TOOLCHAIN,
        "compiler": version.stdout.strip(),
        "pinned_toolchain_verified": pinned,
        "build_exit_code": build.returncode,
        "built_modules": modules,
        "theorem_count": len(names),
        "new_theorem_count": len(by_file["WitnessCL/Intervention.lean"]),
        "theorems_by_file": by_file,
        "source_sha256": hashes,
        "build_input_sha256": {name: digest(formal / name) for name in inputs},
        "runtime_source_sha256": {
            "src/witness_cl/fragments_v8.py": digest(root / "src/witness_cl/fragments_v8.py")
        },
        "source_placeholder_or_custom_axiom_tokens": forbidden,
        "allowed_standard_axioms": sorted(ALLOWED_AXIOMS),
        "passed": False,
    }
    if pinned and version.returncode == 0 and build.returncode == 0 and not forbidden:
        source = output / "formal-kernel-audit.lean"
        source.write_text(kernel_audit_source(modules))
        audit = run([lake, "env", "lean", str(source)], formal, output / "formal-axioms.txt")
        report.update(parse_kernel_audit(audit.stdout, names))
        report["kernel_audit_source_sha256"] = digest(source)
        report["audit_exit_code"] = audit.returncode
        report["passed"] = audit.returncode == 0 and report["axiom_audit_passed"]

    fixtures = [
        ("executable_fixture", "runtime", [str(formal / ".lake/build/bin/witness_fixture")], "v6"),
        (
            "statistical_fixture",
            "statistical",
            [str(formal / ".lake/build/bin/statistical_fixture")],
            "v7",
        ),
        (
            "fragment_fixture",
            "fragments",
            [lake, "env", "lean", "--run", "FragmentFixture.lean"],
            "v8",
        ),
    ]
    if report["passed"]:
        for key, stem, command, archived_version in fixtures:
            fixture = subprocess.run(
                command,
                cwd=formal,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            path = output / f"formal-{stem}.jsonl"
            path.write_text(fixture.stdout)
            (output / f"formal-{stem}-stderr.txt").write_text(fixture.stderr)
            archived = root / "artifacts" / archived_version / path.name
            report[key] = {
                "path": path.name,
                "exit_code": fixture.returncode,
                "sha256": digest(path),
                "line_count": len(fixture.stdout.splitlines()),
                "archived_reference": str(archived.relative_to(root)),
                "matches_archived_fixture": archived.is_file() and digest(path) == digest(archived),
            }
            report["passed"] = (
                report["passed"]
                and fixture.returncode == 0
                and bool(fixture.stdout)
                and report[key]["matches_archived_fixture"]
            )

    (output / "formal-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: report.get(key)
                for key in [
                    "passed",
                    "theorem_count",
                    "new_theorem_count",
                    "kernel_theorem_count",
                    "build_exit_code",
                    "audit_exit_code",
                    "axiom_free_theorems",
                    "unexpected_axioms",
                ]
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
