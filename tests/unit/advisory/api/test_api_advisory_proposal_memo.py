import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.api.main as api_main
from src.api.main import app
from src.api.proposals.router import (
    get_proposal_repository,
    reset_proposal_workflow_service_for_tests,
)
from src.core.proposals import memo_api
from src.core.proposals.memo_ai_ports import ProposalMemoAiCommentaryDraft
from src.core.proposals.memo_persistence_models import ProposalMemoEventRecord
from src.integrations.lotus_report import LotusReportUnavailableError
from src.integrations.lotus_report.request_mapping import build_memo_report_package_job_request

REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_RESPONSE_FIXTURE = REPO_ROOT / "tests/fixtures/memo_report_archived_response.json"
ARCHIVED_REPORT_RESPONSE = json.loads(REPORT_RESPONSE_FIXTURE.read_text(encoding="utf-8"))


def setup_function() -> None:
    reset_proposal_workflow_service_for_tests()
    if hasattr(api_main, "request_proposal_memo_report_package_with_lotus_report"):
        delattr(api_main, "request_proposal_memo_report_package_with_lotus_report")


def test_memo_api_delegates_external_package_payloads() -> None:
    source = (REPO_ROOT / "src/core/proposals/memo_api.py").read_text(encoding="utf-8")
    operation_source = (
        REPO_ROOT / "src/core/proposals/memo_external_request_operations.py"
    ).read_text(encoding="utf-8")
    package_source = (REPO_ROOT / "src/core/proposals/memo_external_packages.py").read_text(
        encoding="utf-8"
    )

    assert "from src.core.proposals.memo_external_request_operations import" in source
    assert "from src.core.proposals.memo_external_packages import" in operation_source
    assert "def _build_report_memo_package(" not in source
    assert "def _build_memo_ai_evidence(" not in source
    assert "def _build_report_memo_package(" not in operation_source
    assert "def _build_memo_ai_evidence(" not in operation_source
    assert "def build_report_memo_package(" in package_source
    assert "def build_memo_ai_evidence(" in package_source


def test_memo_api_delegates_external_request_operations() -> None:
    source = (REPO_ROOT / "src/core/proposals/memo_api.py").read_text(encoding="utf-8")
    operation_source = (
        REPO_ROOT / "src/core/proposals/memo_external_request_operations.py"
    ).read_text(encoding="utf-8")

    for helper_name in (
        "request_memo_report_package_operation",
        "request_memo_ai_commentary_operation",
    ):
        assert f"def {helper_name}(" not in source
        assert f"def {helper_name}(" in operation_source


def test_memo_api_delegates_response_projection_helpers() -> None:
    source = (REPO_ROOT / "src/core/proposals/memo_api.py").read_text(encoding="utf-8")
    projection_source = (REPO_ROOT / "src/core/proposals/memo_response_projection.py").read_text(
        encoding="utf-8"
    )

    assert "from src.core.proposals.memo_response_projection import" in source
    for helper_name in (
        "build_memo_response",
        "to_audit_event",
        "latest_event_posture",
        "report_response_from_event",
        "commentary_from_ai_event",
        "archive_refs_from_report_posture",
        "project_sections",
        "memo_has_replay_metadata",
        "build_memo_projection_response",
        "build_memo_lineage_response",
        "build_memo_replay_evidence_response",
    ):
        assert f"def {helper_name}(" not in source
        assert f"def {helper_name}(" in projection_source
    assert "ProposalMemoProjectionResponse(" not in source
    assert "ProposalMemoLineageItem(" not in source
    assert "ProposalMemoReplayEvidenceResponse(" not in source
    assert "ProposalMemoProjectionResponse(" in projection_source
    assert "ProposalMemoLineageItem(" in projection_source
    assert "ProposalMemoReplayEvidenceResponse(" in projection_source


def test_memo_api_delegates_event_recording_helpers() -> None:
    source = (REPO_ROOT / "src/core/proposals/memo_api.py").read_text(encoding="utf-8")
    event_source = (REPO_ROOT / "src/core/proposals/memo_event_recording.py").read_text(
        encoding="utf-8"
    )

    assert "from src.core.proposals.memo_event_recording import" in source
    for helper_name in (
        "append_or_replay_memo_event",
        "find_or_reserve_memo_event",
        "memo_event_request_hash",
    ):
        assert f"def {helper_name}(" not in source
        assert f"def {helper_name}(" in event_source
    assert "ProposalMemoEventRecord(" not in source
    assert "ProposalMemoEventRecord(" in event_source


def test_memo_api_delegates_request_context_helpers() -> None:
    source = (REPO_ROOT / "src/core/proposals/memo_api.py").read_text(encoding="utf-8")
    context_source = (REPO_ROOT / "src/core/proposals/memo_request_context.py").read_text(
        encoding="utf-8"
    )

    assert "from src.core.proposals.memo_request_context import" in source
    for helper_name in (
        "load_proposal_version_for_memo",
        "load_memo_for_proposal_version",
        "require_advisor_use_review",
        "validate_source_memo_hash",
    ):
        assert f"def {helper_name}(" not in source
        assert f"def {helper_name}(" in context_source
    assert "load_proposal_version_replay_referents(" not in source
    assert "load_proposal_version_replay_referents(" in context_source


def _base_create_payload(portfolio_id: str = "pf_memo_api_1") -> dict:
    return {
        "created_by": "advisor_1",
        "metadata": {
            "title": "Memo API proposal",
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
                    {
                        "instrument_id": "EQ_OLD",
                        "price": "100",
                        "currency": "USD",
                        "valid_to": "3999-12-31",
                    },
                    {
                        "instrument_id": "EQ_NEW",
                        "price": "50",
                        "currency": "USD",
                        "valid_to": "3999-12-31",
                    },
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


def _create_proposal(client: TestClient) -> dict:
    response = client.post(
        "/advisory/proposals",
        json=_base_create_payload(),
        headers={"Idempotency-Key": "memo-api-proposal-create"},
    )
    assert response.status_code == 200
    return response.json()


def _create_memo(client: TestClient, proposal_id: str) -> dict:
    response = client.post(
        f"/advisory/proposals/{proposal_id}/versions/1/memo",
        json={"created_by": "advisor_1", "reason": {"purpose": "advisor review"}},
        headers={"Idempotency-Key": "  memo-api-create  "},
    )
    assert response.status_code == 200
    return response.json()


def _create_proposal_memo(client: TestClient) -> tuple[str, dict]:
    proposal_id = _create_proposal(client)["proposal"]["proposal_id"]
    return proposal_id, _create_memo(client, proposal_id)


def _approve_memo(
    client: TestClient,
    proposal_id: str,
    memo: dict,
    *,
    idempotency_key: str | None = None,
) -> None:
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    response = client.post(
        f"/advisory/proposals/{proposal_id}/versions/1/memo/review",
        json={
            "action": "APPROVE_FOR_ADVISOR_USE",
            "reviewed_by": "compliance_1",
            "reason": "Evidence is sufficient for advisor discussion.",
            "source_memo_hash": memo["memo_hash"],
        },
        headers=headers,
    )
    assert response.status_code == 200


def _archived_report_response(request: dict) -> dict:
    return {
        **ARCHIVED_REPORT_RESPONSE,
        "proposal": request["proposal"],
        "report_request_id": request["report_request_id"],
    }


def _post_report_package(
    client: TestClient, proposal_id: str, payload: dict, headers: dict | None = None
):
    url = f"/advisory/proposals/{proposal_id}/versions/1/memo/report-packages"
    return client.post(url, json=payload, headers=headers)


def test_proposal_memo_api_create_read_project_lineage_and_replay() -> None:
    with TestClient(app) as client:
        proposal_id, memo = _create_proposal_memo(client)
        assert memo["proposal"]["proposal_id"] == proposal_id
        assert memo["proposal_version_no"] == 1
        assert memo["memo_id"].startswith("memo_")
        assert memo["memo_status"] in {"BLOCKED", "PENDING_REVIEW", "READY"}
        assert memo["lifecycle_status"] == "DRAFT"
        assert memo["projection"]["client_ready_publication"] == "BLOCKED"
        assert memo["memo"]["supportability"]["persistence"] == "SUPPORTED_BY_RFC0024_SLICE6"
        assert memo["memo"]["supportability"]["api"] == "SUPPORTED_BY_RFC0024_SLICE7"
        assert (
            memo["memo"]["supportability"]["policy_fee_conflict_enrichment"]
            == "SUPPORTED_BY_RFC0024_SLICE8"
        )
        assert memo["read_posture"]["gateway_supported"] is False
        assert memo["event_count"] == 1
        assert memo["audit_events"][0]["event_type"] == "MEMO_DRAFT_CREATED"
        assert memo["audit_events"][0]["reason"]["idempotency_key"] == "memo-api-create"
        assert memo["replay_metadata"]["idempotency_key"] == "memo-api-create"
        assert memo["audit_events"][0]["reason"]["creation_reason"] == {"purpose": "advisor review"}
        assert memo["replay_metadata"]["creation_reason"] == {"purpose": "advisor review"}
        assert memo["replay_metadata"]["proposal_artifact_hash"].startswith("sha256:")

        replayed_create = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo",
            json={"created_by": "advisor_1", "reason": {"purpose": "advisor review"}},
            headers={"Idempotency-Key": "memo-api-create"},
        )
        assert replayed_create.status_code == 200
        assert replayed_create.json()["memo_id"] == memo["memo_id"]
        assert replayed_create.json()["event_count"] == 1

        drifted_create = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo",
            json={"created_by": "advisor_1", "reason": {"purpose": "different"}},
            headers={"Idempotency-Key": "memo-api-create"},
        )
        assert drifted_create.status_code == 409
        assert "MEMO_IDEMPOTENCY_KEY_CONFLICT" in drifted_create.json()["detail"]

        read = client.get(f"/advisory/proposals/{proposal_id}/versions/1/memo")
        assert read.status_code == 200
        assert read.json()["memo_hash"] == memo["memo_hash"]

        projection = client.get(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/projection",
            params={"audience": "ADVISOR"},
        )
        assert projection.status_code == 200
        projection_body = projection.json()
        assert projection_body["memo_id"] == memo["memo_id"]
        assert projection_body["projection_posture"]["mutation_performed"] is False
        assert projection_body["projection_posture"]["client_ready_publication"] == "BLOCKED"
        assert projection_body["sections"]
        assert all(
            "ADVISOR" in section["audience_visibility"] for section in projection_body["sections"]
        )

        lineage = client.get(f"/advisory/proposals/{proposal_id}/memos/lineage")
        assert lineage.status_code == 200
        lineage_body = lineage.json()
        assert lineage_body["memo_count"] == 1
        assert lineage_body["latest_memo_id"] == memo["memo_id"]
        assert lineage_body["lineage_complete"] is True

        replay = client.get(f"/advisory/proposals/{proposal_id}/versions/1/memo/replay-evidence")
        assert replay.status_code == 200
        replay_body = replay.json()
        assert replay_body["subject"]["memo_id"] == memo["memo_id"]
        assert replay_body["hashes"]["memo_hash"] == memo["memo_hash"]
        assert replay_body["explanation"]["client_ready_publication"] == "BLOCKED"


def test_proposal_memo_review_and_report_package_events_are_idempotent_and_hash_guarded() -> None:
    with TestClient(app) as client:
        proposal_id, memo = _create_proposal_memo(client)

        review_payload = {
            "action": "APPROVE_FOR_ADVISOR_USE",
            "reviewed_by": "compliance_1",
            "reason": "Evidence is sufficient for advisor discussion.",
            "source_memo_hash": memo["memo_hash"],
        }
        review = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/review",
            json=review_payload,
            headers={"Idempotency-Key": "  memo-review-1  "},
        )
        assert review.status_code == 200
        review_body = review.json()
        assert review_body["replayed"] is False
        assert review_body["review_event"]["event_type"] == "MEMO_REVIEW_RECORDED"
        assert review_body["review_event"]["reason"]["idempotency_key"] == "memo-review-1"
        assert review_body["memo"]["review_posture"]["review_action"] == "APPROVE_FOR_ADVISOR_USE"

        replayed_review = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/review",
            json=review_payload,
            headers={"Idempotency-Key": "memo-review-1"},
        )
        assert replayed_review.status_code == 200
        assert replayed_review.json()["replayed"] is True
        assert (
            replayed_review.json()["review_event"]["event_id"]
            == (review_body["review_event"]["event_id"])
        )

        drifted_review = dict(review_payload)
        drifted_review["reason"] = "Different review reason"
        conflict = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/review",
            json=drifted_review,
            headers={"Idempotency-Key": "memo-review-1"},
        )
        assert conflict.status_code == 409
        assert "MEMO_EVENT_IDEMPOTENCY_KEY_CONFLICT" in conflict.json()["detail"]

        stale = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/review",
            json={**review_payload, "source_memo_hash": "sha256:stale"},
        )
        assert stale.status_code == 422
        assert stale.json()["detail"] == "MEMO_SOURCE_HASH_MISMATCH"

        client_ready = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/review",
            json={**review_payload, "client_ready_release_requested": True},
        )
        assert client_ready.status_code == 422
        assert client_ready.json()["detail"] == "MEMO_CLIENT_READY_RELEASE_NOT_SUPPORTED"

        report_event = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/report-package-events",
            json={
                "recorded_by": "ops_1",
                "report_package_id": "memo_report_package_001",
                "report_package_status": "BLOCKED",
                "source_memo_hash": memo["memo_hash"],
                "reason": {"blocked_by": "CLIENT_READY_MEMO_NOT_SUPPORTED"},
            },
            headers={"Idempotency-Key": "memo-report-event-1"},
        )
        assert report_event.status_code == 200
        report_body = report_event.json()
        assert report_body["replayed"] is False
        assert report_body["report_package_event"]["event_type"] == "MEMO_REPORT_PACKAGE_RECORDED"
        assert report_body["memo"]["report_package_posture"]["report_package_status"] == "BLOCKED"

        replay = client.get(f"/advisory/proposals/{proposal_id}/versions/1/memo/replay-evidence")
        assert replay.status_code == 200
        replay_body = replay.json()
        event_types = [event["event_type"] for event in replay_body["audit_events"]]
        assert event_types == [
            "MEMO_DRAFT_CREATED",
            "MEMO_REVIEW_RECORDED",
            "MEMO_REPORT_PACKAGE_RECORDED",
        ]


def test_proposal_memo_report_package_projects_persisted_version_and_replays_once() -> None:
    captured_requests: list[dict] = []

    def _fake_report_package(request: dict) -> dict:
        captured_requests.append(request)
        return _archived_report_response(request)

    api_main.request_proposal_memo_report_package_with_lotus_report = _fake_report_package

    with TestClient(app) as client:
        proposal_id = _create_proposal(client)["proposal"]["proposal_id"]
        repository = get_proposal_repository()
        persisted_version = repository.get_version(proposal_id=proposal_id, version_no=1)
        assert persisted_version is not None
        persisted_version.proposal_result_json.setdefault("explanation", {})["risk_lens"] = {
            "metadata": {"as_of_date": "2026-04-10"}
        }
        repository.create_version(persisted_version)
        memo = _create_memo(client, proposal_id)
        _approve_memo(
            client,
            proposal_id,
            memo,
            idempotency_key="memo-report-package-review",
        )

        report_payload = {
            "requested_by": "advisor_1",
            "source_memo_hash": memo["memo_hash"],
            "requested_output_formats": ["pdf"],
            "reason": {"purpose": "advisor-use memo report package"},
        }
        report_headers = {"Idempotency-Key": "memo-report-package-materialize"}
        materialized = _post_report_package(client, proposal_id, report_payload, report_headers)

        assert materialized.status_code == 200
        body = materialized.json()
        assert body["report"]["status"] == "ARCHIVED"
        assert body["report_package_event"]["reason"]["report_package_id"] == "rjob_memo_001"
        assert body["report_package_event"]["reason"]["render"]["render_job_id"] == "rdr_memo_001"
        assert body["report_package_event"]["reason"]["archive"]["document_id"] == "doc_memo_001"
        assert captured_requests[0]["proposal_memo_package"]["memo_id"] == memo["memo_id"]
        assert (
            captured_requests[0]["proposal_memo_package"]["review"]["review_action"]
            == "APPROVE_FOR_ADVISOR_USE"
        )
        assert (
            captured_requests[0]["proposal_memo_package"]["client_ready_publication"] == "BLOCKED"
        )
        assert "proposal_result" in captured_requests[0]["proposal_version"]
        assert "proposal_result_json" not in captured_requests[0]["proposal_version"]
        mapped_job_request = build_memo_report_package_job_request(captured_requests[0])
        assert mapped_job_request["as_of_date"] == "2026-04-10"
        assert mapped_job_request["reporting_currency"] == "USD"
        assert (
            mapped_job_request["proposal_memo_package"]
            == captured_requests[0]["proposal_memo_package"]
        )

        replayed = _post_report_package(client, proposal_id, report_payload, report_headers)
        assert replayed.status_code == 200
        replayed_body = replayed.json()
        assert replayed_body["replayed"] is True
        assert (
            replayed_body["report_package_event"]["event_id"]
            == body["report_package_event"]["event_id"]
        )
        assert replayed_body["report"]["report_reference_id"] == "rjob_memo_001"
        assert len(captured_requests) == 1

        lineage = client.get(f"/advisory/proposals/{proposal_id}/memos/lineage")
        assert lineage.status_code == 200
        lineage_memo = lineage.json()["memos"][0]
        assert lineage_memo["report_package_posture"]["report_status"] == "ARCHIVED"
        assert lineage_memo["archive_refs"][0]["document_id"] == "doc_memo_001"


def test_proposal_memo_report_retry_reuses_downstream_identity_after_event_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_report_request_ids: list[str] = []

    def _fake_report_package(request: dict) -> dict:
        captured_report_request_ids.append(request["report_request_id"])
        return _archived_report_response(request)

    api_main.request_proposal_memo_report_package_with_lotus_report = _fake_report_package

    with TestClient(app) as client:
        proposal_id, memo = _create_proposal_memo(client)
        _approve_memo(
            client,
            proposal_id,
            memo,
            idempotency_key="memo-report-retry-review",
        )

        repository = get_proposal_repository()
        append_memo_event = repository.append_memo_event
        failed_once = False

        def _fail_first_report_event(event: ProposalMemoEventRecord) -> None:
            nonlocal failed_once
            if event.event_type == "MEMO_REPORT_PACKAGE_RECORDED" and not failed_once:
                failed_once = True
                raise RuntimeError("simulated event persistence failure")
            append_memo_event(event)

        monkeypatch.setattr(repository, "append_memo_event", _fail_first_report_event)
        payload = {
            "requested_by": "advisor_1",
            "source_memo_hash": memo["memo_hash"],
            "requested_output_formats": ["pdf"],
            "reason": {"purpose": "advisor-use memo report package"},
        }
        headers = {"Idempotency-Key": "memo-report-persistence-gap"}

        with pytest.raises(RuntimeError, match="simulated event persistence failure"):
            _post_report_package(client, proposal_id, payload, headers)

        conflict = _post_report_package(
            client,
            proposal_id,
            {**payload, "reason": {"purpose": "different advisor-use report package"}},
            headers,
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "MEMO_EVENT_IDEMPOTENCY_KEY_CONFLICT"
        assert len(captured_report_request_ids) == 1

        retried = _post_report_package(client, proposal_id, payload, headers)

        assert retried.status_code == 200
        assert retried.json()["replayed"] is False
        assert len(captured_report_request_ids) == 2
        assert len(set(captured_report_request_ids)) == 1
        assert captured_report_request_ids[0].startswith("prr_")
        assert "memo-report-persistence-gap" not in captured_report_request_ids[0]
        events = repository.list_memo_events(memo_id=memo["memo_id"])
        assert [event.event_type for event in events].count("MEMO_REPORT_PACKAGE_RECORDED") == 1


def test_proposal_memo_report_package_blocks_without_review_and_client_ready_request() -> None:
    with TestClient(app) as client:
        proposal_id, memo = _create_proposal_memo(client)

        unreviewed = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/report-packages",
            json={"requested_by": "advisor_1", "source_memo_hash": memo["memo_hash"]},
        )
        assert unreviewed.status_code == 422
        assert unreviewed.json()["detail"] == "MEMO_REPORT_PACKAGE_REQUIRES_ADVISOR_USE_REVIEW"

        _approve_memo(client, proposal_id, memo)
        client_ready = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/report-packages",
            json={
                "requested_by": "advisor_1",
                "source_memo_hash": memo["memo_hash"],
                "client_ready_document_requested": True,
            },
        )
        assert client_ready.status_code == 422
        assert client_ready.json()["detail"] == "MEMO_CLIENT_READY_DOCUMENT_NOT_SUPPORTED"


def test_proposal_memo_report_package_maps_runtime_provider_failure_to_503(monkeypatch) -> None:
    def _raise_unavailable(**_: object) -> None:
        raise LotusReportUnavailableError("LOTUS_REPORT_REQUEST_UNAVAILABLE")

    monkeypatch.setattr(
        api_main,
        "request_proposal_memo_report_package_with_lotus_report",
        _raise_unavailable,
        raising=False,
    )

    with TestClient(app) as client:
        proposal_id, memo = _create_proposal_memo(client)
        _approve_memo(client, proposal_id, memo)

        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/report-packages",
            json={
                "requested_by": "advisor_1",
                "source_memo_hash": memo["memo_hash"],
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "LOTUS_REPORT_REQUEST_UNAVAILABLE"


def test_proposal_memo_report_package_rejects_empty_output_formats() -> None:
    with TestClient(app) as client:
        proposal_id, memo = _create_proposal_memo(client)
        _approve_memo(client, proposal_id, memo)

        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/report-packages",
            json={
                "requested_by": "advisor_1",
                "source_memo_hash": memo["memo_hash"],
                "requested_output_formats": [],
            },
        )

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "requested_output_formats"]


def test_proposal_memo_ai_commentary_is_review_gated_idempotent_and_non_authoritative(
    monkeypatch,
) -> None:
    captured_requests: list[dict] = []

    def _fake_ai_commentary(**kwargs) -> ProposalMemoAiCommentaryDraft:
        captured_requests.append(kwargs)
        return ProposalMemoAiCommentaryDraft(
            status="REVIEW_REQUIRED",
            sections=(
                {
                    "section_key": "EXECUTIVE_SUMMARY",
                    "title": "Executive Summary",
                    "text": "Advisor-use commentary from bounded memo evidence.",
                    "review_state": "REVIEW_REQUIRED",
                },
            ),
            lineage={
                "workflow_pack_id": "proposal_memo_commentary.pack",
                "workflow_pack_version": "v1",
                "workflow_run_id": "packrun_memo_commentary_001",
                "fallback_reason": None,
            },
            review_guidance=("Review against persisted memo hash before advisor use.",),
        )

    monkeypatch.setattr(
        memo_api,
        "generate_proposal_memo_commentary_with_lotus_ai",
        _fake_ai_commentary,
    )

    with TestClient(app) as client:
        proposal_id, memo = _create_proposal_memo(client)

        unreviewed = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/ai-commentary",
            json={"requested_by": "advisor_1", "source_memo_hash": memo["memo_hash"]},
        )
        assert unreviewed.status_code == 422
        assert unreviewed.json()["detail"] == "MEMO_REPORT_PACKAGE_REQUIRES_ADVISOR_USE_REVIEW"

        _approve_memo(client, proposal_id, memo)

        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/ai-commentary",
            json={
                "requested_by": "advisor_1",
                "source_memo_hash": memo["memo_hash"],
                "requested_sections": ["EXECUTIVE_SUMMARY"],
                "reason": {"purpose": "advisor-use commentary"},
            },
            headers={"Idempotency-Key": "memo-ai-commentary-1"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["replayed"] is False
        assert body["ai_event"]["event_type"] == "MEMO_AI_REFERENCE_RECORDED"
        assert body["commentary"]["status"] == "REVIEW_REQUIRED"
        assert body["commentary"]["authoritative_for_memo_status"] is False
        assert body["commentary"]["client_ready_publication"] == "BLOCKED"
        assert body["memo"]["memo_hash"] == memo["memo_hash"]
        assert body["memo"]["memo_status"] == memo["memo_status"]
        assert captured_requests[0]["memo_evidence"]["memo_hash"] == memo["memo_hash"]
        assert captured_requests[0]["memo_evidence"]["client_ready_publication"] == "BLOCKED"
        assert "memo" not in captured_requests[0]["memo_evidence"]

        replayed = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/ai-commentary",
            json={
                "requested_by": "advisor_1",
                "source_memo_hash": memo["memo_hash"],
                "requested_sections": ["EXECUTIVE_SUMMARY"],
                "reason": {"purpose": "advisor-use commentary"},
            },
            headers={"Idempotency-Key": "memo-ai-commentary-1"},
        )
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["ai_event"]["event_id"] == body["ai_event"]["event_id"]

        lineage = client.get(f"/advisory/proposals/{proposal_id}/memos/lineage")
        assert lineage.status_code == 200
        ai_posture = lineage.json()["memos"][0]["ai_commentary_posture"]
        assert ai_posture["ai_status"] == "REVIEW_REQUIRED"
        assert ai_posture["authoritative_for_memo_status"] is False


def test_proposal_memo_ai_retry_reuses_original_downstream_run_after_event_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downstream_runs: dict[str, str] = {}
    received_idempotency_keys: list[str] = []

    def _fake_keyed_ai_commentary(**kwargs: object) -> ProposalMemoAiCommentaryDraft:
        idempotency_key = kwargs.get("idempotency_key")
        assert isinstance(idempotency_key, str)
        received_idempotency_keys.append(idempotency_key)
        workflow_run_id = downstream_runs.setdefault(
            idempotency_key, "packrun_memo_commentary_original"
        )
        return ProposalMemoAiCommentaryDraft(
            status="REVIEW_REQUIRED",
            sections=(
                {
                    "section_key": "EXECUTIVE_SUMMARY",
                    "title": "Executive Summary",
                    "text": "Advisor-use commentary from the retained AI response.",
                    "review_state": "REVIEW_REQUIRED",
                },
            ),
            lineage={
                "workflow_pack_id": "proposal_memo_commentary.pack",
                "workflow_pack_version": "v1",
                "workflow_run_id": workflow_run_id,
                "fallback_reason": None,
            },
            review_guidance=("Review against persisted memo evidence.",),
        )

    monkeypatch.setattr(
        memo_api,
        "generate_proposal_memo_commentary_with_lotus_ai",
        _fake_keyed_ai_commentary,
    )

    with TestClient(app) as client:
        proposal_id, memo = _create_proposal_memo(client)
        _approve_memo(
            client,
            proposal_id,
            memo,
            idempotency_key="memo-ai-gap-review",
        )
        repository = get_proposal_repository()
        append_memo_event = repository.append_memo_event
        failed_once = False

        def _fail_first_ai_event(event: ProposalMemoEventRecord) -> None:
            nonlocal failed_once
            if event.event_type == "MEMO_AI_REFERENCE_RECORDED" and not failed_once:
                failed_once = True
                raise RuntimeError("simulated AI event persistence failure")
            append_memo_event(event)

        monkeypatch.setattr(repository, "append_memo_event", _fail_first_ai_event)
        payload = {
            "requested_by": "advisor_1",
            "source_memo_hash": memo["memo_hash"],
            "requested_sections": ["EXECUTIVE_SUMMARY"],
            "reason": {"purpose": "advisor-use commentary"},
        }
        headers = {"Idempotency-Key": "memo-ai-persistence-gap"}

        with pytest.raises(RuntimeError, match="simulated AI event persistence failure"):
            client.post(
                f"/advisory/proposals/{proposal_id}/versions/1/memo/ai-commentary",
                json=payload,
                headers=headers,
            )

        conflict = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/ai-commentary",
            json={**payload, "reason": {"purpose": "changed commentary request"}},
            headers=headers,
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "MEMO_EVENT_IDEMPOTENCY_KEY_CONFLICT"
        assert len(received_idempotency_keys) == 1

        retried = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/ai-commentary",
            json=payload,
            headers=headers,
        )

        assert retried.status_code == 200
        assert retried.json()["replayed"] is False
        assert (
            retried.json()["commentary"]["lineage"]["workflow_run_id"]
            == "packrun_memo_commentary_original"
        )
        assert len(received_idempotency_keys) == 2
        assert len(set(received_idempotency_keys)) == 1
        assert len(downstream_runs) == 1
        assert received_idempotency_keys[0].startswith("memo_ai_")
        assert "memo-ai-persistence-gap" not in received_idempotency_keys[0]
        events = repository.list_memo_events(memo_id=memo["memo_id"])
        ai_events = [event for event in events if event.event_type == "MEMO_AI_REFERENCE_RECORDED"]
        assert len(ai_events) == 1
        assert ai_events[0].reason_json["lineage"]["workflow_run_id"] == (
            "packrun_memo_commentary_original"
        )


def test_proposal_memo_ai_commentary_rejects_empty_requested_sections() -> None:
    with TestClient(app) as client:
        proposal_id, memo = _create_proposal_memo(client)
        _approve_memo(client, proposal_id, memo)

        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/ai-commentary",
            json={
                "requested_by": "advisor_1",
                "source_memo_hash": memo["memo_hash"],
                "requested_sections": [],
            },
        )

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "requested_sections"]


def test_proposal_memo_ai_commentary_records_deterministic_unavailable_posture() -> None:
    with TestClient(app) as client:
        proposal_id, memo = _create_proposal_memo(client)
        _approve_memo(client, proposal_id, memo)

        response = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo/ai-commentary",
            json={"requested_by": "advisor_1", "source_memo_hash": memo["memo_hash"]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["commentary"]["status"] == "UNAVAILABLE"
        assert body["commentary"]["lineage"]["fallback_reason"] == (
            "LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE"
        )
        assert body["commentary"]["sections"] == []
        assert body["memo"]["memo_hash"] == memo["memo_hash"]


def test_memo_api_blocks_finalization_until_source_ready_and_reports_missing_memo() -> None:
    with TestClient(app) as client:
        proposal_id = _create_proposal(client)["proposal"]["proposal_id"]

        missing = client.get(f"/advisory/proposals/{proposal_id}/versions/1/memo")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "PROPOSAL_MEMO_NOT_FOUND"

        finalized = client.post(
            f"/advisory/proposals/{proposal_id}/versions/1/memo",
            json={"created_by": "advisor_1", "lifecycle_status": "FINALIZED"},
            headers={"Idempotency-Key": "memo-finalized-blocked"},
        )
        assert finalized.status_code == 422
        assert finalized.json()["detail"] == "MEMO_FINALIZATION_BLOCKED_BY_EVIDENCE_POSTURE"
