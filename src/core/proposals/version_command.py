from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.core.proposals.command_read_model import load_proposal_command_read_model
from src.core.proposals.command_validation import validate_proposal_simulation_flag
from src.core.proposals.context_evidence import build_context_resolution_evidence
from src.core.proposals.context_hashing import build_version_request_hash
from src.core.proposals.context_resolution import (
    ProposalContextResolutionError,
    apply_context_resolution_override,
    resolve_version_request,
)
from src.core.proposals.create_persistence import persist_created_proposal_version
from src.core.proposals.error_details import (
    PROPOSAL_CONTEXT_RESOLUTION_FAILED_DETAIL,
    safe_proposal_error_detail,
)
from src.core.proposals.exceptions import (
    ProposalNotFoundError,
    ProposalStateConflictError,
    ProposalValidationError,
)
from src.core.proposals.identifiers import new_proposal_version_id, new_workflow_event_id
from src.core.proposals.materialization import build_proposal_version_materialization
from src.core.proposals.models import ProposalCreateResponse, ProposalVersionRequest
from src.core.proposals.projections import to_create_response
from src.core.proposals.repository import ProposalRepository
from src.core.proposals.simulation_execution import run_advisory_proposal_simulation
from src.core.proposals.versions import (
    ProposalVersionConflictError,
    ProposalVersionPortfolioContextError,
    ProposalVersionTerminalStateError,
    build_new_version_created_event_and_apply_state,
    build_proposal_version_record,
    validate_create_version_portfolio_context,
    validate_create_version_state,
)
from src.core.proposals.workflow_rules import TERMINAL_STATES


def create_proposal_version(
    *,
    repository: ProposalRepository,
    proposal_id: str,
    payload: ProposalVersionRequest,
    correlation_id: str | None,
    replay_lineage: dict[str, Any] | None,
    context_resolution_override: dict[str, Any] | None,
    store_evidence_bundle: bool,
    require_proposal_simulation_flag: bool,
    allow_portfolio_id_change_on_new_version: bool,
    utc_now: Callable[[], datetime],
) -> ProposalCreateResponse:
    now = utc_now()
    command_read_model = load_proposal_command_read_model(
        repository=repository,
        proposal_id=proposal_id,
    )
    if command_read_model.proposal is None:
        raise ProposalNotFoundError("PROPOSAL_NOT_FOUND")
    proposal = command_read_model.proposal
    try:
        validate_create_version_state(
            proposal=proposal,
            expected_current_version_no=payload.expected_current_version_no,
            terminal_states=TERMINAL_STATES,
        )
    except ProposalVersionTerminalStateError as exc:
        raise ProposalValidationError(str(exc)) from exc
    except ProposalVersionConflictError as exc:
        raise ProposalStateConflictError(str(exc)) from exc

    try:
        resolved_request = resolve_version_request(payload)
        resolved_request = apply_context_resolution_override(
            resolved_request,
            context_resolution_override,
        )
    except ProposalContextResolutionError as exc:
        raise ProposalValidationError(
            safe_proposal_error_detail(
                str(exc),
                fallback=PROPOSAL_CONTEXT_RESOLUTION_FAILED_DETAIL,
            )
        ) from exc
    validate_proposal_simulation_flag(
        request=resolved_request.simulate_request,
        require_simulation_flag=require_proposal_simulation_flag,
    )
    context_resolution = (
        context_resolution_override
        if context_resolution_override is not None
        else build_context_resolution_evidence(resolved_request)
    )
    request_hash = build_version_request_hash(payload=payload, resolved=resolved_request)
    try:
        validate_create_version_portfolio_context(
            proposal_portfolio_id=proposal.portfolio_id,
            request_portfolio_id=(
                resolved_request.simulate_request.portfolio_snapshot.portfolio_id
            ),
            allow_portfolio_id_change=allow_portfolio_id_change_on_new_version,
        )
    except ProposalVersionPortfolioContextError as exc:
        raise ProposalValidationError(str(exc)) from exc

    proposal_result = run_advisory_proposal_simulation(
        request=resolved_request.simulate_request,
        resolved_as_of=resolved_request.resolved_context.as_of,
        input_mode=resolved_request.input_mode,
        requested_as_of_date=resolved_request.resolved_context.requested_as_of,
        requested_reporting_currency=resolved_request.resolved_context.requested_reporting_currency,
        request_hash=request_hash,
        idempotency_key=None,
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

    next_version_no = proposal.current_version_no + 1
    version = build_proposal_version_record(
        proposal_version_id=new_proposal_version_id(),
        proposal_id=proposal.proposal_id,
        version_no=next_version_no,
        request_hash=request_hash,
        proposal_result=proposal_result,
        artifact=materialization.artifact.model_dump(mode="json"),
        evidence_bundle=materialization.evidence_bundle,
        created_at=now,
        store_evidence_bundle=store_evidence_bundle,
    )
    event = build_new_version_created_event_and_apply_state(
        event_id=new_workflow_event_id(),
        proposal=proposal,
        actor_id=payload.created_by,
        occurred_at=now,
        related_version_no=next_version_no,
        correlation_id=correlation_id,
    )
    persist_created_proposal_version(
        repository=repository,
        proposal=proposal,
        version=version,
        event=event,
    )
    return to_create_response(proposal=proposal, version=version, latest_event=event)


__all__ = ["create_proposal_version"]
