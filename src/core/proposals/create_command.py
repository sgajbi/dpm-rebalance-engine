from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.core.proposals.command_validation import validate_proposal_simulation_flag
from src.core.proposals.context_evidence import build_context_resolution_evidence
from src.core.proposals.context_hashing import (
    build_create_command_idempotency_hash,
    build_create_request_hash,
)
from src.core.proposals.context_resolution import (
    ProposalContextResolutionError,
    ResolvedProposalContext,
    resolve_create_request,
)
from src.core.proposals.create_persistence import persist_created_proposal
from src.core.proposals.error_details import (
    PROPOSAL_CONTEXT_RESOLUTION_FAILED_DETAIL,
    safe_proposal_error_detail,
)
from src.core.proposals.exceptions import (
    ProposalIdempotencyConflictError,
    ProposalValidationError,
)
from src.core.proposals.idempotency_read_model import load_proposal_idempotency_read_model
from src.core.proposals.idempotency_validation import require_proposal_idempotency_key
from src.core.proposals.identifiers import (
    new_proposal_id,
    new_proposal_version_id,
    new_workflow_event_id,
)
from src.core.proposals.lifecycle import (
    ProposalLifecycleOriginError,
    validate_lifecycle_origin,
)
from src.core.proposals.materialization import build_proposal_version_materialization
from src.core.proposals.models import (
    ProposalCreateRequest,
    ProposalCreateResponse,
    ProposalLifecycleOrigin,
)
from src.core.proposals.projections import to_create_response
from src.core.proposals.records import build_proposal_create_command_state
from src.core.proposals.replay_views import build_create_response_from_replay_referents
from src.core.proposals.repository import ProposalRepository
from src.core.proposals.simulation_execution import run_advisory_proposal_simulation
from src.core.proposals.versions import build_proposal_version_record


def create_proposal_command(
    *,
    repository: ProposalRepository,
    payload: ProposalCreateRequest,
    idempotency_key: str,
    correlation_id: str | None,
    lifecycle_origin: ProposalLifecycleOrigin,
    source_workspace_id: str | None,
    replay_lineage: dict[str, Any] | None,
    context_resolution_override: dict[str, Any] | None,
    store_evidence_bundle: bool,
    require_proposal_simulation_flag: bool,
    utc_now: Callable[[], datetime],
) -> ProposalCreateResponse:
    idempotency_key = require_proposal_idempotency_key(idempotency_key)
    try:
        validate_lifecycle_origin(
            lifecycle_origin=lifecycle_origin,
            source_workspace_id=source_workspace_id,
        )
    except ProposalLifecycleOriginError as exc:
        raise ProposalValidationError(str(exc)) from exc

    now = utc_now()
    idempotency_request_hash = build_create_command_idempotency_hash(payload=payload)
    idempotency_read_model = load_proposal_idempotency_read_model(
        repository=repository,
        idempotency_key=idempotency_key,
    )
    existing = idempotency_read_model.record
    if existing is not None:
        if existing.request_hash == idempotency_request_hash or _is_matching_legacy_replay(
            repository=repository,
            payload=payload,
            stored_request_hash=existing.request_hash,
            proposal_id=existing.proposal_id,
            proposal_version_no=existing.proposal_version_no,
        ):
            return build_create_response_from_replay_referents(
                repository=repository,
                proposal_id=existing.proposal_id,
                version_no=existing.proposal_version_no,
            )
        raise ProposalIdempotencyConflictError("IDEMPOTENCY_KEY_CONFLICT: request hash mismatch")

    try:
        resolved_request = resolve_create_request(payload)
    except ProposalContextResolutionError as exc:
        raise ProposalValidationError(
            safe_proposal_error_detail(
                str(exc),
                fallback=PROPOSAL_CONTEXT_RESOLUTION_FAILED_DETAIL,
            )
        ) from exc
    request_hash = build_create_request_hash(payload=payload, resolved=resolved_request)

    validate_proposal_simulation_flag(
        request=resolved_request.simulate_request,
        require_simulation_flag=require_proposal_simulation_flag,
    )
    context_resolution = build_context_resolution_evidence(resolved_request)
    proposal_result = run_advisory_proposal_simulation(
        request=resolved_request.simulate_request,
        resolved_as_of=resolved_request.resolved_context.as_of,
        input_mode=resolved_request.input_mode,
        requested_as_of_date=resolved_request.resolved_context.requested_as_of,
        requested_reporting_currency=resolved_request.resolved_context.requested_reporting_currency,
        request_hash=request_hash,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        policy_context=context_resolution["advisory_policy_context"],
    )
    materialization = build_proposal_version_materialization(
        request=resolved_request.simulate_request,
        proposal_result=proposal_result,
        created_at=now,
        context_resolution=context_resolution,
        context_resolution_override=context_resolution_override,
        replay_lineage=replay_lineage,
    )

    proposal_id = new_proposal_id()
    version_no = 1
    command_state = build_proposal_create_command_state(
        proposal_id=proposal_id,
        portfolio_id=resolved_request.simulate_request.portfolio_snapshot.portfolio_id,
        mandate_id=resolved_request.metadata.mandate_id,
        jurisdiction=resolved_request.metadata.jurisdiction,
        created_by=payload.created_by,
        created_at=now,
        version_no=version_no,
        title=resolved_request.metadata.title,
        advisor_notes=resolved_request.metadata.advisor_notes,
        lifecycle_origin=lifecycle_origin,
        source_workspace_id=source_workspace_id,
        event_id=new_workflow_event_id(),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        request_hash=idempotency_request_hash,
    )
    proposal = command_state.proposal
    version = build_proposal_version_record(
        proposal_version_id=new_proposal_version_id(),
        proposal_id=proposal_id,
        version_no=version_no,
        request_hash=request_hash,
        proposal_result=proposal_result,
        artifact=materialization.artifact.model_dump(mode="json"),
        evidence_bundle=materialization.evidence_bundle,
        created_at=now,
        store_evidence_bundle=store_evidence_bundle,
    )
    created_event = command_state.created_event

    persist_created_proposal(
        repository=repository,
        command_state=command_state,
        version=version,
    )

    return to_create_response(proposal=proposal, version=version, latest_event=created_event)


def _is_matching_legacy_replay(
    *,
    repository: ProposalRepository,
    payload: ProposalCreateRequest,
    stored_request_hash: str,
    proposal_id: str,
    proposal_version_no: int,
) -> bool:
    proposal = repository.get_proposal(proposal_id=proposal_id)
    version = repository.get_version(proposal_id=proposal_id, version_no=proposal_version_no)
    if proposal is None or version is None or stored_request_hash != version.request_hash:
        return False
    if payload.input_mode in (None, "stateless"):
        return _is_matching_direct_legacy_replay(
            proposal=proposal,
            version=version,
            payload=payload,
        )
    if payload.input_mode != "stateful":
        return False
    if payload.stateful_input is None:
        return False
    stateful_input = payload.stateful_input
    if not _legacy_proposal_fields_match(
        proposal=proposal,
        payload=payload,
        stateful_input=stateful_input,
    ):
        return False
    if not _legacy_context_matches(version=version, stateful_input=stateful_input):
        return False
    return _legacy_narrative_request_matches(
        artifact=version.artifact_json,
        expected=stateful_input.narrative_request,
        created_by=payload.created_by,
    )


def _is_matching_direct_legacy_replay(
    *,
    proposal: Any,
    version: Any,
    payload: ProposalCreateRequest,
) -> bool:
    try:
        resolved = resolve_create_request(payload)
    except ProposalContextResolutionError:
        return False
    if resolved.resolution_source != "DIRECT_REQUEST":
        return False
    if not _legacy_direct_proposal_fields_match(
        proposal=proposal,
        payload=payload,
        resolved=resolved,
    ):
        return False
    if not _legacy_direct_context_matches(version=version, resolved=resolved):
        return False
    if not _legacy_direct_inputs_match(version=version, resolved=resolved):
        return False
    return _legacy_narrative_request_matches(
        artifact=version.artifact_json,
        expected=resolved.simulate_request.narrative_request,
        created_by=payload.created_by,
    )


def _legacy_proposal_fields_match(
    *,
    proposal: Any,
    payload: ProposalCreateRequest,
    stateful_input: Any,
) -> bool:
    expected_mandate_id = payload.metadata.mandate_id or stateful_input.mandate_id
    expected_fields = {
        "created_by": payload.created_by,
        "portfolio_id": stateful_input.portfolio_id,
        "title": payload.metadata.title,
        "advisor_notes": payload.metadata.advisor_notes,
        "jurisdiction": payload.metadata.jurisdiction,
        "mandate_id": expected_mandate_id,
    }
    return all(
        expected is None or getattr(proposal, field_name) == expected
        for field_name, expected in expected_fields.items()
    )


def _legacy_direct_proposal_fields_match(
    *,
    proposal: Any,
    payload: ProposalCreateRequest,
    resolved: ResolvedProposalContext,
) -> bool:
    expected_fields = {
        "created_by": payload.created_by,
        "portfolio_id": resolved.simulate_request.portfolio_snapshot.portfolio_id,
        "title": resolved.metadata.title,
        "advisor_notes": resolved.metadata.advisor_notes,
        "jurisdiction": resolved.metadata.jurisdiction,
        "mandate_id": resolved.metadata.mandate_id,
    }
    return all(
        getattr(proposal, field_name) == expected
        for field_name, expected in expected_fields.items()
    )


def _legacy_context_matches(*, version: Any, stateful_input: Any) -> bool:
    context_resolution = version.evidence_bundle_json.get("context_resolution")
    if not isinstance(context_resolution, dict):
        return False
    resolved_context = context_resolution.get("resolved_context")
    if not isinstance(resolved_context, dict):
        return False
    return _legacy_optional_fields_match(
        actual=resolved_context,
        expected={
            "portfolio_id": stateful_input.portfolio_id,
            "as_of": stateful_input.as_of,
            "household_id": getattr(stateful_input, "household_id", None),
            "benchmark_id": getattr(stateful_input, "benchmark_id", None),
        },
    )


def _legacy_direct_context_matches(*, version: Any, resolved: ResolvedProposalContext) -> bool:
    context_resolution = version.evidence_bundle_json.get("context_resolution")
    if not isinstance(context_resolution, dict):
        return False
    expected_context = resolved.resolved_context.model_dump(mode="json")
    return (
        context_resolution.get("input_mode") == "stateless"
        and context_resolution.get("resolution_source") == "DIRECT_REQUEST"
        and context_resolution.get("resolved_context") == expected_context
    )


def _legacy_direct_inputs_match(*, version: Any, resolved: ResolvedProposalContext) -> bool:
    inputs = version.evidence_bundle_json.get("inputs")
    if not isinstance(inputs, dict):
        return False
    simulate_request = resolved.simulate_request
    expected_inputs = {
        "portfolio_snapshot": simulate_request.portfolio_snapshot.model_dump(mode="json"),
        "market_data_snapshot": simulate_request.market_data_snapshot.model_dump(mode="json"),
        "shelf_entries": [row.model_dump(mode="json") for row in simulate_request.shelf_entries],
        "options": simulate_request.options.model_dump(mode="json"),
        "proposed_cash_flows": [
            row.model_dump(mode="json") for row in simulate_request.proposed_cash_flows
        ],
        "proposed_trades": [
            row.model_dump(mode="json") for row in simulate_request.proposed_trades
        ],
        "reference_model": (
            simulate_request.reference_model.model_dump(mode="json")
            if simulate_request.reference_model is not None
            else None
        ),
    }
    return inputs == expected_inputs


def _legacy_narrative_request_matches(
    *,
    artifact: dict[str, Any],
    expected: object | None,
    created_by: str,
) -> bool:
    narrative = artifact.get("proposal_narrative")
    if expected is None:
        return narrative is None
    if not isinstance(narrative, dict):
        return False
    expected_payload = _legacy_expected_narrative_payload(expected)
    narrative_context = _legacy_narrative_context(narrative)
    if expected_payload is None or narrative_context is None:
        return False
    return (
        _legacy_optional_fields_match(
            actual=narrative,
            expected={
                "audience": expected_payload.get("audience"),
                "generation_mode": expected_payload.get("generation_mode"),
            },
        )
        and _legacy_narrative_context_matches(
            actual=narrative_context,
            expected=expected_payload,
        )
        and (
            list(_legacy_narrative_section_keys(narrative)) == expected_payload.get("sections")
            and expected_payload.get("requested_by") == created_by
        )
    )


def _legacy_narrative_context_matches(
    *,
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    return _legacy_optional_fields_match(
        actual=actual,
        expected={
            "jurisdiction": expected.get("jurisdiction"),
            "client_audience": expected.get("client_audience"),
        },
    ) and _legacy_product_types_match(
        actual=actual.get("product_types"),
        expected=expected.get("product_types"),
    )


def _legacy_product_types_match(*, actual: object, expected: object) -> bool:
    if expected is None:
        return True
    if isinstance(expected, list) and not expected:
        return True
    return actual == expected


def _legacy_expected_narrative_payload(expected: object) -> dict[str, Any] | None:
    expected_payload = expected.model_dump(mode="json") if hasattr(expected, "model_dump") else {}
    return expected_payload if isinstance(expected_payload, dict) else None


def _legacy_narrative_context(narrative: dict[str, Any]) -> dict[str, Any] | None:
    narrative_policy = narrative.get("narrative_policy")
    if not isinstance(narrative_policy, dict):
        return None
    narrative_context = narrative_policy.get("context")
    return narrative_context if isinstance(narrative_context, dict) else None


def _legacy_narrative_section_keys(narrative: dict[str, Any]) -> tuple[object, ...]:
    sections = narrative.get("sections", [])
    return tuple(section.get("section_key") for section in sections if isinstance(section, dict))


def _legacy_optional_fields_match(
    *,
    actual: dict[str, Any],
    expected: dict[str, object | None],
) -> bool:
    return all(actual.get(field_name) == value for field_name, value in expected.items())


__all__ = ["create_proposal_command"]
