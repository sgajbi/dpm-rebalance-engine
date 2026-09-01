# PostgreSQL Migration Rollout Runbook

## Scope

Runbook for forward-only schema migration rollout for:

- advisory proposals Postgres namespace (`proposals`)
- advisory copilot Postgres namespace (`advisory_copilot`)
- advisory policy pack and policy evaluation namespace (`policy_packs`)
- advisory workspace session and saved-version namespace (`workspace`)

## Preconditions

- PostgreSQL is reachable and healthy.
- Runtime DSNs are configured:
  - `PROPOSAL_POSTGRES_DSN`
  - `ADVISORY_COPILOT_POSTGRES_DSN` when copilot runs use a separate database. If unset, the
    migration runner uses `PROPOSAL_POSTGRES_DSN`.
  - `POLICY_POSTGRES_DSN` when policy records use a separate database. If unset, the runtime can
    share `PROPOSAL_POSTGRES_DSN`, but production manifests should inject both explicitly.
  - `WORKSPACE_POSTGRES_DSN` when workspace state uses a separate database. If unset, migration
    apply and cutover checks share `PROPOSAL_POSTGRES_DSN`; production manifests should inject it
    explicitly.
- Application image/version to deploy is already tested in non-production.
- A recent backup/restore point exists for every target database before production apply.
- `make migration-rollout-contract-gate` and `make migration-smoke` have passed against a
  production-like non-production database, with the generated rehearsal evidence retained.
- Production compose manifest available:
  - `docker-compose.production.yml`
  - rendered with `LOTUS_ADVISE_IMAGE_DIGEST_REF` from release evidence and DSNs from deployment
    secrets, not committed plaintext credentials.

## Runtime Contract

- Active `lotus-advise` runtime is PostgreSQL-only.
- Startup always enforces the advisory Postgres contract.
- Required backend settings:
  - `PROPOSAL_STORE_BACKEND=POSTGRES`
  - `POLICY_STORE_BACKEND=POSTGRES`
  - `WORKSPACE_STORE_BACKEND=POSTGRES`
  - `PROPOSAL_POSTGRES_DSN` must be configured
  - `POLICY_POSTGRES_DSN` must be configured
  - `WORKSPACE_POSTGRES_DSN` must be configured

## Migration Command

Use the shared migration tool before switching traffic:

```bash
python scripts/postgres_migrate.py --target all
```

Optional per-namespace commands:

```bash
python scripts/postgres_migrate.py --target proposals
python scripts/postgres_migrate.py --target advisory_copilot
python scripts/postgres_migrate.py --target policy_packs
python scripts/postgres_migrate.py --target workspace
```

Production contract check (profile/env/migration readiness):
Production contract check (runtime/env/migration readiness):

```bash
python scripts/production_cutover_check.py --check-migrations
```

## Startup Sequencing

1. Start/verify Postgres instance health.
2. Confirm backup/restore evidence and preflight duplicate scans required by the rollout contract.
3. Run `make migration-rollout-contract-gate` and retain
   `output/postgres-migration-rollout-rehearsal.json`.
4. Apply migrations (`scripts/postgres_migrate.py`).
5. Validate production contract (`scripts/production_cutover_check.py --check-migrations`).
6. Start API services with advisory Postgres runtime enabled:
   - `PROPOSAL_STORE_BACKEND=POSTGRES`
   - `POLICY_STORE_BACKEND=POSTGRES`
   - `WORKSPACE_STORE_BACKEND=POSTGRES`
7. Run advisory smoke API checks.
8. Shift traffic.

Do not start app replicas with Postgres backend enabled before migrations have completed.

## Expand, Migrate, Contract Policy

Every migration must be additive for at least one full deploy wave unless a separate approved
contract migration explicitly proves old application versions are no longer serving traffic.
Non-trivial migrations must declare their phase in
`docs/standards/postgres-migration-rollout-contract.v1.json`:

- `expand`: additive tables, columns, indexes, and idempotency structures that old and new app
  versions can tolerate during rollout.
- `migrate_backfill`: bounded data movement with checkpoint, resume, failure, and quarantine
  behavior.
- `contract`: removal or tightening after old versions and stale consumers are drained.

Current migrations are expand-phase migrations. Existing index migrations use normal PostgreSQL
`CREATE INDEX`/`CREATE UNIQUE INDEX`, not `CONCURRENTLY`; schedule controlled windows for large
tables and rehearse with production-like row counts before production apply.

## Safety Controls

- Migrations are forward-only.
- Applied migration checksums are stored in `schema_migrations`.
- Migration execution is wrapped in a namespace-scoped PostgreSQL advisory lock
  to avoid concurrent deploy races.
- Policy-pack state writes are transactional at the repository adapter boundary. Record/catalog
  state, audit events, and idempotency mappings must commit together or roll back together.
- Policy-pack idempotency mappings are immutable request-hash decisions. Reusing a key with a
  different request hash is a conflict, not an update.
- Policy-pack audit-event inserts must not replace a different payload for the same event id, and
  record/catalog snapshot updates are guarded by persisted event counts to avoid stale-snapshot
  overwrite.
- `--target all` applies `proposals`, `advisory_copilot`, `policy_packs`, and `workspace`;
  production cutover validation checks all four namespaces, uses the policy DSN for `policy_packs`,
  and uses `WORKSPACE_POSTGRES_DSN` or the proposal DSN fallback for `workspace`.
- If a checked-in migration file is modified after apply, execution fails with:
  - `POSTGRES_MIGRATION_CHECKSUM_MISMATCH:{namespace}:{version}`
- Startup runtime guardrails fail-fast with explicit reason codes:
  - `PERSISTENCE_PROFILE_REQUIRES_ADVISORY_POSTGRES`
  - `PERSISTENCE_PROFILE_REQUIRES_ADVISORY_POSTGRES_DSN`
  - `PERSISTENCE_PROFILE_REQUIRES_POLICY_POSTGRES`
  - `PERSISTENCE_PROFILE_REQUIRES_POLICY_POSTGRES_DSN`
  - `PERSISTENCE_PROFILE_REQUIRES_WORKSPACE_POSTGRES`
  - `PERSISTENCE_PROFILE_REQUIRES_WORKSPACE_POSTGRES_DSN`
- The production compose manifest must not contain `.dev.lotus`, `host-gateway`, committed
  plaintext DSNs, database passwords, local image builds, or mutable image tags. Use the immutable
  image digest reference from release evidence and inject environment-specific values at deploy
  time.
- Migration `proposals:0013` adds statuses that pre-0013 application readers cannot parse.
  `IDEA_PROPOSAL_RECONCILIATION_ENABLED` defaults to `false`; apply the migration, complete a full
  deployment wave, prove all pre-0013 pods are drained, and only then enable reconciliation writes.
  Disable the flag before rollback. Once any later realization outcome exists, pre-0013 pods must
  not serve realization reads or original-intake replays.

## CI Smoke Checks

CI executes:

1. `python scripts/postgres_migration_rollout_contract.py --emit-rehearsal-evidence output/postgres-migration-rollout-rehearsal.json`
2. `python scripts/postgres_migrate.py --target all`
3. Live Postgres integration tests:
   - `tests/integration/advisory/engine/test_engine_proposal_repository_postgres_integration.py`
4. Advisory Postgres startup smoke:
   - starts API with advisory Postgres backend.
5. Runtime guardrail negatives:
  - validates startup fails with:
    - `PERSISTENCE_PROFILE_REQUIRES_ADVISORY_POSTGRES`
    - `PERSISTENCE_PROFILE_REQUIRES_ADVISORY_POSTGRES_DSN`
    - `PERSISTENCE_PROFILE_REQUIRES_WORKSPACE_POSTGRES`
    - `PERSISTENCE_PROFILE_REQUIRES_WORKSPACE_POSTGRES_DSN`
    - malformed numeric integration configuration
6. Production cutover contract check:
   - `python scripts/production_cutover_check.py --check-migrations`
7. Optional nightly/manual deep validation:
   - `.github/workflows/nightly-postgres-full.yml`
   - runs integration repositories plus live API demo pack on advisory Postgres runtime.

This validates both migration application and repository contract parity on real Postgres.

## Rollback Guidance

- Schema migrations are forward-only; do not roll back by editing migration files.
- If rollout fails after migration:
  - keep schema as-is,
  - redeploy previous compatible app version,
  - fix forward in a new migration.
- If a backfill or index build breaches its rehearsal budget:
  - stop traffic shift,
  - quarantine the affected rollout window and retain SQL/error evidence,
  - keep old compatible app version serving,
  - add a forward migration or operational remediation before retrying.
- If startup fails due runtime guardrails:
  - correct backend/DSN env configuration,
  - rerun `scripts/production_cutover_check.py --check-migrations`,
  - restart services.

## Completion Evidence

- Production cutover evidence should be recorded in the active advisory rollout documentation for the release being deployed.
- Retain `output/postgres-migration-rollout-rehearsal.json`, migration smoke output, backup/restore
  proof, and cutover check output with the release evidence.
