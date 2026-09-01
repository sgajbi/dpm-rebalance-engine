from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IdeaProposalIntakeRecord:
    """Durable replay claim for one trusted-scope Idea intake key."""

    registry_key: str
    request_fingerprint: str
    response_json: str
    created_at_utc: datetime


@dataclass(frozen=True)
class IdeaProposalIntakeClaim:
    """Result of atomically claiming or replaying an intake record."""

    record: IdeaProposalIntakeRecord
    replayed: bool
