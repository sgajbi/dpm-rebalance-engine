import httpx
import pytest

from src.integrations.lotus_report.adapter import (
    LotusReportUnavailableError,
    _resolve_status_poll_attempts,
    _resolve_status_poll_backoff_seconds,
    _resolve_timeout,
    request_policy_sign_off_report_package_with_lotus_report,
    request_proposal_memo_report_package_with_lotus_report,
    request_proposal_report_with_lotus_report,
)


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: object,
        *,
        method: str = "POST",
        url: str = "http://report.dev.lotus/reports/portfolio-reviews",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request(method, url)

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "report unavailable",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class _FakeClient:
    def __init__(
        self,
        response: _FakeResponse,
        status_payload: dict | list[dict] | None = None,
        *,
        status_code: int = 200,
        status_json: object | None = None,
    ) -> None:
        self.response = response
        self.status_payloads = _status_payload_sequence(status_payload)
        self.status_code = status_code
        self.status_json = status_json
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, *, json: dict, headers: dict[str, str]) -> _FakeResponse:
        self.posts.append({"url": url, "json": json, "headers": headers})
        return self.response

    def get(self, url: str, *, headers: dict[str, str]) -> _FakeResponse:
        self.gets.append({"url": url, "headers": headers})
        if self.status_json is not None:
            return _FakeResponse(self.status_code, self.status_json, method="GET", url=url)
        payload_index = min(len(self.gets) - 1, len(self.status_payloads) - 1)
        return _FakeResponse(
            self.status_code,
            self.status_payloads[payload_index],
            method="GET",
            url=url,
        )


def _status_payload_sequence(status_payload: dict | list[dict] | None) -> list[dict]:
    if isinstance(status_payload, list):
        return status_payload
    if isinstance(status_payload, dict):
        return [status_payload]
    return [
        {
            "status": "archived",
            "render": {"render_job_id": "rdr_memo_001"},
            "archive": {"document_id": "doc_memo_001"},
        }
    ]


def _proposal_request() -> dict:
    return {
        "report_request_id": "prr_live_001",
        "proposal": {
            "proposal_id": "pp_live_001",
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "jurisdiction": "SG",
            "created_by": "advisor_1",
            "created_at": "2026-05-23T00:00:00Z",
            "last_event_at": "2026-05-23T00:01:00Z",
            "current_state": "DRAFT",
            "current_version_no": 1,
            "lifecycle_origin": "DIRECT_CREATE",
        },
        "proposal_version": {
            "proposal_result": {
                "before": {"total_value": {"amount": "100.00", "currency": "USD"}},
                "analytics": {"metadata": {"as_of_date": "2026-04-10"}},
            }
        },
        "report_type": "PORTFOLIO_REVIEW",
        "requested_by": "advisor_1",
        "related_version_no": 1,
        "include_execution_summary": True,
        "include_reviewed_narrative": True,
        "proposal_narrative_package": {
            "package_status": "INCLUDED_REVIEWED_NARRATIVE",
            "usage": "REPORT_REQUEST_APPROVED_ADVISOR_NARRATIVE",
            "proposal_id": "pp_live_001",
            "proposal_version_no": 1,
            "narrative_id": "pnar_live_001",
            "review": {"review_state": "APPROVED_FOR_ADVISOR_USE"},
            "source_lineage": {"source_narrative_hash": "sha256:narrative"},
            "sections": [
                {
                    "section_id": "executive_summary",
                    "title": "Executive Summary",
                    "body": "Advisor-reviewed narrative.",
                }
            ],
        },
    }


def _memo_report_package_request() -> dict:
    request = _proposal_request()
    request.update(
        {
            "report_request_id": "prr_memo_001",
            "requested_output_formats": ["pdf"],
            "proposal_memo_package": {
                "package_status": "INCLUDED_ADVISOR_PROPOSAL_MEMO",
                "usage": "REPORT_REQUEST_APPROVED_ADVISOR_MEMO",
                "memo_id": "memo_001",
                "memo_version": "advisory-proposal-memo-evidence-pack.v1",
                "memo_status": "READY",
                "proposal_id": "pp_live_001",
                "proposal_version_no": 1,
                "memo_hash": "sha256:memo",
                "source_input_hash": "sha256:source",
                "review": {"review_action": "APPROVE_FOR_ADVISOR_USE"},
                "sections": [{"section_id": "EXECUTIVE_SUMMARY", "summary": "Advisor memo."}],
                "client_ready_publication": "BLOCKED",
            },
        }
    )
    return request


def _policy_report_package_request() -> dict:
    request = _proposal_request()
    request.update(
        {
            "report_request_id": "prr_policy_001",
            "requested_output_formats": ["pdf"],
            "related_policy_evaluation_id": "pev_policy_001",
            "policy_sign_off_package": {
                "package_type": "ADVISORY_POLICY_SIGN_OFF_PACKAGE",
                "package_status": "SIGNED_OFF_SOURCE_PACKAGE",
                "evaluation": {
                    "evaluation_id": "pev_policy_001",
                    "evaluation_hash": "sha256:policy-evaluation",
                },
                "workflow": {"sign_off_status": "SIGNED_OFF"},
                "client_ready_publication": "BLOCKED",
            },
        }
    )
    return request


def test_lotus_report_adapter_submits_portfolio_review_job_with_reviewed_narrative(
    monkeypatch,
) -> None:
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_report_001",
                "status": "data_ready",
                "status_url": "/reports/jobs/rjob_report_001",
                "idempotency_key": "prr_live_001",
            },
        )
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_report_with_lotus_report(request=_proposal_request())

    assert response.status == "READY"
    assert response.report_request_id == "prr_live_001"
    assert response.report_reference_id == "rjob_report_001"
    assert response.explanation["proposal_narrative_package"] == {
        "package_status": "INCLUDED_REVIEWED_NARRATIVE",
        "narrative_id": "pnar_live_001",
        "review_state": "APPROVED_FOR_ADVISOR_USE",
        "source_narrative_hash": "sha256:narrative",
    }
    [post] = fake_client.posts
    assert post["url"] == "http://report.dev.lotus/reports/portfolio-reviews"
    assert post["headers"]["Idempotency-Key"] == "prr_live_001"
    assert post["headers"]["X-Caller-Application"] == "lotus-advise"
    assert post["headers"]["X-Actor-Id"] == "advisor_1"
    assert post["headers"]["X-Tenant-Id"] == "tenant-sg-001"
    assert post["json"]["portfolio_scope"] == {"portfolio_ids": ["PB_SG_GLOBAL_BAL_001"]}
    assert post["json"]["as_of_date"] == "2026-04-10"
    assert post["json"]["requested_output_formats"] == ["json"]
    assert post["json"]["proposal_narrative_package"]["narrative_id"] == "pnar_live_001"


def test_lotus_report_adapter_sanitizes_configured_base_url(monkeypatch) -> None:
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_report_001",
                "status": "data_ready",
                "idempotency_key": "prr_live_001",
            },
        )
    )
    monkeypatch.setenv(
        "LOTUS_REPORT_BASE_URL",
        "https://user:secret@report.dev.lotus:8300/api?token=should-not-leak#fragment",
    )
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    request_proposal_report_with_lotus_report(request=_proposal_request())

    [post] = fake_client.posts
    assert post["url"] == "https://report.dev.lotus:8300/api/reports/portfolio-reviews"
    assert "secret" not in post["url"]
    assert "token" not in post["url"]


def test_lotus_report_adapter_bounds_identity_headers_and_payload_actor(monkeypatch) -> None:
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_report_001",
                "status": "data_ready",
                "idempotency_key": "prr_live_001",
            },
        )
    )
    request = _proposal_request()
    request["requested_by"] = "advisor_sg_002"
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", " tenant-private-bank-001 ")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    request_proposal_report_with_lotus_report(request=request)

    [post] = fake_client.posts
    assert post["headers"]["X-Actor-Id"] == "advisor_sg_002"
    assert post["headers"]["X-Tenant-Id"] == "tenant-private-bank-001"
    assert post["json"]["options"] == {}


def test_lotus_report_adapter_rejects_invalid_tenant_identity_before_http_client(
    monkeypatch,
) -> None:
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_report_001",
                "status": "data_ready",
                "idempotency_key": "prr_live_001",
            },
        )
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", "tenant-private-bank-001\x7f")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        request_proposal_report_with_lotus_report(request=_proposal_request())

    assert fake_client.posts == []


def test_lotus_report_adapter_rejects_invalid_actor_identity_before_http_client(
    monkeypatch,
) -> None:
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_report_001",
                "status": "data_ready",
                "idempotency_key": "prr_live_001",
            },
        )
    )
    request = _proposal_request()
    request["requested_by"] = "advisor_1\x7f"
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", "tenant-private-bank-001")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        request_proposal_report_with_lotus_report(request=request)

    assert fake_client.posts == []


def test_lotus_report_adapter_normalizes_pending_status_and_lineage_dates(monkeypatch) -> None:
    request = _proposal_request()
    request["proposal_version"] = {
        "proposal_result": {
            "before": {"total_value": {"amount": "100.00", "currency": "SGD"}},
            "lineage": {
                "core_snapshot_uri": "s3://lotus-core/snapshots/PB_SG_GLOBAL_BAL_001/2026-05-28"
            },
        }
    }
    request["proposal"]["jurisdiction"] = "HK"
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_job_id": "rjob_report_pending_001",
                "status": "queued_for_render",
                "status_url": "/reports/jobs/rjob_report_pending_001",
            },
        )
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_report_with_lotus_report(request=request)

    assert response.status == "QUEUED_FOR_RENDER"
    [post] = fake_client.posts
    assert post["headers"]["X-Region"] == "HK"
    assert post["json"]["as_of_date"] == "2026-05-28"
    assert post["json"]["reporting_currency"] == "SGD"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda request: request["proposal_version"]["proposal_result"].pop("analytics"),
        lambda request: request["proposal_version"]["proposal_result"].pop("before"),
        lambda request: request["proposal"].update({"jurisdiction": ""}),
    ],
)
def test_lotus_report_adapter_rejects_missing_report_source_metadata_before_http_client(
    monkeypatch,
    mutator,
) -> None:
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_report_001",
                "status": "data_ready",
                "idempotency_key": "prr_live_001",
            },
        )
    )
    request = _proposal_request()
    mutator(request)
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", "tenant-private-bank-001")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        request_proposal_report_with_lotus_report(request=request)

    assert fake_client.posts == []


def test_lotus_report_adapter_submits_memo_package_for_pdf_render_archive(monkeypatch) -> None:
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_memo_001",
                "status": "archived",
                "status_url": "/reports/jobs/rjob_memo_001",
                "idempotency_key": "prr_memo_001",
            },
        )
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_memo_report_package_with_lotus_report(
        request=_memo_report_package_request()
    )

    assert response.status == "ARCHIVED"
    assert response.report_reference_id == "rjob_memo_001"
    assert response.artifact_url == "/reports/jobs/rjob_memo_001"
    assert response.explanation["report_job_status_url"] == "/reports/jobs/rjob_memo_001"
    assert response.explanation["render"]["render_job_id"] == "rdr_memo_001"
    assert response.explanation["archive"]["document_id"] == "doc_memo_001"
    [post] = fake_client.posts
    assert post["json"]["requested_output_formats"] == ["pdf"]
    assert post["json"]["proposal_memo_package"]["memo_id"] == "memo_001"
    assert post["json"]["proposal_memo_package"]["client_ready_publication"] == "BLOCKED"
    assert fake_client.gets == [
        {
            "url": "http://report.dev.lotus/reports/jobs/rjob_memo_001",
            "headers": post["headers"],
        }
    ]


def test_lotus_report_adapter_polls_memo_package_until_archived(monkeypatch) -> None:
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_memo_001",
                "status": "accepted",
                "status_url": "/reports/jobs/rjob_memo_001",
                "idempotency_key": "prr_memo_001",
            },
        ),
        status_payload=[
            {"status": "accepted"},
            {"status": "running"},
            {
                "status": "archived",
                "render": {"render_job_id": "rdr_memo_001"},
                "archive": {"document_id": "doc_memo_001"},
            },
        ],
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setenv("LOTUS_REPORT_STATUS_POLL_ATTEMPTS", "3")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_memo_report_package_with_lotus_report(
        request=_memo_report_package_request()
    )

    assert response.status == "ARCHIVED"
    assert response.explanation["report_job_poll_attempts"] == 3
    assert response.explanation["render"]["render_job_id"] == "rdr_memo_001"
    assert response.explanation["archive"]["document_id"] == "doc_memo_001"
    assert len(fake_client.gets) == 3


def test_lotus_report_adapter_returns_pending_after_bounded_status_poll_timeout(
    monkeypatch,
) -> None:
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_memo_001",
                "status": "accepted",
                "status_url": "/reports/jobs/rjob_memo_001",
                "idempotency_key": "prr_memo_001",
            },
        ),
        status_payload=[{"status": "accepted"}, {"status": "running"}],
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setenv("LOTUS_REPORT_STATUS_POLL_ATTEMPTS", "2")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_memo_report_package_with_lotus_report(
        request=_memo_report_package_request()
    )

    assert response.status == "RUNNING"
    assert response.report_reference_id == "rjob_memo_001"
    assert response.explanation["report_job_pending_reason"] == "REPORT_STATUS_POLLING_TIMEOUT"
    assert response.explanation["report_job_poll_attempts"] == 2
    assert response.explanation["render"] == {}
    assert response.explanation["archive"] == {}
    assert len(fake_client.gets) == 2


def test_lotus_report_adapter_defaults_memo_outputs_and_reports_missing_status_url(
    monkeypatch,
) -> None:
    request = _memo_report_package_request()
    request["requested_output_formats"] = ["xlsx", "", "JSON"]
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_job_id": "rjob_memo_accepted_001",
                "status": "completed_with_warnings",
            },
        )
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_memo_report_package_with_lotus_report(request=request)

    assert response.status == "REPORT_STATUS_UNAVAILABLE"
    assert response.report_reference_id == "rjob_memo_accepted_001"
    assert (
        response.explanation["report_job_status_unavailable_reason"]
        == "REPORT_STATUS_URL_UNAVAILABLE"
    )
    assert response.explanation["render"] == {}
    assert response.explanation["archive"] == {}
    [post] = fake_client.posts
    assert post["json"]["requested_output_formats"] == ["json"]
    assert fake_client.gets == []


def test_lotus_report_adapter_ignores_untrusted_status_url(monkeypatch) -> None:
    request = _memo_report_package_request()
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_memo_001",
                "status": "accepted",
                "status_url": "https://example.invalid/reports/jobs/rjob_memo_001",
                "idempotency_key": "prr_memo_001",
            },
        )
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_memo_report_package_with_lotus_report(request=request)

    assert response.status == "REPORT_STATUS_UNAVAILABLE"
    assert response.artifact_url is None
    assert response.explanation["report_job_status_url"] is None
    assert (
        response.explanation["report_job_status_unavailable_reason"]
        == "REPORT_STATUS_URL_UNAVAILABLE"
    )
    assert response.explanation["render"] == {}
    assert response.explanation["archive"] == {}
    assert fake_client.gets == []


def test_lotus_report_adapter_ignores_status_url_with_query_material(monkeypatch) -> None:
    request = _memo_report_package_request()
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_memo_001",
                "status": "accepted",
                "status_url": "/reports/jobs/rjob_memo_001?token=secret",
                "idempotency_key": "prr_memo_001",
            },
        )
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_memo_report_package_with_lotus_report(request=request)

    assert response.status == "REPORT_STATUS_UNAVAILABLE"
    assert response.artifact_url is None
    assert response.explanation["report_job_status_url"] is None
    assert (
        response.explanation["report_job_status_unavailable_reason"]
        == "REPORT_STATUS_URL_UNAVAILABLE"
    )
    assert fake_client.gets == []


def test_lotus_report_adapter_returns_unavailable_when_status_lookup_fails(
    monkeypatch,
) -> None:
    request = _memo_report_package_request()
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_memo_001",
                "status": "accepted",
                "status_url": "/reports/jobs/rjob_memo_001",
                "idempotency_key": "prr_memo_001",
            },
        ),
        status_code=503,
        status_json={"detail": "not ready"},
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_memo_report_package_with_lotus_report(request=request)

    assert response.status == "REPORT_STATUS_UNAVAILABLE"
    assert response.report_reference_id == "rjob_memo_001"
    assert response.explanation["report_job_status_unavailable_reason"] == "REPORT_STATUS_HTTP_503"
    assert len(fake_client.gets) == 1


def test_lotus_report_adapter_returns_unavailable_for_malformed_status_payload(
    monkeypatch,
) -> None:
    request = _memo_report_package_request()
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_memo_001",
                "status": "accepted",
                "status_url": "/reports/jobs/rjob_memo_001",
                "idempotency_key": "prr_memo_001",
            },
        ),
        status_json=["not", "a", "mapping"],
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_memo_report_package_with_lotus_report(request=request)

    assert response.status == "REPORT_STATUS_UNAVAILABLE"
    assert (
        response.explanation["report_job_status_unavailable_reason"]
        == "REPORT_STATUS_PAYLOAD_INVALID"
    )
    assert len(fake_client.gets) == 1


def test_lotus_report_adapter_preserves_terminal_report_failure(monkeypatch) -> None:
    request = _memo_report_package_request()
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_memo_failed_001",
                "status": "accepted",
                "status_url": "/reports/jobs/rjob_memo_failed_001",
                "idempotency_key": "prr_memo_001",
            },
        ),
        status_payload={
            "status": "render_failed",
            "failure_reason": "TEMPLATE_CONTRACT_INVALID",
        },
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_proposal_memo_report_package_with_lotus_report(request=request)

    assert response.status == "FAILED"
    assert response.report_reference_id == "rjob_memo_failed_001"
    assert response.explanation["report_job_poll_attempts"] == 1
    assert response.explanation["render"] == {}
    assert response.explanation["archive"] == {}


def test_lotus_report_adapter_submits_policy_sign_off_package_for_render_archive(
    monkeypatch,
) -> None:
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_request_id": "rrq_report_001",
                "report_job_id": "rjob_policy_001",
                "status": "archived",
                "status_url": "/reports/jobs/rjob_policy_001",
                "idempotency_key": "prr_policy_001",
            },
        ),
        status_payload={
            "status": "archived",
            "render": {"render_job_id": "rdr_policy_001"},
            "archive": {"document_id": "doc_policy_001"},
        },
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_policy_sign_off_report_package_with_lotus_report(
        request=_policy_report_package_request()
    )

    assert response.status == "ARCHIVED"
    assert response.report_reference_id == "rjob_policy_001"
    assert response.explanation["policy_sign_off_package"]["evaluation_id"] == "pev_policy_001"
    assert response.explanation["policy_sign_off_package"]["client_ready_publication"] == "BLOCKED"
    assert response.explanation["render"]["render_job_id"] == "rdr_policy_001"
    assert response.explanation["archive"]["document_id"] == "doc_policy_001"
    [post] = fake_client.posts
    assert post["json"]["options"] == {}
    assert post["json"]["policy_sign_off_package"]["workflow"]["sign_off_status"] == "SIGNED_OFF"


def test_lotus_report_adapter_defaults_policy_outputs_when_formats_are_invalid(
    monkeypatch,
) -> None:
    request = _policy_report_package_request()
    request["requested_output_formats"] = ["docx"]
    fake_client = _FakeClient(
        _FakeResponse(
            202,
            {
                "report_job_id": "rjob_policy_accepted_001",
                "status": "accepted",
            },
        ),
        status_payload={},
    )
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: fake_client,
    )

    response = request_policy_sign_off_report_package_with_lotus_report(request=request)

    assert response.status == "REPORT_STATUS_UNAVAILABLE"
    assert (
        response.explanation["report_job_status_unavailable_reason"]
        == "REPORT_STATUS_URL_UNAVAILABLE"
    )
    [post] = fake_client.posts
    assert post["json"]["requested_output_formats"] == ["pdf"]


def test_lotus_report_adapter_fails_closed_when_report_base_url_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("LOTUS_REPORT_BASE_URL", raising=False)

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        request_proposal_report_with_lotus_report(request=_proposal_request())


def test_lotus_report_adapter_rejects_invalid_base_url_without_http_client(monkeypatch) -> None:
    def _unexpected_client(*args: object, **kwargs: object) -> _FakeClient:
        raise AssertionError("invalid lotus-report base URL should fail before opening a client")

    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "ftp://report.dev.lotus:8300")
    monkeypatch.setattr("src.integrations.lotus_report.adapter.httpx.Client", _unexpected_client)

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        request_proposal_report_with_lotus_report(request=_proposal_request())


def test_lotus_report_adapter_fails_closed_for_http_and_validation_errors(monkeypatch) -> None:
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")
    monkeypatch.setattr(
        "src.integrations.lotus_report.adapter.httpx.Client",
        lambda timeout: _FakeClient(_FakeResponse(500, {"detail": "down"})),
    )

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        request_proposal_report_with_lotus_report(request=_proposal_request())

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        request_proposal_memo_report_package_with_lotus_report(
            request=_memo_report_package_request()
        )

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        request_policy_sign_off_report_package_with_lotus_report(
            request=_policy_report_package_request()
        )


def test_lotus_report_adapter_requires_request_identifiers(monkeypatch) -> None:
    request = _proposal_request()
    request.pop("report_request_id")
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://report.dev.lotus/")

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        request_proposal_report_with_lotus_report(request=request)


def test_lotus_report_timeout_defaults_to_report_job_acceptance_sla(monkeypatch) -> None:
    monkeypatch.delenv("LOTUS_REPORT_TIMEOUT_SECONDS", raising=False)

    timeout = _resolve_timeout()

    assert timeout.connect == 30.0
    assert timeout.read == 30.0


def test_lotus_report_timeout_uses_positive_override(monkeypatch) -> None:
    monkeypatch.setenv("LOTUS_REPORT_TIMEOUT_SECONDS", "45")

    timeout = _resolve_timeout()

    assert timeout.connect == 45.0
    assert timeout.read == 45.0


@pytest.mark.parametrize("configured_value", ["invalid", "0"])
def test_lotus_report_timeout_rejects_invalid_override(
    monkeypatch,
    configured_value: str,
) -> None:
    monkeypatch.setenv("LOTUS_REPORT_TIMEOUT_SECONDS", configured_value)

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        _resolve_timeout()


def test_lotus_report_status_poll_attempts_defaults_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("LOTUS_REPORT_STATUS_POLL_ATTEMPTS", raising=False)

    assert _resolve_status_poll_attempts() == 3


@pytest.mark.parametrize("configured_value", ["invalid", "0", "6"])
def test_lotus_report_status_poll_attempts_rejects_invalid_override(
    monkeypatch,
    configured_value: str,
) -> None:
    monkeypatch.setenv("LOTUS_REPORT_STATUS_POLL_ATTEMPTS", configured_value)

    with pytest.raises(ValueError, match="LOTUS_REPORT_STATUS_POLL_ATTEMPTS"):
        _resolve_status_poll_attempts()


def test_lotus_report_status_poll_backoff_accepts_zero_override(monkeypatch) -> None:
    monkeypatch.setenv("LOTUS_REPORT_STATUS_POLL_BACKOFF_SECONDS", "0")

    assert _resolve_status_poll_backoff_seconds() == 0.0


@pytest.mark.parametrize("configured_value", ["invalid", "-0.1"])
def test_lotus_report_status_poll_backoff_rejects_invalid_override(
    monkeypatch,
    configured_value: str,
) -> None:
    monkeypatch.setenv("LOTUS_REPORT_STATUS_POLL_BACKOFF_SECONDS", configured_value)

    with pytest.raises(LotusReportUnavailableError, match="LOTUS_REPORT_REQUEST_UNAVAILABLE"):
        _resolve_status_poll_backoff_seconds()
