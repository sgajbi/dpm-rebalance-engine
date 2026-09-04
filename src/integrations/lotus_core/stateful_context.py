from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import httpx

from src.core.engine_options_models import (
    EngineOptions,
    ValuationMode,
)
from src.core.portfolio_models import (
    MarketDataSnapshot,
    PortfolioSnapshot,
)
from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.source_completeness_models import SourceCompletenessReport
from src.core.source_provenance_models import SourceProvenanceEnvelope
from src.core.workspace.input_models import WorkspaceResolvedContext, WorkspaceStatefulInput
from src.integrations.lotus_core import classification as _classification
from src.integrations.lotus_core import stateful_context_hydration as _hydration
from src.integrations.lotus_core import stateful_context_source_reads as _source_reads
from src.integrations.lotus_core.context_resolution import (
    LotusCoreResolvedAdvisoryContext,
)
from src.integrations.lotus_core.portfolio_state_snapshot import (
    AuthoritativePortfolioStateError,
    core_snapshot_headers,
    core_snapshot_request,
    resolve_authoritative_portfolio_state,
)
from src.integrations.lotus_core.runtime_config import (
    resolve_lotus_core_timeout,
)
from src.integrations.lotus_core.stateful_context_cache import (
    StatefulContextFetchStats,
    stateful_context_cache_max_size,
    stateful_context_cache_ttl_seconds,
)
from src.integrations.lotus_core.stateful_context_cache import (
    cache_resolved_context as _cache_resolved_context,
)
from src.integrations.lotus_core.stateful_context_cache import (
    clone_resolved_context as _clone_resolved_context,
)
from src.integrations.lotus_core.stateful_context_cache import (
    get_cached_resolved_context as _get_cached_resolved_context,
)
from src.integrations.lotus_core.stateful_context_cache import (
    get_stateful_context_cache_stats as _get_stateful_context_cache_stats,
)
from src.integrations.lotus_core.stateful_context_cache import (
    get_stateful_context_fetch_stats as _get_stateful_context_fetch_stats,
)
from src.integrations.lotus_core.stateful_context_cache import (
    reset_stateful_context_cache as _reset_stateful_context_cache,
)
from src.integrations.lotus_core.stateful_context_completeness import (
    build_lotus_core_source_completeness as _build_lotus_core_source_completeness,
)
from src.integrations.lotus_core.stateful_context_market_data import (
    InvalidLotusCoreFxRateError,
)
from src.integrations.lotus_core.stateful_context_routes import (
    CORE_SNAPSHOT_PATH,
    cash_balances_path,
    positions_path,
    resolve_control_plane_base_url,
    resolve_query_base_url,
)
from src.integrations.lotus_core.stateful_context_routes import (
    PORTFOLIO_PATH as _PORTFOLIO_PATH,
)
from src.integrations.lotus_core.stateful_context_source_reads import (
    LotusCoreStatefulContextUnavailableError,
)
from src.integrations.lotus_core.stateful_context_source_reads import (
    fetch_classification_taxonomy as _fetch_classification_taxonomy,
)
from src.integrations.lotus_core.stateful_context_source_reads import (
    request_json as _request_json,
)
from src.integrations.lotus_core.stateful_context_translation import (
    build_cash_balances as _build_cash_balances,
)
from src.integrations.lotus_core.stateful_context_translation import (
    build_positions as _build_positions,
)
from src.integrations.lotus_core.stateful_context_translation import (
    build_prices as _build_prices,
)
from src.integrations.lotus_core.stateful_context_translation import (
    build_shelf_entries as _build_shelf_entries,
)
from src.integrations.lotus_core.stateful_context_translation import (
    decimal_or_none as _decimal_or_none,
)
from src.integrations.lotus_core.stateful_context_translation import (
    derive_fx_rates as _derive_fx_rates,
)
from src.integrations.lotus_core.timed_cache import TimedCacheStats

ClassificationTaxonomy = _classification.ClassificationTaxonomy
_prefer_upstream_liquidity_tier = _classification.prefer_upstream_liquidity_tier
_append_fx_rate_if_missing = _hydration.append_fx_rate_if_missing
_append_price_if_missing = _hydration.append_price_if_missing
_append_shelf_entry_if_missing = _hydration.append_shelf_entry_if_missing
_has_fx_pair = _hydration.has_fx_pair
_select_instrument_row = _hydration.select_instrument_row
_select_latest_dated_row = _hydration.select_latest_dated_row
_select_latest_fx_row = _hydration.select_latest_fx_row
_select_latest_price_row = _hydration.select_latest_price_row
_fetch_instrument_enrichment_bulk = _source_reads.fetch_instrument_enrichment_bulk
_fetch_instrument_enrichment_bulk_with_diagnostics = (
    _source_reads.fetch_instrument_enrichment_bulk_with_diagnostics
)


@dataclass(frozen=True)
class _StatefulContextSourcePayloads:
    resolved_as_of: str
    source_provenance: SourceProvenanceEnvelope
    portfolio_payload: dict[str, Any]
    positions_payload: dict[str, Any]
    cash_payload: dict[str, Any]
    enrichment_by_instrument_id: dict[str, dict[str, Any]]
    enrichment_malformed_record_count: int
    classification_taxonomy: _classification.ClassificationTaxonomy | None
    classification_taxonomy_unavailable: bool


def _resolve_timeout() -> httpx.Timeout:
    return resolve_lotus_core_timeout()


def _stateful_context_cache_ttl_seconds() -> float:
    return stateful_context_cache_ttl_seconds()  # type: ignore[no-any-return]


def _stateful_context_cache_max_size() -> int:
    return cast(int, stateful_context_cache_max_size())


def reset_stateful_context_cache_for_tests() -> None:
    _reset_stateful_context_cache()


def get_stateful_context_cache_stats_for_tests() -> dict[str, TimedCacheStats]:
    return cast(dict[str, TimedCacheStats], _get_stateful_context_cache_stats())


def get_stateful_context_fetch_stats_for_tests() -> StatefulContextFetchStats:
    return _get_stateful_context_fetch_stats()


def _resolve_query_base_url() -> str:
    try:
        return cast(str, resolve_query_base_url())
    except ValueError as exc:
        raise LotusCoreStatefulContextUnavailableError(
            "LOTUS_CORE_STATEFUL_CONTEXT_UNAVAILABLE"
        ) from exc


def _positions_path(*, portfolio_id: str, as_of: str) -> str:
    return cast(str, positions_path(portfolio_id=portfolio_id, as_of=as_of))


def _cash_balances_path(*, portfolio_id: str, as_of: str) -> str:
    return cast(str, cash_balances_path(portfolio_id=portfolio_id, as_of=as_of))


def _resolve_control_plane_base_url() -> str:
    try:
        return cast(str, resolve_control_plane_base_url())
    except ValueError as exc:
        raise LotusCoreStatefulContextUnavailableError(
            "LOTUS_CORE_STATEFUL_CONTEXT_UNAVAILABLE"
        ) from exc


def _require_decimal(value: Any, *, error_code: str) -> Decimal:
    parsed = _decimal_or_none(value)
    if parsed is None:
        raise LotusCoreStatefulContextUnavailableError(error_code)
    return cast(Decimal, parsed)


def enrich_stateful_simulate_request_for_trade_drafts(
    *,
    simulate_request: ProposalSimulateRequest,
    as_of: str,
) -> ProposalSimulateRequest:
    try:
        return _hydration.enrich_stateful_simulate_request_for_trade_drafts(
            simulate_request=simulate_request,
            as_of=as_of,
            base_url=_resolve_query_base_url(),
            control_plane_base_url=_resolve_control_plane_base_url(),
            timeout=_resolve_timeout(),
            client_factory=lambda timeout: httpx.Client(timeout=timeout),
        )
    except InvalidLotusCoreFxRateError as exc:
        raise LotusCoreStatefulContextUnavailableError("LOTUS_CORE_STATEFUL_FX_INVALID") from exc


def resolve_stateful_context_with_lotus_core(
    stateful_input: WorkspaceStatefulInput,
) -> LotusCoreResolvedAdvisoryContext:
    base_url = _resolve_query_base_url()
    control_plane_base_url = _resolve_control_plane_base_url()
    cached = _get_cached_resolved_context(
        stateful_input,
        query_base_url=base_url,
        control_plane_base_url=control_plane_base_url,
    )
    if cached is not None:
        return cached

    source_payloads = _fetch_stateful_context_source_payloads(
        stateful_input,
        base_url=base_url,
        control_plane_base_url=control_plane_base_url,
    )
    portfolio_id, base_currency = _resolved_portfolio_identity(
        source_payloads.portfolio_payload,
        stateful_input=stateful_input,
    )
    resolved_as_of = source_payloads.resolved_as_of
    source_provenance = source_payloads.source_provenance
    portfolio_snapshot_id = source_provenance.portfolio.source_id
    market_data_snapshot_id = source_provenance.market_data.source_id
    source_completeness = _build_lotus_core_source_completeness(
        portfolio_id=portfolio_id,
        resolved_as_of=resolved_as_of,
        portfolio_base_currency=base_currency,
        positions_payload=source_payloads.positions_payload,
        cash_payload=source_payloads.cash_payload,
        enrichment_by_instrument_id=source_payloads.enrichment_by_instrument_id,
        enrichment_malformed_record_count=source_payloads.enrichment_malformed_record_count,
        classification_taxonomy=source_payloads.classification_taxonomy,
        classification_taxonomy_unavailable=source_payloads.classification_taxonomy_unavailable,
    )
    if source_completeness.has_required_rejections():
        raise LotusCoreStatefulContextUnavailableError("LOTUS_CORE_STATEFUL_SOURCE_INCOMPLETE")
    try:
        simulate_request = _build_stateful_simulate_request(
            source_payloads,
            portfolio_id=portfolio_id,
            base_currency=base_currency,
            portfolio_snapshot_id=portfolio_snapshot_id,
            market_data_snapshot_id=market_data_snapshot_id,
            source_provenance=source_provenance,
            source_completeness=source_completeness,
        )
    except InvalidLotusCoreFxRateError as exc:
        raise LotusCoreStatefulContextUnavailableError("LOTUS_CORE_STATEFUL_FX_INVALID") from exc
    resolved = LotusCoreResolvedAdvisoryContext(
        simulate_request=simulate_request,
        resolved_context=WorkspaceResolvedContext(
            portfolio_id=portfolio_id,
            as_of=resolved_as_of,
            portfolio_snapshot_id=portfolio_snapshot_id,
            market_data_snapshot_id=market_data_snapshot_id,
            source_provenance=source_provenance,
            source_completeness=source_completeness,
        ),
    )
    _cache_resolved_context(
        stateful_input,
        resolved,
        query_base_url=base_url,
        control_plane_base_url=control_plane_base_url,
    )
    return _clone_resolved_context(resolved)


def _fetch_stateful_context_source_payloads(
    stateful_input: WorkspaceStatefulInput,
    *,
    base_url: str,
    control_plane_base_url: str,
) -> _StatefulContextSourcePayloads:
    tenant_id = _required_tenant_id()
    with httpx.Client(timeout=_resolve_timeout()) as client:
        core_snapshot_payload = _request_json(
            client,
            method="POST",
            base_url=control_plane_base_url,
            path=CORE_SNAPSHOT_PATH.format(portfolio_id=stateful_input.portfolio_id),
            error_code="LOTUS_CORE_STATEFUL_CONTEXT_UNAVAILABLE",
            json_body=core_snapshot_request(
                as_of=stateful_input.as_of,
                tenant_id=tenant_id,
            ),
            headers=core_snapshot_headers(tenant_id=tenant_id),
        )
        try:
            resolved_as_of, source_provenance = resolve_authoritative_portfolio_state(
                core_snapshot_payload,
                expected_portfolio_id=stateful_input.portfolio_id,
                requested_as_of=stateful_input.as_of,
                expected_tenant_id=tenant_id,
            )
        except AuthoritativePortfolioStateError as exc:
            raise LotusCoreStatefulContextUnavailableError(
                "LOTUS_CORE_STATEFUL_CONTEXT_INVALID"
            ) from exc
        portfolio_payload = _request_json(
            client,
            method="GET",
            base_url=base_url,
            path=_PORTFOLIO_PATH.format(portfolio_id=stateful_input.portfolio_id),
            error_code="LOTUS_CORE_STATEFUL_PORTFOLIO_UNAVAILABLE",
        )
        positions_payload = _request_json(
            client,
            method="GET",
            base_url=base_url,
            path=_positions_path(
                portfolio_id=stateful_input.portfolio_id,
                as_of=stateful_input.as_of,
            ),
            error_code="LOTUS_CORE_STATEFUL_POSITIONS_UNAVAILABLE",
        )
        cash_payload = _request_json(
            client,
            method="GET",
            base_url=base_url,
            path=_cash_balances_path(
                portfolio_id=stateful_input.portfolio_id,
                as_of=stateful_input.as_of,
            ),
            error_code="LOTUS_CORE_STATEFUL_CASH_UNAVAILABLE",
        )
        enrichment_result = _fetch_instrument_enrichment_bulk_with_diagnostics(
            client,
            base_url=control_plane_base_url,
            security_ids=_held_position_instrument_ids(positions_payload),
            portfolio_id=stateful_input.portfolio_id,
            as_of=stateful_input.as_of,
        )
        classification_taxonomy_unavailable = False
        try:
            classification_taxonomy = _fetch_classification_taxonomy(
                client,
                base_url=control_plane_base_url,
                as_of=stateful_input.as_of,
            )
        except (LotusCoreStatefulContextUnavailableError, AssertionError):
            classification_taxonomy = None
            classification_taxonomy_unavailable = True
    _validate_stateful_payload_identity(
        portfolio_payload=portfolio_payload,
        positions_payload=positions_payload,
        cash_payload=cash_payload,
        stateful_input=stateful_input,
    )
    return _StatefulContextSourcePayloads(
        resolved_as_of=resolved_as_of,
        source_provenance=source_provenance,
        portfolio_payload=portfolio_payload,
        positions_payload=positions_payload,
        cash_payload=cash_payload,
        enrichment_by_instrument_id=enrichment_result.enrichment_by_security_id,
        enrichment_malformed_record_count=enrichment_result.malformed_record_count,
        classification_taxonomy=classification_taxonomy,
        classification_taxonomy_unavailable=classification_taxonomy_unavailable,
    )


def _required_tenant_id() -> str:
    tenant_id = os.getenv("LOTUS_ADVISE_TENANT_ID", "").strip()
    if not tenant_id:
        raise LotusCoreStatefulContextUnavailableError("LOTUS_CORE_STATEFUL_CONTEXT_UNAVAILABLE")
    return tenant_id


def _held_position_instrument_ids(positions_payload: dict[str, Any]) -> list[str]:
    instrument_ids: set[str] = set()
    for raw_position in positions_payload.get("positions", []):
        if not isinstance(raw_position, dict):
            continue
        instrument_id = _held_position_security_id(raw_position)
        if instrument_id is not None:
            instrument_ids.add(instrument_id)
    return sorted(instrument_ids)


def _held_position_security_id(raw_position: dict[str, Any]) -> str | None:
    if _is_cash_position(raw_position):
        return None
    instrument_id = str(raw_position.get("security_id") or "").strip()
    return instrument_id or None


def _is_cash_position(raw_position: dict[str, Any]) -> bool:
    asset_class = str(raw_position.get("asset_class") or "").strip().lower()
    return asset_class == "cash"


def _validate_stateful_payload_identity(
    *,
    portfolio_payload: dict[str, Any],
    positions_payload: dict[str, Any],
    cash_payload: dict[str, Any],
    stateful_input: WorkspaceStatefulInput,
) -> None:
    _require_matching_payload_value(
        portfolio_payload,
        "portfolio_id",
        expected=stateful_input.portfolio_id,
    )
    _require_matching_payload_value(
        positions_payload,
        "portfolio_id",
        expected=stateful_input.portfolio_id,
    )
    _require_matching_payload_value(
        cash_payload,
        "portfolio_id",
        expected=stateful_input.portfolio_id,
    )
    _require_matching_payload_value(
        cash_payload,
        "resolved_as_of_date",
        expected=stateful_input.as_of,
    )


def _require_matching_payload_value(
    payload: dict[str, Any],
    key: str,
    *,
    expected: str,
) -> str:
    actual = str(payload.get(key) or "").strip()
    if actual != expected:
        raise LotusCoreStatefulContextUnavailableError("LOTUS_CORE_STATEFUL_CONTEXT_INVALID")
    return actual


def _resolved_portfolio_identity(
    portfolio_payload: dict[str, Any],
    *,
    stateful_input: WorkspaceStatefulInput,
) -> tuple[str, str]:
    portfolio_id = _require_matching_payload_value(
        portfolio_payload,
        "portfolio_id",
        expected=stateful_input.portfolio_id,
    )
    base_currency = str(portfolio_payload.get("base_currency") or "").strip()
    if not portfolio_id or not base_currency:
        raise LotusCoreStatefulContextUnavailableError("LOTUS_CORE_STATEFUL_CONTEXT_INVALID")
    return portfolio_id, base_currency


def _build_stateful_simulate_request(
    source_payloads: _StatefulContextSourcePayloads,
    *,
    portfolio_id: str,
    base_currency: str,
    portfolio_snapshot_id: str,
    market_data_snapshot_id: str,
    source_provenance: SourceProvenanceEnvelope,
    source_completeness: SourceCompletenessReport,
) -> ProposalSimulateRequest:
    return ProposalSimulateRequest(
        portfolio_snapshot=PortfolioSnapshot(
            snapshot_id=portfolio_snapshot_id,
            source_provenance=source_provenance.portfolio,
            source_completeness=source_completeness,
            portfolio_id=portfolio_id,
            base_currency=base_currency,
            positions=_build_positions(
                source_payloads.positions_payload,
                portfolio_base_currency=base_currency,
            ),
            cash_balances=_build_cash_balances(source_payloads.cash_payload),
        ),
        market_data_snapshot=MarketDataSnapshot(
            snapshot_id=market_data_snapshot_id,
            source_provenance=source_provenance.market_data,
            source_completeness=source_completeness,
            prices=_build_prices(source_payloads.positions_payload),
            fx_rates=_derive_fx_rates(
                portfolio_base_currency=base_currency,
                positions_payload=source_payloads.positions_payload,
                cash_payload=source_payloads.cash_payload,
            ),
        ),
        shelf_entries=_build_shelf_entries(
            positions_payload=source_payloads.positions_payload,
            cash_payload=source_payloads.cash_payload,
            enrichment_by_instrument_id=source_payloads.enrichment_by_instrument_id,
            classification_taxonomy=source_payloads.classification_taxonomy,
        ),
        options=EngineOptions(
            enable_proposal_simulation=True,
            valuation_mode=ValuationMode.TRUST_SNAPSHOT,
        ),
        proposed_cash_flows=[],
        proposed_trades=[],
        reference_model=None,
    )
