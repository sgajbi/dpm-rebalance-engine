from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

IdeaProposalRealizationStatus = Literal[
    "ACCEPTED_FOR_REVIEW",
    "REJECTED_BEFORE_WORK",
]
IdeaProposalReviewWorkStatus = Literal["PENDING_ADVISER_REVIEW"]


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
