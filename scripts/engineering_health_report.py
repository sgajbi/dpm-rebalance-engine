from __future__ import annotations

import argparse
import ast
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

DEFAULT_SOURCE_ROOTS = ("src", "scripts", "tests")
DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "htmlcov",
    "lotus-platform",
    "node_modules",
    "output",
}


@dataclass(frozen=True)
class FileMetric:
    path: str
    lines: int


@dataclass(frozen=True)
class FunctionMetric:
    path: str
    name: str
    lineno: int
    lines: int


@dataclass(frozen=True)
class RouterMetric:
    path: str
    lines: int
    route_decorator_count: int


@dataclass(frozen=True)
class GateInventory:
    make_target: str
    command: str


@dataclass(frozen=True)
class MetricDelta:
    metric: str
    baseline: int
    current: int
    delta: int


@dataclass(frozen=True)
class EngineeringHealthReport:
    generated_at: str
    git_branch: str
    git_head: str
    python_file_count: int
    package_count: int
    module_count: int
    total_python_lines: int
    largest_files: list[FileMetric]
    largest_functions: list[FunctionMetric]
    router_hotspots: list[RouterMetric]
    gate_inventory: list[GateInventory]


def _run_git(repo_root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "UNKNOWN"


def _iter_python_files(repo_root: Path, source_roots: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for source_root in source_roots:
        root = repo_root / source_root
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in DEFAULT_EXCLUDED_DIRS for part in path.parts):
                continue
            paths.append(path)
    return sorted(paths)


def _relative(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _largest_functions(
    repo_root: Path, python_files: list[Path], *, limit: int
) -> list[FunctionMetric]:
    functions: list[FunctionMetric] = []
    for path in python_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            end_lineno = getattr(node, "end_lineno", node.lineno)
            functions.append(
                FunctionMetric(
                    path=_relative(repo_root, path),
                    name=node.name,
                    lineno=node.lineno,
                    lines=end_lineno - node.lineno + 1,
                )
            )
    return sorted(functions, key=lambda item: item.lines, reverse=True)[:limit]


def _router_hotspots(
    repo_root: Path, python_files: list[Path], *, limit: int
) -> list[RouterMetric]:
    hotspots: list[RouterMetric] = []
    for path in python_files:
        relative = _relative(repo_root, path)
        if "routes" not in path.name and "/api/" not in relative:
            continue
        source = path.read_text(encoding="utf-8")
        route_decorator_count = source.count("@shared.router.") + source.count("@router.")
        if route_decorator_count == 0:
            continue
        hotspots.append(
            RouterMetric(
                path=relative,
                lines=len(source.splitlines()),
                route_decorator_count=route_decorator_count,
            )
        )
    return sorted(
        hotspots,
        key=lambda item: (item.route_decorator_count, item.lines),
        reverse=True,
    )[:limit]


def _gate_inventory(repo_root: Path) -> list[GateInventory]:
    makefile = repo_root / "Makefile"
    if not makefile.exists():
        return []
    targets_of_interest = {
        "lint",
        "typecheck",
        "openapi-gate",
        "no-alias-gate",
        "api-vocabulary-gate",
        "proposal-decision-vocabulary-gate",
        "domain-data-products-gate",
        "observability-diagnostics",
        "advisory-domain-golden-regressions",
        "demo-assurance-gate",
        "verify-dependencies",
        "security-audit",
        "coverage-combined",
        "quality-baseline",
        "test-unit",
        "test-integration",
        "test-e2e",
    }
    inventory: list[GateInventory] = []
    current_target: str | None = None
    for line in makefile.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("\t") and ":" in line:
            current_target = line.split(":", 1)[0].strip()
            continue
        if current_target in targets_of_interest and line.startswith("\t"):
            command = line.strip()
            if command:
                inventory.append(GateInventory(make_target=current_target, command=command))
    return inventory


def build_report(
    repo_root: Path,
    *,
    source_roots: Iterable[str] = DEFAULT_SOURCE_ROOTS,
    limit: int = 20,
) -> EngineeringHealthReport:
    python_files = _iter_python_files(repo_root, source_roots)
    file_metrics = [
        FileMetric(path=_relative(repo_root, path), lines=_line_count(path))
        for path in python_files
    ]
    package_count = sum(1 for path in python_files if path.name == "__init__.py")
    return EngineeringHealthReport(
        generated_at=datetime.now(UTC).isoformat(),
        git_branch=_run_git(repo_root, ["branch", "--show-current"]),
        git_head=_run_git(repo_root, ["rev-parse", "HEAD"]),
        python_file_count=len(python_files),
        package_count=package_count,
        module_count=len(python_files) - package_count,
        total_python_lines=sum(item.lines for item in file_metrics),
        largest_files=sorted(file_metrics, key=lambda item: item.lines, reverse=True)[:limit],
        largest_functions=_largest_functions(repo_root, python_files, limit=limit),
        router_hotspots=_router_hotspots(repo_root, python_files, limit=limit),
        gate_inventory=_gate_inventory(repo_root),
    )


def _metric_deltas(
    report: EngineeringHealthReport, baseline: dict[str, object]
) -> list[MetricDelta]:
    comparable_metrics = (
        "python_file_count",
        "package_count",
        "module_count",
        "total_python_lines",
    )
    deltas: list[MetricDelta] = []
    for metric in comparable_metrics:
        baseline_value = baseline.get(metric)
        current_value = getattr(report, metric)
        if not isinstance(baseline_value, int):
            continue
        deltas.append(
            MetricDelta(
                metric=metric,
                baseline=baseline_value,
                current=current_value,
                delta=current_value - baseline_value,
            )
        )
    return deltas


def render_markdown(
    report: EngineeringHealthReport, *, baseline: dict[str, object] | None = None
) -> str:
    lines = [
        "# Lotus Advise Engineering Health Baseline",
        "",
        f"- Generated At: `{report.generated_at}`",
        "- Git Identity: omitted from committed Markdown; use Git history and GitHub Actions",
        "  run metadata for exact branch/head evidence.",
        f"- Python Files: `{report.python_file_count}`",
        f"- Packages: `{report.package_count}`",
        f"- Modules: `{report.module_count}`",
        f"- Total Python Lines: `{report.total_python_lines}`",
        "",
    ]
    if baseline is not None:
        lines.extend(
            [
                "## Baseline Comparison",
                "",
                "| Metric | Baseline | Current | Delta |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for metric_delta in _metric_deltas(report, baseline):
            lines.append(
                f"| `{metric_delta.metric}` | {metric_delta.baseline} | "
                f"{metric_delta.current} | {metric_delta.delta:+} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Largest Files",
            "",
            "| Rank | File | Lines |",
            "| ---: | --- | ---: |",
        ]
    )
    for index, file_metric in enumerate(report.largest_files, start=1):
        lines.append(f"| {index} | `{file_metric.path}` | {file_metric.lines} |")
    lines.extend(
        [
            "",
            "## Largest Functions",
            "",
            "| Rank | Function | File | Line | Lines |",
            "| ---: | --- | --- | ---: | ---: |",
        ]
    )
    for index, function_metric in enumerate(report.largest_functions, start=1):
        lines.append(
            f"| {index} | `{function_metric.name}` | `{function_metric.path}` | "
            f"{function_metric.lineno} | {function_metric.lines} |"
        )
    lines.extend(
        [
            "",
            "## Router Hotspots",
            "",
            "| Rank | Router File | Route Decorators | Lines |",
            "| ---: | --- | ---: | ---: |",
        ]
    )
    for index, router_metric in enumerate(report.router_hotspots, start=1):
        lines.append(
            f"| {index} | `{router_metric.path}` | {router_metric.route_decorator_count} | "
            f"{router_metric.lines} |"
        )
    lines.extend(
        [
            "",
            "## Repo-Native Gate Inventory",
            "",
            "| Make Target | Command |",
            "| --- | --- |",
        ]
    )
    for gate in report.gate_inventory:
        lines.append(f"| `{gate.make_target}` | `{gate.command}` |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This baseline captures deterministic structural metrics from the current branch.",
            "- Use `--format json` to save a phase snapshot and `--compare-to <snapshot.json>`",
            "  to render structural metric deltas in later refactoring phases.",
            "- External scanner inventories should move from measurement to repo-native gates in",
            "  calibrated slices; coverage, import-linter, Spectral, Bandit severity regression,",
            "  Radon C/D/E/F-ranked complexity, Vulture no-new-regression, and deptry",
            "  no-new-regression checks now have enforced paths while interrogate and stricter",
            "  complexity thresholds remain measured backlog.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare-to", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    report = build_report(repo_root, limit=args.limit)
    baseline: dict[str, object] | None = None
    if args.compare_to is not None:
        compare_path = args.compare_to
        if not compare_path.is_absolute():
            compare_path = repo_root / compare_path
        baseline = json.loads(compare_path.read_text(encoding="utf-8"))
    content = (
        json.dumps(asdict(report), indent=2, sort_keys=True)
        if args.format == "json"
        else render_markdown(report, baseline=baseline)
    )
    if args.output is not None:
        output_path = args.output
        if not output_path.is_absolute():
            output_path = repo_root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
