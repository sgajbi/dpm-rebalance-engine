import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import dependency_hygiene_gate
from scripts.dependency_hygiene_gate import DependencyFinding


def _entry(module: str, *, expires_on: str = "2099-01-01") -> dict[str, str]:
    return {
        "code": "DEP002",
        "module": module,
        "path": "requirements.txt",
        "fingerprint": f"deptry.v1|DEP002|requirements.txt|{module}",
        "classification": "pinned-install-closure",
        "owner": "test-owner",
        "reason": "Reviewed test dependency closure entry.",
        "expires_on": expires_on,
    }


def _write_policy(tmp_path: Path, *, modules: list[str]) -> tuple[Path, Path]:
    baseline = {
        "schema_version": "lotus.advise.dependency-hygiene-baseline.v1",
        "baseline_version": "test-baseline",
        "findings": [_entry(module) for module in modules],
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    policy = {
        "schema_version": "lotus.advise.dependency-hygiene-policy.v1",
        "policy_version": "test-policy",
        "tool": "deptry",
        "tool_version": "0.25.1",
        "report_format": "json",
        "config_path": "pyproject.toml",
        "max_new_findings": 0,
        "max_resolved_findings": 0,
        "baseline": {
            "path": "baseline.json",
            "sha256": dependency_hygiene_gate.baseline_content_fingerprint(baseline),
            "owner": "test-owner",
            "reason": "Reviewed test baseline.",
            "expires_on": "2099-01-01",
        },
        "exceptions": {"allowed": False, "entries": []},
    }
    policy["policy_version"] = dependency_hygiene_gate.expected_policy_version(policy)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return policy_path, baseline_path


def _finding(module: str) -> DependencyFinding:
    return DependencyFinding(
        code="DEP002",
        module=module,
        path="requirements.txt",
        line=None,
        column=None,
        message=f"'{module}' defined as a dependency but not used in the codebase",
    )


def test_parse_report_normalizes_absolute_windows_path_and_nullable_location(
    tmp_path: Path,
) -> None:
    payload = [
        {
            "error": {"code": "DEP002", "message": "unused"},
            "module": "sample-package",
            "location": {
                "file": str(tmp_path / "requirements.txt").replace("/", "\\"),
                "line": None,
                "column": None,
            },
        }
    ]

    findings = dependency_hygiene_gate.parse_deptry_report(payload, repo_root=tmp_path)

    assert findings[0].path == "requirements.txt"
    assert findings[0].fingerprint == "deptry.v1|DEP002|requirements.txt|sample-package"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"findings": []}, "must be a list"),
        ([{"module": "sample"}], "error object"),
        (
            [
                {
                    "error": {"code": "DEP002", "message": "unused"},
                    "module": "sample",
                    "location": {"file": "../requirements.txt", "line": None, "column": None},
                }
            ],
            "repository-relative",
        ),
    ],
)
def test_parse_report_rejects_malformed_or_unsafe_findings(payload: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        dependency_hygiene_gate.parse_deptry_report(payload, repo_root=Path.cwd())


def test_validate_tool_version_rejects_unpinned_runtime_tool() -> None:
    with pytest.raises(RuntimeError, match="version mismatch"):
        dependency_hygiene_gate.validate_tool_version("deptry 0.25.2", expected_version="0.25.1")


def test_gate_passes_reviewed_inventory_and_emits_provenance(tmp_path: Path) -> None:
    policy_path, _ = _write_policy(tmp_path, modules=["sample-package"])
    output_path = tmp_path / "gate.json"

    with patch.object(
        dependency_hygiene_gate,
        "_run_deptry",
        return_value=([_finding("sample-package")], 1, "deptry test command", "deptry 0.25.1"),
    ):
        result = dependency_hygiene_gate.run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert report["status"] == "passed"
    assert report["tool_runtime_version"] == "deptry 0.25.1"
    assert report["counts"] == {"baseline": 1, "expired": 0, "findings": 1, "new": 0, "resolved": 0}
    assert report["exception_provenance"] == {"allowed": False, "entries": []}


def test_gate_fails_on_new_finding_with_actionable_fingerprint(tmp_path: Path) -> None:
    policy_path, _ = _write_policy(tmp_path, modules=["reviewed-package"])
    output_path = tmp_path / "gate.json"

    with patch.object(
        dependency_hygiene_gate,
        "_run_deptry",
        return_value=([_finding("new-package")], 1, "deptry test command", "deptry 0.25.1"),
    ):
        result = dependency_hygiene_gate.run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["counts"]["new"] == 1
    assert "Remove the dependency or add a reviewed" in report["failures"][0]
    assert report["new_findings"][0]["fingerprint"].endswith("|new-package")


def test_gate_fails_when_baseline_finding_is_resolved(tmp_path: Path) -> None:
    policy_path, _ = _write_policy(tmp_path, modules=["resolved-package"])
    output_path = tmp_path / "gate.json"

    with patch.object(
        dependency_hygiene_gate,
        "_run_deptry",
        return_value=([], 0, "deptry test command", "deptry 0.25.1"),
    ):
        result = dependency_hygiene_gate.run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["counts"]["resolved"] == 1
    assert "Resolved dependency baseline must be removed" in report["failures"][0]


def test_gate_fails_on_expired_baseline_entry(tmp_path: Path) -> None:
    policy_path, _ = _write_policy(tmp_path, modules=[])
    baseline = {
        "schema_version": "lotus.advise.dependency-hygiene-baseline.v1",
        "baseline_version": "expired-baseline",
        "findings": [_entry("expired-package", expires_on="2020-01-01")],
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["baseline"]["sha256"] = dependency_hygiene_gate.baseline_content_fingerprint(baseline)
    policy["baseline"]["path"] = "baseline.json"
    policy["policy_version"] = dependency_hygiene_gate.expected_policy_version(policy)
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    output_path = tmp_path / "gate.json"

    with patch.object(
        dependency_hygiene_gate,
        "_run_deptry",
        return_value=([_finding("expired-package")], 1, "deptry test command", "deptry 0.25.1"),
    ):
        result = dependency_hygiene_gate.run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["counts"]["expired"] == 1
    assert "Expired dependency-hygiene baseline finding" in report["failures"][0]


def test_gate_fails_closed_when_deptry_cannot_run(tmp_path: Path) -> None:
    policy_path, _ = _write_policy(tmp_path, modules=[])
    output_path = tmp_path / "gate.json"

    with patch.object(
        dependency_hygiene_gate,
        "_run_deptry",
        side_effect=RuntimeError("deptry executable unavailable"),
    ):
        result = dependency_hygiene_gate.run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["status"] == "failed"
    assert report["failures"] == ["deptry executable unavailable"]


def test_gate_rejects_duplicate_normalized_findings(tmp_path: Path) -> None:
    policy_path, _ = _write_policy(tmp_path, modules=[])
    output_path = tmp_path / "gate.json"

    with patch.object(
        dependency_hygiene_gate,
        "_run_deptry",
        return_value=(
            [_finding("duplicate-package"), _finding("duplicate-package")],
            1,
            "deptry test command",
            "deptry 0.25.1",
        ),
    ):
        result = dependency_hygiene_gate.run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["failures"] == ["deptry produced duplicate normalized finding fingerprints."]
