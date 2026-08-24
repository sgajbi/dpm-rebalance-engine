from typing import cast

from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.workspace.draft_models import WorkspaceDraftState
from src.core.workspace.input_models import WorkspaceResolvedContext
from src.core.workspace.ports import WorkspaceSourceContextResolver
from src.core.workspace.session_models import WorkspaceSession, WorkspaceSessionCreateRequest
from src.runtime.workspace_application import get_workspace_source_context_resolver

_SOURCE_CONTEXT_RESOLVER: WorkspaceSourceContextResolver = get_workspace_source_context_resolver()


def build_workspace_simulate_request(session: WorkspaceSession) -> ProposalSimulateRequest:
    return _SOURCE_CONTEXT_RESOLVER.build_simulate_request(session)


def build_initial_workspace_context(
    *,
    request: WorkspaceSessionCreateRequest,
) -> tuple[WorkspaceResolvedContext, WorkspaceDraftState]:
    return cast(
        tuple[WorkspaceResolvedContext, WorkspaceDraftState],
        _SOURCE_CONTEXT_RESOLVER.build_initial_context(
            request=request,
        ),
    )
