from __future__ import annotations

from contextlib import closing
from typing import Any, Callable

from src.core.proposals.exceptions import ProposalIdempotencyConflictError
from src.core.proposals.idea_intake_persistence import (
    IdeaProposalIntakeClaim,
    IdeaProposalIntakeRecord,
)


def claim_idea_proposal_intake(
    *,
    connect: Callable[[], Any],
    record: IdeaProposalIntakeRecord,
) -> IdeaProposalIntakeClaim:
    """Atomically persist or replay a scope-keyed Idea intake claim."""
    with closing(connect()) as connection:
        connection.execute(
            """
            DELETE FROM proposal_idea_intakes
            WHERE expires_at_utc <= %s AND legal_hold = FALSE
            """,
            (record.created_at_utc,),
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
        existing = IdeaProposalIntakeRecord(
            registry_key=str(row["registry_key"]),
            request_fingerprint=str(row["request_fingerprint"]),
            response_json=str(row["response_json"]),
            created_at_utc=row["created_at_utc"],
            expires_at_utc=row["expires_at_utc"],
            legal_hold=bool(row["legal_hold"]),
        )
        if existing.request_fingerprint != record.request_fingerprint:
            connection.rollback()
            raise ProposalIdempotencyConflictError("IDEA_PROPOSAL_INTAKE_IDEMPOTENCY_CONFLICT")
        connection.commit()
        return IdeaProposalIntakeClaim(record=existing, replayed=inserted is None)
