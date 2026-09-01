from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core.proposals.exceptions import (
    ProposalIdempotencyConflictError,
    ProposalStateConflictError,
)
from src.core.proposals.idea_intake_persistence import IdeaProposalIntakeRecord
from src.core.proposals.idea_review_realization import (
    IdeaProposalRealizationOutcomeRecord,
    IdeaProposalRealizationRecord,
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
from src.infrastructure.proposals.in_memory import InMemoryProposalRepository

REPO_ROOT = Path(__file__).resolve().parents[4]
IN_MEMORY_REPOSITORY_PATH = REPO_ROOT / "src/infrastructure/proposals/in_memory.py"
IN_MEMORY_QUERY_PATH = REPO_ROOT / "src/infrastructure/proposals/in_memory_query.py"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _idea_intake_record(created_at: datetime) -> IdeaProposalIntakeRecord:
    realization = IdeaProposalRealizationRecord(
        realization_id="ipr_123456789abc",
        intake_id="ipi_123456789abc",
        review_work_id="iarw_123456789abc",
        review_work_status="PENDING_ADVISER_REVIEW",
        tenant_id="tenant-private-bank-sg",
        legal_entity_code="SGPB",
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        idea_candidate_id="idea_candidate_001",
        conversion_intent_id="conversion_intent_001",
        source_evidence_fingerprint=f"sha256:{'a' * 64}",
        current_status="ACCEPTED_FOR_REVIEW",
        current_source_event_version=1,
        created_at_utc=created_at,
        updated_at_utc=created_at,
    )
    return IdeaProposalIntakeRecord(
        registry_key="scope:retained-key",
        request_fingerprint="sha256:request",
        response_json='{"intake_status":"ACCEPTED"}',
        created_at_utc=created_at,
        expires_at_utc=created_at + timedelta(hours=24),
        realization=realization,
        initial_outcome=IdeaProposalRealizationOutcomeRecord(
            outcome_id="ipro_123456789abc",
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


def test_idea_intake_expiry_allows_reuse_unless_legal_hold_applies() -> None:
    created_at = _now()
    first = _idea_intake_record(created_at)
    repository = InMemoryProposalRepository()
    assert repository.claim_idea_proposal_intake(first).replayed is False
    replacement = replace(
        first,
        request_fingerprint="sha256:replacement",
        created_at_utc=first.expires_at_utc,
        expires_at_utc=first.expires_at_utc + timedelta(hours=24),
    )
    assert repository.claim_idea_proposal_intake(replacement).replayed is False

    held_repository = InMemoryProposalRepository()
    held_repository.claim_idea_proposal_intake(replace(first, legal_hold=True))
    with pytest.raises(ProposalIdempotencyConflictError):
        held_repository.claim_idea_proposal_intake(replacement)


def test_idea_intake_creates_one_scope_checked_review_realization() -> None:
    record = _idea_intake_record(_now())
    repository = InMemoryProposalRepository()

    repository.claim_idea_proposal_intake(record)
    repository.claim_idea_proposal_intake(record)

    history = repository.get_idea_proposal_realization(
        intake_id=record.realization.intake_id,
        tenant_id=record.realization.tenant_id,
        legal_entity_code=record.realization.legal_entity_code,
        portfolio_id=record.realization.portfolio_id,
    )
    assert history is not None
    assert history.realization.review_work_id == "iarw_123456789abc"
    assert history.realization.current_status == "ACCEPTED_FOR_REVIEW"
    assert [outcome.source_event_version for outcome in history.outcomes] == [1]
    assert (
        repository.get_idea_proposal_realization(
            intake_id=record.realization.intake_id,
            tenant_id=record.realization.tenant_id,
            legal_entity_code=record.realization.legal_entity_code,
            portfolio_id="PB_OTHER",
        )
        is None
    )


def _proposal(proposal_id: str, created_by: str, state: str = "DRAFT") -> ProposalRecord:
    now = _now()
    return ProposalRecord(
        proposal_id=proposal_id,
        portfolio_id="pf_repo",
        mandate_id=None,
        jurisdiction="SG",
        created_by=created_by,
        created_at=now,
        last_event_at=now,
        current_state=state,
        current_version_no=1,
        title="repo test",
    )


def _async_operation(
    operation_id: str,
    *,
    status: str = "PENDING",
    created_at: datetime | None = None,
    lease_expires_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> ProposalAsyncOperationRecord:
    return ProposalAsyncOperationRecord(
        operation_id=operation_id,
        operation_type="CREATE_PROPOSAL",
        status=status,
        correlation_id=f"corr_{operation_id}",
        idempotency_key=f"idem_{operation_id}",
        proposal_id=None,
        created_by="advisor_repo",
        created_at=created_at or _now(),
        payload_json={"created_by": "advisor_repo"},
        attempt_count=0,
        max_attempts=3,
        lease_expires_at=lease_expires_at,
        finished_at=finished_at,
    )


def test_in_memory_repository_delegates_query_helpers() -> None:
    repository_source = IN_MEMORY_REPOSITORY_PATH.read_text(encoding="utf-8")
    query_source = IN_MEMORY_QUERY_PATH.read_text(encoding="utf-8")

    assert "from src.infrastructure.proposals.in_memory_query import" in repository_source
    assert "def filtered_proposal_page(" not in repository_source
    assert "def ordered_memos_for_proposals(" not in repository_source
    assert "def ordered_events_for_proposals(" not in repository_source
    assert "def ordered_approvals_for_proposals(" not in repository_source
    assert "def recoverable_operations(" not in repository_source
    assert "def filtered_proposal_page(" in query_source
    assert "def ordered_memos_for_proposals(" in query_source
    assert "def ordered_events_for_proposals(" in query_source
    assert "def ordered_approvals_for_proposals(" in query_source
    assert "def recoverable_operations(" in query_source


def test_repository_idempotency_roundtrip_and_update_proposal():
    repo = InMemoryProposalRepository()
    created_at = _now()
    record = ProposalIdempotencyRecord(
        idempotency_key="idem-repo-1",
        request_hash="sha256:req",
        proposal_id="pp_repo_1",
        proposal_version_no=1,
        created_at=created_at,
    )

    assert repo.get_idempotency(idempotency_key="idem-repo-1") is None
    repo.save_idempotency(record)
    stored = repo.get_idempotency(idempotency_key="idem-repo-1")
    assert stored is not None
    assert stored.request_hash == "sha256:req"

    proposal = _proposal("pp_repo_1", "advisor_repo")
    repo.create_proposal(proposal)
    proposal.current_state = "CANCELLED"
    repo.update_proposal(proposal)
    fetched = repo.get_proposal(proposal_id="pp_repo_1")
    assert fetched is not None
    assert fetched.current_state == "CANCELLED"


def test_repository_simulation_idempotency_roundtrip():
    repo = InMemoryProposalRepository()
    created_at = _now()
    record = ProposalSimulationIdempotencyRecord(
        idempotency_key="idem-sim-1",
        request_hash="sha256:sim-req",
        response_json={"proposal_run_id": "pr_001", "status": "READY"},
        created_at=created_at,
    )
    assert repo.get_simulation_idempotency(idempotency_key="idem-sim-1") is None

    repo.save_simulation_idempotency(record)
    loaded = repo.get_simulation_idempotency(idempotency_key="idem-sim-1")
    assert loaded is not None
    assert loaded.request_hash == "sha256:sim-req"
    assert loaded.response_json["proposal_run_id"] == "pr_001"
    assert loaded.created_at == created_at


def test_repository_list_filters_cursor_events_and_approvals():
    repo = InMemoryProposalRepository()
    first = _proposal("pp_repo_a", "advisor_a")
    second = _proposal("pp_repo_b", "advisor_b", state="EXECUTION_READY")
    repo.create_proposal(first)
    repo.create_proposal(second)

    rows, next_cursor = repo.list_proposals(
        portfolio_id="pf_repo",
        state="DRAFT",
        created_by="advisor_a",
        created_from=None,
        created_to=None,
        limit=1,
        cursor=None,
    )
    assert len(rows) == 1
    assert rows[0].proposal_id == "pp_repo_a"
    assert next_cursor is None

    rows, _ = repo.list_proposals(
        portfolio_id=None,
        state=None,
        created_by=None,
        created_from=None,
        created_to=None,
        limit=1,
        cursor="pp_repo_b",
    )
    assert len(rows) == 1
    assert rows[0].proposal_id == "pp_repo_a"

    event = ProposalWorkflowEventRecord(
        event_id="pwe_repo_1",
        proposal_id="pp_repo_a",
        event_type="CREATED",
        from_state=None,
        to_state="DRAFT",
        actor_id="advisor_a",
        occurred_at=_now(),
        reason_json={},
        related_version_no=1,
    )
    repo.append_event(event)
    assert repo.list_events(proposal_id="pp_repo_a")[0].event_id == "pwe_repo_1"
    second_event = event.model_copy(
        update={
            "event_id": "pwe_repo_2",
            "proposal_id": "pp_repo_b",
            "actor_id": "advisor_b",
        }
    )
    repo.append_event(second_event)
    assert [
        row.event_id
        for row in repo.list_events_for_proposals(proposal_ids=["pp_repo_b", "pp_repo_a"])
    ] == ["pwe_repo_2", "pwe_repo_1"]
    assert repo.list_events_for_proposals(proposal_ids=[]) == []

    approval = ProposalApprovalRecordData(
        approval_id="pap_repo_1",
        proposal_id="pp_repo_a",
        approval_type="RISK",
        approved=True,
        actor_id="risk",
        occurred_at=_now(),
        details_json={"channel": "INTERNAL"},
        related_version_no=1,
    )
    repo.create_approval(approval)
    assert repo.list_approvals(proposal_id="pp_repo_a")[0].approval_id == "pap_repo_1"
    second_approval = approval.model_copy(
        update={
            "approval_id": "pap_repo_2",
            "proposal_id": "pp_repo_b",
            "actor_id": "compliance",
            "approval_type": "COMPLIANCE",
        }
    )
    repo.create_approval(second_approval)
    assert [
        row.approval_id
        for row in repo.list_approvals_for_proposals(proposal_ids=["pp_repo_b", "pp_repo_a"])
    ] == ["pap_repo_2", "pap_repo_1"]
    assert repo.list_approvals_for_proposals(proposal_ids=[]) == []


def test_repository_lists_memos_for_proposals_in_one_ordered_batch():
    repo = InMemoryProposalRepository()
    first = _proposal("pp_repo_a", "advisor_a")
    second = _proposal("pp_repo_b", "advisor_b")
    repo.create_proposal(first)
    repo.create_proposal(second)

    first_memo = ProposalMemoRecord(
        memo_id="memo_repo_a",
        proposal_id=first.proposal_id,
        proposal_version_no=1,
        memo_version="advisory-proposal-memo-evidence-pack.v1",
        memo_status="BLOCKED",
        lifecycle_status="FINALIZED",
        created_by="advisor_a",
        created_at=_now(),
        source_input_hash="sha256:source-a",
        memo_hash="sha256:memo-a",
        memo_json={"memo_id": "memo_repo_a"},
    )
    second_memo = first_memo.model_copy(
        update={
            "memo_id": "memo_repo_b",
            "proposal_id": second.proposal_id,
            "created_by": "advisor_b",
            "source_input_hash": "sha256:source-b",
            "memo_hash": "sha256:memo-b",
            "memo_json": {"memo_id": "memo_repo_b"},
        }
    )
    repo.create_memo(second_memo)
    repo.create_memo(first_memo)

    memos = repo.list_memos_for_proposals(proposal_ids=[second.proposal_id, first.proposal_id])

    assert [memo.memo_id for memo in memos] == ["memo_repo_b", "memo_repo_a"]
    assert repo.list_memos_for_proposals(proposal_ids=[]) == []


def test_repository_rejects_conflicting_memo_idempotency_and_memo_hashes():
    repo = InMemoryProposalRepository()
    created_at = _now()
    idempotency = ProposalMemoIdempotencyRecord(
        idempotency_key="memo-idem-repo",
        request_hash="sha256:memo-request",
        memo_id="memo_repo_a",
        proposal_id="pp_repo_a",
        proposal_version_no=1,
        created_at=created_at,
    )
    repo.save_memo_idempotency(idempotency)
    repo.save_memo_idempotency(idempotency.model_copy())

    with pytest.raises(ValueError, match="MEMO_IDEMPOTENCY_KEY_CONFLICT"):
        repo.save_memo_idempotency(
            idempotency.model_copy(update={"request_hash": "sha256:memo-request-v2"})
        )

    memo = ProposalMemoRecord(
        memo_id="memo_repo_a",
        proposal_id="pp_repo_a",
        proposal_version_no=1,
        memo_version="advisory-proposal-memo-evidence-pack.v1",
        memo_status="BLOCKED",
        lifecycle_status="FINALIZED",
        created_by="advisor_a",
        created_at=created_at,
        source_input_hash="sha256:source-a",
        memo_hash="sha256:memo-a",
        memo_json={"memo_id": "memo_repo_a"},
    )
    repo.create_memo(memo)
    repo.create_memo(memo.model_copy())

    with pytest.raises(ValueError, match="MEMO_HASH_CONFLICT"):
        repo.create_memo(memo.model_copy(update={"memo_hash": "sha256:memo-a-v2"}))

    with pytest.raises(ValueError, match="MEMO_PROPOSAL_VERSION_CONFLICT"):
        repo.create_memo(memo.model_copy(update={"memo_id": "memo_repo_b"}))


def test_repository_versions_and_transition_transaction_path():
    repo = InMemoryProposalRepository()
    proposal = _proposal("pp_repo_txn", "advisor_txn")
    repo.create_proposal(proposal)
    version = ProposalVersionRecord(
        proposal_version_id="ppv_repo_1",
        proposal_id="pp_repo_txn",
        version_no=1,
        created_at=_now(),
        request_hash="sha256:req",
        artifact_hash="sha256:artifact",
        simulation_hash="sha256:sim",
        status_at_creation="READY",
        proposal_result_json={},
        artifact_json={},
        evidence_bundle_json={},
        gate_decision_json=None,
    )
    repo.create_version(version)
    assert repo.get_version(proposal_id="pp_repo_txn", version_no=1) is not None
    assert [row.version_no for row in repo.list_versions(proposal_id="pp_repo_txn")] == [1]
    assert repo.list_versions(proposal_id="pp_missing") == []
    assert repo.get_current_version(proposal_id="pp_repo_txn") is not None

    transition_event = ProposalWorkflowEventRecord(
        event_id="pwe_repo_txn",
        proposal_id="pp_repo_txn",
        event_type="SUBMITTED_FOR_RISK_REVIEW",
        from_state="DRAFT",
        to_state="RISK_REVIEW",
        actor_id="advisor_txn",
        occurred_at=_now(),
        reason_json={"comment": "submit"},
        related_version_no=1,
    )
    proposal.current_state = "RISK_REVIEW"
    result = repo.transition_proposal(
        proposal=proposal,
        event=transition_event,
        approval=None,
        expected_current_state="DRAFT",
        expected_current_version_no=1,
    )
    assert isinstance(result, ProposalTransitionResult)
    assert result.proposal.current_state == "RISK_REVIEW"
    assert result.event.event_id == "pwe_repo_txn"


def test_in_memory_repository_transition_rejects_stale_expected_state():
    repo = InMemoryProposalRepository()
    proposal = _proposal("pp_repo_stale_txn", "advisor_txn")
    repo.create_proposal(proposal)
    transition_event = ProposalWorkflowEventRecord(
        event_id="pwe_repo_stale_txn",
        proposal_id="pp_repo_stale_txn",
        event_type="SUBMITTED_FOR_RISK_REVIEW",
        from_state="DRAFT",
        to_state="RISK_REVIEW",
        actor_id="advisor_txn",
        occurred_at=_now(),
        reason_json={"comment": "submit"},
        related_version_no=1,
    )
    stale_update = proposal.model_copy(update={"current_state": "RISK_REVIEW"})

    with pytest.raises(ProposalStateConflictError) as exc_info:
        repo.transition_proposal(
            proposal=stale_update,
            event=transition_event,
            approval=None,
            expected_current_state="COMPLIANCE_REVIEW",
            expected_current_version_no=1,
        )

    assert str(exc_info.value) == "STATE_CONFLICT: proposal aggregate changed during transition"
    assert repo.get_proposal(proposal_id=proposal.proposal_id) == proposal
    assert repo.list_events(proposal_id=proposal.proposal_id) == []


def test_repository_created_from_to_filters_and_empty_current_version():
    repo = InMemoryProposalRepository()
    now = _now()
    proposal = ProposalRecord(
        proposal_id="pp_repo_date",
        portfolio_id="pf_repo",
        mandate_id=None,
        jurisdiction="SG",
        created_by="advisor_date",
        created_at=now,
        last_event_at=now,
        current_state="DRAFT",
        current_version_no=1,
        title="date filter",
        advisor_notes=None,
    )
    repo.create_proposal(proposal)

    future = now.replace(year=now.year + 1)
    rows, _ = repo.list_proposals(
        portfolio_id=None,
        state=None,
        created_by=None,
        created_from=future,
        created_to=None,
        limit=10,
        cursor=None,
    )
    assert rows == []

    past = now.replace(year=now.year - 1)
    rows, _ = repo.list_proposals(
        portfolio_id=None,
        state=None,
        created_by=None,
        created_from=None,
        created_to=past,
        limit=10,
        cursor=None,
    )
    assert rows == []

    assert repo.get_current_version(proposal_id="pp_repo_date") is None


def test_in_memory_repository_atomic_proposal_create_commits_all_records():
    repo = InMemoryProposalRepository()
    now = _now()
    proposal = _proposal("pp_repo_atomic_create", "advisor_atomic")
    version = ProposalVersionRecord(
        proposal_version_id="ppv_repo_atomic_create",
        proposal_id=proposal.proposal_id,
        version_no=1,
        created_at=now,
        request_hash="sha256:req-atomic",
        artifact_hash="sha256:artifact-atomic",
        simulation_hash="sha256:sim-atomic",
        status_at_creation="READY",
        proposal_result_json={"status": "READY"},
        artifact_json={"artifact_id": "pa_atomic"},
        evidence_bundle_json={"hashes": {"request_hash": "sha256:req-atomic"}},
        gate_decision_json=None,
    )
    event = ProposalWorkflowEventRecord(
        event_id="pwe_repo_atomic_create",
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
        idempotency_key="idem_repo_atomic_create",
        request_hash=version.request_hash,
        proposal_id=proposal.proposal_id,
        proposal_version_no=1,
        created_at=now,
    )

    repo.create_proposal_with_version_event_idempotency(
        proposal=proposal,
        version=version,
        event=event,
        idempotency=idempotency,
    )

    assert repo.get_proposal(proposal_id=proposal.proposal_id) == proposal
    assert repo.get_version(proposal_id=proposal.proposal_id, version_no=1) == version
    assert repo.list_events(proposal_id=proposal.proposal_id) == [event]
    assert repo.get_idempotency(idempotency_key=idempotency.idempotency_key) == idempotency


def test_in_memory_repository_atomic_memo_create_commits_all_records():
    repo = InMemoryProposalRepository()
    now = _now()
    memo = ProposalMemoRecord(
        memo_id="memo_repo_atomic_create",
        proposal_id="pp_repo_atomic_memo",
        proposal_version_no=1,
        proposal_version_id="ppv_repo_atomic_memo",
        artifact_id="pa_repo_atomic_memo",
        memo_version="advisory-proposal-memo-evidence-pack.v1",
        memo_status="BLOCKED",
        lifecycle_status="DRAFT",
        created_by="advisor_atomic_memo",
        created_at=now,
        source_input_hash="sha256:memo-atomic-source",
        memo_hash="sha256:memo-atomic",
        memo_json={"memo_id": "memo_repo_atomic_create", "status": "BLOCKED"},
        projection_json={"client_ready_publication": "BLOCKED"},
        review_events_json=[],
        report_package_events_json=[],
        archive_refs_json=[],
        ai_refs_json=[],
        replay_metadata_json={"proposal_artifact_hash": "sha256:memo-atomic-artifact"},
    )
    idempotency = ProposalMemoIdempotencyRecord(
        idempotency_key="memo-repo-atomic-idem",
        request_hash="sha256:memo-atomic-request",
        memo_id=memo.memo_id,
        proposal_id=memo.proposal_id,
        proposal_version_no=memo.proposal_version_no,
        created_at=now,
    )
    event = ProposalMemoEventRecord(
        event_id="pme_repo_atomic_create",
        memo_id=memo.memo_id,
        proposal_id=memo.proposal_id,
        proposal_version_no=memo.proposal_version_no,
        event_type="MEMO_DRAFT_CREATED",
        actor_id=memo.created_by,
        occurred_at=now,
        reason_json={"memo_hash": memo.memo_hash},
    )

    repo.create_memo_with_idempotency_event(
        memo=memo,
        idempotency=idempotency,
        event=event,
    )

    assert repo.get_memo(memo_id=memo.memo_id) == memo
    assert repo.get_memo_idempotency(idempotency_key=idempotency.idempotency_key) == idempotency
    assert repo.list_memo_events(memo_id=memo.memo_id) == [event]


def test_repository_list_proposals_ignores_unknown_cursor() -> None:
    repo = InMemoryProposalRepository()
    first = _proposal("pp_repo_cursor_a", "advisor_cursor")
    second = _proposal("pp_repo_cursor_b", "advisor_cursor")
    repo.create_proposal(first)
    repo.create_proposal(second)

    rows, next_cursor = repo.list_proposals(
        portfolio_id=None,
        state=None,
        created_by="advisor_cursor",
        created_from=None,
        created_to=None,
        limit=1,
        cursor="pp_repo_missing_cursor",
    )

    assert [row.proposal_id for row in rows] == ["pp_repo_cursor_b"]
    assert next_cursor == "pp_repo_cursor_b"


def test_repository_recoverable_operations_preserve_retry_policy_edges() -> None:
    repo = InMemoryProposalRepository()
    as_of = _now()
    repo.create_operation(
        _async_operation(
            "pop_repo_pending",
            created_at=as_of - timedelta(minutes=4),
        )
    )
    repo.create_operation(
        _async_operation(
            "pop_repo_running_expired",
            status="RUNNING",
            created_at=as_of - timedelta(minutes=3),
            lease_expires_at=as_of - timedelta(seconds=1),
        )
    )
    repo.create_operation(
        _async_operation(
            "pop_repo_running_active",
            status="RUNNING",
            created_at=as_of - timedelta(minutes=2),
            lease_expires_at=as_of + timedelta(seconds=30),
        )
    )
    repo.create_operation(
        _async_operation(
            "pop_repo_running_finished",
            status="RUNNING",
            created_at=as_of - timedelta(minutes=1),
            lease_expires_at=as_of - timedelta(seconds=1),
            finished_at=as_of - timedelta(seconds=30),
        )
    )

    recoverable = repo.list_recoverable_operations(as_of=as_of)

    assert [operation.operation_id for operation in recoverable] == [
        "pop_repo_pending",
        "pop_repo_running_expired",
    ]
