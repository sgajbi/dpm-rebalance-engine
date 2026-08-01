from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import closing
from typing import Any

from src.core.proposals.exceptions import ProposalIdempotencyConflictError
from src.infrastructure.proposals.postgres_mappers import json_dump

ConnectionFactory = Callable[[], Any]


class PostgresPolicyEvaluationStateStore:
    def __init__(self, *, connect: ConnectionFactory) -> None:
        self._connect = connect

    def load_snapshot(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            record_rows = connection.execute(
                """
                SELECT evaluation_id, record_json
                FROM policy_evaluation_records
                ORDER BY generated_at ASC, evaluation_id ASC
                """
            ).fetchall()
            event_rows = connection.execute(
                """
                SELECT evaluation_id, event_json
                FROM policy_evaluation_audit_events
                ORDER BY evaluation_id ASC, occurred_at ASC, event_id ASC
                """
            ).fetchall()
            idempotency_rows = connection.execute(
                """
                SELECT idempotency_key, request_hash, evaluation_id, event_id
                FROM policy_evaluation_idempotency
                ORDER BY idempotency_key ASC
                """
            ).fetchall()
        return {
            "records": _records_snapshot(record_rows),
            "events": _events_snapshot(event_rows),
            "idempotency": [dict(row) for row in idempotency_rows],
            "identity_index": [],
        }

    def save_snapshot(self, snapshot: dict[str, Any]) -> None:
        with closing(self._connect()) as connection:
            try:
                events_by_evaluation = snapshot.get("events", {})
                for record in snapshot.get("records", {}).values():
                    _upsert_policy_evaluation_record(
                        connection=connection,
                        record=record,
                        event_count=len(events_by_evaluation.get(record["evaluation_id"], [])),
                    )
                for events in events_by_evaluation.values():
                    for event in events:
                        _upsert_policy_evaluation_event(connection=connection, event=event)
                for idempotency in snapshot.get("idempotency", []):
                    _upsert_policy_evaluation_idempotency(
                        connection=connection,
                        idempotency=idempotency,
                        created_at=_event_created_at(snapshot=snapshot, idempotency=idempotency),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise


class PostgresPolicyPackCatalogStateStore:
    def __init__(self, *, connect: ConnectionFactory) -> None:
        self._connect = connect

    def load_snapshot(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            definition_rows = connection.execute(
                """
                SELECT definition_json
                FROM policy_pack_catalog_versions
                ORDER BY policy_pack_id ASC, policy_version ASC
                """
            ).fetchall()
            event_rows = connection.execute(
                """
                SELECT event_json
                FROM policy_pack_catalog_audit_events
                ORDER BY policy_pack_id ASC, policy_version ASC, occurred_at ASC, event_id ASC
                """
            ).fetchall()
            idempotency_rows = connection.execute(
                """
                SELECT idempotency_key, request_hash, policy_pack_id, policy_version, event_id
                FROM policy_pack_catalog_idempotency
                ORDER BY idempotency_key ASC
                """
            ).fetchall()
        return {
            "definitions": [json.loads(row["definition_json"]) for row in definition_rows],
            "events": [json.loads(row["event_json"]) for row in event_rows],
            "idempotency": [dict(row) for row in idempotency_rows],
        }

    def save_snapshot(self, snapshot: dict[str, Any]) -> None:
        with closing(self._connect()) as connection:
            try:
                events = snapshot.get("events", [])
                for definition in snapshot.get("definitions", []):
                    _upsert_policy_pack_catalog_version(
                        connection=connection,
                        definition=definition,
                        event_count=_catalog_event_count(
                            events=events,
                            policy_pack_id=definition["policy_pack_id"],
                            policy_version=definition["policy_version"],
                        ),
                    )
                for event in events:
                    _upsert_policy_pack_catalog_event(connection=connection, event=event)
                for idempotency in snapshot.get("idempotency", []):
                    _upsert_policy_pack_catalog_idempotency(
                        connection=connection,
                        idempotency=idempotency,
                        created_at=_catalog_event_created_at(
                            snapshot=snapshot,
                            idempotency=idempotency,
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def _records_snapshot(rows: list[Any]) -> dict[str, dict[str, Any]]:
    return {str(row["evaluation_id"]): json.loads(row["record_json"]) for row in rows}


def _events_snapshot(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    events: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        events.setdefault(str(row["evaluation_id"]), []).append(json.loads(row["event_json"]))
    return events


def _upsert_policy_evaluation_record(
    *, connection: Any, record: dict[str, Any], event_count: int
) -> None:
    cursor = connection.execute(
        """
        INSERT INTO policy_evaluation_records (
            evaluation_id,
            proposal_id,
            proposal_version_id,
            portfolio_id,
            policy_pack_id,
            policy_version,
            generated_at,
            evaluation_status,
            source_evidence_hash,
            policy_content_hash,
            evaluation_hash,
            record_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (evaluation_id) DO UPDATE SET
            evaluation_status=excluded.evaluation_status,
            record_json=excluded.record_json
        WHERE policy_evaluation_records.evaluation_hash = excluded.evaluation_hash
          AND (
              SELECT COUNT(*)
              FROM policy_evaluation_audit_events
              WHERE policy_evaluation_audit_events.evaluation_id = excluded.evaluation_id
          ) <= %s
        """,
        (
            record["evaluation_id"],
            record["proposal_id"],
            record["proposal_version_id"],
            record["portfolio_id"],
            record["policy_pack_id"],
            record["policy_version"],
            record["generated_at"],
            record["evaluation_status"],
            record["source_evidence_hash"],
            record["policy_content_hash"],
            record["evaluation_hash"],
            json_dump(record),
            event_count,
        ),
    )
    _raise_if_no_rows(cursor, "POLICY_EVALUATION_RECORD_CONFLICT")


def _upsert_policy_evaluation_event(*, connection: Any, event: dict[str, Any]) -> None:
    reason = event.get("reason_json", {})
    cursor = connection.execute(
        """
        INSERT INTO policy_evaluation_audit_events (
            evaluation_id,
            event_id,
            event_type,
            actor_id,
            occurred_at,
            idempotency_key,
            request_hash,
            event_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (evaluation_id, event_id) DO UPDATE SET
            event_json=policy_evaluation_audit_events.event_json
        WHERE policy_evaluation_audit_events.request_hash = excluded.request_hash
          AND policy_evaluation_audit_events.event_json = excluded.event_json
        """,
        (
            event["evaluation_id"],
            event["event_id"],
            event["event_type"],
            event["actor_id"],
            event["occurred_at"],
            event.get("idempotency_key"),
            reason.get("idempotency_request_hash", ""),
            json_dump(event),
        ),
    )
    _raise_if_no_rows(cursor, "POLICY_EVALUATION_EVENT_CONFLICT")


def _upsert_policy_evaluation_idempotency(
    *, connection: Any, idempotency: dict[str, Any], created_at: str
) -> None:
    cursor = connection.execute(
        """
        INSERT INTO policy_evaluation_idempotency (
            idempotency_key,
            request_hash,
            evaluation_id,
            event_id,
            created_at
        ) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (idempotency_key) DO UPDATE SET
            request_hash=excluded.request_hash,
            evaluation_id=excluded.evaluation_id,
            event_id=excluded.event_id
        WHERE (
            policy_evaluation_idempotency.request_hash = excluded.request_hash
            AND policy_evaluation_idempotency.evaluation_id = excluded.evaluation_id
            AND policy_evaluation_idempotency.event_id = excluded.event_id
        )
        OR EXISTS (
            SELECT 1
            FROM policy_evaluation_records old_record
            JOIN policy_evaluation_records new_record
              ON new_record.evaluation_id = excluded.evaluation_id
            WHERE old_record.evaluation_id = policy_evaluation_idempotency.evaluation_id
              AND old_record.evaluation_status = 'BLOCKED'
              AND new_record.evaluation_status <> 'BLOCKED'
              AND old_record.proposal_id = new_record.proposal_id
              AND old_record.proposal_version_id = new_record.proposal_version_id
              AND old_record.portfolio_id = new_record.portfolio_id
              AND old_record.policy_pack_id = new_record.policy_pack_id
              AND old_record.policy_version = new_record.policy_version
              AND old_record.record_json::jsonb #> '{replay_metadata_json,creation_reason}'
                  = new_record.record_json::jsonb #> '{replay_metadata_json,creation_reason}'
              AND COALESCE(
                  (old_record.record_json::jsonb #> '{source_gaps}') ? 'legal_entity_code',
                  false
              )
              AND COALESCE(
                  (
                      old_record.record_json::jsonb
                      #> '{evaluation_json,applicability,reason_codes}'
                  ) ? 'POLICY_APPLICABILITY_LEGAL_ENTITY_SOURCE_MISSING',
                  false
              )
              AND NOT COALESCE(
                  (new_record.record_json::jsonb #> '{source_gaps}') ? 'legal_entity_code',
                  false
              )
              AND NOT COALESCE(
                  (
                      new_record.record_json::jsonb
                      #> '{evaluation_json,applicability,reason_codes}'
                  ) ? 'POLICY_APPLICABILITY_LEGAL_ENTITY_SOURCE_MISSING',
                  false
              )
        )
        """,
        (
            idempotency["idempotency_key"],
            idempotency["request_hash"],
            idempotency["evaluation_id"],
            idempotency["event_id"],
            created_at,
        ),
    )
    _raise_if_no_rows(cursor, "POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT")


def _upsert_policy_pack_catalog_version(
    *, connection: Any, definition: dict[str, Any], event_count: int
) -> None:
    cursor = connection.execute(
        """
        INSERT INTO policy_pack_catalog_versions (
            policy_pack_id,
            policy_version,
            activation_state,
            content_hash,
            definition_json
        ) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (policy_pack_id, policy_version) DO UPDATE SET
            activation_state=excluded.activation_state,
            content_hash=excluded.content_hash,
            definition_json=excluded.definition_json
        WHERE policy_pack_catalog_versions.content_hash = excluded.content_hash
          AND (
              SELECT COUNT(*)
              FROM policy_pack_catalog_audit_events
              WHERE policy_pack_catalog_audit_events.policy_pack_id = excluded.policy_pack_id
                AND policy_pack_catalog_audit_events.policy_version = excluded.policy_version
          ) <= %s
        """,
        (
            definition["policy_pack_id"],
            definition["policy_version"],
            definition["activation_state"],
            definition["content_hash"],
            json_dump(definition),
            event_count,
        ),
    )
    _raise_if_no_rows(cursor, "POLICY_PACK_CATALOG_VERSION_CONFLICT")


def _upsert_policy_pack_catalog_event(*, connection: Any, event: dict[str, Any]) -> None:
    reason = event.get("reason", {})
    cursor = connection.execute(
        """
        INSERT INTO policy_pack_catalog_audit_events (
            policy_pack_id,
            policy_version,
            event_id,
            event_type,
            actor_id,
            occurred_at,
            idempotency_key,
            request_hash,
            event_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (policy_pack_id, policy_version, event_id) DO UPDATE SET
            event_json=policy_pack_catalog_audit_events.event_json
        WHERE policy_pack_catalog_audit_events.request_hash = excluded.request_hash
          AND policy_pack_catalog_audit_events.event_json = excluded.event_json
        """,
        (
            event["policy_pack_id"],
            event["policy_version"],
            event["event_id"],
            event["event_type"],
            event["actor_id"],
            event["occurred_at"],
            event.get("idempotency_key"),
            reason.get("idempotency_request_hash", ""),
            json_dump(event),
        ),
    )
    _raise_if_no_rows(cursor, "POLICY_PACK_CATALOG_EVENT_CONFLICT")


def _upsert_policy_pack_catalog_idempotency(
    *, connection: Any, idempotency: dict[str, Any], created_at: str
) -> None:
    cursor = connection.execute(
        """
        INSERT INTO policy_pack_catalog_idempotency (
            idempotency_key,
            request_hash,
            policy_pack_id,
            policy_version,
            event_id,
            created_at
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (idempotency_key) DO UPDATE SET
            request_hash=policy_pack_catalog_idempotency.request_hash,
            policy_pack_id=policy_pack_catalog_idempotency.policy_pack_id,
            policy_version=policy_pack_catalog_idempotency.policy_version,
            event_id=policy_pack_catalog_idempotency.event_id
        WHERE policy_pack_catalog_idempotency.request_hash = excluded.request_hash
          AND policy_pack_catalog_idempotency.policy_pack_id = excluded.policy_pack_id
          AND policy_pack_catalog_idempotency.policy_version = excluded.policy_version
          AND policy_pack_catalog_idempotency.event_id = excluded.event_id
        """,
        (
            idempotency["idempotency_key"],
            idempotency["request_hash"],
            idempotency["policy_pack_id"],
            idempotency["policy_version"],
            idempotency["event_id"],
            created_at,
        ),
    )
    _raise_if_no_rows(cursor, "POLICY_PACK_IDEMPOTENCY_KEY_CONFLICT")


def _event_created_at(*, snapshot: dict[str, Any], idempotency: dict[str, Any]) -> str:
    for event in snapshot.get("events", {}).get(str(idempotency["evaluation_id"]), []):
        if event["event_id"] == idempotency["event_id"]:
            return str(event["occurred_at"])
    return ""


def _catalog_event_created_at(*, snapshot: dict[str, Any], idempotency: dict[str, Any]) -> str:
    for event in snapshot.get("events", []):
        if (
            event["policy_pack_id"] == idempotency["policy_pack_id"]
            and event["policy_version"] == idempotency["policy_version"]
            and event["event_id"] == idempotency["event_id"]
        ):
            return str(event["occurred_at"])
    return ""


def _catalog_event_count(
    *, events: list[dict[str, Any]], policy_pack_id: str, policy_version: str
) -> int:
    return sum(
        1
        for event in events
        if event["policy_pack_id"] == policy_pack_id and event["policy_version"] == policy_version
    )


def _raise_if_no_rows(cursor: Any, message: str) -> None:
    if getattr(cursor, "rowcount", None) == 0:
        raise ProposalIdempotencyConflictError(message)


__all__ = [
    "PostgresPolicyEvaluationStateStore",
    "PostgresPolicyPackCatalogStateStore",
]
