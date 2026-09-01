from datetime import datetime
from threading import Lock
from typing import Optional

from src.core.advisor_cockpit.persistence import (
    CockpitAcknowledgementIdempotencyRecord,
    CockpitAcknowledgementRecord,
)
from src.core.proposals.contract_types import ProposalWorkflowState
from src.core.proposals.exceptions import (
    ProposalIdempotencyConflictError,
    ProposalStateConflictError,
)
from src.core.proposals.idea_intake_persistence import (
    IdeaProposalIntakeClaim,
    IdeaProposalIntakeRecord,
)
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
from src.core.proposals.repository import ProposalRepository
from src.infrastructure.proposals.in_memory_query import (
    control_operations,
    copy_optional,
    copy_record,
    copy_records,
    current_version_for_proposal,
    filtered_proposal_page,
    ordered_approvals_for_proposals,
    ordered_events_for_proposals,
    ordered_memo_events,
    ordered_memos_for_proposal,
    ordered_memos_for_proposals,
    ordered_versions_for_proposal,
    recoverable_operations,
)


def _retained_idea_proposal_intakes(
    records: dict[str, IdeaProposalIntakeRecord],
    *,
    as_of: datetime,
) -> dict[str, IdeaProposalIntakeRecord]:
    """Keep replayable claims and every claim protected by legal hold."""
    return {
        registry_key: record
        for registry_key, record in records.items()
        if record.legal_hold or record.expires_at_utc > as_of
    }


class InMemoryProposalRepository(ProposalRepository):
    def __init__(self) -> None:
        self._lock = Lock()
        self._proposals: dict[str, ProposalRecord] = {}
        self._versions: dict[tuple[str, int], ProposalVersionRecord] = {}
        self._events: dict[str, list[ProposalWorkflowEventRecord]] = {}
        self._approvals: dict[str, list[ProposalApprovalRecordData]] = {}
        self._idempotency: dict[str, ProposalIdempotencyRecord] = {}
        self._simulation_idempotency: dict[str, ProposalSimulationIdempotencyRecord] = {}
        self._memo_idempotency: dict[str, ProposalMemoIdempotencyRecord] = {}
        self._operations: dict[str, ProposalAsyncOperationRecord] = {}
        self._operation_by_correlation: dict[str, str] = {}
        self._operation_by_idempotency: dict[str, str] = {}
        self._memos: dict[str, ProposalMemoRecord] = {}
        self._memo_by_proposal_version: dict[tuple[str, int], str] = {}
        self._memo_events: dict[str, list[ProposalMemoEventRecord]] = {}
        self._cockpit_acknowledgements: dict[str, CockpitAcknowledgementRecord] = {}
        self._cockpit_acknowledgement_idempotency: dict[
            str, CockpitAcknowledgementIdempotencyRecord
        ] = {}
        self._idea_proposal_intakes: dict[str, IdeaProposalIntakeRecord] = {}

    def claim_idea_proposal_intake(
        self, record: IdeaProposalIntakeRecord
    ) -> IdeaProposalIntakeClaim:
        with self._lock:
            self._idea_proposal_intakes = _retained_idea_proposal_intakes(
                self._idea_proposal_intakes,
                as_of=record.created_at_utc,
            )
            existing = self._idea_proposal_intakes.get(record.registry_key)
            if existing is None:
                stored = copy_record(record)
                self._idea_proposal_intakes[record.registry_key] = stored
                return IdeaProposalIntakeClaim(record=copy_record(stored), replayed=False)
            if existing.request_fingerprint != record.request_fingerprint:
                raise ProposalIdempotencyConflictError("IDEA_PROPOSAL_INTAKE_IDEMPOTENCY_CONFLICT")
            return IdeaProposalIntakeClaim(record=copy_record(existing), replayed=True)

    def get_idempotency(self, *, idempotency_key: str) -> Optional[ProposalIdempotencyRecord]:
        with self._lock:
            record = self._idempotency.get(idempotency_key)
            return copy_optional(record)

    def save_idempotency(self, record: ProposalIdempotencyRecord) -> None:
        with self._lock:
            self._idempotency[record.idempotency_key] = copy_record(record)

    def get_simulation_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[ProposalSimulationIdempotencyRecord]:
        with self._lock:
            record = self._simulation_idempotency.get(idempotency_key)
            return copy_optional(record)

    def save_simulation_idempotency(self, record: ProposalSimulationIdempotencyRecord) -> None:
        with self._lock:
            self._simulation_idempotency[record.idempotency_key] = copy_record(record)

    def get_memo_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[ProposalMemoIdempotencyRecord]:
        with self._lock:
            record = self._memo_idempotency.get(idempotency_key)
            return copy_optional(record)

    def save_memo_idempotency(self, record: ProposalMemoIdempotencyRecord) -> None:
        with self._lock:
            existing = self._memo_idempotency.get(record.idempotency_key)
            if existing is not None:
                request_changed = existing.request_hash != record.request_hash
                memo_changed = existing.memo_id != record.memo_id
                if request_changed or memo_changed:
                    raise ValueError("MEMO_IDEMPOTENCY_KEY_CONFLICT")
                return
            self._memo_idempotency[record.idempotency_key] = copy_record(record)

    def create_memo(self, memo: ProposalMemoRecord) -> None:
        with self._lock:
            proposal_version_key = (memo.proposal_id, memo.proposal_version_no)
            existing_memo_id = self._memo_by_proposal_version.get(proposal_version_key)
            if existing_memo_id is not None and existing_memo_id != memo.memo_id:
                raise ValueError("MEMO_PROPOSAL_VERSION_CONFLICT")
            if memo.memo_id in self._memos:
                existing = self._memos[memo.memo_id]
                if existing.memo_hash != memo.memo_hash:
                    raise ValueError("MEMO_HASH_CONFLICT")
                return
            self._memos[memo.memo_id] = copy_record(memo)
            self._memo_by_proposal_version[proposal_version_key] = memo.memo_id

    def create_memo_with_idempotency_event(
        self,
        *,
        memo: ProposalMemoRecord,
        idempotency: Optional[ProposalMemoIdempotencyRecord],
        event: ProposalMemoEventRecord,
    ) -> None:
        memo_copy = copy_record(memo)
        idempotency_copy = copy_optional(idempotency)
        event_copy = copy_record(event)
        with self._lock:
            self._validate_memo_write(memo=memo, idempotency=idempotency)
            self._store_memo_if_absent(memo=memo, memo_copy=memo_copy)
            self._store_memo_idempotency_if_absent(
                idempotency=idempotency,
                idempotency_copy=idempotency_copy,
            )
            self._append_memo_event_if_absent(event=event, event_copy=event_copy)

    def _validate_memo_write(
        self,
        *,
        memo: ProposalMemoRecord,
        idempotency: Optional[ProposalMemoIdempotencyRecord],
    ) -> None:
        proposal_version_key = (memo.proposal_id, memo.proposal_version_no)
        existing_memo_id = self._memo_by_proposal_version.get(proposal_version_key)
        if existing_memo_id is not None and existing_memo_id != memo.memo_id:
            raise ValueError("MEMO_PROPOSAL_VERSION_CONFLICT")
        existing_memo = self._memos.get(memo.memo_id)
        if existing_memo is not None and existing_memo.memo_hash != memo.memo_hash:
            raise ValueError("MEMO_HASH_CONFLICT")
        if idempotency is not None:
            self._validate_memo_idempotency_write(idempotency)

    def _validate_memo_idempotency_write(
        self,
        idempotency: ProposalMemoIdempotencyRecord,
    ) -> None:
        existing = self._memo_idempotency.get(idempotency.idempotency_key)
        if existing is None:
            return
        request_changed = existing.request_hash != idempotency.request_hash
        memo_changed = existing.memo_id != idempotency.memo_id
        if request_changed or memo_changed:
            raise ValueError("MEMO_IDEMPOTENCY_KEY_CONFLICT")

    def _store_memo_if_absent(
        self,
        *,
        memo: ProposalMemoRecord,
        memo_copy: ProposalMemoRecord,
    ) -> None:
        if memo.memo_id in self._memos:
            return
        proposal_version_key = (memo.proposal_id, memo.proposal_version_no)
        self._memos[memo.memo_id] = memo_copy
        self._memo_by_proposal_version[proposal_version_key] = memo.memo_id

    def _store_memo_idempotency_if_absent(
        self,
        *,
        idempotency: Optional[ProposalMemoIdempotencyRecord],
        idempotency_copy: Optional[ProposalMemoIdempotencyRecord],
    ) -> None:
        if idempotency is None or idempotency_copy is None:
            return
        self._memo_idempotency.setdefault(idempotency.idempotency_key, idempotency_copy)

    def _append_memo_event_if_absent(
        self,
        *,
        event: ProposalMemoEventRecord,
        event_copy: ProposalMemoEventRecord,
    ) -> None:
        events = self._memo_events.setdefault(event.memo_id, [])
        if not any(existing.event_id == event.event_id for existing in events):
            events.append(event_copy)

    def get_memo(self, *, memo_id: str) -> Optional[ProposalMemoRecord]:
        with self._lock:
            memo = self._memos.get(memo_id)
            return copy_optional(memo)

    def get_memo_by_proposal_version(
        self, *, proposal_id: str, proposal_version_no: int
    ) -> Optional[ProposalMemoRecord]:
        with self._lock:
            memo_id = self._memo_by_proposal_version.get((proposal_id, proposal_version_no))
            if memo_id is None:
                return None
            memo = self._memos.get(memo_id)
            return copy_optional(memo)

    def list_memos(self, *, proposal_id: str) -> list[ProposalMemoRecord]:
        with self._lock:
            memos = list(self._memos.values())
        return ordered_memos_for_proposal(memos, proposal_id=proposal_id)

    def list_memos_for_proposals(self, *, proposal_ids: list[str]) -> list[ProposalMemoRecord]:
        with self._lock:
            memos = list(self._memos.values())
        return ordered_memos_for_proposals(memos, proposal_ids=proposal_ids)

    def append_memo_event(self, event: ProposalMemoEventRecord) -> None:
        with self._lock:
            events = self._memo_events.setdefault(event.memo_id, [])
            if any(existing.event_id == event.event_id for existing in events):
                return
            events.append(copy_record(event))

    def list_memo_events(self, *, memo_id: str) -> list[ProposalMemoEventRecord]:
        with self._lock:
            events = self._memo_events.get(memo_id, [])
        return ordered_memo_events(events)

    def get_cockpit_acknowledgement(
        self, *, action_item_id: str
    ) -> Optional[CockpitAcknowledgementRecord]:
        with self._lock:
            record = self._cockpit_acknowledgements.get(action_item_id)
            return copy_optional(record)

    def list_cockpit_acknowledgements(
        self, *, action_item_ids: list[str]
    ) -> dict[str, CockpitAcknowledgementRecord]:
        with self._lock:
            return {
                action_item_id: copy_record(record)
                for action_item_id in dict.fromkeys(action_item_ids)
                if (record := self._cockpit_acknowledgements.get(action_item_id)) is not None
            }

    def save_cockpit_acknowledgement_with_idempotency(
        self,
        *,
        acknowledgement: CockpitAcknowledgementRecord,
        idempotency: CockpitAcknowledgementIdempotencyRecord,
    ) -> None:
        with self._lock:
            existing = self._cockpit_acknowledgement_idempotency.get(idempotency.idempotency_key)
            if existing is not None:
                if (
                    existing.request_hash != idempotency.request_hash
                    or existing.acknowledgement_id != idempotency.acknowledgement_id
                    or existing.action_item_id != idempotency.action_item_id
                ):
                    raise ValueError("COCKPIT_ACKNOWLEDGEMENT_IDEMPOTENCY_KEY_CONFLICT")
                return
            self._cockpit_acknowledgement_idempotency[idempotency.idempotency_key] = copy_record(
                idempotency
            )
            self._cockpit_acknowledgements[acknowledgement.action_item_id] = copy_record(
                acknowledgement
            )

    def get_cockpit_acknowledgement_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[CockpitAcknowledgementIdempotencyRecord]:
        with self._lock:
            record = self._cockpit_acknowledgement_idempotency.get(idempotency_key)
            return copy_optional(record)

    def create_operation(self, operation: ProposalAsyncOperationRecord) -> None:
        with self._lock:
            self._operations[operation.operation_id] = copy_record(operation)
            self._operation_by_correlation[operation.correlation_id] = operation.operation_id
            if operation.idempotency_key:
                self._operation_by_idempotency[operation.idempotency_key] = operation.operation_id

    def create_operation_if_absent_by_idempotency(
        self, operation: ProposalAsyncOperationRecord
    ) -> tuple[ProposalAsyncOperationRecord, bool]:
        with self._lock:
            if operation.idempotency_key:
                existing_operation_id = self._operation_by_idempotency.get(
                    operation.idempotency_key
                )
                if existing_operation_id is not None:
                    existing = self._operations.get(existing_operation_id)
                    if existing is not None:
                        return copy_record(existing), False
            self._operations[operation.operation_id] = copy_record(operation)
            self._operation_by_correlation[operation.correlation_id] = operation.operation_id
            if operation.idempotency_key:
                self._operation_by_idempotency[operation.idempotency_key] = operation.operation_id
            return copy_record(operation), True

    def update_operation(self, operation: ProposalAsyncOperationRecord) -> None:
        with self._lock:
            self._operations[operation.operation_id] = copy_record(operation)
            self._operation_by_correlation[operation.correlation_id] = operation.operation_id
            if operation.idempotency_key:
                self._operation_by_idempotency[operation.idempotency_key] = operation.operation_id

    def get_operation(self, *, operation_id: str) -> Optional[ProposalAsyncOperationRecord]:
        with self._lock:
            operation = self._operations.get(operation_id)
            return copy_optional(operation)

    def get_operation_by_correlation(
        self, *, correlation_id: str
    ) -> Optional[ProposalAsyncOperationRecord]:
        with self._lock:
            operation_id = self._operation_by_correlation.get(correlation_id)
            if operation_id is None:
                return None
            operation = self._operations.get(operation_id)
            return copy_optional(operation)

    def get_operation_by_idempotency(
        self, *, idempotency_key: str
    ) -> Optional[ProposalAsyncOperationRecord]:
        with self._lock:
            operation_id = self._operation_by_idempotency.get(idempotency_key)
            if operation_id is None:
                return None
            operation = self._operations.get(operation_id)
            return copy_optional(operation)

    def list_recoverable_operations(
        self, *, as_of: datetime, limit: Optional[int] = None
    ) -> list[ProposalAsyncOperationRecord]:
        with self._lock:
            operations = list(self._operations.values())
        return recoverable_operations(operations, as_of=as_of, limit=limit)

    def list_operations_for_control(
        self, *, as_of: datetime, limit: Optional[int] = None
    ) -> list[ProposalAsyncOperationRecord]:
        del as_of
        with self._lock:
            operations = list(self._operations.values())
        return control_operations(operations, limit=limit)

    def create_proposal(self, proposal: ProposalRecord) -> None:
        with self._lock:
            self._proposals[proposal.proposal_id] = copy_record(proposal)

    def create_proposal_with_version_event_idempotency(
        self,
        *,
        proposal: ProposalRecord,
        version: ProposalVersionRecord,
        event: ProposalWorkflowEventRecord,
        idempotency: ProposalIdempotencyRecord,
    ) -> None:
        proposal_copy = copy_record(proposal)
        version_copy = copy_record(version)
        event_copy = copy_record(event)
        idempotency_copy = copy_record(idempotency)
        with self._lock:
            self._proposals[proposal.proposal_id] = proposal_copy
            self._versions[(version.proposal_id, version.version_no)] = version_copy
            self._events.setdefault(event.proposal_id, []).append(event_copy)
            self._idempotency[idempotency.idempotency_key] = idempotency_copy

    def update_proposal(self, proposal: ProposalRecord) -> None:
        with self._lock:
            self._proposals[proposal.proposal_id] = copy_record(proposal)

    def get_proposal(self, *, proposal_id: str) -> Optional[ProposalRecord]:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            return copy_optional(proposal)

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
        with self._lock:
            rows = list(self._proposals.values())
        return filtered_proposal_page(
            rows,
            portfolio_id=portfolio_id,
            state=state,
            created_by=created_by,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            cursor=cursor,
        )

    def create_version(self, version: ProposalVersionRecord) -> None:
        with self._lock:
            self._versions[(version.proposal_id, version.version_no)] = copy_record(version)

    def get_version(self, *, proposal_id: str, version_no: int) -> Optional[ProposalVersionRecord]:
        with self._lock:
            version = self._versions.get((proposal_id, version_no))
            return copy_optional(version)

    def list_versions(self, *, proposal_id: str) -> list[ProposalVersionRecord]:
        with self._lock:
            versions = list(self._versions.values())
        return ordered_versions_for_proposal(versions, proposal_id=proposal_id)

    def get_current_version(self, *, proposal_id: str) -> Optional[ProposalVersionRecord]:
        with self._lock:
            versions = list(self._versions.values())
        return current_version_for_proposal(versions, proposal_id=proposal_id)

    def append_event(self, event: ProposalWorkflowEventRecord) -> None:
        with self._lock:
            events = self._events.setdefault(event.proposal_id, [])
            events.append(copy_record(event))

    def list_events(self, *, proposal_id: str) -> list[ProposalWorkflowEventRecord]:
        with self._lock:
            events = self._events.get(proposal_id, [])
            return copy_records(events)

    def list_events_for_proposals(
        self, *, proposal_ids: list[str]
    ) -> list[ProposalWorkflowEventRecord]:
        with self._lock:
            event_groups = list(self._events.values())
        return ordered_events_for_proposals(event_groups, proposal_ids=proposal_ids)

    def create_approval(self, approval: ProposalApprovalRecordData) -> None:
        with self._lock:
            approvals = self._approvals.setdefault(approval.proposal_id, [])
            approvals.append(copy_record(approval))

    def list_approvals(self, *, proposal_id: str) -> list[ProposalApprovalRecordData]:
        with self._lock:
            approvals = self._approvals.get(proposal_id, [])
            return copy_records(approvals)

    def list_approvals_for_proposals(
        self, *, proposal_ids: list[str]
    ) -> list[ProposalApprovalRecordData]:
        with self._lock:
            approval_groups = list(self._approvals.values())
        return ordered_approvals_for_proposals(approval_groups, proposal_ids=proposal_ids)

    def transition_proposal(
        self,
        *,
        proposal: ProposalRecord,
        event: ProposalWorkflowEventRecord,
        approval: Optional[ProposalApprovalRecordData],
        expected_current_state: Optional[ProposalWorkflowState] = None,
        expected_current_version_no: Optional[int] = None,
    ) -> ProposalTransitionResult:
        with self._lock:
            current = self._proposals.get(proposal.proposal_id)
            if (
                expected_current_state is not None
                and expected_current_version_no is not None
                and (
                    current is None
                    or current.current_state != expected_current_state
                    or current.current_version_no != expected_current_version_no
                )
            ):
                raise ProposalStateConflictError(
                    "STATE_CONFLICT: proposal aggregate changed during transition"
                )
            self._events.setdefault(event.proposal_id, []).append(copy_record(event))
            if approval is not None:
                self._approvals.setdefault(approval.proposal_id, []).append(copy_record(approval))
            self._proposals[proposal.proposal_id] = copy_record(proposal)

        return ProposalTransitionResult(
            proposal=copy_record(proposal),
            event=copy_record(event),
            approval=copy_optional(approval),
        )
