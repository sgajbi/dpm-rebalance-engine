from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import wiki_quality_gate


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True, text=True)


def _commit(root: Path, message: str) -> None:
    _git(root, "add", ".")
    _git(root, "commit", "-m", message)


def _repository(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.name", "Wiki Gate Test")
    _git(root, "config", "user.email", "wiki-gate@example.invalid")
    (root / "wiki").mkdir()
    for page in ("Home.md", "_Sidebar.md", "Guide.md"):
        (root / "wiki" / page).write_text(f"# {page}\n\nCurrent scope.\n", encoding="utf-8")
    _commit(root, "test: establish wiki source")


def test_changed_wiki_scope_is_focused_but_widens_for_rename_and_deletion(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / "wiki" / "Guide.md").write_text("# Guide\n\nCurrent evidence.\n", encoding="utf-8")
    _commit(tmp_path, "test: change guide")
    assert wiki_quality_gate.changed_wiki_scope(tmp_path, "HEAD^", "HEAD") == (["Guide.md"], False)

    _git(tmp_path, "mv", "wiki/Guide.md", "wiki/Operating-Guide.md")
    _commit(tmp_path, "test: rename guide")
    assert wiki_quality_gate.changed_wiki_scope(tmp_path, "HEAD^", "HEAD") == (
        ["Operating-Guide.md"],
        True,
    )

    (tmp_path / "wiki" / "Operating-Guide.md").unlink()
    _commit(tmp_path, "test: remove guide")
    assert wiki_quality_gate.changed_wiki_scope(tmp_path, "HEAD^", "HEAD") == ([], True)


def test_gate_is_noop_without_wiki_changes_and_fails_closed_when_changed_policy_is_missing(
    tmp_path: Path, capsys
) -> None:
    _repository(tmp_path)
    (tmp_path / "notes.txt").write_text("unrelated\n", encoding="utf-8")
    _commit(tmp_path, "test: unrelated change")
    assert wiki_quality_gate.run_gate(tmp_path, tmp_path / "missing", "HEAD^", "HEAD") == 0
    assert "no changed wiki Markdown pages" in capsys.readouterr().out

    (tmp_path / "wiki" / "Guide.md").write_text("# Guide\n\nCurrent evidence.\n", encoding="utf-8")
    _commit(tmp_path, "test: change guide")
    with pytest.raises(ValueError, match="Platform wiki auditor is unavailable"):
        wiki_quality_gate.run_gate(tmp_path, tmp_path / "missing", "HEAD^", "HEAD")
