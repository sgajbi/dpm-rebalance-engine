import json
from pathlib import Path

import pytest

from src.core.proposals.exceptions import ProposalIdempotencyConflictError
from src.infrastructure.policy_packs.postgres_state import (
    PostgresPolicyEvaluationStateStore,
    PostgresPolicyPackCatalogStateStore,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
POSTGRES_REPOSITORY = REPO_ROOT / "src" / "infrastructure" / "policy_packs" / "postgres.py"
POSTGRES_STATE_HELPER = REPO_ROOT / "src" / "infrastructure" / "policy_packs" / "postgres_state.py"


class _Cursor:
    def __init__(self, *, rows: list[dict] | None = None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self) -> list[dict]:
        return self._rows


class _Connection:
    def __init__(
        self,
        *,
        fail_statement: str | None = None,
        conflict_statement: str | None = None,
        rows_by_statement: dict[str, list[dict]] | None = None,
    ) -> None:
        self.fail_statement = fail_statement
        self.conflict_statement = conflict_statement
        self.rows_by_statement = rows_by_statement or {}
        self.executed: list[tuple[str, tuple | None]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def execute(self, query, args=None):
        sql = " ".join(str(query).split())
        self.executed.append((sql, args))
        if self.fail_statement and self.fail_statement in sql:
            raise RuntimeError("policy persistence failed")
        rowcount = 0 if self.conflict_statement and self.conflict_statement in sql else 1
        for statement, rows in self.rows_by_statement.items():
            if statement in sql:
                return _Cursor(rows=rows, rowcount=rowcount)
        return _Cursor(rowcount=rowcount)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_policy_pack_postgres_repository_remains_delegating_adapter() -> None:
    source = POSTGRES_REPOSITORY.read_text(encoding="utf-8")

    assert "INSERT INTO" not in source
    assert "SELECT" not in source
    assert "FROM policy_" not in source
    assert "ON CONFLICT" not in source
    assert "apply_postgres_migrations" in source
    assert 'namespace="policy_packs"' in source


def test_policy_pack_postgres_state_helper_owns_sql_mapping() -> None:
    source = POSTGRES_STATE_HELPER.read_text(encoding="utf-8")

    assert "policy_evaluation_records" in source
    assert "policy_evaluation_audit_events" in source
    assert "policy_evaluation_idempotency" in source
    assert "policy_pack_catalog_versions" in source
    assert "policy_pack_catalog_audit_events" in source
    assert "policy_pack_catalog_idempotency" in source


def test_policy_pack_postgres_state_helper_guards_transactional_writes() -> None:
    source = POSTGRES_STATE_HELPER.read_text(encoding="utf-8")

    assert "connection.rollback()" in source
    assert "POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT" in source
    assert "POLICY_PACK_IDEMPOTENCY_KEY_CONFLICT" in source
    assert "request_hash=excluded.request_hash" in source
    assert "policy_pack_catalog_idempotency.request_hash = excluded.request_hash" in source
    assert "policy_evaluation_audit_events.request_hash = excluded.request_hash" in source
    assert "policy_pack_catalog_audit_events.request_hash = excluded.request_hash" in source
    assert "old_record.evaluation_status = 'BLOCKED'" in source
    assert "new_record.evaluation_status <> 'BLOCKED'" in source
    assert "POLICY_APPLICABILITY_LEGAL_ENTITY_SOURCE_MISSING" in source
    assert "'{replay_metadata_json,creation_reason}'" in source
    assert "SELECT COUNT(*) FROM policy_evaluation_audit_events" in " ".join(source.split())
    assert "SELECT COUNT(*) FROM policy_pack_catalog_audit_events" in " ".join(source.split())


def test_policy_evaluation_postgres_snapshot_save_rolls_back_on_partial_failure() -> None:
    connection = _Connection(fail_statement="INSERT INTO policy_evaluation_audit_events")
    store = PostgresPolicyEvaluationStateStore(connect=lambda: connection)

    with pytest.raises(RuntimeError, match="policy persistence failed"):
        store.save_snapshot(_policy_evaluation_snapshot())

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.closed is True


def test_policy_evaluation_postgres_snapshot_loads_durable_rows() -> None:
    connection = _Connection(
        rows_by_statement={
            "FROM policy_evaluation_records": [
                {
                    "evaluation_id": "pev_txn_001",
                    "record_json": _json_text(
                        _policy_evaluation_snapshot()["records"]["pev_txn_001"]
                    ),
                }
            ],
            "FROM policy_evaluation_audit_events": [
                {
                    "evaluation_id": "pev_txn_001",
                    "event_json": _json_text(
                        _policy_evaluation_snapshot()["events"]["pev_txn_001"][0]
                    ),
                }
            ],
            "FROM policy_evaluation_idempotency": [
                {
                    "idempotency_key": "idem_txn_001",
                    "request_hash": "sha256:request",
                    "evaluation_id": "pev_txn_001",
                    "event_id": "peev_000001",
                }
            ],
        }
    )
    store = PostgresPolicyEvaluationStateStore(connect=lambda: connection)

    snapshot = store.load_snapshot()

    assert snapshot["records"]["pev_txn_001"]["proposal_id"] == "pp_txn_001"
    assert snapshot["events"]["pev_txn_001"][0]["event_id"] == "peev_000001"
    assert snapshot["idempotency"][0]["idempotency_key"] == "idem_txn_001"
    assert snapshot["identity_index"] == []
    assert connection.closed is True


def test_policy_evaluation_postgres_snapshot_save_commits_all_durable_rows() -> None:
    connection = _Connection()
    store = PostgresPolicyEvaluationStateStore(connect=lambda: connection)

    store.save_snapshot(_policy_evaluation_snapshot())

    executed_sql = [statement for statement, _args in connection.executed]
    executed_args = [args for _statement, args in connection.executed]
    assert any("INSERT INTO policy_evaluation_records" in sql for sql in executed_sql)
    assert any("INSERT INTO policy_evaluation_audit_events" in sql for sql in executed_sql)
    assert any("INSERT INTO policy_evaluation_idempotency" in sql for sql in executed_sql)
    assert any(args and "2026-05-26T00:00:00+00:00" in args for args in executed_args)
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_policy_evaluation_postgres_snapshot_rolls_back_on_idempotency_conflict() -> None:
    connection = _Connection(conflict_statement="INSERT INTO policy_evaluation_idempotency")
    store = PostgresPolicyEvaluationStateStore(connect=lambda: connection)

    with pytest.raises(
        ProposalIdempotencyConflictError,
        match="POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT",
    ):
        store.save_snapshot(_policy_evaluation_snapshot())

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed is True


def test_policy_pack_catalog_postgres_snapshot_loads_durable_rows() -> None:
    connection = _Connection(
        rows_by_statement={
            "FROM policy_pack_catalog_versions": [
                {"definition_json": _json_text(_policy_pack_catalog_snapshot()["definitions"][0])}
            ],
            "FROM policy_pack_catalog_audit_events": [
                {"event_json": _json_text(_policy_pack_catalog_snapshot()["events"][0])}
            ],
            "FROM policy_pack_catalog_idempotency": [
                {
                    "idempotency_key": "idem_catalog_001",
                    "request_hash": "sha256:catalog-request",
                    "policy_pack_id": "SG_PRIVATE_BANKING_REFERENCE",
                    "policy_version": "2026.05",
                    "event_id": "pcat_000001",
                }
            ],
        }
    )
    store = PostgresPolicyPackCatalogStateStore(connect=lambda: connection)

    snapshot = store.load_snapshot()

    assert snapshot["definitions"][0]["policy_pack_id"] == "SG_PRIVATE_BANKING_REFERENCE"
    assert snapshot["events"][0]["event_id"] == "pcat_000001"
    assert snapshot["idempotency"][0]["idempotency_key"] == "idem_catalog_001"
    assert connection.closed is True


def test_policy_pack_catalog_postgres_snapshot_save_commits_all_durable_rows() -> None:
    connection = _Connection()
    store = PostgresPolicyPackCatalogStateStore(connect=lambda: connection)

    store.save_snapshot(_policy_pack_catalog_snapshot())

    executed_sql = [statement for statement, _args in connection.executed]
    executed_args = [args for _statement, args in connection.executed]
    assert any("INSERT INTO policy_pack_catalog_versions" in sql for sql in executed_sql)
    assert any("INSERT INTO policy_pack_catalog_audit_events" in sql for sql in executed_sql)
    assert any("INSERT INTO policy_pack_catalog_idempotency" in sql for sql in executed_sql)
    assert any(args and "2026-05-26T00:00:00+00:00" in args for args in executed_args)
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_policy_pack_catalog_postgres_snapshot_rolls_back_on_event_conflict() -> None:
    connection = _Connection(conflict_statement="INSERT INTO policy_pack_catalog_audit_events")
    store = PostgresPolicyPackCatalogStateStore(connect=lambda: connection)

    with pytest.raises(
        ProposalIdempotencyConflictError,
        match="POLICY_PACK_CATALOG_EVENT_CONFLICT",
    ):
        store.save_snapshot(_policy_pack_catalog_snapshot())

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed is True


def _json_text(value: dict) -> str:
    return json.dumps(value)


def _policy_evaluation_snapshot() -> dict:
    record = {
        "evaluation_id": "pev_txn_001",
        "proposal_id": "pp_txn_001",
        "proposal_version_id": "ppv_txn_001",
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "policy_pack_id": "SG_PRIVATE_BANKING_REFERENCE",
        "policy_version": "2026.05",
        "generated_at": "2026-05-26T00:00:00+00:00",
        "created_by": "advisor_1",
        "evaluation_status": "PENDING_REVIEW",
        "policy_content_hash": "sha256:policy",
        "source_evidence_hash": "sha256:source",
        "evaluation_hash": "sha256:evaluation",
        "rule_result_hashes": {},
        "evaluation_json": {},
        "source_refs": [],
        "source_gaps": [],
        "approval_dependencies": [],
        "disclosure_requirements": [],
        "consent_requirements": [],
        "review_events_json": [],
        "sign_off_events_json": [],
        "report_archive_refs_json": [],
        "replay_metadata_json": {},
    }
    event = {
        "event_id": "peev_000001",
        "evaluation_id": "pev_txn_001",
        "proposal_id": "pp_txn_001",
        "proposal_version_id": "ppv_txn_001",
        "event_type": "POLICY_EVALUATION_FINALIZED",
        "actor_id": "advisor_1",
        "occurred_at": "2026-05-26T00:00:00+00:00",
        "content_hash": "sha256:evaluation",
        "idempotency_key": "idem_txn_001",
        "reason_json": {"idempotency_request_hash": "sha256:request"},
    }
    return {
        "records": {"pev_txn_001": record},
        "events": {"pev_txn_001": [event]},
        "idempotency": [
            {
                "idempotency_key": "idem_txn_001",
                "request_hash": "sha256:request",
                "evaluation_id": "pev_txn_001",
                "event_id": "peev_000001",
            }
        ],
        "identity_index": [],
    }


def _policy_pack_catalog_snapshot() -> dict:
    definition = {
        "policy_pack_id": "SG_PRIVATE_BANKING_REFERENCE",
        "policy_version": "2026.05",
        "activation_state": "ACTIVE",
        "content_hash": "sha256:catalog",
        "jurisdiction": "SG",
        "booking_centers": ["SG"],
        "legal_entities": ["LOTUS_PRIVATE_BANK_SG"],
        "client_segments": ["PRIVATE_BANKING"],
        "policy_product_scope": ["ADVISORY_PROPOSAL"],
        "rules": [],
    }
    event = {
        "event_id": "pcat_000001",
        "policy_pack_id": "SG_PRIVATE_BANKING_REFERENCE",
        "policy_version": "2026.05",
        "event_type": "POLICY_PACK_ACTIVATED",
        "actor_id": "policy_admin_1",
        "occurred_at": "2026-05-26T00:00:00+00:00",
        "idempotency_key": "idem_catalog_001",
        "reason": {"idempotency_request_hash": "sha256:catalog-request"},
    }
    return {
        "definitions": [definition],
        "events": [event],
        "idempotency": [
            {
                "idempotency_key": "idem_catalog_001",
                "request_hash": "sha256:catalog-request",
                "policy_pack_id": "SG_PRIVATE_BANKING_REFERENCE",
                "policy_version": "2026.05",
                "event_id": "pcat_000001",
            }
        ],
    }
