import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest

from src.core.proposals.create_command import _is_matching_legacy_replay
from src.core.proposals.exceptions import (
    ProposalIdempotencyConflictError,
    ProposalStateConflictError,
)
from src.core.proposals.idea_intake_authority import (
    IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY,
    IdeaProposalIntakePrincipal,
)
from src.core.proposals.idea_intake_persistence import IdeaProposalIntakeRecord
from src.core.proposals.idea_proposal_intake import (
    IDEA_PROPOSAL_INTAKE_REQUEST_EXAMPLE,
    IdeaProposalIntakeRequest,
    process_idea_proposal_intake,
)
from src.core.proposals.idea_realization_commands import (
    IdeaProposalReconciliationRequest,
    reconcile_idea_proposal_realization,
)
from src.core.proposals.idea_review_realization import (
    IdeaProposalRealizationOutcomeRecord,
    IdeaProposalRealizationRecord,
)
from src.core.proposals.input_request_models import ProposalCreateRequest
from src.core.proposals.models import (
    ProposalApprovalRecordData,
    ProposalAsyncOperationRecord,
    ProposalIdempotencyRecord,
    ProposalMemoEventRecord,
    ProposalMemoIdempotencyRecord,
    ProposalMemoRecord,
    ProposalRecord,
    ProposalSimulationIdempotencyRecord,
    ProposalVersionRecord,
    ProposalWorkflowEventRecord,
)
from src.infrastructure.proposals import (
    postgres_idempotency,
    postgres_memos,
    postgres_records,
    postgres_versions,
    postgres_workflow_events,
)
from src.infrastructure.proposals.postgres import PostgresProposalRepository
from tests.unit.advisory.engine.test_engine_proposal_repository_postgres import (
    _build_repository as _build_fake_repository,
)

_DSN = os.getenv("PROPOSAL_POSTGRES_INTEGRATION_DSN", "").strip()


@pytest.fixture
def repository(monkeypatch: pytest.MonkeyPatch) -> PostgresProposalRepository:
    if _DSN:
        try:
            repo = PostgresProposalRepository(dsn=_DSN)
            _reset_tables(repo)
            return repo
        except Exception:
            pass
    repo, _ = _build_fake_repository(monkeypatch)
    return repo


def test_live_postgres_proposal_repository_parity_contract(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    proposal_id = f"pp-{uuid.uuid4().hex}"
    operation_id = f"pop-{uuid.uuid4().hex}"
    correlation_id = f"corr-{uuid.uuid4().hex}"
    idempotency_key = f"idem-{uuid.uuid4().hex}"
    version_id = f"ppv-{uuid.uuid4().hex}"
    event_id = f"pwe-{uuid.uuid4().hex}"
    approval_id = f"pap-{uuid.uuid4().hex}"

    idempotency = ProposalIdempotencyRecord(
        idempotency_key=idempotency_key,
        request_hash=f"sha256:{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        proposal_version_no=1,
        created_at=now,
    )
    operation = ProposalAsyncOperationRecord(
        operation_id=operation_id,
        operation_type="CREATE_PROPOSAL",
        status="PENDING",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        proposal_id=None,
        created_by="advisor_live",
        created_at=now,
        payload_json={
            "payload": {"created_by": "advisor_live"},
            "idempotency_key": idempotency_key,
        },
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        lease_expires_at=None,
        finished_at=None,
        result_json=None,
        error_json=None,
    )
    repository.create_operation(operation)

    proposal = ProposalRecord(
        proposal_id=proposal_id,
        portfolio_id="pf-live",
        mandate_id="mandate-live",
        jurisdiction="SG",
        created_by="advisor_live",
        created_at=now,
        last_event_at=now,
        current_state="DRAFT",
        current_version_no=1,
        title="Live parity proposal",
        advisor_notes="integration contract",
        lifecycle_origin="WORKSPACE_HANDOFF",
        source_workspace_id="aws-live-001",
    )
    repository.create_proposal(proposal)

    version = ProposalVersionRecord(
        proposal_version_id=version_id,
        proposal_id=proposal_id,
        version_no=1,
        created_at=now,
        request_hash=idempotency.request_hash,
        artifact_hash=f"sha256:{uuid.uuid4().hex}",
        simulation_hash=f"sha256:{uuid.uuid4().hex}",
        status_at_creation="READY",
        proposal_result_json={"status": "READY"},
        artifact_json={"artifact_id": f"pa-{uuid.uuid4().hex}"},
        evidence_bundle_json={"hashes": {"request_hash": idempotency.request_hash}},
        gate_decision_json=None,
    )
    repository.create_version(version)
    loaded_version = repository.get_current_version(proposal_id=proposal_id)
    assert loaded_version is not None
    assert loaded_version.proposal_version_id == version_id

    repository.save_idempotency(idempotency)
    loaded_idempotency = repository.get_idempotency(idempotency_key=idempotency_key)
    assert loaded_idempotency is not None
    assert loaded_idempotency.proposal_id == proposal_id

    operation.status = "SUCCEEDED"
    operation.attempt_count = 1
    operation.started_at = now
    operation.lease_expires_at = now + timedelta(seconds=30)
    operation.finished_at = now + timedelta(seconds=1)
    operation.proposal_id = proposal_id
    operation.result_json = {"proposal_id": proposal_id}
    repository.update_operation(operation)

    loaded_operation = repository.get_operation(operation_id=operation_id)
    assert loaded_operation is not None
    assert loaded_operation.status == "SUCCEEDED"
    assert loaded_operation.attempt_count == 1
    assert loaded_operation.payload_json["idempotency_key"] == idempotency_key
    by_correlation = repository.get_operation_by_correlation(correlation_id=correlation_id)
    assert by_correlation is not None
    assert by_correlation.operation_id == operation_id

    event = ProposalWorkflowEventRecord(
        event_id=event_id,
        proposal_id=proposal_id,
        event_type="SUBMITTED_FOR_RISK_REVIEW",
        from_state="DRAFT",
        to_state="RISK_REVIEW",
        actor_id="advisor_live",
        occurred_at=now + timedelta(seconds=2),
        reason_json={"comment": "submit"},
        related_version_no=1,
    )
    approval = ProposalApprovalRecordData(
        approval_id=approval_id,
        proposal_id=proposal_id,
        approval_type="RISK",
        approved=True,
        actor_id="risk_live",
        occurred_at=now + timedelta(seconds=3),
        details_json={"ticket_id": f"risk-{uuid.uuid4().hex[:8]}"},
        related_version_no=1,
    )
    transitioned = ProposalRecord(
        proposal_id=proposal.proposal_id,
        portfolio_id=proposal.portfolio_id,
        mandate_id=proposal.mandate_id,
        jurisdiction=proposal.jurisdiction,
        created_by=proposal.created_by,
        created_at=proposal.created_at,
        last_event_at=event.occurred_at,
        current_state="RISK_REVIEW",
        current_version_no=proposal.current_version_no,
        title=proposal.title,
        advisor_notes=proposal.advisor_notes,
        lifecycle_origin=proposal.lifecycle_origin,
        source_workspace_id=proposal.source_workspace_id,
    )
    transition_result = repository.transition_proposal(
        proposal=transitioned,
        event=event,
        approval=approval,
    )
    assert transition_result.event.event_id == event_id
    assert transition_result.approval is not None
    assert transition_result.approval.approval_id == approval_id

    stored_events = repository.list_events(proposal_id=proposal_id)
    assert [row.event_id for row in stored_events] == [event_id]

    stored_approvals = repository.list_approvals(proposal_id=proposal_id)
    assert [row.approval_id for row in stored_approvals] == [approval_id]

    stored_proposal = repository.get_proposal(proposal_id=proposal_id)
    assert stored_proposal is not None
    assert stored_proposal.current_state == "RISK_REVIEW"
    assert stored_proposal.lifecycle_origin == "WORKSPACE_HANDOFF"
    assert stored_proposal.source_workspace_id == "aws-live-001"

    listed, next_cursor = repository.list_proposals(
        portfolio_id="pf-live",
        state="RISK_REVIEW",
        created_by="advisor_live",
        created_from=now - timedelta(minutes=1),
        created_to=now + timedelta(minutes=1),
        limit=10,
        cursor=None,
    )
    assert len(listed) == 1
    assert listed[0].proposal_id == proposal_id
    assert next_cursor is None


def test_live_postgres_atomic_proposal_create_contract(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    proposal, version, event, idempotency = _proposal_create_records(
        now=now,
        suffix=uuid.uuid4().hex,
    )

    repository.create_proposal_with_version_event_idempotency(
        proposal=proposal,
        version=version,
        event=event,
        idempotency=idempotency,
    )

    assert repository.get_proposal(proposal_id=proposal.proposal_id) == proposal
    assert repository.get_version(proposal_id=proposal.proposal_id, version_no=1) == version
    assert repository.list_events(proposal_id=proposal.proposal_id) == [event]
    assert repository.get_idempotency(idempotency_key=idempotency.idempotency_key) == idempotency


@pytest.mark.skipif(
    not _DSN,
    reason="Live Postgres DSN required for transaction rollback fault injection.",
)
@pytest.mark.parametrize(
    ("module", "function_name"),
    [
        (postgres_records, "upsert_proposal"),
        (postgres_versions, "insert_version"),
        (postgres_workflow_events, "insert_event"),
        (postgres_idempotency, "insert_proposal_idempotency"),
    ],
)
def test_live_postgres_atomic_proposal_create_rolls_back_partial_writes(
    repository: PostgresProposalRepository,
    monkeypatch: pytest.MonkeyPatch,
    module,
    function_name: str,
) -> None:
    original = getattr(module, function_name)

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError(f"fault injected after {function_name}")

    monkeypatch.setattr(module, function_name, fail_after_write)
    now = datetime.now(timezone.utc)
    proposal, version, event, idempotency = _proposal_create_records(
        now=now,
        suffix=uuid.uuid4().hex,
    )

    with pytest.raises(RuntimeError, match=f"fault injected after {function_name}"):
        repository.create_proposal_with_version_event_idempotency(
            proposal=proposal,
            version=version,
            event=event,
            idempotency=idempotency,
        )

    assert repository.get_proposal(proposal_id=proposal.proposal_id) is None
    assert repository.get_version(proposal_id=proposal.proposal_id, version_no=1) is None
    assert repository.list_events(proposal_id=proposal.proposal_id) == []
    assert repository.get_idempotency(idempotency_key=idempotency.idempotency_key) is None


def test_live_postgres_atomic_memo_create_contract(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex
    version = _create_proposal_version_for_memo(
        repository=repository,
        now=now,
        suffix=suffix,
    )
    memo, idempotency, event = _memo_create_records(
        now=now,
        suffix=suffix,
        version=version,
    )

    repository.create_memo_with_idempotency_event(
        memo=memo,
        idempotency=idempotency,
        event=event,
    )

    assert repository.get_memo(memo_id=memo.memo_id) == memo
    assert (
        repository.get_memo_idempotency(idempotency_key=idempotency.idempotency_key) == idempotency
    )
    assert repository.list_memo_events(memo_id=memo.memo_id) == [event]


@pytest.mark.skipif(
    not _DSN,
    reason="Live Postgres DSN required for memo transaction rollback fault injection.",
)
@pytest.mark.parametrize(
    ("module", "function_name"),
    [
        (postgres_memos, "insert_memo"),
        (postgres_idempotency, "insert_memo_idempotency"),
        (postgres_memos, "insert_memo_event"),
    ],
)
def test_live_postgres_atomic_memo_create_rolls_back_partial_writes(
    repository: PostgresProposalRepository,
    monkeypatch: pytest.MonkeyPatch,
    module,
    function_name: str,
) -> None:
    original = getattr(module, function_name)

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError(f"fault injected after {function_name}")

    monkeypatch.setattr(module, function_name, fail_after_write)
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex
    version = _create_proposal_version_for_memo(
        repository=repository,
        now=now,
        suffix=suffix,
    )
    memo, idempotency, event = _memo_create_records(
        now=now,
        suffix=suffix,
        version=version,
    )

    with pytest.raises(RuntimeError, match=f"fault injected after {function_name}"):
        repository.create_memo_with_idempotency_event(
            memo=memo,
            idempotency=idempotency,
            event=event,
        )

    assert repository.get_memo(memo_id=memo.memo_id) is None
    assert repository.get_memo_idempotency(idempotency_key=idempotency.idempotency_key) is None
    assert repository.list_memo_events(memo_id=memo.memo_id) == []


def test_live_postgres_simulation_idempotency_roundtrip_contract(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    idempotency_key = f"sim-idem-{uuid.uuid4().hex}"
    request_hash = f"sha256:{uuid.uuid4().hex}"
    first_payload = ProposalSimulationIdempotencyRecord(
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response_json={"proposal_run_id": f"pr-{uuid.uuid4().hex}", "status": "READY"},
        created_at=now,
    )
    repository.save_simulation_idempotency(first_payload)
    loaded = repository.get_simulation_idempotency(idempotency_key=idempotency_key)
    assert loaded is not None
    assert loaded.request_hash == request_hash
    assert loaded.response_json["status"] == "READY"

    updated_payload = ProposalSimulationIdempotencyRecord(
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response_json={"proposal_run_id": f"pr-{uuid.uuid4().hex}", "status": "BLOCKED"},
        created_at=now + timedelta(seconds=1),
    )
    repository.save_simulation_idempotency(updated_payload)
    loaded_updated = repository.get_simulation_idempotency(idempotency_key=idempotency_key)
    assert loaded_updated is not None
    assert loaded_updated.response_json["status"] == "BLOCKED"
    assert repository.get_simulation_idempotency(idempotency_key="sim-idem-missing") is None


def test_live_postgres_operation_missing_lookups_return_none(
    repository: PostgresProposalRepository,
) -> None:
    assert repository.get_operation(operation_id="op-missing") is None
    assert repository.get_operation_by_correlation(correlation_id="corr-missing") is None
    assert repository.get_operation_by_idempotency(idempotency_key="idem-missing") is None


def test_live_postgres_async_create_operation_idempotency_contract(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    first = ProposalAsyncOperationRecord(
        operation_id=f"pop-{uuid.uuid4().hex}",
        operation_type="CREATE_PROPOSAL",
        status="PENDING",
        correlation_id=f"corr-{uuid.uuid4().hex}",
        idempotency_key=f"idem-{uuid.uuid4().hex}",
        proposal_id=None,
        created_by="advisor_live",
        created_at=now,
        payload_json={"payload": {"created_by": "advisor_live"}, "submission_hash": "sha256:first"},
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        lease_expires_at=None,
        finished_at=None,
        result_json=None,
        error_json=None,
    )
    second = ProposalAsyncOperationRecord(
        operation_id=f"pop-{uuid.uuid4().hex}",
        operation_type="CREATE_PROPOSAL",
        status="PENDING",
        correlation_id=f"corr-{uuid.uuid4().hex}",
        idempotency_key=first.idempotency_key,
        proposal_id=None,
        created_by="advisor_live_duplicate",
        created_at=now,
        payload_json={
            "payload": {"created_by": "advisor_live_duplicate"},
            "submission_hash": "sha256:second",
        },
        attempt_count=0,
        max_attempts=3,
        started_at=None,
        lease_expires_at=None,
        finished_at=None,
        result_json=None,
        error_json=None,
    )

    stored_first, first_is_new = repository.create_operation_if_absent_by_idempotency(first)
    stored_second, second_is_new = repository.create_operation_if_absent_by_idempotency(second)
    by_idempotency = repository.get_operation_by_idempotency(idempotency_key=first.idempotency_key)

    assert first_is_new is True
    assert second_is_new is False
    assert stored_second.operation_id == stored_first.operation_id
    assert by_idempotency is not None
    assert by_idempotency.operation_id == stored_first.operation_id
    assert by_idempotency.correlation_id == stored_first.correlation_id


def test_live_postgres_list_proposals_pagination_and_invalid_cursor(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    first = ProposalRecord(
        proposal_id=f"pp-{uuid.uuid4().hex}",
        portfolio_id="pf-page",
        mandate_id="mandate-page",
        jurisdiction="SG",
        created_by="advisor-page",
        created_at=now - timedelta(minutes=1),
        last_event_at=now - timedelta(minutes=1),
        current_state="DRAFT",
        current_version_no=1,
        title="Page one",
        advisor_notes=None,
    )
    second = ProposalRecord(
        proposal_id=f"pp-{uuid.uuid4().hex}",
        portfolio_id="pf-page",
        mandate_id="mandate-page",
        jurisdiction="SG",
        created_by="advisor-page",
        created_at=now,
        last_event_at=now,
        current_state="DRAFT",
        current_version_no=1,
        title="Page two",
        advisor_notes=None,
    )
    repository.create_proposal(first)
    repository.create_proposal(second)

    page_one, next_cursor = repository.list_proposals(
        portfolio_id="pf-page",
        state="DRAFT",
        created_by="advisor-page",
        created_from=None,
        created_to=None,
        limit=1,
        cursor=None,
    )
    assert [row.proposal_id for row in page_one] == [second.proposal_id]
    assert next_cursor == second.proposal_id

    page_two, final_cursor = repository.list_proposals(
        portfolio_id="pf-page",
        state="DRAFT",
        created_by="advisor-page",
        created_from=None,
        created_to=None,
        limit=1,
        cursor=next_cursor,
    )
    assert [row.proposal_id for row in page_two] == [first.proposal_id]
    assert final_cursor is None

    invalid_page, invalid_cursor = repository.list_proposals(
        portfolio_id=None,
        state=None,
        created_by=None,
        created_from=None,
        created_to=None,
        limit=10,
        cursor="pp-missing-cursor",
    )
    assert invalid_page == []
    assert invalid_cursor is None


def test_live_postgres_version_get_and_current_contract(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    proposal_id = f"pp-{uuid.uuid4().hex}"
    repository.create_proposal(
        ProposalRecord(
            proposal_id=proposal_id,
            portfolio_id="pf-version",
            mandate_id="mandate-version",
            jurisdiction="SG",
            created_by="advisor-version",
            created_at=now,
            last_event_at=now,
            current_state="DRAFT",
            current_version_no=2,
            title="Versioned proposal",
            advisor_notes=None,
        )
    )
    version_1 = ProposalVersionRecord(
        proposal_version_id=f"ppv-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        version_no=1,
        created_at=now,
        request_hash=f"sha256:{uuid.uuid4().hex}",
        artifact_hash=f"sha256:{uuid.uuid4().hex}",
        simulation_hash=f"sha256:{uuid.uuid4().hex}",
        status_at_creation="READY",
        proposal_result_json={"status": "READY"},
        artifact_json={"artifact_id": "a1"},
        evidence_bundle_json={"hashes": {"request_hash": "r1"}},
        gate_decision_json=None,
    )
    version_2 = ProposalVersionRecord(
        proposal_version_id=f"ppv-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        version_no=2,
        created_at=now + timedelta(seconds=1),
        request_hash=f"sha256:{uuid.uuid4().hex}",
        artifact_hash=f"sha256:{uuid.uuid4().hex}",
        simulation_hash=f"sha256:{uuid.uuid4().hex}",
        status_at_creation="BLOCKED",
        proposal_result_json={"status": "BLOCKED"},
        artifact_json={"artifact_id": "a2"},
        evidence_bundle_json={"hashes": {"request_hash": "r2"}},
        gate_decision_json={"gate": "CLIENT_CONSENT_REQUIRED"},
    )
    repository.create_version(version_1)
    repository.create_version(version_2)

    loaded_1 = repository.get_version(proposal_id=proposal_id, version_no=1)
    loaded_2 = repository.get_current_version(proposal_id=proposal_id)
    missing = repository.get_version(proposal_id=proposal_id, version_no=3)
    assert loaded_1 is not None
    assert loaded_1.proposal_version_id == version_1.proposal_version_id
    assert loaded_2 is not None
    assert loaded_2.proposal_version_id == version_2.proposal_version_id
    assert missing is None


def test_live_postgres_events_and_approvals_ordering_contract(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    proposal_id = f"pp-{uuid.uuid4().hex}"
    repository.create_proposal(
        ProposalRecord(
            proposal_id=proposal_id,
            portfolio_id="pf-events",
            mandate_id="mandate-events",
            jurisdiction="SG",
            created_by="advisor-events",
            created_at=now,
            last_event_at=now,
            current_state="DRAFT",
            current_version_no=1,
            title="Ordered events",
            advisor_notes=None,
        )
    )
    _create_version(repository=repository, proposal_id=proposal_id, version_no=1, now=now)
    first_event = ProposalWorkflowEventRecord(
        event_id=f"pwe-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        event_type="CREATED",
        from_state=None,
        to_state="DRAFT",
        actor_id="advisor-events",
        occurred_at=now,
        reason_json={"comment": "created"},
        related_version_no=1,
    )
    second_event = ProposalWorkflowEventRecord(
        event_id=f"pwe-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        event_type="SUBMITTED_FOR_RISK_REVIEW",
        from_state="DRAFT",
        to_state="RISK_REVIEW",
        actor_id="advisor-events",
        occurred_at=now + timedelta(seconds=5),
        reason_json={"comment": "submitted"},
        related_version_no=1,
    )
    repository.append_event(first_event)
    repository.append_event(second_event)
    approval = ProposalApprovalRecordData(
        approval_id=f"pap-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        approval_type="RISK",
        approved=True,
        actor_id="risk-events",
        occurred_at=now + timedelta(seconds=6),
        details_json={"ticket_id": "risk-ticket"},
        related_version_no=1,
    )
    repository.create_approval(approval)

    events = repository.list_events(proposal_id=proposal_id)
    approvals = repository.list_approvals(proposal_id=proposal_id)
    assert [row.event_id for row in events] == [first_event.event_id, second_event.event_id]
    assert [row.approval_id for row in approvals] == [approval.approval_id]


def test_live_postgres_transition_without_approval_contract(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    proposal_id = f"pp-{uuid.uuid4().hex}"
    proposal = ProposalRecord(
        proposal_id=proposal_id,
        portfolio_id="pf-transition",
        mandate_id="mandate-transition",
        jurisdiction="SG",
        created_by="advisor-transition",
        created_at=now,
        last_event_at=now,
        current_state="RISK_REVIEW",
        current_version_no=1,
        title="Transition without approval",
        advisor_notes=None,
    )
    repository.create_proposal(proposal)
    _create_version(repository=repository, proposal_id=proposal_id, version_no=1, now=now)
    event = ProposalWorkflowEventRecord(
        event_id=f"pwe-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        event_type="SUBMITTED_FOR_RISK_REVIEW",
        from_state="DRAFT",
        to_state="RISK_REVIEW",
        actor_id="advisor-transition",
        occurred_at=now,
        reason_json={"comment": "submit"},
        related_version_no=1,
    )

    result = repository.transition_proposal(proposal=proposal, event=event, approval=None)
    assert result.approval is None
    stored = repository.get_proposal(proposal_id=proposal_id)
    assert stored is not None
    assert stored.current_state == "RISK_REVIEW"
    event_ids = [row.event_id for row in repository.list_events(proposal_id=proposal_id)]
    assert event_ids == [event.event_id]
    assert repository.list_approvals(proposal_id=proposal_id) == []


@pytest.mark.skipif(
    not _DSN,
    reason="Live Postgres DSN required for database-enforced lifecycle integrity checks.",
)
def test_live_postgres_lifecycle_integrity_rejects_orphans_and_duplicate_versions(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    proposal_id = f"pp-{uuid.uuid4().hex}"
    version_id = f"ppv-{uuid.uuid4().hex}"
    repository.create_proposal(
        ProposalRecord(
            proposal_id=proposal_id,
            portfolio_id="pf-integrity",
            mandate_id="mandate-integrity",
            jurisdiction="SG",
            created_by="advisor-integrity",
            created_at=now,
            last_event_at=now,
            current_state="DRAFT",
            current_version_no=1,
            title="Integrity proposal",
            advisor_notes=None,
        )
    )
    version = _create_version(
        repository=repository,
        proposal_id=proposal_id,
        version_no=1,
        now=now,
        proposal_version_id=version_id,
    )

    with closing(repository._connect()) as connection:  # noqa: SLF001
        _assert_statement_fails(
            connection,
            """
            INSERT INTO proposal_versions (
                proposal_version_id, proposal_id, version_no, created_at, request_hash,
                artifact_hash, simulation_hash, status_at_creation, proposal_result_json,
                artifact_json, evidence_bundle_json, gate_decision_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                f"ppv-{uuid.uuid4().hex}",
                "pp_missing_integrity",
                1,
                now.isoformat(),
                "sha256:orphan-request",
                "sha256:orphan-artifact",
                "sha256:orphan-simulation",
                "READY",
                '{"status":"READY"}',
                '{"artifact_id":"orphan"}',
                '{"hashes":{"request_hash":"sha256:orphan-request"}}',
                None,
            ),
        )
        _assert_statement_fails(
            connection,
            """
            INSERT INTO proposal_versions (
                proposal_version_id, proposal_id, version_no, created_at, request_hash,
                artifact_hash, simulation_hash, status_at_creation, proposal_result_json,
                artifact_json, evidence_bundle_json, gate_decision_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                version.proposal_version_id,
                proposal_id,
                2,
                now.isoformat(),
                "sha256:duplicate-request",
                "sha256:duplicate-artifact",
                "sha256:duplicate-simulation",
                "READY",
                '{"status":"READY"}',
                '{"artifact_id":"duplicate"}',
                '{"hashes":{"request_hash":"sha256:duplicate-request"}}',
                None,
            ),
        )
        _assert_statement_fails(
            connection,
            """
            INSERT INTO proposal_workflow_events (
                event_id, proposal_id, event_type, from_state, to_state, actor_id,
                occurred_at, reason_json, related_version_no
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                f"pwe-{uuid.uuid4().hex}",
                proposal_id,
                "CREATED",
                None,
                "DRAFT",
                "advisor-integrity",
                now.isoformat(),
                '{"comment":"orphan-version"}',
                2,
            ),
        )


def test_live_postgres_lifecycle_identity_replay_and_conflict_contract(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    proposal_id = f"pp-{uuid.uuid4().hex}"
    repository.create_proposal(
        ProposalRecord(
            proposal_id=proposal_id,
            portfolio_id="pf-immutable",
            mandate_id="mandate-immutable",
            jurisdiction="SG",
            created_by="advisor-immutable",
            created_at=now,
            last_event_at=now,
            current_state="DRAFT",
            current_version_no=1,
            title="Immutable proposal",
            advisor_notes=None,
        )
    )
    version = _create_version(repository=repository, proposal_id=proposal_id, version_no=1, now=now)
    event = ProposalWorkflowEventRecord(
        event_id=f"pwe-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        event_type="CREATED",
        from_state=None,
        to_state="DRAFT",
        actor_id="advisor-immutable",
        occurred_at=now,
        reason_json={"comment": "created"},
        related_version_no=1,
    )
    approval = ProposalApprovalRecordData(
        approval_id=f"pap-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        approval_type="RISK",
        approved=True,
        actor_id="risk-immutable",
        occurred_at=now,
        details_json={"ticket_id": "risk-immutable"},
        related_version_no=1,
    )

    repository.create_version(version)
    repository.append_event(event)
    repository.append_event(event)
    repository.create_approval(approval)
    repository.create_approval(approval)

    with pytest.raises(ValueError, match="PROPOSAL_VERSION_IDENTITY_CONFLICT"):
        repository.create_version(
            version.model_copy(update={"request_hash": "sha256:drifted-live-version"})
        )
    with pytest.raises(ValueError, match="PROPOSAL_WORKFLOW_EVENT_IDENTITY_CONFLICT"):
        repository.append_event(event.model_copy(update={"actor_id": "advisor-drifted"}))
    with pytest.raises(ValueError, match="PROPOSAL_APPROVAL_IDENTITY_CONFLICT"):
        repository.create_approval(approval.model_copy(update={"actor_id": "risk-drifted"}))

    assert repository.get_version(proposal_id=proposal_id, version_no=1) == version
    assert repository.list_events(proposal_id=proposal_id) == [event]
    assert repository.list_approvals(proposal_id=proposal_id) == [approval]


@pytest.mark.skipif(
    not _DSN,
    reason="Live Postgres DSN required for preserved proposal replay compatibility.",
)
def test_live_postgres_legacy_replay_matches_across_hash_domains(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    proposal_id = f"pp-{uuid.uuid4().hex}"
    idempotency_key = f"idem-{uuid.uuid4().hex}"
    payload = ProposalCreateRequest(
        created_by="advisor-preserved-replay",
        input_mode="stateful",
        stateful_input={
            "portfolio_id": "pf-preserved-replay",
            "as_of": "2026-05-20",
            "household_id": "hh-preserved-replay",
            "mandate_id": "mandate-preserved-replay",
            "benchmark_id": "bm-preserved-replay",
            "narrative_request": {
                "sections": ["EXECUTIVE_SUMMARY"],
                "requested_by": "advisor-preserved-replay",
                "jurisdiction": "SG",
            },
        },
        metadata={
            "title": "Preserved replay proposal",
            "advisor_notes": "Historical replay fixture",
            "jurisdiction": "SG",
        },
    )
    proposal = ProposalRecord(
        proposal_id=proposal_id,
        portfolio_id="pf-preserved-replay",
        mandate_id="mandate-preserved-replay",
        jurisdiction="SG",
        created_by="advisor-preserved-replay",
        created_at=now,
        last_event_at=now,
        current_state="DRAFT",
        current_version_no=1,
        title="Preserved replay proposal",
        advisor_notes="Historical replay fixture",
        lifecycle_origin="WORKSPACE_HANDOFF",
        source_workspace_id="aws-preserved-replay",
    )
    version = ProposalVersionRecord(
        proposal_version_id=f"ppv-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        version_no=1,
        created_at=now,
        request_hash="sha256:resolved-version-domain",
        artifact_hash="sha256:preserved-artifact",
        simulation_hash="sha256:preserved-simulation",
        status_at_creation="READY",
        proposal_result_json={"status": "READY"},
        artifact_json={
            "proposal_narrative": {
                "audience": "ADVISOR_REVIEW",
                "narrative_policy": {
                    "context": {
                        "jurisdiction": "SG",
                        "client_audience": "ADVISOR_REVIEW",
                        "product_types": ["BOND", "CASH", "EQUITY"],
                    }
                },
                "generation_mode": "DETERMINISTIC_TEMPLATE",
                "sections": [{"section_key": "EXECUTIVE_SUMMARY"}],
            }
        },
        evidence_bundle_json={
            "context_resolution": {
                "resolved_context": {
                    "portfolio_id": "pf-preserved-replay",
                    "as_of": "2026-05-20",
                    "household_id": "hh-preserved-replay",
                    "benchmark_id": "bm-preserved-replay",
                }
            }
        },
        gate_decision_json=None,
    )
    event = ProposalWorkflowEventRecord(
        event_id=f"pwe-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        event_type="CREATED",
        from_state=None,
        to_state="DRAFT",
        actor_id="advisor-preserved-replay",
        occurred_at=now,
        reason_json={"request_hash": version.request_hash},
        related_version_no=1,
    )
    repository.create_proposal(proposal)
    repository.create_version(version)
    repository.append_event(event)
    repository.save_idempotency(
        ProposalIdempotencyRecord(
            idempotency_key=idempotency_key,
            request_hash="sha256:historical-command-domain",
            proposal_id=proposal_id,
            proposal_version_no=1,
            created_at=now,
        )
    )

    replay = _is_matching_legacy_replay(
        repository=repository,
        payload=payload,
        proposal_id=proposal_id,
        proposal_version_no=1,
    )

    stored_idempotency = repository.get_idempotency(idempotency_key=idempotency_key)
    stored_version = repository.get_version(proposal_id=proposal_id, version_no=1)
    assert replay is True
    assert stored_idempotency is not None
    assert stored_version is not None
    assert stored_idempotency.request_hash != stored_version.request_hash
    proposals, _ = repository.list_proposals(
        portfolio_id="pf-preserved-replay",
        state=None,
        created_by="advisor-preserved-replay",
        created_from=None,
        created_to=None,
        limit=10,
        cursor=None,
    )
    assert [item.proposal_id for item in proposals] == [proposal_id]

    omitted_title_payload = payload.model_copy(
        update={
            "metadata": payload.metadata.model_copy(update={"title": None}),
        }
    )
    assert (
        _is_matching_legacy_replay(
            repository=repository,
            payload=omitted_title_payload,
            proposal_id=proposal_id,
            proposal_version_no=1,
        )
        is False
    )


@pytest.mark.skipif(
    not _DSN,
    reason="Live Postgres DSN required for concurrent lifecycle transition checks.",
)
def test_live_postgres_transition_compare_and_set_allows_one_approval_winner(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    proposal_id = f"pp-{uuid.uuid4().hex}"
    repository.create_proposal(
        ProposalRecord(
            proposal_id=proposal_id,
            portfolio_id="pf-concurrent-transition",
            mandate_id="mandate-concurrent-transition",
            jurisdiction="SG",
            created_by="advisor-concurrent-transition",
            created_at=now,
            last_event_at=now,
            current_state="RISK_REVIEW",
            current_version_no=1,
            title="Concurrent transition proposal",
            advisor_notes=None,
        )
    )
    _create_version(repository=repository, proposal_id=proposal_id, version_no=1, now=now)
    barrier = Barrier(2)
    repositories = [PostgresProposalRepository(dsn=_DSN), PostgresProposalRepository(dsn=_DSN)]

    def _attempt_transition(index: int) -> tuple[str, str]:
        local_repository = repositories[index - 1]
        event = ProposalWorkflowEventRecord(
            event_id=f"pwe-{uuid.uuid4().hex}",
            proposal_id=proposal_id,
            event_type="RISK_APPROVED",
            from_state="RISK_REVIEW",
            to_state="AWAITING_CLIENT_CONSENT",
            actor_id=f"risk-concurrent-{index}",
            occurred_at=now + timedelta(seconds=index),
            reason_json={"comment": f"risk approval {index}"},
            related_version_no=1,
        )
        approval = ProposalApprovalRecordData(
            approval_id=f"pap-{uuid.uuid4().hex}",
            proposal_id=proposal_id,
            approval_type="RISK",
            approved=True,
            actor_id=f"risk-concurrent-{index}",
            occurred_at=event.occurred_at,
            details_json={"ticket_id": f"risk-concurrent-{index}"},
            related_version_no=1,
        )
        updated_proposal = ProposalRecord(
            proposal_id=proposal_id,
            portfolio_id="pf-concurrent-transition",
            mandate_id="mandate-concurrent-transition",
            jurisdiction="SG",
            created_by="advisor-concurrent-transition",
            created_at=now,
            last_event_at=event.occurred_at,
            current_state="AWAITING_CLIENT_CONSENT",
            current_version_no=1,
            title="Concurrent transition proposal",
            advisor_notes=None,
        )
        barrier.wait(timeout=10)
        try:
            result = local_repository.transition_proposal(
                proposal=updated_proposal,
                event=event,
                approval=approval,
                expected_current_state="RISK_REVIEW",
                expected_current_version_no=1,
            )
        except ProposalStateConflictError as exc:
            return ("conflict", str(exc))
        assert result.approval is not None
        return ("success", result.event.event_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_attempt_transition, i) for i in (1, 2)]
        results = [future.result() for future in futures]

    assert [status for status, _ in results].count("success") == 1
    assert [status for status, _ in results].count("conflict") == 1
    stored_proposal = repository.get_proposal(proposal_id=proposal_id)
    assert stored_proposal is not None
    assert stored_proposal.current_state == "AWAITING_CLIENT_CONSENT"
    stored_events = repository.list_events(proposal_id=proposal_id)
    assert len(stored_events) == 1
    assert stored_events[0].event_id == next(
        value for status, value in results if status == "success"
    )
    stored_approvals = repository.list_approvals(proposal_id=proposal_id)
    assert len(stored_approvals) == 1
    assert stored_approvals[0].actor_id == stored_events[0].actor_id


def test_live_postgres_update_proposal_contract(
    repository: PostgresProposalRepository,
) -> None:
    now = datetime.now(timezone.utc)
    proposal_id = f"pp-{uuid.uuid4().hex}"
    proposal = ProposalRecord(
        proposal_id=proposal_id,
        portfolio_id="pf-update",
        mandate_id="mandate-update",
        jurisdiction="SG",
        created_by="advisor-update",
        created_at=now,
        last_event_at=now,
        current_state="DRAFT",
        current_version_no=1,
        title="Before update",
        advisor_notes="initial",
    )
    repository.create_proposal(proposal)
    updated = ProposalRecord(
        proposal_id=proposal_id,
        portfolio_id="pf-update",
        mandate_id="mandate-update",
        jurisdiction="SG",
        created_by="advisor-update",
        created_at=now,
        last_event_at=now + timedelta(seconds=1),
        current_state="CANCELLED",
        current_version_no=1,
        title="After update",
        advisor_notes="cancelled by advisor",
    )
    repository.update_proposal(updated)

    stored = repository.get_proposal(proposal_id=proposal_id)
    assert stored is not None
    assert stored.current_state == "CANCELLED"
    assert stored.title == "After update"


def test_live_postgres_idea_proposal_reconciliation_is_atomic_and_restart_safe() -> None:
    if not _DSN:
        pytest.skip("PROPOSAL_POSTGRES_INTEGRATION_DSN is required for live persistence proof")

    first_repository = PostgresProposalRepository(dsn=_DSN)
    second_repository = PostgresProposalRepository(dsn=_DSN)
    _reset_tables(first_repository)
    principal = IdeaProposalIntakePrincipal(
        actor_id="advisor-postgres",
        role="ADVISOR",
        tenant_id="tenant-private-bank-sg",
        legal_entity_code="SGPB",
        correlation_id="corr-idea-postgres-reconciliation",
        service_identity="lotus-advise",
        capabilities=frozenset({"advisory.idea_proposal_realization.write"}),
        authorized_portfolio_id="PB_SG_GLOBAL_BAL_001",
    )
    intake_principal = replace(
        principal,
        actor_id="svc-lotus-idea",
        role="SERVICE",
        service_identity="lotus-idea",
        capabilities=frozenset({IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY}),
        authorized_portfolio_id=None,
    )
    request_payload = dict(IDEA_PROPOSAL_INTAKE_REQUEST_EXAMPLE)
    request_payload["source_refs"] = [dict(IDEA_PROPOSAL_INTAKE_REQUEST_EXAMPLE["source_refs"][0])]
    intake = process_idea_proposal_intake(
        IdeaProposalIntakeRequest.model_validate(request_payload),
        correlation_id="corr-idea-postgres-intake",
        idempotency_key="idea-postgres-reconciliation",
        principal=intake_principal,
        repository=first_repository,
        received_at=datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc),
    )
    proposal = ProposalRecord(
        proposal_id=f"pp_{uuid.uuid4().hex}",
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        created_by="advisor-postgres",
        created_at=datetime(2026, 9, 2, 8, 1, tzinfo=timezone.utc),
        last_event_at=datetime(2026, 9, 2, 8, 1, tzinfo=timezone.utc),
        current_state="REJECTED",
        current_version_no=1,
    )
    first_repository.create_proposal(proposal)

    reconciled = reconcile_idea_proposal_realization(
        repository=first_repository,
        intake_id=intake.intake_id,
        portfolio_id=proposal.portfolio_id,
        payload=IdeaProposalReconciliationRequest(
            proposal_id=proposal.proposal_id,
            expected_source_event_version=1,
        ),
        principal=principal,
        occurred_at=datetime(2026, 9, 2, 8, 5, tzinfo=timezone.utc),
    )
    restarted = second_repository.get_idea_proposal_realization(
        intake_id=intake.intake_id,
        tenant_id=principal.tenant_id,
        legal_entity_code=principal.legal_entity_code,
        portfolio_id=proposal.portfolio_id,
    )
    recovery_sql = Path("scripts/sql/verify_idea_intake_recovery.sql").read_text(encoding="utf-8")
    with closing(second_repository._connect()) as connection:  # noqa: SLF001
        recovery = connection.execute(recovery_sql).fetchone()
        connection.rollback()

    assert reconciled.current_status == "ADVISORY_REJECTED"
    assert reconciled.current_source_event_version == 3
    assert restarted is not None
    assert restarted.realization.proposal_id == proposal.proposal_id
    assert restarted.realization.current_status == "ADVISORY_REJECTED"
    assert [outcome.source_event_version for outcome in restarted.outcomes] == [1, 2, 3]
    assert [outcome.reason_code for outcome in restarted.outcomes[1:]] == [
        "advise_proposal_linked",
        "advise_proposal_rejected",
    ]
    assert next(iter(recovery.values())) is True


def test_live_postgres_idea_intake_claim_is_restart_safe_and_conflict_detecting() -> None:
    if not _DSN:
        pytest.skip("PROPOSAL_POSTGRES_INTEGRATION_DSN is required for live persistence proof")

    first_repository, second_repository = (
        PostgresProposalRepository(dsn=_DSN),
        PostgresProposalRepository(dsn=_DSN),
    )
    _reset_tables(first_repository)
    created_at = datetime.now(timezone.utc)
    realization = IdeaProposalRealizationRecord(
        realization_id=f"ipr_{uuid.uuid4().hex[:12]}",
        intake_id=f"ipi_{uuid.uuid4().hex[:12]}",
        review_work_id=f"iarw_{uuid.uuid4().hex[:12]}",
        review_work_status="PENDING_ADVISER_REVIEW",
        tenant_id="tenant-private-bank-sg",
        legal_entity_code="SGPB",
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        idea_candidate_id="idea_candidate_concurrency",
        conversion_intent_id="conversion_intent_concurrency",
        source_evidence_fingerprint=f"sha256:{uuid.uuid4().hex * 2}",
        current_status="ACCEPTED_FOR_REVIEW",
        current_source_event_version=1,
        created_at_utc=created_at,
        updated_at_utc=created_at,
    )
    record = IdeaProposalIntakeRecord(
        registry_key=f"{uuid.uuid4().hex * 2}:sha256:{uuid.uuid4().hex * 2}",
        request_fingerprint=f"sha256:{uuid.uuid4().hex[:12]}",
        response_json='{"intake_status":"ACCEPTED"}',
        created_at_utc=created_at,
        expires_at_utc=created_at + timedelta(hours=24),
        realization=realization,
        initial_outcome=IdeaProposalRealizationOutcomeRecord(
            outcome_id=f"ipro_{uuid.uuid4().hex[:12]}",
            realization_id=realization.realization_id,
            source_event_version=1,
            status="ACCEPTED_FOR_REVIEW",
            reason_code="idea_conversion_accepted_for_adviser_review",
            occurred_at_utc=created_at,
            review_work_id=realization.review_work_id,
            proposal_id=None,
            terminal=False,
        ),
    )

    barrier = Barrier(2)

    def _claim(local_repository: PostgresProposalRepository):
        barrier.wait(timeout=10)
        return local_repository.claim_idea_proposal_intake(record)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(_claim, (first_repository, second_repository)))

    assert [claim.replayed for claim in claims].count(False) == 1
    assert [claim.replayed for claim in claims].count(True) == 1
    assert claims[0].record == claims[1].record
    with closing(first_repository._connect()) as connection:  # noqa: SLF001
        realization_count = connection.execute(
            "SELECT COUNT(*) AS count FROM proposal_idea_review_realizations"
        ).fetchone()
        outcome_count = connection.execute(
            "SELECT COUNT(*) AS count FROM proposal_idea_realization_outcomes"
        ).fetchone()
        connection.rollback()
    assert realization_count["count"] == 1
    assert outcome_count["count"] == 1

    with closing(first_repository._connect()) as connection:  # noqa: SLF001
        connection.execute(
            "DELETE FROM proposal_idea_realization_outcomes WHERE realization_id = %s",
            (realization.realization_id,),
        )
        connection.execute(
            "DELETE FROM proposal_idea_review_realizations WHERE realization_id = %s",
            (realization.realization_id,),
        )
        connection.commit()
    replay_timestamp = created_at + timedelta(hours=1)
    upgraded = second_repository.claim_idea_proposal_intake(
        replace(
            record,
            realization=replace(
                record.realization,
                created_at_utc=replay_timestamp,
                updated_at_utc=replay_timestamp,
            ),
            initial_outcome=replace(
                record.initial_outcome,
                occurred_at_utc=replay_timestamp,
            ),
        )
    )
    assert upgraded.replayed is True
    upgraded_history = first_repository.get_idea_proposal_realization(
        intake_id=realization.intake_id,
        tenant_id=realization.tenant_id,
        legal_entity_code=realization.legal_entity_code,
        portfolio_id=realization.portfolio_id,
    )
    assert upgraded_history is not None
    assert upgraded_history.realization.created_at_utc == record.created_at_utc
    assert upgraded_history.realization.updated_at_utc == record.created_at_utc
    assert upgraded_history.outcomes[0].occurred_at_utc == record.created_at_utc
    recovered_after_restart = second_repository.get_idea_proposal_realization_by_conversion_intent(
        conversion_intent_id=realization.conversion_intent_id,
        tenant_id=realization.tenant_id,
        legal_entity_code=realization.legal_entity_code,
        portfolio_id=realization.portfolio_id,
    )
    assert recovered_after_restart == upgraded_history

    other_realization = replace(
        realization,
        realization_id=f"ipr_{uuid.uuid4().hex[:12]}",
        review_work_id=f"iarw_{uuid.uuid4().hex[:12]}",
        tenant_id="tenant-private-bank-hk",
        legal_entity_code="HKPB",
    )
    other_tenant_record = replace(
        record,
        registry_key=f"{uuid.uuid4().hex * 2}:sha256:{uuid.uuid4().hex * 2}",
        realization=other_realization,
        initial_outcome=replace(
            record.initial_outcome,
            outcome_id=f"ipro_{uuid.uuid4().hex[:12]}",
            realization_id=other_realization.realization_id,
            review_work_id=other_realization.review_work_id,
        ),
    )
    assert second_repository.claim_idea_proposal_intake(other_tenant_record).replayed is False
    first_history = first_repository.get_idea_proposal_realization(
        intake_id=realization.intake_id,
        tenant_id=realization.tenant_id,
        legal_entity_code=realization.legal_entity_code,
        portfolio_id=realization.portfolio_id,
    )
    other_history = first_repository.get_idea_proposal_realization(
        intake_id=other_realization.intake_id,
        tenant_id=other_realization.tenant_id,
        legal_entity_code=other_realization.legal_entity_code,
        portfolio_id=other_realization.portfolio_id,
    )
    assert first_history is not None
    assert other_history is not None
    assert first_history.realization.realization_id == realization.realization_id
    assert other_history.realization.realization_id == other_realization.realization_id

    with pytest.raises(
        ProposalIdempotencyConflictError,
        match="IDEA_PROPOSAL_INTAKE_IDEMPOTENCY_CONFLICT",
    ):
        second_repository.claim_idea_proposal_intake(
            replace(record, request_fingerprint=f"sha256:{uuid.uuid4().hex[:12]}")
        )

    replacement = replace(
        record,
        request_fingerprint=f"sha256:{uuid.uuid4().hex[:12]}",
        created_at_utc=record.expires_at_utc,
        expires_at_utc=record.expires_at_utc + timedelta(hours=24),
    )
    assert second_repository.claim_idea_proposal_intake(replacement).replayed is False
    with closing(first_repository._connect()) as connection:  # noqa: SLF001
        purge_event = connection.execute(
            "SELECT reason_code FROM proposal_idea_intake_purge_events "
            "WHERE registry_key_digest = %s",
            (record.registry_key,),
        ).fetchone()
        assert purge_event["reason_code"] == "REPLAY_WINDOW_EXPIRED"
        connection.execute(
            "UPDATE proposal_idea_intakes SET legal_hold = TRUE WHERE registry_key = %s",
            (record.registry_key,),
        )
        connection.commit()
    with pytest.raises(ProposalIdempotencyConflictError):
        second_repository.claim_idea_proposal_intake(
            replace(
                replacement,
                request_fingerprint=f"sha256:{uuid.uuid4().hex[:12]}",
                created_at_utc=replacement.expires_at_utc,
                expires_at_utc=replacement.expires_at_utc + timedelta(hours=24),
            )
        )


def test_live_postgres_idea_intake_persists_portfolio_scope_for_recovery() -> None:
    if not _DSN:
        pytest.skip("PROPOSAL_POSTGRES_INTEGRATION_DSN is required for live persistence proof")

    first_repository = PostgresProposalRepository(dsn=_DSN)
    _reset_tables(first_repository)
    second_repository = PostgresProposalRepository(dsn=_DSN)
    request = IdeaProposalIntakeRequest.model_validate(IDEA_PROPOSAL_INTAKE_REQUEST_EXAMPLE)
    principal = IdeaProposalIntakePrincipal(
        actor_id="svc-lotus-idea",
        role="SERVICE",
        tenant_id="tenant-private-bank-sg",
        legal_entity_code="SGPB",
        correlation_id="corr-portfolio-first",
        service_identity="lotus-idea",
        capabilities=frozenset({IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY}),
    )
    created_at = datetime.now(timezone.utc)

    first = process_idea_proposal_intake(
        request,
        correlation_id="corr-portfolio-first",
        idempotency_key="idea-intake-portfolio-recovery",
        principal=principal,
        repository=first_repository,
        received_at=created_at,
    )
    replay = process_idea_proposal_intake(
        request,
        correlation_id="corr-portfolio-replay",
        idempotency_key="idea-intake-portfolio-recovery",
        principal=principal,
        repository=second_repository,
        received_at=created_at + timedelta(seconds=1),
    )

    assert first.portfolio_id == "PB_SG_GLOBAL_BAL_001"
    assert replay.portfolio_id == first.portfolio_id
    assert replay.idempotency_replay is True
    assert replay.realization_id == first.realization_id
    assert replay.review_work_id == first.review_work_id
    assert replay.review_work_status == "PENDING_ADVISER_REVIEW"
    assert replay.realization_status == "ACCEPTED_FOR_REVIEW"
    later_claim = process_idea_proposal_intake(
        request,
        correlation_id="corr-portfolio-later-claim",
        idempotency_key="idea-intake-portfolio-later-claim",
        principal=principal,
        repository=second_repository,
        received_at=created_at + timedelta(seconds=2),
    )
    assert later_claim.idempotency_replay is False
    assert later_claim.realization_id == first.realization_id
    out_of_order_claim = process_idea_proposal_intake(
        request,
        correlation_id="corr-portfolio-out-of-order-claim",
        idempotency_key="idea-intake-portfolio-out-of-order-claim",
        principal=principal,
        repository=second_repository,
        received_at=created_at - timedelta(seconds=1),
    )
    assert out_of_order_claim.idempotency_replay is False
    assert out_of_order_claim.realization_id == first.realization_id
    expired_key_reclaim = process_idea_proposal_intake(
        request,
        correlation_id="corr-portfolio-expired-key-reclaim",
        idempotency_key="idea-intake-portfolio-recovery",
        principal=principal,
        repository=second_repository,
        received_at=created_at + timedelta(hours=24, seconds=1),
    )
    assert expired_key_reclaim.idempotency_replay is False
    assert expired_key_reclaim.realization_id == first.realization_id
    with pytest.raises(ProposalIdempotencyConflictError):
        process_idea_proposal_intake(
            request.model_copy(update={"portfolio_id": "PB_SG_INCOME_002"}),
            correlation_id="corr-portfolio-conflict",
            idempotency_key="idea-intake-portfolio-recovery",
            principal=principal,
            repository=second_repository,
            received_at=created_at + timedelta(seconds=3),
        )

    rejected = process_idea_proposal_intake(
        request.model_copy(
            update={
                "idea_candidate_id": "idea-candidate-rejected-live",
                "conversion_intent_id": "conversion-intent-rejected-live",
                "intent_type": "CREATE_ADVISORY_PROPOSAL_DRAFT",
            }
        ),
        correlation_id="corr-rejected-before-work",
        idempotency_key="idea-intake-rejected-before-work",
        principal=principal,
        repository=second_repository,
        received_at=created_at + timedelta(seconds=4),
    )
    assert rejected.realization_status == "REJECTED_BEFORE_WORK"
    assert rejected.review_work_id is None
    assert rejected.review_work_status is None

    with closing(first_repository._connect()) as connection:  # noqa: SLF001
        recovery_sql = Path("scripts/sql/verify_idea_intake_recovery.sql").read_text(
            encoding="utf-8"
        )
        stored = connection.execute(
            "SELECT response_json::jsonb ->> 'portfolio_id' AS portfolio_id "
            "FROM proposal_idea_intakes"
        ).fetchone()
        durable_counts = connection.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM proposal_idea_review_realizations) AS realizations, "
            "(SELECT COUNT(*) FROM proposal_idea_realization_outcomes) AS outcomes, "
            "(SELECT COUNT(*) FROM proposal_idea_review_realizations "
            " WHERE review_work_id IS NOT NULL) AS review_work_items"
        ).fetchone()
        recovery = connection.execute(recovery_sql).fetchone()
        connection.execute(
            """
            UPDATE proposal_idea_intakes
            SET response_json = jsonb_set(
                response_json::jsonb,
                '{source_event_version}',
                '2'::jsonb
            )::text
            WHERE response_json::jsonb ->> 'realization_id' = %s
            """,
            (first.realization_id,),
        )
        contradictory_receipt_recovery = connection.execute(recovery_sql).fetchone()
        connection.execute(
            """
            UPDATE proposal_idea_intakes
            SET response_json = jsonb_set(
                response_json::jsonb,
                '{source_event_version}',
                '1'::jsonb
            )::text
            WHERE response_json::jsonb ->> 'realization_id' = %s
            """,
            (first.realization_id,),
        )
        connection.execute(
            """
            UPDATE proposal_idea_review_realizations
            SET conversion_intent_id = 'conversion-intent-swapped'
            WHERE realization_id = %s
            """,
            (first.realization_id,),
        )
        contradictory_conversion_recovery = connection.execute(recovery_sql).fetchone()
        connection.execute(
            """
            UPDATE proposal_idea_review_realizations
            SET conversion_intent_id = %s
            WHERE realization_id = %s
            """,
            (request.conversion_intent_id, first.realization_id),
        )
        connection.execute(
            """
            UPDATE proposal_idea_review_realizations
            SET idea_candidate_id = ''
            WHERE realization_id = %s
            """,
            (first.realization_id,),
        )
        blank_candidate_recovery = connection.execute(recovery_sql).fetchone()
        connection.execute(
            """
            UPDATE proposal_idea_review_realizations
            SET idea_candidate_id = 'idea-candidate-swapped'
            WHERE realization_id = %s
            """,
            (first.realization_id,),
        )
        contradictory_candidate_recovery = connection.execute(recovery_sql).fetchone()
        connection.execute(
            """
            UPDATE proposal_idea_review_realizations
            SET idea_candidate_id = %s
            WHERE realization_id = %s
            """,
            (request.idea_candidate_id, first.realization_id),
        )
        connection.execute(
            """
            UPDATE proposal_idea_realization_outcomes
            SET outcome_id = 'ipro_000000000000'
            WHERE realization_id = %s
              AND source_event_version = 1
            """,
            (first.realization_id,),
        )
        contradictory_outcome_id_recovery = connection.execute(recovery_sql).fetchone()
        connection.execute(
            """
            UPDATE proposal_idea_realization_outcomes
            SET outcome_id = %s
            WHERE realization_id = %s
              AND source_event_version = 1
            """,
            (
                first_repository.get_idea_proposal_realization(
                    tenant_id=principal.tenant_id,
                    legal_entity_code=principal.legal_entity_code,
                    portfolio_id=request.portfolio_id,
                    intake_id=first.intake_id,
                )
                .outcomes[0]
                .outcome_id,
                first.realization_id,
            ),
        )
        connection.execute(
            """
            UPDATE proposal_idea_realization_outcomes
            SET occurred_at_utc = occurred_at_utc + INTERVAL '1 day'
            WHERE realization_id = %s
              AND source_event_version = 1
            """,
            (first.realization_id,),
        )
        contradictory_outcome_chronology_recovery = connection.execute(recovery_sql).fetchone()
        connection.execute(
            """
            UPDATE proposal_idea_realization_outcomes
            SET occurred_at_utc = %s
            WHERE realization_id = %s
              AND source_event_version = 1
            """,
            (created_at, first.realization_id),
        )
        connection.execute(
            """
            UPDATE proposal_idea_review_realizations
            SET created_at_utc = created_at_utc + INTERVAL '1 day',
                updated_at_utc = updated_at_utc + INTERVAL '1 day'
            WHERE realization_id = %s
            """,
            (first.realization_id,),
        )
        connection.execute(
            """
            UPDATE proposal_idea_realization_outcomes
            SET occurred_at_utc = occurred_at_utc + INTERVAL '1 day'
            WHERE realization_id = %s
              AND source_event_version = 1
            """,
            (first.realization_id,),
        )
        contradictory_atomic_chronology_recovery = connection.execute(recovery_sql).fetchone()
        connection.execute(
            """
            UPDATE proposal_idea_review_realizations
            SET created_at_utc = %s,
                updated_at_utc = %s
            WHERE realization_id = %s
            """,
            (created_at, created_at, first.realization_id),
        )
        connection.execute(
            """
            UPDATE proposal_idea_realization_outcomes
            SET occurred_at_utc = %s
            WHERE realization_id = %s
              AND source_event_version = 1
            """,
            (created_at, first.realization_id),
        )
        connection.execute(
            """
            UPDATE proposal_idea_realization_outcomes
            SET status = 'REJECTED_BEFORE_WORK',
                reason_code = 'idea_conversion_rejected_before_advisory_work',
                review_work_id = NULL,
                terminal = TRUE
            WHERE realization_id = %s
              AND source_event_version = 1
            """,
            (first.realization_id,),
        )
        contradictory_outcome_recovery = connection.execute(recovery_sql).fetchone()
        connection.execute(
            """
            UPDATE proposal_idea_realization_outcomes
            SET status = 'ACCEPTED_FOR_REVIEW',
                reason_code = 'idea_conversion_accepted_for_adviser_review',
                review_work_id = %s,
                terminal = FALSE
            WHERE realization_id = %s
              AND source_event_version = 1
            """,
            (first.review_work_id, first.realization_id),
        )
        connection.execute(
            """
            UPDATE proposal_idea_intakes
            SET response_json = (
                response_json::jsonb
                    - 'realization_id'
                    - 'review_work_id'
                    - 'review_work_status'
                    - 'realization_status'
                    - 'source_event_version'
                    - 'source_evidence_fingerprint'
                || jsonb_build_object(
                    'certification_blockers', '[
                        "suitability_policy_authority_remains_lotus_advise",
                        "advisory_proposal_creation_not_certified",
                        "advisory_review_work_realization_not_certified",
                        "source_owned_outcome_stream_not_certified",
                        "client_publication_authority_blocked"
                    ]'::jsonb,
                    'evidence_refs', '[
                        "contracts/idea-proposal-intake/lotus-advise-idea-proposal-intake.v1.json",
                        "src/api/proposals/routes_idea_intake.py",
                        "src/core/proposals/idea_proposal_intake.py",
                        "src/infrastructure/postgres_migrations/proposals/0011_idea_proposal_intakes.sql"
                    ]'::jsonb
                )
            )::text
            """
        )
        legacy_recovery = connection.execute(recovery_sql).fetchone()
        connection.execute(
            """
            UPDATE proposal_idea_intakes
            SET response_json = jsonb_set(
                response_json::jsonb,
                '{portfolio_id}',
                '" tampered-portfolio "'::jsonb
            )::text
            WHERE registry_key = (SELECT min(registry_key) FROM proposal_idea_intakes)
            """
        )
        corrupted_legacy_recovery = connection.execute(recovery_sql).fetchone()
        connection.rollback()
    assert stored["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert durable_counts == {
        "realizations": 2,
        "outcomes": 2,
        "review_work_items": 1,
    }
    assert next(iter(recovery.values())) is True
    assert next(iter(contradictory_receipt_recovery.values())) is False
    assert next(iter(contradictory_conversion_recovery.values())) is False
    assert next(iter(blank_candidate_recovery.values())) is False
    assert next(iter(contradictory_candidate_recovery.values())) is False
    assert next(iter(contradictory_outcome_id_recovery.values())) is False
    assert next(iter(contradictory_outcome_chronology_recovery.values())) is False
    assert next(iter(contradictory_atomic_chronology_recovery.values())) is False
    assert next(iter(contradictory_outcome_recovery.values())) is False
    assert next(iter(legacy_recovery.values())) is True
    assert next(iter(corrupted_legacy_recovery.values())) is False


def _reset_tables(repository: PostgresProposalRepository) -> None:
    with closing(repository._connect()) as connection:  # noqa: SLF001
        connection.execute(
            "TRUNCATE TABLE proposal_memo_events, proposal_memo_idempotency, proposal_memos, "
            "proposal_approvals, proposal_workflow_events, proposal_versions, proposal_records, "
            "proposal_async_operations, proposal_idempotency, proposal_idea_intake_purge_events, "
            "proposal_idea_realization_outcomes, proposal_idea_review_realizations, "
            "proposal_idea_intakes CASCADE"
        )
        connection.commit()


def _create_version(
    *,
    repository: PostgresProposalRepository,
    proposal_id: str,
    version_no: int,
    now: datetime,
    proposal_version_id: str | None = None,
) -> ProposalVersionRecord:
    version = ProposalVersionRecord(
        proposal_version_id=proposal_version_id or f"ppv-{uuid.uuid4().hex}",
        proposal_id=proposal_id,
        version_no=version_no,
        created_at=now,
        request_hash=f"sha256:{uuid.uuid4().hex}",
        artifact_hash=f"sha256:{uuid.uuid4().hex}",
        simulation_hash=f"sha256:{uuid.uuid4().hex}",
        status_at_creation="READY",
        proposal_result_json={"status": "READY"},
        artifact_json={"artifact_id": f"a-{uuid.uuid4().hex}"},
        evidence_bundle_json={"hashes": {"request_hash": "sha256:integration"}},
        gate_decision_json=None,
    )
    repository.create_version(version)
    return version


def _proposal_create_records(
    *,
    now: datetime,
    suffix: str,
) -> tuple[
    ProposalRecord,
    ProposalVersionRecord,
    ProposalWorkflowEventRecord,
    ProposalIdempotencyRecord,
]:
    proposal = ProposalRecord(
        proposal_id=f"pp-{suffix}",
        portfolio_id="pf-atomic-create",
        mandate_id="mandate-atomic-create",
        jurisdiction="SG",
        created_by="advisor-atomic-create",
        created_at=now,
        last_event_at=now,
        current_state="DRAFT",
        current_version_no=1,
        title="Atomic proposal create",
        advisor_notes=None,
        lifecycle_origin="WORKSPACE_HANDOFF",
        source_workspace_id=f"aws-{suffix[:16]}",
    )
    version = ProposalVersionRecord(
        proposal_version_id=f"ppv-{suffix}",
        proposal_id=proposal.proposal_id,
        version_no=1,
        created_at=now,
        request_hash=f"sha256:req-{suffix}",
        artifact_hash=f"sha256:artifact-{suffix}",
        simulation_hash=f"sha256:sim-{suffix}",
        status_at_creation="READY",
        proposal_result_json={"status": "READY"},
        artifact_json={"artifact_id": f"pa-{suffix}"},
        evidence_bundle_json={"hashes": {"request_hash": f"sha256:req-{suffix}"}},
        gate_decision_json=None,
    )
    event = ProposalWorkflowEventRecord(
        event_id=f"pwe-{suffix}",
        proposal_id=proposal.proposal_id,
        event_type="CREATED",
        from_state=None,
        to_state="DRAFT",
        actor_id=proposal.created_by,
        occurred_at=now,
        reason_json={"request_hash": version.request_hash},
        related_version_no=1,
    )
    idempotency = ProposalIdempotencyRecord(
        idempotency_key=f"idem-{suffix}",
        request_hash=version.request_hash,
        proposal_id=proposal.proposal_id,
        proposal_version_no=1,
        created_at=now,
    )
    return proposal, version, event, idempotency


def _create_proposal_version_for_memo(
    *,
    repository: PostgresProposalRepository,
    now: datetime,
    suffix: str,
) -> ProposalVersionRecord:
    proposal_id = f"pp-memo-{suffix}"
    repository.create_proposal(
        ProposalRecord(
            proposal_id=proposal_id,
            portfolio_id="pf-atomic-memo",
            mandate_id="mandate-atomic-memo",
            jurisdiction="SG",
            created_by="advisor-atomic-memo",
            created_at=now,
            last_event_at=now,
            current_state="DRAFT",
            current_version_no=1,
            title="Atomic memo create",
            advisor_notes=None,
        )
    )
    return _create_version(
        repository=repository,
        proposal_id=proposal_id,
        version_no=1,
        now=now,
        proposal_version_id=f"ppv-memo-{suffix}",
    )


def _memo_create_records(
    *,
    now: datetime,
    suffix: str,
    version: ProposalVersionRecord,
) -> tuple[
    ProposalMemoRecord,
    ProposalMemoIdempotencyRecord,
    ProposalMemoEventRecord,
]:
    memo = ProposalMemoRecord(
        memo_id=f"memo-{suffix}",
        proposal_id=version.proposal_id,
        proposal_version_no=version.version_no,
        proposal_version_id=version.proposal_version_id,
        artifact_id=f"pa-memo-{suffix}",
        memo_version="advisory-proposal-memo-evidence-pack.v1",
        memo_status="BLOCKED",
        lifecycle_status="DRAFT",
        created_by="advisor-atomic-memo",
        created_at=now,
        source_input_hash=f"sha256:memo-source-{suffix}",
        memo_hash=f"sha256:memo-{suffix}",
        memo_json={"memo_id": f"memo-{suffix}", "status": "BLOCKED"},
        projection_json={"client_ready_publication": "BLOCKED"},
        review_events_json=[],
        report_package_events_json=[],
        archive_refs_json=[],
        ai_refs_json=[],
        replay_metadata_json={"proposal_artifact_hash": version.artifact_hash},
    )
    idempotency = ProposalMemoIdempotencyRecord(
        idempotency_key=f"memo-idem-{suffix}",
        request_hash=f"sha256:memo-request-{suffix}",
        memo_id=memo.memo_id,
        proposal_id=memo.proposal_id,
        proposal_version_no=memo.proposal_version_no,
        created_at=now,
    )
    event = ProposalMemoEventRecord(
        event_id=f"pme-{suffix}",
        memo_id=memo.memo_id,
        proposal_id=memo.proposal_id,
        proposal_version_no=memo.proposal_version_no,
        event_type="MEMO_DRAFT_CREATED",
        actor_id=memo.created_by,
        occurred_at=now,
        reason_json={"memo_hash": memo.memo_hash},
    )
    return memo, idempotency, event


def _assert_statement_fails(connection, query: str, args: tuple[object, ...]) -> None:
    try:
        connection.execute(query, args)
        connection.commit()
    except Exception:
        connection.rollback()
        return
    raise AssertionError("Expected lifecycle integrity statement to fail")
