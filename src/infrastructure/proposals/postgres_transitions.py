from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from typing import Any, Callable

from src.core.proposals.contract_types import ProposalWorkflowState
from src.core.proposals.exceptions import ProposalStateConflictError
from src.core.proposals.models import (
    ProposalApprovalRecordData,
    ProposalRecord,
    ProposalTransitionResult,
    ProposalWorkflowEventRecord,
)
from src.infrastructure.proposals import postgres_approvals as _approvals
from src.infrastructure.proposals import postgres_records as _records
from src.infrastructure.proposals import postgres_workflow_events as _workflow_events


def transition_proposal(
    *,
    connect: Callable[[], Any],
    proposal: ProposalRecord,
    event: ProposalWorkflowEventRecord,
    approval: ProposalApprovalRecordData | None,
    expected_current_state: ProposalWorkflowState | None,
    expected_current_version_no: int | None,
) -> ProposalTransitionResult:
    with closing(connect()) as connection:
        if expected_current_state is None or expected_current_version_no is None:
            _records.upsert_proposal(connection=connection, proposal=proposal)
        elif not _records.update_proposal_if_current(
            connection=connection,
            proposal=proposal,
            expected_current_state=expected_current_state,
            expected_current_version_no=expected_current_version_no,
        ):
            connection.rollback()
            raise ProposalStateConflictError(
                "STATE_CONFLICT: proposal aggregate changed during transition"
            )
        _workflow_events.insert_event(connection=connection, event=event)
        if approval is not None:
            _approvals.insert_approval(connection=connection, approval=approval)
        connection.commit()

    return ProposalTransitionResult(
        proposal=deepcopy(proposal),
        event=deepcopy(event),
        approval=deepcopy(approval) if approval is not None else None,
    )
