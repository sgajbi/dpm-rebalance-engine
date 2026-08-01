from copy import deepcopy
from typing import Any

from src.core.common.canonical import hash_canonical_payload
from src.core.policy_packs.catalog_definitions import (
    REFERENCE_POSTURE,
    summary_from_definition,
    validate_definition,
)
from src.core.policy_packs.catalog_events import (
    append_policy_pack_catalog_event,
    find_replayed_policy_pack_catalog_event,
    latest_policy_pack_validation_event,
)
from src.core.policy_packs.catalog_models import (
    PolicyPackActivationResponse,
    PolicyPackAuditEvent,
    PolicyPackValidationResponse,
)
from src.core.policy_packs.receipt_identity import idempotency_stable_reason
from src.core.proposals.exceptions import ProposalValidationError


def validate_policy_pack_catalog_definition(
    *,
    definition: dict[str, Any],
    events: dict[tuple[str, str], list[PolicyPackAuditEvent]],
    idempotency: dict[str, tuple[str, PolicyPackAuditEvent]],
    policy_pack_id: str,
    policy_version: str,
    requested_by: str,
    idempotency_key: str,
    reason: dict[str, Any],
) -> PolicyPackValidationResponse:
    request_hash = hash_canonical_payload(
        {
            "operation": "POLICY_PACK_VALIDATED",
            "policy_pack_id": policy_pack_id,
            "policy_version": policy_version,
            "requested_by": requested_by,
            "content_hash": definition["content_hash"],
            "reason": _idempotency_stable_catalog_reason(reason),
        }
    )
    replayed = find_replayed_policy_pack_catalog_event(
        idempotency=idempotency,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replayed is not None:
        return PolicyPackValidationResponse(
            policy_pack=summary_from_definition(definition),
            validation_status="READY",
            diagnostics=list(replayed.reason.get("diagnostics", [])),
            validation_event=replayed,
            replayed=True,
        )

    diagnostics = validate_definition(definition)
    if diagnostics:
        raise ProposalValidationError(";".join(diagnostics))
    event = append_policy_pack_catalog_event(
        events=events,
        idempotency=idempotency,
        event_type="POLICY_PACK_VALIDATED",
        policy_pack_id=policy_pack_id,
        policy_version=policy_version,
        actor_id=requested_by,
        content_hash=str(definition["content_hash"]),
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        reason={
            "validation_status": "READY",
            "diagnostics": [],
            "dry_run_status": "REFERENCE_FIXTURES_VALIDATED",
            "sample_fixture_refs": list(definition["sample_fixture_refs"]),
            "reason": deepcopy(reason),
            "reference_posture": REFERENCE_POSTURE,
        },
    )
    return PolicyPackValidationResponse(
        policy_pack=summary_from_definition(definition),
        validation_status="READY",
        diagnostics=[],
        validation_event=event,
        replayed=False,
    )


def activate_policy_pack_catalog_definition(
    *,
    definition: dict[str, Any],
    events: dict[tuple[str, str], list[PolicyPackAuditEvent]],
    idempotency: dict[str, tuple[str, PolicyPackAuditEvent]],
    policy_pack_id: str,
    policy_version: str,
    activated_by: str,
    source_content_hash: str,
    idempotency_key: str,
    reason: dict[str, Any],
    previous_active_policy_version: str | None,
) -> PolicyPackActivationResponse:
    request_hash = _activation_request_hash(
        policy_pack_id=policy_pack_id,
        policy_version=policy_version,
        activated_by=activated_by,
        source_content_hash=source_content_hash,
        reason=reason,
    )
    replayed = find_replayed_policy_pack_catalog_event(
        idempotency=idempotency,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replayed is not None:
        return _activation_response_from_event(definition=definition, event=replayed)

    validation_event = _validated_activation_event(
        definition=definition,
        events=events,
        policy_pack_id=policy_pack_id,
        policy_version=policy_version,
        activated_by=activated_by,
        source_content_hash=source_content_hash,
    )

    definition["activation_state"] = "ACTIVE"
    event = append_policy_pack_catalog_event(
        events=events,
        idempotency=idempotency,
        event_type="POLICY_PACK_ACTIVATED",
        policy_pack_id=policy_pack_id,
        policy_version=policy_version,
        actor_id=activated_by,
        content_hash=str(definition["content_hash"]),
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        reason=_activation_event_reason(
            definition=definition,
            validation_event=validation_event,
            reason=reason,
            previous_active_policy_version=previous_active_policy_version,
        ),
    )
    return PolicyPackActivationResponse(
        policy_pack=summary_from_definition(definition),
        activation_event=event,
        replayed=False,
    )


def _activation_request_hash(
    *,
    policy_pack_id: str,
    policy_version: str,
    activated_by: str,
    source_content_hash: str,
    reason: dict[str, Any],
) -> str:
    return hash_canonical_payload(
        {
            "operation": "POLICY_PACK_ACTIVATED",
            "policy_pack_id": policy_pack_id,
            "policy_version": policy_version,
            "activated_by": activated_by,
            "source_content_hash": source_content_hash,
            "reason": _idempotency_stable_catalog_reason(reason),
        }
    )


def _activation_response_from_event(
    *,
    definition: dict[str, Any],
    event: PolicyPackAuditEvent,
) -> PolicyPackActivationResponse:
    return PolicyPackActivationResponse(
        policy_pack=summary_from_definition(definition),
        activation_event=event,
        replayed=True,
    )


def _validated_activation_event(
    *,
    definition: dict[str, Any],
    events: dict[tuple[str, str], list[PolicyPackAuditEvent]],
    policy_pack_id: str,
    policy_version: str,
    activated_by: str,
    source_content_hash: str,
) -> PolicyPackAuditEvent:
    _validate_activation_definition(definition=definition, source_content_hash=source_content_hash)
    validation_event = latest_policy_pack_validation_event(
        events=events,
        policy_pack_id=policy_pack_id,
        policy_version=policy_version,
    )
    if validation_event is None:
        raise ProposalValidationError("POLICY_PACK_VALIDATION_REQUIRED_BEFORE_ACTIVATION")
    if definition["maker_checker_required"] and validation_event.actor_id == activated_by:
        raise ProposalValidationError("POLICY_PACK_MAKER_CHECKER_REQUIRES_DIFFERENT_ACTOR")
    return validation_event


def _validate_activation_definition(
    *,
    definition: dict[str, Any],
    source_content_hash: str,
) -> None:
    if source_content_hash != definition["content_hash"]:
        raise ProposalValidationError("POLICY_PACK_CONTENT_HASH_MISMATCH")
    if definition["activation_state"] == "ACTIVE":
        raise ProposalValidationError("POLICY_PACK_VERSION_ALREADY_ACTIVE_IMMUTABLE")
    diagnostics = validate_definition(definition)
    if diagnostics:
        raise ProposalValidationError(";".join(diagnostics))


def _activation_event_reason(
    *,
    definition: dict[str, Any],
    validation_event: PolicyPackAuditEvent,
    reason: dict[str, Any],
    previous_active_policy_version: str | None,
) -> dict[str, Any]:
    return {
        "activation_state": "ACTIVE",
        "previous_active_policy_version": previous_active_policy_version,
        "resulting_active_policy_version": definition["policy_version"],
        "superseded_policy_version": previous_active_policy_version,
        "supersession_contract": "ONE_ACTIVE_VERSION_PER_POLICY_PACK",
        "maker_checker_required": definition["maker_checker_required"],
        "validated_by": validation_event.actor_id,
        "validation_event_id": validation_event.event_id,
        "reason": deepcopy(reason),
        "reference_posture": REFERENCE_POSTURE,
    }


def _idempotency_stable_catalog_reason(reason: dict[str, Any]) -> dict[str, Any]:
    return idempotency_stable_reason(reason)
