from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.core.source_provenance_models import (
    SourceProvenanceEnvelope,
    SourceProvenanceRecord,
)

PORTFOLIO_STATE_SNAPSHOT_CONTRACT_VERSION = "PortfolioStateSnapshot:v1"


class AuthoritativePortfolioStateError(ValueError):
    """Raised when Core cannot prove one usable portfolio-state valuation context."""


class _CoreSourceRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    source_system: Literal["LOTUS_CORE"]
    source_kind: Literal["PORTFOLIO", "MARKET_DATA"]
    source_id: str = Field(min_length=1)
    as_of: date
    contract_version: Literal["PortfolioStateSnapshot:v1"]
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    valuation_timestamp: datetime | None = None
    freshness_status: Literal["CURRENT"]

    @field_validator("valuation_timestamp")
    @classmethod
    def require_timezone_when_present(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("valuation_timestamp must be timezone-aware")
        return value


class _CoreSourceProvenance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["lotus.source-provenance.v1"]
    source_system: Literal["LOTUS_CORE"]
    portfolio: _CoreSourceRecord
    market_data: _CoreSourceRecord
    raw_payload_stored: Literal[False]


class _CoreValuationContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    effective_as_of_date: date
    supportability: Literal["READY"]
    reason_code: Literal["SOURCE_EVIDENCE_READY"]


class _CorePortfolioStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    product_name: Literal["PortfolioStateSnapshot"]
    product_version: Literal["v1"]
    portfolio_id: str = Field(min_length=1)
    as_of_date: date
    snapshot_mode: Literal["BASELINE"]
    generated_at: datetime
    contract_version: Literal["rfc_081_v1"]
    tenant_id: str = Field(min_length=1)
    source_evidence_current: Literal[True]
    freshness_status: Literal["CURRENT"]
    valuation_context: _CoreValuationContext
    source_provenance: _CoreSourceProvenance

    @field_validator("generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value


def core_snapshot_request(*, as_of: str, tenant_id: str) -> dict[str, object]:
    return {
        "as_of_date": _requested_business_date(as_of).isoformat(),
        "snapshot_mode": "BASELINE",
        "consumer_system": "lotus-advise",
        "tenant_id": tenant_id,
        "sections": ["portfolio_state"],
        "options": {
            "include_zero_quantity_positions": False,
            "include_cash_positions": True,
            "position_basis": "market_value_base",
            "weight_basis": "total_market_value_base",
        },
    }


def core_snapshot_headers(*, tenant_id: str) -> dict[str, str]:
    return {
        "X-Tenant-Id": tenant_id,
        "X-Service-Identity": "lotus-advise",
        "X-Role": "service",
    }


def resolve_authoritative_portfolio_state(
    payload: dict[str, object],
    *,
    expected_portfolio_id: str,
    requested_as_of: str,
    expected_tenant_id: str,
) -> tuple[str, SourceProvenanceEnvelope]:
    try:
        snapshot = _CorePortfolioStateSnapshot.model_validate(payload)
        requested_date = _requested_business_date(requested_as_of)
    except (ValidationError, ValueError) as exc:
        raise AuthoritativePortfolioStateError("LOTUS_CORE_STATEFUL_CONTEXT_INVALID") from exc

    effective_date = snapshot.valuation_context.effective_as_of_date
    if (
        snapshot.portfolio_id != expected_portfolio_id
        or snapshot.tenant_id != expected_tenant_id
        or snapshot.as_of_date != requested_date
        or snapshot.source_provenance.portfolio.source_kind != "PORTFOLIO"
        or snapshot.source_provenance.market_data.source_kind != "MARKET_DATA"
        or snapshot.source_provenance.portfolio.as_of != effective_date
        or snapshot.source_provenance.market_data.as_of != effective_date
    ):
        raise AuthoritativePortfolioStateError("LOTUS_CORE_STATEFUL_CONTEXT_INVALID")

    return effective_date.isoformat(), SourceProvenanceEnvelope(
        source_system="LOTUS_CORE",
        portfolio=_to_advise_record(snapshot.source_provenance.portfolio),
        market_data=_to_advise_record(snapshot.source_provenance.market_data),
    )


def _requested_business_date(value: str) -> date:
    normalized = value.strip()
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        try:
            return datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise AuthoritativePortfolioStateError("LOTUS_CORE_STATEFUL_CONTEXT_INVALID") from exc


def _to_advise_record(record: _CoreSourceRecord) -> SourceProvenanceRecord:
    return SourceProvenanceRecord(
        source_system=record.source_system,
        source_kind=record.source_kind,
        source_id=record.source_id,
        as_of=record.as_of.isoformat(),
        contract_version=record.contract_version,
        source_hash=record.source_hash,
        valuation_timestamp=(
            record.valuation_timestamp.isoformat() if record.valuation_timestamp else None
        ),
        freshness_status=record.freshness_status,
    )
