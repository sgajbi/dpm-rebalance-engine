from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from src.core.common.idempotency import normalize_optional_idempotency_key
from src.core.proposals.exceptions import ProposalValidationError
from src.core.proposals.identifiers import stable_memo_report_request_id
from src.core.proposals.memo_ai_ports import ProposalMemoAiCommentaryDraft
from src.core.proposals.memo_event_recording import (
    append_or_replay_memo_event,
    find_replayed_memo_event,
    memo_event_request_hash,
)
from src.core.proposals.memo_external_packages import (
    build_memo_ai_evidence,
    build_report_memo_package,
)
from src.core.proposals.memo_request_context import (
    load_memo_for_proposal_version,
    load_proposal_version_for_memo,
    require_advisor_use_review,
    validate_source_memo_hash,
)
from src.core.proposals.memo_response_projection import (
    build_memo_response,
    commentary_from_ai_event,
    memo_report_status,
    report_response_from_event,
    to_audit_event,
)
from src.core.proposals.models import (
    ProposalMemoAiCommentaryRequest,
    ProposalMemoAiCommentaryResponse,
    ProposalMemoReportPackageRequest,
    ProposalMemoReportPackageResponse,
    ProposalReportResponse,
)
from src.core.proposals.projections import to_proposal_summary, to_version_detail
from src.core.proposals.repository import ProposalRepository

MemoReportRequester = Callable[..., ProposalReportResponse]
MemoAiCommentaryGenerator = Callable[..., ProposalMemoAiCommentaryDraft]
MemoAiUnavailableCommentaryBuilder = Callable[[str], ProposalMemoAiCommentaryDraft]


def request_memo_report_package_operation(
    *,
    repository: ProposalRepository,
    proposal_id: str,
    version_no: int,
    payload: ProposalMemoReportPackageRequest,
    idempotency_key: str | None,
    report_request_id: str,
    event_id: str,
    occurred_at: datetime,
    request_report_package: MemoReportRequester,
) -> ProposalMemoReportPackageResponse:
    idempotency_key = normalize_optional_idempotency_key(idempotency_key)
    proposal, version = load_proposal_version_for_memo(
        repository=repository,
        proposal_id=proposal_id,
        version_no=version_no,
    )
    memo = load_memo_for_proposal_version(
        repository=repository, proposal_id=proposal_id, version_no=version_no
    )
    validate_source_memo_hash(memo=memo, source_memo_hash=payload.source_memo_hash)
    if payload.client_ready_document_requested:
        raise ProposalValidationError("MEMO_CLIENT_READY_DOCUMENT_NOT_SUPPORTED")
    memo_events = repository.list_memo_events(memo_id=memo.memo_id)
    review_posture = require_advisor_use_review(memo=memo, events=memo_events)

    request_hash = memo_event_request_hash(
        {
            "operation": "MEMO_REPORT_PACKAGE_REQUESTED",
            "memo_id": memo.memo_id,
            "requested_by": payload.requested_by,
            "source_memo_hash": payload.source_memo_hash,
            "requested_output_formats": payload.requested_output_formats,
            "client_ready_document_requested": payload.client_ready_document_requested,
            "reason": payload.reason,
        }
    )
    if idempotency_key:
        replayed_event = find_replayed_memo_event(
            repository=repository,
            memo=memo,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replayed_event is not None:
            return ProposalMemoReportPackageResponse(
                memo=build_memo_response(repository=repository, proposal=proposal, memo=memo),
                report_package_event=to_audit_event(replayed_event),
                report=report_response_from_event(proposal=proposal, event=replayed_event),
                replayed=True,
            )
        report_request_id = stable_memo_report_request_id(
            proposal_id=proposal.proposal_id,
            memo_id=memo.memo_id,
            idempotency_key=idempotency_key,
        )
    report = request_report_package(
        request={
            "report_request_id": report_request_id,
            "proposal": to_proposal_summary(proposal).model_dump(mode="json"),
            "proposal_version": to_version_detail(version, include_evidence=True).model_dump(
                mode="json"
            ),
            "report_type": "PORTFOLIO_REVIEW",
            "requested_by": payload.requested_by,
            "related_version_no": version_no,
            "requested_output_formats": payload.requested_output_formats,
            "proposal_memo_package": build_report_memo_package(
                memo=memo,
                payload=payload,
                review_posture=review_posture,
            ),
            "reason": payload.reason,
        }
    )
    event, replayed = append_or_replay_memo_event(
        repository=repository,
        memo=memo,
        event_id=event_id,
        event_type="MEMO_REPORT_PACKAGE_RECORDED",
        actor_id=payload.requested_by,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        reason={
            "report_package_id": report.report_reference_id,
            "report_package_status": memo_report_status(report.status),
            "source_memo_hash": payload.source_memo_hash,
            "client_ready_publication": "BLOCKED",
            "requested_output_formats": payload.requested_output_formats,
            "report_request_id": report.report_request_id,
            "report_service": report.report_service,
            "report_status": report.status,
            "report_status_url": report.artifact_url,
            "render": report.explanation.get("render", {}),
            "archive": report.explanation.get("archive", {}),
            "reason": payload.reason,
        },
    )
    return ProposalMemoReportPackageResponse(
        memo=build_memo_response(repository=repository, proposal=proposal, memo=memo),
        report_package_event=to_audit_event(event),
        report=report,
        replayed=replayed,
    )


def request_memo_ai_commentary_operation(
    *,
    repository: ProposalRepository,
    proposal_id: str,
    version_no: int,
    payload: ProposalMemoAiCommentaryRequest,
    idempotency_key: str | None,
    event_id: str,
    occurred_at: datetime,
    generate_commentary: MemoAiCommentaryGenerator,
    build_unavailable_commentary: MemoAiUnavailableCommentaryBuilder,
    unavailable_error: type[Exception],
) -> ProposalMemoAiCommentaryResponse:
    idempotency_key = normalize_optional_idempotency_key(idempotency_key)
    proposal, _version = load_proposal_version_for_memo(
        repository=repository,
        proposal_id=proposal_id,
        version_no=version_no,
    )
    memo = load_memo_for_proposal_version(
        repository=repository, proposal_id=proposal_id, version_no=version_no
    )
    validate_source_memo_hash(memo=memo, source_memo_hash=payload.source_memo_hash)
    memo_events = repository.list_memo_events(memo_id=memo.memo_id)
    review_posture = require_advisor_use_review(memo=memo, events=memo_events)
    requested_sections = [str(section) for section in payload.requested_sections]
    request_hash = memo_event_request_hash(
        {
            "operation": "MEMO_AI_REFERENCE_REQUESTED",
            "memo_id": memo.memo_id,
            "requested_by": payload.requested_by,
            "source_memo_hash": payload.source_memo_hash,
            "requested_sections": requested_sections,
            "reason": payload.reason,
        }
    )
    if idempotency_key:
        replayed_event = find_replayed_memo_event(
            repository=repository,
            memo=memo,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replayed_event is not None:
            return ProposalMemoAiCommentaryResponse(
                memo=build_memo_response(repository=repository, proposal=proposal, memo=memo),
                ai_event=to_audit_event(replayed_event),
                commentary=commentary_from_ai_event(replayed_event),
                replayed=True,
            )

    memo_evidence = build_memo_ai_evidence(memo=memo, review_posture=review_posture)
    try:
        commentary = generate_commentary(
            memo_evidence=memo_evidence,
            requested_sections=requested_sections,
            requested_by=payload.requested_by,
            reason=payload.reason,
        )
        ai_status = "REVIEW_REQUIRED"
    except unavailable_error as exc:
        commentary = build_unavailable_commentary(str(exc))
        ai_status = "UNAVAILABLE"

    event, replayed = append_or_replay_memo_event(
        repository=repository,
        memo=memo,
        event_id=event_id,
        event_type="MEMO_AI_REFERENCE_RECORDED",
        actor_id=payload.requested_by,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        reason={
            "ai_status": ai_status,
            "source_memo_hash": payload.source_memo_hash,
            "requested_sections": requested_sections,
            "client_ready_publication": "BLOCKED",
            "review_required": True,
            "authoritative_for_memo_status": False,
            "lineage": commentary.lineage,
            "sections": list(commentary.sections),
            "review_guidance": list(commentary.review_guidance),
            "reason": payload.reason,
        },
    )
    return ProposalMemoAiCommentaryResponse(
        memo=build_memo_response(repository=repository, proposal=proposal, memo=memo),
        ai_event=to_audit_event(event),
        commentary=commentary_from_ai_event(event),
        replayed=replayed,
    )
