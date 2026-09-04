# Integrations

## Current Scope

This page summarizes implementation-backed upstream and downstream integration contracts for
`lotus-advise`. It is operator and engineering guidance for supported advisory workflows; it is not
a roadmap, client-publication claim, or substitute for provider-owned API documentation.

| Reader | Use this page for | Evidence posture |
| --- | --- | --- |
| Engineering | Adapter ownership, runtime-composed ports, cache identity, and source-boundary rules | Backed by code, adapter tests, and repo-native gates |
| Operations | Environment bindings, degraded states, and support-safe failure behavior | Backed by current runbook and integration tests |
| Product and support | Which upstreams are authoritative for advisory behavior and which claims remain out of scope | Backed by repository context and supported-feature posture |

## Current Upstream Posture

`lotus-advise` follows the upstream contract-family map documented in RFC-0082.

## Runtime Composition Ports

Core advisory and proposal modules depend on Advise-owned ports, not concrete integration
adapters. Runtime startup wires the production providers for Lotus Core simulation/context, Lotus
Risk enrichment and dependency-state, Lotus AI narrative/memo workflow packs, and Lotus Report memo
package requests. Tests should use deterministic port doubles rather than monkeypatching HTTP
adapters into core orchestration.

Provider-specific exceptions must be translated at the runtime adapter boundary. Core logic sees
typed Advise unavailable outcomes and attaches stable authority/degraded evidence for downstream
proposal, workspace, memo, and operator surfaces.

## Consumer Contract Certification

External service adapters must keep provider-compatible fixture evidence in
`tests/fixtures/external-adapter-contracts/lotus-advise-external-adapter-contracts.v1.json`.
Run `make external-adapter-contracts` after changing `lotus-core`, `lotus-risk`, `lotus-report`,
or `lotus-ai` adapter behavior. The lane requires every adapter to cover valid responses,
malformed JSON, missing fields, portfolio/as-of identity mismatch, partial data, auth failures,
timeouts, retry or bounded non-retry posture, duplicate/idempotency behavior, provider error
mapping, and raw-payload/secret non-leakage with references to real regression tests.

## `lotus-core`

Current governed usage includes:

- advisory simulation execution
- portfolio reads
- positions reads
- cash balance reads
- instrument reference reads
- price reads
- FX reads
- enrichment-bulk support
- classification taxonomy support

Environment bindings:

- `LOTUS_CORE_BASE_URL`
- `LOTUS_CORE_QUERY_BASE_URL`

Important rule:

- simulation execution authority lives on the control-plane binding
- query reads do not substitute for execution authority
- stateful proposal context first consumes Core's governed
  `POST /integration/portfolios/{portfolio_id}/core-snapshot` contract as
  `PortfolioStateSnapshot:v1`. The request carries the deployment-owned tenant identity in both
  the governed payload and `X-Tenant-Id`; Advise identifies itself as the service consumer.
- stateful context reads must reject returned portfolio, positions, cash, or resolved-as-of identity
  that conflicts with the requested source identity before advisory snapshots are built or cached
- advisory lineage preserves Lotus Core portfolio and market-data source provenance as typed
  metadata from `PortfolioStateSnapshot:v1`: stable snapshot identity, source-owned effective date,
  source hash, valuation timestamp, and freshness posture. Advise accepts only current evidence with
  `READY` / `SOURCE_EVIDENCE_READY` valuation supportability and coherent portfolio and market-data
  dates, never a future effective date. The separate portfolio, positions, and cash reads continue
  to supply simulation input rows; identical source identities and hashes must fence those reads
  before and after so concurrent Core revision changes fail closed. Component reads cannot
  manufacture or override authoritative provenance. Missing, stale, malformed, drifting, or
  conflicting snapshot evidence fails closed before construction, cache writes, persistence, or
  replay. Raw Lotus Core payloads are never stored in proposal lineage.
- source-derived FX rates must be finite, strictly positive, and as-of eligible before valuation.
  Explicit invalid rates or source ratios fail closed with `LOTUS_CORE_STATEFUL_FX_INVALID`.
  Future-only FX lookup rows are not selected, and missing eligible FX remains bounded
  data-quality evidence rather than a fabricated conversion rate.
- stateful source-row completeness is evaluated before advisory snapshots are constructed. Required
  malformed positions, cash balances, prices, or FX source rows fail closed with
  `LOTUS_CORE_STATEFUL_SOURCE_INCOMPLETE`; optional enrichment and classification taxonomy gaps are
  carried as degraded completeness evidence on resolved context and proposal lineage without raw
  source payload storage.
- stateful context resolution is selected through an explicit runtime-composed port. API startup
  registers the production Lotus Core resolver through the Advise-owned context port; integration
  modules must not discover `src.api.main`, read `sys.modules`, or rely on FastAPI import order for
  resolver behavior.

Cache policy:

- stateful context, enrichment, taxonomy, instrument, price, and FX caches are short-lived,
  process-local `TimedCache` instances
- cache TTL defaults to 15 seconds and is configured with
  `LOTUS_CORE_STATEFUL_CONTEXT_CACHE_TTL_SECONDS`; setting it to `0` disables reuse
- cache size defaults to 128 entries and is configured with
  `LOTUS_CORE_STATEFUL_CONTEXT_CACHE_MAX_SIZE`; oldest entries are evicted when the limit is reached
- keys are built through `stateful_context_cache_identity.py` and include sanitized source URL,
  environment, tenant, contract version, portfolio, as-of, mandate, benchmark, reporting currency,
  current look-through/allocation/risk defaults, and lookup-specific identifiers
- invalidation is TTL, size eviction, process restart, or explicit test reset only; production code
  must not clear one scope to work around missing key dimensions
- cache diagnostics expose hit, miss, write, expiration, eviction, and size counters without raw
  source payloads

## `lotus-risk`

Current governed usage includes:

- concentration and risk-lens enrichment for proposal alternatives and readiness posture

Environment binding:

- `LOTUS_RISK_BASE_URL`
- `LOTUS_RISK_TIMEOUT_SECONDS`
- `LOTUS_RISK_RETRY_ATTEMPTS`
- `LOTUS_RISK_RETRY_BACKOFF_SECONDS`

Operational behavior:

- transient `5xx`, `429`, and network failures are retried with bounded attempts
- `4xx` contract or request failures are not retried
- retry attempts default to `2` and are capped at `5`
- retry backoff defaults to `0.1` seconds and is capped at `2.0` seconds
- response metadata must not contradict the requested portfolio identity or resolved stateful
  as-of date when those fields are present
- unavailable risk authority always carries degraded evidence; dependency-state failures use
  `LOTUS_RISK_DEPENDENCY_UNAVAILABLE`, while configured enrichment failures use
  `LOTUS_RISK_ENRICHMENT_UNAVAILABLE`
- risk enrichment is selected through the Advise-owned runtime port, and provider-specific Lotus
  Risk errors are translated before core orchestration handles degraded authority.

## `lotus-performance`

Current posture:

- readiness dependency only
- not a current advisory source-data input

If advisory behavior later depends on performance analytics, that dependency should be classified explicitly instead of being inferred through another service.

## `lotus-manage`

Current governed usage includes:

- downstream consumption of `TacticalHouseViewAffectedCohort:v1`

Boundary rule:

- `lotus-advise` evaluates affected-cohort membership for supplied source-backed candidates
- `lotus-manage` owns discretionary portfolio-management campaigns, policies, rebalance workflows,
  and execution evidence

## `lotus-idea`

Current governed usage includes:

- downstream consumption of Advise data-product posture as opportunity-intelligence evidence
- source-safe conversion intake and scoped realization read through
  `POST /advisory/proposals/idea-intake` and
  `GET /advisory/proposals/idea-intake/{intake_id}/realization`
- read-only recovery after a lost intake response through scoped Idea-owned conversion identity at
  `GET /advisory/proposals/idea-intake/realization?conversion_intent_id={conversion_intent_id}`
- explicit same-portfolio proposal linkage and authoritative outcome reconciliation through
  `POST /advisory/proposals/idea-intake/{intake_id}/realization/proposal-reconciliation`
- downstream reconciliation of policy-evaluation workflow receipts with Advise-produced
  source-owned as-of identity, trusted legal-entity/booking-center/proposal/version/portfolio scope,
  and source-safe tenant/service/correlation/trace hashes

Boundary rule:

- `lotus-idea` owns idea candidates and conversion-intent evidence
- `lotus-advise` owns advisory proposal lifecycle, suitability, approval, and client-publication
  authority
- policy-evaluation receipt identity lets `lotus-idea` verify producer evidence without substituting
  consumer request dates, caller-generated lineage, or raw tenant/correlation/trace identifiers
- accepted review intent creates one deterministic Advise-owned adviser-review work item and initial
  source-owned outcome; rejected-before-work intent creates no work item
- transport acceptance never means proposal acceptance, suitability, mandate action, report
  completion, execution success, or client publication
- an existing Advise proposal is linked only through explicit compare-and-set reconciliation;
  non-terminal proposal states remain `PROPOSAL_LINKED`, while terminal outcomes come only from
  authoritative `REJECTED`, `CANCELLED`, `EXPIRED`, or `EXECUTED` proposal state
- `ADVISORY_COMPLETED` closes the Advise proposal realization but does not independently prove an
  external order, fill, or settlement
- this boundary remains `not_certified`; it uses trusted local/dev caller headers and does not
  auto-create proposals, create orders, bind production IdP claims, or promote a supported feature

```mermaid
flowchart LR
    I[Idea candidate and conversion intent] -->|scoped POST| A[Advise intake claim]
    A -->|accepted review intent| W[Durable adviser-review work]
    A -->|unsupported intent| R[Rejected-before-work outcome]
    W --> O[Accepted-for-review outcome]
    O -->|explicit same-portfolio link| P[Advise proposal]
    P -->|authoritative state| T[Linked or terminal Advise outcome]
    T -->|source-owned reconciliation| I[Idea outcome posture]
    H[HTTP success or timeout] -. never business outcome .-> I
```

## `lotus-report`

Current usage:

- report-request integration boundary for Lotus-branded advisory outputs

Boundary rule:

- report ownership stays outside `lotus-advise`
- report submissions require bounded trusted tenant and actor identity; unsafe or absent identity
  fails closed before HTTP submission
- report submissions require source-derived as-of date, reporting currency, and jurisdiction; the
  mapper does not manufacture current-date, USD, or SG fallbacks
- memo and policy sign-off report packages use bounded status retrieval before projecting
  readiness. `ARCHIVED` is returned only from terminal report-owned archive evidence; accepted,
  running, missing-status, malformed-status, and status-lookup failures stay explicit pending or
  unavailable postures with the report job id preserved for recovery.
- downstream idempotency echoes must match the Advise report request id when the provider returns
  an idempotency key; mismatches fail closed.
- request overrides are selected through explicit runtime-composed requester ports registered by
  API startup. The adapter must not discover API-module globals or depend on FastAPI import order
  to choose portfolio-review, memo package, or policy sign-off package request behavior. Core memo
  orchestration calls the Advise-owned memo report-package port.

## `lotus-ai`

Current implemented usage:

- workspace-rationale integration boundary
- proposal narrative, proposal memo, policy-evidence, advisory-copilot, and workspace-rationale
  workflow-pack calls use the same trusted tenant envelope

Boundary rule:

- AI may assist with grounded rationale generation
- AI must not become the authority for suitability, approvals, trade generation, or proposal alternatives
- AI workflow-pack calls require `LOTUS_ADVISE_TENANT_ID`; unsafe or absent tenant identity fails
  closed before HTTP submission
- app-local Compose supplies the canonical developer tenant fixture `tenant-sg-001` only for
  standalone and Workbench-orchestrated local startup; production Compose requires deployment-owned
  tenant configuration
- proposal narrative and memo AI calls are selected through Advise-owned ports. Lotus AI adapter
  errors are translated into core unavailable outcomes before proposal narrative or memo
  orchestration handles fallback posture.
- keyed proposal-memo AI commentary derives one opaque downstream identity from the Advise memo
  operation, proposal, memo, and caller key, then sends it as the Lotus AI workflow-pack
  `idempotency_key`. If AI succeeds but the local append-only memo event is not persisted, a retry
  with the original Advise key and payload receives Lotus AI's retained original request/run
  lineage. A changed payload remains an Advise `409` conflict before another AI request, and the
  raw caller key is not disclosed downstream. Calls without an Advise idempotency key retain the
  existing one-request/one-run compatibility posture.
