from __future__ import annotations

import os
from urllib.parse import SplitResult, urlsplit, urlunsplit

DEFAULT_LOTUS_CORE_QUERY_BASE_URL = "http://core-query.dev.lotus"
DEFAULT_LOTUS_CORE_CONTROL_PLANE_BASE_URL = "http://core-control.dev.lotus"
PORTFOLIO_PATH = "/portfolios/{portfolio_id}"
POSITIONS_PATH = "/portfolios/{portfolio_id}/positions"
CASH_BALANCES_PATH = "/portfolios/{portfolio_id}/cash-balances"
INSTRUMENTS_PATH = "/instruments/?security_id={instrument_id}"
INSTRUMENT_ENRICHMENT_BULK_PATH = "/integration/instruments/enrichment-bulk"
PRICES_PATH = "/prices/?security_id={instrument_id}"
FX_RATES_PATH = "/fx-rates/?from_currency={from_currency}&to_currency={to_currency}"
CLASSIFICATION_TAXONOMY_PATH = "/integration/reference/classification-taxonomy"
CORE_SNAPSHOT_PATH = "/integration/portfolios/{portfolio_id}/core-snapshot"


def _sanitized_base_url(value: str) -> str:
    split = urlsplit(value)
    host = split.hostname
    if host is None:
        raise ValueError("LOTUS_CORE_STATEFUL_CONTEXT_UNAVAILABLE")
    return urlunsplit(
        (
            split.scheme or "http",
            _netloc_without_credentials(split, port=split.port),
            split.path.rstrip("/"),
            "",
            "",
        )
    )


def _netloc_without_credentials(split: SplitResult, *, port: int | None) -> str:
    return _netloc_from_host(host=split.hostname, port=port)


def _netloc_from_host(*, host: str | None, port: int | None) -> str:
    if host is None:
        raise ValueError("LOTUS_CORE_STATEFUL_CONTEXT_UNAVAILABLE")
    netloc = host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return netloc


def _url_from_split(split: SplitResult, *, host: str | None, port: int | None) -> str:
    return urlunsplit(
        (
            split.scheme or "http",
            _netloc_from_host(host=host, port=port),
            split.path.rstrip("/"),
            "",
            "",
        )
    )


def _query_port_from_control_plane_port(port: int | None) -> int | None:
    if port == 8202:
        return 8201
    return port


def _control_plane_host_from_query_host(host: str) -> str:
    known_query_hosts = {
        "core-query.dev.lotus": "core-control.dev.lotus",
        "lotus-core-query": "lotus-core-control",
    }
    return known_query_hosts.get(host, host)


def _control_plane_port_from_query_port(port: int | None) -> int | None:
    if port == 8201:
        return 8202
    return port


def resolve_query_base_url() -> str:
    explicit = os.getenv("LOTUS_CORE_QUERY_BASE_URL")
    if explicit:
        return _sanitized_base_url(explicit)

    configured = os.getenv("LOTUS_CORE_BASE_URL")
    if configured:
        split = urlsplit(configured)
        host = split.hostname
        if host is None:
            raise ValueError("LOTUS_CORE_STATEFUL_CONTEXT_UNAVAILABLE")
        configured_port = split.port
        return _url_from_split(
            split,
            host=host,
            port=_query_port_from_control_plane_port(configured_port),
        )
    return DEFAULT_LOTUS_CORE_QUERY_BASE_URL


def positions_path(*, portfolio_id: str, as_of: str) -> str:
    return f"{POSITIONS_PATH.format(portfolio_id=portfolio_id)}?as_of_date={as_of}"


def cash_balances_path(*, portfolio_id: str, as_of: str) -> str:
    return f"{CASH_BALANCES_PATH.format(portfolio_id=portfolio_id)}?as_of_date={as_of}"


def resolve_control_plane_base_url() -> str:
    explicit = os.getenv("LOTUS_CORE_BASE_URL")
    if explicit:
        return _sanitized_base_url(explicit)

    query_base_url = os.getenv("LOTUS_CORE_QUERY_BASE_URL")
    if not query_base_url:
        return DEFAULT_LOTUS_CORE_CONTROL_PLANE_BASE_URL

    split = urlsplit(query_base_url)
    host = split.hostname
    if host is None:
        raise ValueError("LOTUS_CORE_STATEFUL_CONTEXT_UNAVAILABLE")
    return _url_from_split(
        split,
        host=_control_plane_host_from_query_host(host),
        port=_control_plane_port_from_query_port(split.port),
    )
