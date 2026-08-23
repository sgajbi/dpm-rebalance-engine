from __future__ import annotations

from typing import Annotated

from fastapi import Header

from src.api.proposals.principal import (
    ProposalPrincipalContext,
    ProposalPrincipalErrors,
    ProposalPrincipalHeaders,
    resolve_proposal_principal,
)
from src.core.advisory_copilot.review_authority import (
    COPILOT_REVIEW_AUTHORIZED_ROLES,
    COPILOT_REVIEW_CAPABILITY,
    CopilotReviewPrincipal,
)

COPILOT_REVIEW_PRINCIPAL_REQUIRED = "COPILOT_REVIEW_PRINCIPAL_REQUIRED"
COPILOT_REVIEW_PRINCIPAL_INVALID = "COPILOT_REVIEW_PRINCIPAL_INVALID"
COPILOT_REVIEW_ROLE_NOT_AUTHORIZED = "COPILOT_REVIEW_ROLE_NOT_AUTHORIZED"
COPILOT_REVIEW_CAPABILITY_REQUIRED = "COPILOT_REVIEW_CAPABILITY_REQUIRED"

_PRINCIPAL_ERRORS = ProposalPrincipalErrors(
    required=COPILOT_REVIEW_PRINCIPAL_REQUIRED,
    invalid=COPILOT_REVIEW_PRINCIPAL_INVALID,
    role_not_authorized=COPILOT_REVIEW_ROLE_NOT_AUTHORIZED,
    capability_required=COPILOT_REVIEW_CAPABILITY_REQUIRED,
)


def require_advisory_copilot_review_principal(
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_role: Annotated[str | None, Header(alias="X-Role")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_legal_entity_code: Annotated[str | None, Header(alias="X-Legal-Entity-Code")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    x_service_identity: Annotated[str | None, Header(alias="X-Service-Identity")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_capabilities: Annotated[str | None, Header(alias="X-Capabilities")] = None,
    x_principal_status: Annotated[str | None, Header(alias="X-Principal-Status")] = None,
    x_authorized_proposal_id: Annotated[
        str | None, Header(alias="X-Authorized-Proposal-Id")
    ] = None,
    x_authorized_portfolio_id: Annotated[
        str | None, Header(alias="X-Authorized-Portfolio-Id")
    ] = None,
) -> CopilotReviewPrincipal:
    return resolve_proposal_principal(
        required_capability=COPILOT_REVIEW_CAPABILITY,
        authorized_roles=COPILOT_REVIEW_AUTHORIZED_ROLES,
        errors=_PRINCIPAL_ERRORS,
        principal_factory=_build_copilot_review_principal,
        headers=ProposalPrincipalHeaders(
            actor_id=x_actor_id,
            role=x_role,
            tenant_id=x_tenant_id,
            legal_entity_code=x_legal_entity_code,
            correlation_id=x_correlation_id,
            service_identity=x_service_identity,
            authorization=authorization,
            capabilities=x_capabilities,
            principal_status=x_principal_status,
            authorized_proposal_id=x_authorized_proposal_id,
            authorized_portfolio_id=x_authorized_portfolio_id,
        ),
    )


def _build_copilot_review_principal(
    context: ProposalPrincipalContext,
) -> CopilotReviewPrincipal:
    return CopilotReviewPrincipal(
        actor_id=context.actor_id,
        role=context.role,
        tenant_id=context.tenant_id,
        legal_entity_code=context.legal_entity_code,
        correlation_id=context.correlation_id,
        service_identity=context.service_identity,
        capabilities=context.capabilities,
        authorized_proposal_id=context.authorized_proposal_id,
        authorized_portfolio_id=context.authorized_portfolio_id,
    )


__all__ = [
    "COPILOT_REVIEW_CAPABILITY_REQUIRED",
    "COPILOT_REVIEW_PRINCIPAL_INVALID",
    "COPILOT_REVIEW_PRINCIPAL_REQUIRED",
    "COPILOT_REVIEW_ROLE_NOT_AUTHORIZED",
    "require_advisory_copilot_review_principal",
]
