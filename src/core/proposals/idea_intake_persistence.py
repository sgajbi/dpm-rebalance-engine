from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

IDEA_PROPOSAL_INTAKE_REPLAY_RETENTION = timedelta(hours=24)
IDEA_PROPOSAL_INTAKE_PURGE_BATCH_SIZE = 128


@dataclass(frozen=True)
class IdeaProposalIntakeRecord:
    """Durable replay claim for one trusted-scope Idea intake key."""

    registry_key: str
    request_fingerprint: str
    response_json: str
    created_at_utc: datetime
    expires_at_utc: datetime
    legal_hold: bool = False


@dataclass(frozen=True)
class IdeaProposalIntakeClaim:
    """Result of atomically claiming or replaying an intake record."""

    record: IdeaProposalIntakeRecord
    replayed: bool
