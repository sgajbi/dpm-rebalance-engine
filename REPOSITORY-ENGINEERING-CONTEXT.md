# Repository Engineering Context

This file provides repository-local engineering context for `lotus-advise`.

For platform-wide truth, read:

1. `../lotus-platform/context/LOTUS-QUICKSTART-CONTEXT.md`
2. `../lotus-platform/context/LOTUS-ENGINEERING-CONTEXT.md`
3. `../lotus-platform/context/CONTEXT-REFERENCE-MAP.md`

## Repository Role

`lotus-advise` is the advisory workflow and proposal simulation service.

It owns advisor-led proposal lifecycle and recommendation-oriented execution readiness behavior.

## Business And Domain Responsibility

This repository owns:

1. advisor-led proposal simulation,
2. proposal lifecycle state,
3. advisory approvals and consent-related workflow behavior,
4. advisory execution readiness,
5. source-owned tactical house-view affected cohorts for bank-authored house-view instructions and
   caller-supplied source-backed candidate portfolios.

It does not own discretionary portfolio-management operations; those belong to `lotus-manage`.

## Current-State Summary

Current repository posture:

1. `lotus-advise` is now scoped to advisory-only workflows after the split from `lotus-manage`,
2. runtime smoke and production-profile guardrail validation are part of the real CI contract,
3. canonical upstream integration with `lotus-core` and `lotus-risk` matters for truthful proposal behavior,
4. proposal simulation, artifact, workspace, replay, and lifecycle surfaces now expose persisted backend-owned `proposal_decision_summary` and `proposal_alternatives`,
5. RFC-0023 advisor-review proposal narrative is supported in the proposal artifact,
   proposal-version review/replay, reviewed report-request package propagation, and downstream
   `lotus-report`/`lotus-render` advisor-use report rendering path, with `lotus-archive`
   support-safe archive metadata summaries for rendered advisor-use portfolio-review artifacts;
   `lotus-gateway` now exposes product-facing reviewed-narrative posture through canonical
   `lotus-advise` APIs and `lotus-workbench` renders the Gateway-backed advisor-use proposal
   narrative posture. `ProposalNarrativeEvidence:v1` is declared as a governed advisor-review
   evidence product with repo-native trust telemetry and `/platform/capabilities` reviewed
   narrative evidence feature/workflow promotion. Live runtime evidence now validates stateful
   advisor-review narrative requests, immutable read, non-persistent regeneration, advisor-use
   review, reviewed report-package request, replay evidence, deterministic guardrail-failure
   reproduction, and optional AI-assisted narrative validation when enabled. Canonical Workbench
   proof now covers `proposal.narrative_posture`. Slice 13/14 hardening records that even a clean
   advisor-review narrative release request cannot return `APPROVED_FOR_CLIENT_READY`.
   Client-ready commentary, compliance-review and client-draft narrative, and client communication
   remain gated. Standalone proposal-version
   narrative read and non-persistent regeneration APIs are supported for advisor-review posture.
   Historical Slice 0-11 audit wording is preserved only as audit context. Slice 12 closed the
   advisor-review Workbench canonical proof path and Slice 13/14 hardened the client-ready approval
   boundary; client-ready narrative, compliance-review narrative, client-draft narrative,
   client-ready publication, and external client communication remain gated future scope rather
   than supported RFC-0023 closure claims,
6. RFC-0024 advisor proposal memo support now includes advisor-use report/render/archive
   realization, review-gated AI commentary, Gateway/Workbench product realization,
   memo-specific commercial support material, and live-suite implementation proof: Advise
   requires memo hash continuity and `APPROVE_FOR_ADVISOR_USE` review before sending a typed memo
   package to `lotus-report` or a bounded memo evidence packet to `lotus-ai`
   `proposal_memo_commentary.pack@v1`; memo lineage records returned report/render/archive refs and
   append-only AI lineage. Gateway now routes canonical Advise memo endpoints, and Workbench
   consumes Gateway/BFF-only memo posture, projection, report-package, archive-ref, AI-commentary,
   lineage, replay, degraded, and blocked states without local memo inference. The memo commercial
   guide gives sales/pre-sales a claim-controlled one-pager, demo notes, API examples, architecture
   flow, operator guidance, and RFP-safe wording for the implemented advisor-use posture. The
   governed live runtime evidence bundle now emits `proposal_memo` proof for Advise memo APIs, the
   stateful source dependency path, advisor projection, advisor-use report/render/archive request
   posture, review-gated AI commentary, lineage, replay hashes, degraded report posture, and
   stale-hash/client-ready blocked paths. `AdvisoryProposalMemoEvidencePack:v1` is now an active
   advisor-use data product with freshness-gated repo-native trust telemetry, `/platform/capabilities`
   feature/workflow posture, and platform SLO/access/evidence-policy support. Final hardening adds
   canonical `PB_SG_GLOBAL_BAL_001` Workbench proof that the advisor journey and
   `proposal.memo_evidence_pack` panel are Gateway-backed. RFC-0024 is closed for advisor-use memo evidence with durable README/wiki/supported-features/RFC/context/domain-product/trust telemetry truth updated.
   Full RFC-0028 bank-demo/RFP package claims remain gated, and client-ready memo publication remains gated,
7. RFC-0025 enterprise policy-pack implementation is closed for advisor/compliance policy evidence.
   Slice 3 declared `AdvisoryPolicyEvaluationRecord:v1` as a proposed, blocked data product with trust telemetry and
   platform catalog posture. Slice 4 adds `rfc0025.policy-source-readiness.v1` to proposal evidence
   bundles so future policy evaluation consumes explicit `lotus-core`, `lotus-risk`, and
   `lotus-advise` source-readiness sections rather than inferring or defaulting missing source
   facts. Slice 5 adds `rfc0025.policy-pack-catalog.v1`, reference-pack list/detail/validate/
   activate APIs, schema/content validation, content hashes, maker-checker activation, and audit
   events for `GLOBAL_PRIVATE_BANKING_BASELINE` and `SG_PRIVATE_BANKING_REFERENCE`. Slice 6 adds
   the internal `rfc0025.policy-evaluation-engine.v1` applicability and rule-evaluation engine for
   active policy packs, including fail-closed source-backed selection by jurisdiction, booking
   center, legal entity, client segment, and policy product scope, plus material rule posture for
   source readiness, mandate, product eligibility, complex-product disclosure/consent,
   best-interest cost evidence, and conflict/product-document review. Slice 7 adds internal
   `rfc0025.policy-evaluation-persistence.v1` finalized policy evaluation records with
   policy/source/evaluation hashes, per-rule hashes, source gaps, approval dependencies,
   disclosure and consent requirements, replay metadata, duplicate prevention, idempotent replay,
   and append-only review/sign-off/report-archive events. RFC-0002 producer hardening adds the
   `rfc0002.policy-evaluation-receipt-identity.v1` receipt identity to finalized workflow
   projections: receipts fail closed without a source-owned as-of date, trusted local/dev
   policy-control principal, Advise-observed trace context, and stable scope identity; persisted
   replay metadata exposes source-safe tenant/service/correlation/trace hashes rather than raw
   caller identifiers. Slice 8 exposes certified Advise policy
   evaluation create/read/replay/event/lineage/review-queue/sign-off source-package APIs and
   OpenAPI documentation. Slice 9 adds Advise-owned policy workflow projection and sign-off
   decision recording over finalized records, including approval dependencies, disclosure and
   consent requirements, conflict posture, SLA aging, maker-checker enforcement, source-hash
   validation, and append-only sign-off events. Slice 10 adds Advise-owned policy report-package
   realization for signed-off policy evaluations: typed `lotus-report` handoff, returned
   report/render/archive refs in policy lineage, idempotent replay, and fail-closed client-ready
   document handling. Slice 11 adds Advise-owned AI policy-evidence consumption: redacted bounded
   policy evidence packets to `policy_evidence_summary.pack@v1`, forbidden-action rejection,
   deterministic unavailable posture, prompt/output lineage, human review, non-authoritative AI
   posture, and client-ready blocked lineage. Slice 12 adds Gateway and Workbench product
   realization: Gateway routes canonical Advise policy-pack/evaluation BFF APIs, and Workbench
   consumes Gateway-only policy review queue, selected evaluation detail, sign-off source package,
   workflow posture, and bounded request-more-evidence actions without local policy inference.
   Slice 13 adds policy-pack-specific commercial support material with claim-controlled one-pager
   language, demo notes, API examples, architecture flow, operator guidance, security posture, and
   RFP-safe wording. Slice 14 adds live-suite policy implementation proof: `proposal_policy` covers
   Advise policy evaluation APIs, SG reference-pack hashes, source refs and gaps, requirement
   counts, workflow and sign-off posture, report/render/archive refs or degraded reason, bounded AI
   evidence, lineage, replay hashes, and stale-hash/client-ready/forbidden-AI blocked paths.
   Slice 15 hardens the second-last review boundary by centralizing policy-pack supportability
   posture in `src/core/policy_packs/supportability.py` and removing stale earlier-slice
   Gateway/Workbench/report-handoff unsupported claims from code, OpenAPI/schema examples, and
   tests.
   Slice 16 promotes `AdvisoryPolicyEvaluationRecord:v1` as an active advisor/compliance policy
   evidence product with freshness-gated trust telemetry, `/platform/capabilities` feature/workflow
   posture, platform SLO/access/evidence-policy support, and durable README/wiki/RFC/context/
   domain-product/trust telemetry closure truth. Runtime policy catalog/evaluation state is now
   composed through policy repository ports and backed by the `policy_packs` Postgres migration
   namespace for records, audit events, activation state, and idempotency maps. Policy-pack
   PostgreSQL state writes are adapter-transactional across record/catalog state,
   audit events, and idempotency mappings; idempotency mappings are immutable request-hash
   decisions, audit-event conflicts must fail closed, and stale snapshots must not overwrite newer
   event-backed state. Completed
   approval/waiver authority, completed sign-off authority, client-ready policy publication,
   external client communication, and full RFC-0028 bank-demo/RFP package claims remain gated,
   and the generic policy-evaluation event API is review-only: sign-off, report/archive,
   AI-evidence, and finalization events must be created through their specialized workflow,
   report-package, AI-evidence, and finalize commands with event-authority contract checks.
   Policy-pack validation/activation and policy-evaluation finalize/review/sign-off/report/AI
   commands bind actor authority to trusted policy-control headers: `X-Actor-Id`, `X-Role`,
   `X-Tenant-Id`, `X-Legal-Entity-Code`, `X-Correlation-Id`, service identity, capability,
   authorized proposal id, and authorized portfolio id. Body actor fields are compatibility echoes
   only and must match the trusted principal; maker-checker, audit metadata, scope checks, and
   policy-evaluation workflow receipt identity use trusted principal identity rather than request
   strings. The receipt identity is intentionally local/dev trusted-header based until a later
   production identity-provider slice binds bank-authenticated session and token claims,
8. RFC-0026 advisor cockpit first-wave scope is implemented for source-owned Advise evidence and
   cross-repo product consumption: the dedicated `src/core/advisor_cockpit/` package owns action
   construction, source-read-model aggregation, SLA/acknowledgement rules, supportability, and API
   DTO projection; Advise exposes certified action, snapshot, supportability, and acknowledgement
   routes; Gateway and Workbench consume those contracts; canonical `PB_SG_GLOBAL_BAL_001` proof is
   present; `AdvisorCockpitOperatingSnapshot:v1` and `AdvisoryActionItemRegister:v1` are active
   data products with trust telemetry and `/platform/capabilities` feature/workflow posture.
   Advisor Cockpit reads and acknowledgements resolve actor, role, tenant, legal entity,
   capabilities, advisor scope, and portfolio scope from trusted gateway/service headers rather
   than caller-controlled `role` or `advisor_id` query parameters. Public Advisor Cockpit caller and
   owner role vocabulary uses `PORTFOLIO_MANAGER` for portfolio-management owned actions; the legacy
   `DPM_OWNER` caller alias is retired from OpenAPI, API vocabulary inventory, and request
   validation. Acknowledgement writes bind `acknowledged_by` to the trusted principal before
   persistence, idempotency hashing, and audit metadata are recorded.
   Client-ready publication, external client communication, CRM system-of-record behavior, OMS
   order/fill/settlement lifecycle, completed policy approval authority, and full RFC-0028
   demo/RFP package claims remain gated,
9. RFC-0028 bank-demo proof is implemented through the Advise scenario contract,
   `AdvisorySupportedClaimRegister:v1`, sanitized proof-pack capture, Gateway publication,
   Platform canonical scenario/panel registration, and Workbench `advisory.bank_demo_proof`
   evidence. Canonical `PB_SG_GLOBAL_BAL_001` validation records
   `BANK_DEMO_PROOF_PACK_CREATED` and proves blocked client-ready publication posture without
   claiming external client communication, OMS/order/fill/settlement, approval authority, or full
   RFP/demo collateral readiness. Slice 9 adds
   `AdvisoryJourneyIntegrationProofSummary:v1` to the backend proof pack so AI/model-risk,
   policy, and advisor-cockpit boundary evidence is reviewed as source-owned proof without raw
   prompt/source leakage or unsupported approval/client-ready claims. Slice 10 adds
   `AdvisoryCommercialMaterialPack:v1`,
   `docs/commercial/RFC-0028-bank-demo-client-proof-materials.md`, and
   `commercial_rfp_security_material_available` for claim-controlled product, RFP, security,
   architecture, ROI, demo, feature-matrix, boundary, proof-guide, and operator material while
   preserving blocked client-ready, external-communication, legal/regulatory, bank-attestation,
   completed-sign-off, and OMS/order/fill/settlement claims. Slice 11 moves runtime posture into
   `src/core/bank_demo_proof/runtime_posture.py`, records bounded `latency_ms`, rejects runtime
   proof URLs with credentials/query/fragment material, and redacts sensitive runtime summaries
   before proof artifacts can carry security/latency evidence with proof marker
   `RFC0028_RUNTIME_SECURITY_POSTURE_HARDENED`. Slice 13/14 closes final implementation proof and
   hardening through PR #213, `src/core/bank_demo_proof/artifact_refs.py`, local artifact-reference
   normalization, safe HTTP 422 validation error responses that do not echo rejected sensitive
   input, targeted proof tests, `make check`, PR Merge Gate, and Main Releasability Gate run
   `26573760885` on merge `a99474e5457dcdd4c87e79faf83bc8f64580544b`. Slice 15/16 closes durable
   RFC, README, wiki, repository-context, supported-features, and post-completion communication
   truth through `lotus-platform` PR #369 at `26d74e65e231ac3d62457187c6eb7f787a4d9f88`,
   Main Releasability Gate run `26574820026`, and
   `lotus-platform/thought-leadership/linkedin/drafts/LI-2026-05-28-043-demo-proof-should-show-the-boundary.md`.
   RFC-0028 is implemented for repeatable bank-demo proof and claim-controlled commercial
   material; client-ready publication, external client communication, bank-specific attestations,
   legal/regulatory advice, completed sign-off/approval, and OMS/order/fill/settlement remain
   unpromoted,
10. live operator evidence validates decision-summary and proposal-alternatives posture across canonical and degraded runtime paths,
11. upstream service consumption is classified under RFC-0082 in `docs/architecture/RFC-0082-upstream-contract-family-map.md`,
12. repo-native CI is already aligned to explicit lane expectations,
13. RFC-0086 repo-native declaration onboarding now covers the advisory proposal lifecycle product,
   proposal narrative evidence product, and a bounded tactical house-view affected-cohort product
   in `contracts/domain-data-products/`, with explicit upstream dependencies; every route placeholder
   in the complete Advise declaration set must be listed in `identifier_refs` and is enforced by the
   declaration regression gate against the platform vocabulary,
14. RFC-0087 trust telemetry proof for `AdvisoryProposalLifecycleRecord`, RFC-0023 trust telemetry
   proof for `ProposalNarrativeEvidence`, and RFC-0026 trust telemetry proof for the advisor
   cockpit operating snapshot and action-item register now live under `contracts/trust-telemetry/`
   and are validated by `tests/unit/test_trust_telemetry.py` against the platform trust telemetry
   validator when `lotus-platform` is available,
15. the advisory workspace rationale path now uses the explicit `lotus-ai` workflow-pack execution
   seam for the `workspace_rationale.pack` family, preserves bounded run posture in the advisory
   response, and exposes a separate bounded review-action pass-through that retains Lotus AI
   lineage truth,
16. execution handoff, status, and delivery projections carry explicit ownership-boundary evidence
   so advisory posture cannot be confused with downstream execution system-of-record truth,
17. `POST /advisory/proposals/idea-intake` is implemented as a source-safe `lotus-idea`
   conversion-intent intake receipt. It proves trusted local/dev caller scope, durable
   PostgreSQL-backed idempotency conflict detection, restart-safe replay, and bounded
   accepted/rejected outcomes. The required canonical portfolio identity comes from the
   producer-authorized Idea candidate scope, participates in intake identity and fingerprinting,
   and is retained in the durable receipt; Advise never infers it from candidate or conversion
   identifiers. Pre-v1.6 same-key replay conflicts until an operator reconciles the unscoped
   receipt and the producer submits the scoped request with a new key. Claims have a 24-hour replay window, are automatically purged on
   subsequent intake after expiry in target-prioritized batches of at most 128, write sanitized
   purge evidence in the same transaction, and remain protected while under legal hold. It is
   not certified as proposal realization, does not persist
   advisory review work or proposal lifecycle records, does not publish a source-owned business
   outcome stream, does not run suitability,
   does not authorize client publication, and must not be listed as a supported feature until the
   downstream realization blockers are closed with runtime evidence,
18. completed advisory copilot output must pass the Advise-owned approved provider/model inventory
   in `src/core/advisory_copilot/model_governance.py` and
   `contracts/advisory-copilot/approved-model-inventory.v1.json`, then pass the executable
   evaluation gate in `src/core/advisory_copilot/evaluation_gate.py` using
   `contracts/advisory-copilot/evaluation-corpus.v1.json`, then pass structured safety policy in
   `src/core/advisory_copilot/guardrails.py` using
   `contracts/advisory-copilot/safety-abuse-corpus.v1.json`, then satisfy AI data-boundary
   minimization in `src/core/advisory_copilot/ai_data_boundary.py` and
   `contracts/advisory-copilot/ai-data-boundary.v1.json`, then satisfy runtime budget enforcement
   in `src/core/advisory_copilot/runtime_budget.py` and
   `contracts/advisory-copilot/runtime-budget.v1.json`, and then pass claim-level source grounding
   before it can remain review-ready. Unknown, retired, mismatched, or
   environment-incompatible `lotus-ai` model identity returns a stable unavailable posture before
   completed output can be persisted; failed evaluation evidence quarantines output as unsupported,
   while prompt-injection, forbidden-action, client-ready, or sensitive-output evidence returns a
   stable guardrail-rejected posture. Outbound AI payloads carry tokenized portfolio/proposal/source
   identifiers and explicit no-training, retention, residency, and deletion controls; retry,
   timeout, token, payload, cost, and concurrency budget breaches return stable unavailable posture
   with bounded lineage telemetry; grounding
   references remain in the workflow context because generated claims must cite stable source refs.
   Each provider claim must cite source refs from the input evidence packet and align to the output
   section; missing, duplicate, unknown, or mismatched citations are persisted as unsupported or
   unverifiable grounding posture rather than as review-ready AI output. Copilot review actions must
   also bind reviewer authority to trusted
   copilot-review headers before mutation; request-body `actor_id` is a compatibility echo only,
   while trusted principal identity drives role/capability checks, proposal/portfolio/tenant scope,
   maker-checker enforcement, audit metadata, and idempotent replay identity.

## Architecture And Module Map

Primary areas:

1. `src/`
   advisory APIs, workflow logic, and supporting modules.
2. `scripts/`
   dependency-health, runtime smoke, OpenAPI, vocabulary, and governance scripts.
3. `docs/`
   advisory standards and workflow documentation.
4. `tests/`
   unit, integration, and e2e validation.
5. `wiki/`
   canonical authored source for GitHub wiki publication and advisory operator onboarding summaries.
6. `contracts/domain-data-products/`
   repo-native producer and consumer declarations for governed advisory products and dependencies.
7. `contracts/trust-telemetry/`
   repo-native RFC-0087 trust telemetry fixtures for governed advisory products.

Repository organization rule:

1. new backend files must live in the smallest meaningful owner package rather than a broad dump
   folder,
2. package names should describe durable domain or runtime responsibility, such as workspace
   application, infrastructure adapters, route families, repository ports, or supportability
   policy,
3. implementation files must not be named for an RFC, slice, issue, or temporary campaign unless
   the file is actually an RFC document, rollout note, tracking ledger, or contract fixture whose
   purpose is that governance item,
4. tests should mirror the capability/package boundary being protected and should target stable
   ports or dependencies instead of stale helper imports,
5. when moving behavior out of a flat service module, prefer cohesive subpackages with explicit
   interfaces and retire compatibility wrappers only after downstream contracts are safe.
6. `src/api/proposals/principal.py` owns shared proposal-principal header normalization,
   authentication status, role/capability authorization, and service-identity fallback. The
   surface modules retain their typed principal constructors, error vocabulary, and declarative
   role/capability policy; do not copy common principal resolution into another proposal surface.

## Runtime And Integration Boundaries

Runtime model:

1. FastAPI advisory service,
2. depends on `lotus-core` and `lotus-risk`,
3. consumed through `lotus-gateway` for integrated product flows.

Boundary rules:

1. advisor-only workflows belong here,
2. management-only workflows belong in `lotus-manage`,
3. proposal simulation must remain aligned with authoritative upstream data and risk posture,
4. Lotus Core stateful context must reject returned portfolio, positions, cash, or resolved-as-of
   identity that conflicts with the requested source identity before constructing or caching
   advisory snapshots,
5. Lotus Core stateful context, enrichment, taxonomy, instrument, price, and FX caches must use
   the shared semantic cache identity from
   `src/integrations/lotus_core/stateful_context_cache_identity.py`. Keys include sanitized
   query/control-plane source URL, `ENVIRONMENT`, `LOTUS_ADVISE_TENANT_ID` when configured,
   advisory simulation contract version, portfolio, as-of, mandate, benchmark, reporting currency,
   look-through/allocation/risk dimensions, and lookup-specific identifiers; current unsupported
   dimensions remain explicit default dimensions rather than omitted key parts,
6. The app-local Compose manifest supplies `LOTUS_ADVISE_TENANT_ID=tenant-sg-001` only as the
   canonical developer fixture for standalone and Workbench-orchestrated local startup. Production
   Compose must continue to require deployment-owned tenant configuration and must not inherit this
   local fixture,
7. Lotus Core source provenance is part of advisory result lineage. Stateful context must preserve
   upstream portfolio and market-data snapshot identity, source version, event or batch refs, source
   hash, valuation timestamp, freshness posture, and contract version as typed provenance on the
   resolved context, advisory snapshots, and proposal lineage without storing raw source payloads.
   Conflicting source snapshot or provenance values must fail closed before advisory snapshot
   construction, caching, persistence, or replay,
8. Lotus Core source-derived FX rates must be finite, strictly positive, and as-of eligible before
   advisory valuation. Invalid explicit rates or source ratios fail closed with
   `LOTUS_CORE_STATEFUL_FX_INVALID`; missing eligible rates remain data-quality evidence rather
   than fabricated conversion inputs. Inverse-pair valuation is supported only from a valid positive
   inverse rate,
9. Lotus Core stateful context must account for source-row completeness before advisory snapshot
   construction. Required positions, cash, price, and FX source rows cannot silently disappear:
   malformed or incomplete required rows fail closed with
   `LOTUS_CORE_STATEFUL_SOURCE_INCOMPLETE`. Optional enrichment and classification taxonomy gaps
   remain explicit degraded source-completeness evidence on resolved context, advisory snapshots,
   and proposal lineage without storing raw source payloads,
10. External advisory providers are runtime-composed through Advise-owned ports. Core application
   modules must not import concrete `src.integrations` modules or provider-specific exception
   classes. API/runtime startup registers production Lotus Core simulation/context, Lotus Risk
   enrichment/dependency-state, Lotus AI narrative/memo, and Lotus Report memo package adapters
   explicitly; tests should use deterministic port doubles. Shared tests that mutate global
   provider ports must restore the proposal stateful-context resolver through
   `configure_advisory_stateful_context_provider_port()` so engine-level resolver overrides cannot
   leak into API files. Integration modules must not import `src.api.main`, read `sys.modules`, or
   depend on FastAPI import order to select resolver or requester behavior,
11. decision-summary, proposal-alternatives generation, ranking, selection, approval-requirement, and material-change semantics are backend-owned contracts and must not be generated, reranked, or re-inferred in UI or support layers,
12. proposal alternatives must remain anchored to canonical `lotus-core` simulation and `lotus-risk` enrichment rather than local duplicated calculations,
13. tactical house-view affected cohorts must remain bounded to supplied source-backed candidates,
   preserve source refs, and must not discover the global portfolio universe or open DPM campaigns,
14. execution handoff, status, and delivery surfaces must preserve the boundary that `lotus-advise`
   records advisory posture while downstream providers remain execution systems of record,
15. proposal-create persistence must use the repository port's atomic unit-of-work boundary for
   initial proposal aggregate, immutable version 1, `CREATED` workflow event, and proposal-create
   idempotency record writes; callers must not recreate the multi-write sequence in services,
   routers, async glue, or scripts,
16. memo-create persistence must use the repository port's atomic unit-of-work boundary for memo
   record, optional memo-create idempotency record, and initial memo lifecycle event writes; review,
   report-package, archive, and AI lineage event commands remain separate append-only workflow
   commands,
17. REST/OpenAPI remains the canonical integration contract; gRPC is not justified for current advisory upstream calls,
18. runtime smoke should honor injected CI DSNs and canonical service identities rather than stale local assumptions,
19. `lotus-idea` proposal-intake receipt must remain source-safe: Advise acknowledges only the
   handoff envelope through trusted local/dev caller headers and durably retains its intake
   idempotency decision plus its explicit producer-authorized portfolio identity. A changed
   portfolio under the same scoped key must conflict; Advise must not infer scope or claim that
   local/dev headers prove production portfolio entitlement. Advise retains proposal, suitability,
   approval, publication, and execution authority until a later certified realization slice creates
   advisory review work and publishes source-owned outcome evidence. Production IdP binding remains
   deferred,
20. outbound `lotus-report` and `lotus-ai` calls must fail closed when tenant or actor identity is
   missing, malformed, over-length, or control-character-bearing; do not reintroduce synthetic
   production defaults such as a hardcoded tenant or service actor,
   and retryable proposal-memo AI commentary must forward the opaque Advise-derived
   business-operation identity as the Lotus AI workflow-pack `idempotency_key`. A retry after an
   acknowledged AI response but before local memo-event persistence must receive the original AI
   request/run lineage; it must not create replacement generated content. The raw caller key must
   not cross the service boundary,
21. policy-control write routes must resolve `PolicyControlPrincipal` at the API boundary before
    application commands run through the shared proposal-principal resolver; do not pass
    caller-supplied actor strings into policy-pack or evaluation state transitions unless they
    have been bound to the trusted principal and authorized proposal, portfolio, tenant, and
    legal-entity scope,
22. finalized policy-evaluation workflow receipts must derive `as_of_date` from explicit
    source-owned context, portfolio, or market-data evidence; current clock time, generated-at
    timestamps, request-body dates, and consumer-supplied dates cannot certify producer as-of
    identity. Receipt metadata may expose raw business scope codes such as legal entity,
    booking center, proposal, version, and portfolio ids, but tenant, service, correlation, and
    trace identity must be source-safe hashes,
23. outbound `lotus-report` calls must require source-derived as-of date, reporting currency, and
   jurisdiction/booking-center metadata; proposal memo report-package mapping must consume the
   typed `valuation_context.*.effective_as_of_date` source evidence and reject missing or
   conflicting current/simulated values before HTTP; current-date, USD, and SG fallbacks are not
   production source truth,
24. unavailable `lotus-risk` authority must always carry degraded evidence with a stable reason
   code; do not allow `risk_authority="unavailable"` with `degraded=false`.
25. advisor memo and policy sign-off report packages must not project archive-ready status from
    accepted, running, missing-status, malformed-status, or failed status lookups; terminal
    readiness requires `lotus-report` archive evidence and all non-terminal status must preserve
    the report job id for operator recovery.
26. external service adapters for `lotus-core`, `lotus-risk`, `lotus-report`, and `lotus-ai`
    must keep versioned consumer-contract fixtures under
    `tests/fixtures/external-adapter-contracts/` and pass `make external-adapter-contracts`.
    The lane must cover valid responses, malformed JSON, missing fields, portfolio/as-of identity
    mismatch, partial data, auth failures, timeouts, retry or bounded non-retry posture, duplicate
    or idempotency behavior, provider error mapping, and raw-payload/secret non-leakage.
27. Lotus Core advisory simulation responses must enter Advise through
    `CoreProjectedTransactionEffects`. Core-owned before/after transaction effects, rule results,
    allocation lens, and source lineage are accepted after contract validation; Core-returned
    suitability, workflow gate, decision-summary, alternatives, consent, or next-step fields are
    compatibility evidence only and must not drive Advise advisory decisions.
28. advisory copilot review routes must resolve `CopilotReviewPrincipal` at the API boundary before
    application commands run; do not pass caller-supplied actor strings into review persistence
    unless they have been checked as compatibility echoes against the trusted principal and
    authorized proposal, portfolio, and tenant scope.
29. HTTP boundary controls are centralized in `src/api/http_boundary.py`: trusted host validation,
    deny-by-default CORS, approved security headers, write-payload caps, and enterprise
    audit/authorization denial responses must remain API-layer behavior. Production-like profiles
    must configure `HTTP_BOUNDARY_TRUSTED_HOSTS`; wildcard trusted hosts or wildcard allowed origins
    are not acceptable production posture. TLS termination, WAF/rate limiting, and external identity
    provider integration remain ingress/gateway responsibilities unless a later Advise issue
    deliberately moves a specific control into the service.
30. advisory workspace routes compose through `WorkspaceApplicationService` and explicit workspace
    ports for session persistence, Lotus Core source-context resolution, proposal evaluation, and
    proposal lifecycle handoff. Concrete Lotus Core resolution and the current in-memory workspace
    session store are infrastructure/runtime adapters, not route or use-case implementation
    details. This is an internal design-modularity boundary; durable workspace persistence,
    recovery, and broader idempotency controls remain separately governed backlog work. A dedicated
    `workspace` Postgres migration namespace now defines the durable schema foundation for sessions,
    saved versions, events, and idempotency evidence, and `src/infrastructure/workspace/postgres.py`
    contains the durable repository adapter. Runtime validation requires
    `WORKSPACE_STORE_BACKEND=POSTGRES`; the process-local adapter remains a non-release/test
    adapter, while broader idempotency controls and live multi-instance recovery drills remain
    separately governed hardening work.
31. direct/stateless proposal and workspace contexts must preserve an explicit reference-model or
    source-owned lifecycle date and otherwise publish `as_of: null`; no current-date fallback may
    appear beside unavailable typed valuation evidence. Stateful Lotus Core context remains required
    to provide a resolved source date, and consumers must use nested valuation-context effective
    dates for valuation evidence.

## Repo-Native Commands

Use these commands as the primary local contract:

1. install
   `make install`
2. fast local gate
   `make check`
3. PR-grade local gate
   `make ci`
4. feature-lane local gate
   `make ci-local`
5. Docker parity
   `make ci-local-docker`
6. run locally
   `make run`
7. repo-native domain product gate
   `make domain-data-products-gate`
8. trust telemetry freshness gate
   `make trust-telemetry-freshness-gate`
   CI-backed runtime certification uses `make trust-telemetry-certify` and writes derived snapshots
   to `output/trust-telemetry/runtime/`; it requires immutable Git/run provenance and does not
   rewrite historical committed observations.
9. quality evidence freshness gate
   `make quality-baseline-check`
10. quality trend regression gate
   `make quality-trend-gate` compares the committed baseline report at the merge base of the
   governed base/head revisions and the exact head. The versioned policy blocks more than 200
   added Python lines, any new Radon B-ranked block, any increase in worst Radon complexity, or
   any Interrogate coverage decrease; reviewed exceptions require the exact effective comparison
   `base_sha` (the measured merge base), the deterministic fingerprint of every tracked Python
   blob at the measured head, approver, reason, and expiry. The expiry is deliberate
   approver-controlled debt retirement, not uncontrolled external tool-version drift: it makes
   stale exception debt fail closed on the documented date. Any tracked Python change invalidates
   the exception; the fingerprint avoids a self-referential policy-commit SHA. Evidence is emitted
   to `output/quality-trend-gate.json` with requested/resolved ref SHAs, the comparison pair,
   Python-content fingerprint, and metric deltas. When Main Releasability's `HEAD^` comparison
   follows a rebase merge, the gate may use one matching reviewed exception's original base only
   when that base is an ancestor of the exact head; it records `comparison_base_source` so the
   evidence distinguishes that approved provenance from the supplied merge base.
11. changed-wiki professional-quality gate
   `make wiki-quality-gate` discovers authored Markdown changes under `wiki/` from the governed
   base/head comparison and delegates to the Lotus Platform auditor. Hosted CI uses a pinned
   platform revision. A changed page must
   meet first-screen reader/evidence and command-presentation controls; navigation, rename, or
   deletion changes widen to a full professional-page audit. Missing platform audit source fails
   closed. This is CI/documentation evidence only and does not alter product contracts.
12. dead-code regression gate
   `make dead-code-gate`
   This runs the pinned Vulture scanner against `src` and `scripts`, fails on new or malformed
   findings, and permits only fingerprinted compatibility exceptions with owner, reason, and
   expiry metadata in `quality/dead-code-policy.v1.json`. The policy version ends with a
   content fingerprint; changing policy content without updating that version fails closed.
13. oversized module/function regression gate
   `make oversized-code-gate` scans `src` and `scripts` against the 1,000-line module and
   200-line function thresholds, compares stable fingerprints with
   `quality/oversized-code-baseline.v1.json`, and fails on new, grown, resolved, expired, or
   malformed findings. Baseline entries require owner, reason, expiry, and policy/baseline hash
   provenance; this is CI/developer evidence only and does not change product contracts.
14. proposal decision vocabulary contract
   `make proposal-decision-vocabulary-gate` validates
   `docs/standards/proposal-decision-vocabulary.v1.json` against the Advise-owned
   `src/core/advisory/decision_summary_status_rules.py` and `src/core/common/workflow_gates.py`
   rule owners plus `src/core/common/workflow_gate_vocabulary.py`. It fails with the affected
   decision or workflow pairing when a checked-in consumer-facing artifact drifts; approval
   requirements and gate reasons remain separate runtime evidence fields. The status-rule module
   cross-checks workflow-gate pairings against the runtime gate inverse and derives insufficient-
   evidence next actions from the evidence-gap branch map. Its READY/PENDING_REVIEW/BLOCKED
   projections are intentionally documented as reviewed compatibility declarations because no
   separate runtime producer owns that legacy status family.
15. live demo certification evidence
   `make demo-certification-live`

## Validation And CI Expectations

`lotus-advise` uses explicit CI lanes:

1. `Remote Feature Lane`
2. `Pull Request Merge Gate`
3. `Main Releasability Gate`

Important validation expectations:

1. dependency health, OpenAPI, API vocabulary, producer-owned proposal decision vocabulary, and
   no-alias governance are active,
   and direct dependency freshness is evaluated against the repository-supported Python 3.11
   runtime rather than an incompatible package release that only supports a newer Python line.
   Vulnerability-aware dependency health remains blocking in PR and main lanes; strict
   `--fail-on-outdated` freshness runs in the nightly/manual `Dependency Maintenance` workflow so
   an unrelated upstream release cannot invalidate a feature PR or exact-main evidence,
   while routine Dependabot version-update PRs are paused with
   `open-pull-requests-limit: 0` so dependency suggestions are handled through deliberate
   repo-native refresh, security review, and PR validation instead of noisy bot branches. The API
   vocabulary gate recursively rejects placeholder-shaped generated examples such as `sample_text`,
   `sample_key`, `STANDARD_TEXT`, `STANDARD_ITEM`, `ENTITY_001`, and `example_*`; generated
   inventory examples must come from source-authored metadata or the governed deterministic
   fallback policy, and nullable OpenAPI `anyOf`/`oneOf` schemas must retain their non-null
   business type instead of degrading to generic `object`. OpenAPI display enrichment remains
   available for Swagger readability, but the OpenAPI quality gate treats generated operation
   summaries, descriptions, inferred tags, and generic default error responses as missing
   public-route contract truth,
2. `make external-adapter-contracts` is the named consumer-contract lane for external adapters and
   is included in `make check`; it prevents fake-only adapter tests from drifting away from
   provider-compatible fixtures and adversarial failure-mode evidence,
3. migration rollout-contract validation, migration smoke, coverage, Docker build, Postgres
   runtime smoke, and production-profile guardrail validation are part of the merge gate.
   `make migration-rollout-contract-gate` must stay aligned with
   `src/infrastructure/postgres_migrations`, `scripts/postgres_migrate.py --target all`, and
   production cutover checks so `proposals`, `advisory_copilot`, and `policy_packs` remain covered
   by rollout phase, compatibility-window, lock/online-behavior, backfill, rollback, and rehearsal
   evidence,
4. release-image provenance is part of the repo-native CI contract: `Dockerfile` must carry
   support-safe build args, OCI labels for commit/ref/repo/version/build/run metadata, and runtime
   `/version` parity; `make release-image-provenance-gate` blocks Dockerfile/Makefile drift; Main
   Releasability pushes Git-SHA-tagged images from CI only and retains digest-bearing
   `release-evidence.json`, SBOM, vulnerability scan, signature, and provenance attestation
   artifacts,
5. Bandit security posture is enforced through `make bandit-severity-regression-gate`: high
   findings are blocked, current medium/low findings are accepted only through
   `quality/bandit_security_baseline.v1.json`, and new, stale, expired, or worsened entries fail
   local and CI gates,
6. License/IP posture is enforced through `make license-ip-gate`: runtime and development
   dependency graphs, including transitive packages, must match
   `docs/standards/license-ip-inventory.v1.json` and
   `docs/standards/license-ip-policy.v1.json`; review-required terms need owner-approved expiring
   exceptions before release evidence is green. License/IP inventory generation and validation run
   in a temporary virtual environment installed from the governed runtime/development requirements
   files, constrained to the exact package versions projected from `uv.lock`, with pinned
   pip/setuptools bootstrap tooling and pip isolated from caller configuration, so ambient developer
   or runner packages and upstream transitive releases cannot define release evidence. Transitive
   version-only drift is not a governance event; new packages, license terms, classifications,
   dependency groups, and exception evidence remain blocking,
7. Dependency-lock posture is enforced through `make dependency-lock-gate`: `uv.lock` is the
   generated lock mirror for the current requirements install strategy and must match
   requirement-file hashes plus the license/IP dependency inventory hash,
   and the deptry no-new-regression posture is enforced through `make unused-dependency-gate`
   with `quality/dependency-hygiene-policy.v1.json` and its owner/reason/expiry baseline. New or
   resolved normalized dependency fingerprints, expired entries, tool-version drift, malformed
   reports, and policy/baseline hash drift are blocking in local and GitHub governance lanes;
   oversized-code regression is enforced through `make oversized-code-gate` with the versioned
   threshold/baseline contract described above,
8. Trust telemetry freshness is enforced through `make trust-telemetry-freshness-gate`: committed
   snapshots under `contracts/trust-telemetry/` must derive age, freshness state, and blocking
   posture from observed implementation evidence instead of carrying static `current`/zero-age
   promotion claims,
9. Advisory evidence and telemetry lifecycle inventory is enforced through
   `make advisory-data-lifecycle-gate`: persisted proposal/workspace/copilot evidence, emitted
   logs/traces/metrics, API projections, and downstream `lotus-ai` payload fields must have entries
   in `contracts/data-governance/advisory-evidence-telemetry-field-inventory.v1.json` with purpose,
   classification, owner, allowed consumers, retention/purge, masking, and projection decisions.
   High-cardinality identifiers and business evidence must not become metric labels,
10. Advisory record lifecycle purge decisions are governed by
   `src/core/record_lifecycle/advisory_records.py`: proposal versions, lifecycle events,
   approvals, policy evaluations, report requests, and advisory copilot packet/run/review records
   have explicit retention classes, owner, legal-hold behavior, dependency refusal, append-only
   correction posture, and sanitized purge/hold audit evidence. Do not add jurisdiction-specific
   retention periods without approved bank policy input,
11. proposal async operation support tooling is governed by
   `src/core/proposals/async_operation_control_plane.py`: list filters are bounded, pending,
   leased, stuck, retry-exhausted, quarantined, and terminal states are explicitly classified,
   retry/quarantine/dry-run/pause-drain decisions require the trusted
   `advisory.proposals.async_operations.control` capability, active leases fail closed, retry
   exhaustion cannot be bypassed by payload or attempt mutation, and audit evidence hashes raw
   operation, correlation, proposal, actor, service identity, idempotency, and reason values,
12. durable state recovery is governed by
   `docs/standards/advisory-durable-state-recovery.v1.json` and
   `make durable-state-recovery-gate`: the contract must match checked-in PostgreSQL migration
   namespaces, preserve RTO 30 minutes and RPO 15 minutes, inventory owner/retention/backup scope,
   define restore checks and replay quarantine rules, and emit
   `output/durable-state-recovery/recovery-drill-evidence.json` for non-production restore drills.
   Advise owns service-specific integrity/replay/quarantine evidence; platform database operations
   own backup vendor, encrypted backup retention, point-in-time restore execution, and cross-region
   database controls,
13. advisory workflow changes should be validated against canonical upstream posture,
14. live runtime evidence should prove decision-summary and proposal-alternatives posture on canonical and degraded paths when advisory proposal behavior changes materially,
15. `make demo-certification-live` is the repo-native app-level live certification command; it writes
   machine-readable evidence under `output/demo-certification/`, validates deterministic synthetic
   scenarios, route-safety posture, required `/platform/capabilities` feature/workflow truth, and
   domain assertions, and is wired into the scheduled/manual Postgres runtime workflow as uploaded
   evidence rather than a PR-blocking static gate,
16. `/platform/capabilities` is deployment-scoped informational discovery. It must not accept,
   trust, echo, or imply tenant-specific entitlement policy unless a future slice adds an explicit
   authoritative entitlement port and contract tests,
17. committed quality Markdown intentionally omits volatile branch/head metadata; exact Git identity belongs to Git history and GitHub Actions run metadata, while `make quality-baseline-check` enforces non-timestamp report freshness,
18. HTTP boundary changes should run focused API tests covering host/origin policy, approved
    security headers, validation-error responses, and enterprise denial responses before broader
    merge-gate validation.
19. `/platform/capabilities` publishes known Lotus integration boundaries with explicit
    `required_by_enabled_capability` posture. Only dependencies declared by enabled features or
    workflows degrade deployment-wide readiness and supportability; optional unconfigured
    dependencies remain visible and use `readiness_basis=not_configured` without degrading the
    contract. A future feature or workflow must declare its dependency key before that dependency
    becomes required.
20. PR coverage quality retains the aggregate 97% floor and additionally enforces the versioned
    `quality/quality-policy.v1.json` changed-source threshold through
    `scripts/changed_coverage_gate.py`. The gate compares the pull request base/head, or
    `origin/main` and the selected checkout SHA for a manual PR Merge Gate dispatch, reports every
    changed executable source lines under `src/` with measured and threshold percentages, and emits
    `output/changed-coverage-gate.json`; it has no exceptions in this initial slice. Diff parsing is
    fail-closed: supported hunk shapes are validated for new-line counts, and malformed Python
    hunks produce failed machine-readable evidence rather than an empty 100% measurement. Manual
    dispatches log and resolve the event-aware comparison refs before running the trend gate so
    missing pull-request fields cannot silently produce an unbound quality comparison.
21. CI-local Docker execution is isolated from the product runtime: `make ci-local-docker`,
    `make ci-local-docker-down`, and `scripts/run_runtime_smoke_checks.py` use the same
    checkout-specific `CI_LOCAL_COMPOSE_PROJECT` identity, derived from the absolute checkout path
    unless an orchestrator supplies an explicit, unique CI-owned override. Cleanup must remain
    scoped to that project and callers must verify the health of any shared product runtime
    afterward; arbitrary overrides are not collision-safe. The CI-local image includes the pinned
    Node `22.14.0` runtime used by the workflow Spectral gate, and OpenAPI tooling must fail closed
    when that executable is unavailable. Docker-local CI mounts the central Platform contract tree
    read-only at `/lotus-platform` from `LOTUS_PLATFORM_ROOT` (default `../lotus-platform`) and
    all repo-native domain-product source checkouts at their canonical `/lotus-*` paths from
    `LOTUS_REPOSITORIES_ROOT` (default `..`) so domain-data-product validation and trust-telemetry
    catalog generation use the same federated source topology as the host lane rather than
    silently omitting or inventing upstream declarations.
22. duplicate-code quality is enforced by `make duplicate-code-gate` using the pinned jscpd
    `5.0.16` scanner in strict mode across `src` and `scripts`, with 100-token/10-line minimums.
    The committed baseline contains stable clone fingerprints and explicit owner, reason, expiry,
    and content-hash provenance; new or resolved fingerprints, scanner/parser failures, and
    baseline/policy integrity drift fail closed. This is CI/developer evidence only and does not
    change runtime, API, persistence, migration, or data-model contracts.

## Standards And RFCs That Govern This Repository

Most relevant current governance:

1. `../lotus-platform/rfcs/RFC-0066-lotus-advise-to-lotus-advise-and-lotus-manage-split.md`
2. `../lotus-platform/rfcs/RFC-0067-centralized-api-vocabulary-inventory-and-openapi-documentation-governance.md`
3. `../lotus-platform/rfcs/RFC-0072-platform-wide-multi-lane-ci-validation-and-release-governance.md`
4. `../lotus-platform/rfcs/RFC-0073-lotus-ecosystem-engineering-context-and-agent-guidance-system.md`
5. `../lotus-platform/rfcs/RFC-0082-lotus-core-domain-authority-and-analytics-serving-boundary-hardening.md`
6. `docs/architecture/RFC-0082-upstream-contract-family-map.md`
7. `docs/architecture/RFC-0086-repo-native-domain-product-onboarding.md`
8. `docs/standards/`

## Known Constraints And Implementation Notes

1. advisory and management boundaries must remain explicit after the repository split,
2. runtime smoke orchestration is operationally important here because CI includes real environment behavior, not just unit logic,
3. proposal behavior must not drift away from upstream data and risk authorities,
4. persisted proposal versions are expected to preserve the exact decision summary and proposal alternatives used by artifact, replay, workspace, and operator evidence surfaces,
5. proposal alternatives remain opt-in, bounded, and dependent on canonical upstream authorities; unsupported objectives must reject explicitly rather than degrade into guessed behavior,
6. restricted-product alternatives remain deferred until canonical eligibility evidence is available,
7. advisory stateful context operational reads, advisory simulation execution, and enrichment fallback labels remain RFC-0082 watchlist surfaces,
8. RFC-0086 consumer declarations should stay conservative and only reference upstream products
   already approved and truthfully mapped in the current platform catalog,
9. advisory lifecycle changes should update both code and repo context in the same slice,
10. tactical house-view cohort changes should preserve the Advise/Manage boundary: Advise owns
   source cohort evaluation; Manage owns DPM workflows, campaigns, policies, and evidence,
11. repo-local `wiki/` content should stay concise, operator-focused, and derived from repo truth rather
   than duplicating the full `docs/` tree.

## Context Maintenance Rule

Update this document when:

1. advisory workflow ownership or lifecycle scope changes,
2. repo-native commands or runtime smoke behavior changes,
3. upstream integration posture changes materially,
4. guardrail or production-profile expectations change,
5. RFC-0082 contract-family classification changes,
6. current-state rollout posture changes,
7. wiki ownership or publication workflow changes.

## Cross-Links

1. `../lotus-platform/context/LOTUS-QUICKSTART-CONTEXT.md`
2. `../lotus-platform/context/LOTUS-ENGINEERING-CONTEXT.md`
3. `../lotus-platform/context/CONTEXT-REFERENCE-MAP.md`
4. `../lotus-platform/context/Repository-Engineering-Context-Contract.md`
5. [Lotus Developer Onboarding](../lotus-platform/docs/onboarding/LOTUS-DEVELOPER-ONBOARDING.md)
6. [Lotus Agent Ramp-Up](../lotus-platform/docs/onboarding/LOTUS-AGENT-RAMP-UP.md)
