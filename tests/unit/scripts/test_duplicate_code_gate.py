import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import duplicate_code_gate
from scripts.duplicate_code_gate import DuplicateFinding
from scripts.quality_gate_common import expected_policy_version


def _write_policy(tmp_path: Path, *, fingerprints: list[str]) -> tuple[Path, Path]:
    baseline = {
        "schema_version": "lotus.advise.duplicate-code-baseline.v1",
        "baseline_version": "test-baseline",
        "fingerprints": fingerprints,
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    policy = {
        "schema_version": "lotus.advise.duplicate-code-policy.v1",
        "policy_version": "test-policy",
        "tool": "jscpd",
        "tool_version": "5.0.16",
        "mode": "strict",
        "scan_paths": ["src", "scripts"],
        "formats": ["python", "sql"],
        "min_tokens": 100,
        "min_lines": 10,
        "max_new_findings": 0,
        "baseline": {
            "path": "baseline.json",
            "sha256": duplicate_code_gate._baseline_fingerprint(baseline),
            "owner": "test-owner",
            "reason": "Reviewed test baseline.",
            "expires_on": "2099-01-01",
        },
        "exceptions": {"allowed": False, "entries": []},
    }
    policy["policy_version"] = expected_policy_version(policy)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return policy_path, baseline_path


def _finding(*, fingerprint: str) -> DuplicateFinding:
    return DuplicateFinding(
        format="python",
        first_file="src/first.py",
        first_start=10,
        first_end=21,
        second_file="src/second.py",
        second_start=30,
        second_end=41,
        lines=12,
        tokens=120,
        fingerprint=fingerprint,
    )


def test_parse_report_scopes_paths_and_numbers_repeated_clone_occurrences(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "first.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "second.py").write_text("", encoding="utf-8")
    duplicate = {
        "format": "python",
        "fragment": "return value\n",
        "firstFile": {"name": "first.py", "start": 10, "end": 21},
        "secondFile": {"name": "second.py", "start": 30, "end": 41},
        "lines": 12,
        "tokens": 120,
    }
    payload = {
        "duplicates": [
            duplicate,
            {**duplicate, "firstFile": {"name": "first.py", "start": 50, "end": 61}},
        ]
    }

    findings = duplicate_code_gate.parse_jscpd_report(
        payload,
        allowed_formats={"python"},
        repo_root=tmp_path,
        scan_paths=("src",),
    )

    assert [finding.fingerprint.rsplit("|", 1)[-1] for finding in findings] == [
        "occurrence=1",
        "occurrence=2",
    ]
    assert findings[0].first_file == "src/first.py"
    assert findings[0].second_file == "src/second.py"


def test_parse_report_rejects_unsupported_format() -> None:
    with pytest.raises(ValueError, match="unsupported format"):
        duplicate_code_gate.parse_jscpd_report(
            {"duplicates": [{"format": "javascript"}]},
            allowed_formats={"python"},
        )


def test_gate_fails_when_a_new_fingerprint_is_observed(tmp_path: Path) -> None:
    baseline_fingerprint = "jscpd.v1|python|src/first.py|src/second.py|baseline|occurrence=1"
    new_finding = _finding(fingerprint="jscpd.v1|python|src/new.py|src/other.py|new|occurrence=1")
    policy_path, _ = _write_policy(tmp_path, fingerprints=[baseline_fingerprint])
    output_path = tmp_path / "duplicate-code.json"

    with patch.object(
        duplicate_code_gate,
        "_run_jscpd",
        return_value=([new_finding], "jscpd test command"),
    ):
        result = duplicate_code_gate.run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["counts"]["new"] == 1
    assert "Extract a shared owner" in report["failures"][0]
    assert report["new_findings"][0]["fingerprint"] == new_finding.fingerprint


def test_gate_fails_when_a_baseline_fingerprint_is_resolved(tmp_path: Path) -> None:
    resolved_fingerprint = "jscpd.v1|python|src/first.py|src/second.py|resolved|occurrence=1"
    policy_path, _ = _write_policy(tmp_path, fingerprints=[resolved_fingerprint])
    output_path = tmp_path / "duplicate-code.json"

    with patch.object(
        duplicate_code_gate,
        "_run_jscpd",
        return_value=([], "jscpd test command"),
    ):
        result = duplicate_code_gate.run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["counts"]["resolved"] == 1
    assert "Resolved duplicate-code baseline must be removed" in report["failures"][0]
    assert resolved_fingerprint in report["resolved_baseline_fingerprints"]


def test_gate_fails_closed_when_scanner_errors(tmp_path: Path) -> None:
    baseline_fingerprint = "jscpd.v1|python|src/first.py|src/second.py|baseline|occurrence=1"
    policy_path, _ = _write_policy(tmp_path, fingerprints=[baseline_fingerprint])
    output_path = tmp_path / "duplicate-code.json"

    with patch.object(
        duplicate_code_gate,
        "_run_jscpd",
        side_effect=RuntimeError("jscpd did not produce JSON"),
    ):
        result = duplicate_code_gate.run_gate(
            repo_root=tmp_path,
            policy_path=policy_path,
            output_path=output_path,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["status"] == "failed"
    assert report["failures"] == ["jscpd did not produce JSON"]


def test_policy_version_must_change_when_policy_content_changes(tmp_path: Path) -> None:
    fingerprint = "jscpd.v1|python|src/first.py|src/second.py|baseline|occurrence=1"
    policy_path, _ = _write_policy(tmp_path, fingerprints=[fingerprint])
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["min_lines"] = 11
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(ValueError, match="content fingerprint"):
        duplicate_code_gate.load_policy(policy_path)


def test_baseline_hash_change_requires_policy_update(tmp_path: Path) -> None:
    fingerprint = "jscpd.v1|python|src/first.py|src/second.py|baseline|occurrence=1"
    policy_path, baseline_path = _write_policy(tmp_path, fingerprints=[fingerprint])
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline["fingerprints"].append("jscpd.v1|python|src/other.py|src/more.py|new|occurrence=1")
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    with pytest.raises(ValueError, match="baseline.sha256"):
        duplicate_code_gate.load_baseline(
            baseline_path,
            expected_sha256=json.loads(policy_path.read_text(encoding="utf-8"))["baseline"][
                "sha256"
            ],
        )
