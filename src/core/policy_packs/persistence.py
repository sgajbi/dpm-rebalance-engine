from __future__ import annotations

from typing import Any

from src.core.common.idempotency import normalize_optional_idempotency_key
from src.core.policy_packs.event_authority import PolicyEvaluationEventAuthority
from src.core.policy_packs.persistence_models import (
    PolicyEvaluationAuditEvent,
    PolicyEvaluationEventType,
    PolicyEvaluationPersistenceResult,
    PolicyEvaluationRecord,
    PolicyEvaluationReplayResponse,
)
from src.core.policy_packs.persistence_store import PolicyEvaluationRecordStore
from src.core.policy_packs.projection_models import (
    PolicyEvaluationLineageResponse,
    PolicyEvaluationReviewQueueResponse,
    PolicyEvaluationSignOffPackageResponse,
)
from src.core.policy_packs.repositories import PolicyEvaluationRepository
from src.core.policy_packs.supportability import (
    POLICY_EVALUATION_PERSISTENCE_CONTRACT_VERSION,
)
from src.core.proposals.idempotency_validation import require_proposal_idempotency_key

_PERSISTENCE_CONTRACT_VERSION = POLICY_EVALUATION_PERSISTENCE_CONTRACT_VERSION


def finalize_policy_evaluation_record(
    *,
    evidence_bundle: dict[str, Any],
    policy_pack_id: str,
    policy_version: str,
    proposal_id: str,
    proposal_version_id: str,
    created_by: str,
    idempotency_key: str,
    reason: dict[str, Any] | None = None,
    observed_trace_id: str | None = None,
) -> PolicyEvaluationPersistenceResult:
    idempotency_key = require_proposal_idempotency_key(idempotency_key)
    return _repository().finalize_policy_evaluation_record(
        evidence_bundle=evidence_bundle,
        policy_pack_id=policy_pack_id,
        policy_version=policy_version,
        proposal_id=proposal_id,
        proposal_version_id=proposal_version_id,
        created_by=created_by,
        idempotency_key=idempotency_key,
        reason=reason or {},
        observed_trace_id=observed_trace_id,
    )


def get_policy_evaluation_record(*, evaluation_id: str) -> PolicyEvaluationRecord:
    return _repository().get_policy_evaluation_record(evaluation_id=evaluation_id)


def list_policy_evaluation_records(
    *, evaluation_status: str | None = None, portfolio_id: str | None = None
) -> list[PolicyEvaluationRecord]:
    return _repository().list_policy_evaluation_records(
        evaluation_status=evaluation_status,
        portfolio_id=portfolio_id,
    )


def list_policy_evaluation_events(*, evaluation_id: str) -> list[PolicyEvaluationAuditEvent]:
    return _repository().list_policy_evaluation_events(evaluation_id=evaluation_id)


def get_policy_evaluation_lineage(*, evaluation_id: str) -> PolicyEvaluationLineageResponse:
    return _repository().get_policy_evaluation_lineage(evaluation_id=evaluation_id)


def get_policy_evaluation_review_queue(
    *, evaluation_status: str | None = "PENDING_REVIEW", portfolio_id: str | None = None
) -> PolicyEvaluationReviewQueueResponse:
    return _repository().get_policy_evaluation_review_queue(
        evaluation_status=evaluation_status,
        portfolio_id=portfolio_id,
    )


def get_policy_evaluation_sign_off_package(
    *, evaluation_id: str
) -> PolicyEvaluationSignOffPackageResponse:
    return _repository().get_policy_evaluation_sign_off_package(evaluation_id=evaluation_id)


def append_policy_evaluation_event(
    *,
    evaluation_id: str,
    event_type: PolicyEvaluationEventType,
    actor_id: str,
    reason: dict[str, Any],
    idempotency_key: str | None = None,
    authority: PolicyEvaluationEventAuthority | None = None,
) -> PolicyEvaluationAuditEvent:
    idempotency_key = normalize_optional_idempotency_key(idempotency_key)
    return _repository().append_policy_evaluation_event(
        evaluation_id=evaluation_id,
        event_type=event_type,
        actor_id=actor_id,
        reason=reason,
        idempotency_key=idempotency_key,
        authority=authority,
    )


def replay_policy_evaluation_record(
    *, evaluation_id: str, evidence_bundle: dict[str, Any] | None = None
) -> PolicyEvaluationReplayResponse:
    return _repository().replay_policy_evaluation_record(
        evaluation_id=evaluation_id,
        evidence_bundle=evidence_bundle,
    )


def configure_policy_evaluation_repository(repository: PolicyEvaluationRepository) -> None:
    global _REPOSITORY
    _REPOSITORY = repository


def get_policy_evaluation_repository() -> PolicyEvaluationRepository:
    return _repository()


def reset_policy_evaluation_store_for_tests() -> None:
    configure_policy_evaluation_repository(PolicyEvaluationRecordStore())


def _repository() -> PolicyEvaluationRepository:
    return _REPOSITORY


_REPOSITORY: PolicyEvaluationRepository = PolicyEvaluationRecordStore()
