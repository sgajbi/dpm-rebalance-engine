from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import src.api.services.advisory_simulation_validation as advisory_simulation_validation
from src.api.main import app
from src.api.proposals.router import reset_proposal_workflow_service_for_tests
from src.core.advisory.narrative_ai_models import ProposalNarrativeAiLineage
from src.core.advisory.narrative_ai_ports import (
    ProposalNarrativeDraftResponse,
    ProposalNarrativeDraftSection,
)
from src.core.advisory.narrative_ai_ports import (
    ProposalNarrativeDraftUnavailableError as LotusAIProposalNarrativeUnavailableError,
)
from src.core.advisory.provider_ports import (
    AdvisoryRiskEnrichmentUnavailableError as LotusRiskEnrichmentUnavailableError,
)
from src.core.advisory.provider_ports import (
    AdvisorySimulationUnavailableError as LotusCoreSimulationUnavailableError,
)
from src.core.advisory_engine import run_proposal_simulation
from src.core.proposals.context import ProposalContextResolutionError
from src.integrations.lotus_core.stateful_context import (
    get_stateful_context_fetch_stats_for_tests,
    reset_stateful_context_cache_for_tests,
)
from tests.shared.lotus_core_query_fakes import (
    CountingLotusCoreQueryClient,
    build_basic_stateful_query_responses,
)
from tests.shared.stateful_context_assertions import assert_core_context_fetch_counts
from tests.shared.stateful_context_builders import build_resolved_stateful_context


@pytest.fixture(autouse=True)
def override_db_dependency():
    original_overrides = dict(app.dependency_overrides)
    reset_proposal_workflow_service_for_tests()
    reset_stateful_context_cache_for_tests()
    yield
    app.dependency_overrides = original_overrides
    reset_proposal_workflow_service_for_tests()
    reset_stateful_context_cache_for_tests()


@pytest.fixture(autouse=True)
def stub_core_simulation_authority(monkeypatch):
    def _simulate_with_lotus_core(**kwargs):
        request = kwargs["request"]
        return run_proposal_simulation(
            portfolio=request.portfolio_snapshot,
            market_data=request.market_data_snapshot,
            shelf=request.shelf_entries,
            options=request.options,
            proposed_cash_flows=request.proposed_cash_flows,
            proposed_trades=request.proposed_trades,
            reference_model=request.reference_model,
            request_hash=kwargs["request_hash"],
            idempotency_key=kwargs["idempotency_key"],
            correlation_id=kwargs["correlation_id"],
            simulation_contract_version="advisory-simulation.v1",
            policy_context=kwargs.get("policy_context"),
        )

    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        _simulate_with_lotus_core,
    )


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _base_simulation_payload(portfolio_id: str = "pf_prop_api_1") -> dict:
    return {
        "portfolio_snapshot": {
            "portfolio_id": portfolio_id,
            "base_currency": "USD",
            "positions": [],
            "cash_balances": [{"currency": "USD", "amount": "1000"}],
        },
        "market_data_snapshot": {
            "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
            "fx_rates": [],
        },
        "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED"}],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [{"currency": "USD", "amount": "200"}],
        "proposed_trades": [{"side": "BUY", "instrument_id": "EQ_1", "quantity": "2"}],
    }


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


def _resolved_stateful_context(portfolio_id: str, as_of: str) -> dict:
    return build_resolved_stateful_context(
        portfolio_id,
        as_of,
        prices=[{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
        shelf_entries=[{"instrument_id": "EQ_1", "status": "APPROVED"}],
    )


class _FakeRiskResponse:
    def __init__(self, *, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://lotus-risk/analytics/risk/concentration")
            response = httpx.Response(self.status_code, json=self._payload, request=request)
            raise httpx.HTTPStatusError("upstream risk error", request=request, response=response)

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeRiskClient:
    def __init__(self, response: _FakeRiskResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> "_FakeRiskClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeRiskResponse:
        return self.response


def _risk_response_payload() -> dict[str, Any]:
    return {
        "source_service": "lotus-risk",
        "input_mode": "simulation",
        "risk_proxy": {"hhi_current": 5200.0, "hhi_proposed": 6800.0, "hhi_delta": 1600.0},
        "single_position_concentration": {
            "top_position_weight_current": 0.5,
            "top_position_weight_proposed": 0.6,
            "top_position_weight_delta": 0.1,
            "top_n_cumulative_weight_current": 0.8,
            "top_n_cumulative_weight_proposed": 0.9,
            "top_n_cumulative_weight_delta": 0.1,
            "top_n": 10,
            "top_position_current": {
                "security_id": "EQ_1",
                "security_name": "Security 1",
                "weight": 0.5,
            },
            "top_position_proposed": {
                "security_id": "EQ_1",
                "security_name": "Security 1",
                "weight": 0.6,
            },
        },
        "issuer_concentration": {
            "hhi_current": 5200.0,
            "hhi_proposed": 5800.0,
            "hhi_delta": 600.0,
            "top_issuer_weight_current": 0.5,
            "top_issuer_weight_proposed": 0.6,
            "top_issuer_weight_delta": 0.1,
            "coverage_status": "complete",
            "coverage_ratio_current": 1.0,
            "coverage_ratio_proposed": 1.0,
            "covered_position_count_current": 1,
            "covered_position_count_proposed": 1,
            "total_position_count_current": 1,
            "total_position_count_proposed": 1,
            "uncovered_position_count_current": 0,
            "uncovered_position_count_proposed": 0,
            "top_issuer_current": {
                "issuer_id": "PARENT_1",
                "issuer_name": "Parent 1",
                "weight": 0.5,
            },
            "top_issuer_proposed": {
                "issuer_id": "PARENT_1",
                "issuer_name": "Parent 1",
                "weight": 0.6,
            },
        },
    }


def test_advisory_proposal_simulate_endpoint_success(client):
    payload = _base_simulation_payload()

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["proposal_run_id"].startswith("pr_")
    assert body["status"] == "READY"
    assert body["intents"][0]["intent_type"] == "CASH_FLOW"
    assert body["correlation_id"].startswith("corr_")
    assert body["suitability"]["recommended_gate"] in {
        "NONE",
        "RISK_REVIEW",
        "COMPLIANCE_REVIEW",
    }
    assert body["gate_decision"]["gate"] in {
        "BLOCKED",
        "RISK_REVIEW_REQUIRED",
        "COMPLIANCE_REVIEW_REQUIRED",
        "CLIENT_CONSENT_REQUIRED",
        "EXECUTION_READY",
    }
    assert body["proposal_decision_summary"]["top_level_status"] == body["status"]
    assert body["proposal_decision_summary"]["primary_reason_code"]
    assert body["proposal_decision_summary"]["recommended_next_action"]
    assert body["explanation"]["context_resolution"]["input_mode"] == "stateless"
    assert body["explanation"]["context_resolution"]["resolution_source"] == "DIRECT_REQUEST"
    assert body["explanation"]["context_resolution"]["used_legacy_contract"] is True


def test_advisory_proposal_simulate_returns_backend_owned_proposal_alternatives(client):
    payload = _base_simulation_payload()
    payload["portfolio_snapshot"]["positions"] = [
        {"instrument_id": "EQ_1", "quantity": "20"},
        {"instrument_id": "EQ_2", "quantity": "10"},
    ]
    payload["market_data_snapshot"]["prices"].append(
        {"instrument_id": "EQ_2", "price": "80", "currency": "USD"}
    )
    payload["shelf_entries"].append({"instrument_id": "EQ_2", "status": "APPROVED"})
    payload["alternatives_request"] = {
        "enabled": True,
        "objectives": ["LOWER_TURNOVER", "REDUCE_CONCENTRATION"],
        "include_rejected_candidates": True,
    }

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-alt-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal_alternatives"]["requested_objectives"] == [
        "LOWER_TURNOVER",
        "REDUCE_CONCENTRATION",
    ]
    assert body["proposal_alternatives"]["alternatives"] == []
    assert len(body["proposal_alternatives"]["rejected_candidates"]) == 2


def test_advisory_proposal_simulate_requires_feature_flag(client):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_2", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-2"},
    )
    assert response.status_code == 422
    assert "PROPOSAL_SIMULATION_DISABLED" in response.json()["detail"]


def test_advisory_proposal_simulate_supports_stateful_context_resolution(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    payload = {
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_prop_api_stateful",
            "as_of": "2026-03-25",
            "mandate_id": "mandate_stateful_001",
        },
    }

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-stateful"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lineage"]["portfolio_snapshot_id"] == "ps_pf_prop_api_stateful_2026-03-25"
    assert body["lineage"]["market_data_snapshot_id"] == "md_2026-03-25"
    assert body["explanation"]["context_resolution"]["input_mode"] == "stateful"
    assert body["explanation"]["context_resolution"]["resolution_source"] == "LOTUS_CORE"
    assert body["explanation"]["context_resolution"]["used_legacy_contract"] is False


def test_advisory_proposal_simulate_stateful_requests_preserve_alternatives_request(
    client, monkeypatch
):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: build_resolved_stateful_context(
            stateful_input.portfolio_id,
            stateful_input.as_of,
            positions=[
                {"instrument_id": "EQ_1", "quantity": "20"},
                {"instrument_id": "EQ_2", "quantity": "10"},
            ],
            prices=[
                {"instrument_id": "EQ_1", "price": "100", "currency": "USD"},
                {"instrument_id": "EQ_2", "price": "80", "currency": "USD"},
            ],
            shelf_entries=[
                {"instrument_id": "EQ_1", "status": "APPROVED"},
                {"instrument_id": "EQ_2", "status": "APPROVED"},
            ],
        ),
        raising=False,
    )
    payload = {
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_prop_api_stateful_alt",
            "as_of": "2026-03-25",
        },
        "alternatives_request": {
            "enabled": True,
            "objectives": ["LOWER_TURNOVER", "REDUCE_CONCENTRATION"],
            "include_rejected_candidates": True,
        },
    }

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-stateful-alt-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["explanation"]["context_resolution"]["input_mode"] == "stateful"
    assert body["proposal_alternatives"]["requested_objectives"] == [
        "LOWER_TURNOVER",
        "REDUCE_CONCENTRATION",
    ]
    assert body["proposal_alternatives"]["alternatives"] == []
    assert len(body["proposal_alternatives"]["rejected_candidates"]) == 2


def test_advisory_proposal_simulate_rejects_oversized_alternatives_request_with_422(
    client, monkeypatch
):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    payload = {
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_prop_api_stateful_alt_invalid",
            "as_of": "2026-03-25",
        },
        "alternatives_request": {
            "enabled": True,
            "objectives": ["REDUCE_CONCENTRATION"],
            "max_alternatives": 4,
        },
    }

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-stateful-alt-invalid"},
    )

    assert response.status_code == 422
    assert "ALTERNATIVES_MAX_LIMIT_EXCEEDED" in response.json()["detail"]


def test_advisory_proposal_simulate_projects_available_policy_context_for_complex_product(
    client, monkeypatch
):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: build_resolved_stateful_context(
            stateful_input.portfolio_id,
            stateful_input.as_of,
            prices=[{"instrument_id": "STRUCT_NOTE_1", "price": "100", "currency": "USD"}],
            shelf_entries=[
                {
                    "instrument_id": "STRUCT_NOTE_1",
                    "status": "APPROVED",
                    "attributes": {"product_complexity": "HIGH"},
                }
            ],
        ),
        raising=False,
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json={
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": "pf_prop_api_context_ready",
                "as_of": "2026-03-25",
                "household_id": "hh_001",
                "mandate_id": "mandate_growth_01",
            },
        },
        headers={"Idempotency-Key": "prop-key-stateful-context-ready"},
    )

    assert response.status_code == 200
    body = response.json()
    assert (
        body["explanation"]["context_resolution"]["advisory_policy_context"][
            "client_context_status"
        ]
        == "AVAILABLE"
    )
    assert body["proposal_decision_summary"]["client_and_mandate_posture"]["status"] == "AVAILABLE"
    assert not any(
        item["reason_code"] == "MISSING_CLIENT_PRODUCT_COMPLEXITY_EVIDENCE"
        for item in body["proposal_decision_summary"]["missing_evidence"]
    )


def test_advisory_proposal_simulate_requests_mandate_context_for_restricted_product_buy(
    client, monkeypatch
):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: build_resolved_stateful_context(
            stateful_input.portfolio_id,
            stateful_input.as_of,
            prices=[{"instrument_id": "RESTRICTED_1", "price": "100", "currency": "USD"}],
            shelf_entries=[
                {
                    "instrument_id": "RESTRICTED_1",
                    "status": "RESTRICTED",
                    "issuer_id": "ISS_RESTRICTED",
                }
            ],
            options={"enable_proposal_simulation": True, "allow_restricted": True},
            proposed_trades=[{"side": "BUY", "instrument_id": "RESTRICTED_1", "quantity": "1"}],
        ),
        raising=False,
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json={
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": "pf_prop_api_mandate_gap",
                "as_of": "2026-03-25",
                "household_id": "hh_001",
            },
        },
        headers={"Idempotency-Key": "prop-key-stateful-mandate-gap"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal_decision_summary"]["decision_status"] == "INSUFFICIENT_EVIDENCE"
    assert body["proposal_decision_summary"]["recommended_next_action"] == "REQUEST_MANDATE_CONTEXT"
    assert any(
        item["reason_code"] == "MISSING_MANDATE_RESTRICTED_PRODUCT_EVIDENCE"
        for item in body["proposal_decision_summary"]["missing_evidence"]
    )


def test_advisory_proposal_simulate_rejects_stateful_request_when_resolution_unavailable(client):
    response = client.post(
        "/advisory/proposals/simulate",
        json={
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": "pf_prop_api_stateful_missing",
                "as_of": "2026-03-25",
            },
        },
        headers={"Idempotency-Key": "prop-key-stateful-missing"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "PROPOSAL_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"


def test_advisory_proposal_simulate_normalized_stateless_contract_matches_legacy_payload(client):
    legacy_payload = _base_simulation_payload(portfolio_id="pf_prop_api_equivalent")
    normalized_payload = {
        "input_mode": "stateless",
        "stateless_input": {
            "simulate_request": _base_simulation_payload(portfolio_id="pf_prop_api_equivalent")
        },
    }
    headers = {"Idempotency-Key": "prop-key-equivalent"}

    first = client.post("/advisory/proposals/simulate", json=legacy_payload, headers=headers)
    second = client.post("/advisory/proposals/simulate", json=normalized_payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_advisory_proposal_simulate_idempotency_conflict_returns_409(client):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_3", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }
    headers = {"Idempotency-Key": "prop-key-3"}

    first = client.post("/advisory/proposals/simulate", json=payload, headers=headers)
    assert first.status_code == 200

    payload["proposed_cash_flows"] = [{"currency": "USD", "amount": "1"}]
    second = client.post("/advisory/proposals/simulate", json=payload, headers=headers)
    assert second.status_code == 409
    assert "IDEMPOTENCY_KEY_CONFLICT" in second.json()["detail"]


def test_advisory_proposal_simulate_returns_cached_response_on_same_payload(client):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_4", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }
    headers = {"Idempotency-Key": "prop-key-4"}

    first = client.post("/advisory/proposals/simulate", json=payload, headers=headers)
    second = client.post("/advisory/proposals/simulate", json=payload, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_advisory_proposal_simulate_returns_503_when_idempotency_store_write_fails(
    client, monkeypatch
):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_store_error", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    class _FailingSimulationIdempotencyRepository:
        def get_simulation_idempotency(self, *, idempotency_key):
            return None

        def save_simulation_idempotency(self, record):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "src.api.services.advisory_simulation_service.get_proposal_repository",
        lambda: _FailingSimulationIdempotencyRepository(),
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-store-error"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "PROPOSAL_IDEMPOTENCY_STORE_WRITE_FAILED"


def test_advisory_proposal_simulate_redacts_sensitive_idempotency_validation_detail(
    client,
    monkeypatch,
):
    def _raise_sensitive_idempotency_error(_idempotency_key: str) -> str:
        raise ValueError("Authorization Bearer token leaked from upstream validation")

    monkeypatch.setattr(
        advisory_simulation_validation,
        "normalize_required_idempotency_key",
        _raise_sensitive_idempotency_error,
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=_base_simulation_payload("pf_sensitive_idempotency"),
        headers={"Idempotency-Key": "prop-key-sensitive-idempotency"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "PROPOSAL_REQUEST_VALIDATION_FAILED"


def test_advisory_proposal_simulate_redacts_sensitive_context_resolution_detail(
    client,
    monkeypatch,
):
    def _raise_sensitive_context_error(_request):
        raise ProposalContextResolutionError("raw payload includes secret client context")

    monkeypatch.setattr(
        advisory_simulation_validation,
        "resolve_simulation_request",
        _raise_sensitive_context_error,
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=_base_simulation_payload("pf_sensitive_context"),
        headers={"Idempotency-Key": "prop-key-sensitive-context"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "PROPOSAL_REQUEST_VALIDATION_FAILED"


def test_advisory_proposal_simulate_unhandled_error_returns_problem_details(monkeypatch):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_5", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    def _raise_unhandled(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        _raise_unhandled,
    )

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.post(
            "/advisory/proposals/simulate",
            json=payload,
            headers={"Idempotency-Key": "prop-key-500"},
        )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["title"] == "Internal Server Error"
    assert body["status"] == 500
    assert body["instance"] == "/advisory/proposals/simulate"


def test_advisory_proposal_simulate_uses_upstream_authorities_when_available(client, monkeypatch):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_upstream", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    def _simulate_with_lotus_core(**kwargs):
        request = kwargs["request"]
        return run_proposal_simulation(
            portfolio=request.portfolio_snapshot,
            market_data=request.market_data_snapshot,
            shelf=request.shelf_entries,
            options=request.options,
            proposed_cash_flows=request.proposed_cash_flows,
            proposed_trades=request.proposed_trades,
            reference_model=request.reference_model,
            request_hash=kwargs["request_hash"],
            idempotency_key=kwargs["idempotency_key"],
            correlation_id=kwargs["correlation_id"],
            policy_context=kwargs.get("policy_context"),
        )

    def _enrich_with_lotus_risk(**kwargs):
        return kwargs["proposal_result"]

    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")
    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        _simulate_with_lotus_core,
    )
    monkeypatch.setattr(
        "src.core.advisory.orchestration.enrich_with_lotus_risk",
        _enrich_with_lotus_risk,
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-upstream"},
    )

    assert response.status_code == 200
    authority = response.json()["explanation"]["authority_resolution"]
    assert authority["simulation_authority"] == "lotus_core"
    assert authority["risk_authority"] == "lotus_risk"
    assert authority["degraded"] is False


def test_advisory_proposal_simulate_sets_risk_authority_only_after_valid_risk_response(
    client, monkeypatch
):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_risk_client", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }
    fake_client = _FakeRiskClient(
        _FakeRiskResponse(status_code=200, payload=_risk_response_payload())
    )

    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")
    monkeypatch.setattr(
        "src.integrations.lotus_risk.enrichment.httpx.Client",
        lambda timeout: fake_client,
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-risk-client"},
    )

    assert response.status_code == 200
    body = response.json()
    authority = body["explanation"]["authority_resolution"]
    assert authority["simulation_authority"] == "lotus_core"
    assert authority["risk_authority"] == "lotus_risk"
    assert body["explanation"]["risk_lens"]["source_service"] == "lotus-risk"
    assert body["explanation"]["risk_lens"]["risk_proxy"]["hhi_delta"] == "1600.0"
    assert (
        body["explanation"]["risk_lens"]["single_position_concentration"]["top_position_current"][
            "security_id"
        ]
        == "EQ_1"
    )
    assert (
        body["explanation"]["risk_lens"]["issuer_concentration"]["top_issuer_current"]["issuer_id"]
        == "PARENT_1"
    )
    assert (
        body["explanation"]["risk_lens"]["issuer_concentration"]["coverage_ratio_current"] == "1.0"
    )


def test_advisory_proposal_simulate_marks_risk_authority_unavailable_when_risk_enrichment_fails(
    client, monkeypatch
):
    payload = {
        "portfolio_snapshot": {
            "portfolio_id": "pf_prop_api_risk_unavailable",
            "base_currency": "USD",
        },
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")

    def _raise_unavailable(**kwargs):
        raise LotusRiskEnrichmentUnavailableError("LOTUS_RISK_ENRICHMENT_UNAVAILABLE")

    monkeypatch.setattr(
        "src.core.advisory.orchestration.enrich_with_lotus_risk",
        _raise_unavailable,
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-risk-unavailable"},
    )

    assert response.status_code == 200
    body = response.json()
    authority = body["explanation"]["authority_resolution"]
    assert authority["simulation_authority"] == "lotus_core"
    assert authority["risk_authority"] == "unavailable"
    assert authority["degraded"] is True
    assert authority["degraded_reasons"] == ["LOTUS_RISK_ENRICHMENT_UNAVAILABLE"]
    assert "risk_lens" not in body["explanation"]
    assert body["proposal_decision_summary"]["risk_posture"]["status"] == "UNAVAILABLE"
    assert any(
        item["reason_code"] == "MISSING_RISK_LENS"
        for item in body["proposal_decision_summary"]["missing_evidence"]
    )


def test_advisory_proposal_simulate_reports_local_fallback_when_explicitly_enabled(
    client, monkeypatch
):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_fallback", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")
    monkeypatch.setenv("LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK", "true")

    def _simulate_with_lotus_core(**kwargs):
        raise LotusCoreSimulationUnavailableError("LOTUS_CORE_SIMULATION_UNAVAILABLE")

    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        _simulate_with_lotus_core,
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-fallback"},
    )

    assert response.status_code == 200
    authority = response.json()["explanation"]["authority_resolution"]
    assert authority["simulation_authority"] == "lotus_advise_local_fallback"
    assert authority["risk_authority"] == "unavailable"
    assert authority["degraded"] is True
    assert authority["degraded_reasons"] == [
        "LOTUS_CORE_SIMULATION_UNAVAILABLE",
        "LOTUS_RISK_ENRICHMENT_UNAVAILABLE",
    ]
    assert response.json()["allocation_lens"]["source"] == "LOTUS_ADVISE_LOCAL_FALLBACK"


def test_advisory_proposal_simulate_disallows_local_fallback_in_production_environment(
    client, monkeypatch
):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_prod_guard", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setenv("LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")

    def _simulate_with_lotus_core(**kwargs):
        raise LotusCoreSimulationUnavailableError("LOTUS_CORE_SIMULATION_UNAVAILABLE")

    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        _simulate_with_lotus_core,
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-prod-guard"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "LOTUS_CORE_SIMULATION_REQUIRED_IN_THIS_ENVIRONMENT"


def test_advisory_proposal_simulate_requires_lotus_core_when_fallback_disabled(client, monkeypatch):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_core_required", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    monkeypatch.delenv("LOTUS_CORE_BASE_URL", raising=False)
    monkeypatch.delenv("LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK", raising=False)
    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        lambda **kwargs: (_ for _ in ()).throw(
            LotusCoreSimulationUnavailableError("LOTUS_CORE_SIMULATION_UNAVAILABLE")
        ),
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-core-required"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "LOTUS_CORE_SIMULATION_UNAVAILABLE"


def test_advisory_proposal_simulate_returns_503_when_core_execution_unavailable(
    client, monkeypatch
):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_core_down", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        lambda **kwargs: (_ for _ in ()).throw(
            LotusCoreSimulationUnavailableError("LOTUS_CORE_SIMULATION_UNAVAILABLE")
        ),
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-core-down"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"].startswith("LOTUS_CORE_SIMULATION_UNAVAILABLE")


def test_advisory_proposal_simulate_redacts_sensitive_core_execution_error_detail(
    client,
    monkeypatch,
):
    payload = {
        "portfolio_snapshot": {
            "portfolio_id": "pf_prop_api_core_sensitive",
            "base_currency": "USD",
        },
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    def _raise_sensitive_core_error(**kwargs):
        raise LotusCoreSimulationUnavailableError(
            "provider response included Authorization Bearer token material"
        )

    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        _raise_sensitive_core_error,
    )

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-core-sensitive"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "LOTUS_CORE_SIMULATION_UNAVAILABLE"


def test_advisory_proposal_simulate_preserves_upstream_contract_error_status(client, monkeypatch):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_contract", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    def _simulate_with_lotus_core(**kwargs):
        raise LotusCoreSimulationUnavailableError(
            "Unsupported canonical simulation contract version: "
            "advisory-simulation.v0. Expected advisory-simulation.v1.",
            status_code=412,
        )

    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        _simulate_with_lotus_core,
    )
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-contract-mismatch"},
    )

    assert response.status_code == 412
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["title"] == "Upstream Canonical Simulation Error"
    assert "Unsupported canonical simulation contract version" in body["detail"]


def test_advisory_proposal_simulate_returns_drift_analysis_when_reference_model_provided(client):
    payload = {
        "portfolio_snapshot": {
            "portfolio_id": "pf_prop_api_14c",
            "base_currency": "USD",
            "positions": [{"instrument_id": "EQ_1", "quantity": "10"}],
            "cash_balances": [{"currency": "USD", "amount": "0"}],
        },
        "market_data_snapshot": {
            "prices": [{"instrument_id": "EQ_1", "price": "100", "currency": "USD"}],
            "fx_rates": [],
        },
        "shelf_entries": [{"instrument_id": "EQ_1", "status": "APPROVED", "asset_class": "EQUITY"}],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
        "reference_model": {
            "model_id": "mdl_api_14c",
            "as_of": "2026-02-18",
            "base_currency": "USD",
            "asset_class_targets": [
                {"asset_class": "EQUITY", "weight": "0.9"},
                {"asset_class": "CASH", "weight": "0.1"},
            ],
        },
    }

    response = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-key-14c"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["drift_analysis"]["reference_model"]["model_id"] == "mdl_api_14c"


def test_advisory_proposal_artifact_endpoint_success(client):
    payload = {
        "portfolio_snapshot": {
            "portfolio_id": "pf_prop_api_art_1",
            "base_currency": "SGD",
            "positions": [{"instrument_id": "SG_BOND", "quantity": "10"}],
            "cash_balances": [{"currency": "SGD", "amount": "1000"}],
        },
        "market_data_snapshot": {
            "prices": [
                {"instrument_id": "SG_BOND", "price": "100", "currency": "SGD"},
                {"instrument_id": "US_EQ", "price": "100", "currency": "USD"},
            ],
            "fx_rates": [{"pair": "USD/SGD", "rate": "1.35"}],
        },
        "shelf_entries": [
            {
                "instrument_id": "SG_BOND",
                "status": "APPROVED",
                "asset_class": "BOND",
                "issuer_id": "ISS_SG_BOND",
                "liquidity_tier": "L1",
            },
            {
                "instrument_id": "US_EQ",
                "status": "APPROVED",
                "asset_class": "EQUITY",
                "issuer_id": "ISS_US_EQ",
                "liquidity_tier": "L1",
            },
        ],
        "options": {
            "enable_proposal_simulation": True,
            "suitability_thresholds": {
                "single_position_max_weight": "1.00",
                "issuer_max_weight": "1.00",
                "max_weight_by_liquidity_tier": {},
                "cash_band_min_weight": "0",
                "cash_band_max_weight": "1",
            },
        },
        "proposed_cash_flows": [{"currency": "SGD", "amount": "100"}],
        "proposed_trades": [{"side": "BUY", "instrument_id": "US_EQ", "quantity": "2"}],
    }

    response = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "prop-art-key-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"].startswith("pa_")
    assert body["proposal_run_id"].startswith("pr_")
    assert body["status"] == "READY"
    assert body["summary"]["recommended_next_step"] == "CLIENT_CONSENT"
    assert body["gate_decision"]["gate"] == "CLIENT_CONSENT_REQUIRED"
    assert body["proposal_decision_summary"]["top_level_status"] == "READY"
    assert body["proposal_decision_summary"]["decision_status"] == "INSUFFICIENT_EVIDENCE"
    assert body["proposal_decision_summary"]["primary_reason_code"] == "MISSING_RISK_LENS"
    assert body["trades_and_funding"]["trade_list"][0]["instrument_id"] == "US_EQ"
    assert body["evidence_bundle"]["hashes"]["artifact_hash"].startswith("sha256:")


def test_advisory_proposal_artifact_can_include_deterministic_advisor_narrative(client):
    payload = _base_simulation_payload("pf_narrative_artifact")
    payload["narrative_request"] = {
        "audience": "ADVISOR_REVIEW",
        "sections": [
            "EXECUTIVE_SUMMARY",
            "RISK_AND_CONCENTRATION",
            "ALTERNATIVES_CONSIDERED",
        ],
        "requested_by": "advisor_123",
    }

    first = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "artifact-narrative-001"},
    )
    second = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "artifact-narrative-002"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    narrative = first.json()["proposal_narrative"]
    second_narrative = second.json()["proposal_narrative"]
    assert narrative["audience"] == "ADVISOR_REVIEW"
    assert narrative["generation_mode"] == "DETERMINISTIC_TEMPLATE"
    assert narrative["review_state"] == "DRAFT"
    assert [section["section_key"] for section in narrative["sections"]] == [
        "EXECUTIVE_SUMMARY",
        "RISK_AND_CONCENTRATION",
        "ALTERNATIVES_CONSIDERED",
    ]
    assert narrative["narrative_id"].startswith("pn_")
    assert narrative["sections"] == second_narrative["sections"]
    assert narrative["grounding_packet"]["input_hashes"]["request_hash"].startswith("sha256:")
    assert narrative["grounding_packet"]["input_hashes"]["artifact_hash"].startswith("sha256:")
    assert narrative["grounding_packet"]["packet_id"].startswith("pgp_")
    assert set(narrative["grounding_packet"]["facts"]) == {
        "proposal_status",
        "recommended_next_step",
        "objective_tags",
        "gate",
        "gate_recommended_next_step",
        "decision_status",
        "primary_reason_code",
        "recommended_next_action",
        "primary_summary",
        "decision_confidence",
        "approval_requirement_count",
        "blocking_approval_count",
        "approval_requirement_summaries",
        "material_change_count",
        "material_change_summaries",
        "missing_decision_evidence_count",
        "missing_decision_evidence_summaries",
        "risk_status",
        "risk_summary",
        "risk_highlights",
        "suitability_status",
        "suitability_new_issues",
        "suitability_resolved_issues",
        "suitability_persistent_issues",
        "highest_severity_new",
        "alternatives_status",
        "selected_alternative_id",
        "selected_alternative_label",
        "selected_alternative_objective",
        "selected_alternative_status",
        "alternative_tradeoff_summaries",
        "alternative_improvement_summaries",
        "alternative_deterioration_summaries",
        "alternative_count",
        "rejected_alternative_count",
        "rejected_alternative_summaries",
        "trade_count",
        "fx_count",
        "cash_takeaway",
        "drift_takeaway",
        "risk_disclaimer",
        "costs_and_fees_note",
        "tax_note",
        "execution_note",
    }
    assert {ref["ref_type"] for ref in narrative["grounding_packet"]["source_refs"]} <= {
        "proposal_artifact",
        "proposal_result",
        "decision_summary",
        "risk_lens",
        "suitability",
        "alternatives",
        "limitations",
    }
    assert {item["evidence_key"] for item in narrative["limitations"]} >= {
        "disclosure_policy",
        "review_workflow",
        "report_archive_lineage",
    }
    limitation_messages = " ".join(item["message"] for item in narrative["limitations"])
    assert "not implemented" not in limitation_messages.lower()
    assert "deferred" not in limitation_messages.lower()
    assert "completed mandate-policy approval/sign-off" in limitation_messages
    assert "client-ready narrative publication remains blocked" in limitation_messages


def test_advisory_proposal_narrative_leads_blocked_proposal_with_remediation(client):
    payload = _base_simulation_payload("pf_narrative_blocked")
    payload["market_data_snapshot"]["prices"] = []
    payload["narrative_request"] = {
        "audience": "ADVISOR_REVIEW",
        "sections": ["EXECUTIVE_SUMMARY", "APPROVALS_AND_NEXT_STEPS"],
    }

    response = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "artifact-narrative-blocked"},
    )

    assert response.status_code == 200
    narrative = response.json()["proposal_narrative"]
    executive_summary = narrative["sections"][0]["text"]
    approvals = narrative["sections"][1]["text"]
    assert executive_summary.startswith("Blockers require attention before benefits")
    assert "Required price data is missing" in executive_summary
    assert "Recommended action is FIX_INPUT" in executive_summary
    assert "DATA_REMEDIATION" in approvals
    assert "blocking requirement" in approvals


def test_advisory_proposal_narrative_does_not_imply_suitability_pass_with_insufficient_evidence(
    client,
):
    payload = _base_simulation_payload("pf_narrative_insufficient_evidence")
    payload["shelf_entries"][0]["status"] = "RESTRICTED"
    payload["options"]["allow_restricted"] = True
    payload["narrative_request"] = {
        "audience": "ADVISOR_REVIEW",
        "sections": ["EXECUTIVE_SUMMARY", "SUITABILITY_AND_MANDATE"],
    }

    response = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "artifact-narrative-insufficient"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal_decision_summary"]["decision_status"] == "INSUFFICIENT_EVIDENCE"
    narrative = body["proposal_narrative"]
    executive_summary = narrative["sections"][0]["text"]
    suitability = narrative["sections"][1]["text"]
    assert executive_summary.startswith(
        "Evidence is insufficient for a suitability pass or client-ready recommendation"
    )
    assert "REQUEST_MANDATE_CONTEXT" in executive_summary
    assert "not client-ready approval" in suitability


def test_advisory_proposal_narrative_uses_selected_alternative_tradeoff_evidence(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        "src.core.advisory.orchestration.enrich_with_lotus_risk",
        lambda **kwargs: _risk_enriched_result(kwargs["proposal_result"]),
    )
    portfolio_id = "pf_narrative_alt_selected"
    payload = {
        "portfolio_snapshot": {
            "portfolio_id": portfolio_id,
            "base_currency": "USD",
            "positions": [{"instrument_id": "EQ_OLD", "quantity": "10"}],
            "cash_balances": [{"currency": "USD", "amount": "1000"}],
        },
        "market_data_snapshot": {
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
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [{"currency": "USD", "amount": "100"}],
        "proposed_trades": [{"side": "BUY", "instrument_id": "EQ_NEW", "quantity": "2"}],
        "alternatives_request": {
            "enabled": True,
            "objectives": ["LOWER_TURNOVER"],
            "selected_alternative_id": f"alt_lower_turnover_{portfolio_id}_eq_new",
            "include_rejected_candidates": True,
        },
        "narrative_request": {
            "audience": "ADVISOR_REVIEW",
            "sections": ["ALTERNATIVES_CONSIDERED"],
        },
    }

    response = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "artifact-narrative-alt-selected"},
    )

    assert response.status_code == 200
    narrative = response.json()["proposal_narrative"]
    alternatives_text = narrative["sections"][0]["text"]
    assert "Alternatives evidence includes 1 feasible alternative(s)" in alternatives_text
    assert "Selected alternative" in alternatives_text
    assert "LOWER_TURNOVER" in alternatives_text
    assert "Tradeoff:" in alternatives_text
    assert "Improvement evidence:" in alternatives_text
    assert narrative["sections"][0]["source_refs"][0]["ref_type"] == "alternatives"


def test_advisory_proposal_artifact_selects_policy_disclosures_for_sg_equity_fx(client):
    payload = _base_simulation_payload("pf_narrative_policy_sg")
    payload["shelf_entries"][0]["asset_class"] = "EQUITY"
    payload["shelf_entries"][0]["attributes"] = {"product_type": "EQUITY"}
    payload["narrative_request"] = {
        "audience": "ADVISOR_REVIEW",
        "jurisdiction": "SG",
        "product_types": ["FX"],
        "client_audience": "ADVISOR_REVIEW",
        "sections": ["LIMITATIONS_AND_DISCLOSURES"],
    }

    response = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "artifact-narrative-policy-sg"},
    )

    assert response.status_code == 200
    narrative = response.json()["proposal_narrative"]
    policy = narrative["narrative_policy"]
    assert policy["policy_version"] == "advisory-narrative-policy.2026-05"
    assert policy["status"] == "READY_FOR_ADVISOR_REVIEW"
    assert policy["context"]["jurisdiction"] == "SG"
    assert policy["context"]["client_audience"] == "ADVISOR_REVIEW"
    assert set(policy["context"]["product_types"]) >= {"EQUITY", "FX"}
    assert {item["disclosure_id"] for item in narrative["disclosures"]} >= {
        "DISC_SG_GENERAL_MARKET_RISK",
        "DISC_SG_EQUITY_PRODUCT_RISK",
        "DISC_SG_FX_EXECUTION_RISK",
    }
    assert {item["evidence_key"] for item in narrative["limitations"]}.isdisjoint(
        {"disclosure_policy"}
    )
    assert narrative["guardrail_results"] == [
        {
            "guardrail_id": "GR_UNSUPPORTED_CLAIMS",
            "status": "PASS",
            "message": "No unsupported deterministic narrative claims detected.",
            "section_key": None,
        }
    ]


def test_advisory_proposal_artifact_blocks_client_ready_when_disclosure_policy_missing(client):
    payload = _base_simulation_payload("pf_narrative_policy_blocked")
    payload["narrative_request"] = {
        "audience": "ADVISOR_REVIEW",
        "jurisdiction": "ZZ",
        "client_audience": "CLIENT_READY",
        "sections": ["EXECUTIVE_SUMMARY"],
    }

    response = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "artifact-narrative-policy-blocked"},
    )

    assert response.status_code == 200
    narrative = response.json()["proposal_narrative"]
    policy = narrative["narrative_policy"]
    assert narrative["status"] == "BLOCKED_POLICY_INCOMPLETE"
    assert policy["status"] == "BLOCKED_CLIENT_READY"
    assert policy["context"]["jurisdiction"] == "ZZ"
    assert policy["client_ready_blockers"] == [
        "CLIENT_READY_DISCLOSURE_POLICY_UNAVAILABLE",
        "CLIENT_READY_DISCLOSURES_NOT_SELECTED",
        "CLIENT_READY_NARRATIVE_RELEASE_NOT_SUPPORTED",
    ]
    assert {item["evidence_key"] for item in narrative["limitations"]} >= {
        "disclosure_policy",
        "review_workflow",
    }


def _ai_lineage() -> ProposalNarrativeAiLineage:
    return ProposalNarrativeAiLineage(
        requested_generation_mode="AI_ASSISTED_DRAFT",
        adapter_version="proposal-narrative-lotus-ai-adapter.v1",
        workflow_pack_id="proposal_narrative_draft.pack",
        workflow_pack_version="v1",
        prompt_template_version="proposal-narrative-instructions.v1",
        model_version="lotus-ai-governed-model.v1",
        workflow_run_id="packrun_proposal_narrative_001",
    )


def test_advisory_proposal_artifact_can_include_ai_assisted_draft_narrative(
    client,
    monkeypatch,
):
    def _generate_ai_draft(**kwargs):
        return ProposalNarrativeDraftResponse(
            sections=(
                ProposalNarrativeDraftSection(
                    section_key="EXECUTIVE_SUMMARY",
                    title="Executive Summary",
                    text=(
                        "AI-assisted advisor-review draft based on the supplied proposal evidence."
                    ),
                ),
            ),
            lineage=_ai_lineage(),
        )

    monkeypatch.setattr(
        "src.core.advisory.narrative.generate_proposal_narrative_draft_with_lotus_ai",
        _generate_ai_draft,
    )
    payload = _base_simulation_payload("pf_narrative_ai")
    payload["narrative_request"] = {
        "audience": "ADVISOR_REVIEW",
        "generation_mode": "AI_ASSISTED_DRAFT",
        "jurisdiction": "SG",
        "sections": ["EXECUTIVE_SUMMARY"],
        "requested_by": "advisor_123",
    }

    response = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "artifact-narrative-ai"},
    )

    assert response.status_code == 200
    narrative = response.json()["proposal_narrative"]
    assert narrative["generation_mode"] == "AI_ASSISTED_DRAFT"
    assert narrative["review_state"] == "DRAFT"
    assert narrative["status"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert narrative["ai_lineage"]["workflow_run_id"] == "packrun_proposal_narrative_001"
    assert narrative["ai_lineage"]["fallback_reason"] is None
    assert narrative["sections"][0]["text"] == (
        "AI-assisted advisor-review draft based on the supplied proposal evidence."
    )
    assert narrative["guardrail_results"] == [
        {
            "guardrail_id": "GR_UNSUPPORTED_CLAIMS",
            "status": "PASS",
            "message": "No unsupported deterministic narrative claims detected.",
            "section_key": None,
        }
    ]


def test_advisory_proposal_artifact_falls_back_when_ai_narrative_unavailable(
    client,
    monkeypatch,
):
    def _generate_ai_draft(**kwargs):
        raise LotusAIProposalNarrativeUnavailableError("LOTUS_AI_NARRATIVE_UNAVAILABLE")

    monkeypatch.setattr(
        "src.core.advisory.narrative.generate_proposal_narrative_draft_with_lotus_ai",
        _generate_ai_draft,
    )
    payload = _base_simulation_payload("pf_narrative_ai_fallback")
    payload["narrative_request"] = {
        "audience": "ADVISOR_REVIEW",
        "generation_mode": "AI_ASSISTED_DRAFT",
        "sections": ["EXECUTIVE_SUMMARY"],
    }

    response = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "artifact-narrative-ai-fallback"},
    )

    assert response.status_code == 200
    narrative = response.json()["proposal_narrative"]
    assert narrative["generation_mode"] == "DETERMINISTIC_TEMPLATE"
    assert narrative["review_state"] == "DRAFT"
    assert narrative["ai_lineage"]["fallback_reason"] == "LOTUS_AI_NARRATIVE_UNAVAILABLE"
    assert narrative["ai_lineage"]["workflow_run_id"] is None
    assert narrative["sections"][0]["section_key"] == "EXECUTIVE_SUMMARY"


def test_advisory_proposal_artifact_rejects_unsafe_ai_claims(client, monkeypatch):
    def _generate_ai_draft(**kwargs):
        return ProposalNarrativeDraftResponse(
            sections=(
                ProposalNarrativeDraftSection(
                    section_key="EXECUTIVE_SUMMARY",
                    title="Executive Summary",
                    text="This proposal provides a guaranteed return for the client.",
                ),
            ),
            lineage=_ai_lineage(),
        )

    monkeypatch.setattr(
        "src.core.advisory.narrative.generate_proposal_narrative_draft_with_lotus_ai",
        _generate_ai_draft,
    )
    payload = _base_simulation_payload("pf_narrative_ai_guardrail")
    payload["narrative_request"] = {
        "audience": "ADVISOR_REVIEW",
        "generation_mode": "AI_ASSISTED_DRAFT",
        "sections": ["EXECUTIVE_SUMMARY"],
    }

    response = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "artifact-narrative-ai-guardrail"},
    )

    assert response.status_code == 200
    narrative = response.json()["proposal_narrative"]
    assert narrative["generation_mode"] == "AI_ASSISTED_DRAFT"
    assert narrative["status"] == "BLOCKED_GUARDRAIL_FAILURE"
    assert narrative["guardrail_results"][0]["status"] == "FAIL"
    assert narrative["guardrail_results"][0]["guardrail_id"] == ("GR_UNSUPPORTED_GUARANTEED_RETURN")


def test_advisory_proposal_artifact_supports_stateful_context_resolution(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )

    response = client.post(
        "/advisory/proposals/artifact",
        json={
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": "pf_prop_api_art_stateful",
                "as_of": "2026-03-25",
            },
        },
        headers={"Idempotency-Key": "prop-art-key-stateful"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_bundle"]["hashes"]["request_hash"].startswith("sha256:")
    assert body["summary"]["title"] == "Proposal for pf_prop_api_art_stateful"
    assert body["evidence_bundle"]["hashes"]["artifact_hash"].startswith("sha256:")


def test_stateful_simulate_and_artifact_share_warm_lotus_core_context(client, monkeypatch):
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    query_client = CountingLotusCoreQueryClient(
        build_basic_stateful_query_responses(
            base_url=base_url,
            portfolio_id="pf_stateful_artifact_cache",
            as_of="2026-03-25",
        )
    )
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: query_client,
    )
    monkeypatch.setattr(
        "src.core.advisory.orchestration.enrich_with_lotus_risk",
        lambda **kwargs: kwargs["proposal_result"],
    )
    payload = {
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_artifact_cache",
            "as_of": "2026-03-25",
        },
    }

    simulated = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "stateful-artifact-cache-simulate"},
    )
    artifact = client.post(
        "/advisory/proposals/artifact",
        json=payload,
        headers={"Idempotency-Key": "stateful-artifact-cache-artifact"},
    )

    assert simulated.status_code == 200
    assert artifact.status_code == 200
    assert artifact.json()["summary"]["title"] == "Proposal for pf_stateful_artifact_cache"
    assert query_client.request_count == 5
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=1, positions=1, cash=1)


def test_advisory_proposal_artifact_reuses_idempotent_simulation_response(client):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_art_2", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }
    first_headers = {"Idempotency-Key": "  prop-art-key-2  "}
    replay_headers = {"Idempotency-Key": "prop-art-key-2"}

    first = client.post("/advisory/proposals/artifact", json=payload, headers=first_headers)
    second = client.post("/advisory/proposals/artifact", json=payload, headers=replay_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["proposal_run_id"] == second_body["proposal_run_id"]
    assert (
        first_body["evidence_bundle"]["hashes"]["artifact_hash"]
        == second_body["evidence_bundle"]["hashes"]["artifact_hash"]
    )


def test_advisory_proposal_artifact_idempotency_conflict_returns_409(client):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_art_3", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }
    headers = {"Idempotency-Key": "prop-art-key-3"}

    first = client.post("/advisory/proposals/artifact", json=payload, headers=headers)
    assert first.status_code == 200

    payload["proposed_cash_flows"] = [{"currency": "USD", "amount": "1"}]
    second = client.post("/advisory/proposals/artifact", json=payload, headers=headers)
    assert second.status_code == 409
    assert "IDEMPOTENCY_KEY_CONFLICT" in second.json()["detail"]


def test_advisory_proposal_simulate_allows_different_idempotency_keys(client):
    payload = {
        "portfolio_snapshot": {"portfolio_id": "pf_prop_api_cache", "base_currency": "USD"},
        "market_data_snapshot": {"prices": [], "fx_rates": []},
        "shelf_entries": [],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [],
    }

    first = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "  prop-cache-1  "},
    )
    second = client.post(
        "/advisory/proposals/simulate",
        json=payload,
        headers={"Idempotency-Key": "prop-cache-2"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["proposal_run_id"] == second.json()["proposal_run_id"]
    assert first.json()["lineage"]["idempotency_key"] == "prop-cache-1"
