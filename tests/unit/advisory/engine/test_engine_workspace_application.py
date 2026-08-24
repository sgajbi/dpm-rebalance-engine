from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.core.diagnostics_models import RuleResult
from src.core.portfolio_models import Money
from src.core.proposal_effect_models import Reconciliation
from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposal_result_models import ProposalResult
from src.core.proposals.models import ProposalCreateResponse
from src.core.simulation_state_models import SimulatedState
from src.core.workspace.application import WorkspaceApplicationService
from src.core.workspace.draft_models import (
    WorkspaceDraftState,
    WorkspaceEvaluationImpactSummary,
    WorkspaceEvaluationSummary,
)
from src.core.workspace.input_models import WorkspaceResolvedContext
from src.core.workspace.ports import WorkspaceEvaluationOutcome
from src.core.workspace.session_models import WorkspaceSession, WorkspaceSessionCreateRequest
from src.core.workspace.version_models import WorkspaceReplayEvidence


class _FakeWorkspaceSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, WorkspaceSession] = {}
        self.resize_calls: list[int] = []
        self.reset_called = False

    def save(self, session: WorkspaceSession) -> None:
        self.sessions[session.workspace_id] = session

    def get(self, workspace_id: str) -> WorkspaceSession:
        return self.sessions[workspace_id]

    def reset(self) -> None:
        self.reset_called = True
        self.sessions.clear()

    def resize(self, max_size: int) -> None:
        self.resize_calls.append(max_size)


class _SharedDurableWorkspaceStorage:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.saved_versions: dict[str, list[dict[str, Any]]] = {}


class _DurableFakeWorkspaceSessionRepository:
    def __init__(self, storage: _SharedDurableWorkspaceStorage) -> None:
        self._storage = storage

    def save(self, session: WorkspaceSession) -> None:
        self._storage.sessions[session.workspace_id] = session.model_dump(mode="json")
        self._storage.saved_versions[session.workspace_id] = [
            saved_version.model_dump(mode="json") for saved_version in session.saved_versions
        ]

    def get(self, workspace_id: str) -> WorkspaceSession:
        payload = dict(self._storage.sessions[workspace_id])
        payload["saved_versions"] = list(self._storage.saved_versions.get(workspace_id, []))
        return WorkspaceSession.model_validate(payload)

    def reset(self) -> None:
        self._storage.sessions.clear()
        self._storage.saved_versions.clear()

    def resize(self, max_size: int) -> None:
        _ = max_size


class _FakeWorkspaceSourceContextResolver:
    def __init__(self) -> None:
        self.initial_context_requests: list[WorkspaceSessionCreateRequest] = []
        self.simulate_request_sessions: list[str] = []

    def build_initial_context(
        self,
        *,
        request: WorkspaceSessionCreateRequest,
    ) -> tuple[WorkspaceResolvedContext, WorkspaceDraftState]:
        self.initial_context_requests.append(request)
        if request.stateful_input is not None:
            portfolio_id = request.stateful_input.portfolio_id
        elif request.stateless_input is not None:
            portfolio_id = request.stateless_input.simulate_request.portfolio_snapshot.portfolio_id
        else:
            raise AssertionError("workspace input is required")
        return (
            WorkspaceResolvedContext(
                portfolio_id=portfolio_id,
                as_of="2026-07-11",
                portfolio_snapshot_id="ps_fake_context_001",
            ),
            WorkspaceDraftState(),
        )

    def build_simulate_request(self, session: WorkspaceSession) -> ProposalSimulateRequest:
        self.simulate_request_sessions.append(session.workspace_id)
        if session.stateless_input is None:
            raise AssertionError("stateless simulate request is required for this test")
        return session.stateless_input.simulate_request


class _FakeWorkspaceProposalEvaluator:
    def __init__(self) -> None:
        self.evaluated_workspace_ids: list[str] = []

    def evaluate(
        self,
        *,
        session: WorkspaceSession,
        simulate_request: ProposalSimulateRequest,
    ) -> WorkspaceEvaluationOutcome:
        _ = simulate_request
        self.evaluated_workspace_ids.append(session.workspace_id)
        return WorkspaceEvaluationOutcome(
            proposal_result=_fake_proposal_result(),
            evaluation_summary=WorkspaceEvaluationSummary(
                status="READY",
                impact_summary=WorkspaceEvaluationImpactSummary(
                    portfolio_value_delta_base_ccy="0.00",
                    trade_count=len(session.draft_state.trade_drafts),
                    cash_flow_count=len(session.draft_state.cash_flow_drafts),
                ),
            ),
            replay_evidence=WorkspaceReplayEvidence(
                input_mode=session.input_mode,
                resolved_context=session.resolved_context,
                draft_state_hash="sha256:fake_draft_state",
                evaluation_request_hash="sha256:fake_evaluation_request",
                captured_at="2026-07-11T08:31:00+00:00",
            ),
        )


class _FakeProposalLifecycle:
    def __init__(self) -> None:
        self.create_proposal_calls: list[dict[str, object]] = []

    def create_proposal(self, **kwargs: object) -> ProposalCreateResponse:
        self.create_proposal_calls.append(kwargs)
        from src.core.proposals.models import (
            ProposalCreateResponse,
            ProposalSummary,
            ProposalVersionDetail,
            ProposalWorkflowEvent,
        )

        return ProposalCreateResponse.model_construct(
            proposal=ProposalSummary.model_construct(
                proposal_id="pp_fake_001",
                portfolio_id="PB_SG_GLOBAL_BAL_001",
                lifecycle_origin="WORKSPACE_HANDOFF",
                created_at="2026-07-11T08:32:00+00:00",
                created_by="advisor_123",
                last_event_at="2026-07-11T08:32:00+00:00",
                current_state="DRAFT",
                current_version_no=1,
            ),
            version=ProposalVersionDetail.model_construct(
                proposal_version_id="ppv_fake_001",
                proposal_id="pp_fake_001",
                version_no=1,
                request_hash="sha256:fake_request",
                artifact_hash="sha256:fake_artifact",
                simulation_hash="sha256:fake_simulation",
                status_at_creation="READY",
                created_at="2026-07-11T08:32:00+00:00",
            ),
            latest_workflow_event=ProposalWorkflowEvent.model_construct(
                event_id="pwe_fake_001",
                proposal_id="pp_fake_001",
                event_type="CREATED",
                to_state="DRAFT",
                actor_id="advisor_123",
                occurred_at="2026-07-11T08:32:00+00:00",
            ),
        )

    def create_version(self, **kwargs: Any) -> ProposalCreateResponse:
        _ = kwargs
        raise AssertionError("new proposal handoff should not create a version")


def test_workspace_application_create_session_uses_ports_not_api_service_state() -> None:
    repository = _FakeWorkspaceSessionRepository()
    source_resolver = _FakeWorkspaceSourceContextResolver()
    service = WorkspaceApplicationService(
        session_repository=repository,
        source_context_resolver=source_resolver,
        clock=lambda: datetime(2026, 7, 11, 8, 30, tzinfo=UTC),
        workspace_id_factory=lambda: "aws_application_001",
        workspace_version_id_factory=lambda: "awsv_application_001",
    )
    request = WorkspaceSessionCreateRequest.model_validate(
        {
            "workspace_name": "Application-bound workspace",
            "created_by": "advisor_123",
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "as_of": "2026-07-11",
            },
        }
    )

    response = service.create_session(request)

    assert response.workspace.workspace_id == "aws_application_001"
    assert response.workspace.created_at == "2026-07-11T08:30:00+00:00"
    assert response.workspace.resolved_context is not None
    assert response.workspace.resolved_context.portfolio_snapshot_id == "ps_fake_context_001"
    assert repository.sessions["aws_application_001"] is response.workspace
    assert source_resolver.initial_context_requests == [request]


def test_workspace_application_reevaluate_session_uses_source_and_evaluator_ports() -> None:
    repository = _FakeWorkspaceSessionRepository()
    source_resolver = _FakeWorkspaceSourceContextResolver()
    proposal_evaluator = _FakeWorkspaceProposalEvaluator()
    service = WorkspaceApplicationService(
        session_repository=repository,
        source_context_resolver=source_resolver,
        proposal_evaluator=proposal_evaluator,
        clock=lambda: datetime(2026, 7, 11, 8, 30, tzinfo=UTC),
    )
    session = service.create_session(
        WorkspaceSessionCreateRequest.model_validate(
            {
                "workspace_name": "Application-bound workspace",
                "created_by": "advisor_123",
                "input_mode": "stateless",
                "stateless_input": {
                    "simulate_request": {
                        "portfolio_snapshot": {
                            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                            "base_currency": "USD",
                            "positions": [],
                            "cash_balances": [{"currency": "USD", "amount": "1000"}],
                        },
                        "market_data_snapshot": {"prices": [], "fx_rates": []},
                        "shelf_entries": [],
                        "options": {"enable_proposal_simulation": True},
                        "proposed_cash_flows": [],
                        "proposed_trades": [],
                    }
                },
            }
        )
    ).workspace

    updated = service.reevaluate_session(session.workspace_id)

    assert source_resolver.simulate_request_sessions == [session.workspace_id]
    assert proposal_evaluator.evaluated_workspace_ids == [session.workspace_id]
    assert updated.evaluation_summary is not None
    assert updated.evaluation_summary.status == "READY"
    assert updated.latest_replay_evidence is not None
    assert (
        updated.latest_replay_evidence.evaluation_request_hash == "sha256:fake_evaluation_request"
    )
    assert repository.sessions[session.workspace_id] is updated


def test_workspace_application_handoff_uses_lifecycle_port() -> None:
    repository = _FakeWorkspaceSessionRepository()
    source_resolver = _FakeWorkspaceSourceContextResolver()
    service = WorkspaceApplicationService(
        session_repository=repository,
        source_context_resolver=source_resolver,
        clock=lambda: datetime(2026, 7, 11, 8, 30, tzinfo=UTC),
        workspace_id_factory=lambda: "aws_handoff_001",
    )
    session = service.create_session(
        WorkspaceSessionCreateRequest.model_validate(
            {
                "workspace_name": "Lifecycle workspace",
                "created_by": "advisor_123",
                "input_mode": "stateless",
                "stateless_input": {
                    "simulate_request": {
                        "portfolio_snapshot": {
                            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                            "base_currency": "USD",
                            "positions": [],
                            "cash_balances": [{"currency": "USD", "amount": "1000"}],
                        },
                        "market_data_snapshot": {"prices": [], "fx_rates": []},
                        "shelf_entries": [],
                        "options": {"enable_proposal_simulation": True},
                        "proposed_cash_flows": [],
                        "proposed_trades": [],
                    }
                },
            }
        )
    ).workspace
    lifecycle = _FakeProposalLifecycle()

    from src.core.workspace.handoff_models import WorkspaceLifecycleHandoffRequest

    response = service.handoff_to_proposal_lifecycle(
        workspace_id=session.workspace_id,
        request=WorkspaceLifecycleHandoffRequest(handoff_by="advisor_123"),
        proposal_lifecycle=lifecycle,
        idempotency_key="workspace-handoff-fake-001",
        correlation_id="corr-workspace-handoff-fake-001",
    )

    assert response.proposal.proposal.proposal_id == "pp_fake_001"
    assert lifecycle.create_proposal_calls
    assert lifecycle.create_proposal_calls[0]["source_workspace_id"] == "aws_handoff_001"
    assert repository.sessions[session.workspace_id].lifecycle_link is not None


def test_workspace_application_recovers_saved_state_across_repository_instances() -> None:
    storage = _SharedDurableWorkspaceStorage()
    first_repository = _DurableFakeWorkspaceSessionRepository(storage)
    first_service = WorkspaceApplicationService(
        session_repository=first_repository,
        source_context_resolver=_FakeWorkspaceSourceContextResolver(),
        proposal_evaluator=_FakeWorkspaceProposalEvaluator(),
        clock=lambda: datetime(2026, 7, 11, 8, 30, tzinfo=UTC),
        workspace_id_factory=lambda: "aws_persisted_001",
        workspace_version_id_factory=lambda: "awsv_persisted_001",
    )
    created = first_service.create_session(
        _stateless_workspace_request("Persisted workspace")
    ).workspace
    evaluated = first_service.reevaluate_session(created.workspace_id)
    saved = first_service.save_version(
        evaluated.workspace_id,
        request=_workspace_save_request(),
    ).saved_version

    second_repository = _DurableFakeWorkspaceSessionRepository(storage)
    second_service = WorkspaceApplicationService(
        session_repository=second_repository,
        source_context_resolver=_FakeWorkspaceSourceContextResolver(),
        clock=lambda: datetime(2026, 7, 11, 8, 35, tzinfo=UTC),
    )

    recovered = second_service.get_session("aws_persisted_001")
    listed = second_service.list_saved_versions(recovered.workspace_id)
    comparison = second_service.compare_to_saved_version(
        recovered.workspace_id,
        request=_workspace_compare_request(saved.workspace_version_id),
    )
    resumed = second_service.resume_version(
        recovered.workspace_id,
        request=_workspace_resume_request(saved.workspace_version_id),
    )
    lifecycle = _FakeProposalLifecycle()
    handoff = second_service.handoff_to_proposal_lifecycle(
        workspace_id=recovered.workspace_id,
        request=_workspace_handoff_request(),
        proposal_lifecycle=lifecycle,
        idempotency_key="workspace-handoff-persisted-001",
        correlation_id="corr-workspace-handoff-persisted-001",
    )

    assert recovered.workspace_id == "aws_persisted_001"
    assert recovered is not evaluated
    assert listed.saved_versions[0].workspace_version_id == "awsv_persisted_001"
    assert comparison.baseline_version.workspace_version_id == "awsv_persisted_001"
    assert comparison.current_replay_evidence is not None
    assert comparison.current_replay_evidence.evaluation_request_hash == (
        "sha256:fake_evaluation_request"
    )
    assert resumed.latest_replay_evidence is not None
    assert resumed.latest_replay_evidence.evaluation_request_hash == (
        "sha256:fake_evaluation_request"
    )
    assert handoff.workspace.lifecycle_link is not None
    assert handoff.workspace.lifecycle_link.proposal_id == "pp_fake_001"
    assert lifecycle.create_proposal_calls[0]["source_workspace_id"] == "aws_persisted_001"


def test_workspace_application_and_routes_preserve_layering_boundary() -> None:
    application_source = Path("src/core/workspace/application.py").read_text(encoding="utf-8")
    ports_source = Path("src/core/workspace/ports.py").read_text(encoding="utf-8")
    routes_session_source = Path("src/api/workspaces/routes_session.py").read_text(encoding="utf-8")
    routes_handoff_source = Path("src/api/workspaces/routes_handoff.py").read_text(encoding="utf-8")
    context_adapter_source = Path("src/infrastructure/workspace/lotus_core_context.py").read_text(
        encoding="utf-8"
    )

    assert "src.api.services.workspace_service" not in routes_session_source
    assert "src.api.services.workspace_service" not in routes_handoff_source
    assert "get_workspace_application_service_dependency" in routes_session_source
    assert "get_workspace_application_service_dependency" in routes_handoff_source
    assert "ProposalWorkflowService" not in routes_handoff_source
    assert "proposal_shared" not in routes_handoff_source

    assert "src.api." not in application_source
    assert "src.integrations." not in application_source
    assert "src.api." not in ports_source
    assert "src.integrations." not in ports_source

    assert "from src.integrations.lotus_core" in context_adapter_source


def _stateless_workspace_request(workspace_name: str) -> WorkspaceSessionCreateRequest:
    return WorkspaceSessionCreateRequest.model_validate(
        {
            "workspace_name": workspace_name,
            "created_by": "advisor_123",
            "input_mode": "stateless",
            "stateless_input": {
                "simulate_request": {
                    "portfolio_snapshot": {
                        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                        "base_currency": "USD",
                        "positions": [],
                        "cash_balances": [{"currency": "USD", "amount": "1000"}],
                    },
                    "market_data_snapshot": {"prices": [], "fx_rates": []},
                    "shelf_entries": [],
                    "options": {"enable_proposal_simulation": True},
                    "proposed_cash_flows": [],
                    "proposed_trades": [],
                }
            },
        }
    )


def _workspace_save_request():
    from src.core.workspace.save_models import WorkspaceSaveRequest

    return WorkspaceSaveRequest(
        saved_by="advisor_123",
        version_label="Persisted checkpoint",
    )


def _workspace_compare_request(workspace_version_id: str):
    from src.core.workspace.compare_models import WorkspaceCompareRequest

    return WorkspaceCompareRequest(workspace_version_id=workspace_version_id)


def _workspace_resume_request(workspace_version_id: str):
    from src.core.workspace.save_models import WorkspaceResumeRequest

    return WorkspaceResumeRequest(
        actor_id="advisor_123",
        workspace_version_id=workspace_version_id,
    )


def _workspace_handoff_request():
    from src.core.workspace.handoff_models import WorkspaceLifecycleHandoffRequest

    return WorkspaceLifecycleHandoffRequest(handoff_by="advisor_123")


def _fake_proposal_result() -> ProposalResult:
    state = SimulatedState(
        total_value=Money(amount=Decimal("1000"), currency="USD"),
        cash_balances=[],
        positions=[],
        allocation_by_asset_class=[],
        allocation_by_instrument=[],
        allocation=[],
        allocation_by_attribute={},
    )
    return ProposalResult(
        proposal_run_id="pr_workspace_fake_001",
        correlation_id="corr_workspace_fake_001",
        status="READY",
        before=state,
        intents=[],
        after_simulated=state,
        reconciliation=Reconciliation(
            before_total_value=Money(amount=Decimal("1000"), currency="USD"),
            after_total_value=Money(amount=Decimal("1000"), currency="USD"),
            delta=Money(amount=Decimal("0"), currency="USD"),
            tolerance=Money(amount=Decimal("1"), currency="USD"),
            status="OK",
        ),
        rule_results=[
            RuleResult(
                rule_id="DATA_QUALITY",
                severity="HARD",
                status="PASS",
                measured=Decimal("0"),
                threshold={"max": Decimal("0")},
                reason_code="OK",
            )
        ],
        explanation={"summary": "READY"},
        diagnostics={"data_quality": {"price_missing": [], "fx_missing": [], "shelf_missing": []}},
        lineage={
            "portfolio_snapshot_id": "ps_workspace_fake_001",
            "market_data_snapshot_id": "md_workspace_fake_001",
            "request_hash": "sha256:fake_request",
        },
    )
