from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IdeaProposalIntakeRecord:
    registry_key: str
    request_fingerprint: str
    response_json: str
    created_at_utc: datetime


@dataclass(frozen=True)
class IdeaProposalIntakeClaim:
    record: IdeaProposalIntakeRecord
    replayed: bool
