from dataclasses import dataclass
from typing import Any, cast

from src.core.advisory.policy_context import ProposalPolicySelectors
from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposals.context_evidence import build_context_resolution_evidence
from src.core.proposals.context_hashing import build_simulation_request_hash
from src.core.proposals.context_resolution import ResolvedSimulationContext
from src.core.workspace.context_resolution import build_workspace_proposal_context
from src.core.workspace.session_models import WorkspaceSession


class WorkspaceReevaluationContextError(ValueError):
    pass


@dataclass(frozen=True)
class WorkspaceEvaluationContext:
    resolved_request: ResolvedSimulationContext
    context_resolution: dict[str, Any]
    request_hash: str


def build_workspace_evaluation_context(
    *,
    session: WorkspaceSession,
    simulate_request: ProposalSimulateRequest,
) -> WorkspaceEvaluationContext:
    if session.resolved_context is None:
        raise WorkspaceReevaluationContextError("WORKSPACE_RESOLVED_CONTEXT_MISSING")
    proposal_resolved_context = build_workspace_proposal_context(
        resolved_context=session.resolved_context,
        stateful_input=session.stateful_input,
    )
    resolved_request = ResolvedSimulationContext(
        input_mode=session.input_mode,
        resolution_source="LOTUS_CORE" if session.input_mode == "stateful" else "DIRECT_REQUEST",
        simulate_request=simulate_request,
        resolved_context=proposal_resolved_context,
        policy_selectors=ProposalPolicySelectors(
            household_id=(
                session.stateful_input.household_id if session.stateful_input is not None else None
            ),
            mandate_id=(
                session.stateful_input.mandate_id if session.stateful_input is not None else None
            ),
            benchmark_id=(
                session.stateful_input.benchmark_id if session.stateful_input is not None else None
            ),
        ),
        used_legacy_contract=False,
    )
    context_resolution = cast(
        dict[str, Any],
        build_context_resolution_evidence(resolved_request),
    )
    request_hash = build_simulation_request_hash(resolved=resolved_request)
    return WorkspaceEvaluationContext(
        resolved_request=resolved_request,
        context_resolution=context_resolution,
        request_hash=request_hash,
    )
