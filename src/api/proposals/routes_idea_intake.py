from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Path, Request, status

import src.api.proposals.router as shared
from src.api.observability import correlation_id_var
from src.api.proposals.errors import reject_unexpected_query_params, run_proposal_operation
from src.api.proposals.idea_intake_parameters import (
    IdeaProposalIntakeCorrelationIdHeader,
    IdeaProposalIntakeIdempotencyKeyHeader,
    IdeaProposalRealizationPortfolioHeader,
)
from src.api.proposals.idea_intake_principal import (
    require_idea_proposal_intake_principal,
    require_idea_proposal_realization_reader,
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
from src.core.proposals.idea_realization_read_model import (
    IdeaProposalRealizationHistoryResponse,
    load_idea_proposal_realization_history,
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
    intake_id: Annotated[
        str,
        Path(min_length=1, max_length=160, examples=["ipi_7a1d2b3c4d5e"]),
    ],
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


def _resolved_intake_correlation_id(correlation_id: str | None) -> str:
    return cast(
        str,
        normalize_optional_correlation_id(correlation_id)
        or correlation_id_var.get()
        or resolve_correlation_id(None),
    )
