import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import dead_code_gate
from scripts.dead_code_gate import DeadCodeFinding, load_policy, parse_finding, run_gate
from scripts.quality_gate_common import expected_policy_version


def _completed(*, stdout: str = "", returncode: int = 0, stderr: str = "") -> object:
    return type(
        "CompletedVulture",
        (),
        {"stdout": stdout, "returncode": returncode, "stderr": stderr},
    )()


def _write_policy(path: Path, policy: dict[str, object]) -> None:
    policy["policy_version"] = expected_policy_version(policy)
    path.write_text(json.dumps(policy), encoding="utf-8")


def test_parse_finding_normalizes_path_and_builds_stable_fingerprint(tmp_path: Path) -> None:
    finding = parse_finding(
        r"src\core\advisory\sample.py:12: unused import '_helper' (90% confidence)",
        repo_root=tmp_path,
    )

    assert finding == DeadCodeFinding(
        path="src/core/advisory/sample.py",
        line=12,
        kind="unused import",
        symbol="_helper",
        confidence=90,
    )
    assert finding.fingerprint == ("vulture.v1|src/core/advisory/sample.py|unused import|_helper")


def test_parse_finding_supports_vultures_no_symbol_unreachable_code_report(
    tmp_path: Path,
) -> None:
    finding = parse_finding(
        "src/sample.py:4: unreachable code (100% confidence)",
        repo_root=tmp_path,
    )

    assert finding.kind == "unreachable code"
    assert finding.symbol == ""
    assert finding.fingerprint == "vulture.v1|src/sample.py|unreachable code|"


def test_gate_passes_only_reviewed_findings_and_emits_provenance(tmp_path: Path) -> None:
    finding = "src/sample.py:4: unused function 'legacy' (90% confidence)\n"
    policy = {
        "schema_version": "lotus.advise.dead-code-policy.v1",
        "policy_version": "test-policy",
        "tool": "vulture",
        "min_confidence": 80,
        "scan_paths": ["src", "scripts"],
        "max_new_findings": 0,
        "exceptions": {
            "allowed": True,
            "entries": [
                {
                    "fingerprint": "vulture.v1|src/sample.py|unused function|legacy",
                    "path": "src/sample.py",
                    "line": 4,
                    "kind": "unused function",
                    "symbol": "legacy",
                    "confidence": 90,
                    "owner": "test-owner",
                    "reason": "Compatibility surface under review.",
                    "expires_on": "2099-01-01",
                }
            ],
        },
    }
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "output.json"
    _write_policy(policy_path, policy)

    with patch.object(dead_code_gate.subprocess, "run", return_value=_completed(stdout=finding)):
        result = run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert report["status"] == "passed"
    assert report["max_new_findings"] == 0
    assert report["counts"] == {"findings": 1, "allowed": 1, "new": 0, "expired": 0, "resolved": 0}
    assert report["exception_provenance"]["entries"][0]["owner"] == "test-owner"


def test_gate_fails_on_unapproved_finding_with_actionable_fingerprint(tmp_path: Path) -> None:
    policy = {
        "schema_version": "lotus.advise.dead-code-policy.v1",
        "policy_version": "test-policy",
        "tool": "vulture",
        "min_confidence": 80,
        "scan_paths": ["src"],
        "max_new_findings": 0,
        "exceptions": {"allowed": True, "entries": []},
    }
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "output.json"
    _write_policy(policy_path, policy)

    with patch.object(
        dead_code_gate.subprocess,
        "run",
        return_value=_completed(
            stdout="src/new.py:8: unused variable 'uncovered' (80% confidence)\n",
            returncode=3,
        ),
    ):
        result = run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["status"] == "failed"
    assert report["new_findings"][0]["path"] == "src/new.py"
    assert "vulture.v1|src/new.py|unused variable|uncovered" in report["failures"][0]


def test_gate_fails_closed_on_malformed_tool_output(tmp_path: Path) -> None:
    policy = {
        "schema_version": "lotus.advise.dead-code-policy.v1",
        "policy_version": "test-policy",
        "tool": "vulture",
        "min_confidence": 80,
        "scan_paths": ["src"],
        "max_new_findings": 0,
        "exceptions": {"allowed": True, "entries": []},
    }
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "output.json"
    _write_policy(policy_path, policy)

    with patch.object(
        dead_code_gate.subprocess,
        "run",
        return_value=_completed(stdout="unexpected scanner output\n", returncode=0),
    ):
        result = run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["status"] == "failed"
    assert "Unable to parse Vulture finding" in report["failures"][0]


def test_gate_fails_closed_when_vulture_is_unavailable(tmp_path: Path) -> None:
    policy = {
        "schema_version": "lotus.advise.dead-code-policy.v1",
        "policy_version": "test-policy",
        "tool": "vulture",
        "min_confidence": 80,
        "scan_paths": ["src"],
        "max_new_findings": 0,
        "exceptions": {"allowed": True, "entries": []},
    }
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "output.json"
    _write_policy(policy_path, policy)

    with patch.object(
        dead_code_gate.subprocess,
        "run",
        return_value=_completed(returncode=127, stderr="No module named vulture"),
    ):
        result = run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["status"] == "failed"
    assert "Vulture exited 127" in report["failures"][0]


def test_gate_fails_when_a_reviewed_exception_is_expired(tmp_path: Path) -> None:
    policy = {
        "schema_version": "lotus.advise.dead-code-policy.v1",
        "policy_version": "test-policy",
        "tool": "vulture",
        "min_confidence": 80,
        "scan_paths": ["src"],
        "max_new_findings": 0,
        "exceptions": {
            "allowed": True,
            "entries": [
                {
                    "fingerprint": "vulture.v1|src/sample.py|unused function|legacy",
                    "path": "src/sample.py",
                    "line": 4,
                    "kind": "unused function",
                    "symbol": "legacy",
                    "confidence": 90,
                    "owner": "test-owner",
                    "reason": "Compatibility surface under review.",
                    "expires_on": "2000-01-01",
                }
            ],
        },
    }
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "output.json"
    _write_policy(policy_path, policy)

    with patch.object(
        dead_code_gate.subprocess,
        "run",
        return_value=_completed(
            stdout="src/sample.py:4: unused function 'legacy' (90% confidence)\n",
            returncode=3,
        ),
    ):
        result = run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert "Expired dead-code exception" in report["failures"][0]


def test_gate_fails_when_a_reviewed_exception_is_resolved(tmp_path: Path) -> None:
    policy = {
        "schema_version": "lotus.advise.dead-code-policy.v1",
        "policy_version": "test-policy",
        "tool": "vulture",
        "min_confidence": 80,
        "scan_paths": ["src"],
        "max_new_findings": 0,
        "exceptions": {
            "allowed": True,
            "entries": [
                {
                    "fingerprint": "vulture.v1|src/sample.py|unused function|legacy",
                    "path": "src/sample.py",
                    "line": 4,
                    "kind": "unused function",
                    "symbol": "legacy",
                    "confidence": 90,
                    "owner": "test-owner",
                    "reason": "Compatibility surface under review.",
                    "expires_on": "2099-01-01",
                }
            ],
        },
    }
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "output.json"
    _write_policy(policy_path, policy)

    with patch.object(dead_code_gate.subprocess, "run", return_value=_completed()):
        result = run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["counts"]["resolved"] == 1
    assert "Resolved dead-code exception must be removed from policy" in report["failures"][0]


def test_policy_version_must_change_when_policy_content_changes(tmp_path: Path) -> None:
    policy = {
        "schema_version": "lotus.advise.dead-code-policy.v1",
        "policy_version": "test-policy",
        "tool": "vulture",
        "min_confidence": 80,
        "scan_paths": ["src"],
        "max_new_findings": 0,
        "exceptions": {"allowed": True, "entries": []},
    }
    policy_path = tmp_path / "policy.json"
    _write_policy(policy_path, policy)
    original_version = policy["policy_version"]

    changed_policy = json.loads(policy_path.read_text(encoding="utf-8"))
    changed_policy["scan_paths"] = ["src", "scripts"]
    policy_path.write_text(json.dumps(changed_policy), encoding="utf-8")

    with pytest.raises(ValueError, match="Bump policy_version when policy content changes"):
        load_policy(policy_path)

    changed_policy["policy_version"] = expected_policy_version(changed_policy)
    policy_path.write_text(json.dumps(changed_policy), encoding="utf-8")
    loaded = load_policy(policy_path)
    assert loaded["policy_version"] != original_version
    assert loaded["policy_version"] == expected_policy_version(loaded)


def test_repository_policy_is_versioned_and_classifies_current_facade_findings() -> None:
    policy = load_policy(Path("quality/dead-code-policy.v1.json"))

    assert policy["policy_version"].startswith("lotus-advise-dead-code.v1+")
    assert policy["policy_version"] == expected_policy_version(policy)
    assert policy["max_new_findings"] == 0
    assert len(policy["exceptions"]["entries"]) == 6
