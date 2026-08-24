from typing import Any, Optional, cast

from src.core.proposals.delivery_summary import build_delivery_summary_from_events
from src.core.proposals.models import (
    ProposalAsyncOperationRecord,
    ProposalRecord,
    ProposalVersionRecord,
    ProposalWorkflowEventRecord,
)
from src.core.proposals.narrative_review import latest_narrative_review_record
from src.core.replay.models import (
    AdvisoryReplayContinuity,
    AdvisoryReplayEvidenceResponse,
    AdvisoryReplayHashes,
    AdvisoryReplayResolvedContext,
    AdvisoryReplaySubject,
)
from src.core.workspace.session_models import WorkspaceSession
from src.core.workspace.version_models import WorkspaceSavedVersion


def build_workspace_saved_version_replay_response(
    *,
    session: WorkspaceSession,
    saved_version: WorkspaceSavedVersion,
) -> AdvisoryReplayEvidenceResponse:
    continuity = saved_version.replay_evidence.continuity
    return AdvisoryReplayEvidenceResponse(
        subject=AdvisoryReplaySubject(
            scope="WORKSPACE_SAVED_VERSION",
            workspace_id=session.workspace_id,
            workspace_version_id=saved_version.workspace_version_id,
            proposal_id=_optional_str(continuity.get("proposal_id")),
            proposal_version_no=_optional_int(continuity.get("proposal_version_no")),
        ),
        resolved_context=_to_replay_resolved_context(
            saved_version.replay_evidence.resolved_context
        ),
        hashes=AdvisoryReplayHashes(
            evaluation_request_hash=saved_version.replay_evidence.evaluation_request_hash,
            draft_state_hash=saved_version.replay_evidence.draft_state_hash,
        ),
        continuity=AdvisoryReplayContinuity(
            workspace_version_id=saved_version.workspace_version_id,
            handoff_action=_optional_str(continuity.get("handoff_action")),
            handoff_at=_optional_str(continuity.get("handoff_at")),
            handoff_by=_optional_str(continuity.get("handoff_by")),
            source_workspace_id=session.workspace_id,
            lifecycle_origin="WORKSPACE_HANDOFF"
            if continuity.get("proposal_id") is not None
            else None,
        ),
        evidence={
            "saved_at": saved_version.saved_at,
            "saved_by": saved_version.saved_by,
            "version_number": saved_version.version_number,
            "version_label": saved_version.version_label,
            "risk_lens": saved_version.replay_evidence.risk_lens,
            "proposal_decision_summary": _proposal_decision_summary_from_saved_version(
                saved_version
            ),
            "proposal_alternatives": _proposal_alternatives_from_saved_version(saved_version),
        },
        explanation={
            "source": "WORKSPACE_SAVED_VERSION",
            "continuity_status": (
                "LINKED_TO_PROPOSAL_LIFECYCLE"
                if continuity.get("proposal_id") is not None
                else "WORKSPACE_ONLY_REPLAY_EVIDENCE"
            ),
        },
    )


def build_proposal_version_replay_response(
    *,
    proposal: ProposalRecord,
    version: ProposalVersionRecord,
    events: list[ProposalWorkflowEventRecord],
) -> AdvisoryReplayEvidenceResponse:
    context_resolution = version.evidence_bundle_json.get("context_resolution", {})
    replay_lineage = version.evidence_bundle_json.get("replay_lineage", {})
    delivery_summary = build_delivery_summary_from_events(events)
    proposal_narrative = version.artifact_json.get("proposal_narrative")
    narrative_review = latest_narrative_review_record(events=events, version=version)
    return AdvisoryReplayEvidenceResponse(
        subject=AdvisoryReplaySubject(
            scope="PROPOSAL_VERSION",
            workspace_id=_optional_str(replay_lineage.get("workspace_id"))
            or proposal.source_workspace_id,
            workspace_version_id=_optional_str(replay_lineage.get("workspace_version_id")),
            proposal_id=proposal.proposal_id,
            proposal_version_id=version.proposal_version_id,
            proposal_version_no=version.version_no,
            operation_id=_optional_str(replay_lineage.get("async_operation_id")),
        ),
        resolved_context=_to_replay_resolved_context(context_resolution.get("resolved_context")),
        hashes=AdvisoryReplayHashes(
            request_hash=version.request_hash,
            evaluation_request_hash=_optional_str(replay_lineage.get("evaluation_request_hash")),
            draft_state_hash=_optional_str(replay_lineage.get("draft_state_hash")),
            simulation_hash=version.simulation_hash,
            artifact_hash=version.artifact_hash,
        ),
        continuity=AdvisoryReplayContinuity(
            lifecycle_origin=proposal.lifecycle_origin,
            source_workspace_id=proposal.source_workspace_id,
            workspace_version_id=_optional_str(replay_lineage.get("workspace_version_id")),
            handoff_action=_optional_str(replay_lineage.get("handoff_action")),
            handoff_at=_optional_str(replay_lineage.get("handoff_at")),
            handoff_by=_optional_str(replay_lineage.get("handoff_by")),
            async_operation_id=_optional_str(replay_lineage.get("async_operation_id")),
            async_operation_type=_optional_str(replay_lineage.get("async_operation_type")),
            correlation_id=_optional_str(replay_lineage.get("correlation_id")),
            idempotency_key=_optional_str(replay_lineage.get("idempotency_key")),
        ),
        evidence={
            "context_resolution": context_resolution,
            "replay_lineage": replay_lineage,
            "risk_lens": version.evidence_bundle_json.get("risk_lens"),
            "proposal_decision_summary": version.proposal_result_json.get(
                "proposal_decision_summary"
            ),
            "proposal_alternatives": version.proposal_result_json.get("proposal_alternatives"),
            "proposal_narrative": proposal_narrative,
            "proposal_narrative_review": (
                narrative_review.model_dump(mode="json") if narrative_review is not None else None
            ),
            "delivery": delivery_summary,
        },
        explanation={
            "source": "PROPOSAL_VERSION_EVIDENCE_BUNDLE",
            "continuity_status": (
                "WORKSPACE_AND_ASYNC_LINKED" if replay_lineage else "PROPOSAL_ONLY_REPLAY_EVIDENCE"
            ),
        },
    )


def build_async_operation_replay_response(
    *,
    operation: ProposalAsyncOperationRecord,
    proposal: Optional[ProposalRecord],
    version: Optional[ProposalVersionRecord],
    events: list[ProposalWorkflowEventRecord] | None = None,
) -> AdvisoryReplayEvidenceResponse:
    proposal_replay = _proposal_replay_response(
        proposal=proposal,
        version=version,
        events=events,
    )
    if proposal_replay is not None:
        return _async_operation_with_proposal_replay_response(
            operation=operation,
            proposal_replay=proposal_replay,
        )
    return _async_operation_only_replay_response(operation)


def _proposal_replay_response(
    *,
    proposal: Optional[ProposalRecord],
    version: Optional[ProposalVersionRecord],
    events: list[ProposalWorkflowEventRecord] | None,
) -> AdvisoryReplayEvidenceResponse | None:
    if proposal is None or version is None:
        return None
    return build_proposal_version_replay_response(
        proposal=proposal,
        version=version,
        events=events or [],
    )


def _async_operation_with_proposal_replay_response(
    *,
    operation: ProposalAsyncOperationRecord,
    proposal_replay: AdvisoryReplayEvidenceResponse,
) -> AdvisoryReplayEvidenceResponse:
    evidence = dict(proposal_replay.evidence)
    evidence["async_runtime"] = _async_runtime_evidence(operation)
    explanation = dict(proposal_replay.explanation)
    explanation["source"] = "ASYNC_OPERATION_AND_PROPOSAL_VERSION"
    return AdvisoryReplayEvidenceResponse(
        subject=_async_operation_subject(operation, proposal_replay),
        resolved_context=proposal_replay.resolved_context,
        hashes=proposal_replay.hashes,
        continuity=_async_operation_continuity(operation, proposal_replay),
        evidence=evidence,
        explanation=explanation,
    )


def _async_operation_only_replay_response(
    operation: ProposalAsyncOperationRecord,
) -> AdvisoryReplayEvidenceResponse:
    return AdvisoryReplayEvidenceResponse(
        subject=AdvisoryReplaySubject(
            scope="ASYNC_OPERATION",
            proposal_id=operation.proposal_id,
            operation_id=operation.operation_id,
        ),
        resolved_context=None,
        hashes=AdvisoryReplayHashes(),
        continuity=AdvisoryReplayContinuity(
            async_operation_id=operation.operation_id,
            async_operation_type=operation.operation_type,
            correlation_id=operation.correlation_id,
            idempotency_key=operation.idempotency_key,
        ),
        evidence={
            "async_runtime": _async_runtime_evidence(
                operation,
                include_payload=True,
            )
        },
        explanation={
            "source": "ASYNC_OPERATION_ONLY",
            "continuity_status": "NO_TERMINAL_PROPOSAL_VERSION_AVAILABLE",
        },
    )


def _async_operation_subject(
    operation: ProposalAsyncOperationRecord,
    proposal_replay: AdvisoryReplayEvidenceResponse,
) -> AdvisoryReplaySubject:
    return cast(
        AdvisoryReplaySubject,
        proposal_replay.subject.model_copy(
            update={
                "scope": "ASYNC_OPERATION",
                "operation_id": operation.operation_id,
            }
        ),
    )


def _async_operation_continuity(
    operation: ProposalAsyncOperationRecord,
    proposal_replay: AdvisoryReplayEvidenceResponse,
) -> AdvisoryReplayContinuity:
    return cast(
        AdvisoryReplayContinuity,
        proposal_replay.continuity.model_copy(
            update={
                "async_operation_id": operation.operation_id,
                "async_operation_type": operation.operation_type,
                "correlation_id": operation.correlation_id,
                "idempotency_key": operation.idempotency_key,
            }
        ),
    )


def _async_runtime_evidence(
    operation: ProposalAsyncOperationRecord,
    *,
    include_payload: bool = False,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "status": operation.status,
        "attempt_count": operation.attempt_count,
        "max_attempts": operation.max_attempts,
        "created_at": operation.created_at.isoformat(),
        "started_at": operation.started_at.isoformat() if operation.started_at else None,
        "finished_at": operation.finished_at.isoformat() if operation.finished_at else None,
    }
    if include_payload:
        evidence["payload_json"] = operation.payload_json
        evidence["error"] = operation.error_json
    return evidence


def _to_replay_resolved_context(
    raw_context: Any,
) -> AdvisoryReplayResolvedContext | None:
    if raw_context is None:
        return None
    if hasattr(raw_context, "model_dump"):
        data = raw_context.model_dump(mode="json")
    elif isinstance(raw_context, dict):
        data = raw_context
    else:
        return None
    if data.get("portfolio_id") is None:
        return None
    context: AdvisoryReplayResolvedContext = AdvisoryReplayResolvedContext.model_validate(data)
    return context


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _proposal_decision_summary_from_saved_version(
    saved_version: WorkspaceSavedVersion,
) -> dict[str, Any] | None:
    if saved_version.latest_proposal_result is None:
        return None
    summary = saved_version.latest_proposal_result.proposal_decision_summary
    if summary is None:
        return None
    return cast(dict[str, Any], summary.model_dump(mode="json"))


def _proposal_alternatives_from_saved_version(
    saved_version: WorkspaceSavedVersion,
) -> dict[str, Any] | None:
    if saved_version.latest_proposal_result is None:
        return None
    alternatives = saved_version.latest_proposal_result.proposal_alternatives
    if alternatives is None:
        return None
    return cast(dict[str, Any], alternatives.model_dump(mode="json"))
