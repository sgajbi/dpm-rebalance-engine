from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from src.core.common.canonical import hash_canonical_payload
from src.core.source_provenance_models import (
    SourceFreshnessStatus,
    SourceProvenanceEnvelope,
    SourceProvenanceRecord,
)
from src.integrations.lotus_core.context_resolution import LotusCoreContextResolutionError
from src.integrations.lotus_core.contracts import ADVISORY_SIMULATION_CONTRACT_VERSION

_SOURCE_SYSTEM = "LOTUS_CORE"
_FRESHNESS_VALUES: set[SourceFreshnessStatus] = {"CURRENT", "STALE", "PARTIAL", "UNKNOWN"}
_FRESHNESS_PRECEDENCE: tuple[SourceFreshnessStatus, ...] = (
    "STALE",
    "PARTIAL",
    "UNKNOWN",
    "CURRENT",
)


@dataclass(frozen=True)
class _SourceIdentity:
    source_id: str
    source_version: str | None
    source_event_id: str | None
    source_batch_id: str | None
    source_hash: str | None
    valuation_timestamp: str | None
    freshness_status: SourceFreshnessStatus


class LotusCoreSourceProvenanceError(LotusCoreContextResolutionError):
    pass


def build_lotus_core_source_provenance(
    *,
    portfolio_id: str,
    resolved_as_of: str,
    portfolio_payload: dict[str, Any],
    positions_payload: dict[str, Any],
    cash_payload: dict[str, Any],
) -> SourceProvenanceEnvelope:
    portfolio = _source_identity(
        source_kind="PORTFOLIO",
        fallback_id=f"lotus-core:portfolio:{portfolio_id}:{resolved_as_of}",
        identity_payloads=(portfolio_payload, positions_payload, cash_payload),
        metadata_payloads=(portfolio_payload,),
        id_keys=("portfolio_snapshot_id", "portfolio_source_snapshot_id"),
        fallback_payload=portfolio_payload,
    )
    market_data = _source_identity(
        source_kind="MARKET_DATA",
        fallback_id=f"lotus-core:market-data:{portfolio_id}:{resolved_as_of}",
        identity_payloads=(positions_payload, cash_payload),
        metadata_payloads=(positions_payload, cash_payload),
        metadata_component_names=("positions", "cash_balances"),
        id_keys=("market_data_snapshot_id", "valuation_snapshot_id"),
        fallback_payload=positions_payload,
        allow_component_hashes=True,
        aggregate_freshness=True,
        aggregate_latest_timestamp=True,
    )
    return SourceProvenanceEnvelope(
        source_system=_SOURCE_SYSTEM,
        portfolio=_record(
            source_kind="PORTFOLIO",
            identity=portfolio,
            as_of=resolved_as_of,
        ),
        market_data=_record(
            source_kind="MARKET_DATA",
            identity=market_data,
            as_of=resolved_as_of,
        ),
    )


def _source_identity(
    *,
    source_kind: Literal["PORTFOLIO", "MARKET_DATA"],
    fallback_id: str,
    identity_payloads: tuple[dict[str, Any], ...],
    metadata_payloads: tuple[dict[str, Any], ...],
    id_keys: tuple[str, ...],
    fallback_payload: dict[str, Any],
    metadata_component_names: tuple[str, ...] | None = None,
    allow_component_hashes: bool = False,
    aggregate_freshness: bool = False,
    aggregate_latest_timestamp: bool = False,
) -> _SourceIdentity:
    source_version = _consistent_payload_text(
        source_kind,
        metadata_payloads,
        keys=("source_version", "snapshot_version", "revision", "revision_id"),
    )
    source_event_id = _consistent_payload_text(
        source_kind,
        metadata_payloads,
        keys=("source_event_id", "event_id", "source_revision_id"),
    )
    source_batch_id = _consistent_payload_text(
        source_kind,
        metadata_payloads,
        keys=("source_batch_id", "batch_id", "ingestion_batch_id"),
    )
    source_hash = _source_hash(
        source_kind,
        metadata_payloads,
        allow_component_hashes=allow_component_hashes,
        component_names=metadata_component_names,
    )
    valuation_timestamp = _valuation_timestamp(
        source_kind,
        metadata_payloads,
        aggregate_latest_timestamp=aggregate_latest_timestamp,
    )
    explicit_source_id = _consistent_payload_text(source_kind, identity_payloads, keys=id_keys)
    if explicit_source_id is None and not allow_component_hashes:
        explicit_source_id = _normalized_text(fallback_payload.get("snapshot_id"))
    source_id = explicit_source_id or _fallback_source_id(
        fallback_id=fallback_id,
        source_version=source_version,
        source_event_id=source_event_id,
        source_batch_id=source_batch_id,
        source_hash=source_hash,
    )
    return _SourceIdentity(
        source_id=source_id,
        source_version=source_version,
        source_event_id=source_event_id,
        source_batch_id=source_batch_id,
        source_hash=source_hash,
        valuation_timestamp=valuation_timestamp,
        freshness_status=_freshness_status(
            source_kind=source_kind,
            payloads=metadata_payloads,
            aggregate=aggregate_freshness,
        ),
    )


def _source_hash(
    source_kind: Literal["PORTFOLIO", "MARKET_DATA"],
    payloads: tuple[dict[str, Any], ...],
    *,
    allow_component_hashes: bool,
    component_names: tuple[str, ...] | None,
) -> str | None:
    values = _payload_text_values(
        source_kind,
        payloads,
        keys=("source_hash", "content_hash", "snapshot_hash"),
    )
    component_values = _payload_component_text_values(
        payloads,
        component_names=component_names,
        keys=("source_hash", "content_hash", "snapshot_hash"),
    )
    if len(values) <= 1:
        if len(component_values) <= 1:
            return next(iter(values), None)
        if not allow_component_hashes:
            raise LotusCoreSourceProvenanceError("LOTUS_CORE_STATEFUL_CONTEXT_INVALID")
    if not allow_component_hashes:
        raise LotusCoreSourceProvenanceError("LOTUS_CORE_STATEFUL_CONTEXT_INVALID")
    return hash_canonical_payload(
        {
            "source_system": _SOURCE_SYSTEM,
            "source_kind": source_kind,
            "component_hashes": component_values,
        }
    )


def _valuation_timestamp(
    source_kind: Literal["PORTFOLIO", "MARKET_DATA"],
    payloads: tuple[dict[str, Any], ...],
    *,
    aggregate_latest_timestamp: bool,
) -> str | None:
    values = _payload_text_values(
        source_kind,
        payloads,
        keys=("valuation_timestamp", "valuation_as_of", "source_generated_at", "generated_at"),
    )
    if len(values) <= 1:
        return next(iter(values), None)
    if aggregate_latest_timestamp:
        return max(values)
    raise LotusCoreSourceProvenanceError("LOTUS_CORE_STATEFUL_CONTEXT_INVALID")


def _record(
    *,
    source_kind: Literal["PORTFOLIO", "MARKET_DATA"],
    identity: _SourceIdentity,
    as_of: str,
) -> SourceProvenanceRecord:
    return SourceProvenanceRecord(
        source_system=_SOURCE_SYSTEM,
        source_kind=source_kind,
        source_id=identity.source_id,
        as_of=as_of,
        contract_version=ADVISORY_SIMULATION_CONTRACT_VERSION,
        source_version=identity.source_version,
        source_event_id=identity.source_event_id,
        source_batch_id=identity.source_batch_id,
        source_hash=identity.source_hash,
        valuation_timestamp=identity.valuation_timestamp,
        freshness_status=identity.freshness_status,
    )


def _consistent_payload_text(
    source_kind: Literal["PORTFOLIO", "MARKET_DATA"],
    payloads: tuple[dict[str, Any], ...],
    *,
    keys: tuple[str, ...],
) -> str | None:
    values = _payload_text_values(source_kind, payloads, keys=keys)
    if len(values) > 1:
        raise LotusCoreSourceProvenanceError("LOTUS_CORE_STATEFUL_CONTEXT_INVALID")
    return next(iter(values), None)


def _payload_text_values(
    source_kind: Literal["PORTFOLIO", "MARKET_DATA"],
    payloads: tuple[dict[str, Any], ...],
    *,
    keys: tuple[str, ...],
) -> tuple[str, ...]:
    del source_kind
    return tuple(
        sorted(
            {
                value
                for payload in payloads
                for key in keys
                if (value := _normalized_text(payload.get(key))) is not None
            }
        )
    )


def _payload_component_text_values(
    payloads: tuple[dict[str, Any], ...],
    *,
    component_names: tuple[str, ...] | None,
    keys: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    components: list[dict[str, str]] = []
    for index, payload in enumerate(payloads):
        value = next(
            (
                normalized
                for key in keys
                if (normalized := _normalized_text(payload.get(key))) is not None
            ),
            None,
        )
        if value is None:
            continue
        component = (
            component_names[index]
            if component_names is not None and index < len(component_names)
            else f"component_{index + 1}"
        )
        components.append({"component": component, "source_hash": value})
    return tuple(
        sorted(
            components,
            key=lambda item: (item["component"], item["source_hash"]),
        )
    )


def _fallback_source_id(
    *,
    fallback_id: str,
    source_version: str | None,
    source_event_id: str | None,
    source_batch_id: str | None,
    source_hash: str | None,
) -> str:
    for value in (source_version, source_event_id, source_batch_id, source_hash):
        if value is not None:
            return f"{fallback_id}:{value}"
    return fallback_id


def _freshness_status(
    *,
    source_kind: Literal["PORTFOLIO", "MARKET_DATA"],
    payloads: tuple[dict[str, Any], ...],
    aggregate: bool = False,
) -> SourceFreshnessStatus:
    raw_values = _freshness_raw_values(source_kind=source_kind, payloads=payloads)
    if aggregate:
        return _aggregate_freshness_status(raw_values)
    return _single_freshness_status(source_kind=source_kind, payloads=payloads)


def _freshness_raw_values(
    *,
    source_kind: Literal["PORTFOLIO", "MARKET_DATA"],
    payloads: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    return tuple(
        value.upper()
        for value in _payload_text_values(
            source_kind,
            payloads,
            keys=("freshness_status", "valuation_freshness_status"),
        )
    )


def _aggregate_freshness_status(raw_values: tuple[str, ...]) -> SourceFreshnessStatus:
    values = tuple(freshness for freshness in raw_values if freshness in _FRESHNESS_VALUES)
    if not values or len(values) != len(raw_values):
        return "UNKNOWN"
    for freshness in _FRESHNESS_PRECEDENCE:
        if freshness in values:
            return freshness
    return "UNKNOWN"


def _single_freshness_status(
    *,
    source_kind: Literal["PORTFOLIO", "MARKET_DATA"],
    payloads: tuple[dict[str, Any], ...],
) -> SourceFreshnessStatus:
    value = _consistent_payload_text(
        source_kind,
        payloads,
        keys=("freshness_status", "valuation_freshness_status"),
    )
    if value is None:
        return "UNKNOWN"
    normalized = value.upper()
    if normalized not in _FRESHNESS_VALUES:
        return "UNKNOWN"
    return cast(SourceFreshnessStatus, normalized)


def _normalized_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "LotusCoreSourceProvenanceError",
    "build_lotus_core_source_provenance",
]
