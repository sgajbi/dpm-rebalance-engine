from typing import cast

from fastapi import Depends, status

import src.api.proposals.router as shared
from src.api.observability import record_policy_evaluation_operation, trace_id_var
from src.api.proposals.errors import run_proposal_operation
from src.api.proposals.policy_control_principal import (
    POLICY_EVALUATION_FINALIZE_CAPABILITY,
    POLICY_EVALUATION_REVIEW_EVENT_CAPABILITY,
    PolicyControlPrincipal,
    assert_policy_evaluation_create_scope,
    assert_policy_evaluation_record_scope,
    bind_policy_control_actor,
    policy_control_audit_reason,
    require_policy_evaluation_finalize_principal,
    require_policy_evaluation_review_principal,
)
from src.api.proposals.policy_evaluation_parameters import (
    PolicyEvaluationEventIdempotencyKeyHeader,
    PolicyEvaluationFinalizeIdempotencyKeyHeader,
    PolicyEvaluationIdPath,
    PolicyEvaluationProposalIdPath,
    PolicyEvaluationProposalVersionIdPath,
)
from src.api.proposals.policy_evaluation_responses import (
    POLICY_EVALUATION_CREATE_RESPONSES,
    POLICY_EVALUATION_EVENT_RESPONSES,
)
from src.core.policy_packs import (
    PolicyEvaluationAuditEvent,
    PolicyEvaluationCreateRequest,
    PolicyEvaluationEventRequest,
    PolicyEvaluationPersistenceResult,
)
from src.core.proposals.exceptions import ProposalIdempotencyConflictError, ProposalValidationError


@shared.router.post(
    "/advisory/proposals/{proposal_id}/versions/{proposal_version_id}/policy-evaluations",
    response_model=PolicyEvaluationPersistenceResult,
    status_code=status.HTTP_200_OK,
    tags=["Advisory Policy Evaluation"],
    summary="Create Or Replay Policy Evaluation",
    description=(
        "Creates or replays a finalized RFC-0025 policy evaluation record from source-backed "
        "proposal evidence. The record is hash-backed, idempotent, and bounded to Advise APIs; "
        "the `created_by` field must match the trusted `X-Actor-Id` advisor principal and the "
        "request must carry authorized proposal, portfolio, tenant, and legal-entity scope. "
        "Gateway/Workbench consumption and signed-off report-package handoff are supported by "
        "the current RFC-0025 implementation, while client-ready publication remains gated."
    ),
    responses=POLICY_EVALUATION_CREATE_RESPONSES,
)
def create_or_replay_policy_evaluation(
    proposal_id: PolicyEvaluationProposalIdPath,
    proposal_version_id: PolicyEvaluationProposalVersionIdPath,
    payload: PolicyEvaluationCreateRequest,
    idempotency_key: PolicyEvaluationFinalizeIdempotencyKeyHeader,
    principal: PolicyControlPrincipal = Depends(require_policy_evaluation_finalize_principal),
) -> PolicyEvaluationPersistenceResult:
    return cast(
        PolicyEvaluationPersistenceResult,
        run_proposal_operation(
            lambda: _create_or_replay_policy_evaluation_with_telemetry(
                proposal_id=proposal_id,
                proposal_version_id=proposal_version_id,
                payload=payload,
                idempotency_key=idempotency_key,
                principal=principal,
            )
        ),
    )


@shared.router.post(
    "/advisory/policy-evaluations/{evaluation_id}/events",
    response_model=PolicyEvaluationAuditEvent,
    status_code=status.HTTP_200_OK,
    tags=["Advisory Policy Evaluation"],
    summary="Record Policy Evaluation Review Event",
    description=(
        "Records an append-only non-privileged policy review event against the finalized policy "
        "evaluation hash. The `actor_id` field must match the trusted compliance or policy "
        "steward principal, and the request must be authorized for the evaluation scope. "
        "Sign-off, report/archive, AI-evidence, and finalized events are created "
        "only through their specialized workflow, report-package, AI-evidence, and finalize "
        "commands. Event capture does not mutate immutable evaluation truth or release "
        "client-ready publication."
    ),
    responses=POLICY_EVALUATION_EVENT_RESPONSES,
)
def record_policy_evaluation_event(
    evaluation_id: PolicyEvaluationIdPath,
    payload: PolicyEvaluationEventRequest,
    idempotency_key: PolicyEvaluationEventIdempotencyKeyHeader,
    principal: PolicyControlPrincipal = Depends(require_policy_evaluation_review_principal),
) -> PolicyEvaluationAuditEvent:
    return cast(
        PolicyEvaluationAuditEvent,
        run_proposal_operation(
            lambda: _record_policy_evaluation_event_with_telemetry(
                evaluation_id=evaluation_id,
                payload=payload,
                idempotency_key=idempotency_key,
                principal=principal,
            )
        ),
    )


def _create_or_replay_policy_evaluation_with_telemetry(
    *,
    proposal_id: str,
    proposal_version_id: str,
    payload: PolicyEvaluationCreateRequest,
    idempotency_key: str,
    principal: PolicyControlPrincipal,
) -> PolicyEvaluationPersistenceResult:
    assert_policy_evaluation_create_scope(
        principal=principal,
        proposal_id=proposal_id,
        evidence_bundle=payload.evidence_bundle,
    )
    try:
        response = (
            shared.get_policy_evidence_application_service().finalize_policy_evaluation_record(
                evidence_bundle=payload.evidence_bundle,
                policy_pack_id=payload.policy_pack_id,
                policy_version=payload.policy_version,
                proposal_id=proposal_id,
                proposal_version_id=proposal_version_id,
                created_by=bind_policy_control_actor(payload.created_by, principal),
                idempotency_key=idempotency_key,
                reason=policy_control_audit_reason(
                    payload.reason,
                    principal=principal,
                    capability=POLICY_EVALUATION_FINALIZE_CAPABILITY,
                ),
                observed_trace_id=trace_id_var.get() or None,
            )
        )
    except ProposalIdempotencyConflictError:
        _record_policy_command_operation("create", "conflict", "idempotency")
        raise
    except ProposalValidationError as exc:
        _record_policy_command_operation("create", "validation_blocked", str(exc))
        raise
    _record_policy_command_operation(
        "create",
        "replay" if response.replayed else "success",
        "replayed" if response.replayed else "finalized",
    )
    return response


def _record_policy_evaluation_event_with_telemetry(
    *,
    evaluation_id: str,
    payload: PolicyEvaluationEventRequest,
    idempotency_key: str,
    principal: PolicyControlPrincipal,
) -> PolicyEvaluationAuditEvent:
    service = shared.get_policy_evidence_application_service()
    record = service.get_policy_evaluation_record(evaluation_id=evaluation_id)
    lineage = service.get_policy_evaluation_lineage(evaluation_id=evaluation_id)
    assert_policy_evaluation_record_scope(
        principal=principal,
        record=record,
        lineage=lineage,
    )
    try:
        response = service.append_policy_evaluation_event(
            evaluation_id=evaluation_id,
            event_type=payload.event_type,
            actor_id=bind_policy_control_actor(payload.actor_id, principal),
            reason=policy_control_audit_reason(
                payload.reason,
                principal=principal,
                capability=POLICY_EVALUATION_REVIEW_EVENT_CAPABILITY,
            ),
            idempotency_key=idempotency_key,
        )
    except ProposalIdempotencyConflictError:
        _record_policy_command_operation("review_recorded", "conflict", "idempotency")
        raise
    except ProposalValidationError as exc:
        _record_policy_command_operation("review_recorded", "validation_blocked", str(exc))
        raise
    _record_policy_command_operation("review_recorded", "success", "recorded")
    return response


def _record_policy_command_operation(operation: str, status: str, reason: str) -> None:
    record_policy_evaluation_operation(
        operation=f"policy_evaluation.{operation}",
        status=status,
        reason=reason,
        dependency="none",
    )


__all__ = [
    "create_or_replay_policy_evaluation",
    "record_policy_evaluation_event",
]
