from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

from src.core.common.canonical import hash_canonical_payload
from src.core.proposals.exceptions import ProposalValidationError

POLICY_EVALUATION_RECEIPT_IDENTITY_CONTRACT_VERSION = (
    "rfc0002.policy-evaluation-receipt-identity.v1"
)
_VOLATILE_TRUSTED_PRINCIPAL_FIELDS = {"correlation_id", "trace_id"}


class PolicyEvaluationReceiptScopeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_contract_version: Literal["rfc0002.policy-evaluation-receipt-identity.v1"] = Field(
        description="Closed receipt identity contract governing source-safe scope fields.",
        examples=["rfc0002.policy-evaluation-receipt-identity.v1"],
    )
    authority_source: Literal["trusted_policy_control_principal"] = Field(
        description="Server-side authority used to derive the scope identity.",
        examples=["trusted_policy_control_principal"],
    )
    tenant_scope_hash: str = Field(
        description="Source-safe deterministic hash of the trusted tenant scope.",
        examples=["sha256:tenant"],
    )
    legal_entity_code: str = Field(
        description="Trusted legal entity code that bounds the policy evaluation scope.",
        examples=["REFERENCE"],
    )
    booking_center_code: str | None = Field(
        default=None,
        description="Source evidence booking center where present and matched to the evaluation.",
        examples=["SG"],
    )
    service_identity_hash: str = Field(
        description="Source-safe deterministic hash of the trusted service identity.",
        examples=["sha256:service"],
    )
    proposal_id: str = Field(
        description="Proposal identifier bound to this receipt.",
        examples=["pp_001"],
    )
    proposal_version_id: str = Field(
        description="Immutable proposal version identifier bound to this receipt.",
        examples=["ppv_001"],
    )
    portfolio_id: str = Field(
        description="Portfolio identifier bound to this receipt.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )


class PolicyEvaluationReceiptIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_contract_version: Literal["rfc0002.policy-evaluation-receipt-identity.v1"] = Field(
        description="Closed receipt identity contract version."
    )
    as_of_date: str = Field(
        description="Source-owned business date for the evidence evaluated by Advise."
    )
    scope_identity: PolicyEvaluationReceiptScopeIdentity = Field(
        description="Trusted, source-safe tenant/legal-entity/portfolio scope identity."
    )
    observed_correlation_id_hash: str = Field(
        description="Source-safe deterministic hash of the correlation id observed by Advise."
    )
    observed_trace_id_hash: str = Field(
        description="Source-safe deterministic hash of the trace id observed by Advise."
    )
    correlation_identity_source: Literal["trusted_policy_control_principal"] = Field(
        description="Producer-observed source for correlation identity."
    )
    trace_identity_source: Literal[
        "advise_observability_context",
        "trusted_policy_control_principal",
    ] = Field(description="Producer-observed source for trace identity.")


def build_policy_evaluation_receipt_identity(
    *,
    evidence_bundle: dict[str, Any],
    proposal_id: str,
    proposal_version_id: str,
    portfolio_id: str,
    reason: dict[str, Any],
    observed_trace_id: str | None,
    observed_at: datetime,
) -> PolicyEvaluationReceiptIdentity:
    trusted_principal = _trusted_principal(reason)
    as_of_date = _source_owned_as_of_date(evidence_bundle, observed_at=observed_at)
    trace_id, trace_identity_source = _trace_identity(
        observed_trace_id=observed_trace_id,
        trusted_principal=trusted_principal,
    )
    tenant_id = _required_identity_value(
        trusted_principal.get("tenant_id"),
        "POLICY_EVALUATION_TRUSTED_TENANT_REQUIRED",
    )
    legal_entity_code = _required_identity_value(
        trusted_principal.get("legal_entity_code"),
        "POLICY_EVALUATION_TRUSTED_LEGAL_ENTITY_REQUIRED",
    ).upper()
    correlation_id = _required_identity_value(
        trusted_principal.get("correlation_id"),
        "POLICY_EVALUATION_OBSERVED_CORRELATION_ID_REQUIRED",
    )
    service_identity = _required_identity_value(
        trusted_principal.get("service_identity"),
        "POLICY_EVALUATION_TRUSTED_SERVICE_IDENTITY_REQUIRED",
    )

    return PolicyEvaluationReceiptIdentity(
        receipt_contract_version=POLICY_EVALUATION_RECEIPT_IDENTITY_CONTRACT_VERSION,
        as_of_date=as_of_date,
        scope_identity=PolicyEvaluationReceiptScopeIdentity(
            identity_contract_version=POLICY_EVALUATION_RECEIPT_IDENTITY_CONTRACT_VERSION,
            authority_source="trusted_policy_control_principal",
            tenant_scope_hash=_safe_hash("tenant_scope", tenant_id),
            legal_entity_code=legal_entity_code,
            booking_center_code=_booking_center_code(evidence_bundle),
            service_identity_hash=_safe_hash("service_identity", service_identity),
            proposal_id=proposal_id,
            proposal_version_id=proposal_version_id,
            portfolio_id=portfolio_id,
        ),
        observed_correlation_id_hash=_safe_hash("correlation_id", correlation_id),
        observed_trace_id_hash=_safe_hash("trace_id", trace_id),
        correlation_identity_source="trusted_policy_control_principal",
        trace_identity_source=trace_identity_source,
    )


def receipt_identity_from_record(record: Any) -> PolicyEvaluationReceiptIdentity:
    identity = record.replay_metadata_json.get("receipt_identity")
    if not isinstance(identity, dict):
        return _legacy_receipt_identity_from_record(record)
    return cast(
        PolicyEvaluationReceiptIdentity,
        PolicyEvaluationReceiptIdentity.model_validate(identity),
    )


def idempotency_stable_reason(reason: dict[str, Any]) -> dict[str, Any]:
    stable = deepcopy(reason)
    _strip_volatile_trusted_principal_fields(stable)
    return stable


def replay_safe_reason(reason: dict[str, Any]) -> dict[str, Any]:
    safe_reason = deepcopy(reason)
    safe_reason.pop("system_repair_intent", None)
    trusted_principal = safe_reason.get("trusted_principal")
    if isinstance(trusted_principal, dict):
        safe_reason["trusted_principal"] = {
            "authority_source": "trusted_policy_control_principal",
            **{
                key: value
                for key, value in trusted_principal.items()
                if key in {"role", "capability", "legal_entity_code"}
            },
        }
    return safe_reason


def _strip_volatile_trusted_principal_fields(value: Any) -> None:
    if isinstance(value, dict):
        trusted_principal = value.get("trusted_principal")
        if isinstance(trusted_principal, dict):
            value["trusted_principal"] = {
                key: nested_value
                for key, nested_value in trusted_principal.items()
                if key not in _VOLATILE_TRUSTED_PRINCIPAL_FIELDS
            }
        for nested_value in value.values():
            _strip_volatile_trusted_principal_fields(nested_value)
    elif isinstance(value, list):
        for item in value:
            _strip_volatile_trusted_principal_fields(item)


def _trusted_principal(reason: dict[str, Any]) -> dict[str, Any]:
    trusted_principal = reason.get("trusted_principal")
    if not isinstance(trusted_principal, dict):
        raise ProposalValidationError("POLICY_EVALUATION_TRUSTED_PRINCIPAL_REQUIRED")
    return trusted_principal


def _source_owned_as_of_date(
    evidence_bundle: dict[str, Any],
    *,
    observed_at: datetime,
) -> str:
    candidates = [
        _nested_value(evidence_bundle, ("context_resolution", "as_of_date")),
        _nested_value(evidence_bundle, ("context_resolution", "as_of")),
        _nested_value(evidence_bundle, ("context_resolution", "resolved_context", "as_of_date")),
        _nested_value(evidence_bundle, ("context_resolution", "resolved_context", "as_of")),
        _nested_value(evidence_bundle, ("inputs", "portfolio_snapshot", "as_of_date")),
        _nested_value(evidence_bundle, ("inputs", "portfolio_snapshot", "as_of")),
        _nested_value(evidence_bundle, ("inputs", "portfolio_snapshot", "snapshot_date")),
        _nested_value(evidence_bundle, ("inputs", "portfolio_snapshot", "valuation_date")),
        _nested_value(evidence_bundle, ("inputs", "market_data_snapshot", "as_of_date")),
        _nested_value(evidence_bundle, ("inputs", "market_data_snapshot", "as_of")),
        _nested_value(evidence_bundle, ("inputs", "market_data_snapshot", "snapshot_date")),
        _nested_value(evidence_bundle, ("inputs", "market_data_snapshot", "valuation_date")),
    ]
    normalized = [_normalize_source_date(value) for value in candidates if _has_value(value)]
    if not normalized:
        raise ProposalValidationError("POLICY_EVALUATION_SOURCE_AS_OF_DATE_REQUIRED")
    unique_dates = list(dict.fromkeys(normalized))
    if len(unique_dates) != 1:
        raise ProposalValidationError("POLICY_EVALUATION_SOURCE_AS_OF_DATE_MISMATCH")
    if date.fromisoformat(unique_dates[0]) > _observed_business_date(
        evidence_bundle=evidence_bundle,
        observed_at=observed_at,
    ):
        raise ProposalValidationError("POLICY_EVALUATION_SOURCE_AS_OF_DATE_IN_FUTURE")
    return unique_dates[0]


def _normalize_source_date(value: Any) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if not isinstance(value, str):
        raise ProposalValidationError("POLICY_EVALUATION_SOURCE_AS_OF_DATE_INVALID")
    candidate = value.strip()
    if not candidate:
        raise ProposalValidationError("POLICY_EVALUATION_SOURCE_AS_OF_DATE_REQUIRED")
    if "T" not in candidate:
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError as exc:
            raise ProposalValidationError("POLICY_EVALUATION_SOURCE_AS_OF_DATE_INVALID") from exc
    parsed = _parse_source_datetime(candidate)
    return parsed.date().isoformat()


def _parse_source_datetime(value: str) -> datetime:
    normalized = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProposalValidationError("POLICY_EVALUATION_SOURCE_AS_OF_DATE_INVALID") from exc
    if parsed.tzinfo is None:
        raise ProposalValidationError("POLICY_EVALUATION_SOURCE_AS_OF_DATE_TIMEZONE_REQUIRED")
    return parsed


def _booking_center_code(evidence_bundle: dict[str, Any]) -> str | None:
    value = _nested_value(
        evidence_bundle,
        ("context_resolution", "advisory_policy_context", "booking_center_code"),
    )
    if isinstance(value, str) and value.strip():
        return value.strip().upper()
    return None


def _observed_business_date(
    *,
    evidence_bundle: dict[str, Any],
    observed_at: datetime,
) -> date:
    observed = observed_at if observed_at.tzinfo is not None else observed_at.replace(tzinfo=UTC)
    source_location_code = _booking_center_code(evidence_bundle)
    timezone_name = {
        "SG": "Asia/Singapore",
        "HK": "Asia/Hong_Kong",
        "CH": "Europe/Zurich",
        "UK": "Europe/London",
        "US": "America/New_York",
    }.get(source_location_code or "")
    if timezone_name is None:
        return observed.astimezone(UTC).date()
    try:
        return observed.astimezone(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError:
        return observed.astimezone(UTC).date()


def _trace_identity(
    *,
    observed_trace_id: str | None,
    trusted_principal: dict[str, Any],
) -> tuple[str, Literal["advise_observability_context", "trusted_policy_control_principal"]]:
    if isinstance(observed_trace_id, str) and observed_trace_id.strip():
        return observed_trace_id.strip(), "advise_observability_context"
    trace_id = _required_identity_value(
        trusted_principal.get("trace_id"),
        "POLICY_EVALUATION_OBSERVED_TRACE_ID_REQUIRED",
    )
    return trace_id, "trusted_policy_control_principal"


def _legacy_receipt_identity_from_record(record: Any) -> PolicyEvaluationReceiptIdentity:
    as_of_date = _legacy_as_of_date(record)
    return PolicyEvaluationReceiptIdentity(
        receipt_contract_version=POLICY_EVALUATION_RECEIPT_IDENTITY_CONTRACT_VERSION,
        as_of_date=as_of_date,
        scope_identity=PolicyEvaluationReceiptScopeIdentity(
            identity_contract_version=POLICY_EVALUATION_RECEIPT_IDENTITY_CONTRACT_VERSION,
            authority_source="trusted_policy_control_principal",
            tenant_scope_hash=_safe_hash("legacy_tenant_scope", str(record.evaluation_id)),
            legal_entity_code="LEGACY_UNAVAILABLE",
            booking_center_code=None,
            service_identity_hash=_safe_hash("legacy_service_identity", "legacy_record"),
            proposal_id=str(record.proposal_id),
            proposal_version_id=str(record.proposal_version_id),
            portfolio_id=str(record.portfolio_id),
        ),
        observed_correlation_id_hash=_safe_hash(
            "legacy_correlation_id",
            str(record.evaluation_id),
        ),
        observed_trace_id_hash=_safe_hash("legacy_trace_id", str(record.evaluation_id)),
        correlation_identity_source="trusted_policy_control_principal",
        trace_identity_source="trusted_policy_control_principal",
    )


def _legacy_as_of_date(record: Any) -> str:
    replay_metadata = getattr(record, "replay_metadata_json", {})
    if isinstance(replay_metadata, dict):
        value = replay_metadata.get("as_of_date")
        if isinstance(value, str) and value.strip():
            return _normalize_source_date(value)
    generated_at = getattr(record, "generated_at", "")
    if isinstance(generated_at, str) and generated_at.strip():
        return _normalize_source_date(generated_at)
    raise ProposalValidationError("POLICY_EVALUATION_RECEIPT_IDENTITY_REQUIRED")


def _nested_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for item in path:
        if not isinstance(current, dict):
            return None
        current = current.get(item)
    return current


def _has_value(value: Any) -> bool:
    return not (value is None or (isinstance(value, str) and not value.strip()))


def _required_identity_value(value: Any, error_code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProposalValidationError(error_code)
    return value.strip()


def _safe_hash(field: str, value: str) -> str:
    return cast(
        str,
        hash_canonical_payload(
            {
                "contract_version": POLICY_EVALUATION_RECEIPT_IDENTITY_CONTRACT_VERSION,
                "field": field,
                "value": value,
            }
        ),
    )


__all__ = [
    "POLICY_EVALUATION_RECEIPT_IDENTITY_CONTRACT_VERSION",
    "PolicyEvaluationReceiptIdentity",
    "PolicyEvaluationReceiptScopeIdentity",
    "build_policy_evaluation_receipt_identity",
    "idempotency_stable_reason",
    "receipt_identity_from_record",
    "replay_safe_reason",
]
