from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, TypeAlias, cast
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.integrations.lotus_core.runtime_config import resolve_lotus_core_timeout
from src.integrations.lotus_core.stateful_context_routes import resolve_control_plane_base_url

_BENCHMARK_ASSIGNMENT_PATH = "/integration/portfolios/{portfolio_id}/benchmark-assignment"
_CURRENT_FRESHNESS_STATUS = "CURRENT"
_NO_DEGRADATION_STATUS = "NONE"
_RECONCILED_STATUS = "RECONCILED"
_CORE_TENANT_HEADER = "X-Tenant-Id"
_COMPLETE_DATA_QUALITY_STATUS = "COMPLETE"

LotusCoreBenchmarkAssignmentSupportability: TypeAlias = Literal["READY", "PARTIAL"]
LotusCoreBenchmarkAssignmentUnavailableReason: TypeAlias = Literal[
    "CORE_BENCHMARK_ASSIGNMENT_SOURCE_UNAVAILABLE",
    "CORE_BENCHMARK_ASSIGNMENT_SOURCE_NOT_FOUND",
    "CORE_BENCHMARK_ASSIGNMENT_SOURCE_INVALID",
    "CORE_BENCHMARK_ASSIGNMENT_PORTFOLIO_MISMATCH",
    "CORE_BENCHMARK_ASSIGNMENT_AS_OF_MISMATCH",
    "CORE_BENCHMARK_ASSIGNMENT_TENANT_MISMATCH",
    "CORE_BENCHMARK_ASSIGNMENT_TENANT_REQUIRED",
]


@dataclass(frozen=True)
class LotusCoreBenchmarkAssignment:
    """Validated, source-owned BenchmarkAssignment:v1 facts at the Core boundary."""

    effective_benchmark_id: str
    effective_as_of_date: str
    effective_from_date: str
    effective_to_date: str | None
    assignment_source: str
    assignment_status: str
    assignment_recorded_at: datetime
    assignment_version: int
    assignment_policy_pack_id: str | None
    assignment_source_system: str | None
    assignment_contract_version: str
    source_product_name: str
    source_product_version: str
    source_tenant_id: str | None
    source_generated_at: datetime
    source_restatement_version: str
    source_reconciliation_status: str
    source_data_quality_status: str
    source_latest_evidence_at: datetime | None
    source_batch_fingerprint: str | None
    source_snapshot_id: str | None
    source_content_hash: str
    source_references: tuple[str, ...]
    source_lineage: dict[str, str]
    source_evidence_current: bool
    source_freshness_status: str
    source_policy_version: str | None
    supportability: LotusCoreBenchmarkAssignmentSupportability


class LotusCoreBenchmarkAssignmentUnavailableError(Exception):
    def __init__(self, reason: LotusCoreBenchmarkAssignmentUnavailableReason) -> None:
        super().__init__(reason)
        self.reason = reason


class _CoreDegradation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = _NO_DEGRADATION_STATUS


class _CoreBenchmarkAssignmentResponse(BaseModel):
    """The Core v1 product projected into Advise's integration boundary."""

    model_config = ConfigDict(extra="ignore")

    product_name: Literal["BenchmarkAssignment"]
    product_version: Literal["v1"]
    portfolio_id: str = Field(min_length=1)
    benchmark_id: str = Field(min_length=1)
    as_of_date: date
    effective_from: date
    effective_to: date | None = None
    assignment_source: str = Field(min_length=1)
    assignment_status: str = Field(min_length=1)
    assignment_recorded_at: datetime
    assignment_version: int = Field(ge=1)
    policy_pack_id: str | None = None
    source_system: str | None = None
    contract_version: str = Field(min_length=1)
    tenant_id: str | None = None
    generated_at: datetime
    restatement_version: str = Field(min_length=1)
    reconciliation_status: str = Field(min_length=1)
    data_quality_status: str = Field(min_length=1)
    latest_evidence_timestamp: datetime | None = None
    source_batch_fingerprint: str | None = None
    snapshot_id: str | None = None
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_refs: list[str] = Field(default_factory=list)
    source_lineage: dict[str, str] = Field(default_factory=dict)
    source_evidence_current: bool = False
    freshness_status: str = "UNAVAILABLE"
    policy_version: str | None = None
    degradation: _CoreDegradation = Field(default_factory=_CoreDegradation)


def fetch_benchmark_assignment_with_lotus_core(
    *,
    portfolio_id: str,
    as_of_date: str,
    reporting_currency: str | None,
    policy_context: dict[str, object] | None,
    correlation_id: str,
) -> LotusCoreBenchmarkAssignment:
    """Fetch Core's effective-dated BenchmarkAssignment:v1 without inferring its semantics."""

    admitted_tenant_id = _require_admitted_tenant(policy_context)
    response = _post_benchmark_assignment_request(
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        reporting_currency=reporting_currency,
        policy_context=policy_context,
        correlation_id=correlation_id,
        admitted_tenant_id=admitted_tenant_id,
    )
    return _map_response(
        response,
        requested_portfolio_id=portfolio_id,
        requested_as_of_date=as_of_date,
        requested_tenant_id=admitted_tenant_id,
    )


def _require_admitted_tenant(policy_context: dict[str, object] | None) -> str:
    """Establish the tenant this read is made under, before any request is sent.

    Core's shared middleware requires a nonblank `X-Tenant-Id` on this route and
    answers 401 without one, so an unscoped call cannot succeed. It must also not
    be attempted: refusing only after the response returns would mean the request
    was already made under no established authority.

    This never mints or defaults a tenant. Absent authority is a refusal.
    """

    admitted = _core_policy_context(policy_context).get("tenant_id")
    if not admitted:
        raise LotusCoreBenchmarkAssignmentUnavailableError(
            "CORE_BENCHMARK_ASSIGNMENT_TENANT_REQUIRED"
        )
    return admitted


def _post_benchmark_assignment_request(
    *,
    portfolio_id: str,
    as_of_date: str,
    reporting_currency: str | None,
    policy_context: dict[str, object] | None,
    correlation_id: str,
    admitted_tenant_id: str,
) -> httpx.Response:
    path = _BENCHMARK_ASSIGNMENT_PATH.format(portfolio_id=quote(portfolio_id, safe=""))
    url = f"{resolve_control_plane_base_url()}{path}"
    try:
        with httpx.Client(timeout=resolve_lotus_core_timeout()) as client:
            response = client.post(
                url,
                json=_request_payload(
                    as_of_date=as_of_date,
                    reporting_currency=reporting_currency,
                    policy_context=policy_context,
                ),
                headers={
                    "X-Correlation-Id": correlation_id,
                    _CORE_TENANT_HEADER: admitted_tenant_id,
                },
            )
            response.raise_for_status()
            return response
    except httpx.HTTPStatusError as exc:
        reason: LotusCoreBenchmarkAssignmentUnavailableReason = (
            "CORE_BENCHMARK_ASSIGNMENT_SOURCE_NOT_FOUND"
            if exc.response.status_code == 404
            else "CORE_BENCHMARK_ASSIGNMENT_SOURCE_UNAVAILABLE"
        )
        raise LotusCoreBenchmarkAssignmentUnavailableError(reason) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise LotusCoreBenchmarkAssignmentUnavailableError(
            "CORE_BENCHMARK_ASSIGNMENT_SOURCE_UNAVAILABLE"
        ) from exc


def _request_payload(
    *,
    as_of_date: str,
    reporting_currency: str | None,
    policy_context: dict[str, object] | None,
) -> dict[str, object]:
    payload: dict[str, object] = {"as_of_date": as_of_date}
    if reporting_currency is not None and reporting_currency.strip():
        payload["reporting_currency"] = reporting_currency.strip()
    core_policy_context = _core_policy_context(policy_context)
    if core_policy_context:
        payload["policy_context"] = core_policy_context
    return payload


def _core_policy_context(policy_context: dict[str, object] | None) -> dict[str, str]:
    if policy_context is None:
        return {}
    core_policy_context: dict[str, str] = {}
    for key in ("tenant_id", "policy_pack_id"):
        value = policy_context.get(key)
        if isinstance(value, str) and value.strip():
            core_policy_context[key] = value.strip()
    return core_policy_context


def _map_response(
    response: httpx.Response,
    *,
    requested_portfolio_id: str,
    requested_as_of_date: str,
    requested_tenant_id: str,
) -> LotusCoreBenchmarkAssignment:
    parsed = _parse_response(response)
    _validate_requested_identity(
        parsed,
        requested_portfolio_id=requested_portfolio_id,
        requested_as_of_date=requested_as_of_date,
        requested_tenant_id=requested_tenant_id,
    )
    _validate_effective_range(parsed)
    return LotusCoreBenchmarkAssignment(
        effective_benchmark_id=parsed.benchmark_id,
        effective_as_of_date=parsed.as_of_date.isoformat(),
        effective_from_date=parsed.effective_from.isoformat(),
        effective_to_date=(
            parsed.effective_to.isoformat() if parsed.effective_to is not None else None
        ),
        assignment_source=parsed.assignment_source,
        assignment_status=parsed.assignment_status,
        assignment_recorded_at=parsed.assignment_recorded_at,
        assignment_version=parsed.assignment_version,
        assignment_policy_pack_id=parsed.policy_pack_id,
        assignment_source_system=parsed.source_system,
        assignment_contract_version=parsed.contract_version,
        source_product_name=parsed.product_name,
        source_product_version=parsed.product_version,
        source_tenant_id=parsed.tenant_id,
        source_generated_at=parsed.generated_at,
        source_restatement_version=parsed.restatement_version,
        source_reconciliation_status=parsed.reconciliation_status,
        source_data_quality_status=parsed.data_quality_status,
        source_latest_evidence_at=parsed.latest_evidence_timestamp,
        source_batch_fingerprint=parsed.source_batch_fingerprint,
        source_snapshot_id=parsed.snapshot_id,
        source_content_hash=parsed.content_hash,
        source_references=tuple(sorted({ref.strip() for ref in parsed.source_refs if ref.strip()})),
        source_lineage=dict(sorted(parsed.source_lineage.items())),
        source_evidence_current=parsed.source_evidence_current,
        source_freshness_status=parsed.freshness_status,
        source_policy_version=parsed.policy_version,
        supportability=_supportability(parsed),
    )


def _parse_response(response: httpx.Response) -> _CoreBenchmarkAssignmentResponse:
    try:
        payload = response.json()
        return cast(
            _CoreBenchmarkAssignmentResponse,
            _CoreBenchmarkAssignmentResponse.model_validate(payload),
        )
    except (ValidationError, ValueError) as exc:
        raise LotusCoreBenchmarkAssignmentUnavailableError(
            "CORE_BENCHMARK_ASSIGNMENT_SOURCE_INVALID"
        ) from exc


def _validate_requested_identity(
    response: _CoreBenchmarkAssignmentResponse,
    *,
    requested_portfolio_id: str,
    requested_as_of_date: str,
    requested_tenant_id: str,
) -> None:
    if response.portfolio_id != requested_portfolio_id:
        raise LotusCoreBenchmarkAssignmentUnavailableError(
            "CORE_BENCHMARK_ASSIGNMENT_PORTFOLIO_MISMATCH"
        )
    if response.as_of_date.isoformat() != requested_as_of_date:
        raise LotusCoreBenchmarkAssignmentUnavailableError(
            "CORE_BENCHMARK_ASSIGNMENT_AS_OF_MISMATCH"
        )
    _validate_requested_tenant(response, requested_tenant_id=requested_tenant_id)


def _validate_requested_tenant(
    response: _CoreBenchmarkAssignmentResponse,
    *,
    requested_tenant_id: str,
) -> None:
    """Bind the response to the tenant this read was admitted under.

    A matching portfolio and as-of date do not establish that the assignment
    belongs to the requesting tenant: Core is asked with a tenant and answers
    with one, and until they are compared a misrouted or cache-collided
    response is indistinguishable from a correct one.

    A response that states no tenant cannot be confirmed in scope either, so it
    is refused rather than accepted on the strength of the other two fields.
    There is no unscoped case to decide here: `_require_admitted_tenant` has
    already refused before the request was sent."""

    if response.tenant_id is None or response.tenant_id != requested_tenant_id:
        raise LotusCoreBenchmarkAssignmentUnavailableError(
            "CORE_BENCHMARK_ASSIGNMENT_TENANT_MISMATCH"
        )


def _validate_effective_range(response: _CoreBenchmarkAssignmentResponse) -> None:
    _validate_effective_date_order(response)
    _validate_effective_date_contains_as_of(response)


def _validate_effective_date_order(response: _CoreBenchmarkAssignmentResponse) -> None:
    if response.effective_to is not None and response.effective_from > response.effective_to:
        raise LotusCoreBenchmarkAssignmentUnavailableError(
            "CORE_BENCHMARK_ASSIGNMENT_SOURCE_INVALID"
        )


def _validate_effective_date_contains_as_of(response: _CoreBenchmarkAssignmentResponse) -> None:
    if response.effective_from > response.as_of_date:
        raise LotusCoreBenchmarkAssignmentUnavailableError(
            "CORE_BENCHMARK_ASSIGNMENT_AS_OF_MISMATCH"
        )
    if response.effective_to is not None and response.as_of_date > response.effective_to:
        raise LotusCoreBenchmarkAssignmentUnavailableError(
            "CORE_BENCHMARK_ASSIGNMENT_AS_OF_MISMATCH"
        )


def _supportability(
    response: _CoreBenchmarkAssignmentResponse,
) -> LotusCoreBenchmarkAssignmentSupportability:
    """READY means the source says its evidence is usable, in every dimension it states.

    `reconciliation_status` and `data_quality_status` were parsed and stored
    but excluded from this decision, so an unreconciled or incomplete
    assignment was reported READY on the strength of freshness alone. Source
    states the limitation; this adapter must not discard it."""

    stated_dimensions_are_healthy = (
        response.source_evidence_current,
        response.freshness_status.upper() == _CURRENT_FRESHNESS_STATUS,
        response.degradation.status.upper() == _NO_DEGRADATION_STATUS,
        response.reconciliation_status.upper() == _RECONCILED_STATUS,
        response.data_quality_status.upper() == _COMPLETE_DATA_QUALITY_STATUS,
    )
    return "READY" if all(stated_dimensions_are_healthy) else "PARTIAL"


__all__ = [
    "LotusCoreBenchmarkAssignment",
    "LotusCoreBenchmarkAssignmentSupportability",
    "LotusCoreBenchmarkAssignmentUnavailableError",
    "LotusCoreBenchmarkAssignmentUnavailableReason",
    "fetch_benchmark_assignment_with_lotus_core",
]
