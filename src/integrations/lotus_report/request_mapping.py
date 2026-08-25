from __future__ import annotations

import re
from typing import Any, cast

from src.core.proposals.correlation import MAX_CORRELATION_ID_LENGTH

_SNAPSHOT_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_REPORT_DATE_KEYS = {
    "as_of_date",
    "effective_as_of_date",
    "report_end_date",
    "valuation_date",
}
_SUPPORTED_OUTPUT_FORMATS = {"pdf", "json"}
_ADVISORY_POLICY_SIGN_OFF_PACKAGE = "ADVISORY_POLICY_SIGN_OFF_PACKAGE"


class LotusReportRequestMappingError(ValueError):
    """Raised when an Advise-to-Report request cannot be safely projected."""


def report_request_id(request: dict[str, Any]) -> str:
    return required_string(request, "report_request_id")


def build_report_headers(
    *,
    request: dict[str, Any],
    request_id: str,
    tenant_id: str | None,
) -> dict[str, str]:
    region = proposal_region(request)
    return {
        "Idempotency-Key": request_id,
        "X-Actor-Id": report_actor_id(request),
        "X-Caller-Application": "lotus-advise",
        "X-Tenant-Id": bounded_tenant_id(tenant_id),
        "X-Region": region,
        "X-Booking-Center-Code": region,
        "X-Role": "advisor",
    }


def build_portfolio_review_job_request(request: dict[str, Any]) -> dict[str, Any]:
    proposal = cast(dict[str, Any], request.get("proposal") or {})
    portfolio_id = required_string(proposal, "portfolio_id")
    proposal_narrative_package = request.get("proposal_narrative_package")
    payload: dict[str, Any] = {
        "portfolio_scope": {"portfolio_ids": [portfolio_id]},
        "as_of_date": extract_report_as_of_date(request),
        "requested_output_formats": ["json"],
        "reporting_currency": extract_reporting_currency(request),
        "options": {},
    }
    if isinstance(proposal_narrative_package, dict):
        payload["proposal_narrative_package"] = proposal_narrative_package
    return payload


def build_memo_report_package_job_request(request: dict[str, Any]) -> dict[str, Any]:
    proposal = cast(dict[str, Any], request.get("proposal") or {})
    portfolio_id = required_string(proposal, "portfolio_id")
    payload = {
        "portfolio_scope": {"portfolio_ids": [portfolio_id]},
        "as_of_date": extract_report_as_of_date(request),
        "requested_output_formats": normalized_output_formats(
            request.get("requested_output_formats")
        ),
        "reporting_currency": extract_reporting_currency(request),
        "options": _report_operational_options(request),
        "proposal_memo_package": request.get("proposal_memo_package"),
    }
    return payload


def build_policy_sign_off_package_job_request(request: dict[str, Any]) -> dict[str, Any]:
    proposal = cast(dict[str, Any], request.get("proposal") or {})
    portfolio_id = required_string(proposal, "portfolio_id")
    policy_sign_off_package = _policy_sign_off_package(request)
    payload = {
        "portfolio_scope": {"portfolio_ids": [portfolio_id]},
        "as_of_date": extract_report_as_of_date(request),
        "requested_output_formats": normalized_output_formats(
            request.get("requested_output_formats")
        ),
        "reporting_currency": extract_reporting_currency(request),
        "options": _report_operational_options(request),
        "policy_sign_off_package": policy_sign_off_package,
    }
    return payload


def _report_operational_options(request: dict[str, Any]) -> dict[str, Any]:
    reason = as_mapping(request.get("reason"))
    retention_policy_id = optional_string(reason.get("retention_policy_id"))
    if retention_policy_id is None:
        return {}
    return {"retention_policy_id": retention_policy_id}


def _policy_sign_off_package(request: dict[str, Any]) -> dict[str, Any]:
    package = as_mapping(request.get("policy_sign_off_package"))
    if optional_string(package.get("package_type")) != _ADVISORY_POLICY_SIGN_OFF_PACKAGE:
        raise LotusReportRequestMappingError("LOTUS_REPORT_REQUEST_UNAVAILABLE")
    return package


def normalized_output_formats(value: Any) -> list[str]:
    return _requested_output_formats(value) or ["pdf"]


def _requested_output_formats(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        output_format
        for item in value
        if (output_format := _normalized_output_format(item)) is not None
    ]


def _normalized_output_format(value: Any) -> str | None:
    normalized = str(value).strip().lower()
    return normalized if normalized in _SUPPORTED_OUTPUT_FORMATS else None


def extract_report_as_of_date(request: dict[str, Any]) -> str:
    proposal_result = _proposal_result_payload(request)
    dates = _unique_report_as_of_dates(proposal_result)
    if len(dates) == 1:
        return next(iter(dates))
    raise LotusReportRequestMappingError("LOTUS_REPORT_REQUEST_UNAVAILABLE")


def _proposal_result_payload(request: dict[str, Any]) -> dict[str, Any]:
    proposal_version = cast(dict[str, Any], request.get("proposal_version") or {})
    return cast(dict[str, Any], proposal_version.get("proposal_result") or {})


def _direct_report_as_of_date(proposal_result: dict[str, Any]) -> str | None:
    return find_first_key_value(proposal_result, keys=_REPORT_DATE_KEYS)


def _lineage_report_as_of_date(proposal_result: dict[str, Any]) -> str | None:
    lineage = proposal_result.get("lineage")
    if isinstance(lineage, dict):
        return _first_snapshot_date_in_mapping(lineage)
    return None


def _unique_report_as_of_dates(proposal_result: dict[str, Any]) -> set[str]:
    dates = set(_report_date_values(proposal_result))
    lineage_date = _lineage_report_as_of_date(proposal_result)
    if lineage_date is not None:
        dates.add(lineage_date)
    return dates


def _report_date_values(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        return _report_date_values_from_mapping(payload)
    if isinstance(payload, list):
        dates: list[str] = []
        for value in payload:
            dates.extend(_report_date_values(value))
        return dates
    return []


def _report_date_values_from_mapping(payload: dict[str, Any]) -> list[str]:
    dates: list[str] = []
    for key, value in payload.items():
        if key in _REPORT_DATE_KEYS:
            normalized = normalized_snapshot_date(value)
            if normalized is not None:
                dates.append(normalized)
        dates.extend(_report_date_values(value))
    return dates


def _first_snapshot_date_in_mapping(lineage: dict[str, Any]) -> str | None:
    for value in lineage.values():
        if isinstance(value, str):
            match = _SNAPSHOT_DATE_PATTERN.search(value)
            if match:
                return match.group(0)
    return None


def extract_reporting_currency(request: dict[str, Any]) -> str | None:
    currency = _before_total_value_currency(_proposal_result_payload(request))
    if currency is None:
        raise LotusReportRequestMappingError("LOTUS_REPORT_REQUEST_UNAVAILABLE")
    return currency


def _before_total_value_currency(proposal_result: dict[str, Any]) -> str | None:
    before = as_mapping(proposal_result.get("before"))
    total_value = as_mapping(before.get("total_value"))
    currency = optional_string(total_value.get("currency"))
    if currency is None or not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    return currency


def find_first_key_value(payload: Any, *, keys: set[str]) -> str | None:
    if isinstance(payload, dict):
        return find_first_key_value_in_mapping(payload, keys=keys)
    if isinstance(payload, list):
        return find_first_key_value_in_sequence(payload, keys=keys)
    return None


def find_first_key_value_in_mapping(
    payload: dict[str, Any],
    *,
    keys: set[str],
) -> str | None:
    for key, value in payload.items():
        if key in keys:
            normalized = normalized_snapshot_date(value)
            if normalized:
                return normalized
        nested = find_first_key_value(value, keys=keys)
        if nested:
            return nested
    return None


def find_first_key_value_in_sequence(
    payload: list[Any],
    *,
    keys: set[str],
) -> str | None:
    for value in payload:
        nested = find_first_key_value(value, keys=keys)
        if nested:
            return nested
    return None


def normalized_snapshot_date(value: Any) -> str | None:
    normalized = optional_string(value)
    if normalized and _SNAPSHOT_DATE_PATTERN.fullmatch(normalized):
        return normalized
    return None


def proposal_region(request: dict[str, Any]) -> str:
    proposal = cast(dict[str, Any], request.get("proposal") or {})
    return required_string(proposal, "jurisdiction")


def report_actor_id(request: dict[str, Any]) -> str:
    return required_bounded_identity(request.get("requested_by"))


def bounded_tenant_id(value: Any) -> str:
    return required_bounded_identity(value)


def report_status_path(status_url: Any) -> str | None:
    normalized = optional_string(status_url)
    if normalized is None or not _is_safe_report_status_path(normalized):
        return None
    return normalized


def _is_safe_report_status_path(value: str) -> bool:
    return (
        not _contains_control_character(value)
        and not _has_url_metadata(value)
        and _is_lotus_report_job_status_path(value)
    )


def _contains_control_character(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _has_url_metadata(value: str) -> bool:
    return "?" in value or "#" in value


def _is_lotus_report_job_status_path(value: str) -> bool:
    return value.startswith("/reports/jobs/")


def normalize_report_job_status(value: Any) -> str:
    normalized = optional_string(value)
    if normalized in {"data_ready", "completed", "archived", "completed_with_warnings"}:
        return "READY"
    if normalized:
        return normalized.upper()
    return "ACCEPTED"


def normalize_memo_report_job_status(value: Any) -> str:
    normalized = optional_string(value)
    if normalized == "archived":
        return "ARCHIVED"
    return normalize_report_job_status(value)


def as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def required_string(payload: dict[str, Any], key: str) -> str:
    normalized = optional_string(payload.get(key))
    if normalized is None:
        raise LotusReportRequestMappingError("LOTUS_REPORT_REQUEST_UNAVAILABLE")
    return normalized


def optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def required_bounded_identity(value: Any) -> str:
    normalized = optional_string(value)
    if (
        normalized is None
        or len(normalized) > MAX_CORRELATION_ID_LENGTH
        or _contains_control_character(normalized)
    ):
        raise LotusReportRequestMappingError("LOTUS_REPORT_REQUEST_UNAVAILABLE")
    return normalized
