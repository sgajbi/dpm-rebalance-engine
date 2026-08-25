from pathlib import Path

from scripts.quality_baseline_report import (
    _radon_inventory_from_payload,
    _review_ledger_range,
    _spectral_inventory_from_payload,
    build_quality_context,
    check_quality_reports,
    main,
    render_baseline_report,
    render_quality_scorecard,
    render_refactor_health_report,
)
from scripts.refactor_health_report import build_refactor_health_lines


def test_radon_inventory_counts_nested_blocks_and_worst_complexity() -> None:
    payload = {
        "src/example.py": [
            {
                "type": "class",
                "name": "Service",
                "rank": "A",
                "complexity": 2,
                "methods": [
                    {"type": "method", "name": "run", "rank": "B", "complexity": 7},
                    {
                        "type": "method",
                        "name": "decide",
                        "rank": "C",
                        "complexity": 13,
                        "closures": [
                            {"type": "function", "name": "inner", "rank": "A", "complexity": 1}
                        ],
                    },
                ],
            }
        ]
    }

    assert _radon_inventory_from_payload(payload) == (
        True,
        4,
        {"A": 2, "B": 1, "C": 1},
        "C",
        13,
    )


def test_spectral_inventory_parses_valid_executable_payload() -> None:
    payload = {
        "spectralExecutable": True,
        "issueCount": 3,
        "severityInventory": {"error": 1, "warn": 2, "ignored": "not-a-count"},
        "openapiPathCount": 84,
    }

    assert _spectral_inventory_from_payload(payload) == (
        True,
        3,
        {"error": 1, "warn": 2},
        84,
    )
    assert _spectral_inventory_from_payload({"spectralExecutable": False}) == (
        False,
        None,
        {},
        None,
    )


def test_review_ledger_range_reads_current_ledger_ids(tmp_path: Path) -> None:
    ledger = tmp_path / "docs" / "architecture" / "CODEBASE-REVIEW-LEDGER.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "\n".join(
            [
                "# Review Ledger",
                "",
                "## LA-REV-013",
                "",
                "## LA-REV-105",
                "",
                "## LA-REV-099",
            ]
        ),
        encoding="utf-8",
    )

    assert _review_ledger_range(tmp_path) == ("LA-REV-013", "LA-REV-105")


def test_quality_baseline_report_captures_required_quality_sections(tmp_path: Path) -> None:
    src = tmp_path / "src" / "api"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "routes_demo.py").write_text(
        "\n".join(
            [
                "router = object()",
                "@router.get('/demo')",
                "def demo_route():",
                "    return {'ok': True}",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "Makefile").write_text(
        "\n".join(
            [
                "lint:",
                "\tpython -m ruff check .",
                "typecheck:",
                "\tpython -m mypy --config-file mypy.ini",
                "openapi-gate:",
                "\tpython scripts/openapi_quality_gate.py",
                "coverage-combined:",
                "\tpython -m coverage report --fail-under=97",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    (tmp_path / ".importlinter").write_text(
        "[importlinter]\nroot_package = src\n",
        encoding="utf-8",
    )
    (tmp_path / ".spectral.yaml").write_text("rules: {}\n", encoding="utf-8")

    context = build_quality_context(tmp_path)
    baseline = render_baseline_report(context)
    scorecard = render_quality_scorecard(context)
    refactor_health = render_refactor_health_report(context)

    assert "Code Size" in baseline
    assert "Complexity" in baseline
    assert "Radon config executable" in baseline
    assert "Radon complexity rank inventory" in baseline
    assert "Radon worst complexity" in baseline
    assert "Dead Code" in baseline
    assert "Vulture config executable" in baseline
    assert "Vulture current issue inventory" in baseline
    assert "Vulture confidence inventory" in baseline
    assert "Deptry config executable" in baseline
    assert "Deptry current issue inventory" in baseline
    assert "Bandit config executable" in baseline
    assert "Bandit current issue inventory" in baseline
    assert "Bandit severity inventory" in baseline
    assert "OpenAPI Gaps" in baseline
    assert "Spectral config executable" in baseline
    assert "Spectral current issue inventory" in baseline
    assert "Spectral severity inventory" in baseline
    assert "Architecture Violations" in baseline
    assert "Import-linter config executable" in baseline
    assert "Import-linter contract inventory" in baseline
    assert "Documentation Gaps" in baseline
    assert "Interrogate config executable" in baseline
    assert "Interrogate docstring inventory" in baseline
    assert "Observability Gaps" in baseline
    assert "make observability-diagnostics" in baseline
    assert "make demo-assurance-gate" in baseline
    assert "make demo-certification-live" in baseline
    assert "- Branch:" not in baseline
    assert "- Head:" not in baseline
    assert "Branch Commits Over Main" not in baseline
    assert "Git Identity: omitted from committed Markdown" in baseline
    assert "Progressive Gate Phase" in scorecard
    assert "- Branch:" not in scorecard
    assert "- Head:" not in scorecard
    assert "Git Identity: omitted from committed Markdown" in scorecard
    assert "C/D/E/F Radon gate plus inventory" in scorecard
    assert "C/D/E/F gate enforced through `make lint`" in scorecard
    assert "Quality baseline freshness" in scorecard
    assert "make quality-trend-gate" in scorecard
    assert "make check, make ci, make ci-local" in scorecard
    assert "Feature Lane, PR Merge Gate, and Main Releasability" in scorecard
    assert "Hard no-new-regression Vulture gate" in scorecard
    assert "Hard no-new-regression jscpd gate" in scorecard
    assert "make duplicate-code-gate" in baseline
    assert "Hard no-new-regression deptry gate" in scorecard
    assert "severity-regression gate enforced" in scorecard
    assert "quality/bandit_security_baseline.v1.json" in scorecard
    assert "make check + Feature Lane + security-audit" in scorecard
    assert "Enforced with Spectral" in scorecard
    assert "make lint runs import-linter architecture contracts" in scorecard
    assert "Gap tracked plus Interrogate inventory" in scorecard
    assert "wiki CI/operator guidance contract" in scorecard
    assert "Diagnostics target added" in scorecard
    assert "Demo assurance" in scorecard
    assert "API/domain/observability/data-mesh gate plus live certification command" in scorecard
    assert "make demo-certification-live" in scorecard
    assert "Before/After Evidence" in scorecard
    assert "make quality-baseline-check" in scorecard
    assert "does not claim bank" in scorecard
    assert "- Branch:" not in refactor_health
    assert "- Head:" not in refactor_health
    assert "Branch Commits Over Main" not in refactor_health
    assert "Git Identity: omitted from committed Markdown" in refactor_health
    assert "Proposal input models are split" in refactor_health
    assert "Advisory-copilot proposal-version lineage extraction delegates" in refactor_health
    assert "Advisory simulation orchestration is split" in refactor_health
    assert "Feature capability catalog assembly is split" in refactor_health
    assert "Workflow capability catalog assembly is split" in refactor_health
    assert "Proposal memo section assembly is split" in refactor_health
    assert "Bank-demo supported-claim register assembly is split" in refactor_health
    assert "Compliance rule evaluation is split" in refactor_health
    assert "Target-generation solver orchestration delegates" in refactor_health
    assert "Proposal memo source-readiness assembly is split" in refactor_health
    assert "Bank-demo runtime summary sanitization is split" in refactor_health
    assert "Bank-demo commercial material pack assembly delegates" in refactor_health
    assert "Bank-demo commercial material register validation delegates" in refactor_health
    assert "Bank-demo supported-claim classification validation delegates" in refactor_health
    assert "Bank-demo proof-pack contract-reference normalization delegates" in refactor_health
    assert "evidence-bundle, and hash finalization" in refactor_health
    assert "Advisory auto-funding planning delegates FX source selection" in refactor_health
    assert "Policy source-readiness assembly is split" in refactor_health
    assert "Lotus Core stateful-context dated-row selection delegates" in refactor_health
    assert "Proposal narrative product-type policy delegates" in refactor_health
    assert "Proposal memo foundational sections are split" in refactor_health
    assert "Proposal memo API orchestration delegates report-package" in refactor_health
    assert "Proposal memo API response assembly delegates memo" in refactor_health
    assert "Proposal memo API external request orchestration delegates" in refactor_health
    assert "Alternative strategy construction delegates input DTOs" in refactor_health
    assert "Alternatives objective strategies are split" in refactor_health
    assert "Proposal alternatives models are split" in refactor_health
    assert "Proposal alternatives projection delegates request-to-strategy" in refactor_health
    assert "Proposal alternatives comparison evidence delegates approval" in refactor_health
    assert "Proposal alternatives ranking delegates comparator" in refactor_health
    assert "Proposal memo request DTOs and memo vocabulary literals are split" in refactor_health
    assert "Proposal memo section assembly delegates source evidence" in refactor_health
    assert "Proposal memo audit event DTOs are split" in refactor_health
    assert "Proposal memo lineage and replay evidence DTOs are split" in refactor_health
    assert "Policy evaluation result builders are split" in refactor_health
    assert "Policy evaluation product evidence helpers are split" in refactor_health
    assert "Policy evaluation Singapore product rule implementations are split" in refactor_health
    assert "Policy evaluation cost and conflict review rules are split" in refactor_health
    assert "Policy evaluation source-readiness and mandate rules are split" in refactor_health
    assert "Policy evaluation source-readiness rule handling delegates" in refactor_health
    assert "Proposal artifact summary DTOs are split" in refactor_health
    assert "Proposal artifact portfolio-impact DTOs are split" in refactor_health
    assert "Proposal artifact trade/funding DTOs are split" in refactor_health
    assert "Proposal artifact review DTOs are split" in refactor_health
    assert "Proposal artifact assumptions and disclosure DTOs are split" in refactor_health
    assert "Proposal artifact evidence DTOs are split" in refactor_health
    assert "Proposal artifact builders import focused DTO owner modules directly" in refactor_health
    assert "Proposal narrative vocabulary Literal aliases are split" in refactor_health
    assert "Proposal narrative request DTOs are split" in refactor_health
    assert "Proposal narrative grounding DTOs are split" in refactor_health
    assert "Proposal narrative section DTOs are split" in refactor_health
    assert "Proposal narrative policy and guardrail DTOs are split" in refactor_health
    assert "Proposal narrative AI-lineage DTOs are split" in refactor_health
    assert "Proposal narrative envelope DTOs are split" in refactor_health
    assert "Proposal narrative review DTOs are split" in refactor_health
    assert "Proposal narrative runtime modules import focused DTO owner modules" in refactor_health
    assert "Proposal narrative grounding fact projection delegates" in refactor_health
    assert "Proposal narrative deterministic section rendering delegates" in refactor_health
    assert "Proposal narrative alternatives text rendering delegates" in refactor_health
    assert (
        "Advisor cockpit source read models delegate source projection helpers" in refactor_health
    )
    assert "Advisor cockpit service delegates repository-backed source loading" in refactor_health
    assert "Advisory workspace routes now compose through a workspace application service" in (
        refactor_health
    )
    assert "source-context, proposal-evaluator, and" in refactor_health
    assert "proposal-lifecycle ports while keeping the current in-memory session store" in (
        refactor_health
    )
    assert "Policy evaluation report-package validation delegates" in refactor_health
    assert "Policy evaluation sign-off validation delegates" in refactor_health
    assert "Workspace session input-mode validation delegates" in refactor_health
    assert "Workspace draft action request validation delegates" in refactor_health
    assert "table-driven map and identifier-scope rules" in refactor_health
    assert "Workspace draft action reduction delegates" in refactor_health
    assert "Local valuation state assembly delegates" in refactor_health
    assert "Local position valuation delegates" in refactor_health
    assert "Enterprise write authorization delegates" in refactor_health
    assert "In-memory proposal listing delegates" in refactor_health
    assert "Persistent proposal listing delegates" in refactor_health
    assert "OpenAPI operation enrichment delegates" in refactor_health
    assert "API vocabulary inventory generation delegates" in refactor_health
    assert "OpenAPI example repair delegates" in refactor_health
    assert "OpenAPI field-description inference delegates" in refactor_health
    assert "OpenAPI example inference delegates" in refactor_health
    assert "OpenAPI string example inference delegates" in refactor_health
    assert "Commercial material source-reference normalization delegates" in refactor_health
    assert "Bank-demo proof artifact-reference normalization delegates" in refactor_health
    assert "Shared proposal intent dependency linking delegates" in refactor_health
    assert "Shared proposal intent dependency linking now keeps SELL selection" in (refactor_health)
    assert "Advisory copilot record-text list normalization delegates" in refactor_health
    assert "Advisory copilot run replay delegates idempotency hash matching" in refactor_health
    assert "Lotus AI tenant runtime configuration delegates configured-value loading" in (
        refactor_health
    )
    assert "Proposal artifact evidence assembly delegates model serialization" in refactor_health
    assert "Proposal artifact portfolio impact delegates weight-change row construction" in (
        refactor_health
    )
    assert "Proposal artifact trades and funding delegates intent dispatch" in refactor_health
    assert "API structured logging formatter delegates" in refactor_health
    assert "Proposal workflow delivery operations delegate execution handoff" in refactor_health
    assert "Proposal workflow narrative operations delegate narrative read" in refactor_health
    assert "Proposal workflow read operations delegate proposal" in refactor_health
    assert "Proposal workflow command operations delegate create" in refactor_health
    assert "Policy evaluation persistence delegates lineage/posture projection" in refactor_health
    assert "Policy evaluation persistence delegates replay hash comparison" in refactor_health
    assert "Advisory copilot review persistence delegates" in refactor_health
    assert "Advisory copilot source-projection persistence delegates" in refactor_health
    assert "Advisory copilot section tuple validation delegates" in refactor_health
    assert "Suitability issue projection delegates" in refactor_health
    assert "Proposal workflow gate suitability reasons delegate" in refactor_health
    assert "Lotus Report request mapping delegates output-format normalization" in refactor_health
    assert "Proposed trade request sizing validation delegates" in refactor_health
    assert "Advisory funding selection delegates" in refactor_health
    assert "Advisory trade-intent construction delegates" in refactor_health
    assert "Advisory cash-flow intent planning delegates" in refactor_health
    assert "Advisory security-trade intent planning delegates" in refactor_health
    assert "Proposal simulation review delegates" in refactor_health
    assert "Advisory proposal orchestration delegates" in refactor_health
    assert "Direct dependency freshness governance aligns" in refactor_health
    assert "API observability instrumentation tolerates" in refactor_health
    assert "API observability route-name compatibility delegates" in refactor_health
    assert "Bank-demo runtime proof evidence delegates" in refactor_health
    assert "PR auto-merge queue verification now checks protected main-branch metadata" in (
        refactor_health
    )
    assert "Quality baseline report rendering delegates metric formatting" in refactor_health
    assert "Quality baseline Radon inventory parsing delegates nested block traversal" in (
        refactor_health
    )
    assert "Quality baseline Spectral inventory parsing delegates report availability" in (
        refactor_health
    )
    assert "Proposal narrative AI draft handling delegates adapter invocation" in (refactor_health)
    assert "Proposal execution-status projection delegates request metadata" in refactor_health
    assert "Lotus Core stateful-context position translation delegates row validation" in (
        refactor_health
    )
    assert "Tactical house-view affected-cohort construction delegates" in refactor_health
    assert "Refactored complexity enforcement now protects" in refactor_health
    assert "already-remediated Lotus Risk" in refactor_health
    assert "enrichment, tactical house-view, policy workflow projection, narrative AI draft" in (
        refactor_health
    )
    assert "Lotus Core stateful-context translation, proposal" in refactor_health
    assert "async/context command modules, narrative policy helpers, and decision-summary" in (
        refactor_health
    )
    assert "evidence-reference helpers with A-only Radon gates" in refactor_health
    assert "A-only Radon gates" in refactor_health
    assert "Lotus Core stateful-context market-data projection delegates" in refactor_health
    assert "last-source-wins FX pair behavior" in refactor_health
    assert "Bank-demo proof artifact-reference normalization delegates URL-material" in (
        refactor_health
    )
    assert "preserving local proof-artifact path normalization" in refactor_health
    assert "CI workflow jobs now declare explicit timeouts" in refactor_health
    assert "Development requirements pin the quality tools" in refactor_health
    assert "Bandit security scanning now fails earlier" in refactor_health
    assert "Remaining Enterprise-Readiness Work" in refactor_health
    assert "Calibrate stricter Radon/Xenon thresholds beyond the current C/D/E/F gate" in (
        refactor_health
    )
    assert "machine-readable quality trend/regression gate" in refactor_health
    assert "Interrogate docstring inventory" in refactor_health
    assert "Reduce the governed Bandit medium/low baseline before expiry" in refactor_health
    assert "Spectral OpenAPI enforcement" in refactor_health
    assert "deptry no-new-regression baseline" in refactor_health
    assert "advisory trade-intent construction" in scorecard
    assert "advisory cash-flow intent planning" in scorecard
    assert "advisory security-trade intent planning" in scorecard
    assert "advisory simulation review" in scorecard
    assert "advisory proposal authority orchestration" in scorecard
    assert "advisory reduce-concentration strategy" in scorecard
    assert "proposal async operation runner" in scorecard
    assert "proposal execution update command" in scorecard
    assert "proposal memo conflict-disclosure enrichment" in scorecard
    assert "policy evaluation record listing" in scorecard
    assert "policy-pack activation validation" in scorecard
    assert "policy evaluation report-package validation" in scorecard
    assert "policy evaluation sign-off validation" in scorecard
    assert "workspace session input-mode validation" in scorecard
    assert "workspace draft action validation" in scorecard
    assert "proposal alternatives projection helpers" in scorecard
    assert "decision-summary approval implication mapping" in scorecard
    assert "decision-summary material-change mapping" in scorecard
    assert "CI warning/topology/freshness contracts" in scorecard
    assert "workflow contract tests protect local CI target freshness" in scorecard
    assert "protected-main verification" in scorecard
    assert "demo-assurance checks" in scorecard
    assert "refactored-complexity enforcement" in scorecard
    assert "Proposal async operation referent loading" in refactor_health
    assert "Shared canonical payload helpers" in refactor_health
    assert "Proposal idempotency replay delegates event and approval replay matching" in (
        refactor_health
    )
    assert "Quality evidence freshness plus dead-code, duplicate-code, unused-dependency, and" in (
        scorecard
    )
    assert "oversized-code regression prevention" in scorecard
    assert "wiki validation guidance now maps local, Feature Lane, PR Merge Gate" in scorecard
    assert "agent-facing CI guidance is pinned by a deterministic wiki contract test" in scorecard
    assert "Review ledger includes `LA-REV-611` through `LA-REV-896`" in scorecard


def test_refactor_health_sections_preserve_committed_report_order_and_content() -> None:
    lines = build_refactor_health_lines()
    rendered = "\n".join(lines)
    committed = Path("quality/refactor_health_report.md").read_text(encoding="utf-8")

    assert lines[0] == "# Lotus Advise Refactor Health Report"
    assert lines.count("## Current Progress Signals") == 1
    assert lines.count("## Remaining Enterprise-Readiness Work") == 1
    assert lines.index("## Current Progress Signals") < lines.index(
        "## Remaining Enterprise-Readiness Work"
    )
    assert rendered == committed


def test_quality_baseline_report_cli_writes_requested_reports(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    output_dir = tmp_path / "quality"

    exit_code = main(["--repo-root", str(tmp_path), "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert (output_dir / "baseline_report.md").exists()
    assert (output_dir / "refactor_health_report.md").exists()
    assert (output_dir / "quality_scorecard.md").exists()


def test_quality_baseline_check_ignores_timestamp_and_detects_report_drift(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    output_dir = tmp_path / "quality"

    assert main(["--repo-root", str(tmp_path), "--output-dir", str(output_dir)]) == 0
    baseline_path = output_dir / "baseline_report.md"
    baseline_path.write_text(
        baseline_path.read_text(encoding="utf-8").replace(
            "- Generated At: `", "- Generated At: `2099-01-01T00:00:00+00:00"
        ),
        encoding="utf-8",
    )

    ok, drifted = check_quality_reports(tmp_path, output_dir)

    assert ok is True
    assert drifted == ()

    baseline_path.write_text(
        baseline_path.read_text(encoding="utf-8") + "\nUntracked drift\n",
        encoding="utf-8",
    )

    ok, drifted = check_quality_reports(tmp_path, output_dir)

    assert ok is False
    assert drifted == ("baseline_report.md",)
    assert main(["--repo-root", str(tmp_path), "--output-dir", str(output_dir), "--check"]) == 1
