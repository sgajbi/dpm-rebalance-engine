import json
from dataclasses import replace

from fastapi.testclient import TestClient

import src.api.proposals.router as proposals_router
from src.api.main import app
from src.core.proposals.idea_proposal_intake import (
    IDEA_PROPOSAL_INTAKE_CERTIFICATION_BLOCKERS,
    IdeaProposalIntakeRequest,
    acknowledge_idea_proposal_intake,
)
from src.infrastructure.proposals.in_memory import InMemoryProposalRepository


def _payload() -> dict[str, object]:
    return {
        "source_system": "lotus-idea",
        "source_product": "lotus-idea:IdeaCandidate:v1",
        "idea_candidate_id": "idea_candidate_001",
        "conversion_intent_id": "conversion_intent_001",
        "intent_type": "REVIEW_FOR_ADVISORY_PROPOSAL",
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "source_refs": [
            {
                "source_system": "lotus-idea",
                "source_type": "IdeaCandidate",
                "source_id": "idea_candidate_001",
                "content_hash": "sha256:abc123",
            }
        ],
    }


def _headers(
    *,
    correlation_id: str | None = "corr-idea-proposal-001",
    idempotency_key: str = "idea-intake-idem-001",
    capabilities: str = "advisory.idea_proposal_intake.accept",
    role: str = "SERVICE",
) -> dict[str, str]:
    headers = {
        "Idempotency-Key": idempotency_key,
        "X-Actor-Id": "svc-lotus-idea",
        "X-Role": role,
        "X-Tenant-Id": "tenant-private-bank-sg",
        "X-Legal-Entity-Code": "SGPB",
        "X-Service-Identity": "lotus-idea",
        "X-Capabilities": capabilities,
    }
    if correlation_id is not None:
        headers["X-Correlation-Id"] = correlation_id
    return headers


def _realization_headers(*, portfolio_id: str = "PB_SG_GLOBAL_BAL_001") -> dict[str, str]:
    headers = _headers(capabilities="advisory.idea_proposal_realization.read")
    headers["X-Portfolio-Id"] = portfolio_id
    return headers


def test_idea_proposal_intake_route_returns_source_safe_non_proposal_posture() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(),
        )

    assert response.status_code == 202
    body = response.json()
    assert body["intake_id"].startswith("ipi_")
    assert body["intake_status"] == "ACCEPTED"
    assert body["supportability_status"] == "not_certified"
    assert body["source_authority"] == "lotus-idea"
    assert body["proposal_authority"] == "lotus-advise"
    assert body["target_product"] == "lotus-advise:AdvisoryProposalLifecycleRecord:v1"
    assert body["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert body["realization_id"].startswith("ipr_")
    assert body["review_work_id"].startswith("iarw_")
    assert body["review_work_status"] == "PENDING_ADVISER_REVIEW"
    assert body["realization_status"] == "ACCEPTED_FOR_REVIEW"
    assert body["source_event_version"] == 1
    assert body["source_evidence_fingerprint"].startswith("sha256:")
    assert body["route_existence_proven"] is True
    assert body["intake_receipt_accepted"] is True
    assert body["idempotency_replay"] is False
    assert body["idempotency_key_hash"].startswith("sha256:")
    assert body["request_fingerprint"].startswith("sha256:")
    assert body["trusted_scope"] == {
        "subject": "svc-lotus-idea",
        "role": "SERVICE",
        "tenant_id": "tenant-private-bank-sg",
        "legal_entity_code": "SGPB",
        "correlation_id": "corr-idea-proposal-001",
        "service_identity": "lotus-idea",
        "capability": "advisory.idea_proposal_intake.accept",
    }
    assert body["outcome_reason_codes"] == ["idea_intake_receipt_accepted"]
    assert body["proposal_record_created"] is False
    assert body["suitability_authority_granted"] is False
    assert body["order_created"] is False
    assert body["client_publication_authorized"] is False
    assert body["certification_blockers"] == IDEA_PROPOSAL_INTAKE_CERTIFICATION_BLOCKERS
    assert body["correlation_id"] == "corr-idea-proposal-001"


def test_idea_proposal_intake_route_uses_generated_request_correlation_id() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(correlation_id=None, idempotency_key="idea-intake-idem-generated"),
        )

    assert response.status_code == 202
    assert response.json()["correlation_id"] == response.headers["X-Correlation-Id"]
    assert response.json()["correlation_id"].startswith("corr_")


def test_idea_proposal_intake_route_uses_generated_correlation_for_blank_header() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(correlation_id="   ", idempotency_key="idea-intake-idem-blank"),
        )

    assert response.status_code == 202
    assert response.json()["correlation_id"] == response.headers["X-Correlation-Id"]
    assert response.json()["correlation_id"].startswith("corr_")


def test_idea_proposal_intake_rejects_query_parameters() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/idea-intake?dry_run=true",
            json=_payload(),
            headers=_headers(),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "UNSUPPORTED_QUERY_PARAMETER: dry_run not supported for this endpoint"
    )


def test_idea_proposal_intake_route_replays_same_idempotency_key_and_payload() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(correlation_id="corr-first"),
        )
        second = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(correlation_id="corr-second"),
        )

    assert first.status_code == 202
    assert second.status_code == 202
    first_body = first.json()
    second_body = second.json()
    assert second_body["intake_id"] == first_body["intake_id"]
    assert second_body["intake_status"] == "ACCEPTED_REPLAYED"
    assert second_body["idempotency_replay"] is True
    assert second_body["portfolio_id"] == first_body["portfolio_id"]
    assert second_body["outcome_reason_codes"] == ["idea_intake_receipt_replayed"]
    assert second_body["correlation_id"] == "corr-second"


def test_idea_proposal_intake_route_upgrades_pre_realization_replay_receipt() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(idempotency_key="idea-intake-idem-legacy-replay"),
        )
        repository = proposals_router.get_proposal_repository()
        assert isinstance(repository, InMemoryProposalRepository)
        registry_key, stored = next(iter(repository._idea_proposal_intakes.items()))  # noqa: SLF001
        legacy_payload = json.loads(stored.response_json)
        for field in (
            "realization_id",
            "review_work_id",
            "review_work_status",
            "realization_status",
            "source_event_version",
            "source_evidence_fingerprint",
        ):
            legacy_payload.pop(field)
        repository._idea_proposal_intakes[registry_key] = replace(  # noqa: SLF001
            stored,
            response_json=json.dumps(legacy_payload),
        )
        repository._idea_proposal_realizations.clear()  # noqa: SLF001
        repository._idea_realization_by_intake.clear()  # noqa: SLF001
        repository._idea_proposal_realization_outcomes.clear()  # noqa: SLF001

        replay = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(idempotency_key="idea-intake-idem-legacy-replay"),
        )

    assert first.status_code == 202
    assert replay.status_code == 202
    body = replay.json()
    assert body["idempotency_replay"] is True
    assert body["realization_id"].startswith("ipr_")
    assert body["review_work_id"].startswith("iarw_")
    assert body["review_work_status"] == "PENDING_ADVISER_REVIEW"
    assert body["realization_status"] == "ACCEPTED_FOR_REVIEW"
    assert body["source_event_version"] == 1


def test_idea_proposal_intake_route_normalizes_idempotency_key() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(
                correlation_id="corr-normalized-first",
                idempotency_key="  idea-intake-idem-normalized  ",
            ),
        )
        second = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(
                correlation_id="corr-normalized-second",
                idempotency_key="idea-intake-idem-normalized",
            ),
        )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["idempotency_replay"] is True
    assert second.json()["intake_status"] == "ACCEPTED_REPLAYED"


def test_idea_proposal_intake_route_rejects_invalid_idempotency_keys() -> None:
    invalid_keys = ["   ", "x" * 129]

    with TestClient(app) as client:
        responses = [
            client.post(
                "/advisory/proposals/idea-intake",
                json=_payload(),
                headers=_headers(idempotency_key=invalid_key),
            )
            for invalid_key in invalid_keys
        ]

    assert [response.status_code for response in responses] == [422, 422]


def test_idea_proposal_intake_route_requires_canonical_portfolio_scope() -> None:
    missing = _payload()
    missing.pop("portfolio_id")
    blank = {**_payload(), "portfolio_id": "   "}
    oversized = {**_payload(), "portfolio_id": "p" * 161}
    control_bearing = {**_payload(), "portfolio_id": "PB_SG_GLOBAL\nBAL_001"}

    with TestClient(app) as client:
        responses = [
            client.post(
                "/advisory/proposals/idea-intake",
                json=payload,
                headers=_headers(idempotency_key=f"portfolio-validation-{index}"),
            )
            for index, payload in enumerate((missing, blank, oversized, control_bearing))
        ]

    assert [response.status_code for response in responses] == [422, 422, 422, 422]


def test_idea_proposal_intake_idempotency_is_namespaced_by_trusted_scope() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(idempotency_key="idea-intake-idem-shared-scope"),
        )
        second_headers = _headers(idempotency_key="idea-intake-idem-shared-scope")
        second_headers["X-Tenant-Id"] = "tenant-private-bank-hk"
        second_headers["X-Legal-Entity-Code"] = "HKPB"
        second = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=second_headers,
        )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["idempotency_replay"] is False
    assert second.json()["idempotency_replay"] is False
    assert second.json()["trusted_scope"]["tenant_id"] == "tenant-private-bank-hk"
    assert second.json()["trusted_scope"]["legal_entity_code"] == "HKPB"


def test_idea_proposal_intake_route_rejects_conflicting_idempotency_replay() -> None:
    changed_payload = _payload()
    changed_payload["conversion_intent_id"] = "conversion_intent_changed"

    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(),
        )
        second = client.post(
            "/advisory/proposals/idea-intake",
            json=changed_payload,
            headers=_headers(),
        )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"] == "IDEA_PROPOSAL_INTAKE_IDEMPOTENCY_CONFLICT"


def test_idea_proposal_intake_route_conflicts_on_changed_portfolio_scope() -> None:
    changed_scope = {**_payload(), "portfolio_id": "PB_SG_INCOME_002"}

    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(idempotency_key="idea-intake-idem-portfolio-conflict"),
        )
        conflict = client.post(
            "/advisory/proposals/idea-intake",
            json=changed_scope,
            headers=_headers(idempotency_key="idea-intake-idem-portfolio-conflict"),
        )

    assert first.status_code == 202
    assert first.json()["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "IDEA_PROPOSAL_INTAKE_IDEMPOTENCY_CONFLICT"


def test_idea_proposal_intake_route_returns_bounded_rejection_without_proposal_creation() -> None:
    payload = _payload()
    payload["intent_type"] = "CREATE_ADVISORY_PROPOSAL_DRAFT"

    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/idea-intake",
            json=payload,
            headers=_headers(idempotency_key="idea-intake-idem-rejected"),
        )

    assert response.status_code == 202
    body = response.json()
    assert body["intake_status"] == "REJECTED"
    assert body["intake_receipt_accepted"] is False
    assert body["review_work_id"] is None
    assert body["review_work_status"] is None
    assert body["realization_status"] == "REJECTED_BEFORE_WORK"
    assert body["proposal_record_created"] is False
    assert body["suitability_authority_granted"] is False
    assert body["outcome_reason_codes"] == [
        "advisory_proposal_creation_not_certified",
        "idea_intake_receipt_rejected_no_proposal_created",
    ]


def test_idea_proposal_intake_route_requires_trusted_local_dev_principal() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers={"Idempotency-Key": "idea-intake-idem-missing-principal"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "IDEA_PROPOSAL_INTAKE_PRINCIPAL_REQUIRED"


def test_idea_proposal_intake_route_rejects_unauthorized_role() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(role="CLIENT"),
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "IDEA_PROPOSAL_INTAKE_ROLE_NOT_AUTHORIZED"


def test_idea_proposal_intake_route_rejects_missing_capability() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(capabilities="advisory.proposals.read"),
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "IDEA_PROPOSAL_INTAKE_CAPABILITY_REQUIRED"


def test_idea_proposal_intake_domain_acknowledgement_is_deterministic() -> None:
    request = IdeaProposalIntakeRequest.model_validate(_payload())

    first = acknowledge_idea_proposal_intake(request, correlation_id="corr-a")
    second = acknowledge_idea_proposal_intake(request, correlation_id="corr-b")

    assert first.intake_id == second.intake_id
    assert first.realization_id == second.realization_id
    assert first.review_work_id == second.review_work_id
    assert first.proposal_record_created is False
    assert first.intake_receipt_accepted is True
    assert first.suitability_authority_granted is False
    assert first.order_created is False
    assert first.client_publication_authorized is False


def test_idea_proposal_intake_id_changes_when_source_evidence_changes() -> None:
    original = IdeaProposalIntakeRequest.model_validate(_payload())
    changed_payload = _payload()
    changed_payload["source_refs"] = [
        {
            "source_system": "lotus-idea",
            "source_type": "IdeaCandidate",
            "source_id": "idea_candidate_001",
            "content_hash": "sha256:changed",
        }
    ]
    changed = IdeaProposalIntakeRequest.model_validate(changed_payload)

    first = acknowledge_idea_proposal_intake(original, correlation_id="corr-a")
    second = acknowledge_idea_proposal_intake(changed, correlation_id="corr-a")

    assert first.intake_id != second.intake_id


def test_idea_proposal_intake_id_changes_with_portfolio_scope() -> None:
    original = IdeaProposalIntakeRequest.model_validate(_payload())
    changed = IdeaProposalIntakeRequest.model_validate(
        {**_payload(), "portfolio_id": "PB_SG_INCOME_002"}
    )

    first = acknowledge_idea_proposal_intake(original, correlation_id="corr-a")
    second = acknowledge_idea_proposal_intake(changed, correlation_id="corr-a")

    assert first.portfolio_id == "PB_SG_GLOBAL_BAL_001"
    assert second.portfolio_id == "PB_SG_INCOME_002"
    assert first.intake_id != second.intake_id


def test_idea_proposal_intake_id_is_stable_for_reordered_source_evidence() -> None:
    first_payload = _payload()
    first_payload["source_refs"] = [
        {
            "source_system": "lotus-idea",
            "source_type": "IdeaCandidate",
            "source_id": "idea_candidate_002",
            "content_hash": "sha256:def456",
        },
        {
            "source_system": "lotus-idea",
            "source_type": "IdeaCandidate",
            "source_id": "idea_candidate_001",
            "content_hash": "sha256:abc123",
        },
    ]
    second_payload = _payload()
    second_payload["source_refs"] = list(reversed(first_payload["source_refs"]))
    first_request = IdeaProposalIntakeRequest.model_validate(first_payload)
    second_request = IdeaProposalIntakeRequest.model_validate(second_payload)

    first = acknowledge_idea_proposal_intake(first_request, correlation_id="corr-a")
    second = acknowledge_idea_proposal_intake(second_request, correlation_id="corr-a")

    assert first.intake_id == second.intake_id


def test_idea_proposal_intake_route_is_documented_in_openapi() -> None:
    app.openapi_schema = None
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    operation = openapi["paths"]["/advisory/proposals/idea-intake"]["post"]
    assert operation["summary"] == "Accept lotus-idea Proposal Intake Receipt"
    assert "does not grant suitability" in operation["description"]
    assert "202" in operation["responses"]
    assert "401" in operation["responses"]
    assert "403" in operation["responses"]
    assert "409" in operation["responses"]
    realization_operation = openapi["paths"][
        "/advisory/proposals/idea-intake/{intake_id}/realization"
    ]["get"]
    assert realization_operation["summary"] == "Read Advise-owned Idea realization outcomes"
    assert "proposal creation" in realization_operation["description"]
    assert "404" in realization_operation["responses"]


def test_idea_proposal_realization_route_returns_one_durable_initial_outcome() -> None:
    with TestClient(app) as client:
        accepted = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(idempotency_key="idea-realization-read"),
        )
        intake_id = accepted.json()["intake_id"]
        response = client.get(
            f"/advisory/proposals/idea-intake/{intake_id}/realization",
            headers=_realization_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intake_id"] == intake_id
    assert body["review_work_id"] == accepted.json()["review_work_id"]
    assert body["review_work_status"] == "PENDING_ADVISER_REVIEW"
    assert body["current_status"] == "ACCEPTED_FOR_REVIEW"
    assert body["current_source_event_version"] == 1
    assert body["proposal_record_created"] is False
    assert body["suitability_authority_granted"] is False
    assert body["order_created"] is False
    assert body["client_publication_authorized"] is False
    assert len(body["outcomes"]) == 1
    assert body["outcomes"][0]["status"] == "ACCEPTED_FOR_REVIEW"
    assert body["outcomes"][0]["terminal"] is False


def test_idea_proposal_realization_route_fails_closed_on_scope_mismatch() -> None:
    with TestClient(app) as client:
        accepted = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(idempotency_key="idea-realization-scope"),
        )
        intake_id = accepted.json()["intake_id"]
        wrong_portfolio = client.get(
            f"/advisory/proposals/idea-intake/{intake_id}/realization",
            headers=_realization_headers(portfolio_id="PB_OTHER"),
        )
        wrong_tenant_headers = _realization_headers()
        wrong_tenant_headers["X-Tenant-Id"] = "tenant-private-bank-hk"
        wrong_tenant = client.get(
            f"/advisory/proposals/idea-intake/{intake_id}/realization",
            headers=wrong_tenant_headers,
        )

    assert wrong_portfolio.status_code == 404
    assert wrong_portfolio.json()["detail"] == "IDEA_PROPOSAL_REALIZATION_NOT_FOUND"
    assert wrong_tenant.status_code == 404
    assert wrong_tenant.json()["detail"] == "IDEA_PROPOSAL_REALIZATION_NOT_FOUND"


def test_idea_proposal_realization_route_requires_read_capability() -> None:
    with TestClient(app) as client:
        accepted = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(idempotency_key="idea-realization-capability"),
        )
        response = client.get(
            f"/advisory/proposals/idea-intake/{accepted.json()['intake_id']}/realization",
            headers={**_headers(), "X-Portfolio-Id": "PB_SG_GLOBAL_BAL_001"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "IDEA_PROPOSAL_REALIZATION_CAPABILITY_REQUIRED"


def test_idea_proposal_rejection_has_terminal_outcome_without_review_work() -> None:
    payload = {**_payload(), "intent_type": "CREATE_ADVISORY_PROPOSAL_DRAFT"}
    with TestClient(app) as client:
        rejected = client.post(
            "/advisory/proposals/idea-intake",
            json=payload,
            headers=_headers(idempotency_key="idea-realization-rejected"),
        )
        response = client.get(
            f"/advisory/proposals/idea-intake/{rejected.json()['intake_id']}/realization",
            headers=_realization_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["review_work_id"] is None
    assert body["review_work_status"] is None
    assert body["current_status"] == "REJECTED_BEFORE_WORK"
    assert body["outcomes"] == [
        {
            "outcome_id": body["outcomes"][0]["outcome_id"],
            "source_event_version": 1,
            "status": "REJECTED_BEFORE_WORK",
            "reason_code": "idea_conversion_rejected_before_advisory_work",
            "occurred_at": body["outcomes"][0]["occurred_at"],
            "review_work_id": None,
            "proposal_id": None,
            "terminal": True,
        }
    ]


def test_idea_conversion_identity_prevents_second_work_item_for_changed_evidence() -> None:
    changed = _payload()
    changed["source_refs"] = [
        {
            "source_system": "lotus-idea",
            "source_type": "IdeaCandidate",
            "source_id": "idea_candidate_001",
            "content_hash": "sha256:materially-changed",
        }
    ]
    with TestClient(app) as client:
        first = client.post(
            "/advisory/proposals/idea-intake",
            json=_payload(),
            headers=_headers(idempotency_key="idea-realization-original"),
        )
        conflict = client.post(
            "/advisory/proposals/idea-intake",
            json=changed,
            headers=_headers(idempotency_key="idea-realization-changed"),
        )

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "IDEA_PROPOSAL_REALIZATION_CONFLICT"
