"""Shared deterministic scaffolding for repository quality gates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def non_empty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Quality-gate field {field!r} must be a non-empty string.")
    return value


def load_json_object(path: Path, *, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load {description} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{description.capitalize()} must be a JSON object.")
    return payload


def policy_content_fingerprint(policy: dict[str, Any]) -> str:
    content = {key: value for key, value in policy.items() if key != "policy_version"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def expected_policy_version(policy: dict[str, Any]) -> str:
    version = non_empty_string(policy.get("policy_version"), field="policy_version")
    prefix = version.rsplit("+", 1)[0] if "+" in version else version
    return f"{prefix}+{policy_content_fingerprint(policy)[:12]}"


def write_report(output_path: Path, report: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finish_gate(
    report: dict[str, Any],
    output_path: Path,
    gate_name: str,
    passed_message: str,
) -> int:
    write_report(output_path, report)
    failures = report["failures"]
    if failures:
        print(f"{gate_name} FAILED.")
        for failure in failures:
            print(f"- {failure}")
        print(f"Machine-readable evidence: {output_path}")
        return 1
    counts = report.get("counts", {})
    print(
        passed_message.format(
            findings=counts.get("findings", "unknown"),
            allowed=counts.get("allowed", "unknown"),
            new=counts.get("new", "unknown"),
            resolved=counts.get("resolved", "unknown"),
            policy=report.get("policy_version", "unknown"),
        )
    )
    print(f"Machine-readable evidence: {output_path}")
    return 0


def parse_gate_arguments(
    *,
    description: str,
    default_policy_path: Path,
    default_output_path: Path,
    include_repo_root: bool = False,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    if include_repo_root:
        parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--policy", type=Path, default=default_policy_path)
    parser.add_argument("--output", type=Path, default=default_output_path)
    return parser.parse_args()
