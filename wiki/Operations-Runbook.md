# Operations Runbook

## Current Scope

This page covers first-response operation of the implemented `lotus-advise` service: health and
readiness endpoints, release image evidence, production manifest expectations, workflow readiness,
and basic troubleshooting. It does not certify upstream `lotus-core`, `lotus-risk`, `lotus-report`,
or `lotus-ai` availability beyond the dependency posture that Advise exposes.

| Reader | Start Here | Evidence Or Action |
| --- | --- | --- |
| Operations | Release Image Operations | Compare `/version` with retained Main Releasability evidence before promotion. |
| Platform/Release | Production Deployment Manifest | Deploy the immutable digest image and inject runtime secrets at deployment time. |
| Support | Health And Workflow Readiness | Use readiness for pod routing and `/platform/capabilities` for workflow posture. |
| Engineering | Troubleshooting | Reproduce with repo-native checks before changing runtime policy. |

## Health Endpoints

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /version`

## Readiness Meaning

Readiness is not a cosmetic check. Startup and readiness validate:

1. numeric integration runtime configuration
2. advisory runtime persistence posture
3. proposal repository boot readiness
4. proposal async runtime recovery posture

If the service cannot satisfy the advisory persistence contract, readiness should fail closed.
Malformed numeric settings also fail startup/readiness with the setting name and validation rule
only; raw configured values are not exposed in readiness bodies.

`GET /version` is not a readiness check. It exposes support-safe build and image metadata so
operators can compare a running container with Main Releasability release evidence.

## Release Image Operations

Release images are pushed only by the Main Releasability Gate. The release image must be tagged with
the Git SHA and accompanied by retained evidence:

1. digest-bearing `release-evidence.json`,
2. SBOM,
3. passing high/critical fixable-vulnerability scan report plus full all-severity inventory,
4. image signature,
5. provenance attestation.

Deployment should use the immutable image digest from the release manifest and promote that same
image across environments. Do not rebuild per environment, and do not inject secrets through Docker
build args, OCI labels, release manifests, or `/version` metadata.

## Production Deployment Manifest

`docker-compose.production.yml` is environment-neutral. Deployment automation must inject the
immutable image digest reference, upstream service URLs, Postgres DSNs from secrets, and the trusted
tenant id. The production manifest must not contain `.dev.lotus`, `host-gateway`, plaintext DSNs,
database passwords, local image builds, or mutable image tags.

The app-local Compose manifest is different by design: it supplies
`LOTUS_ADVISE_TENANT_ID=tenant-sg-001` as a developer fixture for standalone and canonical
Workbench startup. That fixture is not production tenant-isolation or entitlement evidence.

Production container healthchecks use `/health/ready`. `/version` is release metadata for
comparing runtime build identity with release evidence; it is not a readiness endpoint.

## Health And Workflow Readiness

`GET /health/ready` is the local runtime readiness gate for traffic routing. It checks configured
integration runtime settings, advisory runtime persistence, proposal repository boot posture, and
async recovery readiness. It does not probe upstream dependency health.

Use `GET /platform/capabilities` for upstream dependency and workflow readiness. Missing
`lotus-core`, degraded `lotus-risk`, unavailable `lotus-report`, unavailable `lotus-ai`, or
`lotus-performance` readiness-only posture must degrade the relevant dependency, feature, and
workflow evidence there without forcing the Advise pod out of service.

Kubernetes readiness probes and container healthchecks should use `/health/ready`. Demo, release,
RFP, and workflow certification must require both a ready `/health/ready` response and ready
`/platform/capabilities` evidence for every claimed workflow.

## Durable State Recovery

Durable recovery scope is governed by
`docs/standards/advisory-durable-state-recovery.v1.json` and validated by
`make durable-state-recovery-gate`. The gate emits
`output/durable-state-recovery/recovery-drill-evidence.json` and keeps backup/restore ownership,
RTO/RPO, replay quarantine, stop/resume criteria, and restore checks aligned with the checked-in
PostgreSQL migration namespaces.

Advise owns post-restore integrity and replay checks for `proposals`, `policy_packs`,
`advisory_copilot`, and `workspace`. Platform database operations own backup vendor, encrypted
backup storage, point-in-time restore execution, and cross-region database controls.

Non-production restore drills must restore a selected backup or PITR point into an isolated DSN,
apply `python scripts/postgres_migrate.py --target all`, then run:

1. `make durable-state-recovery-gate`
2. `make migration-rollout-contract-gate`
3. `make migration-smoke`
4. `python scripts/production_cutover_check.py --check-migrations`

Do not resume traffic when schema checksums drift, a durable namespace is missing, idempotency or
append-only audit conflicts appear, replay hashes drift, or downstream report/archive/AI lineage
refs are missing. Quarantine the affected workflow and escalate to the namespace owner from the
recovery contract.

## Proposal Async Operation Controls

`src/core/proposals/async_operation_control_plane.py` governs support-safe decisions for proposal
async operations. The boundary classifies operations as `PENDING`, `LEASED`, `RECOVERABLE_STUCK`,
`RETRY_EXHAUSTED`, `QUARANTINED`, `TERMINAL_FAILED`, or `TERMINAL_SUCCEEDED` using persisted
operation state, attempt counts, and lease expiry.

Only trusted operations principals with `advisory.proposals.async_operations.control` can receive
allowed control decisions. Supported actions are `DRY_RUN`, `RETRY`, `QUARANTINE`, and
`PAUSE_DRAIN`. Active leases block retry and quarantine so operators do not duplicate worker-owned
execution. Retry-exhausted operations can be quarantined for support triage, but cannot be retried
by resetting attempts or mutating the original payload.

Control audit evidence is intentionally sanitized: operation, correlation, proposal, actor, service
identity, idempotency key, and reason values are hashed, and payload mutation is always reported as
not allowed. Do not add arbitrary SQL, unredacted request-content editing, request-body actor
authority, or lifecycle-invariant bypasses to async-operation support tooling.

## SLO And Capacity Budgets

Endpoint, workflow, dependency, and AI cost budgets are governed by
`docs/standards/advisory-slo-capacity-budgets.v1.json` and validated by
`make slo-capacity-gate`. The gate emits `output/slo-capacity-smoke-plan.json` for live
load/capacity automation.

Operators should alert and triage by bounded dimensions only: route template, operation name,
workflow key, dependency key, status class, outcome, degraded reason, fallback mode, and readiness
basis. Do not add client, portfolio, account, proposal, workspace, request, response, trace, or
correlation identifiers as metric labels or alert dimensions.

When a budget is breached:

1. confirm whether the breach is local runtime, dependency, AI cost/latency, or degraded-workflow
   posture using `/health/ready`, `/platform/capabilities`, and bounded telemetry,
2. compare the affected workflow with its p95/p99, timeout, error-rate, degraded-rate,
   concurrency, and dependency budgets,
3. route dependency budget breaches to the owning service with the dependency key and readiness
   basis, not raw downstream payloads,
4. route AI token, output, cost, latency, or fallback breaches through the advisory AI governance
   owner before increasing limits,
5. record live smoke evidence against the generated smoke plan before claiming recovery.

Advisory copilot `lotus-ai` calls carry the governed runtime budget contract in
`contracts/advisory-copilot/runtime-budget.v1.json`. Stable unavailable reasons such as
`COPILOT_AI_INPUT_BUDGET_EXHAUSTED`, `COPILOT_AI_OUTPUT_BUDGET_EXHAUSTED`,
`COPILOT_AI_CONCURRENCY_BUDGET_EXHAUSTED`, and `COPILOT_AI_RETRY_BUDGET_EXHAUSTED` are operator
diagnostics, not model output. Do not raise limits until the source evidence size, workflow-pack
usage, provider status, and bounded lineage telemetry explain the breach.

## Advisory Supportability Metrics

`GET /platform/capabilities` publishes the implemented feature key
`advise.observability.advisory_supportability` and a source-backed `supportability` summary. The
summary reports only bounded operational posture:

1. `state`
2. `reason`
3. `freshness_bucket`
4. dependency and feature readiness counts

`/metrics` emits `lotus_advise_advisory_supportability_total` with `state`, `reason`, and
`freshness_bucket` labels only. The `supportability.metric_labels` response field must match this
metric exactly. Do not add portfolio, account, client, advisor, proposal, workspace, request,
response, correlation, trace, transaction, security, or payload identifiers to this metric.

## HTTP Telemetry And Audit Labels

Request logs and enterprise audit actions must aggregate by bounded route templates and operation
names. Use fields such as `route_template`, `operation_name`, `http_status_code`,
`http_status_class`, and supportability reason codes for dashboards and alerts.

Do not use raw URL paths or proposal, workspace, policy-evaluation, async-operation, portfolio,
client, or account identifiers as metric labels, dashboard dimensions, alert dimensions, request
log endpoint fields, or enterprise audit action strings. If raw identifiers are needed for a
support investigation, capture them only in a separately governed diagnostic artifact with explicit
redaction and retention controls.

## Risk Authority Degradation

Proposal authority evidence must stay internally consistent when `lotus-risk` is unavailable. If
`authority_resolution.risk_authority` is `unavailable`, `authority_resolution.degraded` is `true`
and `degraded_reasons` contains a stable reason. Dependency configuration/readiness failures use
`LOTUS_RISK_DEPENDENCY_UNAVAILABLE`; configured enrichment failures use
`LOTUS_RISK_ENRICHMENT_UNAVAILABLE`. Do not infer local risk metrics when either reason is present.

## Policy Evaluation Diagnostics

Use `GET /advisory/policy-evaluations/{evaluation_id}/diagnostics` when support needs one
bounded view of policy-evaluation posture. The projection is derived from the finalized policy
evaluation record and append-only audit events. It reports sign-off status, latest review,
sign-off, report-package and AI evidence event summaries, report-package handoff posture, AI
fallback posture, replay hashes, safe next action, and this runbook reference.

Diagnostics must stay support-safe. Do not add raw source evidence, raw downstream report or AI
payloads, prompt text, unrestricted exception details, credentials, trace identifiers, correlation
identifiers, client secrets, or portfolio/account payloads to this endpoint.

Do not use the generic policy-evaluation event route to backfill sign-off, report/archive, or AI
evidence. That route accepts non-privileged review events only. Sign-off events must come from the
policy workflow command, report/archive events from the report-package command, and AI evidence
events from the bounded AI-evidence command so source hashes, maker-checker posture, downstream
references, redaction, lineage, idempotency, and client-ready blocked posture remain validated.

Policy-control writes must carry trusted principal headers before Advise records catalog or
evaluation state:

1. `X-Actor-Id`, `X-Role`, `X-Tenant-Id`, `X-Legal-Entity-Code`, and `X-Correlation-Id`
2. `X-Service-Identity` or `Authorization`
3. `X-Capabilities` containing the route capability, for example
   `advisory.policy_pack.validate`, `advisory.policy_pack.activate`,
   `advisory.policy_evaluation.finalize`, `advisory.policy_evaluation.review_event`,
   `advisory.policy_evaluation.sign_off`, `advisory.policy_evaluation.report_package`, or
   `advisory.policy_evaluation.ai_evidence`
4. `X-Authorized-Proposal-Id` and `X-Authorized-Portfolio-Id` for evaluation-scoped writes

Body actor fields are compatibility echoes only. A mismatch with `X-Actor-Id`, a missing/expired
principal, wrong role, missing capability, missing scope, or cross-scope proposal, portfolio, tenant,
or legal-entity access fails closed with 401/403 policy-control errors. Successful audit events
retain trusted subject, role, tenant, legal entity, correlation id, service identity, and capability
metadata.

## Policy-Pack Applicability

Policy-pack applicability is evaluated before any material rule executes. The selector contract is
source-backed and fail-closed across jurisdiction, booking center, legal entity, client segment, and
policy product scope.

Operational interpretation:

1. missing required selector evidence returns `BLOCKED` with field-level reason codes such as
   `POLICY_APPLICABILITY_LEGAL_ENTITY_SOURCE_MISSING` or
   `POLICY_APPLICABILITY_PRODUCT_SCOPE_SOURCE_MISSING`
2. selector mismatch returns `NOT_APPLICABLE` with the mismatched dimension reason code
3. failed applicability produces no rule results and must not be treated as a positive policy
   posture
4. `applicability.matched_selectors` is retained in finalized records, lineage, replay, and
   diagnostics so operators can see which source-backed selectors drove the decision
5. product scope comes from proposed-trade shelf evidence; unsupported or missing product
   classification must be fixed at the source-evidence boundary rather than inferred in support
   tooling

## Report Package Status Recovery

Advisor memo and policy sign-off report packages preserve `lotus-report` as the report/render/
archive owner. Advise submits the report job, performs bounded status retrieval, and keeps the
report job id in the response even when the downstream status is not terminal.

Operational interpretation:

1. `ARCHIVED` means `lotus-report` returned terminal archive evidence.
2. `ACCEPTED`, `RUNNING`, and `PENDING_ARCHIVE` are not archive-ready states.
3. `REPORT_STATUS_UNAVAILABLE` means the status URL was missing/unsafe, the status lookup failed,
   or the status payload was malformed. Operators should use the preserved report job id and
   idempotency key to inspect `lotus-report`.
4. `FAILED` means the downstream report/render/archive workflow reached a terminal failure and
   should be escalated to the report/render/archive owner.

## Advisor Cockpit Operations

RFC-0026 cockpit supportability is exposed through `GET /advisory/cockpit/supportability` and
`GET /platform/capabilities`. The supported posture is source-owned advisor workflow
evidence: action items, snapshot posture, acknowledgement replay, active data products, Gateway
publication, Workbench rendering, and canonical `PB_SG_GLOBAL_BAL_001` proof.

Operationally, cockpit acknowledgements are not remediation authority. Treat them as append-only
advisor workflow evidence. They must not be used as proof of completed policy approval, client
communication, CRM system-of-record task creation, or OMS order/fill/settlement activity.

## RFC-0028 Bank Demo Proof Operations

RFC-0028 proof capture is repeatable and evidence-backed for the governed canonical portfolio
`PB_SG_GLOBAL_BAL_001`. The expected proof marker is `BANK_DEMO_PROOF_PACK_CREATED`; material drift
is represented by `RFC0028_BACKEND_PROOF_MATERIAL_REVIEW_BLOCKED` or an HTTP 409 response from the
proof-pack API.

Use one of these capture modes:

```bash
python scripts/capture_rfc0028_backend_proof.py --live-suite-json <path> --output-dir output/rfc0028/backend-proof
python scripts/capture_rfc0028_backend_proof.py --run-live-suite --output-dir output/rfc0028/backend-proof
```

When `--output-dir` is absolute or outside the governed default path, set `--artifact-ref-prefix`
to a relative proof-artifact reference such as `output/rfc0028/backend-proof`. The filesystem
location may vary by operator, but proof-pack asset references must stay portable, local-relative,
and free of URL/query/fragment/traversal or sensitive credential or AI-input material.

Review these artifacts before reusing demo, RFP, security, or proof-guide material:

1. `proof-pack.json`
2. `scenario-contract.json`
3. `supported-claim-register.json`
4. `runtime-posture.json`
5. `sanitized-runtime-summary.json`
6. `material-field-review.json`
7. `document-proof-summary.json`
8. `journey-integration-proof-summary.json`
9. `commercial-material-pack.json`
10. `capture-summary.md`

Operational interpretation:

1. a material-review block or HTTP 409 is a defect to triage at the source layer; do not work
   around it in Workbench, Gateway, or documentation
2. runtime posture must not contain credentials, query strings, fragments, unredacted AI inputs,
   unrestricted runtime payloads, trace identifiers, or correlation identifiers
3. ready `/platform/capabilities` runtime evidence must include feature
   `advisory.bank_demo_proof` and workflow `advisory_bank_demo_proof`; missing keys indicate stale
   capability discovery and block proof-pack reuse
4. live-suite result refs, live-suite bundle refs, and output ref prefixes must be local relative
   artifact references; URL/query/fragment/traversal and sensitive credential or AI-input material
   is rejected
5. HTTP 422 request-validation responses should name the invalid field and rule without echoing the
   rejected sensitive value
6. endpoint posture should use bounded integer `latency_ms` values, not unrestricted traces or
   request payloads
7. local `output/` artifacts are evidence, not authored documentation source; README and wiki truth
   must be updated separately when implementation posture changes
8. client-ready publication, external client communication, bank-specific attestations,
   legal/regulatory advice, completed policy sign-off/approval, and OMS/order/fill/settlement stay
   blocked unless separately implemented and proven

For `lotus-advise` app-level demo certification, run:

```bash
make demo-certification-live
```

The command validates the live service readiness, OpenAPI route-safety posture, deterministic
synthetic advisory scenarios, required `/platform/capabilities` feature/workflow truth, and domain
assertions, then writes evidence under `output/demo-certification/`. The scheduled/manual Postgres
runtime workflow uploads the same evidence artifact. Treat any non-zero exit or unsafe route probe
as a release-blocking defect for the demo scope.

Use `docs/commercial/RFC-0028-bank-demo-client-proof-materials.md` for sales, pre-sales, RFP, and
demo-lead wording. It is the business-facing guide, but it remains constrained by the supported
claim register and proof-pack evidence.

## Canonical Local Identity

Use:

- [canonical local service identity](http://advise.dev.lotus)

That is the canonical local service identity for cross-app and demo-oriented flows.

## Postgres Rollout Notes

The active runtime direction is PostgreSQL-backed proposal lifecycle and policy evidence
persistence. Proposal state uses the `proposals` migration namespace, advisory copilot state uses
`advisory_copilot`, and policy-pack catalog, policy-evaluation records, audit events, and
idempotency maps use the `policy_packs` migration namespace and are composed through runtime
repository ports.

Operationally important commands from the rollout runbook:

```bash
python scripts/postgres_migration_rollout_contract.py --emit-rehearsal-evidence output/postgres-migration-rollout-rehearsal.json
python scripts/postgres_migrate.py --target all
python scripts/production_cutover_check.py --check-migrations
```

`--target all` applies all three namespaces. Production cutover validation checks all three and
uses `POLICY_POSTGRES_DSN` for `policy_packs` when policy storage is separate.

Every migration must be represented in
`docs/standards/postgres-migration-rollout-contract.v1.json` with expand/migrate/contract phase,
old/new app compatibility, lock and online behavior, backfill checkpoint/resume/quarantine posture,
rollback limits, and rehearsal evidence. Current index migrations are normal PostgreSQL index
builds, not concurrent index builds, so use controlled rollout windows for production-sized tables.
Before applying policy-pack active-version uniqueness changes, preflight that each
`policy_pack_id` has at most one `ACTIVE` version; duplicate active rows must be quarantined and
remediated before migration apply.

Policy-pack repository writes use a single adapter-owned PostgreSQL transaction for record/catalog
state, audit events, and idempotency mappings. A partial failure must roll back the whole write.
Operators should treat `POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT`,
`POLICY_PACK_IDEMPOTENCY_KEY_CONFLICT`, policy event conflicts, or stale record/catalog conflicts
as retry/diagnostic events, not as permission to patch rows manually. Preserve the idempotency key,
request hash, evaluation or policy-pack id, event id, and failed SQL operation in incident evidence.

Use the full runbook in `docs/documentation/postgres-migration-rollout-runbook.md` for rollout,
smoke, and fix-forward guidance.

## Policy Evaluation Replay

New policy evaluations require an `ACTIVE` policy-pack version. Historical replay pins the stored
policy pack, version, and content hash from the finalized record. Replay may compare retained
`SUPERSEDED` or `DISABLED` versions, but it must not substitute the current active version. Use
`hash_comparison.policy_activation_state` and `hash_comparison.replay_reason_code` to distinguish
exact match, source/evaluation drift, missing retained definition, or content-hash drift.

Proposal workflow events and approval history are indexed for the supported hot reads:

- `proposal_workflow_events (proposal_id, occurred_at, event_id)`,
- `proposal_approvals (proposal_id, occurred_at, approval_id)`.

These support single-proposal history/replay and batched Advisor Cockpit/source-loader reads.
Validate query shape and retention evidence before adding broader lifecycle-history indexes.

## Advisory Record Lifecycle

`src/core/record_lifecycle/advisory_records.py` defines the governed record-family retention and
purge decision boundary for proposal versions, lifecycle events, approvals, policy evaluations,
report requests, and advisory copilot packet/run/review records. Operators must treat purge output
as a decision record until a repository-owned purge/tombstone workflow applies it. Legal hold always
blocks purge, dependency references block purge, unexpired records block purge, and prior tombstones
return idempotent refusal. Authorized eligible records require tombstone audit evidence with hashed
record, actor, and idempotency references. Corrections append compensating records; do not rewrite
historical evidence. Jurisdiction-specific durations require approved bank policy input and must not
be added as application constants.

## Proposal Lifecycle Integrity

The proposal migration namespace validates lifecycle relational integrity before recording
`0010_proposal_lifecycle_integrity.sql`. Treat failures from
`ux_proposal_versions_proposal_version_id`, `fk_proposal_versions_proposal`,
`fk_proposal_workflow_events_related_version`, `fk_proposal_approvals_related_version`, or
`fk_proposal_idempotency_version` as data quarantine events. Do not bypass the migration by
manually patching `schema_migrations`; remediate orphan proposal versions, orphan workflow events or
approvals, duplicate version identifiers, or invalid version/state vocabulary and rerun migration
apply.

Repository-level append-only conflict handling preserves the first proposal version, workflow event,
or approval row for a repeated identity. Exact replay is a no-op. Same identity with different
persisted content fails with `PROPOSAL_VERSION_IDENTITY_CONFLICT`,
`PROPOSAL_WORKFLOW_EVENT_IDENTITY_CONFLICT`, or `PROPOSAL_APPROVAL_IDENTITY_CONFLICT`. Treat these
as lifecycle evidence conflicts and preserve the proposal id, version number, event id, approval id,
request hash, and failed operation in incident evidence.

Proposal create writes use an adapter-owned unit-of-work boundary for the initial proposal
aggregate, immutable version 1 record, `CREATED` workflow event, and proposal-create idempotency
record. A partial write failure must roll back all four records. Preserve the proposal id, version
number, event id, idempotency key, request hash, correlation id, and failed operation when
investigating create failures; do not manually insert missing lifecycle rows.

Memo create writes use the same adapter-owned unit-of-work posture for the memo record, optional
memo-create idempotency record, and initial memo lifecycle event. A partial write failure must roll
back the memo, idempotency, and event evidence together. Preserve the memo id, proposal id, proposal
version number, event id, idempotency key when supplied, request hash, and failed operation; do not
repair memo lifecycle gaps by inserting isolated rows.

Proposal transition writes use an adapter-owned compare-and-set boundary on the proposal aggregate
state and current version. When two callers race from the same lifecycle state, the first committed
transition wins and a stale writer fails closed with
`STATE_CONFLICT: proposal aggregate changed during transition`. The losing workflow event or
approval must not be present in history. Operators should retry only after re-reading the current
proposal state and should preserve the correlation id, idempotency key, expected state/version, and
observed state/version in incident evidence.
