# Lotus Advise Engineering Health Baseline

- Generated At: `2026-08-23T21:08:14.339329+00:00`
- Git Identity: omitted from committed Markdown; use Git history and GitHub Actions
  run metadata for exact branch/head evidence.
- Python Files: `1064`
- Packages: `41`
- Modules: `1023`
- Total Python Lines: `192093`

## Largest Files

| Rank | File | Lines |
| ---: | --- | ---: |
| 1 | `tests/unit/advisory/api/test_api_advisory_proposal_lifecycle.py` | 4043 |
| 2 | `scripts/validate_cross_service_parity_live.py` | 4010 |
| 3 | `tests/unit/advisory/engine/test_engine_proposal_workflow_service.py` | 2691 |
| 4 | `tests/unit/advisory/api/test_lotus_core_stateful_context.py` | 2675 |
| 5 | `tests/unit/advisory/api/test_api_workspace.py` | 2555 |
| 6 | `tests/unit/advisory/engine/test_engine_proposal_repository_postgres.py` | 1978 |
| 7 | `tests/unit/advisory/engine/test_advisory_copilot_persistence.py` | 1907 |
| 8 | `tests/unit/advisory/api/test_api_advisory_policy_evaluations.py` | 1760 |
| 9 | `tests/unit/advisory/api/test_api_advisory_proposal_simulate.py` | 1737 |
| 10 | `scripts/quality_baseline_report.py` | 1636 |
| 11 | `tests/unit/advisory/api/test_lotus_ai_advisory_copilot.py` | 1615 |
| 12 | `tests/unit/advisory/engine/test_engine_policy_pack_persistence.py` | 1511 |
| 13 | `tests/unit/advisory/engine/test_engine_advisory_copilot_foundation.py` | 1337 |
| 14 | `tests/integration/advisory/engine/test_engine_proposal_repository_postgres_integration.py` | 1191 |
| 15 | `tests/integration/advisory/api/test_proposal_api_workflow_integration.py` | 1184 |
| 16 | `tests/unit/advisory/engine/test_engine_advisor_cockpit_service.py` | 1083 |
| 17 | `tests/unit/advisory/api/test_api_integration_capabilities.py` | 1005 |
| 18 | `src/api/openapi_enrichment.py` | 983 |
| 19 | `tests/unit/advisory/engine/test_engine_advisory_proposal_simulation.py` | 975 |
| 20 | `tests/unit/advisory/contracts/test_contract_openapi_lifecycle_docs.py` | 946 |

## Largest Functions

| Rank | Function | File | Line | Lines |
| ---: | --- | --- | ---: | ---: |
| 1 | `execute` | `tests/unit/advisory/engine/test_engine_proposal_repository_postgres.py` | 63 | 508 |
| 2 | `render_refactor_health_report` | `scripts/quality_baseline_report.py` | 817 | 494 |
| 3 | `test_lifecycle_async_and_support_schemas_have_descriptions_and_examples` | `tests/unit/advisory/contracts/test_contract_openapi_lifecycle_docs.py` | 62 | 398 |
| 4 | `test_quality_baseline_report_captures_required_quality_sections` | `tests/unit/scripts/test_quality_baseline_report.py` | 92 | 308 |
| 5 | `validate_live_cross_service_parity` | `scripts/validate_cross_service_parity_live.py` | 3695 | 274 |
| 6 | `_assert_persisted_read_surfaces` | `scripts/validate_cross_service_parity_live.py` | 3422 | 271 |
| 7 | `render_quality_scorecard` | `scripts/quality_baseline_report.py` | 1313 | 256 |
| 8 | `_assert_live_policy_evaluation_flow` | `scripts/validate_cross_service_parity_live.py` | 2491 | 252 |
| 9 | `_assert_lifecycle_and_delivery_flow` | `scripts/validate_cross_service_parity_live.py` | 1788 | 249 |
| 10 | `_validate_live_proposal_alternatives_paths` | `scripts/validate_cross_service_parity_live.py` | 608 | 230 |
| 11 | `_assert_live_proposal_memo_flow` | `scripts/validate_cross_service_parity_live.py` | 2261 | 228 |
| 12 | `test_resolve_stateful_context_with_lotus_core_builds_simulation_request` | `tests/unit/advisory/api/test_lotus_core_stateful_context.py` | 1331 | 225 |
| 13 | `test_proof_pack_indexes_assets_and_blocks_sensitive_committed_material` | `tests/unit/advisory/engine/test_engine_bank_demo_proof_models.py` | 381 | 216 |
| 14 | `_live_runtime_payload` | `tests/unit/advisory/engine/test_engine_bank_demo_proof_capture.py` | 26 | 187 |
| 15 | `test_lifecycle_endpoints_use_separate_request_and_response_objects` | `tests/unit/advisory/contracts/test_contract_openapi_lifecycle_docs.py` | 462 | 185 |
| 16 | `test_openapi_enrichment_adds_operation_docs_tags_errors_and_schema_examples` | `tests/unit/advisory/api/test_openapi_enrichment.py` | 6 | 179 |
| 17 | `_assert_live_proposal_narrative_flow` | `scripts/validate_cross_service_parity_live.py` | 2053 | 174 |
| 18 | `_assert_workspace_flow` | `scripts/validate_cross_service_parity_live.py` | 3052 | 173 |
| 19 | `_assert_mixed_approval_routes_remain_version_scoped` | `scripts/validate_cross_service_parity_live.py` | 1616 | 170 |
| 20 | `test_live_postgres_proposal_repository_parity_contract` | `tests/integration/advisory/engine/test_engine_proposal_repository_postgres_integration.py` | 51 | 170 |

## Router Hotspots

| Rank | Router File | Route Decorators | Lines |
| ---: | --- | ---: | ---: |
| 1 | `src/api/proposals/routes_lifecycle.py` | 10 | 319 |
| 2 | `src/api/workspaces/routes_session.py` | 9 | 276 |
| 3 | `src/api/proposals/routes_advisory_copilot.py` | 8 | 268 |
| 4 | `src/api/proposals/routes_advisor_cockpit.py` | 6 | 301 |
| 5 | `src/api/proposals/routes_policy_evaluation_reads.py` | 6 | 187 |
| 6 | `src/api/proposals/routes_delivery.py` | 6 | 156 |
| 7 | `src/api/proposals/routes_support.py` | 6 | 147 |
| 8 | `src/api/proposals/routes_policy_packs.py` | 4 | 208 |
| 9 | `src/api/proposals/routes_memo_reads.py` | 4 | 139 |
| 10 | `src/api/proposals/routes_async.py` | 4 | 124 |
| 11 | `tests/unit/advisory/api/test_api_internal_guards.py` | 3 | 801 |
| 12 | `src/api/proposals/routes_memo_commands.py` | 3 | 141 |
| 13 | `src/api/routers/bank_demo_proof.py` | 3 | 97 |
| 14 | `src/api/proposals/routes_policy_evaluation_commands.py` | 2 | 391 |
| 15 | `src/api/proposals/routes_policy_evaluation_packages.py` | 2 | 249 |
| 16 | `src/api/proposals/routes_policy_evaluation_workflow.py` | 2 | 149 |
| 17 | `src/api/proposals/routes_memo_packages.py` | 2 | 107 |
| 18 | `src/api/routers/advisory_simulation.py` | 2 | 90 |
| 19 | `src/api/workspaces/routes_assistant.py` | 2 | 69 |
| 20 | `src/api/proposals/routes_idea_intake.py` | 1 | 77 |

## Repo-Native Gate Inventory

| Make Target | Command |
| --- | --- |
| `test-unit` | `python -m pytest tests/unit` |
| `test-integration` | `python -m pytest tests/integration` |
| `test-e2e` | `python -m pytest tests/e2e` |
| `typecheck` | `python -m mypy --config-file mypy.ini` |
| `openapi-gate` | `python scripts/openapi_quality_gate.py` |
| `openapi-gate` | `python -m pytest tests/unit/advisory/contracts/test_contract_openapi_lifecycle_docs.py -q` |
| `openapi-gate` | `$(MAKE) openapi-spectral-report` |
| `no-alias-gate` | `python scripts/no_alias_contract_guard.py` |
| `api-vocabulary-gate` | `python scripts/api_vocabulary_inventory.py` |
| `api-vocabulary-gate` | `python scripts/api_vocabulary_inventory.py --validate-only` |
| `domain-data-products-gate` | `python scripts/validate_domain_data_product_declarations.py` |
| `quality-baseline` | `python scripts/quality_baseline_report.py --output-dir quality` |
| `lint` | `python -m ruff check .` |
| `lint` | `python -m ruff format --check .` |
| `lint` | `$(MAKE) monetary-float-guard` |
| `lint` | `$(MAKE) architecture-boundaries` |
| `lint` | `$(MAKE) complexity-regression-gate` |
| `lint` | `$(MAKE) refactored-complexity-gate` |
| `observability-diagnostics` | `python -m pytest tests/unit/advisory/api/test_api_observability.py -q` |
| `advisory-domain-golden-regressions` | `python -m pytest tests/unit/advisory/golden -q` |
| `demo-assurance-gate` | `@echo "Demo assurance gate passed"` |
| `verify-dependencies` | `python scripts/dependency_health_check.py --requirements requirements.txt --dev-requirements requirements-dev.txt --outdated-scope direct --target-python-version $${PYTHON_VERSION:-3.11} --skip-audit` |
| `security-audit` | `python scripts/dependency_health_check.py --requirements requirements.txt --dev-requirements requirements-dev.txt --outdated-scope direct --target-python-version $${PYTHON_VERSION:-3.11}` |
| `security-audit` | `$(MAKE) bandit-severity-regression-gate` |
| `coverage-combined` | `COVERAGE_FILE=.coverage.unit python -m pytest tests/unit --cov=src --cov-report=` |
| `coverage-combined` | `COVERAGE_FILE=.coverage.integration python -m pytest tests/integration --cov=src --cov-report=` |
| `coverage-combined` | `COVERAGE_FILE=.coverage.e2e python -m pytest tests/e2e --cov=src --cov-report=` |
| `coverage-combined` | `python -m coverage combine .coverage.unit .coverage.integration .coverage.e2e` |
| `coverage-combined` | `python -m coverage report --fail-under=97` |

## Interpretation

- This baseline captures deterministic structural metrics from the current branch.
- Use `--format json` to save a phase snapshot and `--compare-to <snapshot.json>`
  to render structural metric deltas in later refactoring phases.
- External scanner inventories should move from measurement to repo-native gates in
  calibrated slices; coverage, import-linter, Spectral, Bandit severity regression,
  Radon C/D/E/F-ranked complexity, Vulture no-new-regression, and deptry
  no-new-regression checks now have enforced paths while interrogate and stricter
  complexity thresholds remain measured backlog.
