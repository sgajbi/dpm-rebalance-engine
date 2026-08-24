# Lotus Advise Operations Runbook

## Local Validation

- `make check`: local Feature Lane parity for lint, typecheck, OpenAPI, vocabulary, data-product,
  producer-owned proposal-decision vocabulary, trust-telemetry freshness,
  dead/duplicate/unused-dependency/oversized-code regression, and unit-test gates.
- `make ci-local`: local PR Merge Gate subset without Docker, including quality-baseline
  freshness.
- `make quality-baseline`: regenerate report-only quality artifacts in `quality/`.
- `make engineering-health`: regenerate the structural engineering-health baseline.
- `make ci-local-docker` and `make ci-local-docker-down`: run and clean up the CI-local Compose
  project. By default, both targets derive the same checkout-specific project identity, so `down
  --remove-orphans` is scoped to CI-owned containers, networks, and volumes and cannot collide with
  the product Compose project. `CI_LOCAL_COMPOSE_PROJECT` may override the derived identity only
  when an orchestrator supplies a unique, CI-owned name; arbitrary overrides are not collision-safe.
  The CI-local image carries the pinned Node `22.14.0` runtime used by the workflow OpenAPI
  Spectral gate; missing Spectral tooling is a hard failure, not a report-only success. The
  Docker-local lane also mounts the central Platform contract tree read-only at `/lotus-platform`
  and all repo-native domain-product source checkouts at their canonical `/lotus-*` paths;
  `LOTUS_PLATFORM_ROOT` overrides the default sibling platform checkout path `../lotus-platform`,
  and `LOTUS_REPOSITORIES_ROOT` overrides the default sibling repository root `..`.
- `make demo-certification-live`: run live app-level demo certification against
  `LOTUS_ADVISE_DEMO_BASE_URL` or `http://127.0.0.1:8000`, writing machine-readable evidence to
  `LOTUS_ADVISE_DEMO_EVIDENCE` or
  `output/demo-certification/latest/lotus-advise-demo-certification.json`.

## Runtime Validation

- `make migration-smoke`: migration and runtime persistence smoke tests.
- `make migration-rollout-contract-gate`: validates every Postgres migration namespace and SQL
  file has rollout phase, lock/online behavior, compatibility, rollback, and rehearsal metadata.
- `make durable-state-recovery-gate`: validates durable namespace backup/restore scope, RTO/RPO,
  replay quarantine rules, and non-production restore-drill evidence shape.
- `make postgres-runtime-contracts-local`: local Postgres runtime contract checks.
- `make production-profile-guardrail-negatives-local`: production-profile negative guardrail
  checks, including malformed numeric integration runtime configuration.
- `make docker-build`: Docker image build validation.
- `make release-image-provenance-gate`: static Dockerfile, OCI label, release metadata, and
  support-safe build metadata contract validation.
- `make dependency-lock-gate`: validates `uv.lock` against requirement-file hashes and dependency
  inventory evidence.
- `make license-ip-gate`: runtime/development dependency license inventory and approved-exception
  validation for release evidence, evaluated in a temporary virtual environment installed from the
  governed runtime/development requirements files, constrained to the exact package versions
  projected from `uv.lock`, with pinned pip/setuptools bootstrap tooling and pip isolated from the
  caller's ambient Python environment and user configuration. Transitive version-only drift is not
  a governance event; new packages, license terms, classifications, group membership, and
  exception evidence remain blocking.
- `make bandit-severity-regression-gate`: Bandit security gate that blocks all high findings and
  fails on new, stale, expired, or worsened medium/low findings relative to the governed baseline.
- `make trust-telemetry-freshness-gate`: derives committed trust-telemetry age and blocking posture
  from observed implementation evidence so stale snapshots cannot claim current data-product
  promotion evidence.
- `make proposal-decision-vocabulary-gate`: validates the checked-in versioned proposal decision
  vocabulary against `decision_summary_status_rules.py`, `workflow_gates.py`, and the dedicated
  `workflow_gate_vocabulary.py` contract owner; pairing drift fails with the affected decision
  status or workflow gate. Workflow-gate pairings are cross-checked against the runtime gate
  inverse, and insufficient-evidence next actions are derived from the evidence-gap branch map.
  The legacy `READY`/`PENDING_REVIEW`/`BLOCKED` projections remain an explicit reviewed
  compatibility declaration because no separate runtime producer owns that status family.

## Required Runtime Identity

Production-like report and AI integrations require `LOTUS_ADVISE_TENANT_ID` to contain the trusted
tenant identifier propagated to downstream boundaries. Report requests also require a bounded
`requested_by` actor in the advisory request payload. Missing, blank, over-length, or
control-character-containing values fail closed before `lotus-report` or `lotus-ai` HTTP
submission.

Report requests additionally require source-derived as-of date, reporting currency, and proposal
jurisdiction metadata. The service does not manufacture current-date, USD, or SG fallbacks for
production-like downstream report submissions.

## Runtime Configuration Guardrails

Explicit numeric integration settings fail startup and readiness when malformed or out of range.
Unset values use documented local/test defaults, but configured values are never silently coerced.

Guarded settings include:

- `LOTUS_CORE_TIMEOUT_SECONDS`
- `LOTUS_CORE_STATEFUL_CONTEXT_CACHE_TTL_SECONDS`
- `LOTUS_CORE_STATEFUL_CONTEXT_CACHE_MAX_SIZE`
- `LOTUS_AI_TIMEOUT_SECONDS`
- `LOTUS_RISK_TIMEOUT_SECONDS`
- `LOTUS_RISK_RETRY_ATTEMPTS`
- `LOTUS_RISK_RETRY_BACKOFF_SECONDS`
- `LOTUS_REPORT_TIMEOUT_SECONDS`
- `LOTUS_REPORT_STATUS_POLL_ATTEMPTS`
- `LOTUS_REPORT_STATUS_POLL_BACKOFF_SECONDS`

Readiness and startup errors expose only the setting name and validation rule, not the raw configured
value.

## Health And Workflow Readiness

`GET /health/ready` is the local runtime readiness gate for traffic routing. It checks configured
integration runtime settings, advisory runtime persistence, proposal repository boot posture, and
async recovery readiness. It does not probe upstream dependency health.

Use `GET /platform/capabilities` for upstream dependency and workflow readiness. Missing
`lotus-core`, degraded `lotus-risk`, unavailable `lotus-report`, unavailable `lotus-ai`, or
`lotus-performance` readiness-only posture must degrade the relevant capability/workflow there
without forcing the Advise pod out of service.

Deployment healthchecks and Kubernetes readiness probes should use `/health/ready`. Demo,
release, RFP, and workflow certification must require both a ready `/health/ready` response and
ready `/platform/capabilities` evidence for every claimed workflow.

## Release Image Evidence

Runtime build identity is exposed at `GET /version`. Operators should compare it with the retained
Main Releasability image release evidence before promoting or diagnosing a container:

1. image tag must be the Git SHA,
2. OCI labels must carry commit, branch/ref, repository URL, service version, build timestamp, CI
   run ID, and image-digest posture,
3. `release-evidence.json` must carry the pushed image digest plus dependency-lock evidence, SBOM,
   license/IP inventory, the passing high/critical fixable-vulnerability scan, signature, and
   provenance-attestation references,
4. production deployment must use the immutable digest reference and promote the same image across
   environments instead of rebuilding,
5. Docker build args, environment variables, OCI labels, release manifests, and runtime `/version`
   metadata must remain support-safe and must not carry secrets or DSNs.
6. release evidence must link Bandit, dependency lock, dependency audit, license/IP inventory, SBOM,
   the full all-severity container vulnerability inventory, and the passing high/critical
   fixable-vulnerability scan so security posture is reviewable with the immutable image identity.

## Production Deployment Manifest

`docker-compose.production.yml` is environment-neutral. It must be rendered by the deployment
environment with:

- `LOTUS_ADVISE_IMAGE_DIGEST_REF`: immutable image reference with digest from release evidence,
- upstream service URLs (`LOTUS_CORE_BASE_URL`, `LOTUS_CORE_QUERY_BASE_URL`, `LOTUS_RISK_BASE_URL`,
  `LOTUS_REPORT_BASE_URL`, `LOTUS_AI_BASE_URL`),
- `PROPOSAL_POSTGRES_DSN`, `POLICY_POSTGRES_DSN`, and `WORKSPACE_POSTGRES_DSN` from deployment
  secrets,
- `LOTUS_ADVISE_TENANT_ID` from governed tenant configuration.

Do not add `.dev.lotus`, `host-gateway`, plaintext DSNs, database passwords, local image builds, or
mutable image tags to the production manifest. The manifest healthcheck uses `/health/ready` for
local runtime readiness; workflow promotion evidence must also inspect `/platform/capabilities`.
`/version` remains release metadata, not readiness.

## Operational Posture

- Treat GitHub Actions as CI truth.
- Treat `quality/` reports as baseline evidence, not production-readiness signoff.
- Publish wiki only when repo-local `wiki/` source changes.

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

## PostgreSQL Migration Rollout

PostgreSQL schema rollout is governed by
`docs/standards/postgres-migration-rollout-contract.v1.json` and validated by
`make migration-rollout-contract-gate`. The gate emits
`output/postgres-migration-rollout-rehearsal.json` and fails if a checked-in SQL migration lacks
expand/migrate/contract phase metadata, old/new application compatibility, lock and online
behavior, backfill checkpoint/resume/quarantine posture, rollback limits, or rehearsal evidence.

`python scripts/postgres_migrate.py --target all` applies `proposals`, `advisory_copilot`,
`policy_packs`, and `workspace`. `python scripts/production_cutover_check.py --check-migrations`
verifies all four namespaces. The policy namespace uses `POLICY_POSTGRES_DSN` when policy storage is
separate; the workspace namespace uses `WORKSPACE_POSTGRES_DSN` when configured and otherwise shares
`PROPOSAL_POSTGRES_DSN`. Production deployments must set `WORKSPACE_STORE_BACKEND=POSTGRES` and
inject `WORKSPACE_POSTGRES_DSN` explicitly.

Current index migrations are not `CREATE INDEX CONCURRENTLY`; treat them as controlled-window
operations on production-sized tables. Keep the previous compatible app version available, retain
backup/restore evidence, and fix forward with a new migration rather than editing applied SQL.
Before applying the `policy_packs` active-version uniqueness migration, verify there is no more
than one `ACTIVE` row per `policy_pack_id`; if duplicates exist, quarantine policy activation and
remediate the intended current version before rerunning migration apply.

Policy-pack repository writes use a single adapter-owned PostgreSQL transaction for record/catalog
state, audit events, and idempotency mappings. A partial failure must roll back the whole write.
Operators should treat `POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT`,
`POLICY_PACK_IDEMPOTENCY_KEY_CONFLICT`, policy event conflicts, or stale record/catalog conflicts
as retry/diagnostic events, not as permission to patch rows manually. Preserve the idempotency key,
request hash, evaluation or policy-pack id, event id, and failed SQL operation in incident evidence.

## Durable State Recovery

Durable-state recovery is governed by
`docs/standards/advisory-durable-state-recovery.v1.json` and validated by
`make durable-state-recovery-gate`. The gate emits
`output/durable-state-recovery/recovery-drill-evidence.json` and fails if any migration namespace is
missing backup scope, RTO/RPO, restore checks, replay quarantine rules, stop criteria, resume
criteria, or escalation ownership.

Advise owns recovery checks for the `proposals`, `policy_packs`, `advisory_copilot`, and
`workspace` namespaces. Platform database operations own encrypted backup scheduling, backup
storage retention, point-in-time restore execution, and cross-region database controls.

For a non-production restore drill:

1. restore the selected PostgreSQL backup or PITR point into an isolated DSN,
2. apply `python scripts/postgres_migrate.py --target all`,
3. run `make durable-state-recovery-gate`,
4. run `make migration-rollout-contract-gate` and `make migration-smoke`,
5. run `python scripts/production_cutover_check.py --check-migrations`,
6. retain `output/durable-state-recovery/recovery-drill-evidence.json` with release evidence.

Do not resume traffic if schema checksums drift, durable namespaces are missing, lifecycle or
policy rows are orphaned, idempotency conflicts appear after restore, replay hashes drift, or
downstream report/archive/AI lineage refs are missing. Quarantine the affected workflow and
escalate to the namespace owner in the recovery contract.

## Policy Evaluation Replay

New policy evaluations require an `ACTIVE` policy-pack version. Historical replay pins the stored
`policy_pack_id`, `policy_version`, and `policy_content_hash` from the finalized record. Replay may
compare retained `SUPERSEDED` or `DISABLED` versions, but it must not substitute the current active
version. Operators should inspect `hash_comparison.policy_activation_state` and
`hash_comparison.replay_reason_code` to distinguish exact match, source/evaluation drift, missing
retained definition, or content-hash drift.

## Proposal History Reads

Proposal workflow events and approvals are indexed for bounded history reads by proposal and
occurrence time:

- `proposal_workflow_events`: `(proposal_id, occurred_at, event_id)`,
- `proposal_approvals`: `(proposal_id, occurred_at, approval_id)`.

These indexes support single-proposal detail/replay reads and batched Advisor Cockpit/source-loader
history reads. Before adding broader history indexes, validate the concrete query path and retention
profile so proposal lifecycle storage does not accumulate unowned indexes.

## Proposal Lifecycle Integrity

The proposal migration namespace validates lifecycle relational integrity before the
`0010_proposal_lifecycle_integrity.sql` migration is recorded. Operators should treat failures from
constraints or indexes named `ux_proposal_versions_proposal_version_id`,
`fk_proposal_versions_proposal`, `fk_proposal_workflow_events_related_version`,
`fk_proposal_approvals_related_version`, or `fk_proposal_idempotency_version` as data quarantine
events. Do not bypass the migration by hand-editing `schema_migrations`; identify orphan proposal
versions, orphan workflow events or approvals, duplicate `proposal_version_id` values, or invalid
version/state vocabularies, remediate the owning lifecycle records, and rerun migration apply.

Repository-level append-only conflict handling preserves the first proposal version, workflow
event, or approval row for a repeated identity. Exact replay is a no-op. Same identity with
different persisted content fails with `PROPOSAL_VERSION_IDENTITY_CONFLICT`,
`PROPOSAL_WORKFLOW_EVENT_IDENTITY_CONFLICT`, or `PROPOSAL_APPROVAL_IDENTITY_CONFLICT`. Treat these
as lifecycle evidence conflicts and preserve the proposal id, version number, event id, approval id,
request hash, and failed operation in incident evidence.

Proposal create writes use an adapter-owned unit-of-work boundary for the initial proposal
aggregate, immutable version 1 record, `CREATED` workflow event, and proposal-create idempotency
record. A partial write failure must roll back all four records. Operators should preserve the
proposal id, version number, event id, idempotency key, request hash, correlation id, and failed
operation when investigating create failures; do not manually insert missing lifecycle rows.

Memo create writes use the same adapter-owned unit-of-work posture for the memo record, optional
memo-create idempotency record, and initial memo lifecycle event. A partial write failure must roll
back the memo, idempotency, and event evidence together. Operators should preserve the memo id,
proposal id, proposal version number, event id, idempotency key when supplied, request hash, and
failed operation; do not repair memo lifecycle gaps by inserting isolated rows.

Proposal transition writes use an adapter-owned compare-and-set boundary on the proposal aggregate
state and current version. When two callers race from the same lifecycle state, the first committed
transition wins and a stale writer fails closed with
`STATE_CONFLICT: proposal aggregate changed during transition`. The losing workflow event or
approval must not be present in history. Operators should retry only after re-reading the current
proposal state and should preserve the correlation id, idempotency key, expected state/version, and
observed state/version in incident evidence.
