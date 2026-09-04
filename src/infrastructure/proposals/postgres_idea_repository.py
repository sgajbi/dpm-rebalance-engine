from __future__ import annotations

from typing import Any, Callable, Optional

from src.core.proposals.idea_intake_persistence import (
    IdeaProposalIntakeClaim,
    IdeaProposalIntakeRecord,
)
from src.core.proposals.idea_review_realization import (
    IdeaProposalRealizationHistoryRecord,
    IdeaProposalRealizationOutcomeRecord,
    IdeaProposalRealizationRecord,
)
from src.infrastructure.proposals import postgres_idea_intakes


class PostgresIdeaIntakeRepositoryMixin:
    """Delegate Idea intake and realization persistence to its cohesive adapter."""

    _connect: Callable[[], Any]

    def claim_idea_proposal_intake(
        self, record: IdeaProposalIntakeRecord
    ) -> IdeaProposalIntakeClaim:
        return postgres_idea_intakes.claim_idea_proposal_intake(
            connect=self._connect, record=record
        )

    def get_idea_proposal_realization(
        self,
        *,
        intake_id: str,
        tenant_id: str,
        legal_entity_code: str,
        portfolio_id: str,
    ) -> Optional[IdeaProposalRealizationHistoryRecord]:
        return postgres_idea_intakes.get_idea_proposal_realization(
            connect=self._connect,
            intake_id=intake_id,
            tenant_id=tenant_id,
            legal_entity_code=legal_entity_code,
            portfolio_id=portfolio_id,
        )

    def get_idea_proposal_realization_by_conversion_intent(
        self,
        *,
        conversion_intent_id: str,
        tenant_id: str,
        legal_entity_code: str,
        portfolio_id: str,
    ) -> Optional[IdeaProposalRealizationHistoryRecord]:
        return postgres_idea_intakes.get_idea_proposal_realization_by_conversion_intent(
            connect=self._connect,
            conversion_intent_id=conversion_intent_id,
            tenant_id=tenant_id,
            legal_entity_code=legal_entity_code,
            portfolio_id=portfolio_id,
        )

    def advance_idea_proposal_realization(
        self,
        *,
        expected_source_event_version: int,
        realization: IdeaProposalRealizationRecord,
        outcomes: tuple[IdeaProposalRealizationOutcomeRecord, ...],
    ) -> IdeaProposalRealizationHistoryRecord:
        return postgres_idea_intakes.advance_idea_proposal_realization(
            connect=self._connect,
            expected_source_event_version=expected_source_event_version,
            realization=realization,
            outcomes=outcomes,
        )
