"""Fail closed when committed quality metrics regress beyond reviewed policy limits."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from scripts import quality_gate_common

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "quality" / "quality-trend-policy.v1.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "output" / "quality-trend-gate.json"
_POLICY_VERSION = re.compile(r"^.+\+[0-9a-f]{12}$")
_REPORT_PATTERNS: dict[str, re.Pattern[str]] = {
    "total_python_lines": re.compile(r"^- Total Python lines: `(?P<value>\d+)`$", re.MULTILINE),
    "radon_b_ranked_blocks": re.compile(
        r"^- Radon complexity rank inventory: `A=\d+, B=(?P<value>\d+)`$", re.MULTILINE
    ),
    "radon_worst_complexity": re.compile(
        r"^- Radon worst complexity: `rank=[A-F], complexity=(?P<value>\d+)`$", re.MULTILINE
    ),
    "interrogate_coverage_percent": re.compile(
        r"^- Interrogate docstring inventory: `.*coverage=(?P<value>\d+(?:\.\d+)?)%`$",
        re.MULTILINE,
    ),
}


@dataclass(frozen=True)
class MetricResult:
    name: str
    base: float
    head: float
    delta: float
    direction: str
    policy_allowed_delta: float
    allowed_delta: float
    status: str
    reason: str
    exception: dict[str, Any] | None


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"Quality-trend field {field!r} must be a non-negative number.")
    return float(value)


def load_policy(path: Path) -> dict[str, Any]:
    policy = quality_gate_common.load_json_object(path, description="quality-trend policy")
    if policy.get("schema_version") != "lotus.advise.quality-trend-policy.v1":
        raise ValueError("Quality-trend policy has an unsupported schema_version.")
    version = quality_gate_common.non_empty_string(
        policy.get("policy_version"), field="policy_version"
    )
    if _POLICY_VERSION.fullmatch(version) is None:
        raise ValueError(
            "Quality-trend policy_version must end with a 12-character content fingerprint."
        )
    expected = quality_gate_common.expected_policy_version(policy)
    if version != expected:
        raise ValueError(
            "Quality-trend policy policy_version does not match its content fingerprint; "
            f"expected {expected}. Bump policy_version when policy content changes."
        )
    report_path = quality_gate_common.non_empty_string(
        policy.get("report_path"), field="report_path"
    )
    if Path(report_path).is_absolute() or ".." in Path(report_path).parts:
        raise ValueError("Quality-trend report_path must be repository-relative.")
    raw_metrics = policy.get("metrics")
    if not isinstance(raw_metrics, list) or not raw_metrics:
        raise ValueError("Quality-trend policy metrics must be a non-empty list.")
    metrics: list[dict[str, Any]] = []
    names: set[str] = set()
    for raw_metric in raw_metrics:
        if not isinstance(raw_metric, dict):
            raise ValueError("Every quality-trend metric must be an object.")
        name = quality_gate_common.non_empty_string(raw_metric.get("name"), field="metrics[].name")
        if name not in _REPORT_PATTERNS or name in names:
            raise ValueError(f"Unsupported or duplicate quality-trend metric: {name}")
        direction = quality_gate_common.non_empty_string(
            raw_metric.get("direction"), field=f"metrics[{name}].direction"
        )
        if direction not in {"increase", "decrease"}:
            raise ValueError(f"Unsupported quality-trend direction for {name}: {direction}")
        allowed_delta = _number(
            raw_metric.get("allowed_delta"), field=f"metrics[{name}].allowed_delta"
        )
        reason = quality_gate_common.non_empty_string(
            raw_metric.get("reason"), field=f"metrics[{name}].reason"
        )
        names.add(name)
        metrics.append(
            {"name": name, "direction": direction, "allowed_delta": allowed_delta, "reason": reason}
        )
    exceptions = policy.get("exceptions")
    if not isinstance(exceptions, dict) or exceptions.get("allowed") is not True:
        raise ValueError("Quality-trend policy must explicitly enable reviewed exceptions.")
    entries = exceptions.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Quality-trend policy exception entries must be a list.")
    seen_exceptions: set[str] = set()
    today = date.today()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Every quality-trend exception must be an object.")
        name = quality_gate_common.non_empty_string(
            entry.get("metric"), field="exceptions[].metric"
        )
        if name not in names or name in seen_exceptions:
            raise ValueError(f"Unsupported or duplicate quality-trend exception metric: {name}")
        allowed = _number(entry.get("allowed_delta"), field=f"exceptions[{name}].allowed_delta")
        if allowed < next(metric["allowed_delta"] for metric in metrics if metric["name"] == name):
            raise ValueError(f"Quality-trend exception for {name} may not weaken its policy limit.")
        quality_gate_common.non_empty_string(entry.get("reason"), field="exceptions[].reason")
        quality_gate_common.non_empty_string(entry.get("approver"), field="exceptions[].approver")
        expiry = quality_gate_common.non_empty_string(
            entry.get("expires_on"), field="exceptions[].expires_on"
        )
        try:
            expiry_date = date.fromisoformat(expiry)
        except ValueError as exc:
            raise ValueError(
                f"Quality-trend exception expiry is not an ISO date: {expiry}"
            ) from exc
        if expiry_date < today:
            raise ValueError(f"Expired quality-trend exception for {name}: {expiry}")
        seen_exceptions.add(name)
    return {**policy, "metrics": metrics, "exceptions": {**exceptions, "entries": entries}}


def parse_report(content: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for name, pattern in _REPORT_PATTERNS.items():
        match = pattern.search(content)
        if match is None:
            raise ValueError(f"Quality baseline report is missing metric: {name}")
        values[name] = float(match.group("value"))
    return values


def compare_metrics(
    base_values: dict[str, float], head_values: dict[str, float], policy: dict[str, Any]
) -> tuple[list[MetricResult], list[str]]:
    results: list[MetricResult] = []
    failures: list[str] = []
    entries = {entry["metric"]: entry for entry in policy["exceptions"]["entries"]}
    for metric in policy["metrics"]:
        name = metric["name"]
        base = base_values[name]
        head = head_values[name]
        delta = head - base
        policy_allowed_delta = float(metric["allowed_delta"])
        exception = entries.get(name)
        allowed_delta = (
            float(exception["allowed_delta"]) if exception is not None else policy_allowed_delta
        )
        regressed = (
            (delta > allowed_delta)
            if metric["direction"] == "increase"
            else (delta < -allowed_delta)
        )
        result = MetricResult(
            name=name,
            base=base,
            head=head,
            delta=delta,
            direction=metric["direction"],
            policy_allowed_delta=policy_allowed_delta,
            allowed_delta=allowed_delta,
            status="failed" if regressed else "passed",
            reason=metric["reason"],
            exception=exception,
        )
        results.append(result)
        if regressed:
            failures.append(
                f"Quality trend regression: {name} base={base:g}, head={head:g}, delta={delta:+g}, "
                f"allowed_delta={allowed_delta:g} (policy={policy_allowed_delta:g}). "
                "Review the change or add an expiring, approved exception."
            )
    return results, failures


def _git_file(repo_root: Path, ref: str, path: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=repo_root, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise ValueError(
            f"Unable to read quality baseline report at {ref}: {completed.stderr.strip()}"
        )
    return completed.stdout


def _git_sha(repo_root: Path, ref: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"Unable to resolve quality trend revision: {ref}")
    return completed.stdout.strip()


def run_gate(
    *, repo_root: Path, policy_path: Path, output_path: Path, base_ref: str, head_ref: str
) -> int:
    report: dict[str, Any] = {
        "schema_version": "lotus.advise.quality-trend-gate.v1",
        "status": "failed",
        "failures": [],
        "base_ref": base_ref,
        "head_ref": head_ref,
    }
    try:
        policy = load_policy(policy_path)
        head_sha = _git_sha(repo_root, head_ref)
        effective_base_ref = base_ref or "origin/main"
        base_sha = _git_sha(repo_root, effective_base_ref)
        if base_sha == head_sha:
            effective_base_ref = "HEAD^"
            base_sha = _git_sha(repo_root, effective_base_ref)
        report_path = policy["report_path"]
        base_values = parse_report(_git_file(repo_root, effective_base_ref, report_path))
        head_values = parse_report(_git_file(repo_root, head_ref, report_path))
        results, failures = compare_metrics(base_values, head_values, policy)
        report.update(
            {
                "policy_path": policy_path.as_posix(),
                "policy_version": policy["policy_version"],
                "policy_content_fingerprint": quality_gate_common.policy_content_fingerprint(
                    policy
                ),
                "report_path": report_path,
                "base_ref": effective_base_ref,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "metrics": [asdict(result) for result in results],
                "counts": {
                    "findings": len(results),
                    "regressions": len(failures),
                    "new": len(failures),
                    "resolved": 0,
                    "exceptions": sum(result.exception is not None for result in results),
                },
                "failures": failures,
                "status": "failed" if failures else "passed",
            }
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report["failures"] = [str(exc)]
        report["status"] = "failed"
    return quality_gate_common.finish_gate(
        report,
        output_path,
        "Quality trend gate",
        "Quality trend gate passed: {findings} metrics, {new} regressions, "
        "{resolved} resolved, policy={policy}.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "Quality trend regression gate")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--head-ref", default="HEAD")
    args = parser.parse_args(argv)
    return run_gate(
        repo_root=args.repo_root.resolve(),
        policy_path=args.policy.resolve(),
        output_path=args.output.resolve(),
        base_ref=args.base_ref,
        head_ref=args.head_ref,
    )


if __name__ == "__main__":
    raise SystemExit(main())
