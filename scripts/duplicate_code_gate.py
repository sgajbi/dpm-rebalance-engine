"""Fail closed when jscpd reports a new duplicate-code fingerprint."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from scripts import quality_gate_common

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "quality" / "duplicate-code-policy.v1.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "output" / "duplicate-code-gate.json"
_POLICY_VERSION = re.compile(r"^(?P<prefix>.+)\+(?P<fingerprint>[0-9a-f]{12})$")


@dataclass(frozen=True)
class DuplicateFinding:
    format: str
    first_file: str
    first_start: int
    first_end: int
    second_file: str
    second_start: int
    second_end: int
    lines: int
    tokens: int
    fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_path(value: object) -> str:
    path = quality_gate_common.non_empty_string(value, field="path").replace("\\", "/")
    if path.startswith("/") or ":/" in path:
        raise ValueError(f"Duplicate-code finding path must be repository-relative: {path}")
    return path.removeprefix("./")


def _scoped_path(path: str, *, repo_root: Path | None, scan_paths: tuple[str, ...]) -> str:
    if repo_root is None:
        return path
    if any(path == scope or path.startswith(f"{scope}/") for scope in scan_paths):
        return path
    matches = [f"{scope}/{path}" for scope in scan_paths if (repo_root / scope / path).is_file()]
    if len(matches) > 1:
        raise ValueError(f"jscpd finding path is ambiguous across scan paths: {path}")
    return matches[0] if matches else path


def load_policy(path: Path) -> dict[str, Any]:
    policy = quality_gate_common.load_json_object(path, description="duplicate-code policy")
    if policy.get("schema_version") != "lotus.advise.duplicate-code-policy.v1":
        raise ValueError("Duplicate-code policy has an unsupported schema_version.")
    version = quality_gate_common.non_empty_string(
        policy.get("policy_version"), field="policy_version"
    )
    if _POLICY_VERSION.fullmatch(version) is None:
        raise ValueError(
            "Duplicate-code policy policy_version must end with '+' and a 12-character "
            "content fingerprint."
        )
    expected = quality_gate_common.expected_policy_version(policy)
    if version != expected:
        raise ValueError(
            "Duplicate-code policy policy_version does not match its content fingerprint; "
            f"expected {expected}. Bump policy_version when policy content changes."
        )
    if policy.get("tool") != "jscpd":
        raise ValueError("Duplicate-code policy tool must be jscpd.")
    quality_gate_common.non_empty_string(policy.get("tool_version"), field="tool_version")
    if policy.get("mode") != "strict":
        raise ValueError("Duplicate-code policy mode must remain strict.")
    scan_paths = policy.get("scan_paths")
    if (
        not isinstance(scan_paths, list)
        or not scan_paths
        or not all(isinstance(item, str) and item for item in scan_paths)
    ):
        raise ValueError("Duplicate-code policy scan_paths must be a non-empty string list.")
    formats = policy.get("formats")
    if (
        not isinstance(formats, list)
        or not formats
        or not all(isinstance(item, str) and item for item in formats)
    ):
        raise ValueError("Duplicate-code policy formats must be a non-empty string list.")
    for field in ("min_tokens", "min_lines"):
        value = policy.get(field)
        if not isinstance(value, int) or value < 1:
            raise ValueError(f"Duplicate-code policy {field} must be a positive integer.")
    if policy.get("max_new_findings") != 0:
        raise ValueError("Duplicate-code policy max_new_findings must remain zero.")
    exceptions = policy.get("exceptions")
    if not isinstance(exceptions, dict) or exceptions.get("allowed") is not False:
        raise ValueError("Duplicate-code policy must disable unreviewed exceptions.")
    if exceptions.get("entries") != []:
        raise ValueError("Duplicate-code policy must start with an empty exception set.")
    baseline = policy.get("baseline")
    if not isinstance(baseline, dict):
        raise ValueError("Duplicate-code policy must define baseline provenance.")
    quality_gate_common.non_empty_string(baseline.get("path"), field="baseline.path")
    quality_gate_common.non_empty_string(baseline.get("sha256"), field="baseline.sha256")
    quality_gate_common.non_empty_string(baseline.get("owner"), field="baseline.owner")
    quality_gate_common.non_empty_string(baseline.get("reason"), field="baseline.reason")
    expires_on = quality_gate_common.non_empty_string(
        baseline.get("expires_on"), field="baseline.expires_on"
    )
    try:
        if date.fromisoformat(expires_on) < date.today():
            raise ValueError(f"Duplicate-code baseline has expired: {expires_on}")
    except ValueError as exc:
        if "expired" in str(exc):
            raise
        raise ValueError(
            f"Duplicate-code baseline expires_on is not ISO date: {expires_on}"
        ) from exc
    return policy


def _baseline_fingerprint(baseline: dict[str, Any]) -> str:
    canonical = json.dumps(baseline, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_baseline(path: Path, *, expected_sha256: str) -> set[str]:
    baseline = quality_gate_common.load_json_object(path, description="duplicate-code baseline")
    if baseline.get("schema_version") != "lotus.advise.duplicate-code-baseline.v1":
        raise ValueError("Duplicate-code baseline has an unsupported schema_version.")
    actual_sha256 = _baseline_fingerprint(baseline)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "Duplicate-code baseline does not match policy baseline.sha256; update the "
            "baseline hash and policy version together after review."
        )
    fingerprints = baseline.get("fingerprints")
    if not isinstance(fingerprints, list) or not all(
        isinstance(item, str) and item for item in fingerprints
    ):
        raise ValueError("Duplicate-code baseline fingerprints must be a non-empty string list.")
    values = set(fingerprints)
    if len(values) != len(fingerprints):
        raise ValueError("Duplicate-code baseline contains duplicate fingerprints.")
    for fingerprint in values:
        if not fingerprint.startswith("jscpd.v1|"):
            raise ValueError(f"Unsupported duplicate-code baseline fingerprint: {fingerprint}")
    return values


def _finding_location(
    value: object,
    *,
    field: str,
    repo_root: Path | None,
    scan_paths: tuple[str, ...],
) -> tuple[str, int, int]:
    if not isinstance(value, dict):
        raise ValueError(f"jscpd finding {field} must be an object.")
    path = _scoped_path(
        _canonical_path(value.get("name")),
        repo_root=repo_root,
        scan_paths=scan_paths,
    )
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        raise ValueError(f"jscpd finding {field} has invalid line bounds.")
    return path, start, end


def _base_fingerprint(*, format_name: str, first_file: str, second_file: str, fragment: str) -> str:
    fragment_hash = hashlib.sha256(fragment.replace("\r\n", "\n").encode("utf-8")).hexdigest()
    return f"jscpd.v1|{format_name}|{first_file}|{second_file}|{fragment_hash}"


def parse_jscpd_report(
    payload: dict[str, Any],
    *,
    allowed_formats: set[str],
    repo_root: Path | None = None,
    scan_paths: tuple[str, ...] = (),
) -> list[DuplicateFinding]:
    raw_duplicates = payload.get("duplicates")
    if not isinstance(raw_duplicates, list):
        raise ValueError("jscpd JSON must define a duplicates list.")
    candidates: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_duplicates):
        if not isinstance(raw, dict):
            raise ValueError(f"jscpd duplicate {index} must be an object.")
        format_name = quality_gate_common.non_empty_string(raw.get("format"), field="format")
        if format_name not in allowed_formats:
            raise ValueError(f"jscpd reported unsupported format: {format_name}")
        fragment = quality_gate_common.non_empty_string(raw.get("fragment"), field="fragment")
        first = _finding_location(
            raw.get("firstFile"),
            field="firstFile",
            repo_root=repo_root,
            scan_paths=scan_paths,
        )
        second = _finding_location(
            raw.get("secondFile"),
            field="secondFile",
            repo_root=repo_root,
            scan_paths=scan_paths,
        )
        left, right = sorted((first, second))
        lines = raw.get("lines")
        tokens = raw.get("tokens")
        if not isinstance(lines, int) or lines < 1 or not isinstance(tokens, int) or tokens < 1:
            raise ValueError(f"jscpd duplicate {index} has invalid line/token counts.")
        candidates.append(
            {
                "format": format_name,
                "left": left,
                "right": right,
                "lines": lines,
                "tokens": tokens,
                "base_fingerprint": _base_fingerprint(
                    format_name=format_name,
                    first_file=left[0],
                    second_file=right[0],
                    fragment=fragment,
                ),
            }
        )

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate["base_fingerprint"]].append(candidate)
    findings: list[DuplicateFinding] = []
    for base_fingerprint, group in grouped.items():
        group.sort(key=lambda item: (item["left"][1:], item["right"][1:]))
        for occurrence, candidate in enumerate(group, start=1):
            first = candidate["left"]
            second = candidate["right"]
            findings.append(
                DuplicateFinding(
                    format=candidate["format"],
                    first_file=first[0],
                    first_start=first[1],
                    first_end=first[2],
                    second_file=second[0],
                    second_start=second[1],
                    second_end=second[2],
                    lines=candidate["lines"],
                    tokens=candidate["tokens"],
                    fingerprint=f"{base_fingerprint}|occurrence={occurrence}",
                )
            )
    return sorted(findings, key=lambda finding: finding.fingerprint)


def _jscpd_command(repo_root: Path, tool_version: str) -> list[str]:
    executable_name = "jscpd.cmd" if sys.platform.startswith("win") else "jscpd"
    local_executable = repo_root / "node_modules" / ".bin" / executable_name
    if local_executable.exists():
        return [str(local_executable)]
    npx_executable = "npx.cmd" if sys.platform.startswith("win") else "npx"
    return [npx_executable, "--yes", f"jscpd@{tool_version}"]


def _run_jscpd(*, repo_root: Path, policy: dict[str, Any]) -> tuple[list[DuplicateFinding], str]:
    with tempfile.TemporaryDirectory(prefix="lotus-advise-duplicate-code-") as temporary:
        output_dir = Path(temporary)
        command = [
            *_jscpd_command(repo_root, policy["tool_version"]),
            *policy["scan_paths"],
            "--format",
            ",".join(policy["formats"]),
            "--min-tokens",
            str(policy["min_tokens"]),
            "--min-lines",
            str(policy["min_lines"]),
            "--mode",
            policy["mode"],
            "--reporters",
            "json",
            "--output",
            str(output_dir),
            "--no-colors",
            "--no-tips",
            "--silent",
            "--workers",
            "2",
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
            raise RuntimeError(f"jscpd exited {completed.returncode}: {detail}")
        report_path = output_dir / "jscpd-report.json"
        if not report_path.is_file():
            raise RuntimeError("jscpd did not produce jscpd-report.json.")
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to parse jscpd JSON report: {exc}") from exc
    return (
        parse_jscpd_report(
            payload,
            allowed_formats=set(policy["formats"]),
            repo_root=repo_root,
            scan_paths=tuple(policy["scan_paths"]),
        ),
        " ".join(command),
    )


def run_gate(*, repo_root: Path, policy_path: Path, output_path: Path) -> int:
    report: dict[str, Any] = {
        "schema_version": "lotus.advise.duplicate-code-gate.v1",
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
        findings, command = _run_jscpd(repo_root=repo_root, policy=policy)
        observed = {finding.fingerprint: finding for finding in findings}
        if len(observed) != len(findings):
            raise ValueError("jscpd produced duplicate normalized fingerprints.")
        new_findings = [finding for finding in findings if finding.fingerprint not in baseline]
        resolved = sorted(baseline - set(observed))
        max_new_findings = policy["max_new_findings"]
        failures = []
        if len(new_findings) > max_new_findings:
            failures = [
                "New duplicate-code finding: "
                f"{finding.first_file}:{finding.first_start}-{finding.first_end} and "
                f"{finding.second_file}:{finding.second_start}-{finding.second_end}; "
                f"{finding.lines} lines, {finding.tokens} tokens; "
                f"fingerprint={finding.fingerprint}. Extract a shared owner or update the "
                "reviewed baseline with owner/reason/expiry evidence."
                for finding in new_findings
            ]
        if resolved:
            failures.extend(
                "Resolved duplicate-code baseline must be removed from the baseline; "
                f"bump baseline/policy versions: {fingerprint}"
                for fingerprint in resolved
            )
        report.update(
            {
                "policy_version": policy["policy_version"],
                "policy_content_fingerprint": quality_gate_common.policy_content_fingerprint(
                    policy
                ),
                "tool": policy["tool"],
                "tool_version": policy["tool_version"],
                "mode": policy["mode"],
                "scan_paths": policy["scan_paths"],
                "formats": policy["formats"],
                "min_tokens": policy["min_tokens"],
                "min_lines": policy["min_lines"],
                "max_new_findings": max_new_findings,
                "command": command,
                "findings": [finding.as_dict() for finding in findings],
                "new_findings": [finding.as_dict() for finding in new_findings],
                "counts": {
                    "findings": len(findings),
                    "baseline": len(baseline),
                    "new": len(new_findings),
                    "resolved": len(resolved),
                },
                "resolved_baseline_fingerprints": resolved,
                "baseline_provenance": policy["baseline"],
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
        "Duplicate-code gate",
        "Duplicate-code gate passed: {findings} findings, {new} new, policy={policy}.",
    )


def main() -> int:
    args = quality_gate_common.parse_gate_arguments(
        description=__doc__ or "Duplicate-code regression gate",
        default_policy_path=DEFAULT_POLICY_PATH,
        default_output_path=DEFAULT_OUTPUT_PATH,
    )
    return run_gate(
        repo_root=REPO_ROOT,
        policy_path=args.policy,
        output_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
