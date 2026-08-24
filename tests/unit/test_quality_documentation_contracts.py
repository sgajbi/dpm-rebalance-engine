from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_architecture_documentation_matches_enforced_quality_controls() -> None:
    rules = (REPO_ROOT / "quality" / "architecture_rules.md").read_text(encoding="utf-8")
    architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "Current phase: regression-enforced" in rules
    assert "make architecture-boundaries" in rules
    assert "make complexity-regression-gate" in rules
    assert "report-only rollout" not in rules
    assert "report-only gap" not in rules

    assert "enforced by `make architecture-boundaries` through `make lint`" in architecture
    assert "report-only rollout" not in architecture
    assert "complexity-regression-gate" in makefile
    assert "architecture-boundaries" in makefile
