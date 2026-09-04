# Lotus Advise Quality Baseline Report

- Generated At: `2026-09-04T20:10:38.593553+00:00`
- Git Identity: omitted from committed Markdown; use Git history and GitHub Actions
  run metadata for exact branch/head evidence.
- CI Phase: `calibrated-regression`

## Code Size

- Python files: `1112`
- Packages: `42`
- Modules: `1070`
- Total Python lines: `205209`

## Largest Files

| Rank | File | Lines |
| ---: | --- | ---: |
| 1 | `tests/unit/advisory/api/test_api_advisory_proposal_lifecycle.py` | 4049 |
| 2 | `tests/unit/advisory/api/test_lotus_core_stateful_context.py` | 2763 |
| 3 | `tests/unit/advisory/engine/test_engine_proposal_workflow_service.py` | 2691 |
| 4 | `tests/unit/advisory/api/test_api_workspace.py` | 2569 |
| 5 | `tests/unit/advisory/engine/test_engine_proposal_repository_postgres.py` | 2293 |
| 6 | `scripts/validate_cross_service_parity_live.py` | 2155 |
| 7 | `tests/integration/advisory/engine/test_engine_proposal_repository_postgres_integration.py` | 1989 |
| 8 | `tests/unit/advisory/engine/test_advisory_copilot_persistence.py` | 1907 |
| 9 | `tests/unit/advisory/api/test_api_advisory_policy_evaluations.py` | 1760 |
| 10 | `tests/unit/advisory/api/test_api_advisory_proposal_simulate.py` | 1737 |

## Largest Functions And Maintainability Hotspots

| Rank | Function | File | Line | Lines |
| ---: | --- | --- | ---: | ---: |
| 1 | `test_lifecycle_async_and_support_schemas_have_descriptions_and_examples` | `tests/unit/advisory/contracts/test_contract_openapi_lifecycle_docs.py` | 62 | 405 |
| 2 | `test_live_postgres_idea_intake_persists_portfolio_scope_for_recovery` | `tests/integration/advisory/engine/test_engine_proposal_repository_postgres_integration.py` | 1444 | 355 |
| 3 | `execute` | `tests/unit/advisory/engine/test_engine_proposal_repository_postgres.py` | 197 | 325 |
| 4 | `test_quality_baseline_report_captures_required_quality_sections` | `tests/unit/scripts/test_quality_baseline_report.py` | 120 | 311 |
| 5 | `test_resolve_stateful_context_with_lotus_core_builds_simulation_request` | `tests/unit/advisory/api/test_lotus_core_stateful_context.py` | 1389 | 225 |
| 6 | `test_proof_pack_indexes_assets_and_blocks_sensitive_committed_material` | `tests/unit/advisory/engine/test_engine_bank_demo_proof_models.py` | 381 | 216 |
| 7 | `_live_runtime_payload` | `tests/unit/advisory/engine/test_engine_bank_demo_proof_capture.py` | 26 | 187 |
| 8 | `test_live_postgres_idea_intake_claim_is_restart_safe_and_conflict_detecting` | `tests/integration/advisory/engine/test_engine_proposal_repository_postgres_integration.py` | 1257 | 185 |
| 9 | `test_lifecycle_endpoints_use_separate_request_and_response_objects` | `tests/unit/advisory/contracts/test_contract_openapi_lifecycle_docs.py` | 469 | 185 |
| 10 | `assert_live_workspace_flow` | `scripts/live_workspace_flow.py` | 121 | 181 |

## Complexity

- Current baseline uses largest-function and router-hotspot evidence as deterministic
  complexity proxies.
- Radon config executable: `True`
- Radon analyzed block inventory: `5144`
- Radon complexity rank inventory: `A=5013, B=131`
- Radon worst complexity: `rank=B, complexity=10`
- Radon C/D/E/F-ranked block enforcement is repo-native through
  `make complexity-regression-gate` and the `lint` lane.
- Xenon and stricter B-ranked Radon thresholds remain report-only until current
  B-ranked helpers are classified.

## Lint And Type Issues

- Ruff configured: `True`
- Mypy configured: `True`
- Current enforcement remains repo-native through `make lint` and `make typecheck`.

## Coverage

- Unit/integration/E2E coverage gate is repo-native through `make coverage-combined`.
- Configured fail-under target: `97`.

## Dead Code

- Vulture config executable: `True`
- Vulture current issue inventory: `6`
- Vulture confidence inventory: `90%=6`
- Vulture findings are hard-gated by `make dead-code-gate`; reviewed compatibility-facade
  exceptions are fingerprinted and carry owner, reason, and expiry metadata.

## Duplicate Code

- jscpd is pinned at `5.0.16` in `package-lock.json`.
- New clone fingerprints are hard-gated by `make duplicate-code-gate`; the reviewed
  baseline is versioned with owner, reason, expiry, and content-hash provenance.
- Scanner, parser, policy, or baseline-integrity failures fail closed.

## Dependencies

- Dependency verification configured: `True`
- Security audit configured: `True`
- Available dependency/security tools: `ruff, mypy, pytest, coverage.py, pip-audit, radon, xenon, vulture, deptry, bandit, interrogate`
- Pending optional tools: ``
- Deptry config executable: `True`
- Deptry current issue inventory: `13`
- Bandit config executable: `True`
- Bandit current issue inventory: `30`
- Bandit severity inventory: `high=0, medium=30, low=0`

## Security

- `pip-audit` is present in development requirements.
- `bandit` severity-regression enforcement is repo-native through
  `make bandit-severity-regression-gate`, `make check`, Feature Lane, and the
  `security-audit` lane.
- Medium and low Bandit findings are governed by
  `quality/bandit_security_baseline.v1.json` with expiry and remediation links.
- Sensitive-data handling remains governed by API error redaction and structured
  payload tests until the security report gate is calibrated.

## OpenAPI Gaps

- Repo-native OpenAPI gate configured: `True`
- Spectral rules present: `True`
- Spectral config executable: `True`
- Spectral OpenAPI path inventory: `90`
- Spectral current issue inventory: `0`
- Spectral severity inventory: `none`
- Spectral is enforced through `make openapi-gate`; the inventory remains recorded
  for before/after scorecard evidence.

## Architecture Violations

- Import-linter contracts present: `True`
- Import-linter config executable: `True`
- Import-linter contract inventory: `total=4, kept=4, broken=0`
- Import-linter contracts enforced by `make architecture-boundaries` and `make lint`.

## Documentation Gaps

- Requested docs present: `docs/architecture.md, docs/api-governance.md, docs/observability.md, docs/security.md, docs/operations-runbook.md, docs/supported-features.md`
- Requested docs missing: `none`
- Interrogate config executable: `True`
- Interrogate docstring inventory: `total=5918, missing=5721, covered=197, coverage=3.3%`
- Interrogate documentation coverage trend is hard-gated by `make quality-trend-gate`;
  absolute public API and module-ownership thresholds remain report-only until
  classified.

## Observability Gaps

- Observability documentation is present.
- Observability diagnostics target: `make observability-diagnostics`
- Focused diagnostics currently verify correlation, request, trace,
  and structured-log propagation.
- Request and audit telemetry use bounded route templates and operation names
  instead of raw URL paths or resource identifiers.
- Demo assurance gate: `make demo-assurance-gate` ties API governance,
  domain golden regressions, observability diagnostics, and domain-data
  product validation into a repeatable local evidence command.
- Live demo certification: `make demo-certification-live` writes
  machine-readable app-level evidence for live runtime route safety,
  deterministic synthetic scenarios, and capability truth.
- Dashboard, alert, SLO, and distributed-tracing evidence remain tracked gaps.
