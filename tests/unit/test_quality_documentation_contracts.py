import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REFACTORED_COMPLEXITY_PATHS = (
    "src/integrations/lotus_risk/enrichment.py",
    "src/core/tactical_house_view.py",
    "src/core/policy_packs/workflow_projection.py",
    "src/core/advisory/narrative_ai.py",
    "src/core/proposals/execution_status.py",
    "src/integrations/lotus_core/stateful_context_translation.py",
    "src/core/proposals/async_operations.py",
    "src/core/proposals/async_operation_runner.py",
    "src/core/proposals/async_payloads.py",
    "src/core/proposals/command_validation.py",
    "src/integrations/lotus_core/stateful_context_market_data.py",
    "src/core/bank_demo_proof/artifact_refs.py",
    "src/core/proposals/async_replay.py",
    "src/core/common/canonical.py",
    "src/core/proposals/idempotency.py",
    "src/core/common/intent_dependencies.py",
    "src/core/advisory_copilot/record_text.py",
    "src/core/advisory_copilot/run_replay_policy.py",
    "src/integrations/lotus_ai/runtime_config.py",
    "src/core/advisory/artifact_evidence.py",
    "src/core/advisory/artifact_portfolio.py",
    "src/core/advisory/artifact_trades.py",
    "src/core/advisory/alternatives_projection.py",
    "src/core/advisory/decision_requirements.py",
    "src/core/advisory/decision_material_changes.py",
    "src/core/advisory/narrative_policy.py",
    "src/core/advisory/decision_summary.py",
    "src/core/proposals/memo_builder.py",
    "src/core/proposals/memo_persistence.py",
    "src/core/proposals/memo_response_projection.py",
)


def _make_recipe(makefile: str, target: str) -> str:
    match = re.search(rf"(?m)^{re.escape(target)}:\n(?P<recipe>(?:\t.*\n)+)", makefile)
    assert match is not None, f"Make target {target!r} is missing a recipe."
    return match.group("recipe")


def _make_invocations(recipe: str) -> set[str]:
    return set(re.findall(r"^\t\$\(MAKE\) (?P<target>[a-z0-9-]+)\s*$", recipe, re.MULTILINE))


def _normalize_make_command(command: str) -> str:
    while command[:1] in {"+", "@"}:
        command = command[1:].lstrip()
    return command


def _active_make_commands(recipe: str) -> tuple[str, ...]:
    commands = []
    continued = ""
    for line in recipe.splitlines():
        command = f"{continued}{line.strip()}"
        if command.endswith("\\"):
            continued = command[:-1].rstrip() + " "
        else:
            if command:
                normalized = _normalize_make_command(command)
                if not normalized.startswith("#"):
                    commands.append(normalized)
            continued = ""
    if continued:
        normalized = _normalize_make_command(continued.rstrip())
        if not normalized.startswith("#"):
            commands.append(normalized)
    return tuple(commands)


def _contains_unquoted_shell_operator(command: str) -> bool:
    quote = None
    escaped = False
    for character in command:
        if quote:
            if quote == "'":
                if character == quote:
                    quote = None
            elif escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character in {"'", '"'}:
            quote = character
        elif character in {";", "|", "&"}:
            return True
    return False


def _active_python_commands(recipe: str) -> tuple[str, ...]:
    commands = []
    for command in _active_make_commands(recipe):
        if re.match(
            r"^python(?:\.exe)?(?:\s|$)", command, re.IGNORECASE
        ) and not _contains_unquoted_shell_operator(command):
            commands.append(command)
    return tuple(commands)


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
    architecture_commands = _active_python_commands(
        _make_recipe(makefile, "architecture-boundaries")
    )
    assert (
        'python -c "from importlinter.cli import lint_imports_command; '
        "lint_imports_command(args=['--config','.importlinter'], standalone_mode=True)\""
        in architecture_commands
    )
    assert all(
        any(
            command.startswith("python scripts/radon_complexity_gate.py ")
            for command in _active_python_commands(_make_recipe(makefile, target))
        )
        for target in complexity_targets
    )
    assert "python scripts/radon_complexity_gate.py --fail-rank C" in _active_python_commands(
        _make_recipe(makefile, "complexity-regression-gate")
    )
    refactored_commands = _active_python_commands(
        _make_recipe(makefile, "refactored-complexity-gate")
    )
    assert set(refactored_commands) == {
        f"python scripts/radon_complexity_gate.py --source-path {path} --fail-rank B"
        for path in REFACTORED_COMPLEXITY_PATHS
    }


def test_quality_control_command_parser_rejects_comments_and_echoes() -> None:
    recipe = "\n".join(
        (
            "\t# python scripts/radon_complexity_gate.py --fail-rank C",
            "\t@echo python scripts/radon_complexity_gate.py --fail-rank C",
            "\t@python scripts/radon_complexity_gate.py --fail-rank C",
            "\t-python scripts/radon_complexity_gate.py --fail-rank C",
            "\t@-python scripts/radon_complexity_gate.py --fail-rank C",
            "\tpython scripts/radon_complexity_gate.py --fail-rank C || true",
            "\tpython scripts/radon_complexity_gate.py --fail-rank C \\",
            "\t  || true",
            '\tpython scripts/radon_complexity_gate.py --fail-rank C \\" || true',
            "\tpython -c \"print('quoted; semicolon')\"",
        )
    )

    assert _active_python_commands(recipe) == (
        "python scripts/radon_complexity_gate.py --fail-rank C",
        "python -c \"print('quoted; semicolon')\"",
    )


def test_make_recipe_does_not_capture_later_targets() -> None:
    makefile = "alpha:\n\techo alpha\n\nbeta:\n\techo beta\n"

    assert _make_recipe(makefile, "alpha") == "\techo alpha\n"
