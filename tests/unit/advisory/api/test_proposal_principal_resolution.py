from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import HTTPException

from src.api.proposals.advisor_cockpit_principal import (
    ADVISOR_COCKPIT_READ_CAPABILITY,
    require_advisor_cockpit_read_principal,
)
from src.api.proposals.copilot_review_principal import (
    require_advisory_copilot_review_principal,
)
from src.api.proposals.idea_intake_principal import (
    require_idea_proposal_intake_principal,
    require_idea_proposal_realization_reader,
)
from src.api.proposals.policy_control_principal import (
    POLICY_PACK_VALIDATE_CAPABILITY,
    POLICY_STEWARD_ROLE,
    require_policy_pack_validation_principal,
)

_PrincipalDependency = Callable[..., object]


@pytest.mark.parametrize(
    ("dependency", "role", "capability"),
    [
        (
            require_advisor_cockpit_read_principal,
            "ADVISOR",
            ADVISOR_COCKPIT_READ_CAPABILITY,
        ),
        (
            require_advisory_copilot_review_principal,
            "ADVISORY_SUPERVISOR",
            "advisory.copilot.review",
        ),
        (
            require_idea_proposal_intake_principal,
            "ADVISOR",
            "advisory.idea_proposal_intake.accept",
        ),
        (
            require_idea_proposal_realization_reader,
            "ADVISOR",
            "advisory.idea_proposal_realization.read",
        ),
        (
            require_policy_pack_validation_principal,
            POLICY_STEWARD_ROLE,
            POLICY_PACK_VALIDATE_CAPABILITY,
        ),
    ],
)
def test_shared_principal_resolution_preserves_typed_surface_contracts(
    dependency: _PrincipalDependency,
    role: str,
    capability: str,
) -> None:
    principal_kwargs = {
        "x_actor_id": " actor-001 ",
        "x_role": f" {role.lower()} ",
        "x_tenant_id": " tenant-001 ",
        "x_legal_entity_code": " reference ",
        "x_correlation_id": None
        if dependency
        in {require_idea_proposal_intake_principal, require_idea_proposal_realization_reader}
        else " correlation-001 ",
        "x_service_identity": None,
        "authorization": "Bearer trusted-token",
        "x_capabilities": f" {capability}, advisory.proposals.read ",
        "x_principal_status": " active ",
    }
    if dependency is require_advisor_cockpit_read_principal:
        principal_kwargs.update(
            x_authorized_advisor_id=" advisor-001 ",
            x_authorized_portfolio_id=" portfolio-001 ",
        )
    elif dependency is require_advisory_copilot_review_principal:
        principal_kwargs.update(
            x_authorized_proposal_id=" proposal-001 ",
            x_authorized_portfolio_id=" portfolio-001 ",
        )
    elif dependency is require_idea_proposal_realization_reader:
        principal_kwargs.update(x_authorized_portfolio_id=" portfolio-001 ")

    principal = dependency(**principal_kwargs)

    assert principal.actor_id == "actor-001"
    assert principal.role == role
    assert principal.tenant_id == "tenant-001"
    assert principal.legal_entity_code == "REFERENCE"
    assert principal.service_identity == "authorization"
    assert capability in principal.capabilities
    assert principal.capabilities == frozenset({capability, "advisory.proposals.read"})
    assert principal.correlation_id in {"correlation-001", "route-correlation-pending"}

    if dependency is require_advisor_cockpit_read_principal:
        assert principal.authorized_advisor_id == "advisor-001"
    elif dependency is require_idea_proposal_intake_principal:
        assert not hasattr(principal, "authorized_proposal_id")
        assert principal.authorized_portfolio_id is None
    elif dependency is require_idea_proposal_realization_reader:
        assert not hasattr(principal, "authorized_proposal_id")
        assert principal.authorized_portfolio_id == "portfolio-001"
        metadata = principal.audit_metadata(capability=capability)
        assert metadata["authorized_portfolio_id"] == "portfolio-001"
    elif dependency is require_advisory_copilot_review_principal:
        assert principal.authorized_proposal_id == "proposal-001"
        assert principal.authorized_portfolio_id == "portfolio-001"


@pytest.mark.parametrize(
    ("dependency", "role", "capability", "detail"),
    [
        (
            require_advisor_cockpit_read_principal,
            "ADVISOR",
            ADVISOR_COCKPIT_READ_CAPABILITY,
            "ADVISOR_COCKPIT_PRINCIPAL_INVALID",
        ),
        (
            require_advisory_copilot_review_principal,
            "ADVISORY_SUPERVISOR",
            "advisory.copilot.review",
            "COPILOT_REVIEW_PRINCIPAL_INVALID",
        ),
        (
            require_idea_proposal_intake_principal,
            "ADVISOR",
            "advisory.idea_proposal_intake.accept",
            "IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID",
        ),
        (
            require_idea_proposal_realization_reader,
            "ADVISOR",
            "advisory.idea_proposal_realization.read",
            "IDEA_PROPOSAL_INTAKE_PRINCIPAL_INVALID",
        ),
        (
            require_policy_pack_validation_principal,
            POLICY_STEWARD_ROLE,
            POLICY_PACK_VALIDATE_CAPABILITY,
            "POLICY_CONTROL_PRINCIPAL_INVALID",
        ),
    ],
)
def test_shared_principal_resolution_rejects_inactive_principals_consistently(
    dependency: _PrincipalDependency,
    role: str,
    capability: str,
    detail: str,
) -> None:
    with pytest.raises(HTTPException) as error:
        dependency(
            x_actor_id="actor-001",
            x_role=role,
            x_tenant_id="tenant-001",
            x_legal_entity_code="REFERENCE",
            x_correlation_id="correlation-001",
            x_service_identity="lotus-gateway",
            authorization=None,
            x_capabilities=capability,
            x_principal_status="SUSPENDED",
        )

    assert error.value.status_code == 401
    assert error.value.detail == detail


@pytest.mark.parametrize(
    ("dependency", "role", "capability", "detail"),
    [
        (
            require_advisor_cockpit_read_principal,
            "ADVISOR",
            ADVISOR_COCKPIT_READ_CAPABILITY,
            "ADVISOR_COCKPIT_PRINCIPAL_REQUIRED",
        ),
        (
            require_advisory_copilot_review_principal,
            "ADVISORY_SUPERVISOR",
            "advisory.copilot.review",
            "COPILOT_REVIEW_PRINCIPAL_REQUIRED",
        ),
        (
            require_idea_proposal_intake_principal,
            "ADVISOR",
            "advisory.idea_proposal_intake.accept",
            "IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED",
        ),
        (
            require_idea_proposal_realization_reader,
            "ADVISOR",
            "advisory.idea_proposal_realization.read",
            "IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED",
        ),
        (
            require_policy_pack_validation_principal,
            POLICY_STEWARD_ROLE,
            POLICY_PACK_VALIDATE_CAPABILITY,
            "POLICY_CONTROL_PRINCIPAL_REQUIRED",
        ),
    ],
)
def test_shared_principal_resolution_requires_service_identity(
    dependency: _PrincipalDependency,
    role: str,
    capability: str,
    detail: str,
) -> None:
    with pytest.raises(HTTPException) as error:
        dependency(
            x_actor_id="actor-001",
            x_role=role,
            x_tenant_id="tenant-001",
            x_legal_entity_code="REFERENCE",
            x_correlation_id="correlation-001",
            x_service_identity=None,
            authorization=None,
            x_capabilities=capability,
            x_principal_status="ACTIVE",
        )

    assert error.value.status_code == 401
    assert error.value.detail == detail
