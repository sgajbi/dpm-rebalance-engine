import sys
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import ModuleType

import pytest

import src.infrastructure.proposals.postgres as postgres_module
from src.core.advisor_cockpit.persistence import (
    CockpitAcknowledgementIdempotencyRecord,
    CockpitAcknowledgementRecord,
)
from src.core.proposals.exceptions import (
    ProposalIdempotencyConflictError,
    ProposalStateConflictError,
)
from src.core.proposals.idea_intake_persistence import IdeaProposalIntakeRecord
from src.core.proposals.idea_review_realization import (
    IdeaProposalRealizationOutcomeRecord,
    IdeaProposalRealizationRecord,
)
from src.core.proposals.models import (
    ProposalApprovalRecordData,
    ProposalAsyncOperationRecord,
    ProposalIdempotencyRecord,
    ProposalMemoEventRecord,
    ProposalMemoIdempotencyRecord,
    ProposalMemoRecord,
    ProposalRecord,
    ProposalSimulationIdempotencyRecord,
    ProposalVersionRecord,
    ProposalWorkflowEventRecord,
)
from src.infrastructure.proposals import postgres_async_operations, postgres_mappers
from src.infrastructure.proposals.postgres import PostgresProposalRepository


class _FakeCursor:
    def __init__(self, row=None, rows=None, rowcount: int = 0):
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return list(self._rows)


def _row(field_names: str, args) -> dict:
    return dict(zip(field_names.split(), args, strict=True))


def _matching(rows, **criteria):
    return [
        row for row in rows if all(row[field] == expected for field, expected in criteria.items())
    ]


def _sorted_matching(rows, *sort_fields, reverse=False, **criteria):
    return sorted(
        _matching(rows, **criteria),
        key=lambda row: tuple(row[field] for field in sort_fields),
        reverse=reverse,
    )


def _first_matching(rows, **criteria):
    return next(iter(_matching(rows, **criteria)), None)


def _ordered_parent_rows(rows, parent_ids, *sort_fields):
    parent_order = {parent_id: index for index, parent_id in enumerate(parent_ids)}
    return sorted(
        (row for row in rows if row["proposal_id"] in parent_order),
        key=lambda row: (
            parent_order[row["proposal_id"]],
            *(row[field] for field in sort_fields),
        ),
    )


def _apply_proposal_filters(rows, sql, args, arg_index, *, prefix=""):
    for clause, field, matches in _PROPOSAL_FILTERS:
        if f"{prefix}{clause}" in sql:
            expected = args[arg_index]
            arg_index += 1
            rows = [row for row in rows if matches(row[field], expected)]
    return rows, arg_index


_IDEMPOTENCY_FIELDS = "idempotency_key request_hash proposal_id proposal_version_no created_at"
_SIMULATION_IDEMPOTENCY_FIELDS = "idempotency_key request_hash response_json created_at"
_IDEA_INTAKE_FIELDS = (
    "registry_key request_fingerprint response_json created_at_utc expires_at_utc legal_hold"
)
_IDEA_REALIZATION_FIELDS = (
    "realization_id intake_id review_work_id review_work_status tenant_id legal_entity_code "
    "portfolio_id "
    "idea_candidate_id conversion_intent_id source_evidence_fingerprint current_status "
    "current_source_event_version created_at_utc updated_at_utc"
)
_IDEA_REALIZATION_OUTCOME_FIELDS = (
    "outcome_id realization_id source_event_version status reason_code occurred_at_utc "
    "review_work_id proposal_id terminal"
)
_MEMO_IDEMPOTENCY_FIELDS = (
    "idempotency_key request_hash memo_id proposal_id proposal_version_no created_at"
)
_MEMO_FIELDS = (
    "memo_id proposal_id proposal_version_no proposal_version_id artifact_id memo_version "
    "memo_status lifecycle_status created_by created_at source_input_hash memo_hash memo_json "
    "projection_json review_events_json report_package_events_json archive_refs_json ai_refs_json "
    "replay_metadata_json"
)
_MEMO_EVENT_FIELDS = (
    "event_id memo_id proposal_id proposal_version_no event_type actor_id occurred_at reason_json"
)
_ACKNOWLEDGEMENT_FIELDS = (
    "acknowledgement_id action_item_id action_item_version acknowledged_by acknowledged_at "
    "acknowledgement_note correlation_id reason_json"
)
_ACKNOWLEDGEMENT_IDEMPOTENCY_FIELDS = (
    "idempotency_key request_hash acknowledgement_id action_item_id created_at"
)
_OPERATION_FIELDS = (
    "operation_id operation_type status correlation_id idempotency_key proposal_id created_by "
    "created_at payload_json attempt_count max_attempts started_at lease_expires_at finished_at "
    "result_json error_json"
)
_PROPOSAL_FIELDS = (
    "proposal_id portfolio_id mandate_id jurisdiction created_by created_at last_event_at "
    "current_state current_version_no title advisor_notes lifecycle_origin source_workspace_id"
)
_PROPOSAL_UPDATE_FIELDS = (
    "portfolio_id mandate_id jurisdiction created_by created_at last_event_at current_state "
    "current_version_no title advisor_notes lifecycle_origin source_workspace_id"
)
_VERSION_FIELDS = (
    "proposal_version_id proposal_id version_no created_at request_hash artifact_hash "
    "simulation_hash status_at_creation proposal_result_json artifact_json evidence_bundle_json "
    "gate_decision_json"
)
_WORKFLOW_EVENT_FIELDS = (
    "event_id proposal_id event_type from_state to_state actor_id occurred_at reason_json "
    "related_version_no"
)
_APPROVAL_FIELDS = (
    "approval_id proposal_id approval_type approved actor_id occurred_at details_json "
    "related_version_no"
)
_TRANSACTIONAL_STORES = (
    "idempotency simulation_idempotency operations proposals versions events approvals memos "
    "memo_idempotency memo_events cockpit_acknowledgements "
    "cockpit_acknowledgement_idempotency idea_intakes idea_intake_purge_events "
    "idea_realizations idea_realization_outcomes schema_migrations"
).split()
_MIGRATION_DEFAULTS = (
    ("lifecycle_origin", "proposals", "DIRECT_CREATE"),
    ("source_workspace_id", "proposals", None),
    ("payload_json", "operations", "{}"),
    ("attempt_count", "operations", 0),
    ("max_attempts", "operations", 3),
    ("lease_expires_at", "operations", None),
)
_PROPOSAL_FILTERS = (
    ("portfolio_id = %s", "portfolio_id", lambda actual, expected: actual == expected),
    ("current_state = %s", "current_state", lambda actual, expected: actual == expected),
    ("created_by = %s", "created_by", lambda actual, expected: actual == expected),
    ("created_at >= %s", "created_at", lambda actual, expected: actual >= expected),
    ("created_at <= %s", "created_at", lambda actual, expected: actual <= expected),
)


class _FakeConnection:
    def __init__(self):
        for field in _TRANSACTIONAL_STORES:
            setattr(self, field, {})
        self.suppress_idea_intake_read = False
        self.executed_sql = []
        self.executed_args = []
        self.rollback_count = 0
        self._transaction_snapshot = None

    def execute(self, query, args=None):
        sql = " ".join(str(query).split())
        self.executed_sql.append(sql)
        self.executed_args.append(tuple(args or ()))
        if _is_transactional_write_sql(sql):
            self._ensure_transaction_snapshot()
        if sql in {
            "SELECT pg_advisory_lock(%s::bigint)",
            "SELECT pg_advisory_unlock(%s::bigint)",
        } or sql.startswith(("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX")):
            return _FakeCursor()
        for field, store, default in _MIGRATION_DEFAULTS:
            if sql.startswith("ALTER TABLE") and f"ADD COLUMN IF NOT EXISTS {field}" in sql:
                for row in getattr(self, store).values():
                    row.setdefault(field, default)
                return _FakeCursor()
        if sql.startswith("ALTER TABLE"):
            return _FakeCursor()
        if "FROM schema_migrations" in sql:
            namespace = args[0]
            rows = [
                {"version": version, "checksum": checksum}
                for (stored_namespace, version), checksum in self.schema_migrations.items()
                if stored_namespace == namespace
            ]
            rows = sorted(rows, key=lambda row: row["version"])
            return _FakeCursor(rows=rows)
        if "INSERT INTO schema_migrations" in sql:
            self.schema_migrations[(args[1], args[0])] = args[2]
            return _FakeCursor()
        if "INSERT INTO proposal_idempotency" in sql:
            self.idempotency[args[0]] = _row(_IDEMPOTENCY_FIELDS, args)
            return _FakeCursor()
        if "DELETE FROM proposal_idea_intakes" in sql:
            as_of, target_key, limit, purged_at = args
            expired = sorted(
                (
                    stored
                    for stored in self.idea_intakes.values()
                    if not stored["legal_hold"] and stored["expires_at_utc"] <= as_of
                ),
                key=lambda stored: (
                    stored["registry_key"] != target_key,
                    stored["expires_at_utc"],
                    stored["registry_key"],
                ),
            )[:limit]
            for stored in expired:
                self.idea_intake_purge_events[stored["registry_key"]] = {
                    **stored,
                    "purged_at_utc": purged_at,
                    "reason_code": "REPLAY_WINDOW_EXPIRED",
                }
                del self.idea_intakes[stored["registry_key"]]
            return _FakeCursor()
        if "INSERT INTO proposal_idea_intakes" in sql:
            inserted = args[0] not in self.idea_intakes
            self.idea_intakes.setdefault(args[0], _row(_IDEA_INTAKE_FIELDS, args))
            return _FakeCursor({"registry_key": args[0]} if inserted else None)
        if "FROM proposal_idea_intakes" in sql:
            row = None if self.suppress_idea_intake_read else self.idea_intakes.get(args[0])
            return _FakeCursor(row)
        if "INSERT INTO proposal_idea_review_realizations" in sql:
            self.idea_realizations.setdefault(args[0], _row(_IDEA_REALIZATION_FIELDS, args))
            return _FakeCursor()
        if "FROM proposal_idea_review_realizations" in sql:
            if "WHERE realization_id = %s" in sql:
                return _FakeCursor(self.idea_realizations.get(args[0]))
            row = next(
                (
                    stored
                    for stored in self.idea_realizations.values()
                    if stored["intake_id"] == args[0]
                    and stored["tenant_id"] == args[1]
                    and stored["legal_entity_code"] == args[2]
                    and stored["portfolio_id"] == args[3]
                ),
                None,
            )
            return _FakeCursor(row)
        if "INSERT INTO proposal_idea_realization_outcomes" in sql:
            key = (args[1], args[2])
            self.idea_realization_outcomes.setdefault(
                key, _row(_IDEA_REALIZATION_OUTCOME_FIELDS, args)
            )
            return _FakeCursor()
        if "FROM proposal_idea_realization_outcomes" in sql:
            if "source_event_version = %s" in sql:
                return _FakeCursor(self.idea_realization_outcomes.get((args[0], args[1])))
            rows = [
                stored
                for (realization_id, _), stored in self.idea_realization_outcomes.items()
                if realization_id == args[0]
            ]
            return _FakeCursor(rows=sorted(rows, key=lambda stored: stored["source_event_version"]))
        if "FROM proposal_idempotency WHERE idempotency_key = %s" in sql:
            return _FakeCursor(self.idempotency.get(args[0]))
        if "INSERT INTO proposal_simulation_idempotency" in sql:
            self.simulation_idempotency[args[0]] = _row(_SIMULATION_IDEMPOTENCY_FIELDS, args)
            return _FakeCursor()
        if "FROM proposal_simulation_idempotency WHERE idempotency_key = %s" in sql:
            return _FakeCursor(self.simulation_idempotency.get(args[0]))
        if "INSERT INTO proposal_memo_idempotency" in sql:
            self.memo_idempotency.setdefault(args[0], _row(_MEMO_IDEMPOTENCY_FIELDS, args))
            return _FakeCursor()
        if "FROM proposal_memo_idempotency WHERE idempotency_key = %s" in sql:
            return _FakeCursor(self.memo_idempotency.get(args[0]))
        if "INSERT INTO proposal_memos" in sql:
            self.memos.setdefault(args[0], _row(_MEMO_FIELDS, args))
            return _FakeCursor()
        if "FROM proposal_memos WHERE memo_id = %s" in sql:
            return _FakeCursor(self.memos.get(args[0]))
        if "FROM proposal_memos WHERE proposal_id = %s AND proposal_version_no = %s" in sql:
            row = _first_matching(
                self.memos.values(),
                proposal_id=args[0],
                proposal_version_no=args[1],
            )
            return _FakeCursor(row)
        if "FROM proposal_memos WHERE proposal_id = %s" in sql:
            rows = _sorted_matching(
                self.memos.values(),
                "proposal_version_no",
                "created_at",
                "memo_id",
                proposal_id=args[0],
            )
            return _FakeCursor(rows=rows)
        if "FROM proposal_memos" in sql and "WHERE proposal_id = ANY(%s)" in sql:
            rows = _ordered_parent_rows(
                self.memos.values(),
                args[0],
                "proposal_version_no",
                "created_at",
                "memo_id",
            )
            return _FakeCursor(rows=rows)
        if "INSERT INTO proposal_memo_events" in sql:
            self.memo_events.setdefault(args[0], _row(_MEMO_EVENT_FIELDS, args))
            return _FakeCursor()
        if "FROM proposal_memo_events" in sql and "ORDER BY occurred_at ASC, event_id ASC" in sql:
            rows = _sorted_matching(
                self.memo_events.values(), "occurred_at", "event_id", memo_id=args[0]
            )
            return _FakeCursor(rows=rows)
        if "INSERT INTO advisor_cockpit_acknowledgements" in sql:
            self.cockpit_acknowledgements[args[1]] = _row(_ACKNOWLEDGEMENT_FIELDS, args)
            return _FakeCursor()
        if (
            "FROM advisor_cockpit_acknowledgements" in sql
            and "WHERE action_item_id = ANY(%s)" in sql
        ):
            action_item_ids = set(args[0])
            rows = [
                row
                for action_item_id, row in self.cockpit_acknowledgements.items()
                if action_item_id in action_item_ids
            ]
            return _FakeCursor(rows=rows)
        if "FROM advisor_cockpit_acknowledgements" in sql:
            return _FakeCursor(self.cockpit_acknowledgements.get(args[0]))
        if "INSERT INTO advisor_cockpit_acknowledgement_idempotency" in sql:
            self.cockpit_acknowledgement_idempotency.setdefault(
                args[0], _row(_ACKNOWLEDGEMENT_IDEMPOTENCY_FIELDS, args)
            )
            return _FakeCursor()
        if "FROM advisor_cockpit_acknowledgement_idempotency" in sql:
            return _FakeCursor(self.cockpit_acknowledgement_idempotency.get(args[0]))
        if "INSERT INTO proposal_async_operations" in sql:
            operation = _row(_OPERATION_FIELDS, args[:16])
            if "ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING" in sql:
                inserted_operation_id = args[0]
                idempotency_key = args[4]
                existing = _first_matching(
                    self.operations.values(), idempotency_key=idempotency_key
                )
                if existing is None:
                    self.operations[inserted_operation_id] = operation
                    return _FakeCursor(operation)
                return _FakeCursor(existing)
            self.operations[args[0]] = operation
            return _FakeCursor()
        if "FROM proposal_async_operations WHERE operation_id = %s" in sql:
            return _FakeCursor(self.operations.get(args[0]))
        if "FROM proposal_async_operations WHERE correlation_id = %s" in sql:
            row = _first_matching(self.operations.values(), correlation_id=args[0])
            return _FakeCursor(row)
        if (
            "FROM proposal_async_operations WHERE idempotency_key = %s" in sql
            and "ORDER BY created_at DESC, operation_id DESC" in sql
        ):
            rows = _sorted_matching(
                self.operations.values(),
                "created_at",
                "operation_id",
                reverse=True,
                idempotency_key=args[0],
            )
            return _FakeCursor(rows[0] if rows else None)
        if (
            "FROM proposal_async_operations" in sql
            and "ORDER BY created_at ASC, operation_id ASC" in sql
        ):
            as_of = args[0]
            rows = []
            for row in self.operations.values():
                if row["status"] == "PENDING":
                    rows.append(row)
                    continue
                if (
                    row["status"] == "RUNNING"
                    and row["finished_at"] is None
                    and row["lease_expires_at"] is not None
                    and row["lease_expires_at"] <= as_of
                ):
                    rows.append(row)
            rows = sorted(rows, key=lambda row: (row["created_at"], row["operation_id"]))
            if "LIMIT %s" in sql:
                rows = rows[: args[1]]
            return _FakeCursor(rows=rows)
        if "INSERT INTO proposal_records" in sql:
            self.proposals[args[0]] = _row(_PROPOSAL_FIELDS, args)
            return _FakeCursor()
        if sql.startswith("UPDATE proposal_records SET"):
            return self._execute_update_proposal_records(args)
        if "FROM proposal_records WHERE proposal_id = %s" in sql and "ORDER BY" not in sql:
            return _FakeCursor(self.proposals.get(args[0]))
        if "FROM proposal_records" in sql and "ORDER BY created_at DESC, proposal_id DESC" in sql:
            rows = list(self.proposals.values())
            rows, arg_index = _apply_proposal_filters(rows, sql, args, 0)
            if "FROM proposal_records cursor_record WHERE cursor_record.proposal_id = %s" in sql:
                cursor = args[arg_index]
                arg_index += 1
                cursor_row = self.proposals.get(cursor)
                if cursor_row is None:
                    return _FakeCursor(rows=[])
                cursor_rows, arg_index = _apply_proposal_filters(
                    [cursor_row], sql, args, arg_index, prefix="cursor_record."
                )
                if not cursor_rows:
                    return _FakeCursor(rows=[])
                cursor_key = (cursor_row["created_at"], cursor_row["proposal_id"])
                rows = [row for row in rows if (row["created_at"], row["proposal_id"]) < cursor_key]
            rows = sorted(
                rows,
                key=lambda row: (row["created_at"], row["proposal_id"]),
                reverse=True,
            )
            if "LIMIT %s" in sql:
                rows = rows[: args[arg_index]]
            return _FakeCursor(rows=rows)
        if "INSERT INTO proposal_versions" in sql:
            self.versions.setdefault((args[1], args[2]), _row(_VERSION_FIELDS, args))
            return _FakeCursor()
        if "FROM proposal_versions WHERE proposal_id = %s AND version_no = %s" in sql:
            return _FakeCursor(self.versions.get((args[0], args[1])))
        if "FROM proposal_versions" in sql and "ORDER BY version_no ASC" in sql:
            rows = _sorted_matching(self.versions.values(), "version_no", proposal_id=args[0])
            return _FakeCursor(rows=rows)
        if "FROM proposal_versions" in sql and "ORDER BY version_no DESC" in sql:
            rows = _sorted_matching(
                self.versions.values(), "version_no", reverse=True, proposal_id=args[0]
            )
            return _FakeCursor(rows[0] if rows else None)
        if "INSERT INTO proposal_workflow_events" in sql:
            self.events.setdefault(args[0], _row(_WORKFLOW_EVENT_FIELDS, args))
            return _FakeCursor()
        if "FROM proposal_workflow_events" in sql and "WHERE event_id = %s" in sql:
            return _FakeCursor(self.events.get(args[0]))
        if (
            "FROM proposal_workflow_events" in sql
            and "ORDER BY occurred_at ASC, event_id ASC" in sql
        ):
            rows = _sorted_matching(
                self.events.values(), "occurred_at", "event_id", proposal_id=args[0]
            )
            return _FakeCursor(rows=rows)
        if "FROM proposal_workflow_events" in sql and "WHERE proposal_id = ANY(%s)" in sql:
            rows = _ordered_parent_rows(self.events.values(), args[0], "occurred_at", "event_id")
            return _FakeCursor(rows=rows)
        if "INSERT INTO proposal_approvals" in sql:
            self.approvals.setdefault(args[0], _row(_APPROVAL_FIELDS, args))
            return _FakeCursor()
        if "FROM proposal_approvals" in sql and "WHERE approval_id = %s" in sql:
            return _FakeCursor(self.approvals.get(args[0]))
        if "FROM proposal_approvals" in sql and "ORDER BY occurred_at ASC, approval_id ASC" in sql:
            rows = _sorted_matching(
                self.approvals.values(), "occurred_at", "approval_id", proposal_id=args[0]
            )
            return _FakeCursor(rows=rows)
        if "FROM proposal_approvals" in sql and "WHERE proposal_id = ANY(%s)" in sql:
            rows = _ordered_parent_rows(
                self.approvals.values(), args[0], "occurred_at", "approval_id"
            )
            return _FakeCursor(rows=rows)
        raise AssertionError(f"Unhandled SQL in fake connection: {sql}")

    def _ensure_transaction_snapshot(self):
        if self._transaction_snapshot is not None:
            return
        self._transaction_snapshot = {
            field: deepcopy(getattr(self, field)) for field in _TRANSACTIONAL_STORES
        }

    def _restore_transaction_snapshot(self):
        if self._transaction_snapshot is None:
            return
        for field, value in self._transaction_snapshot.items():
            setattr(self, field, value)
        self._transaction_snapshot = None

    def _execute_update_proposal_records(self, args):
        proposal_id = args[12]
        expected_current_state = args[13]
        expected_current_version_no = args[14]
        current = self.proposals.get(proposal_id)
        if (
            current is None
            or current["current_state"] != expected_current_state
            or current["current_version_no"] != expected_current_version_no
        ):
            return _FakeCursor(rowcount=0)
        current.update(_row(_PROPOSAL_UPDATE_FIELDS, args[:12]))
        return _FakeCursor(rowcount=1)

    def commit(self):
        self._transaction_snapshot = None

    def rollback(self):
        self.rollback_count += 1
        self._restore_transaction_snapshot()

    def close(self): ...


class _NoOperationReturnedConnection(_FakeConnection):
    def execute(self, query, args=None):
        sql = " ".join(str(query).split())
        if (
            "INSERT INTO proposal_async_operations" in sql
            and "ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING" in sql
        ):
            self.executed_sql.append(sql)
            self.executed_args.append(tuple(args or ()))
            return _FakeCursor()
        return super().execute(query, args)


class _FailingAfterWriteConnection(_FakeConnection):
    def __init__(self, *, fail_sql_fragment: str):
        super().__init__()
        self._fail_sql_fragment = fail_sql_fragment

    def execute(self, query, args=None):
        sql = " ".join(str(query).split())
        cursor = super().execute(query, args)
        if self._fail_sql_fragment in sql:
            raise RuntimeError(f"fault injected after {self._fail_sql_fragment}")
        return cursor


def _is_transactional_write_sql(sql: str) -> bool:
    return sql.startswith(("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER "))


def _build_repository(monkeypatch, connection=None):
    connection = connection or _FakeConnection()
    monkeypatch.setattr(postgres_module, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        PostgresProposalRepository,
        "_connect",
        lambda self: connection,  # noqa: ARG005
    )
    repository = PostgresProposalRepository(dsn="postgresql://user:pass@localhost:5432/proposals")
    return repository, connection


def test_postgres_repository_requires_dsn():
    try:
        PostgresProposalRepository(dsn="")
    except RuntimeError as exc:
        assert str(exc) == "PROPOSAL_POSTGRES_DSN_REQUIRED"
    else:
        raise AssertionError("Expected RuntimeError for missing proposal postgres dsn")


def test_postgres_repository_requires_driver(monkeypatch):
    monkeypatch.setattr(postgres_module, "find_spec", lambda _name: None)
    try:
        PostgresProposalRepository(dsn="postgresql://user:pass@localhost:5432/proposals")
    except RuntimeError as exc:
        assert str(exc) == "PROPOSAL_POSTGRES_DRIVER_MISSING"
    else:
        raise AssertionError("Expected RuntimeError for missing proposal postgres driver")


def test_postgres_repository_initializes_proposal_list_keyset_indexes(monkeypatch):
    _, connection = _build_repository(monkeypatch)

    assert any(
        sql
        == (
            "CREATE INDEX IF NOT EXISTS idx_proposal_records_list_created "
            "ON proposal_records (created_at DESC, proposal_id DESC)"
        )
        for sql in connection.executed_sql
    )
    assert any(
        sql
        == (
            "CREATE INDEX IF NOT EXISTS idx_proposal_records_list_portfolio_state_advisor "
            "ON proposal_records ( portfolio_id, current_state, created_by, "
            "created_at DESC, proposal_id DESC )"
        )
        for sql in connection.executed_sql
    )
    assert ("proposals", "proposals:0006") in connection.schema_migrations


def test_postgres_repository_idempotency_roundtrip(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    created_at = datetime.now(timezone.utc)
    record = ProposalIdempotencyRecord(
        idempotency_key="idem-prop-pg-1",
        request_hash="sha256:req",
        proposal_id="pp_001",
        proposal_version_no=1,
        created_at=created_at,
    )

    assert repository.get_idempotency(idempotency_key=record.idempotency_key) is None
    repository.save_idempotency(record)
    loaded = repository.get_idempotency(idempotency_key=record.idempotency_key)
    assert loaded is not None
    assert loaded.idempotency_key == "idem-prop-pg-1"
    assert loaded.request_hash == "sha256:req"
    assert loaded.proposal_id == "pp_001"
    assert loaded.proposal_version_no == 1
    assert loaded.created_at == created_at


def _idea_intake_record(created_at: datetime, *, registry_key: str) -> IdeaProposalIntakeRecord:
    realization = IdeaProposalRealizationRecord(
        realization_id="ipr_123456789abc",
        intake_id="ipi_123456789abc",
        review_work_id="iarw_123456789abc",
        review_work_status="PENDING_ADVISER_REVIEW",
        tenant_id="tenant-private-bank-sg",
        legal_entity_code="SGPB",
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        idea_candidate_id="idea_candidate_001",
        conversion_intent_id="conversion_intent_001",
        source_evidence_fingerprint=f"sha256:{'a' * 64}",
        current_status="ACCEPTED_FOR_REVIEW",
        current_source_event_version=1,
        created_at_utc=created_at,
        updated_at_utc=created_at,
    )
    return IdeaProposalIntakeRecord(
        registry_key=registry_key,
        request_fingerprint="sha256:request",
        response_json='{"intake_status":"ACCEPTED"}',
        created_at_utc=created_at,
        expires_at_utc=created_at + timedelta(hours=24),
        realization=realization,
        initial_outcome=IdeaProposalRealizationOutcomeRecord(
            outcome_id="ipro_123456789abc",
            realization_id=realization.realization_id,
            source_event_version=1,
            status="ACCEPTED_FOR_REVIEW",
            reason_code="idea_conversion_accepted_for_adviser_review",
            occurred_at_utc=created_at,
            review_work_id=realization.review_work_id,
            proposal_id=None,
            terminal=False,
        ),
    )


def test_postgres_repository_claims_replays_and_conflicts_idea_intake(monkeypatch):
    repository, connection = _build_repository(monkeypatch)
    created_at = datetime.now(timezone.utc)
    record = _idea_intake_record(created_at, registry_key="scope:key")

    assert repository.claim_idea_proposal_intake(record).replayed is False
    assert repository.claim_idea_proposal_intake(record).replayed is True
    with pytest.raises(ProposalIdempotencyConflictError):
        repository.claim_idea_proposal_intake(replace(record, request_fingerprint="sha256:changed"))
    connection.suppress_idea_intake_read = True
    with pytest.raises(RuntimeError, match="IDEA_PROPOSAL_INTAKE_PERSISTENCE_FAILED"):
        repository.claim_idea_proposal_intake(replace(record, registry_key="scope:unreadable"))


def test_postgres_repository_reuses_expired_intake_key_but_preserves_legal_hold(monkeypatch):
    repository, connection = _build_repository(monkeypatch)
    created_at = datetime.now(timezone.utc)
    record = _idea_intake_record(created_at, registry_key="scope:retained-key")
    repository.claim_idea_proposal_intake(record)

    replacement = replace(
        record,
        request_fingerprint="sha256:replacement",
        created_at_utc=record.expires_at_utc,
        expires_at_utc=record.expires_at_utc + timedelta(hours=24),
    )
    assert repository.claim_idea_proposal_intake(replacement).replayed is False
    purge_sql_index = next(
        index
        for index, sql in enumerate(connection.executed_sql)
        if "INSERT INTO proposal_idea_intake_purge_events" in sql
    )
    assert "response_json" not in connection.executed_sql[purge_sql_index]
    assert connection.executed_args[purge_sql_index][2] == 128

    connection.idea_intakes[record.registry_key]["legal_hold"] = True
    held_replacement = replace(
        replacement,
        request_fingerprint="sha256:held-replacement",
        created_at_utc=replacement.expires_at_utc,
        expires_at_utc=replacement.expires_at_utc + timedelta(hours=24),
    )
    with pytest.raises(ProposalIdempotencyConflictError):
        repository.claim_idea_proposal_intake(held_replacement)


def test_postgres_repository_simulation_idempotency_roundtrip(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    created_at = datetime.now(timezone.utc)
    record = ProposalSimulationIdempotencyRecord(
        idempotency_key="idem-prop-sim-pg-1",
        request_hash="sha256:req-sim",
        response_json={"proposal_run_id": "pr_001", "status": "READY"},
        created_at=created_at,
    )

    assert repository.get_simulation_idempotency(idempotency_key=record.idempotency_key) is None
    repository.save_simulation_idempotency(record)
    loaded = repository.get_simulation_idempotency(idempotency_key=record.idempotency_key)
    assert loaded is not None
    assert loaded.idempotency_key == record.idempotency_key
    assert loaded.request_hash == "sha256:req-sim"
    assert loaded.response_json["proposal_run_id"] == "pr_001"
    assert loaded.created_at == created_at


def test_postgres_repository_create_update_and_lookup_operation(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    created_at = datetime.now(timezone.utc)
    operation = ProposalAsyncOperationRecord(
        operation_id="pop_001",
        operation_type="CREATE_PROPOSAL",
        status="PENDING",
        correlation_id="corr-prop-1",
        idempotency_key="idem-prop-pg-1",
        proposal_id=None,
        created_by="advisor_1",
        created_at=created_at,
        payload_json={"payload": {"created_by": "advisor_1"}, "idempotency_key": "idem-prop-pg-1"},
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        lease_expires_at=None,
        finished_at=None,
        result_json=None,
        error_json=None,
    )
    repository.create_operation(operation)

    loaded = repository.get_operation(operation_id="pop_001")
    assert loaded is not None
    assert loaded.status == "PENDING"
    assert loaded.payload_json["idempotency_key"] == "idem-prop-pg-1"
    assert loaded.attempt_count == 0
    assert loaded.max_attempts == 3
    assert loaded.result_json is None
    assert loaded.error_json is None

    operation.status = "SUCCEEDED"
    operation.proposal_id = "pp_001"
    operation.attempt_count = 2
    operation.started_at = created_at
    operation.lease_expires_at = created_at
    operation.finished_at = created_at
    operation.result_json = {"proposal": {"proposal_id": "pp_001"}}
    operation.error_json = None
    repository.update_operation(operation)

    by_operation = repository.get_operation(operation_id="pop_001")
    assert by_operation is not None
    assert by_operation.status == "SUCCEEDED"
    assert by_operation.proposal_id == "pp_001"
    assert by_operation.attempt_count == 2
    assert by_operation.lease_expires_at == created_at
    assert by_operation.result_json == {"proposal": {"proposal_id": "pp_001"}}
    assert by_operation.error_json is None
    assert by_operation.started_at == created_at
    assert by_operation.finished_at == created_at

    by_correlation = repository.get_operation_by_correlation(correlation_id="corr-prop-1")
    assert by_correlation is not None
    assert by_correlation.operation_id == "pop_001"
    assert by_correlation.status == "SUCCEEDED"


def test_postgres_repository_create_operation_if_absent_by_idempotency_is_atomic(monkeypatch):
    repository, connection = _build_repository(monkeypatch)
    created_at = datetime.now(timezone.utc)
    first = ProposalAsyncOperationRecord(
        operation_id="pop_atomic_1",
        operation_type="CREATE_PROPOSAL",
        status="PENDING",
        correlation_id="corr-atomic-1",
        idempotency_key="idem-atomic-1",
        proposal_id=None,
        created_by="advisor_1",
        created_at=created_at,
        payload_json={"payload": {"created_by": "advisor_1"}, "submission_hash": "sha256:first"},
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        lease_expires_at=None,
        finished_at=None,
        result_json=None,
        error_json=None,
    )
    second = ProposalAsyncOperationRecord(
        operation_id="pop_atomic_2",
        operation_type="CREATE_PROPOSAL",
        status="PENDING",
        correlation_id="corr-atomic-2",
        idempotency_key="idem-atomic-1",
        proposal_id=None,
        created_by="advisor_2",
        created_at=created_at,
        payload_json={"payload": {"created_by": "advisor_2"}, "submission_hash": "sha256:second"},
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        lease_expires_at=None,
        finished_at=None,
        result_json=None,
        error_json=None,
    )

    stored_first, first_is_new = repository.create_operation_if_absent_by_idempotency(first)
    stored_second, second_is_new = repository.create_operation_if_absent_by_idempotency(second)
    by_idempotency = repository.get_operation_by_idempotency(idempotency_key="idem-atomic-1")

    assert first_is_new is True
    assert second_is_new is False
    assert stored_first.operation_id == "pop_atomic_1"
    assert stored_second.operation_id == "pop_atomic_1"
    assert by_idempotency is not None
    assert by_idempotency.operation_id == "pop_atomic_1"
    assert by_idempotency.correlation_id == "corr-atomic-1"
    assert list(connection.operations) == ["pop_atomic_1"]


def test_create_operation_if_absent_raises_stable_error_when_insert_returns_no_row():
    connection = _NoOperationReturnedConnection()
    operation = ProposalAsyncOperationRecord(
        operation_id="pop_missing_row",
        operation_type="CREATE_PROPOSAL",
        status="PENDING",
        correlation_id="corr-missing-row",
        idempotency_key="idem-missing-row",
        proposal_id=None,
        created_by="advisor_1",
        created_at=datetime.now(timezone.utc),
        payload_json={"payload": {"created_by": "advisor_1"}},
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        lease_expires_at=None,
        finished_at=None,
        result_json=None,
        error_json=None,
    )

    with pytest.raises(
        RuntimeError,
        match="PROPOSAL_ASYNC_OPERATION_CREATE_INVARIANT_FAILED",
    ):
        postgres_async_operations.create_operation_if_absent_by_idempotency(
            connect=lambda: connection,
            operation=operation,
        )


def test_postgres_repository_non_idempotent_operation_create_returns_snapshot(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    created_at = datetime.now(timezone.utc)
    operation = ProposalAsyncOperationRecord(
        operation_id="pop_non_idempotent_1",
        operation_type="CREATE_PROPOSAL_VERSION",
        status="PENDING",
        correlation_id="corr-non-idempotent-1",
        idempotency_key=None,
        proposal_id="pp_001",
        created_by="advisor_1",
        created_at=created_at,
        payload_json={"payload": {"created_by": "advisor_1"}},
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        lease_expires_at=None,
        finished_at=None,
        result_json=None,
        error_json=None,
    )

    stored, is_new = repository.create_operation_if_absent_by_idempotency(operation)

    operation.payload_json["payload"]["created_by"] = "tampered"
    loaded = repository.get_operation(operation_id="pop_non_idempotent_1")

    assert is_new is True
    assert stored.payload_json == {"payload": {"created_by": "advisor_1"}}
    assert loaded is not None
    assert loaded.payload_json == {"payload": {"created_by": "advisor_1"}}


def test_postgres_repository_lists_recoverable_operations(monkeypatch):
    repository, connection = _build_repository(monkeypatch)
    now = datetime.now(timezone.utc)
    pending = ProposalAsyncOperationRecord(
        operation_id="pop_pending",
        operation_type="CREATE_PROPOSAL",
        status="PENDING",
        correlation_id="corr-pending",
        idempotency_key="idem-pending",
        proposal_id=None,
        created_by="advisor_1",
        created_at=now,
        payload_json={"payload": {"created_by": "advisor_1"}, "idempotency_key": "idem-pending"},
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        lease_expires_at=None,
        finished_at=None,
        result_json=None,
        error_json=None,
    )
    expired_running = ProposalAsyncOperationRecord(
        operation_id="pop_expired",
        operation_type="CREATE_PROPOSAL_VERSION",
        status="RUNNING",
        correlation_id="corr-expired",
        idempotency_key=None,
        proposal_id="pp_001",
        created_by="advisor_1",
        created_at=now,
        payload_json={"proposal_id": "pp_001", "payload": {"created_by": "advisor_1"}},
        attempt_count=1,
        max_attempts=3,
        started_at=now,
        lease_expires_at=now,
        finished_at=None,
        result_json=None,
        error_json={"code": "RuntimeError", "message": "timeout"},
    )
    running = ProposalAsyncOperationRecord(
        operation_id="pop_running",
        operation_type="CREATE_PROPOSAL",
        status="RUNNING",
        correlation_id="corr-running",
        idempotency_key="idem-running",
        proposal_id=None,
        created_by="advisor_1",
        created_at=now,
        payload_json={"payload": {"created_by": "advisor_1"}, "idempotency_key": "idem-running"},
        attempt_count=1,
        max_attempts=3,
        started_at=now,
        lease_expires_at=now + timedelta(minutes=5),
        finished_at=None,
        result_json=None,
        error_json=None,
    )
    succeeded = ProposalAsyncOperationRecord(
        operation_id="pop_succeeded",
        operation_type="CREATE_PROPOSAL",
        status="SUCCEEDED",
        correlation_id="corr-succeeded",
        idempotency_key="idem-succeeded",
        proposal_id="pp_002",
        created_by="advisor_1",
        created_at=now,
        payload_json={"payload": {"created_by": "advisor_1"}, "idempotency_key": "idem-succeeded"},
        attempt_count=1,
        max_attempts=3,
        started_at=now,
        lease_expires_at=None,
        finished_at=now,
        result_json={"proposal": {"proposal_id": "pp_002"}},
        error_json=None,
    )
    for operation in [pending, expired_running, running, succeeded]:
        repository.create_operation(operation)

    recoverable = repository.list_recoverable_operations(as_of=now)

    assert [operation.operation_id for operation in recoverable] == ["pop_expired", "pop_pending"]

    limited = repository.list_recoverable_operations(as_of=now, limit=1)

    assert [operation.operation_id for operation in limited] == ["pop_expired"]
    assert "LIMIT %s" in connection.executed_sql[-1]
    assert connection.executed_args[-1] == (now.isoformat(), 1)
    assert repository.list_recoverable_operations(as_of=now, limit=0) == []


def test_postgres_repository_proposal_create_update_get_and_list(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    first_created = datetime.now(timezone.utc)
    first = ProposalRecord(
        proposal_id="pp_a",
        portfolio_id="pf_repo",
        mandate_id="mandate_1",
        jurisdiction="SG",
        created_by="advisor_a",
        created_at=first_created,
        last_event_at=first_created,
        current_state="DRAFT",
        current_version_no=1,
        title="A",
        advisor_notes="note-a",
    )
    repository.create_proposal(first)

    second_created = datetime.now(timezone.utc)
    second = ProposalRecord(
        proposal_id="pp_b",
        portfolio_id="pf_repo",
        mandate_id="mandate_2",
        jurisdiction="SG",
        created_by="advisor_b",
        created_at=second_created,
        last_event_at=second_created,
        current_state="EXECUTION_READY",
        current_version_no=2,
        title="B",
        advisor_notes=None,
        lifecycle_origin="WORKSPACE_HANDOFF",
        source_workspace_id="aws_002",
    )
    repository.create_proposal(second)

    loaded_first = repository.get_proposal(proposal_id="pp_a")
    assert loaded_first is not None
    assert loaded_first.title == "A"
    assert loaded_first.current_state == "DRAFT"

    first.current_state = "CANCELLED"
    repository.update_proposal(first)
    updated_first = repository.get_proposal(proposal_id="pp_a")
    assert updated_first is not None
    assert updated_first.current_state == "CANCELLED"

    rows, next_cursor = repository.list_proposals(
        portfolio_id="pf_repo",
        state="EXECUTION_READY",
        created_by="advisor_b",
        created_from=None,
        created_to=None,
        limit=1,
        cursor=None,
    )
    assert len(rows) == 1
    assert rows[0].proposal_id == "pp_b"
    assert rows[0].lifecycle_origin == "WORKSPACE_HANDOFF"
    assert rows[0].source_workspace_id == "aws_002"
    assert next_cursor is None

    rows, _ = repository.list_proposals(
        portfolio_id=None,
        state=None,
        created_by=None,
        created_from=None,
        created_to=None,
        limit=1,
        cursor="pp_b",
    )
    assert len(rows) == 1
    assert rows[0].proposal_id == "pp_a"

    rows, next_cursor = repository.list_proposals(
        portfolio_id=None,
        state=None,
        created_by=None,
        created_from=None,
        created_to=None,
        limit=1,
        cursor="pp_missing",
    )
    assert rows == []
    assert next_cursor is None


def test_postgres_repository_list_proposals_uses_keyset_limit(monkeypatch):
    repository, connection = _build_repository(monkeypatch)
    base_created_at = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)
    for index, proposal_id in enumerate(("pp_a", "pp_b", "pp_c")):
        created_at = base_created_at + timedelta(minutes=index)
        repository.create_proposal(
            ProposalRecord(
                proposal_id=proposal_id,
                portfolio_id="pf_keyset",
                mandate_id=f"mandate_{index}",
                jurisdiction="SG",
                created_by="advisor_keyset",
                created_at=created_at,
                last_event_at=created_at,
                current_state="DRAFT",
                current_version_no=1,
                title=f"Proposal {proposal_id}",
                advisor_notes=None,
            )
        )
    other_created_at = base_created_at + timedelta(minutes=10)
    repository.create_proposal(
        ProposalRecord(
            proposal_id="pp_other",
            portfolio_id="pf_other",
            mandate_id="mandate_other",
            jurisdiction="SG",
            created_by="advisor_keyset",
            created_at=other_created_at,
            last_event_at=other_created_at,
            current_state="DRAFT",
            current_version_no=1,
            title="Other portfolio proposal",
            advisor_notes=None,
        )
    )

    rows, next_cursor = repository.list_proposals(
        portfolio_id="pf_keyset",
        state=None,
        created_by=None,
        created_from=None,
        created_to=None,
        limit=1,
        cursor=None,
    )

    assert [row.proposal_id for row in rows] == ["pp_c"]
    assert next_cursor == "pp_c"
    assert "LIMIT %s" in connection.executed_sql[-1]
    assert connection.executed_args[-1][-1] == 2

    rows, next_cursor = repository.list_proposals(
        portfolio_id="pf_keyset",
        state=None,
        created_by=None,
        created_from=None,
        created_to=None,
        limit=1,
        cursor="pp_c",
    )

    assert [row.proposal_id for row in rows] == ["pp_b"]
    assert next_cursor == "pp_b"
    assert (
        "FROM proposal_records cursor_record WHERE cursor_record.proposal_id = %s"
        in (connection.executed_sql[-1])
    )
    assert connection.executed_args[-1] == ("pf_keyset", "pp_c", "pf_keyset", 2)

    rows, next_cursor = repository.list_proposals(
        portfolio_id="pf_keyset",
        state=None,
        created_by=None,
        created_from=None,
        created_to=None,
        limit=1,
        cursor="pp_other",
    )

    assert rows == []
    assert next_cursor is None


def test_postgres_repository_version_create_get_and_current(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    now = datetime.now(timezone.utc)
    version_1 = ProposalVersionRecord(
        proposal_version_id="ppv_001",
        proposal_id="pp_001",
        version_no=1,
        created_at=now,
        request_hash="sha256:req1",
        artifact_hash="sha256:artifact1",
        simulation_hash="sha256:sim1",
        status_at_creation="READY",
        proposal_result_json={"status": "READY"},
        artifact_json={"artifact_id": "a1"},
        evidence_bundle_json={"hashes": {"artifact_hash": "sha256:artifact1"}},
        gate_decision_json=None,
    )
    version_2 = ProposalVersionRecord(
        proposal_version_id="ppv_002",
        proposal_id="pp_001",
        version_no=2,
        created_at=now,
        request_hash="sha256:req2",
        artifact_hash="sha256:artifact2",
        simulation_hash="sha256:sim2",
        status_at_creation="BLOCKED",
        proposal_result_json={"status": "BLOCKED"},
        artifact_json={"artifact_id": "a2"},
        evidence_bundle_json={"hashes": {"artifact_hash": "sha256:artifact2"}},
        gate_decision_json={"gate": "CLIENT_CONSENT_REQUIRED"},
    )
    repository.create_version(version_1)
    repository.create_version(version_2)

    loaded_1 = repository.get_version(proposal_id="pp_001", version_no=1)
    assert loaded_1 is not None
    assert loaded_1.proposal_version_id == "ppv_001"
    assert loaded_1.proposal_result_json == {"status": "READY"}
    assert loaded_1.gate_decision_json is None

    loaded_2 = repository.get_version(proposal_id="pp_001", version_no=2)
    assert loaded_2 is not None
    assert loaded_2.proposal_version_id == "ppv_002"
    assert loaded_2.gate_decision_json == {"gate": "CLIENT_CONSENT_REQUIRED"}

    listed = repository.list_versions(proposal_id="pp_001")
    assert [version.version_no for version in listed] == [1, 2]
    assert [version.proposal_version_id for version in listed] == ["ppv_001", "ppv_002"]
    assert repository.list_versions(proposal_id="pp_missing") == []

    missing = repository.get_version(proposal_id="pp_001", version_no=3)
    assert missing is None

    current = repository.get_current_version(proposal_id="pp_001")
    assert current is not None
    assert current.version_no == 2
    assert current.proposal_version_id == "ppv_002"

    empty_current = repository.get_current_version(proposal_id="pp_missing")
    assert empty_current is None


def test_postgres_repository_versions_are_replay_safe_and_immutable(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    now = datetime.now(timezone.utc)
    version = ProposalVersionRecord(
        proposal_version_id="ppv_immutable_001",
        proposal_id="pp_immutable",
        version_no=1,
        created_at=now,
        request_hash="sha256:immutable-request",
        artifact_hash="sha256:immutable-artifact",
        simulation_hash="sha256:immutable-simulation",
        status_at_creation="READY",
        proposal_result_json={"status": "READY"},
        artifact_json={"artifact_id": "artifact_immutable"},
        evidence_bundle_json={"hashes": {"artifact_hash": "sha256:immutable-artifact"}},
        gate_decision_json=None,
    )

    repository.create_version(version)
    repository.create_version(version)

    with pytest.raises(ValueError, match="PROPOSAL_VERSION_IDENTITY_CONFLICT"):
        repository.create_version(
            version.model_copy(
                update={
                    "proposal_version_id": "ppv_immutable_drifted",
                    "request_hash": "sha256:drifted-request",
                }
            )
        )

    stored = repository.get_version(proposal_id="pp_immutable", version_no=1)
    assert stored == version


def test_postgres_repository_memo_idempotency_memo_and_events_roundtrip(monkeypatch):
    repository, connection = _build_repository(monkeypatch)
    now = datetime.now(timezone.utc)
    memo = ProposalMemoRecord(
        memo_id="memo_pg_001",
        proposal_id="pp_pg_memo",
        proposal_version_no=1,
        proposal_version_id="ppv_pg_memo_001",
        artifact_id="pa_pg_memo_001",
        memo_version="advisory-proposal-memo-evidence-pack.v1",
        memo_status="BLOCKED",
        lifecycle_status="DRAFT",
        created_by="advisor_pg",
        created_at=now,
        source_input_hash="sha256:source",
        memo_hash="sha256:memo",
        memo_json={"memo_id": "memo_pg_001", "status": "BLOCKED"},
        projection_json={"client_ready_publication": "BLOCKED"},
        review_events_json=[],
        report_package_events_json=[],
        archive_refs_json=[],
        ai_refs_json=[],
        replay_metadata_json={"proposal_artifact_hash": "sha256:artifact"},
    )
    idempotency = ProposalMemoIdempotencyRecord(
        idempotency_key="memo-pg-idem",
        request_hash="sha256:request",
        memo_id=memo.memo_id,
        proposal_id=memo.proposal_id,
        proposal_version_no=memo.proposal_version_no,
        created_at=now,
    )
    event = ProposalMemoEventRecord(
        event_id="pme_pg_001",
        memo_id=memo.memo_id,
        proposal_id=memo.proposal_id,
        proposal_version_no=memo.proposal_version_no,
        event_type="MEMO_DRAFT_CREATED",
        actor_id="advisor_pg",
        occurred_at=now,
        reason_json={"memo_hash": "sha256:memo"},
    )

    repository.create_memo(memo)
    repository.save_memo_idempotency(idempotency)
    repository.append_memo_event(event)

    loaded = repository.get_memo(memo_id=memo.memo_id)
    assert loaded is not None
    assert loaded.memo_hash == "sha256:memo"
    assert loaded.projection_json["client_ready_publication"] == "BLOCKED"
    by_version = repository.get_memo_by_proposal_version(
        proposal_id=memo.proposal_id,
        proposal_version_no=1,
    )
    assert by_version is not None
    assert by_version.memo_id == memo.memo_id
    assert [row.memo_id for row in repository.list_memos(proposal_id=memo.proposal_id)] == [
        memo.memo_id
    ]
    batch_memo = memo.model_copy(
        update={
            "memo_id": "memo_pg_002",
            "proposal_id": "proposal_pg_other",
            "memo_hash": "sha256:memo-other",
            "source_input_hash": "sha256:source-other",
            "memo_json": {"memo_id": "memo_pg_002", "status": "BLOCKED"},
        }
    )
    repository.create_memo(batch_memo)
    assert [
        row.memo_id
        for row in repository.list_memos_for_proposals(
            proposal_ids=[batch_memo.proposal_id, memo.proposal_id]
        )
    ] == [batch_memo.memo_id, memo.memo_id]
    assert repository.list_memos_for_proposals(proposal_ids=[]) == []
    loaded_idempotency = repository.get_memo_idempotency(idempotency_key="memo-pg-idem")
    assert loaded_idempotency is not None
    assert loaded_idempotency.memo_id == memo.memo_id
    repository.save_memo_idempotency(
        idempotency.model_copy(
            update={
                "request_hash": "sha256:drifted-request",
                "memo_id": "memo_pg_drifted",
            }
        )
    )
    preserved_idempotency = repository.get_memo_idempotency(idempotency_key="memo-pg-idem")
    assert preserved_idempotency is not None
    assert preserved_idempotency.request_hash == "sha256:request"
    assert preserved_idempotency.memo_id == memo.memo_id
    assert repository.list_memo_events(memo_id=memo.memo_id)[0].event_id == "pme_pg_001"
    assert any("INSERT INTO proposal_memos" in sql for sql in connection.executed_sql)


@pytest.mark.parametrize(
    "fail_sql_fragment",
    [
        "INSERT INTO proposal_memos",
        "INSERT INTO proposal_memo_idempotency",
        "INSERT INTO proposal_memo_events",
    ],
)
def test_postgres_repository_atomic_memo_create_rolls_back_partial_writes(
    monkeypatch,
    fail_sql_fragment,
):
    connection = _FailingAfterWriteConnection(fail_sql_fragment=fail_sql_fragment)
    repository, _ = _build_repository(monkeypatch, connection=connection)
    memo, idempotency, event = _memo_create_records()

    with pytest.raises(RuntimeError, match="fault injected"):
        repository.create_memo_with_idempotency_event(
            memo=memo,
            idempotency=idempotency,
            event=event,
        )

    assert connection.rollback_count == 1
    assert repository.get_memo(memo_id=memo.memo_id) is None
    assert repository.get_memo_idempotency(idempotency_key=idempotency.idempotency_key) is None
    assert repository.list_memo_events(memo_id=memo.memo_id) == []


def test_postgres_repository_atomic_memo_create_commits_all_records(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    memo, idempotency, event = _memo_create_records()

    repository.create_memo_with_idempotency_event(
        memo=memo,
        idempotency=idempotency,
        event=event,
    )

    assert repository.get_memo(memo_id=memo.memo_id) == memo
    assert (
        repository.get_memo_idempotency(idempotency_key=idempotency.idempotency_key) == idempotency
    )
    assert repository.list_memo_events(memo_id=memo.memo_id) == [event]


def test_postgres_repository_cockpit_acknowledgement_roundtrip(monkeypatch):
    repository, connection = _build_repository(monkeypatch)
    now = datetime.now(timezone.utc)
    acknowledgement = CockpitAcknowledgementRecord(
        acknowledgement_id="ack_pg_001",
        action_item_id="cockpit_action_pg_001",
        action_item_version=1,
        acknowledged_by="advisor_pg",
        acknowledged_at=now,
        acknowledgement_note="Reviewed pending cockpit action.",
        correlation_id="corr-pg-ack",
        reason_json={"contract_version": "rfc0026.advisor-cockpit-api.v1"},
    )
    idempotency = CockpitAcknowledgementIdempotencyRecord(
        idempotency_key="ack-pg-idem",
        request_hash="sha256:ack-request",
        acknowledgement_id=acknowledgement.acknowledgement_id,
        action_item_id=acknowledgement.action_item_id,
        created_at=now,
    )

    repository.save_cockpit_acknowledgement_with_idempotency(
        acknowledgement=acknowledgement,
        idempotency=idempotency,
    )

    loaded = repository.get_cockpit_acknowledgement(action_item_id=acknowledgement.action_item_id)
    assert loaded is not None
    assert loaded.acknowledgement_note == "Reviewed pending cockpit action."
    assert loaded.reason_json["contract_version"] == "rfc0026.advisor-cockpit-api.v1"
    loaded_by_action_id = repository.list_cockpit_acknowledgements(
        action_item_ids=[acknowledgement.action_item_id, "missing-action"]
    )
    assert list(loaded_by_action_id) == [acknowledgement.action_item_id]
    assert loaded_by_action_id[acknowledgement.action_item_id].acknowledgement_id == "ack_pg_001"
    batch_selects = [
        sql
        for sql in connection.executed_sql
        if "FROM advisor_cockpit_acknowledgements" in sql
        and "WHERE action_item_id = ANY(%s)" in sql
    ]
    assert len(batch_selects) == 1
    loaded_idempotency = repository.get_cockpit_acknowledgement_idempotency(
        idempotency_key=idempotency.idempotency_key
    )
    assert loaded_idempotency is not None
    assert loaded_idempotency.request_hash == "sha256:ack-request"
    try:
        repository.save_cockpit_acknowledgement_with_idempotency(
            acknowledgement=acknowledgement.model_copy(
                update={
                    "acknowledgement_id": "ack_pg_002",
                    "action_item_id": "cockpit_action_pg_002",
                }
            ),
            idempotency=idempotency.model_copy(
                update={
                    "request_hash": "sha256:ack-request-drifted",
                    "acknowledgement_id": "ack_pg_002",
                    "action_item_id": "cockpit_action_pg_002",
                }
            ),
        )
    except ValueError as exc:
        assert str(exc) == "COCKPIT_ACKNOWLEDGEMENT_IDEMPOTENCY_KEY_CONFLICT"
    else:
        raise AssertionError("Expected cockpit acknowledgement idempotency conflict")
    assert repository.get_cockpit_acknowledgement(action_item_id="cockpit_action_pg_002") is None


def test_postgres_repository_workflow_events_and_approvals_roundtrip(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    first_at = datetime.now(timezone.utc)
    second_at = datetime.now(timezone.utc)

    first_event = ProposalWorkflowEventRecord(
        event_id="pwe_001",
        proposal_id="pp_001",
        event_type="CREATED",
        from_state=None,
        to_state="DRAFT",
        actor_id="advisor_1",
        occurred_at=first_at,
        reason_json={"comment": "created"},
        related_version_no=1,
    )
    second_event = ProposalWorkflowEventRecord(
        event_id="pwe_002",
        proposal_id="pp_001",
        event_type="SUBMITTED_FOR_RISK_REVIEW",
        from_state="DRAFT",
        to_state="RISK_REVIEW",
        actor_id="advisor_1",
        occurred_at=second_at,
        reason_json={"comment": "submit"},
        related_version_no=1,
    )
    repository.append_event(first_event)
    repository.append_event(second_event)

    events = repository.list_events(proposal_id="pp_001")
    assert [event.event_id for event in events] == ["pwe_001", "pwe_002"]
    assert events[1].to_state == "RISK_REVIEW"
    assert events[1].reason_json == {"comment": "submit"}
    third_event = second_event.model_copy(
        update={
            "event_id": "pwe_003",
            "proposal_id": "pp_002",
            "actor_id": "advisor_2",
        }
    )
    repository.append_event(third_event)
    assert [
        row.event_id
        for row in repository.list_events_for_proposals(proposal_ids=["pp_002", "pp_001"])
    ] == ["pwe_003", "pwe_001", "pwe_002"]
    assert repository.list_events_for_proposals(proposal_ids=[]) == []

    approval_at = datetime.now(timezone.utc)
    approval = ProposalApprovalRecordData(
        approval_id="pap_001",
        proposal_id="pp_001",
        approval_type="RISK",
        approved=True,
        actor_id="risk_officer_1",
        occurred_at=approval_at,
        details_json={"ticket_id": "risk-42"},
        related_version_no=1,
    )
    repository.create_approval(approval)
    approvals = repository.list_approvals(proposal_id="pp_001")
    assert len(approvals) == 1
    assert approvals[0].approval_id == "pap_001"
    assert approvals[0].details_json == {"ticket_id": "risk-42"}
    second_approval = approval.model_copy(
        update={
            "approval_id": "pap_002",
            "proposal_id": "pp_002",
            "approval_type": "COMPLIANCE",
            "actor_id": "compliance_officer_1",
        }
    )
    repository.create_approval(second_approval)
    assert [
        row.approval_id
        for row in repository.list_approvals_for_proposals(proposal_ids=["pp_002", "pp_001"])
    ] == ["pap_002", "pap_001"]
    assert repository.list_approvals_for_proposals(proposal_ids=[]) == []


def test_postgres_repository_events_and_approvals_are_replay_safe_and_immutable(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    now = datetime.now(timezone.utc)
    event = ProposalWorkflowEventRecord(
        event_id="pwe_immutable_001",
        proposal_id="pp_immutable",
        event_type="CREATED",
        from_state=None,
        to_state="DRAFT",
        actor_id="advisor_1",
        occurred_at=now,
        reason_json={"request_hash": "sha256:immutable-event"},
        related_version_no=1,
    )
    approval = ProposalApprovalRecordData(
        approval_id="pap_immutable_001",
        proposal_id="pp_immutable",
        approval_type="RISK",
        approved=True,
        actor_id="risk_officer_1",
        occurred_at=now,
        details_json={"request_hash": "sha256:immutable-approval"},
        related_version_no=1,
    )

    repository.append_event(event)
    repository.append_event(event)
    repository.create_approval(approval)
    repository.create_approval(approval)

    with pytest.raises(ValueError, match="PROPOSAL_WORKFLOW_EVENT_IDENTITY_CONFLICT"):
        repository.append_event(
            event.model_copy(
                update={
                    "actor_id": "advisor_2",
                    "reason_json": {"request_hash": "sha256:drifted-event"},
                }
            )
        )
    with pytest.raises(ValueError, match="PROPOSAL_APPROVAL_IDENTITY_CONFLICT"):
        repository.create_approval(
            approval.model_copy(
                update={
                    "actor_id": "risk_officer_2",
                    "details_json": {"request_hash": "sha256:drifted-approval"},
                }
            )
        )

    stored_events = repository.list_events(proposal_id="pp_immutable")
    assert stored_events == [event]
    stored_approvals = repository.list_approvals(proposal_id="pp_immutable")
    assert stored_approvals == [approval]


def test_postgres_repository_transition_proposal_writes_all_records(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    now = datetime.now(timezone.utc)
    initial = ProposalRecord(
        proposal_id="pp_002",
        portfolio_id="pf_repo",
        mandate_id="mandate_1",
        jurisdiction="SG",
        created_by="advisor_a",
        created_at=now,
        last_event_at=now,
        current_state="DRAFT",
        current_version_no=1,
        title="Needs Risk Signoff",
        advisor_notes="priority",
    )
    proposal = ProposalRecord(
        proposal_id="pp_002",
        portfolio_id="pf_repo",
        mandate_id="mandate_1",
        jurisdiction="SG",
        created_by="advisor_a",
        created_at=now,
        last_event_at=now,
        current_state="RISK_REVIEW",
        current_version_no=1,
        title="Needs Risk Signoff",
        advisor_notes="priority",
    )
    event = ProposalWorkflowEventRecord(
        event_id="pwe_010",
        proposal_id="pp_002",
        event_type="SUBMITTED_FOR_RISK_REVIEW",
        from_state="DRAFT",
        to_state="RISK_REVIEW",
        actor_id="advisor_a",
        occurred_at=now,
        reason_json={"comment": "submitted"},
        related_version_no=1,
    )
    approval = ProposalApprovalRecordData(
        approval_id="pap_010",
        proposal_id="pp_002",
        approval_type="RISK",
        approved=True,
        actor_id="risk_1",
        occurred_at=now,
        details_json={"ticket_id": "risk-010"},
        related_version_no=1,
    )

    repository.create_proposal(initial)
    result = repository.transition_proposal(
        proposal=proposal,
        event=event,
        approval=approval,
        expected_current_state="DRAFT",
        expected_current_version_no=1,
    )
    assert result.proposal.proposal_id == "pp_002"
    assert result.event.event_id == "pwe_010"
    assert result.approval is not None
    assert result.approval.approval_id == "pap_010"

    proposal.current_state = "CANCELLED"
    event.reason_json["comment"] = "tampered"
    approval.details_json["ticket_id"] = "tampered"
    assert result.proposal.current_state == "RISK_REVIEW"
    assert result.event.reason_json == {"comment": "submitted"}
    assert result.approval.details_json == {"ticket_id": "risk-010"}

    stored_proposal = repository.get_proposal(proposal_id="pp_002")
    assert stored_proposal is not None
    assert stored_proposal.current_state == "RISK_REVIEW"
    stored_event_ids = [
        stored_event.event_id for stored_event in repository.list_events(proposal_id="pp_002")
    ]
    assert stored_event_ids == ["pwe_010"]
    assert [
        stored_approval.approval_id
        for stored_approval in repository.list_approvals(proposal_id="pp_002")
    ] == ["pap_010"]


def test_postgres_repository_transition_rejects_stale_expected_state(monkeypatch):
    repository, connection = _build_repository(monkeypatch)
    now = datetime.now(timezone.utc)
    initial = ProposalRecord(
        proposal_id="pp_stale_transition",
        portfolio_id="pf_repo",
        mandate_id="mandate_1",
        jurisdiction="SG",
        created_by="advisor_a",
        created_at=now,
        last_event_at=now,
        current_state="DRAFT",
        current_version_no=1,
        title="Stale transition",
        advisor_notes=None,
    )
    proposal = initial.model_copy(
        update={
            "current_state": "RISK_REVIEW",
            "last_event_at": now + timedelta(seconds=1),
        }
    )
    event = ProposalWorkflowEventRecord(
        event_id="pwe_stale_transition",
        proposal_id=initial.proposal_id,
        event_type="SUBMITTED_FOR_RISK_REVIEW",
        from_state="DRAFT",
        to_state="RISK_REVIEW",
        actor_id="advisor_a",
        occurred_at=proposal.last_event_at,
        reason_json={"comment": "submitted"},
        related_version_no=1,
    )
    approval = ProposalApprovalRecordData(
        approval_id="pap_stale_transition",
        proposal_id=initial.proposal_id,
        approval_type="RISK",
        approved=True,
        actor_id="risk_1",
        occurred_at=proposal.last_event_at,
        details_json={"ticket_id": "risk-stale"},
        related_version_no=1,
    )

    repository.create_proposal(initial)

    with pytest.raises(ProposalStateConflictError) as exc_info:
        repository.transition_proposal(
            proposal=proposal,
            event=event,
            approval=approval,
            expected_current_state="COMPLIANCE_REVIEW",
            expected_current_version_no=1,
        )

    assert str(exc_info.value) == "STATE_CONFLICT: proposal aggregate changed during transition"
    assert connection.rollback_count == 1
    assert repository.get_proposal(proposal_id=initial.proposal_id) == initial
    assert repository.list_events(proposal_id=initial.proposal_id) == []
    assert repository.list_approvals(proposal_id=initial.proposal_id) == []


@pytest.mark.parametrize(
    "fail_sql_fragment",
    [
        "INSERT INTO proposal_records",
        "INSERT INTO proposal_versions",
        "INSERT INTO proposal_workflow_events",
        "INSERT INTO proposal_idempotency",
    ],
)
def test_postgres_repository_atomic_proposal_create_rolls_back_partial_writes(
    monkeypatch,
    fail_sql_fragment,
):
    connection = _FailingAfterWriteConnection(fail_sql_fragment=fail_sql_fragment)
    repository, _ = _build_repository(monkeypatch, connection=connection)
    proposal, version, event, idempotency = _proposal_create_records()

    with pytest.raises(RuntimeError, match="fault injected"):
        repository.create_proposal_with_version_event_idempotency(
            proposal=proposal,
            version=version,
            event=event,
            idempotency=idempotency,
        )

    assert connection.rollback_count == 1
    assert repository.get_proposal(proposal_id=proposal.proposal_id) is None
    assert repository.get_version(proposal_id=proposal.proposal_id, version_no=1) is None
    assert repository.list_events(proposal_id=proposal.proposal_id) == []
    assert repository.get_idempotency(idempotency_key=idempotency.idempotency_key) is None


def test_postgres_repository_atomic_proposal_create_commits_all_records(monkeypatch):
    repository, _ = _build_repository(monkeypatch)
    proposal, version, event, idempotency = _proposal_create_records()

    repository.create_proposal_with_version_event_idempotency(
        proposal=proposal,
        version=version,
        event=event,
        idempotency=idempotency,
    )

    assert repository.get_proposal(proposal_id=proposal.proposal_id) == proposal
    assert repository.get_version(proposal_id=proposal.proposal_id, version_no=1) == version
    assert repository.list_events(proposal_id=proposal.proposal_id) == [event]
    assert repository.get_idempotency(idempotency_key=idempotency.idempotency_key) == idempotency


def test_import_psycopg_returns_driver_and_row_factory(monkeypatch):
    fake_psycopg = ModuleType("psycopg")
    fake_psycopg_rows = ModuleType("psycopg.rows")
    fake_dict_row = object()
    fake_psycopg_rows.dict_row = fake_dict_row

    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.rows", fake_psycopg_rows)

    psycopg, dict_row = postgres_module._import_psycopg()
    assert psycopg is fake_psycopg
    assert dict_row is fake_dict_row


def test_postgres_repository_connect_uses_dsn_and_row_factory(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeDriver:
        def connect(self, dsn, row_factory):  # noqa: ANN001
            captured["dsn"] = dsn
            captured["row_factory"] = row_factory
            return "connected"

    fake_row_factory = object()
    monkeypatch.setattr(
        postgres_module,
        "_import_psycopg",
        lambda: (_FakeDriver(), fake_row_factory),
    )

    repository = object.__new__(PostgresProposalRepository)
    repository._dsn = "postgresql://user:pass@localhost:5432/proposals"
    connected = repository._connect()
    assert connected == "connected"
    assert captured["dsn"] == repository._dsn
    assert captured["row_factory"] is fake_row_factory


def _proposal_create_records():
    now = datetime.now(timezone.utc)
    proposal = ProposalRecord(
        proposal_id="pp_atomic_create",
        portfolio_id="pf_atomic_create",
        mandate_id="mandate_atomic_create",
        jurisdiction="SG",
        created_by="advisor_atomic_create",
        created_at=now,
        last_event_at=now,
        current_state="DRAFT",
        current_version_no=1,
        title="Atomic proposal create",
        advisor_notes=None,
    )
    version = ProposalVersionRecord(
        proposal_version_id="ppv_atomic_create",
        proposal_id=proposal.proposal_id,
        version_no=1,
        created_at=now,
        request_hash="sha256:atomic-request",
        artifact_hash="sha256:atomic-artifact",
        simulation_hash="sha256:atomic-simulation",
        status_at_creation="READY",
        proposal_result_json={"status": "READY"},
        artifact_json={"artifact_id": "pa_atomic_create"},
        evidence_bundle_json={"hashes": {"request_hash": "sha256:atomic-request"}},
        gate_decision_json=None,
    )
    event = ProposalWorkflowEventRecord(
        event_id="pwe_atomic_create",
        proposal_id=proposal.proposal_id,
        event_type="CREATED",
        from_state=None,
        to_state="DRAFT",
        actor_id=proposal.created_by,
        occurred_at=now,
        reason_json={"request_hash": version.request_hash},
        related_version_no=1,
    )
    idempotency = ProposalIdempotencyRecord(
        idempotency_key="idem_atomic_create",
        request_hash=version.request_hash,
        proposal_id=proposal.proposal_id,
        proposal_version_no=1,
        created_at=now,
    )
    return proposal, version, event, idempotency


def _memo_create_records():
    now = datetime.now(timezone.utc)
    memo = ProposalMemoRecord(
        memo_id="memo_atomic_create",
        proposal_id="pp_memo_atomic_create",
        proposal_version_no=1,
        proposal_version_id="ppv_memo_atomic_create",
        artifact_id="pa_memo_atomic_create",
        memo_version="advisory-proposal-memo-evidence-pack.v1",
        memo_status="BLOCKED",
        lifecycle_status="DRAFT",
        created_by="advisor_memo_atomic",
        created_at=now,
        source_input_hash="sha256:memo-atomic-source",
        memo_hash="sha256:memo-atomic",
        memo_json={"memo_id": "memo_atomic_create", "status": "BLOCKED"},
        projection_json={"client_ready_publication": "BLOCKED"},
        review_events_json=[],
        report_package_events_json=[],
        archive_refs_json=[],
        ai_refs_json=[],
        replay_metadata_json={"proposal_artifact_hash": "sha256:memo-atomic-artifact"},
    )
    idempotency = ProposalMemoIdempotencyRecord(
        idempotency_key="memo-atomic-idem",
        request_hash="sha256:memo-atomic-request",
        memo_id=memo.memo_id,
        proposal_id=memo.proposal_id,
        proposal_version_no=memo.proposal_version_no,
        created_at=now,
    )
    event = ProposalMemoEventRecord(
        event_id="pme_atomic_create",
        memo_id=memo.memo_id,
        proposal_id=memo.proposal_id,
        proposal_version_no=memo.proposal_version_no,
        event_type="MEMO_DRAFT_CREATED",
        actor_id=memo.created_by,
        occurred_at=now,
        reason_json={"memo_hash": memo.memo_hash},
    )
    return memo, idempotency, event


def test_to_proposal_returns_none_for_missing_row():
    assert postgres_mappers.to_proposal(None) is None
