import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_recipe(makefile: str, target: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(target)}:\n(?P<recipe>(?:\t.*\n)+)", makefile)
    assert match is not None, f"Make target {target!r} is missing a recipe."
    return match.group("recipe")


def test_architecture_documentation_matches_enforced_quality_controls() -> None:
    rules = (REPO_ROOT / "quality" / "architecture_rules.md").read_text(encoding="utf-8")
    architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "Current phase: regression-enforced" in rules
    assert "the `make lint` recipe invokes `make architecture-boundaries`" in rules
    assert "The `make lint` recipe invokes `make complexity-regression-gate`" in rules
    assert "report-only rollout" not in rules
    assert "report-only gap" not in rules

    assert "enforced by `make architecture-boundaries` through `make lint`" in architecture
    assert "report-only rollout" not in architecture
    lint_recipe = _make_recipe(makefile, "lint")
    assert "\t$(MAKE) architecture-boundaries\n" in lint_recipe
    assert "\t$(MAKE) complexity-regression-gate\n" in lint_recipe
