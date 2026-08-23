from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, Any, NoReturn

from fastapi import Header, status

from src.api.proposals.errors import raise_policy_control_http_exception
from src.api.proposals.principal import (
    ProposalPrincipalContext,
    ProposalPrincipalErrors,
    ProposalPrincipalHeaders,
    resolve_proposal_principal,
)

POLICY_PACK_VALIDATE_CAPABILITY = "advisory.policy_pack.validate"
POLICY_PACK_ACTIVATE_CAPABILITY = "advisory.policy_pack.activate"
POLICY_EVALUATION_FINALIZE_CAPABILITY = "advisory.policy_evaluation.finalize"
POLICY_EVALUATION_REVIEW_EVENT_CAPABILITY = "advisory.policy_evaluation.review_event"
POLICY_EVALUATION_SIGN_OFF_CAPABILITY = "advisory.policy_evaluation.sign_off"
POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY = "advisory.policy_evaluation.report_package"
POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY = "advisory.policy_evaluation.ai_evidence"

POLICY_STEWARD_ROLE = "POLICY_STEWARD"
POLICY_CHECKER_ROLE = "POLICY_CHECKER"
ADVISOR_ROLE = "ADVISOR"
COMPLIANCE_REVIEWER_ROLE = "COMPLIANCE_REVIEWER"

POLICY_CONTROL_PRINCIPAL_REQUIRED = "POLICY_CONTROL_PRINCIPAL_REQUIRED"
POLICY_CONTROL_PRINCIPAL_INVALID = "POLICY_CONTROL_PRINCIPAL_INVALID"
POLICY_CONTROL_ROLE_NOT_AUTHORIZED = "POLICY_CONTROL_ROLE_NOT_AUTHORIZED"
POLICY_CONTROL_CAPABILITY_REQUIRED = "POLICY_CONTROL_CAPABILITY_REQUIRED"
POLICY_CONTROL_ACTOR_MISMATCH = "POLICY_CONTROL_ACTOR_MISMATCH"
POLICY_CONTROL_SCOPE_REQUIRED = "POLICY_CONTROL_SCOPE_REQUIRED"
POLICY_CONTROL_SCOPE_FORBIDDEN = "POLICY_CONTROL_SCOPE_FORBIDDEN"

_PRINCIPAL_ERRORS = ProposalPrincipalErrors(
    required=POLICY_CONTROL_PRINCIPAL_REQUIRED,
    invalid=POLICY_CONTROL_PRINCIPAL_INVALID,
    role_not_authorized=POLICY_CONTROL_ROLE_NOT_AUTHORIZED,
    capability_required=POLICY_CONTROL_CAPABILITY_REQUIRED,
)


@dataclass(frozen=True)
class PolicyControlPrincipal:
    actor_id: str
    role: str
    tenant_id: str
    legal_entity_code: str
    correlation_id: str
    service_identity: str
    capabilities: frozenset[str]
    authorized_proposal_id: str | None = None
    authorized_portfolio_id: str | None = None

    def audit_metadata(self, *, capability: str) -> dict[str, str]:
        return {
            "subject": self.actor_id,
            "role": self.role,
            "tenant_id": self.tenant_id,
            "legal_entity_code": self.legal_entity_code,
            "correlation_id": self.correlation_id,
            "service_identity": self.service_identity,
            "capability": capability,
        }


def resolve_policy_control_principal(
    *,
    required_capability: str,
    authorized_roles: Iterable[str],
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
) -> PolicyControlPrincipal:
    return resolve_proposal_principal(
        required_capability=required_capability,
        authorized_roles=authorized_roles,
        errors=_PRINCIPAL_ERRORS,
        principal_factory=_build_policy_control_principal,
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


def require_policy_pack_validation_principal(
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_role: Annotated[str | None, Header(alias="X-Role")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_legal_entity_code: Annotated[str | None, Header(alias="X-Legal-Entity-Code")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    x_service_identity: Annotated[str | None, Header(alias="X-Service-Identity")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_capabilities: Annotated[str | None, Header(alias="X-Capabilities")] = None,
    x_principal_status: Annotated[str | None, Header(alias="X-Principal-Status")] = None,
) -> PolicyControlPrincipal:
    return resolve_policy_control_principal(
        required_capability=POLICY_PACK_VALIDATE_CAPABILITY,
        authorized_roles=(POLICY_STEWARD_ROLE,),
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


def require_policy_pack_activation_principal(
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_role: Annotated[str | None, Header(alias="X-Role")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_legal_entity_code: Annotated[str | None, Header(alias="X-Legal-Entity-Code")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    x_service_identity: Annotated[str | None, Header(alias="X-Service-Identity")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_capabilities: Annotated[str | None, Header(alias="X-Capabilities")] = None,
    x_principal_status: Annotated[str | None, Header(alias="X-Principal-Status")] = None,
) -> PolicyControlPrincipal:
    return resolve_policy_control_principal(
        required_capability=POLICY_PACK_ACTIVATE_CAPABILITY,
        authorized_roles=(POLICY_CHECKER_ROLE,),
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


def require_policy_evaluation_finalize_principal(
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
) -> PolicyControlPrincipal:
    return resolve_policy_control_principal(
        required_capability=POLICY_EVALUATION_FINALIZE_CAPABILITY,
        authorized_roles=(ADVISOR_ROLE,),
        x_actor_id=x_actor_id,
        x_role=x_role,
        x_tenant_id=x_tenant_id,
        x_legal_entity_code=x_legal_entity_code,
        x_correlation_id=x_correlation_id,
        x_service_identity=x_service_identity,
        authorization=authorization,
        x_capabilities=x_capabilities,
        x_principal_status=x_principal_status,
        x_authorized_proposal_id=x_authorized_proposal_id,
        x_authorized_portfolio_id=x_authorized_portfolio_id,
    )


def require_policy_evaluation_review_principal(
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
) -> PolicyControlPrincipal:
    return resolve_policy_control_principal(
        required_capability=POLICY_EVALUATION_REVIEW_EVENT_CAPABILITY,
        authorized_roles=(COMPLIANCE_REVIEWER_ROLE, POLICY_STEWARD_ROLE),
        x_actor_id=x_actor_id,
        x_role=x_role,
        x_tenant_id=x_tenant_id,
        x_legal_entity_code=x_legal_entity_code,
        x_correlation_id=x_correlation_id,
        x_service_identity=x_service_identity,
        authorization=authorization,
        x_capabilities=x_capabilities,
        x_principal_status=x_principal_status,
        x_authorized_proposal_id=x_authorized_proposal_id,
        x_authorized_portfolio_id=x_authorized_portfolio_id,
    )


def require_policy_evaluation_sign_off_principal(
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
) -> PolicyControlPrincipal:
    return resolve_policy_control_principal(
        required_capability=POLICY_EVALUATION_SIGN_OFF_CAPABILITY,
        authorized_roles=(POLICY_CHECKER_ROLE,),
        x_actor_id=x_actor_id,
        x_role=x_role,
        x_tenant_id=x_tenant_id,
        x_legal_entity_code=x_legal_entity_code,
        x_correlation_id=x_correlation_id,
        x_service_identity=x_service_identity,
        authorization=authorization,
        x_capabilities=x_capabilities,
        x_principal_status=x_principal_status,
        x_authorized_proposal_id=x_authorized_proposal_id,
        x_authorized_portfolio_id=x_authorized_portfolio_id,
    )


def require_policy_evaluation_report_package_principal(
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
) -> PolicyControlPrincipal:
    return resolve_policy_control_principal(
        required_capability=POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY,
        authorized_roles=(POLICY_CHECKER_ROLE,),
        x_actor_id=x_actor_id,
        x_role=x_role,
        x_tenant_id=x_tenant_id,
        x_legal_entity_code=x_legal_entity_code,
        x_correlation_id=x_correlation_id,
        x_service_identity=x_service_identity,
        authorization=authorization,
        x_capabilities=x_capabilities,
        x_principal_status=x_principal_status,
        x_authorized_proposal_id=x_authorized_proposal_id,
        x_authorized_portfolio_id=x_authorized_portfolio_id,
    )


def require_policy_evaluation_ai_evidence_principal(
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
) -> PolicyControlPrincipal:
    return resolve_policy_control_principal(
        required_capability=POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
        authorized_roles=(POLICY_CHECKER_ROLE, COMPLIANCE_REVIEWER_ROLE),
        x_actor_id=x_actor_id,
        x_role=x_role,
        x_tenant_id=x_tenant_id,
        x_legal_entity_code=x_legal_entity_code,
        x_correlation_id=x_correlation_id,
        x_service_identity=x_service_identity,
        authorization=authorization,
        x_capabilities=x_capabilities,
        x_principal_status=x_principal_status,
        x_authorized_proposal_id=x_authorized_proposal_id,
        x_authorized_portfolio_id=x_authorized_portfolio_id,
    )


def bind_policy_control_actor(submitted_actor: str, principal: PolicyControlPrincipal) -> str:
    if submitted_actor.strip() != principal.actor_id:
        _raise_authz(POLICY_CONTROL_ACTOR_MISMATCH)
    return principal.actor_id


def policy_control_audit_reason(
    reason: dict[str, Any],
    *,
    principal: PolicyControlPrincipal,
    capability: str,
) -> dict[str, Any]:
    return {
        **reason,
        "trusted_principal": principal.audit_metadata(capability=capability),
    }


def assert_policy_pack_scope(
    *,
    principal: PolicyControlPrincipal,
    policy_pack: Any,
) -> None:
    legal_entities = _upper_set(policy_pack.applicability.get("legal_entity_scope", []))
    if legal_entities and principal.legal_entity_code not in legal_entities:
        _raise_authz(POLICY_CONTROL_SCOPE_FORBIDDEN)


def assert_policy_evaluation_create_scope(
    *,
    principal: PolicyControlPrincipal,
    proposal_id: str,
    evidence_bundle: dict[str, Any],
) -> None:
    _require_scope(principal.authorized_proposal_id)
    _require_scope(principal.authorized_portfolio_id)
    if principal.authorized_proposal_id != proposal_id:
        _raise_authz(POLICY_CONTROL_SCOPE_FORBIDDEN)
    source_portfolio_id = _portfolio_id_from_evidence(evidence_bundle)
    if source_portfolio_id is not None and source_portfolio_id != principal.authorized_portfolio_id:
        _raise_authz(POLICY_CONTROL_SCOPE_FORBIDDEN)
    _assert_legal_entity_scope(
        principal=principal,
        legal_entity_code=_legal_entity_from_evidence(evidence_bundle),
    )
    evidence_tenant = _tenant_from_evidence(evidence_bundle)
    if evidence_tenant is not None and evidence_tenant != principal.tenant_id:
        _raise_authz(POLICY_CONTROL_SCOPE_FORBIDDEN)


def assert_policy_evaluation_record_scope(
    *,
    principal: PolicyControlPrincipal,
    record: Any,
    lineage: Any | None = None,
) -> None:
    _require_scope(principal.authorized_proposal_id)
    _require_scope(principal.authorized_portfolio_id)
    if principal.authorized_proposal_id != record.proposal_id:
        _raise_authz(POLICY_CONTROL_SCOPE_FORBIDDEN)
    if principal.authorized_portfolio_id != record.portfolio_id:
        _raise_authz(POLICY_CONTROL_SCOPE_FORBIDDEN)
    _assert_legal_entity_scope(
        principal=principal,
        legal_entity_code=_legal_entity_from_record(record),
    )
    tenant_id = _tenant_from_lineage(lineage)
    if tenant_id is not None and tenant_id != principal.tenant_id:
        _raise_authz(POLICY_CONTROL_SCOPE_FORBIDDEN)


def _build_policy_control_principal(
    context: ProposalPrincipalContext,
) -> PolicyControlPrincipal:
    return PolicyControlPrincipal(
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


def _optional_header(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _require_scope(value: str | None) -> None:
    if value is None:
        _raise_authz(POLICY_CONTROL_SCOPE_REQUIRED)


def _portfolio_id_from_evidence(evidence_bundle: dict[str, Any]) -> str | None:
    portfolio = evidence_bundle.get("inputs", {}).get("portfolio_snapshot", {})
    return _optional_header(portfolio.get("portfolio_id"))


def _legal_entity_from_evidence(evidence_bundle: dict[str, Any]) -> str | None:
    context = evidence_bundle.get("context_resolution", {}).get("advisory_policy_context", {})
    return _optional_header(context.get("legal_entity_code"))


def _tenant_from_evidence(evidence_bundle: dict[str, Any]) -> str | None:
    context = evidence_bundle.get("context_resolution", {}).get("advisory_policy_context", {})
    return _optional_header(context.get("tenant_id"))


def _legal_entity_from_record(record: Any) -> str | None:
    selectors = record.evaluation_json.get("applicability", {}).get("matched_selectors", {})
    return _optional_header(selectors.get("legal_entity_code"))


def _tenant_from_lineage(lineage: Any | None) -> str | None:
    if lineage is None:
        return None
    for event in lineage.audit_events:
        metadata = event.reason_json.get("trusted_principal")
        if isinstance(metadata, dict):
            return _optional_header(metadata.get("tenant_id"))
    return None


def _assert_legal_entity_scope(
    *,
    principal: PolicyControlPrincipal,
    legal_entity_code: str | None,
) -> None:
    if legal_entity_code is None:
        return
    if legal_entity_code.upper() != principal.legal_entity_code:
        _raise_authz(POLICY_CONTROL_SCOPE_FORBIDDEN)


def _upper_set(values: Iterable[Any]) -> set[str]:
    return {str(value).strip().upper() for value in values if str(value).strip()}


def _raise_authn(detail: str) -> NoReturn:
    raise_policy_control_http_exception(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
    raise AssertionError("unreachable")  # pragma: no cover


def _raise_authz(detail: str) -> NoReturn:
    raise_policy_control_http_exception(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    raise AssertionError("unreachable")  # pragma: no cover


__all__ = [
    "ADVISOR_ROLE",
    "COMPLIANCE_REVIEWER_ROLE",
    "POLICY_CHECKER_ROLE",
    "POLICY_CONTROL_ACTOR_MISMATCH",
    "POLICY_CONTROL_CAPABILITY_REQUIRED",
    "POLICY_CONTROL_PRINCIPAL_INVALID",
    "POLICY_CONTROL_PRINCIPAL_REQUIRED",
    "POLICY_CONTROL_ROLE_NOT_AUTHORIZED",
    "POLICY_CONTROL_SCOPE_FORBIDDEN",
    "POLICY_CONTROL_SCOPE_REQUIRED",
    "POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY",
    "POLICY_EVALUATION_FINALIZE_CAPABILITY",
    "POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY",
    "POLICY_EVALUATION_REVIEW_EVENT_CAPABILITY",
    "POLICY_EVALUATION_SIGN_OFF_CAPABILITY",
    "POLICY_PACK_ACTIVATE_CAPABILITY",
    "POLICY_PACK_VALIDATE_CAPABILITY",
    "POLICY_STEWARD_ROLE",
    "PolicyControlPrincipal",
    "assert_policy_evaluation_create_scope",
    "assert_policy_evaluation_record_scope",
    "assert_policy_pack_scope",
    "bind_policy_control_actor",
    "policy_control_audit_reason",
    "require_policy_evaluation_ai_evidence_principal",
    "require_policy_evaluation_finalize_principal",
    "require_policy_evaluation_report_package_principal",
    "require_policy_evaluation_review_principal",
    "require_policy_evaluation_sign_off_principal",
    "require_policy_pack_activation_principal",
    "require_policy_pack_validation_principal",
]
