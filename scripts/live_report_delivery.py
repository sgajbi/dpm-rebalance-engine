from dataclasses import dataclass
from typing import Any, Callable, cast

import httpx


@dataclass(frozen=True)
class ReportDeliveryPrimitives:
    """Dependencies needed to certify report delivery without owning HTTP plumbing."""

    get_json: Callable[..., dict[str, Any]]
    feature_by_key: Callable[..., dict[str, Any]]
    assertion: Callable[..., None]
    assert_persisted_read_surfaces: Callable[..., None]


def assert_report_delivery(
    client: httpx.Client,
    *,
    primitives: ReportDeliveryPrimitives,
    advise_base_url: str,
    proposal_id: str,
    related_version_no: int,
    expected_portfolio_id: str,
) -> str:
    """Assert READY or explicitly degraded report delivery and persisted read surfaces."""

    capabilities = primitives.get_json(
        client,
        url=f"{advise_base_url}/platform/capabilities",
        expected_status=200,
    )
    report_feature = primitives.feature_by_key(capabilities, "advisory.proposals.reporting")
    report_response = client.post(
        f"{advise_base_url}/advisory/proposals/{proposal_id}/report-requests",
        json={
            "report_type": "CLIENT_PROPOSAL_SUMMARY",
            "requested_by": "advisor_1",
            "related_version_no": related_version_no,
            "include_execution_summary": True,
        },
    )
    if report_feature["operational_ready"]:
        primitives.assertion(
            report_response.status_code == 200,
            (
                f"{proposal_id}: expected live report request success, got "
                f"{report_response.status_code} body={report_response.text}"
            ),
        )
        report_body = cast(dict[str, Any], report_response.json())
        primitives.assertion(
            report_body["report_service"] == "lotus-report",
            f"{proposal_id}: unexpected report service {report_body['report_service']}",
        )
        primitives.assertion(
            report_body["status"] == "READY",
            f"{proposal_id}: unexpected report status {report_body['status']}",
        )
        primitives.assert_persisted_read_surfaces(
            client,
            advise_base_url=advise_base_url,
            proposal_id=proposal_id,
            expected_portfolio_id=expected_portfolio_id,
            created_by_filter="live-parity-validator",
            current_version_no=related_version_no,
            expected_state="EXECUTED",
            expected_report_status=report_body["status"],
        )
        return str(report_body["status"])

    primitives.assertion(
        report_response.status_code == 503,
        (
            f"{proposal_id}: expected lotus-report degraded 503, got "
            f"{report_response.status_code} body={report_response.text}"
        ),
    )
    detail = cast(dict[str, Any], report_response.json()).get("detail")
    primitives.assertion(
        detail == "LOTUS_REPORT_REQUEST_UNAVAILABLE",
        f"{proposal_id}: unexpected degraded report detail {detail}",
    )
    primitives.assert_persisted_read_surfaces(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        expected_portfolio_id=expected_portfolio_id,
        created_by_filter="live-parity-validator",
        current_version_no=related_version_no,
        expected_state="EXECUTED",
        expected_report_status="UNAVAILABLE",
    )
    return "UNAVAILABLE"
