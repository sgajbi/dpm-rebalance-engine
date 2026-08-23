from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from fastapi import status

from src.api.proposals.errors import raise_proposal_api_http_exception

_PrincipalT = TypeVar("_PrincipalT")


@dataclass(frozen=True)
class ProposalPrincipalErrors:
    required: str
    invalid: str
    role_not_authorized: str
    capability_required: str


@dataclass(frozen=True)
class ProposalPrincipalHeaders:
    actor_id: str | None
    role: str | None
    tenant_id: str | None
    legal_entity_code: str | None
    correlation_id: str | None
    service_identity: str | None
    authorization: str | None
    capabilities: str | None
    principal_status: str | None
    authorized_advisor_id: str | None = None
    authorized_proposal_id: str | None = None
    authorized_portfolio_id: str | None = None


@dataclass(frozen=True)
class ProposalPrincipalContext:
    actor_id: str
    role: str
    tenant_id: str
    legal_entity_code: str
    correlation_id: str
    service_identity: str
    capabilities: frozenset[str]
    authorized_advisor_id: str | None = None
    authorized_proposal_id: str | None = None
    authorized_portfolio_id: str | None = None


def resolve_proposal_principal(
    *,
    required_capability: str,
    authorized_roles: Iterable[str],
    errors: ProposalPrincipalErrors,
    principal_factory: Callable[[ProposalPrincipalContext], _PrincipalT],
    headers: ProposalPrincipalHeaders,
    correlation_id_fallback: str | None = None,
) -> _PrincipalT:
    actor_id = _required_header(headers.actor_id, detail=errors.required)
    role = _required_header(headers.role, detail=errors.required).upper()
    tenant_id = _required_header(headers.tenant_id, detail=errors.required)
    legal_entity_code = _required_header(headers.legal_entity_code, detail=errors.required).upper()
    correlation_id = _correlation_id(
        headers.correlation_id,
        fallback=correlation_id_fallback,
        detail=errors.required,
    )
    service_identity = _service_identity(
        headers.service_identity,
        headers.authorization,
        detail=errors.required,
    )
    capabilities = frozenset(_capability_set(headers.capabilities))

    if (headers.principal_status or "ACTIVE").strip().upper() != "ACTIVE":
        _raise_authn(errors.invalid)
    if role not in {item.upper() for item in authorized_roles}:
        _raise_authz(errors.role_not_authorized)
    if required_capability not in capabilities:
        _raise_authz(errors.capability_required)

    return principal_factory(
        ProposalPrincipalContext(
            actor_id=actor_id,
            role=role,
            tenant_id=tenant_id,
            legal_entity_code=legal_entity_code,
            correlation_id=correlation_id,
            service_identity=service_identity,
            capabilities=capabilities,
            authorized_advisor_id=_optional_header(headers.authorized_advisor_id),
            authorized_proposal_id=_optional_header(headers.authorized_proposal_id),
            authorized_portfolio_id=_optional_header(headers.authorized_portfolio_id),
        )
    )


def _required_header(value: str | None, *, detail: str) -> str:
    normalized = _optional_header(value)
    if normalized is None:
        _raise_authn(detail)
    return normalized


def _correlation_id(
    value: str | None,
    *,
    fallback: str | None,
    detail: str,
) -> str:
    if fallback is not None:
        return _optional_header(value) or fallback
    return _required_header(value, detail=detail)


def _optional_header(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _service_identity(
    x_service_identity: str | None,
    authorization: str | None,
    *,
    detail: str,
) -> str:
    service_identity = _optional_header(x_service_identity)
    if service_identity is not None:
        return service_identity
    if _optional_header(authorization) is not None:
        return "authorization"
    _raise_authn(detail)


def _capability_set(value: str | None) -> set[str]:
    return {part.strip() for part in (value or "").split(",") if part.strip()}


def _raise_authn(detail: str) -> NoReturn:
    raise_proposal_api_http_exception(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
    )
    raise AssertionError("unreachable")  # pragma: no cover


def _raise_authz(detail: str) -> NoReturn:
    raise_proposal_api_http_exception(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )
    raise AssertionError("unreachable")  # pragma: no cover


__all__ = [
    "ProposalPrincipalContext",
    "ProposalPrincipalErrors",
    "ProposalPrincipalHeaders",
    "resolve_proposal_principal",
]
