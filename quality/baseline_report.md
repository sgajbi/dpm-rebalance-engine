# Lotus Advise Quality Baseline Report

- Generated At: `2026-08-24T15:35:40.865178+00:00`
- Git Identity: omitted from committed Markdown; use Git history and GitHub Actions
  run metadata for exact branch/head evidence.
- CI Phase: `calibrated-regression`

## Code Size

- Python files: `1077`
- Packages: `42`
- Modules: `1035`
- Total Python lines: `194694`

## Largest Files

| Rank | File | Lines |
| ---: | --- | ---: |
| 1 | `tests/unit/advisory/api/test_api_advisory_proposal_lifecycle.py` | 4043 |
| 2 | `scripts/validate_cross_service_parity_live.py` | 4010 |
| 3 | `tests/unit/advisory/engine/test_engine_proposal_workflow_service.py` | 2691 |
| 4 | `tests/unit/advisory/api/test_lotus_core_stateful_context.py` | 2675 |
| 5 | `tests/unit/advisory/api/test_api_workspace.py` | 2567 |
| 6 | `tests/unit/advisory/engine/test_engine_proposal_repository_postgres.py` | 1978 |
| 7 | `tests/unit/advisory/engine/test_advisory_copilot_persistence.py` | 1907 |
| 8 | `tests/unit/advisory/api/test_api_advisory_policy_evaluations.py` | 1760 |
| 9 | `tests/unit/advisory/api/test_api_advisory_proposal_simulate.py` | 1737 |
| 10 | `scripts/quality_baseline_report.py` | 1635 |

## Largest Functions And Maintainability Hotspots

| Rank | Function | File | Line | Lines |
| ---: | --- | --- | ---: | ---: |
| 1 | `execute` | `tests/unit/advisory/engine/test_engine_proposal_repository_postgres.py` | 63 | 508 |
| 2 | `render_refactor_health_report` | `scripts/quality_baseline_report.py` | 817 | 494 |
| 3 | `test_lifecycle_async_and_support_schemas_have_descriptions_and_examples` | `tests/unit/advisory/contracts/test_contract_openapi_lifecycle_docs.py` | 62 | 405 |
| 4 | `test_quality_baseline_report_captures_required_quality_sections` | `tests/unit/scripts/test_quality_baseline_report.py` | 92 | 310 |
| 5 | `validate_live_cross_service_parity` | `scripts/validate_cross_service_parity_live.py` | 3695 | 274 |
| 6 | `_assert_persisted_read_surfaces` | `scripts/validate_cross_service_parity_live.py` | 3422 | 271 |
| 7 | `render_quality_scorecard` | `scripts/quality_baseline_report.py` | 1313 | 255 |
| 8 | `_assert_live_policy_evaluation_flow` | `scripts/validate_cross_service_parity_live.py` | 2491 | 252 |
| 9 | `_assert_lifecycle_and_delivery_flow` | `scripts/validate_cross_service_parity_live.py` | 1788 | 249 |
| 10 | `_validate_live_proposal_alternatives_paths` | `scripts/validate_cross_service_parity_live.py` | 608 | 230 |

## Complexity

- Current baseline uses largest-function and router-hotspot evidence as deterministic
  complexity proxies.
- Radon config executable: `True`
- Radon analyzed block inventory: `5005`
- Radon complexity rank inventory: `A=4871, B=134`
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
- Interrogate docstring inventory: `total=5658, missing=5586, covered=72, coverage=1.3%`
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
