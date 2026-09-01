from datetime import datetime, timedelta, timezone

import pytest

from src.core.proposals.contract_types import ProposalWorkflowState
from src.core.proposals.exceptions import (
    ProposalNotFoundError,
    ProposalStateConflictError,
    ProposalTransitionError,
)
from src.core.proposals.idea_intake_authority import IdeaProposalIntakePrincipal
from src.core.proposals.idea_proposal_intake import (
    IdeaProposalIntakeRequest,
    IdeaProposalIntentType,
    process_idea_proposal_intake,
)
from src.core.proposals.idea_realization_commands import (
    IdeaProposalReconciliationRequest,
    reconcile_idea_proposal_realization,
)
from src.core.proposals.idea_review_realization import IdeaProposalRealizationStatus
from src.core.proposals.persistence_models import ProposalRecord
from src.infrastructure.proposals.in_memory import InMemoryProposalRepository

NOW = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
PORTFOLIO_ID = "PB_SG_GLOBAL_BAL_001"


def _principal(
    *, authorized_portfolio_id: str | None = PORTFOLIO_ID
) -> IdeaProposalIntakePrincipal:
    return IdeaProposalIntakePrincipal(
        actor_id="advisor-001",
        role="ADVISOR",
        tenant_id="tenant-private-bank-sg",
        legal_entity_code="SGPB",
        correlation_id="corr-idea-reconciliation",
        service_identity="lotus-advise",
        capabilities=frozenset({"advisory.idea_proposal_realization.write"}),
        authorized_portfolio_id=authorized_portfolio_id,
    )


def _intake_request(
    *, intent_type: IdeaProposalIntentType = "REVIEW_FOR_ADVISORY_PROPOSAL"
) -> IdeaProposalIntakeRequest:
    return IdeaProposalIntakeRequest.model_validate(
        {
            "source_system": "lotus-idea",
            "source_product": "lotus-idea:IdeaCandidate:v1",
            "idea_candidate_id": "idea_candidate_001",
            "conversion_intent_id": "conversion_intent_001",
            "intent_type": intent_type,
            "portfolio_id": PORTFOLIO_ID,
            "source_refs": [
                {
                    "source_system": "lotus-idea",
                    "source_type": "IdeaCandidate",
                    "source_id": "idea_candidate_001",
                    "content_hash": "sha256:evidence",
                }
            ],
        }
    )


def _seed_intake(
    repository: InMemoryProposalRepository,
    *,
    intent_type: IdeaProposalIntentType = "REVIEW_FOR_ADVISORY_PROPOSAL",
) -> str:
    response = process_idea_proposal_intake(
        _intake_request(intent_type=intent_type),
        correlation_id="corr-idea-intake",
        idempotency_key=f"idea-intake-{intent_type}",
        principal=_principal(),
        repository=repository,
        received_at=NOW,
    )
    return response.intake_id


def _proposal(
    *,
    proposal_id: str = "pp_idea_001",
    portfolio_id: str = PORTFOLIO_ID,
    state: ProposalWorkflowState = "DRAFT",
) -> ProposalRecord:
    return ProposalRecord(
        proposal_id=proposal_id,
        portfolio_id=portfolio_id,
        created_by="advisor-001",
        created_at=NOW,
        last_event_at=NOW,
        current_state=state,
        current_version_no=1,
    )


@pytest.mark.parametrize(
    ("proposal_state", "expected_status", "expected_reason"),
    [
        ("REJECTED", "ADVISORY_REJECTED", "advise_proposal_rejected"),
        ("CANCELLED", "ADVISORY_CANCELLED", "advise_proposal_cancelled"),
        ("EXPIRED", "ADVISORY_EXPIRED", "advise_proposal_expired"),
        ("EXECUTED", "ADVISORY_COMPLETED", "advise_proposal_workflow_completed"),
    ],
)
def test_reconciliation_links_and_records_authoritative_terminal_proposal_state(
    proposal_state: ProposalWorkflowState,
    expected_status: IdeaProposalRealizationStatus,
    expected_reason: str,
) -> None:
    repository = InMemoryProposalRepository()
    intake_id = _seed_intake(repository)
    proposal = _proposal(state=proposal_state)
    repository.create_proposal(proposal)

    response = reconcile_idea_proposal_realization(
        repository=repository,
        intake_id=intake_id,
        portfolio_id=PORTFOLIO_ID,
        payload=IdeaProposalReconciliationRequest(
            proposal_id=proposal.proposal_id,
            expected_source_event_version=1,
        ),
        principal=_principal(),
        occurred_at=NOW,
    )

    assert response.current_status == expected_status
    assert response.current_source_event_version == 3
    assert response.review_work_status == "CLOSED"
    assert [outcome.status for outcome in response.outcomes] == [
        "ACCEPTED_FOR_REVIEW",
        "PROPOSAL_LINKED",
        expected_status,
    ]
    assert response.outcomes[-1].reason_code == expected_reason
    assert response.outcomes[-1].terminal is True
    assert response.proposal_id == proposal.proposal_id
    assert response.proposal_record_created is True
    assert response.suitability_authority_granted is False
    assert response.order_created is False
    assert response.client_publication_authorized is False


@pytest.mark.parametrize(
    "proposal_state",
    ["DRAFT", "RISK_REVIEW", "COMPLIANCE_REVIEW", "AWAITING_CLIENT_CONSENT", "EXECUTION_READY"],
)
def test_reconciliation_does_not_infer_terminal_outcome_from_nonterminal_proposal(
    proposal_state: ProposalWorkflowState,
) -> None:
    repository = InMemoryProposalRepository()
    intake_id = _seed_intake(repository)
    proposal = _proposal(state=proposal_state)
    repository.create_proposal(proposal)

    response = reconcile_idea_proposal_realization(
        repository=repository,
        intake_id=intake_id,
        portfolio_id=PORTFOLIO_ID,
        payload=IdeaProposalReconciliationRequest(
            proposal_id=proposal.proposal_id,
            expected_source_event_version=1,
        ),
        principal=_principal(),
        occurred_at=NOW,
    )

    assert response.current_status == "PROPOSAL_LINKED"
    assert response.current_source_event_version == 2
    assert response.outcomes[-1].terminal is False


def test_reconciliation_rejects_stale_progression_after_proposal_state_changes() -> None:
    repository = InMemoryProposalRepository()
    intake_id = _seed_intake(repository)
    proposal = _proposal()
    repository.create_proposal(proposal)
    request = IdeaProposalReconciliationRequest(
        proposal_id=proposal.proposal_id,
        expected_source_event_version=1,
    )
    reconcile_idea_proposal_realization(
        repository=repository,
        intake_id=intake_id,
        portfolio_id=PORTFOLIO_ID,
        payload=request,
        principal=_principal(),
        occurred_at=NOW,
    )
    repository.update_proposal(proposal.model_copy(update={"current_state": "REJECTED"}))

    with pytest.raises(
        ProposalStateConflictError,
        match="IDEA_PROPOSAL_REALIZATION_VERSION_CONFLICT",
    ):
        reconcile_idea_proposal_realization(
            repository=repository,
            intake_id=intake_id,
            portfolio_id=PORTFOLIO_ID,
            payload=request,
            principal=_principal(),
            occurred_at=NOW,
        )


def test_reconciliation_rejects_intake_that_never_created_review_work() -> None:
    repository = InMemoryProposalRepository()
    intake_id = _seed_intake(repository, intent_type="CREATE_ADVISORY_PROPOSAL_DRAFT")
    proposal = _proposal()
    repository.create_proposal(proposal)

    with pytest.raises(
        ProposalTransitionError,
        match="IDEA_PROPOSAL_REALIZATION_REJECTED_BEFORE_WORK",
    ):
        reconcile_idea_proposal_realization(
            repository=repository,
            intake_id=intake_id,
            portfolio_id=PORTFOLIO_ID,
            payload=IdeaProposalReconciliationRequest(
                proposal_id=proposal.proposal_id,
                expected_source_event_version=1,
            ),
            principal=_principal(),
            occurred_at=NOW,
        )


def test_reconciliation_hides_realization_and_proposal_outside_authorized_scope() -> None:
    repository = InMemoryProposalRepository()
    intake_id = _seed_intake(repository)
    repository.create_proposal(_proposal(portfolio_id="PB_OTHER"))

    with pytest.raises(ProposalNotFoundError, match="IDEA_PROPOSAL_REALIZATION_NOT_FOUND"):
        reconcile_idea_proposal_realization(
            repository=repository,
            intake_id=intake_id,
            portfolio_id=PORTFOLIO_ID,
            payload=IdeaProposalReconciliationRequest(
                proposal_id="pp_idea_001",
                expected_source_event_version=1,
            ),
            principal=_principal(authorized_portfolio_id="PB_OTHER"),
            occurred_at=NOW,
        )


def test_reconciliation_rejects_proposal_that_predates_review_work() -> None:
    repository = InMemoryProposalRepository()
    intake_id = _seed_intake(repository)
    proposal = _proposal().model_copy(
        update={"created_at": NOW - timedelta(seconds=1), "last_event_at": NOW}
    )
    repository.create_proposal(proposal)

    with pytest.raises(
        ProposalTransitionError,
        match="IDEA_PROPOSAL_RECONCILIATION_PROPOSAL_PRECEDES_REVIEW_WORK",
    ):
        reconcile_idea_proposal_realization(
            repository=repository,
            intake_id=intake_id,
            portfolio_id=PORTFOLIO_ID,
            payload=IdeaProposalReconciliationRequest(
                proposal_id=proposal.proposal_id,
                expected_source_event_version=1,
            ),
            principal=_principal(),
            occurred_at=NOW,
        )
