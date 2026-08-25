from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

try:
    from scripts.engineering_health_report import EngineeringHealthReport, build_report
except ModuleNotFoundError:
    from engineering_health_report import EngineeringHealthReport, build_report

if __package__ in {None, ""}:
    from quality_scorecard import _optional_count, render_quality_scorecard
else:
    from .quality_scorecard import _optional_count, render_quality_scorecard

if __package__ in {None, ""}:
    from refactor_health_report import build_refactor_health_lines
else:
    from .refactor_health_report import build_refactor_health_lines

QUALITY_TOOLS: tuple[tuple[str, str], ...] = (
    ("ruff", "ruff"),
    ("mypy", "mypy"),
    ("pytest", "pytest"),
    ("coverage.py", "coverage"),
    ("pip-audit", "pip_audit"),
    ("radon", "radon"),
    ("xenon", "xenon"),
    ("vulture", "vulture"),
    ("deptry", "deptry"),
    ("bandit", "bandit"),
    ("interrogate", "interrogate"),
)

REQUESTED_DOCS = (
    "docs/architecture.md",
    "docs/api-governance.md",
    "docs/observability.md",
    "docs/security.md",
    "docs/operations-runbook.md",
    "docs/supported-features.md",
)

REPORT_FILENAMES = (
    "baseline_report.md",
    "refactor_health_report.md",
    "quality_scorecard.md",
)

GENERATED_AT_PATTERN = re.compile(r"^- Generated At: `[^`]+`$", re.MULTILINE)


@dataclass(frozen=True)
class QualityContext:
    report: EngineeringHealthReport
    branch_commit_count: int
    pyproject_present: bool
    importlinter_present: bool
    spectral_present: bool
    ci_quality_workflow_present: bool
    requested_docs_present: tuple[str, ...]
    requested_docs_missing: tuple[str, ...]
    available_tools: tuple[str, ...]
    unavailable_tools: tuple[str, ...]
    deptry_config_valid: bool
    deptry_issue_count: int | None
    bandit_config_valid: bool
    bandit_issue_count: int | None
    bandit_high_count: int | None
    bandit_medium_count: int | None
    bandit_low_count: int | None
    importlinter_config_valid: bool
    importlinter_contract_count: int | None
    importlinter_kept_count: int | None
    importlinter_broken_count: int | None
    radon_config_valid: bool
    radon_analyzed_block_count: int | None
    radon_rank_counts: dict[str, int]
    radon_worst_rank: str | None
    radon_worst_complexity: int | None
    vulture_config_valid: bool
    vulture_issue_count: int | None
    vulture_confidence_counts: dict[str, int]
    spectral_config_valid: bool
    spectral_issue_count: int | None
    spectral_severity_counts: dict[str, int]
    spectral_openapi_path_count: int | None
    interrogate_config_valid: bool
    interrogate_total_count: int | None
    interrogate_missing_count: int | None
    interrogate_covered_count: int | None
    interrogate_coverage_percent: str | None
    review_ledger_first_id: str
    review_ledger_latest_id: str


def _run_git(repo_root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip()


def _branch_commit_count(repo_root: Path) -> int:
    value = _run_git(repo_root, ["rev-list", "--count", "origin/main..HEAD"])
    try:
        return int(value)
    except ValueError:
        return 0


def _tool_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _deptry_issue_count(repo_root: Path) -> tuple[bool, int | None]:
    if not _tool_available("deptry") or not (repo_root / "pyproject.toml").exists():
        return False, None
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "deptry",
                ".",
                "--config",
                "pyproject.toml",
                "--json-output",
                str(output_path),
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if not output_path.exists() or completed.returncode not in {0, 1}:
            return False, None
        try:
            findings = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, None
        if not isinstance(findings, list):
            return False, None
        return True, len(findings)
    finally:
        output_path.unlink(missing_ok=True)


def _bandit_issue_counts(
    repo_root: Path,
) -> tuple[bool, int | None, int | None, int | None, int | None]:
    if not _tool_available("bandit") or not (repo_root / "pyproject.toml").exists():
        return False, None, None, None, None
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "bandit",
            "-q",
            "-r",
            "src",
            "-c",
            "pyproject.toml",
            "-f",
            "json",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in {0, 1}:
        return False, None, None, None, None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return False, None, None, None, None
    if not isinstance(payload, dict):
        return False, None, None, None, None
    results = payload.get("results")
    metrics = payload.get("metrics")
    if not isinstance(results, list) or not isinstance(metrics, dict):
        return False, None, None, None, None
    totals = metrics.get("_totals")
    if not isinstance(totals, dict):
        return False, None, None, None, None
    return (
        True,
        len(results),
        int(totals.get("SEVERITY.HIGH", 0)),
        int(totals.get("SEVERITY.MEDIUM", 0)),
        int(totals.get("SEVERITY.LOW", 0)),
    )


def _importlinter_contract_counts(
    repo_root: Path,
) -> tuple[bool, int | None, int | None, int | None]:
    if not _tool_available("importlinter") or not (repo_root / ".importlinter").exists():
        return False, None, None, None
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from importlinter.cli import lint_imports_command; "
                "lint_imports_command(args=['--config','.importlinter'], standalone_mode=True)"
            ),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    contract_match = re.search(
        r"Contracts:\s+(?P<kept>\d+)\s+kept,\s+(?P<broken>\d+)\s+broken",
        completed.stdout,
    )
    if contract_match is None:
        return False, None, None, None
    kept = int(contract_match.group("kept"))
    broken = int(contract_match.group("broken"))
    return completed.returncode in {0, 1}, kept + broken, kept, broken


def _radon_complexity_inventory(
    repo_root: Path,
) -> tuple[bool, int | None, dict[str, int], str | None, int | None]:
    if not _tool_available("radon"):
        return _empty_radon_inventory()
    completed = subprocess.run(
        [sys.executable, "-m", "radon", "cc", "src", "-s", "-j"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return _empty_radon_inventory()
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return _empty_radon_inventory()
    return _radon_inventory_from_payload(payload)


def _empty_radon_inventory() -> tuple[bool, int | None, dict[str, int], str | None, int | None]:
    return False, None, {}, None, None


def _radon_inventory_from_payload(
    payload: object,
) -> tuple[bool, int | None, dict[str, int], str | None, int | None]:
    if not isinstance(payload, dict):
        return _empty_radon_inventory()
    blocks = list(_iter_radon_blocks(payload))
    rank_counts = Counter(_radon_rank(block) for block in blocks if _radon_rank(block))
    worst_block = max(blocks, key=_radon_complexity, default=None)
    if worst_block is None:
        return True, 0, {}, None, None
    return (
        True,
        len(blocks),
        dict(sorted(rank_counts.items())),
        _radon_rank(worst_block),
        _radon_complexity(worst_block),
    )


def _iter_radon_blocks(payload: dict[str, object]) -> Iterable[dict[str, object]]:
    for file_blocks in payload.values():
        if isinstance(file_blocks, list):
            for block in file_blocks:
                yield from _iter_radon_block_tree(block)


def _iter_radon_block_tree(block: object) -> Iterable[dict[str, object]]:
    if not isinstance(block, dict):
        return
    yield block
    for child_key in ("methods", "closures"):
        children = block.get(child_key)
        if isinstance(children, list):
            for child in children:
                yield from _iter_radon_block_tree(child)


def _radon_rank(block: dict[str, object]) -> str | None:
    rank = block.get("rank")
    return rank if isinstance(rank, str) and rank else None


def _radon_complexity(block: dict[str, object]) -> int:
    complexity = block.get("complexity")
    return complexity if isinstance(complexity, int) else 0


def _vulture_issue_inventory(repo_root: Path) -> tuple[bool, int | None, dict[str, int]]:
    if not _tool_available("vulture"):
        return False, None, {}
    completed = subprocess.run(
        [sys.executable, "-m", "vulture", "src", "scripts", "--min-confidence", "80"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in {0, 1, 3}:
        return False, None, {}
    findings = [line for line in completed.stdout.splitlines() if line.strip()]
    confidence_counts: Counter[str] = Counter()
    for finding in findings:
        confidence_match = re.search(r"\((?P<confidence>\d+)% confidence\)", finding)
        if confidence_match is not None:
            confidence_counts[confidence_match.group("confidence")] += 1
    return True, len(findings), dict(sorted(confidence_counts.items()))


def _interrogate_inventory(
    repo_root: Path,
) -> tuple[bool, int | None, int | None, int | None, str | None]:
    if not _tool_available("interrogate") or not (repo_root / "pyproject.toml").exists():
        return False, None, None, None, None
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "interrogate",
            "src",
            "scripts",
            "--config",
            "pyproject.toml",
            "-v",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in {0, 1}:
        return False, None, None, None, None
    total_match = re.search(
        r"\|\s+TOTAL\s+\|\s+(?P<total>\d+)\s+\|\s+(?P<miss>\d+)\s+\|"
        r"\s+(?P<cover>\d+)\s+\|\s+(?P<percent>[0-9.]+%)\s+\|",
        completed.stdout,
    )
    if total_match is None:
        return False, None, None, None, None
    return (
        True,
        int(total_match.group("total")),
        int(total_match.group("miss")),
        int(total_match.group("cover")),
        total_match.group("percent"),
    )


def _review_ledger_range(repo_root: Path) -> tuple[str, str]:
    ledger_path = repo_root / "docs" / "architecture" / "CODEBASE-REVIEW-LEDGER.md"
    if not ledger_path.exists():
        return "LA-REV-611", "LA-REV-896"
    review_numbers = [
        int(match)
        for match in re.findall(
            r"^## LA-REV-(\d+)\b",
            ledger_path.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    ]
    if not review_numbers:
        return "LA-REV-611", "LA-REV-896"
    return (
        f"LA-REV-{min(review_numbers):03d}",
        f"LA-REV-{max(review_numbers):03d}",
    )


def _spectral_openapi_inventory(
    repo_root: Path,
) -> tuple[bool, int | None, dict[str, int], int | None]:
    if not _spectral_inventory_available(repo_root):
        return _empty_spectral_inventory()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        completed = _run_spectral_inventory_report(repo_root, output_path)
        if not output_path.exists() or completed.returncode not in {0, 1}:
            return _empty_spectral_inventory()
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _empty_spectral_inventory()
        return _spectral_inventory_from_payload(payload)
    finally:
        output_path.unlink(missing_ok=True)


def _spectral_inventory_available(repo_root: Path) -> bool:
    return (repo_root / ".spectral.yaml").exists() and (
        repo_root / "scripts" / "openapi_spectral_report.py"
    ).exists()


def _run_spectral_inventory_report(
    repo_root: Path,
    output_path: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/openapi_spectral_report.py",
            "--output",
            str(output_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _empty_spectral_inventory() -> tuple[bool, int | None, dict[str, int], int | None]:
    return False, None, {}, None


def _spectral_inventory_from_payload(
    payload: object,
) -> tuple[bool, int | None, dict[str, int], int | None]:
    if not isinstance(payload, dict) or payload.get("spectralExecutable") is not True:
        return _empty_spectral_inventory()
    issue_count = payload.get("issueCount")
    severity_inventory = payload.get("severityInventory")
    if not isinstance(issue_count, int) or not isinstance(severity_inventory, dict):
        return _empty_spectral_inventory()
    return (
        True,
        issue_count,
        _spectral_severity_counts(severity_inventory),
        _spectral_path_count(payload),
    )


def _spectral_severity_counts(severity_inventory: dict[object, object]) -> dict[str, int]:
    return {
        str(severity): count
        for severity, count in severity_inventory.items()
        if isinstance(count, int)
    }


def _spectral_path_count(payload: dict[str, object]) -> int | None:
    path_count = payload.get("openapiPathCount")
    return path_count if isinstance(path_count, int) else None


def build_quality_context(repo_root: Path) -> QualityContext:
    available_tools = tuple(name for name, module in QUALITY_TOOLS if _tool_available(module))
    unavailable_tools = tuple(name for name, module in QUALITY_TOOLS if not _tool_available(module))
    requested_docs_present = tuple(path for path in REQUESTED_DOCS if (repo_root / path).exists())
    requested_docs_missing = tuple(
        path for path in REQUESTED_DOCS if not (repo_root / path).exists()
    )
    deptry_config_valid, deptry_issue_count = _deptry_issue_count(repo_root)
    (
        bandit_config_valid,
        bandit_issue_count,
        bandit_high_count,
        bandit_medium_count,
        bandit_low_count,
    ) = _bandit_issue_counts(repo_root)
    (
        importlinter_config_valid,
        importlinter_contract_count,
        importlinter_kept_count,
        importlinter_broken_count,
    ) = _importlinter_contract_counts(repo_root)
    (
        radon_config_valid,
        radon_analyzed_block_count,
        radon_rank_counts,
        radon_worst_rank,
        radon_worst_complexity,
    ) = _radon_complexity_inventory(repo_root)
    vulture_config_valid, vulture_issue_count, vulture_confidence_counts = _vulture_issue_inventory(
        repo_root
    )
    (
        spectral_config_valid,
        spectral_issue_count,
        spectral_severity_counts,
        spectral_openapi_path_count,
    ) = _spectral_openapi_inventory(repo_root)
    (
        interrogate_config_valid,
        interrogate_total_count,
        interrogate_missing_count,
        interrogate_covered_count,
        interrogate_coverage_percent,
    ) = _interrogate_inventory(repo_root)
    review_ledger_first_id, review_ledger_latest_id = _review_ledger_range(repo_root)
    return QualityContext(
        report=build_report(repo_root),
        branch_commit_count=_branch_commit_count(repo_root),
        pyproject_present=(repo_root / "pyproject.toml").exists(),
        importlinter_present=(repo_root / ".importlinter").exists(),
        spectral_present=(repo_root / ".spectral.yaml").exists(),
        ci_quality_workflow_present=(
            repo_root / ".github" / "workflows" / "quality-baseline-report.yml"
        ).exists(),
        requested_docs_present=requested_docs_present,
        requested_docs_missing=requested_docs_missing,
        available_tools=available_tools,
        unavailable_tools=unavailable_tools,
        deptry_config_valid=deptry_config_valid,
        deptry_issue_count=deptry_issue_count,
        bandit_config_valid=bandit_config_valid,
        bandit_issue_count=bandit_issue_count,
        bandit_high_count=bandit_high_count,
        bandit_medium_count=bandit_medium_count,
        bandit_low_count=bandit_low_count,
        importlinter_config_valid=importlinter_config_valid,
        importlinter_contract_count=importlinter_contract_count,
        importlinter_kept_count=importlinter_kept_count,
        importlinter_broken_count=importlinter_broken_count,
        radon_config_valid=radon_config_valid,
        radon_analyzed_block_count=radon_analyzed_block_count,
        radon_rank_counts=radon_rank_counts,
        radon_worst_rank=radon_worst_rank,
        radon_worst_complexity=radon_worst_complexity,
        vulture_config_valid=vulture_config_valid,
        vulture_issue_count=vulture_issue_count,
        vulture_confidence_counts=vulture_confidence_counts,
        spectral_config_valid=spectral_config_valid,
        spectral_issue_count=spectral_issue_count,
        spectral_severity_counts=spectral_severity_counts,
        spectral_openapi_path_count=spectral_openapi_path_count,
        interrogate_config_valid=interrogate_config_valid,
        interrogate_total_count=interrogate_total_count,
        interrogate_missing_count=interrogate_missing_count,
        interrogate_covered_count=interrogate_covered_count,
        interrogate_coverage_percent=interrogate_coverage_percent,
        review_ledger_first_id=review_ledger_first_id,
        review_ledger_latest_id=review_ledger_latest_id,
    )


def _gate_commands(context: QualityContext) -> dict[str, list[str]]:
    gates: dict[str, list[str]] = {}
    for gate in context.report.gate_inventory:
        gates.setdefault(gate.make_target, []).append(gate.command)
    return gates


def _counter_inventory(values: dict[str, int], *, empty: str = "not run", suffix: str = "") -> str:
    inventory = ", ".join(f"{key}{suffix}={count}" for key, count in values.items())
    return inventory or empty


def _radon_worst_inventory(context: QualityContext) -> str:
    if context.radon_worst_rank is None or context.radon_worst_complexity is None:
        return "not run"
    return f"rank={context.radon_worst_rank}, complexity={context.radon_worst_complexity}"


def _baseline_header(context: QualityContext) -> list[str]:
    return [
        "# Lotus Advise Quality Baseline Report",
        "",
        f"- Generated At: `{context.report.generated_at}`",
        "- Git Identity: omitted from committed Markdown; use Git history and GitHub Actions",
        "  run metadata for exact branch/head evidence.",
        "- CI Phase: `calibrated-regression`",
        "",
    ]


def _code_size_section(report: EngineeringHealthReport) -> list[str]:
    return [
        "## Code Size",
        "",
        f"- Python files: `{report.python_file_count}`",
        f"- Packages: `{report.package_count}`",
        f"- Modules: `{report.module_count}`",
        f"- Total Python lines: `{report.total_python_lines}`",
        "",
    ]


def _largest_files_section(report: EngineeringHealthReport) -> list[str]:
    lines = [
        "## Largest Files",
        "",
        "| Rank | File | Lines |",
        "| ---: | --- | ---: |",
    ]
    for index, file_metric in enumerate(report.largest_files[:10], start=1):
        lines.append(f"| {index} | `{file_metric.path}` | {file_metric.lines} |")
    lines.append("")
    return lines


def _largest_functions_section(report: EngineeringHealthReport) -> list[str]:
    lines = [
        "## Largest Functions And Maintainability Hotspots",
        "",
        "| Rank | Function | File | Line | Lines |",
        "| ---: | --- | --- | ---: | ---: |",
    ]
    for index, function_metric in enumerate(report.largest_functions[:10], start=1):
        lines.append(
            f"| {index} | `{function_metric.name}` | `{function_metric.path}` | "
            f"{function_metric.lineno} | {function_metric.lines} |"
        )
    lines.append("")
    return lines


def _complexity_section(context: QualityContext) -> list[str]:
    return [
        "## Complexity",
        "",
        "- Current baseline uses largest-function and router-hotspot evidence as deterministic",
        "  complexity proxies.",
        f"- Radon config executable: `{context.radon_config_valid}`",
        "- Radon analyzed block inventory: "
        f"`{_optional_count(context.radon_analyzed_block_count)}`",
        f"- Radon complexity rank inventory: `{_counter_inventory(context.radon_rank_counts)}`",
        f"- Radon worst complexity: `{_radon_worst_inventory(context)}`",
        "- Radon C/D/E/F-ranked block enforcement is repo-native through",
        "  `make complexity-regression-gate` and the `lint` lane.",
        "- Xenon and stricter B-ranked Radon thresholds remain report-only until current",
        "  B-ranked helpers are classified.",
        "",
    ]


def _lint_type_coverage_sections(gates: dict[str, list[str]]) -> list[str]:
    return [
        "## Lint And Type Issues",
        "",
        f"- Ruff configured: `{'lint' in gates}`",
        f"- Mypy configured: `{'typecheck' in gates}`",
        "- Current enforcement remains repo-native through `make lint` and `make typecheck`.",
        "",
        "## Coverage",
        "",
        "- Unit/integration/E2E coverage gate is repo-native through `make coverage-combined`.",
        "- Configured fail-under target: `97`.",
        "",
    ]


def _dead_code_section(context: QualityContext) -> list[str]:
    return [
        "## Dead Code",
        "",
        f"- Vulture config executable: `{context.vulture_config_valid}`",
        f"- Vulture current issue inventory: `{_optional_count(context.vulture_issue_count)}`",
        "- Vulture confidence inventory: "
        f"`{_counter_inventory(context.vulture_confidence_counts, suffix='%')}`",
        "- Vulture findings are hard-gated by `make dead-code-gate`; reviewed compatibility-facade",
        "  exceptions are fingerprinted and carry owner, reason, and expiry metadata.",
        "",
    ]


def _duplicate_code_section() -> list[str]:
    return [
        "## Duplicate Code",
        "",
        "- jscpd is pinned at `5.0.16` in `package-lock.json`.",
        "- New clone fingerprints are hard-gated by `make duplicate-code-gate`; the reviewed",
        "  baseline is versioned with owner, reason, expiry, and content-hash provenance.",
        "- Scanner, parser, policy, or baseline-integrity failures fail closed.",
        "",
    ]


def _dependency_security_sections(
    context: QualityContext, gates: dict[str, list[str]]
) -> list[str]:
    return [
        "## Dependencies",
        "",
        f"- Dependency verification configured: `{'verify-dependencies' in gates}`",
        f"- Security audit configured: `{'security-audit' in gates}`",
        f"- Available dependency/security tools: `{', '.join(context.available_tools)}`",
        f"- Pending optional tools: `{', '.join(context.unavailable_tools)}`",
        f"- Deptry config executable: `{context.deptry_config_valid}`",
        f"- Deptry current issue inventory: `{_optional_count(context.deptry_issue_count)}`",
        f"- Bandit config executable: `{context.bandit_config_valid}`",
        f"- Bandit current issue inventory: `{_optional_count(context.bandit_issue_count)}`",
        "- Bandit severity inventory: "
        f"`high={_optional_count(context.bandit_high_count)}, "
        f"medium={_optional_count(context.bandit_medium_count)}, "
        f"low={_optional_count(context.bandit_low_count)}`",
        "",
        "## Security",
        "",
        "- `pip-audit` is present in development requirements.",
        "- `bandit` severity-regression enforcement is repo-native through",
        "  `make bandit-severity-regression-gate`, `make check`, Feature Lane, and the",
        "  `security-audit` lane.",
        "- Medium and low Bandit findings are governed by",
        "  `quality/bandit_security_baseline.v1.json` with expiry and remediation links.",
        "- Sensitive-data handling remains governed by API error redaction and structured",
        "  payload tests until the security report gate is calibrated.",
        "",
    ]


def _openapi_section(context: QualityContext, gates: dict[str, list[str]]) -> list[str]:
    spectral_severity_inventory = _counter_inventory(
        context.spectral_severity_counts,
        empty="none" if context.spectral_issue_count == 0 else "not run",
    )
    return [
        "## OpenAPI Gaps",
        "",
        f"- Repo-native OpenAPI gate configured: `{'openapi-gate' in gates}`",
        f"- Spectral rules present: `{context.spectral_present}`",
        f"- Spectral config executable: `{context.spectral_config_valid}`",
        "- Spectral OpenAPI path inventory: "
        f"`{_optional_count(context.spectral_openapi_path_count)}`",
        f"- Spectral current issue inventory: `{_optional_count(context.spectral_issue_count)}`",
        f"- Spectral severity inventory: `{spectral_severity_inventory}`",
        "- Spectral is enforced through `make openapi-gate`; the inventory remains recorded",
        "  for before/after scorecard evidence.",
        "",
    ]


def _architecture_section(context: QualityContext) -> list[str]:
    return [
        "## Architecture Violations",
        "",
        f"- Import-linter contracts present: `{context.importlinter_present}`",
        f"- Import-linter config executable: `{context.importlinter_config_valid}`",
        "- Import-linter contract inventory: "
        f"`total={_optional_count(context.importlinter_contract_count)}, "
        f"kept={_optional_count(context.importlinter_kept_count)}, "
        f"broken={_optional_count(context.importlinter_broken_count)}`",
        "- Import-linter contracts enforced by `make architecture-boundaries` and `make lint`.",
        "",
    ]


def _documentation_section(context: QualityContext) -> list[str]:
    return [
        "## Documentation Gaps",
        "",
        f"- Requested docs present: `{', '.join(context.requested_docs_present) or 'none'}`",
        f"- Requested docs missing: `{', '.join(context.requested_docs_missing) or 'none'}`",
        f"- Interrogate config executable: `{context.interrogate_config_valid}`",
        "- Interrogate docstring inventory: "
        f"`total={_optional_count(context.interrogate_total_count)}, "
        f"missing={_optional_count(context.interrogate_missing_count)}, "
        f"covered={_optional_count(context.interrogate_covered_count)}, "
        f"coverage={context.interrogate_coverage_percent or 'not run'}`",
        "- Interrogate documentation coverage trend is hard-gated by `make quality-trend-gate`;",
        "  absolute public API and module-ownership thresholds remain report-only until",
        "  classified.",
        "",
    ]


def _observability_section() -> list[str]:
    return [
        "## Observability Gaps",
        "",
        "- Observability documentation is present.",
        "- Observability diagnostics target: `make observability-diagnostics`",
        "- Focused diagnostics currently verify correlation, request, trace,",
        "  and structured-log propagation.",
        "- Request and audit telemetry use bounded route templates and operation names",
        "  instead of raw URL paths or resource identifiers.",
        "- Demo assurance gate: `make demo-assurance-gate` ties API governance,",
        "  domain golden regressions, observability diagnostics, and domain-data",
        "  product validation into a repeatable local evidence command.",
        "- Live demo certification: `make demo-certification-live` writes",
        "  machine-readable app-level evidence for live runtime route safety,",
        "  deterministic synthetic scenarios, and capability truth.",
        "- Dashboard, alert, SLO, and distributed-tracing evidence remain tracked gaps.",
        "",
    ]


def render_baseline_report(context: QualityContext) -> str:
    gates = _gate_commands(context)
    lines = [
        *_baseline_header(context),
        *_code_size_section(context.report),
        *_largest_files_section(context.report),
        *_largest_functions_section(context.report),
        *_complexity_section(context),
        *_lint_type_coverage_sections(gates),
        *_dead_code_section(context),
        *_duplicate_code_section(),
        *_dependency_security_sections(context, gates),
        *_openapi_section(context, gates),
        *_architecture_section(context),
        *_documentation_section(context),
        *_observability_section(),
    ]
    return "\n".join(lines)


def render_refactor_health_report(context: QualityContext) -> str:
    """Render the stable report from cohesive, owned section builders."""

    del context
    return "\n".join(build_refactor_health_lines())


def render_quality_reports(repo_root: Path) -> dict[str, str]:
    context = build_quality_context(repo_root)
    return {
        "baseline_report.md": render_baseline_report(context),
        "refactor_health_report.md": render_refactor_health_report(context),
        "quality_scorecard.md": render_quality_scorecard(context),
    }


def write_quality_reports(repo_root: Path, output_dir: Path) -> None:
    reports = render_quality_reports(repo_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in reports.items():
        (output_dir / filename).write_text(content, encoding="utf-8", newline="\n")


def _normalize_report_for_check(content: str) -> str:
    return GENERATED_AT_PATTERN.sub("- Generated At: `<normalized>`", content).rstrip() + "\n"


def check_quality_reports(repo_root: Path, output_dir: Path) -> tuple[bool, tuple[str, ...]]:
    expected_reports = render_quality_reports(repo_root)
    drifted: list[str] = []
    for filename in REPORT_FILENAMES:
        report_path = output_dir / filename
        expected = _normalize_report_for_check(expected_reports[filename])
        if not report_path.exists():
            drifted.append(filename)
            continue
        actual = _normalize_report_for_check(report_path.read_text(encoding="utf-8"))
        if actual != expected:
            drifted.append(filename)
    return not drifted, tuple(drifted)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Lotus Advise quality baseline reports.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("quality"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when committed quality reports drift, ignoring the generated timestamp.",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    if args.check:
        ok, drifted = check_quality_reports(repo_root, output_dir)
        if not ok:
            print(
                "Quality baseline reports are stale. Regenerate with "
                "`make quality-baseline`. Drifted files: " + ", ".join(drifted),
                file=sys.stderr,
            )
            return 1
        return 0
    write_quality_reports(repo_root, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
