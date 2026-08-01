from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.proposals import router as proposals_router
from src.api.proposals.policy_control_principal import (
    ADVISOR_ROLE,
    COMPLIANCE_REVIEWER_ROLE,
    POLICY_CHECKER_ROLE,
    POLICY_CONTROL_ACTOR_MISMATCH,
    POLICY_CONTROL_PRINCIPAL_INVALID,
    POLICY_CONTROL_PRINCIPAL_REQUIRED,
    POLICY_CONTROL_SCOPE_FORBIDDEN,
    POLICY_CONTROL_SCOPE_REQUIRED,
    POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
    POLICY_EVALUATION_FINALIZE_CAPABILITY,
    POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY,
    POLICY_EVALUATION_REVIEW_EVENT_CAPABILITY,
    POLICY_EVALUATION_SIGN_OFF_CAPABILITY,
    POLICY_PACK_ACTIVATE_CAPABILITY,
    POLICY_PACK_VALIDATE_CAPABILITY,
    POLICY_STEWARD_ROLE,
)
from src.api.proposals.policy_evaluation_responses import (
    POLICY_AI_EVIDENCE_RESPONSES,
    POLICY_EVALUATION_CREATE_RESPONSES,
    POLICY_REPORT_PACKAGE_RESPONSES,
)
from src.core.policy_packs import (
    get_policy_pack_version,
    reset_policy_evaluation_store_for_tests,
    reset_policy_pack_catalog_for_tests,
)
from src.core.policy_packs.ai_models import (
    LotusAIPolicyEvidenceUnavailableError,
    PolicyAiEvidenceDraft,
)
from src.core.policy_packs.workflow_projection import workflow_lineage_metadata
from src.core.proposals.models import ProposalRecord, ProposalVersionRecord
from src.core.proposals.response_models import ProposalReportResponse
from src.infrastructure.proposals.in_memory import InMemoryProposalRepository
from src.integrations.lotus_report import LotusReportUnavailableError
from src.runtime.policy_evaluation_clients import (
    set_policy_ai_evidence_client_for_tests,
    set_policy_report_package_client_for_tests,
)

NOW = datetime(2026, 5, 26, 9, 0, tzinfo=UTC)


class _FakePolicyReportPackageClient:
    def __init__(self, handler):
        self._handler = handler

    def request_policy_sign_off_report_package(self, *, request: dict) -> ProposalReportResponse:
        return ProposalReportResponse.model_validate(self._handler(request=request))


class _FakePolicyAiEvidenceClient:
    def __init__(self, handler):
        self._handler = handler

    def generate_policy_evidence_summary(self, **kwargs) -> PolicyAiEvidenceDraft:
        return self._handler(**kwargs)


def setup_function() -> None:
    set_policy_report_package_client_for_tests(None)
    set_policy_ai_evidence_client_for_tests(None)
    reset_policy_pack_catalog_for_tests()
    reset_policy_evaluation_store_for_tests()


def _base_evidence_bundle() -> dict:
    return {
        "context_resolution": {
            "as_of_date": "2026-05-26",
            "advisory_policy_context": {
                "household_id": "HH-PB-001",
                "jurisdiction": "SG",
                "client_classification": "ACCREDITED_INVESTOR",
                "booking_center_code": "SG",
                "legal_entity_code": "REFERENCE",
                "account_id": "ACCT-PB-001",
                "time_horizon": "5Y",
                "liquidity_need": "MEDIUM",
                "mandate_id": "MANDATE-BALANCED-001",
                "objectives": ["capital_preservation", "balanced_growth"],
                "restrictions": ["no_single_name_above_10pct"],
            },
        },
        "inputs": {
            "portfolio_snapshot": {
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "as_of_date": "2026-05-26",
                "positions": [{"instrument_id": "US_EQ_ETF", "quantity": "100"}],
                "cash_balances": [{"currency": "USD", "amount": "50000"}],
            },
            "market_data_snapshot": {
                "as_of_date": "2026-05-26",
                "prices": [{"instrument_id": "US_EQ_ETF", "price": "100", "currency": "USD"}],
                "fx_rates": [{"pair": "USD/SGD", "rate": "1.35"}],
            },
            "shelf_entries": [
                {
                    "instrument_id": "US_EQ_ETF",
                    "eligibility": {"jurisdictions": ["SG"]},
                    "target_market": {"client_segments": ["ACCREDITED_INVESTOR"]},
                    "complexity": "NON_COMPLEX",
                    "private_asset": False,
                    "structured_product": False,
                }
            ],
            "proposed_trades": [{"instrument_id": "US_EQ_ETF", "side": "BUY"}],
        },
        "risk_lens": {
            "source_service": "lotus-risk",
            "single_position_concentration": {"top_position_weight_current": "0.10"},
            "issuer_concentration": {"hhi_current": "1200"},
            "drawdown": {"max_drawdown_1y": "0.08"},
            "var": {"var_95_1m": "0.04"},
            "stress": {"equity_down_20": "-0.09"},
            "liquidity_risk": {"days_to_liquidate": "3"},
            "private_asset_risk": {"private_asset_weight": "0.00"},
            "climate_geopolitical_risk": {"status": "not_material"},
        },
        "artifact": {
            "assumptions_and_limits": {
                "costs_and_fees": {"included": True},
                "tax": {"included": True},
                "execution": {"included": True},
            },
            "disclosures": {
                "product_docs": [{"instrument_id": "US_EQ_ETF", "doc_ref": "Factsheet"}],
            },
        },
        "conflict_evidence": {"material_conflict": False, "review_ref": "conflict-review-001"},
    }


def _proposal_bound_evidence_bundle(*, as_of: str = "2026-05-26") -> dict:
    evidence = _base_evidence_bundle()
    evidence["context_resolution"].pop("as_of_date", None)
    evidence["context_resolution"]["resolved_context"] = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of": as_of,
    }
    evidence["inputs"]["portfolio_snapshot"].pop("as_of_date", None)
    evidence["inputs"]["market_data_snapshot"].pop("as_of_date", None)
    return evidence


def _proposal_repository_with_version(
    *,
    proposal_id: str,
    proposal_version_id: str,
    evidence_bundle: dict,
) -> InMemoryProposalRepository:
    repository = InMemoryProposalRepository()
    repository.create_proposal(
        ProposalRecord(
            proposal_id=proposal_id,
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            created_by="advisor_1",
            created_at=NOW,
            last_event_at=NOW,
            current_state="DRAFT",
            current_version_no=1,
        )
    )
    repository.create_version(
        ProposalVersionRecord(
            proposal_version_id=proposal_version_id,
            proposal_id=proposal_id,
            version_no=1,
            created_at=NOW,
            request_hash="sha256:proposal-request",
            artifact_hash="sha256:proposal-artifact",
            simulation_hash="sha256:proposal-simulation",
            status_at_creation="READY",
            proposal_result_json={"status": "READY"},
            artifact_json={"artifact_id": "proposal-artifact"},
            evidence_bundle_json=evidence_bundle,
        )
    )
    return repository


def _create_payload(evidence: dict | None = None) -> dict:
    return {
        "policy_pack_id": "GLOBAL_PRIVATE_BANKING_BASELINE",
        "policy_version": "2026.05",
        "created_by": "advisor_1",
        "evidence_bundle": evidence or _base_evidence_bundle(),
        "reason": {"purpose": "advisor suitability review"},
    }


def _receipt_identity(
    *,
    proposal_id: str = "proposal-gap",
    proposal_version_id: str = "version-gap",
    portfolio_id: str = "PB_SG_GLOBAL_BAL_001",
) -> dict:
    return {
        "receipt_contract_version": "rfc0002.policy-evaluation-receipt-identity.v1",
        "as_of_date": "2026-05-26",
        "scope_identity": {
            "identity_contract_version": "rfc0002.policy-evaluation-receipt-identity.v1",
            "authority_source": "trusted_policy_control_principal",
            "tenant_scope_hash": "sha256:tenant",
            "legal_entity_code": "REFERENCE",
            "booking_center_code": "SG",
            "service_identity_hash": "sha256:service",
            "proposal_id": proposal_id,
            "proposal_version_id": proposal_version_id,
            "portfolio_id": portfolio_id,
        },
        "observed_correlation_id_hash": "sha256:correlation",
        "observed_trace_id_hash": "sha256:trace",
        "correlation_identity_source": "trusted_policy_control_principal",
        "trace_identity_source": "advise_observability_context",
    }


def _policy_headers(
    *,
    actor_id: str,
    role: str,
    capability: str,
    idempotency_key: str | None = None,
    proposal_id: str | None = None,
    portfolio_id: str | None = "PB_SG_GLOBAL_BAL_001",
    tenant_id: str = "tenant_sg_001",
    legal_entity_code: str = "REFERENCE",
    service_identity: str = "lotus-gateway",
    principal_status: str | None = None,
) -> dict[str, str]:
    headers = {
        "X-Actor-Id": actor_id,
        "X-Role": role,
        "X-Tenant-Id": tenant_id,
        "X-Legal-Entity-Code": legal_entity_code,
        "X-Correlation-Id": f"corr-{actor_id}",
        "X-Service-Identity": service_identity,
        "X-Capabilities": capability,
        "traceparent": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
    }
    if principal_status is not None:
        headers["X-Principal-Status"] = principal_status
    if proposal_id is not None:
        headers["X-Authorized-Proposal-Id"] = proposal_id
    if portfolio_id is not None:
        headers["X-Authorized-Portfolio-Id"] = portfolio_id
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _policy_evaluation_create_headers(
    *,
    proposal_id: str,
    idempotency_key: str,
    actor_id: str = "advisor_1",
    portfolio_id: str = "PB_SG_GLOBAL_BAL_001",
    tenant_id: str = "tenant_sg_001",
    legal_entity_code: str = "REFERENCE",
    service_identity: str = "lotus-gateway",
    principal_status: str | None = None,
) -> dict[str, str]:
    return _policy_headers(
        actor_id=actor_id,
        role=ADVISOR_ROLE,
        capability=POLICY_EVALUATION_FINALIZE_CAPABILITY,
        idempotency_key=idempotency_key,
        proposal_id=proposal_id,
        portfolio_id=portfolio_id,
        tenant_id=tenant_id,
        legal_entity_code=legal_entity_code,
        service_identity=service_identity,
        principal_status=principal_status,
    )


def _policy_review_headers(*, proposal_id: str, idempotency_key: str) -> dict[str, str]:
    return _policy_headers(
        actor_id="compliance_1",
        role=COMPLIANCE_REVIEWER_ROLE,
        capability=POLICY_EVALUATION_REVIEW_EVENT_CAPABILITY,
        idempotency_key=idempotency_key,
        proposal_id=proposal_id,
    )


def _policy_checker_headers(
    *,
    capability: str,
    idempotency_key: str | None = None,
    proposal_id: str,
    actor_id: str = "policy_checker_1",
) -> dict[str, str]:
    return _policy_headers(
        actor_id=actor_id,
        role=POLICY_CHECKER_ROLE,
        capability=capability,
        idempotency_key=idempotency_key,
        proposal_id=proposal_id,
    )


def _activate_sg_pack(client: TestClient) -> None:
    content_hash = get_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
    ).policy_pack.content_hash
    validated = client.post(
        "/advisory/policy-packs/SG_PRIVATE_BANKING_REFERENCE/versions/2026.05/validate",
        json={"requested_by": "policy_steward_1", "reason": {"purpose": "api test"}},
        headers=_policy_headers(
            actor_id="policy_steward_1",
            role=POLICY_STEWARD_ROLE,
            capability=POLICY_PACK_VALIDATE_CAPABILITY,
            idempotency_key="api-policy-eval-validate-sg",
            portfolio_id=None,
        ),
    )
    assert validated.status_code == 200
    activated = client.post(
        "/advisory/policy-packs/SG_PRIVATE_BANKING_REFERENCE/versions/2026.05/activate",
        json={
            "activated_by": "policy_checker_1",
            "source_content_hash": content_hash,
            "reason": {"purpose": "api test"},
        },
        headers=_policy_headers(
            actor_id="policy_checker_1",
            role=POLICY_CHECKER_ROLE,
            capability=POLICY_PACK_ACTIVATE_CAPABILITY,
            idempotency_key="api-policy-eval-activate-sg",
            portfolio_id=None,
        ),
    )
    assert activated.status_code == 200


def _sg_pending_payload() -> dict:
    evidence = _base_evidence_bundle()
    evidence["inputs"]["shelf_entries"][0]["instrument_id"] = "SG_STRUCTURED_NOTE"
    evidence["inputs"]["shelf_entries"][0]["complexity"] = "COMPLEX"
    evidence["inputs"]["shelf_entries"][0]["structured_product"] = True
    evidence["inputs"]["proposed_trades"][0]["instrument_id"] = "SG_STRUCTURED_NOTE"
    evidence["artifact"]["disclosures"]["product_docs"] = [
        {"instrument_id": "SG_STRUCTURED_NOTE", "doc_ref": "Term sheet"}
    ]
    payload = _create_payload(evidence)
    payload["policy_pack_id"] = "SG_PRIVATE_BANKING_REFERENCE"
    return payload


def test_policy_evaluation_control_routes_bind_trusted_principal_and_scope() -> None:
    with TestClient(app) as client:
        missing_auth = client.post(
            "/advisory/proposals/pp_policy_auth/versions/ppv_policy_auth/policy-evaluations",
            json=_create_payload(),
            headers={"Idempotency-Key": "api-policy-auth-missing"},
        )
        assert missing_auth.status_code == 401
        assert missing_auth.json()["detail"] == POLICY_CONTROL_PRINCIPAL_REQUIRED

        expired_principal = client.post(
            "/advisory/proposals/pp_policy_auth/versions/ppv_policy_auth/policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_auth",
                idempotency_key="api-policy-auth-expired",
                principal_status="EXPIRED",
            ),
        )
        assert expired_principal.status_code == 401
        assert expired_principal.json()["detail"] == POLICY_CONTROL_PRINCIPAL_INVALID

        missing_scope = client.post(
            "/advisory/proposals/pp_policy_auth/versions/ppv_policy_auth/policy-evaluations",
            json=_create_payload(),
            headers=_policy_headers(
                actor_id="advisor_1",
                role=ADVISOR_ROLE,
                capability=POLICY_EVALUATION_FINALIZE_CAPABILITY,
                idempotency_key="api-policy-auth-missing-scope",
                proposal_id=None,
            ),
        )
        assert missing_scope.status_code == 403
        assert missing_scope.json()["detail"] == POLICY_CONTROL_SCOPE_REQUIRED

        cross_scope = client.post(
            "/advisory/proposals/pp_policy_auth/versions/ppv_policy_auth/policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_other",
                idempotency_key="api-policy-auth-cross-scope",
            ),
        )
        assert cross_scope.status_code == 403
        assert cross_scope.json()["detail"] == POLICY_CONTROL_SCOPE_FORBIDDEN

        spoofed_actor = client.post(
            "/advisory/proposals/pp_policy_auth/versions/ppv_policy_auth/policy-evaluations",
            json={**_create_payload(), "created_by": "impersonated_advisor"},
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_auth",
                idempotency_key="api-policy-auth-spoof",
            ),
        )
        assert spoofed_actor.status_code == 403
        assert spoofed_actor.json()["detail"] == POLICY_CONTROL_ACTOR_MISMATCH

        created = client.post(
            "/advisory/proposals/pp_policy_auth/versions/ppv_policy_auth/policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_auth",
                idempotency_key="api-policy-auth-success",
                service_identity="lotus-gateway",
            ),
        )
        assert created.status_code == 200
        trusted_principal = created.json()["audit_event"]["reason_json"]["trusted_principal"]
        assert trusted_principal["subject"] == "advisor_1"
        assert trusted_principal["role"] == ADVISOR_ROLE
        assert trusted_principal["tenant_id"] == "tenant_sg_001"
        assert trusted_principal["correlation_id"] == "corr-advisor_1"
        assert trusted_principal["service_identity"] == "lotus-gateway"

        evaluation_id = created.json()["record"]["evaluation_id"]
        review_spoof = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/events",
            json={
                "event_type": "POLICY_EVALUATION_REVIEW_RECORDED",
                "actor_id": "impersonated_reviewer",
                "reason": {"review_action": "REQUEST_MORE_EVIDENCE"},
            },
            headers=_policy_review_headers(
                proposal_id="pp_policy_auth",
                idempotency_key="api-policy-auth-review-spoof",
            ),
        )
        assert review_spoof.status_code == 403
        assert review_spoof.json()["detail"] == POLICY_CONTROL_ACTOR_MISMATCH


def test_policy_sign_off_maker_checker_uses_trusted_principal_identity() -> None:
    with TestClient(app) as client:
        _activate_sg_pack(client)
        payload = _sg_pending_payload()
        payload["created_by"] = "policy_checker_1"
        created = client.post(
            "/advisory/proposals/pp_policy_same_actor/versions/ppv_policy_same_actor/policy-evaluations",
            json=payload,
            headers=_policy_evaluation_create_headers(
                actor_id="policy_checker_1",
                proposal_id="pp_policy_same_actor",
                idempotency_key="api-policy-same-actor-create",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]

        same_actor_signoff = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/sign-off-decisions",
            json={
                "actor_id": "policy_checker_1",
                "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
                "source_evaluation_hash": record["evaluation_hash"],
                "resolved_approval_dependencies": record["approval_dependencies"],
                "satisfied_disclosure_requirements": record["disclosure_requirements"],
                "satisfied_consent_requirements": record["consent_requirements"],
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_SIGN_OFF_CAPABILITY,
                proposal_id="pp_policy_same_actor",
                idempotency_key="api-policy-same-actor-signoff",
            ),
        )
        assert same_actor_signoff.status_code == 422
        assert same_actor_signoff.json()["detail"] == (
            "POLICY_EVALUATION_SIGN_OFF_REQUIRES_MAKER_CHECKER"
        )


def test_policy_evaluation_binds_missing_source_as_of_from_proposal_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal_id = "pp_policy_bound_context"
    proposal_version_id = "ppv_policy_bound_context"
    repository = _proposal_repository_with_version(
        proposal_id=proposal_id,
        proposal_version_id=proposal_version_id,
        evidence_bundle=_proposal_bound_evidence_bundle(as_of="2026-05-26"),
    )
    monkeypatch.setattr(proposals_router, "get_proposal_repository", lambda: repository)
    payload = _create_payload()
    payload["evidence_bundle"]["context_resolution"].pop("as_of_date", None)
    payload["evidence_bundle"]["inputs"]["portfolio_snapshot"].pop("as_of_date", None)
    payload["evidence_bundle"]["inputs"]["market_data_snapshot"].pop("as_of_date", None)

    with TestClient(app) as client:
        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions/{proposal_version_id}/policy-evaluations",
            json=payload,
            headers=_policy_evaluation_create_headers(
                proposal_id=proposal_id,
                idempotency_key="api-policy-eval-bound-context",
            ),
        )

    assert response.status_code == 200
    record = response.json()["record"]
    assert record["replay_metadata_json"]["as_of_date"] == "2026-05-26"
    assert record["source_evidence_hash"].startswith("sha256:")


def test_policy_evaluation_rejects_request_source_date_drift_from_proposal_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal_id = "pp_policy_bound_context_drift"
    proposal_version_id = "ppv_policy_bound_context_drift"
    repository = _proposal_repository_with_version(
        proposal_id=proposal_id,
        proposal_version_id=proposal_version_id,
        evidence_bundle=_proposal_bound_evidence_bundle(as_of="2026-05-26"),
    )
    monkeypatch.setattr(proposals_router, "get_proposal_repository", lambda: repository)
    payload = _create_payload()
    payload["evidence_bundle"]["context_resolution"]["as_of_date"] = "2026-05-27"
    payload["evidence_bundle"]["inputs"]["portfolio_snapshot"]["as_of_date"] = "2026-05-27"
    payload["evidence_bundle"]["inputs"]["market_data_snapshot"]["as_of_date"] = "2026-05-27"

    with TestClient(app) as client:
        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions/{proposal_version_id}/policy-evaluations",
            json=payload,
            headers=_policy_evaluation_create_headers(
                proposal_id=proposal_id,
                idempotency_key="api-policy-eval-bound-context-drift",
            ),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "POLICY_EVALUATION_SOURCE_AS_OF_DATE_MISMATCH"


def test_policy_evaluation_uses_caller_evidence_when_version_evidence_storage_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal_id = "pp_policy_version_evidence_disabled"
    proposal_version_id = "ppv_policy_version_evidence_disabled"
    repository = _proposal_repository_with_version(
        proposal_id=proposal_id,
        proposal_version_id=proposal_version_id,
        evidence_bundle={},
    )
    monkeypatch.setattr(proposals_router, "get_proposal_repository", lambda: repository)

    with TestClient(app) as client:
        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions/{proposal_version_id}/policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id=proposal_id,
                idempotency_key="api-policy-eval-version-evidence-disabled",
            ),
        )

    assert response.status_code == 200
    record = response.json()["record"]
    assert record["evaluation_status"] == "PENDING_REVIEW"
    assert record["replay_metadata_json"]["as_of_date"] == "2026-05-26"


def test_policy_evaluation_binds_missing_legal_entity_from_trusted_principal() -> None:
    payload = _sg_pending_payload()
    payload["evidence_bundle"]["context_resolution"]["advisory_policy_context"].pop(
        "legal_entity_code"
    )

    with TestClient(app) as client:
        _activate_sg_pack(client)
        response = client.post(
            "/advisory/proposals/pp_policy_trusted_legal/versions/"
            "ppv_policy_trusted_legal/policy-evaluations",
            json=payload,
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_trusted_legal",
                idempotency_key="api-policy-eval-trusted-legal",
            ),
        )

    assert response.status_code == 200
    record = response.json()["record"]
    assert record["evaluation_status"] == "PENDING_REVIEW"
    assert (
        record["evaluation_json"]["applicability"]["matched_selectors"]["legal_entity_code"]
        == "REFERENCE"
    )


def test_policy_evaluation_rejects_legal_entity_body_scope_drift() -> None:
    payload = _sg_pending_payload()
    payload["evidence_bundle"]["context_resolution"]["advisory_policy_context"][
        "legal_entity_code"
    ] = "OTHER_ENTITY"

    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/pp_policy_legal_drift/versions/"
            "ppv_policy_legal_drift/policy-evaluations",
            json=payload,
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_legal_drift",
                idempotency_key="api-policy-eval-legal-drift",
            ),
        )

    assert response.status_code == 403
    assert response.json()["detail"] == POLICY_CONTROL_SCOPE_FORBIDDEN


def test_policy_evaluation_api_finalizes_reads_replays_and_records_events() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals/pp_policy_api_001/versions/ppv_policy_api_001/policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_api_001",
                idempotency_key="api-policy-eval-create-001",
            ),
        )
        assert created.status_code == 200
        created_body = created.json()
        evaluation_id = created_body["record"]["evaluation_id"]

        replayed = client.post(
            "/advisory/proposals/pp_policy_api_001/versions/ppv_policy_api_001/policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_api_001",
                idempotency_key="api-policy-eval-create-001",
            ),
        )
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True

        drift = client.post(
            "/advisory/proposals/pp_policy_api_001/versions/ppv_policy_api_001/policy-evaluations",
            json={**_create_payload(), "reason": {"purpose": "changed"}},
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_api_001",
                idempotency_key="api-policy-eval-create-001",
            ),
        )
        assert drift.status_code == 409

        read = client.get(f"/advisory/policy-evaluations/{evaluation_id}")
        assert read.status_code == 200
        read_body = read.json()
        assert read_body["evaluation_hash"].startswith("sha256:")
        assert read_body["evaluation_json"]["supportability"]["policy_evaluation_api"] == (
            "SUPPORTED_BY_RFC0025_SLICE8_ADVISE_API"
        )
        assert read_body["evaluation_json"]["supportability"]["gateway_supported"] is True
        assert read_body["evaluation_json"]["supportability"]["gateway_support"] == (
            "SUPPORTED_BY_RFC0025_SLICE12_GATEWAY_BFF"
        )
        assert read_body["evaluation_json"]["supportability"]["active_data_product_promotion"] == (
            "SUPPORTED_BY_RFC0025_SLICE16_FINAL_CLOSURE"
        )
        assert (
            read_body["evaluation_json"]["applicability"]["matched_selectors"]["legal_entity_code"]
            == "REFERENCE"
        )
        assert (
            read_body["evaluation_json"]["applicability"]["matched_selectors"]["product_scope"]
            == "MULTI_ASSET"
        )

        replay = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/replay",
            json={"evidence_bundle": _base_evidence_bundle()},
        )
        assert replay.status_code == 200
        assert replay.json()["hash_comparison"]["evaluation_hash_matches"] is True

        changed_evidence = deepcopy(_base_evidence_bundle())
        changed_evidence["inputs"]["market_data_snapshot"]["fx_rates"][0]["rate"] = "1.36"
        changed = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/replay",
            json={"evidence_bundle": changed_evidence},
        )
        assert changed.status_code == 200
        assert changed.json()["hash_comparison"]["source_evidence_hash_matches"] is False

        review = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/events",
            json={
                "event_type": "POLICY_EVALUATION_REVIEW_RECORDED",
                "actor_id": "compliance_1",
                "reason": {"review_action": "REQUEST_MORE_EVIDENCE"},
            },
            headers=_policy_review_headers(
                proposal_id="pp_policy_api_001",
                idempotency_key="api-policy-eval-review-001",
            ),
        )
        assert review.status_code == 200
        assert review.json()["event_type"] == "POLICY_EVALUATION_REVIEW_RECORDED"

        lineage = client.get(f"/advisory/policy-evaluations/{evaluation_id}/lineage")
        assert lineage.status_code == 200
        lineage_body = lineage.json()
        assert [event["event_type"] for event in lineage_body["audit_events"]] == [
            "POLICY_EVALUATION_FINALIZED",
            "POLICY_EVALUATION_REVIEW_RECORDED",
        ]
        assert lineage_body["lineage_posture"]["client_ready_publication"] == "BLOCKED"

        sign_off = client.get(f"/advisory/policy-evaluations/{evaluation_id}/sign-off-package")
        assert sign_off.status_code == 200
        sign_off_body = sign_off.json()
        assert sign_off_body["evaluation"]["evaluation_id"] == evaluation_id
        assert sign_off_body["package_posture"]["report_render_archive_realization"] == (
            "SUPPORTED_BY_RFC0025_SLICE10_SIGNED_OFF_PACKAGE_HANDOFF"
        )
        assert sign_off_body["package_posture"]["client_ready_publication"] == "BLOCKED"


def test_generic_policy_evaluation_event_api_rejects_privileged_event_types() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals/pp_policy_event_bypass/versions/"
            "ppv_policy_event_bypass/policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_event_bypass",
                idempotency_key="api-policy-eval-bypass",
            ),
        )
        assert created.status_code == 200
        evaluation_id = created.json()["record"]["evaluation_id"]

        privileged_events = [
            (
                "POLICY_EVALUATION_FINALIZED",
                {"evaluation_status": "PENDING_REVIEW"},
            ),
            (
                "POLICY_EVALUATION_SIGN_OFF_RECORDED",
                {
                    "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
                    "source_evaluation_hash": created.json()["record"]["evaluation_hash"],
                },
            ),
            (
                "POLICY_EVALUATION_REPORT_ARCHIVE_RECORDED",
                {
                    "report_package_status": "RECORDED",
                    "report_request_id": "rreq_forged_001",
                    "report_package_id": "rjob_forged_001",
                },
            ),
            (
                "POLICY_EVALUATION_AI_EVIDENCE_RECORDED",
                {
                    "ai_status": "REVIEW_REQUIRED",
                    "lineage": {"provider": "forged"},
                },
            ),
        ]
        for event_type, reason in privileged_events:
            response = client.post(
                f"/advisory/policy-evaluations/{evaluation_id}/events",
                json={
                    "event_type": event_type,
                    "actor_id": "compliance_1",
                    "reason": reason,
                },
                headers=_policy_review_headers(
                    proposal_id="pp_policy_event_bypass",
                    idempotency_key=f"api-policy-forged-{event_type.lower()}",
                ),
            )
            assert response.status_code == 422

        lineage = client.get(f"/advisory/policy-evaluations/{evaluation_id}/lineage")
        assert lineage.status_code == 200
        assert [event["event_type"] for event in lineage.json()["audit_events"]] == [
            "POLICY_EVALUATION_FINALIZED"
        ]

        workflow = client.get(f"/advisory/policy-evaluations/{evaluation_id}/workflow")
        assert workflow.status_code == 200
        workflow_body = workflow.json()
        assert workflow_body["sign_off_status"] != "SIGNED_OFF"
        assert workflow_body["metadata"]["as_of_date"] == "2026-05-26"
        assert workflow_body["metadata"]["scope_identity"]["authority_source"] == (
            "trusted_policy_control_principal"
        )
        assert workflow_body["metadata"]["scope_identity"]["tenant_scope_hash"].startswith(
            "sha256:"
        )
        assert workflow_body["metadata"]["scope_identity"]["legal_entity_code"] == "REFERENCE"
        assert workflow_body["metadata"]["observed_correlation_id_hash"].startswith("sha256:")
        assert workflow_body["metadata"]["observed_trace_id_hash"].startswith("sha256:")
        assert workflow_body["replay_metadata"]["as_of_date"] == "2026-05-26"
        assert (
            workflow_body["replay_metadata"]["observed_trace_id_hash"]
            == workflow_body["metadata"]["observed_trace_id_hash"]
        )


def test_policy_evaluation_workflow_and_sign_off_decision_api_enforce_requirements() -> None:
    with TestClient(app) as client:
        _activate_sg_pack(client)
        created = client.post(
            "/advisory/proposals/pp_policy_signoff_001/versions/ppv_policy_signoff_001/policy-evaluations",
            json=_sg_pending_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_signoff_001",
                idempotency_key="api-policy-eval-signoff-001",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]
        evaluation_id = record["evaluation_id"]

        workflow = client.get(f"/advisory/policy-evaluations/{evaluation_id}/workflow")
        assert workflow.status_code == 200
        workflow_body = workflow.json()
        assert workflow_body["sign_off_status"] == "PENDING_REVIEW"
        assert workflow_body["client_ready_publication"] == "BLOCKED"
        assert workflow_body["sla_posture"]["open_requirement_count"] >= 3
        assert workflow_body["approval_dependencies"][0]["requirement_id"] == (
            "REVIEW_DISCLOSURE:SG_STRUCTURED_NOTE"
        )
        assert workflow_body["metadata"]["product_id"] == (
            "lotus-advise:AdvisoryPolicyEvaluationRecord:v1"
        )
        assert workflow_body["metadata"]["generated_at"] == record["generated_at"]
        assert workflow_body["metadata"]["content_hash"] == record["evaluation_hash"]
        assert workflow_body["metadata"]["freshness_state"] == "current"
        assert workflow_body["metadata"]["data_quality_status"] == "incomplete"
        assert workflow_body["metadata"]["source_gap_count"] >= 1
        assert (
            workflow_body["replay_metadata"]["source_evidence_hash"]
            == (record["source_evidence_hash"])
        )
        assert workflow_body["replay_metadata"]["evaluation_hash"] == record["evaluation_hash"]

        blocked = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/sign-off-decisions",
            json={
                "actor_id": "policy_checker_1",
                "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
                "source_evaluation_hash": record["evaluation_hash"],
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_SIGN_OFF_CAPABILITY,
                proposal_id="pp_policy_signoff_001",
                idempotency_key="api-policy-signoff-missing-requirements",
            ),
        )
        assert blocked.status_code == 422
        assert blocked.json()["detail"] == "POLICY_EVALUATION_SIGN_OFF_REQUIREMENTS_OPEN"

        signed = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/sign-off-decisions",
            json={
                "actor_id": "policy_checker_1",
                "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
                "source_evaluation_hash": record["evaluation_hash"],
                "resolved_approval_dependencies": record["approval_dependencies"],
                "satisfied_disclosure_requirements": record["disclosure_requirements"],
                "satisfied_consent_requirements": record["consent_requirements"],
                "reason": {"purpose": "requirements reviewed"},
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_SIGN_OFF_CAPABILITY,
                proposal_id="pp_policy_signoff_001",
                idempotency_key="  api-policy-signoff-approved  ",
            ),
        )
        assert signed.status_code == 200
        signed_body = signed.json()
        assert signed_body["workflow"]["sign_off_status"] == "SIGNED_OFF"
        assert signed_body["workflow"]["sign_off_blockers"] == []
        assert signed_body["sign_off_event"]["event_type"] == (
            "POLICY_EVALUATION_SIGN_OFF_RECORDED"
        )
        assert signed_body["sign_off_event"]["idempotency_key"] == "api-policy-signoff-approved"
        assert signed_body["replay_metadata"]["report_render_archive_realization"] == (
            "SUPPORTED_BY_RFC0025_SLICE10_SIGNED_OFF_PACKAGE_HANDOFF"
        )

        missing_key = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/sign-off-decisions",
            json={
                "actor_id": "policy_checker_1",
                "decision": "REQUEST_MORE_EVIDENCE",
                "source_evaluation_hash": record["evaluation_hash"],
                "reason": {"purpose": "missing idempotency header is rejected"},
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_SIGN_OFF_CAPABILITY,
                proposal_id="pp_policy_signoff_001",
            ),
        )
        assert missing_key.status_code == 422
        assert missing_key.json()["detail"][0]["loc"] == ["header", "Idempotency-Key"]


def test_policy_workflow_metadata_reports_incomplete_source_gaps() -> None:
    record = SimpleNamespace(
        evaluation_id="eval-gap",
        proposal_id="proposal-gap",
        proposal_version_id="version-gap",
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        policy_pack_id="SG_ADVISORY_POLICY_PACK",
        policy_version="2026.04",
        generated_at="2026-04-10T00:00:00+00:00",
        evaluation_hash="sha256:evaluation",
        source_evidence_hash="sha256:source-evidence",
        policy_content_hash="sha256:policy-content",
        source_gaps=["MISSING_CLIENT_CONSENT"],
        replay_metadata_json={"receipt_identity": _receipt_identity()},
    )

    metadata = workflow_lineage_metadata(
        record=record,
        client_ready_publication="BLOCKED",
    )

    assert metadata.data_quality_status == "incomplete"
    assert metadata.source_gap_count == 1
    assert metadata.source_gaps == ["MISSING_CLIENT_CONSENT"]
    assert metadata.as_of_date == "2026-05-26"
    assert metadata.scope_identity.tenant_scope_hash == "sha256:tenant"


def test_policy_report_package_records_report_render_archive_refs_after_sign_off() -> None:
    captured_requests: list[dict] = []

    def _fake_report_package(*, request: dict) -> dict:
        captured_requests.append(request)
        return {
            "proposal": request["proposal"],
            "report_request_id": request["report_request_id"],
            "report_type": "PORTFOLIO_REVIEW",
            "report_service": "lotus-report",
            "status": "ARCHIVED",
            "generated_at": "2026-05-26T04:00:00Z",
            "report_reference_id": "rjob_policy_001",
            "artifact_url": "/reports/jobs/rjob_policy_001",
            "explanation": {
                "render": {"render_job_id": "rdr_policy_001"},
                "archive": {
                    "archive_request_id": "arch_policy_001",
                    "document_id": "doc_policy_001",
                    "retention_posture": "OWNED_BY_LOTUS_ARCHIVE",
                    "legal_hold_posture": "OWNED_BY_LOTUS_ARCHIVE",
                    "access_audit_ref": "audit_policy_001",
                },
            },
        }

    set_policy_report_package_client_for_tests(_FakePolicyReportPackageClient(_fake_report_package))

    with TestClient(app) as client:
        _activate_sg_pack(client)
        created = client.post(
            "/advisory/proposals/pp_policy_report_001/versions/ppv_policy_report_001/policy-evaluations",
            json=_sg_pending_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_report_001",
                idempotency_key="api-policy-eval-report-001",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]
        evaluation_id = record["evaluation_id"]

        unsigned = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/report-packages",
            json={
                "requested_by": "policy_checker_1",
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_output_formats": ["pdf"],
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY,
                proposal_id="pp_policy_report_001",
                idempotency_key="api-policy-report-unsigned",
            ),
        )
        assert unsigned.status_code == 422
        assert unsigned.json()["detail"] == "POLICY_REPORT_PACKAGE_REQUIRES_SIGN_OFF"

        signed = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/sign-off-decisions",
            json={
                "actor_id": "policy_checker_1",
                "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
                "source_evaluation_hash": record["evaluation_hash"],
                "resolved_approval_dependencies": record["approval_dependencies"],
                "satisfied_disclosure_requirements": record["disclosure_requirements"],
                "satisfied_consent_requirements": record["consent_requirements"],
                "reason": {"purpose": "requirements reviewed"},
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_SIGN_OFF_CAPABILITY,
                proposal_id="pp_policy_report_001",
                idempotency_key="api-policy-report-signoff",
            ),
        )
        assert signed.status_code == 200

        report = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/report-packages",
            json={
                "requested_by": "policy_checker_1",
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_output_formats": ["pdf"],
                "reason": {"purpose": "policy sign-off package"},
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY,
                proposal_id="pp_policy_report_001",
                idempotency_key="  api-policy-report-package  ",
            ),
        )
        assert report.status_code == 200
        body = report.json()
        assert body["report_package_event"]["event_type"] == (
            "POLICY_EVALUATION_REPORT_ARCHIVE_RECORDED"
        )
        assert body["report_package_event"]["reason_json"]["report_package_id"] == (
            "rjob_policy_001"
        )
        assert body["report_package_event"]["idempotency_key"] == "api-policy-report-package"
        assert body["report_package_event"]["reason_json"]["render"]["render_job_id"] == (
            "rdr_policy_001"
        )
        assert body["report_package_event"]["reason_json"]["archive"]["document_id"] == (
            "doc_policy_001"
        )
        assert body["report"]["explanation"]["archive"]["access_audit_ref"] == ("audit_policy_001")
        assert captured_requests[0]["policy_sign_off_package"]["client_ready_publication"] == (
            "BLOCKED"
        )
        assert captured_requests[0]["policy_sign_off_package"]["workflow"]["sign_off_status"] == (
            "SIGNED_OFF"
        )

        replayed = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/report-packages",
            json={
                "requested_by": "policy_checker_1",
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_output_formats": ["pdf"],
                "reason": {"purpose": "policy sign-off package"},
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY,
                proposal_id="pp_policy_report_001",
                idempotency_key="api-policy-report-package",
            ),
        )
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert len(captured_requests) == 1

        conflict = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/report-packages",
            json={
                "requested_by": "policy_checker_1",
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_output_formats": ["json"],
                "reason": {"purpose": "policy sign-off package"},
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY,
                proposal_id="pp_policy_report_001",
                idempotency_key="api-policy-report-package",
            ),
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT"
        assert len(captured_requests) == 1

        lineage = client.get(f"/advisory/policy-evaluations/{evaluation_id}/lineage")
        assert lineage.status_code == 200
        event_types = [event["event_type"] for event in lineage.json()["audit_events"]]
        assert event_types[-1] == "POLICY_EVALUATION_REPORT_ARCHIVE_RECORDED"


def test_policy_report_package_unavailable_response_is_safe() -> None:
    def _unavailable_report_package(*, request: dict) -> dict:
        raise LotusReportUnavailableError("provider response leaked bearer token detail")

    set_policy_report_package_client_for_tests(
        _FakePolicyReportPackageClient(_unavailable_report_package)
    )

    with TestClient(app) as client:
        _activate_sg_pack(client)
        created = client.post(
            "/advisory/proposals/pp_policy_report_unavailable/versions/"
            "ppv_policy_report_unavailable/policy-evaluations",
            json=_sg_pending_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_report_unavailable",
                idempotency_key="api-policy-eval-report-unavailable",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]

        signed = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/sign-off-decisions",
            json={
                "actor_id": "policy_checker_1",
                "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
                "source_evaluation_hash": record["evaluation_hash"],
                "resolved_approval_dependencies": record["approval_dependencies"],
                "satisfied_disclosure_requirements": record["disclosure_requirements"],
                "satisfied_consent_requirements": record["consent_requirements"],
                "reason": {"purpose": "requirements reviewed"},
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_SIGN_OFF_CAPABILITY,
                proposal_id="pp_policy_report_unavailable",
                idempotency_key="api-policy-report-unavailable-signoff",
            ),
        )
        assert signed.status_code == 200

        response = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/report-packages",
            json={
                "requested_by": "policy_checker_1",
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_output_formats": ["pdf"],
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY,
                proposal_id="pp_policy_report_unavailable",
                idempotency_key="api-policy-report-unavailable",
            ),
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "LOTUS_REPORT_REQUEST_UNAVAILABLE"


def test_policy_report_package_blocks_client_ready_document_request() -> None:
    with TestClient(app) as client:
        _activate_sg_pack(client)
        created = client.post(
            "/advisory/proposals/pp_policy_report_blocked/versions/ppv_policy_report_blocked/policy-evaluations",
            json=_sg_pending_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_report_blocked",
                idempotency_key="api-policy-eval-report-blocked",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]

        blocked = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/report-packages",
            json={
                "requested_by": "policy_checker_1",
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_output_formats": ["pdf"],
                "client_ready_document_requested": True,
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY,
                proposal_id="pp_policy_report_blocked",
                idempotency_key="api-policy-report-client-ready-blocked",
            ),
        )
        assert blocked.status_code == 422
        assert blocked.json()["detail"] == "POLICY_CLIENT_READY_DOCUMENT_NOT_SUPPORTED"


def test_policy_ai_evidence_records_bounded_lineage_without_mutating_policy() -> None:
    captured_requests: list[dict] = []

    def _fake_policy_ai_evidence(**kwargs) -> PolicyAiEvidenceDraft:
        captured_requests.append(kwargs)
        return PolicyAiEvidenceDraft(
            status="REVIEW_REQUIRED",
            sections=(
                {
                    "section_key": "POLICY_POSTURE",
                    "title": "Policy Posture",
                    "text": "Policy evidence summary for compliance review.",
                    "review_state": "REVIEW_REQUIRED",
                },
            ),
            lineage={
                "workflow_pack_id": "policy_evidence_summary.pack",
                "workflow_pack_version": "v1",
                "workflow_run_id": "packrun_policy_ai_001",
                "fallback_reason": None,
            },
            review_guidance=("Review against immutable policy evaluation hash.",),
        )

    set_policy_ai_evidence_client_for_tests(_FakePolicyAiEvidenceClient(_fake_policy_ai_evidence))

    with TestClient(app) as client:
        _activate_sg_pack(client)
        created = client.post(
            "/advisory/proposals/pp_policy_ai_001/versions/ppv_policy_ai_001/policy-evaluations",
            json=_sg_pending_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_ai_001",
                idempotency_key="api-policy-eval-ai-001",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]
        original_status = record["evaluation_status"]

        response = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/ai-evidence",
            json={
                "requested_by": "policy_checker_1",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_actions": [
                    " summarize_policy_posture ",
                    "explain_open_requirements",
                ],
                "reason": {"purpose": "policy evidence explanation"},
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
                proposal_id="pp_policy_ai_001",
                idempotency_key="  api-policy-ai-evidence-001  ",
            ),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["replayed"] is False
        assert body["ai_event"]["event_type"] == "POLICY_EVALUATION_AI_EVIDENCE_RECORDED"
        assert body["ai_event"]["idempotency_key"] == "api-policy-ai-evidence-001"
        assert body["policy_evidence"]["status"] == "REVIEW_REQUIRED"
        assert body["policy_evidence"]["human_review_required"] is True
        assert body["policy_evidence"]["authoritative_for_policy_status"] is False
        assert body["policy_evidence"]["client_ready_publication"] == "BLOCKED"
        assert body["evaluation"]["evaluation_status"] == original_status
        assert (
            captured_requests[0]["policy_evidence"]["evaluation_hash"]
            == (record["evaluation_hash"])
        )
        assert captured_requests[0]["requested_actions"] == [
            "SUMMARIZE_POLICY_POSTURE",
            "EXPLAIN_OPEN_REQUIREMENTS",
        ]
        assert (
            captured_requests[0]["policy_evidence"]["redaction_profile"][
                "raw_source_evidence_included"
            ]
            is False
        )
        assert "evidence_bundle" not in captured_requests[0]["policy_evidence"]

        replayed = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/ai-evidence",
            json={
                "requested_by": "policy_checker_1",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_actions": [
                    "SUMMARIZE_POLICY_POSTURE",
                    "EXPLAIN_OPEN_REQUIREMENTS",
                ],
                "reason": {"purpose": "policy evidence explanation"},
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
                proposal_id="pp_policy_ai_001",
                idempotency_key="api-policy-ai-evidence-001",
            ),
        )
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert len(captured_requests) == 1

        conflict = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/ai-evidence",
            json={
                "requested_by": "policy_checker_1",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_actions": ["SUMMARIZE_POLICY_POSTURE"],
                "reason": {"purpose": "changed AI evidence explanation"},
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
                proposal_id="pp_policy_ai_001",
                idempotency_key="api-policy-ai-evidence-001",
            ),
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT"
        assert len(captured_requests) == 1

        lineage = client.get(f"/advisory/policy-evaluations/{record['evaluation_id']}/lineage")
        assert lineage.status_code == 200
        assert lineage.json()["audit_events"][-1]["event_type"] == (
            "POLICY_EVALUATION_AI_EVIDENCE_RECORDED"
        )


def test_policy_ai_evidence_rejects_forbidden_action_and_stale_hash() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals/pp_policy_ai_blocked/versions/ppv_policy_ai_blocked/policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_ai_blocked",
                idempotency_key="api-policy-eval-ai-blocked",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]

        forbidden = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/ai-evidence",
            json={
                "requested_by": "policy_checker_1",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_actions": ["APPROVE_POLICY"],
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
                proposal_id="pp_policy_ai_blocked",
                idempotency_key="api-policy-ai-forbidden-action",
            ),
        )
        assert forbidden.status_code == 422
        assert forbidden.json()["detail"] == "POLICY_AI_EVIDENCE_FORBIDDEN_ACTION"

        blank_action = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/ai-evidence",
            json={
                "requested_by": "policy_checker_1",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_actions": ["   "],
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
                proposal_id="pp_policy_ai_blocked",
                idempotency_key="api-policy-ai-blank-action",
            ),
        )
        assert blank_action.status_code == 422
        assert blank_action.json()["detail"] == "POLICY_AI_EVIDENCE_ACTION_REQUIRED"

        stale = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/ai-evidence",
            json={
                "requested_by": "policy_checker_1",
                "source_evaluation_hash": "sha256:stale",
                "requested_actions": ["SUMMARIZE_POLICY_POSTURE"],
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
                proposal_id="pp_policy_ai_blocked",
                idempotency_key="api-policy-ai-stale-hash",
            ),
        )
        assert stale.status_code == 422
        assert stale.json()["detail"] == "POLICY_AI_EVIDENCE_HASH_MISMATCH"


def test_policy_ai_evidence_records_deterministic_unavailable_posture() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals/pp_policy_ai_unavailable/versions/ppv_policy_ai_unavailable/policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_ai_unavailable",
                idempotency_key="api-policy-eval-ai-unavailable",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]

        response = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/ai-evidence",
            json={
                "requested_by": "policy_checker_1",
                "source_evaluation_hash": record["evaluation_hash"],
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
                proposal_id="pp_policy_ai_unavailable",
                idempotency_key="api-policy-ai-unavailable-request",
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["policy_evidence"]["status"] == "UNAVAILABLE"
        assert body["policy_evidence"]["lineage"]["fallback_reason"] == (
            "LOTUS_AI_POLICY_EVIDENCE_UNAVAILABLE"
        )
        assert body["policy_evidence"]["sections"] == []
        assert body["evaluation"]["evaluation_hash"] == record["evaluation_hash"]


def test_policy_ai_evidence_sanitizes_provider_detail_before_lineage() -> None:
    provider_detail = "policy evidence packet rejected with internal/provider text"

    def _unsafe_policy_ai_evidence(**kwargs) -> PolicyAiEvidenceDraft:
        raise LotusAIPolicyEvidenceUnavailableError(provider_detail)

    set_policy_ai_evidence_client_for_tests(_FakePolicyAiEvidenceClient(_unsafe_policy_ai_evidence))

    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals/pp_policy_ai_provider_detail/versions/"
            "ppv_policy_ai_provider_detail/policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_ai_provider_detail",
                idempotency_key="api-policy-eval-ai-provider-detail",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]

        response = client.post(
            f"/advisory/policy-evaluations/{record['evaluation_id']}/ai-evidence",
            json={
                "requested_by": "policy_checker_1",
                "source_evaluation_hash": record["evaluation_hash"],
                "requested_actions": ["SUMMARIZE_POLICY_POSTURE"],
            },
            headers=_policy_checker_headers(
                capability=POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
                proposal_id="pp_policy_ai_provider_detail",
                idempotency_key="api-policy-ai-provider-detail",
            ),
        )

        assert response.status_code == 200
        policy_evidence = response.json()["policy_evidence"]
        assert policy_evidence["lineage"]["fallback_reason"] == (
            "LOTUS_AI_POLICY_EVIDENCE_UNAVAILABLE"
        )
        assert provider_detail not in repr(response.json())


def test_policy_write_side_effect_routes_require_idempotency_key() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/advisory/proposals/pp_policy_missing_idem/versions/ppv_policy_missing_idem/"
            "policy-evaluations",
            json=_create_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_missing_idem",
                idempotency_key="api-policy-eval-missing-idem",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]
        evaluation_id = record["evaluation_id"]

        route_payloads = [
            (
                f"/advisory/policy-evaluations/{evaluation_id}/events",
                {
                    "event_type": "POLICY_EVALUATION_REVIEW_RECORDED",
                    "actor_id": "compliance_1",
                    "reason": {"review_action": "REQUEST_MORE_EVIDENCE"},
                },
                _policy_headers(
                    actor_id="compliance_1",
                    role=COMPLIANCE_REVIEWER_ROLE,
                    capability=POLICY_EVALUATION_REVIEW_EVENT_CAPABILITY,
                    proposal_id="pp_policy_missing_idem",
                ),
            ),
            (
                f"/advisory/policy-evaluations/{evaluation_id}/report-packages",
                {
                    "requested_by": "policy_checker_1",
                    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                    "source_evaluation_hash": record["evaluation_hash"],
                    "requested_output_formats": ["pdf"],
                },
                _policy_checker_headers(
                    capability=POLICY_EVALUATION_REPORT_PACKAGE_CAPABILITY,
                    proposal_id="pp_policy_missing_idem",
                ),
            ),
            (
                f"/advisory/policy-evaluations/{evaluation_id}/ai-evidence",
                {
                    "requested_by": "policy_checker_1",
                    "source_evaluation_hash": record["evaluation_hash"],
                    "requested_actions": ["SUMMARIZE_POLICY_POSTURE"],
                },
                _policy_checker_headers(
                    capability=POLICY_EVALUATION_AI_EVIDENCE_CAPABILITY,
                    proposal_id="pp_policy_missing_idem",
                ),
            ),
        ]

        for route, payload, headers in route_payloads:
            response = client.post(route, json=payload, headers=headers)
            assert response.status_code == 422
            assert response.json()["detail"][0]["loc"] == ["header", "Idempotency-Key"]


def test_policy_evaluation_diagnostics_project_safe_operator_posture() -> None:
    with TestClient(app) as client:
        _activate_sg_pack(client)
        created = client.post(
            "/advisory/proposals/pp_policy_diag/versions/ppv_policy_diag/policy-evaluations",
            json=_sg_pending_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_diag",
                idempotency_key="api-policy-eval-diagnostics",
            ),
        )
        assert created.status_code == 200
        record = created.json()["record"]
        evaluation_id = record["evaluation_id"]

        no_report = client.get(f"/advisory/policy-evaluations/{evaluation_id}/diagnostics")
        assert no_report.status_code == 200
        no_report_body = no_report.json()
        assert no_report_body["sign_off_status"] == "PENDING_REVIEW"
        assert no_report_body["report_package_posture"]["status"] == "NO_REPORT_REQUEST"
        assert no_report_body["ai_evidence_posture"]["status"] == "NO_AI_EVIDENCE_REQUEST"
        assert no_report_body["safe_next_action"] == "RESOLVE_POLICY_SIGN_OFF_BLOCKERS"

        report_event = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/events",
            json={
                "event_type": "POLICY_EVALUATION_REPORT_ARCHIVE_RECORDED",
                "actor_id": "compliance_1",
                "reason": {
                    "report_package_status": "RECORDED",
                    "report_request_id": "rreq_diag_001",
                    "report_package_id": "rjob_diag_001",
                    "render": {"render_job_id": "rdr_diag_001"},
                    "archive": {"document_id": "doc_diag_001"},
                },
            },
            headers=_policy_review_headers(
                proposal_id="pp_policy_diag",
                idempotency_key="api-policy-diag-report",
            ),
        )
        assert report_event.status_code == 422

        ai_event = client.post(
            f"/advisory/policy-evaluations/{evaluation_id}/events",
            json={
                "event_type": "POLICY_EVALUATION_AI_EVIDENCE_RECORDED",
                "actor_id": "compliance_1",
                "reason": {
                    "ai_status": "UNAVAILABLE",
                    "lineage": {
                        "fallback_reason": "LOTUS_AI_POLICY_EVIDENCE_UNAVAILABLE",
                    },
                },
            },
            headers=_policy_review_headers(
                proposal_id="pp_policy_diag",
                idempotency_key="api-policy-diag-ai",
            ),
        )
        assert ai_event.status_code == 422

        diagnostics = client.get(f"/advisory/policy-evaluations/{evaluation_id}/diagnostics")
        assert diagnostics.status_code == 200
        body = diagnostics.json()
        assert body["latest_events"]["report_package"] is None
        assert body["report_package_posture"]["status"] == "NO_REPORT_REQUEST"
        assert body["ai_evidence_posture"]["status"] == "NO_AI_EVIDENCE_REQUEST"
        assert body["runbook_ref"] == "wiki/Operations-Runbook.md#policy-evaluation-diagnostics"
        serialized = str(body)
        assert "provider response leaked" not in serialized
        assert "prompt" not in serialized.lower()


def test_policy_evaluation_diagnostics_returns_not_found_for_unknown_record() -> None:
    with TestClient(app) as client:
        response = client.get("/advisory/policy-evaluations/pev_missing/diagnostics")

    assert response.status_code == 404
    assert response.json()["detail"] == "POLICY_EVALUATION_RECORD_NOT_FOUND"


def test_policy_review_queue_filters_records_that_need_policy_review() -> None:
    with TestClient(app) as client:
        _activate_sg_pack(client)
        created = client.post(
            "/advisory/proposals/pp_policy_queue_001/versions/ppv_policy_queue_001/policy-evaluations",
            json=_sg_pending_payload(),
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_queue_001",
                idempotency_key="api-policy-eval-queue-001",
            ),
        )
        assert created.status_code == 200
        evaluation_id = created.json()["record"]["evaluation_id"]
        assert created.json()["record"]["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"

        other_portfolio_payload = _sg_pending_payload()
        other_portfolio_payload["evidence_bundle"]["inputs"]["portfolio_snapshot"][
            "portfolio_id"
        ] = "PB_SG_OTHER_BAL_001"
        other_created = client.post(
            "/advisory/proposals/pp_policy_queue_002/versions/ppv_policy_queue_002/policy-evaluations",
            json=other_portfolio_payload,
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_queue_002",
                idempotency_key="api-policy-eval-queue-002",
                portfolio_id="PB_SG_OTHER_BAL_001",
            ),
        )
        assert other_created.status_code == 200
        other_evaluation_id = other_created.json()["record"]["evaluation_id"]

        queue = client.get("/advisory/policy-evaluations/review-queue")
        assert queue.status_code == 200
        queue_body = queue.json()
        assert [item["evaluation_id"] for item in queue_body["items"]] == [
            evaluation_id,
            other_evaluation_id,
        ]
        assert queue_body["items"][0]["evaluation_status"] == "PENDING_REVIEW"
        assert queue_body["queue_posture"]["workbench_supported"] is True
        assert queue_body["queue_posture"]["workbench_support"] == (
            "SUPPORTED_BY_RFC0025_SLICE12_GATEWAY_ONLY_UI"
        )
        assert queue_body["queue_posture"]["client_ready_publication"] == "BLOCKED"

        portfolio_queue = client.get(
            "/advisory/policy-evaluations/review-queue",
            params={
                "evaluation_status": "PENDING_REVIEW",
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            },
        )
        assert portfolio_queue.status_code == 200
        assert [item["evaluation_id"] for item in portfolio_queue.json()["items"]] == [
            evaluation_id
        ]

        ready_queue = client.get(
            "/advisory/policy-evaluations/review-queue",
            params={"evaluation_status": "READY"},
        )
        assert ready_queue.status_code == 200
        assert ready_queue.json()["items"] == []


def test_policy_evaluation_rejects_missing_portfolio_identity() -> None:
    payload = _create_payload()
    del payload["evidence_bundle"]["inputs"]["portfolio_snapshot"]["portfolio_id"]

    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/pp_policy_missing_portfolio/versions/"
            "ppv_policy_missing_portfolio/policy-evaluations",
            json=payload,
            headers=_policy_evaluation_create_headers(
                proposal_id="pp_policy_missing_portfolio",
                idempotency_key="api-policy-eval-missing-portfolio",
            ),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "POLICY_EVALUATION_PORTFOLIO_ID_REQUIRED"


def test_policy_evaluation_openapi_registers_certified_advise_routes() -> None:
    app.openapi_schema = None
    openapi = app.openapi()
    paths = openapi["paths"]

    create_path = (
        "/advisory/proposals/{proposal_id}/versions/{proposal_version_id}/policy-evaluations"
    )
    assert paths[create_path]["post"]["tags"] == ["Advisory Policy Evaluation"]
    idempotency_header = paths[create_path]["post"]["parameters"][2]
    assert idempotency_header["description"].startswith(
        "Required idempotency key for replay-safe policy evaluation finalization."
    )
    assert "at most 128 visible characters" in idempotency_header["description"]
    assert idempotency_header["schema"]["maxLength"] == 128
    assert "/advisory/policy-evaluations/review-queue" in paths
    assert "/advisory/policy-evaluations/{evaluation_id}/events" in paths
    assert "/advisory/policy-evaluations/{evaluation_id}/lineage" in paths
    assert "/advisory/policy-evaluations/{evaluation_id}/sign-off-package" in paths
    assert "/advisory/policy-evaluations/{evaluation_id}/workflow" in paths
    assert "/advisory/policy-evaluations/{evaluation_id}/sign-off-decisions" in paths
    assert "/advisory/policy-evaluations/{evaluation_id}/report-packages" in paths
    assert "/advisory/policy-evaluations/{evaluation_id}/ai-evidence" in paths
    assert (
        paths[create_path]["post"]["responses"]["422"]["description"]
        == (POLICY_EVALUATION_CREATE_RESPONSES[422]["description"])
    )
    report_package_path = "/advisory/policy-evaluations/{evaluation_id}/report-packages"
    ai_evidence_path = "/advisory/policy-evaluations/{evaluation_id}/ai-evidence"
    for path in (
        "/advisory/policy-evaluations/{evaluation_id}/events",
        "/advisory/policy-evaluations/{evaluation_id}/sign-off-decisions",
        report_package_path,
        ai_evidence_path,
    ):
        idempotency_parameters = [
            parameter
            for parameter in paths[path]["post"]["parameters"]
            if parameter["name"] == "Idempotency-Key"
        ]
        assert idempotency_parameters
        assert idempotency_parameters[0]["required"] is True
        assert idempotency_parameters[0]["description"].startswith(
            "Required idempotency key for replay-safe policy"
        )

    assert (
        paths[report_package_path]["post"]["responses"]["503"]["description"]
        == (POLICY_REPORT_PACKAGE_RESPONSES[503]["description"])
    )
    assert (
        paths[ai_evidence_path]["post"]["responses"]["422"]["description"]
        == (POLICY_AI_EVIDENCE_RESPONSES[422]["description"])
    )
