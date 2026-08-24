from typing import Any, cast

from src.core.advisory.policy_context import ProposalPolicySelectors
from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposals.context_evidence import build_context_resolution_evidence
from src.core.proposals.context_resolution import ResolvedProposalContext
from src.core.proposals.models import (
    ProposalCreateMetadata,
    ProposalCreateRequest,
    ProposalCreateResponse,
    ProposalVersionRequest,
)
from src.core.workspace.context_resolution import build_workspace_proposal_context
from src.core.workspace.handoff_models import (
    WorkspaceLifecycleHandoffRequest,
    WorkspaceLifecycleHandoffResponse,
)
from src.core.workspace.replay import apply_workspace_handoff_replay_lineage
from src.core.workspace.session_models import WorkspaceSession
from src.core.workspace.version_models import WorkspaceLifecycleLink


class WorkspaceHandoffError(ValueError):
    pass


def build_handoff_metadata(
    request: WorkspaceLifecycleHandoffRequest,
    session: WorkspaceSession,
) -> ProposalCreateMetadata:
    mandate_id = request.metadata.mandate_id
    if mandate_id is None and session.stateful_input is not None:
        mandate_id = session.stateful_input.mandate_id
    return ProposalCreateMetadata(
        title=request.metadata.title or session.workspace_name,
        advisor_notes=request.metadata.advisor_notes,
        jurisdiction=request.metadata.jurisdiction,
        mandate_id=mandate_id,
    )


def build_workspace_handoff_context_resolution(
    session: WorkspaceSession,
    simulate_request: ProposalSimulateRequest,
    metadata: ProposalCreateMetadata,
) -> dict[str, Any]:
    if session.resolved_context is None:
        raise WorkspaceHandoffError("WORKSPACE_RESOLVED_CONTEXT_MISSING")
    resolved_context = build_workspace_proposal_context(
        resolved_context=session.resolved_context,
        stateful_input=session.stateful_input,
    )
    resolved_request = ResolvedProposalContext(
        input_mode=session.input_mode,
        resolution_source="LOTUS_CORE" if session.input_mode == "stateful" else "DIRECT_REQUEST",
        simulate_request=simulate_request,
        resolved_context=resolved_context,
        metadata=metadata,
        policy_selectors=ProposalPolicySelectors(
            household_id=(
                session.stateful_input.household_id if session.stateful_input is not None else None
            ),
            mandate_id=metadata.mandate_id,
            jurisdiction=metadata.jurisdiction,
            benchmark_id=(
                session.stateful_input.benchmark_id if session.stateful_input is not None else None
            ),
        ),
        used_legacy_contract=False,
    )
    return cast(dict[str, Any], build_context_resolution_evidence(resolved_request))


def require_handoff_simulate_request(
    simulate_request: ProposalSimulateRequest | None,
) -> ProposalSimulateRequest:
    if simulate_request is None:
        raise WorkspaceHandoffError("WORKSPACE_HANDOFF_SIMULATE_REQUEST_MISSING")
    return simulate_request


def build_proposal_create_request(
    session: WorkspaceSession,
    request: WorkspaceLifecycleHandoffRequest,
    simulate_request: ProposalSimulateRequest,
) -> ProposalCreateRequest:
    return ProposalCreateRequest(
        created_by=request.handoff_by,
        simulate_request=simulate_request,
        metadata=build_handoff_metadata(request, session),
    )


def build_proposal_version_request(
    session: WorkspaceSession,
    request: WorkspaceLifecycleHandoffRequest,
    simulate_request: ProposalSimulateRequest,
) -> ProposalVersionRequest:
    expected_current_version_no = (
        session.lifecycle_link.current_version_no if session.lifecycle_link is not None else None
    )
    return ProposalVersionRequest(
        created_by=request.handoff_by,
        expected_current_version_no=expected_current_version_no,
        simulate_request=simulate_request,
    )


def complete_workspace_lifecycle_handoff(
    *,
    session: WorkspaceSession,
    request: WorkspaceLifecycleHandoffRequest,
    proposal_response: ProposalCreateResponse,
    replay_lineage: dict[str, str | int | None],
    handoff_action: str,
    completed_at: str,
) -> WorkspaceLifecycleHandoffResponse:
    replay_lineage["proposal_id"] = proposal_response.proposal.proposal_id
    replay_lineage["proposal_version_no"] = proposal_response.version.version_no
    apply_workspace_handoff_replay_lineage(session, replay_lineage)
    session.lifecycle_link = WorkspaceLifecycleLink(
        proposal_id=proposal_response.proposal.proposal_id,
        current_version_no=proposal_response.version.version_no,
        last_handoff_at=completed_at,
        last_handoff_by=request.handoff_by,
    )
    return WorkspaceLifecycleHandoffResponse(
        workspace=session,
        handoff_action=handoff_action,
        proposal=proposal_response,
    )
