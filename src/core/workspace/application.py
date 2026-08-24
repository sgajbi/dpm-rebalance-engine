from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import cast

from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposals.models import ProposalCreateMetadata, ProposalCreateResponse
from src.core.replay.models import AdvisoryReplayEvidenceResponse
from src.core.replay.service import build_workspace_saved_version_replay_response
from src.core.workspace.action_models import (
    WorkspaceDraftActionRequest,
    WorkspaceDraftActionResponse,
)
from src.core.workspace.compare import build_workspace_compare_response
from src.core.workspace.compare_models import (
    WorkspaceCompareRequest,
    WorkspaceCompareResponse,
)
from src.core.workspace.draft_actions import WorkspaceDraftActionError
from src.core.workspace.errors import WorkspaceNotFoundError, WorkspaceSavedVersionNotFoundError
from src.core.workspace.evaluator import CoreWorkspaceProposalEvaluator
from src.core.workspace.handoff import (
    build_proposal_create_request,
    build_proposal_version_request,
    build_workspace_handoff_context_resolution,
    complete_workspace_lifecycle_handoff,
    require_handoff_simulate_request,
)
from src.core.workspace.handoff_models import (
    WorkspaceLifecycleHandoffRequest,
    WorkspaceLifecycleHandoffResponse,
)
from src.core.workspace.identifiers import new_workspace_id, new_workspace_version_id
from src.core.workspace.ports import (
    WorkspaceProposalEvaluator,
    WorkspaceProposalLifecyclePort,
    WorkspaceSessionRepository,
    WorkspaceSourceContextResolver,
)
from src.core.workspace.replay import (
    build_workspace_handoff_replay_lineage,
)
from src.core.workspace.save_models import (
    WorkspaceResumeRequest,
    WorkspaceSavedVersionListResponse,
    WorkspaceSaveRequest,
    WorkspaceSaveResponse,
)
from src.core.workspace.session_models import (
    WorkspaceSession,
    WorkspaceSessionCreateRequest,
    WorkspaceSessionCreateResponse,
)
from src.core.workspace.sessions import build_workspace_session
from src.core.workspace.version_models import WorkspaceSavedVersion
from src.core.workspace.versions import (
    WorkspaceSavedVersionLookupError,
    apply_saved_workspace_version,
    build_saved_version_list_response,
    build_saved_workspace_version,
    find_saved_version,
    refresh_saved_version_metadata,
)

WorkspaceClock = Callable[[], datetime]
WorkspaceIdFactory = Callable[[], str]


class WorkspaceApplicationService:
    def __init__(
        self,
        *,
        session_repository: WorkspaceSessionRepository,
        source_context_resolver: WorkspaceSourceContextResolver,
        proposal_evaluator: WorkspaceProposalEvaluator | None = None,
        clock: WorkspaceClock | None = None,
        workspace_id_factory: WorkspaceIdFactory = new_workspace_id,
        workspace_version_id_factory: WorkspaceIdFactory = new_workspace_version_id,
    ) -> None:
        self._session_repository = session_repository
        self._source_context_resolver = source_context_resolver
        self._proposal_evaluator = proposal_evaluator or CoreWorkspaceProposalEvaluator()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._workspace_id_factory = workspace_id_factory
        self._workspace_version_id_factory = workspace_version_id_factory

    def get_session(self, workspace_id: str) -> WorkspaceSession:
        return self._session_repository.get(workspace_id)

    def save_session(self, session: WorkspaceSession) -> None:
        self._session_repository.save(session)

    def reset_sessions_for_tests(self) -> None:
        self._session_repository.reset()

    def build_simulate_request_for_workspace(
        self,
        session: WorkspaceSession,
    ) -> ProposalSimulateRequest:
        return self._source_context_resolver.build_simulate_request(session)

    def create_session(
        self,
        request: WorkspaceSessionCreateRequest,
    ) -> WorkspaceSessionCreateResponse:
        resolved_context, draft_state = self._source_context_resolver.build_initial_context(
            request=request,
        )
        workspace = build_workspace_session(
            request=request,
            workspace_id=self._workspace_id_factory(),
            created_at=self._utc_now_iso(),
            draft_state=draft_state,
            resolved_context=resolved_context,
        )
        self._session_repository.save(workspace)
        return WorkspaceSessionCreateResponse(workspace=workspace)

    def reevaluate_session(self, workspace_id: str) -> WorkspaceSession:
        session = self.get_session(workspace_id)
        simulate_request = self.build_simulate_request_for_workspace(session)
        outcome = self._proposal_evaluator.evaluate(
            session=session,
            simulate_request=simulate_request,
        )
        session.latest_proposal_result = outcome.proposal_result
        session.evaluation_summary = outcome.evaluation_summary
        session.latest_replay_evidence = outcome.replay_evidence
        self._session_repository.save(session)
        return session

    def apply_draft_action(
        self,
        workspace_id: str,
        request: WorkspaceDraftActionRequest,
    ) -> WorkspaceDraftActionResponse:
        from src.core.workspace.draft_actions import apply_workspace_draft_action_to_state

        session = self.get_session(workspace_id)
        try:
            apply_workspace_draft_action_to_state(draft_state=session.draft_state, request=request)
        except WorkspaceDraftActionError as exc:
            raise WorkspaceNotFoundError(str(exc)) from exc
        self._session_repository.save(session)
        return WorkspaceDraftActionResponse(workspace=self.reevaluate_session(workspace_id))

    def save_version(
        self,
        workspace_id: str,
        request: WorkspaceSaveRequest,
    ) -> WorkspaceSaveResponse:
        session = self.get_session(workspace_id)
        saved_version = build_saved_workspace_version(
            session=session,
            request=request,
            workspace_version_id=self._workspace_version_id_factory(),
            saved_at=self._utc_now_iso(),
        )
        session.saved_versions.append(saved_version)
        refresh_saved_version_metadata(session)
        self._session_repository.save(session)
        return WorkspaceSaveResponse(workspace=session, saved_version=saved_version)

    def list_saved_versions(self, workspace_id: str) -> WorkspaceSavedVersionListResponse:
        return build_saved_version_list_response(self.get_session(workspace_id))

    def get_saved_version_replay(
        self,
        workspace_id: str,
        workspace_version_id: str,
    ) -> AdvisoryReplayEvidenceResponse:
        session = self.get_session(workspace_id)
        saved_version = self._find_saved_version(session, workspace_version_id)
        return build_workspace_saved_version_replay_response(
            session=session,
            saved_version=saved_version,
        )

    def resume_version(
        self,
        workspace_id: str,
        request: WorkspaceResumeRequest,
    ) -> WorkspaceSession:
        session = self.get_session(workspace_id)
        saved_version = self._find_saved_version(session, request.workspace_version_id)
        apply_saved_workspace_version(session=session, saved_version=saved_version)
        self._session_repository.save(session)
        return session

    def compare_to_saved_version(
        self,
        workspace_id: str,
        request: WorkspaceCompareRequest,
    ) -> WorkspaceCompareResponse:
        session = self.get_session(workspace_id)
        saved_version = self._find_saved_version(session, request.workspace_version_id)
        return build_workspace_compare_response(session=session, baseline_version=saved_version)

    def handoff_to_proposal_lifecycle(
        self,
        *,
        workspace_id: str,
        request: WorkspaceLifecycleHandoffRequest,
        proposal_lifecycle: WorkspaceProposalLifecyclePort,
        idempotency_key: str | None,
        correlation_id: str | None,
    ) -> WorkspaceLifecycleHandoffResponse:
        from src.core.workspace.handoff_errors import run_workspace_handoff_operation
        from src.core.workspace.handoff_idempotency import (
            normalize_workspace_handoff_idempotency_key,
        )

        session = self.get_session(workspace_id)

        def _execute() -> tuple[ProposalCreateResponse, dict[str, str | int | None], str]:
            if session.lifecycle_link is None:
                normalized_idempotency_key = normalize_workspace_handoff_idempotency_key(
                    idempotency_key
                )
                create_request = build_proposal_create_request(
                    session,
                    request,
                    self.build_simulate_request_for_workspace(session),
                )
                replay_lineage = build_workspace_handoff_replay_lineage(
                    session,
                    request,
                    "CREATED_PROPOSAL",
                    proposal_id="",
                    proposal_version_no=1,
                )
                proposal_response = proposal_lifecycle.create_proposal(
                    payload=create_request,
                    idempotency_key=normalized_idempotency_key,
                    correlation_id=correlation_id,
                    lifecycle_origin="WORKSPACE_HANDOFF",
                    source_workspace_id=workspace_id,
                    replay_lineage=replay_lineage,
                    context_resolution_override=build_workspace_handoff_context_resolution(
                        session,
                        require_handoff_simulate_request(create_request.simulate_request),
                        create_request.metadata,
                    ),
                )
                return proposal_response, replay_lineage, "CREATED_PROPOSAL"

            version_request = build_proposal_version_request(
                session,
                request,
                self.build_simulate_request_for_workspace(session),
            )
            replay_lineage = build_workspace_handoff_replay_lineage(
                session,
                request,
                "CREATED_PROPOSAL_VERSION",
                proposal_id=session.lifecycle_link.proposal_id,
                proposal_version_no=session.lifecycle_link.current_version_no + 1,
            )
            proposal_response = proposal_lifecycle.create_version(
                proposal_id=session.lifecycle_link.proposal_id,
                payload=version_request,
                correlation_id=correlation_id,
                replay_lineage=replay_lineage,
                context_resolution_override=build_workspace_handoff_context_resolution(
                    session,
                    require_handoff_simulate_request(version_request.simulate_request),
                    ProposalCreateMetadata(),
                ),
            )
            return proposal_response, replay_lineage, "CREATED_PROPOSAL_VERSION"

        proposal_response, replay_lineage, handoff_action = run_workspace_handoff_operation(
            _execute
        )
        response = complete_workspace_lifecycle_handoff(
            session=session,
            request=request,
            proposal_response=proposal_response,
            replay_lineage=replay_lineage,
            handoff_action=handoff_action,
            completed_at=self._utc_now_iso(),
        )
        self._session_repository.save(session)
        return cast(WorkspaceLifecycleHandoffResponse, response)

    def _find_saved_version(
        self,
        session: WorkspaceSession,
        workspace_version_id: str,
    ) -> WorkspaceSavedVersion:
        try:
            return find_saved_version(session, workspace_version_id)
        except WorkspaceSavedVersionLookupError as exc:
            raise WorkspaceSavedVersionNotFoundError("WORKSPACE_SAVED_VERSION_NOT_FOUND") from exc

    def _utc_now_iso(self) -> str:
        return self._clock().isoformat()
