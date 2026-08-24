from src.core.workspace.draft_models import WorkspaceDraftState
from src.core.workspace.input_models import (
    WorkspaceResolvedContext,
    WorkspaceStatelessInput,
)
from src.core.workspace.session_models import WorkspaceSession, WorkspaceSessionCreateRequest


def build_stateless_workspace_resolved_context(
    *,
    stateless_input: WorkspaceStatelessInput,
) -> WorkspaceResolvedContext:
    simulate_request = stateless_input.simulate_request
    return WorkspaceResolvedContext(
        portfolio_id=simulate_request.portfolio_snapshot.portfolio_id,
        as_of=(
            simulate_request.reference_model.as_of
            if simulate_request.reference_model is not None
            else None
        ),
        requested_as_of=(
            simulate_request.reference_model.as_of
            if simulate_request.reference_model is not None
            else None
        ),
        portfolio_snapshot_id=simulate_request.portfolio_snapshot.snapshot_id,
        market_data_snapshot_id=simulate_request.market_data_snapshot.snapshot_id,
    )


def build_workspace_session(
    *,
    request: WorkspaceSessionCreateRequest,
    workspace_id: str,
    created_at: str,
    draft_state: WorkspaceDraftState,
    resolved_context: WorkspaceResolvedContext,
) -> WorkspaceSession:
    return WorkspaceSession(
        workspace_id=workspace_id,
        workspace_name=request.workspace_name,
        lifecycle_state="ACTIVE",
        input_mode=request.input_mode,
        created_by=request.created_by,
        created_at=created_at,
        stateless_input=request.stateless_input,
        stateful_input=request.stateful_input,
        draft_state=draft_state,
        resolved_context=resolved_context,
        evaluation_summary=None,
        latest_proposal_result=None,
        latest_replay_evidence=None,
        saved_version_count=0,
        latest_saved_version=None,
        lifecycle_link=None,
        saved_versions=[],
    )
