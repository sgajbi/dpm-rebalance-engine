# Advisory Proposal Engine Know-How

Implementation scope:
- API: `src/api/main.py` (`/advisory/proposals/simulate`)
- API: `src/api/main.py` (`/advisory/proposals/artifact`)
- API router package: `src/api/proposals/` (`/advisory/proposals` lifecycle family)
- API router package: `src/api/workspaces/` (`/advisory/workspaces` workspace session, draft action, and re-evaluation contract)
- Models: `src/core/models.py`
- Workspace models: `src/core/workspace/models.py`
- Artifact models: `src/core/advisory/artifact_models.py`
- Proposal lifecycle domain:
  - `src/core/proposals/models.py`
  - `src/core/proposals/service.py`
  - `src/core/proposals/repository.py`
- Proposal lifecycle persistence adapter:
  - `src/infrastructure/proposals/in_memory.py`
  - `src/infrastructure/proposals/postgres.py`
- Core orchestration: `src/core/advisory_engine.py` (`run_proposal_simulation`)
- Advisory modular internals:
  - `src/core/advisory/ids.py` (deterministic run id generation)
  - `src/core/advisory/intents.py` (proposal cash/trade intent construction helpers)
  - `src/core/advisory/funding.py` (RFC-0008 auto-funding planner)
  - `src/core/advisory/artifact.py` (RFC-0011 artifact builder)
- Shared simulation primitives: `src/core/common/simulation_shared.py`
- Shared intent dependency linker: `src/core/common/intent_dependencies.py`
- Shared diagnostics builders: `src/core/common/diagnostics.py`
- Shared deterministic canonical serialization/hash: `src/core/common/canonical.py`
- Shared workflow gate evaluator: `src/core/common/workflow_gates.py`
- Shared advisory analytics:
  - `src/core/common/drift_analytics.py` (RFC-0009 drift analytics)
  - `src/core/common/suitability.py` (RFC-0010 suitability scanner)
- Valuation: `src/core/valuation.py`
- Rules: `src/core/compliance.py`

## API Surface

### `POST /advisory/proposals/simulate`
- Purpose: simulate advisor-entered manual cash flows and manual security trades.
- Required header: `Idempotency-Key`
- Optional header: `X-Correlation-Id` (generated when missing)
- Output: `ProposalResult` with status `READY | PENDING_REVIEW | BLOCKED`
- Unhandled errors: `500` with `application/problem+json` payload.
- Idempotency behavior:
  - same key + same canonical payload: cached response
  - same key + different canonical payload: `409 Conflict`

### `POST /advisory/proposals/artifact`
- Purpose: run proposal simulation and build deterministic advisory proposal package.
- Required header: `Idempotency-Key`
- Optional header: `X-Correlation-Id` (generated when missing)
- Output: `ProposalArtifact`
- Idempotency behavior:
  - Uses the same proposal simulation idempotency cache/hash behavior as `/advisory/proposals/simulate`.
  - Same key + different canonical payload returns `409 Conflict`.

Authority orchestration note:
- advisory proposal evaluation now routes through explicit Lotus authority seams
- `lotus-core` is the normal runtime simulation authority through the versioned canonical contract
- `lotus-risk` may provide risk enrichment authority when configured
- local evaluation is retained only as a controlled non-production fallback and test oracle in
  local/dev/test-style environments, and the response explanation includes
  `authority_resolution` metadata showing which authorities were used and whether fallback
  degradation occurred
- unavailable `lotus-risk` authority always sets `authority_resolution.degraded=true` with a
  stable reason code. Dependency-state failures use `LOTUS_RISK_DEPENDENCY_UNAVAILABLE`; configured
  enrichment failures use `LOTUS_RISK_ENRICHMENT_UNAVAILABLE`.

### `POST /advisory/proposals`
- Purpose: run simulation+artifact and persist proposal aggregate/version/workflow event.
- Required header: `Idempotency-Key`
- Optional header: `X-Correlation-Id`
- Output: `ProposalCreateResponse`
- Idempotency behavior:
  - same key + same canonical request: returns same proposal/version
  - same key + different canonical request: `409 Conflict`
  - preserved legacy records may replay when the proposal and narrative business semantics match;
    the idempotency command hash and immutable version request hash are separate domains and are
    not compared to one another

### `POST /advisory/proposals/async`
- Purpose: accept proposal create for asynchronous execution.
- Required header: `Idempotency-Key`
- Optional header: `X-Correlation-Id`
- Output: async operation reference (`operation_id`, `status_url`).

### `GET /advisory/proposals/{proposal_id}`
- Purpose: read proposal summary + current version + last gate decision.
- Query: `include_evidence=true|false` (defaults true)

### `GET /advisory/proposals`
- Purpose: list proposals with filters and cursor pagination.
- Filters: `portfolio_id`, `state`, `created_by`, `created_from`, `created_to`, `limit`, `cursor`

### `GET /advisory/proposals/{proposal_id}/versions/{version_no}`
- Purpose: read one immutable proposal version.
- Query: `include_evidence=true|false`

### `GET /advisory/proposals/{proposal_id}/workflow-events`
- Purpose: retrieve append-only workflow timeline for operations investigation and audit.

### `GET /advisory/proposals/{proposal_id}/approvals`
- Purpose: retrieve structured approval/consent records for supportability and controls review.

### `GET /advisory/proposals/{proposal_id}/lineage`
- Purpose: retrieve immutable version lineage metadata (request/simulation/artifact hashes).

### `GET /advisory/proposals/idempotency/{idempotency_key}`
- Purpose: resolve idempotency-key mappings during retry and incident investigations.

### `GET /advisory/proposals/operations/{operation_id}`
- Purpose: retrieve asynchronous operation status and terminal result/error payload.

### `GET /advisory/proposals/operations/by-correlation/{correlation_id}`
- Purpose: retrieve latest asynchronous operation by correlation id.

### `POST /advisory/proposals/{proposal_id}/versions`
- Purpose: create immutable version `N+1` for existing proposal.
- Guard: same `portfolio_id` as aggregate unless `PROPOSAL_ALLOW_PORTFOLIO_CHANGE_ON_NEW_VERSION=true`.

### `POST /advisory/proposals/{proposal_id}/versions/async`
- Purpose: accept proposal version create for asynchronous execution.
- Optional header: `X-Correlation-Id`
- Output: async operation reference (`operation_id`, `status_url`).

### `POST /advisory/proposals/{proposal_id}/transitions`
- Purpose: apply one workflow transition.
- Concurrency: `expected_state` required by default (`PROPOSAL_REQUIRE_EXPECTED_STATE=true`).

### `POST /advisory/proposals/{proposal_id}/approvals`
- Purpose: persist structured approval/consent and corresponding workflow event.
- Approval types: `RISK`, `COMPLIANCE`, `CLIENT_CONSENT`

### `POST /advisory/proposals/{proposal_id}/report-requests`
- Purpose: request a Lotus-branded advisory report payload through the lotus-report seam.
- Ownership rule: lotus-advise assembles advisory context, but reporting ownership remains with
  `lotus-report`.
- Reviewed narrative package propagation: set `include_reviewed_narrative=true` only when the
  selected immutable proposal version has a persisted advisor-review narrative and an
  `APPROVED_FOR_ADVISOR_USE` review. The request is blocked before the report seam if review
  evidence is missing, not approved, or hash continuity no longer matches the source narrative.
- Evidence rule: delivery summary and replay evidence expose only a compact package summary; raw
  report rendering and archive ownership remain downstream responsibilities.
- Report-package readiness rule: memo and policy sign-off package requests preserve the
  `lotus-report` job id and only report archive-ready posture when a bounded status lookup returns
  terminal report-owned archive evidence. Accepted/running states remain pending, missing or unsafe
  status URLs become `REPORT_STATUS_UNAVAILABLE`, and terminal downstream failures become `FAILED`.

### `POST /advisory/proposals/{proposal_id}/execution-handoffs`
- Purpose: record an auditable advisory execution handoff request for an execution provider.
- State rule: proposal must already be `EXECUTION_READY`.

### `GET /advisory/proposals/{proposal_id}/execution-status`
- Purpose: derive advisory execution correlation state from append-only workflow history.
- Output: explicit `NOT_REQUESTED | REQUESTED | EXECUTED` handoff posture with latest correlated
  execution event metadata.

Persistence note:
- Lifecycle persistence supports repository backends selected by runtime config.
- Runtime wiring and repository bootstrap live under `src/api/proposals/runtime.py`.
- Postgres-backed persistence is implemented (`PROPOSAL_STORE_BACKEND=POSTGRES`).
- In-memory persistence remains a test-only helper and is not part of the active advisory runtime
  posture.

## Pipeline (`run_proposal_simulation`)

Authority note:
- `run_proposal_simulation` remains the local deterministic engine implementation
- active API, workspace, and lifecycle flows reach it only through the advisory orchestration layer
  when the explicit non-production fallback policy is enabled

1. Validate and gate
- Requires `options.enable_proposal_simulation=true` at API layer.
- Validates proposal input models (`ProposedCashFlow`, `ProposedTrade`).

2. Before-state valuation
- Uses the shared portfolio valuation stack (`build_simulated_state`).

3. Apply proposal intents
- Cash flows can be applied before trades (`proposal_apply_cash_flows_first`).
- Trades are manually supplied and priced from market data.
- For notional-driven trades, `notional.currency` must match priced instrument currency; mismatch blocks with `PROPOSAL_INVALID_TRADE_INPUT`.
- RFC-0008 auto-funding:
  - Build funding plan per BUY currency.
  - Generate `FX_SPOT` intents for deficits using `BASE_ONLY` or `ANY_CASH` policy.
  - Apply deterministic dependencies from BUY intents to generated FX intent ids.
- Deterministic ordering:
  - `CASH_FLOW` (as provided)
  - `SECURITY_TRADE` SELL (instrument ascending)
  - `FX_SPOT` (pair ascending)
  - `SECURITY_TRADE` BUY (instrument ascending)

4. Safety and shelf guards
- Blocks on withdrawal-driven negative cash when enabled (`proposal_block_negative_cash`).
- Blocks disallowed BUY trades (`SELL_ONLY`, `BANNED`, `SUSPENDED`, and `RESTRICTED` unless `allow_restricted=true`).

5. After-state, rules, reconciliation
- Simulates portfolio mutation using shared primitives.
- Runs standard rule engine (`RuleEngine.evaluate`).
- Performs proposal reconciliation against expected cash-flow-adjusted total.
- Derives deterministic `proposal_run_id` from request hash when provided.

## Advisory Feature Flags

- `enable_proposal_simulation`
- `enable_workflow_gates`
- `workflow_requires_client_consent`
- `client_consent_already_obtained`
- `proposal_apply_cash_flows_first`
- `proposal_block_negative_cash`
- `link_buy_to_same_currency_sell_dependency`
- `enable_drift_analytics`
- `enable_suitability_scanner`
- `suitability_thresholds`:
  - `single_position_max_weight`
  - `issuer_max_weight`
  - `max_weight_by_liquidity_tier`
  - `cash_band_min_weight`
  - `cash_band_max_weight`
  - `data_quality_issue_severity`
- `enable_instrument_drift`
- `drift_top_contributors_limit`
- `drift_unmodeled_exposure_threshold`
- `auto_funding`
- `funding_mode`
- `fx_funding_source_currency`
- `fx_generation_policy`
- dependency policy note:
  - `link_buy_to_same_currency_sell_dependency=null` defaults to `false` in advisory.
  - when `true`, BUY security intents also depend on same-currency SELL intents.
- plus shared controls:
  - `block_on_missing_prices`
  - `block_on_missing_fx`
  - `allow_restricted`
  - cash-band options (affect final status via rule engine)

Lifecycle runtime config (env):
- `PROPOSAL_WORKFLOW_LIFECYCLE_ENABLED` (default `true`)
- `PROPOSAL_STORE_EVIDENCE_BUNDLE` (default `true`)
- `PROPOSAL_REQUIRE_EXPECTED_STATE` (default `true`)
- `PROPOSAL_ALLOW_PORTFOLIO_CHANGE_ON_NEW_VERSION` (default `false`)
- `PROPOSAL_REQUIRE_SIMULATION_FLAG` (default `true`)
- `PROPOSAL_SUPPORT_APIS_ENABLED` (default `true`)
- `PROPOSAL_ASYNC_OPERATIONS_ENABLED` (default `true`)

Swagger contract quality:
- Lifecycle request/response models include explicit attribute-level `description` and `examples`.
- Path/query/header parameters include explicit descriptions and examples in router definitions.

## Proposal-Specific Diagnostics/Outcomes

- `PROPOSAL_WITHDRAWAL_NEGATIVE_CASH`
- `PROPOSAL_TRADE_NOT_SUPPORTED_BY_SHELF`
- `PROPOSAL_INVALID_TRADE_INPUT`
- `PROPOSAL_MISSING_FX_FOR_FUNDING`
- `PROPOSAL_INSUFFICIENT_FUNDING_CASH`
- `REFERENCE_MODEL_BASE_CURRENCY_MISMATCH`
- `diagnostics.missing_fx_pairs`
- `diagnostics.funding_plan`
- `diagnostics.insufficient_cash`
- `drift_analysis` (when `reference_model` is provided and drift analytics is enabled)
- `suitability`:
  - `summary` (`new_count`, `resolved_count`, `persistent_count`, `highest_severity_new`)
  - deterministic ordered `issues` classified as `NEW`, `PERSISTENT`, `RESOLVED`
  - `recommended_gate` (`NONE`, `RISK_REVIEW`, `COMPLIANCE_REVIEW`)
- standard safety/data-quality rules continue to apply (`NO_SHORTING`, `INSUFFICIENT_CASH`, etc.)

## Proposal Artifact (RFC-0011)

Deterministic sections:
- `gate_decision`
- `summary`
- `portfolio_impact`
- `trades_and_funding`
- `suitability_summary`
- `assumptions_and_limits`
- `disclosures`
- `evidence_bundle`

Determinism controls:
- Stable sorting for allocations and FX list.
- Stable trade ordering inherited from proposal simulation ordering policy.
- `artifact_hash` from canonical JSON that excludes volatile fields:
  - `created_at`
  - `evidence_bundle.hashes.artifact_hash`

## Tests That Lock Advisory Behavior

- API: `tests/unit/advisory/api/test_api_advisory_proposal_simulate.py`
- API: `tests/unit/advisory/api/test_api_advisory_proposal_lifecycle.py`
- Contract: `tests/unit/advisory/contracts/test_contract_advisory_models.py`
- Contract: `tests/unit/advisory/contracts/test_contract_proposal_artifact_models.py`
- Engine: `tests/unit/advisory/engine/test_engine_advisory_proposal_simulation.py`
- Engine: `tests/unit/advisory/engine/test_engine_proposal_artifact.py`
- Engine: `tests/unit/advisory/engine/test_engine_proposal_workflow_service.py`
- Engine: workflow-gate behavior is covered through advisory simulation and artifact tests, including:
  - `tests/unit/advisory/api/test_api_advisory_proposal_simulate.py`
  - `tests/unit/advisory/engine/test_engine_proposal_artifact.py`
- Proposal golden: `tests/unit/advisory/golden/test_golden_advisory_proposal_scenarios.py`
- Artifact golden: `tests/unit/advisory/golden/test_golden_advisory_proposal_artifact_scenarios.py`
- Workspace API: `tests/unit/advisory/api/test_api_workspace.py`
- Workspace contract: `tests/unit/advisory/contracts/test_contract_workspace_models.py`
- Workspace OpenAPI contract: `tests/unit/advisory/contracts/test_contract_openapi_workspace_docs.py`

## Workspace Foundation and Mutation Loop

Current workspace scope:
- `POST /advisory/workspaces` creates a draft workspace session in `stateless` or `stateful` mode.
- `GET /advisory/workspaces/{workspace_id}` returns current draft state and latest evaluation.
- `POST /advisory/workspaces/{workspace_id}/draft-actions` applies a single deterministic draft mutation and re-evaluates when evaluation context is available.
- `POST /advisory/workspaces/{workspace_id}/evaluate` re-runs deterministic evaluation for the current workspace draft.
- `POST /advisory/workspaces/{workspace_id}/save` captures a replay-safe saved workspace version.
- `GET /advisory/workspaces/{workspace_id}/saved-versions` returns the saved version history for support, resume, and compare workflows.
- `POST /advisory/workspaces/{workspace_id}/resume` restores a saved version into the current editable draft.
- `POST /advisory/workspaces/{workspace_id}/compare` compares the current draft to a saved version baseline.
- `POST /advisory/workspaces/{workspace_id}/assistant/rationale` generates an evidence-grounded workspace rationale through the explicit Lotus AI workflow-pack seam.
- `POST /advisory/workspaces/{workspace_id}/assistant/rationale/review-actions` applies bounded workflow-pack review actions for the rationale run without rewriting the rationale narrative.
- `POST /advisory/workspaces/{workspace_id}/handoff` bridges the current draft into persisted proposal lifecycle without duplicating lifecycle ownership.

Current Slice 2 draft actions:
- `ADD_TRADE`
- `UPDATE_TRADE`
- `REMOVE_TRADE`
- `ADD_CASH_FLOW`
- `UPDATE_CASH_FLOW`
- `REMOVE_CASH_FLOW`
- `REPLACE_OPTIONS`

Current evaluation rule:
- stateless workspaces support full deterministic re-evaluation from the embedded simulation context
- stateful workspaces can resolve deterministic evaluation context through the Lotus Core advisory context seam when it is configured
- unresolved stateful workspaces fail explicitly with `WORKSPACE_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE`
- proposal stateful create, version, and simulation resolution fails explicitly with
  `WORKSPACE_STATEFUL_CONTEXT_AS_OF_MISSING` when Lotus Core returns no resolved date; direct/stateless
  requests remain nullable when no caller-owned date exists

Current saved-version rule:
- saved workspace versions are retained within the active workspace session and expose replay-safe evidence
- resume restores the saved draft state, evaluation summary, and replay evidence without hidden reconstruction
- compare currently returns deterministic summary deltas against a saved baseline version

Current handoff rule:
- the first workspace handoff creates a persisted proposal and records a lifecycle link on the workspace
- later workspace handoffs create new versions on the linked proposal instead of creating duplicate proposal aggregates
- stateless workspaces support lifecycle handoff directly from embedded simulation payloads
- stateful workspaces support lifecycle handoff when the Lotus Core advisory context seam can resolve replay-safe simulation inputs
- stateful workspace handoff preserves explicit requested as-of date and reporting currency in the
  proposal valuation context for both current and simulated states; the workspace's edited
  simulation payload remains the source for draft trades, cash flows, and options
- proposal stateful handoff resolution fails closed before simulation, hashing, policy evidence, or
  persistence when the authoritative source omits its required resolved as-of date

Current AI assistance rule:
- workspace AI rationale is available only for evaluated workspaces
- the Lotus AI seam receives a deterministic evidence bundle containing workspace identity, resolved context, evaluation summary, proposal status, and advisor instruction
- the advisory runtime now sends that bundle through `workspace_rationale.pack@v1` on the explicit Lotus AI workflow-pack execution route
- the response always includes that evidence bundle and now also preserves bounded workflow-pack run posture so the AI output remains reviewable and grounded
- bounded review actions for that run are exposed on a separate route that forwards Lotus AI `replacement_run_id` lineage unchanged for `REVISE` and `SUPERSEDE`
- review-action responses update only workflow-pack posture and summary; they do not imply that the workspace rationale text itself was rewritten
- the live runtime parity validator now proves that this seam executes end to end, emits distinct replacement run ids, and marks the superseded run as `HISTORICAL`

Current capability-truth rule:
- `/platform/capabilities` reports supported input modes as `stateless` and `stateful`
- feature enablement is separated from operational readiness
- workflow readiness now exposes dependency keys, degraded reasons, and fallback posture where applicable
- report-request readiness now reflects `lotus-report` dependency truth
- `/platform/capabilities` publishes every known integration boundary, but only dependencies declared
  by enabled features or workflows degrade deployment-wide readiness and supportability; optional
  unconfigured boundaries remain visible with `required_by_enabled_capability=false`
- execution handoff remains advisory-owned while external provider state stays upstream-owned

Dependency quality gate:
- `scripts/dependency_health_check.py --requirements requirements.txt`
- CI runs this check before lint/test to enforce vulnerability visibility.

## Import Path Notes

- `src/core/advisory_engine.py` is the current stable advisory engine import path.
- No advisory engine compatibility shim is supported. Historical references to removed shims are
  audit context only and must not be used as implementation guidance.
