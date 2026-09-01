from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import quality_trend_gate
from scripts.quality_gate_common import expected_policy_version

BASE_SHA = "a" * 40
HEAD_PYTHON_CONTENT_FINGERPRINT = "b" * 64


def _report(
    *,
    total_lines: int = 100,
    b_ranked_blocks: int = 4,
    worst_complexity: int = 10,
    documentation_total: int = 100,
    documentation_missing: int = 90,
    documentation_covered: int = 10,
    documentation_coverage: float = 1.2,
) -> str:
    return "\n".join(
        [
            f"- Total Python lines: `{total_lines}`",
            f"- Radon complexity rank inventory: `A=20, B={b_ranked_blocks}`",
            f"- Radon worst complexity: `rank=B, complexity={worst_complexity}`",
            "- Interrogate docstring inventory: "
            f"`total={documentation_total}, missing={documentation_missing}, "
            f"covered={documentation_covered}, coverage={documentation_coverage}%`",
        ]
    )


def _policy() -> dict[str, Any]:
    return quality_trend_gate.load_policy(Path("quality/quality-trend-policy.v1.json"))


def test_compare_metrics_passes_within_thresholds_and_reports_deltas() -> None:
    policy = _policy()
    policy["metrics"][0]["allowed_delta"] = 5
    results, failures = quality_trend_gate.compare_metrics(
        quality_trend_gate.parse_report(_report()),
        quality_trend_gate.parse_report(
            _report(
                total_lines=105, b_ranked_blocks=4, worst_complexity=10, documentation_coverage=1.2
            )
        ),
        policy,
        base_sha=BASE_SHA,
        head_python_content_fingerprint=HEAD_PYTHON_CONTENT_FINGERPRINT,
    )

    assert failures == []
    assert results[0].delta == 5
    assert results[0].status == "passed"


def test_compare_metrics_rejects_complexity_and_documentation_regressions() -> None:
    policy = _policy()
    policy["exceptions"]["entries"] = []
    policy["metrics"][0]["allowed_delta"] = 5
    results, failures = quality_trend_gate.compare_metrics(
        quality_trend_gate.parse_report(_report()),
        quality_trend_gate.parse_report(
            _report(
                total_lines=106,
                b_ranked_blocks=5,
                worst_complexity=11,
                documentation_missing=91,
                documentation_covered=9,
                documentation_coverage=1.1,
            )
        ),
        policy,
        base_sha=BASE_SHA,
        head_python_content_fingerprint=HEAD_PYTHON_CONTENT_FINGERPRINT,
    )

    assert len(failures) == 4
    assert all(result.status == "failed" for result in results)
    assert "radon_b_ranked_blocks" in failures[1]
    assert "interrogate_coverage_percent" in failures[3]


def test_compare_metrics_rejects_sub_rounding_interrogate_decrease() -> None:
    policy = _policy()
    policy["exceptions"]["entries"] = []
    base = quality_trend_gate.parse_report(
        _report(
            documentation_total=10_000,
            documentation_missing=9_877,
            documentation_covered=123,
            documentation_coverage=1.2,
        )
    )
    head = quality_trend_gate.parse_report(
        _report(
            documentation_total=10_000,
            documentation_missing=9_878,
            documentation_covered=122,
            documentation_coverage=1.2,
        )
    )

    results, failures = quality_trend_gate.compare_metrics(
        base,
        head,
        policy,
        base_sha=BASE_SHA,
        head_python_content_fingerprint=HEAD_PYTHON_CONTENT_FINGERPRINT,
    )

    assert base["interrogate_coverage_percent"] == pytest.approx(1.23)
    assert head["interrogate_coverage_percent"] == pytest.approx(1.22)
    assert results[3].delta == pytest.approx(-0.01)
    assert results[3].status == "failed"
    assert any("interrogate_coverage_percent" in failure for failure in failures)


@pytest.mark.parametrize(
    ("documentation_total", "documentation_missing", "documentation_covered"),
    [(0, 0, 0), (100, 90, 9)],
)
def test_parse_report_rejects_invalid_interrogate_counts(
    documentation_total: int, documentation_missing: int, documentation_covered: int
) -> None:
    with pytest.raises(ValueError, match="Interrogate report counts"):
        quality_trend_gate.parse_report(
            _report(
                documentation_total=documentation_total,
                documentation_missing=documentation_missing,
                documentation_covered=documentation_covered,
            )
        )


def test_reviewed_exception_is_visible_and_applies_its_expiring_limit() -> None:
    policy = _policy()
    policy["exceptions"]["entries"] = [
        {
            "metric": "radon_b_ranked_blocks",
            "base_sha": BASE_SHA,
            "head_python_content_fingerprint": HEAD_PYTHON_CONTENT_FINGERPRINT,
            "allowed_delta": 2,
            "reason": "Reviewed decomposition is scheduled.",
            "approver": "review-lead",
            "expires_on": "2099-01-01",
        }
    ]
    results, failures = quality_trend_gate.compare_metrics(
        quality_trend_gate.parse_report(_report()),
        quality_trend_gate.parse_report(_report(b_ranked_blocks=6)),
        policy,
        base_sha=BASE_SHA,
        head_python_content_fingerprint=HEAD_PYTHON_CONTENT_FINGERPRINT,
    )

    assert failures == []
    assert results[1].exception is not None
    assert results[1].policy_allowed_delta == 0
    assert results[1].allowed_delta == 2


def test_reviewed_exception_does_not_apply_to_different_python_content() -> None:
    policy = _policy()
    policy["exceptions"]["entries"] = [
        {
            "metric": "radon_b_ranked_blocks",
            "base_sha": BASE_SHA,
            "head_python_content_fingerprint": HEAD_PYTHON_CONTENT_FINGERPRINT,
            "allowed_delta": 2,
            "reason": "Reviewed decomposition is scheduled.",
            "approver": "review-lead",
            "expires_on": "2099-01-01",
        }
    ]
    results, failures = quality_trend_gate.compare_metrics(
        quality_trend_gate.parse_report(_report()),
        quality_trend_gate.parse_report(_report(b_ranked_blocks=6)),
        policy,
        base_sha=BASE_SHA,
        head_python_content_fingerprint="c" * 64,
    )

    assert any("radon_b_ranked_blocks" in failure for failure in failures)
    assert results[1].exception is None
    assert results[1].allowed_delta == 0


def test_current_policy_has_only_revision_bound_python_growth_exceptions() -> None:
    policy = _policy()
    entries = policy["exceptions"]["entries"]

    assert len(entries) == 2
    exceptions_by_base = {entry["base_sha"]: entry for entry in entries}
    benchmark_exception = exceptions_by_base["e879984ed78262ff2dc97bb7f345e1209fe53103"]
    realization_exception = exceptions_by_base["4337fb939bc9d675a49e640678b01fbc40f9fd9d"]
    assert all(entry["metric"] == "total_python_lines" for entry in entries)
    assert all(len(entry["head_python_content_fingerprint"]) == 64 for entry in entries)
    assert all(entry["approver"] == "sgajbi" for entry in entries)
    assert "production +313 lines" in benchmark_exception["reason"]
    assert "tests +259 lines" in benchmark_exception["reason"]
    assert realization_exception["allowed_delta"] == 1508
    assert "+885 net production lines" in realization_exception["reason"]
    assert "+623 net test lines" in realization_exception["reason"]
    assert "atomic conflict rejection with corrected retry" in realization_exception["reason"]
    assert "#607" in realization_exception["reason"]
    total_lines = next(
        metric for metric in policy["metrics"] if metric["name"] == "total_python_lines"
    )
    assert total_lines["allowed_delta"] == 200


def test_python_content_fingerprint_excludes_policy_json_but_detects_python_changes(
    tmp_path: Path,
) -> None:
    def git(*arguments: str) -> None:
        subprocess.run(
            ["git", *arguments], cwd=tmp_path, check=True, capture_output=True, text=True
        )

    git("init")
    git("config", "user.name", "Quality Trend Test")
    git("config", "user.email", "quality-trend-test@example.invalid")
    (tmp_path / "example.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "quality-policy.json").write_text('{"entry": 1}\n', encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "test: establish measured content")
    initial = quality_trend_gate._python_content_fingerprint(tmp_path, "HEAD")

    (tmp_path / "quality-policy.json").write_text('{"entry": 2}\n', encoding="utf-8")
    git("add", "quality-policy.json")
    git("commit", "-m", "test: amend policy metadata")

    assert quality_trend_gate._python_content_fingerprint(tmp_path, "HEAD") == initial

    (tmp_path / "example.py").write_text("value = 2\n", encoding="utf-8")
    git("add", "example.py")
    git("commit", "-m", "test: change measured Python content")

    assert quality_trend_gate._python_content_fingerprint(tmp_path, "HEAD") != initial


def test_active_python_growth_threshold_is_a_hard_200_line_boundary() -> None:
    policy = _policy()
    policy["exceptions"]["entries"] = []
    base = quality_trend_gate.parse_report(_report(total_lines=100))

    within_limit, within_failures = quality_trend_gate.compare_metrics(
        base,
        quality_trend_gate.parse_report(_report(total_lines=300)),
        policy,
        base_sha=BASE_SHA,
        head_python_content_fingerprint=HEAD_PYTHON_CONTENT_FINGERPRINT,
    )
    beyond_limit, beyond_failures = quality_trend_gate.compare_metrics(
        base,
        quality_trend_gate.parse_report(_report(total_lines=301)),
        policy,
        base_sha=BASE_SHA,
        head_python_content_fingerprint=HEAD_PYTHON_CONTENT_FINGERPRINT,
    )

    assert within_failures == []
    assert within_limit[0].delta == 200
    assert within_limit[0].allowed_delta == 200
    assert beyond_limit[0].delta == 201
    assert beyond_limit[0].status == "failed"
    assert beyond_failures == [
        "Quality trend regression: total_python_lines base=100, head=301, delta=+201, "
        "allowed_delta=200 (policy=200). Review the change or add an expiring, approved exception."
    ]


def test_load_policy_rejects_content_without_a_matching_fingerprint(tmp_path: Path) -> None:
    policy = json.loads(Path("quality/quality-trend-policy.v1.json").read_text(encoding="utf-8"))
    policy["policy_version"] = "lotus-advise-quality-trend.v1+000000000000"
    policy_path = tmp_path / "quality-trend-policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(ValueError, match="content fingerprint"):
        quality_trend_gate.load_policy(policy_path)


def test_load_policy_rejects_expired_reviewed_exception(tmp_path: Path) -> None:
    policy = json.loads(Path("quality/quality-trend-policy.v1.json").read_text(encoding="utf-8"))
    policy["exceptions"]["entries"] = [
        {
            "metric": "total_python_lines",
            "base_sha": BASE_SHA,
            "head_python_content_fingerprint": HEAD_PYTHON_CONTENT_FINGERPRINT,
            "allowed_delta": 501,
            "reason": "Expired test exception.",
            "approver": "review-lead",
            "expires_on": "2000-01-01",
        }
    ]
    policy["policy_version"] = expected_policy_version(policy)
    policy_path = tmp_path / "quality-trend-policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(ValueError, match="Expired quality-trend exception"):
        quality_trend_gate.load_policy(policy_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_sha", ""),
        ("head_python_content_fingerprint", "not-a-sha"),
    ],
)
def test_load_policy_rejects_unbound_or_malformed_exception_revision(
    tmp_path: Path, field: str, value: str
) -> None:
    policy = json.loads(Path("quality/quality-trend-policy.v1.json").read_text(encoding="utf-8"))
    entry = {
        "metric": "total_python_lines",
        "base_sha": BASE_SHA,
        "head_python_content_fingerprint": HEAD_PYTHON_CONTENT_FINGERPRINT,
        "allowed_delta": 501,
        "reason": "Bounded test exception.",
        "approver": "review-lead",
        "expires_on": "2099-01-01",
    }
    entry[field] = value
    policy["exceptions"]["entries"] = [entry]
    policy["policy_version"] = expected_policy_version(policy)
    policy_path = tmp_path / "quality-trend-policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(ValueError, match=rf"exceptions\[\]\.{field}"):
        quality_trend_gate.load_policy(policy_path)


def test_run_gate_compares_reports_and_preserves_failure_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quality_dir = tmp_path / "quality"
    quality_dir.mkdir()
    policy_path = quality_dir / "quality-trend-policy.v1.json"
    policy_path.write_text(
        json.dumps(
            json.loads(Path("quality/quality-trend-policy.v1.json").read_text(encoding="utf-8"))
        ),
        encoding="utf-8",
    )
    report_path = quality_dir / "baseline_report.md"
    report_path.write_text(_report(), encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True)

    git("init")
    git("config", "user.name", "Quality Trend Test")
    git("config", "user.email", "quality-trend-test@example.invalid")
    git("branch", "-M", "main")
    git("add", ".")
    git("commit", "-m", "test: establish quality baseline")
    git("switch", "-c", "feature")
    report_path.write_text(_report(total_lines=104, b_ranked_blocks=5), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "test: advance feature quality baseline")
    git("switch", "main")
    report_path.write_text(_report(total_lines=103), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "test: advance unrelated main baseline")
    git("switch", "feature")

    comparison_base_sha = subprocess.check_output(
        ["git", "merge-base", "main", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    head_python_content_fingerprint = quality_trend_gate._python_content_fingerprint(
        tmp_path, "HEAD"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["exceptions"]["entries"] = [
        {
            "metric": "radon_b_ranked_blocks",
            "base_sha": comparison_base_sha,
            "head_python_content_fingerprint": head_python_content_fingerprint,
            "allowed_delta": 1,
            "reason": "Bounded comparison-pair regression fixture.",
            "approver": "review-lead",
            "expires_on": "2099-01-01",
        }
    ]
    policy["policy_version"] = expected_policy_version(policy)
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    output_path = tmp_path / "output" / "quality-trend-gate.json"
    result = quality_trend_gate.run_gate(
        repo_root=tmp_path,
        policy_path=policy_path,
        output_path=output_path,
        base_ref="main",
        head_ref="HEAD",
    )
    evidence = json.loads(output_path.read_text(encoding="utf-8"))

    assert result == 0
    assert evidence["status"] == "passed"
    assert evidence["counts"]["findings"] == 4
    assert evidence["base_ref_sha"] != evidence["base_sha"]
    assert evidence["base_sha"] == comparison_base_sha
    assert evidence["merge_base_sha"] == comparison_base_sha
    assert evidence["head_sha"] == head_sha
    assert evidence["head_python_content_fingerprint"] == head_python_content_fingerprint
    assert evidence["counts"]["exceptions"] == 1
    assert evidence["supplied_base_ref"] == "main"
    assert evidence["base_ref"] == "main"
    assert evidence["base_ref_fallback"] is False
    assert evidence["metrics"][0]["base"] == 100.0
    assert evidence["metrics"][0]["head"] == 104.0
    assert evidence["metrics"][0]["delta"] == 4.0

    fallback_output_path = tmp_path / "output" / "quality-trend-gate-fallback.json"
    fallback_result = quality_trend_gate.run_gate(
        repo_root=tmp_path,
        policy_path=policy_path,
        output_path=fallback_output_path,
        base_ref="feature",
        head_ref="HEAD",
    )
    fallback_evidence = json.loads(fallback_output_path.read_text(encoding="utf-8"))

    assert fallback_result == 0
    assert fallback_evidence["supplied_base_ref"] == "feature"
    assert fallback_evidence["base_ref"] == "HEAD^"
    assert fallback_evidence["base_ref_fallback"] is True

    def malformed_baseline(_repo_root: Path, _ref: str, _path: str) -> str:
        return "- Total Python lines: `100`"

    monkeypatch.setattr(quality_trend_gate, "_git_file", malformed_baseline)
    failure_output_path = tmp_path / "output" / "quality-trend-gate-failure.json"
    failure_result = quality_trend_gate.run_gate(
        repo_root=tmp_path,
        policy_path=policy_path,
        output_path=failure_output_path,
        base_ref="feature",
        head_ref="HEAD",
    )
    failure_evidence = json.loads(failure_output_path.read_text(encoding="utf-8"))

    assert failure_result == 1
    assert failure_evidence["status"] == "failed"
    assert failure_evidence["supplied_base_ref"] == "feature"
    assert failure_evidence["base_ref"] == "HEAD^"
    assert failure_evidence["base_ref_fallback"] is True
    assert "missing metric" in failure_evidence["failures"][0]


def test_run_gate_preserves_a_reviewed_pr_base_after_rebase_mainline_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quality_dir = tmp_path / "quality"
    quality_dir.mkdir()
    policy_path = quality_dir / "quality-trend-policy.v1.json"
    policy_path.write_text(
        json.dumps(
            json.loads(Path("quality/quality-trend-policy.v1.json").read_text(encoding="utf-8"))
        ),
        encoding="utf-8",
    )
    report_path = quality_dir / "baseline_report.md"
    report_path.write_text(_report(), encoding="utf-8")
    source_path = tmp_path / "example.py"
    source_path.write_text("value = 1\n", encoding="utf-8")

    def git(*arguments: str) -> None:
        subprocess.run(
            ["git", *arguments], cwd=tmp_path, check=True, capture_output=True, text=True
        )

    git("init")
    git("config", "user.name", "Quality Trend Test")
    git("config", "user.email", "quality-trend-test@example.invalid")
    git("add", ".")
    git("commit", "-m", "test: establish reviewed PR base")
    reviewed_base_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()

    source_path.write_text("value = 1\nvalue += 2\n", encoding="utf-8")
    git("add", "example.py")
    git("commit", "-m", "feat: add reviewed source")
    (tmp_path / "README.md").write_text("intermediate rebase commit\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "docs: retain intermediate rebase commit")

    head_python_content_fingerprint = quality_trend_gate._python_content_fingerprint(
        tmp_path, "HEAD"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["exceptions"]["entries"] = [
        {
            "metric": "total_python_lines",
            "base_sha": reviewed_base_sha,
            "head_python_content_fingerprint": head_python_content_fingerprint,
            "allowed_delta": 204,
            "reason": "Reviewed rebase-mainline provenance fixture.",
            "approver": "review-lead",
            "expires_on": "2099-01-01",
        }
    ]
    policy["policy_version"] = expected_policy_version(policy)
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    report_path.write_text(_report(total_lines=304), encoding="utf-8")
    git("add", "quality")
    git("commit", "-m", "build: approve reviewed source growth")

    output_path = tmp_path / "output" / "quality-trend-gate.json"
    result = quality_trend_gate.run_gate(
        repo_root=tmp_path,
        policy_path=policy_path,
        output_path=output_path,
        base_ref="HEAD^",
        head_ref="HEAD",
    )
    evidence = json.loads(output_path.read_text(encoding="utf-8"))

    assert result == 0
    assert evidence["status"] == "passed"
    assert evidence["base_ref_sha"] == evidence["merge_base_sha"]
    assert evidence["base_sha"] == reviewed_base_sha
    assert evidence["comparison_base_source"] == "reviewed_exception"
    assert evidence["metrics"][0]["delta"] == 204.0
    assert evidence["metrics"][0]["allowed_delta"] == 204.0

    ambiguous_policy = {
        "exceptions": {
            "entries": [
                {
                    "base_sha": "a" * 40,
                    "head_python_content_fingerprint": HEAD_PYTHON_CONTENT_FINGERPRINT,
                },
                {
                    "base_sha": "b" * 40,
                    "head_python_content_fingerprint": HEAD_PYTHON_CONTENT_FINGERPRINT,
                },
            ]
        }
    }
    monkeypatch.setattr(quality_trend_gate, "_git_is_ancestor", lambda *_args: True)

    with pytest.raises(ValueError, match="Ambiguous reviewed quality-trend exception bases"):
        quality_trend_gate._reviewed_exception_comparison_base(
            repo_root=tmp_path,
            policy=ambiguous_policy,
            supplied_merge_base_sha="c" * 40,
            head_sha="d" * 40,
            head_python_content_fingerprint=HEAD_PYTHON_CONTENT_FINGERPRINT,
        )


def test_reviewed_exception_base_requires_ancestry_and_git_failure_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = {
        "exceptions": {
            "entries": [
                {
                    "base_sha": "a" * 40,
                    "head_python_content_fingerprint": HEAD_PYTHON_CONTENT_FINGERPRINT,
                }
            ]
        }
    }
    monkeypatch.setattr(quality_trend_gate, "_git_is_ancestor", lambda *_args: False)

    assert quality_trend_gate._reviewed_exception_comparison_base(
        repo_root=tmp_path,
        policy=policy,
        supplied_merge_base_sha="c" * 40,
        head_sha="d" * 40,
        head_python_content_fingerprint=HEAD_PYTHON_CONTENT_FINGERPRINT,
    ) == ("c" * 40, "supplied_merge_base")
    monkeypatch.undo()

    def failed_git(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="git unavailable"
        )

    monkeypatch.setattr(quality_trend_gate.subprocess, "run", failed_git)

    with pytest.raises(
        ValueError, match="Unable to verify reviewed quality-trend exception ancestry"
    ):
        quality_trend_gate._git_is_ancestor(tmp_path, "a" * 40, "d" * 40)
