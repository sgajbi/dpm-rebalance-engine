from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from src.core.proposals.exceptions import ProposalStateConflictError

IdeaProposalRealizationStatus = Literal[
    "ACCEPTED_FOR_REVIEW",
    "PROPOSAL_LINKED",
    "ADVISORY_REJECTED",
    "ADVISORY_CANCELLED",
    "ADVISORY_EXPIRED",
    "ADVISORY_COMPLETED",
    "REJECTED_BEFORE_WORK",
]
IdeaProposalReviewWorkStatus = Literal[
    "PENDING_ADVISER_REVIEW",
    "PROPOSAL_LINKED",
    "CLOSED",
]


@dataclass(frozen=True)
class IdeaProposalRealizationRecord:
    """Advise-owned realization of one immutable Idea conversion intent."""

    realization_id: str
    intake_id: str
    review_work_id: str | None
    review_work_status: IdeaProposalReviewWorkStatus | None
    tenant_id: str
    legal_entity_code: str
    portfolio_id: str
    idea_candidate_id: str
    conversion_intent_id: str
    source_evidence_fingerprint: str
    current_status: IdeaProposalRealizationStatus
    current_source_event_version: int
    created_at_utc: datetime
    updated_at_utc: datetime
    proposal_id: str | None = None


@dataclass(frozen=True)
class IdeaProposalRealizationOutcomeRecord:
    """One append-only, Advise-owned realization outcome."""

    outcome_id: str
    realization_id: str
    source_event_version: int
    status: IdeaProposalRealizationStatus
    reason_code: str
    occurred_at_utc: datetime
    review_work_id: str | None
    proposal_id: str | None
    terminal: bool


@dataclass(frozen=True)
class IdeaProposalRealizationHistoryRecord:
    """Scope-checked realization aggregate and its ordered outcome history."""

    realization: IdeaProposalRealizationRecord
    outcomes: tuple[IdeaProposalRealizationOutcomeRecord, ...]


def realization_claim_identity(record: IdeaProposalRealizationRecord) -> tuple[object, ...]:
    """Return request-derived identity retained across replay and later progression."""

    return (
        record.realization_id,
        record.intake_id,
        record.review_work_id,
        record.tenant_id,
        record.legal_entity_code,
        record.portfolio_id,
        record.idea_candidate_id,
        record.conversion_intent_id,
        record.source_evidence_fingerprint,
    )


def realization_progression_identity(record: IdeaProposalRealizationRecord) -> tuple[object, ...]:
    """Return immutable persisted identity, including the original chronology anchor."""

    return (*realization_claim_identity(record), record.created_at_utc)


def validate_realization_progression(
    *,
    current_source_event_version: int,
    expected_source_event_version: int,
    realization: IdeaProposalRealizationRecord,
    outcomes: tuple[IdeaProposalRealizationOutcomeRecord, ...],
) -> None:
    """Enforce the shared compare-and-set and append-only outcome sequence."""

    if current_source_event_version != expected_source_event_version:
        raise ProposalStateConflictError("IDEA_PROPOSAL_REALIZATION_VERSION_CONFLICT")
    expected_final_version = expected_source_event_version + len(outcomes)
    if realization.current_source_event_version != expected_final_version:
        raise ProposalStateConflictError("IDEA_PROPOSAL_REALIZATION_PROGRESSION_INVALID")
    if not all(
        _matches_expected_outcome(
            outcome=outcome,
            realization_id=realization.realization_id,
            source_event_version=expected_source_event_version + offset,
        )
        for offset, outcome in enumerate(outcomes, start=1)
    ):
        raise ProposalStateConflictError("IDEA_PROPOSAL_REALIZATION_PROGRESSION_INVALID")


def _matches_expected_outcome(
    *,
    outcome: IdeaProposalRealizationOutcomeRecord,
    realization_id: str,
    source_event_version: int,
) -> bool:
    return (
        outcome.realization_id == realization_id
        and outcome.source_event_version == source_event_version
    )
