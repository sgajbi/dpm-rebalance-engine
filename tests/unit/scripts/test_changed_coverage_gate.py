import json
from pathlib import Path
from unittest.mock import patch

import coverage
import pytest

from scripts import changed_coverage_gate
from scripts.changed_coverage_gate import _coverage_percent, _load_policy, run_gate


def _completed_diff(diff: str) -> object:
    return type("CompletedDiff", (), {"stdout": diff})()


@pytest.mark.parametrize(
    ("diff", "expected"),
    [
        (
            "diff --git a/src/sample.py b/src/sample.py\n"
            "--- a/src/sample.py\n"
            "+++ b/src/sample.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "@@ -5,2 +5,3 @@\n"
            " context\n"
            "+added\n"
            "+added again\n"
            "\\ No newline at end of file\n",
            {"src/sample.py": {1, 6, 7}},
        ),
        (
            "diff --git a/src/sample.py b/src/sample.py\n"
            "--- a/src/sample.py\n"
            "+++ b/src/sample.py\n"
            "@@ -10,2 +10,0 @@\n"
            "-removed\n"
            "-removed again\n",
            {"src/sample.py": set()},
        ),
        (
            "diff --git a/src/old.py b/src/new.py\n"
            "similarity index 90%\n"
            "rename from src/old.py\n"
            "rename to src/new.py\n"
            "--- a/src/old.py\n"
            "+++ b/src/new.py\n"
            "@@ -1 +1,2 @@\n"
            "-old\n"
            "+new\n"
            "+new again\n",
            {"src/new.py": {1, 2}},
        ),
    ],
)
def test_changed_source_lines_parses_supported_git_hunk_shapes(
    diff: str, expected: dict[str, set[int]]
) -> None:
    with patch.object(
        changed_coverage_gate.subprocess,
        "run",
        return_value=_completed_diff(diff),
    ) as run:
        result = changed_coverage_gate._changed_source_lines(
            base_ref="base", head_ref="head", source_root="src"
        )

    assert result == expected
    run.assert_called_once()


@pytest.mark.parametrize(
    "diff",
    [
        "diff --git a/src/sample.py b/src/sample.py\n"
        "--- a/src/sample.py\n"
        "+++ b/src/sample.py\n"
        "@@ malformed\n"
        "+new\n",
        "diff --git a/src/sample.py b/src/sample.py\n"
        "--- a/src/sample.py\n"
        "+++ b/src/sample.py\n"
        "@@ -1 +1,2 @@\n"
        "-old\n"
        "+new\n",
    ],
)
def test_changed_source_lines_rejects_unaccounted_python_hunks(diff: str) -> None:
    with patch.object(
        changed_coverage_gate.subprocess,
        "run",
        return_value=_completed_diff(diff),
    ):
        with pytest.raises(ValueError, match="parse|expected"):
            changed_coverage_gate._changed_source_lines(
                base_ref="base", head_ref="head", source_root="src"
            )


def test_run_gate_fails_closed_and_writes_evidence_on_diff_parse_error(tmp_path: Path) -> None:
    output = tmp_path / "changed-coverage.json"
    with patch.object(
        changed_coverage_gate,
        "_changed_source_lines",
        side_effect=ValueError("malformed hunk"),
    ):
        result = run_gate(
            base_ref="base",
            head_ref="head",
            coverage_data=tmp_path / ".coverage",
            policy_path=Path("quality/quality-policy.v1.json"),
            output_path=output,
        )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == 1
    assert report["status"] == "failed"
    assert report["failures"] == ["Changed-source diff parsing failed: malformed hunk"]


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
