from pathlib import Path

from scripts.check_monetary_float_usage import (
    finding_code_key,
    load_allowlist,
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
