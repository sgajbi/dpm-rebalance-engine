from __future__ import annotations

from typing import Annotated

from fastapi import Header

from src.api.proposals.principal import (
    ProposalPrincipalContext,
    ProposalPrincipalErrors,
    ProposalPrincipalHeaders,
    resolve_proposal_principal,
)
from src.core.proposals.idea_intake_authority import (
    IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY,
    IDEA_PROPOSAL_INTAKE_AUTHORIZED_ROLES,
    IdeaProposalIntakePrincipal,
)

IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED = "IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED"
IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID = "IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID"
IDEA_PROPOSAL_INTAKE_ROLE_NOT_AUTHORIZED = "IDEA_PROPOSAL_INTAKE_ROLE_NOT_AUTHORIZED"
IDEA_PROPOSAL_INTAKE_CAPABILITY_REQUIRED = "IDEA_PROPOSAL_INTAKE_CAPABILITY_REQUIRED"

_PRINCIPAL_ERRORS = ProposalPrincipalErrors(
    required=IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED,
    invalid=IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID,
    role_not_authorized=IDEA_PROPOSAL_INTAKE_ROLE_NOT_AUTHORIZED,
    capability_required=IDEA_PROPOSAL_INTAKE_CAPABILITY_REQUIRED,
)


def require_idea_proposal_intake_principal(
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_role: Annotated[str | None, Header(alias="X-Role")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_legal_entity_code: Annotated[str | None, Header(alias="X-Legal-Entity-Code")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    x_service_identity: Annotated[str | None, Header(alias="X-Service-Identity")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_capabilities: Annotated[str | None, Header(alias="X-Capabilities")] = None,
    x_principal_status: Annotated[str | None, Header(alias="X-Principal-Status")] = None,
) -> IdeaProposalIntakePrincipal:
    return resolve_proposal_principal(
        required_capability=IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY,
        authorized_roles=IDEA_PROPOSAL_INTAKE_AUTHORIZED_ROLES,
        errors=_PRINCIPAL_ERRORS,
        principal_factory=_build_idea_proposal_intake_principal,
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
        ),
        correlation_id_fallback="route-correlation-pending",
    )


def _build_idea_proposal_intake_principal(
    context: ProposalPrincipalContext,
) -> IdeaProposalIntakePrincipal:
    return IdeaProposalIntakePrincipal(
        actor_id=context.actor_id,
        role=context.role,
        tenant_id=context.tenant_id,
        legal_entity_code=context.legal_entity_code,
        correlation_id=context.correlation_id,
        service_identity=context.service_identity,
        capabilities=context.capabilities,
    )


__all__ = [
    "IDEA_PROPOSAL_INTAKE_CAPABILITY_REQUIRED",
    "IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID",
    "IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED",
    "IDEA_PROPOSAL_INTAKE_ROLE_NOT_AUTHORIZED",
    "require_idea_proposal_intake_principal",
]
