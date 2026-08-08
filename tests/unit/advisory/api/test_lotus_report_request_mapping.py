import pytest

from src.integrations.lotus_report.request_mapping import (
    LotusReportRequestMappingError,
    build_memo_report_package_job_request,
    build_policy_sign_off_package_job_request,
    build_portfolio_review_job_request,
    build_report_headers,
    extract_report_as_of_date,
    extract_reporting_currency,
    find_first_key_value,
    normalized_output_formats,
    report_status_path,
)


def _proposal_request() -> dict:
    return {
        "report_request_id": "prr_live_001",
        "proposal": {
            "proposal_id": "pp_live_001",
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "jurisdiction": "SG",
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
    }


def test_portfolio_review_mapping_preserves_advisory_report_context() -> None:
    request = _proposal_request()
    request["proposal_narrative_package"] = {
        "package_status": "INCLUDED_REVIEWED_NARRATIVE",
        "narrative_id": "pnar_live_001",
    }

    payload = build_portfolio_review_job_request(request)

    assert payload["portfolio_scope"] == {"portfolio_ids": ["PB_SG_GLOBAL_BAL_001"]}
    assert payload["as_of_date"] == "2026-04-10"
    assert payload["requested_output_formats"] == ["json"]
    assert payload["reporting_currency"] == "USD"
    assert payload["options"] == {}
    assert payload["proposal_narrative_package"]["narrative_id"] == "pnar_live_001"


def test_portfolio_review_mapping_keeps_source_provenance_out_of_report_options() -> None:
    request = _proposal_request()
    request["proposal_narrative_package"] = {
        "package_status": "INCLUDED_REVIEWED_NARRATIVE",
        "proposal_id": "pp_live_001",
        "proposal_version_no": 1,
        "narrative_id": "pnar_live_001",
        "review": {
            "review_state": "APPROVED_FOR_ADVISOR_USE",
            "source_narrative_hash": "sha256:narrative",
        },
        "source_lineage": {"source_narrative_hash": "sha256:narrative"},
        "sections": [
            {
                "section_id": "EXECUTIVE_SUMMARY",
                "title": "Executive Summary",
                "body": "Advisor-reviewed proposal context.",
            }
        ],
    }

    payload = build_portfolio_review_job_request(request)

    assert payload["options"] == {}
    assert payload["proposal_narrative_package"]["proposal_id"] == "pp_live_001"
    assert payload["proposal_narrative_package"]["source_lineage"] == {
        "source_narrative_hash": "sha256:narrative"
    }


def test_memo_and_policy_mappings_keep_report_package_boundaries() -> None:
    memo_request = _proposal_request()
    memo_request.update(
        {
            "requested_output_formats": ["PDF", "xlsx", "json"],
            "reason": {"retention_policy_id": "advisor-use-retention"},
            "proposal_memo_package": {
                "memo_id": "memo_001",
                "client_ready_publication": "BLOCKED",
            },
        }
    )
    policy_request = _proposal_request()
    policy_request.update(
        {
            "requested_output_formats": ["docx"],
            "related_policy_evaluation_id": "pev_policy_001",
            "policy_sign_off_package": {
                "package_type": "ADVISORY_POLICY_SIGN_OFF_PACKAGE",
                "evaluation": {"evaluation_id": "pev_policy_001"},
                "client_ready_publication": "BLOCKED",
            },
        }
    )

    memo_payload = build_memo_report_package_job_request(memo_request)
    policy_payload = build_policy_sign_off_package_job_request(policy_request)

    assert memo_payload["requested_output_formats"] == ["pdf", "json"]
    assert memo_payload["options"] == {"retention_policy_id": "advisor-use-retention"}
    assert memo_payload["proposal_memo_package"]["client_ready_publication"] == "BLOCKED"
    assert policy_payload["requested_output_formats"] == ["pdf"]
    assert policy_payload["options"] == {}
    assert policy_payload["policy_sign_off_package"]["client_ready_publication"] == "BLOCKED"


def test_policy_sign_off_mapping_requires_advisory_package_identity() -> None:
    request = _proposal_request()
    request.update(
        {
            "requested_output_formats": ["pdf"],
            "related_policy_evaluation_id": "pev_policy_001",
            "policy_sign_off_package": {
                "package_type": "PORTFOLIO_REVIEW",
                "evaluation": {"evaluation_id": "pev_policy_001"},
            },
        }
    )

    with pytest.raises(
        LotusReportRequestMappingError,
        match="LOTUS_REPORT_REQUEST_UNAVAILABLE",
    ):
        build_policy_sign_off_package_job_request(request)


def test_mapping_preserves_trusted_headers_output_formats_and_status_paths() -> None:
    request = _proposal_request()

    headers = build_report_headers(
        request=request,
        request_id="prr_live_001",
        tenant_id="tenant-private-bank-001",
    )

    assert headers["X-Actor-Id"] == "advisor_1"
    assert headers["X-Tenant-Id"] == "tenant-private-bank-001"
    assert normalized_output_formats(["xlsx", "", "JSON"]) == ["json"]
    assert normalized_output_formats("pdf") == ["pdf"]
    assert report_status_path("/reports/jobs/rjob_001") == "/reports/jobs/rjob_001"
    assert report_status_path("https://example.invalid/reports/jobs/rjob_001") is None
    assert report_status_path("/reports/jobs/rjob_001?token=secret") is None
    assert report_status_path("/reports/jobs/rjob_001#fragment") is None
    assert report_status_path("/reports/jobs/rjob_001\x7f") is None


@pytest.mark.parametrize(
    ("requested_by", "tenant_id"),
    [
        ("advisor_1\x7f", "tenant-private-bank-001"),
        ("advisor_1", "tenant-private-bank-001\x7f"),
        ("", "tenant-private-bank-001"),
        ("advisor_1", None),
    ],
)
def test_mapping_rejects_untrusted_actor_and_tenant_identity(
    requested_by: str | None,
    tenant_id: str | None,
) -> None:
    request = _proposal_request()
    request["requested_by"] = requested_by

    with pytest.raises(
        LotusReportRequestMappingError,
        match="LOTUS_REPORT_REQUEST_UNAVAILABLE",
    ):
        build_report_headers(
            request=request,
            request_id="prr_live_001",
            tenant_id=tenant_id,
        )


def test_reporting_currency_uses_source_total_value_and_requires_authority() -> None:
    request = _proposal_request()
    request["proposal_version"]["proposal_result"]["before"]["total_value"]["currency"] = " SGD "

    assert extract_reporting_currency(request) == "SGD"

    request["proposal_version"]["proposal_result"].pop("before")

    with pytest.raises(
        LotusReportRequestMappingError,
        match="LOTUS_REPORT_REQUEST_UNAVAILABLE",
    ):
        extract_reporting_currency(request)


def test_find_first_key_value_preserves_depth_first_report_date_selection() -> None:
    payload = {
        "metadata": [
            {"ignored": {"as_of_date": ""}},
            {"nested": {"report_end_date": "2026-04-11"}},
        ],
        "analytics": {"valuation_date": "2026-04-12"},
    }

    assert (
        find_first_key_value(
            payload,
            keys={"as_of_date", "report_end_date", "valuation_date"},
        )
        == "2026-04-11"
    )


def test_extract_report_as_of_date_ignores_invalid_direct_dates_before_lineage_fallback() -> None:
    request = _proposal_request()
    request["proposal_version"]["proposal_result"] = {
        "analytics": {
            "metadata": {
                "as_of_date": "2026-04",
                "valuation_date": "not-a-date",
            }
        },
        "lineage": {"snapshot_ref": "lotus-core/snapshot/2026-04-13.json"},
    }

    assert extract_report_as_of_date(request) == "2026-04-13"


def test_extract_report_as_of_date_rejects_missing_or_conflicting_source_dates() -> None:
    request = _proposal_request()
    request["proposal_version"]["proposal_result"] = {
        "analytics": {"metadata": {"as_of_date": "2026-04-10"}},
        "lineage": {"snapshot_ref": "lotus-core/snapshot/2026-04-13.json"},
    }

    with pytest.raises(
        LotusReportRequestMappingError,
        match="LOTUS_REPORT_REQUEST_UNAVAILABLE",
    ):
        extract_report_as_of_date(request)

    request["proposal_version"]["proposal_result"] = {
        "before": {"total_value": {"amount": "100.00", "currency": "USD"}},
    }

    with pytest.raises(
        LotusReportRequestMappingError,
        match="LOTUS_REPORT_REQUEST_UNAVAILABLE",
    ):
        extract_report_as_of_date(request)


def test_mapping_rejects_missing_report_jurisdiction_before_headers() -> None:
    request = _proposal_request()
    request["proposal"]["jurisdiction"] = ""

    with pytest.raises(
        LotusReportRequestMappingError,
        match="LOTUS_REPORT_REQUEST_UNAVAILABLE",
    ):
        build_report_headers(
            request=request,
            request_id="prr_live_001",
            tenant_id="tenant-private-bank-001",
        )


def test_mapping_fails_closed_when_required_advisory_source_identity_is_missing() -> None:
    request = _proposal_request()
    request["proposal"].pop("portfolio_id")

    with pytest.raises(
        LotusReportRequestMappingError,
        match="LOTUS_REPORT_REQUEST_UNAVAILABLE",
    ):
        build_portfolio_review_job_request(request)
