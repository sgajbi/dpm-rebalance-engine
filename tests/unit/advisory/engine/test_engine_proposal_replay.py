from datetime import datetime, timezone

from src.core.proposals.models import (
    ProposalAsyncOperationRecord,
    ProposalRecord,
    ProposalVersionRecord,
    ProposalWorkflowEventRecord,
)
from src.core.proposals.proposal_replay import load_proposal_version_replay_referents
from src.core.replay.service import (
    build_async_operation_replay_response,
    build_proposal_version_replay_response,
)
from src.infrastructure.proposals.in_memory import InMemoryProposalRepository


def _now() -> datetime:
    return datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)


def _proposal() -> ProposalRecord:
    return ProposalRecord(
        proposal_id="pp_replay",
        portfolio_id="pf_replay",
        mandate_id="mandate_replay",
        jurisdiction="SG",
        created_by="advisor_replay",
        created_at=_now(),
        last_event_at=_now(),
        current_state="DRAFT",
        current_version_no=1,
        title="Replay proposal",
    )


def _version() -> ProposalVersionRecord:
    return ProposalVersionRecord(
        proposal_version_id="ppv_replay_1",
        proposal_id="pp_replay",
        version_no=1,
        created_at=_now(),
        request_hash="sha256:req-replay",
        artifact_hash="sha256:artifact-replay",
        simulation_hash="sha256:sim-replay",
        status_at_creation="READY",
        proposal_result_json={"status": "READY"},
        artifact_json={},
        evidence_bundle_json={},
        gate_decision_json=None,
    )


def _event(event_id: str, related_version_no: int | None = 1) -> ProposalWorkflowEventRecord:
    return ProposalWorkflowEventRecord(
        event_id=event_id,
        proposal_id="pp_replay",
        event_type="CREATED",
        from_state=None,
        to_state="DRAFT",
        actor_id="advisor_replay",
        occurred_at=_now(),
        reason_json={},
        related_version_no=related_version_no,
    )


def _async_operation(
    *,
    proposal_id: str | None = "pp_replay",
    status: str = "SUCCEEDED",
) -> ProposalAsyncOperationRecord:
    return ProposalAsyncOperationRecord(
        operation_id="pop_replay_1",
        operation_type="CREATE_PROPOSAL_VERSION",
        status=status,
        correlation_id="corr_replay",
        idempotency_key="idem_replay",
        proposal_id=proposal_id,
        created_by="advisor_replay",
        created_at=_now(),
        payload_json={"proposal_id": proposal_id, "request_hash": "sha256:req-replay"},
        attempt_count=2,
        max_attempts=3,
        started_at=_now(),
        finished_at=_now(),
        result_json={"version": {"version_no": 1}},
        error_json={"code": "UPSTREAM_RETRYABLE"},
    )


def test_load_proposal_version_replay_referents_returns_complete_replay_context():
    repository = InMemoryProposalRepository()
    repository.create_proposal(_proposal())
    repository.create_version(_version())
    repository.append_event(_event("pwe_replay_1"))
    repository.append_event(_event("pwe_replay_2", related_version_no=None))

    referents = load_proposal_version_replay_referents(
        repository=repository,
        proposal_id="pp_replay",
        version_no=1,
    )

    assert referents.proposal is not None
    assert referents.proposal.proposal_id == "pp_replay"
    assert referents.version is not None
    assert referents.version.proposal_version_id == "ppv_replay_1"
    assert [event.event_id for event in referents.events] == ["pwe_replay_1", "pwe_replay_2"]


def test_load_proposal_version_replay_referents_preserves_missing_proposal_boundary():
    referents = load_proposal_version_replay_referents(
        repository=InMemoryProposalRepository(),
        proposal_id="pp_missing",
        version_no=1,
    )

    assert referents.proposal is None
    assert referents.version is None
    assert referents.events == []


def test_load_proposal_version_replay_referents_preserves_missing_version_boundary():
    repository = InMemoryProposalRepository()
    repository.create_proposal(_proposal())

    referents = load_proposal_version_replay_referents(
        repository=repository,
        proposal_id="pp_replay",
        version_no=99,
    )

    assert referents.proposal is not None
    assert referents.version is None
    assert referents.events == []


def test_build_async_operation_replay_response_links_terminal_proposal_version():
    response = build_async_operation_replay_response(
        operation=_async_operation(),
        proposal=_proposal(),
        version=_version(),
        events=[_event("pwe_replay_1")],
    )

    assert response.subject.scope == "ASYNC_OPERATION"
    assert response.subject.proposal_id == "pp_replay"
    assert response.subject.proposal_version_id == "ppv_replay_1"
    assert response.subject.operation_id == "pop_replay_1"
    assert response.continuity.async_operation_id == "pop_replay_1"
    assert response.continuity.async_operation_type == "CREATE_PROPOSAL_VERSION"
    assert response.continuity.correlation_id == "corr_replay"
    assert response.continuity.idempotency_key == "idem_replay"
    assert response.hashes.request_hash == "sha256:req-replay"
    assert response.hashes.simulation_hash == "sha256:sim-replay"
    assert response.evidence["async_runtime"] == {
        "status": "SUCCEEDED",
        "attempt_count": 2,
        "max_attempts": 3,
        "created_at": "2026-05-21T10:00:00+00:00",
        "started_at": "2026-05-21T10:00:00+00:00",
        "finished_at": "2026-05-21T10:00:00+00:00",
    }
    assert "payload_json" not in response.evidence["async_runtime"]
    assert response.explanation["source"] == "ASYNC_OPERATION_AND_PROPOSAL_VERSION"


def test_build_proposal_version_replay_response_preserves_context_without_inferred_date():
    version = _version().model_copy(
        update={
            "evidence_bundle_json": {
                "context_resolution": {
                    "resolved_context": {
                        "portfolio_id": "pf_replay",
                        "as_of": None,
                        "portfolio_snapshot_id": "ps_replay",
                    }
                }
            }
        }
    )

    response = build_proposal_version_replay_response(
        proposal=_proposal(),
        version=version,
        events=[_event("pwe_replay_1")],
    )

    assert response.resolved_context is not None
    assert response.resolved_context.portfolio_id == "pf_replay"
    assert response.resolved_context.as_of is None
    assert response.resolved_context.portfolio_snapshot_id == "ps_replay"


def test_build_async_operation_replay_response_preserves_operation_only_runtime_evidence():
    response = build_async_operation_replay_response(
        operation=_async_operation(proposal_id=None, status="FAILED"),
        proposal=None,
        version=None,
        events=None,
    )

    assert response.subject.scope == "ASYNC_OPERATION"
    assert response.subject.proposal_id is None
    assert response.subject.operation_id == "pop_replay_1"
    assert response.resolved_context is None
    assert response.hashes.model_dump(exclude_none=True) == {}
    assert response.continuity.async_operation_id == "pop_replay_1"
    assert response.continuity.async_operation_type == "CREATE_PROPOSAL_VERSION"
    assert response.evidence["async_runtime"] == {
        "status": "FAILED",
        "attempt_count": 2,
        "max_attempts": 3,
        "created_at": "2026-05-21T10:00:00+00:00",
        "started_at": "2026-05-21T10:00:00+00:00",
        "finished_at": "2026-05-21T10:00:00+00:00",
        "payload_json": {"proposal_id": None, "request_hash": "sha256:req-replay"},
        "error": {"code": "UPSTREAM_RETRYABLE"},
    }
    assert response.explanation == {
        "source": "ASYNC_OPERATION_ONLY",
        "continuity_status": "NO_TERMINAL_PROPOSAL_VERSION_AVAILABLE",
    }
