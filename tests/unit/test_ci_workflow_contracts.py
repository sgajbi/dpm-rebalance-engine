from pathlib import Path

WORKFLOW_ROOT = Path(".github/workflows")


def _workflow_text(name: str) -> str:
    return (WORKFLOW_ROOT / name).read_text(encoding="utf-8")


def _workflow_job_section(workflow: str, job_id: str) -> str:
    start = workflow.index(f"  {job_id}:")
    next_job = workflow.find("\n  ", start + 1)
    while next_job != -1 and workflow[next_job + 3] == " ":
        next_job = workflow.find("\n  ", next_job + 1)
    if next_job == -1:
        return workflow[start:]
    return workflow[start:next_job]


def _assert_default_ci_guardrails(
    workflow: str,
    *,
    concurrency_group: str = "group: ${{ github.workflow }}-${{ github.ref }}",
) -> None:
    assert "concurrency:" in workflow
    assert concurrency_group in workflow
    assert "cancel-in-progress: true" in workflow
    assert "permissions:\n  contents: read" in workflow


def _workflow_job_ids(workflow: str) -> list[str]:
    job_section = workflow.split("\njobs:\n", maxsplit=1)[1]
    return [
        line.strip()[:-1]
        for line in job_section.splitlines()
        if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":")
    ]


def _assert_all_jobs_have_timeout(workflow: str) -> None:
    for job_id in _workflow_job_ids(workflow):
        assert "timeout-minutes:" in _workflow_job_section(workflow, job_id), job_id


def _assert_governance_job_runs_baseline_freshness(workflow: str, job_id: str) -> None:
    governance_section = _workflow_job_section(workflow, job_id)

    assert "Quality Baseline Freshness" in governance_section
    assert "run: make quality-baseline-check" in governance_section


def _assert_governance_job_runs_trust_telemetry_freshness(workflow: str, job_id: str) -> None:
    governance_section = _workflow_job_section(workflow, job_id)

    assert "Trust Telemetry Freshness" in governance_section
    assert "run: make trust-telemetry-freshness-gate" in governance_section


def _makefile_target_dependencies(makefile: str, target: str) -> set[str]:
    prefix = f"{target}: "
    for line in makefile.splitlines():
        if line.startswith(prefix):
            return set(line.removeprefix(prefix).split())
    raise AssertionError(f"Missing Makefile target: {target}")


def test_local_ci_targets_enforce_quality_baseline_freshness() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    for target in ("check", "ci", "ci-local"):
        assert "quality-baseline-check" in _makefile_target_dependencies(makefile, target)
    for target in ("check", "check-all", "ci", "ci-local"):
        assert "dead-code-gate" in _makefile_target_dependencies(makefile, target)
        assert "duplicate-code-gate" in _makefile_target_dependencies(makefile, target)
    for target in ("check", "check-all", "ci", "ci-local"):
        assert "unused-dependency-gate" in _makefile_target_dependencies(makefile, target)
        assert "oversized-code-gate" in _makefile_target_dependencies(makefile, target)
        assert "proposal-decision-vocabulary-gate" in _makefile_target_dependencies(
            makefile, target
        )


def test_quality_trend_gate_is_hard_versioned_and_present_across_ci_lanes() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    policy = Path("quality/quality-trend-policy.v1.json").read_text(encoding="utf-8")

    assert all(
        "quality-trend-gate" in _makefile_target_dependencies(makefile, target)
        for target in ("check", "check-all", "ci", "ci-local")
    )
    assert "python -m scripts.quality_trend_gate" in makefile
    assert '"schema_version": "lotus.advise.quality-trend-policy.v1"' in policy
    assert '"allowed_delta": 500' in policy
    assert policy.count('"allowed_delta": 0') == 3
    assert '"exceptions"' in policy
    assert '"base_sha"' in policy
    assert '"head_sha"' in policy
    assert '"expires_on"' in policy
    for workflow_name, governance_job in (
        ("feature-lane.yml", "lint-dependency-governance"),
        ("pr-merge-gate.yml", "lint-typecheck-governance"),
        ("main-releasability.yml", "lint-typecheck-governance"),
    ):
        section = _workflow_job_section(_workflow_text(workflow_name), governance_job)
        assert all(
            marker in section
            for marker in (
                "run: make quality-trend-gate",
                "path: output/quality-trend-gate.json",
                "fetch-depth: 0",
            )
        )
        assert "Quality Trend Regression Gate" in section
        base_ref = {
            "feature-lane.yml": "origin/main",
            "pr-merge-gate.yml": (
                "${{ github.event_name == 'pull_request' && "
                "github.event.pull_request.base.sha || 'origin/main' }}"
            ),
            "main-releasability.yml": "HEAD^",
        }[workflow_name]
        assert f"QUALITY_BASE_REF: {base_ref}" in section


def test_manual_pr_gate_dispatch_binds_quality_and_changed_coverage_refs() -> None:
    workflow = _workflow_text("pr-merge-gate.yml")
    governance_section = _workflow_job_section(workflow, "lint-typecheck-governance")
    coverage_section = _workflow_job_section(workflow, "coverage-gate")
    event_aware_base = (
        "QUALITY_BASE_REF: ${{ github.event_name == 'pull_request' && "
        "github.event.pull_request.base.sha || 'origin/main' }}"
    )
    event_aware_head = (
        "QUALITY_HEAD_REF: ${{ github.event_name == 'pull_request' && "
        "github.event.pull_request.head.sha || github.sha }}"
    )
    manual_coverage_condition = (
        "if: github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch'"
    )
    coverage_base_arg = (
        "--base-ref \"${{ github.event_name == 'pull_request' && "
        "github.event.pull_request.base.sha || 'origin/main' }}\""
    )
    coverage_head_arg = (
        "--head-ref \"${{ github.event_name == 'pull_request' && "
        'github.event.pull_request.head.sha || github.sha }}"'
    )
    unsupported_event_condition = (
        "if: github.event_name != 'pull_request' && github.event_name != 'workflow_dispatch'"
    )

    assert "workflow_dispatch:" in workflow
    assert event_aware_base in governance_section
    assert event_aware_head in governance_section
    assert "Verify quality comparison refs" in governance_section
    assert "Quality comparison context:" in governance_section
    assert "refusing an unbound quality-trend comparison" in governance_section
    assert 'git rev-parse --verify "${QUALITY_BASE_REF}^{commit}"' in governance_section
    assert 'git rev-parse --verify "${QUALITY_HEAD_REF}^{commit}"' in governance_section
    assert manual_coverage_condition in coverage_section
    assert coverage_base_arg in coverage_section
    assert coverage_head_arg in coverage_section
    assert "Record changed coverage skip for unsupported workflow event" in coverage_section
    assert unsupported_event_condition in coverage_section


def test_dead_code_regression_gate_is_hard_and_versioned_across_ci_lanes() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    policy = Path("quality/dead-code-policy.v1.json").read_text(encoding="utf-8")

    assert "dead-code-gate" in makefile
    assert "python -m scripts.dead_code_gate" in makefile
    assert "quality/dead-code-policy.v1.json" in makefile
    assert '"max_new_findings": 0' in policy
    assert '"exceptions"' in policy
    assert '"expires_on"' in policy
    for workflow_name in ("feature-lane.yml", "pr-merge-gate.yml", "main-releasability.yml"):
        workflow = _workflow_text(workflow_name)
        governance_job = (
            "lint-dependency-governance"
            if workflow_name == "feature-lane.yml"
            else "lint-typecheck-governance"
        )
        section = _workflow_job_section(workflow, governance_job)
        assert "Dead Code Regression Gate" in section
        assert "run: make dead-code-gate" in section


def test_duplicate_code_regression_gate_is_hard_and_versioned_across_ci_lanes() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    package_json = Path("package.json").read_text(encoding="utf-8")
    policy = Path("quality/duplicate-code-policy.v1.json").read_text(encoding="utf-8")
    baseline = Path("quality/duplicate-code-baseline.v1.json").read_text(encoding="utf-8")

    assert "duplicate-code-gate" in makefile
    assert "python -m scripts.duplicate_code_gate" in makefile
    assert '"jscpd": "5.0.16"' in package_json
    assert '"max_new_findings": 0' in policy
    assert '"tool_version": "5.0.16"' in policy
    assert '"mode": "strict"' in policy
    assert '"fingerprints"' in baseline
    for workflow_name in ("feature-lane.yml", "pr-merge-gate.yml", "main-releasability.yml"):
        workflow = _workflow_text(workflow_name)
        governance_job = (
            "lint-dependency-governance"
            if workflow_name == "feature-lane.yml"
            else "lint-typecheck-governance"
        )
        section = _workflow_job_section(workflow, governance_job)
        assert "Duplicate Code Regression Gate" in section
        assert "run: make duplicate-code-gate" in section


def test_unused_dependency_regression_gate_is_hard_and_versioned_across_ci_lanes() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    policy = Path("quality/dependency-hygiene-policy.v1.json").read_text(encoding="utf-8")
    baseline = Path("quality/dependency-hygiene-baseline.v1.json").read_text(encoding="utf-8")
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "unused-dependency-gate" in makefile
    assert "python -m scripts.dependency_hygiene_gate" in makefile
    assert '"tool": "deptry"' in policy
    assert '"tool_version": "0.25.1"' in policy
    assert '"max_new_findings": 0' in policy
    assert '"max_resolved_findings": 0' in policy
    assert '"allowed": false' in policy
    assert '"findings"' in baseline
    assert '"owner"' in baseline
    assert '"reason"' in baseline
    assert '"expires_on"' in baseline
    assert '"ci_local_compose_project"' in pyproject
    for workflow_name in ("feature-lane.yml", "pr-merge-gate.yml", "main-releasability.yml"):
        workflow = _workflow_text(workflow_name)
        governance_job = (
            "lint-dependency-governance"
            if workflow_name == "feature-lane.yml"
            else "lint-typecheck-governance"
        )
        section = _workflow_job_section(workflow, governance_job)
        assert "Unused Dependency Regression Gate" in section
        assert "run: make unused-dependency-gate" in section
        assert "Upload Dependency Hygiene Evidence" in section
        assert "path: output/dependency-hygiene-gate.json" in section


def test_oversized_code_regression_gate_is_hard_and_versioned_across_ci_lanes() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    policy = Path("quality/oversized-code-policy.v1.json").read_text(encoding="utf-8")
    baseline = Path("quality/oversized-code-baseline.v1.json").read_text(encoding="utf-8")

    assert "oversized-code-gate" in makefile
    assert "python -m scripts.oversized_code_gate" in makefile
    assert '"module_max_lines": 1000' in policy
    assert '"function_max_lines": 200' in policy
    assert '"allowed": false' in policy
    assert '"fingerprint"' in baseline
    assert '"max_lines"' in baseline
    assert '"owner"' in baseline
    assert '"reason"' in baseline
    assert '"expires_on"' in baseline
    for workflow_name in ("feature-lane.yml", "pr-merge-gate.yml", "main-releasability.yml"):
        workflow = _workflow_text(workflow_name)
        governance_job = (
            "lint-dependency-governance"
            if workflow_name == "feature-lane.yml"
            else "lint-typecheck-governance"
        )
        section = _workflow_job_section(workflow, governance_job)
        assert "Oversized Module/Function Regression Gate" in section
        assert "run: make oversized-code-gate" in section
        assert "Upload Oversized Code Evidence" in section
        assert "path: output/oversized-code-gate.json" in section


def test_proposal_decision_vocabulary_is_source_owned_and_hard_across_ci_lanes() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    contract = Path("docs/standards/proposal-decision-vocabulary.v1.json").read_text(
        encoding="utf-8"
    )

    assert "proposal-decision-vocabulary-gate" in makefile
    assert "python scripts/proposal_decision_vocabulary.py --validate-only" in makefile
    assert '"schema_version": "lotus.advise.proposal-decision-vocabulary.v1"' in contract
    assert '"service": "lotus-advise"' in contract
    assert "decision_summary_status_rules.py" in contract
    assert "workflow_gates.py" in contract
    assert "workflow_gate_vocabulary.py" in contract
    for workflow_name in ("feature-lane.yml", "pr-merge-gate.yml", "main-releasability.yml"):
        workflow = _workflow_text(workflow_name)
        governance_job = (
            "lint-dependency-governance"
            if workflow_name == "feature-lane.yml"
            else "lint-typecheck-governance"
        )
        section = _workflow_job_section(workflow, governance_job)
        assert "Proposal Decision Vocabulary Contract" in section
        assert "run: make proposal-decision-vocabulary-gate" in section


def test_coverage_gate_enforces_changed_source_floor_with_versioned_policy() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    workflow = _workflow_text("pr-merge-gate.yml")
    coverage_section = _workflow_job_section(workflow, "coverage-gate")

    assert "changed-coverage-gate" in makefile
    assert "scripts/changed_coverage_gate.py" in makefile
    assert "quality/quality-policy.v1.json" in makefile
    assert "Enforce changed source coverage floor" in coverage_section
    assert "github.event.pull_request.base.sha" in coverage_section
    assert "github.event.pull_request.head.sha" in coverage_section
    assert "Record changed coverage skip for unsupported workflow event" in coverage_section
    assert "quality/quality-policy.v1.json" in coverage_section
    assert "Upload changed coverage evidence" in coverage_section
    assert "fetch-depth: 0" in coverage_section


def test_docker_local_ci_image_supports_changed_coverage_git_diff() -> None:
    dockerfile = Path("Dockerfile.ci-local").read_text(encoding="utf-8")

    assert "apt-get install -y --no-install-recommends git make" in dockerfile


def test_docker_local_ci_image_and_workflows_share_pinned_spectral_node_runtime() -> None:
    dockerfile = Path("Dockerfile.ci-local").read_text(encoding="utf-8")

    assert "FROM node:22.14.0-bookworm-slim AS node-runtime" in dockerfile
    assert "FROM python:3.11-slim-bookworm" in dockerfile
    assert "COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node" in dockerfile
    assert "ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx" in dockerfile
    assert "node --version" in dockerfile
    assert "npm --version" in dockerfile
    assert "npx --version" in dockerfile

    for workflow_name in (
        "feature-lane.yml",
        "pr-merge-gate.yml",
        "quality-baseline-report.yml",
        "main-releasability.yml",
    ):
        workflow = _workflow_text(workflow_name)
        assert 'NODE_VERSION: "22.14.0"' in workflow
        assert "node-version: ${{ env.NODE_VERSION }}" in workflow


def test_docker_local_ci_mounts_platform_contracts_for_domain_product_gate() -> None:
    compose = Path("docker-compose.ci-local.yml").read_text(encoding="utf-8")

    assert "${LOTUS_PLATFORM_ROOT:-../lotus-platform}:/lotus-platform:ro" in compose
    assert "${LOTUS_REPOSITORIES_ROOT:-..}/lotus-core:/lotus-core:ro" in compose
    assert "${LOTUS_REPOSITORIES_ROOT:-..}/lotus-performance:/lotus-performance:ro" in compose
    assert "${LOTUS_REPOSITORIES_ROOT:-..}/lotus-risk:/lotus-risk:ro" in compose
    assert "${LOTUS_REPOSITORIES_ROOT:-..}/lotus-advise:/lotus-advise:ro" in compose
    assert "${LOTUS_REPOSITORIES_ROOT:-..}/lotus-report:/lotus-report:ro" in compose
    assert "${LOTUS_REPOSITORIES_ROOT:-..}/lotus-manage:/lotus-manage:ro" in compose
    assert "${LOTUS_REPOSITORIES_ROOT:-..}/lotus-gateway:/lotus-gateway:ro" in compose
    assert "${LOTUS_REPOSITORIES_ROOT:-..}/lotus-idea:/lotus-idea:ro" in compose
    assert "LOTUS_PLATFORM_ROOT: /lotus-platform" in compose


def test_local_ci_targets_enforce_trust_telemetry_freshness() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    for target in ("check", "ci", "ci-local"):
        assert "trust-telemetry-freshness-gate" in _makefile_target_dependencies(makefile, target)


def test_local_ci_targets_enforce_advisory_data_lifecycle_inventory() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    for target in ("check", "ci", "ci-local"):
        assert "advisory-data-lifecycle-gate" in _makefile_target_dependencies(makefile, target)


def test_local_ci_targets_enforce_durable_state_recovery_contract() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    for target in ("check", "ci", "ci-local"):
        assert "durable-state-recovery-gate" in _makefile_target_dependencies(makefile, target)
    assert "scripts/durable_state_recovery_contract.py" in makefile
    assert "output/durable-state-recovery/recovery-drill-evidence.json" in makefile


def test_local_ci_targets_enforce_release_image_provenance_contract() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    for target in ("check", "ci", "ci-local"):
        assert "release-image-provenance-gate" in _makefile_target_dependencies(makefile, target)


def test_dependency_lock_refreshes_license_ip_inventory_first() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "license-ip-inventory" in _makefile_target_dependencies(makefile, "dependency-lock")


def test_local_check_and_feature_lane_enforce_bandit_severity_regression_scan() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    feature_lane = _workflow_text("feature-lane.yml")
    governance_section = _workflow_job_section(feature_lane, "lint-dependency-governance")

    assert "bandit-severity-regression-gate" in _makefile_target_dependencies(makefile, "check")
    assert "bandit-high-severity-gate: bandit-severity-regression-gate" in makefile
    assert "Security Audit" not in governance_section
    assert "Bandit Severity Regression Gate" in governance_section
    assert "run: make bandit-severity-regression-gate" in governance_section


def test_lint_enforces_refactored_complexity_gate_for_ci_lanes() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "$(MAKE) refactored-complexity-gate" in makefile
    assert "refactored-complexity-gate" in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/integrations/lotus_risk/enrichment.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/tactical_house_view.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/policy_packs/workflow_projection.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory/narrative_ai.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/proposals/execution_status.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/integrations/lotus_core/stateful_context_translation.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/proposals/async_operations.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/proposals/async_operation_runner.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/proposals/async_payloads.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/proposals/command_validation.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/integrations/lotus_core/stateful_context_market_data.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/bank_demo_proof/artifact_refs.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/proposals/async_replay.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/common/canonical.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/proposals/idempotency.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/common/intent_dependencies.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory_copilot/record_text.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory_copilot/run_replay_policy.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/integrations/lotus_ai/runtime_config.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory/artifact_evidence.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory/artifact_portfolio.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory/artifact_trades.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory/alternatives_projection.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory/decision_requirements.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory/decision_material_changes.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory/narrative_policy.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/advisory/decision_summary.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/proposals/memo_builder.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/proposals/memo_persistence.py --fail-rank B"
    ) in makefile
    assert (
        "python scripts/radon_complexity_gate.py --source-path "
        "src/core/proposals/memo_response_projection.py --fail-rank B"
    ) in makefile

    for workflow_name in ("feature-lane.yml", "pr-merge-gate.yml", "main-releasability.yml"):
        workflow = _workflow_text(workflow_name)
        assert "run: make lint" in workflow


def test_ci_workflow_jobs_are_bounded_by_timeouts() -> None:
    for workflow_path in WORKFLOW_ROOT.glob("*.yml"):
        _assert_all_jobs_have_timeout(workflow_path.read_text(encoding="utf-8"))


def test_demo_assurance_gate_covers_demo_critical_evidence() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert _makefile_target_dependencies(makefile, "demo-assurance-gate") == {
        "openapi-gate",
        "no-alias-gate",
        "api-vocabulary-gate",
        "domain-data-products-gate",
        "observability-diagnostics",
        "advisory-domain-golden-regressions",
    }


def test_live_demo_certification_command_is_repo_native_and_report_only() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "demo-certification-live:" in makefile
    assert "scripts/run_demo_pack_live.py" in makefile
    assert "LOTUS_ADVISE_DEMO_BASE_URL" in makefile
    assert "LOTUS_ADVISE_DEMO_EVIDENCE" in makefile
    assert "demo-certification-live" not in _makefile_target_dependencies(makefile, "check")
    assert "demo-certification-live" not in _makefile_target_dependencies(makefile, "ci")


def _assert_governance_job_runs_demo_assurance_checks(workflow: str, job_id: str) -> None:
    governance_section = _workflow_job_section(workflow, job_id)

    assert "run: make openapi-gate" in governance_section
    assert "run: make api-vocabulary-gate" in governance_section
    assert governance_section.index("Quality Baseline Freshness") < governance_section.index(
        "Checkout Lotus Platform Contracts"
    )
    assert governance_section.index("Trust Telemetry Freshness") < governance_section.index(
        "Checkout Lotus Platform Contracts"
    )
    assert "Checkout Lotus Platform Contracts" in governance_section
    assert "repository: sgajbi/lotus-platform" in governance_section
    assert "path: lotus-platform" in governance_section
    assert "LOTUS_PLATFORM_ROOT: ${{ github.workspace }}/lotus-platform" in governance_section
    assert "run: make domain-data-products-gate" in governance_section
    assert "run: make observability-diagnostics" in governance_section
    assert "run: make advisory-domain-golden-regressions" in governance_section


def test_pytest_configuration_has_single_authoritative_file() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    pytest_ini = Path("pytest.ini").read_text(encoding="utf-8")

    assert "[tool.pytest.ini_options]" not in pyproject
    assert "[pytest]" in pytest_ini
    assert "testpaths =" in pytest_ini
    assert "addopts = --strict-markers" in pytest_ini


def test_mypy_configuration_has_no_unused_override_sections() -> None:
    mypy_config = Path("mypy.ini").read_text(encoding="utf-8")

    assert "warn_unused_configs = True" in mypy_config
    assert "[mypy-tests.*]" not in mypy_config
    assert "[mypy-scripts.*]" not in mypy_config


def test_feature_lane_unit_tests_run_in_parallel_with_static_governance() -> None:
    workflow = _workflow_text("feature-lane.yml")

    unit_section = _workflow_job_section(workflow, "unit-tests")

    _assert_default_ci_guardrails(workflow)
    _assert_governance_job_runs_baseline_freshness(workflow, "lint-dependency-governance")
    _assert_governance_job_runs_trust_telemetry_freshness(workflow, "lint-dependency-governance")
    _assert_governance_job_runs_demo_assurance_checks(workflow, "lint-dependency-governance")
    assert "Feature Lane / Tests (unit)" in unit_section
    assert "needs:" not in unit_section
    assert "Feature Lane / Lint Dependency Governance" in workflow


def test_pr_and_main_runtime_jobs_are_parallelized_without_renaming_required_checks() -> None:
    for workflow_name, lane_name, coverage_artifact_prefix in (
        ("pr-merge-gate.yml", "PR Merge Gate", "coverage-data-"),
        ("main-releasability.yml", "Main Releasability", "main-releasability-coverage-data-"),
    ):
        workflow = _workflow_text(workflow_name)

        concurrency_group = (
            "group: ${{ github.workflow }}-${{ inputs.expected_sha || github.sha }}"
            if workflow_name == "main-releasability.yml"
            else "group: ${{ github.workflow }}-${{ github.ref }}"
        )
        _assert_default_ci_guardrails(workflow, concurrency_group=concurrency_group)
        _assert_governance_job_runs_baseline_freshness(workflow, "lint-typecheck-governance")
        _assert_governance_job_runs_trust_telemetry_freshness(workflow, "lint-typecheck-governance")
        _assert_governance_job_runs_demo_assurance_checks(workflow, "lint-typecheck-governance")
        assert f"{lane_name} / Lint Typecheck Governance" in workflow
        assert f"{lane_name} / Tests (${{{{ matrix.suite }}}})" in workflow
        assert f"{lane_name} / Coverage Gate (Combined)" in workflow
        assert f"{lane_name} / Validate Docker Build" in workflow

        for job_id in (
            "test-suites",
            "postgres-migration-smoke",
            "production-profile-smoke",
            "production-profile-guardrail-negatives",
        ):
            job_section = _workflow_job_section(workflow, job_id)
            if workflow_name == "main-releasability.yml":
                assert "needs: [exact-revision-assertion]" in job_section
            else:
                assert "needs: [lint-typecheck-governance]" not in job_section

        docker_section = _workflow_job_section(workflow, "docker-build")
        assert (
            "needs: [coverage-gate, postgres-migration-smoke, production-profile-smoke, "
            "production-profile-guardrail-negatives]"
        ) in docker_section
        assert "CI_PIPELINE_ID: ${{ github.run_id }}" in docker_section
        assert "GIT_SHA: ${{ github.sha }}" in docker_section
        assert "run: make docker-build" in docker_section

        coverage_section = _workflow_job_section(workflow, "coverage-gate")
        assert "needs: [test-suites]" in coverage_section
        assert f"pattern: {coverage_artifact_prefix}*" in coverage_section

        test_section = _workflow_job_section(workflow, "test-suites")
        assert f"name: {coverage_artifact_prefix}${{{{ matrix.suite }}}}" in test_section
        assert "include-hidden-files: true" in test_section
        assert "if-no-files-found: error" in test_section


def test_main_releasability_pushes_only_ci_release_image_with_evidence_artifacts() -> None:
    workflow = _workflow_text("main-releasability.yml")
    release_section = _workflow_job_section(workflow, "image-release-evidence")
    pr_workflow = _workflow_text("pr-merge-gate.yml")

    assert "Main Releasability / Image Release Evidence" in release_section
    assert "needs: [docker-build]" in release_section
    assert "packages: write" in release_section
    assert "id-token: write" in release_section
    assert "attestations: write" in release_section
    assert "IMAGE_REF: ghcr.io/${{ github.repository }}:${{ github.sha }}" in release_section
    assert "docker/setup-buildx-action@v4.2.0" in release_section
    assert "docker/login-action@v4.4.0" in release_section
    assert "docker/build-push-action@v7.3.0" in release_section
    assert "docker/setup-buildx-action@v3" not in release_section
    assert "docker/login-action@v3" not in release_section
    assert "docker/build-push-action@v6" not in release_section
    assert "push: true" in release_section
    assert "LOTUS_BUILD_COMMIT_SHA=${{ github.sha }}" in release_section
    assert "LOTUS_CI_PIPELINE_ID=${{ github.run_id }}" in release_section
    assert "anchore/sbom-action@v0" in release_section
    assert 'TRIVY_VERSION: "0.72.0"' in release_section
    assert "Install Trivy CLI" in release_section
    assert (
        'trivy_release_base="https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}"'
        in release_section
    )
    assert 'expected_checksum="$(awk -v file="$archive"' in release_section
    assert 'test "$expected_checksum" = "$actual_checksum"' in release_section
    assert 'mkdir -p "$HOME/.local/bin"' in release_section
    assert "Record full image vulnerability inventory" in release_section
    assert "Enforce fixable high critical vulnerability gate" in release_section
    assert "trivy image" in release_section
    assert "--output output/release/trivy-image-inventory.json" in release_section
    assert "--output output/release/trivy-image-scan.json" in release_section
    assert "--severity UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL" in release_section
    assert "--exit-code 0" in release_section
    assert "--severity HIGH,CRITICAL" in release_section
    assert "--ignore-unfixed" in release_section
    assert "--exit-code 1" in release_section
    assert "sigstore/cosign-installer@v3.9.2" in release_section
    assert "cosign sign --yes" in release_section
    assert "actions/attest-build-provenance@v4.1.1" in release_section
    assert "subject-name: ghcr.io/${{ github.repository }}" in release_section
    assert "subject-name: ${{ env.IMAGE_REF }}" not in release_section
    assert "scripts/release_image_evidence.py write-manifest" in release_section
    assert "release-evidence.json" in release_section
    assert "name: lotus-advise-image-release-evidence" in release_section

    assert "docker/login-action@v3" not in pr_workflow
    assert "docker/login-action@v4" not in pr_workflow
    assert "push: true" not in pr_workflow


def test_nightly_postgres_demo_pack_declares_controlled_ci_fallback() -> None:
    workflow = _workflow_text("nightly-postgres-full.yml")

    _assert_default_ci_guardrails(workflow)
    assert "PROPOSAL_STORE_BACKEND: POSTGRES" in workflow
    assert "POLICY_STORE_BACKEND: POSTGRES" in workflow
    assert "WORKSPACE_STORE_BACKEND: POSTGRES" in workflow
    expected_dsn = "postgresql://dpm:dpm@127.0.0.1:5432/dpm_supportability"
    assert f"PROPOSAL_POSTGRES_DSN: {expected_dsn}" in workflow
    assert f"POLICY_POSTGRES_DSN: {expected_dsn}" in workflow
    assert f"WORKSPACE_POSTGRES_DSN: {expected_dsn}" in workflow
    assert "python scripts/postgres_migrate.py --target all" in workflow
    assert "DPM_SUPPORTABILITY_POSTGRES_DSN" not in workflow
    assert "DPM_POLICY_PACK_POSTGRES_DSN" not in workflow
    assert "DPM_POLICY_PACK_CATALOG_BACKEND" not in workflow
    assert "ENVIRONMENT: ci" in workflow
    assert 'LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK: "true"' in workflow
    assert "python scripts/run_demo_pack_live.py \\" in workflow
    assert "--base-url http://127.0.0.1:8010 \\" in workflow
    assert (
        "--output output/demo-certification/nightly-postgres/lotus-advise-demo-certification.json"
    ) in workflow
    assert "Upload Demo Certification Evidence" in workflow
    assert "name: lotus-advise-demo-certification" in workflow
    assert "if-no-files-found: error" in workflow


def test_validation_wiki_documents_repo_native_ci_enforcement() -> None:
    text = Path("wiki/Validation-and-CI.md").read_text(encoding="utf-8")

    required_terms = [
        "Local fast gate",
        "Remote Feature Lane",
        "PR Merge Gate",
        "Main Releasability Gate",
        "Report-only quality evidence",
        "make quality-baseline-check",
        "make trust-telemetry-freshness-gate",
        "make demo-assurance-gate",
        "make demo-certification-live",
        "make bandit-severity-regression-gate",
        "make observability-diagnostics",
        "make advisory-domain-golden-regressions",
        "measured, deterministic, repo-native, and low-noise",
        "poll GitHub sparsely",
        "..\\lotus-platform\\automation\\Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-advise",
        "..\\lotus-platform\\automation\\Sync-RepoWikis.ps1 -Publish -Repository lotus-advise",
        "does not by itself",
        "bank certification",
    ]

    for term in required_terms:
        assert term in text


def test_pull_request_target_auto_merge_is_guarded_to_internal_labeled_prs() -> None:
    workflow = _workflow_text("pr-auto-merge.yml")
    auto_merge_section = _workflow_job_section(workflow, "queue-auto-merge")

    assert "pull_request_target:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "contents: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "github.event.pull_request.base.ref == 'main'" in auto_merge_section
    assert "github.event.pull_request.head.repo.fork == false" in auto_merge_section
    assert "contains(github.event.pull_request.labels.*.name, 'automerge')" in auto_merge_section
    assert "secrets.LOTUS_AUTOMERGE_TOKEN" in auto_merge_section
    assert "github.token" not in workflow
    assert "LOTUS_AUTOMERGE_TOKEN is required" in auto_merge_section
    assert "Skipping auto-merge; use an authorized human or release actor" in auto_merge_section
    assert 'gh pr merge "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --auto --rebase' in (
        auto_merge_section
    )
    assert "--auto --merge" not in auto_merge_section


def test_merged_pr_dispatches_main_releasability_on_main() -> None:
    workflow = _workflow_text("merged-pr-main-releasability.yml")
    dispatch_section = _workflow_job_section(workflow, "dispatch-main-releasability")

    assert "pull_request_target:" in workflow
    assert "types: [closed]" in workflow
    assert "permissions:\n  actions: write\n  contents: write" in workflow
    assert "github.event.pull_request.merged == true" in dispatch_section
    assert "github.event.pull_request.base.ref == 'main'" in dispatch_section
    assert "gh workflow run main-releasability.yml" in dispatch_section
    assert 'dispatch_ref="main-releasability-${MERGE_COMMIT_SHA}"' in dispatch_section
    assert (
        'existing_ref_sha="$(gh api "repos/$GITHUB_REPOSITORY/git/ref/tags/$dispatch_ref"'
        in dispatch_section
    )
    assert "Dispatch ref $dispatch_ref points to $existing_ref_sha" in dispatch_section
    assert 'gh api "repos/$GITHUB_REPOSITORY/git/refs"' in dispatch_section
    assert '--ref "$dispatch_ref"' in dispatch_section
    assert "github.event.pull_request.merge_commit_sha" in dispatch_section
    assert '-f expected_sha="$MERGE_COMMIT_SHA"' in dispatch_section
    assert '-f triggering_pr="$PR_NUMBER"' in dispatch_section


def test_main_releasability_uses_dispatcher_without_duplicate_push_trigger() -> None:
    workflow = _workflow_text("main-releasability.yml")
    trigger_section = workflow.split("concurrency:", maxsplit=1)[0]

    assert "workflow_dispatch:" in trigger_section
    assert "expected_sha:" in trigger_section
    assert "triggering_pr:" in trigger_section
    assert "${{ inputs.expected_sha || github.sha }}" in workflow
    assert "LOTUS_RELEASE_GIT_REF: ${{ inputs.expected_sha && 'main' || github.ref_name }}" in (
        workflow
    )
    assert "GIT_BRANCH: ${{ env.LOTUS_RELEASE_GIT_REF }}" in workflow
    assert "LOTUS_BUILD_GIT_BRANCH=${{ env.LOTUS_RELEASE_GIT_REF }}" in workflow
    assert "org.opencontainers.image.ref.name=${{ env.LOTUS_RELEASE_GIT_REF }}" in workflow
    assert '--git-ref "${{ env.LOTUS_RELEASE_GIT_REF }}"' in workflow
    assert "git rev-parse HEAD" in workflow
    assert 'if [ "$actual_sha" != "$EXPECTED_SHA" ]; then' in workflow
    assert "does not match expected merged PR SHA" in workflow
    assert "git fetch --no-tags origin main:refs/remotes/origin/main" in workflow
    assert 'git merge-base --is-ancestor "$EXPECTED_SHA" origin/main' in workflow
    assert "refusing to label this run as mainline release evidence" in workflow
    assert "push:" not in trigger_section
    assert 'branches: ["main"]' not in trigger_section
