from decimal import Decimal

import pytest

from src.api.proposals.router import (
    get_proposal_workflow_service,
    reset_proposal_workflow_service_for_tests,
)
from src.api.services import workspace_service
from src.api.services.workspace_errors import (
    WorkspaceEvaluationUnavailableError,
    WorkspaceNotFoundError,
)
from src.api.services.workspace_service import (
    WorkspaceDraftActionRequest,
    WorkspaceSessionCreateRequest,
    create_workspace_session,
    get_workspace_session,
    handoff_workspace_to_proposal_lifecycle,
    reset_workspace_sessions_for_tests,
    save_workspace_version,
)
from src.core.workspace.evaluation import format_portfolio_delta
from src.core.workspace.handoff import (
    build_handoff_metadata,
    build_proposal_version_request,
)
from src.core.workspace.models import WorkspaceLifecycleLink
from tests.shared.stateful_context_builders import build_resolved_stateful_context


def setup_function() -> None:
    reset_workspace_sessions_for_tests()
    reset_proposal_workflow_service_for_tests()


def _resolved_stateful_context(portfolio_id: str, as_of: str) -> dict:
    return build_resolved_stateful_context(
        portfolio_id,
        as_of,
        include_context_ids=False,
    )


def test_workspace_session_cache_evicts_oldest_entry() -> None:
    original_limit = workspace_service.MAX_WORKSPACE_SESSION_CACHE_SIZE
    workspace_service.MAX_WORKSPACE_SESSION_CACHE_SIZE = 1
    try:
        first = create_workspace_session(
            WorkspaceSessionCreateRequest.model_validate(
                {
                    "workspace_name": "First workspace",
                    "created_by": "advisor_123",
                    "input_mode": "stateful",
                    "stateful_input": {"portfolio_id": "pf_001", "as_of": "2026-03-25"},
                }
            )
        ).workspace
        second = create_workspace_session(
            WorkspaceSessionCreateRequest.model_validate(
                {
                    "workspace_name": "Second workspace",
                    "created_by": "advisor_123",
                    "input_mode": "stateful",
                    "stateful_input": {"portfolio_id": "pf_002", "as_of": "2026-03-25"},
                }
            )
        ).workspace

        with pytest.raises(WorkspaceNotFoundError):
            get_workspace_session(first.workspace_id)

        assert get_workspace_session(second.workspace_id).workspace_name == "Second workspace"
    finally:
        workspace_service.MAX_WORKSPACE_SESSION_CACHE_SIZE = original_limit
        reset_workspace_sessions_for_tests()


def test_create_workspace_session_rejects_malformed_constructed_requests() -> None:
    malformed_stateless = WorkspaceSessionCreateRequest.model_construct(
        workspace_name="Bad stateless",
        created_by="advisor_123",
        input_mode="stateless",
        stateless_input=None,
        stateful_input=None,
    )
    malformed_stateful = WorkspaceSessionCreateRequest.model_construct(
        workspace_name="Bad stateful",
        created_by="advisor_123",
        input_mode="stateful",
        stateless_input=None,
        stateful_input=None,
    )

    with pytest.raises(ValueError, match="stateless workspace creation requires stateless_input"):
        create_workspace_session(malformed_stateless)

    with pytest.raises(ValueError, match="stateful workspace creation requires stateful_input"):
        create_workspace_session(malformed_stateful)


def test_workspace_service_replace_options_and_stateful_handoff_guard(monkeypatch) -> None:
    monkeypatch.setenv("LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK", "true")
    session = create_workspace_session(
        WorkspaceSessionCreateRequest.model_validate(
            {
                "workspace_name": "Stateful workspace",
                "created_by": "advisor_123",
                "input_mode": "stateful",
                "stateful_input": {
                    "portfolio_id": "pf_001",
                    "household_id": "hh_001",
                    "mandate_id": "mandate_growth_01",
                    "as_of": "2026-03-25",
                    "reporting_currency": "EUR",
                },
            }
        )
    ).workspace

    with pytest.raises(
        WorkspaceEvaluationUnavailableError,
        match="WORKSPACE_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE",
    ):
        workspace_service._build_simulate_request_for_workspace(session)

    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )

    resolved_request = workspace_service._build_simulate_request_for_workspace(session)
    assert resolved_request.portfolio_snapshot.snapshot_id == "ps_pf_001_2026-03-25"
    assert session.resolved_context is not None
    assert session.resolved_context.portfolio_snapshot_id == "ps_pf_001_2026-03-25"

    request = WorkspaceDraftActionRequest.model_validate(
        {
            "actor_id": "advisor_123",
            "action_type": "REPLACE_OPTIONS",
            "options": {
                "enable_proposal_simulation": True,
                "auto_funding": False,
                "fx_buffer_pct": Decimal("0.02"),
            },
        }
    )
    session.draft_state.options = request.options.model_copy(deep=True)
    assert session.draft_state.options.auto_funding is False
    assert session.draft_state.options.fx_buffer_pct == Decimal("0.02")

    handoff_response = handoff_workspace_to_proposal_lifecycle(
        workspace_id=session.workspace_id,
        request=workspace_service.WorkspaceLifecycleHandoffRequest(handoff_by="advisor_123"),
        proposal_service=get_proposal_workflow_service(),
        idempotency_key="workspace-handoff-idem-direct",
        correlation_id=None,
    )
    assert handoff_response.proposal.proposal.lifecycle_origin == "WORKSPACE_HANDOFF"
    assert handoff_response.workspace.resolved_context is not None
    assert (
        handoff_response.workspace.resolved_context.portfolio_snapshot_id == "ps_pf_001_2026-03-25"
    )
    first_valuation = handoff_response.proposal.version.proposal_result.valuation_context
    assert first_valuation.current_state.requested_as_of_date == "2026-03-25"
    assert first_valuation.current_state.requested_reporting_currency == "EUR"
    assert first_valuation.simulated_state.requested_as_of_date == "2026-03-25"
    assert first_valuation.simulated_state.requested_reporting_currency == "EUR"
    assert first_valuation.current_state.supportability == "PARTIAL"
    assert first_valuation.current_state.reason_code == ("REQUESTED_REPORTING_CURRENCY_NOT_HONORED")
    assert first_valuation.simulated_state.supportability == "PARTIAL"
    assert first_valuation.simulated_state.reason_code == (
        "REQUESTED_REPORTING_CURRENCY_NOT_HONORED"
    )

    version_response = handoff_workspace_to_proposal_lifecycle(
        workspace_id=session.workspace_id,
        request=workspace_service.WorkspaceLifecycleHandoffRequest(handoff_by="advisor_123"),
        proposal_service=get_proposal_workflow_service(),
        idempotency_key="workspace-handoff-idem-version",
        correlation_id=None,
    )
    version_valuation = version_response.proposal.version.proposal_result.valuation_context
    assert version_valuation.current_state.requested_as_of_date == "2026-03-25"
    assert version_valuation.current_state.requested_reporting_currency == "EUR"
    assert version_valuation.simulated_state.requested_as_of_date == "2026-03-25"
    assert version_valuation.simulated_state.requested_reporting_currency == "EUR"
    assert version_valuation.current_state.supportability == "PARTIAL"
    assert version_valuation.current_state.reason_code == (
        "REQUESTED_REPORTING_CURRENCY_NOT_HONORED"
    )
    assert version_valuation.simulated_state.supportability == "PARTIAL"
    assert version_valuation.simulated_state.reason_code == (
        "REQUESTED_REPORTING_CURRENCY_NOT_HONORED"
    )


def test_workspace_service_trade_and_cash_flow_not_found_guards() -> None:
    session = create_workspace_session(
        WorkspaceSessionCreateRequest.model_validate(
            {
                "workspace_name": "Sandbox workspace",
                "created_by": "advisor_123",
                "input_mode": "stateless",
                "stateless_input": {
                    "simulate_request": {
                        "portfolio_snapshot": {
                            "portfolio_id": "pf_001",
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

    with pytest.raises(
        WorkspaceNotFoundError,
        match="WORKSPACE_CASH_FLOW_NOT_FOUND",
    ):
        workspace_service.apply_workspace_draft_action(
            session.workspace_id,
            WorkspaceDraftActionRequest.model_validate(
                {
                    "actor_id": "advisor_123",
                    "action_type": "REMOVE_CASH_FLOW",
                    "workspace_cash_flow_id": "wcf_missing",
                }
            ),
        )

    with pytest.raises(WorkspaceNotFoundError, match="WORKSPACE_TRADE_NOT_FOUND"):
        workspace_service.apply_workspace_draft_action(
            session.workspace_id,
            WorkspaceDraftActionRequest.model_validate(
                {
                    "actor_id": "advisor_123",
                    "action_type": "REMOVE_TRADE",
                    "workspace_trade_id": "wtd_missing",
                }
            ),
        )


def test_workspace_service_portfolio_delta_and_mandate_fallback() -> None:
    summary_request = WorkspaceSessionCreateRequest.model_validate(
        {
            "workspace_name": "Sandbox workspace",
            "created_by": "advisor_123",
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": "pf_001",
                "mandate_id": "mandate_growth_01",
                "as_of": "2026-03-25",
            },
        }
    )
    session = create_workspace_session(summary_request).workspace

    metadata = build_handoff_metadata(
        workspace_service.WorkspaceLifecycleHandoffRequest(handoff_by="advisor_123"),
        session,
    )
    assert metadata.mandate_id == "mandate_growth_01"

    class ResultWithoutReconciliation:
        reconciliation = None

        class after_simulated:
            total_value = type("MoneyHolder", (), {"amount": Decimal("120.00")})()

        class before:
            total_value = type("MoneyHolder", (), {"amount": Decimal("100.00")})()

    assert format_portfolio_delta(ResultWithoutReconciliation()) == "20.00"


def test_workspace_service_builds_version_request_with_expected_current_version() -> None:
    session = create_workspace_session(
        WorkspaceSessionCreateRequest.model_validate(
            {
                "workspace_name": "Lifecycle-linked workspace",
                "created_by": "advisor_123",
                "input_mode": "stateless",
                "stateless_input": {
                    "simulate_request": {
                        "portfolio_snapshot": {
                            "portfolio_id": "pf_001",
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
    session.lifecycle_link = WorkspaceLifecycleLink(
        proposal_id="pp_001",
        current_version_no=3,
        last_handoff_at="2026-03-25T10:00:00+00:00",
        last_handoff_by="advisor_123",
    )

    assert session.stateless_input is not None
    payload = build_proposal_version_request(
        session,
        workspace_service.WorkspaceLifecycleHandoffRequest(handoff_by="advisor_123"),
        session.stateless_input.simulate_request,
    )

    assert payload.expected_current_version_no == 3


def test_workspace_handoff_updates_saved_version_replay_continuity() -> None:
    session = create_workspace_session(
        WorkspaceSessionCreateRequest.model_validate(
            {
                "workspace_name": "Replay continuity workspace",
                "created_by": "advisor_123",
                "input_mode": "stateless",
                "stateless_input": {
                    "simulate_request": {
                        "portfolio_snapshot": {
                            "portfolio_id": "pf_001",
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

    session = workspace_service.reevaluate_workspace_session(session.workspace_id)
    saved = save_workspace_version(
        session.workspace_id,
        workspace_service.WorkspaceSaveRequest(saved_by="advisor_123", version_label="Baseline"),
    ).saved_version

    handoff = handoff_workspace_to_proposal_lifecycle(
        workspace_id=session.workspace_id,
        request=workspace_service.WorkspaceLifecycleHandoffRequest(handoff_by="advisor_123"),
        proposal_service=get_proposal_workflow_service(),
        idempotency_key="workspace-handoff-replay-001",
        correlation_id="corr-workspace-handoff-replay-001",
    )

    continuity = handoff.workspace.latest_replay_evidence.continuity
    assert continuity["workspace_version_id"] == saved.workspace_version_id
    assert continuity["proposal_id"] == handoff.proposal.proposal.proposal_id
    assert continuity["proposal_version_no"] == handoff.proposal.version.version_no
    assert continuity["handoff_action"] == "CREATED_PROPOSAL"
    assert continuity["handoff_by"] == "advisor_123"
    assert saved.latest_proposal_result is not None
    assert saved.latest_proposal_result.proposal_decision_summary is not None

    reloaded = get_workspace_session(session.workspace_id)
    assert reloaded.saved_versions[0].replay_evidence.continuity == continuity
    assert reloaded.saved_versions[0].latest_proposal_result is not None
    assert reloaded.saved_versions[0].latest_proposal_result.proposal_decision_summary is not None
