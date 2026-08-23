import json
from pathlib import Path

from scripts.engineering_health_report import build_report, main, render_markdown


def test_engineering_health_report_captures_structural_metrics(tmp_path: Path) -> None:
    src = tmp_path / "src" / "api"
    src.mkdir(parents=True)
    platform = tmp_path / "lotus-platform"
    platform.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "routes_demo.py").write_text(
        "\n".join(
            [
                "from fastapi import APIRouter",
                "router = APIRouter()",
                "@router.get('/demo')",
                "def demo_route():",
                "    value = 1",
                "    return {'value': value}",
            ]
        ),
        encoding="utf-8",
    )
    (platform / "platform_module.py").write_text("def ignored():\n    return 1\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text(
        "\n".join(
            [
                "lint:",
                "\tpython -m ruff check .",
                "typecheck:",
                "\tpython -m mypy --config-file mypy.ini",
                "quality-baseline:",
                "\tpython scripts/quality_baseline_report.py --output-dir quality",
                "proposal-decision-vocabulary-gate:",
                "\tpython scripts/proposal_decision_vocabulary.py --validate-only",
                "demo-assurance-gate: openapi-gate domain-data-products-gate "
                "observability-diagnostics advisory-domain-golden-regressions",
                '\t@echo "Demo assurance gate passed"',
            ]
        ),
        encoding="utf-8",
    )

    report = build_report(tmp_path, source_roots=("src",), limit=5)
    markdown = render_markdown(report)

    assert report.python_file_count == 2
    assert report.package_count == 1
    assert report.module_count == 1
    assert report.router_hotspots[0].path == "src/api/routes_demo.py"
    assert report.router_hotspots[0].route_decorator_count == 1
    assert any(gate.make_target == "lint" for gate in report.gate_inventory)
    assert any(gate.make_target == "quality-baseline" for gate in report.gate_inventory)
    assert any(
        gate.make_target == "proposal-decision-vocabulary-gate" for gate in report.gate_inventory
    )
    assert any(gate.make_target == "demo-assurance-gate" for gate in report.gate_inventory)
    assert "- Branch:" not in markdown
    assert "- Head:" not in markdown
    assert "Git Identity: omitted from committed Markdown" in markdown
    assert "Largest Functions" in markdown
    assert "`demo_route`" in markdown


def test_engineering_health_report_renders_baseline_comparison(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "module.py").write_text("def current_function():\n    return 1\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "python_file_count": 3,
                "package_count": 1,
                "module_count": 2,
                "total_python_lines": 100,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "report.md"

    report = build_report(tmp_path, source_roots=("src",), limit=5)
    markdown = render_markdown(
        report,
        baseline=json.loads(baseline.read_text(encoding="utf-8")),
    )

    assert "Baseline Comparison" in markdown
    assert "| `python_file_count` | 3 | 1 | -2 |" in markdown

    exit_code = main(
        [
            "--repo-root",
            str(tmp_path),
            "--compare-to",
            str(baseline),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    assert "Baseline Comparison" in output.read_text(encoding="utf-8")
