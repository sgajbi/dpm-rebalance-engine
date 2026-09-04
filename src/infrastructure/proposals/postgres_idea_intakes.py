from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from typing import Any, Callable, cast

from src.core.proposals.exceptions import (
    ProposalIdempotencyConflictError,
    ProposalNotFoundError,
    ProposalStateConflictError,
)
from src.core.proposals.idea_intake_persistence import (
    IDEA_PROPOSAL_INTAKE_PURGE_BATCH_SIZE,
    IdeaProposalIntakeClaim,
    IdeaProposalIntakeRecord,
)
from src.core.proposals.idea_review_realization import (
    IdeaProposalRealizationHistoryRecord,
    IdeaProposalRealizationOutcomeRecord,
    IdeaProposalRealizationRecord,
    IdeaProposalRealizationStatus,
    IdeaProposalReviewWorkStatus,
    realization_claim_identity,
    realization_progression_identity,
    validate_realization_progression,
)

_REALIZATION_HISTORY_SELECT = """
    SELECT realization_id, intake_id, review_work_id, review_work_status, proposal_id,
           tenant_id, legal_entity_code, portfolio_id, idea_candidate_id, conversion_intent_id,
           source_evidence_fingerprint, current_status, current_source_event_version,
           created_at_utc, updated_at_utc
    FROM proposal_idea_review_realizations
"""


def claim_idea_proposal_intake(
    *,
    connect: Callable[[], Any],
    record: IdeaProposalIntakeRecord,
) -> IdeaProposalIntakeClaim:
    """Atomically persist or replay a scope-keyed Idea intake claim."""
    with closing(connect()) as connection:
        connection.execute(
            """
            WITH expired AS (
                SELECT registry_key
                FROM proposal_idea_intakes
                WHERE expires_at_utc <= %s AND legal_hold = FALSE
                ORDER BY (registry_key = %s) DESC, expires_at_utc, registry_key
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            ), deleted AS (
                DELETE FROM proposal_idea_intakes AS intake
                USING expired
                WHERE intake.registry_key = expired.registry_key
                  AND intake.legal_hold = FALSE
                RETURNING intake.registry_key, intake.request_fingerprint,
                          intake.created_at_utc, intake.expires_at_utc
            )
            INSERT INTO proposal_idea_intake_purge_events (
                registry_key_digest, request_fingerprint, claim_created_at_utc,
                claim_expired_at_utc, purged_at_utc, reason_code
            )
            SELECT registry_key, request_fingerprint, created_at_utc,
                   expires_at_utc, %s, 'REPLAY_WINDOW_EXPIRED'
            FROM deleted
            ON CONFLICT (registry_key_digest, claim_expired_at_utc) DO NOTHING
            """,
            (
                record.created_at_utc,
                record.registry_key,
                IDEA_PROPOSAL_INTAKE_PURGE_BATCH_SIZE,
                record.created_at_utc,
            ),
        )
        inserted = connection.execute(
            """
            INSERT INTO proposal_idea_intakes (
                registry_key, request_fingerprint, response_json, created_at_utc,
                expires_at_utc, legal_hold
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (registry_key) DO NOTHING
            RETURNING registry_key
            """,
            (
                record.registry_key,
                record.request_fingerprint,
                record.response_json,
                record.created_at_utc,
                record.expires_at_utc,
                record.legal_hold,
            ),
        ).fetchone()
        row = connection.execute(
            """
            SELECT registry_key, request_fingerprint, response_json, created_at_utc,
                   expires_at_utc, legal_hold
            FROM proposal_idea_intakes WHERE registry_key = %s
            """,
            (record.registry_key,),
        ).fetchone()
        if row is None:
            connection.rollback()
            raise RuntimeError("IDEA_PROPOSAL_INTAKE_PERSISTENCE_FAILED")
        if str(row["request_fingerprint"]) != record.request_fingerprint:
            connection.rollback()
            raise ProposalIdempotencyConflictError("IDEA_PROPOSAL_INTAKE_IDEMPOTENCY_CONFLICT")
        realization_claim = record
        if inserted is None:
            origin_timestamp = row["created_at_utc"]
            realization_claim = replace(
                record,
                realization=replace(
                    record.realization,
                    created_at_utc=origin_timestamp,
                    updated_at_utc=origin_timestamp,
                ),
                initial_outcome=replace(
                    record.initial_outcome,
                    occurred_at_utc=origin_timestamp,
                ),
            )
        realization = _claim_realization(
            connection=connection,
            requested=realization_claim.realization,
            source_claim_registry_key=record.registry_key,
        )
        initial_outcome = _claim_outcome(
            connection=connection,
            requested=realization_claim.initial_outcome,
        )
        existing = IdeaProposalIntakeRecord(
            registry_key=str(row["registry_key"]),
            request_fingerprint=str(row["request_fingerprint"]),
            response_json=str(row["response_json"]),
            created_at_utc=row["created_at_utc"],
            expires_at_utc=row["expires_at_utc"],
            realization=realization,
            initial_outcome=initial_outcome,
            legal_hold=bool(row["legal_hold"]),
        )
        connection.commit()
        return IdeaProposalIntakeClaim(record=existing, replayed=inserted is None)


def get_idea_proposal_realization(
    *,
    connect: Callable[[], Any],
    intake_id: str,
    tenant_id: str,
    legal_entity_code: str,
    portfolio_id: str,
) -> IdeaProposalRealizationHistoryRecord | None:
    """Load one realization only when every trusted scope dimension matches."""
    with closing(connect()) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        row = connection.execute(
            _REALIZATION_HISTORY_SELECT
            + """
            WHERE intake_id = %s
              AND tenant_id = %s
              AND legal_entity_code = %s
              AND portfolio_id = %s
            """,
            (intake_id, tenant_id, legal_entity_code, portfolio_id),
        ).fetchone()
        return None if row is None else _history_from_row(connection=connection, row=row)


def get_idea_proposal_realization_by_conversion_intent(
    *,
    connect: Callable[[], Any],
    conversion_intent_id: str,
    tenant_id: str,
    legal_entity_code: str,
    portfolio_id: str,
) -> IdeaProposalRealizationHistoryRecord | None:
    with closing(connect()) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        row = connection.execute(
            _REALIZATION_HISTORY_SELECT
            + """
            WHERE conversion_intent_id = %s
              AND tenant_id = %s
              AND legal_entity_code = %s
              AND portfolio_id = %s
            """,
            (conversion_intent_id, tenant_id, legal_entity_code, portfolio_id),
        ).fetchone()
        return None if row is None else _history_from_row(connection=connection, row=row)


def _history_from_row(*, connection: Any, row: Any) -> IdeaProposalRealizationHistoryRecord:
    realization = _realization_from_row(row)
    outcome_rows = connection.execute(
        """
        SELECT outcome_id, realization_id, source_event_version, status, reason_code,
               occurred_at_utc, review_work_id, proposal_id, terminal
        FROM proposal_idea_realization_outcomes
        WHERE realization_id = %s
        ORDER BY source_event_version
        """,
        (realization.realization_id,),
    ).fetchall()
    return IdeaProposalRealizationHistoryRecord(
        realization=realization,
        outcomes=tuple(_outcome_from_row(outcome_row) for outcome_row in outcome_rows),
    )


def advance_idea_proposal_realization(
    *,
    connect: Callable[[], Any],
    expected_source_event_version: int,
    realization: IdeaProposalRealizationRecord,
    outcomes: tuple[IdeaProposalRealizationOutcomeRecord, ...],
) -> IdeaProposalRealizationHistoryRecord:
    """Atomically append monotonic outcomes and advance the scoped realization."""

    with closing(connect()) as connection:
        try:
            current = _load_locked_realization(connection, realization.realization_id)
            _validate_realization_progression(
                current=current,
                expected_source_event_version=expected_source_event_version,
                realization=realization,
                outcomes=outcomes,
            )
            _require_valid_proposal_link(connection=connection, realization=realization)
            _append_realization_outcomes(connection=connection, outcomes=outcomes)
            _update_realization_progression(
                connection=connection,
                expected_source_event_version=expected_source_event_version,
                realization=realization,
            )
            stored_outcomes = _load_outcomes(
                connection=connection,
                realization_id=realization.realization_id,
            )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            if _constraint_name(exc) == "uq_proposal_idea_realization_proposal":
                raise ProposalStateConflictError(
                    "IDEA_PROPOSAL_REALIZATION_PROPOSAL_CONFLICT"
                ) from exc
            raise
        return IdeaProposalRealizationHistoryRecord(
            realization=realization,
            outcomes=stored_outcomes,
        )


def _constraint_name(exc: Exception) -> str | None:
    diagnostics = getattr(exc, "diag", None)
    constraint_name = getattr(diagnostics, "constraint_name", None)
    return str(constraint_name) if constraint_name is not None else None


def _load_locked_realization(connection: Any, realization_id: str) -> IdeaProposalRealizationRecord:
    row = connection.execute(
        _REALIZATION_HISTORY_SELECT
        + """
        WHERE realization_id = %s
        FOR UPDATE
        """,
        (realization_id,),
    ).fetchone()
    if row is None:
        raise ProposalNotFoundError("IDEA_PROPOSAL_REALIZATION_NOT_FOUND")
    return _realization_from_row(row)


def _validate_realization_progression(
    *,
    current: IdeaProposalRealizationRecord,
    expected_source_event_version: int,
    realization: IdeaProposalRealizationRecord,
    outcomes: tuple[IdeaProposalRealizationOutcomeRecord, ...],
) -> None:
    if realization_progression_identity(current) != realization_progression_identity(realization):
        raise ProposalStateConflictError("IDEA_PROPOSAL_REALIZATION_SCOPE_CONFLICT")
    validate_realization_progression(
        current_source_event_version=current.current_source_event_version,
        expected_source_event_version=expected_source_event_version,
        realization=realization,
        outcomes=outcomes,
    )


def _require_valid_proposal_link(
    *, connection: Any, realization: IdeaProposalRealizationRecord
) -> None:
    proposal_row = connection.execute(
        "SELECT portfolio_id, created_at::timestamptz AS created_at "
        "FROM proposal_records WHERE proposal_id = %s",
        (realization.proposal_id,),
    ).fetchone()
    if proposal_row is None or str(proposal_row["portfolio_id"]) != realization.portfolio_id:
        raise ProposalNotFoundError("IDEA_PROPOSAL_RECONCILIATION_PROPOSAL_NOT_FOUND")
    if proposal_row["created_at"] < realization.created_at_utc:
        raise ProposalNotFoundError("IDEA_PROPOSAL_RECONCILIATION_PROPOSAL_NOT_FOUND")


def _append_realization_outcomes(
    *, connection: Any, outcomes: tuple[IdeaProposalRealizationOutcomeRecord, ...]
) -> None:
    for outcome in outcomes:
        _claim_outcome(connection=connection, requested=outcome)


def _update_realization_progression(
    *,
    connection: Any,
    expected_source_event_version: int,
    realization: IdeaProposalRealizationRecord,
) -> None:
    updated = connection.execute(
        """
        UPDATE proposal_idea_review_realizations
        SET review_work_status = %s,
            proposal_id = %s,
            current_status = %s,
            current_source_event_version = %s,
            updated_at_utc = %s
        WHERE realization_id = %s AND current_source_event_version = %s
        RETURNING realization_id
        """,
        (
            realization.review_work_status,
            realization.proposal_id,
            realization.current_status,
            realization.current_source_event_version,
            realization.updated_at_utc,
            realization.realization_id,
            expected_source_event_version,
        ),
    ).fetchone()
    if updated is None:
        raise ProposalStateConflictError("IDEA_PROPOSAL_REALIZATION_VERSION_CONFLICT")


def _load_outcomes(
    *, connection: Any, realization_id: str
) -> tuple[IdeaProposalRealizationOutcomeRecord, ...]:
    rows = connection.execute(
        """
        SELECT outcome_id, realization_id, source_event_version, status, reason_code,
               occurred_at_utc, review_work_id, proposal_id, terminal
        FROM proposal_idea_realization_outcomes
        WHERE realization_id = %s
        ORDER BY source_event_version
        """,
        (realization_id,),
    ).fetchall()
    return tuple(_outcome_from_row(row) for row in rows)


def _claim_realization(
    *,
    connection: Any,
    requested: IdeaProposalRealizationRecord,
    source_claim_registry_key: str,
) -> IdeaProposalRealizationRecord:
    connection.execute(
        """
        INSERT INTO proposal_idea_review_realizations (
            realization_id, intake_id, source_claim_registry_key,
            review_work_id, review_work_status, proposal_id,
            tenant_id, legal_entity_code,
            portfolio_id, idea_candidate_id, conversion_intent_id,
            source_evidence_fingerprint, current_status, current_source_event_version,
            created_at_utc, updated_at_utc
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (realization_id) DO NOTHING
        """,
        (
            requested.realization_id,
            requested.intake_id,
            source_claim_registry_key,
            requested.review_work_id,
            requested.review_work_status,
            requested.proposal_id,
            requested.tenant_id,
            requested.legal_entity_code,
            requested.portfolio_id,
            requested.idea_candidate_id,
            requested.conversion_intent_id,
            requested.source_evidence_fingerprint,
            requested.current_status,
            requested.current_source_event_version,
            requested.created_at_utc,
            requested.updated_at_utc,
        ),
    )
    row = connection.execute(
        _REALIZATION_HISTORY_SELECT
        + """
        WHERE realization_id = %s
        """,
        (requested.realization_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("IDEA_PROPOSAL_REALIZATION_PERSISTENCE_FAILED")
    stored = _realization_from_row(row)
    if realization_claim_identity(stored) != realization_claim_identity(requested):
        raise ProposalIdempotencyConflictError("IDEA_PROPOSAL_REALIZATION_CONFLICT")
    return stored


def _claim_outcome(
    *, connection: Any, requested: IdeaProposalRealizationOutcomeRecord
) -> IdeaProposalRealizationOutcomeRecord:
    connection.execute(
        """
        INSERT INTO proposal_idea_realization_outcomes (
            outcome_id, realization_id, source_event_version, status, reason_code,
            occurred_at_utc, review_work_id, proposal_id, terminal
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (realization_id, source_event_version) DO NOTHING
        """,
        (
            requested.outcome_id,
            requested.realization_id,
            requested.source_event_version,
            requested.status,
            requested.reason_code,
            requested.occurred_at_utc,
            requested.review_work_id,
            requested.proposal_id,
            requested.terminal,
        ),
    )
    row = connection.execute(
        """
        SELECT outcome_id, realization_id, source_event_version, status, reason_code,
               occurred_at_utc, review_work_id, proposal_id, terminal
        FROM proposal_idea_realization_outcomes
        WHERE realization_id = %s AND source_event_version = %s
        """,
        (requested.realization_id, requested.source_event_version),
    ).fetchone()
    if row is None:
        raise RuntimeError("IDEA_PROPOSAL_REALIZATION_OUTCOME_PERSISTENCE_FAILED")
    stored = _outcome_from_row(row)
    if _outcome_identity(stored) != _outcome_identity(requested):
        raise ProposalIdempotencyConflictError("IDEA_PROPOSAL_REALIZATION_CONFLICT")
    return stored


def _realization_from_row(row: Any) -> IdeaProposalRealizationRecord:
    return IdeaProposalRealizationRecord(
        realization_id=str(row["realization_id"]),
        intake_id=str(row["intake_id"]),
        review_work_id=(str(row["review_work_id"]) if row["review_work_id"] is not None else None),
        review_work_status=(
            cast(IdeaProposalReviewWorkStatus, str(row["review_work_status"]))
            if row["review_work_status"] is not None
            else None
        ),
        proposal_id=str(row["proposal_id"]) if row["proposal_id"] is not None else None,
        tenant_id=str(row["tenant_id"]),
        legal_entity_code=str(row["legal_entity_code"]),
        portfolio_id=str(row["portfolio_id"]),
        idea_candidate_id=str(row["idea_candidate_id"]),
        conversion_intent_id=str(row["conversion_intent_id"]),
        source_evidence_fingerprint=str(row["source_evidence_fingerprint"]),
        current_status=cast(IdeaProposalRealizationStatus, str(row["current_status"])),
        current_source_event_version=int(row["current_source_event_version"]),
        created_at_utc=row["created_at_utc"],
        updated_at_utc=row["updated_at_utc"],
    )


def _outcome_from_row(row: Any) -> IdeaProposalRealizationOutcomeRecord:
    return IdeaProposalRealizationOutcomeRecord(
        outcome_id=str(row["outcome_id"]),
        realization_id=str(row["realization_id"]),
        source_event_version=int(row["source_event_version"]),
        status=cast(IdeaProposalRealizationStatus, str(row["status"])),
        reason_code=str(row["reason_code"]),
        occurred_at_utc=row["occurred_at_utc"],
        review_work_id=(str(row["review_work_id"]) if row["review_work_id"] is not None else None),
        proposal_id=str(row["proposal_id"]) if row["proposal_id"] is not None else None,
        terminal=bool(row["terminal"]),
    )


def _outcome_identity(record: IdeaProposalRealizationOutcomeRecord) -> tuple[Any, ...]:
    return (
        record.outcome_id,
        record.realization_id,
        record.source_event_version,
        record.status,
        record.reason_code,
        record.review_work_id,
        record.proposal_id,
        record.terminal,
    )
