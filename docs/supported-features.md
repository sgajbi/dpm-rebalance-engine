# Lotus Advise Supported Features

This document records current supported-feature posture without overclaiming production or bank
certification readiness.

For the fuller operator-facing matrix, use `wiki/Supported-Features.md`. For demo preparation, use
`wiki/Demo-Readiness-Guide.md` and
`docs/commercial/RFC-0028-bank-demo-client-proof-materials.md`.

## Supported In Current Repo Gates

| Capability family | Current support | Primary evidence |
| --- | --- | --- |
| Advisory proposal simulation and artifact | Supported for governed advisory scenarios and deterministic proposal artifact generation. | Unit, integration, OpenAPI, and demo payload tests. |
| Proposal lifecycle | Supported for persisted proposal creation, immutable versions, transitions, approvals, consent posture, delivery posture, execution-readiness posture, and additive typed caller-requested/effective valuation-date and reporting-currency evidence for current and simulated states. The additive proposal-review evidence envelope now preserves requested benchmark/mandate context while exposing effective benchmark and mandate-limit evidence as explicit `UNAVAILABLE`: Core has an existing benchmark-assignment route, but Advise does not yet consume or map it, and no mandate-limit observation producer is mapped. Omitted caller dimensions remain omitted; Advise does not calculate valuation, benchmark, or mandate limits. | Proposal lifecycle tests, typed valuation-context/proposal-review-evidence/OpenAPI contract tests, Core-route revisit fitness test, Postgres migration smoke, and workflow contract docs. |
| Idea conversion realization | Implemented for source-safe intake, durable adviser-review work, explicit one-to-one linkage to an existing same-portfolio Advise proposal, and append-only terminal advisory outcomes derived only from authoritative proposal state. Cross-repository Idea consumer reconciliation and production IdP binding remain uncertified. | `contracts/idea-proposal-intake/lotus-advise-idea-proposal-intake.v1.json`, `docs/architecture/idea-conversion-realization.md`, API/domain/PostgreSQL integration tests, migration and recovery gates. |
| Proposal decision vocabulary contract | Supported as a versioned Advise-owned contract for decision-status, reviewed top-level-status compatibility declarations, recommended-action, runtime-checked workflow-gate, and gate-next-step pairings. | `docs/standards/proposal-decision-vocabulary.v1.json`, `make proposal-decision-vocabulary-gate`, and focused contract tests. |
| Advisory workspace | Supported for draft, save, resume, compare, rationale, and lifecycle handoff flows with Postgres-backed workspace session and saved-version state in production runtime. | Workspace API, engine, repository, migration, and runtime persistence tests. |
| Proposal narrative evidence | Supported for advisor-review posture, review/replay, report-package propagation, report/render/archive lineage, Gateway/Workbench exposure, and data-product/trust posture. | RFC-0023 contract tests and supported-feature wiki truth. |
| Proposal memo evidence | Supported for advisor-use memo posture, review-gated AI commentary, report/render/archive lineage, Gateway/Workbench exposure, and evidence-pack data-product posture. | RFC-0024 contract tests, commercial guide, and supported-feature wiki truth. |
| Policy-pack evidence | Supported for policy-pack catalog, evaluation records, workflow/sign-off posture, source-owned as-of and trusted scope receipt identity, report-package lineage, bounded AI evidence, Gateway/Workbench exposure, and active data-product posture. Production IdP binding remains a separate gated control. | RFC-0025 contract tests, RFC-0002 producer receipt tests, commercial guide, and trust telemetry validation. |
| Advisor cockpit | Supported for source-owned action items, operating snapshots, supportability, acknowledgements, Gateway/Workbench consumption, and canonical proof posture. | RFC-0026 tests and wiki supported-feature matrix. |
| Advisory copilot | Supported for governed evidence packets, approved `lotus-ai` provider/model inventory enforcement, executable evaluation-pack and safety-abuse gates, AI data-boundary minimization, runtime budget enforcement, claim-level source grounding, structured guardrails, workflow-pack integration, trusted-principal run review, maker-checker audit, retention, certified APIs, and product-realization proof. Unknown, retired, mismatched, or environment-incompatible model identity returns unavailable; failed evaluation, unsafe source evidence, unsafe output, budget exhaustion, unsupported, unclassified data, or unverifiable AI claims remain not review-ready, and request-body actor fields cannot authorize review actions. | RFC-0027 tests, model-governance/evaluation/safety/data-boundary/runtime-budget tests, and API contract evidence. |
| Proposal async operation controls | Supported as an internal control-plane decision boundary for bounded pending/leased/stuck/retry-exhausted/quarantined operation lists, authorized retry/quarantine/dry-run/pause-drain decisions, idempotent quarantine projection, and sanitized audit evidence. No arbitrary payload mutation, SQL access, or lifecycle bypass is supported. | `src/core/proposals/async_operation_control_plane.py`, focused control-plane tests, and operations runbook. |
| Advisory record lifecycle | Supported for record-family retention classification, legal-hold audit events, append-only correction posture, authorized purge decisioning, dependency refusal, tombstone audit evidence, and sanitized subject/record hashes. Jurisdiction-specific retention durations remain policy-input configuration, not application constants. | `src/core/record_lifecycle/`, lifecycle tests, data-governance inventory, and operations runbook. |
| Durable state recovery | Supported for service-owned recovery-scope declaration, RTO/RPO alignment, namespace backup/restore inventory, replay quarantine rules, non-production drill evidence shape, and CI validation against checked-in migration namespaces. Backup vendor, PITR execution, and bank DR certification remain platform/environment responsibilities. | `docs/standards/advisory-durable-state-recovery.v1.json`, `make durable-state-recovery-gate`, and operations runbook. |
| Bank-demo proof | Supported for scenario contract, supported-claim register, sanitized proof-pack capture, commercial material pack, Gateway/Workbench proof surface, and blocked-claim governance. | RFC-0028 tests, `wiki/Demo-Readiness-Guide.md`, and `docs/commercial/RFC-0028-bank-demo-client-proof-materials.md`. |
| API governance | Enforced for OpenAPI quality, no-alias behavior, API vocabulary, producer-owned proposal decision vocabulary, domain data products, trust telemetry freshness, advisory data-lifecycle inventory, architecture boundaries, complexity and oversized-code regression, high-severity security findings, dependency-lock evidence, and license/IP release evidence. | `make check`, `make proposal-decision-vocabulary-gate`, `make advisory-data-lifecycle-gate`, `make trust-telemetry-freshness-gate`, `make oversized-code-gate`, `make dependency-lock-gate`, `make license-ip-gate`, Feature Lane, PR Merge Gate, Main Releasability. |

## Explicit Boundaries

- No claim of final client-ready publication approval.
- No claim of legal, regulatory, compliance, or bank certification signoff.
- No claim of OMS/order/fill/settlement support unless separately implemented and proven.
- No claim that Workbench reconstructs advisory, suitability, memo, policy, narrative, or AI
  semantics locally; it consumes governed Gateway/Advise contracts.
- No claim that AI approves recommendations, policy posture, sign-off, or client communication.
- Quality baseline reports are evidence for progressive hardening, not final production readiness.

## How To Use This Page

- Business and demo reviewers should start with the supported and blocked capability families.
- Sales and pre-sales should use the commercial guide for exact wording.
- Operations should use the wiki runbook and proof-pack stop conditions before playback.
- Engineers should use the linked RFCs, route docs, and repo-native gates before changing support
  posture.
