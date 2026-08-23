"""Enforce a deterministic coverage floor for changed Python source files."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import coverage

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "quality" / "quality-policy.v1.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "output" / "changed-coverage-gate.json"


def _changed_source_files(*, base_ref: str, head_ref: str, source_root: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base_ref}...{head_ref}",
            "--",
            source_root,
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(
        {
            path.replace("\\", "/")
            for path in result.stdout.splitlines()
            if path.replace("\\", "/").endswith(".py")
        }
    )


def _coverage_percent(cov: coverage.Coverage, path: Path) -> dict[str, Any]:
    _, statements, _, missing, missing_display = cov.analysis2(str(path))
    statement_count = len(statements)
    missing_count = len(missing)
    percent = (
        100.0
        if statement_count == 0
        else 100.0 * (statement_count - missing_count) / statement_count
    )
    try:
        display_path = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display_path = path.as_posix()
    return {
        "file": display_path,
        "covered_statements": statement_count - missing_count,
        "missing_statements": missing_count,
        "statement_count": statement_count,
        "percent": round(percent, 2),
        "missing_lines": missing_display,
    }


def _load_policy(path: Path) -> tuple[str, int | float]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    version = policy.get("policy_version")
    threshold = policy.get("coverage", {}).get("changed_source_min_percent")
    if not isinstance(version, str) or not version:
        raise ValueError(f"Quality policy {path} must define a non-empty policy_version.")
    if not isinstance(threshold, (int, float)) or not 0 < threshold <= 100:
        raise ValueError(
            f"Quality policy {path} must define coverage.changed_source_min_percent in (0, 100]."
        )
    return version, threshold


def evaluate_changed_files(
    *,
    changed_files: list[str],
    coverage_data: Path,
    minimum_percent: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    cov = coverage.Coverage(data_file=str(coverage_data))
    cov.load()
    measurements: list[dict[str, Any]] = []
    failures: list[str] = []
    for relative_file in changed_files:
        path = REPO_ROOT / relative_file
        measurement = _coverage_percent(cov, path)
        measurement["threshold_percent"] = minimum_percent
        measurements.append(measurement)
        if measurement["percent"] < minimum_percent:
            failures.append(
                f"{relative_file}: measured {measurement['percent']:.2f}% < "
                f"threshold {minimum_percent:.2f}% "
                f"({measurement['missing_statements']} missing of "
                f"{measurement['statement_count']} executable statements; "
                f"lines {measurement['missing_lines'] or 'none'})"
            )
    return measurements, failures


def run_gate(
    *,
    base_ref: str,
    head_ref: str,
    coverage_data: Path,
    policy_path: Path,
    output_path: Path,
) -> int:
    policy_version, minimum_percent = _load_policy(policy_path)
    changed_files = _changed_source_files(
        base_ref=base_ref,
        head_ref=head_ref,
        source_root="src",
    )
    measurements, failures = evaluate_changed_files(
        changed_files=changed_files,
        coverage_data=coverage_data,
        minimum_percent=minimum_percent,
    )
    report = {
        "schema_version": "lotus.advise.changed-coverage-gate.v1",
        "policy_version": policy_version,
        "base_ref": base_ref,
        "head_ref": head_ref,
        "threshold_percent": minimum_percent,
        "changed_source_files": measurements,
        "exceptions": [],
        "status": "failed" if failures else "passed",
        "failures": failures,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not changed_files:
        print(
            f"Changed source coverage gate passed: no changed Python source files "
            f"(policy={policy_version}, threshold={minimum_percent:.2f}%)."
        )
        return 0
    if failures:
        print(
            f"Changed source coverage gate FAILED (policy={policy_version}, "
            f"threshold={minimum_percent:.2f}%)."
        )
        for failure in failures:
            print(f"- {failure}")
        print(f"Machine-readable evidence: {output_path}")
        return 1
    print(
        f"Changed source coverage gate passed for {len(changed_files)} file(s) "
        f"(policy={policy_version}, threshold={minimum_percent:.2f}%)."
    )
    print(f"Machine-readable evidence: {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--coverage-data", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    return run_gate(
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        coverage_data=args.coverage_data,
        policy_path=args.policy,
        output_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
