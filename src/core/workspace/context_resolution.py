from typing import cast

from src.core.proposals.models import ProposalResolvedContext
from src.core.workspace.input_models import WorkspaceResolvedContext, WorkspaceStatefulInput


def build_workspace_proposal_context(
    *,
    resolved_context: WorkspaceResolvedContext,
    stateful_input: WorkspaceStatefulInput | None,
) -> ProposalResolvedContext:
    """Project workspace source context into the proposal lifecycle contract."""

    return cast(
        ProposalResolvedContext,
        ProposalResolvedContext.model_validate(resolved_context.model_dump(mode="json")).model_copy(
            update={
                "requested_as_of": stateful_input.as_of if stateful_input is not None else None,
                "requested_reporting_currency": (
                    stateful_input.reporting_currency if stateful_input is not None else None
                ),
            }
        ),
    )
