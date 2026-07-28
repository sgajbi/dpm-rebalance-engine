from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from src.core.policy_packs.catalog import PolicyPackCatalogStore
from src.core.policy_packs.catalog_models import (
    PolicyPackActivationResponse,
    PolicyPackAuditEvent,
    PolicyPackDetailResponse,
    PolicyPackListResponse,
    PolicyPackValidationResponse,
)
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


class PolicyEvaluationStateStore(Protocol):
    def load_snapshot(self) -> dict[str, Any]: ...

    def save_snapshot(self, snapshot: dict[str, Any]) -> None: ...


class PolicyPackCatalogStateStore(Protocol):
    def load_snapshot(self) -> dict[str, Any]: ...

    def save_snapshot(self, snapshot: dict[str, Any]) -> None: ...


class InMemoryPolicyEvaluationStateStore:
    def __init__(self) -> None:
        self._snapshot: dict[str, Any] = {}

    def load_snapshot(self) -> dict[str, Any]:
        return deepcopy(self._snapshot)

    def save_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = deepcopy(snapshot)


class InMemoryPolicyPackCatalogStateStore:
    def __init__(self) -> None:
        self._snapshot: dict[str, Any] = {}

    def load_snapshot(self) -> dict[str, Any]:
        return deepcopy(self._snapshot)

    def save_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = deepcopy(snapshot)


class DurablePolicyEvaluationRepository:
    def __init__(self, *, state_store: PolicyEvaluationStateStore) -> None:
        self._state_store = state_store

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
        store = self._load_store()
        result = store.finalize_policy_evaluation_record(
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
        self._save_store(store)
        return result

    def get_policy_evaluation_record(self, *, evaluation_id: str) -> PolicyEvaluationRecord:
        return self._load_store().get_policy_evaluation_record(evaluation_id=evaluation_id)

    def list_policy_evaluation_records(
        self, *, evaluation_status: str | None, portfolio_id: str | None
    ) -> list[PolicyEvaluationRecord]:
        return self._load_store().list_policy_evaluation_records(
            evaluation_status=evaluation_status,
            portfolio_id=portfolio_id,
        )

    def list_policy_evaluation_events(
        self, *, evaluation_id: str
    ) -> list[PolicyEvaluationAuditEvent]:
        return self._load_store().list_policy_evaluation_events(evaluation_id=evaluation_id)

    def get_policy_evaluation_lineage(
        self, *, evaluation_id: str
    ) -> PolicyEvaluationLineageResponse:
        return self._load_store().get_policy_evaluation_lineage(evaluation_id=evaluation_id)

    def get_policy_evaluation_review_queue(
        self, *, evaluation_status: str | None, portfolio_id: str | None
    ) -> PolicyEvaluationReviewQueueResponse:
        return self._load_store().get_policy_evaluation_review_queue(
            evaluation_status=evaluation_status,
            portfolio_id=portfolio_id,
        )

    def get_policy_evaluation_sign_off_package(
        self, *, evaluation_id: str
    ) -> PolicyEvaluationSignOffPackageResponse:
        return self._load_store().get_policy_evaluation_sign_off_package(
            evaluation_id=evaluation_id
        )

    def append_policy_evaluation_event(
        self,
        *,
        evaluation_id: str,
        event_type: PolicyEvaluationEventType,
        actor_id: str,
        reason: dict[str, Any],
        idempotency_key: str | None,
        authority: PolicyEvaluationEventAuthority | None = None,
    ) -> PolicyEvaluationAuditEvent:
        store = self._load_store()
        event = store.append_policy_evaluation_event(
            evaluation_id=evaluation_id,
            event_type=event_type,
            actor_id=actor_id,
            reason=reason,
            idempotency_key=idempotency_key,
            authority=authority,
        )
        self._save_store(store)
        return event

    def replay_policy_evaluation_record(
        self,
        *,
        evaluation_id: str,
        evidence_bundle: dict[str, Any] | None,
    ) -> PolicyEvaluationReplayResponse:
        return self._load_store().replay_policy_evaluation_record(
            evaluation_id=evaluation_id,
            evidence_bundle=evidence_bundle,
        )

    def _load_store(self) -> PolicyEvaluationRecordStore:
        return PolicyEvaluationRecordStore.from_snapshot(self._state_store.load_snapshot())

    def _save_store(self, store: PolicyEvaluationRecordStore) -> None:
        self._state_store.save_snapshot(store.snapshot())


class DurablePolicyPackCatalogRepository:
    def __init__(self, *, state_store: PolicyPackCatalogStateStore) -> None:
        self._state_store = state_store

    def list_policy_pack_versions(self) -> PolicyPackListResponse:
        return self._load_store().list_policy_pack_versions()

    def get_policy_pack_version(
        self, *, policy_pack_id: str, policy_version: str
    ) -> PolicyPackDetailResponse:
        return self._load_store().get_policy_pack_version(
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
        store = self._load_store()
        response = store.validate_policy_pack_version(
            policy_pack_id=policy_pack_id,
            policy_version=policy_version,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
            reason=reason,
        )
        self._save_store(store)
        return response

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
        store = self._load_store()
        response = store.activate_policy_pack_version(
            policy_pack_id=policy_pack_id,
            policy_version=policy_version,
            activated_by=activated_by,
            source_content_hash=source_content_hash,
            idempotency_key=idempotency_key,
            reason=reason,
        )
        self._save_store(store)
        return response

    def list_policy_pack_events(
        self, *, policy_pack_id: str, policy_version: str
    ) -> list[PolicyPackAuditEvent]:
        return self._load_store().list_policy_pack_events(
            policy_pack_id=policy_pack_id,
            policy_version=policy_version,
        )

    def _load_store(self) -> PolicyPackCatalogStore:
        return PolicyPackCatalogStore.from_snapshot(self._state_store.load_snapshot())

    def _save_store(self, store: PolicyPackCatalogStore) -> None:
        self._state_store.save_snapshot(store.snapshot())


__all__ = [
    "DurablePolicyEvaluationRepository",
    "DurablePolicyPackCatalogRepository",
    "InMemoryPolicyEvaluationStateStore",
    "InMemoryPolicyPackCatalogStateStore",
    "PolicyEvaluationStateStore",
    "PolicyPackCatalogStateStore",
]
