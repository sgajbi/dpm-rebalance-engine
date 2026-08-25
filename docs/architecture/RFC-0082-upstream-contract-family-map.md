# RFC-0082 Upstream Contract Family Map

This document records how `lotus-advise` consumes upstream Lotus services under `lotus-platform`
RFC-0082.

`lotus-advise` owns advisory workflow, proposal simulation orchestration, proposal lifecycle state,
decision summary persistence, proposal alternatives, approval posture, consent-related workflow
behavior, and advisory execution readiness. It does not own canonical portfolio source data,
performance analytics, or risk analytics.

## Current Integration Posture

1. REST/OpenAPI remains the governed integration contract for current `lotus-advise` upstream calls.
2. No current advisory integration requires or justifies gRPC.
3. `lotus-core` remains the source-data and simulation-execution authority for advisory proposal
   context.
4. `lotus-risk` remains the risk methodology authority for advisory risk-lens enrichment.
5. `lotus-performance` is currently a published integration boundary only; `lotus-advise` does
   not consume performance analytics data as an input contract. When it is unconfigured and no
   enabled feature or workflow declares it, Advise publishes that optional posture without
   degrading deployment-wide readiness or supportability.

## `lotus-core` Contract Family Map

| Advise integration surface | Upstream route | RFC-0082 family | Advise use | Boundary rule |
| --- | --- | --- | --- | --- |
| advisory simulation execution client | `/integration/advisory/proposals/simulate-execution` | Control Execution / advisory simulation | execute proposal simulation through core-governed state and execution semantics | do not duplicate core simulation or execution readiness semantics locally |
| stateful context portfolio load | `GET /portfolios/{portfolio_id}` | Operational Read | proposal context source data | do not infer analytics conclusions from operational reads |
| stateful context positions load | `GET /portfolios/{portfolio_id}/positions` | Operational Read | holdings context for proposal construction | keep valuation and source attribution aligned to core |
| stateful context cash balance load | `GET /portfolios/{portfolio_id}/cash-balances` | Operational Read | cash context for proposal construction | preserve source-owned cash methodology; use the strategic HoldingsAsOf balance route rather than deprecated reporting convenience shapes |
| stateful context instrument load | `GET /instruments/` | Operational Read | instrument reference support | source attributes remain core-owned |
| stateful context price load | `GET /prices/` | Operational Read | market price support for advisory context | price authority remains core-owned |
| stateful context FX load | `GET /fx-rates/` | Operational Read | currency conversion support for advisory context | FX authority remains core-owned |
| stateful context enrichment load | `POST /integration/instruments/enrichment-bulk` | Analytics Input watchlist | enrichment context for proposal construction | enrichment semantics remain upstream; local fallback labels are not authoritative analytics |
| stateful context classification taxonomy load | `POST /integration/reference/classification-taxonomy` | Analytics Input watchlist | governed instrument classification labels for proposal shelf construction | use effective-dated core taxonomy labels where available; expose `UNKNOWN` plus supportability attributes when upstream labels are missing from the governed taxonomy |
| benchmark assignment evidence (not currently consumed) | `POST /integration/portfolios/{portfolio_id}/benchmark-assignment` | Analytics Input | future source-owned benchmark evidence mapping for proposal review | the Core route exists, but Advise does not consume it; a future adapter must map source references and effective dating into the typed evidence envelope rather than treating the requested selector as applied evidence |

### Source Effects And Advisory Decision Ownership

`lotus-core` v1 can still return legacy advisory decision-shaped fields on the simulation route.
`lotus-advise` treats those fields as compatibility evidence only. The adapter maps the response
into `CoreProjectedTransactionEffects`, then recomputes advisory suitability, gate, decision
summary, alternatives, and next-step posture inside Advise.
When Core v1 includes decision-shaped fields, Advise emits `core_decision_parity` to classify
match versus mismatch for migration review without treating Core as decision authority.

| Field family | Authority | Advise handling |
| --- | --- | --- |
| before-state, after-state, intents, reconciliation, rule results, allocation lens, typed requested/effective valuation context, source lineage | `lotus-core` source-effects authority | Accepted through `CoreProjectedTransactionEffects` after contract-version validation; Advise preserves source dates/currencies as typed evidence and never infers missing valuation facts. |
| requested benchmark/mandate selectors and proposal-review evidence envelope | Requested selectors: Advise context; effective benchmark evidence: existing Core benchmark-assignment route not currently consumed by Advise; mandate-limit evidence: authoritative upstream producer not yet mapped | Advise preserves requested selectors and emits typed `UNAVAILABLE` effective evidence with null effective values; it must not treat selectors or generic `rule_results` as applied benchmark or mandate-limit evidence. |
| suitability issues, recommended suitability gate, workflow gate, proposal decision summary, proposal alternatives, advisory next step, consent posture | `lotus-advise` advisory-decision authority | Recomputed by Advise policy modules; any Core-returned values are retained only under `non_authoritative_core_decisions` and classified under `core_decision_parity` for migration review. |
| risk-lens enrichment and concentration methodology | `lotus-risk` risk authority | Attached by the risk adapter; missing risk authority remains degraded evidence, not a local risk calculation. |

Environment binding:

1. `LOTUS_CORE_BASE_URL` is the lotus-core control-plane base URL for advisory simulation execution
   and control-plane enrichment routes.
2. `LOTUS_CORE_QUERY_BASE_URL` is the lotus-core query-plane base URL for operational portfolio,
   position, cash, price, instrument, and FX reads.
3. Stateful context enrichment uses the control-plane base URL for
   `/integration/instruments/enrichment-bulk`; query reads must not be reused for this route.
4. Stateful context classification taxonomy uses the control-plane base URL for
   `/integration/reference/classification-taxonomy`; taxonomy absence must remain visible as bounded
   supportability fallback, not local classification authority.
5. Advisory simulation must fail closed when only `LOTUS_CORE_QUERY_BASE_URL` is configured; query
   reads are not an execution authority for `/integration/advisory/proposals/simulate-execution`.

## `lotus-risk` Contract Family Map

| Advise integration surface | Upstream route | Authority | Advise use | Boundary rule |
| --- | --- | --- | --- | --- |
| risk enrichment client | `/analytics/risk/concentration` | `lotus-risk` risk analytics authority | concentration and risk-lens enrichment for proposal alternatives | no local duplicated concentration methodology or risk conclusion generation |

## `lotus-performance` Posture

`lotus-advise` currently publishes `lotus-performance` dependency readiness, but it does not
consume performance analytics as proposal source data. Its unconfigured `not_configured` row is
marked `required_by_enabled_capability=false`, so optional absence is visible without becoming a
deployment-wide degraded signal. If advisory proposal behavior later depends on performance
analytics, the enabled feature or workflow must declare `lotus-performance` explicitly; the same
row then becomes required and an unavailable dependency degrades readiness and supportability.
Advise should consume `lotus-performance` as the analytics authority rather than sourcing
performance conclusions from `lotus-core` operational reads.

## Conformance Rules

1. Advisory workflows may evaluate proposal intent, suitability posture, alternatives, approvals, and
   workflow readiness.
2. Advisory workflows must not become the source of portfolio valuation, performance attribution, risk
   concentration, benchmark methodology, or reporting methodology.
3. Local fallback or derivation behavior must be bounded, explicitly supportability-oriented, and never
   presented as an authoritative replacement for core or risk output.
4. Typed proposal valuation context must distinguish requested values from effective source values;
   missing or mismatched dates/currencies remain partial, restricted, or unavailable evidence.
5. Requested valuation-context dimensions must be populated only from explicit caller input; a
   portfolio base currency must not be relabeled as a requested reporting currency.
6. `ProposalResolvedContext.as_of` and normalized replay-context `as_of` are optional lifecycle
   evaluation/replay/routing values, not authoritative valuation evidence. Direct/stateless requests
   without an explicit reference-model or source-owned date keep them null; no current-date fallback
   is permitted. Consumers must use the nested `valuation_context` effective date, which stays null
   when trusted source provenance is unavailable. When both requested date and currency are not
   honored, the single v1 `reason_code` is the primary date reason rather than a complete mismatch
   list.
7. Proposal alternatives must remain anchored to canonical `lotus-core` simulation and `lotus-risk`
   enrichment.
8. New upstream source-data consumption must be classified into an RFC-0082 family before becoming a
   stable advisory contract.
9. Transport optimization discussions start with retrieval shape, payload size, caching, and upstream
   contract design. gRPC is not a default answer for advisory integration.

## Current Evidence

Existing tests that cover this posture include:

1. `tests/unit/advisory/api/test_lotus_core_stateful_context.py`
2. `tests/unit/advisory/api/test_lotus_core_simulation_client.py`
3. `tests/unit/advisory/api/test_lotus_core_runtime_config.py`
4. `tests/unit/advisory/api/test_lotus_risk_enrichment_client.py`
5. `tests/integration/advisory/api/test_proposal_api_workflow_integration.py`
6. `tests/e2e/live/test_cross_service_parity_live.py`
7. `tests/e2e/live/test_degraded_runtime_live.py`
8. `tests/e2e/live/test_live_runtime_suite.py`

The source-effects ownership hardening is covered by focused adapter tests that prove Core
suitability and gate payloads are quarantined as non-authoritative compatibility evidence while
Advise-owned decision support is recomputed locally.
Curated simulation parity scenarios and the canonical `PB_SG_GLOBAL_BAL_001` private-banking request
example also replay stale Core v1 decision fields through the source-effects contract and assert the
Advise-owned output remains authoritative while `core_decision_parity` records every mismatch.

## Core Simulation Compatibility Retirement

`lotus-advise` preserves the existing public proposal simulation response shape while Core still
publishes the v1 simulation contract. The v1 consumer path accepts Core source effects, quarantines
legacy Core decision-shaped fields under `non_authoritative_core_decisions`, and records
`core_decision_parity` for migration review.

Advise must not delete the v1 compatibility quarantine until the Core producer closes the linked
source-contract work:

1. `sgajbi/lotus-core#470` contains advisory decisioning so Core remains source-data focused.
2. `sgajbi/lotus-core#709` projects transaction economics through Core-owned transaction semantics.
3. `sgajbi/lotus-core#710` pins source baseline, content hash, freshness, and replay lineage.

Cutover requires a Core source-effects-only v2 contract fixture, updated Advise adapter contract
fixtures, successful dual-run parity over the curated and `PB_SG_GLOBAL_BAL_001` cases, and remote
feature-lane evidence. Rollback keeps the v1 quarantine path enabled; no Advise fallback may invent
missing Core source facts.

## Gap Register

1. Advisory stateful context still uses multiple operational reads. If the access pattern grows into a
   bulk analytics input, prefer a governed `lotus-core` snapshot or analytics-input contract over
   additional convenience reads.
2. `/integration/advisory/proposals/simulate-execution` should remain visible in the RFC-0082 watchlist
   because it is advisory-specific control execution rather than a generic read model.
3. Enrichment and classification fallback labels in advisory context should stay
   supportability-only and must not expand into local risk, liquidity, or suitability methodology.
   This now applies to both held-position context resolution and non-held trade-draft hydration; do
   not let draft enrichment bypass the governed classification taxonomy.
4. If proposal simulation becomes latency-constrained, tune source-data shape, simulation payloads,
   caching, and upstream query design before considering a transport change.

## Validation Lane

This document is governed as Feature Lane documentation and contract proof. Escalate to PR Merge Gate
only when a future slice changes advisory runtime behavior, public API contracts, or upstream coupling.
