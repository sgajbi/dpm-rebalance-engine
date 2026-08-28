# RFC Index

## Current Scope

Current scope: this page is the reader map for repository-local Advise RFC truth. It distinguishes
implemented advisory backbone, active future work, crown-jewel implementation posture, and
historical slice evidence. The evidence posture is repository RFC source, supported-feature truth,
tests, and linked proof artifacts; target-state roadmap text below must not be read as current
client-ready, external communication, OMS/order lifecycle, or bank-attestation support.

## Reader Map

| Reader | Start here | Decision supported |
| --- | --- | --- |
| Product or demo reviewer | Important Interpretation | Which implemented RFCs can be discussed and which claims remain gated. |
| Engineer or future agent | Active Implemented Backbone and detailed RFC sections | Which RFC owns a behavior before changing code or docs. |
| Operations/support | Crown-jewel RFC summaries and closure notes | Which evidence, lineage, replay, and supportability surfaces are current. |
| Platform reviewer | RFC links and data-product references | Which repo-local truth should align with platform governance. |

## Governing Rule

Service-specific implementation RFCs live in this repository. Cross-cutting or multi-service RFCs
belong in `lotus-platform`.

## Active Implemented Backbone

The current implemented advisory backbone is anchored by:

- RFC-0003 advisory proposal workflow coverage hardening
- RFC-0004 iterative advisory proposal workspace contract
- RFC-0005 advisory PostgreSQL runtime and persistence cutover
- RFC-0006 target operating model and integration architecture
- RFC-0007 proposal simulation MVP
- RFC-0008 proposal auto-funding
- RFC-0009 drift analytics
- RFC-0010 suitability scanner v1
- RFC-0011 proposal artifact
- RFC-0012 workflow gates and next-step semantics
- RFC-0013 persistence, workflow lifecycle, and audit model
- RFC-0019 authoritative context, durable runtime, and workspace closure
- RFC-0020 canonical allocation and risk-lens convergence
- RFC-0021 proposal decision summary and enterprise suitability policy
- RFC-0022 proposal alternatives and portfolio construction workbench

## Active Future Work

The repository RFC index currently keeps these as active future work:

- RFC-0014 data quality, snapshots, and replayability
- RFC-0015 jurisdiction and policy packs
- RFC-0016 costs, fees, and transaction frictions
- RFC-0017 execution integration interface
- RFC-0018 monitoring, surveillance, and post-trade controls

## Important Interpretation

RFC-0023 through RFC-0028 are the crown-jewel advisory roadmap. RFC-0023 is implemented for
governed advisor-review proposal narrative evidence and defines the grounded narrative prerequisite
consumed by proposal memo, policy, cockpit, copilot, and demo work. RFC-0024 is implemented for
advisor-use proposal memo evidence and remains the bounded memo source of truth; client-ready memo
publication and external client communication remain gated; RFC-0028 governs bank-demo/RFP proof
through supported claims. RFC-0025 is
implemented for advisor/compliance policy evaluation evidence and remains bounded to policy
evidence, review posture, report-package lineage, bounded AI evidence, Gateway/Workbench exposure,
and active `AdvisoryPolicyEvaluationRecord:v1` data-product support. Completed approval/waiver
authority, completed sign-off authority, client-ready policy publication, external client
communication remain gated; RFC-0028 governs bank-demo/RFP proof through supported claims.

RFC-0026 is implemented for the source-owned advisor cockpit operating workflow. Advise
owns action, snapshot, supportability, preparation-packet, supervisory queue, report/readiness,
execution-status attention, house-view impact, and acknowledgement truth; Gateway and Workbench
consume the canonical contract; active cockpit data products, trust telemetry, and
`/platform/capabilities` are promoted. Slice 16 adds hardened live canonical proof for action
detail, cursor pagination, invalid-cursor rejection, compliance and discretionary
portfolio-management role projection, preparation packets, house-view impact, acknowledgement
idempotency, supportability posture, and action evidence/lineage.

RFC-0027 is implemented for governed internal advisor/reviewer copilot interactions. It supports
all six supported action families through Advise-owned source evidence, governed `lotus-ai`
workflow-pack execution, claim-level source grounding, Gateway publication, Workbench Gateway-first
rendering, canonical `RFC27_ADVISORY_COPILOT_CANONICAL` proof, and active
`AdvisoryCopilotInteractionRecord:v1` data-product posture. Evidence packets and review events are
audit records inside the interaction product boundary rather than standalone promoted data
products. Client-ready publication, external client communication, policy approval/sign-off
authority, OMS order lifecycle, fills, and settlement remain gated. RFC-0028 governs bank-demo/RFP
proof through supported claims rather than RFC-0027 runtime authority.

RFC-0028 is implemented for repeatable bank-demo proof and claim-controlled commercial material.
Slice 0 locks the
hybrid Advise proof API plus platform/front-office automation path for scenario
`RFC28_BANK_DEMO_CLIENT_READY_PROOF_CANONICAL`, portfolio `PB_SG_GLOBAL_BAL_001`, and proof marker
`BANK_DEMO_PROOF_PACK_CREATED`. Slice 1 merged the reusable `lotus-platform` supported-claim
register schema and validator through PR #366, with main releasability run `26554797152` green.
Slices 2-5 add durable index cleanup, no-premature data-product promotion guards, core
proof/claim/scenario models, and repeatable backend proof capture through
`scripts/capture_rfc0028_backend_proof.py` with sanitized `output/rfc0028/backend-proof` artifacts
and material-field review. Slice 6 adds `AdvisoryDocumentProofSummary:v1`, live-suite document
proof fields, and `document-proof-summary.json` for advisor-use memo/policy report-render-archive
posture while client-ready document publication remains blocked. Slice 7A exposes source-owned
Advise proof APIs for the scenario contract, supported-claim register, and sanitized proof-pack
capture with HTTP 409 material-drift rejection. Slice 7B closes Gateway publication through
`lotus-gateway` PR #252 at `f99ca1dfe074b57c99793ab1ca86542869d579a4`, with Gateway Main
Releasability Gate run `26559811341` green and wiki publish commit `a73cd24`. Slice 8 closes
Workbench proof through `lotus-workbench` PR #384 and `lotus-platform` PR #367: canonical
validation for `PB_SG_GLOBAL_BAL_001` proves `advisory.bank_demo_proof`, screenshot
`advisory-bank-demo-proof-live.png`, and blocked client-ready publication posture through
Gateway/BFF. Slice 9 adds Advise-owned `AdvisoryJourneyIntegrationProofSummary:v1`,
`journey-integration-proof-summary.json`, governed panel ids, proof marker
`RFC0028_JOURNEY_INTEGRATION_PROOF_CREATED`, and supported claim
`ai_policy_cockpit_proof_integrated` for AI/model-risk, policy, and advisor-cockpit proof
boundaries without promoting AI authority, legal advice, policy approval, client-ready
publication, RFP/security, product one-pager, ROI, external client communication, or
OMS/order/fill/settlement claims. Slice 10 adds Advise-owned
`AdvisoryCommercialMaterialPack:v1`, `commercial-material-pack.json`, proof marker
`RFC0028_COMMERCIAL_MATERIAL_PACK_CREATED`, and supported claim
`commercial_rfp_security_material_available` for the claim-controlled product one-pager, RFP
response, security posture, architecture, ROI, demo, feature-matrix, proof-guide, boundary, and
operator material in `docs/commercial/RFC-0028-bank-demo-client-proof-materials.md`. Client-ready
publication, external client communication, bank-specific attestations, legal/regulatory advice,
completed sign-off/approval, OMS/order/fill/settlement, and LinkedIn post-completion output remain
unpromoted until separately implementation-backed and reviewed. Slice 11 adds
`src/core/bank_demo_proof/runtime_posture.py`, bounded `latency_ms`, runtime base-URL
credential/query/fragment rejection, sensitive summary redaction, and proof marker
`RFC0028_RUNTIME_SECURITY_POSTURE_HARDENED` so runtime proof artifacts carry sanitized
security/latency posture without leaking credential, AI-input, runtime-payload, trace, or
correlation material. Slice 12 updates README and wiki product truth for the source-owned proof
APIs, runtime posture artifacts, repeatable capture commands, commercial proof-guide navigation,
HTTP 409 material-drift handling, and blocked client-ready publication plus OMS/order/fill/settlement
boundaries. Slice 13/14 close implementation proof and final hardening through PR #213,
`src/core/bank_demo_proof/artifact_refs.py`, local artifact-reference normalization, safe HTTP 422
validation error responses that do not echo rejected sensitive input, targeted proof tests,
`make check`, PR Merge Gate, and Main Releasability Gate run `26573760885` on merge
`a99474e5457dcdd4c87e79faf83bc8f64580544b`. Slice 15/16 close durable
docs/context/wiki/supported-features truth and post-completion communication through
`lotus-platform` PR #369 at `26d74e65e231ac3d62457187c6eb7f787a4d9f88`, Main Releasability
Gate run `26574820026`, and
`lotus-platform/thought-leadership/linkedin/drafts/LI-2026-05-28-043-demo-proof-should-show-the-boundary.md`.
Client-ready publication, external client communication, bank-specific attestations,
legal/regulatory advice, completed sign-off/approval, and OMS/order/fill/settlement remain
unpromoted.

## Implementation slices by RFC

Per-slice implementation status, grouped by RFC. The summaries above say what each RFC
delivers; these say which slices are implemented and what evidence backs them.

### RFC-0027

RFC-0027 Slice 1 is implemented as platform automation and scaffolding review. Evidence lives in
`docs/rfcs/RFC-0027-slice-1-platform-automation-and-scaffolding-review.md`. Existing platform and
repo-native controls are sufficient before copilot domain work, so no `lotus-platform` code change
is required for this slice. Copilot APIs, evidence-packet persistence, guardrails, `lotus-ai`
workflow-pack integration, review actions, data-product promotion, Gateway routes, Workbench
surfaces, canonical RFC-0027 seed data, and client-demo claims remain mandatory subsequent RFC-0027
work and are unpromoted in this slice.

RFC-0027 Slice 2 is implemented as cleanup and structure. Evidence lives in
`docs/rfcs/RFC-0027-slice-2-cleanup-and-structure.md`. `lotus-advise` now has a dedicated
`src/core/advisory_copilot/` package for supported copilot action catalog, source/evidence
vocabulary, guardrail reason-code foundation, review posture mapping, workflow-pack boundary
metadata, and business-facing projection labels. No copilot API, persistence, `lotus-ai`
invocation, data product, Gateway route, Workbench surface, canonical seed, or supported runtime
claim is promoted by this slice.

RFC-0027 Slice 3 is implemented as non-promoting data-product posture. Evidence lives in
`docs/rfcs/RFC-0027-slice-3-data-product-and-platform-hardening.md`. The slice blocks premature
`AdvisoryCopilotInteractionRecord:v1`, `AdvisoryCopilotEvidencePacket:v1`, and
`AdvisoryCopilotReviewRecord:v1` declarations, trust telemetry, and `/platform/capabilities`
promotion until copilot runtime APIs, persistence, Gateway/Workbench consumption, mesh posture, and
canonical proof exist.

RFC-0027 Slice 4 is implemented as pure domain model, vocabulary, and review-state hardening.
Evidence lives in `docs/rfcs/RFC-0027-slice-4-domain-model-vocabulary-review-state.md`. The
copilot core now defines evidence packets, evidence sections, source refs, lineage refs,
unsupported-evidence posture, retention classes, and review-state mapping while preserving blocked
client-ready posture and no runtime/API promotion.

RFC-0027 Slice 5 is implemented as pure evidence-packet projection. Evidence lives in
`docs/rfcs/RFC-0027-slice-5-evidence-packet-redaction-projection.md`. The copilot core now builds
deterministic projected evidence packets from already source-projected sections, emits explicit
missing/restricted unsupported posture, preserves source refs and lineage refs, computes stable
packet hashes, rejects technical-copy leakage, and keeps client-ready publication blocked. No source
reads, persistence, API, `lotus-ai`, Gateway, Workbench, data-product, canonical seed, or supported
runtime claim is promoted by this slice.

RFC-0027 Slice 6 is implemented as a pure guardrail and unsupported-evidence engine foundation.
Evidence lives in `docs/rfcs/RFC-0027-slice-6-guardrail-unsupported-evidence-engine.md`. The
copilot core now returns stable reason codes for forbidden intents, missing source refs, prompt
injection, client-ready wording, and sensitive technical leakage. Persistence, API, `lotus-ai`,
Gateway, Workbench, canonical proof, and supported runtime claims remain unpromoted.

RFC-0027 Slice 7 is implemented as a governed `lotus-ai` workflow-pack and model-risk control boundary.
Evidence lives in `docs/rfcs/RFC-0027-slice-7-lotus-ai-workflow-pack-model-risk-controls.md`.
`lotus-ai` now registers six review-gated advisory copilot workflow packs, and `lotus-advise`
consumes them only through `/platform/workflow-packs/execute` with evidence-packet, source-ref,
approved-instruction-set, output-schema, prompt-template, evaluation-pack, unavailable, and
guardrail proof. Advise copilot APIs, persistence, Gateway, Workbench, canonical proof,
data-product promotion, and supported runtime claims remain unpromoted.

RFC-0027 Slice 8 is implemented as copilot run persistence, review audit, and retention
foundation. Evidence lives in
`docs/rfcs/RFC-0027-slice-8-copilot-run-review-audit-retention.md`. `lotus-advise` now has durable
run, idempotency, review, audit, retention, legal-hold, and Postgres migration support for governed
copilot records. The persistence layer rejects unredacted AI input, provider output, and unsafe
output storage.
Advise copilot APIs, Gateway, Workbench, canonical proof, data-product promotion, and supported
runtime claims remain unpromoted.

RFC-0027 Slice 9 is implemented as certified Advise advisory copilot APIs and OpenAPI coverage.
Evidence lives in `docs/rfcs/RFC-0027-slice-9-certified-advise-apis-openapi.md`. `lotus-advise`
now exposes evidence-packet create/read, Workbench-safe proposal-version source projection, action
run/read, review, supportability, and proposal-version run lookup endpoints with no free-form
prompt endpoint. Its Workbench, canonical proof, data-product promotion, and supported runtime
claim boundary is historical and closed by the final RFC-0027 slices.

RFC-0027 Slices 10-14 are implemented as Gateway/Workbench product realization, canonical proof,
data-mesh promotion, repeatability hardening, and closure. Evidence lives in
`docs/rfcs/RFC-0027-slice-10-14-product-realization-proof-closure.md`. Canonical validation records
`ADVISORY_COPILOT_CANONICAL_PROOF_CREATED`, proves all six supported action families, internal
review, client-ready guardrail rejection, proposal-version run lineage, and the
`advisory.advisory_copilot` Workbench panel. `AdvisoryCopilotInteractionRecord:v1` is active with
trust telemetry; standalone evidence-packet and review-record products are not promoted.

### RFC-0026

RFC-0026 Slice 1 is implemented as platform automation and scaffolding review. Evidence lives in
`docs/rfcs/RFC-0026-slice-1-platform-automation-and-scaffolding-review.md`. Existing platform and
repo-native controls are sufficient before cockpit domain work, so no `lotus-platform` code change
is required for this slice. Cockpit APIs, action-item persistence, acknowledgement writes, data
products, Gateway routes, Workbench surfaces, canonical RFC-0026 seed data, and client-demo claims
remain mandatory subsequent RFC-0026 work and are unpromoted in this slice.

RFC-0026 Slice 2 is implemented as cleanup and structure. Evidence lives in
`docs/rfcs/RFC-0026-slice-2-cleanup-and-structure.md`. `lotus-advise` now has a dedicated
`src/core/advisor_cockpit/` package for typed cockpit models, vocabulary, deterministic action
ordering, and pagination defaults. No cockpit API, data product, Gateway route, Workbench surface,
canonical seed, or supported runtime claim is promoted by this slice.

RFC-0026 Slice 3 is implemented as non-promoting data-product posture. Evidence lives in
`docs/rfcs/RFC-0026-slice-3-data-product-and-platform-hardening.md`. The slice blocks premature
`AdvisorCockpitOperatingSnapshot:v1` and `AdvisoryActionItemRegister:v1` declarations, trust
telemetry, and `/platform/capabilities` promotion until cockpit runtime APIs, Gateway/Workbench
consumption, mesh posture, and canonical proof exist.

RFC-0026 Slice 4 is implemented as source-backed cockpit action construction. Evidence lives in
`docs/rfcs/RFC-0026-slice-4-cockpit-domain-model-and-vocabulary.md`.
`src/core/advisor_cockpit/action_sources.py` owns the source DTOs and
`src/core/advisor_cockpit/action_factory.py` centralizes Advise-owned action construction for
policy review, memo blockers, meeting preparation, source supportability, and unsupported
capabilities, with behavior tests that keep source refs, evidence refs, lineage, reason codes,
owner roles, and client-ready blocked posture explicit. Runtime APIs, persistence, data-product
promotion, Gateway routes, Workbench surfaces, and canonical proof remain mandatory subsequent
RFC-0026 slices.

RFC-0026 Slice 5 is implemented as preloaded source-read-model aggregation. Evidence lives in
`docs/rfcs/RFC-0026-slice-5-source-read-model-and-aggregation.md`.
`src/core/advisor_cockpit/source_read_model.py` maps preloaded proposal, policy evaluation, memo,
supportability, and unsupported-capability source batches into source counts, action sources, and
sorted cockpit action items without adding API routes, persistence, Gateway routes, Workbench
surfaces, data-product promotion, or runtime support claims.

RFC-0026 Slice 6 is implemented as deterministic SLA and acknowledgement posture. Evidence lives in
`docs/rfcs/RFC-0026-slice-6-priority-sla-acknowledgement-rules.md`.
`src/core/advisor_cockpit/rules.py` now centralizes SLA age-band derivation, owner-blocking status
checks, and acknowledgement attachment that cannot clear blocking status, priority, or owner role.
Runtime APIs, persistence, Gateway routes, Workbench surfaces, data-product promotion, and
canonical proof remain mandatory subsequent RFC-0026 slices.

RFC-0026 Slice 7 is implemented as Advise-owned cockpit API support. Evidence lives in
`docs/rfcs/RFC-0026-slice-7-certified-advise-apis.md`. `lotus-advise` now exposes cockpit action
list/detail, snapshot, supportability, and idempotent acknowledgement APIs backed by
`AdvisorCockpitService`, `AdvisorCockpitRepository`, OpenAPI tests, and durable acknowledgement
persistence.

RFC-0026 Slice 8 is implemented as source-backed preparation and follow-up support. Evidence lives
in `docs/rfcs/RFC-0026-slice-8-meeting-preparation-client-follow-up.md`. `lotus-advise` now exposes
paginated meeting-preparation packets and advisor follow-up actions without claiming CRM,
calendar, external client communication, or client-ready publication behavior.

RFC-0026 Slice 9 is implemented as source-backed supervisory and approval queue support. Evidence
lives in `docs/rfcs/RFC-0026-slice-9-supervisory-approval-compliance-queues.md`. `lotus-advise`
now projects risk, compliance, and consent queue items through batched approval source reads with
deterministic owner roles and blocked completed-approval/client-ready authority.

RFC-0026 Slice 10 is implemented as source-backed readiness, execution, and house-view action
support. Evidence lives in `docs/rfcs/RFC-0026-slice-10-readiness-execution-house-view.md`.
`lotus-advise` now projects report/archive readiness, execution handoff/status attention, and
explicit source-batched tactical house-view impact actions without claiming report/archive, OMS, or
discretionary portfolio-management system-of-record ownership.

RFC-0026 Slice 13 is implemented as data-product and capability promotion. Evidence lives in
`docs/rfcs/RFC-0026-slice-13-data-product-capability-promotion.md`.
`AdvisorCockpitOperatingSnapshot:v1` and `AdvisoryActionItemRegister:v1` are active products with
trust telemetry, `/platform/capabilities` advertises `advisory.advisor_cockpit` and
`advisor_cockpit_operating_workflow`, and Advise supportability records Gateway support,
Workbench canonical proof, active data-product posture, and canonical
`RFC26_ADVISOR_COCKPIT_POLICY_ACTION_CANONICAL` validation for `PB_SG_GLOBAL_BAL_001`.
Client-ready publication, external client communication, CRM system-of-record behavior,
OMS order lifecycle, and completed policy approval authority remain gated. RFC-0028 governs broader
bank-demo/RFP proof through supported claims.

RFC-0026 Slice 16 is implemented as hardened implementation proof. Evidence lives in
`docs/rfcs/RFC-0026-slice-16-implementation-proof.md`. The governed Workbench live validation now
records `ADVISOR_COCKPIT_ACTION_ACKNOWLEDGED`, `paginationCursor`, `roleProjectionValidated`,
`houseViewCohortId`, preparation-packet counts, `clientReadyPublication: BLOCKED`,
`ADVISE_GATEWAY_WORKBENCH_CANONICAL_PROOF_SUPPORTED`, and
`CANONICAL_WORKBENCH_PROOF_PASSED_RFC0026`. Live defects found in stale image rebuild posture,
portfolio-scoped preparation, memo/report portfolio scoping, and source-backed cockpit lineage were
fixed at the owning layer and pinned by lower-level tests before rerun.

### RFC-0025

RFC-0025 Slice 1 is implemented as platform automation and scaffolding review. Evidence lives in
`docs/rfcs/RFC-0025-slice-1-platform-automation-and-scaffolding-review.md`. Existing platform and
repo-native controls are sufficient before policy domain work, so no `lotus-platform` code change
is required for this slice. Policy-pack catalog APIs, activation, evaluation, persistence, review
queues, report/render/archive sign-off packs, Gateway/Workbench policy surfaces, data-product
promotion, and client-ready publication remain unimplemented and unpromoted.

RFC-0025 Slice 2 is implemented as current-boundary cleanup and structure review. Evidence lives in
`docs/rfcs/RFC-0025-slice-2-cleanup-and-structure-review.md`. The slice centralizes advisory
policy-context status vocabulary/accessors, removes duplicate suitability scanner baseline-pack
wiring, and records that dedicated policy-pack modules must be introduced only when RFC-0025 slices
add real catalog, validation, evaluation, persistence, replay, review, sign-off, report, AI,
Gateway, Workbench, or supportability behavior. No runtime policy-pack capability is promoted.

RFC-0025 Slice 3 is implemented as proposed, blocked data-product posture. Evidence lives in
`docs/rfcs/RFC-0025-slice-3-data-product-and-platform-hardening.md`.
`AdvisoryPolicyEvaluationRecord:v1` now has a repo-native producer declaration and blocked trust
telemetry, while current routes and `/platform/capabilities` policy support remain absent until
runtime policy evaluation, persistence, replay, Gateway/Workbench consumption, and proof are real.

RFC-0025 Slice 4 is implemented as source-readiness-only policy evidence. Evidence lives in
`docs/rfcs/RFC-0025-slice-4-upstream-source-evidence-completion.md`. Proposal evidence bundles now
carry `rfc0025.policy-source-readiness.v1`, separating `lotus-core`, `lotus-risk`, and
`lotus-advise` source responsibilities while keeping policy evaluation, policy APIs,
Gateway/Workbench policy support, and client-ready publication unimplemented and unpromoted.

RFC-0025 Slice 5 is implemented as policy-pack catalog and activation support only. Evidence lives
in `docs/rfcs/RFC-0025-slice-5-policy-pack-catalog-schema-activation.md`. Advise now exposes
catalog list/detail/validate/activate routes for `GLOBAL_PRIVATE_BANKING_BASELINE` and
`SG_PRIVATE_BANKING_REFERENCE`, with schema validation, content hashes, maker-checker activation,
and audit events. Policy evaluation, policy review queues, sign-off packages, Gateway/Workbench
policy consumption, and client-ready publication remain unimplemented and unpromoted.

RFC-0025 Slice 6 is implemented as an internal policy applicability and rule-evaluation engine only.
Evidence lives in `docs/rfcs/RFC-0025-slice-6-policy-applicability-and-evaluation-engine.md`.
Advise can evaluate active policy packs against source-backed proposal evidence and return
material rule posture, source refs, missing evidence, reason codes, and required actions for
source readiness, mandate, product eligibility, complex-product disclosure/consent, best-interest
cost evidence, and conflict/product-document review. Policy evaluation persistence, certified
evaluation APIs, review queues, sign-off packages, Gateway/Workbench policy consumption, and
client-ready publication remain unimplemented and unpromoted.

RFC-0025 Slice 7 is implemented as internal policy evaluation persistence, replay, idempotency, and
audit. Evidence lives in
`docs/rfcs/RFC-0025-slice-7-policy-evaluation-persistence-replay-audit.md`. Advise now persists
finalized policy evaluation records with policy version, policy content hash, source evidence hash,
aggregate evaluation hash, per-rule result hashes, source refs, source gaps, approval
dependencies, disclosure requirements, consent requirements, replay metadata, and append-only
review/sign-off/report-archive events. Certified policy evaluation APIs, policy review queues,
sign-off package realization, Gateway/Workbench policy consumption, active data-product promotion,
and client-ready publication remain unimplemented and unpromoted.

RFC-0025 Slice 8 is implemented as certified Advise policy evaluation APIs and OpenAPI support.
Evidence lives in `docs/rfcs/RFC-0025-slice-8-certified-apis-and-openapi.md`. Advise now exposes
policy evaluation create/replay, immutable read, replay hash comparison, review queue projection,
append-only review/sign-off/report-reference events, lineage, and sign-off source-package routes.
Gateway/Workbench policy consumption, report/render/archive realization, active data-product
promotion, and client-ready publication remain gated.

RFC-0025 Slice 9 is implemented as Advise source policy workflow and sign-off decision support.
Evidence lives in `docs/rfcs/RFC-0025-slice-9-policy-approval-consent-signoff-workflow.md`. Advise
now exposes workflow projection and sign-off decision routes over finalized policy records,
including approval dependencies, disclosure and consent requirements, conflict posture, SLA aging,
maker-checker enforcement, source-hash validation, and append-only sign-off events.
Report/render/archive realization remains gated to Slice 10. Gateway/Workbench policy consumption,
active data-product promotion, and client-ready publication remain gated.

RFC-0025 Slice 10 is implemented as Advise-owned policy report-package realization. Evidence lives
in `docs/rfcs/RFC-0025-slice-10-report-render-archive-realization.md`. Advise now exposes a
signed-off policy evaluation report-package route, submits a typed policy sign-off package to
`lotus-report`, records report/render/archive refs in policy lineage, supports idempotent replay,
and blocks client-ready document generation. Gateway/Workbench policy consumption, live canonical
proof, active data-product promotion, and client-ready publication remain gated.

RFC-0025 Slice 11 is implemented as Advise-owned AI policy-evidence consumption. Evidence lives in
`docs/rfcs/RFC-0025-slice-11-ai-policy-evidence-boundary.md`. Advise now exposes a bounded policy
AI evidence route, sends redacted policy status/rule/workflow/source-ref evidence to
`policy_evidence_summary.pack@v1`, records prompt/output lineage in policy lineage, rejects
forbidden actions, preserves deterministic unavailable posture, requires human review, and blocks
client-ready publication. Active data-product promotion and client-ready publication remain gated.

RFC-0025 Slice 12 is implemented as Gateway and Workbench product realization. Evidence lives in
`docs/rfcs/RFC-0025-slice-12-gateway-workbench-product-realization.md`. Gateway now routes the
canonical Advise policy-pack and policy-evaluation BFF surface, including review queue, selected
evaluation, sign-off source package, workflow, sign-off decision, report-package, and AI-evidence
routes. Workbench now consumes Gateway/BFF-only policy review posture, selected evaluation
evidence, sign-off package posture, workflow posture, and a bounded request-more-evidence action
without local suitability calculation, approval/waiver authority, completed sign-off authority, or
client-ready publication. Canonical live proof, active data-product promotion, final hardening,
final closure, and post-completion communication remain gated.

RFC-0025 Slice 13 is implemented as policy-pack-specific commercial, demo, and RFP-support
material. Evidence lives in `docs/rfcs/RFC-0025-slice-13-commercial-demo-rfp-support.md`, with the
claim-controlled guide at `docs/commercial/RFC-0025-enterprise-policy-pack-commercial-support.md`.
The guide covers implementation-backed one-pager language, demo notes, API examples, architecture
flow, operator guidance, security posture, and RFP-safe wording. Active data-product promotion,
canonical live proof, approval/waiver authority, completed sign-off authority, final closure, and
client-ready publication remain gated.

RFC-0025 Slice 14 is implemented as policy evaluation implementation proof. Evidence lives in
`docs/rfcs/RFC-0025-slice-14-implementation-proof.md`. The governed live runtime suite now emits a
`proposal_policy` snapshot covering Advise policy evaluation create/read/review-queue/workflow/
sign-off-package/sign-off-decision/report-package/AI-evidence/lineage/replay endpoints, SG
reference-pack policy hashes, source refs and gaps, requirement counts, workflow and sign-off
posture, report/render/archive refs or degraded reason, bounded AI posture, replay hash comparison,
and stale-hash/client-ready/forbidden-AI blocked paths. Active data-product promotion, completed
approval/waiver authority, completed sign-off authority, final closure, and client-ready
publication remain gated.

RFC-0025 Slice 15 is implemented as final hardening and review. Evidence lives in
`docs/rfcs/RFC-0025-slice-15-final-hardening-and-review.md`. Policy-pack supportability truth is
now centralized, stale earlier-slice Gateway/Workbench/report-handoff posture has been removed from
code, OpenAPI/schema examples, and tests, and the implementation now accurately records
Gateway/Workbench product support and signed-off report-package handoff while active data-product
promotion, completed approval/waiver authority, completed sign-off authority, final closure, and
client-ready publication remain gated.

RFC-0025 Slice 16 is implemented as final closure. Evidence lives in
`docs/rfcs/RFC-0025-slice-16-final-closure.md`. `AdvisoryPolicyEvaluationRecord:v1` is active for
advisor/compliance policy evidence with freshness-gated trust telemetry, `/platform/capabilities`, platform
SLO/access/evidence-policy posture, Gateway/Workbench visibility, and live-suite proof. Completed
approval/waiver authority, completed sign-off authority, client-ready policy publication, external
client communication remain gated; RFC-0028 governs bank-demo/RFP proof through supported claims.

RFC-0025 Slice 17 is implemented as post-completion communication. Evidence lives in
`docs/rfcs/RFC-0025-slice-17-post-completion-communication.md`. The `lotus-platform` LinkedIn draft
`LI-2026-05-26-042-policy-evidence-should-show-its-limits.md` and content-ledger entry are
employer-safe, non-promotional, and do not claim completed approval/waiver authority, completed
sign-off authority, client-ready policy publication, external client communication, bank adoption,
or full RFC-0028 bank-demo/RFP support. The draft remains in draft status.

### RFC-0024

RFC-0024 Slice 0 is implemented as a critical-review, source-map, and product-gap allocation gate.
It records memo source authorities, cross-repo ownership, required blocked states, and the first
bounded implementation direction. It does not implement advisor proposal memo generation, memo APIs,
memo persistence, memo report packages, Gateway/Workbench memo surfaces, or client-ready memo
publication.

RFC-0024 Slice 1 is implemented as a platform automation and scaffolding review. It records that
existing Lotus platform and repo-native controls are sufficient before memo domain work, rejects
one-off local memo scaffolding, and pins the controls RFC-0024 implementation slices must satisfy for API
quality, observability, test pyramid, data-product promotion, trust telemetry, live proof, and
documentation truth.

RFC-0024 Slice 2 is implemented as cleanup and structure work. It moves reviewed narrative
report-package business rules from the API service layer into the core proposal report-handoff
boundary and adds engine-level tests for source-backed package construction, review approval,
hash-continuity, and support-safe summaries. It does not implement or promote advisor proposal memo
support.

RFC-0024 Slice 3 is implemented as data-product and platform-hardening work. It declares proposed
`AdvisoryProposalMemoEvidencePack:v1` product identity and blocked trust telemetry so governance
controls can see the planned memo product boundary. It does not add memo routes, active mesh
policy, `/platform/capabilities` support, Gateway/Workbench memo support, or client-ready memo
publication.

RFC-0024 Slice 4 is implemented as upstream source evidence completion. Proposal evidence bundles
now include a persisted `rfc0024.memo-source-readiness.v1` manifest that attributes memo-critical
source families to `lotus-core`, `lotus-risk`, and `lotus-advise`, marks unsupported or incomplete
facts as `PENDING_REVIEW`, `BLOCKED`, or `NOT_AVAILABLE`, and keeps memo generation and client-ready
publication unpromoted.

RFC-0024 Slice 5 is implemented as memo domain model and pure builder work. It introduces typed
`AdvisoryProposalMemoEvidencePack` models and a deterministic side-effect-free builder that projects
stored proposal evidence and the Slice 4 source-readiness manifest into advisor-review memo
sections. It does not add memo routes, memo persistence, report/render/archive support,
Gateway/Workbench support, active data-product support, or client-ready memo claims.

RFC-0024 Slice 6 is implemented as persistence, replay, idempotency, and audit foundation work. It
adds durable memo records, memo idempotency mappings, replay metadata, Postgres migration-backed
storage, and memo audit events for the Slice 5 evidence pack. It does not add public memo APIs,
report/render/archive realization, Gateway/Workbench support, active data-product support, or
client-ready memo claims.

RFC-0024 Slice 7 is implemented as certified Advise memo APIs and OpenAPI work. It exposes
canonical memo create/read/projection/review/report-package-event/lineage/replay endpoints under
the `Advisory Proposal Memo` tag, backed by persisted memo records and append-only audit events.
Gateway/Workbench product support, report/render/archive realization, active data-product support,
and client-ready memo publication remain gated at this slice.

RFC-0024 Slice 8 is implemented as memo-critical policy, fees, costs, conflicts, and disclosure
enrichment. It projects suitability issue counts, product eligibility and complexity coverage,
cost/fee/tax/friction limitation evidence, risk disclosures, product-document references, and
explicit conflict-policy blockers into persisted memo sections without converting missing evidence
into positive best-interest or client-ready wording.

RFC-0024 Slice 9 is implemented as advisor-use report/render/archive realization. Advise now
requires memo hash continuity and an `APPROVE_FOR_ADVISOR_USE` review before requesting a typed
memo package from `lotus-report`; `lotus-report` preserves the package in the report snapshot and
render package; `lotus-archive` stores support-safe advisor proposal memo archive metadata; and
Advise memo lineage records returned report, render, and archive refs. Gateway/Workbench product
support, active data-product support, AI commentary, and client-ready memo publication remain
gated at this slice.

RFC-0024 Slice 10 is implemented as advisor-use AI narrative and review-gated commentary. Advise now
requires memo hash continuity and `APPROVE_FOR_ADVISOR_USE` review before requesting bounded
commentary from `lotus-ai`; `lotus-ai` registers `proposal_memo_commentary.pack@v1` as a
review-gated workflow pack; and Advise records append-only AI lineage with deterministic
unavailable posture when AI is not configured. Gateway/Workbench product support, active
data-product support, commercial/demo claims, and client-ready memo publication remain gated at
this slice.

RFC-0024 Slice 11 is implemented as Gateway and Workbench product realization. `lotus-gateway`
routes proposal memo create/read/projection/review/report-package/AI-commentary, lineage, and
replay-evidence calls through canonical `lotus-advise` memo endpoints without recomputing memo
truth. `lotus-workbench` consumes Gateway/BFF only for memo posture, projection, report-package,
archive-ref, AI-commentary, lineage, replay, degraded, and blocked states, and browser proof keeps
client-ready release and send-to-client controls absent. Active data-product support,
commercial/demo claims, and client-ready memo publication remain gated at this slice.

RFC-0024 Slice 12 is implemented as memo-specific commercial, demo, and RFP-support material.
Evidence lives in `docs/rfcs/RFC-0024-slice-12-commercial-demo-rfp-support.md`, with the
claim-controlled guide at `docs/commercial/RFC-0024-advisor-proposal-memo-commercial-support.md`.
The guide covers implementation-backed one-pager language, demo notes, API examples, architecture
flow, operator guidance, and RFP-safe wording. Active data-product support and client-ready memo
publication remain gated at this slice; RFC-0028 now governs broader bank-demo/RFP proof through
supported claims.

RFC-0024 Slice 13 is implemented as memo implementation proof in the live runtime evidence bundle.
Evidence lives in `docs/rfcs/RFC-0024-slice-13-implementation-proof.md`. The live-suite
`proposal_memo` snapshot covers Advise memo APIs, the stateful source dependency path, advisor
projection, advisor-use report/render/archive request posture, review-gated AI commentary, lineage,
replay hashes, degraded report posture, and stale-hash/client-ready blocked paths.

RFC-0024 Slice 14 is implemented as data-product promotion and supportability hardening. Evidence
lives in `docs/rfcs/RFC-0024-slice-14-data-product-promotion-and-supportability-hardening.md`.
`AdvisoryProposalMemoEvidencePack:v1` is now an active advisor-use data product with current trust
telemetry, `/platform/capabilities`, and platform SLO/access/evidence-policy posture. Client-ready
memo publication remains gated; RFC-0028 now governs broader bank-demo/RFP proof through supported
claims.

RFC-0024 Slice 15 is implemented as final hardening and review. Evidence lives in
`docs/rfcs/RFC-0024-slice-15-final-hardening-and-review.md`. Canonical Workbench validation for
`PB_SG_GLOBAL_BAL_001` now proves the advisor journey and `proposal.memo_evidence_pack` panel are
ready and Gateway-backed. Client-ready memo publication and external client communication remain
gated; RFC-0028 now governs broader bank-demo/RFP proof through supported claims.

RFC-0024 Slice 16 is implemented as final closure. Evidence lives in
`docs/rfcs/RFC-0024-slice-16-final-closure.md`. RFC-0024 is implemented for advisor-use proposal
memo evidence with durable truth updated across README, wiki source, supported-features, RFC status,
repo context, domain-product declaration, trust telemetry, and proof summaries. Wiki publication was
completed after merge, and no Lotus context or skill guidance change was required. Client-ready memo
publication and external client communication remain gated; RFC-0028 now governs broader
bank-demo/RFP proof through supported claims.

RFC-0024 Slice 17 is implemented as post-completion communication. Evidence lives in
`docs/rfcs/RFC-0024-slice-17-post-completion-communication.md`. `lotus-platform` PR #357 added
`LI-2026-05-25-036-a-proposal-memo-is-an-evidence-product.md` and updated the content ledger. The
draft remains in draft status and does not claim client-ready memo publication, external client
communication, bank adoption, or full RFC-0028 bank-demo/RFP support.

### RFC-0023

RFC-0023 Slice 0 is implemented as a critical-review, source-map, and product-gap allocation gate.
It records source authorities, cross-repo ownership, and the first bounded implementation direction.
It does not implement generated proposal narrative.

RFC-0023 Slice 1 is implemented as a platform automation and scaffolding review. It records that
existing Lotus platform automation is sufficient for the next RFC-0023 slices and that no
`lotus-platform` code change is required before cleanup and contract work begins.

RFC-0023 Slice 2 is implemented as cleanup and structure work. It moves workspace-rationale
evidence construction into core workspace code, keeps the API service thin, removes a premature
client-ready OpenAPI wording claim, and does not promote proposal narrative support.

RFC-0023 Slice 3 is implemented as current-state assessment and narrative contract baseline work.
It maps current artifact, proposal detail, workspace, lifecycle, replay, decision-summary, and
alternatives evidence, defines an additive `proposal_narrative` contract baseline, and proves no
public API v2 is needed before implementation-bearing slices.

RFC-0023 Slice 4 is implemented as data-product and supportability baseline work. It records that
proposal narrative is not yet promoted as a domain data product, trust-telemetry fixture, or
`/platform/capabilities` feature because deterministic advisor-review narrative readiness has not
been implemented yet.

RFC-0023 Slice 5 is implemented as grounding-packet and deterministic-template baseline work. It
adds opt-in deterministic `ADVISOR_REVIEW` narrative in the proposal artifact path without AI
dependency. Standalone narrative endpoints, persistence, replay, review approval, AI-assisted
drafts, client-ready commentary, report/render/archive integration, data-product promotion, and
`/platform/capabilities` narrative rows remain gated at this slice.

RFC-0023 Slice 6 is implemented as narrative-policy, disclosure, and guardrail baseline work. It
adds deterministic policy metadata, approved disclosure selection, unsupported-claim guardrails,
and client-ready policy blockers to the artifact-path narrative response. Standalone narrative
endpoints, persistence, replay, review approval, client-ready commentary,
report/render/archive integration, data-product promotion, and `/platform/capabilities` narrative
rows remain gated at this slice.

RFC-0023 Slice 7 is implemented as a narrow lotus-ai adapter and AI-assisted advisor-review draft
baseline. It adds opt-in `AI_ASSISTED_DRAFT` narrative in the proposal artifact path, sends only
structured grounding packet, resolved policy, requested sections, approved instructions, and source
refs to the workflow-pack adapter, records AI lineage or deterministic fallback reason, and runs AI
text through the same unsupported-claim guardrails before returning the draft. Standalone narrative
endpoints, persistence, replay, review approval, client-ready commentary, report/render/archive
integration, data-product promotion, and `/platform/capabilities` narrative rows remain gated at
this slice.

RFC-0023 Slice 8 is implemented as a proposal-version review, persistence, idempotency, and replay
baseline. It persists narrative JSON with immutable proposal versions when lifecycle create/version
requests include `narrative_request`, records append-only `NARRATIVE_REVIEWED` review events for
approve, reject, and regeneration-request decisions, supports idempotent review replay and payload
drift conflicts, and returns exact persisted narrative plus latest review evidence from replay
endpoints. Client-ready commentary, report/render/archive integration, Gateway and Workbench
surfaces, data-product promotion, trust telemetry, and `/platform/capabilities` narrative rows
remain gated at this slice.

RFC-0023 Slice 9 is implemented as alternatives, decision-summary, and policy-evidence integration
work. It enriches advisor-review narrative sections with RFC-0021 decision-summary posture,
blockers, approval/remediation requirements, material changes, RFC-0022 selected-alternative
tradeoffs, rejected-candidate evidence, and risk/suitability limitations.

RFC-0023 Slice 10 is implemented as certified API and OpenAPI baseline work. It certifies the
existing additive advisor-review narrative API shape, canonical proposal-version review route,
proposal/async replay evidence routes, response documentation, idempotency header guidance,
stale-route absence, and material returned-field coverage. Standalone narrative read/regeneration
is tracked separately in Slice 10B.

RFC-0023 Slice 10B is implemented as standalone narrative read and regeneration API work. It adds
exact persisted narrative reads and non-persistent advisor-review regeneration candidates under the
canonical proposal-version route family, with source hashes, replay path, material-change posture,
and explicit review-required/non-client-ready posture.

RFC-0023 Slice 11A is implemented as reviewed narrative report-request package propagation
baseline work. It adds explicit `include_reviewed_narrative` support to proposal report requests,
requires the selected immutable proposal version to have an `APPROVED_FOR_ADVISOR_USE` narrative
review with matching source hash, propagates a compact source-backed narrative package to the
report-package integration boundary, and persists a package summary in report-request delivery
evidence.

RFC-0023 Slices 11B and 11C are implemented as downstream report and render realization work.
`lotus-report` consumes and snapshots the reviewed advisory narrative package, projects an
immutable render payload into `report_data.reviewed_advisory_narrative`, and preserves package
lineage, disclosure refs, guardrail posture, limitations, review state, policy version, source
hashes, and advisor-use restrictions. `lotus-render` consumes that payload and renders an optional
portfolio-review v1 advisory narrative page when the package status is `included`, while omitting
the page for reports without a reviewed package.

RFC-0023 Slice 11D is implemented as downstream archive realization work. `lotus-archive` stores a
support-safe `reviewed_advisory_narrative` metadata summary for rendered advisor-use
portfolio-review artifacts, requires approved advisor-review posture and `sha256:` source hashes,
rejects client-ready statuses, and records source events with reviewed narrative package lineage
without storing raw narrative sections separately.

RFC-0023 Slice 11E is implemented as Gateway and Workbench realization work. `lotus-gateway`
exposes product-facing reviewed-narrative posture through canonical `lotus-advise` review,
report-request, delivery-summary, and delivery-event APIs, while `lotus-workbench` renders the
Gateway-backed advisor-use proposal narrative posture without inferring narrative facts locally.

RFC-0023 Slice 11F is implemented as narrative data-product, trust-telemetry, and capability
promotion work. `lotus-advise` now declares `ProposalNarrativeEvidence:v1`, validates
advisor-review narrative trust telemetry against that declaration, and advertises
`advisory.proposals.reviewed_narrative_evidence` plus
`advisory_proposal_reviewed_narrative_evidence` in `/platform/capabilities`. `lotus-platform`
catalog and certification artifacts include the new product.

RFC-0023 Slice 12 is implemented as live validation, canonical proof, and operator-evidence
hardening. The live suite now creates stateful advisor-review narrative proposals from Lotus Core
context, validates immutable read, non-persistent regeneration, advisor-use review, reviewed
report-package request, replay evidence, guardrail failure reproduction, and optional
AI-assisted validation when enabled. Workbench canonical validation now proves
`proposal.narrative_posture` with a governed screenshot and panel-registry classification.

RFC-0023 Slice 13/14 is implemented as closure hardening and gold-standard review. It records that
RFC-0023 is not a full client-ready publication capability and hardens the review workflow so an
otherwise clean advisor-review narrative release request still cannot return
`APPROVED_FOR_CLIENT_READY`.

RFC-0023 is now implemented for artifact-path advisor-review narrative and proposal-version
review/replay evidence with decision-summary and alternatives-aware section rendering, and the
canonical API/OpenAPI surface is certified for standalone read, non-persistent regeneration,
review, and replay. Report requests can include a reviewed narrative package only when review
posture and hash continuity are sufficient, and the package can now flow through
`lotus-report`, `lotus-render`, `lotus-archive`, `lotus-gateway`, and `lotus-workbench` as
advisor-use product content and posture. Advisor-review narrative evidence now has data-product,
trust telemetry, platform catalog/certification, capability-discovery posture, live validation, and
governed canonical Workbench proof. Later RFC-0024 through RFC-0028 capabilities add advisor-use
memo evidence, policy review posture, cockpit workflow, governed copilot support, and bank-demo
proof. Compliance-review, client-draft, client-ready artifact publication, and external client
communication remain blocked unless a separately approved implementation explicitly supports and
proves those controls; they are not supported RFC-0023 closure claims.

## Source Index

Use `docs/rfcs/README.md` as the authoritative repository RFC disposition index.

Implementation evidence:
- `docs/rfcs/RFC-0023-slice-0-critical-review-source-map-and-product-gap-allocation.md`
- `docs/rfcs/RFC-0023-slice-1-platform-automation-and-scaffolding-review.md`
- `docs/rfcs/RFC-0023-slice-2-cleanup-and-structure.md`
- `docs/rfcs/RFC-0023-slice-3-current-state-assessment-and-narrative-contract-baseline.md`
- `docs/rfcs/RFC-0023-slice-4-data-product-and-supportability-baseline.md`
- `docs/rfcs/RFC-0023-slice-5-grounding-packet-and-deterministic-template-baseline.md`
- `docs/rfcs/RFC-0023-slice-6-narrative-policy-disclosure-and-guardrail-framework.md`
- `docs/rfcs/RFC-0023-slice-7-lotus-ai-adapter-and-ai-assisted-draft-baseline.md`
- `docs/rfcs/RFC-0023-slice-8-review-workflow-persistence-idempotency-artifact-and-replay.md`
- `docs/rfcs/RFC-0023-slice-9-alternatives-decision-summary-and-policy-evidence-integration.md`
- `docs/rfcs/RFC-0023-slice-10-certified-api-and-openapi.md`
- `docs/rfcs/RFC-0023-slice-10B-standalone-narrative-read-regeneration-api.md`
- `docs/rfcs/RFC-0023-slice-11A-reviewed-narrative-report-request-package-propagation.md`
- `docs/rfcs/RFC-0023-slice-11B-11C-report-render-reviewed-narrative-realization.md`
- `docs/rfcs/RFC-0023-slice-11D-archive-reviewed-narrative-artifact-realization.md`
- `docs/rfcs/RFC-0023-slice-11E-gateway-workbench-reviewed-narrative-realization.md`
- `docs/rfcs/RFC-0023-slice-11F-narrative-data-product-trust-capability-promotion.md`
- `docs/rfcs/RFC-0023-slice-12-live-validation-canonical-proof-and-operator-evidence.md`
- `docs/rfcs/RFC-0023-slice-13-14-closure-hardening-and-review.md`
- `docs/rfcs/RFC-0024-slice-0-critical-review-source-map-and-product-gap-allocation.md`
- `docs/rfcs/RFC-0024-slice-1-platform-automation-and-scaffolding-review.md`
- `docs/rfcs/RFC-0024-slice-2-cleanup-and-structure.md`
- `docs/rfcs/RFC-0024-slice-3-data-product-and-platform-hardening.md`
- `docs/rfcs/RFC-0024-slice-4-upstream-source-evidence-completion.md`
- `docs/rfcs/RFC-0024-slice-5-memo-domain-model-and-pure-builder.md`
- `docs/rfcs/RFC-0024-slice-6-persistence-replay-idempotency-and-audit.md`
- `docs/rfcs/RFC-0024-slice-7-certified-apis-and-openapi.md`
- `docs/rfcs/RFC-0024-slice-8-policy-fees-costs-conflicts-and-disclosures.md`
- `docs/rfcs/RFC-0024-slice-9-report-render-archive-realization.md`
- `docs/rfcs/RFC-0024-slice-10-ai-narrative-and-review-gated-commentary.md`
- `docs/rfcs/RFC-0024-slice-11-gateway-workbench-product-realization.md`
- `docs/rfcs/RFC-0024-slice-12-commercial-demo-rfp-support.md`
- `docs/rfcs/RFC-0024-slice-13-implementation-proof.md`
- `docs/rfcs/RFC-0025-slice-1-platform-automation-and-scaffolding-review.md`
- `docs/rfcs/RFC-0025-slice-3-data-product-and-platform-hardening.md`
- `docs/rfcs/RFC-0025-slice-4-upstream-source-evidence-completion.md`
- `docs/rfcs/RFC-0025-slice-5-policy-pack-catalog-schema-activation.md`
- `docs/rfcs/RFC-0025-slice-6-policy-applicability-and-evaluation-engine.md`
- `docs/rfcs/RFC-0025-slice-13-commercial-demo-rfp-support.md`
- `docs/commercial/RFC-0025-enterprise-policy-pack-commercial-support.md`
- `docs/rfcs/RFC-0025-slice-7-policy-evaluation-persistence-replay-audit.md`
- `docs/rfcs/RFC-0025-slice-8-certified-apis-and-openapi.md`
- `docs/rfcs/RFC-0025-slice-9-policy-approval-consent-signoff-workflow.md`
- `docs/rfcs/RFC-0025-slice-10-report-render-archive-realization.md`
- `docs/rfcs/RFC-0025-slice-11-ai-policy-evidence-boundary.md`
- `docs/rfcs/RFC-0025-slice-14-implementation-proof.md`
- `docs/rfcs/RFC-0025-slice-15-final-hardening-and-review.md`
- `docs/rfcs/RFC-0025-slice-16-final-closure.md`
- `docs/rfcs/RFC-0026-slice-1-platform-automation-and-scaffolding-review.md`
- `docs/rfcs/RFC-0026-slice-2-cleanup-and-structure.md`
- `docs/rfcs/RFC-0026-slice-3-data-product-and-platform-hardening.md`
- `docs/rfcs/RFC-0026-slice-4-cockpit-domain-model-and-vocabulary.md`
- `docs/rfcs/RFC-0026-slice-5-source-read-model-and-aggregation.md`
- `docs/rfcs/RFC-0026-slice-6-priority-sla-acknowledgement-rules.md`
- `docs/rfcs/RFC-0026-slice-7-certified-advise-apis.md`
- `docs/rfcs/RFC-0026-slice-8-meeting-preparation-client-follow-up.md`
- `docs/rfcs/RFC-0026-slice-9-supervisory-approval-compliance-queues.md`
- `docs/rfcs/RFC-0026-slice-10-readiness-execution-house-view.md`
- `docs/rfcs/RFC-0026-slice-13-data-product-capability-promotion.md`
- `docs/rfcs/RFC-0026-slice-16-implementation-proof.md`
- `docs/rfcs/RFC-0027-slice-1-platform-automation-and-scaffolding-review.md`
- `docs/rfcs/RFC-0027-slice-2-cleanup-and-structure.md`
- `docs/rfcs/RFC-0027-slice-3-data-product-and-platform-hardening.md`
- `docs/rfcs/RFC-0027-slice-4-domain-model-vocabulary-review-state.md`
- `docs/rfcs/RFC-0027-slice-5-evidence-packet-redaction-projection.md`
- `docs/rfcs/RFC-0027-slice-6-guardrail-unsupported-evidence-engine.md`
- `docs/rfcs/RFC-0027-slice-7-lotus-ai-workflow-pack-model-risk-controls.md`
- `docs/rfcs/RFC-0027-slice-8-copilot-run-review-audit-retention.md`
- `docs/rfcs/RFC-0027-slice-9-certified-advise-apis-openapi.md`
- `docs/rfcs/RFC-0027-slice-10-14-product-realization-proof-closure.md`
- `docs/rfcs/RFC-0028-bank-demo-journey-and-client-ready-proof.md`
- `docs/commercial/RFC-0028-bank-demo-client-proof-materials.md`
