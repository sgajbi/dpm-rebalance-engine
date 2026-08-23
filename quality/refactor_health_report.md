# Lotus Advise Refactor Health Report

- Git Identity: omitted from committed Markdown; use Git history and GitHub Actions
  run metadata for exact branch/head evidence.
- Current Phase: `feature-branch modularity and quality-baseline hardening`

## Current Progress Signals

- Proposal input models are split into focused context DTOs, request-envelope DTOs,
  and a compatibility facade.
- Proposal context resolution, canonical request hashing, and context evidence
  projection are split into focused owner modules with a compatibility facade.
- Advisory-copilot API DTOs are split into request, response, limits, and compatibility
  modules.
- Advisory-copilot source projections and run-record limits have focused owner modules.
- Advisory-copilot proposal-version lineage extraction delegates lineage-ref and
  section-source-ref matching to focused helpers.
- Advisory simulation orchestration is split into intent planning, review policy,
  and decision-support modules with focused boundary tests.
- Feature capability catalog assembly is split into foundation, evidence-product,
  and operational capability groups.
- Workflow capability catalog assembly is split into foundation, evidence-product,
  and operational workflow groups.
- Proposal memo section assembly is split into foundational, policy-review,
  operational, and appendix section groups.
- Bank-demo supported-claim register assembly is split into artifact policy,
  backend-evidence, product-surface, and boundary claim groups.
- Compliance rule evaluation is split into focused cash-band, concentration,
  data-quality, trade-size, shorting, and cash-sufficiency evaluators.
- Target-generation solver orchestration delegates sell-only redistribution, solver
  indexing, constraint assembly, and solved-weight application to focused helpers.
- Workflow gate decision policy delegates reason bundling, ordered gate-outcome rules,
  client-consent checks, and deterministic reason sorting to focused helpers.
- Proposal memo source-readiness assembly is split into core, risk, and Advise
  source-owner section groups.
- Proposal memo source-readiness owner groups are split into focused Lotus Core,
  Lotus Risk, and Lotus Advise modules with a compatibility facade.
- Bank-demo runtime summary sanitization is split into access helpers and
  focused projection builders.
- Bank-demo commercial material pack assembly delegates governed material rows to
  a focused catalog module.
- Bank-demo commercial material register validation delegates claim lookup,
  reference aggregation, and client-facing claim-posture checks to focused helpers.
- Bank-demo supported-claim classification validation delegates evidence,
  proof-reference, planned/unsupported, and UI-pending posture checks to focused helpers.
- Bank-demo proof-pack contract-reference normalization delegates scheme, credential,
  path, traversal, and sensitive-detail checks to focused helpers.
- Bank-demo proof asset commit-safety validation delegates local-only, secret
  retention, and commit-safe hash checks to focused helpers.
- Bank-demo journey integration proof DTOs and validators are split into a focused
  model owner while preserving the proof summary builder and public import path.
- Proposal artifact assembly delegates gate fallback, decision-summary fallback,
  alternatives copying, summary, portfolio-impact, assumptions, disclosures,
  evidence-bundle, and hash finalization to focused artifact helpers.
- Proposal artifact summary projection delegates objective tags, intent counts,
  cash, drift, and suitability takeaways to focused summary helpers.
- Shared valuation FX lookup delegates pair formatting, market-rate lookup,
  decimal conversion, and inverse-rate handling to focused helpers.
- Lotus Core classification label resolution delegates taxonomy-record parsing,
  ungoverned fallback, governed dimension lookup, and label resolution to
  focused helpers.
- Advisory auto-funding planning delegates FX source selection and missing-rate
  diagnostics to a focused funding-selection module.
- Policy source-readiness assembly is split into Lotus Core, product-policy,
  and Lotus Risk source-owner section modules.
- Lotus Risk concentration request issuer mapping delegates changed-security
  detection, issuer-evidence eligibility, and compact payload projection to
  focused helpers.
- Lotus Report request mapping delegates report-date source selection, lineage
  fallback, safe status-path validation, and bounded identity checks to focused
  helpers.
- Lotus Report request mapping delegates output-format normalization and
  reporting-currency extraction while preserving PDF/JSON and USD fallback
  behavior.
- Proposed trade request sizing validation delegates quantity/notional
  exclusivity and positive-notional checks to focused helpers while preserving
  product-safe validation messages.
- Advisory funding selection delegates candidate ordering, FX lookup,
  sufficient-cash selection, and smallest-deficit tracking to focused helpers.
- Advisory trade-intent construction delegates price lookup, quantity/notional
  resolution, and base-currency notional projection to focused helpers.
- Advisory cash-flow intent planning delegates intent DTO construction,
  negative-cash guardrail checks, and failure recording to focused helpers.
- Advisory security-trade intent planning delegates per-trade shelf validation,
  supported-intent construction, and failure recording to focused helpers.
- Lotus Core stateful-context held-position selection delegates cash exclusion
  and security-id normalization to focused helpers.
- Lotus Core stateful-context dated-row selection delegates malformed-row
  filtering, as-of eligibility, and future-row fallback to focused helpers.
- Proposal narrative product-type policy delegates shelf-entry attribute
  evidence, asset-class mapping, and FX evidence inference to focused helpers.
- Proposal memo foundational sections are split into focused per-section builders
  outside the shared memo section group coordinator.
- Proposal memo foundational sections delegate summary extraction and value
  normalization to a focused helper module while preserving section construction.
- Proposal memo evidence-pack assembly delegates deterministic section, appendix,
  and material-claim construction to a focused section factory.
- Proposal memo API orchestration delegates report-package and AI-evidence payloads
  to a focused external-package module.
- Proposal memo API routes are split into command, external-package, and read/projection
  route modules while preserving the route loader and OpenAPI surface.
- Policy evaluation API routes are split into command, read/projection, workflow,
  and external-package route modules while preserving the route loader and OpenAPI
  surface.
- Proposal memo API response assembly delegates memo, audit-event, report replay,
  AI commentary, archive-ref, section, and replay-metadata projection to a
  focused response projection module.
- Proposal memo API external request orchestration delegates report-package and
  AI-commentary integration flows to a focused operations module.
- Alternative strategy construction delegates input DTOs, base mechanics,
  objective classes, selection helpers, trade-payload formatting, and notional math
  to focused strategy modules.
- Alternatives objective strategies are split into portfolio/cash, baseline-trade,
  currency-alignment, and deferred restricted-product modules.
- Alternative sellable-position selection delegates blocked-position eligibility and
  currency filtering to focused predicates while preserving rank ordering.
- Alternative baseline-trade reduction delegates trade adjustability and
  quantity/notional payload shaping to focused helpers.
- Alternatives enrichment delegates candidate-intent simulation splitting,
  authority rejection, and alternative status classification to focused helpers.
- Proposal alternatives models are split into vocabulary, request-validation,
  response/evidence, and compatibility facade modules.
- Proposal alternatives projection delegates request-to-strategy input mapping
  to a focused projection module.
- Proposal alternatives comparison evidence delegates approval, risk, cash,
  currency, and tradeoff deltas to a focused projection module.
- Proposal alternatives ranking delegates comparator, reason-code, rank,
  and selected-alternative projection to a focused ranking module.
- Live proposal alternatives snapshot extraction delegates payload validation,
  ranked-alternative summarization, selected fallback, top-rank projection,
  and rejected-reason extraction to focused helpers.
- Proposal memo request DTOs and memo vocabulary literals are split from
  response, lineage, and replay evidence models.
- Proposal memo persistence records are split into a focused owner module
  while preserving the existing persistence model facade.
- Proposal memo section assembly delegates source evidence and hash-payload
  collection to focused factory helpers.
- Proposal memo audit event DTOs are split into a focused append-only
  event model module.
- Proposal memo lineage and replay evidence DTOs are split into a
  focused lineage response module.
- Policy evaluation result builders are split from specialized rule
  evaluation logic.
- Policy evaluation product evidence helpers are split from specialized
  rule evaluation logic.
- Policy evaluation product helper complexity classification and proposed-shelf
  projection delegate source extraction and product flags to focused helpers.
- Policy evaluation rule dispatch and Singapore product disclosure actions
  delegate rule selection and evidence/action list construction to focused helpers.
- Policy evaluation Singapore product rule implementations are split
  into a focused rule-family module.
- Policy evaluation cost and conflict review rules are split into a
  focused review-rule module.
- Policy evaluation source-readiness and mandate rules are split into
  a focused source-rule module.
- Policy evaluation source-readiness rule handling delegates policy-posture
  aggregation and section evidence collection to focused helpers.
- Policy AI evidence action normalization delegates request trimming,
  empty-action rejection, allowlist checks, and forbidden-fragment blocking to
  focused helpers while preserving non-authoritative AI evidence posture.
- Workspace rationale Lotus AI workflow-pack run mapping delegates bounded
  finding normalization to focused helpers while preserving fail-closed run
  identity handling and bounded review-action posture.
- Proposal artifact summary DTOs are split into a focused summary model module
  while preserving the existing artifact model facade.
- Proposal artifact portfolio-impact DTOs are split into a focused portfolio model
  module while preserving the existing artifact model facade.
- Proposal artifact trade/funding DTOs are split into a focused execution-evidence
  model module while preserving the existing artifact model facade.
- Proposal artifact review DTOs are split into a focused suitability/risk-lens
  model module while preserving the existing artifact model facade.
- Proposal artifact assumptions and disclosure DTOs are split into a focused
  model module while preserving the existing artifact model facade.
- Proposal artifact evidence DTOs are split into a focused lineage/evidence
  model module while preserving the existing artifact model facade.
- Proposal artifact builders import focused DTO owner modules directly instead of
  routing section DTOs through the artifact model facade.
- Proposal narrative vocabulary Literal aliases are split into a focused type
  module while preserving the existing narrative model facade.
- Proposal narrative request DTOs are split into a focused request model module
  while preserving the existing narrative model facade.
- Proposal narrative grounding DTOs are split into a focused evidence model module
  while preserving the existing narrative model facade.
- Proposal narrative section DTOs are split into a focused section model module
  while preserving the existing narrative model facade.
- Proposal narrative policy and guardrail DTOs are split into a focused policy
  model module while preserving the existing narrative model facade.
- Proposal narrative AI-lineage DTOs are split into a focused AI model module
  while preserving the existing narrative model facade.
- Proposal narrative envelope DTOs are split into a focused envelope model module
  while preserving the existing narrative model facade.
- Proposal narrative review DTOs are split into a focused review model module
  while preserving the existing narrative model facade.
- Proposal narrative runtime modules import focused DTO owner modules directly
  instead of routing DTOs through the narrative model facade.
- Proposal narrative grounding fact projection delegates decision-summary and
  alternatives fact assembly to focused helpers.
- Advisor cockpit source read models delegate source projection helpers to a focused
  source-projection module while preserving the existing read-model facade.
- Advisor cockpit source projection delegates policy-review and memo package blockage
  source rules to a focused policy/memo projection module.
- Advisor cockpit source projection delegates proposal meeting-preparation, client
  follow-up, and approval-dependency rules to a focused proposal projection module.
- Advisor cockpit source projection delegates report/archive readiness and execution
  handoff/status rules to focused source-family projection modules.
- Advisor cockpit service delegates repository-backed source loading and tactical
  house-view source mapping to a focused source-loader module.
- In-memory proposal repository adapters delegate pure filtering, ordering,
  batching, recoverable-operation selection, and copy semantics to focused helpers.
- Advisor cockpit service delegates acknowledgement idempotency, replay,
  persistence payload, and response projection to a focused service boundary.
- Advisor cockpit runtime-state hydration uses a repository batch acknowledgement
  read and version-aware in-memory join instead of per-action acknowledgement queries.
- Engine option models delegate suitability threshold DTOs, group constraints,
  and reusable validators to focused owner modules while preserving public imports.
- Tactical house-view source products delegate DTOs and eligibility/supportability
  rules to focused owner modules while preserving the public cohort facade.
- Policy evaluation workflow commands delegate projection and sign-off decision
  validation to focused workflow owner modules.
- Integration capability response models delegate feature/workflow, readiness,
  and supportability DTO families to focused owner modules while preserving
  the public response facade.
- Proposal workflow service construction delegates operation-owner wiring to
  a focused registry while preserving the public service facade.
- Proposal workflow service async submission, execution, replay, correlation
  lookup, recovery, and test-stat facade methods live in a focused mixin.
- Proposal workflow service read, timeline, approval, lineage, version, replay,
  and idempotency lookup facade methods live in a focused read mixin.
- Advisory workspace routes are split into session/version, assistant-rationale,
  and lifecycle-handoff route modules behind the public aggregate router.
- Advisory workspace routes now compose through a workspace application service
  with explicit repository, source-context, proposal-evaluator, and
  proposal-lifecycle ports while keeping the current in-memory session store
  as an infrastructure adapter.
- Policy evaluation report-package validation delegates hash, client-ready,
  output-format, and workflow-readiness checks to named helpers.
- Policy evaluation sign-off validation delegates requirement blocker
  construction to data-driven approval, disclosure, and consent families.
- Workspace session input-mode validation delegates stateless/stateful payload
  requirements to one shared create/session policy helper.
- Workspace draft action request validation delegates action-specific payload
  requirements to a table-driven map and identifier-scope rules to focused helpers.
- Workspace draft action reduction delegates trade, cash-flow, and options
  mutations to explicit action handlers behind a registry dispatch boundary.
- Local valuation state assembly delegates position summary collection, cash
  conversion, shelf allocation, and allocation-metric rendering to focused helpers.
- Local position valuation delegates trust-snapshot authority handling,
  mark-to-market valuation, price lookup, and FX conversion to focused helpers.
- Enterprise write authorization delegates header normalization, required-header
  checks, service identity, capability config, and capability matching to
  focused helpers.
- In-memory proposal listing delegates filter matching, cursor slicing, and
  next-cursor calculation to focused query helpers.
- Persistent proposal listing delegates filter SQL, cursor SQL, query rendering,
  and page projection to focused helpers.
- OpenAPI operation enrichment delegates operation eligibility, default
  summary/description, tag inference, error response, and idempotency header handling.
- OpenAPI quality gate evaluation delegates operation iteration, endpoint
  documentation checks, schema-field metadata checks, and duplicate operation ID
  detection to focused helpers.
- API vocabulary inventory generation delegates OpenAPI operation traversal,
  schema-field extraction, fallback example policy, endpoint projection,
  attribute observation merging, and validation rule families to focused helpers.
- OpenAPI example repair delegates array, object-property, required-field,
  existing-field, and additional-property repair paths to focused helpers.
- OpenAPI example repair now delegates `$ref` and composite schema resolution,
  structured example dispatch, scalar enum/type checks, and integer bound checks.
- OpenAPI field-description inference delegates identifier, date/time, currency,
  monetary, quantity, rate/price, status, and fallback descriptions to focused helpers.
- OpenAPI example inference delegates const/enum/ref/composite priority handling
  and schema-type dispatch to focused helpers.
- OpenAPI string example inference delegates pattern, format, keyed, identifier,
  semantic-key, and fallback example paths to focused helpers.
- Commercial material source-reference normalization delegates text, repository-local
  location, path, and fragment validation to focused helpers.
- Bank-demo proof artifact-reference normalization delegates local text, URL/location,
  and path safety validation to focused helpers.
- Shared proposal intent dependency linking delegates SELL indexing, BUY selection,
  and idempotent dependency appending to focused helpers.
- Shared proposal intent dependency linking now keeps SELL selection in a
  focused helper and is protected by the refactored complexity gate.
- Advisory copilot record-text list normalization delegates list capacity and
  bounded item validation to focused helpers protected by the refactored complexity gate.
- Advisory copilot run replay delegates idempotency hash matching, orphan detection,
  and retryable refresh policy before its A-only complexity gate.
- Lotus AI tenant runtime configuration delegates configured-value loading, bounded
  tenant-id support, and control-character rejection before its A-only complexity gate.
- Proposal artifact evidence assembly delegates model serialization to focused helpers
  before its A-only complexity gate.
- Proposal artifact portfolio impact delegates weight-change row construction and
  projection before its A-only complexity gate.
- Proposal artifact trades and funding delegates intent dispatch, FX-rate lookup,
  and dependency-note detection before its A-only complexity gate.
- API structured logging formatter delegates base payload, extra-field, audit-field,
  and null-filtering behavior to focused helpers.
- Policy-pack catalog state delegates validation/activation commands, audit-event
  mechanics, and detail projection to focused owner modules.
- Proposal decision-summary assembly delegates status, reason, next-action,
  and confidence rules to a focused decision-status module.
- Proposal workflow delivery operations delegate execution handoff, status, summary,
  history, and execution-update replay behavior to a focused service boundary.
- Proposal workflow narrative operations delegate narrative read/regeneration/review
  and report-request event recording to a focused service boundary.
- Proposal workflow read operations delegate proposal, timeline, approval, lineage,
  idempotency, version, and replay views to a focused service boundary.
- Proposal workflow command operations delegate create, version, transition, and
  approval commands to a focused service boundary.
- Async operation replay evidence delegates proposal-version-backed replay,
  operation-only diagnostics, subject continuity, and runtime evidence projection
  to focused helpers.
- Proposal async operation referent loading delegates missing-scope handling,
  succeeded-version resolution, result-version lookup, and proposal-event loading
  to focused helpers.
- Shared canonical payload helpers delegate recursive mapping and sequence key
  stripping to focused helpers while preserving stable evidence hashes.
- Proposal idempotency replay delegates event and approval replay matching to
  a shared hash-conflict policy while preserving latest-record replay semantics.
- Policy evaluation persistence delegates lineage/posture projection and audit-event
  attachment mapping to a focused projection module.
- Policy evaluation persistence delegates replay hash comparison and replay response
  assembly to a focused replay module.
- Policy evaluation persistence delegates mutable record storage, idempotency replay,
  event construction, and store-backed projections to a focused record-store module.
- Lotus Core stateful-context translation delegates payload normalization, market-data
  projection, and shelf-entry projection to focused owner modules.
- Lotus Core stateful-context source reads delegate enrichment cache partitioning,
  missing-id batching, source fetch, and cache writeback to focused helpers.
- Lotus Core stateful-context resolver and trade-draft hydration paths now read as
  orchestration over source fetch, validation, DTO assembly, and per-instrument
  hydration.
- Lotus Core stateful-context route resolution delegates sanitized URL rendering,
  query/control-plane host mapping, and port derivation to focused helpers.
- Lotus Core liquidity-tier and simulation adapter logic delegates ordered policy
  rule evaluation, HTTP posting, problem-detail mapping, contract validation,
  and suitability classification normalization.
- Proposal alternatives comparison summaries delegate approval/evidence count deltas
  and decimal risk/cash delta message projection to focused helpers.
- Proposal artifact and decision-summary rule helpers delegate next-step gate mapping,
  reason-code fallback, and approval-requirement collection to focused helpers.
- Proposal artifact trade projection and advisory auto-funding planning delegate
  execution DTO construction, dependency-note assembly, per-target funding,
  missing-FX handling, and FX-intent recording to focused helpers.
- Deterministic proposal narrative orchestration delegates section filtering,
  generation-mode handling, canonical narrative id construction, and status
  resolution to focused helpers.
- Proposal narrative executive-summary text delegates blocked, insufficient-evidence,
  and ready-for-review branches to focused renderers.
- Proposal narrative deterministic section rendering delegates section-specific
  source refs, limitation refs, and fallback text to focused renderers.
- Proposal narrative alternatives text rendering delegates sentence cleanup,
  punctuation, selected-alternative resolution, and labeled evidence groups
  to focused helpers.
- Proposal narrative grounding facts delegate alternatives availability, selected
  alternative, count, rejected-summary, decision-scalar, approval, material-change,
  and missing-evidence projection to focused helpers.
- Proposal narrative policy delegates asset-class normalization, disclosure rule
  projection, and guardrail failure construction to focused helpers before its
  A-only complexity gate.
- Proposal simulation security-trade intent planning delegates shelf presence,
  shelf eligibility, unsupported-trade diagnostics, and intent construction to
  focused helpers.
- Proposal simulation review delegates input-guard, funding data-quality,
  reconciliation, and pending-review status projection to focused helpers.
- Advisory proposal orchestration delegates simulation authority resolution,
  risk enrichment authority, authority explanation projection, and proposal
  output attachment to focused helpers.
- Advisory copilot bounded tuple validation delegates sequence validation,
  bounded item normalization, duplicate handling, and non-empty enforcement to
  focused helpers.
- Advisory copilot structured payload validation delegates mapping, sequence,
  item-count, raw-AI key, and text safety checks to focused helpers.
- Advisory copilot run persistence delegates payload safety validation,
  idempotency replay lookup, run-record construction, retryable refresh, and
  idempotency-record construction to focused helpers.
- Advisory copilot review persistence delegates idempotent replay,
  active-posture validation, review-record construction, and run-posture mutation
  to focused helpers.
- Advisory copilot source-projection persistence delegates shared refresh policy,
  proposal-version run filtering, and run page projection to focused helpers.
- Advisory copilot section tuple validation delegates bounded summary normalization
  and unique audience literal policy to focused helpers.
- Suitability issue projection delegates transition selection, deterministic
  ordering, and highest-new-severity gate policy to focused helpers.
- Proposal workflow gate suitability reasons delegate new-issue reason
  construction and high/medium count projection to focused helpers.
- Direct dependency freshness governance aligns duplicated runtime and
  development pins while preserving the strict CI gate.
- API observability instrumentation tolerates pathless Starlette route
  markers while preserving Prometheus metrics exposure.
- API observability route-name compatibility delegates pathless, full-match,
  and partial-match decisions to focused helpers while preserving Prometheus
  route templating behavior.
- Bank-demo runtime proof evidence delegates summary value sanitization,
  capability endpoint lookup, readiness validation, and promoted feature/workflow
  proof checks to focused helpers.
- In-memory advisory copilot run persistence delegates idempotency replay,
  run-id replay, conflict policy, and new-run storage to focused helpers.
- Enterprise readiness runtime policy delegates config issue collection,
  write-authorization denial selection, recursive audit redaction, and
  audit-identity validation to focused helpers while preserving bounded denial and
  redaction behavior.
- HTTP observability and enterprise audit telemetry use bounded route templates,
  operation names, and status-class fields instead of raw request paths.
- Integration runtime numeric settings fail startup/readiness when explicitly
  malformed or out of range while preserving documented defaults for unset
  local/test configuration.
- Production deployment manifest policy requires immutable image digest refs,
  deployment-time endpoint/secret injection, and readiness healthchecks while
  rejecting dev DNS, host-gateway, plaintext DSNs, local builds, and latest tags.
- Integration dependency readiness delegates sanitized URL configuration,
  health-endpoint probing, readiness-basis selection, and unavailable-reason
  projection to focused helpers while preserving fail-closed dependency posture.
- Advisory supportability projection delegates dependency/feature counts,
  posture selection, degraded-state detection, and metric emission to focused
  helpers while preserving bounded supportability labels.
- Integration capability dependency diagnostics delegate readiness checks and
  public degraded-reason extraction to focused helpers while preserving
  fail-closed fallback behavior.
- Lotus Risk enrichment delegates response contract validation and bounded retry
  decisions to focused helpers while preserving safe unavailable-error mapping,
  correlation propagation, and retry/backoff behavior.
- Tactical house-view affected-cohort construction delegates candidate classification,
  source-ref aggregation, cohort identity hashing, and listing filters to focused
  helpers while preserving source-backed inclusion/exclusion semantics.
- API observability request-id normalization reuses the shared bounded
  identifier policy while preserving generated request-id fallback behavior.
- Proposal reporting service orchestration delegates related-version selection,
  reviewed-narrative packaging, request assembly, response normalization, and
  workflow recording to focused helpers.
- Policy-pack applicability evaluation delegates source context extraction,
  missing-evidence detection, not-applicable result construction, and selector
  construction to focused helpers.
- Engineering-health and quality-baseline reporting now provide repeatable evidence.
- CI workflow quality contracts now enforce committed quality-baseline freshness in
  Feature Lane, PR Merge Gate, and Main Releasability static governance jobs.
- PR auto-merge queue verification now checks protected main-branch metadata through
  a workflow-token-readable endpoint before enabling rebase auto-merge.
- Quality baseline report rendering delegates metric formatting and Markdown sections
  to focused helpers while preserving the freshness-gated report contract.
- Quality baseline Radon inventory parsing delegates nested block traversal, rank
  counting, and worst-complexity selection to tested helpers.
- Quality baseline Spectral inventory parsing delegates report availability, payload
  validation, severity counts, and path-count projection to focused helpers.
- Proposal narrative AI draft handling delegates adapter invocation, grounded section
  projection, and deterministic fallback lineage to focused helpers.
- Proposal execution-status projection delegates request metadata, downstream status
  updates, execution timestamps, and external references to focused helpers.
- Lotus Core stateful-context position translation delegates row validation and
  market-value projection to focused helpers while preserving upstream payload
  filtering semantics.
- Refactored complexity enforcement now protects the already-remediated Lotus Risk
  enrichment, tactical house-view, policy workflow projection, narrative AI draft,
  execution-status projection, Lotus Core stateful-context translation, proposal
  async/context command modules, narrative policy helpers, and decision-summary
  evidence-reference helpers with A-only Radon gates inherited by Feature Lane, PR
  Merge Gate, and Main Releasability through `make lint`.
- Lotus Core stateful-context market-data projection delegates price field extraction,
  FX pair validation, and decimal rate input handling to focused helpers while preserving
  malformed-row skipping and last-source-wins FX pair behavior.
- Bank-demo proof artifact-reference normalization delegates URL-material,
  absolute-path, traversal, and sensitive-fragment rejection to focused helpers while
  preserving local proof-artifact path normalization.
- CI workflow jobs now declare explicit timeouts so feature, PR, main releasability,
  quality-baseline, and auto-merge automation fail closed instead of hanging
  indefinitely.
- Development requirements pin the quality tools used by committed baseline
  evidence so GitHub CI and local developer runs measure the same quality surface.
- Bandit security scanning now fails earlier through `make check` and Remote Feature
  Lane for high findings plus new, stale, expired, or worsened medium/low findings.

## Remaining Enterprise-Readiness Work

- Calibrate remaining report-only tools: xenon and optional schemathesis/load testing.
- Keep Spectral OpenAPI enforcement green while route and schema contracts evolve.
- Convert the Interrogate docstring inventory into a targeted documentation-quality gate
  after classifying public API and module ownership thresholds.
- Extend CI quality enforcement with machine-readable trend/regression slices;
  keep reviewed Vulture exceptions expiring after the oversized-code gate.
- Calibrate Radon complexity enforcement beyond the current no-C/D/E/F gate after
  classifying current B-ranked blocks.
- Reduce the governed Bandit medium/low baseline before expiry after classifying current
  SQL-construction findings and resolving true positives.
- Maintain the deptry no-new-regression baseline with owner, reason, and expiry review
  as dependency closure and runtime launcher requirements evolve.
- Convert baseline reports into fail-on-new-regression gates before enforcing absolute
  thresholds.
- Continue moving oversized proposal/advisory service modules into focused use-case and
  policy modules with tests.
- Complete requested docs and wiki updates only when they describe implemented truth.
