from src.core.portfolio_models import ReferenceModel
from src.core.workspace.draft_state import build_draft_state_from_simulate_request
from src.core.workspace.models import WorkspaceResolvedContext, WorkspaceSessionCreateRequest
from src.core.workspace.sessions import (
    build_stateless_workspace_resolved_context,
    build_workspace_session,
)


def _stateless_create_request() -> WorkspaceSessionCreateRequest:
    return WorkspaceSessionCreateRequest.model_validate(
        {
            "workspace_name": "Session builder workspace",
            "created_by": "advisor_123",
            "input_mode": "stateless",
            "stateless_input": {
                "simulate_request": {
                    "portfolio_snapshot": {
                        "portfolio_id": "pf_sessions",
                        "base_currency": "USD",
                        "positions": [],
                        "cash_balances": [{"currency": "USD", "amount": "1000"}],
                    },
                    "market_data_snapshot": {"prices": [], "fx_rates": []},
                    "shelf_entries": [],
                    "options": {"enable_proposal_simulation": True},
                    "proposed_cash_flows": [],
                    "proposed_trades": [
                        {"side": "BUY", "instrument_id": "EQ_GROWTH", "quantity": "2"}
                    ],
                }
            },
        }
    )


def test_build_workspace_session_uses_supplied_identity_context_and_draft_state() -> None:
    request = _stateless_create_request()
    assert request.stateless_input is not None
    draft_state = build_draft_state_from_simulate_request(request.stateless_input.simulate_request)
    resolved_context = WorkspaceResolvedContext(
        portfolio_id="pf_sessions",
        as_of="2026-05-20",
        portfolio_snapshot_id="ps_001",
        market_data_snapshot_id="md_001",
    )

    session = build_workspace_session(
        request=request,
        workspace_id="aws_supplied",
        created_at="2026-05-20T10:30:00+00:00",
        draft_state=draft_state,
        resolved_context=resolved_context,
    )

    assert session.workspace_id == "aws_supplied"
    assert session.workspace_name == "Session builder workspace"
    assert session.lifecycle_state == "ACTIVE"
    assert session.created_by == "advisor_123"
    assert session.created_at == "2026-05-20T10:30:00+00:00"
    assert session.stateless_input is request.stateless_input
    assert session.stateful_input is None
    assert session.draft_state is draft_state
    assert session.resolved_context is resolved_context
    assert session.saved_versions == []
    assert session.saved_version_count == 0
    assert session.latest_saved_version is None
    assert session.lifecycle_link is None


def test_build_stateless_workspace_resolved_context_does_not_infer_date() -> None:
    request = _stateless_create_request()
    assert request.stateless_input is not None
    simulate_request = request.stateless_input.simulate_request
    simulate_request.portfolio_snapshot.snapshot_id = "ps_sessions"
    simulate_request.market_data_snapshot.snapshot_id = "md_sessions"

    resolved_context = build_stateless_workspace_resolved_context(
        stateless_input=request.stateless_input,
    )

    assert resolved_context.portfolio_id == "pf_sessions"
    assert resolved_context.as_of is None
    assert resolved_context.requested_as_of is None
    assert resolved_context.portfolio_snapshot_id == "ps_sessions"
    assert resolved_context.market_data_snapshot_id == "md_sessions"


def test_build_stateless_workspace_resolved_context_preserves_reference_model_date() -> None:
    request = _stateless_create_request()
    assert request.stateless_input is not None
    request.stateless_input.simulate_request.reference_model = ReferenceModel(
        model_id="model_sessions",
        as_of="2026-05-21",
        base_currency="USD",
    )

    resolved_context = build_stateless_workspace_resolved_context(
        stateless_input=request.stateless_input,
    )

    assert resolved_context.as_of == "2026-05-21"
    assert resolved_context.requested_as_of == "2026-05-21"
