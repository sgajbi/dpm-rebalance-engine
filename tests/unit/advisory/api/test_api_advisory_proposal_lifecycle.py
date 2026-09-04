import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import src.api.proposals.router as proposals_router
from src.api.main import app
from src.api.proposals.router import reset_proposal_workflow_service_for_tests
from src.core.advisory.provider_ports import (
    AdvisoryRiskEnrichmentUnavailableError as LotusRiskEnrichmentUnavailableError,
)
from src.core.proposals import ProposalAsyncAcceptedResponse, ProposalIdempotencyConflictError
from src.integrations.lotus_core.stateful_context import (
    get_stateful_context_fetch_stats_for_tests,
    reset_stateful_context_cache_for_tests,
)
from src.integrations.lotus_report import LotusReportUnavailableError
from src.runtime import proposal_repositories
from tests.shared.lotus_core_query_fakes import (
    CountingLotusCoreQueryClient,
    build_basic_stateful_query_responses,
)
from tests.shared.stateful_context_assertions import assert_core_context_fetch_counts
from tests.shared.stateful_context_builders import build_resolved_stateful_context


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


def _base_create_payload(portfolio_id: str = "pf_lifecycle_1") -> dict:
    return {
        "created_by": "advisor_1",
        "metadata": {
            "title": "Lifecycle proposal",
            "advisor_notes": "Advisor notes",
            "jurisdiction": "SG",
            "mandate_id": "mandate_1",
        },
        "simulate_request": {
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
        },
    }


def _base_create_payload_with_narrative(portfolio_id: str = "pf_lifecycle_narrative") -> dict:
    payload = _base_create_payload(portfolio_id)
    payload["simulate_request"]["narrative_request"] = {
        "audience": "ADVISOR_REVIEW",
        "jurisdiction": "SG",
        "client_audience": "ADVISOR_REVIEW",
        "sections": ["EXECUTIVE_SUMMARY", "RISK_AND_CONCENTRATION"],
        "requested_by": "advisor_1",
    }
    return payload


def _create(client: TestClient, idempotency_key: str, payload: dict | None = None) -> dict:
    response = client.post(
        "/advisory/proposals",
        json=payload or _base_create_payload(),
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response.status_code == 200
    return response.json()


def _future_execution_timestamp(*, seconds: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


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


def _promote_to_execution_ready(
    client: TestClient,
    proposal_id: str,
    *,
    related_version_no: int = 1,
    route: str = "compliance",
) -> None:
    route_event_type = (
        "SUBMITTED_FOR_COMPLIANCE_REVIEW" if route == "compliance" else "SUBMITTED_FOR_RISK_REVIEW"
    )
    route_state = "COMPLIANCE_REVIEW" if route == "compliance" else "RISK_REVIEW"
    submitted = client.post(
        f"/advisory/proposals/{proposal_id}/transitions",
        json={
            "event_type": route_event_type,
            "actor_id": "advisor_1",
            "expected_state": "DRAFT",
            "reason": {"comment": "needs compliance"},
            "related_version_no": related_version_no,
        },
        headers={"Idempotency-Key": f"promote-{route}-submit-{proposal_id}"},
    )
    assert submitted.status_code == 200

    first_approval = client.post(
        f"/advisory/proposals/{proposal_id}/approvals",
        json={
            "approval_type": "COMPLIANCE" if route == "compliance" else "RISK",
            "approved": True,
            "actor_id": "compliance_user" if route == "compliance" else "risk_user",
            "expected_state": route_state,
            "details": {"comment": "ok"},
            "related_version_no": related_version_no,
        },
        headers={"Idempotency-Key": f"promote-{route}-approval-{proposal_id}"},
    )
    assert first_approval.status_code == 200

    consent = client.post(
        f"/advisory/proposals/{proposal_id}/approvals",
        json={
            "approval_type": "CLIENT_CONSENT",
            "approved": True,
            "actor_id": "client_1",
            "expected_state": "AWAITING_CLIENT_CONSENT",
            "details": {"channel": "IN_PERSON"},
            "related_version_no": related_version_no,
        },
        headers={"Idempotency-Key": f"promote-{route}-consent-{proposal_id}"},
    )
    assert consent.status_code == 200
    assert consent.json()["current_state"] == "EXECUTION_READY"


def _request_execution_handoff(
    client: TestClient,
    proposal_id: str,
    *,
    external_request_id: str = "oms_req_001",
) -> dict:
    handoff = client.post(
        f"/advisory/proposals/{proposal_id}/execution-handoffs",
        json={
            "actor_id": "ops_001",
            "execution_provider": "lotus-manage",
            "expected_state": "EXECUTION_READY",
            "related_version_no": 1,
            "correlation_id": "corr-exec-handoff-001",
            "external_request_id": external_request_id,
            "notes": {"channel": "OMS", "priority": "STANDARD"},
        },
    )
    assert handoff.status_code == 200
    return handoff.json()


def _resolved_stateful_context(
    portfolio_id: str,
    as_of: str,
) -> dict:
    payload = _base_create_payload(portfolio_id=portfolio_id)["simulate_request"]
    return build_resolved_stateful_context(
        portfolio_id,
        as_of,
        positions=payload["portfolio_snapshot"]["positions"],
        cash_amount=payload["portfolio_snapshot"]["cash_balances"][0]["amount"],
        prices=payload["market_data_snapshot"]["prices"],
        shelf_entries=payload["shelf_entries"],
    )


def setup_function() -> None:
    reset_proposal_workflow_service_for_tests()
    reset_stateful_context_cache_for_tests()


def test_create_proposal_persists_immutable_version_and_created_event():
    with TestClient(app) as client:
        body = _create(client, "lifecycle-create-1")

        assert body["proposal"]["current_state"] == "DRAFT"
        assert body["proposal"]["current_version_no"] == 1
        assert body["proposal"]["lifecycle_origin"] == "DIRECT_CREATE"
        assert body["proposal"]["source_workspace_id"] is None
        assert body["version"]["version_no"] == 1
        assert body["version"]["status_at_creation"] == "READY"
        assert body["version"]["artifact_hash"].startswith("sha256:")
        assert body["latest_workflow_event"]["event_type"] == "CREATED"


def test_create_proposal_supports_stateful_context_resolution(monkeypatch):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_001",
            "as_of": "2026-03-25",
            "mandate_id": "mandate_stateful_001",
        },
        "metadata": {
            "title": "Stateful proposal",
            "advisor_notes": "Resolved from lotus-core",
            "jurisdiction": "SG",
        },
    }

    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-create-stateful-1"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"]["portfolio_id"] == "pf_stateful_001"
    assert body["proposal"]["mandate_id"] == "mandate_stateful_001"
    context_resolution = body["version"]["evidence_bundle"]["context_resolution"]
    assert context_resolution["input_mode"] == "stateful"
    assert context_resolution["resolution_source"] == "LOTUS_CORE"
    assert context_resolution["resolved_context"]["portfolio_snapshot_id"] == (
        "ps_pf_stateful_001_2026-03-25"
    )


def test_stateful_create_can_request_advisor_review_narrative(monkeypatch):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_narrative_001",
            "as_of": "2026-03-25",
            "mandate_id": "mandate_stateful_narrative_001",
            "narrative_request": {
                "audience": "ADVISOR_REVIEW",
                "jurisdiction": "SG",
                "client_audience": "ADVISOR_REVIEW",
                "sections": ["EXECUTIVE_SUMMARY", "RISK_AND_CONCENTRATION"],
                "requested_by": "advisor_1",
            },
        },
        "metadata": {"jurisdiction": "SG"},
    }

    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-create-stateful-narrative"},
        )

    assert response.status_code == 200
    body = response.json()
    narrative = body["version"]["artifact"]["proposal_narrative"]
    assert narrative["generation_mode"] == "DETERMINISTIC_TEMPLATE"
    assert narrative["audience"] == "ADVISOR_REVIEW"
    assert narrative["review_state"] == "DRAFT"
    assert narrative["narrative_policy"]["status"] == "READY_FOR_ADVISOR_REVIEW"
    assert body["version"]["evidence_bundle"]["context_resolution"]["input_mode"] == "stateful"


def test_stateful_create_idempotency_replays_same_command_without_source_reresolution(monkeypatch):
    resolver_calls: list[str] = []

    def _resolve(stateful_input):  # noqa: ANN001
        resolver_calls.append(stateful_input.portfolio_id)
        resolved = _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        )
        volatile_snapshot_id = f"md_{stateful_input.as_of}_volatile_{len(resolver_calls)}"
        resolved["resolved_context"]["market_data_snapshot_id"] = volatile_snapshot_id
        resolved["simulate_request"]["market_data_snapshot"]["snapshot_id"] = volatile_snapshot_id
        return resolved

    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        _resolve,
        raising=False,
    )
    payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_idempotent_001",
            "as_of": "2026-03-25",
            "mandate_id": "mandate_stateful_idempotent_001",
        },
        "metadata": {
            "title": "Stateful idempotency proposal",
            "advisor_notes": "Replay should not re-resolve volatile source context",
            "jurisdiction": "SG",
        },
    }

    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-create-stateful-idempotent"},
        )
        replay = client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-create-stateful-idempotent"},
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert resolver_calls == ["pf_stateful_idempotent_001"]


def test_stateful_create_idempotency_rejects_changed_command_before_source_reresolution(
    monkeypatch,
):
    resolver_calls: list[str] = []

    def _resolve(stateful_input):  # noqa: ANN001
        resolver_calls.append(stateful_input.portfolio_id)
        return _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        )

    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        _resolve,
        raising=False,
    )
    payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_idempotent_conflict",
            "as_of": "2026-03-25",
        },
        "metadata": {
            "title": "Original stateful command",
            "jurisdiction": "SG",
        },
    }

    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-create-stateful-idempotent-conflict"},
        )
        conflict = client.post(
            "/advisory/proposals",
            json=payload | {"metadata": payload["metadata"] | {"title": "Changed command"}},
            headers={"Idempotency-Key": "lifecycle-create-stateful-idempotent-conflict"},
        )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "IDEMPOTENCY_KEY_CONFLICT: request hash mismatch"
    assert resolver_calls == ["pf_stateful_idempotent_conflict"]


def test_stateful_simulate_and_create_share_warm_lotus_core_context(monkeypatch):
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", base_url)
    query_client = CountingLotusCoreQueryClient(
        build_basic_stateful_query_responses(
            base_url=base_url,
            portfolio_id="pf_stateful_cross_surface",
            as_of="2026-03-25",
        )
    )
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: query_client,
    )

    simulate_payload = {
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_cross_surface",
            "as_of": "2026-03-25",
        },
    }
    create_payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_cross_surface",
            "as_of": "2026-03-25",
        },
        "metadata": {
            "title": "Cross-surface cached proposal",
            "advisor_notes": "Should reuse the warmed stateful context",
            "jurisdiction": "SG",
        },
    }

    with TestClient(app) as client:
        simulated = client.post(
            "/advisory/proposals/simulate",
            json=simulate_payload,
            headers={"Idempotency-Key": "stateful-cross-surface-simulate"},
        )
        created = client.post(
            "/advisory/proposals",
            json=create_payload,
            headers={"Idempotency-Key": "stateful-cross-surface-create"},
        )

    assert simulated.status_code == 200
    assert created.status_code == 200
    assert query_client.request_count == 5
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=1, positions=1, cash=1)


def test_create_proposal_rejects_stateful_request_when_context_resolution_is_unavailable():
    payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_missing",
            "as_of": "2026-03-25",
        },
        "metadata": {"title": "Unavailable stateful proposal"},
    }

    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-create-stateful-missing"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "PROPOSAL_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"


def test_create_proposal_stateful_request_does_not_use_local_fallback_for_context_resolution(
    monkeypatch,
):
    payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_missing",
            "as_of": "2026-03-25",
        },
        "metadata": {"title": "Unavailable stateful proposal"},
    }
    monkeypatch.setenv("LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK", "true")

    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-create-stateful-fallback-requested"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "PROPOSAL_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"


def test_get_proposal_repository_maps_runtime_and_value_errors(monkeypatch):
    reset_proposal_workflow_service_for_tests()

    def _raise_runtime():
        raise RuntimeError("PROPOSAL_POSTGRES_DSN_REQUIRED")

    monkeypatch.setattr(proposals_router.runtime, "build_repository", _raise_runtime)
    with pytest.raises(HTTPException) as runtime_exc:
        proposals_router.get_proposal_repository()
    assert runtime_exc.value.status_code == 503
    assert runtime_exc.value.detail == "PROPOSAL_POSTGRES_DSN_REQUIRED"

    reset_proposal_workflow_service_for_tests()

    def _raise_value():
        raise ValueError("invalid")

    monkeypatch.setattr(proposals_router.runtime, "build_repository", _raise_value)
    with pytest.raises(HTTPException) as value_exc:
        proposals_router.get_proposal_repository()
    assert value_exc.value.status_code == 503
    assert value_exc.value.detail == "PROPOSAL_POSTGRES_CONNECTION_FAILED"


def test_proposal_repository_backend_init_errors_return_503(monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setenv("PROPOSAL_STORE_BACKEND", "POSTGRES")
        monkeypatch.delenv("PROPOSAL_POSTGRES_DSN", raising=False)
        reset_proposal_workflow_service_for_tests()

        missing_dsn = client.get("/advisory/proposals")
        assert missing_dsn.status_code == 503
        assert missing_dsn.json()["detail"] == "PROPOSAL_POSTGRES_DSN_REQUIRED"

        monkeypatch.setenv(
            "PROPOSAL_POSTGRES_DSN",
            "postgresql://user:pass@localhost:5432/proposals",
        )
        monkeypatch.setattr(
            proposal_repositories,
            "PostgresProposalRepository",
            lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("boom")),
        )
        reset_proposal_workflow_service_for_tests()
        not_implemented = client.get("/advisory/proposals")
        assert not_implemented.status_code == 503
        assert not_implemented.json()["detail"] == "PROPOSAL_POSTGRES_CONNECTION_FAILED"


def test_proposal_repository_unexpected_init_error_mapped_to_503(monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setattr(
            "src.api.proposals.router.runtime.build_repository",
            lambda: (_ for _ in ()).throw(ValueError("boom")),
        )
        reset_proposal_workflow_service_for_tests()

        response = client.get("/advisory/proposals")
        assert response.status_code == 503
        assert response.json()["detail"] == "PROPOSAL_POSTGRES_CONNECTION_FAILED"


def test_proposal_supportability_config_endpoint_removed():
    with TestClient(app) as client:
        response = client.get("/advisory/proposals/supportability/config")

    assert response.status_code == 404


def test_create_proposal_idempotency_reuses_existing_proposal_and_detects_conflict():
    with TestClient(app) as client:
        first = _create(client, "lifecycle-create-2")
        second = _create(client, "lifecycle-create-2")

        assert first == second

        changed = _base_create_payload()
        changed["simulate_request"]["proposed_cash_flows"] = [{"currency": "USD", "amount": "777"}]
        conflict = client.post(
            "/advisory/proposals",
            json=changed,
            headers={"Idempotency-Key": "lifecycle-create-2"},
        )
        assert conflict.status_code == 409
        assert "IDEMPOTENCY_KEY_CONFLICT" in conflict.json()["detail"]


def test_get_list_and_version_include_and_hide_evidence():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-create-3")
        proposal_id = created["proposal"]["proposal_id"]

        listed = client.get("/advisory/proposals", params={"portfolio_id": "pf_lifecycle_1"})
        assert listed.status_code == 200
        assert listed.json()["items"][0]["proposal_id"] == proposal_id
        assert listed.json()["items"][0]["lifecycle_origin"] == "DIRECT_CREATE"
        assert listed.json()["items"][0]["source_workspace_id"] is None

        detail = client.get(
            f"/advisory/proposals/{proposal_id}", params={"include_evidence": False}
        )
        assert detail.status_code == 200
        assert detail.json()["proposal"]["lifecycle_origin"] == "DIRECT_CREATE"
        assert detail.json()["proposal"]["source_workspace_id"] is None
        assert detail.json()["current_version"]["evidence_bundle"] == {}

        version = client.get(
            f"/advisory/proposals/{proposal_id}/versions/1",
            params={"include_evidence": True},
        )
        assert version.status_code == 200
        assert version.json()["evidence_bundle"]["hashes"]["artifact_hash"].startswith("sha256:")


def test_create_version_increments_version_and_preserves_state():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-create-4")
        proposal_id = created["proposal"]["proposal_id"]

        version_payload = {
            "created_by": "advisor_2",
            "simulate_request": _base_create_payload()["simulate_request"],
        }
        version_payload["simulate_request"]["proposed_trades"] = [
            {"side": "BUY", "instrument_id": "EQ_NEW", "quantity": "3"}
        ]

        response = client.post(f"/advisory/proposals/{proposal_id}/versions", json=version_payload)
        assert response.status_code == 200
        body = response.json()
        assert body["proposal"]["current_version_no"] == 2
        assert body["proposal"]["current_state"] == "DRAFT"
        assert body["version"]["version_no"] == 2
        assert body["latest_workflow_event"]["event_type"] == "NEW_VERSION_CREATED"


def test_create_version_returns_409_for_expected_current_version_conflict():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-create-version-conflict")
        proposal_id = created["proposal"]["proposal_id"]

        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json={
                "created_by": "advisor_2",
                "expected_current_version_no": 2,
                "simulate_request": _base_create_payload()["simulate_request"],
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "VERSION_CONFLICT: expected_current_version_no mismatch"


def test_create_version_supports_stateful_context_resolution(monkeypatch):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    with TestClient(app) as client:
        created = _create(client, "lifecycle-create-stateful-version-base")
        proposal_id = created["proposal"]["proposal_id"]

        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json={
                "created_by": "advisor_2",
                "expected_current_version_no": 1,
                "input_mode": "stateful",
                "stateful_input": {
                    "portfolio_id": "pf_lifecycle_1",
                    "as_of": "2026-03-25",
                    "mandate_id": "mandate_stateful_002",
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"]["current_version_no"] == 2
    context_resolution = body["version"]["evidence_bundle"]["context_resolution"]
    assert context_resolution["input_mode"] == "stateful"
    assert context_resolution["resolved_context"]["portfolio_snapshot_id"] == (
        "ps_pf_lifecycle_1_2026-03-25"
    )


def test_stateful_version_can_request_fresh_advisor_review_narrative(monkeypatch):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    with TestClient(app) as client:
        created = _create(client, "lifecycle-create-stateful-narrative-version-base")
        proposal_id = created["proposal"]["proposal_id"]

        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json={
                "created_by": "advisor_2",
                "expected_current_version_no": 1,
                "input_mode": "stateful",
                "stateful_input": {
                    "portfolio_id": "pf_lifecycle_1",
                    "as_of": "2026-03-25",
                    "narrative_request": {
                        "audience": "ADVISOR_REVIEW",
                        "jurisdiction": "SG",
                        "client_audience": "ADVISOR_REVIEW",
                        "sections": ["EXECUTIVE_SUMMARY"],
                        "requested_by": "advisor_2",
                    },
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"]["current_version_no"] == 2
    narrative = body["version"]["artifact"]["proposal_narrative"]
    assert narrative["generation_mode"] == "DETERMINISTIC_TEMPLATE"
    assert [section["section_key"] for section in narrative["sections"]] == ["EXECUTIVE_SUMMARY"]
    assert body["version"]["evidence_bundle"]["context_resolution"]["input_mode"] == "stateful"


def test_stateful_create_and_version_share_warm_lotus_core_context(monkeypatch):
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", base_url)
    query_client = CountingLotusCoreQueryClient(
        build_basic_stateful_query_responses(
            base_url=base_url,
            portfolio_id="pf_stateful_version_cache",
            as_of="2026-03-25",
        )
    )
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: query_client,
    )

    create_payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_version_cache",
            "as_of": "2026-03-25",
        },
        "metadata": {
            "title": "Version cache warm base",
            "advisor_notes": "Base proposal should warm the Lotus Core context cache",
            "jurisdiction": "SG",
        },
    }
    version_payload = {
        "created_by": "advisor_2",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_version_cache",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals",
            json=create_payload,
            headers={"Idempotency-Key": "stateful-version-cache-create"},
        )
        proposal_id = created.json()["proposal"]["proposal_id"]
        versioned = client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json=version_payload,
        )

    assert created.status_code == 200
    assert versioned.status_code == 200
    assert query_client.request_count == 5
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=1, positions=1, cash=1)


def test_stateful_create_refetches_for_distinct_as_of_inputs(monkeypatch):
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", base_url)
    cash_dates = iter(["2026-03-25", "2026-03-26"])

    class _AsOfAwareQueryClient(CountingLotusCoreQueryClient):
        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
        ):
            if method.upper() == "GET" and url.startswith(
                f"{base_url}/portfolios/pf_stateful_asof_boundary/cash-balances"
            ):
                self.request_count += 1
                return self._responses[
                    ("GET", f"{base_url}/portfolios/pf_stateful_asof_boundary/cash-balances")
                ].__class__(
                    {
                        "portfolio_id": "pf_stateful_asof_boundary",
                        "resolved_as_of_date": next(cash_dates),
                        "cash_accounts": [],
                    }
                )
            return super().request(method, url, json=json, headers=headers)

    query_client = _AsOfAwareQueryClient(
        build_basic_stateful_query_responses(
            base_url=base_url,
            portfolio_id="pf_stateful_asof_boundary",
            as_of="2026-03-25",
        )
    )
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: query_client,
    )

    first_payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_asof_boundary",
            "as_of": "2026-03-25",
        },
        "metadata": {"title": "Boundary create 1", "jurisdiction": "SG"},
    }
    second_payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_asof_boundary",
            "as_of": "2026-03-26",
        },
        "metadata": {"title": "Boundary create 2", "jurisdiction": "SG"},
    }

    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals",
            json=first_payload,
            headers={"Idempotency-Key": "stateful-asof-boundary-1"},
        )
        second = client.post(
            "/advisory/proposals",
            json=second_payload,
            headers={"Idempotency-Key": "stateful-asof-boundary-2"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    first_context = first.json()["version"]["evidence_bundle"]["context_resolution"][
        "resolved_context"
    ]
    second_context = second.json()["version"]["evidence_bundle"]["context_resolution"][
        "resolved_context"
    ]
    assert first_context["source_provenance"]["portfolio"]["as_of"] == "2026-03-25"
    assert second_context["source_provenance"]["portfolio"]["as_of"] == "2026-03-26"
    assert first_context["portfolio_snapshot_id"] != second_context["portfolio_snapshot_id"]
    assert first_context["portfolio_snapshot_id"].startswith(
        "lotus-core:portfolio-state-snapshot:portfolio:pf_stateful_asof_boundary:"
    )
    assert second_context["portfolio_snapshot_id"].startswith(
        "lotus-core:portfolio-state-snapshot:portfolio:pf_stateful_asof_boundary:"
    )
    assert query_client.request_count == 10
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=2, positions=2, cash=2)


def test_stateful_create_refetches_when_optional_context_identity_changes(monkeypatch):
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", base_url)
    query_client = CountingLotusCoreQueryClient(
        build_basic_stateful_query_responses(
            base_url=base_url,
            portfolio_id="pf_stateful_identity_boundary",
            as_of="2026-03-25",
        )
    )
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: query_client,
    )

    first_payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_identity_boundary",
            "as_of": "2026-03-25",
            "mandate_id": "mandate_growth_01",
            "benchmark_id": "benchmark_balanced_usd",
        },
        "metadata": {"title": "Identity boundary 1", "jurisdiction": "SG"},
    }
    second_payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_identity_boundary",
            "as_of": "2026-03-25",
            "mandate_id": "mandate_income_01",
            "benchmark_id": "benchmark_income_usd",
        },
        "metadata": {"title": "Identity boundary 2", "jurisdiction": "SG"},
    }

    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals",
            json=first_payload,
            headers={"Idempotency-Key": "stateful-identity-boundary-1"},
        )
        second = client.post(
            "/advisory/proposals",
            json=second_payload,
            headers={"Idempotency-Key": "stateful-identity-boundary-2"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["proposal"]["mandate_id"] == "mandate_growth_01"
    assert second.json()["proposal"]["mandate_id"] == "mandate_income_01"
    assert query_client.request_count == 10
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=2, positions=2, cash=2)


def test_async_create_proposal_supports_stateful_context_resolution(monkeypatch):
    monkeypatch.setattr(
        "src.api.main.resolve_lotus_core_advisory_context",
        lambda stateful_input: _resolved_stateful_context(
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        ),
        raising=False,
    )
    payload = {
        "created_by": "advisor_async",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_async_stateful_001",
            "as_of": "2026-03-25",
            "mandate_id": "mandate_async_001",
        },
        "metadata": {"title": "Async stateful proposal"},
    }

    with TestClient(app) as client:
        accepted = client.post(
            "/advisory/proposals/async",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-async-stateful-1"},
        )

        assert accepted.status_code == 202
        operation_id = accepted.json()["operation_id"]
        operation = client.get(f"/advisory/proposals/operations/{operation_id}")

    assert operation.status_code == 200
    body = operation.json()
    assert body["status"] == "SUCCEEDED"
    result = body["result"]
    assert result["proposal"]["portfolio_id"] == "pf_async_stateful_001"
    assert result["version"]["evidence_bundle"]["context_resolution"]["input_mode"] == "stateful"


def test_stateful_async_create_reuses_cached_lotus_core_context(monkeypatch):
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", base_url)
    client = CountingLotusCoreQueryClient(
        build_basic_stateful_query_responses(
            base_url=base_url,
            portfolio_id="pf_async_stateful_cached",
            as_of="2026-03-25",
        )
    )
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: client,
    )

    payload = {
        "created_by": "advisor_1",
        "metadata": {"title": "Cached async stateful create"},
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_async_stateful_cached",
            "as_of": "2026-03-25",
        },
    }

    with TestClient(app) as test_client:
        first = test_client.post(
            "/advisory/proposals/async",
            json=payload,
            headers={
                "Idempotency-Key": "lifecycle-async-stateful-cache-1",
                "X-Correlation-Id": "corr-async-stateful-cache-1",
            },
        )
        second = test_client.post(
            "/advisory/proposals/async",
            json=payload,
            headers={
                "Idempotency-Key": "lifecycle-async-stateful-cache-2",
                "X-Correlation-Id": "corr-async-stateful-cache-2",
            },
        )

    assert first.status_code == 202
    assert second.status_code == 202
    assert client.request_count == 5


def test_stateful_create_recovers_after_initial_lotus_core_resolution_failure(monkeypatch):
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", base_url)
    portfolio_payload = {
        "portfolio_id": "pf_stateful_recovery_create",
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
                f"{base_url}/portfolios/pf_stateful_recovery_create",
            ):
                self.request_count += 1
                return self._responses[(method.upper(), url)].__class__(dict(portfolio_payload))
            return super().request(method, url, json=json, headers=headers)

    client = _RecoveringQueryClient(
        build_basic_stateful_query_responses(
            base_url=base_url,
            portfolio_id="pf_stateful_recovery_create",
            as_of="2026-03-25",
        )
    )
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: client,
    )
    payload = {
        "created_by": "advisor_1",
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": "pf_stateful_recovery_create",
            "as_of": "2026-03-25",
        },
        "metadata": {"title": "Recovering stateful create"},
    }

    with TestClient(app) as test_client:
        failed = test_client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-create-stateful-recovery-failed"},
        )

        portfolio_payload["base_currency"] = "USD"
        recovered = test_client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-create-stateful-recovery-success"},
        )

    assert failed.status_code == 422
    assert failed.json()["detail"] == "PROPOSAL_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"
    assert recovered.status_code == 200
    assert recovered.json()["proposal"]["portfolio_id"] == "pf_stateful_recovery_create"
    assert client.request_count == 10


def test_stateful_version_recovers_after_initial_lotus_core_resolution_failure(monkeypatch):
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", base_url)
    portfolio_payload = {
        "portfolio_id": "pf_lifecycle_1",
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
            if (method.upper(), url) == ("GET", f"{base_url}/portfolios/pf_lifecycle_1"):
                self.request_count += 1
                return self._responses[(method.upper(), url)].__class__(dict(portfolio_payload))
            return super().request(method, url, json=json, headers=headers)

    client = _RecoveringQueryClient(
        build_basic_stateful_query_responses(
            base_url=base_url,
            portfolio_id="pf_lifecycle_1",
            as_of="2026-03-25",
        )
    )
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: client,
    )

    with TestClient(app) as test_client:
        created = _create(test_client, "lifecycle-create-stateful-version-recovery-base")
        proposal_id = created["proposal"]["proposal_id"]

        failed = test_client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json={
                "created_by": "advisor_2",
                "expected_current_version_no": 1,
                "input_mode": "stateful",
                "stateful_input": {
                    "portfolio_id": "pf_lifecycle_1",
                    "as_of": "2026-03-25",
                },
            },
        )

        portfolio_payload["base_currency"] = "USD"
        recovered = test_client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json={
                "created_by": "advisor_2",
                "expected_current_version_no": 1,
                "input_mode": "stateful",
                "stateful_input": {
                    "portfolio_id": "pf_lifecycle_1",
                    "as_of": "2026-03-25",
                },
            },
        )

    assert failed.status_code == 422
    assert failed.json()["detail"] == "PROPOSAL_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"
    assert recovered.status_code == 200
    assert recovered.json()["proposal"]["current_version_no"] == 2
    assert recovered.json()["version"]["evidence_bundle"]["context_resolution"]["input_mode"] == (
        "stateful"
    )
    assert client.request_count == 10


def test_stateful_version_does_not_use_local_fallback_for_context_resolution(monkeypatch):
    monkeypatch.setenv("LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK", "true")

    with TestClient(app) as test_client:
        created = _create(test_client, "lifecycle-create-stateful-version-fallback-base")
        proposal_id = created["proposal"]["proposal_id"]

        failed = test_client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json={
                "created_by": "advisor_2",
                "expected_current_version_no": 1,
                "input_mode": "stateful",
                "stateful_input": {
                    "portfolio_id": "pf_lifecycle_missing",
                    "as_of": "2026-03-25",
                },
            },
        )

    assert failed.status_code == 422
    assert failed.json()["detail"] == "PROPOSAL_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"


def test_transition_requires_expected_state_and_rejects_invalid_transition():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-create-5")
        proposal_id = created["proposal"]["proposal_id"]

        missing_expected = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "SUBMITTED_FOR_RISK_REVIEW",
                "actor_id": "advisor_1",
                "reason": {"comment": "submit"},
            },
            headers={"Idempotency-Key": "transition-missing-expected-state"},
        )
        assert missing_expected.status_code == 409
        assert "expected_state is required" in missing_expected.json()["detail"]

        invalid = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "EXECUTED",
                "actor_id": "advisor_1",
                "expected_state": "DRAFT",
                "reason": {"comment": "invalid"},
            },
            headers={"Idempotency-Key": "transition-invalid-transition"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"] == "INVALID_TRANSITION"


def test_lifecycle_mutating_routes_require_idempotency_key():
    with TestClient(app) as client:
        created = _create(
            client,
            "lifecycle-required-idempotency-create",
            _base_create_payload_with_narrative("pf_lifecycle_required_idempotency"),
        )
        proposal_id = created["proposal"]["proposal_id"]
        version_no = created["version"]["version_no"]

        missing_transition_key = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "SUBMITTED_FOR_RISK_REVIEW",
                "actor_id": "advisor_1",
                "expected_state": "DRAFT",
                "reason": {"comment": "submit"},
                "related_version_no": 1,
            },
        )
        missing_approval_key = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "RISK",
                "approved": True,
                "actor_id": "risk_user",
                "expected_state": "RISK_REVIEW",
                "details": {"ticket": "risk_1"},
                "related_version_no": 1,
            },
        )
        missing_review_key = client.post(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review",
            json={
                "action": "APPROVE",
                "reviewed_by": "compliance_001",
                "reason": "Evidence-grounded advisor-review narrative.",
            },
        )

        proposal_after_rejections = client.get(f"/advisory/proposals/{proposal_id}")
        approvals_after_rejections = client.get(f"/advisory/proposals/{proposal_id}/approvals")

    for response in (missing_transition_key, missing_approval_key, missing_review_key):
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["header", "Idempotency-Key"]
    assert proposal_after_rejections.status_code == 200
    assert proposal_after_rejections.json()["proposal"]["current_state"] == "DRAFT"
    assert approvals_after_rejections.status_code == 200
    assert approvals_after_rejections.json()["approval_count"] == 0


def test_workflow_transitions_and_approvals_happy_path_to_executed():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-create-6")
        proposal_id = created["proposal"]["proposal_id"]

        to_compliance = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "SUBMITTED_FOR_COMPLIANCE_REVIEW",
                "actor_id": "advisor_1",
                "expected_state": "DRAFT",
                "reason": {"comment": "needs compliance"},
                "related_version_no": 1,
            },
            headers={"Idempotency-Key": "happy-compliance-submit"},
        )
        assert to_compliance.status_code == 200
        assert to_compliance.json()["current_state"] == "COMPLIANCE_REVIEW"

        compliance_approved = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "COMPLIANCE",
                "approved": True,
                "actor_id": "compliance_user",
                "expected_state": "COMPLIANCE_REVIEW",
                "details": {"comment": "ok"},
                "related_version_no": 1,
            },
            headers={"Idempotency-Key": "happy-compliance-approval"},
        )
        assert compliance_approved.status_code == 200
        assert compliance_approved.json()["current_state"] == "AWAITING_CLIENT_CONSENT"
        assert compliance_approved.json()["approval"]["approval_type"] == "COMPLIANCE"

        consent = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "CLIENT_CONSENT",
                "approved": True,
                "actor_id": "client_1",
                "expected_state": "AWAITING_CLIENT_CONSENT",
                "details": {"channel": "IN_PERSON"},
                "related_version_no": 1,
            },
            headers={"Idempotency-Key": "happy-client-consent"},
        )
        assert consent.status_code == 200
        assert consent.json()["current_state"] == "EXECUTION_READY"

        executed = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "EXECUTED",
                "actor_id": "ops_1",
                "expected_state": "EXECUTION_READY",
                "reason": {"execution_id": "oms_123"},
                "related_version_no": 1,
            },
            headers={"Idempotency-Key": "happy-executed-transition"},
        )
        assert executed.status_code == 200
        assert executed.json()["current_state"] == "EXECUTED"


def test_workflow_transitions_happy_path_via_risk_to_execution_ready():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-create-risk-happy")
        proposal_id = created["proposal"]["proposal_id"]

        to_risk = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "SUBMITTED_FOR_RISK_REVIEW",
                "actor_id": "advisor_1",
                "expected_state": "DRAFT",
                "reason": {"comment": "risk first"},
                "related_version_no": 1,
            },
            headers={"Idempotency-Key": "happy-risk-submit"},
        )
        assert to_risk.status_code == 200
        assert to_risk.json()["current_state"] == "RISK_REVIEW"

        risk_approved = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "RISK",
                "approved": True,
                "actor_id": "risk_user",
                "expected_state": "RISK_REVIEW",
                "details": {"ticket": "risk_1"},
                "related_version_no": 1,
            },
            headers={"Idempotency-Key": "happy-risk-approval"},
        )
        assert risk_approved.status_code == 200
        assert risk_approved.json()["current_state"] == "AWAITING_CLIENT_CONSENT"
        assert risk_approved.json()["latest_workflow_event"]["event_type"] == "RISK_APPROVED"

        consent = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "CLIENT_CONSENT",
                "approved": True,
                "actor_id": "client_1",
                "expected_state": "AWAITING_CLIENT_CONSENT",
                "details": {"channel": "DIGITAL"},
                "related_version_no": 1,
            },
            headers={"Idempotency-Key": "happy-risk-client-consent"},
        )
        assert consent.status_code == 200
        assert consent.json()["current_state"] == "EXECUTION_READY"


def test_execution_handoff_and_status_are_auditable(monkeypatch):
    def _request_proposal_report_with_lotus_report(*, request):
        assert request["proposal_version"]["version_no"] == 1
        return {
            "proposal": request["proposal"],
            "report_request_id": request["report_request_id"],
            "report_type": request["report_type"],
            "report_service": "lotus-report",
            "status": "READY",
            "generated_at": "2026-03-26T09:00:00+00:00",
            "report_reference_id": "lotus_report_artifact_001",
            "artifact_url": "https://lotus-report.local/artifacts/lotus_report_artifact_001",
            "explanation": {
                "ownership": "REPORTING_OWNED_BY_LOTUS_REPORT",
                "related_version_no": request["related_version_no"],
                "include_execution_summary": request["include_execution_summary"],
            },
        }

    monkeypatch.setattr(
        "src.api.main.request_proposal_report_with_lotus_report",
        _request_proposal_report_with_lotus_report,
        raising=False,
    )

    with TestClient(app) as client:
        created = _create(client, "lifecycle-execution-handoff")
        proposal_id = created["proposal"]["proposal_id"]

        _promote_to_execution_ready(client, proposal_id)
        handoff_body = _request_execution_handoff(client, proposal_id)
        assert handoff_body["handoff_status"] == "REQUESTED"
        assert handoff_body["execution_provider"] == "lotus-manage"
        assert handoff_body["latest_workflow_event"]["event_type"] == "EXECUTION_REQUESTED"

        status_response = client.get(f"/advisory/proposals/{proposal_id}/execution-status")
        assert status_response.status_code == 200
        status_body = status_response.json()
        assert status_body["handoff_status"] == "REQUESTED"
        assert status_body["execution_request_id"] == "oms_req_001"
        assert status_body["execution_provider"] == "lotus-manage"
        assert status_body["related_version_no"] == 1
        assert status_body["latest_workflow_event"]["event_type"] == "EXECUTION_REQUESTED"
        assert status_body["explanation"]["source"] == "ADVISORY_WORKFLOW_EVENTS"

        executed = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "EXECUTED",
                "actor_id": "ops_001",
                "expected_state": "EXECUTION_READY",
                "reason": {
                    "execution_id": "oms_fill_001",
                    "execution_request_id": "oms_req_001",
                    "execution_provider": "lotus-manage",
                },
                "related_version_no": 1,
            },
            headers={"Idempotency-Key": "execution-status-executed-transition"},
        )
        assert executed.status_code == 200

        executed_status = client.get(f"/advisory/proposals/{proposal_id}/execution-status")
        assert executed_status.status_code == 200
        executed_body = executed_status.json()
        assert executed_body["handoff_status"] == "EXECUTED"
        assert executed_body["external_execution_id"] == "oms_fill_001"
        assert executed_body["latest_workflow_event"]["event_type"] == "EXECUTED"
        assert (
            executed_body["explanation"]["state_correlation"]
            == "EXECUTION_REQUESTED_AND_EXECUTED_EVENTS"
        )

        report_request = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "CLIENT_PROPOSAL_SUMMARY",
                "requested_by": "advisor_1",
                "related_version_no": 1,
                "include_execution_summary": True,
            },
        )
        assert report_request.status_code == 200
        report_body = report_request.json()
        assert report_body["report_service"] == "lotus-report"
        assert report_body["report_type"] == "CLIENT_PROPOSAL_SUMMARY"
        assert report_body["explanation"]["ownership"] == "REPORTING_OWNED_BY_LOTUS_REPORT"


def test_execution_handoff_requires_execution_ready_state():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-execution-handoff-conflict")
        proposal_id = created["proposal"]["proposal_id"]

        handoff = client.post(
            f"/advisory/proposals/{proposal_id}/execution-handoffs",
            json={
                "actor_id": "ops_001",
                "execution_provider": "lotus-manage",
                "expected_state": "DRAFT",
                "notes": {"channel": "OMS"},
            },
        )

    assert handoff.status_code == 409
    assert "EXECUTION_READY" in handoff.json()["detail"]


def test_execution_status_returns_404_for_missing_proposal():
    with TestClient(app) as client:
        response = client.get("/advisory/proposals/pp_missing/execution-status")

    assert response.status_code == 404
    assert response.json()["detail"] == "PROPOSAL_NOT_FOUND"


def test_report_request_returns_404_for_missing_proposal():
    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/pp_missing/report-requests",
            json={
                "report_type": "PORTFOLIO_REVIEW",
                "requested_by": "advisor_1",
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "PROPOSAL_NOT_FOUND"


@pytest.mark.parametrize(
    ("update_status", "expected_handoff_status", "expected_state", "expected_correlation"),
    [
        (
            "ACCEPTED",
            "ACCEPTED",
            "EXECUTION_READY",
            "EXECUTION_REQUESTED_AND_ACCEPTED_EVENTS",
        ),
        (
            "PARTIALLY_EXECUTED",
            "PARTIALLY_EXECUTED",
            "EXECUTION_READY",
            "EXECUTION_REQUESTED_AND_PARTIAL_EXECUTION_EVENTS",
        ),
        (
            "REJECTED",
            "REJECTED",
            "REJECTED",
            "EXECUTION_REQUESTED_AND_REJECTED_EVENTS",
        ),
        (
            "CANCELLED",
            "CANCELLED",
            "CANCELLED",
            "EXECUTION_REQUESTED_AND_CANCELLED_EVENTS",
        ),
        (
            "EXPIRED",
            "EXPIRED",
            "EXPIRED",
            "EXECUTION_REQUESTED_AND_EXPIRED_EVENTS",
        ),
        (
            "EXECUTED",
            "EXECUTED",
            "EXECUTED",
            "EXECUTION_REQUESTED_AND_EXECUTED_EVENTS",
        ),
    ],
)
def test_execution_updates_reconcile_downstream_statuses(
    update_status: str,
    expected_handoff_status: str,
    expected_state: str,
    expected_correlation: str,
):
    with TestClient(app) as client:
        created = _create(client, f"lifecycle-execution-update-{update_status.lower()}")
        proposal_id = created["proposal"]["proposal_id"]
        _promote_to_execution_ready(client, proposal_id)
        _request_execution_handoff(client, proposal_id)
        occurred_at = _future_execution_timestamp()

        response = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": f"exec_update_{update_status.lower()}",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_001",
                "execution_provider": "lotus-manage",
                "update_status": update_status,
                "related_version_no": 1,
                "external_execution_id": "oms_fill_001",
                "occurred_at": occurred_at,
                "details": {"filled_quantity": "50", "remaining_quantity": "25"},
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["handoff_status"] == expected_handoff_status
        assert body["proposal"]["current_state"] == expected_state
        assert body["execution_request_id"] == "oms_req_001"
        assert body["execution_provider"] == "lotus-manage"
        assert body["external_execution_id"] == "oms_fill_001"
        assert body["latest_workflow_event"]["related_version_no"] == 1
        assert body["explanation"]["state_correlation"] == expected_correlation
        if update_status == "EXECUTED":
            assert body["executed_at"] == occurred_at
        else:
            assert body["executed_at"] is None


def test_execution_update_is_replay_safe_and_rejects_payload_conflicts():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-execution-update-idempotency")
        proposal_id = created["proposal"]["proposal_id"]
        _promote_to_execution_ready(client, proposal_id)
        _request_execution_handoff(client, proposal_id, external_request_id="oms_req_replay_001")

        payload = {
            "update_id": "exec_update_replay_001",
            "actor_id": "lotus-manage",
            "execution_request_id": "oms_req_replay_001",
            "execution_provider": "lotus-manage",
            "update_status": "ACCEPTED",
            "related_version_no": 1,
            "occurred_at": _future_execution_timestamp(),
            "details": {"desk": "SG"},
        }
        first = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json=payload,
        )
        second = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json=payload,
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()

        conflict = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json=payload | {"update_status": "PARTIALLY_EXECUTED"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "IDEMPOTENCY_KEY_CONFLICT: request hash mismatch"


def test_execution_update_requires_matching_handoff_identity():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-execution-update-match")
        proposal_id = created["proposal"]["proposal_id"]
        _promote_to_execution_ready(client, proposal_id)
        _request_execution_handoff(client, proposal_id, external_request_id="oms_req_match_001")

        mismatched_request = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_mismatch_request",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_other",
                "execution_provider": "lotus-manage",
                "update_status": "ACCEPTED",
            },
        )
        assert mismatched_request.status_code == 409
        assert mismatched_request.json()["detail"] == "EXECUTION_REQUEST_ID_MISMATCH"

        mismatched_provider = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_mismatch_provider",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_match_001",
                "execution_provider": "other-oms",
                "update_status": "ACCEPTED",
            },
        )
        assert mismatched_provider.status_code == 409
        assert mismatched_provider.json()["detail"] == "EXECUTION_PROVIDER_MISMATCH"


def test_execution_update_requires_prior_handoff_and_respects_terminal_state():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-execution-update-guardrails")
        proposal_id = created["proposal"]["proposal_id"]

        without_handoff = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_missing_handoff",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_missing",
                "execution_provider": "lotus-manage",
                "update_status": "ACCEPTED",
            },
        )
        assert without_handoff.status_code == 422
        assert without_handoff.json()["detail"] == "EXECUTION_HANDOFF_NOT_FOUND"

        _promote_to_execution_ready(client, proposal_id)
        _request_execution_handoff(client, proposal_id, external_request_id="oms_req_terminal_001")
        executed = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_terminal_executed",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_terminal_001",
                "execution_provider": "lotus-manage",
                "update_status": "EXECUTED",
                "external_execution_id": "oms_fill_terminal_001",
                "occurred_at": _future_execution_timestamp(),
            },
        )
        assert executed.status_code == 200

        after_terminal = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_after_terminal",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_terminal_001",
                "execution_provider": "lotus-manage",
                "update_status": "ACCEPTED",
            },
        )
        assert after_terminal.status_code == 409
        assert (
            after_terminal.json()["detail"] == "PROPOSAL_TERMINAL_STATE: execution update rejected"
        )


def test_execution_update_rejects_occurred_at_before_handoff():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-execution-update-timestamp")
        proposal_id = created["proposal"]["proposal_id"]
        _promote_to_execution_ready(client, proposal_id)
        handoff = _request_execution_handoff(
            client,
            proposal_id,
            external_request_id="oms_req_timestamp_001",
        )
        handoff_requested_at = handoff["latest_workflow_event"]["occurred_at"]

        response = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_before_handoff",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_timestamp_001",
                "execution_provider": "lotus-manage",
                "update_status": "ACCEPTED",
                "related_version_no": 1,
                "occurred_at": "2026-03-26T09:10:00+00:00",
            },
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "EXECUTION_UPDATE_OCCURRED_BEFORE_HANDOFF"

        status = client.get(f"/advisory/proposals/{proposal_id}/execution-status")
        assert status.status_code == 200
        assert status.json()["handoff_status"] == "REQUESTED"
        assert status.json()["handoff_requested_at"] == handoff_requested_at


def test_execution_handoff_is_replay_safe_with_idempotency_key():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-execution-handoff-idem-create")
        proposal_id = created["proposal"]["proposal_id"]
        _promote_to_execution_ready(client, proposal_id)

        payload = {
            "actor_id": "ops_001",
            "execution_provider": "lotus-manage",
            "expected_state": "EXECUTION_READY",
            "related_version_no": 1,
            "external_request_id": "oms_req_idem_001",
            "notes": {"channel": "OMS"},
        }
        first = client.post(
            f"/advisory/proposals/{proposal_id}/execution-handoffs",
            json=payload,
            headers={"Idempotency-Key": "handoff-idem-001"},
        )
        second = client.post(
            f"/advisory/proposals/{proposal_id}/execution-handoffs",
            json=payload,
            headers={"Idempotency-Key": "handoff-idem-001"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()

        timeline = client.get(f"/advisory/proposals/{proposal_id}/workflow-events")
        assert timeline.status_code == 200
        execution_requested = [
            event
            for event in timeline.json()["events"]
            if event["event_type"] == "EXECUTION_REQUESTED"
        ]
        assert len(execution_requested) == 1


def test_report_request_uses_requested_immutable_version(monkeypatch):
    seen: dict[str, object] = {}

    def _request_proposal_report_with_lotus_report(*, request):
        seen.update(request)
        return {
            "proposal": request["proposal"],
            "report_request_id": request["report_request_id"],
            "report_type": request["report_type"],
            "report_service": "lotus-report",
            "status": "READY",
            "generated_at": "2026-03-26T09:00:00+00:00",
            "report_reference_id": "lotus_report_artifact_002",
            "artifact_url": None,
            "explanation": {
                "ownership": "REPORTING_OWNED_BY_LOTUS_REPORT",
                "related_version_no": request["related_version_no"],
                "include_execution_summary": request["include_execution_summary"],
            },
        }

    monkeypatch.setattr(
        "src.api.main.request_proposal_report_with_lotus_report",
        _request_proposal_report_with_lotus_report,
        raising=False,
    )

    with TestClient(app) as client:
        created = _create(client, "lifecycle-report-version-anchor")
        proposal_id = created["proposal"]["proposal_id"]
        version_response = client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json={
                "created_by": "advisor_2",
                "simulate_request": {
                    **_base_create_payload()["simulate_request"],
                    "proposed_trades": [
                        {"side": "BUY", "instrument_id": "EQ_NEW", "quantity": "3"}
                    ],
                },
            },
        )
        assert version_response.status_code == 200

        report_response = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "CLIENT_PROPOSAL_SUMMARY",
                "requested_by": "advisor_1",
                "related_version_no": 1,
                "include_execution_summary": False,
            },
        )

    assert report_response.status_code == 200, report_response.text
    assert seen["related_version_no"] == 1
    assert seen["proposal_version"]["version_no"] == 1


def test_report_request_persists_workflow_event_and_replay_delivery_evidence(monkeypatch):
    def _request_proposal_report_with_lotus_report(*, request):
        return {
            "proposal": request["proposal"],
            "report_request_id": request["report_request_id"],
            "report_type": request["report_type"],
            "report_service": "lotus-report",
            "status": "READY",
            "generated_at": "2026-03-26T09:00:00+00:00",
            "report_reference_id": "lotus_report_artifact_delivery_001",
            "artifact_url": "https://lotus-report.local/artifacts/lotus_report_artifact_delivery_001",
            "explanation": {
                "ownership": "REPORTING_OWNED_BY_LOTUS_REPORT",
                "related_version_no": request["related_version_no"],
                "include_execution_summary": request["include_execution_summary"],
            },
        }

    monkeypatch.setattr(
        "src.api.main.request_proposal_report_with_lotus_report",
        _request_proposal_report_with_lotus_report,
        raising=False,
    )

    with TestClient(app) as client:
        created = _create(client, "lifecycle-report-replay-delivery")
        proposal_id = created["proposal"]["proposal_id"]
        _promote_to_execution_ready(client, proposal_id)
        _request_execution_handoff(
            client,
            proposal_id,
            external_request_id="oms_req_report_delivery_001",
        )
        executed = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_report_delivery",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_report_delivery_001",
                "execution_provider": "lotus-manage",
                "update_status": "EXECUTED",
                "related_version_no": 1,
                "external_execution_id": "oms_fill_report_delivery_001",
                "occurred_at": _future_execution_timestamp(seconds=2),
            },
        )
        assert executed.status_code == 200

        report_response = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "CLIENT_PROPOSAL_SUMMARY",
                "requested_by": "advisor_1",
                "related_version_no": 1,
                "include_execution_summary": True,
            },
        )
        timeline = client.get(f"/advisory/proposals/{proposal_id}/workflow-events")
        replay = client.get(f"/advisory/proposals/{proposal_id}/versions/1/replay-evidence")

    assert report_response.status_code == 200, report_response.text
    assert timeline.status_code == 200
    assert replay.status_code == 200
    timeline_body = timeline.json()
    replay_body = replay.json()
    report_events = [
        event for event in timeline_body["events"] if event["event_type"] == "REPORT_REQUESTED"
    ]
    assert len(report_events) == 1
    report_event = report_events[0]
    assert report_event["reason"]["report_type"] == "CLIENT_PROPOSAL_SUMMARY"
    assert report_event["reason"]["report_service"] == "lotus-report"
    assert report_event["reason"]["status"] == "READY"
    assert report_event["reason"]["include_execution_summary"] is True
    assert report_event["related_version_no"] == 1
    assert replay_body["evidence"]["delivery"]["execution"]["handoff_status"] == "EXECUTED"
    assert (
        replay_body["evidence"]["delivery"]["execution"]["execution_request_id"]
        == "oms_req_report_delivery_001"
    )
    assert replay_body["evidence"]["delivery"]["reporting"]["report_type"] == (
        "CLIENT_PROPOSAL_SUMMARY"
    )
    assert replay_body["evidence"]["delivery"]["reporting"]["report_request_id"].startswith("prr_")
    assert replay_body["evidence"]["delivery"]["reporting"]["report_service"] == "lotus-report"
    assert replay_body["evidence"]["delivery"]["reporting"]["requested_by"] == "advisor_1"


def test_report_request_includes_only_approved_reviewed_narrative_package(monkeypatch):
    seen: dict[str, Any] = {}

    def _request_proposal_report_with_lotus_report(*, request):
        seen.update(request)
        return {
            "proposal": request["proposal"],
            "report_request_id": request["report_request_id"],
            "report_type": request["report_type"],
            "report_service": "lotus-report",
            "status": "READY",
            "generated_at": "2026-03-26T09:00:00+00:00",
            "report_reference_id": "lotus_report_artifact_reviewed_narrative_001",
            "artifact_url": None,
            "explanation": {
                "ownership": "REPORTING_OWNED_BY_LOTUS_REPORT",
                "related_version_no": request["related_version_no"],
                "include_execution_summary": request["include_execution_summary"],
            },
        }

    monkeypatch.setattr(
        "src.api.main.request_proposal_report_with_lotus_report",
        _request_proposal_report_with_lotus_report,
        raising=False,
    )

    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals",
            json=_base_create_payload_with_narrative("pf_report_reviewed_narrative_001"),
            headers={"Idempotency-Key": "lifecycle-report-reviewed-narrative-create"},
        )
        assert created.status_code == 200
        proposal_id = created.json()["proposal"]["proposal_id"]
        version_no = created.json()["version"]["version_no"]
        narrative_id = created.json()["version"]["artifact"]["proposal_narrative"]["narrative_id"]

        review = client.post(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review",
            json={
                "action": "APPROVE",
                "reviewed_by": "compliance_001",
                "reason": "Evidence-grounded advisor-review narrative.",
            },
            headers={"Idempotency-Key": "lifecycle-report-reviewed-narrative-approve"},
        )
        assert review.status_code == 200

        report_response = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "CLIENT_PROPOSAL_SUMMARY",
                "requested_by": "advisor_1",
                "related_version_no": version_no,
                "include_execution_summary": True,
                "include_reviewed_narrative": True,
            },
        )
        delivery_summary = client.get(f"/advisory/proposals/{proposal_id}/delivery-summary")

    assert report_response.status_code == 200, report_response.text
    assert seen["include_reviewed_narrative"] is True
    package = seen["proposal_narrative_package"]
    assert package["package_status"] == "INCLUDED_REVIEWED_NARRATIVE"
    assert package["narrative_id"] == narrative_id
    assert package["review"]["review_state"] == "APPROVED_FOR_ADVISOR_USE"
    assert package["review"]["source_narrative_hash"].startswith("sha256:")
    assert package["source_lineage"]["request_hash"].startswith("sha256:")
    assert package["source_lineage"]["artifact_hash"].startswith("sha256:")
    assert package["sections"][0]["section_id"]
    assert package["sections"][0]["body"]
    assert "section_key" not in package["sections"][0]
    assert "text" not in package["sections"][0]
    assert package["execution_boundary"] is None
    report_body = report_response.json()
    response_package = report_body["explanation"]["proposal_narrative_package"]
    assert response_package["narrative_id"] == narrative_id
    assert response_package["review_state"] == "APPROVED_FOR_ADVISOR_USE"
    delivery_body = delivery_summary.json()
    assert delivery_body["reporting"]["include_reviewed_narrative"] is True
    assert delivery_body["reporting"]["proposal_narrative_package"]["narrative_id"] == narrative_id


def test_report_request_blocks_reviewed_narrative_without_approved_review(monkeypatch):
    def _request_proposal_report_with_lotus_report(*, request):
        raise AssertionError("lotus-report must not be called for an unreviewed narrative")

    monkeypatch.setattr(
        "src.api.main.request_proposal_report_with_lotus_report",
        _request_proposal_report_with_lotus_report,
        raising=False,
    )

    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals",
            json=_base_create_payload_with_narrative("pf_report_unreviewed_narrative_001"),
            headers={"Idempotency-Key": "lifecycle-report-unreviewed-narrative-create"},
        )
        assert created.status_code == 200
        proposal_id = created.json()["proposal"]["proposal_id"]

        blocked = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "CLIENT_PROPOSAL_SUMMARY",
                "requested_by": "advisor_1",
                "related_version_no": 1,
                "include_reviewed_narrative": True,
            },
        )

    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "PROPOSAL_REPORT_NARRATIVE_REVIEW_REQUIRED"


def test_delivery_summary_and_history_endpoints_return_persisted_delivery_projection(monkeypatch):
    def _request_proposal_report_with_lotus_report(*, request):
        return {
            "proposal": request["proposal"],
            "report_request_id": request["report_request_id"],
            "report_type": request["report_type"],
            "report_service": "lotus-report",
            "status": "READY",
            "generated_at": "2026-03-26T09:00:00+00:00",
            "report_reference_id": "lotus_report_artifact_delivery_projection_001",
            "artifact_url": None,
            "explanation": {
                "ownership": "REPORTING_OWNED_BY_LOTUS_REPORT",
                "related_version_no": request["related_version_no"],
                "include_execution_summary": request["include_execution_summary"],
            },
        }

    monkeypatch.setattr(
        "src.api.main.request_proposal_report_with_lotus_report",
        _request_proposal_report_with_lotus_report,
        raising=False,
    )

    with TestClient(app) as client:
        created = _create(client, "lifecycle-delivery-summary")
        proposal_id = created["proposal"]["proposal_id"]
        _promote_to_execution_ready(client, proposal_id)
        _request_execution_handoff(
            client,
            proposal_id,
            external_request_id="oms_req_delivery_summary_001",
        )
        executed = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_delivery_summary",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_delivery_summary_001",
                "execution_provider": "lotus-manage",
                "update_status": "EXECUTED",
                "related_version_no": 1,
                "external_execution_id": "oms_fill_delivery_summary_001",
                "occurred_at": _future_execution_timestamp(seconds=2),
            },
        )
        assert executed.status_code == 200
        report_response = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "PORTFOLIO_REVIEW",
                "requested_by": "advisor_77",
                "related_version_no": 1,
                "include_execution_summary": False,
            },
        )
        assert report_response.status_code == 200

        delivery_summary = client.get(f"/advisory/proposals/{proposal_id}/delivery-summary")
        delivery_history = client.get(f"/advisory/proposals/{proposal_id}/delivery-events")

    assert delivery_summary.status_code == 200
    assert delivery_history.status_code == 200
    summary_body = delivery_summary.json()
    history_body = delivery_history.json()
    assert summary_body["proposal"]["proposal_id"] == proposal_id
    assert summary_body["execution"]["handoff_status"] == "EXECUTED"
    assert summary_body["execution"]["execution_provider"] == "lotus-manage"
    assert summary_body["reporting"]["report_type"] == "PORTFOLIO_REVIEW"
    assert summary_body["reporting"]["requested_by"] == "advisor_77"
    assert summary_body["explanation"]["delivery_projection"] == (
        "LATEST_EXECUTION_AND_REPORTING_POSTURE"
    )
    assert history_body["proposal"]["proposal_id"] == proposal_id
    assert history_body["event_count"] == 3
    assert history_body["events"][0]["event_type"] == "EXECUTION_REQUESTED"
    assert history_body["events"][1]["event_type"] == "EXECUTED"
    assert history_body["events"][2]["event_type"] == "REPORT_REQUESTED"
    assert history_body["latest_event"]["event_type"] == "REPORT_REQUESTED"
    assert history_body["explanation"]["filter"] == "DELIVERY_ONLY"


def test_delivery_summary_and_history_return_404_for_missing_proposal():
    with TestClient(app) as client:
        summary = client.get("/advisory/proposals/pp_missing/delivery-summary")
        history = client.get("/advisory/proposals/pp_missing/delivery-events")

    assert summary.status_code == 404
    assert summary.json()["detail"] == "PROPOSAL_NOT_FOUND"
    assert history.status_code == 404
    assert history.json()["detail"] == "PROPOSAL_NOT_FOUND"


def test_persisted_read_surfaces_stay_aligned_on_latest_delivery_version(monkeypatch):
    def _request_proposal_report_with_lotus_report(*, request):
        return {
            "proposal": request["proposal"],
            "report_request_id": request["report_request_id"],
            "report_type": request["report_type"],
            "report_service": "lotus-report",
            "status": "READY",
            "generated_at": "2026-03-26T10:00:00+00:00",
            "report_reference_id": "lotus_report_artifact_latest_version_001",
            "artifact_url": None,
            "explanation": {
                "ownership": "REPORTING_OWNED_BY_LOTUS_REPORT",
                "related_version_no": request["related_version_no"],
                "include_execution_summary": request["include_execution_summary"],
            },
        }

    monkeypatch.setattr(
        "src.api.main.request_proposal_report_with_lotus_report",
        _request_proposal_report_with_lotus_report,
        raising=False,
    )

    with TestClient(app) as client:
        created = _create(client, "lifecycle-read-surface-latest-version")
        proposal_id = created["proposal"]["proposal_id"]
        versioned = client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json={
                "created_by": "advisor_2",
                "expected_current_version_no": 1,
                "simulate_request": _base_create_payload()["simulate_request"],
            },
        )
        assert versioned.status_code == 200
        assert versioned.json()["proposal"]["current_version_no"] == 2

        submitted = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "SUBMITTED_FOR_RISK_REVIEW",
                "actor_id": "advisor_2",
                "expected_state": "DRAFT",
                "reason": {"comment": "latest version delivery alignment"},
                "related_version_no": 2,
            },
            headers={"Idempotency-Key": "latest-version-risk-submit"},
        )
        assert submitted.status_code == 200
        risk_approved = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "RISK",
                "approved": True,
                "actor_id": "risk_approver",
                "expected_state": "RISK_REVIEW",
                "related_version_no": 2,
                "details": {"channel": "LATEST_VERSION_TEST"},
            },
            headers={"Idempotency-Key": "latest-version-risk-approval"},
        )
        assert risk_approved.status_code == 200
        client_consent = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "CLIENT_CONSENT",
                "approved": True,
                "actor_id": "client_approved",
                "expected_state": "AWAITING_CLIENT_CONSENT",
                "related_version_no": 2,
                "details": {"channel": "LATEST_VERSION_TEST"},
            },
            headers={"Idempotency-Key": "latest-version-client-consent"},
        )
        assert client_consent.status_code == 200

        handoff = client.post(
            f"/advisory/proposals/{proposal_id}/execution-handoffs",
            json={
                "actor_id": "ops_2",
                "execution_provider": "lotus-manage",
                "expected_state": "EXECUTION_READY",
                "related_version_no": 2,
                "external_request_id": "oms_req_latest_version_001",
                "notes": {"channel": "OMS"},
            },
            headers={"Idempotency-Key": "latest-version-handoff"},
        )
        assert handoff.status_code == 200

        executed = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_latest_version",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_latest_version_001",
                "execution_provider": "lotus-manage",
                "update_status": "EXECUTED",
                "related_version_no": 2,
                "external_execution_id": "oms_fill_latest_version_001",
                "occurred_at": _future_execution_timestamp(seconds=2),
            },
        )
        assert executed.status_code == 200

        reported = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "CLIENT_PROPOSAL_SUMMARY",
                "requested_by": "advisor_2",
                "related_version_no": 2,
                "include_execution_summary": True,
            },
        )
        assert reported.status_code == 200

        listed = client.get("/advisory/proposals?portfolio_id=pf_lifecycle_1&limit=100")
        detail = client.get(f"/advisory/proposals/{proposal_id}?include_evidence=false")
        version = client.get(f"/advisory/proposals/{proposal_id}/versions/2?include_evidence=false")
        timeline = client.get(f"/advisory/proposals/{proposal_id}/workflow-events")
        lineage = client.get(f"/advisory/proposals/{proposal_id}/lineage")
        approvals = client.get(f"/advisory/proposals/{proposal_id}/approvals")
        delivery_summary = client.get(f"/advisory/proposals/{proposal_id}/delivery-summary")
        delivery_history = client.get(f"/advisory/proposals/{proposal_id}/delivery-events")

    assert listed.status_code == 200
    list_item = next(item for item in listed.json()["items"] if item["proposal_id"] == proposal_id)
    assert detail.status_code == 200
    assert version.status_code == 200
    assert timeline.status_code == 200
    assert lineage.status_code == 200
    assert approvals.status_code == 200
    assert delivery_summary.status_code == 200
    assert delivery_history.status_code == 200

    detail_body = detail.json()
    version_body = version.json()
    timeline_body = timeline.json()
    lineage_body = lineage.json()
    approvals_body = approvals.json()
    delivery_summary_body = delivery_summary.json()
    delivery_history_body = delivery_history.json()

    assert list_item["current_version_no"] == 2
    assert detail_body["proposal"]["current_version_no"] == 2
    assert detail_body["current_version"]["version_no"] == 2
    assert version_body["version_no"] == 2
    assert lineage_body["latest_version_no"] == 2
    assert lineage_body["version_count"] == 2
    assert lineage_body["lineage_complete"] is True
    assert lineage_body["missing_version_numbers"] == []
    assert timeline_body["current_state"] == "EXECUTED"
    assert detail_body["proposal"]["current_state"] == "EXECUTED"
    assert delivery_summary_body["proposal"]["current_state"] == "EXECUTED"
    assert approvals_body["approval_count"] >= 2
    assert delivery_summary_body["execution"]["related_version_no"] == 2
    assert delivery_summary_body["execution"]["handoff_status"] == "EXECUTED"
    assert delivery_summary_body["reporting"]["related_version_no"] == 2
    assert delivery_summary_body["reporting"]["status"] == "READY"
    assert delivery_history_body["latest_event"]["event_type"] == "REPORT_REQUESTED"
    assert [event["event_type"] for event in delivery_history_body["events"]] == [
        "EXECUTION_REQUESTED",
        "EXECUTED",
        "REPORT_REQUESTED",
    ]


def test_multi_version_history_keeps_latest_delivery_and_approval_scope_isolated(monkeypatch):
    def _request_proposal_report_with_lotus_report(*, request):
        return {
            "proposal": request["proposal"],
            "report_request_id": request["report_request_id"],
            "report_type": request["report_type"],
            "report_service": "lotus-report",
            "status": "READY",
            "generated_at": "2026-03-26T10:00:00+00:00",
            "report_reference_id": "lotus_report_artifact_version_scope_001",
            "artifact_url": None,
            "explanation": {
                "ownership": "REPORTING_OWNED_BY_LOTUS_REPORT",
                "related_version_no": request["related_version_no"],
                "include_execution_summary": request["include_execution_summary"],
            },
        }

    monkeypatch.setattr(
        "src.api.main.request_proposal_report_with_lotus_report",
        _request_proposal_report_with_lotus_report,
        raising=False,
    )

    with TestClient(app) as client:
        created = _create(client, "lifecycle-version-scope")
        proposal_id = created["proposal"]["proposal_id"]
        versioned = client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json={
                "created_by": "advisor_2",
                "expected_current_version_no": 1,
                "simulate_request": _base_create_payload()["simulate_request"],
            },
        )
        assert versioned.status_code == 200

        submitted = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "SUBMITTED_FOR_RISK_REVIEW",
                "actor_id": "advisor_2",
                "expected_state": "DRAFT",
                "reason": {"comment": "latest version scoping"},
                "related_version_no": 2,
            },
            headers={"Idempotency-Key": "version-scope-risk-submit"},
        )
        assert submitted.status_code == 200
        risk_approved = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "RISK",
                "approved": True,
                "actor_id": "risk_approver",
                "expected_state": "RISK_REVIEW",
                "related_version_no": 2,
                "details": {"channel": "VERSION_SCOPE"},
            },
            headers={"Idempotency-Key": "version-scope-risk-approval"},
        )
        assert risk_approved.status_code == 200
        client_consent = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "CLIENT_CONSENT",
                "approved": True,
                "actor_id": "client_approved",
                "expected_state": "AWAITING_CLIENT_CONSENT",
                "related_version_no": 2,
                "details": {"channel": "VERSION_SCOPE"},
            },
            headers={"Idempotency-Key": "version-scope-client-consent"},
        )
        assert client_consent.status_code == 200
        handoff = client.post(
            f"/advisory/proposals/{proposal_id}/execution-handoffs",
            json={
                "actor_id": "ops_2",
                "execution_provider": "lotus-manage",
                "expected_state": "EXECUTION_READY",
                "related_version_no": 2,
                "external_request_id": "oms_req_version_scope_001",
                "notes": {"channel": "OMS"},
            },
            headers={"Idempotency-Key": "version-scope-handoff"},
        )
        assert handoff.status_code == 200
        executed = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_version_scope",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_version_scope_001",
                "execution_provider": "lotus-manage",
                "update_status": "EXECUTED",
                "related_version_no": 2,
                "external_execution_id": "oms_fill_version_scope_001",
                "occurred_at": _future_execution_timestamp(seconds=2),
            },
        )
        assert executed.status_code == 200
        reported = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "CLIENT_PROPOSAL_SUMMARY",
                "requested_by": "advisor_2",
                "related_version_no": 2,
                "include_execution_summary": True,
            },
        )
        assert reported.status_code == 200

        timeline = client.get(f"/advisory/proposals/{proposal_id}/workflow-events")
        approvals = client.get(f"/advisory/proposals/{proposal_id}/approvals")
        delivery_history = client.get(f"/advisory/proposals/{proposal_id}/delivery-events")
        lineage = client.get(f"/advisory/proposals/{proposal_id}/lineage")
        version_1_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/1/replay-evidence"
        )
        version_2_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/2/replay-evidence"
        )

    assert timeline.status_code == 200
    assert approvals.status_code == 200
    assert delivery_history.status_code == 200
    assert lineage.status_code == 200
    assert version_1_replay.status_code == 200
    assert version_2_replay.status_code == 200

    timeline_body = timeline.json()
    approvals_body = approvals.json()
    delivery_body = delivery_history.json()
    lineage_body = lineage.json()
    version_1_replay_body = version_1_replay.json()
    version_2_replay_body = version_2_replay.json()

    assert [item["version_no"] for item in lineage_body["versions"]] == [1, 2]
    created_events = [
        event for event in timeline_body["events"] if event["event_type"] == "CREATED"
    ]
    new_version_events = [
        event for event in timeline_body["events"] if event["event_type"] == "NEW_VERSION_CREATED"
    ]
    assert len(created_events) == 1
    assert created_events[0]["related_version_no"] == 1
    assert len(new_version_events) == 1
    assert new_version_events[0]["related_version_no"] == 2
    assert new_version_events[0]["to_state"] == "DRAFT"
    assert all(approval["related_version_no"] == 2 for approval in approvals_body["approvals"])
    assert all(event["related_version_no"] == 2 for event in delivery_body["events"])
    assert [event["event_type"] for event in delivery_body["events"]] == [
        "EXECUTION_REQUESTED",
        "EXECUTED",
        "REPORT_REQUESTED",
    ]
    assert version_1_replay_body["subject"]["proposal_version_no"] == 1
    assert version_2_replay_body["subject"]["proposal_version_no"] == 2


def test_new_version_requires_fresh_approvals_before_execution_handoff():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-version-approval-reset")
        proposal_id = created["proposal"]["proposal_id"]

        _promote_to_execution_ready(client, proposal_id)

        versioned = client.post(
            f"/advisory/proposals/{proposal_id}/versions",
            json={
                "created_by": "advisor_2",
                "expected_current_version_no": 1,
                "simulate_request": _base_create_payload()["simulate_request"],
            },
        )
        assert versioned.status_code == 200
        assert versioned.json()["proposal"]["current_version_no"] == 2
        assert versioned.json()["proposal"]["current_state"] == "DRAFT"
        assert versioned.json()["latest_workflow_event"]["event_type"] == "NEW_VERSION_CREATED"
        assert versioned.json()["latest_workflow_event"]["to_state"] == "DRAFT"

        handoff = client.post(
            f"/advisory/proposals/{proposal_id}/execution-handoffs",
            json={
                "actor_id": "ops_reset_001",
                "execution_provider": "lotus-manage",
                "expected_state": "EXECUTION_READY",
                "related_version_no": 2,
                "external_request_id": "oms_req_reset_001",
                "notes": {"channel": "OMS"},
            },
        )
        assert handoff.status_code == 409
        assert "STATE_CONFLICT" in handoff.json()["detail"]
        assert "expected_state mismatch" in handoff.json()["detail"]


def test_mixed_approval_routes_remain_version_scoped():
    def _request_proposal_report_with_lotus_report(*, request):
        return {
            "proposal": request["proposal"],
            "report_request_id": request["report_request_id"],
            "report_type": request["report_type"],
            "report_service": "lotus-report",
            "status": "READY",
            "generated_at": "2026-03-26T10:15:00+00:00",
            "report_reference_id": "lotus_report_artifact_mixed_routes_001",
            "artifact_url": None,
            "explanation": {
                "ownership": "REPORTING_OWNED_BY_LOTUS_REPORT",
                "related_version_no": request["related_version_no"],
                "include_execution_summary": request["include_execution_summary"],
            },
        }

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "src.api.main.request_proposal_report_with_lotus_report",
        _request_proposal_report_with_lotus_report,
        raising=False,
    )
    try:
        with TestClient(app) as client:
            created = _create(client, "lifecycle-version-mixed-routes")
            proposal_id = created["proposal"]["proposal_id"]

            _promote_to_execution_ready(client, proposal_id, route="compliance")

            versioned = client.post(
                f"/advisory/proposals/{proposal_id}/versions",
                json={
                    "created_by": "advisor_2",
                    "expected_current_version_no": 1,
                    "simulate_request": _base_create_payload()["simulate_request"],
                },
            )
            assert versioned.status_code == 200

            _promote_to_execution_ready(client, proposal_id, related_version_no=2, route="risk")

            handoff = client.post(
                f"/advisory/proposals/{proposal_id}/execution-handoffs",
                json={
                    "actor_id": "ops_mixed_001",
                    "execution_provider": "lotus-manage",
                    "expected_state": "EXECUTION_READY",
                    "related_version_no": 2,
                    "external_request_id": "oms_req_mixed_routes_001",
                    "notes": {"channel": "OMS"},
                },
            )
            assert handoff.status_code == 200

            executed = client.post(
                f"/advisory/proposals/{proposal_id}/execution-updates",
                json={
                    "update_id": "exec_update_mixed_routes",
                    "actor_id": "lotus-manage",
                    "execution_request_id": "oms_req_mixed_routes_001",
                    "execution_provider": "lotus-manage",
                    "update_status": "EXECUTED",
                    "related_version_no": 2,
                    "external_execution_id": "oms_fill_mixed_routes_001",
                    "occurred_at": _future_execution_timestamp(seconds=2),
                },
            )
            assert executed.status_code == 200

            reported = client.post(
                f"/advisory/proposals/{proposal_id}/report-requests",
                json={
                    "report_type": "CLIENT_PROPOSAL_SUMMARY",
                    "requested_by": "advisor_2",
                    "related_version_no": 2,
                    "include_execution_summary": True,
                },
            )
            assert reported.status_code == 200

            approvals = client.get(f"/advisory/proposals/{proposal_id}/approvals")
            timeline = client.get(f"/advisory/proposals/{proposal_id}/workflow-events")
            delivery_summary = client.get(f"/advisory/proposals/{proposal_id}/delivery-summary")
            delivery_history = client.get(f"/advisory/proposals/{proposal_id}/delivery-events")
    finally:
        monkeypatch.undo()

    assert approvals.status_code == 200
    assert timeline.status_code == 200
    assert delivery_summary.status_code == 200
    assert delivery_history.status_code == 200

    approvals_body = approvals.json()
    timeline_body = timeline.json()
    delivery_summary_body = delivery_summary.json()
    delivery_history_body = delivery_history.json()

    assert {approval["approval_type"] for approval in approvals_body["approvals"]} == {
        "COMPLIANCE",
        "RISK",
        "CLIENT_CONSENT",
    }
    assert {approval["related_version_no"] for approval in approvals_body["approvals"]} == {1, 2}
    assert any(
        event["event_type"] == "COMPLIANCE_APPROVED" and event["related_version_no"] == 1
        for event in timeline_body["events"]
    )
    assert any(
        event["event_type"] == "RISK_APPROVED" and event["related_version_no"] == 2
        for event in timeline_body["events"]
    )
    assert delivery_summary_body["execution"]["related_version_no"] == 2
    assert delivery_summary_body["execution"]["handoff_status"] == "EXECUTED"
    assert delivery_summary_body["reporting"]["related_version_no"] == 2
    assert delivery_summary_body["reporting"]["status"] == "READY"
    assert all(event["related_version_no"] == 2 for event in delivery_history_body["events"])
    assert [event["event_type"] for event in delivery_history_body["events"]] == [
        "EXECUTION_REQUESTED",
        "EXECUTED",
        "REPORT_REQUESTED",
    ]


def test_async_replay_evidence_includes_persisted_delivery_summary(monkeypatch):
    def _request_proposal_report_with_lotus_report(*, request):
        return {
            "proposal": request["proposal"],
            "report_request_id": request["report_request_id"],
            "report_type": request["report_type"],
            "report_service": "lotus-report",
            "status": "READY",
            "generated_at": "2026-03-26T10:00:00+00:00",
            "report_reference_id": "lotus_report_artifact_async_delivery_001",
            "artifact_url": None,
            "explanation": {
                "ownership": "REPORTING_OWNED_BY_LOTUS_REPORT",
                "related_version_no": request["related_version_no"],
                "include_execution_summary": request["include_execution_summary"],
            },
        }

    monkeypatch.setattr(
        "src.api.main.request_proposal_report_with_lotus_report",
        _request_proposal_report_with_lotus_report,
        raising=False,
    )

    with TestClient(app) as client:
        accepted = client.post(
            "/advisory/proposals/async",
            json=_base_create_payload("pf_async_delivery_replay_001"),
            headers={
                "Idempotency-Key": "lifecycle-async-delivery-replay",
                "X-Correlation-Id": "corr-lifecycle-async-delivery-replay",
            },
        )
        assert accepted.status_code == 202
        operation_id = accepted.json()["operation_id"]

        operation = client.get(f"/advisory/proposals/operations/{operation_id}")
        assert operation.status_code == 200
        operation_body = operation.json()
        proposal_id = operation_body["result"]["proposal"]["proposal_id"]

        _promote_to_execution_ready(client, proposal_id)
        _request_execution_handoff(
            client,
            proposal_id,
            external_request_id="oms_req_async_delivery_001",
        )
        executed = client.post(
            f"/advisory/proposals/{proposal_id}/execution-updates",
            json={
                "update_id": "exec_update_async_delivery",
                "actor_id": "lotus-manage",
                "execution_request_id": "oms_req_async_delivery_001",
                "execution_provider": "lotus-manage",
                "update_status": "EXECUTED",
                "related_version_no": 1,
                "external_execution_id": "oms_fill_async_delivery_001",
                "occurred_at": _future_execution_timestamp(seconds=2),
            },
        )
        assert executed.status_code == 200
        report_response = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "PORTFOLIO_REVIEW",
                "requested_by": "advisor_2",
                "related_version_no": 1,
                "include_execution_summary": False,
            },
        )
        assert report_response.status_code == 200

        async_replay = client.get(f"/advisory/proposals/operations/{operation_id}/replay-evidence")

    assert async_replay.status_code == 200
    async_body = async_replay.json()
    assert async_body["evidence"]["delivery"]["execution"]["handoff_status"] == "EXECUTED"
    assert async_body["evidence"]["delivery"]["reporting"]["report_type"] == "PORTFOLIO_REVIEW"
    assert async_body["evidence"]["delivery"]["reporting"]["requested_by"] == "advisor_2"


def test_report_request_returns_503_when_lotus_report_is_unavailable(monkeypatch):
    monkeypatch.delattr("src.api.main.request_proposal_report_with_lotus_report", raising=False)

    with TestClient(app) as client:
        created = _create(client, "lifecycle-report-unavailable")
        proposal_id = created["proposal"]["proposal_id"]
        response = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "PORTFOLIO_REVIEW",
                "requested_by": "advisor_1",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "LOTUS_REPORT_REQUEST_UNAVAILABLE"


def test_report_request_redacts_sensitive_lotus_report_unavailable_detail(monkeypatch):
    def _raise_sensitive_lotus_report_error(**_: Any):
        raise LotusReportUnavailableError("provider response included bearer token detail")

    monkeypatch.setattr(
        "src.api.proposals.routes_delivery.request_proposal_report",
        _raise_sensitive_lotus_report_error,
    )

    with TestClient(app) as client:
        created = _create(client, "lifecycle-report-sensitive-unavailable")
        proposal_id = created["proposal"]["proposal_id"]
        response = client.post(
            f"/advisory/proposals/{proposal_id}/report-requests",
            json={
                "report_type": "PORTFOLIO_REVIEW",
                "requested_by": "advisor_1",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "LOTUS_REPORT_REQUEST_UNAVAILABLE"


def test_workflow_rejection_path_transitions_to_rejected_terminal_state():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-create-rejected")
        proposal_id = created["proposal"]["proposal_id"]

        to_risk = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "SUBMITTED_FOR_RISK_REVIEW",
                "actor_id": "advisor_1",
                "expected_state": "DRAFT",
                "reason": {"comment": "risk first"},
            },
            headers={"Idempotency-Key": "rejected-risk-submit"},
        )
        assert to_risk.status_code == 200
        assert to_risk.json()["current_state"] == "RISK_REVIEW"

        rejected = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "RISK",
                "approved": False,
                "actor_id": "risk_user",
                "expected_state": "RISK_REVIEW",
                "details": {"comment": "client not suitable"},
            },
            headers={"Idempotency-Key": "rejected-risk-rejection"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["current_state"] == "REJECTED"
        assert rejected.json()["latest_workflow_event"]["event_type"] == "REJECTED"

        invalid_after_terminal = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "SUBMITTED_FOR_COMPLIANCE_REVIEW",
                "actor_id": "advisor_1",
                "expected_state": "REJECTED",
                "reason": {"comment": "should fail"},
            },
            headers={"Idempotency-Key": "rejected-invalid-transition"},
        )
        assert invalid_after_terminal.status_code == 422
        assert invalid_after_terminal.json()["detail"] == "INVALID_TRANSITION"


def test_approval_requires_matching_expected_state():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-create-7")
        proposal_id = created["proposal"]["proposal_id"]

        approval = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "CLIENT_CONSENT",
                "approved": True,
                "actor_id": "client_1",
                "expected_state": "RISK_REVIEW",
                "details": {},
            },
            headers={"Idempotency-Key": "approval-matching-state"},
        )
        assert approval.status_code == 409
        assert "STATE_CONFLICT" in approval.json()["detail"]


def test_lifecycle_router_returns_404_when_disabled(monkeypatch):
    monkeypatch.setenv("PROPOSAL_WORKFLOW_LIFECYCLE_ENABLED", "false")
    reset_proposal_workflow_service_for_tests()
    with TestClient(app) as client:
        response = client.get("/advisory/proposals")
    assert response.status_code == 404
    assert response.json()["detail"] == "PROPOSAL_WORKFLOW_LIFECYCLE_DISABLED"


def test_create_proposal_returns_422_when_simulation_flag_disabled():
    with TestClient(app) as client:
        payload = _base_create_payload()
        payload["simulate_request"]["options"] = {"enable_proposal_simulation": False}
        response = client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-create-disabled"},
        )
    assert response.status_code == 422
    assert "PROPOSAL_SIMULATION_DISABLED" in response.json()["detail"]


def test_get_and_get_version_return_404_for_missing_proposal():
    with TestClient(app) as client:
        proposal_response = client.get("/advisory/proposals/pp_missing_1")
        version_response = client.get("/advisory/proposals/pp_missing_1/versions/1")
    assert proposal_response.status_code == 404
    assert version_response.status_code == 404


def test_create_version_not_found_and_context_validation_paths():
    with TestClient(app) as client:
        version_payload = {
            "created_by": "advisor_2",
            "simulate_request": _base_create_payload()["simulate_request"],
        }

        missing = client.post("/advisory/proposals/pp_missing_2/versions", json=version_payload)
        assert missing.status_code == 404

        created = _create(client, "lifecycle-create-ctx-1")
        proposal_id = created["proposal"]["proposal_id"]
        version_payload["simulate_request"]["portfolio_snapshot"]["portfolio_id"] = "pf_other"
        invalid = client.post(f"/advisory/proposals/{proposal_id}/versions", json=version_payload)
        assert invalid.status_code == 422
        assert invalid.json()["detail"] == "PORTFOLIO_CONTEXT_MISMATCH"


def test_transition_and_approval_not_found_and_invalid_approval_state_paths():
    with TestClient(app) as client:
        missing_transition = client.post(
            "/advisory/proposals/pp_missing_3/transitions",
            json={
                "event_type": "SUBMITTED_FOR_RISK_REVIEW",
                "actor_id": "advisor_1",
                "expected_state": "DRAFT",
                "reason": {},
            },
            headers={"Idempotency-Key": "missing-proposal-transition"},
        )
        assert missing_transition.status_code == 404

        missing_approval = client.post(
            "/advisory/proposals/pp_missing_3/approvals",
            json={
                "approval_type": "RISK",
                "approved": True,
                "actor_id": "risk_1",
                "expected_state": "RISK_REVIEW",
                "details": {},
            },
            headers={"Idempotency-Key": "missing-proposal-approval"},
        )
        assert missing_approval.status_code == 404

        created = _create(client, "lifecycle-create-approval-422")
        proposal_id = created["proposal"]["proposal_id"]
        invalid_state = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "COMPLIANCE",
                "approved": True,
                "actor_id": "compliance_1",
                "expected_state": "DRAFT",
                "details": {},
            },
            headers={"Idempotency-Key": "invalid-approval-state"},
        )
        assert invalid_state.status_code == 422
        assert invalid_state.json()["detail"] == "INVALID_APPROVAL_STATE"


def test_support_endpoints_return_timeline_approvals_lineage_and_idempotency():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-support-1")
        proposal_id = created["proposal"]["proposal_id"]

        submit = client.post(
            f"/advisory/proposals/{proposal_id}/transitions",
            json={
                "event_type": "SUBMITTED_FOR_COMPLIANCE_REVIEW",
                "actor_id": "advisor_1",
                "expected_state": "DRAFT",
                "reason": {"comment": "submit"},
                "related_version_no": 1,
            },
            headers={"Idempotency-Key": "support-submit"},
        )
        assert submit.status_code == 200
        approval = client.post(
            f"/advisory/proposals/{proposal_id}/approvals",
            json={
                "approval_type": "COMPLIANCE",
                "approved": True,
                "actor_id": "compliance_1",
                "expected_state": "COMPLIANCE_REVIEW",
                "details": {"ticket": "cmp_1"},
                "related_version_no": 1,
            },
            headers={"Idempotency-Key": "support-approval"},
        )
        assert approval.status_code == 200

        timeline = client.get(f"/advisory/proposals/{proposal_id}/workflow-events")
        assert timeline.status_code == 200
        timeline_body = timeline.json()
        assert timeline_body["proposal"]["proposal_id"] == proposal_id
        assert len(timeline_body["events"]) >= 3
        assert timeline_body["event_count"] == len(timeline_body["events"])
        assert timeline_body["latest_event"]["event_type"] == "COMPLIANCE_APPROVED"
        assert timeline_body["events"][0]["event_type"] == "CREATED"

        approvals = client.get(f"/advisory/proposals/{proposal_id}/approvals")
        assert approvals.status_code == 200
        approvals_body = approvals.json()
        assert approvals_body["proposal"]["proposal_id"] == proposal_id
        assert approvals_body["approval_count"] == 1
        assert approvals_body["latest_approval_at"] is not None
        assert len(approvals_body["approvals"]) == 1
        assert approvals_body["approvals"][0]["approval_type"] == "COMPLIANCE"

        lineage = client.get(f"/advisory/proposals/{proposal_id}/lineage")
        assert lineage.status_code == 200
        lineage_body = lineage.json()
        assert lineage_body["proposal"]["proposal_id"] == proposal_id
        assert lineage_body["version_count"] == 1
        assert lineage_body["latest_version_no"] == 1
        assert lineage_body["lineage_complete"] is True
        assert lineage_body["missing_version_numbers"] == []
        assert lineage_body["versions"][0]["version_no"] == 1
        assert lineage_body["versions"][0]["artifact_hash"].startswith("sha256:")

        idem_lookup = client.get("/advisory/proposals/idempotency/lifecycle-support-1")
        assert idem_lookup.status_code == 200
        idem_body = idem_lookup.json()
        assert idem_body["idempotency_key"] == "lifecycle-support-1"
        assert idem_body["proposal_id"] == proposal_id
        assert idem_body["proposal_version_no"] == 1


def test_support_endpoints_404_for_missing_entities():
    with TestClient(app) as client:
        missing_timeline = client.get("/advisory/proposals/pp_missing_support/workflow-events")
        assert missing_timeline.status_code == 404

        missing_approvals = client.get("/advisory/proposals/pp_missing_support/approvals")
        assert missing_approvals.status_code == 404

        missing_lineage = client.get("/advisory/proposals/pp_missing_support/lineage")
        assert missing_lineage.status_code == 404

        missing_idempotency = client.get("/advisory/proposals/idempotency/missing-idem")
        assert missing_idempotency.status_code == 404
        assert missing_idempotency.json()["detail"] == "PROPOSAL_IDEMPOTENCY_KEY_NOT_FOUND"


def test_support_endpoints_return_404_when_support_apis_disabled(monkeypatch):
    monkeypatch.setenv("PROPOSAL_SUPPORT_APIS_ENABLED", "false")
    reset_proposal_workflow_service_for_tests()
    with TestClient(app) as client:
        created = _create(client, "lifecycle-support-disabled")
        proposal_id = created["proposal"]["proposal_id"]

        timeline = client.get(f"/advisory/proposals/{proposal_id}/workflow-events")
        assert timeline.status_code == 404
        assert timeline.json()["detail"] == "PROPOSAL_SUPPORT_APIS_DISABLED"


def test_async_create_and_lookup_by_operation_and_correlation():
    with TestClient(app) as client:
        payload = _base_create_payload()
        accepted = client.post(
            "/advisory/proposals/async",
            json=payload,
            headers={
                "Idempotency-Key": "lifecycle-async-create-1",
                "X-Correlation-Id": "corr-async-create-1",
            },
        )
        assert accepted.status_code == 202
        accepted_body = accepted.json()
        assert accepted_body["operation_type"] == "CREATE_PROPOSAL"
        assert accepted_body["correlation_id"] == "corr-async-create-1"
        assert accepted_body["attempt_count"] == 0
        assert accepted_body["max_attempts"] == 3

        operation_id = accepted_body["operation_id"]
        by_operation = client.get(f"/advisory/proposals/operations/{operation_id}")
        assert by_operation.status_code == 200
        op_body = by_operation.json()
        assert op_body["status"] == "SUCCEEDED"
        assert op_body["attempt_count"] == 1
        assert op_body["max_attempts"] == 3
        assert op_body["lease_expires_at"] is None
        assert op_body["result"]["proposal"]["proposal_id"].startswith("pp_")

        by_correlation = client.get(
            "/advisory/proposals/operations/by-correlation/corr-async-create-1"
        )
        assert by_correlation.status_code == 200
        assert by_correlation.json()["operation_id"] == operation_id

        missing_by_correlation = client.get(
            "/advisory/proposals/operations/by-correlation/corr-missing"
        )
        assert missing_by_correlation.status_code == 404
        assert missing_by_correlation.json()["detail"] == "PROPOSAL_ASYNC_OPERATION_NOT_FOUND"


def test_async_create_deduplicates_by_idempotency_key_and_rejects_payload_conflicts():
    with TestClient(app) as client:
        payload = _base_create_payload()
        first = client.post(
            "/advisory/proposals/async",
            json=payload,
            headers={
                "Idempotency-Key": "lifecycle-async-create-idem-1",
                "X-Correlation-Id": "corr-async-idem-1",
            },
        )
        assert first.status_code == 202
        first_body = first.json()

        duplicate = client.post(
            "/advisory/proposals/async",
            json=payload,
            headers={
                "Idempotency-Key": "lifecycle-async-create-idem-1",
                "X-Correlation-Id": "corr-async-idem-2",
            },
        )
        assert duplicate.status_code == 202
        duplicate_body = duplicate.json()
        assert duplicate_body["operation_id"] == first_body["operation_id"]
        assert duplicate_body["correlation_id"] == first_body["correlation_id"]

        conflicting_payload = _base_create_payload()
        conflicting_payload["metadata"]["title"] = "Conflicting async payload"
        conflict = client.post(
            "/advisory/proposals/async",
            json=conflicting_payload,
            headers={
                "Idempotency-Key": "lifecycle-async-create-idem-1",
                "X-Correlation-Id": "corr-async-idem-3",
            },
        )
        assert conflict.status_code == 409
        assert (
            conflict.json()["detail"] == "IDEMPOTENCY_KEY_CONFLICT: async submission hash mismatch"
        )


def test_async_create_treats_legacy_and_normalized_stateless_payloads_as_equivalent():
    with TestClient(app) as client:
        legacy_payload = _base_create_payload()
        normalized_payload = {
            "created_by": legacy_payload["created_by"],
            "metadata": legacy_payload["metadata"],
            "input_mode": "stateless",
            "stateless_input": {"simulate_request": legacy_payload["simulate_request"]},
        }

        first = client.post(
            "/advisory/proposals/async",
            json=legacy_payload,
            headers={
                "Idempotency-Key": "lifecycle-async-create-idem-shape-1",
                "X-Correlation-Id": "corr-async-shape-1",
            },
        )
        assert first.status_code == 202
        duplicate = client.post(
            "/advisory/proposals/async",
            json=normalized_payload,
            headers={
                "Idempotency-Key": "lifecycle-async-create-idem-shape-1",
                "X-Correlation-Id": "corr-async-shape-2",
            },
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["operation_id"] == first.json()["operation_id"]


def test_async_create_route_does_not_reschedule_replayed_submission() -> None:
    class _ReplayAwareService:
        def __init__(self) -> None:
            self.executions = 0

        def accept_create_proposal_async_submission(self, **kwargs):  # noqa: ANN003
            return (
                ProposalAsyncAcceptedResponse(
                    operation_id="pop_replayed_async",
                    operation_type="CREATE_PROPOSAL",
                    status="PENDING",
                    correlation_id="corr-replayed-async",
                    created_at="2026-04-07T00:00:00+00:00",
                    attempt_count=0,
                    max_attempts=3,
                    status_url="/advisory/proposals/operations/pop_replayed_async",
                ),
                False,
            )

        def execute_create_proposal_async(self, **kwargs):  # noqa: ANN003
            self.executions += 1

    service = _ReplayAwareService()
    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[proposals_router.get_proposal_workflow_service] = lambda: service
    try:
        with TestClient(app) as client:
            accepted = client.post(
                "/advisory/proposals/async",
                json=_base_create_payload(),
                headers={"Idempotency-Key": "lifecycle-async-route-replayed"},
            )
        assert accepted.status_code == 202
        assert accepted.json()["operation_id"] == "pop_replayed_async"
        assert service.executions == 0
    finally:
        app.dependency_overrides = original_overrides


def test_async_create_route_schedules_new_submission_once() -> None:
    class _ReplayAwareService:
        def __init__(self) -> None:
            self.executions = 0

        def accept_create_proposal_async_submission(self, **kwargs):  # noqa: ANN003
            return (
                ProposalAsyncAcceptedResponse(
                    operation_id="pop_new_async",
                    operation_type="CREATE_PROPOSAL",
                    status="PENDING",
                    correlation_id="corr-new-async",
                    created_at="2026-04-07T00:00:00+00:00",
                    attempt_count=0,
                    max_attempts=3,
                    status_url="/advisory/proposals/operations/pop_new_async",
                ),
                True,
            )

        def execute_create_proposal_async(self, **kwargs):  # noqa: ANN003
            self.executions += 1

    service = _ReplayAwareService()
    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[proposals_router.get_proposal_workflow_service] = lambda: service
    try:
        with TestClient(app) as client:
            accepted = client.post(
                "/advisory/proposals/async",
                json=_base_create_payload(),
                headers={"Idempotency-Key": "lifecycle-async-route-new"},
            )
        assert accepted.status_code == 202
        assert accepted.json()["operation_id"] == "pop_new_async"
        assert service.executions == 1
    finally:
        app.dependency_overrides = original_overrides


def test_proposal_version_and_async_replay_evidence_endpoints_return_normalized_lineage():
    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals",
            json=_base_create_payload(),
            headers={"Idempotency-Key": "lifecycle-replay-version-001"},
        )
        assert created.status_code == 200
        proposal_id = created.json()["proposal"]["proposal_id"]
        version_no = created.json()["version"]["version_no"]

        version_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/replay-evidence"
        )
        assert version_replay.status_code == 200
        version_body = version_replay.json()
        assert version_body["subject"]["scope"] == "PROPOSAL_VERSION"
        assert version_body["subject"]["proposal_id"] == proposal_id
        assert version_body["subject"]["proposal_version_no"] == version_no
        assert version_body["hashes"]["request_hash"] == created.json()["version"]["request_hash"]
        assert (
            version_body["hashes"]["simulation_hash"]
            == created.json()["version"]["simulation_hash"]
        )
        assert (
            version_body["resolved_context"]["portfolio_id"]
            == created.json()["proposal"]["portfolio_id"]
        )
        assert (
            version_body["evidence"]["proposal_decision_summary"]["top_level_status"]
            == created.json()["version"]["proposal_result"]["status"]
        )
        assert version_body["evidence"]["proposal_decision_summary"]["decision_status"]

        accepted = client.post(
            "/advisory/proposals/async",
            json=_base_create_payload(),
            headers={
                "Idempotency-Key": "lifecycle-replay-async-001",
                "X-Correlation-Id": "corr-lifecycle-replay-async-001",
            },
        )
        assert accepted.status_code == 202
        operation_id = accepted.json()["operation_id"]

        async_replay = client.get(f"/advisory/proposals/operations/{operation_id}/replay-evidence")

    assert async_replay.status_code == 200
    async_body = async_replay.json()
    assert async_body["subject"]["scope"] == "ASYNC_OPERATION"
    assert async_body["subject"]["operation_id"] == operation_id
    assert async_body["continuity"]["async_operation_id"] == operation_id
    assert async_body["continuity"]["correlation_id"] == "corr-lifecycle-replay-async-001"
    assert async_body["evidence"]["async_runtime"]["attempt_count"] >= 1
    assert async_body["evidence"]["proposal_decision_summary"]["decision_status"]


def test_persisted_proposal_narrative_review_is_idempotent_and_replayable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals",
            json=_base_create_payload_with_narrative("pf_lifecycle_narrative_review_001"),
            headers={"Idempotency-Key": "lifecycle-narrative-review-create"},
        )
        assert created.status_code == 200
        proposal_id = created.json()["proposal"]["proposal_id"]
        version_no = created.json()["version"]["version_no"]
        narrative_id = created.json()["version"]["artifact"]["proposal_narrative"]["narrative_id"]

        review_payload = {
            "action": "APPROVE",
            "reviewed_by": "compliance_001",
            "reason": "Evidence-grounded advisor-review narrative.",
        }
        first_review = client.post(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review",
            json=review_payload,
            headers={"Idempotency-Key": "lifecycle-narrative-review-approve"},
        )
        replayed_review = client.post(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review",
            json=review_payload,
            headers={"Idempotency-Key": "lifecycle-narrative-review-approve"},
        )

        def _fail_if_replay_regenerates_narrative(**kwargs):  # noqa: ANN003
            raise AssertionError("Replay must use persisted narrative evidence only")

        monkeypatch.setattr(
            "src.core.advisory.narrative.generate_proposal_narrative_draft_with_lotus_ai",
            _fail_if_replay_regenerates_narrative,
        )
        replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/replay-evidence"
        )

    assert first_review.status_code == 200
    assert replayed_review.status_code == 200
    first_body = first_review.json()
    replayed_body = replayed_review.json()
    assert first_body["latest_workflow_event"]["event_type"] == "NARRATIVE_REVIEWED"
    assert first_body["narrative_review"]["narrative_id"] == narrative_id
    assert first_body["narrative_review"]["review_state"] == "APPROVED_FOR_ADVISOR_USE"
    assert first_body["narrative_review"]["client_ready_status"] == "NOT_REQUESTED"
    assert (
        replayed_body["narrative_review"]["review_id"]
        == (first_body["narrative_review"]["review_id"])
    )
    assert replayed_body["narrative_review"]["replayed"] is True
    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["evidence"]["proposal_narrative"]["narrative_id"] == narrative_id
    assert (
        replay_body["evidence"]["proposal_narrative_review"]["review_id"]
        == (first_body["narrative_review"]["review_id"])
    )
    assert (
        replay_body["evidence"]["proposal_narrative_review"]["source_narrative_hash"]
        == first_body["narrative_review"]["source_narrative_hash"]
    )
    for material_field in (
        "review_id",
        "proposal_id",
        "proposal_version_no",
        "narrative_id",
        "action",
        "review_state",
        "client_ready_status",
        "reviewed_by",
        "reviewed_at",
        "reason",
        "source_narrative_hash",
        "replayed",
    ):
        assert material_field in first_body["narrative_review"]


def test_persisted_proposal_narrative_can_be_read_without_regeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals",
            json=_base_create_payload_with_narrative("pf_lifecycle_narrative_read_001"),
            headers={"Idempotency-Key": "lifecycle-narrative-read-create"},
        )
        assert created.status_code == 200
        proposal_id = created.json()["proposal"]["proposal_id"]
        version_no = created.json()["version"]["version_no"]
        narrative_id = created.json()["version"]["artifact"]["proposal_narrative"]["narrative_id"]

        review = client.post(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review",
            json={
                "action": "APPROVE",
                "reviewed_by": "compliance_001",
                "reason": "Evidence-grounded advisor-review narrative.",
            },
            headers={"Idempotency-Key": "lifecycle-narrative-read-review"},
        )
        assert review.status_code == 200

        def _fail_if_read_regenerates_narrative(**kwargs):  # noqa: ANN003
            raise AssertionError("Standalone narrative read must not regenerate text")

        monkeypatch.setattr(
            "src.core.advisory.narrative.generate_proposal_narrative_draft_with_lotus_ai",
            _fail_if_read_regenerates_narrative,
        )
        read_response = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/narrative"
        )

    assert read_response.status_code == 200
    body = read_response.json()
    assert body["proposal_narrative"]["narrative_id"] == narrative_id
    assert body["narrative_review"]["review_state"] == "APPROVED_FOR_ADVISOR_USE"
    assert body["source_narrative_hash"].startswith("sha256:")
    assert body["replay_evidence_path"].endswith(f"/versions/{version_no}/replay-evidence")
    assert body["read_posture"] == {
        "source": "IMMUTABLE_PROPOSAL_VERSION_ARTIFACT",
        "mutation_performed": False,
        "client_ready_publication": "GATED",
    }


def test_proposal_narrative_regeneration_returns_non_persisted_review_required_candidate() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals",
            json=_base_create_payload_with_narrative("pf_lifecycle_narrative_regen_001"),
            headers={"Idempotency-Key": "lifecycle-narrative-regenerate-create"},
        )
        assert created.status_code == 200
        proposal_id = created.json()["proposal"]["proposal_id"]
        version_no = created.json()["version"]["version_no"]
        current_narrative_id = created.json()["version"]["artifact"]["proposal_narrative"][
            "narrative_id"
        ]

        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/regenerate",
            json={
                "requested_by": "advisor_001",
                "reason": "Refresh advisor wording with a narrower section set.",
                "sections": ["EXECUTIVE_SUMMARY"],
            },
        )
        reread = client.get(f"/advisory/proposals/{proposal_id}/versions/{version_no}/narrative")

    assert response.status_code == 200
    body = response.json()
    assert body["current_narrative_id"] == current_narrative_id
    assert body["regenerated_narrative"]["audience"] == "ADVISOR_REVIEW"
    assert [section["section_key"] for section in body["regenerated_narrative"]["sections"]] == [
        "EXECUTIVE_SUMMARY"
    ]
    assert body["current_source_narrative_hash"].startswith("sha256:")
    assert body["regenerated_source_narrative_hash"].startswith("sha256:")
    assert body["materially_changed"] is True
    assert body["regeneration_posture"] == {
        "source": "IMMUTABLE_PROPOSAL_VERSION_ARTIFACT",
        "persistence_status": "NOT_PERSISTED_REVIEW_REQUIRED",
        "mutation_performed": False,
        "client_ready_publication": "GATED",
        "review_required_before_report_package": True,
    }
    assert reread.status_code == 200
    assert reread.json()["proposal_narrative"]["narrative_id"] == current_narrative_id


def test_standalone_narrative_read_and_regeneration_certify_missing_inputs() -> None:
    with TestClient(app) as client:
        created_without_narrative = client.post(
            "/advisory/proposals",
            json=_base_create_payload("pf_lifecycle_narrative_read_missing_001"),
            headers={"Idempotency-Key": "lifecycle-narrative-read-missing-create"},
        )
        assert created_without_narrative.status_code == 200
        proposal_id = created_without_narrative.json()["proposal"]["proposal_id"]

        missing_read = client.get(f"/advisory/proposals/{proposal_id}/versions/1/narrative")
        missing_regeneration = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/narrative/regenerate",
            json={
                "requested_by": "advisor_001",
                "reason": "No narrative exists on this version.",
            },
        )
        missing_proposal = client.get("/advisory/proposals/pp_missing/versions/1/narrative")

    assert missing_read.status_code == 422
    assert missing_read.json()["detail"] == "PROPOSAL_NARRATIVE_NOT_FOUND"
    assert missing_regeneration.status_code == 422
    assert missing_regeneration.json()["detail"] == "PROPOSAL_NARRATIVE_NOT_FOUND"
    assert missing_proposal.status_code == 404
    assert missing_proposal.json()["detail"] == "PROPOSAL_NOT_FOUND"


def test_narrative_review_blocks_client_ready_release_without_approval() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals",
            json=_base_create_payload_with_narrative("pf_lifecycle_narrative_reject_001"),
            headers={"Idempotency-Key": "lifecycle-narrative-reject-create"},
        )
        assert created.status_code == 200
        proposal_id = created.json()["proposal"]["proposal_id"]
        version_no = created.json()["version"]["version_no"]

        review = client.post(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review",
            json={
                "action": "REJECT",
                "reviewed_by": "compliance_001",
                "reason": "Rejected narrative cannot be released as client-ready.",
                "client_ready_release_requested": True,
            },
            headers={"Idempotency-Key": "lifecycle-narrative-reject-review"},
        )

    assert review.status_code == 200
    body = review.json()
    assert body["narrative_review"]["review_state"] == "REJECTED"
    assert body["narrative_review"]["client_ready_status"] == "BLOCKED_REVIEW_REQUIRED"


def test_narrative_review_certifies_404_409_and_missing_narrative_behavior() -> None:
    with TestClient(app) as client:
        created_without_narrative = client.post(
            "/advisory/proposals",
            json=_base_create_payload("pf_lifecycle_narrative_missing_001"),
            headers={"Idempotency-Key": "lifecycle-narrative-missing-create"},
        )
        assert created_without_narrative.status_code == 200
        proposal_without_narrative_id = created_without_narrative.json()["proposal"]["proposal_id"]

        missing_narrative = client.post(
            (f"/advisory/proposals/{proposal_without_narrative_id}/versions/1/narrative/review"),
            json={
                "action": "APPROVE",
                "reviewed_by": "compliance_001",
                "reason": "No narrative exists on this version.",
            },
            headers={"Idempotency-Key": "lifecycle-narrative-missing-review"},
        )

        missing_proposal = client.post(
            "/advisory/proposals/pp_missing/versions/1/narrative/review",
            json={
                "action": "APPROVE",
                "reviewed_by": "compliance_001",
                "reason": "Missing proposal.",
            },
            headers={"Idempotency-Key": "lifecycle-narrative-missing-proposal-review"},
        )

        created = client.post(
            "/advisory/proposals",
            json=_base_create_payload_with_narrative("pf_lifecycle_narrative_conflict_001"),
            headers={"Idempotency-Key": "lifecycle-narrative-conflict-create"},
        )
        assert created.status_code == 200
        proposal_id = created.json()["proposal"]["proposal_id"]
        version_no = created.json()["version"]["version_no"]
        route = f"/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review"
        first_review = client.post(
            route,
            json={
                "action": "APPROVE",
                "reviewed_by": "compliance_001",
                "reason": "Evidence-grounded advisor-review narrative.",
            },
            headers={"Idempotency-Key": "lifecycle-narrative-review-conflict"},
        )
        conflict = client.post(
            route,
            json={
                "action": "REQUEST_REGENERATION",
                "reviewed_by": "compliance_001",
                "reason": "Changed payload must not replay.",
                "replacement_narrative_id": "pn_replacement_001",
            },
            headers={"Idempotency-Key": "lifecycle-narrative-review-conflict"},
        )

    assert missing_narrative.status_code == 422
    assert missing_narrative.json()["detail"] == "PROPOSAL_NARRATIVE_NOT_FOUND"
    assert missing_proposal.status_code == 404
    assert missing_proposal.json()["detail"] == "PROPOSAL_NOT_FOUND"
    assert first_review.status_code == 200
    assert conflict.status_code == 409
    assert "IDEMPOTENCY_KEY_CONFLICT" in conflict.json()["detail"]


def test_async_and_proposal_replay_evidence_stay_hash_aligned():
    with TestClient(app) as client:
        accepted = client.post(
            "/advisory/proposals/async",
            json=_base_create_payload("pf_async_replay_alignment_001"),
            headers={
                "Idempotency-Key": "lifecycle-replay-async-alignment-001",
                "X-Correlation-Id": "corr-lifecycle-replay-async-alignment-001",
            },
        )
        assert accepted.status_code == 202
        operation_id = accepted.json()["operation_id"]

        operation = client.get(f"/advisory/proposals/operations/{operation_id}")
        assert operation.status_code == 200
        operation_body = operation.json()
        proposal_id = operation_body["result"]["proposal"]["proposal_id"]
        proposal_version_no = operation_body["result"]["version"]["version_no"]

        async_replay = client.get(f"/advisory/proposals/operations/{operation_id}/replay-evidence")
        proposal_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{proposal_version_no}/replay-evidence"
        )

    assert async_replay.status_code == 200
    assert proposal_replay.status_code == 200
    async_body = async_replay.json()
    proposal_body = proposal_replay.json()
    assert async_body["subject"]["proposal_id"] == proposal_id
    assert async_body["subject"]["proposal_version_no"] == proposal_version_no
    assert async_body["hashes"]["request_hash"] == proposal_body["hashes"]["request_hash"]
    assert async_body["hashes"]["simulation_hash"] == proposal_body["hashes"]["simulation_hash"]
    assert async_body["hashes"]["artifact_hash"] == proposal_body["hashes"]["artifact_hash"]
    assert async_body["resolved_context"] == proposal_body["resolved_context"]
    assert async_body["continuity"]["correlation_id"] == "corr-lifecycle-replay-async-alignment-001"
    assert async_body["continuity"]["async_operation_id"] == operation_id
    assert (
        async_body["evidence"]["proposal_decision_summary"]
        == proposal_body["evidence"]["proposal_decision_summary"]
    )


def test_proposal_and_async_replay_evidence_preserve_proposal_alternatives():
    payload = _base_create_payload("pf_async_alt_replay_001")
    payload["simulate_request"]["alternatives_request"] = {
        "enabled": True,
        "objectives": ["LOWER_TURNOVER"],
        "selected_alternative_id": "alt_lower_turnover_pf_async_alt_replay_001_eq_new",
        "include_rejected_candidates": True,
    }

    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-alt-replay-create"},
        )
        assert created.status_code == 200
        proposal_id = created.json()["proposal"]["proposal_id"]
        version_no = created.json()["version"]["version_no"]

        version_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/replay-evidence"
        )

        accepted = client.post(
            "/advisory/proposals/async",
            json=payload,
            headers={
                "Idempotency-Key": "lifecycle-alt-replay-async",
                "X-Correlation-Id": "corr-lifecycle-alt-replay-async",
            },
        )
        assert accepted.status_code == 202
        operation_id = accepted.json()["operation_id"]
        async_replay = client.get(f"/advisory/proposals/operations/{operation_id}/replay-evidence")

    assert version_replay.status_code == 200
    assert async_replay.status_code == 200
    version_body = version_replay.json()
    async_body = async_replay.json()
    assert (
        version_body["evidence"]["proposal_alternatives"]["selected_alternative_id"]
        == "alt_lower_turnover_pf_async_alt_replay_001_eq_new"
    )
    assert (
        async_body["evidence"]["proposal_alternatives"]["selected_alternative_id"]
        == "alt_lower_turnover_pf_async_alt_replay_001_eq_new"
    )


def test_proposal_and_async_replay_evidence_preserve_risk_lens(monkeypatch):
    monkeypatch.setattr(
        "src.core.advisory.orchestration.enrich_with_lotus_risk",
        lambda **kwargs: _risk_enriched_result(kwargs["proposal_result"]),
    )

    with TestClient(app) as client:
        created = _create(client, "lifecycle-risk-replay-create")
        proposal_id = created["proposal"]["proposal_id"]
        version_no = created["version"]["version_no"]

        version_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{version_no}/replay-evidence"
        )
        accepted = client.post(
            "/advisory/proposals/async",
            json=_base_create_payload("pf_async_risk_replay_001"),
            headers={
                "Idempotency-Key": "lifecycle-risk-replay-async",
                "X-Correlation-Id": "corr-lifecycle-risk-replay-async",
            },
        )
        operation_id = accepted.json()["operation_id"]
        async_replay = client.get(f"/advisory/proposals/operations/{operation_id}/replay-evidence")

    assert version_replay.status_code == 200
    assert async_replay.status_code == 200
    version_body = version_replay.json()
    async_body = async_replay.json()
    assert version_body["evidence"]["risk_lens"]["source_service"] == "lotus-risk"
    assert version_body["evidence"]["risk_lens"]["risk_proxy"]["hhi_delta"] == 1600.0
    assert async_body["evidence"]["risk_lens"]["source_service"] == "lotus-risk"
    assert async_body["evidence"]["risk_lens"]["risk_proxy"]["hhi_delta"] == 1600.0
    assert (
        version_body["evidence"]["proposal_decision_summary"]["risk_posture"]["status"]
        == "AVAILABLE"
    )
    assert (
        async_body["evidence"]["proposal_decision_summary"]["risk_posture"]["status"] == "AVAILABLE"
    )


def test_async_create_version_and_lookup():
    with TestClient(app) as client:
        created = _create(client, "lifecycle-async-version-base")
        proposal_id = created["proposal"]["proposal_id"]
        payload = {
            "created_by": "advisor_2",
            "simulate_request": _base_create_payload()["simulate_request"],
        }
        payload["simulate_request"]["proposed_trades"] = [
            {"side": "BUY", "instrument_id": "EQ_NEW", "quantity": "4"}
        ]
        accepted = client.post(
            f"/advisory/proposals/{proposal_id}/versions/async",
            json=payload,
            headers={"X-Correlation-Id": "corr-async-version-1"},
        )
        assert accepted.status_code == 202
        accepted_body = accepted.json()
        assert accepted_body["attempt_count"] == 0
        assert accepted_body["max_attempts"] == 3
        operation_id = accepted_body["operation_id"]

        operation = client.get(f"/advisory/proposals/operations/{operation_id}")
        assert operation.status_code == 200
        body = operation.json()
        assert body["operation_type"] == "CREATE_PROPOSAL_VERSION"
        assert body["status"] == "SUCCEEDED"
        assert body["attempt_count"] == 1
        assert body["max_attempts"] == 3
        assert body["lease_expires_at"] is None
        assert body["result"]["proposal"]["current_version_no"] == 2


def test_async_operation_read_surfaces_stay_aligned_with_latest_version_result():
    def _await_async_result(client: TestClient, operation_id: str) -> dict[str, Any]:
        for _ in range(10):
            operation = client.get(f"/advisory/proposals/operations/{operation_id}")
            assert operation.status_code == 200
            body = operation.json()
            if body["status"] == "SUCCEEDED":
                return body
            assert body["status"] != "FAILED"
            time.sleep(0.01)
        pytest.fail(f"{operation_id}: async operation did not finish in time")

    with TestClient(app) as client:
        accepted = client.post(
            "/advisory/proposals/async",
            json=_base_create_payload("pf_async_surface_alignment_001"),
            headers={
                "Idempotency-Key": "async-surface-alignment-create-001",
                "X-Correlation-Id": "corr-async-surface-alignment-create-001",
            },
        )
        assert accepted.status_code == 202
        create_accepted_body = accepted.json()
        create_operation_id = create_accepted_body["operation_id"]

        create_operation_body = _await_async_result(client, create_operation_id)
        proposal_id = create_operation_body["result"]["proposal"]["proposal_id"]
        create_version_no = create_operation_body["result"]["version"]["version_no"]

        create_by_correlation = client.get(
            "/advisory/proposals/operations/by-correlation/corr-async-surface-alignment-create-001"
        )
        create_replay = client.get(
            f"/advisory/proposals/operations/{create_operation_id}/replay-evidence"
        )
        create_version_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{create_version_no}/replay-evidence"
        )

        version_payload = {
            "created_by": "advisor_async_surface_alignment",
            "expected_current_version_no": create_version_no,
            "simulate_request": _base_create_payload("pf_async_surface_alignment_001")[
                "simulate_request"
            ],
        }
        version_payload["simulate_request"]["proposed_trades"] = [
            {"side": "BUY", "instrument_id": "EQ_NEW", "quantity": "4"}
        ]
        accepted_version = client.post(
            f"/advisory/proposals/{proposal_id}/versions/async",
            json=version_payload,
            headers={"X-Correlation-Id": "corr-async-surface-alignment-version-001"},
        )
        assert accepted_version.status_code == 202
        version_accepted_body = accepted_version.json()
        version_operation_id = version_accepted_body["operation_id"]

        version_operation_body = _await_async_result(client, version_operation_id)
        current_version_no = version_operation_body["result"]["version"]["version_no"]
        version_by_correlation = client.get(
            "/advisory/proposals/operations/by-correlation/corr-async-surface-alignment-version-001"
        )
        version_replay = client.get(
            f"/advisory/proposals/operations/{version_operation_id}/replay-evidence"
        )
        proposal_detail = client.get(f"/advisory/proposals/{proposal_id}?include_evidence=false")
        current_version = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{current_version_no}?include_evidence=false"
        )
        current_version_replay = client.get(
            f"/advisory/proposals/{proposal_id}/versions/{current_version_no}/replay-evidence"
        )

    assert create_by_correlation.status_code == 200
    assert create_replay.status_code == 200
    assert create_version_replay.status_code == 200
    assert create_operation_body["status"] == "SUCCEEDED"
    assert create_by_correlation.json()["operation_id"] == create_operation_id
    assert create_replay.json()["continuity"]["correlation_id"] == (
        "corr-async-surface-alignment-create-001"
    )
    assert create_replay.json()["subject"]["proposal_id"] == proposal_id
    assert create_replay.json()["subject"]["proposal_version_no"] == create_version_no
    assert (
        create_replay.json()["hashes"]["request_hash"]
        == (create_version_replay.json()["hashes"]["request_hash"])
    )
    assert (
        create_replay.json()["hashes"]["simulation_hash"]
        == (create_version_replay.json()["hashes"]["simulation_hash"])
    )
    assert (
        create_replay.json()["resolved_context"] == create_version_replay.json()["resolved_context"]
    )

    assert version_by_correlation.status_code == 200
    assert version_replay.status_code == 200
    assert proposal_detail.status_code == 200
    assert current_version.status_code == 200
    assert current_version_replay.status_code == 200
    assert version_operation_body["status"] == "SUCCEEDED"
    assert version_by_correlation.json()["operation_id"] == version_operation_id
    assert proposal_detail.json()["proposal"]["current_version_no"] == current_version_no == 2
    assert current_version.json()["version_no"] == current_version_no
    assert version_replay.json()["continuity"]["correlation_id"] == (
        "corr-async-surface-alignment-version-001"
    )
    assert version_replay.json()["continuity"]["async_operation_id"] == version_operation_id
    assert version_replay.json()["subject"]["proposal_id"] == proposal_id
    assert version_replay.json()["subject"]["proposal_version_no"] == current_version_no
    assert (
        version_replay.json()["hashes"]["request_hash"]
        == (current_version_replay.json()["hashes"]["request_hash"])
    )
    assert (
        version_replay.json()["hashes"]["simulation_hash"]
        == (current_version_replay.json()["hashes"]["simulation_hash"])
    )
    assert (
        version_replay.json()["resolved_context"]
        == current_version_replay.json()["resolved_context"]
    )


def test_async_create_version_route_does_not_reschedule_replayed_submission() -> None:
    class _ReplayAwareService:
        def __init__(self) -> None:
            self.executions = 0

        def accept_create_version_async_submission(self, **kwargs):  # noqa: ANN003
            return (
                ProposalAsyncAcceptedResponse(
                    operation_id="pop_replayed_version_async",
                    operation_type="CREATE_PROPOSAL_VERSION",
                    status="PENDING",
                    correlation_id="corr-replayed-version-async",
                    created_at="2026-04-07T00:00:00+00:00",
                    attempt_count=0,
                    max_attempts=3,
                    status_url="/advisory/proposals/operations/pop_replayed_version_async",
                ),
                False,
            )

        def execute_create_version_async(self, **kwargs):  # noqa: ANN003
            self.executions += 1

    service = _ReplayAwareService()
    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[proposals_router.get_proposal_workflow_service] = lambda: service
    try:
        with TestClient(app) as client:
            accepted = client.post(
                "/advisory/proposals/pp_replayed/versions/async",
                json={
                    "created_by": "advisor_2",
                    "simulate_request": _base_create_payload()["simulate_request"],
                },
                headers={"X-Correlation-Id": "corr-replayed-version-async"},
            )
        assert accepted.status_code == 202
        assert accepted.json()["operation_id"] == "pop_replayed_version_async"
        assert service.executions == 0
    finally:
        app.dependency_overrides = original_overrides


def test_async_create_version_route_maps_correlation_conflict_to_409() -> None:
    class _ConflictService:
        def accept_create_version_async_submission(self, **kwargs):  # noqa: ANN003
            raise ProposalIdempotencyConflictError(
                "CORRELATION_ID_CONFLICT: async version submission mismatch"
            )

    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[proposals_router.get_proposal_workflow_service] = lambda: (
        _ConflictService()
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/advisory/proposals/pp_conflict/versions/async",
                json={
                    "created_by": "advisor_2",
                    "simulate_request": _base_create_payload()["simulate_request"],
                },
                headers={"X-Correlation-Id": "corr-conflict-version-async"},
            )
        assert response.status_code == 409
        assert (
            response.json()["detail"]
            == "CORRELATION_ID_CONFLICT: async version submission mismatch"
        )
    finally:
        app.dependency_overrides = original_overrides


def test_async_operation_endpoints_return_404_when_disabled(monkeypatch):
    monkeypatch.setenv("PROPOSAL_ASYNC_OPERATIONS_ENABLED", "false")
    reset_proposal_workflow_service_for_tests()
    with TestClient(app) as client:
        payload = _base_create_payload()
        response = client.post(
            "/advisory/proposals/async",
            json=payload,
            headers={"Idempotency-Key": "lifecycle-async-disabled"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "PROPOSAL_ASYNC_OPERATIONS_DISABLED"


def test_async_operation_lookup_returns_404_for_missing_operation():
    with TestClient(app) as client:
        missing = client.get("/advisory/proposals/operations/pop_missing")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "PROPOSAL_ASYNC_OPERATION_NOT_FOUND"


def test_transition_maps_idempotency_conflict_to_409():
    detail = "IDEMPOTENCY_KEY_CONFLICT: request hash mismatch"

    class _ConflictService:
        def transition_state(self, **kwargs):  # noqa: ANN003
            raise ProposalIdempotencyConflictError(detail)

    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[proposals_router.get_proposal_workflow_service] = lambda: (
        _ConflictService()
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/advisory/proposals/pp_conflict/transitions",
                json={
                    "event_type": "SUBMITTED_FOR_RISK_REVIEW",
                    "actor_id": "advisor_1",
                    "expected_state": "DRAFT",
                    "reason": {},
                },
                headers={"Idempotency-Key": "transition-conflict"},
            )
        assert response.status_code == 409
        assert "IDEMPOTENCY_KEY_CONFLICT" in response.json()["detail"]
    finally:
        app.dependency_overrides = original_overrides


def test_approval_maps_idempotency_conflict_to_409():
    detail = "IDEMPOTENCY_KEY_CONFLICT: request hash mismatch"

    class _ConflictService:
        def record_approval(self, **kwargs):  # noqa: ANN003
            raise ProposalIdempotencyConflictError(detail)

    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[proposals_router.get_proposal_workflow_service] = lambda: (
        _ConflictService()
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/advisory/proposals/pp_conflict/approvals",
                json={
                    "approval_type": "RISK",
                    "approved": True,
                    "actor_id": "risk_1",
                    "expected_state": "RISK_REVIEW",
                    "details": {},
                },
                headers={"Idempotency-Key": "approval-conflict"},
            )
        assert response.status_code == 409
        assert "IDEMPOTENCY_KEY_CONFLICT" in response.json()["detail"]
    finally:
        app.dependency_overrides = original_overrides
