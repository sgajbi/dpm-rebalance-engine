"""Fail closed when deptry finds an unreviewed dependency regression."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from scripts import quality_gate_common


def __getattr__(name: str) -> Any:
    return getattr(quality_gate_common, name)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "quality" / "dependency-hygiene-policy.v1.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "output" / "dependency-hygiene-gate.json"
_POLICY_VERSION = re.compile(r"^(?P<prefix>.+)\+(?P<fingerprint>[0-9a-f]{12})$")


@dataclass(frozen=True)
class DependencyFinding:
    code: str
    module: str
    path: str
    line: int | None
    column: int | None
    message: str

    @property
    def fingerprint(self) -> str:
        return f"deptry.v1|{self.code}|{self.path}|{self.module}"

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "fingerprint": self.fingerprint}


def _canonical_repo_path(raw_path: object, *, repo_root: Path) -> str:
    value = quality_gate_common.non_empty_string(raw_path, field="location.file").replace("\\", "/")
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(repo_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Dependency finding path is outside the repository: {value}") from exc
    normalized = PurePosixPath(candidate.as_posix()).as_posix()
    if normalized in {"", "."} or normalized.startswith("../") or "/../" in normalized:
        raise ValueError(f"Dependency finding path must be repository-relative: {value}")
    return normalized.removeprefix("./")


def _optional_positive_integer(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"Dependency finding field {field!r} must be null or a positive integer.")
    return value


def parse_deptry_report(payload: object, *, repo_root: Path) -> list[DependencyFinding]:
    if not isinstance(payload, list):
        raise ValueError("deptry JSON must be a list of findings.")
    findings: list[DependencyFinding] = []
    for index, raw in enumerate(payload):
        if not isinstance(raw, dict):
            raise ValueError(f"deptry finding {index} must be a JSON object.")
        error = raw.get("error")
        if not isinstance(error, dict):
            raise ValueError(f"deptry finding {index} must define an error object.")
        code = quality_gate_common.non_empty_string(error.get("code"), field="error.code")
        message = quality_gate_common.non_empty_string(error.get("message"), field="error.message")
        module = quality_gate_common.non_empty_string(raw.get("module"), field="module")
        location = raw.get("location")
        if not isinstance(location, dict):
            raise ValueError(f"deptry finding {index} must define a location object.")
        findings.append(
            DependencyFinding(
                code=code,
                module=module,
                path=_canonical_repo_path(location.get("file"), repo_root=repo_root),
                line=_optional_positive_integer(location.get("line"), field="location.line"),
                column=_optional_positive_integer(location.get("column"), field="location.column"),
                message=message,
            )
        )
    return sorted(findings, key=lambda finding: finding.fingerprint)


def _parse_expiry(value: object, *, field: str) -> date:
    raw = quality_gate_common.non_empty_string(value, field=field)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Dependency-hygiene field {field!r} is not an ISO date: {raw}") from exc


def validate_tool_version(raw_version: str, *, expected_version: str) -> str:
    actual_version = raw_version.strip()
    expected = f"deptry {expected_version}"
    if actual_version != expected:
        raise RuntimeError(
            f"deptry version mismatch: policy requires {expected}, observed {actual_version!r}"
        )
    return actual_version


def load_policy(path: Path) -> dict[str, Any]:
    policy = quality_gate_common.load_json_object(path, description="dependency-hygiene policy")
    if policy.get("schema_version") != "lotus.advise.dependency-hygiene-policy.v1":
        raise ValueError("Dependency-hygiene policy has an unsupported schema_version.")
    version = quality_gate_common.non_empty_string(
        policy.get("policy_version"), field="policy_version"
    )
    if _POLICY_VERSION.fullmatch(version) is None:
        raise ValueError(
            "Dependency-hygiene policy policy_version must end with '+' and a 12-character "
            "content fingerprint."
        )
    expected = quality_gate_common.expected_policy_version(policy)
    if version != expected:
        raise ValueError(
            "Dependency-hygiene policy policy_version does not match its content fingerprint; "
            f"expected {expected}. Bump policy_version when policy content changes."
        )
    if policy.get("tool") != "deptry":
        raise ValueError("Dependency-hygiene policy tool must be deptry.")
    quality_gate_common.non_empty_string(policy.get("tool_version"), field="tool_version")
    if policy.get("report_format") != "json":
        raise ValueError("Dependency-hygiene policy report_format must be json.")
    quality_gate_common.non_empty_string(policy.get("config_path"), field="config_path")
    if policy.get("max_new_findings") != 0 or policy.get("max_resolved_findings") != 0:
        raise ValueError("Dependency-hygiene policy must reject both new and resolved findings.")

    baseline = policy.get("baseline")
    if not isinstance(baseline, dict):
        raise ValueError("Dependency-hygiene policy must define baseline provenance.")
    quality_gate_common.non_empty_string(baseline.get("path"), field="baseline.path")
    quality_gate_common.non_empty_string(baseline.get("sha256"), field="baseline.sha256")
    quality_gate_common.non_empty_string(baseline.get("owner"), field="baseline.owner")
    quality_gate_common.non_empty_string(baseline.get("reason"), field="baseline.reason")
    _parse_expiry(baseline.get("expires_on"), field="baseline.expires_on")

    exceptions = policy.get("exceptions")
    if not isinstance(exceptions, dict) or exceptions.get("allowed") is not False:
        raise ValueError("Dependency-hygiene policy must disable unreviewed exceptions.")
    if exceptions.get("entries") != []:
        raise ValueError("Dependency-hygiene policy exception entries must be empty.")
    return policy


def baseline_content_fingerprint(baseline: dict[str, Any]) -> str:
    canonical = json.dumps(baseline, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_baseline(path: Path, *, expected_sha256: str) -> list[dict[str, Any]]:
    baseline = quality_gate_common.load_json_object(path, description="dependency-hygiene baseline")
    if baseline.get("schema_version") != "lotus.advise.dependency-hygiene-baseline.v1":
        raise ValueError("Dependency-hygiene baseline has an unsupported schema_version.")
    quality_gate_common.non_empty_string(baseline.get("baseline_version"), field="baseline_version")
    findings = baseline.get("findings")
    if not isinstance(findings, list):
        raise ValueError("Dependency-hygiene baseline findings must be a list.")
    observed_fingerprints: set[str] = set()
    for entry in findings:
        if not isinstance(entry, dict):
            raise ValueError("Each dependency-hygiene baseline finding must be an object.")
        code = quality_gate_common.non_empty_string(entry.get("code"), field="code")
        module = quality_gate_common.non_empty_string(entry.get("module"), field="module")
        path_value = quality_gate_common.non_empty_string(entry.get("path"), field="path").replace(
            "\\", "/"
        )
        if Path(path_value).is_absolute() or ".." in PurePosixPath(path_value).parts:
            raise ValueError(f"Dependency-hygiene baseline path must be relative: {path_value}")
        fingerprint = quality_gate_common.non_empty_string(
            entry.get("fingerprint"), field="fingerprint"
        )
        expected_fingerprint = f"deptry.v1|{code}|{path_value}|{module}"
        if fingerprint != expected_fingerprint:
            raise ValueError(
                "Dependency-hygiene baseline fingerprint does not match its identity: "
                f"{fingerprint}"
            )
        if fingerprint in observed_fingerprints:
            raise ValueError(f"Duplicate dependency-hygiene baseline fingerprint: {fingerprint}")
        observed_fingerprints.add(fingerprint)
        quality_gate_common.non_empty_string(entry.get("classification"), field="classification")
        quality_gate_common.non_empty_string(entry.get("owner"), field="owner")
        quality_gate_common.non_empty_string(entry.get("reason"), field="reason")
        _parse_expiry(entry.get("expires_on"), field="expires_on")
    actual_sha256 = baseline_content_fingerprint(baseline)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "Dependency-hygiene baseline sha256 does not match policy; "
            f"expected {expected_sha256}, observed {actual_sha256}."
        )
    return findings


def _run_deptry(
    *, repo_root: Path, policy: dict[str, Any]
) -> tuple[list[DependencyFinding], int, str, str]:
    config_path = policy["config_path"]
    version_command = [sys.executable, "-m", "deptry", "--version"]
    version_result = subprocess.run(
        version_command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if version_result.returncode != 0:
        detail = version_result.stderr.strip() or version_result.stdout.strip() or "no tool output"
        raise RuntimeError(f"deptry version check exited {version_result.returncode}: {detail}")
    actual_version = validate_tool_version(
        version_result.stdout,
        expected_version=policy["tool_version"],
    )
    with tempfile.TemporaryDirectory(prefix="lotus-advise-deptry-") as temporary:
        report_path = Path(temporary) / "deptry-report.json"
        command = [
            sys.executable,
            "-m",
            "deptry",
            ".",
            "--config",
            config_path,
            "--json-output",
            str(report_path),
        ]
        completed = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode not in {0, 1}:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no tool output"
            raise RuntimeError(f"deptry exited {completed.returncode}: {detail}")
        if not report_path.is_file():
            raise RuntimeError("deptry did not produce a JSON report.")
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to parse deptry JSON report: {exc}") from exc
    return (
        parse_deptry_report(payload, repo_root=repo_root),
        completed.returncode,
        " ".join(command),
        actual_version,
    )


def run_gate(*, repo_root: Path, policy_path: Path, output_path: Path) -> int:
    report: dict[str, Any] = {
        "schema_version": "lotus.advise.dependency-hygiene-gate.v1",
        "policy_path": policy_path.as_posix(),
        "status": "failed",
        "failures": [],
    }
    try:
        policy = load_policy(policy_path)
        baseline_path = repo_root / policy["baseline"]["path"]
        baseline = load_baseline(
            baseline_path,
            expected_sha256=policy["baseline"]["sha256"],
        )
        findings, return_code, command, tool_runtime_version = _run_deptry(
            repo_root=repo_root, policy=policy
        )
        observed = {finding.fingerprint: finding for finding in findings}
        if len(observed) != len(findings):
            raise ValueError("deptry produced duplicate normalized finding fingerprints.")
        baseline_by_fingerprint = {entry["fingerprint"]: entry for entry in baseline}
        new_findings = [
            finding for finding in findings if finding.fingerprint not in baseline_by_fingerprint
        ]
        resolved = [
            baseline_by_fingerprint[fingerprint]
            for fingerprint in sorted(set(baseline_by_fingerprint) - set(observed))
        ]
        today = date.today()
        expired_baseline = [
            entry for entry in baseline if date.fromisoformat(entry["expires_on"]) < today
        ]
        baseline_expiry = date.fromisoformat(policy["baseline"]["expires_on"])
        failures: list[str] = []
        if baseline_expiry < today:
            failures.append(
                "Expired dependency-hygiene baseline provenance: "
                f"owner={policy['baseline']['owner']}, "
                f"expires_on={policy['baseline']['expires_on']}"
            )
        if expired_baseline:
            failures.extend(
                "Expired dependency-hygiene baseline finding: "
                f"{entry['fingerprint']} (owner={entry['owner']}, expires_on={entry['expires_on']})"
                for entry in expired_baseline
            )
        if new_findings:
            failures.extend(
                "New dependency finding: "
                f"{finding.code} {finding.module} at {finding.path}; "
                f"fingerprint={finding.fingerprint}. Remove the dependency or add a reviewed, "
                "owner/reason/expiry baseline entry."
                for finding in new_findings
            )
        if resolved:
            failures.extend(
                "Resolved dependency baseline must be removed from the baseline and the "
                f"policy/baseline fingerprints refreshed: {entry['fingerprint']}"
                for entry in resolved
            )
        report.update(
            {
                "policy_version": policy["policy_version"],
                "policy_content_fingerprint": quality_gate_common.policy_content_fingerprint(
                    policy
                ),
                "tool": policy["tool"],
                "tool_version": policy["tool_version"],
                "tool_runtime_version": tool_runtime_version,
                "config_path": policy["config_path"],
                "max_new_findings": policy["max_new_findings"],
                "max_resolved_findings": policy["max_resolved_findings"],
                "command": command,
                "tool_return_code": return_code,
                "findings": [finding.as_dict() for finding in findings],
                "new_findings": [finding.as_dict() for finding in new_findings],
                "resolved_baseline_findings": resolved,
                "expired_baseline_findings": expired_baseline,
                "counts": {
                    "findings": len(findings),
                    "baseline": len(baseline),
                    "new": len(new_findings),
                    "resolved": len(resolved),
                    "expired": len(expired_baseline),
                },
                "baseline_provenance": {
                    **policy["baseline"],
                    "content_fingerprint": baseline_content_fingerprint(
                        quality_gate_common.load_json_object(
                            baseline_path, description="dependency-hygiene baseline"
                        )
                    ),
                    "findings": baseline,
                },
                "exception_provenance": policy["exceptions"],
                "failures": failures,
                "status": "failed" if failures else "passed",
            }
        )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        report["failures"] = [str(exc)]
        report["status"] = "failed"

    return quality_gate_common.finish_gate(
        report,
        output_path,
        "Dependency-hygiene gate",
        "Dependency-hygiene gate passed: {findings} findings, {new} new, "
        "{resolved} resolved, policy={policy}.",
    )


def main() -> int:
    args = quality_gate_common.parse_gate_arguments(
        description=__doc__ or "Dependency-hygiene regression gate",
        default_policy_path=DEFAULT_POLICY_PATH,
        default_output_path=DEFAULT_OUTPUT_PATH,
        include_repo_root=True,
    )
    return run_gate(
        repo_root=(args.repo_root or REPO_ROOT).resolve(),
        policy_path=args.policy.resolve(),
        output_path=args.output.resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
