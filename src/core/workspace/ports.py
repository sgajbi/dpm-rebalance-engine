from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposal_result_models import ProposalResult
from src.core.proposals.models import (
    ProposalCreateRequest,
    ProposalCreateResponse,
    ProposalVersionRequest,
)
from src.core.workspace.draft_models import WorkspaceDraftState, WorkspaceEvaluationSummary
from src.core.workspace.input_models import WorkspaceResolvedContext
from src.core.workspace.session_models import WorkspaceSession, WorkspaceSessionCreateRequest
from src.core.workspace.version_models import WorkspaceReplayEvidence


@dataclass(frozen=True)
class WorkspaceEvaluationOutcome:
    proposal_result: ProposalResult
    evaluation_summary: WorkspaceEvaluationSummary
    replay_evidence: WorkspaceReplayEvidence


class WorkspaceSessionRepository(Protocol):
    def save(self, session: WorkspaceSession) -> None: ...

    def get(self, workspace_id: str) -> WorkspaceSession: ...

    def reset(self) -> None: ...

    def resize(self, max_size: int) -> None: ...


class WorkspaceSourceContextResolver(Protocol):
    def build_simulate_request(self, session: WorkspaceSession) -> ProposalSimulateRequest: ...

    def build_initial_context(
        self,
        *,
        request: WorkspaceSessionCreateRequest,
    ) -> tuple[WorkspaceResolvedContext, WorkspaceDraftState]: ...


class WorkspaceProposalEvaluator(Protocol):
    def evaluate(
        self,
        *,
        session: WorkspaceSession,
        simulate_request: ProposalSimulateRequest,
    ) -> WorkspaceEvaluationOutcome: ...


class WorkspaceProposalLifecyclePort(Protocol):
    def create_proposal(
        self,
        *,
        payload: ProposalCreateRequest,
        idempotency_key: str,
        correlation_id: str | None,
        lifecycle_origin: Literal["WORKSPACE_HANDOFF"],
        source_workspace_id: str,
        replay_lineage: dict[str, Any] | None,
        context_resolution_override: dict[str, Any] | None,
    ) -> ProposalCreateResponse: ...

    def create_version(
        self,
        *,
        proposal_id: str,
        payload: ProposalVersionRequest,
        correlation_id: str | None,
        replay_lineage: dict[str, Any] | None,
        context_resolution_override: dict[str, Any] | None,
    ) -> ProposalCreateResponse: ...
