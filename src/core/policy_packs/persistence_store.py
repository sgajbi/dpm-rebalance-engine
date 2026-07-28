from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from src.core.common.canonical import hash_canonical_payload
from src.core.policy_packs.catalog import get_policy_pack_version
from src.core.policy_packs.evaluation import evaluate_policy_pack_version
from src.core.policy_packs.event_authority import (
    PolicyEvaluationEventAuthority,
    validate_policy_evaluation_event_authority,
)
from src.core.policy_packs.persistence_models import (
    PolicyEvaluationAuditEvent,
    PolicyEvaluationEventType,
    PolicyEvaluationPersistenceResult,
    PolicyEvaluationRecord,
    PolicyEvaluationReplayResponse,
)
from src.core.policy_packs.persistence_projection import (
    attach_policy_evaluation_event,
    build_policy_evaluation_lineage_response,
    policy_evaluation_api_posture,
)
from src.core.policy_packs.persistence_record_builder import build_policy_evaluation_record
from src.core.policy_packs.persistence_replay import build_policy_evaluation_replay_response
from src.core.policy_packs.projection_models import (
    PolicyEvaluationLineageResponse,
    PolicyEvaluationReviewQueueResponse,
    PolicyEvaluationSignOffPackageResponse,
)
from src.core.policy_packs.receipt_identity import idempotency_stable_reason
from src.core.policy_packs.supportability import (
    POLICY_EVALUATION_PERSISTENCE_CONTRACT_VERSION,
    policy_sign_off_package_posture,
)
from src.core.proposals.exceptions import (
    ProposalIdempotencyConflictError,
    ProposalNotFoundError,
)

_PERSISTENCE_CONTRACT_VERSION = POLICY_EVALUATION_PERSISTENCE_CONTRACT_VERSION


class PolicyEvaluationRecordStore:
    def __init__(self) -> None:
        self.reset()

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> PolicyEvaluationRecordStore:
        store = cls()
        store._records = {
            evaluation_id: PolicyEvaluationRecord.model_validate(record)
            for evaluation_id, record in snapshot.get("records", {}).items()
        }
        store._events = {
            evaluation_id: [PolicyEvaluationAuditEvent.model_validate(event) for event in events]
            for evaluation_id, events in snapshot.get("events", {}).items()
        }
        store._idempotency = {
            str(item["idempotency_key"]): (
                str(item["request_hash"]),
                str(item["evaluation_id"]),
                str(item["event_id"]),
            )
            for item in snapshot.get("idempotency", [])
        }
        store._identity_index = _identity_index_from_snapshot(snapshot.get("identity_index", []))
        return store

    def reset(self) -> None:
        self._records: dict[str, PolicyEvaluationRecord] = {}
        self._events: dict[str, list[PolicyEvaluationAuditEvent]] = {}
        self._idempotency: dict[str, tuple[str, str, str]] = {}
        self._identity_index: dict[tuple[str, str, str, str, str], str] = {}

    def snapshot(self) -> dict[str, Any]:
        return {
            "records": {
                evaluation_id: record.model_dump(mode="json")
                for evaluation_id, record in self._records.items()
            },
            "events": {
                evaluation_id: [event.model_dump(mode="json") for event in events]
                for evaluation_id, events in self._events.items()
            },
            "idempotency": [
                {
                    "idempotency_key": idempotency_key,
                    "request_hash": request_hash,
                    "evaluation_id": evaluation_id,
                    "event_id": event_id,
                }
                for idempotency_key, (
                    request_hash,
                    evaluation_id,
                    event_id,
                ) in self._idempotency.items()
            ],
            "identity_index": [
                {
                    "identity": list(identity),
                    "evaluation_id": evaluation_id,
                }
                for identity, evaluation_id in self._identity_index.items()
            ],
        }

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
        source_evidence_hash = hash_canonical_payload(evidence_bundle)
        request_hash = hash_canonical_payload(
            {
                "operation": "POLICY_EVALUATION_FINALIZED",
                "proposal_id": proposal_id,
                "proposal_version_id": proposal_version_id,
                "policy_pack_id": policy_pack_id,
                "policy_version": policy_version,
                "source_evidence_hash": source_evidence_hash,
                "reason": idempotency_stable_reason(reason),
            }
        )
        replayed = self._find_replayed_event(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replayed is not None:
            _, record = replayed
            return PolicyEvaluationPersistenceResult(
                record=deepcopy(record),
                created=False,
                replayed=True,
                audit_event=deepcopy(replayed[0]),
            )

        identity = (
            proposal_id,
            proposal_version_id,
            policy_pack_id,
            policy_version,
            source_evidence_hash,
        )
        existing_id = self._identity_index.get(identity)
        if existing_id is not None:
            record = self._load_record(existing_id)
            event = self._events[existing_id][0]
            self._idempotency[idempotency_key] = (request_hash, existing_id, event.event_id)
            return PolicyEvaluationPersistenceResult(
                record=deepcopy(record),
                created=False,
                replayed=False,
                audit_event=deepcopy(event),
            )

        evaluation = evaluate_policy_pack_version(
            evidence_bundle=deepcopy(evidence_bundle),
            policy_pack_id=policy_pack_id,
            policy_version=policy_version,
        )
        detail = get_policy_pack_version(
            policy_pack_id=policy_pack_id,
            policy_version=policy_version,
        )
        record = build_policy_evaluation_record(
            evaluation=evaluation,
            evidence_bundle=evidence_bundle,
            proposal_id=proposal_id,
            proposal_version_id=proposal_version_id,
            created_by=created_by,
            source_evidence_hash=source_evidence_hash,
            policy_content_hash=detail.policy_pack.content_hash,
            idempotency_key=idempotency_key,
            reason=reason,
            observed_trace_id=observed_trace_id,
        )
        event = self._event(
            record=record,
            event_type="POLICY_EVALUATION_FINALIZED",
            actor_id=created_by,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason={
                "evaluation_status": record.evaluation_status,
                "policy_content_hash": record.policy_content_hash,
                "source_evidence_hash": record.source_evidence_hash,
                "evaluation_hash": record.evaluation_hash,
                "finalization_reason": reason,
                **_trusted_principal_from_reason(reason),
            },
        )
        self._records[record.evaluation_id] = record
        self._events[record.evaluation_id] = [event]
        self._identity_index[identity] = record.evaluation_id
        self._idempotency[idempotency_key] = (
            request_hash,
            record.evaluation_id,
            event.event_id,
        )
        return PolicyEvaluationPersistenceResult(
            record=deepcopy(record),
            created=True,
            replayed=False,
            audit_event=deepcopy(event),
        )

    def get_policy_evaluation_record(self, *, evaluation_id: str) -> PolicyEvaluationRecord:
        return deepcopy(self._load_record(evaluation_id))

    def list_policy_evaluation_records(
        self, *, evaluation_status: str | None, portfolio_id: str | None
    ) -> list[PolicyEvaluationRecord]:
        return _copied_policy_evaluation_records(
            _ordered_policy_evaluation_records(
                _filtered_policy_evaluation_records(
                    self._records.values(),
                    evaluation_status=evaluation_status,
                    portfolio_id=portfolio_id,
                )
            )
        )

    def list_policy_evaluation_events(
        self, *, evaluation_id: str
    ) -> list[PolicyEvaluationAuditEvent]:
        self._load_record(evaluation_id)
        return [deepcopy(event) for event in self._events[evaluation_id]]

    def get_policy_evaluation_lineage(
        self, *, evaluation_id: str
    ) -> PolicyEvaluationLineageResponse:
        record = self._load_record(evaluation_id)
        return build_policy_evaluation_lineage_response(
            record=record,
            audit_events=self._events[evaluation_id],
        )

    def get_policy_evaluation_review_queue(
        self, *, evaluation_status: str | None, portfolio_id: str | None
    ) -> PolicyEvaluationReviewQueueResponse:
        return PolicyEvaluationReviewQueueResponse(
            items=self.list_policy_evaluation_records(
                evaluation_status=evaluation_status,
                portfolio_id=portfolio_id,
            ),
            queue_posture=policy_evaluation_api_posture(),
        )

    def get_policy_evaluation_sign_off_package(
        self, *, evaluation_id: str
    ) -> PolicyEvaluationSignOffPackageResponse:
        record = self._load_record(evaluation_id)
        lineage = build_policy_evaluation_lineage_response(
            record=record,
            audit_events=self._events[evaluation_id],
        )
        return PolicyEvaluationSignOffPackageResponse(
            evaluation=deepcopy(record),
            lineage=lineage,
            package_posture=policy_sign_off_package_posture(),
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
        record = self._load_record(evaluation_id)
        validate_policy_evaluation_event_authority(
            event_type=event_type,
            reason=reason,
            evaluation_hash=record.evaluation_hash,
            authority=authority,
        )
        request_hash = hash_canonical_payload(
            {
                "operation": event_type,
                "evaluation_id": evaluation_id,
                "actor_id": actor_id,
                "reason": reason,
                "evaluation_hash": record.evaluation_hash,
            }
        )
        if idempotency_key:
            replayed = self._find_replayed_event(
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replayed is not None:
                return deepcopy(replayed[0])
        event = self._event(
            record=record,
            event_type=event_type,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=deepcopy(reason),
        )
        self._events[evaluation_id].append(event)
        attach_policy_evaluation_event(record=record, event=event)
        if idempotency_key:
            self._idempotency[idempotency_key] = (request_hash, evaluation_id, event.event_id)
        return deepcopy(event)

    def replay_policy_evaluation_record(
        self,
        *,
        evaluation_id: str,
        evidence_bundle: dict[str, Any] | None,
    ) -> PolicyEvaluationReplayResponse:
        record = self._load_record(evaluation_id)
        return build_policy_evaluation_replay_response(
            record=record,
            evidence_bundle=evidence_bundle,
        )

    def _load_record(self, evaluation_id: str) -> PolicyEvaluationRecord:
        record = self._records.get(evaluation_id)
        if record is None:
            raise ProposalNotFoundError("POLICY_EVALUATION_RECORD_NOT_FOUND")
        return record

    def _event(
        self,
        *,
        record: PolicyEvaluationRecord,
        event_type: PolicyEvaluationEventType,
        actor_id: str,
        idempotency_key: str | None,
        request_hash: str,
        reason: dict[str, Any],
    ) -> PolicyEvaluationAuditEvent:
        events = self._events.get(record.evaluation_id, [])
        return PolicyEvaluationAuditEvent(
            event_id=f"peev_{len(events) + 1:06d}",
            evaluation_id=record.evaluation_id,
            proposal_id=record.proposal_id,
            proposal_version_id=record.proposal_version_id,
            event_type=event_type,
            actor_id=actor_id,
            occurred_at=datetime.now(UTC).isoformat(),
            content_hash=record.evaluation_hash,
            idempotency_key=idempotency_key,
            reason_json={
                **reason,
                "idempotency_request_hash": request_hash,
                "persistence_contract_version": _PERSISTENCE_CONTRACT_VERSION,
            },
        )

    def _find_replayed_event(
        self, *, idempotency_key: str, request_hash: str
    ) -> tuple[PolicyEvaluationAuditEvent, PolicyEvaluationRecord] | None:
        stored = self._idempotency.get(idempotency_key)
        if stored is None:
            return None
        stored_hash, evaluation_id, event_id = stored
        if stored_hash != request_hash:
            raise ProposalIdempotencyConflictError("POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT")
        record = self._load_record(evaluation_id)
        event = next(event for event in self._events[evaluation_id] if event.event_id == event_id)
        return event, record


def _filtered_policy_evaluation_records(
    records: Iterable[PolicyEvaluationRecord],
    *,
    evaluation_status: str | None,
    portfolio_id: str | None,
) -> list[PolicyEvaluationRecord]:
    filters = _policy_evaluation_record_filters(
        evaluation_status=evaluation_status,
        portfolio_id=portfolio_id,
    )
    return [record for record in records if all(matches(record) for matches in filters)]


def _policy_evaluation_record_filters(
    *,
    evaluation_status: str | None,
    portfolio_id: str | None,
) -> tuple[Callable[[PolicyEvaluationRecord], bool], ...]:
    filters: list[Callable[[PolicyEvaluationRecord], bool]] = []
    if evaluation_status:
        filters.append(lambda record: record.evaluation_status == evaluation_status)
    if portfolio_id:
        filters.append(lambda record: record.portfolio_id == portfolio_id)
    return tuple(filters)


def _ordered_policy_evaluation_records(
    records: list[PolicyEvaluationRecord],
) -> list[PolicyEvaluationRecord]:
    return sorted(records, key=lambda item: item.generated_at)


def _copied_policy_evaluation_records(
    records: list[PolicyEvaluationRecord],
) -> list[PolicyEvaluationRecord]:
    return [deepcopy(record) for record in records]


def _identity_index_from_snapshot(
    items: list[dict[str, Any]],
) -> dict[tuple[str, str, str, str, str], str]:
    index: dict[tuple[str, str, str, str, str], str] = {}
    for item in items:
        identity = [str(part) for part in item["identity"]]
        if len(identity) != 5:
            continue
        index[
            (
                identity[0],
                identity[1],
                identity[2],
                identity[3],
                identity[4],
            )
        ] = str(item["evaluation_id"])
    return index


def _trusted_principal_from_reason(reason: dict[str, Any]) -> dict[str, Any]:
    trusted_principal = reason.get("trusted_principal")
    if isinstance(trusted_principal, dict):
        return {"trusted_principal": trusted_principal}
    return {}


__all__ = ["PolicyEvaluationRecordStore"]
