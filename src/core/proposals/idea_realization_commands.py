from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from typing import Final

from pydantic import BaseModel, Field, field_validator

from src.core.proposals.contract_types import ProposalWorkflowState
from src.core.proposals.exceptions import (
    ProposalNotFoundError,
    ProposalStateConflictError,
    ProposalTransitionError,
)
from src.core.proposals.idea_intake_authority import IdeaProposalIntakePrincipal
from src.core.proposals.idea_realization_read_model import (
    IdeaProposalRealizationHistoryResponse,
    build_idea_proposal_realization_history_response,
)
from src.core.proposals.idea_review_realization import (
    IdeaProposalRealizationHistoryRecord,
    IdeaProposalRealizationOutcomeRecord,
    IdeaProposalRealizationRecord,
    IdeaProposalRealizationStatus,
    IdeaProposalReviewWorkStatus,
)
from src.core.proposals.persistence_models import ProposalRecord
from src.core.proposals.repository import ProposalRepository


class IdeaProposalReconciliationRequest(BaseModel):
    """Compare-and-set command that links and reconciles one Advise proposal."""

    proposal_id: str = Field(
        min_length=1,
        max_length=160,
        description="Existing Advise proposal to link to the Idea conversion realization.",
        examples=["pp_001"],
    )
    expected_source_event_version: int = Field(
        ge=1,
        description=(
            "Latest realization version observed by the caller. Replays of an already-applied "
            "proposal posture remain idempotent; competing progression fails with 409."
        ),
        examples=[1],
    )

    @field_validator("proposal_id")
    @classmethod
    def _normalize_proposal_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not normalized.isprintable():
            raise ValueError("IDEA_PROPOSAL_RECONCILIATION_PROPOSAL_ID_REQUIRED")
        return normalized


_TERMINAL_PROPOSAL_OUTCOMES: Final[
    dict[ProposalWorkflowState, tuple[IdeaProposalRealizationStatus, str]]
] = {
    "REJECTED": ("ADVISORY_REJECTED", "advise_proposal_rejected"),
    "CANCELLED": ("ADVISORY_CANCELLED", "advise_proposal_cancelled"),
    "EXPIRED": ("ADVISORY_EXPIRED", "advise_proposal_expired"),
    "EXECUTED": ("ADVISORY_COMPLETED", "advise_proposal_workflow_completed"),
}


def reconcile_idea_proposal_realization(
    *,
    repository: ProposalRepository,
    intake_id: str,
    portfolio_id: str,
    payload: IdeaProposalReconciliationRequest,
    principal: IdeaProposalIntakePrincipal,
    occurred_at: datetime | None = None,
) -> IdeaProposalRealizationHistoryResponse:
    """Link an actual proposal and project only authoritative Advise terminal posture."""

    normalized_intake_id = _required_printable(intake_id, "IDEA_PROPOSAL_INTAKE_ID_REQUIRED")
    normalized_portfolio_id = _required_printable(
        portfolio_id, "IDEA_PROPOSAL_PORTFOLIO_ID_REQUIRED"
    )
    if principal.authorized_portfolio_id != normalized_portfolio_id:
        raise ProposalNotFoundError("IDEA_PROPOSAL_REALIZATION_NOT_FOUND")

    history, proposal = _load_reconciliation_context(
        repository=repository,
        intake_id=normalized_intake_id,
        portfolio_id=normalized_portfolio_id,
        principal=principal,
        proposal_id=payload.proposal_id,
    )
    timestamp = occurred_at or datetime.now(timezone.utc)
    target_status = _target_status(proposal.current_state)
    if _already_reconciled(
        realization=history.realization,
        proposal_id=proposal.proposal_id,
        target_status=target_status,
    ):
        return build_idea_proposal_realization_history_response(history)

    realization = history.realization
    _validate_progression_request(
        realization=realization,
        proposal_id=proposal.proposal_id,
        expected_source_event_version=payload.expected_source_event_version,
    )
    updated, new_outcomes = _build_progression(
        realization=realization,
        proposal_id=proposal.proposal_id,
        proposal_state=proposal.current_state,
        occurred_at=timestamp,
    )
    advanced = _advance_or_replay_concurrent_progression(
        repository=repository,
        expected_source_event_version=realization.current_source_event_version,
        updated=updated,
        outcomes=new_outcomes,
        intake_id=normalized_intake_id,
        portfolio_id=normalized_portfolio_id,
        principal=principal,
        proposal_id=proposal.proposal_id,
        target_status=target_status,
    )
    return build_idea_proposal_realization_history_response(advanced)


def _load_reconciliation_context(
    *,
    repository: ProposalRepository,
    intake_id: str,
    portfolio_id: str,
    principal: IdeaProposalIntakePrincipal,
    proposal_id: str,
) -> tuple[IdeaProposalRealizationHistoryRecord, ProposalRecord]:
    history = _load_history(
        repository=repository,
        intake_id=intake_id,
        portfolio_id=portfolio_id,
        principal=principal,
    )
    proposal = repository.get_proposal(proposal_id=proposal_id)
    if proposal is None or proposal.portfolio_id != portfolio_id:
        raise ProposalNotFoundError("IDEA_PROPOSAL_RECONCILIATION_PROPOSAL_NOT_FOUND")
    if proposal.created_at < history.realization.created_at_utc:
        raise ProposalTransitionError("IDEA_PROPOSAL_RECONCILIATION_PROPOSAL_PRECEDES_REVIEW_WORK")
    return history, proposal


def _validate_progression_request(
    *,
    realization: IdeaProposalRealizationRecord,
    proposal_id: str,
    expected_source_event_version: int,
) -> None:
    if realization.current_status == "REJECTED_BEFORE_WORK":
        raise ProposalTransitionError("IDEA_PROPOSAL_REALIZATION_REJECTED_BEFORE_WORK")
    if realization.proposal_id not in {None, proposal_id}:
        raise ProposalStateConflictError("IDEA_PROPOSAL_REALIZATION_PROPOSAL_CONFLICT")
    if expected_source_event_version != realization.current_source_event_version:
        raise ProposalStateConflictError("IDEA_PROPOSAL_REALIZATION_VERSION_CONFLICT")


def _advance_or_replay_concurrent_progression(
    *,
    repository: ProposalRepository,
    expected_source_event_version: int,
    updated: IdeaProposalRealizationRecord,
    outcomes: tuple[IdeaProposalRealizationOutcomeRecord, ...],
    intake_id: str,
    portfolio_id: str,
    principal: IdeaProposalIntakePrincipal,
    proposal_id: str,
    target_status: IdeaProposalRealizationStatus,
) -> IdeaProposalRealizationHistoryRecord:
    try:
        return repository.advance_idea_proposal_realization(
            expected_source_event_version=expected_source_event_version,
            realization=updated,
            outcomes=outcomes,
        )
    except ProposalStateConflictError:
        concurrent = _load_history(
            repository=repository,
            intake_id=intake_id,
            portfolio_id=portfolio_id,
            principal=principal,
        )
        if _already_reconciled(
            realization=concurrent.realization,
            proposal_id=proposal_id,
            target_status=target_status,
        ):
            return concurrent
        raise


def _load_history(
    *,
    repository: ProposalRepository,
    intake_id: str,
    portfolio_id: str,
    principal: IdeaProposalIntakePrincipal,
) -> IdeaProposalRealizationHistoryRecord:
    history = repository.get_idea_proposal_realization(
        intake_id=intake_id,
        tenant_id=principal.tenant_id,
        legal_entity_code=principal.legal_entity_code,
        portfolio_id=portfolio_id,
    )
    if history is None:
        raise ProposalNotFoundError("IDEA_PROPOSAL_REALIZATION_NOT_FOUND")
    return history


def _build_progression(
    *,
    realization: IdeaProposalRealizationRecord,
    proposal_id: str,
    proposal_state: ProposalWorkflowState,
    occurred_at: datetime,
) -> tuple[IdeaProposalRealizationRecord, tuple[IdeaProposalRealizationOutcomeRecord, ...]]:
    outcomes: list[IdeaProposalRealizationOutcomeRecord] = []
    version = realization.current_source_event_version
    if realization.proposal_id is None:
        version += 1
        outcomes.append(
            _outcome(
                realization=realization,
                proposal_id=proposal_id,
                version=version,
                status="PROPOSAL_LINKED",
                reason_code="advise_proposal_linked",
                occurred_at=occurred_at,
                terminal=False,
            )
        )

    terminal_outcome = _TERMINAL_PROPOSAL_OUTCOMES.get(proposal_state)
    review_work_status: IdeaProposalReviewWorkStatus
    current_status: IdeaProposalRealizationStatus
    if terminal_outcome is not None:
        version += 1
        status, reason_code = terminal_outcome
        outcomes.append(
            _outcome(
                realization=realization,
                proposal_id=proposal_id,
                version=version,
                status=status,
                reason_code=reason_code,
                occurred_at=occurred_at,
                terminal=True,
            )
        )
        review_work_status = "CLOSED"
        current_status = status
    else:
        review_work_status = "PROPOSAL_LINKED"
        current_status = "PROPOSAL_LINKED"

    return (
        replace(
            realization,
            proposal_id=proposal_id,
            review_work_status=review_work_status,
            current_status=current_status,
            current_source_event_version=version,
            updated_at_utc=occurred_at,
        ),
        tuple(outcomes),
    )


def _outcome(
    *,
    realization: IdeaProposalRealizationRecord,
    proposal_id: str,
    version: int,
    status: IdeaProposalRealizationStatus,
    reason_code: str,
    occurred_at: datetime,
    terminal: bool,
) -> IdeaProposalRealizationOutcomeRecord:
    identity = f"{realization.realization_id}|{version}|{status}|{proposal_id}"
    return IdeaProposalRealizationOutcomeRecord(
        outcome_id=f"ipro_{sha256(identity.encode()).hexdigest()[:12]}",
        realization_id=realization.realization_id,
        source_event_version=version,
        status=status,
        reason_code=reason_code,
        occurred_at_utc=occurred_at,
        review_work_id=realization.review_work_id,
        proposal_id=proposal_id,
        terminal=terminal,
    )


def _target_status(proposal_state: ProposalWorkflowState) -> IdeaProposalRealizationStatus:
    terminal = _TERMINAL_PROPOSAL_OUTCOMES.get(proposal_state)
    return terminal[0] if terminal is not None else "PROPOSAL_LINKED"


def _already_reconciled(
    *,
    realization: IdeaProposalRealizationRecord,
    proposal_id: str,
    target_status: IdeaProposalRealizationStatus,
) -> bool:
    return bool(
        realization.proposal_id == proposal_id and realization.current_status == target_status
    )


def _required_printable(value: str, detail: str) -> str:
    normalized = value.strip()
    if not normalized or not normalized.isprintable():
        raise ProposalTransitionError(detail)
    return normalized


__all__ = [
    "IdeaProposalReconciliationRequest",
    "reconcile_idea_proposal_realization",
]
