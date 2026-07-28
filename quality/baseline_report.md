# Lotus Advise Quality Baseline Report

- Generated At: `2026-07-28T12:39:38.739868+00:00`
- Git Identity: omitted from committed Markdown; use Git history and GitHub Actions
  run metadata for exact branch/head evidence.
- CI Phase: `baseline/report-only`

## Code Size

- Python files: `1053`
- Packages: `41`
- Modules: `1012`
- Total Python lines: `184087`

## Largest Files

| Rank | File | Lines |
| ---: | --- | ---: |
| 1 | `scripts/validate_cross_service_parity_live.py` | 4010 |
| 2 | `tests/unit/advisory/api/test_api_advisory_proposal_lifecycle.py` | 3943 |
| 3 | `tests/unit/advisory/engine/test_engine_proposal_workflow_service.py` | 2560 |
| 4 | `tests/unit/advisory/api/test_api_workspace.py` | 2547 |
| 5 | `tests/unit/advisory/api/test_lotus_core_stateful_context.py` | 2449 |
| 6 | `tests/unit/advisory/engine/test_engine_proposal_repository_postgres.py` | 1978 |
| 7 | `tests/unit/advisory/engine/test_advisory_copilot_persistence.py` | 1863 |
| 8 | `tests/unit/advisory/api/test_api_advisory_proposal_simulate.py` | 1737 |
| 9 | `scripts/quality_baseline_report.py` | 1615 |
| 10 | `tests/unit/advisory/api/test_api_advisory_policy_evaluations.py` | 1567 |

## Largest Functions And Maintainability Hotspots

| Rank | Function | File | Line | Lines |
| ---: | --- | --- | ---: | ---: |
| 1 | `execute` | `tests/unit/advisory/engine/test_engine_proposal_repository_postgres.py` | 63 | 508 |
| 2 | `render_refactor_health_report` | `scripts/quality_baseline_report.py` | 805 | 494 |
| 3 | `test_lifecycle_async_and_support_schemas_have_descriptions_and_examples` | `tests/unit/advisory/contracts/test_contract_openapi_lifecycle_docs.py` | 62 | 398 |
| 4 | `test_quality_baseline_report_captures_required_quality_sections` | `tests/unit/scripts/test_quality_baseline_report.py` | 92 | 304 |
| 5 | `validate_live_cross_service_parity` | `scripts/validate_cross_service_parity_live.py` | 3695 | 274 |
| 6 | `_assert_persisted_read_surfaces` | `scripts/validate_cross_service_parity_live.py` | 3422 | 271 |
| 7 | `_assert_live_policy_evaluation_flow` | `scripts/validate_cross_service_parity_live.py` | 2491 | 252 |
| 8 | `_assert_lifecycle_and_delivery_flow` | `scripts/validate_cross_service_parity_live.py` | 1788 | 249 |
| 9 | `render_quality_scorecard` | `scripts/quality_baseline_report.py` | 1301 | 247 |
| 10 | `_validate_live_proposal_alternatives_paths` | `scripts/validate_cross_service_parity_live.py` | 608 | 230 |

## Complexity

- Current baseline uses largest-function and router-hotspot evidence as deterministic
  complexity proxies.
- Radon config executable: `True`
- Radon analyzed block inventory: `4916`
- Radon complexity rank inventory: `A=4801, B=115`
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
- Vulture remains report-only until validator false positives and compatibility
  facade imports are classified.
- Current dead-code cleanup remains code-led through review-ledger slices.

## Dependencies

- Dependency verification configured: `True`
- Security audit configured: `True`
- Available dependency/security tools: `ruff, mypy, pytest, coverage.py, pip-audit, radon, xenon, vulture, deptry, bandit, interrogate`
- Pending optional tools: ``
- Deptry config executable: `True`
- Deptry current issue inventory: `19`
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
- Spectral OpenAPI path inventory: `87`
- Spectral current issue inventory: `0`
- Spectral severity inventory: `none`
- Spectral is enforced through `make openapi-gate`; the inventory remains recorded
  for before/after scorecard evidence.

## Architecture Violations

- Import-linter contracts present: `True`
- Import-linter config executable: `True`
- Import-linter contract inventory: `total=4, kept=4, broken=0`
- Contracts remain report-only until the kept inventory is wired into a CI gate.

## Documentation Gaps

- Requested docs present: `docs/architecture.md, docs/api-governance.md, docs/observability.md, docs/security.md, docs/operations-runbook.md, docs/supported-features.md`
- Requested docs missing: `none`
- Interrogate config executable: `True`
- Interrogate docstring inventory: `total=5457, missing=5406, covered=51, coverage=0.9%`
- Interrogate remains report-only until public API and module ownership thresholds
  are classified.

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
