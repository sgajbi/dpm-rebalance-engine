"""Enforce a deterministic coverage floor for changed Python source files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import coverage

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "quality" / "quality-policy.v1.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "output" / "changed-coverage-gate.json"


_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _changed_source_lines(*, base_ref: str, head_ref: str, source_root: str) -> dict[str, set[int]]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--unified=0",
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
    diff_result = subprocess.run(
        [
            "git",
            "diff",
            "--unified=0",
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
    changed_files = {
        path.replace("\\", "/")
        for path in result.stdout.splitlines()
        if path.replace("\\", "/").endswith(".py")
    }
    changed_lines = {path: set() for path in sorted(changed_files)}
    current_file: str | None = None
    new_line: int | None = None
    for line in diff_result.stdout.splitlines():
        if line.startswith("+++ b/"):
            candidate = line.removeprefix("+++ b/").replace("\\", "/")
            current_file = candidate if candidate in changed_lines else None
            new_line = None
            continue
        hunk = _HUNK_HEADER.match(line)
        if hunk:
            new_line = int(hunk.group(1))
            continue
        if current_file is None or new_line is None or line.startswith("\\"):
            continue
        if line.startswith("+"):
            changed_lines[current_file].add(new_line)
            new_line += 1
        elif line.startswith("-"):
            continue
        elif line.startswith(" "):
            new_line += 1
    return changed_lines


def _coverage_percent(
    cov: coverage.Coverage,
    path: Path,
    *,
    changed_lines: set[int] | None = None,
) -> dict[str, Any]:
    _, statements, _, missing, _ = cov.analysis2(str(path))
    missing_statement_lines = set(missing)
    measured_lines = set(statements) if changed_lines is None else set(statements) & changed_lines
    missing_statement_lines &= measured_lines
    statement_count = len(measured_lines)
    missing_count = len(missing_statement_lines)
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
        "changed_executable_lines": sorted(measured_lines),
        "missing_lines": sorted(missing_statement_lines),
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
    exceptions = policy.get("exceptions")
    if not isinstance(exceptions, dict) or exceptions.get("allowed") is not False:
        raise ValueError(f"Quality policy {path} must disable unreviewed coverage exceptions.")
    if exceptions.get("entries") != []:
        raise ValueError(f"Quality policy {path} must start with an empty exception set.")
    return version, threshold


def evaluate_changed_files(
    *,
    changed_files: dict[str, set[int]],
    coverage_data: Path,
    minimum_percent: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    cov = coverage.Coverage(data_file=str(coverage_data))
    cov.load()
    measurements: list[dict[str, Any]] = []
    failures: list[str] = []
    for relative_file, changed_lines in changed_files.items():
        path = REPO_ROOT / relative_file
        measurement = _coverage_percent(cov, path, changed_lines=changed_lines)
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
    changed_files = _changed_source_lines(
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
        "exception_provenance": {"allowed": False, "entries": []},
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
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--coverage-data", type=Path, default=REPO_ROOT / ".coverage")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--skip-reason")
    args = parser.parse_args()
    if args.skip_reason:
        policy_version, minimum_percent = _load_policy(args.policy)
        report = {
            "schema_version": "lotus.advise.changed-coverage-gate.v1",
            "policy_version": policy_version,
            "base_ref": args.base_ref,
            "head_ref": args.head_ref,
            "threshold_percent": minimum_percent,
            "changed_source_files": [],
            "exception_provenance": {"allowed": False, "entries": []},
            "status": "skipped",
            "skip_reason": args.skip_reason,
            "failures": [],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Changed source coverage gate skipped: {args.skip_reason}")
        return 0
    if not args.base_ref or not args.head_ref:
        parser.error("changed coverage gate requires PR base/head refs outside an explicit skip")
    return run_gate(
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        coverage_data=args.coverage_data,
        policy_path=args.policy,
        output_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
