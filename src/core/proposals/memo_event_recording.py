from __future__ import annotations

from datetime import datetime
from typing import Any

from src.core.common.canonical import hash_canonical_payload
from src.core.proposals.exceptions import ProposalIdempotencyConflictError
from src.core.proposals.memo_persistence_models import (
    ProposalMemoEventRecord,
    ProposalMemoEventType,
    ProposalMemoIdempotencyRecord,
    ProposalMemoRecord,
)
from src.core.proposals.repository import ProposalRepository


def memo_event_request_hash(payload: dict[str, Any]) -> str:
    return str(hash_canonical_payload(payload))


def append_or_replay_memo_event(
    *,
    repository: ProposalRepository,
    memo: ProposalMemoRecord,
    event_id: str,
    event_type: ProposalMemoEventType,
    actor_id: str,
    occurred_at: datetime,
    idempotency_key: str | None,
    request_hash: str,
    reason: dict[str, Any],
) -> tuple[ProposalMemoEventRecord, bool]:
    if idempotency_key:
        replayed = find_or_reserve_memo_event(
            repository=repository,
            memo=memo,
            event_type=event_type,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            occurred_at=occurred_at,
        )
        if replayed is not None:
            return replayed, True
    event = ProposalMemoEventRecord(
        event_id=event_id,
        memo_id=memo.memo_id,
        proposal_id=memo.proposal_id,
        proposal_version_no=memo.proposal_version_no,
        event_type=event_type,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason_json={
            **reason,
            "memo_hash": memo.memo_hash,
            "source_input_hash": memo.source_input_hash,
            "idempotency_key": idempotency_key,
            "idempotency_request_hash": request_hash,
        },
    )
    repository.append_memo_event(event)
    return event, False


def find_or_reserve_memo_event(
    *,
    repository: ProposalRepository,
    memo: ProposalMemoRecord,
    event_type: ProposalMemoEventType,
    idempotency_key: str,
    request_hash: str,
    occurred_at: datetime,
) -> ProposalMemoEventRecord | None:
    for event in repository.list_memo_events(memo_id=memo.memo_id):
        if event.reason_json.get("idempotency_key") != idempotency_key:
            continue
        if event.reason_json.get("idempotency_request_hash") != request_hash:
            raise ProposalIdempotencyConflictError("MEMO_EVENT_IDEMPOTENCY_KEY_CONFLICT")
        return event
    reservation_key = "memo-event-" + memo_event_request_hash(
        {"event_type": event_type, "memo_id": memo.memo_id, "key": idempotency_key}
    )
    reservation = ProposalMemoIdempotencyRecord(
        idempotency_key=reservation_key,
        request_hash=request_hash,
        created_at=occurred_at,
        **memo.model_dump(include={"memo_id", "proposal_id", "proposal_version_no"}),
    )
    _persist_memo_event_reservation(repository, reservation)
    return None


def _persist_memo_event_reservation(
    repository: ProposalRepository,
    reservation: ProposalMemoIdempotencyRecord,
) -> None:
    try:
        repository.save_memo_idempotency(reservation)
    except ValueError as exc:
        raise ProposalIdempotencyConflictError("MEMO_EVENT_IDEMPOTENCY_KEY_CONFLICT") from exc
    reserved = repository.get_memo_idempotency(idempotency_key=reservation.idempotency_key)
    if (
        reserved is None
        or reserved.model_copy(update={"created_at": reservation.created_at}) != reservation
    ):
        raise ProposalIdempotencyConflictError("MEMO_EVENT_IDEMPOTENCY_KEY_CONFLICT")
