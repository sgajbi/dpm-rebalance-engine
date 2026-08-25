from datetime import date
from pathlib import Path

import pytest

from scripts.check_monetary_float_usage import (
    MONETARY_FLOAT_EXPIRY_WARNING_DAYS,
    expiring_allowlist_entries,
    finding_code_key,
    load_allowlist,
    main,
    scan_repo,
)


def test_finding_code_key_ignores_line_number_drift() -> None:
    original = "src/core/target_generation.py:210:w_model = float(weight)"
    shifted = "src/core/target_generation.py:213:w_model = float(weight)"

    assert finding_code_key(original) == finding_code_key(shifted)


def test_finding_code_key_preserves_code_text() -> None:
    original = "src/core/target_generation.py:210:w_model = float(weight)"
    changed = "src/core/target_generation.py:210:w_model = float(model_weight)"

    assert finding_code_key(original) != finding_code_key(changed)


def test_scan_repo_finding_matches_allowlist_when_only_line_number_moves(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "core" / "target_generation.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "\n\n\nfrom decimal import Decimal\nw_model = float(model_weight)\n",
        encoding="utf-8",
    )
    allowlist_path = tmp_path / "docs" / "standards" / "monetary-float-allowlist.json"
    allowlist_path.parent.mkdir(parents=True)
    allowlist_path.write_text(
        """
{
  "description": "Approved baseline monetary-float findings. New findings fail CI.",
  "policy_version": "1.1.0",
  "generated_at": "2026-04-08T01:55:26Z",
  "allowlist": [
    {
      "finding": "src/core/target_generation.py:1:w_model = float(model_weight)",
      "justification": "Temporary approved monetary float usage; migrate to Decimal.",
      "owner": "platform-governance",
      "review_by": "2099-12-31"
    }
  ]
}
""",
        encoding="utf-8",
    )

    findings = scan_repo(tmp_path)
    allowlist_entries, errors, stale = load_allowlist(allowlist_path)
    allowlisted_code_keys = {finding_code_key(finding) for finding in allowlist_entries}

    assert errors == []
    assert stale == []
    assert len(findings) == 1
    assert finding_code_key(findings[0]) in allowlisted_code_keys


def test_load_allowlist_reports_expired_review(tmp_path: Path) -> None:
    allowlist_path = tmp_path / "docs" / "standards" / "monetary-float-allowlist.json"
    allowlist_path.parent.mkdir(parents=True)
    allowlist_path.write_text(
        """
{
  "allowlist": [
    {
      "finding": "src/core/target_generation.py:1:w_model = float(model_weight)",
      "justification": "Temporary approved monetary float usage; migrate to Decimal.",
      "owner": "platform-governance",
      "review_by": "2020-01-01"
    }
  ]
}
""",
        encoding="utf-8",
    )

    entries, errors, stale = load_allowlist(allowlist_path)

    assert errors == []
    assert list(entries) == ["src/core/target_generation.py:1:w_model = float(model_weight)"]
    assert stale == ["src/core/target_generation.py:1:w_model = float(model_weight)"]


def test_expiry_window_is_inclusive_and_excludes_distant_or_stale_entries() -> None:
    entries = {
        "due-today": {"review_by": "2026-06-01"},
        "seven-days": {"review_by": "2026-06-08"},
        "eight-days": {"review_by": "2026-06-09"},
        "stale": {"review_by": "2026-05-31"},
    }

    assert expiring_allowlist_entries(
        entries,
        today=date(2026, 6, 1),
    ) == [
        ("due-today", "2026-06-01", 0),
        ("seven-days", "2026-06-08", MONETARY_FLOAT_EXPIRY_WARNING_DAYS),
    ]


def test_expiry_window_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError, match="^warning_days must be non-negative$"):
        expiring_allowlist_entries({}, today=date(2026, 6, 1), warning_days=-1)


def test_main_fails_with_expiring_finding_and_actionable_evidence(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(
        '{"allowlist": [{'
        '"finding": "src/core/target_generation.py:1:w_model = float(model_weight)", '
        '"justification": "approved", "owner": "owner", "review_by": "2026-06-08"'
        "}]}",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.check_monetary_float_usage.scan_repo",
        lambda _repo_root: [],
    )

    result = main(
        ["--repo-root", str(tmp_path), "--allowlist", "allowlist.json"],
        today=date(2026, 6, 1),
    )

    assert result == 1
    output = capsys.readouterr().out
    assert "7-day pre-expiry review window" in output
    assert "days_remaining=7" in output
