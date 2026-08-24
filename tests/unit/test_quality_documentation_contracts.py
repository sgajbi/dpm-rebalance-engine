import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_recipe(makefile: str, target: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(target)}:\n(?P<recipe>(?:\t.*\n)+)", makefile)
    assert match is not None, f"Make target {target!r} is missing a recipe."
    return match.group("recipe")


def _make_invocations(recipe: str) -> set[str]:
    return set(re.findall(r"^\t\$\(MAKE\) (?P<target>[a-z0-9-]+)\s*$", recipe, re.MULTILINE))


def _active_make_commands(recipe: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in recipe.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _documented_make_targets(document: str) -> set[str]:
    return set(re.findall(r"`make (?P<target>[a-z0-9-]+)`", document))


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
    lint_targets = _make_invocations(_make_recipe(makefile, "lint"))
    assert "architecture-boundaries" in lint_targets
    complexity_targets = {
        target for target in lint_targets if "complexity" in target and target.endswith("-gate")
    }
    assert complexity_targets
    assert complexity_targets <= _documented_make_targets(rules)
    assert any(
        "importlinter" in command
        for command in _active_make_commands(_make_recipe(makefile, "architecture-boundaries"))
    )
    assert all(
        any(
            "python scripts/radon_complexity_gate.py" in command
            for command in _active_make_commands(_make_recipe(makefile, target))
        )
        for target in complexity_targets
    )
    assert "python scripts/radon_complexity_gate.py --fail-rank C" in _active_make_commands(
        _make_recipe(makefile, "complexity-regression-gate")
    )
