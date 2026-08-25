"""Fail closed when governed Python modules or functions exceed size limits."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from scripts import quality_gate_common

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "quality" / "oversized-code-policy.v1.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "output" / "oversized-code-gate.json"
_POLICY_VERSION = re.compile(r"^(?P<prefix>.+)\+(?P<fingerprint>[0-9a-f]{12})$")
_KINDS = {"module", "function"}


@dataclass(frozen=True)
class OversizedFinding:
    kind: str
    path: str
    symbol: str
    start_line: int
    end_line: int
    lines: int
    threshold: int

    @property
    def fingerprint(self) -> str:
        identity = f"{self.path}|{self.symbol}" if self.kind == "function" else self.path
        return f"oversized-code.v1|{self.kind}|{identity}"

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "fingerprint": self.fingerprint}


def _parse_expiry(value: object, *, field: str) -> date:
    raw = quality_gate_common.non_empty_string(value, field=field)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Oversized-code field {field!r} is not an ISO date: {raw}") from exc


def _canonical_path(value: object, *, repo_root: Path) -> str:
    raw = quality_gate_common.non_empty_string(value, field="path").replace("\\", "/")
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(repo_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Oversized-code path is outside the repository: {raw}") from exc
    normalized = PurePosixPath(candidate.as_posix()).as_posix()
    if normalized in {"", "."} or normalized.startswith("../") or "/../" in normalized:
        raise ValueError(f"Oversized-code path must be repository-relative: {raw}")
    return normalized.removeprefix("./")


def _validate_scan_paths(policy: dict[str, Any]) -> tuple[str, ...]:
    raw_paths = policy.get("scan_paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ValueError("Oversized-code policy scan_paths must be a non-empty list.")
    paths: list[str] = []
    for raw_path in raw_paths:
        path = quality_gate_common.non_empty_string(raw_path, field="scan_paths[]").replace(
            "\\", "/"
        )
        normalized = PurePosixPath(path).as_posix().removeprefix("./")
        if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
            raise ValueError(f"Oversized-code scan path must be repository-relative: {path}")
        if normalized in paths:
            raise ValueError(f"Duplicate oversized-code scan path: {normalized}")
        paths.append(normalized)
    return tuple(paths)


def _validate_relative_policy_path(value: object, *, field: str) -> str:
    raw = quality_gate_common.non_empty_string(value, field=field).replace("\\", "/")
    candidate = Path(raw)
    normalized = PurePosixPath(raw).as_posix().removeprefix("./")
    if (
        candidate.is_absolute()
        or normalized.startswith("/")
        or ".." in PurePosixPath(normalized).parts
    ):
        raise ValueError(f"Oversized-code {field} must be repository-relative: {raw}")
    if normalized in {"", "."}:
        raise ValueError(f"Oversized-code {field} must name a repository file: {raw}")
    return normalized


def load_policy(path: Path) -> dict[str, Any]:
    policy = quality_gate_common.load_json_object(path, description="oversized-code policy")
    if policy.get("schema_version") != "lotus.advise.oversized-code-policy.v1":
        raise ValueError("Oversized-code policy has an unsupported schema_version.")
    version = quality_gate_common.non_empty_string(
        policy.get("policy_version"), field="policy_version"
    )
    if _POLICY_VERSION.fullmatch(version) is None:
        raise ValueError(
            "Oversized-code policy policy_version must end with '+' and a 12-character "
            "content fingerprint."
        )
    expected = quality_gate_common.expected_policy_version(policy)
    if version != expected:
        raise ValueError(
            "Oversized-code policy policy_version does not match its content fingerprint; "
            f"expected {expected}. Bump policy_version when policy content changes."
        )
    scan_paths = _validate_scan_paths(policy)
    thresholds = policy.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("Oversized-code policy must define thresholds.")
    for field in ("module_max_lines", "function_max_lines"):
        value = thresholds.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"Oversized-code threshold {field!r} must be a positive integer.")
    baseline = policy.get("baseline")
    if not isinstance(baseline, dict):
        raise ValueError("Oversized-code policy must define baseline provenance.")
    _validate_relative_policy_path(baseline.get("path"), field="baseline.path")
    quality_gate_common.non_empty_string(baseline.get("sha256"), field="baseline.sha256")
    quality_gate_common.non_empty_string(baseline.get("owner"), field="baseline.owner")
    quality_gate_common.non_empty_string(baseline.get("reason"), field="baseline.reason")
    _parse_expiry(baseline.get("expires_on"), field="baseline.expires_on")
    if (
        not isinstance(policy.get("exceptions"), dict)
        or policy["exceptions"].get("allowed") is not False
    ):
        raise ValueError("Oversized-code policy must disable unreviewed exceptions.")
    if policy["exceptions"].get("entries") != []:
        raise ValueError("Oversized-code policy exception entries must be empty.")
    return {**policy, "scan_paths": list(scan_paths)}


def baseline_content_fingerprint(baseline: dict[str, Any]) -> str:
    canonical = json.dumps(baseline, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _expected_fingerprint(kind: str, path: str, symbol: str) -> str:
    identity = f"{path}|{symbol}" if kind == "function" else path
    return f"oversized-code.v1|{kind}|{identity}"


def load_baseline(
    path: Path,
    *,
    repo_root: Path,
    expected_sha256: str,
    thresholds: dict[str, int],
    scan_paths: tuple[str, ...],
) -> list[dict[str, Any]]:
    baseline = quality_gate_common.load_json_object(path, description="oversized-code baseline")
    if baseline.get("schema_version") != "lotus.advise.oversized-code-baseline.v1":
        raise ValueError("Oversized-code baseline has an unsupported schema_version.")
    quality_gate_common.non_empty_string(baseline.get("baseline_version"), field="baseline_version")
    raw_findings = baseline.get("findings")
    if not isinstance(raw_findings, list):
        raise ValueError("Oversized-code baseline findings must be a list.")
    fingerprints: set[str] = set()
    for index, entry in enumerate(raw_findings):
        if not isinstance(entry, dict):
            raise ValueError(f"Oversized-code baseline finding {index} must be an object.")
        kind = quality_gate_common.non_empty_string(entry.get("kind"), field="kind")
        if kind not in _KINDS:
            raise ValueError(f"Unsupported oversized-code baseline kind: {kind}")
        path_value = _canonical_path(entry.get("path"), repo_root=repo_root)
        if not any(path_value == root or path_value.startswith(f"{root}/") for root in scan_paths):
            raise ValueError(f"Oversized-code baseline path is outside scan_paths: {path_value}")
        symbol = quality_gate_common.non_empty_string(entry.get("symbol"), field="symbol")
        if kind == "module" and symbol != "__module__":
            raise ValueError("Oversized-code module baseline symbol must be __module__.")
        expected_fingerprint = _expected_fingerprint(kind, path_value, symbol)
        fingerprint = quality_gate_common.non_empty_string(
            entry.get("fingerprint"), field="fingerprint"
        )
        if fingerprint != expected_fingerprint:
            raise ValueError(
                f"Oversized-code baseline fingerprint does not match its identity: {fingerprint}"
            )
        if fingerprint in fingerprints:
            raise ValueError(f"Duplicate oversized-code baseline fingerprint: {fingerprint}")
        fingerprints.add(fingerprint)
        max_lines = entry.get("max_lines")
        threshold = thresholds[f"{kind}_max_lines"]
        if not isinstance(max_lines, int) or isinstance(max_lines, bool) or max_lines <= threshold:
            raise ValueError(
                f"Oversized-code baseline max_lines for {fingerprint} must exceed {threshold}."
            )
        quality_gate_common.non_empty_string(entry.get("owner"), field="owner")
        quality_gate_common.non_empty_string(entry.get("reason"), field="reason")
        _parse_expiry(entry.get("expires_on"), field="expires_on")
        entry["path"] = path_value
        entry["fingerprint"] = fingerprint
    actual_sha256 = baseline_content_fingerprint(baseline)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "Oversized-code baseline sha256 does not match policy; "
            f"expected {expected_sha256}, observed {actual_sha256}."
        )
    return raw_findings


class _FunctionCollector(ast.NodeVisitor):
    def __init__(self, *, path: str, threshold: int) -> None:
        self.path = path
        self.threshold = threshold
        self.scope: list[str] = []
        self.findings: list[OversizedFinding] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _record(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        end_line = node.end_lineno or node.lineno
        lines = end_line - node.lineno + 1
        if lines > self.threshold:
            symbol = ".".join([*self.scope, node.name])
            self.findings.append(
                OversizedFinding(
                    kind="function",
                    path=self.path,
                    symbol=symbol,
                    start_line=node.lineno,
                    end_line=end_line,
                    lines=lines,
                    threshold=self.threshold,
                )
            )


def scan_repository(
    *, repo_root: Path, scan_paths: tuple[str, ...], thresholds: dict[str, int]
) -> list[OversizedFinding]:
    findings: list[OversizedFinding] = []
    for scan_path in scan_paths:
        root = (repo_root / scan_path).resolve()
        try:
            root.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Oversized-code scan path is outside the repository: {scan_path}"
            ) from exc
        if not root.is_dir():
            raise ValueError(f"Oversized-code scan path does not exist: {scan_path}")
        for path in sorted(root.rglob("*.py")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(repo_root).as_posix()
            source = path.read_text(encoding="utf-8")
            module_lines = len(source.splitlines())
            if module_lines > thresholds["module_max_lines"]:
                findings.append(
                    OversizedFinding(
                        kind="module",
                        path=relative_path,
                        symbol="__module__",
                        start_line=1,
                        end_line=module_lines,
                        lines=module_lines,
                        threshold=thresholds["module_max_lines"],
                    )
                )
            tree = ast.parse(source, filename=relative_path)
            collector = _FunctionCollector(
                path=relative_path,
                threshold=thresholds["function_max_lines"],
            )
            collector.visit(tree)
            findings.extend(collector.findings)
    return sorted(findings, key=lambda finding: finding.fingerprint)


@dataclass(frozen=True)
class _GateInputs:
    policy: dict[str, Any]
    thresholds: dict[str, int]
    scan_paths: tuple[str, ...]
    baseline_path: Path
    baseline: list[dict[str, Any]]


@dataclass(frozen=True)
class _FindingGroups:
    baseline_by_fingerprint: dict[str, dict[str, Any]]
    new: list[OversizedFinding]
    grown: list[OversizedFinding]
    shrunken: list[OversizedFinding]
    resolved: list[dict[str, Any]]
    expired: list[dict[str, Any]]
    provenance_expired: bool


def _classify_live_findings(
    findings: list[OversizedFinding], baseline_by_fingerprint: dict[str, dict[str, Any]]
) -> tuple[list[OversizedFinding], list[OversizedFinding], list[OversizedFinding]]:
    new: list[OversizedFinding] = []
    grown: list[OversizedFinding] = []
    shrunken: list[OversizedFinding] = []
    for finding in findings:
        baseline_entry = baseline_by_fingerprint.get(finding.fingerprint)
        if baseline_entry is None:
            new.append(finding)
        elif finding.lines > baseline_entry["max_lines"]:
            grown.append(finding)
        elif finding.lines < baseline_entry["max_lines"]:
            shrunken.append(finding)
    return new, grown, shrunken


def _classify_baseline_state(
    *, baseline: list[dict[str, Any]], observed: set[str], policy: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    baseline_by_fingerprint = {entry["fingerprint"]: entry for entry in baseline}
    resolved = [
        baseline_by_fingerprint[fingerprint]
        for fingerprint in sorted(set(baseline_by_fingerprint) - observed)
    ]
    today = date.today()
    expired = [entry for entry in baseline if date.fromisoformat(entry["expires_on"]) < today]
    provenance_expired = date.fromisoformat(policy["baseline"]["expires_on"]) < today
    return resolved, expired, provenance_expired


def _load_gate_inputs(*, repo_root: Path, policy_path: Path) -> _GateInputs:
    policy = load_policy(policy_path)
    thresholds = policy["thresholds"]
    scan_paths = tuple(policy["scan_paths"])
    baseline_relative_path = _validate_relative_policy_path(
        policy["baseline"]["path"], field="baseline.path"
    )
    baseline_path = repo_root / baseline_relative_path
    baseline = load_baseline(
        baseline_path,
        repo_root=repo_root,
        expected_sha256=policy["baseline"]["sha256"],
        thresholds=thresholds,
        scan_paths=scan_paths,
    )
    return _GateInputs(
        policy=policy,
        thresholds=thresholds,
        scan_paths=scan_paths,
        baseline_path=baseline_path,
        baseline=baseline,
    )


def _classify_findings(
    *, findings: list[OversizedFinding], baseline: list[dict[str, Any]], policy: dict[str, Any]
) -> _FindingGroups:
    observed = {finding.fingerprint: finding for finding in findings}
    if len(observed) != len(findings):
        raise ValueError("Oversized-code scanner produced duplicate fingerprints.")
    baseline_by_fingerprint = {entry["fingerprint"]: entry for entry in baseline}
    new, grown, shrunken = _classify_live_findings(findings, baseline_by_fingerprint)
    resolved, expired, provenance_expired = _classify_baseline_state(
        baseline=baseline,
        observed=set(observed),
        policy=policy,
    )
    return _FindingGroups(
        baseline_by_fingerprint=baseline_by_fingerprint,
        new=new,
        grown=grown,
        shrunken=shrunken,
        resolved=resolved,
        expired=expired,
        provenance_expired=provenance_expired,
    )


def _build_failures(*, policy: dict[str, Any], groups: _FindingGroups) -> list[str]:
    failures: list[str] = []
    if groups.provenance_expired:
        failures.append(
            "Expired oversized-code baseline provenance: "
            f"owner={policy['baseline']['owner']}, "
            f"expires_on={policy['baseline']['expires_on']}"
        )
    failures.extend(
        "Expired oversized-code baseline finding: "
        f"{entry['fingerprint']} (owner={entry['owner']}, expires_on={entry['expires_on']})"
        for entry in groups.expired
    )
    failures.extend(
        "New oversized-code finding: "
        f"{finding.path}:{finding.symbol} has {finding.lines} lines; "
        f"threshold={finding.threshold}, fingerprint={finding.fingerprint}. "
        "Refactor it or add a reviewed owner/reason/expiry baseline entry."
        for finding in groups.new
    )
    failures.extend(
        "Oversized-code baseline finding grew: "
        f"{finding.path}:{finding.symbol} has {finding.lines} lines; "
        f"baseline_max={groups.baseline_by_fingerprint[finding.fingerprint]['max_lines']}. "
        "Refactor it or refresh the reviewed baseline with evidence."
        for finding in groups.grown
    )
    failures.extend(
        "Shrunken oversized-code baseline must be ratcheted: "
        f"{finding.path}:{finding.symbol} has {finding.lines} lines; "
        f"baseline_max={groups.baseline_by_fingerprint[finding.fingerprint]['max_lines']}. "
        "Update max_lines to the measured value and bump the baseline/policy fingerprints."
        for finding in groups.shrunken
    )
    failures.extend(
        "Resolved oversized-code baseline must be removed from the baseline and its "
        f"policy/baseline fingerprints refreshed: {entry['fingerprint']}"
        for entry in groups.resolved
    )
    return failures


def _build_report_payload(
    *,
    inputs: _GateInputs,
    findings: list[OversizedFinding],
    groups: _FindingGroups,
    failures: list[str],
) -> dict[str, Any]:
    policy = inputs.policy
    return {
        "policy_version": policy["policy_version"],
        "policy_content_fingerprint": quality_gate_common.policy_content_fingerprint(policy),
        "scan_paths": inputs.scan_paths,
        "thresholds": inputs.thresholds,
        "findings": [finding.as_dict() for finding in findings],
        "new_findings": [finding.as_dict() for finding in groups.new],
        "grown_findings": [finding.as_dict() for finding in groups.grown],
        "shrunken_findings": [finding.as_dict() for finding in groups.shrunken],
        "resolved_baseline_findings": groups.resolved,
        "expired_baseline_findings": groups.expired,
        "counts": {
            "findings": len(findings),
            "baseline": len(inputs.baseline),
            "new": len(groups.new),
            "grown": len(groups.grown),
            "shrunken": len(groups.shrunken),
            "resolved": len(groups.resolved),
            "expired": len(groups.expired),
            "modules": sum(finding.kind == "module" for finding in findings),
            "functions": sum(finding.kind == "function" for finding in findings),
        },
        "baseline_provenance": {
            **policy["baseline"],
            "content_fingerprint": baseline_content_fingerprint(
                quality_gate_common.load_json_object(
                    inputs.baseline_path, description="oversized-code baseline"
                )
            ),
            "findings": inputs.baseline,
        },
        "exception_provenance": policy["exceptions"],
        "failures": failures,
        "status": "failed" if failures else "passed",
    }


def run_gate(*, repo_root: Path, policy_path: Path, output_path: Path) -> int:
    report: dict[str, Any] = {
        "schema_version": "lotus.advise.oversized-code-gate.v1",
        "policy_path": policy_path.as_posix(),
        "status": "failed",
        "failures": [],
    }
    try:
        inputs = _load_gate_inputs(repo_root=repo_root, policy_path=policy_path)
        findings = scan_repository(
            repo_root=repo_root,
            scan_paths=inputs.scan_paths,
            thresholds=inputs.thresholds,
        )
        groups = _classify_findings(
            findings=findings,
            baseline=inputs.baseline,
            policy=inputs.policy,
        )
        failures = _build_failures(policy=inputs.policy, groups=groups)
        report.update(
            _build_report_payload(
                inputs=inputs,
                findings=findings,
                groups=groups,
                failures=failures,
            )
        )
    except (OSError, SyntaxError, ValueError, KeyError, TypeError) as exc:
        report["failures"] = [str(exc)]
        report["status"] = "failed"

    return int(
        quality_gate_common.finish_gate(
            report,
            output_path,
            "Oversized-code gate",
            "Oversized-code gate passed: {findings} findings, {new} new, "
            "{resolved} resolved, policy={policy}.",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "Oversized-code regression gate")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)
    return run_gate(
        repo_root=args.repo_root.resolve(),
        policy_path=args.policy.resolve(),
        output_path=args.output.resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
