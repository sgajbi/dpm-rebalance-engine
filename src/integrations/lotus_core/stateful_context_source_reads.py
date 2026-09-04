from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import httpx

from src.integrations.lotus_core.classification import (
    ClassificationTaxonomy,
    parse_classification_taxonomy,
)
from src.integrations.lotus_core.context_resolution import LotusCoreContextResolutionError
from src.integrations.lotus_core.stateful_context_cache import (
    CLASSIFICATION_TAXONOMY_CACHE,
    INSTRUMENT_ENRICHMENT_CACHE,
    cache_payload,
    get_cached_payload,
    record_fetch_stat,
)
from src.integrations.lotus_core.stateful_context_cache_identity import (
    classification_taxonomy_cache_key,
    instrument_enrichment_cache_key,
)
from src.integrations.lotus_core.stateful_context_routes import (
    CLASSIFICATION_TAXONOMY_PATH,
    INSTRUMENT_ENRICHMENT_BULK_PATH,
)
from src.integrations.lotus_core.timed_cache import TimedCache


class LotusCoreStatefulContextUnavailableError(LotusCoreContextResolutionError):
    pass


@dataclass(frozen=True)
class InstrumentEnrichmentFetchResult:
    enrichment_by_security_id: dict[str, dict[str, Any]]
    malformed_record_count: int = 0


_FETCH_STAT_BY_ERROR_CODE = {
    "LOTUS_CORE_STATEFUL_PORTFOLIO_UNAVAILABLE": "portfolio_fetches",
    "LOTUS_CORE_STATEFUL_POSITIONS_UNAVAILABLE": "positions_fetches",
    "LOTUS_CORE_STATEFUL_CASH_UNAVAILABLE": "cash_fetches",
    "LOTUS_CORE_STATEFUL_INSTRUMENT_LOOKUP_UNAVAILABLE": "instrument_fetches",
    "LOTUS_CORE_STATEFUL_PRICE_LOOKUP_UNAVAILABLE": "price_fetches",
    "LOTUS_CORE_STATEFUL_FX_LOOKUP_UNAVAILABLE": "fx_fetches",
}


def request_json(
    client: httpx.Client,
    *,
    method: str,
    base_url: str,
    path: str,
    error_code: str,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    fetch_stat = _FETCH_STAT_BY_ERROR_CODE.get(error_code)
    if fetch_stat is not None:
        record_fetch_stat(fetch_stat)
    url = f"{base_url}{path}"
    try:
        if headers is None:
            response = client.request(method, url, json=json_body)
        else:
            response = client.request(method, url, json=json_body, headers=headers)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LotusCoreStatefulContextUnavailableError(error_code) from exc

    if not isinstance(payload, dict):
        raise LotusCoreStatefulContextUnavailableError(error_code)
    return payload


def fetch_json_with_cache(
    client: httpx.Client,
    *,
    cache: TimedCache[str, dict[str, Any]],
    cache_key: str,
    method: str,
    base_url: str,
    path: str,
    error_code: str,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cached_payload = get_cached_payload(cache, cache_key=cache_key)
    if cached_payload is not None:
        return cast(dict[str, Any], cached_payload)
    payload = request_json(
        client,
        method=method,
        base_url=base_url,
        path=path,
        error_code=error_code,
        json_body=json_body,
    )
    return cast(dict[str, Any], cache_payload(cache, cache_key=cache_key, payload=payload))


def fetch_instrument_enrichment_bulk(
    client: httpx.Client,
    *,
    base_url: str,
    security_ids: list[str],
    portfolio_id: str,
    as_of: str,
) -> dict[str, dict[str, Any]]:
    return fetch_instrument_enrichment_bulk_with_diagnostics(
        client,
        base_url=base_url,
        security_ids=security_ids,
        portfolio_id=portfolio_id,
        as_of=as_of,
    ).enrichment_by_security_id


def fetch_instrument_enrichment_bulk_with_diagnostics(
    client: httpx.Client,
    *,
    base_url: str,
    security_ids: list[str],
    portfolio_id: str,
    as_of: str,
) -> InstrumentEnrichmentFetchResult:
    requested_ids = _requested_security_ids(security_ids)
    enrichment_by_security_id, missing_ids = _cached_instrument_enrichment(
        requested_ids,
        base_url=base_url,
        portfolio_id=portfolio_id,
        as_of=as_of,
    )
    if not requested_ids:
        return InstrumentEnrichmentFetchResult(enrichment_by_security_id)
    if not missing_ids:
        return InstrumentEnrichmentFetchResult(enrichment_by_security_id)
    payload = request_json(
        client,
        method="POST",
        base_url=base_url,
        path=INSTRUMENT_ENRICHMENT_BULK_PATH,
        error_code="LOTUS_CORE_STATEFUL_INSTRUMENT_LOOKUP_UNAVAILABLE",
        json_body={"security_ids": missing_ids},
    )
    return _with_fetched_instrument_enrichment(
        enrichment_by_security_id,
        payload,
        base_url=base_url,
        portfolio_id=portfolio_id,
        as_of=as_of,
    )


def _requested_security_ids(security_ids: list[str]) -> list[str]:
    return sorted({security_id for security_id in security_ids if security_id})


def _cached_instrument_enrichment(
    requested_ids: list[str],
    *,
    base_url: str,
    portfolio_id: str,
    as_of: str,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    enrichment_by_security_id: dict[str, dict[str, Any]] = {}
    missing_ids: list[str] = []
    for security_id in requested_ids:
        cached_record = get_cached_payload(
            INSTRUMENT_ENRICHMENT_CACHE,
            cache_key=instrument_enrichment_cache_key(
                control_plane_base_url=base_url,
                security_id=security_id,
                portfolio_id=portfolio_id,
                as_of=as_of,
            ),
        )
        if cached_record is None:
            missing_ids.append(security_id)
        else:
            enrichment_by_security_id[security_id] = cached_record
    return enrichment_by_security_id, missing_ids


def _with_fetched_instrument_enrichment(
    enrichment_by_security_id: dict[str, dict[str, Any]],
    payload: dict[str, Any],
    *,
    base_url: str,
    portfolio_id: str,
    as_of: str,
) -> InstrumentEnrichmentFetchResult:
    malformed_record_count = 0
    records = payload.get("records")
    if not isinstance(records, list):
        return InstrumentEnrichmentFetchResult(
            enrichment_by_security_id,
            malformed_record_count=1,
        )
    for record in records:
        if not _append_instrument_enrichment_record(
            enrichment_by_security_id,
            record,
            base_url=base_url,
            portfolio_id=portfolio_id,
            as_of=as_of,
        ):
            malformed_record_count += 1
    return InstrumentEnrichmentFetchResult(
        enrichment_by_security_id,
        malformed_record_count=malformed_record_count,
    )


def _append_instrument_enrichment_record(
    enrichment_by_security_id: dict[str, dict[str, Any]],
    record: Any,
    *,
    base_url: str,
    portfolio_id: str,
    as_of: str,
) -> bool:
    if not isinstance(record, dict):
        return False
    security_id = str(record.get("security_id") or "").strip()
    if not security_id:
        return False
    enrichment_by_security_id[security_id] = cache_payload(
        INSTRUMENT_ENRICHMENT_CACHE,
        cache_key=instrument_enrichment_cache_key(
            control_plane_base_url=base_url,
            security_id=security_id,
            portfolio_id=portfolio_id,
            as_of=as_of,
        ),
        payload=record,
    )
    return True


def fetch_classification_taxonomy(
    client: httpx.Client,
    *,
    base_url: str,
    as_of: str,
    taxonomy_scope: str = "instrument",
) -> ClassificationTaxonomy:
    cache_key = classification_taxonomy_cache_key(
        control_plane_base_url=base_url,
        as_of=as_of,
        taxonomy_scope=taxonomy_scope,
    )
    payload = fetch_json_with_cache(
        client,
        cache=CLASSIFICATION_TAXONOMY_CACHE,
        cache_key=cache_key,
        method="POST",
        base_url=base_url,
        path=CLASSIFICATION_TAXONOMY_PATH,
        error_code="LOTUS_CORE_STATEFUL_INSTRUMENT_LOOKUP_UNAVAILABLE",
        json_body={"as_of_date": as_of, "taxonomy_scope": taxonomy_scope},
    )
    return parse_classification_taxonomy(payload)
