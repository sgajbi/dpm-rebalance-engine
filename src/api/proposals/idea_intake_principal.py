from __future__ import annotations

from typing import cast

from src.api.proposals.idea_intake_parameters import (
    IdeaProposalActorHeader,
    IdeaProposalAuthorizationHeader,
    IdeaProposalAuthorizedPortfolioHeader,
    IdeaProposalCapabilitiesHeader,
    IdeaProposalLegalEntityHeader,
    IdeaProposalPrincipalCorrelationHeader,
    IdeaProposalPrincipalStatusHeader,
    IdeaProposalRoleHeader,
    IdeaProposalServiceIdentityHeader,
    IdeaProposalTenantHeader,
)
from src.api.proposals.principal import (
    ProposalPrincipalContext,
    ProposalPrincipalErrors,
    ProposalPrincipalHeaders,
    resolve_proposal_principal,
)
from src.core.proposals.idea_intake_authority import (
    IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY,
    IDEA_PROPOSAL_INTAKE_AUTHORIZED_ROLES,
    IDEA_PROPOSAL_REALIZATION_READ_CAPABILITY,
    IdeaProposalIntakePrincipal,
)

IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED = "IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED"
IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID = "IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID"
IDEA_PROPOSAL_INTAKE_ROLE_NOT_AUTHORIZED = "IDEA_PROPOSAL_INTAKE_ROLE_NOT_AUTHORIZED"
IDEA_PROPOSAL_INTAKE_CAPABILITY_REQUIRED = "IDEA_PROPOSAL_INTAKE_CAPABILITY_REQUIRED"
IDEA_PROPOSAL_REALIZATION_CAPABILITY_REQUIRED = "IDEA_PROPOSAL_REALIZATION_CAPABILITY_REQUIRED"

_PRINCIPAL_ERRORS = ProposalPrincipalErrors(
    required=IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED,
    invalid=IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID,
    role_not_authorized=IDEA_PROPOSAL_INTAKE_ROLE_NOT_AUTHORIZED,
    capability_required=IDEA_PROPOSAL_INTAKE_CAPABILITY_REQUIRED,
)
_REALIZATION_READER_ERRORS = ProposalPrincipalErrors(
    required=IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED,
    invalid=IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID,
    role_not_authorized=IDEA_PROPOSAL_INTAKE_ROLE_NOT_AUTHORIZED,
    capability_required=IDEA_PROPOSAL_REALIZATION_CAPABILITY_REQUIRED,
)


class _IdeaProposalPrincipalDependency:
    def __init__(self, *, required_capability: str, errors: ProposalPrincipalErrors) -> None:
        self._required_capability = required_capability
        self._errors = errors

    def __call__(
        self,
        x_actor_id: IdeaProposalActorHeader = None,
        x_role: IdeaProposalRoleHeader = None,
        x_tenant_id: IdeaProposalTenantHeader = None,
        x_legal_entity_code: IdeaProposalLegalEntityHeader = None,
        x_correlation_id: IdeaProposalPrincipalCorrelationHeader = None,
        x_service_identity: IdeaProposalServiceIdentityHeader = None,
        authorization: IdeaProposalAuthorizationHeader = None,
        x_capabilities: IdeaProposalCapabilitiesHeader = None,
        x_principal_status: IdeaProposalPrincipalStatusHeader = None,
    ) -> IdeaProposalIntakePrincipal:
        return _resolve_idea_proposal_principal(
            required_capability=self._required_capability,
            errors=self._errors,
            x_actor_id=x_actor_id,
            x_role=x_role,
            x_tenant_id=x_tenant_id,
            x_legal_entity_code=x_legal_entity_code,
            x_correlation_id=x_correlation_id,
            x_service_identity=x_service_identity,
            authorization=authorization,
            x_capabilities=x_capabilities,
            x_principal_status=x_principal_status,
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
        authorized_portfolio_id=context.authorized_portfolio_id,
    )


require_idea_proposal_intake_principal = _IdeaProposalPrincipalDependency(
    required_capability=IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY,
    errors=_PRINCIPAL_ERRORS,
)


def require_idea_proposal_realization_reader(
    x_actor_id: IdeaProposalActorHeader = None,
    x_role: IdeaProposalRoleHeader = None,
    x_tenant_id: IdeaProposalTenantHeader = None,
    x_legal_entity_code: IdeaProposalLegalEntityHeader = None,
    x_correlation_id: IdeaProposalPrincipalCorrelationHeader = None,
    x_service_identity: IdeaProposalServiceIdentityHeader = None,
    authorization: IdeaProposalAuthorizationHeader = None,
    x_capabilities: IdeaProposalCapabilitiesHeader = None,
    x_principal_status: IdeaProposalPrincipalStatusHeader = None,
    x_authorized_portfolio_id: IdeaProposalAuthorizedPortfolioHeader = None,
) -> IdeaProposalIntakePrincipal:
    return _resolve_idea_proposal_principal(
        required_capability=IDEA_PROPOSAL_REALIZATION_READ_CAPABILITY,
        errors=_REALIZATION_READER_ERRORS,
        x_actor_id=x_actor_id,
        x_role=x_role,
        x_tenant_id=x_tenant_id,
        x_legal_entity_code=x_legal_entity_code,
        x_correlation_id=x_correlation_id,
        x_service_identity=x_service_identity,
        authorization=authorization,
        x_capabilities=x_capabilities,
        x_principal_status=x_principal_status,
        x_authorized_portfolio_id=x_authorized_portfolio_id,
    )


def _resolve_idea_proposal_principal(
    *,
    required_capability: str,
    errors: ProposalPrincipalErrors,
    x_actor_id: str | None,
    x_role: str | None,
    x_tenant_id: str | None,
    x_legal_entity_code: str | None,
    x_correlation_id: str | None,
    x_service_identity: str | None,
    authorization: str | None,
    x_capabilities: str | None,
    x_principal_status: str | None,
    x_authorized_portfolio_id: str | None = None,
) -> IdeaProposalIntakePrincipal:
    return cast(
        IdeaProposalIntakePrincipal,
        resolve_proposal_principal(
            required_capability=required_capability,
            authorized_roles=IDEA_PROPOSAL_INTAKE_AUTHORIZED_ROLES,
            errors=errors,
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
                authorized_portfolio_id=x_authorized_portfolio_id,
            ),
            correlation_id_fallback="route-correlation-pending",
        ),
    )


__all__ = [
    "IDEA_PROPOSAL_INTAKE_CAPABILITY_REQUIRED",
    "IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID",
    "IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED",
    "IDEA_PROPOSAL_INTAKE_ROLE_NOT_AUTHORIZED",
    "IDEA_PROPOSAL_REALIZATION_CAPABILITY_REQUIRED",
    "require_idea_proposal_intake_principal",
    "require_idea_proposal_realization_reader",
]
