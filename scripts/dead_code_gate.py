"""Fail closed when Vulture reports an unapproved dead-code finding."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from scripts import quality_gate_common


def __getattr__(name: str) -> Any:
    return getattr(quality_gate_common, name)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "quality" / "dead-code-policy.v1.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "output" / "dead-code-gate.json"

_FINDING = re.compile(
    r"^(?P<path>.+):(?P<line>\d+): (?P<message>.+) \((?P<confidence>\d+)% confidence\)$"
)
_MESSAGE = re.compile(r"^(?P<kind>.+?) '(?P<symbol>[^']+)'$")
_NO_SYMBOL_KINDS = frozenset({"unreachable code"})
_POLICY_VERSION = re.compile(r"^(?P<prefix>.+)\+(?P<fingerprint>[0-9a-f]{12})$")


@dataclass(frozen=True)
class DeadCodeFinding:
    path: str
    line: int
    kind: str
    symbol: str
    confidence: int

    @property
    def fingerprint(self) -> str:
        return f"vulture.v1|{self.path}|{self.kind}|{self.symbol}"

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "fingerprint": self.fingerprint}


def _relative_path(raw_path: str, repo_root: Path) -> str:
    candidate = Path(raw_path.replace("\\", "/"))
    if candidate.is_absolute():
        candidate = candidate.relative_to(repo_root)
    return candidate.as_posix()


def parse_finding(line: str, *, repo_root: Path) -> DeadCodeFinding:
    match = _FINDING.fullmatch(line.strip())
    if match is None:
        raise ValueError(f"Unable to parse Vulture finding: {line!r}")
    message = _MESSAGE.fullmatch(match.group("message"))
    if message is None and match.group("message") not in _NO_SYMBOL_KINDS:
        raise ValueError(f"Unable to parse Vulture finding message: {line!r}")
    kind = message.group("kind") if message is not None else match.group("message")
    symbol = message.group("symbol") if message is not None else ""
    return DeadCodeFinding(
        path=_relative_path(match.group("path"), repo_root),
        line=int(match.group("line")),
        kind=kind,
        symbol=symbol,
        confidence=int(match.group("confidence")),
    )


def load_policy(path: Path) -> dict[str, Any]:
    policy = quality_gate_common.load_json_object(path, description="dead-code policy")
    if policy.get("schema_version") != "lotus.advise.dead-code-policy.v1":
        raise ValueError("Dead-code policy has an unsupported schema_version.")
    policy_version = quality_gate_common.non_empty_string(
        policy.get("policy_version"), field="policy_version"
    )
    version_match = _POLICY_VERSION.fullmatch(policy_version)
    if version_match is None:
        raise ValueError(
            "Dead-code policy policy_version must end with '+' and the 12-character "
            "content fingerprint."
        )
    expected_version = quality_gate_common.expected_policy_version(policy)
    if policy_version != expected_version:
        raise ValueError(
            "Dead-code policy policy_version does not match its content fingerprint; "
            f"expected {expected_version}. Bump policy_version when policy content changes."
        )
    if policy.get("tool") != "vulture":
        raise ValueError("Dead-code policy tool must be vulture.")
    minimum_confidence = policy.get("min_confidence")
    if not isinstance(minimum_confidence, int) or not 0 <= minimum_confidence <= 100:
        raise ValueError("Dead-code policy min_confidence must be an integer in [0, 100].")
    scan_paths = policy.get("scan_paths")
    if (
        not isinstance(scan_paths, list)
        or not scan_paths
        or not all(isinstance(item, str) and item for item in scan_paths)
    ):
        raise ValueError("Dead-code policy scan_paths must be a non-empty string list.")
    if policy.get("max_new_findings") != 0:
        raise ValueError("Dead-code policy max_new_findings must remain zero.")

    exceptions = policy.get("exceptions")
    if not isinstance(exceptions, dict) or exceptions.get("allowed") is not True:
        raise ValueError("Dead-code policy must explicitly enable reviewed exceptions.")
    entries = exceptions.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Dead-code policy exceptions.entries must be a list.")
    fingerprints: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each dead-code exception must be a JSON object.")
        fingerprint = quality_gate_common.non_empty_string(
            entry.get("fingerprint"), field="fingerprint"
        )
        if fingerprint in fingerprints:
            raise ValueError(f"Duplicate dead-code exception fingerprint: {fingerprint}")
        fingerprints.add(fingerprint)
        path_value = quality_gate_common.non_empty_string(entry.get("path"), field="path").replace(
            "\\", "/"
        )
        kind = quality_gate_common.non_empty_string(entry.get("kind"), field="kind")
        symbol_value = entry.get("symbol")
        if not isinstance(symbol_value, str):
            raise ValueError("Dead-code exception field 'symbol' must be a string.")
        symbol = symbol_value
        line = entry.get("line")
        if not isinstance(line, int) or line < 1:
            raise ValueError("Dead-code exception field 'line' must be a positive integer.")
        confidence = entry.get("confidence")
        if not isinstance(confidence, int) or not 0 <= confidence <= 100:
            raise ValueError(
                "Dead-code exception field 'confidence' must be an integer in [0, 100]."
            )
        expected = f"vulture.v1|{path_value}|{kind}|{symbol}"
        if fingerprint != expected:
            raise ValueError(
                f"Dead-code exception fingerprint does not match its identity: {fingerprint}"
            )
        quality_gate_common.non_empty_string(entry.get("owner"), field="owner")
        quality_gate_common.non_empty_string(entry.get("reason"), field="reason")
        expires_on = quality_gate_common.non_empty_string(
            entry.get("expires_on"), field="expires_on"
        )
        try:
            date.fromisoformat(expires_on)
        except ValueError as exc:
            raise ValueError(
                f"Dead-code exception expires_on is not ISO date: {expires_on}"
            ) from exc
    return policy


def _run_vulture(
    *, repo_root: Path, scan_paths: list[str], minimum_confidence: int
) -> tuple[list[DeadCodeFinding], int, str]:
    command = [
        sys.executable,
        "-m",
        "vulture",
        *scan_paths,
        "--min-confidence",
        str(minimum_confidence),
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in {0, 1, 3}:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no tool output"
        raise RuntimeError(f"Vulture exited {completed.returncode}: {detail}")
    findings = [
        parse_finding(line, repo_root=repo_root)
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    return (
        sorted(findings, key=lambda finding: (finding.path, finding.line, finding.fingerprint)),
        completed.returncode,
        " ".join(command),
    )


def run_gate(*, repo_root: Path, policy_path: Path, output_path: Path) -> int:
    report: dict[str, Any] = {
        "schema_version": "lotus.advise.dead-code-gate.v1",
        "policy_path": policy_path.as_posix(),
        "status": "failed",
        "failures": [],
    }
    try:
        policy = load_policy(policy_path)
        report.update(
            {
                "policy_version": policy["policy_version"],
                "policy_content_fingerprint": quality_gate_common.policy_content_fingerprint(
                    policy
                ),
                "tool": policy["tool"],
                "min_confidence": policy["min_confidence"],
                "scan_paths": policy["scan_paths"],
                "max_new_findings": policy["max_new_findings"],
            }
        )
        findings, return_code, command = _run_vulture(
            repo_root=repo_root,
            scan_paths=policy["scan_paths"],
            minimum_confidence=policy["min_confidence"],
        )
        exceptions = {entry["fingerprint"]: entry for entry in policy["exceptions"]["entries"]}
        today = date.today()
        expired = [
            entry
            for entry in exceptions.values()
            if date.fromisoformat(entry["expires_on"]) < today
        ]
        finding_by_fingerprint = {finding.fingerprint: finding for finding in findings}
        duplicate_findings = len(finding_by_fingerprint) != len(findings)
        new_findings = [finding for finding in findings if finding.fingerprint not in exceptions]
        resolved_exceptions = [
            exceptions[fingerprint]
            for fingerprint in sorted(set(exceptions) - set(finding_by_fingerprint))
        ]
        failures: list[str] = []
        if duplicate_findings:
            failures.append("Vulture returned duplicate finding fingerprints.")
        if new_findings:
            failures.extend(
                f"New dead-code finding: {finding.path}:{finding.line}: {finding.kind} "
                f"'{finding.symbol}' ({finding.confidence}% confidence; "
                f"fingerprint={finding.fingerprint})"
                for finding in new_findings
            )
        if expired:
            failures.extend(
                f"Expired dead-code exception: {entry['fingerprint']} "
                f"(owner={entry['owner']}, expires_on={entry['expires_on']})"
                for entry in expired
            )
        if resolved_exceptions:
            failures.extend(
                f"Resolved dead-code exception must be removed from policy: {entry['fingerprint']}"
                for entry in resolved_exceptions
            )
        report.update(
            {
                "command": command,
                "tool_return_code": return_code,
                "findings": [finding.as_dict() for finding in findings],
                "allowed_findings": [
                    finding.as_dict() for finding in findings if finding.fingerprint in exceptions
                ],
                "new_findings": [finding.as_dict() for finding in new_findings],
                "expired_exceptions": expired,
                "resolved_exceptions": resolved_exceptions,
                "counts": {
                    "findings": len(findings),
                    "allowed": len(findings) - len(new_findings),
                    "new": len(new_findings),
                    "expired": len(expired),
                    "resolved": len(resolved_exceptions),
                },
                "exception_provenance": {
                    "allowed": True,
                    "entries": policy["exceptions"]["entries"],
                },
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
        "Dead-code gate",
        "Dead-code gate passed: {findings} finding(s), {allowed} reviewed exception(s), "
        "no new findings.",
    )


def main() -> int:
    args = quality_gate_common.parse_gate_arguments(
        description=__doc__ or "Dead-code regression gate",
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
