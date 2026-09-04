import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.proposals.router import reset_proposal_workflow_service_for_tests
from src.api.services.workspace_errors import (
    WorkspaceAssistantUnavailableError,
    WorkspaceEvaluationUnavailableError,
    WorkspaceNotFoundError,
)
from src.api.services.workspace_service import (
    get_workspace_session,
    reevaluate_workspace_session,
    reset_workspace_sessions_for_tests,
)
from src.api.workspaces.dependencies import get_workspace_application_service_dependency
from src.core.advisory.provider_ports import (
    AdvisoryRiskEnrichmentUnavailableError as LotusRiskEnrichmentUnavailableError,
)
from src.integrations.lotus_core.stateful_context import reset_stateful_context_cache_for_tests
from tests.shared.lotus_core_query_fakes import (
    CountingLotusCoreQueryClient,
    build_basic_stateful_query_responses,
)
from tests.shared.stateful_context_builders import (
    build_resolved_stateful_context,
    build_tradeable_universe_stateful_context,
)

workspace_router = importlib.import_module("src.api.workspaces.router")
workspace_routes_assistant = importlib.import_module("src.api.workspaces.routes_assistant")
workspace_evaluator_module = importlib.import_module("src.core.workspace.evaluator")
workspace_service_module = importlib.import_module("src.api.services.workspace_service")


@pytest.fixture(autouse=True)
def clear_risk_dependency_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "")
    monkeypatch.setattr(
        "src.core.advisory.orchestration.build_lotus_risk_dependency_state",
        lambda: SimpleNamespace(configured=False),
    )

    def _risk_unavailable(**kwargs):  # noqa: ANN003
        raise LotusRiskEnrichmentUnavailableError("LOTUS_RISK_ENRICHMENT_UNAVAILABLE")

    monkeypatch.setattr(
        "src.core.advisory.orchestration.enrich_with_lotus_risk",
        _risk_unavailable,
    )


def setup_function() -> None:
    reset_workspace_sessions_for_tests()
    reset_proposal_workflow_service_for_tests()
    reset_stateful_context_cache_for_tests()


def _resolved_stateful_context(portfolio_id: str, as_of: str) -> dict:
    return build_resolved_stateful_context(
        portfolio_id,
        as_of,
        cash_amount="10000",
        include_context_ids=False,
    )


def _resolved_stateful_context_with_tradeable_universe(portfolio_id: str, as_of: str) -> dict:
    return build_tradeable_universe_stateful_context(portfolio_id, as_of)


def _normalize_proposal_result_for_parity(body: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        key: value for key, value in body.items() if key not in {"correlation_id", "lineage"}
    }
    lineage = dict(body["lineage"])
    lineage.pop("idempotency_key", None)
    normalized["lineage"] = lineage
    explanation = dict(normalized.get("explanation", {}))
    context_resolution = explanation.get("context_resolution")
    if isinstance(context_resolution, dict):
        normalized_context_resolution = dict(context_resolution)
        normalized_context_resolution.pop("used_legacy_contract", None)
        explanation["context_resolution"] = normalized_context_resolution
        normalized["explanation"] = explanation
    return normalized


def _normalize_created_version_result_for_parity(body: dict[str, Any]) -> dict[str, Any]:
    return _normalize_proposal_result_for_parity(body["version"]["proposal_result"])


def _normalize_business_result_for_cross_mode_parity(body: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_proposal_result_for_parity(body)
    normalized.pop("proposal_run_id", None)
    normalized.pop("lineage", None)
    normalized.pop("explanation", None)
    normalized.pop("proposal_review_evidence", None)
    normalized.pop("valuation_context", None)
    return normalized


def _risk_enriched_result(result):  # noqa: ANN001
    result.explanation["risk_lens"] = {
        "source_service": "lotus-risk",
        "input_mode": "simulation",
        "risk_proxy": {"hhi_current": 5200.0, "hhi_proposed": 6800.0, "hhi_delta": 1600.0},
        "single_position_concentration": {
            "top_position_weight_current": 0.5,
            "top_position_weight_proposed": 0.6,
        },
        "issuer_concentration": {
            "hhi_current": 5200.0,
            "hhi_proposed": 5800.0,
        },
    }
    return result


def test_create_stateful_workspace_session_returns_workspace_context(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    payload = {
        "workspace_name": "Q2 2026 growth reallocation draft",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_advisory_01",
            "household_id": "hh_001",
            "as_of": "2026-03-25",
            "mandate_id": "mandate_growth_01",
        },
    }

    with TestClient(app) as client:
        response = client.post("/advisory/workspaces", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["workspace"]["workspace_id"].startswith("aws_")
    assert body["workspace"]["input_mode"] == "stateful"
    assert body["workspace"]["stateful_input"]["portfolio_id"] == "pf_advisory_01"
    assert body["workspace"]["resolved_context"]["portfolio_id"] == "pf_advisory_01"
    assert body["workspace"]["resolved_context"]["portfolio_snapshot_id"] == (
        "ps_pf_advisory_01_2026-03-25"
    )
    assert body["workspace"]["draft_state"]["trade_drafts"] == []
    assert body["workspace"]["evaluation_summary"] is None


def test_stateful_workspace_reuses_cached_lotus_core_context_across_re_evaluations(
    monkeypatch,
) -> None:
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", base_url)
    client = CountingLotusCoreQueryClient(
        build_basic_stateful_query_responses(
            base_url=base_url,
            portfolio_id="pf_stateful_cached_workspace",
            as_of="2026-03-25",
        )
    )
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: client,
    )
    payload = {
        "workspace_name": "Cached stateful workspace",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_cached_workspace",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as test_client:
        created = test_client.post("/advisory/workspaces", json=payload)
        assert created.status_code == 201
        workspace_id = created.json()["workspace"]["workspace_id"]

        first = test_client.post(f"/advisory/workspaces/{workspace_id}/evaluate")
        second = test_client.post(f"/advisory/workspaces/{workspace_id}/evaluate")

    assert first.status_code == 200
    assert second.status_code == 200
    assert client.request_count == 6


def test_stateful_workspace_recovers_after_initial_lotus_core_resolution_failure(
    monkeypatch,
) -> None:
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", base_url)
    portfolio_payload = {
        "portfolio_id": "pf_stateful_recovery_workspace",
        "base_currency": "",
    }

    class _RecoveringQueryClient(CountingLotusCoreQueryClient):
        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
        ):
            if (method.upper(), url) == (
                "GET",
                f"{base_url}/portfolios/pf_stateful_recovery_workspace",
            ):
                self.request_count += 1
                return self._responses[(method.upper(), url)].__class__(dict(portfolio_payload))
            return super().request(method, url, json=json, headers=headers)

    responses = build_basic_stateful_query_responses(
        base_url=base_url,
        portfolio_id="pf_stateful_recovery_workspace",
        as_of="2026-03-25",
    )
    client = _RecoveringQueryClient(responses)
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: client,
    )
    payload = {
        "workspace_name": "Recovering stateful workspace",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_recovery_workspace",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as test_client:
        created = test_client.post("/advisory/workspaces", json=payload)
        assert created.status_code == 201
        workspace_id = created.json()["workspace"]["workspace_id"]

        failed = test_client.post(f"/advisory/workspaces/{workspace_id}/evaluate")

        portfolio_payload["base_currency"] = "USD"
        recovered = test_client.post(f"/advisory/workspaces/{workspace_id}/evaluate")

    assert failed.status_code == 409
    assert failed.json()["detail"] == "WORKSPACE_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"
    assert recovered.status_code == 200
    assert recovered.json()["resolved_context"]["portfolio_id"] == "pf_stateful_recovery_workspace"
    assert client.request_count == 18


def test_create_stateless_workspace_session_returns_snapshot_context():
    payload = {
        "workspace_name": "Sandbox drift review",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "snapshot_id": "ps_001",
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [],
                },
                "market_data_snapshot": {
                    "snapshot_id": "md_001",
                    "prices": [],
                    "fx_rates": [],
                },
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        response = client.post("/advisory/workspaces", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["workspace"]["input_mode"] == "stateless"
    assert body["workspace"]["resolved_context"]["portfolio_snapshot_id"] == "ps_001"
    assert body["workspace"]["resolved_context"]["market_data_snapshot_id"] == "md_001"
    assert body["workspace"]["draft_state"]["trade_drafts"] == []


def test_create_workspace_rejects_mixed_mode_payloads():
    payload = {
        "workspace_name": "Bad mixed workspace",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [],
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
        "stateful_input": {
            "portfolio_id": "pf_advisory_01",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as client:
        response = client.post("/advisory/workspaces", json=payload)

    assert response.status_code == 422


def test_workspace_draft_action_adds_trade_and_reevaluates_stateless_workspace():
    create_payload = {
        "workspace_name": "Sandbox drift review",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "snapshot_id": "ps_001",
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "snapshot_id": "md_001",
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        create_response = client.post("/advisory/workspaces", json=create_payload)
        workspace_id = create_response.json()["workspace"]["workspace_id"]

        action_response = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_TRADE",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_1",
                    "quantity": "2",
                },
            },
        )

    assert action_response.status_code == 200
    body = action_response.json()
    assert len(body["workspace"]["draft_state"]["trade_drafts"]) == 1
    assert body["workspace"]["evaluation_summary"]["status"] == "READY"
    assert body["workspace"]["evaluation_summary"]["impact_summary"]["trade_count"] == 1
    assert body["workspace"]["latest_proposal_result"]["status"] == "READY"


def test_workspace_draft_action_updates_and_removes_trade():
    create_payload = {
        "workspace_name": "Sandbox drift review",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        add_body = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_TRADE",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_1",
                    "quantity": "2",
                },
            },
        ).json()
        trade_id = add_body["workspace"]["draft_state"]["trade_drafts"][0]["workspace_trade_id"]

        update_response = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "UPDATE_TRADE",
                "workspace_trade_id": trade_id,
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_1",
                    "quantity": "3",
                },
            },
        )
        remove_response = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "REMOVE_TRADE",
                "workspace_trade_id": trade_id,
            },
        )

    assert update_response.status_code == 200
    assert (
        update_response.json()["workspace"]["draft_state"]["trade_drafts"][0]["trade"]["quantity"]
        == "3"
    )
    assert remove_response.status_code == 200
    assert remove_response.json()["workspace"]["draft_state"]["trade_drafts"] == []


def test_workspace_draft_action_updates_and_removes_cash_flow():
    create_payload = {
        "workspace_name": "Sandbox funding review",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [],
                    "fx_rates": [],
                },
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        add_body = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_CASH_FLOW",
                "cash_flow": {
                    "direction": "CONTRIBUTION",
                    "amount": "2500",
                    "currency": "USD",
                },
            },
        ).json()
        cash_flow_id = add_body["workspace"]["draft_state"]["cash_flow_drafts"][0][
            "workspace_cash_flow_id"
        ]

        update_response = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "UPDATE_CASH_FLOW",
                "workspace_cash_flow_id": cash_flow_id,
                "cash_flow": {
                    "direction": "CONTRIBUTION",
                    "amount": "3000",
                    "currency": "USD",
                },
            },
        )
        remove_response = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "REMOVE_CASH_FLOW",
                "workspace_cash_flow_id": cash_flow_id,
            },
        )

    assert update_response.status_code == 200
    assert (
        update_response.json()["workspace"]["draft_state"]["cash_flow_drafts"][0]["cash_flow"][
            "amount"
        ]
        == "3000"
    )
    assert (
        update_response.json()["workspace"]["evaluation_summary"]["impact_summary"][
            "cash_flow_count"
        ]
        == 1
    )
    assert remove_response.status_code == 200
    assert remove_response.json()["workspace"]["draft_state"]["cash_flow_drafts"] == []


def test_workspace_get_returns_latest_workspace_state_after_mutation():
    create_payload = {
        "workspace_name": "Sandbox drift review",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_TRADE",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_1",
                    "quantity": "2",
                },
            },
        )
        get_response = client.get(f"/advisory/workspaces/{workspace_id}")

    assert get_response.status_code == 200
    body = get_response.json()
    assert len(body["draft_state"]["trade_drafts"]) == 1
    assert body["evaluation_summary"]["impact_summary"]["trade_count"] == 1


def test_workspace_evaluate_reruns_stateless_workspace_successfully():
    create_payload = {
        "workspace_name": "Sandbox drift review",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_TRADE",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_1",
                    "quantity": "2",
                },
            },
        )
        response = client.post(f"/advisory/workspaces/{workspace_id}/evaluate")

    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_summary"]["status"] == "READY"
    assert body["latest_proposal_result"]["status"] == "READY"


def test_stateless_workspace_evaluate_matches_direct_simulation_for_equivalent_input():
    simulate_request = {
        "portfolio_snapshot": {
            "snapshot_id": "ps_parity_001",
            "portfolio_id": "pf_parity_001",
            "base_currency": "USD",
            "positions": [{"instrument_id": "EQ_OLD", "quantity": "10"}],
            "cash_balances": [{"currency": "USD", "amount": "10000"}],
        },
        "market_data_snapshot": {
            "snapshot_id": "md_parity_001",
            "prices": [
                {"instrument_id": "EQ_OLD", "price": "100", "currency": "USD"},
                {"instrument_id": "EQ_NEW", "price": "50", "currency": "USD"},
            ],
            "fx_rates": [],
        },
        "shelf_entries": [
            {"instrument_id": "EQ_OLD", "status": "APPROVED"},
            {"instrument_id": "EQ_NEW", "status": "APPROVED"},
        ],
        "options": {
            "enable_proposal_simulation": True,
            "enable_workflow_gates": True,
            "enable_suitability_scanner": True,
        },
        "proposed_cash_flows": [{"direction": "CONTRIBUTION", "amount": "250", "currency": "USD"}],
        "proposed_trades": [
            {
                "intent_type": "SECURITY_TRADE",
                "side": "BUY",
                "instrument_id": "EQ_NEW",
                "quantity": "4",
            }
        ],
    }
    create_payload = {
        "workspace_name": "Parity workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {"simulate_request": simulate_request},
    }

    with TestClient(app) as client:
        simulate_response = client.post(
            "/advisory/proposals/simulate",
            json=simulate_request,
            headers={"Idempotency-Key": "parity-simulate-001"},
        )
        assert simulate_response.status_code == 200

        workspace_create_response = client.post("/advisory/workspaces", json=create_payload)
        assert workspace_create_response.status_code == 201
        workspace_id = workspace_create_response.json()["workspace"]["workspace_id"]

        workspace_evaluate_response = client.post(f"/advisory/workspaces/{workspace_id}/evaluate")
        assert workspace_evaluate_response.status_code == 200

    direct_result = _normalize_proposal_result_for_parity(simulate_response.json())
    workspace_result = _normalize_proposal_result_for_parity(
        workspace_evaluate_response.json()["latest_proposal_result"]
    )

    assert workspace_result == direct_result


def test_workspace_evaluate_uses_stateful_context_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    create_payload = {
        "workspace_name": "Q2 2026 growth reallocation draft",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_advisory_01",
            "household_id": "hh_001",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(f"/advisory/workspaces/{workspace_id}/evaluate")

    assert response.status_code == 200
    assert response.json()["evaluation_summary"]["status"] == "READY"
    assert response.json()["resolved_context"]["portfolio_snapshot_id"] == (
        "ps_pf_advisory_01_2026-03-25"
    )


def test_workspace_evaluate_rejects_missing_resolved_context() -> None:
    create_payload = {
        "workspace_name": "Broken workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_missing_context",
                    "base_currency": "USD",
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]

    session = get_workspace_session(workspace_id)
    session.resolved_context = None

    with pytest.raises(WorkspaceEvaluationUnavailableError) as exc:
        reevaluate_workspace_session(workspace_id)

    assert str(exc.value) == "WORKSPACE_RESOLVED_CONTEXT_MISSING"


def test_workspace_service_redacts_sensitive_evaluation_context_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_payload = {
        "workspace_name": "Sensitive context failure workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_sensitive_context",
                    "base_currency": "USD",
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]

    def _raise_sensitive_context_error(**_kwargs: Any) -> None:
        raise workspace_evaluator_module.WorkspaceReevaluationContextError(
            "raw payload includes Authorization Bearer token material"
        )

    monkeypatch.setattr(
        workspace_evaluator_module,
        "build_workspace_evaluation_context",
        _raise_sensitive_context_error,
    )

    with pytest.raises(WorkspaceEvaluationUnavailableError) as exc:
        reevaluate_workspace_session(workspace_id)

    assert str(exc.value) == "WORKSPACE_EVALUATION_UNAVAILABLE"
    assert "token" not in str(exc.value).lower()


def test_workspace_endpoints_return_404_for_missing_workspace():
    with TestClient(app) as client:
        get_response = client.get("/advisory/workspaces/aws_missing")
        evaluate_response = client.post("/advisory/workspaces/aws_missing/evaluate")
        save_response = client.post(
            "/advisory/workspaces/aws_missing/save",
            json={"saved_by": "advisor_123"},
        )
        list_response = client.get("/advisory/workspaces/aws_missing/saved-versions")
        handoff_response = client.post(
            "/advisory/workspaces/aws_missing/handoff",
            headers={"Idempotency-Key": "workspace-handoff-idem-missing"},
            json={"handoff_by": "advisor_123"},
        )

    assert get_response.status_code == 404
    assert evaluate_response.status_code == 404
    assert save_response.status_code == 404
    assert list_response.status_code == 404
    assert handoff_response.status_code == 404


def test_workspace_not_found_route_errors_redact_sensitive_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_sensitive_not_found(_workspace_id: str):
        raise WorkspaceNotFoundError("Authorization Bearer token leaked from upstream")

    app.dependency_overrides[get_workspace_application_service_dependency] = lambda: (
        SimpleNamespace(
            get_session=_raise_sensitive_not_found,
        )
    )

    try:
        with TestClient(app) as client:
            response = client.get("/advisory/workspaces/aws_sensitive")
    finally:
        app.dependency_overrides.pop(get_workspace_application_service_dependency, None)

    assert response.status_code == 404
    assert response.json()["detail"] == "WORKSPACE_NOT_FOUND"


def test_workspace_conflict_route_errors_redact_sensitive_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_sensitive_conflict(_workspace_id: str):
        raise WorkspaceEvaluationUnavailableError("raw payload includes secret advisor context")

    app.dependency_overrides[get_workspace_application_service_dependency] = lambda: (
        SimpleNamespace(
            reevaluate_session=_raise_sensitive_conflict,
        )
    )

    try:
        with TestClient(app) as client:
            response = client.post("/advisory/workspaces/aws_sensitive/evaluate")
    finally:
        app.dependency_overrides.pop(get_workspace_application_service_dependency, None)

    assert response.status_code == 409
    assert response.json()["detail"] == "WORKSPACE_CONFLICT"


def test_workspace_assistant_route_errors_redact_sensitive_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_sensitive_assistant_error(_workspace_id: str, _request):
        raise WorkspaceAssistantUnavailableError("provider response included api_key material")

    monkeypatch.setattr(
        workspace_routes_assistant,
        "generate_workspace_rationale",
        _raise_sensitive_assistant_error,
    )

    with TestClient(app) as client:
        response = client.post(
            "/advisory/workspaces/aws_sensitive/assistant/rationale",
            json={
                "requested_by": "advisor_123",
                "instruction": "Summarize the workspace rationale for review.",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "WORKSPACE_ASSISTANT_UNAVAILABLE"


def test_workspace_draft_action_not_found_paths_return_404():
    create_payload = {
        "workspace_name": "Sandbox drift review",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        update_trade = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "UPDATE_TRADE",
                "workspace_trade_id": "wtd_missing",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_1",
                    "quantity": "1",
                },
            },
        )
        remove_cash_flow = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "REMOVE_CASH_FLOW",
                "workspace_cash_flow_id": "wcf_missing",
            },
        )

    assert update_trade.status_code == 404
    assert update_trade.json()["detail"] == "WORKSPACE_TRADE_NOT_FOUND"
    assert remove_cash_flow.status_code == 404
    assert remove_cash_flow.json()["detail"] == "WORKSPACE_CASH_FLOW_NOT_FOUND"


def test_workspace_draft_action_replace_options_rejects_stateful_workspace_without_resolution():
    create_payload = {
        "workspace_name": "Q2 2026 growth reallocation draft",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_advisory_01",
            "household_id": "hh_001",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "REPLACE_OPTIONS",
                "options": {"enable_proposal_simulation": True, "auto_funding": False},
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "WORKSPACE_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"


def test_workspace_stateful_evaluate_does_not_use_local_fallback_for_context_resolution(
    monkeypatch,
):
    monkeypatch.setenv("LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK", "true")
    create_payload = {
        "workspace_name": "Fallback should not bypass stateful context",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_missing_stateful_workspace",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as client:
        created = client.post("/advisory/workspaces", json=create_payload)
        assert created.status_code == 201
        workspace_id = created.json()["workspace"]["workspace_id"]
        response = client.post(f"/advisory/workspaces/{workspace_id}/evaluate")

    assert response.status_code == 409
    assert response.json()["detail"] == "WORKSPACE_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"


def test_workspace_draft_action_replace_options_uses_stateful_context_resolution(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    create_payload = {
        "workspace_name": "Q2 2026 growth reallocation draft",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_advisory_01",
            "household_id": "hh_001",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "REPLACE_OPTIONS",
                "options": {"enable_proposal_simulation": True, "auto_funding": False},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["workspace"]["draft_state"]["options"]["auto_funding"] is False
    assert body["workspace"]["resolved_context"]["portfolio_snapshot_id"] == (
        "ps_pf_advisory_01_2026-03-25"
    )


def test_stateful_workspace_draft_action_applies_trade_drafts_to_evaluation(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context_with_tradeable_universe(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    create_payload = {
        "workspace_name": "Stateful trade draft workspace",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_tradeable_001",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_TRADE",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_NEW",
                    "quantity": "4",
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["workspace"]["evaluation_summary"]["impact_summary"]["trade_count"] == 1
    assert body["workspace"]["latest_proposal_result"]["status"] == "READY"
    assert body["workspace"]["latest_proposal_result"]["intents"][-1]["instrument_id"] == "EQ_NEW"
    assert (
        body["workspace"]["latest_proposal_result"]["explanation"]["context_resolution"][
            "input_mode"
        ]
        == "stateful"
    )


def test_stateful_workspace_evaluate_matches_direct_simulation_for_equivalent_input(
    monkeypatch,
) -> None:
    resolved = _resolved_stateful_context_with_tradeable_universe(
        portfolio_id="pf_stateful_parity_001",
        as_of="2026-03-25",
    )
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: resolved,
        raising=False,
    )
    direct_payload = resolved["simulate_request"] | {
        "proposed_trades": [
            {
                "intent_type": "SECURITY_TRADE",
                "side": "BUY",
                "instrument_id": "EQ_NEW",
                "quantity": "4",
            }
        ]
    }
    create_payload = {
        "workspace_name": "Stateful parity workspace",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_parity_001",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as client:
        direct_response = client.post(
            "/advisory/proposals/simulate",
            json=direct_payload,
            headers={"Idempotency-Key": "stateful-parity-direct-001"},
        )
        assert direct_response.status_code == 200

        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        draft_action = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_TRADE",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_NEW",
                    "quantity": "4",
                },
            },
        )
        assert draft_action.status_code == 200
        workspace_response = client.post(f"/advisory/workspaces/{workspace_id}/evaluate")
        assert workspace_response.status_code == 200

    assert _normalize_business_result_for_cross_mode_parity(
        workspace_response.json()["latest_proposal_result"]
    ) == (_normalize_business_result_for_cross_mode_parity(direct_response.json()))

    direct_valuation_context = direct_response.json()["valuation_context"]
    workspace_valuation_context = workspace_response.json()["latest_proposal_result"][
        "valuation_context"
    ]
    assert direct_valuation_context["current_state"]["requested_as_of_date"] is None
    assert direct_valuation_context["current_state"]["effective_as_of_date"] is None
    assert workspace_valuation_context["current_state"]["requested_as_of_date"] == "2026-03-25"
    assert direct_valuation_context["current_state"]["requested_reporting_currency"] is None
    assert workspace_valuation_context["current_state"]["requested_reporting_currency"] is None
    assert direct_valuation_context["current_state"]["supportability"] == "PARTIAL"
    assert workspace_valuation_context["current_state"]["supportability"] == "PARTIAL"


def test_stateful_workspace_handoff_uses_current_draft_state(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context_with_tradeable_universe(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    create_payload = {
        "workspace_name": "Stateful handoff workspace",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_handoff_001",
            "as_of": "2026-03-25",
            "mandate_id": "mandate_stateful_001",
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        add_trade = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_TRADE",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_NEW",
                    "quantity": "4",
                },
            },
        )
        assert add_trade.status_code == 200

        handoff = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            headers={"Idempotency-Key": "stateful-workspace-handoff-001"},
            json={"handoff_by": "advisor_123"},
        )

    assert handoff.status_code == 200
    handoff_body = handoff.json()["proposal"]
    proposal_result = handoff_body["version"]["proposal_result"]
    assert proposal_result["status"] == "READY"
    assert proposal_result["intents"][-1]["instrument_id"] == "EQ_NEW"
    assert handoff_body["proposal"]["mandate_id"] == "mandate_stateful_001"


def test_stateful_workspace_enriches_missing_trade_instruments_from_lotus_core(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class _FakeClient:
        def __init__(self, responses):
            self._responses = responses

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def request(self, method, url, json=None):
            key = (method.upper(), url)
            if key not in self._responses:
                raise AssertionError(f"unexpected request: {key}")
            return self._responses[key]

    base_url = "http://core-query.dev.lotus"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", base_url)
    responses = {
        ("POST", f"{base_url}/integration/instruments/enrichment-bulk"): _FakeResponse(
            {
                "records": [
                    {
                        "security_id": "EQ_NEW",
                        "asset_class": "Equity",
                        "sector": "Technology",
                        "country_of_risk": "US",
                        "product_type": "Equity",
                        "rating": None,
                        "issuer_id": "ISSUER_EQ_NEW",
                        "issuer_name": "New Issuer",
                        "ultimate_parent_issuer_id": "ISSUER_EQ_PARENT",
                        "ultimate_parent_issuer_name": "Parent Issuer",
                        "liquidity_tier": "L1",
                    }
                ]
            }
        ),
        ("GET", f"{base_url}/instruments/?security_id=EQ_NEW"): _FakeResponse(
            {
                "total": 1,
                "instruments": [
                    {
                        "security_id": "EQ_NEW",
                        "currency": "USD",
                        "asset_class": "Equity",
                    }
                ],
            }
        ),
        ("GET", f"{base_url}/prices/?security_id=EQ_NEW"): _FakeResponse(
            {
                "security_id": "EQ_NEW",
                "prices": [
                    {"price_date": "2026-03-25", "price": "50", "currency": "USD"},
                ],
            }
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    create_payload = {
        "workspace_name": "Stateful enrichment workspace",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_enrichment_001",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_TRADE",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_NEW",
                    "quantity": "4",
                },
            },
        )

    assert response.status_code == 200
    latest_proposal_result = response.json()["workspace"]["latest_proposal_result"]
    assert latest_proposal_result["status"] == "READY"
    assert latest_proposal_result["intents"][-1]["instrument_id"] == "EQ_NEW"


def test_workspace_save_list_resume_and_compare_saved_versions():
    create_payload = {
        "workspace_name": "Sandbox compare review",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        initial_action = client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_TRADE",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_1",
                    "quantity": "2",
                },
            },
        ).json()
        save_response = client.post(
            f"/advisory/workspaces/{workspace_id}/save",
            json={"saved_by": "advisor_123", "version_label": "Initial sandbox draft"},
        )
        saved_version_id = save_response.json()["saved_version"]["workspace_version_id"]
        client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_CASH_FLOW",
                "cash_flow": {
                    "direction": "CONTRIBUTION",
                    "amount": "3000",
                    "currency": "USD",
                },
            },
        )
        compare_response = client.post(
            f"/advisory/workspaces/{workspace_id}/compare",
            json={"workspace_version_id": saved_version_id},
        )
        list_response = client.get(f"/advisory/workspaces/{workspace_id}/saved-versions")
        resume_response = client.post(
            f"/advisory/workspaces/{workspace_id}/resume",
            json={"actor_id": "advisor_123", "workspace_version_id": saved_version_id},
        )

    assert initial_action["workspace"]["evaluation_summary"]["impact_summary"]["trade_count"] == 1
    assert save_response.status_code == 200
    assert save_response.json()["workspace"]["saved_version_count"] == 1
    assert (
        save_response.json()["workspace"]["latest_saved_version"]["version_label"]
        == "Initial sandbox draft"
    )
    assert save_response.json()["saved_version"]["replay_evidence"]["evaluation_request_hash"]
    assert compare_response.status_code == 200
    assert compare_response.json()["diff_summary"]["trade_count_delta"] == 0
    assert compare_response.json()["diff_summary"]["cash_flow_count_delta"] == 1
    assert list_response.status_code == 200
    assert len(list_response.json()["saved_versions"]) == 1
    assert list_response.json()["saved_versions"][0]["workspace_version_id"] == saved_version_id
    assert resume_response.status_code == 200
    assert resume_response.json()["draft_state"]["cash_flow_drafts"] == []
    assert resume_response.json()["evaluation_summary"]["impact_summary"]["trade_count"] == 1


def test_workspace_resume_and_compare_missing_saved_version_return_404():
    create_payload = {
        "workspace_name": "Sandbox compare review",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        resume_response = client.post(
            f"/advisory/workspaces/{workspace_id}/resume",
            json={"actor_id": "advisor_123", "workspace_version_id": "awv_missing"},
        )
        compare_response = client.post(
            f"/advisory/workspaces/{workspace_id}/compare",
            json={"workspace_version_id": "awv_missing"},
        )

    assert resume_response.status_code == 404
    assert resume_response.json()["detail"] == "WORKSPACE_SAVED_VERSION_NOT_FOUND"
    assert compare_response.status_code == 404
    assert compare_response.json()["detail"] == "WORKSPACE_SAVED_VERSION_NOT_FOUND"


def test_workspace_resume_and_compare_missing_workspace_return_404():
    with TestClient(app) as client:
        resume_response = client.post(
            "/advisory/workspaces/aws_missing/resume",
            json={"actor_id": "advisor_123", "workspace_version_id": "awv_001"},
        )
        compare_response = client.post(
            "/advisory/workspaces/aws_missing/compare",
            json={"workspace_version_id": "awv_001"},
        )

    assert resume_response.status_code == 404
    assert compare_response.status_code == 404


def test_workspace_handoff_creates_proposal_then_new_version_without_duplicating_lifecycle():
    create_payload = {
        "workspace_name": "Growth rotation workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_TRADE",
                "trade": {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_1",
                    "quantity": "2",
                },
            },
        )
        first_handoff = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            headers={"Idempotency-Key": "  workspace-handoff-idem-001  "},
            json={
                "handoff_by": "advisor_123",
                "metadata": {
                    "title": "Q2 2026 growth reallocation proposal",
                    "jurisdiction": "SG",
                    "mandate_id": "mandate_growth_01",
                },
            },
        )
        client.post(
            f"/advisory/workspaces/{workspace_id}/draft-actions",
            json={
                "actor_id": "advisor_123",
                "action_type": "ADD_CASH_FLOW",
                "cash_flow": {
                    "direction": "CONTRIBUTION",
                    "amount": "1500",
                    "currency": "USD",
                },
            },
        )
        second_handoff = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            json={"handoff_by": "advisor_123"},
        )

    assert first_handoff.status_code == 200
    first_body = first_handoff.json()
    assert first_body["handoff_action"] == "CREATED_PROPOSAL"
    proposal_id = first_body["proposal"]["proposal"]["proposal_id"]
    assert first_body["proposal"]["proposal"]["lifecycle_origin"] == "WORKSPACE_HANDOFF"
    assert first_body["proposal"]["proposal"]["source_workspace_id"] == workspace_id
    assert first_body["workspace"]["lifecycle_link"]["proposal_id"] == proposal_id
    assert first_body["proposal"]["version"]["version_no"] == 1
    assert (
        first_body["proposal"]["version"]["proposal_result"]["lineage"]["idempotency_key"]
        == "workspace-handoff-idem-001"
    )

    assert second_handoff.status_code == 200
    second_body = second_handoff.json()
    assert second_body["handoff_action"] == "CREATED_PROPOSAL_VERSION"
    assert second_body["proposal"]["proposal"]["proposal_id"] == proposal_id
    assert second_body["proposal"]["proposal"]["lifecycle_origin"] == "WORKSPACE_HANDOFF"
    assert second_body["proposal"]["proposal"]["source_workspace_id"] == workspace_id
    assert second_body["proposal"]["version"]["version_no"] == 2
    assert second_body["workspace"]["lifecycle_link"]["current_version_no"] == 2


def test_workspace_saved_version_replay_evidence_preserves_handoff_continuity():
    payload = {
        "workspace_name": "Replay continuity workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_replay_workspace_001",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        created = client.post("/advisory/workspaces", json=payload)
        workspace_id = created.json()["workspace"]["workspace_id"]
        evaluated = client.post(f"/advisory/workspaces/{workspace_id}/evaluate")
        assert evaluated.status_code == 200
        saved = client.post(
            f"/advisory/workspaces/{workspace_id}/save",
            json={"saved_by": "advisor_123", "version_label": "Replay baseline"},
        )
        assert saved.status_code == 200
        workspace_version_id = saved.json()["saved_version"]["workspace_version_id"]

        handoff = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            headers={"Idempotency-Key": "workspace-replay-handoff-001"},
            json={"handoff_by": "advisor_123"},
        )
        assert handoff.status_code == 200
        proposal_id = handoff.json()["proposal"]["proposal"]["proposal_id"]
        proposal_version_no = handoff.json()["proposal"]["version"]["version_no"]

        replay = client.get(
            f"/advisory/workspaces/{workspace_id}/saved-versions/{workspace_version_id}/replay-evidence"
        )

    assert replay.status_code == 200
    body = replay.json()
    assert body["subject"]["scope"] == "WORKSPACE_SAVED_VERSION"
    assert body["subject"]["workspace_id"] == workspace_id
    assert body["subject"]["workspace_version_id"] == workspace_version_id
    assert body["subject"]["proposal_id"] == proposal_id
    assert body["subject"]["proposal_version_no"] == proposal_version_no
    assert body["continuity"]["handoff_action"] == "CREATED_PROPOSAL"
    assert body["hashes"]["draft_state_hash"]
    assert body["hashes"]["evaluation_request_hash"]
    assert body["evidence"]["proposal_decision_summary"]["decision_status"]


def test_workspace_and_proposal_replay_evidence_stay_hash_aligned_after_handoff():
    payload = {
        "workspace_name": "Replay alignment workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_replay_alignment_001",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [{"side": "BUY", "instrument_id": "EQ_1", "quantity": "2"}],
            }
        },
    }

    with TestClient(app) as client:
        created = client.post("/advisory/workspaces", json=payload)
        workspace_id = created.json()["workspace"]["workspace_id"]
        evaluated = client.post(f"/advisory/workspaces/{workspace_id}/evaluate")
        assert evaluated.status_code == 200
        saved = client.post(
            f"/advisory/workspaces/{workspace_id}/save",
            json={"saved_by": "advisor_123", "version_label": "Replay alignment baseline"},
        )
        assert saved.status_code == 200
        workspace_version_id = saved.json()["saved_version"]["workspace_version_id"]

        handoff = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            headers={"Idempotency-Key": "workspace-replay-alignment-001"},
            json={"handoff_by": "advisor_123"},
        )
        assert handoff.status_code == 200
        proposal_id = handoff.json()["proposal"]["proposal"]["proposal_id"]
        proposal_version_no = handoff.json()["proposal"]["version"]["version_no"]

        workspace_replay = client.get(
            f"/advisory/workspaces/{workspace_id}/saved-versions/{workspace_version_id}/replay-evidence"
        )
        proposal_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{proposal_version_no}/replay-evidence"
        )

    assert workspace_replay.status_code == 200
    assert proposal_replay.status_code == 200
    workspace_body = workspace_replay.json()
    proposal_body = proposal_replay.json()
    assert proposal_body["subject"]["workspace_id"] == workspace_id
    assert proposal_body["subject"]["workspace_version_id"] == workspace_version_id
    assert (
        proposal_body["hashes"]["evaluation_request_hash"]
        == (workspace_body["hashes"]["evaluation_request_hash"])
    )
    assert (
        proposal_body["hashes"]["draft_state_hash"]
        == (workspace_body["hashes"]["draft_state_hash"])
    )
    assert proposal_body["continuity"]["workspace_version_id"] == workspace_version_id
    assert (
        proposal_body["continuity"]["handoff_action"]
        == (workspace_body["continuity"]["handoff_action"])
    )
    assert (
        proposal_body["resolved_context"]["portfolio_id"]
        == (workspace_body["resolved_context"]["portfolio_id"])
    )
    assert (
        proposal_body["evidence"]["proposal_decision_summary"]
        == workspace_body["evidence"]["proposal_decision_summary"]
    )


def test_workspace_save_resume_handoff_and_replay_preserve_proposal_alternatives_selection(
    monkeypatch,
):
    monkeypatch.setattr(
        "src.core.advisory.orchestration.enrich_with_lotus_risk",
        lambda **kwargs: _risk_enriched_result(kwargs["proposal_result"]),
    )
    payload = {
        "workspace_name": "Alternatives continuity workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_workspace_alt_001",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_NEW", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_NEW", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [{"side": "BUY", "instrument_id": "EQ_NEW", "quantity": "2"}],
                "alternatives_request": {
                    "enabled": True,
                    "objectives": ["LOWER_TURNOVER"],
                    "selected_alternative_id": "alt_lower_turnover_pf_workspace_alt_001_eq_new",
                    "include_rejected_candidates": True,
                },
            }
        },
    }

    with TestClient(app) as client:
        created = client.post("/advisory/workspaces", json=payload)
        assert created.status_code == 201
        workspace_id = created.json()["workspace"]["workspace_id"]

        evaluated = client.post(f"/advisory/workspaces/{workspace_id}/evaluate")
        assert evaluated.status_code == 200
        evaluated_body = evaluated.json()
        assert (
            evaluated_body["latest_proposal_result"]["proposal_alternatives"][
                "selected_alternative_id"
            ]
            == "alt_lower_turnover_pf_workspace_alt_001_eq_new"
        )
        assert (
            evaluated_body["draft_state"]["alternatives_request"]["selected_alternative_id"]
            == "alt_lower_turnover_pf_workspace_alt_001_eq_new"
        )

        saved = client.post(
            f"/advisory/workspaces/{workspace_id}/save",
            json={"saved_by": "advisor_123", "version_label": "Alternatives baseline"},
        )
        assert saved.status_code == 200
        workspace_version_id = saved.json()["saved_version"]["workspace_version_id"]
        assert (
            saved.json()["saved_version"]["latest_proposal_result"]["proposal_alternatives"][
                "selected_alternative_id"
            ]
            == "alt_lower_turnover_pf_workspace_alt_001_eq_new"
        )

        resumed = client.post(
            f"/advisory/workspaces/{workspace_id}/resume",
            json={"actor_id": "advisor_123", "workspace_version_id": workspace_version_id},
        )
        assert resumed.status_code == 200
        assert (
            resumed.json()["draft_state"]["alternatives_request"]["selected_alternative_id"]
            == "alt_lower_turnover_pf_workspace_alt_001_eq_new"
        )

        handoff = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            headers={"Idempotency-Key": "workspace-alt-handoff-001"},
            json={"handoff_by": "advisor_123"},
        )
        assert handoff.status_code == 200
        handoff_body = handoff.json()
        proposal_id = handoff_body["proposal"]["proposal"]["proposal_id"]
        proposal_version_no = handoff_body["proposal"]["version"]["version_no"]
        assert (
            handoff_body["proposal"]["version"]["proposal_result"]["proposal_alternatives"][
                "selected_alternative_id"
            ]
            == "alt_lower_turnover_pf_workspace_alt_001_eq_new"
        )
        assert (
            handoff_body["proposal"]["version"]["artifact"]["proposal_alternatives"][
                "selected_alternative_id"
            ]
            == "alt_lower_turnover_pf_workspace_alt_001_eq_new"
        )

        workspace_replay = client.get(
            f"/advisory/workspaces/{workspace_id}/saved-versions/{workspace_version_id}/replay-evidence"
        )
        proposal_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{proposal_version_no}/replay-evidence"
        )

    assert workspace_replay.status_code == 200
    assert proposal_replay.status_code == 200
    assert (
        workspace_replay.json()["evidence"]["proposal_alternatives"]["selected_alternative_id"]
        == "alt_lower_turnover_pf_workspace_alt_001_eq_new"
    )
    assert (
        proposal_replay.json()["evidence"]["proposal_alternatives"]["selected_alternative_id"]
        == "alt_lower_turnover_pf_workspace_alt_001_eq_new"
    )


def test_workspace_handoff_replay_evidence_preserves_risk_lens(monkeypatch):
    monkeypatch.setattr(
        "src.core.advisory.orchestration.enrich_with_lotus_risk",
        lambda **kwargs: _risk_enriched_result(kwargs["proposal_result"]),
    )
    payload = {
        "workspace_name": "Risk lens handoff workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_workspace_risk_replay_001",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [{"side": "BUY", "instrument_id": "EQ_1", "quantity": "2"}],
            }
        },
    }

    with TestClient(app) as client:
        created = client.post("/advisory/workspaces", json=payload)
        workspace_id = created.json()["workspace"]["workspace_id"]
        client.post(f"/advisory/workspaces/{workspace_id}/evaluate")
        saved = client.post(
            f"/advisory/workspaces/{workspace_id}/save",
            json={"saved_by": "advisor_123", "version_label": "Risk lens baseline"},
        )
        workspace_version_id = saved.json()["saved_version"]["workspace_version_id"]
        handoff = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            headers={"Idempotency-Key": "workspace-risk-lens-handoff-001"},
            json={"handoff_by": "advisor_123"},
        )
        proposal_id = handoff.json()["proposal"]["proposal"]["proposal_id"]
        proposal_version_no = handoff.json()["proposal"]["version"]["version_no"]
        workspace_replay = client.get(
            f"/advisory/workspaces/{workspace_id}/saved-versions/{workspace_version_id}/replay-evidence"
        )
        proposal_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{proposal_version_no}/replay-evidence"
        )

    assert workspace_replay.status_code == 200
    assert proposal_replay.status_code == 200
    workspace_body = workspace_replay.json()
    proposal_body = proposal_replay.json()
    assert workspace_body["evidence"]["risk_lens"]["source_service"] == "lotus-risk"
    assert proposal_body["evidence"]["risk_lens"]["source_service"] == "lotus-risk"
    assert workspace_body["evidence"]["risk_lens"]["risk_proxy"]["hhi_delta"] == 1600.0
    assert proposal_body["evidence"]["risk_lens"]["risk_proxy"]["hhi_delta"] == 1600.0
    assert (
        workspace_body["evidence"]["proposal_decision_summary"]["risk_posture"]["status"]
        == "AVAILABLE"
    )
    assert (
        proposal_body["evidence"]["proposal_decision_summary"]["risk_posture"]["status"]
        == "AVAILABLE"
    )


def test_workspace_handoff_requires_idempotency_key_for_first_create():
    create_payload = {
        "workspace_name": "Growth rotation workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            json={"handoff_by": "advisor_123"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "WORKSPACE_HANDOFF_IDEMPOTENCY_KEY_REQUIRED"


def test_workspace_handoff_uses_stateful_context_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    create_payload = {
        "workspace_name": "Q2 2026 growth reallocation draft",
        "created_by": "advisor_123",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_advisory_01",
            "household_id": "hh_001",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            headers={"Idempotency-Key": "workspace-handoff-idem-002"},
            json={"handoff_by": "advisor_123"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"]["proposal"]["lifecycle_origin"] == "WORKSPACE_HANDOFF"
    assert body["workspace"]["resolved_context"]["portfolio_snapshot_id"] == (
        "ps_pf_advisory_01_2026-03-25"
    )
    context_resolution = body["proposal"]["version"]["evidence_bundle"]["context_resolution"]
    assert context_resolution["input_mode"] == "stateful"
    assert context_resolution["resolution_source"] == "LOTUS_CORE"
    assert context_resolution["resolved_context"]["as_of"] == "2026-03-25"
    assert context_resolution["resolved_context"]["portfolio_snapshot_id"] == (
        "ps_pf_advisory_01_2026-03-25"
    )


def test_stateless_workspace_handoff_matches_direct_proposal_create_for_equivalent_input():
    simulate_request = {
        "portfolio_snapshot": {
            "snapshot_id": "ps_handoff_parity_001",
            "portfolio_id": "pf_handoff_parity_001",
            "base_currency": "USD",
            "positions": [{"instrument_id": "EQ_OLD", "quantity": "10"}],
            "cash_balances": [{"currency": "USD", "amount": "10000"}],
        },
        "market_data_snapshot": {
            "snapshot_id": "md_handoff_parity_001",
            "prices": [
                {"instrument_id": "EQ_OLD", "price": "100", "currency": "USD"},
                {"instrument_id": "EQ_NEW", "price": "50", "currency": "USD"},
            ],
            "fx_rates": [],
        },
        "shelf_entries": [
            {"instrument_id": "EQ_OLD", "status": "APPROVED"},
            {"instrument_id": "EQ_NEW", "status": "APPROVED"},
        ],
        "options": {
            "enable_proposal_simulation": True,
            "enable_workflow_gates": True,
            "enable_suitability_scanner": True,
        },
        "proposed_cash_flows": [{"direction": "CONTRIBUTION", "amount": "250", "currency": "USD"}],
        "proposed_trades": [
            {
                "intent_type": "SECURITY_TRADE",
                "side": "BUY",
                "instrument_id": "EQ_NEW",
                "quantity": "4",
            }
        ],
    }
    metadata = {
        "title": "Parity handoff proposal",
        "advisor_notes": "Workspace and lifecycle create should match.",
        "jurisdiction": "SG",
        "mandate_id": "mandate_parity_001",
    }
    direct_create_payload = {
        "created_by": "advisor_123",
        "simulate_request": simulate_request,
        "metadata": metadata,
    }
    workspace_create_payload = {
        "workspace_name": "Parity handoff workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {"simulate_request": simulate_request},
    }

    with TestClient(app) as client:
        direct_create_response = client.post(
            "/advisory/proposals",
            json=direct_create_payload,
            headers={"Idempotency-Key": "parity-direct-create-001"},
        )
        assert direct_create_response.status_code == 200

        workspace_create_response = client.post(
            "/advisory/workspaces",
            json=workspace_create_payload,
        )
        assert workspace_create_response.status_code == 201
        workspace_id = workspace_create_response.json()["workspace"]["workspace_id"]

        workspace_handoff_response = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            headers={"Idempotency-Key": "parity-workspace-handoff-001"},
            json={"handoff_by": "advisor_123", "metadata": metadata},
        )
        assert workspace_handoff_response.status_code == 200

    direct_body = direct_create_response.json()
    handoff_body = workspace_handoff_response.json()["proposal"]

    assert _normalize_created_version_result_for_parity(handoff_body) == (
        _normalize_created_version_result_for_parity(direct_body)
    )
    assert handoff_body["version"]["request_hash"] == direct_body["version"]["request_hash"]
    assert handoff_body["version"]["simulation_hash"] == direct_body["version"]["simulation_hash"]
    assert handoff_body["version"]["artifact_hash"].startswith("sha256:")
    assert direct_body["version"]["artifact_hash"].startswith("sha256:")
    assert handoff_body["proposal"]["portfolio_id"] == direct_body["proposal"]["portfolio_id"]
    assert handoff_body["proposal"]["current_version_no"] == 1
    assert handoff_body["proposal"]["lifecycle_origin"] == "WORKSPACE_HANDOFF"


def test_workspace_handoff_returns_422_when_proposal_simulation_flag_is_disabled():
    create_payload = {
        "workspace_name": "Growth rotation workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_advisory_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": False},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/handoff",
            headers={"Idempotency-Key": "workspace-handoff-idem-003"},
            json={"handoff_by": "advisor_123"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "PROPOSAL_SIMULATION_DISABLED: set options.enable_proposal_simulation=true"
    )


class _FakeLotusAIResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeLotusAIClient:
    def __init__(
        self,
        *args,
        responses: dict[str, _FakeLotusAIResponse],
        record: dict[str, Any],
        **kwargs,
    ):  # noqa: ANN002, ANN003
        self._responses = responses
        self._record = record

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
        return False

    def post(
        self,
        url: str,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> _FakeLotusAIResponse:
        self._record["url"] = url
        self._record["json"] = json
        self._record["headers"] = headers
        if headers != {"X-Caller-App": "lotus-advise"}:
            raise AssertionError(f"unexpected authenticated caller headers: {headers}")
        response = self._responses.get(url)
        if response is None:
            raise AssertionError(f"unexpected request url: {url}")
        return response


def test_workspace_ai_rationale_returns_evidence_grounded_output(monkeypatch) -> None:
    recorded: dict[str, Any] = {}
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeLotusAIClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeLotusAIResponse(
                    200,
                    {
                        "execution": {
                            "status": "COMPLETED",
                            "result": {
                                "message": (
                                    "advisor_123 requested a rationale for the evaluated workspace."
                                )
                            },
                        },
                        "workflow_pack_run": {
                            "run_id": "packrun_workspace_rationale_req_001",
                            "runtime_state": "COMPLETED",
                            "review_state": "AWAITING_REVIEW",
                            "allowed_review_actions": ["ACCEPT", "REJECT", "REVISE"],
                            "supportability_status": "ACTION_REQUIRED",
                            "workflow_authority_owner": "lotus-advise",
                        },
                    },
                )
            },
            record=recorded,
            **kwargs,
        ),
    )
    create_payload = {
        "workspace_name": "AI rationale workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_ai_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
                    "fx_rates": [],
                },
                "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        client.post(f"/advisory/workspaces/{workspace_id}/evaluate")
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/assistant/rationale",
            json={
                "requested_by": "advisor_123",
                "instruction": "Summarize the proposal rationale for an advisor review note.",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["generated_by"] == "lotus-ai"
    assert body["evidence"]["workspace_id"] == workspace_id
    assert body["evidence"]["proposal_status"] == "READY"
    assert body["workflow_pack_run"]["run_id"] == "packrun_workspace_rationale_req_001"
    assert body["workflow_pack_run"]["workflow_authority_owner"] == "lotus-advise"
    assert recorded["url"] == f"{base_url}/platform/workflow-packs/execute"
    assert recorded["json"]["pack_id"] == "workspace_rationale.pack"
    assert recorded["json"]["version"] == "v1"
    assert recorded["json"]["workflow_surface"] == "advisory-workspace-assistant"
    assert recorded["json"]["task_request"]["caller"]["caller_app"] == "lotus-advise"
    assert recorded["json"]["task_request"]["context"]["payload"]["workspace"]["workspace_id"] == (
        workspace_id
    )
    assert recorded["json"]["task_request"]["context"]["payload"]["instruction"]["text"] == (
        "Summarize the proposal rationale for an advisor review note."
    )


def test_workspace_ai_rationale_review_action_preserves_replacement_lineage(monkeypatch) -> None:
    recorded: dict[str, Any] = {}
    base_url = "http://lotus-ai.dev.lotus"
    review_action_url = (
        f"{base_url}/platform/workflow-packs/runs/"
        "packrun_workspace_rationale_req_001/review-actions"
    )
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeLotusAIClient(
            *args,
            responses={
                review_action_url: _FakeLotusAIResponse(
                    200,
                    {
                        "run": {
                            "run_id": "packrun_workspace_rationale_req_001",
                            "runtime_state": "COMPLETED",
                            "review_state": "SUPERSEDED",
                            "allowed_review_actions": [],
                            "supportability_status": "HISTORICAL",
                            "workflow_authority_owner": "lotus-advise",
                            "replacement_run_id": "packrun_workspace_rationale_req_002",
                            "findings": [
                                {
                                    "finding_id": "superseded",
                                    "severity": "INFO",
                                    "summary": (
                                        "Run is historical after replacement lineage was recorded."
                                    ),
                                }
                            ],
                        },
                        "summary": ["Run superseded in favor of replacement lineage."],
                    },
                )
            },
            record=recorded,
            **kwargs,
        ),
    )
    create_payload = {
        "workspace_name": "AI rationale review workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_ai_review_01",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/assistant/rationale/review-actions",
            json={
                "run_id": "packrun_workspace_rationale_req_001",
                "action_type": "SUPERSEDE",
                "reviewed_by": "advisor_123",
                "reason": "A refreshed rationale run supersedes this earlier draft.",
                "replacement_run_id": "packrun_workspace_rationale_req_002",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_pack_run"]["run_id"] == "packrun_workspace_rationale_req_001"
    assert body["workflow_pack_run"]["supportability_status"] == "HISTORICAL"
    assert body["workflow_pack_run"]["superseded"] is True
    assert body["workflow_pack_run"]["replacement_run_id"] == "packrun_workspace_rationale_req_002"
    assert body["summary"] == ["Run superseded in favor of replacement lineage."]
    assert recorded["url"] == review_action_url
    assert recorded["json"] == {
        "action_type": "SUPERSEDE",
        "caller_app": "lotus-advise",
        "workflow_surface": "advisory-workspace-assistant",
        "pack_id": "workspace_rationale.pack",
        "version": "v1",
        "reviewed_by": "advisor_123",
        "reason": "A refreshed rationale run supersedes this earlier draft.",
        "replacement_run_id": "packrun_workspace_rationale_req_002",
        "correlation_id": f"workspace-rationale-review-{workspace_id}",
        "review_context": {
            "workspace_id": workspace_id,
            "source_refs": [f"lotus-advise:workspace:{workspace_id}"],
        },
    }


def test_workspace_ai_rationale_review_action_propagates_conflicts_truthfully(monkeypatch) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    review_action_url = (
        f"{base_url}/platform/workflow-packs/runs/"
        "packrun_workspace_rationale_req_001/review-actions"
    )
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeLotusAIClient(
            *args,
            responses={
                review_action_url: _FakeLotusAIResponse(
                    409,
                    {"detail": "Replacement run must belong to the same workflow-pack family."},
                )
            },
            record={},
            **kwargs,
        ),
    )
    create_payload = {
        "workspace_name": "AI rationale review conflict workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_ai_review_02",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/assistant/rationale/review-actions",
            json={
                "run_id": "packrun_workspace_rationale_req_001",
                "action_type": "REVISE",
                "reviewed_by": "advisor_123",
                "reason": "Use the replacement rationale run instead.",
                "replacement_run_id": "packrun_other_family_req_001",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Replacement run must belong to the same workflow-pack family."
    )


def test_workspace_ai_rationale_review_action_requires_replacement_lineage_for_supersede() -> None:
    create_payload = {
        "workspace_name": "AI rationale review validation workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_ai_review_03",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/assistant/rationale/review-actions",
            json={
                "run_id": "packrun_workspace_rationale_req_001",
                "action_type": "SUPERSEDE",
                "reviewed_by": "advisor_123",
                "reason": "Missing replacement lineage should be rejected.",
            },
        )

    assert response.status_code == 422
    assert "replacement_run_id is required" in response.json()["detail"][0]["msg"]


def test_workspace_ai_rationale_requires_evaluated_workspace() -> None:
    create_payload = {
        "workspace_name": "AI rationale workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_ai_02",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/assistant/rationale",
            json={
                "requested_by": "advisor_123",
                "instruction": "Summarize the proposal rationale for an advisor review note.",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "WORKSPACE_AI_REQUIRES_EVALUATED_WORKSPACE"


def test_workspace_ai_rationale_returns_503_when_lotus_ai_is_unavailable() -> None:
    create_payload = {
        "workspace_name": "AI rationale workspace",
        "created_by": "advisor_123",
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": {
                "portfolio_snapshot": {
                    "portfolio_id": "pf_ai_03",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "10000"}],
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        },
    }

    with TestClient(app) as client:
        workspace_id = client.post("/advisory/workspaces", json=create_payload).json()["workspace"][
            "workspace_id"
        ]
        client.post(f"/advisory/workspaces/{workspace_id}/evaluate")
        response = client.post(
            f"/advisory/workspaces/{workspace_id}/assistant/rationale",
            json={
                "requested_by": "advisor_123",
                "instruction": "Summarize the proposal rationale for an advisor review note.",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "LOTUS_AI_RATIONALE_UNAVAILABLE"
