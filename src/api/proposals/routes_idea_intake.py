from __future__ import annotations

from typing import cast

from fastapi import Depends, Request, status

import src.api.proposals.router as shared
from src.api.observability import correlation_id_var
from src.api.proposals.errors import reject_unexpected_query_params, run_proposal_operation
from src.api.proposals.feature_gates import assert_idea_proposal_reconciliation_enabled
from src.api.proposals.idea_intake_parameters import (
    IdeaProposalConversionIntentIdPath,
    IdeaProposalIntakeCorrelationIdHeader,
    IdeaProposalIntakeIdempotencyKeyHeader,
    IdeaProposalIntakeIdPath,
    IdeaProposalRealizationPortfolioHeader,
)
from src.api.proposals.idea_intake_principal import (
    require_idea_proposal_intake_principal,
    require_idea_proposal_realization_reader,
    require_idea_proposal_realization_writer,
)
from src.api.proposals.idea_intake_responses import IDEA_PROPOSAL_INTAKE_RESPONSES
from src.core.proposals.correlation import normalize_optional_correlation_id, resolve_correlation_id
from src.core.proposals.idea_intake_authority import IdeaProposalIntakePrincipal
from src.core.proposals.idea_proposal_intake import (
    IDEA_PROPOSAL_INTAKE_REQUEST_EXAMPLE,
    IdeaProposalIntakeRequest,
    IdeaProposalIntakeResponse,
    process_idea_proposal_intake,
)
from src.core.proposals.idea_realization_commands import (
    IdeaProposalReconciliationRequest,
    reconcile_idea_proposal_realization,
)
from src.core.proposals.idea_realization_read_model import (
    IdeaProposalRealizationHistoryResponse,
    load_idea_proposal_realization_history,
    load_idea_proposal_realization_history_by_conversion_intent,
)
from src.core.proposals.repository import ProposalRepository

_IDEA_PROPOSAL_INTAKE_DESCRIPTION = (
    "Accepts a source-safe lotus-idea conversion-intent handoff for advisory-side review. "
    "This route proves an Advise-owned executable intake receipt with trusted caller scope, "
    "idempotent replay, and bounded accepted/rejected outcomes. It does not grant suitability, "
    "create an advisory proposal record, create orders, authorize client publication, or promote "
    "a supported feature."
)


@shared.router.post(
    "/advisory/proposals/idea-intake",
    response_model=IdeaProposalIntakeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Advisory Proposal Lifecycle"],
    summary="Accept lotus-idea Proposal Intake Receipt",
    description=_IDEA_PROPOSAL_INTAKE_DESCRIPTION,
    responses=IDEA_PROPOSAL_INTAKE_RESPONSES,
    openapi_extra={
        "requestBody": {
            "content": {"application/json": {"example": IDEA_PROPOSAL_INTAKE_REQUEST_EXAMPLE}}
        }
    },
)
def accept_idea_proposal_intake(
    request: Request,
    payload: IdeaProposalIntakeRequest,
    idempotency_key: IdeaProposalIntakeIdempotencyKeyHeader,
    correlation_id: IdeaProposalIntakeCorrelationIdHeader = None,
    principal: IdeaProposalIntakePrincipal = Depends(require_idea_proposal_intake_principal),
    repository: ProposalRepository = Depends(shared.get_proposal_repository),
) -> IdeaProposalIntakeResponse:
    shared._assert_lifecycle_enabled()
    reject_unexpected_query_params(request, allowed_params=set())
    resolved_correlation_id = _resolved_intake_correlation_id(correlation_id)
    return cast(
        IdeaProposalIntakeResponse,
        run_proposal_operation(
            lambda: process_idea_proposal_intake(
                payload,
                correlation_id=resolved_correlation_id,
                idempotency_key=idempotency_key,
                principal=principal,
                repository=repository,
            )
        ),
    )


@shared.router.get(
    "/advisory/proposals/idea-intake/by-conversion-intent/{conversion_intent_id}/realization",
    response_model=IdeaProposalRealizationHistoryResponse,
    tags=["Advisory Proposal Lifecycle"],
    summary="Recover Advise-owned Idea realization by conversion intent",
    description=(
        "Returns the canonical Advise-owned realization after a lost intake response, using the "
        "Idea-owned conversion-intent identity and exact trusted scope. This is a read-only "
        "recovery path: it does not replay the intake, create work, infer acceptance from "
        "transport, or grant downstream authority."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Trusted realization reader principal is missing or invalid."
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Principal lacks the realization read capability."
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "No realization exists in the exact trusted scope."
        },
    },
)
def recover_idea_proposal_realization(
    request: Request,
    conversion_intent_id: IdeaProposalConversionIntentIdPath,
    portfolio_id: IdeaProposalRealizationPortfolioHeader,
    principal: IdeaProposalIntakePrincipal = Depends(require_idea_proposal_realization_reader),
    repository: ProposalRepository = Depends(shared.get_proposal_repository),
) -> IdeaProposalRealizationHistoryResponse:
    shared._assert_lifecycle_enabled()
    reject_unexpected_query_params(request, allowed_params=set())
    return cast(
        IdeaProposalRealizationHistoryResponse,
        run_proposal_operation(
            lambda: load_idea_proposal_realization_history_by_conversion_intent(
                repository=repository,
                conversion_intent_id=conversion_intent_id,
                portfolio_id=portfolio_id,
                principal=principal,
            )
        ),
    )


@shared.router.get(
    "/advisory/proposals/idea-intake/{intake_id}/realization",
    response_model=IdeaProposalRealizationHistoryResponse,
    tags=["Advisory Proposal Lifecycle"],
    summary="Read Advise-owned Idea realization outcomes",
    description=(
        "Returns the durable Advise adviser-review work posture and append-only source outcome "
        "history for one Idea intake. Tenant, legal-entity, and producer-authorized portfolio "
        "scope must all match. Intake acceptance remains distinct from proposal creation, "
        "suitability, execution, and client publication."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Trusted realization reader principal is missing or invalid."
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Principal lacks the realization read capability."
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "No realization exists in the exact trusted scope."
        },
    },
)
def read_idea_proposal_realization(
    request: Request,
    intake_id: IdeaProposalIntakeIdPath,
    portfolio_id: IdeaProposalRealizationPortfolioHeader,
    principal: IdeaProposalIntakePrincipal = Depends(require_idea_proposal_realization_reader),
    repository: ProposalRepository = Depends(shared.get_proposal_repository),
) -> IdeaProposalRealizationHistoryResponse:
    shared._assert_lifecycle_enabled()
    reject_unexpected_query_params(request, allowed_params=set())
    return cast(
        IdeaProposalRealizationHistoryResponse,
        run_proposal_operation(
            lambda: load_idea_proposal_realization_history(
                repository=repository,
                intake_id=intake_id,
                portfolio_id=portfolio_id,
                principal=principal,
            )
        ),
    )


@shared.router.post(
    "/advisory/proposals/idea-intake/{intake_id}/realization/proposal-reconciliation",
    response_model=IdeaProposalRealizationHistoryResponse,
    status_code=status.HTTP_200_OK,
    tags=["Advisory Proposal Lifecycle"],
    summary="Link and reconcile an Advise proposal for an Idea realization",
    description=(
        "Links one existing same-portfolio Advise proposal to the durable Idea review work and "
        "appends monotonic Advise-owned outcomes. A terminal outcome is emitted only when the "
        "authoritative proposal lifecycle is REJECTED, CANCELLED, EXPIRED, or EXECUTED. The "
        "EXECUTED mapping closes the advisory realization only; it does not independently prove "
        "orders, fills, settlement, suitability, or client publication."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Trusted realization writer principal is missing or invalid."
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Principal lacks the realization write capability."
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "The scoped realization or same-portfolio proposal was not found."
        },
        status.HTTP_409_CONFLICT: {
            "description": "The expected version or proposal linkage conflicts with current state."
        },
    },
)
def reconcile_idea_proposal(
    request: Request,
    payload: IdeaProposalReconciliationRequest,
    intake_id: IdeaProposalIntakeIdPath,
    portfolio_id: IdeaProposalRealizationPortfolioHeader,
    principal: IdeaProposalIntakePrincipal = Depends(require_idea_proposal_realization_writer),
    repository: ProposalRepository = Depends(shared.get_proposal_repository),
) -> IdeaProposalRealizationHistoryResponse:
    shared._assert_lifecycle_enabled()
    assert_idea_proposal_reconciliation_enabled()
    reject_unexpected_query_params(request, allowed_params=set())
    return cast(
        IdeaProposalRealizationHistoryResponse,
        run_proposal_operation(
            lambda: reconcile_idea_proposal_realization(
                repository=repository,
                intake_id=intake_id,
                portfolio_id=portfolio_id,
                payload=payload,
                principal=principal,
            )
        ),
    )


def _resolved_intake_correlation_id(correlation_id: str | None) -> str:
    return cast(
        str,
        normalize_optional_correlation_id(correlation_id)
        or correlation_id_var.get()
        or resolve_correlation_id(None),
    )
