from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.core.proposals.exceptions import ProposalNotFoundError, ProposalValidationError
from src.core.proposals.idea_intake_authority import IdeaProposalIntakePrincipal
from src.core.proposals.idea_review_realization import (
    IdeaProposalRealizationStatus,
    IdeaProposalReviewWorkStatus,
)
from src.core.proposals.repository import ProposalRepository


class IdeaProposalRealizationOutcome(BaseModel):
    outcome_id: str = Field(description="Deterministic Advise-owned outcome identity.")
    source_event_version: int = Field(
        ge=1,
        description="Monotonic version within this realization history.",
    )
    status: IdeaProposalRealizationStatus = Field(
        description="Advise-owned realization posture at this event version."
    )
    reason_code: str = Field(description="Bounded machine-readable Advise outcome reason.")
    occurred_at: datetime = Field(description="UTC time at which Advise recorded the outcome.")
    review_work_id: str | None = Field(
        description="Advise review-work identity, absent when rejected before work."
    )
    proposal_id: str | None = Field(
        description="Advise proposal identity when linked; absent in the initial outcome tranche."
    )
    terminal: bool = Field(
        description="Whether this outcome terminally closes the conversion realization."
    )


class IdeaProposalRealizationHistoryResponse(BaseModel):
    realization_id: str = Field(description="Advise-owned conversion realization identity.")
    intake_id: str = Field(description="Deterministic Idea intake identity.")
    review_work_id: str | None = Field(
        description="Durable adviser-review work identity when accepted."
    )
    review_work_status: IdeaProposalReviewWorkStatus | None = Field(
        description="Current adviser-review queue posture when work exists."
    )
    source_authority: str = Field(default="lotus-idea")
    realization_authority: str = Field(default="lotus-advise")
    tenant_id: str
    legal_entity_code: str
    portfolio_id: str
    idea_candidate_id: str
    conversion_intent_id: str
    source_evidence_fingerprint: str
    current_status: IdeaProposalRealizationStatus
    current_source_event_version: int = Field(ge=1)
    proposal_record_created: bool = Field(
        default=False,
        description="False until a later Advise-owned proposal linkage is certified.",
    )
    suitability_authority_granted: bool = Field(default=False)
    order_created: bool = Field(default=False)
    client_publication_authorized: bool = Field(default=False)
    created_at: datetime
    updated_at: datetime
    outcomes: list[IdeaProposalRealizationOutcome]


def load_idea_proposal_realization_history(
    *,
    repository: ProposalRepository,
    intake_id: str,
    portfolio_id: str,
    principal: IdeaProposalIntakePrincipal,
) -> IdeaProposalRealizationHistoryResponse:
    normalized_intake_id = _required_printable(intake_id, "IDEA_PROPOSAL_INTAKE_ID_REQUIRED")
    normalized_portfolio_id = _required_printable(
        portfolio_id, "IDEA_PROPOSAL_PORTFOLIO_ID_REQUIRED"
    )
    if principal.authorized_portfolio_id != normalized_portfolio_id:
        raise ProposalNotFoundError("IDEA_PROPOSAL_REALIZATION_NOT_FOUND")
    history = repository.get_idea_proposal_realization(
        intake_id=normalized_intake_id,
        tenant_id=principal.tenant_id,
        legal_entity_code=principal.legal_entity_code,
        portfolio_id=normalized_portfolio_id,
    )
    if history is None:
        raise ProposalNotFoundError("IDEA_PROPOSAL_REALIZATION_NOT_FOUND")
    realization = history.realization
    return IdeaProposalRealizationHistoryResponse(
        realization_id=realization.realization_id,
        intake_id=realization.intake_id,
        review_work_id=realization.review_work_id,
        review_work_status=realization.review_work_status,
        tenant_id=realization.tenant_id,
        legal_entity_code=realization.legal_entity_code,
        portfolio_id=realization.portfolio_id,
        idea_candidate_id=realization.idea_candidate_id,
        conversion_intent_id=realization.conversion_intent_id,
        source_evidence_fingerprint=realization.source_evidence_fingerprint,
        current_status=realization.current_status,
        current_source_event_version=realization.current_source_event_version,
        created_at=realization.created_at_utc,
        updated_at=realization.updated_at_utc,
        outcomes=[
            IdeaProposalRealizationOutcome(
                outcome_id=outcome.outcome_id,
                source_event_version=outcome.source_event_version,
                status=outcome.status,
                reason_code=outcome.reason_code,
                occurred_at=outcome.occurred_at_utc,
                review_work_id=outcome.review_work_id,
                proposal_id=outcome.proposal_id,
                terminal=outcome.terminal,
            )
            for outcome in history.outcomes
        ],
    )


def _required_printable(value: str, detail: str) -> str:
    normalized = value.strip()
    if not normalized or not normalized.isprintable():
        raise ProposalValidationError(detail)
    return normalized
