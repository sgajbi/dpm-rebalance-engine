from pathlib import Path

import pytest

import src.infrastructure.postgres_migrations as migrations_module
from src.infrastructure.postgres_migrations import PostgresMigration, apply_postgres_migrations


class _Cursor:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(
        self,
        *,
        fail_statement: str | None = None,
        fail_rollback: bool = False,
        fail_unlock: bool = False,
    ) -> None:
        self.fail_statement = fail_statement
        self.fail_rollback = fail_rollback
        self.fail_unlock = fail_unlock
        self.executed: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query, args=None):
        sql = " ".join(str(query).split())
        self.executed.append(sql)
        if self.fail_unlock and sql == "SELECT pg_advisory_unlock(%s::bigint)":
            raise RuntimeError("unlock failed")
        if self.fail_statement and self.fail_statement in sql:
            raise RuntimeError("migration failed")
        if "FROM schema_migrations" in sql:
            return _Cursor(rows=[])
        return _Cursor()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.fail_rollback:
            raise RuntimeError("rollback failed")


def _one_migration(tmp_path: Path) -> list[PostgresMigration]:
    sql_path = tmp_path / "0001_sample.sql"
    sql_path.write_text(
        "CREATE TABLE sample_migration(id TEXT);\nINSERT INTO sample_migration VALUES ('1');",
        encoding="utf-8",
    )
    return [
        PostgresMigration(
            version="0001",
            sql_path=sql_path,
            checksum="checksum-0001",
        )
    ]


def test_apply_postgres_migrations_rolls_back_and_releases_lock_on_failure(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        migrations_module,
        "_load_migrations",
        lambda *, namespace: _one_migration(tmp_path),
    )
    connection = _Connection(fail_statement="INSERT INTO sample_migration")

    with pytest.raises(RuntimeError, match="migration failed"):
        apply_postgres_migrations(connection=connection, namespace="proposals")

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.executed[-1] == "SELECT pg_advisory_unlock(%s::bigint)"


def test_apply_postgres_migrations_preserves_original_error_when_cleanup_fails(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        migrations_module,
        "_load_migrations",
        lambda *, namespace: _one_migration(tmp_path),
    )
    connection = _Connection(
        fail_statement="INSERT INTO sample_migration",
        fail_rollback=True,
        fail_unlock=True,
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        apply_postgres_migrations(connection=connection, namespace="proposals")

    assert connection.rollbacks == 1
    assert connection.executed[-1] == "SELECT pg_advisory_unlock(%s::bigint)"


def test_apply_postgres_migrations_surfaces_unlock_failure_after_success(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        migrations_module,
        "_load_migrations",
        lambda *, namespace: _one_migration(tmp_path),
    )
    connection = _Connection(fail_unlock=True)

    with pytest.raises(RuntimeError, match="POSTGRES_MIGRATION_UNLOCK_FAILED:proposals"):
        apply_postgres_migrations(connection=connection, namespace="proposals")

    assert connection.commits == 1


def test_policy_pack_migration_namespace_declares_durable_state_tables() -> None:
    migration_path = (
        Path("src")
        / "infrastructure"
        / "postgres_migrations"
        / "policy_packs"
        / "0001_policy_pack_state.sql"
    )
    sql = migration_path.read_text(encoding="utf-8")

    for table_name in (
        "policy_evaluation_records",
        "policy_evaluation_audit_events",
        "policy_evaluation_idempotency",
        "policy_pack_catalog_versions",
        "policy_pack_catalog_audit_events",
        "policy_pack_catalog_idempotency",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in sql

    assert "source_evidence_hash" in sql
    assert "UNIQUE (" in sql
    assert "ux_policy_pack_catalog_active_version" in sql


def test_policy_pack_migration_enforces_one_active_version_per_pack() -> None:
    migration_path = (
        Path("src")
        / "infrastructure"
        / "postgres_migrations"
        / "policy_packs"
        / "0002_one_active_policy_pack_version.sql"
    )
    sql = " ".join(migration_path.read_text(encoding="utf-8").split())

    assert "DROP INDEX IF EXISTS ux_policy_pack_catalog_active_version" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_policy_pack_catalog_one_active_version" in sql
    assert "ON policy_pack_catalog_versions (policy_pack_id)" in sql
    assert "WHERE activation_state = 'ACTIVE'" in sql
    assert "policy_pack_id, policy_version" not in sql


def test_workspace_migration_namespace_declares_durable_state_tables() -> None:
    migration_path = (
        Path("src")
        / "infrastructure"
        / "postgres_migrations"
        / "workspace"
        / "0001_workspace_state.sql"
    )
    sql = " ".join(migration_path.read_text(encoding="utf-8").split())

    for table_name in (
        "advisory_workspace_sessions",
        "advisory_workspace_saved_versions",
        "advisory_workspace_events",
        "advisory_workspace_idempotency",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in sql

    assert "workspace_id TEXT PRIMARY KEY" in sql
    assert "PRIMARY KEY (workspace_id, workspace_version_id)" in sql
    assert "UNIQUE (workspace_id, version_no)" in sql
    assert "latest_evaluation_request_hash" in sql
    assert "lifecycle_proposal_id" in sql
    assert "retention_status TEXT NOT NULL DEFAULT 'ACTIVE'" in sql
    assert "idx_advisory_workspace_sessions_lifecycle_link" in sql
    assert "idx_advisory_workspace_saved_versions_lookup" in sql
    assert "idx_advisory_workspace_events_lookup" in sql


def test_proposal_migrations_index_lifecycle_history_read_paths() -> None:
    migration_path = (
        Path("src")
        / "infrastructure"
        / "postgres_migrations"
        / "proposals"
        / "0009_lifecycle_history_indexes.sql"
    )
    sql = " ".join(migration_path.read_text(encoding="utf-8").split())

    assert (
        "CREATE INDEX IF NOT EXISTS idx_proposal_workflow_events_history "
        "ON proposal_workflow_events (proposal_id, occurred_at ASC, event_id ASC)"
    ) in sql
    assert (
        "CREATE INDEX IF NOT EXISTS idx_proposal_approvals_history "
        "ON proposal_approvals (proposal_id, occurred_at ASC, approval_id ASC)"
    ) in sql


def test_proposal_lifecycle_integrity_migration_adds_relational_guards() -> None:
    migration_path = (
        Path("src")
        / "infrastructure"
        / "postgres_migrations"
        / "proposals"
        / "0010_proposal_lifecycle_integrity.sql"
    )
    sql = " ".join(migration_path.read_text(encoding="utf-8").split())

    assert "ux_proposal_versions_proposal_version_id" in sql
    assert "ON proposal_versions (proposal_version_id)" in sql
    for constraint_name in (
        "fk_proposal_versions_proposal",
        "fk_proposal_workflow_events_proposal",
        "fk_proposal_workflow_events_related_version",
        "fk_proposal_approvals_proposal",
        "fk_proposal_approvals_related_version",
        "fk_proposal_idempotency_version",
        "fk_proposal_async_operations_proposal",
        "ck_proposal_records_current_version_positive",
        "ck_proposal_records_current_state",
        "ck_proposal_versions_version_positive",
        "ck_proposal_versions_status_at_creation",
        "ck_proposal_workflow_events_event_type",
        "ck_proposal_workflow_events_states",
        "ck_proposal_approvals_type",
    ):
        assert f"ADD CONSTRAINT {constraint_name}" in sql
        assert f"VALIDATE CONSTRAINT {constraint_name}" in sql

    assert "FOREIGN KEY (proposal_id, related_version_no)" in sql
    assert "REFERENCES proposal_versions (proposal_id, version_no)" in sql
    assert "current_state IN (" in sql
    assert "event_type IN (" in sql
    assert "approval_type IN ('RISK', 'COMPLIANCE', 'CLIENT_CONSENT')" in sql


def test_idea_realization_migration_scopes_intake_identity() -> None:
    migration_path = (
        Path("src")
        / "infrastructure"
        / "postgres_migrations"
        / "proposals"
        / "0012_idea_review_realizations.sql"
    )
    sql = " ".join(migration_path.read_text(encoding="utf-8").split())

    assert "intake_id TEXT NOT NULL," in sql
    assert "intake_id TEXT NOT NULL UNIQUE" not in sql
    assert "CONSTRAINT uq_proposal_idea_realization_intake_scope" in sql
    assert "source_claim_registry_key TEXT NOT NULL" in sql
    assert "CONSTRAINT ck_proposal_idea_realization_source_claim" in sql
    assert "UNIQUE (tenant_id, legal_entity_code, portfolio_id, intake_id)" in sql


def test_idea_proposal_outcome_migration_enforces_linkage_and_terminal_posture() -> None:
    migration_path = (
        Path("src")
        / "infrastructure"
        / "postgres_migrations"
        / "proposals"
        / "0013_idea_proposal_outcomes.sql"
    )
    sql = " ".join(migration_path.read_text(encoding="utf-8").split())

    assert "ADD COLUMN IF NOT EXISTS proposal_id TEXT NULL" in sql
    assert "UNIQUE (proposal_id)" in sql
    assert "REFERENCES proposal_records(proposal_id) ON DELETE RESTRICT" in sql
    assert "expected_source_event_version" not in sql
    for status in (
        "PROPOSAL_LINKED",
        "ADVISORY_REJECTED",
        "ADVISORY_CANCELLED",
        "ADVISORY_EXPIRED",
        "ADVISORY_COMPLETED",
    ):
        assert f"'{status}'" in sql
    for reason_code in (
        "advise_proposal_linked",
        "advise_proposal_rejected",
        "advise_proposal_cancelled",
        "advise_proposal_expired",
        "advise_proposal_workflow_completed",
    ):
        assert f"'{reason_code}'" in sql
    assert "status = 'PROPOSAL_LINKED'" in sql
    assert "terminal = FALSE" in sql
    assert "terminal = TRUE" in sql
