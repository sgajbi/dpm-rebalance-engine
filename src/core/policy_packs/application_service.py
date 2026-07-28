from __future__ import annotations

from typing import Any

from src.core.policy_packs.ai import request_policy_evaluation_ai_evidence
from src.core.policy_packs.ai_models import (
    PolicyEvaluationAiEvidenceRequest,
    PolicyEvaluationAiEvidenceResponse,
)
from src.core.policy_packs.catalog import (
    activate_policy_pack_version,
    get_policy_pack_version,
    list_policy_pack_versions,
    validate_policy_pack_version,
)
from src.core.policy_packs.catalog_models import (
    PolicyPackActivationResponse,
    PolicyPackDetailResponse,
    PolicyPackListResponse,
    PolicyPackValidationResponse,
)
from src.core.policy_packs.diagnostics import get_policy_evaluation_diagnostics
from src.core.policy_packs.persistence import (
    append_policy_evaluation_event,
    finalize_policy_evaluation_record,
    get_policy_evaluation_lineage,
    get_policy_evaluation_record,
    get_policy_evaluation_review_queue,
    get_policy_evaluation_sign_off_package,
    replay_policy_evaluation_record,
)
from src.core.policy_packs.persistence_models import (
    PolicyEvaluationAuditEvent,
    PolicyEvaluationPersistenceResult,
    PolicyEvaluationRecord,
    PolicyEvaluationReplayResponse,
    PolicyEvaluationReviewEventType,
)
from src.core.policy_packs.ports import PolicyAiEvidenceClient, PolicyReportPackageClient
from src.core.policy_packs.projection_models import (
    PolicyEvaluationDiagnosticsResponse,
    PolicyEvaluationLineageResponse,
    PolicyEvaluationReviewQueueResponse,
    PolicyEvaluationSignOffPackageResponse,
)
from src.core.policy_packs.reporting import request_policy_evaluation_report_package
from src.core.policy_packs.reporting_models import (
    PolicyEvaluationReportPackageRequest,
    PolicyEvaluationReportPackageResponse,
)
from src.core.policy_packs.workflow import (
    get_policy_evaluation_workflow,
    record_policy_evaluation_sign_off_decision,
)
from src.core.policy_packs.workflow_models import (
    PolicyEvaluationSignOffDecisionRequest,
    PolicyEvaluationSignOffDecisionResponse,
    PolicyEvaluationWorkflowResponse,
)


class PolicyEvidenceApplicationService:
    def list_policy_pack_versions(self) -> PolicyPackListResponse:
        return list_policy_pack_versions()

    def get_policy_pack_version(
        self, *, policy_pack_id: str, policy_version: str
    ) -> PolicyPackDetailResponse:
        return get_policy_pack_version(
            policy_pack_id=policy_pack_id,
            policy_version=policy_version,
        )

    def validate_policy_pack_version(
        self,
        *,
        policy_pack_id: str,
        policy_version: str,
        requested_by: str,
        idempotency_key: str,
        reason: dict[str, Any],
    ) -> PolicyPackValidationResponse:
        return validate_policy_pack_version(
            policy_pack_id=policy_pack_id,
            policy_version=policy_version,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
            reason=reason,
        )

    def activate_policy_pack_version(
        self,
        *,
        policy_pack_id: str,
        policy_version: str,
        activated_by: str,
        source_content_hash: str,
        idempotency_key: str,
        reason: dict[str, Any],
    ) -> PolicyPackActivationResponse:
        return activate_policy_pack_version(
            policy_pack_id=policy_pack_id,
            policy_version=policy_version,
            activated_by=activated_by,
            source_content_hash=source_content_hash,
            idempotency_key=idempotency_key,
            reason=reason,
        )

    def finalize_policy_evaluation_record(
        self,
        *,
        evidence_bundle: dict[str, Any],
        policy_pack_id: str,
        policy_version: str,
        proposal_id: str,
        proposal_version_id: str,
        created_by: str,
        idempotency_key: str,
        reason: dict[str, Any],
        observed_trace_id: str | None = None,
    ) -> PolicyEvaluationPersistenceResult:
        return finalize_policy_evaluation_record(
            evidence_bundle=evidence_bundle,
            policy_pack_id=policy_pack_id,
            policy_version=policy_version,
            proposal_id=proposal_id,
            proposal_version_id=proposal_version_id,
            created_by=created_by,
            idempotency_key=idempotency_key,
            reason=reason,
            observed_trace_id=observed_trace_id,
        )

    def append_policy_evaluation_event(
        self,
        *,
        evaluation_id: str,
        event_type: PolicyEvaluationReviewEventType,
        actor_id: str,
        reason: dict[str, Any],
        idempotency_key: str | None,
    ) -> PolicyEvaluationAuditEvent:
        return append_policy_evaluation_event(
            evaluation_id=evaluation_id,
            event_type=event_type,
            actor_id=actor_id,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def get_policy_evaluation_review_queue(
        self, *, evaluation_status: str | None, portfolio_id: str | None
    ) -> PolicyEvaluationReviewQueueResponse:
        return get_policy_evaluation_review_queue(
            evaluation_status=evaluation_status,
            portfolio_id=portfolio_id,
        )

    def get_policy_evaluation_record(self, *, evaluation_id: str) -> PolicyEvaluationRecord:
        return get_policy_evaluation_record(evaluation_id=evaluation_id)

    def replay_policy_evaluation_record(
        self, *, evaluation_id: str, evidence_bundle: dict[str, Any] | None
    ) -> PolicyEvaluationReplayResponse:
        return replay_policy_evaluation_record(
            evaluation_id=evaluation_id,
            evidence_bundle=evidence_bundle,
        )

    def get_policy_evaluation_lineage(
        self, *, evaluation_id: str
    ) -> PolicyEvaluationLineageResponse:
        return get_policy_evaluation_lineage(evaluation_id=evaluation_id)

    def get_policy_evaluation_diagnostics(
        self, *, evaluation_id: str
    ) -> PolicyEvaluationDiagnosticsResponse:
        return get_policy_evaluation_diagnostics(evaluation_id=evaluation_id)

    def get_policy_evaluation_sign_off_package(
        self, *, evaluation_id: str
    ) -> PolicyEvaluationSignOffPackageResponse:
        return get_policy_evaluation_sign_off_package(evaluation_id=evaluation_id)

    def get_policy_evaluation_workflow(
        self, *, evaluation_id: str
    ) -> PolicyEvaluationWorkflowResponse:
        return get_policy_evaluation_workflow(evaluation_id=evaluation_id)

    def record_policy_evaluation_sign_off_decision(
        self,
        *,
        evaluation_id: str,
        payload: PolicyEvaluationSignOffDecisionRequest,
        idempotency_key: str,
    ) -> PolicyEvaluationSignOffDecisionResponse:
        return record_policy_evaluation_sign_off_decision(
            evaluation_id=evaluation_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )

    def request_policy_evaluation_report_package(
        self,
        *,
        evaluation_id: str,
        payload: PolicyEvaluationReportPackageRequest,
        report_request_id: str,
        report_client: PolicyReportPackageClient,
        idempotency_key: str,
    ) -> PolicyEvaluationReportPackageResponse:
        return request_policy_evaluation_report_package(
            evaluation_id=evaluation_id,
            payload=payload,
            report_request_id=report_request_id,
            report_client=report_client,
            idempotency_key=idempotency_key,
        )

    def request_policy_evaluation_ai_evidence(
        self,
        *,
        evaluation_id: str,
        payload: PolicyEvaluationAiEvidenceRequest,
        ai_client: PolicyAiEvidenceClient,
        idempotency_key: str,
    ) -> PolicyEvaluationAiEvidenceResponse:
        return request_policy_evaluation_ai_evidence(
            evaluation_id=evaluation_id,
            payload=payload,
            ai_client=ai_client,
            idempotency_key=idempotency_key,
        )


__all__ = ["PolicyEvidenceApplicationService"]
