# API Surface

## Current Scope

Current scope: this page summarizes the implementation-backed `lotus-advise` API route families,
the contract rules that are easy to misuse, and the evidence boundaries that consumers must
preserve. OpenAPI, API vocabulary, source-reference, and wiki checks back the page; unsupported
client-ready publication, external client communication, OMS/order lifecycle, and bank attestation
claims remain out of scope.

## Reader Map

| Reader | Start here | Evidence posture |
| --- | --- | --- |
| API consumers | Route family sections below | Use the listed Advise contracts through Gateway/Workbench where applicable. |
| Operators | Contract Notes and readiness/capability bullets | Use `/health/ready` for local runtime readiness and `/platform/capabilities` for workflow dependency posture. |
| Reviewers | Advisory copilot, policy, memo, and bank-demo notes | Claims are bounded by persisted evidence, review posture, and supported-feature proof. |
| Future agents | Contract Notes | Preserve source-owned semantics and do not infer unsupported capability from route existence. |

## Health

- `GET /health`
- `GET /health/live`
- `GET /health/ready`

## Advisory Simulation

- `POST /advisory/proposals/simulate`
- `POST /advisory/proposals/artifact`

These endpoints accept normalized advisory input contracts and require `Idempotency-Key`. They are the core deterministic simulation and artifact entry points.

## Advisory Proposal Lifecycle

- `POST /advisory/proposals`
- `POST /advisory/proposals/idea-intake`
- `GET /advisory/proposals`
- `GET /advisory/proposals/{proposal_id}`
- `GET /advisory/proposals/{proposal_id}/versions/{version_no}`
- `POST /advisory/proposals/{proposal_id}/versions`
- `GET /advisory/proposals/{proposal_id}/versions/{version_no}/narrative`
- `POST /advisory/proposals/{proposal_id}/versions/{version_no}/narrative/regenerate`
- `POST /advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review`
- `POST /advisory/proposals/{proposal_id}/transitions`
- `POST /advisory/proposals/{proposal_id}/approvals`
- `POST /advisory/proposals/{proposal_id}/report-requests`
- `POST /advisory/proposals/{proposal_id}/execution-handoffs`
- `POST /advisory/proposals/{proposal_id}/execution-updates`

Report requests support `include_reviewed_narrative=true` for RFC-0023 advisor-review narrative
package propagation. The request is blocked unless the selected immutable proposal version has a
persisted narrative, an `APPROVED_FOR_ADVISOR_USE` review, and matching source narrative hash.
Standalone narrative read returns exact persisted advisor-review narrative and latest review
posture. Standalone regeneration returns a non-persisted, review-required advisor-review candidate
from immutable version evidence and does not mutate proposal truth or publish client-ready
commentary.
Delivery evidence records the compact narrative package summary. `lotus-report` now consumes and
snapshots the reviewed package, and `lotus-render` renders it as an optional advisor-use
portfolio-review advisory narrative page. `lotus-archive` stores a support-safe archive metadata
summary for rendered advisor-use portfolio-review artifacts with approved review posture and source
hash lineage. `lotus-gateway` exposes product-facing reviewed-narrative posture from these
canonical advisory routes, and `lotus-workbench` renders the Gateway-backed advisor-use proposal
narrative posture. Client-ready publication remains gated.

`POST /advisory/proposals/idea-intake` is a source-safe executable intake receipt for `lotus-idea`
conversion-intent handoff. It returns HTTP 202 with accepted, replayed, or rejected receipt posture,
requires `Idempotency-Key`, and derives bounded trusted scope from local/dev caller headers. It
persists the scoped intake idempotency decision through the proposal repository so replay and
conflict behavior survive restart, and detects changed-payload replay with HTTP 409. The replay
window is 24 hours: expired unheld claims are purged in target-prioritized batches of at most 128
before a new claim, with sanitized append-only purge evidence written in the same transaction.
Legal hold prevents purge and preserves replay/conflict protection. It does not
create advisory review work or proposal lifecycle records, publish a source-owned business outcome,
run suitability, grant advisory approval, create orders, authorize client publication, bind
production IdP claims, certify a data product, or promote a supported feature.

## Advisory Operations And Support

- `GET /advisory/proposals/{proposal_id}/delivery-summary`
- `GET /advisory/proposals/{proposal_id}/delivery-events`
- `GET /advisory/proposals/{proposal_id}/execution-status`

These support surfaces derive operator-facing posture from append-only workflow history.
Execution handoff, execution-status, delivery-summary, and delivery-history payloads include
structured ownership-boundary evidence so operators can see that `lotus-advise` records advisory
handoff and status posture while the downstream execution provider remains the execution system of
record.

## Advisory Workspace

- `POST /advisory/workspaces`
- `GET /advisory/workspaces/{workspace_id}`
- `POST /advisory/workspaces/{workspace_id}/draft-actions`
- `POST /advisory/workspaces/{workspace_id}/evaluate`
- `POST /advisory/workspaces/{workspace_id}/save`
- `GET /advisory/workspaces/{workspace_id}/saved-versions`
- `GET /advisory/workspaces/{workspace_id}/saved-versions/{workspace_version_id}/replay-evidence`
- `POST /advisory/workspaces/{workspace_id}/resume`
- `POST /advisory/workspaces/{workspace_id}/compare`
- `POST /advisory/workspaces/{workspace_id}/assistant/rationale`
- `POST /advisory/workspaces/{workspace_id}/handoff`

## Tactical House View

- `POST /advisory/tactical-house-view/cohorts/evaluate`

This endpoint returns `TacticalHouseViewAffectedCohort:v1` for a governed bank-authored tactical
house-view instruction and caller-supplied source-backed candidate portfolios. It does not discover
the global portfolio universe, create rebalance waves, approve trades, or integrate with OMS.

## Advisor Cockpit

- `GET /advisory/cockpit/actions`
- `GET /advisory/cockpit/actions/{action_item_id}`
- `POST /advisory/cockpit/actions/{action_item_id}/acknowledgements`
- `GET /advisory/cockpit/snapshot`
- `GET /advisory/cockpit/supportability`

These RFC-0026 endpoints expose source-owned advisor operating workflow evidence for action items,
daily snapshot posture, supportability, and durable acknowledgement replay. Responses preserve
source refs, action reason codes, SLA posture, acknowledgement lineage, and unsupported-claim
boundaries. Caller role, advisor scope, and portfolio scope come from trusted gateway/service
headers; `role` and `advisor_id` query parameters are not authorization inputs. Acknowledgements
are advisor workflow evidence only: they do not approve policy, clear blockers, contact clients,
create CRM tasks, or initiate OMS activity.

## Bank Demo Proof

- `GET /advisory/bank-demo-proof/scenario-contract`
- `GET /advisory/bank-demo-proof/supported-claim-register`
- `POST /advisory/bank-demo-proof/proof-packs`

These RFC-0028 endpoints expose the Advise-owned bank-demo proof contract for Gateway and Workbench
product consumption. The scenario contract fixes the canonical `PB_SG_GLOBAL_BAL_001` journey,
the supported-claim register maps each demo/RFP claim to implementation evidence, and proof-pack
capture writes sanitized runtime posture for repeatable validation.

`POST /advisory/bank-demo-proof/proof-packs` must fail with HTTP 409 when material proof fields
drift from the supported-claim register. Runtime posture rejects runtime base URLs that carry
credentials, query strings, or fragments; proof artifact refs reject URL/query/fragment/traversal
and sensitive credential, AI-input, or runtime-payload material; HTTP 422 validation responses do
not echo rejected sensitive input; summaries redact credential, AI-input, runtime-payload, trace,
and correlation material; endpoint evidence records bounded integer `latency_ms` values.

The proof APIs do not approve client-ready publication, external client communication,
bank-specific attestations, legal/regulatory advice, completed sign-off/approval, or
OMS/order/fill/settlement. Gateway and Workbench must consume this source-owned contract rather
than reconstructing advisory suitability, memo, narrative, policy, or proof semantics locally.

## Contract Notes

- OpenAPI is the governed external contract.
- Swagger display enrichment may improve readability, but generated summaries, descriptions,
  inferred tags, and generic default errors do not satisfy the OpenAPI quality gate for public
  routes. Route owners must author public summaries, descriptions, tags, and response metadata in
  source.
- Generated API vocabulary is a governed consumer artifact. It must not publish placeholder-shaped
  examples such as `sample_text`, `sample_key`, `STANDARD_TEXT`, `STANDARD_ITEM`, `ENTITY_001`, or
  `example_*`; examples must be source-authored or derived from the deterministic domain fallback
  policy used by `make api-vocabulary-gate`.
- `POST /advisory/policy-evaluations/{evaluation_id}/events` is a review-event command only.
  Sign-off, report/archive, AI-evidence, and finalization events are owned by their specialized
  workflow, report-package, AI-evidence, and finalize commands and must not be manufactured through
  the generic event API.
- Policy-control write routes require a trusted Advise principal at the API boundary. Validation,
  activation, finalization, review-event, sign-off, report-package, and AI-evidence commands use
  `X-Actor-Id`, `X-Role`, `X-Tenant-Id`, `X-Legal-Entity-Code`, `X-Correlation-Id`, service
  identity, `X-Capabilities`, and, for evaluation-scoped writes, authorized proposal and portfolio
  headers. Body actor fields such as `requested_by`, `activated_by`, `created_by`, and `actor_id`
  are compatibility echoes; mismatch returns stable 403 policy-control errors and no state
  mutation.
- Policy-evaluation workflow responses expose `metadata.as_of_date`, `metadata.scope_identity`, and
  replay metadata from the Advise-produced receipt identity. The as-of date must come from explicit
  source evidence, not request dates or clocks. Tenant, service, observed correlation, and observed
  trace identity are published as source-safe hashes; legal entity, booking center, proposal,
  version, and portfolio identity remain visible business scope so downstream consumers can detect
  mismatch without treating local/dev headers as production identity-provider claims.
- Advisory copilot run output includes bounded claim-grounding posture in persisted output sections
  and lineage. Completed provider output remains review-ready only when every claim cites source
  refs from the input evidence packet and aligns to the output section; missing, duplicate,
  unknown, or mismatched citations are exposed as unsupported or unverifiable review posture.
- Advisory copilot Lotus AI output also requires approved provider/model lineage from
  `contracts/advisory-copilot/approved-model-inventory.v1.json`. Unknown, retired, mismatched, or
  environment-incompatible model identity returns unavailable before completed output sections are
  accepted, and persisted run lineage includes model approval, evaluation, release, change, and
  rollback references.
- Advisory copilot completed output also records executable evaluation-pack evidence from
  `src/core/advisory_copilot/evaluation_gate.py` and
  `contracts/advisory-copilot/evaluation-corpus.v1.json`. Failed evaluation posture prevents
  review-ready output and records evaluator version, dataset id, thresholds, metrics, failure
  reasons, and evaluation hash in lineage.
- Advisory copilot safety-abuse posture is executable through
  `src/core/advisory_copilot/guardrails.py` and
  `contracts/advisory-copilot/safety-abuse-corpus.v1.json`. Unsafe user instruction, source
  evidence, or generated output returns stable guardrail reason codes before output is persisted or
  exposed as review-ready.
- Advisory copilot AI data-boundary posture is governed by
  `contracts/advisory-copilot/ai-data-boundary.v1.json`. Outbound Lotus AI payloads use tokenized
  portfolio/proposal/source identifiers and carry provider no-training, retention, residency, and
  deletion controls; context source refs remain available for claim grounding.
- Advisory copilot runtime-budget posture is governed by
  `contracts/advisory-copilot/runtime-budget.v1.json`. Advise enforces input/output payload,
  token-estimate, timeout, bounded retry, per-process concurrency, and cost-budget controls before
  output can become review-ready. Retryable transport failures are capped; provider status and
  validation errors do not retry. Budget exhaustion returns stable unavailable posture with bounded
  lineage telemetry for operator diagnostics.
- Advisory copilot review routes require a trusted reviewer principal at the API boundary.
  `X-Actor-Id`, `X-Role`, `X-Tenant-Id`, `X-Legal-Entity-Code`, `X-Correlation-Id`, service
  identity, `X-Capabilities`, and authorized proposal/portfolio headers drive authority,
  maker-checker, audit metadata, and idempotency. Body `actor_id` is a compatibility echo only and
  cannot grant or widen review authority.
- `contracts/idea-proposal-intake/lotus-advise-idea-proposal-intake.v1.json` is the current
  source-safe `lotus-idea` proposal-intake contract. Its supportability status is
  `not_certified`, and remaining blockers include Advise suitability authority and client
  publication authority.
- REST remains the current contract posture; this service does not justify gRPC today.
- Lifecycle and support routes can be feature-gated by runtime flags.
- Tactical house-view cohorts preserve source refs and supportability posture rather than
  recalculating source-owned portfolio facts locally.
- `GET /health/ready` is the local runtime readiness gate for process traffic: configured
  integration runtime settings, advisory persistence, proposal repository boot posture, and async
  recovery readiness. It does not probe upstream dependency health.
- Upstream dependency and workflow readiness live in `GET /platform/capabilities`; missing
  `lotus-core`, degraded `lotus-risk`, unavailable `lotus-report`, unavailable `lotus-ai`, or
  readiness-only `lotus-performance` posture must degrade the relevant dependency, feature, and
  workflow evidence there before any demo, RFP, release, or workflow claim is made.
- Feature records carry `dependency_keys` for every material upstream dependency that affects
  feature-level operational readiness. A degraded enabled feature is release-acceptable only when
  it carries explicit dependency lineage and a bounded `degraded_reason`; unexplained unready
  feature posture remains a certification failure.
- Capability publication is deployment-scoped and informational. The response carries
  `publication_scope=deployment`, `tenant_policy_evaluated=false`, and a fixed
  `tenant_id=deployment-wide` compatibility marker; arbitrary `tenant_id` query values are not
  documented, trusted, echoed, or used for entitlement decisions.
- `GET /platform/capabilities` includes `advise.observability.advisory_supportability`,
  `advisory.proposals.reviewed_narrative_evidence`, and the
  `advisory_proposal_reviewed_narrative_evidence` workflow for advisor-review narrative evidence.
  The capability wording remains bounded: compliance-review, client-draft, client-ready
  publication, and client communication are not promoted. Canonical Workbench proof is now covered
  by the live runtime suite and the governed `proposal.narrative_posture` panel proof rather than
  by `/platform/capabilities`.
- `GET /platform/capabilities` includes `advisory.proposals.memo_evidence_pack` and
  `advisory_proposal_memo_evidence_pack` for RFC-0024 advisor-use memo evidence. The workflow
  depends on lifecycle, reporting, and `lotus-report` readiness, and it does not promote
  client-ready memo publication, external client communication, or full bank-demo/RFP package
  claims.
- `GET /platform/capabilities` includes `advisory.advisor_cockpit` and
  `advisor_cockpit_operating_workflow` for RFC-0026 advisor cockpit evidence after
  Advise, Gateway, Workbench, and canonical `PB_SG_GLOBAL_BAL_001` proof. The wording remains
  bounded to advisor operating workflow evidence and does not promote client-ready publication,
  external client communication, CRM system-of-record behavior, OMS lifecycle, completed policy
  approval authority, or full RFC-0028 demo/RFP package claims.
- RFC-0028 bank-demo proof is exposed through `/advisory/bank-demo-proof/*`, not through a
  generic capability toggle. Supported demo claims must be backed by the supported-claim register,
  proof-pack evidence, and runtime posture artifacts before they are reused in demo, RFP, security,
  or commercial material.
- `GET /platform/capabilities` also includes a bounded `supportability` summary for advisory
  readiness, degraded dependency posture, and lifecycle-disabled posture. The
  `supportability.metric_labels` field documents the exact bounded label tuple for
  `lotus_advise_advisory_supportability_total`.
- Dependency readiness entries include `runtime_probe_enabled`, `readiness_basis`, and
  `degraded_reason` so operators can distinguish missing configuration, configuration-only
  non-production posture, successful runtime probes, and failed runtime probes without exposing
  dependency base URLs.
- Execution posture entries include `execution_ownership` evidence with advisory role,
  downstream system-of-record, and ownership-boundary labels for audit, support, and pre-sales
  explanation.
