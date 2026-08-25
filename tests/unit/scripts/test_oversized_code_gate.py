from __future__ import annotations

import json
from pathlib import Path

from scripts import oversized_code_gate
from scripts.oversized_code_gate import baseline_content_fingerprint
from scripts.quality_gate_common import expected_policy_version


def _finding(*, kind: str, path: str, symbol: str, max_lines: int) -> dict[str, object]:
    identity = f"{path}|{symbol}" if kind == "function" else path
    return {
        "kind": kind,
        "path": path,
        "symbol": symbol,
        "fingerprint": f"oversized-code.v1|{kind}|{identity}",
        "max_lines": max_lines,
        "owner": "test-owner",
        "reason": "Test baseline is intentionally explicit.",
        "expires_on": "2099-01-01",
    }


def _fixture(
    tmp_path: Path,
    *,
    findings: list[dict[str, object]] | None = None,
    module_max_lines: int = 100,
    function_max_lines: int = 10,
    expires_on: str = "2099-01-01",
) -> tuple[Path, Path, Path]:
    (tmp_path / "src").mkdir()
    (tmp_path / "quality").mkdir()
    baseline = {
        "schema_version": "lotus.advise.oversized-code-baseline.v1",
        "baseline_version": "test-baseline",
        "findings": findings or [],
    }
    baseline_path = tmp_path / "quality" / "oversized-code-baseline.v1.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    policy = {
        "schema_version": "lotus.advise.oversized-code-policy.v1",
        "policy_version": "test-policy",
        "scan_paths": ["src"],
        "thresholds": {
            "module_max_lines": module_max_lines,
            "function_max_lines": function_max_lines,
        },
        "baseline": {
            "path": "quality/oversized-code-baseline.v1.json",
            "sha256": baseline_content_fingerprint(baseline),
            "owner": "test-owner",
            "reason": "Test policy is intentionally explicit.",
            "expires_on": expires_on,
        },
        "exceptions": {"allowed": False, "entries": []},
    }
    policy["policy_version"] = expected_policy_version(policy)
    policy_path = tmp_path / "quality" / "oversized-code-policy.v1.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return tmp_path, policy_path, tmp_path / "output" / "gate.json"


def _write_source(repo_root: Path, relative_path: str, lines: list[str]) -> None:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(repo_root: Path, policy_path: Path, output_path: Path) -> dict[str, object]:
    exit_code = oversized_code_gate.run_gate(
        repo_root=repo_root,
        policy_path=policy_path,
        output_path=output_path,
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))
    report["exit_code"] = exit_code
    return report


def test_gate_passes_reviewed_baseline_and_reports_exact_inventory(tmp_path: Path) -> None:
    finding = _finding(kind="module", path="src/legacy.py", symbol="__module__", max_lines=4)
    repo_root, policy_path, output_path = _fixture(
        tmp_path,
        findings=[finding],
        module_max_lines=3,
    )
    _write_source(repo_root, "src/legacy.py", ["a = 1", "b = 2", "c = 3", "d = 4"])

    report = _run(repo_root, policy_path, output_path)

    assert report["exit_code"] == 0
    assert report["status"] == "passed"
    assert report["counts"] == {
        "baseline": 1,
        "expired": 0,
        "findings": 1,
        "functions": 0,
        "grown": 0,
        "modules": 1,
        "new": 0,
        "resolved": 0,
        "shrunken": 0,
    }


def test_gate_report_preserves_policy_and_baseline_provenance(tmp_path: Path) -> None:
    repo_root, policy_path, output_path = _fixture(tmp_path)

    report = _run(repo_root, policy_path, output_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))

    assert report["status"] == "passed"
    assert report["policy_version"] == policy["policy_version"]
    assert report["scan_paths"] == ["src"]
    assert report["thresholds"] == {"module_max_lines": 100, "function_max_lines": 10}
    assert report["baseline_provenance"]["findings"] == []
    assert report["exception_provenance"] == {"allowed": False, "entries": []}
    assert report["new_findings"] == []
    assert report["grown_findings"] == []
    assert report["shrunken_findings"] == []
    assert report["resolved_baseline_findings"] == []
    assert report["expired_baseline_findings"] == []


def test_gate_rejects_new_oversized_module_with_actionable_fingerprint(tmp_path: Path) -> None:
    repo_root, policy_path, output_path = _fixture(tmp_path, module_max_lines=3)
    _write_source(repo_root, "src/new.py", ["a = 1", "b = 2", "c = 3", "d = 4"])

    report = _run(repo_root, policy_path, output_path)

    assert report["exit_code"] == 1
    assert report["status"] == "failed"
    assert report["counts"]["new"] == 1
    assert "src/new.py:__module__ has 4 lines; threshold=3" in report["failures"][0]
    assert "oversized-code.v1|module|src/new.py" in report["failures"][0]


def test_gate_rejects_growth_of_existing_finding(tmp_path: Path) -> None:
    finding = _finding(kind="module", path="src/legacy.py", symbol="__module__", max_lines=4)
    repo_root, policy_path, output_path = _fixture(
        tmp_path,
        findings=[finding],
        module_max_lines=3,
    )
    _write_source(repo_root, "src/legacy.py", ["a = 1", "b = 2", "c = 3", "d = 4", "e = 5"])

    report = _run(repo_root, policy_path, output_path)

    assert report["exit_code"] == 1
    assert report["counts"]["grown"] == 1
    assert "baseline_max=4" in report["failures"][0]


def test_gate_rejects_shrink_without_baseline_ratchet(tmp_path: Path) -> None:
    finding = _finding(kind="module", path="src/legacy.py", symbol="__module__", max_lines=5)
    repo_root, policy_path, output_path = _fixture(
        tmp_path,
        findings=[finding],
        module_max_lines=3,
    )
    _write_source(repo_root, "src/legacy.py", ["a = 1", "b = 2", "c = 3", "d = 4"])

    report = _run(repo_root, policy_path, output_path)

    assert report["exit_code"] == 1
    assert report["counts"]["shrunken"] == 1
    assert report["shrunken_findings"][0]["lines"] == 4
    assert "src/legacy.py:__module__ has 4 lines" in report["failures"][0]
    assert "baseline_max=5" in report["failures"][0]
    assert "bump the baseline/policy fingerprints" in report["failures"][0]


def test_gate_rejects_stale_baseline_after_hotspot_is_removed(tmp_path: Path) -> None:
    finding = _finding(kind="module", path="src/legacy.py", symbol="__module__", max_lines=4)
    repo_root, policy_path, output_path = _fixture(
        tmp_path,
        findings=[finding],
        module_max_lines=3,
    )

    report = _run(repo_root, policy_path, output_path)

    assert report["exit_code"] == 1
    assert report["counts"]["resolved"] == 1
    assert "Resolved oversized-code baseline must be removed" in report["failures"][0]


def test_gate_collects_qualified_nested_function_names(tmp_path: Path) -> None:
    finding = _finding(
        kind="function",
        path="src/service.py",
        symbol="Service.execute",
        max_lines=4,
    )
    repo_root, policy_path, output_path = _fixture(
        tmp_path,
        findings=[finding],
        function_max_lines=3,
    )
    _write_source(
        repo_root,
        "src/service.py",
        [
            "class Service:",
            "    def execute(self):",
            "        one = 1",
            "        two = 2",
            "        return one + two",
        ],
    )

    report = _run(repo_root, policy_path, output_path)

    assert report["exit_code"] == 0
    assert report["findings"][0]["symbol"] == "Service.execute"


def test_gate_fails_closed_for_syntax_errors(tmp_path: Path) -> None:
    repo_root, policy_path, output_path = _fixture(tmp_path)
    _write_source(repo_root, "src/broken.py", ["def broken(:", "    pass"])

    report = _run(repo_root, policy_path, output_path)

    assert report["exit_code"] == 1
    assert report["status"] == "failed"
    assert "invalid syntax" in report["failures"][0]


def test_gate_rejects_policy_content_without_version_bump(tmp_path: Path) -> None:
    repo_root, policy_path, output_path = _fixture(tmp_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["thresholds"]["module_max_lines"] = 99
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    report = _run(repo_root, policy_path, output_path)

    assert report["exit_code"] == 1
    assert "does not match its content fingerprint" in report["failures"][0]


def test_gate_rejects_expired_baseline_provenance(tmp_path: Path) -> None:
    repo_root, policy_path, output_path = _fixture(tmp_path, expires_on="2000-01-01")

    report = _run(repo_root, policy_path, output_path)

    assert report["exit_code"] == 1
    assert "Expired oversized-code baseline provenance" in report["failures"][0]


def test_gate_rejects_baseline_path_traversal_after_policy_version_update(tmp_path: Path) -> None:
    repo_root, policy_path, output_path = _fixture(tmp_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["baseline"]["path"] = "../outside.json"
    policy["policy_version"] = expected_policy_version(policy)
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    report = _run(repo_root, policy_path, output_path)

    assert report["exit_code"] == 1
    assert "baseline.path must be repository-relative" in report["failures"][0]
