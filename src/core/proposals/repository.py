from datetime import datetime
from typing import Optional, Protocol

from src.core.proposals.contract_types import ProposalWorkflowState
from src.core.proposals.idea_intake_persistence import (
    IdeaProposalIntakeClaim,
    IdeaProposalIntakeRecord,
)
from src.core.proposals.idea_review_realization import (
    IdeaProposalRealizationHistoryRecord,
    IdeaProposalRealizationOutcomeRecord,
    IdeaProposalRealizationRecord,
)
from src.core.proposals.memo_persistence_models import (
    ProposalMemoEventRecord,
    ProposalMemoIdempotencyRecord,
    ProposalMemoRecord,
)
from src.core.proposals.models import (
    ProposalApprovalRecordData,
    ProposalAsyncOperationRecord,
    ProposalIdempotencyRecord,
    ProposalRecord,
    ProposalSimulationIdempotencyRecord,
    ProposalTransitionResult,
    ProposalVersionRecord,
    ProposalWorkflowEventRecord,
)


class ProposalRepository(Protocol):
    def claim_idea_proposal_intake(
        self, record: IdeaProposalIntakeRecord
    ) -> IdeaProposalIntakeClaim: ...

    def get_idea_proposal_realization(
        self,
        *,
        intake_id: str,
        tenant_id: str,
        legal_entity_code: str,
        portfolio_id: str,
    ) -> Optional[IdeaProposalRealizationHistoryRecord]: ...

    def get_idea_proposal_realization_by_conversion_intent(
        self,
        *,
        conversion_intent_id: str,
        tenant_id: str,
        legal_entity_code: str,
        portfolio_id: str,
    ) -> Optional[IdeaProposalRealizationHistoryRecord]: ...

    def advance_idea_proposal_realization(
        self,
        *,
        expected_source_event_version: int,
        realization: IdeaProposalRealizationRecord,
        outcomes: tuple[IdeaProposalRealizationOutcomeRecord, ...],
    ) -> IdeaProposalRealizationHistoryRecord: ...

    def get_idempotency(self, *, idempotency_key: str) -> Optional[ProposalIdempotencyRecord]: ...

    def save_idempotency(self, record: ProposalIdempotencyRecord) -> None: ...

    def get_simulation_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[ProposalSimulationIdempotencyRecord]: ...

    def save_simulation_idempotency(self, record: ProposalSimulationIdempotencyRecord) -> None: ...

    def get_memo_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[ProposalMemoIdempotencyRecord]: ...

    def save_memo_idempotency(self, record: ProposalMemoIdempotencyRecord) -> None: ...

    def create_memo(self, memo: ProposalMemoRecord) -> None: ...

    def create_memo_with_idempotency_event(
        self,
        *,
        memo: ProposalMemoRecord,
        idempotency: Optional[ProposalMemoIdempotencyRecord],
        event: ProposalMemoEventRecord,
    ) -> None: ...

    def get_memo(self, *, memo_id: str) -> Optional[ProposalMemoRecord]: ...

    def get_memo_by_proposal_version(
        self, *, proposal_id: str, proposal_version_no: int
    ) -> Optional[ProposalMemoRecord]: ...

    def list_memos(self, *, proposal_id: str) -> list[ProposalMemoRecord]: ...

    def list_memos_for_proposals(self, *, proposal_ids: list[str]) -> list[ProposalMemoRecord]: ...

    def append_memo_event(self, event: ProposalMemoEventRecord) -> None: ...

    def list_memo_events(self, *, memo_id: str) -> list[ProposalMemoEventRecord]: ...

    def create_operation(self, operation: ProposalAsyncOperationRecord) -> None: ...

    def create_operation_if_absent_by_idempotency(
        self, operation: ProposalAsyncOperationRecord
    ) -> tuple[ProposalAsyncOperationRecord, bool]: ...

    def update_operation(self, operation: ProposalAsyncOperationRecord) -> None: ...

    def get_operation(self, *, operation_id: str) -> Optional[ProposalAsyncOperationRecord]: ...

    def get_operation_by_correlation(
        self, *, correlation_id: str
    ) -> Optional[ProposalAsyncOperationRecord]: ...

    def get_operation_by_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[ProposalAsyncOperationRecord]: ...

    def list_recoverable_operations(
        self, *, as_of: datetime, limit: Optional[int] = None
    ) -> list[ProposalAsyncOperationRecord]: ...

    def list_operations_for_control(
        self, *, as_of: datetime, limit: Optional[int] = None
    ) -> list[ProposalAsyncOperationRecord]: ...

    def create_proposal(self, proposal: ProposalRecord) -> None: ...

    def create_proposal_with_version_event_idempotency(
        self,
        *,
        proposal: ProposalRecord,
        version: ProposalVersionRecord,
        event: ProposalWorkflowEventRecord,
        idempotency: ProposalIdempotencyRecord,
    ) -> None: ...

    def update_proposal(self, proposal: ProposalRecord) -> None: ...

    def get_proposal(self, *, proposal_id: str) -> Optional[ProposalRecord]: ...

    def list_proposals(
        self,
        *,
        portfolio_id: Optional[str],
        state: Optional[str],
        created_by: Optional[str],
        created_from: Optional[datetime],
        created_to: Optional[datetime],
        limit: int,
        cursor: Optional[str],
    ) -> tuple[list[ProposalRecord], Optional[str]]: ...

    def create_version(self, version: ProposalVersionRecord) -> None: ...

    def get_version(
        self, *, proposal_id: str, version_no: int
    ) -> Optional[ProposalVersionRecord]: ...

    def list_versions(self, *, proposal_id: str) -> list[ProposalVersionRecord]: ...

    def get_current_version(self, *, proposal_id: str) -> Optional[ProposalVersionRecord]: ...

    def append_event(self, event: ProposalWorkflowEventRecord) -> None: ...

    def list_events(self, *, proposal_id: str) -> list[ProposalWorkflowEventRecord]: ...

    def list_events_for_proposals(
        self, *, proposal_ids: list[str]
    ) -> list[ProposalWorkflowEventRecord]: ...

    def create_approval(self, approval: ProposalApprovalRecordData) -> None: ...

    def list_approvals(self, *, proposal_id: str) -> list[ProposalApprovalRecordData]: ...

    def list_approvals_for_proposals(
        self, *, proposal_ids: list[str]
    ) -> list[ProposalApprovalRecordData]: ...

    def transition_proposal(
        self,
        *,
        proposal: ProposalRecord,
        event: ProposalWorkflowEventRecord,
        approval: Optional[ProposalApprovalRecordData],
        expected_current_state: Optional[ProposalWorkflowState] = None,
        expected_current_version_no: Optional[int] = None,
    ) -> ProposalTransitionResult: ...
