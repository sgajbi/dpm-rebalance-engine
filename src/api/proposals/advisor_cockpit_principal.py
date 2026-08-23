from __future__ import annotations

from typing import Annotated

from fastapi import Header

from src.api.proposals.principal import (
    ProposalPrincipalContext,
    ProposalPrincipalErrors,
    ProposalPrincipalHeaders,
    resolve_proposal_principal,
)
from src.core.advisor_cockpit.caller_authority import (
    ADVISOR_COCKPIT_ACKNOWLEDGE_CAPABILITY,
    ADVISOR_COCKPIT_AUTHORIZED_ROLES,
    ADVISOR_COCKPIT_READ_CAPABILITY,
    AdvisorCockpitPrincipal,
)

ADVISOR_COCKPIT_PRINCIPAL_REQUIRED = "ADVISOR_COCKPIT_PRINCIPAL_REQUIRED"
ADVISOR_COCKPIT_PRINCIPAL_INVALID = "ADVISOR_COCKPIT_PRINCIPAL_INVALID"
ADVISOR_COCKPIT_ROLE_NOT_AUTHORIZED = "ADVISOR_COCKPIT_ROLE_NOT_AUTHORIZED"
ADVISOR_COCKPIT_CAPABILITY_REQUIRED = "ADVISOR_COCKPIT_CAPABILITY_REQUIRED"

_PRINCIPAL_ERRORS = ProposalPrincipalErrors(
    required=ADVISOR_COCKPIT_PRINCIPAL_REQUIRED,
    invalid=ADVISOR_COCKPIT_PRINCIPAL_INVALID,
    role_not_authorized=ADVISOR_COCKPIT_ROLE_NOT_AUTHORIZED,
    capability_required=ADVISOR_COCKPIT_CAPABILITY_REQUIRED,
)


def require_advisor_cockpit_read_principal(
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_role: Annotated[str | None, Header(alias="X-Role")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_legal_entity_code: Annotated[str | None, Header(alias="X-Legal-Entity-Code")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    x_service_identity: Annotated[str | None, Header(alias="X-Service-Identity")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_capabilities: Annotated[str | None, Header(alias="X-Capabilities")] = None,
    x_principal_status: Annotated[str | None, Header(alias="X-Principal-Status")] = None,
    x_authorized_advisor_id: Annotated[str | None, Header(alias="X-Authorized-Advisor-Id")] = None,
    x_authorized_portfolio_id: Annotated[
        str | None, Header(alias="X-Authorized-Portfolio-Id")
    ] = None,
) -> AdvisorCockpitPrincipal:
    return resolve_advisor_cockpit_principal(
        required_capability=ADVISOR_COCKPIT_READ_CAPABILITY,
        x_actor_id=x_actor_id,
        x_role=x_role,
        x_tenant_id=x_tenant_id,
        x_legal_entity_code=x_legal_entity_code,
        x_correlation_id=x_correlation_id,
        x_service_identity=x_service_identity,
        authorization=authorization,
        x_capabilities=x_capabilities,
        x_principal_status=x_principal_status,
        x_authorized_advisor_id=x_authorized_advisor_id,
        x_authorized_portfolio_id=x_authorized_portfolio_id,
    )


def require_advisor_cockpit_acknowledgement_principal(
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_role: Annotated[str | None, Header(alias="X-Role")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_legal_entity_code: Annotated[str | None, Header(alias="X-Legal-Entity-Code")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    x_service_identity: Annotated[str | None, Header(alias="X-Service-Identity")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_capabilities: Annotated[str | None, Header(alias="X-Capabilities")] = None,
    x_principal_status: Annotated[str | None, Header(alias="X-Principal-Status")] = None,
    x_authorized_advisor_id: Annotated[str | None, Header(alias="X-Authorized-Advisor-Id")] = None,
    x_authorized_portfolio_id: Annotated[
        str | None, Header(alias="X-Authorized-Portfolio-Id")
    ] = None,
) -> AdvisorCockpitPrincipal:
    return resolve_advisor_cockpit_principal(
        required_capability=ADVISOR_COCKPIT_ACKNOWLEDGE_CAPABILITY,
        x_actor_id=x_actor_id,
        x_role=x_role,
        x_tenant_id=x_tenant_id,
        x_legal_entity_code=x_legal_entity_code,
        x_correlation_id=x_correlation_id,
        x_service_identity=x_service_identity,
        authorization=authorization,
        x_capabilities=x_capabilities,
        x_principal_status=x_principal_status,
        x_authorized_advisor_id=x_authorized_advisor_id,
        x_authorized_portfolio_id=x_authorized_portfolio_id,
    )


def resolve_advisor_cockpit_principal(
    *,
    required_capability: str,
    x_actor_id: str | None,
    x_role: str | None,
    x_tenant_id: str | None,
    x_legal_entity_code: str | None,
    x_correlation_id: str | None,
    x_service_identity: str | None,
    authorization: str | None,
    x_capabilities: str | None,
    x_principal_status: str | None,
    x_authorized_advisor_id: str | None,
    x_authorized_portfolio_id: str | None,
) -> AdvisorCockpitPrincipal:
    return resolve_proposal_principal(
        required_capability=required_capability,
        authorized_roles=ADVISOR_COCKPIT_AUTHORIZED_ROLES,
        errors=_PRINCIPAL_ERRORS,
        principal_factory=_build_advisor_cockpit_principal,
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
            authorized_advisor_id=x_authorized_advisor_id,
            authorized_portfolio_id=x_authorized_portfolio_id,
        ),
    )


def _build_advisor_cockpit_principal(
    context: ProposalPrincipalContext,
) -> AdvisorCockpitPrincipal:
    return AdvisorCockpitPrincipal(
        actor_id=context.actor_id,
        role=context.role,
        tenant_id=context.tenant_id,
        legal_entity_code=context.legal_entity_code,
        correlation_id=context.correlation_id,
        service_identity=context.service_identity,
        capabilities=context.capabilities,
        authorized_advisor_id=context.authorized_advisor_id,
        authorized_portfolio_id=context.authorized_portfolio_id,
    )


__all__ = [
    "ADVISOR_COCKPIT_CAPABILITY_REQUIRED",
    "ADVISOR_COCKPIT_PRINCIPAL_INVALID",
    "ADVISOR_COCKPIT_PRINCIPAL_REQUIRED",
    "ADVISOR_COCKPIT_ROLE_NOT_AUTHORIZED",
    "require_advisor_cockpit_acknowledgement_principal",
    "require_advisor_cockpit_read_principal",
]
