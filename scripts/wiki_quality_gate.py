"""Run the platform-owned professional wiki audit for changed Advise wiki pages."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = Path("codex/skills/lotus-readme-wiki-governance/scripts/audit_wiki_quality.py")
NAVIGATION_PAGES = {"Home.md", "_Sidebar.md"}


def changed_wiki_scope(repo_root: Path, base_ref: str, head_ref: str) -> tuple[list[str], bool]:
    """Return changed page names and whether navigation requires a full professional audit."""
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            f"{base_ref}...{head_ref}",
            "--",
            "wiki",
        ],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Unable to discover changed wiki pages: {detail}")

    pages: set[str] = set()
    audit_all = False
    tokens = iter(completed.stdout.split(b"\0"))
    for raw_status in tokens:
        if not raw_status:
            continue
        status = raw_status.decode("utf-8")
        kind = status[0]
        old_path = next(tokens).decode("utf-8")
        path = next(tokens).decode("utf-8") if kind in {"R", "C"} else old_path
        paths = (old_path, path) if kind == "R" else (path,)
        for candidate in paths:
            source = Path(candidate)
            if source.parent != Path("wiki") or source.suffix != ".md":
                continue
            if (
                kind == "D"
                or candidate == old_path
                and kind == "R"
                or source.name in NAVIGATION_PAGES
            ):
                audit_all = True
            if kind != "D" and candidate == path:
                pages.add(source.name)
    return sorted(pages), audit_all


def run_gate(repo_root: Path, platform_root: Path, base_ref: str, head_ref: str) -> int:
    """Fail closed for changed wiki pages when the governed platform policy is unavailable."""
    pages, audit_all = changed_wiki_scope(repo_root, base_ref, head_ref)
    if not pages and not audit_all:
        print(f"Wiki quality gate: no changed wiki Markdown pages ({base_ref}...{head_ref}).")
        return 0
    auditor = platform_root / AUDITOR_PATH
    if not auditor.is_file():
        raise ValueError(f"Platform wiki auditor is unavailable at {auditor}.")
    command = [
        sys.executable,
        str(auditor),
        "--wiki-dir",
        str(repo_root / "wiki"),
        "--repo-root",
        str(repo_root),
    ]
    if audit_all:
        command.append("--all-professional-pages")
    for page in pages:
        command.extend(("--changed-page", page))
    return subprocess.run(command, cwd=repo_root, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--platform-root",
        type=Path,
        default=Path(os.getenv("LOTUS_PLATFORM_ROOT", REPO_ROOT.parent / "lotus-platform")),
    )
    parser.add_argument("--base-ref", default=os.getenv("QUALITY_BASE_REF", "origin/main"))
    parser.add_argument("--head-ref", default=os.getenv("QUALITY_HEAD_REF", "HEAD"))
    args = parser.parse_args()
    try:
        return run_gate(
            args.repo_root.resolve(),
            args.platform_root.resolve(),
            args.base_ref,
            args.head_ref,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"Wiki quality gate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
