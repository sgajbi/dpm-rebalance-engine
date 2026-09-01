from __future__ import annotations

from dataclasses import dataclass
from typing import Any

IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY = "advisory.idea_proposal_intake.accept"
IDEA_PROPOSAL_REALIZATION_READ_CAPABILITY = "advisory.idea_proposal_realization.read"
IDEA_PROPOSAL_INTAKE_AUTHORIZED_ROLES = frozenset(
    {"ADVISOR", "PORTFOLIO_MANAGER", "RELATIONSHIP_MANAGER", "SERVICE"}
)


@dataclass(frozen=True)
class IdeaProposalIntakePrincipal:
    actor_id: str
    role: str
    tenant_id: str
    legal_entity_code: str
    correlation_id: str
    service_identity: str
    capabilities: frozenset[str]

    def audit_metadata(self, *, capability: str) -> dict[str, Any]:
        return {
            "subject": self.actor_id,
            "role": self.role,
            "tenant_id": self.tenant_id,
            "legal_entity_code": self.legal_entity_code,
            "correlation_id": self.correlation_id,
            "service_identity": self.service_identity,
            "capability": capability,
        }


__all__ = [
    "IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY",
    "IDEA_PROPOSAL_INTAKE_AUTHORIZED_ROLES",
    "IDEA_PROPOSAL_REALIZATION_READ_CAPABILITY",
    "IdeaProposalIntakePrincipal",
]
