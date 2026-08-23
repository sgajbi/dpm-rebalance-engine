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

    result = _coverage_percent(measured, source, changed_lines={4})

    assert result["file"] == source.as_posix()
    assert result["changed_executable_lines"] == [4]
    assert result["statement_count"] == 1
    assert result["covered_statements"] == 0
    assert result["percent"] == 0.0
    assert result["missing_lines"]


def test_coverage_percent_maps_changed_multiline_statement_continuations(tmp_path: Path) -> None:
    source = tmp_path / "multiline.py"
    source.write_text(
        "def message():\n"
        "    return (\n"
        "        'covered'\n"
        "        ' continuation'\n"
        "    )\n"
        "message()\n",
        encoding="utf-8",
    )
    data_file = tmp_path / ".coverage"
    measured = coverage.Coverage(data_file=str(data_file), branch=True)
    measured.start()
    exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), {})
    measured.stop()
    measured.save()

    result = _coverage_percent(measured, source, changed_lines={4})

    assert result["changed_executable_lines"] == [2]
    assert result["percent"] == 100.0


def test_quality_policy_exposes_changed_source_threshold() -> None:
    version, threshold = _load_policy(Path("quality/quality-policy.v1.json"))

    assert version == "lotus-advise-quality.v1"
    assert threshold == 90.0
