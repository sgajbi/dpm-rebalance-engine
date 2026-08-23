from pathlib import Path

import coverage

from scripts.changed_coverage_gate import _coverage_percent, _load_policy


def test_coverage_percent_reports_uncovered_executable_lines(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "def choose(flag):\n    if flag:\n        return 'yes'\n    return 'no'\nchoose(True)\n",
        encoding="utf-8",
    )
    data_file = tmp_path / ".coverage"
    measured = coverage.Coverage(data_file=str(data_file), branch=True)
    measured.start()
    exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), {})
    measured.stop()
    measured.save()

    result = _coverage_percent(measured, source)

    assert result["file"] == source.as_posix()
    assert result["statement_count"] > result["covered_statements"]
    assert result["percent"] < 100.0
    assert result["missing_lines"]


def test_quality_policy_exposes_changed_source_threshold() -> None:
    version, threshold = _load_policy(Path("quality/quality-policy.v1.json"))

    assert version == "lotus-advise-quality.v1"
    assert threshold == 90.0
