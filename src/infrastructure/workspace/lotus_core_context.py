from __future__ import annotations

from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.workspace.draft_models import WorkspaceDraftState
from src.core.workspace.draft_state import (
    apply_workspace_draft_state,
    build_draft_state_from_simulate_request,
)
from src.core.workspace.errors import WorkspaceEvaluationUnavailableError
from src.core.workspace.input_models import WorkspaceResolvedContext
from src.core.workspace.session_models import WorkspaceSession, WorkspaceSessionCreateRequest
from src.core.workspace.sessions import build_stateless_workspace_resolved_context
from src.integrations.lotus_core import (
    LotusCoreContextResolutionError,
    resolve_lotus_core_advisory_context,
)
from src.integrations.lotus_core.stateful_context import (
    enrich_stateful_simulate_request_for_trade_drafts,
)


class LotusCoreWorkspaceSourceContextResolver:
    def build_simulate_request(self, session: WorkspaceSession) -> ProposalSimulateRequest:
        if session.input_mode == "stateful":
            if session.stateful_input is None:
                raise WorkspaceEvaluationUnavailableError("WORKSPACE_STATEFUL_INPUT_MISSING")
            try:
                resolved_stateful_context = resolve_lotus_core_advisory_context(
                    session.stateful_input
                )
            except LotusCoreContextResolutionError as exc:
                raise WorkspaceEvaluationUnavailableError(
                    "WORKSPACE_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"
                ) from exc
            session.resolved_context = resolved_stateful_context.resolved_context
            return enrich_stateful_simulate_request_for_trade_drafts(
                simulate_request=apply_workspace_draft_state(
                    base_request=resolved_stateful_context.simulate_request,
                    draft_state=session.draft_state,
                ),
                as_of=_require_stateful_context_as_of(session.resolved_context),
            )

        if session.stateless_input is None:
            raise WorkspaceEvaluationUnavailableError("WORKSPACE_STATELESS_INPUT_MISSING")

        return apply_workspace_draft_state(
            base_request=session.stateless_input.simulate_request,
            draft_state=session.draft_state,
        )

    def build_initial_context(
        self,
        *,
        request: WorkspaceSessionCreateRequest,
    ) -> tuple[WorkspaceResolvedContext, WorkspaceDraftState]:
        if request.input_mode == "stateless":
            if request.stateless_input is None:
                raise ValueError("stateless workspace creation requires stateless_input")
            return (
                build_stateless_workspace_resolved_context(
                    stateless_input=request.stateless_input,
                ),
                build_draft_state_from_simulate_request(request.stateless_input.simulate_request),
            )

        if request.stateful_input is None:
            raise ValueError("stateful workspace creation requires stateful_input")
        try:
            resolved_stateful_context = resolve_lotus_core_advisory_context(request.stateful_input)
        except LotusCoreContextResolutionError:
            return (
                WorkspaceResolvedContext(
                    portfolio_id=request.stateful_input.portfolio_id,
                    as_of=request.stateful_input.as_of,
                ),
                WorkspaceDraftState(),
            )
        return (
            resolved_stateful_context.resolved_context,
            build_draft_state_from_simulate_request(resolved_stateful_context.simulate_request),
        )


def _require_stateful_context_as_of(context: WorkspaceResolvedContext) -> str:
    if context.as_of is None:
        raise WorkspaceEvaluationUnavailableError("WORKSPACE_STATEFUL_CONTEXT_AS_OF_MISSING")
    return context.as_of
