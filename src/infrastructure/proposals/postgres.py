from contextlib import closing
from datetime import datetime
from typing import Any, Optional, cast

from src.core.advisor_cockpit.persistence import (
    CockpitAcknowledgementIdempotencyRecord,
    CockpitAcknowledgementRecord,
)
from src.core.proposals.contract_types import ProposalWorkflowState
from src.core.proposals.models import (
    ProposalApprovalRecordData,
    ProposalAsyncOperationRecord,
    ProposalIdempotencyRecord,
    ProposalMemoEventRecord,
    ProposalMemoIdempotencyRecord,
    ProposalMemoRecord,
    ProposalRecord,
    ProposalSimulationIdempotencyRecord,
    ProposalTransitionResult,
    ProposalVersionRecord,
    ProposalWorkflowEventRecord,
)
from src.infrastructure.postgres_migrations import apply_postgres_migrations
from src.infrastructure.proposals import postgres_approvals as _approvals
from src.infrastructure.proposals import (
    postgres_async_operations as _async_operations,
)
from src.infrastructure.proposals import (
    postgres_cockpit_acknowledgements as _cockpit_acknowledgements,
)
from src.infrastructure.proposals import postgres_connection as _postgres_connection
from src.infrastructure.proposals import (
    postgres_idempotency as _idempotency,
)
from src.infrastructure.proposals import (
    postgres_memos as _memos,
)
from src.infrastructure.proposals import (
    postgres_records as _records,
)
from src.infrastructure.proposals import (
    postgres_versions as _versions,
)
from src.infrastructure.proposals import (
    postgres_workflow_events as _workflow_events,
)
from src.infrastructure.proposals.postgres_idea_repository import (
    PostgresIdeaIntakeRepositoryMixin,
)


class PostgresProposalRepository(PostgresIdeaIntakeRepositoryMixin):
    def __init__(self, *, dsn: str) -> None:
        if not dsn:
            raise RuntimeError("PROPOSAL_POSTGRES_DSN_REQUIRED")
        _postgres_connection.ensure_postgres_driver()
        self._dsn = dsn
        self._init_db()

    def get_idempotency(self, *, idempotency_key: str) -> Optional[ProposalIdempotencyRecord]:
        return _idempotency.get_proposal_idempotency(
            connect=self._connect,
            idempotency_key=idempotency_key,
        )

    def save_idempotency(self, record: ProposalIdempotencyRecord) -> None:
        _idempotency.save_proposal_idempotency(connect=self._connect, record=record)

    def get_simulation_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[ProposalSimulationIdempotencyRecord]:
        return _idempotency.get_simulation_idempotency(
            connect=self._connect,
            idempotency_key=idempotency_key,
        )

    def save_simulation_idempotency(self, record: ProposalSimulationIdempotencyRecord) -> None:
        _idempotency.save_simulation_idempotency(connect=self._connect, record=record)

    def get_memo_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[ProposalMemoIdempotencyRecord]:
        return _idempotency.get_memo_idempotency(
            connect=self._connect,
            idempotency_key=idempotency_key,
        )

    def save_memo_idempotency(self, record: ProposalMemoIdempotencyRecord) -> None:
        _idempotency.save_memo_idempotency(connect=self._connect, record=record)

    def create_memo(self, memo: ProposalMemoRecord) -> None:
        _memos.create_memo(connect=self._connect, memo=memo)

    def create_memo_with_idempotency_event(
        self,
        *,
        memo: ProposalMemoRecord,
        idempotency: Optional[ProposalMemoIdempotencyRecord],
        event: ProposalMemoEventRecord,
    ) -> None:
        with closing(self._connect()) as connection:
            try:
                _memos.insert_memo(connection=connection, memo=memo)
                if idempotency is not None:
                    _idempotency.insert_memo_idempotency(
                        connection=connection,
                        record=idempotency,
                    )
                _memos.insert_memo_event(connection=connection, event=event)
            except Exception:
                connection.rollback()
                raise
            connection.commit()

    def get_memo(self, *, memo_id: str) -> Optional[ProposalMemoRecord]:
        return _memos.get_memo(connect=self._connect, memo_id=memo_id)

    def get_memo_by_proposal_version(
        self, *, proposal_id: str, proposal_version_no: int
    ) -> Optional[ProposalMemoRecord]:
        return _memos.get_memo_by_proposal_version(
            connect=self._connect,
            proposal_id=proposal_id,
            proposal_version_no=proposal_version_no,
        )

    def list_memos(self, *, proposal_id: str) -> list[ProposalMemoRecord]:
        return cast(
            list[ProposalMemoRecord],
            _memos.list_memos(connect=self._connect, proposal_id=proposal_id),
        )

    def list_memos_for_proposals(self, *, proposal_ids: list[str]) -> list[ProposalMemoRecord]:
        return cast(
            list[ProposalMemoRecord],
            _memos.list_memos_for_proposals(connect=self._connect, proposal_ids=proposal_ids),
        )

    def append_memo_event(self, event: ProposalMemoEventRecord) -> None:
        _memos.append_memo_event(connect=self._connect, event=event)

    def list_memo_events(self, *, memo_id: str) -> list[ProposalMemoEventRecord]:
        return cast(
            list[ProposalMemoEventRecord],
            _memos.list_memo_events(connect=self._connect, memo_id=memo_id),
        )

    def get_cockpit_acknowledgement(
        self, *, action_item_id: str
    ) -> Optional[CockpitAcknowledgementRecord]:
        return _cockpit_acknowledgements.get_cockpit_acknowledgement(
            connect=self._connect,
            action_item_id=action_item_id,
        )

    def list_cockpit_acknowledgements(
        self, *, action_item_ids: list[str]
    ) -> dict[str, CockpitAcknowledgementRecord]:
        return cast(
            dict[str, CockpitAcknowledgementRecord],
            _cockpit_acknowledgements.list_cockpit_acknowledgements(
                connect=self._connect,
                action_item_ids=action_item_ids,
            ),
        )

    def save_cockpit_acknowledgement_with_idempotency(
        self,
        *,
        acknowledgement: CockpitAcknowledgementRecord,
        idempotency: CockpitAcknowledgementIdempotencyRecord,
    ) -> None:
        _cockpit_acknowledgements.save_cockpit_acknowledgement_with_idempotency(
            connect=self._connect,
            acknowledgement=acknowledgement,
            idempotency=idempotency,
        )

    def get_cockpit_acknowledgement_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[CockpitAcknowledgementIdempotencyRecord]:
        return _cockpit_acknowledgements.get_cockpit_acknowledgement_idempotency(
            connect=self._connect,
            idempotency_key=idempotency_key,
        )

    def create_operation(self, operation: ProposalAsyncOperationRecord) -> None:
        _async_operations.upsert_operation(connect=self._connect, operation=operation)

    def create_operation_if_absent_by_idempotency(
        self, operation: ProposalAsyncOperationRecord
    ) -> tuple[ProposalAsyncOperationRecord, bool]:
        return cast(
            tuple[ProposalAsyncOperationRecord, bool],
            _async_operations.create_operation_if_absent_by_idempotency(
                connect=self._connect,
                operation=operation,
            ),
        )

    def update_operation(self, operation: ProposalAsyncOperationRecord) -> None:
        _async_operations.upsert_operation(connect=self._connect, operation=operation)

    def get_operation(self, *, operation_id: str) -> Optional[ProposalAsyncOperationRecord]:
        return _async_operations.get_operation(connect=self._connect, operation_id=operation_id)

    def get_operation_by_correlation(
        self, *, correlation_id: str
    ) -> Optional[ProposalAsyncOperationRecord]:
        return _async_operations.get_operation_by_correlation(
            connect=self._connect, correlation_id=correlation_id
        )

    def get_operation_by_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[ProposalAsyncOperationRecord]:
        return _async_operations.get_operation_by_idempotency(
            connect=self._connect, idempotency_key=idempotency_key
        )

    def list_recoverable_operations(
        self, *, as_of: datetime, limit: Optional[int] = None
    ) -> list[ProposalAsyncOperationRecord]:
        return cast(
            list[ProposalAsyncOperationRecord],
            _async_operations.list_recoverable_operations(
                connect=self._connect, as_of=as_of, limit=limit
            ),
        )

    def list_operations_for_control(
        self, *, as_of: datetime, limit: Optional[int] = None
    ) -> list[ProposalAsyncOperationRecord]:
        return cast(
            list[ProposalAsyncOperationRecord],
            _async_operations.list_operations_for_control(connect=self._connect, limit=limit),
        )  # noqa: E501

    def create_proposal(self, proposal: ProposalRecord) -> None:
        _records.create_proposal(connect=self._connect, proposal=proposal)

    def create_proposal_with_version_event_idempotency(
        self,
        *,
        proposal: ProposalRecord,
        version: ProposalVersionRecord,
        event: ProposalWorkflowEventRecord,
        idempotency: ProposalIdempotencyRecord,
    ) -> None:
        with closing(self._connect()) as connection:
            try:
                _records.upsert_proposal(connection=connection, proposal=proposal)
                _versions.insert_version(connection=connection, version=version)
                _workflow_events.insert_event(connection=connection, event=event)
                _idempotency.insert_proposal_idempotency(
                    connection=connection,
                    record=idempotency,
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()

    def update_proposal(self, proposal: ProposalRecord) -> None:
        _records.update_proposal(connect=self._connect, proposal=proposal)

    def get_proposal(self, *, proposal_id: str) -> Optional[ProposalRecord]:
        return _records.get_proposal(connect=self._connect, proposal_id=proposal_id)

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
    ) -> tuple[list[ProposalRecord], Optional[str]]:
        return cast(
            tuple[list[ProposalRecord], Optional[str]],
            _records.list_proposals(
                connect=self._connect,
                portfolio_id=portfolio_id,
                state=state,
                created_by=created_by,
                created_from=created_from,
                created_to=created_to,
                limit=limit,
                cursor=cursor,
            ),
        )

    def create_version(self, version: ProposalVersionRecord) -> None:
        _versions.create_version(connect=self._connect, version=version)

    def get_version(self, *, proposal_id: str, version_no: int) -> Optional[ProposalVersionRecord]:
        return _versions.get_version(
            connect=self._connect,
            proposal_id=proposal_id,
            version_no=version_no,
        )

    def list_versions(self, *, proposal_id: str) -> list[ProposalVersionRecord]:
        return cast(
            list[ProposalVersionRecord],
            _versions.list_versions(connect=self._connect, proposal_id=proposal_id),
        )

    def get_current_version(self, *, proposal_id: str) -> Optional[ProposalVersionRecord]:
        return _versions.get_current_version(connect=self._connect, proposal_id=proposal_id)

    def append_event(self, event: ProposalWorkflowEventRecord) -> None:
        _workflow_events.append_event(connect=self._connect, event=event)

    def list_events(self, *, proposal_id: str) -> list[ProposalWorkflowEventRecord]:
        return cast(
            list[ProposalWorkflowEventRecord],
            _workflow_events.list_events(connect=self._connect, proposal_id=proposal_id),
        )

    def list_events_for_proposals(
        self, *, proposal_ids: list[str]
    ) -> list[ProposalWorkflowEventRecord]:
        return cast(
            list[ProposalWorkflowEventRecord],
            _workflow_events.list_events_for_proposals(
                connect=self._connect, proposal_ids=proposal_ids
            ),
        )

    def create_approval(self, approval: ProposalApprovalRecordData) -> None:
        _approvals.create_approval(connect=self._connect, approval=approval)

    def list_approvals(self, *, proposal_id: str) -> list[ProposalApprovalRecordData]:
        return cast(
            list[ProposalApprovalRecordData],
            _approvals.list_approvals(connect=self._connect, proposal_id=proposal_id),
        )

    def list_approvals_for_proposals(
        self, *, proposal_ids: list[str]
    ) -> list[ProposalApprovalRecordData]:
        return cast(
            list[ProposalApprovalRecordData],
            _approvals.list_approvals_for_proposals(
                connect=self._connect, proposal_ids=proposal_ids
            ),
        )

    def transition_proposal(
        self,
        *,
        proposal: ProposalRecord,
        event: ProposalWorkflowEventRecord,
        approval: Optional[ProposalApprovalRecordData],
        expected_current_state: Optional[ProposalWorkflowState] = None,
        expected_current_version_no: Optional[int] = None,
    ) -> ProposalTransitionResult:
        return _workflow_events.transition_proposal(
            connect=self._connect,
            proposal=proposal,
            event=event,
            approval=approval,
            expected_current_state=expected_current_state,
            expected_current_version_no=expected_current_version_no,
        )

    def _connect(self) -> Any:
        return _postgres_connection.connect_postgres(self._dsn)

    def _init_db(self) -> None:
        with closing(self._connect()) as connection:
            apply_postgres_migrations(connection=connection, namespace="proposals")
