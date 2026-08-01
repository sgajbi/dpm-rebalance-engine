from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from src.core.advisory_engine import run_proposal_simulation
from src.core.common.canonical import hash_canonical_payload
from src.core.models import (
    EngineOptions,
    MarketDataSnapshot,
    Money,
    PortfolioSnapshot,
    Position,
    ProposalSimulateRequest,
    ValuationMode,
)
from src.core.valuation import build_simulated_state
from src.integrations.lotus_core.context_resolution import LotusCoreResolvedAdvisoryContext
from src.integrations.lotus_core.runtime_config import RuntimeConfigurationError
from src.integrations.lotus_core.stateful_context import (
    ClassificationTaxonomy,
    LotusCoreStatefulContextUnavailableError,
    _append_fx_rate_if_missing,
    _append_price_if_missing,
    _append_shelf_entry_if_missing,
    _build_cash_balances,
    _build_positions,
    _build_prices,
    _build_shelf_entries,
    _cash_balances_path,
    _decimal_or_none,
    _derive_fx_rates,
    _fetch_classification_taxonomy,
    _fetch_instrument_enrichment_bulk,
    _positions_path,
    _prefer_upstream_liquidity_tier,
    _request_json,
    _require_decimal,
    _resolve_control_plane_base_url,
    _resolve_query_base_url,
    _resolve_timeout,
    _select_instrument_row,
    _select_latest_dated_row,
    _select_latest_fx_row,
    _select_latest_price_row,
    _stateful_context_cache_max_size,
    _stateful_context_cache_ttl_seconds,
    enrich_stateful_simulate_request_for_trade_drafts,
    get_stateful_context_cache_stats_for_tests,
    get_stateful_context_fetch_stats_for_tests,
    reset_stateful_context_cache_for_tests,
    resolve_stateful_context_with_lotus_core,
)
from src.integrations.lotus_core.stateful_context_completeness import (
    build_lotus_core_source_completeness,
)
from tests.shared.stateful_context_assertions import assert_core_context_fetch_counts


class _FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("boom")

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    def __init__(self, responses: dict[tuple[str, str], _FakeResponse]) -> None:
        self._responses = responses
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def request(self, method: str, url: str, json: dict[str, Any] | None = None) -> _FakeResponse:
        self.requests.append((method.upper(), url, json))
        key = (method.upper(), url)
        if key not in self._responses and "?" in url:
            key = (method.upper(), url.split("?", 1)[0])
        if key not in self._responses:
            raise AssertionError(f"unexpected request: {key} body={json}")
        return self._responses[key]


@pytest.fixture
def stateful_input():
    from src.core.workspace.models import WorkspaceStatefulInput

    return WorkspaceStatefulInput(
        portfolio_id="DEMO_ADV_USD_001",
        as_of="2026-03-27",
        mandate_id="mandate_growth_01",
    )


@pytest.fixture(autouse=True)
def reset_stateful_context_cache():
    reset_stateful_context_cache_for_tests()
    yield
    reset_stateful_context_cache_for_tests()


def test_query_base_url_derives_query_service_from_control_plane_env(monkeypatch):
    monkeypatch.delenv("LOTUS_CORE_QUERY_BASE_URL", raising=False)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://host.docker.internal:8202")

    assert _resolve_query_base_url() == "http://host.docker.internal:8201"


def test_query_base_url_prefers_explicit_query_env(monkeypatch):
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://host.docker.internal:8202")
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", "http://query.example.internal:9999/")

    assert _resolve_query_base_url() == "http://query.example.internal:9999"


def test_explicit_query_base_url_strips_credentials_query_and_fragment(monkeypatch):
    monkeypatch.setenv(
        "LOTUS_CORE_QUERY_BASE_URL",
        "https://user:secret@query.example.internal:9999/api?token=secret#fragment",
    )
    monkeypatch.delenv("LOTUS_CORE_BASE_URL", raising=False)

    assert _resolve_query_base_url() == "https://query.example.internal:9999/api"


def test_stateful_context_default_core_urls_keep_query_and_control_planes_separate(monkeypatch):
    monkeypatch.delenv("LOTUS_CORE_BASE_URL", raising=False)
    monkeypatch.delenv("LOTUS_CORE_QUERY_BASE_URL", raising=False)

    assert _resolve_query_base_url() == "http://core-query.dev.lotus"
    assert _resolve_control_plane_base_url() == "http://core-control.dev.lotus"


def test_control_plane_base_url_derives_from_recognized_query_service_env(monkeypatch):
    monkeypatch.delenv("LOTUS_CORE_BASE_URL", raising=False)
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", "http://core-query.dev.lotus")

    assert _resolve_control_plane_base_url() == "http://core-control.dev.lotus"


def test_control_plane_base_url_derives_from_query_service_port_env(monkeypatch):
    monkeypatch.delenv("LOTUS_CORE_BASE_URL", raising=False)
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", "http://host.docker.internal:8201")

    assert _resolve_control_plane_base_url() == "http://host.docker.internal:8202"


def test_core_base_url_derivation_strips_credentials_and_swaps_ports(monkeypatch):
    monkeypatch.delenv("LOTUS_CORE_QUERY_BASE_URL", raising=False)
    monkeypatch.setenv(
        "LOTUS_CORE_BASE_URL",
        "http://user:secret@core.dev.lotus:8202/api/?token=should-not-leak#fragment",
    )

    assert _resolve_query_base_url() == "http://core.dev.lotus:8201/api"
    assert _resolve_control_plane_base_url() == "http://core.dev.lotus:8202/api"


def test_stateful_context_env_parsing_uses_defaults_for_missing_values(monkeypatch) -> None:
    monkeypatch.delenv("LOTUS_CORE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("LOTUS_CORE_STATEFUL_CONTEXT_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.delenv("LOTUS_CORE_STATEFUL_CONTEXT_CACHE_MAX_SIZE", raising=False)

    timeout = _resolve_timeout()

    assert timeout.connect == 10.0
    assert _stateful_context_cache_ttl_seconds() == 15.0
    assert _stateful_context_cache_max_size() == 128


def test_stateful_context_env_parsing_fails_fast_for_invalid_values(monkeypatch) -> None:
    monkeypatch.setenv("LOTUS_CORE_TIMEOUT_SECONDS", "invalid")
    monkeypatch.setenv("LOTUS_CORE_STATEFUL_CONTEXT_CACHE_TTL_SECONDS", "invalid")
    monkeypatch.setenv("LOTUS_CORE_STATEFUL_CONTEXT_CACHE_MAX_SIZE", "invalid")

    with pytest.raises(RuntimeConfigurationError):
        _resolve_timeout()
    with pytest.raises(RuntimeConfigurationError):
        _stateful_context_cache_ttl_seconds()
    with pytest.raises(RuntimeConfigurationError):
        _stateful_context_cache_max_size()


def test_stateful_context_env_parsing_rejects_non_positive_runtime_values(monkeypatch) -> None:
    monkeypatch.setenv("LOTUS_CORE_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("LOTUS_CORE_STATEFUL_CONTEXT_CACHE_TTL_SECONDS", "-1")
    monkeypatch.setenv("LOTUS_CORE_STATEFUL_CONTEXT_CACHE_MAX_SIZE", "0")

    with pytest.raises(RuntimeConfigurationError):
        _resolve_timeout()
    with pytest.raises(RuntimeConfigurationError):
        _stateful_context_cache_ttl_seconds()
    with pytest.raises(RuntimeConfigurationError):
        _stateful_context_cache_max_size()


def test_decimal_and_liquidity_helpers_cover_fallback_branches() -> None:
    assert _decimal_or_none(None) is None
    assert _decimal_or_none("") is None
    assert _decimal_or_none("bad") is None
    assert _require_decimal("12.5", error_code="UNUSED") == pytest.approx(12.5)
    with pytest.raises(LotusCoreStatefulContextUnavailableError):
        _require_decimal("bad", error_code="DECIMAL_REQUIRED")

    assert (
        _prefer_upstream_liquidity_tier(
            raw_liquidity_tier="L4",
            asset_class="Equity",
            product_type="Equity",
            sector="Technology",
            rating="A",
        )
        == "L4"
    )
    assert (
        _prefer_upstream_liquidity_tier(
            asset_class="Equity",
            product_type="ETF",
            sector="Technology",
            rating="A",
        )
        == "L1"
    )
    assert (
        _prefer_upstream_liquidity_tier(
            asset_class="Bond",
            product_type="Bond",
            sector="Government",
            rating="AA",
        )
        == "L1"
    )
    assert (
        _prefer_upstream_liquidity_tier(
            asset_class="Bond",
            product_type="Bond",
            sector="Corporate",
            rating="BBB",
        )
        == "L2"
    )
    assert (
        _prefer_upstream_liquidity_tier(
            asset_class="Bond",
            product_type="Bond",
            sector="Corporate",
            rating="BB",
        )
        == "L3"
    )
    assert (
        _prefer_upstream_liquidity_tier(
            asset_class="Fund",
            product_type="Fund",
            sector="Private Credit",
            rating=None,
        )
        == "L5"
    )
    assert (
        _prefer_upstream_liquidity_tier(
            asset_class="Fund",
            product_type="Fund",
            sector="Fixed Income",
            rating=None,
        )
        == "L3"
    )
    assert (
        _prefer_upstream_liquidity_tier(
            asset_class="Fund",
            product_type="Fund",
            sector="Equity",
            rating=None,
        )
        == "L2"
    )
    assert (
        _prefer_upstream_liquidity_tier(
            asset_class="Fixed Income",
            product_type="Note",
            sector="Government",
            rating=None,
        )
        == "L1"
    )
    assert (
        _prefer_upstream_liquidity_tier(
            asset_class="Fixed Income",
            product_type="Note",
            sector="Corporate",
            rating=None,
        )
        == "L2"
    )
    assert (
        _prefer_upstream_liquidity_tier(
            asset_class="Other",
            product_type="Structured",
            sector="Other",
            rating=None,
        )
        is None
    )


def test_request_and_selector_helpers_reject_invalid_payload_shapes(monkeypatch) -> None:
    class _BadJsonClient:
        def request(
            self, method: str, url: str, json: dict[str, Any] | None = None
        ) -> _FakeResponse:
            return _FakeResponse(payload=["not-a-dict"])

    with pytest.raises(LotusCoreStatefulContextUnavailableError):
        _request_json(
            _BadJsonClient(),  # type: ignore[arg-type]
            method="GET",
            base_url="http://core-query.dev.lotus",
            path="/portfolios/demo",
            error_code="LOTUS_CORE_STATEFUL_PORTFOLIO_UNAVAILABLE",
        )

    assert _select_latest_dated_row([], date_key="price_date", as_of="2026-03-27") is None
    assert _select_instrument_row({"instruments": []}) is None
    assert _select_latest_price_row(price_payload={"prices": "bad"}, as_of="2026-03-27") is None
    assert _select_latest_fx_row(fx_payload={"rates": "bad"}, as_of="2026-03-27") is None


def test_instrument_enrichment_bulk_ignores_invalid_records(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            (
                "POST",
                "http://core-control.dev.lotus/integration/instruments/enrichment-bulk",
            ): _FakeResponse(
                {
                    "records": [
                        {"security_id": "SEC_OK", "issuer_id": "ISSUER_OK"},
                        "bad-row",
                        {"security_id": ""},
                    ]
                }
            )
        }
    )

    payload = _fetch_instrument_enrichment_bulk(
        fake_client,  # type: ignore[arg-type]
        base_url="http://core-control.dev.lotus",
        security_ids=["SEC_OK", "SEC_BAD"],
        portfolio_id="PF_TEST",
        as_of="2026-03-27",
    )

    assert payload == {"SEC_OK": {"security_id": "SEC_OK", "issuer_id": "ISSUER_OK"}}


def test_classification_taxonomy_fetches_governed_instrument_labels() -> None:
    fake_client = _FakeClient(
        {
            (
                "POST",
                "http://core-control.dev.lotus/integration/reference/classification-taxonomy",
            ): _FakeResponse(
                {
                    "taxonomy_version": "rfc_062_v1",
                    "records": [
                        {
                            "classification_set_id": "wm_global_taxonomy_v1",
                            "taxonomy_scope": "instrument",
                            "dimension_name": "asset_class",
                            "dimension_value": "fixed income",
                            "effective_from": "2025-01-01",
                            "quality_status": "accepted",
                        },
                        {
                            "classification_set_id": "wm_global_taxonomy_v1",
                            "taxonomy_scope": "instrument",
                            "dimension_name": "product_type",
                            "dimension_value": "ETF",
                            "effective_from": "2025-01-01",
                            "quality_status": "accepted",
                        },
                        {"dimension_name": "", "dimension_value": "ignored"},
                        "bad-row",
                    ],
                    "request_fingerprint": "fingerprint_001",
                }
            )
        }
    )

    taxonomy = _fetch_classification_taxonomy(
        fake_client,  # type: ignore[arg-type]
        base_url="http://core-control.dev.lotus",
        as_of="2026-03-27",
    )

    assert fake_client.requests == [
        (
            "POST",
            "http://core-control.dev.lotus/integration/reference/classification-taxonomy",
            {"as_of_date": "2026-03-27", "taxonomy_scope": "instrument"},
        )
    ]
    assert taxonomy.taxonomy_version == "rfc_062_v1"
    assert taxonomy.labels_by_dimension == {
        "ASSET_CLASS": {"FIXED_INCOME": "FIXED_INCOME"},
        "PRODUCT_TYPE": {"ETF": "ETF"},
    }


def test_shelf_entries_prefer_governed_taxonomy_and_expose_missing_labels() -> None:
    taxonomy = ClassificationTaxonomy(
        labels_by_dimension={
            "ASSET_CLASS": {"EQUITY": "EQUITY"},
            "PRODUCT_TYPE": {"ETF": "ETF"},
        },
        taxonomy_version="rfc_062_v1",
    )
    shelf_entries = _build_shelf_entries(
        positions_payload={
            "positions": [
                {
                    "security_id": "SEC_GOVERNED",
                    "asset_class": "equity",
                    "product_type": "etf",
                    "sector": "Technology",
                    "rating": "A",
                },
                {
                    "security_id": "SEC_UNGOVERNED",
                    "asset_class": "Digital Asset",
                    "product_type": "Structured Note",
                    "sector": "Other",
                },
            ]
        },
        cash_payload={"cash_accounts": []},
        classification_taxonomy=taxonomy,
    )

    by_id = {entry.instrument_id: entry.model_dump(mode="json") for entry in shelf_entries}
    assert by_id["SEC_GOVERNED"]["asset_class"] == "EQUITY"
    assert by_id["SEC_GOVERNED"]["attributes"] == {
        "asset_class_source": "lotus_core_classification_taxonomy",
        "classification_taxonomy_version": "rfc_062_v1",
        "product_type": "ETF",
        "product_type_source": "lotus_core_classification_taxonomy",
        "rating": "A",
        "sector": "Technology",
        "source": "LOTUS_CORE_STATEFUL_CONTEXT",
    }
    assert by_id["SEC_UNGOVERNED"]["asset_class"] == "UNKNOWN"
    assert by_id["SEC_UNGOVERNED"]["attributes"]["asset_class_source"] == (
        "missing_governed_taxonomy_label"
    )
    assert by_id["SEC_UNGOVERNED"]["attributes"]["product_type_source"] == (
        "missing_governed_taxonomy_label"
    )


def test_stateful_builders_skip_malformed_rows() -> None:
    positions_payload = {
        "positions": [
            "bad-row",
            {"security_id": "CASH_USD", "asset_class": "Cash", "currency": "USD"},
            {"security_id": "", "asset_class": "Equity", "quantity": "10"},
            {"security_id": "SEC_NO_QTY", "asset_class": "Equity", "quantity": None},
            {
                "security_id": "SEC_NO_VAL",
                "asset_class": "Equity",
                "quantity": "10",
                "currency": "USD",
                "valuation": "bad",
            },
            {
                "security_id": "SEC_NO_PRICE",
                "asset_class": "Equity",
                "quantity": "10",
                "currency": "USD",
                "valuation": {"market_price": None},
            },
        ]
    }
    cash_payload = {
        "cash_accounts": [
            "bad-row",
            {"account_currency": "", "balance_account_currency": "10"},
            {"account_currency": "USD", "balance_account_currency": None},
            {"account_currency": "USD", "balance_account_currency": "10", "instrument_id": ""},
        ]
    }

    assert _build_positions(positions_payload, portfolio_base_currency="USD") == [
        Position(instrument_id="SEC_NO_VAL", quantity="10", market_value=None, lots=[]),
        Position(instrument_id="SEC_NO_PRICE", quantity="10", market_value=None, lots=[]),
    ]
    assert _build_prices(positions_payload) == []
    assert [balance.currency for balance in _build_cash_balances(cash_payload)] == ["USD"]
    assert (
        _derive_fx_rates(
            portfolio_base_currency="USD",
            positions_payload={"positions": ["bad-row", {"currency": "CHF", "valuation": "bad"}]},
            cash_payload={"cash_accounts": ["bad-row"]},
        )
        == []
    )
    assert (
        _build_shelf_entries(
            positions_payload={"positions": ["bad-row", {"security_id": ""}]},
            cash_payload={"cash_accounts": ["bad-row", {"instrument_id": ""}]},
            enrichment_by_instrument_id={},
        )
        == []
    )


def test_append_helpers_skip_duplicates_and_invalid_market_data(monkeypatch) -> None:
    request = ProposalSimulateRequest(
        portfolio_snapshot=PortfolioSnapshot(
            portfolio_id="pf_1",
            base_currency="USD",
            positions=[],
            cash_balances=[],
        ),
        market_data_snapshot=MarketDataSnapshot(prices=[], fx_rates=[]),
        shelf_entries=[],
        options=EngineOptions(enable_proposal_simulation=True),
        proposed_cash_flows=[],
        proposed_trades=[],
        reference_model=None,
    )

    _append_price_if_missing(
        simulate_request=request,
        instrument_id="SEC_1",
        instrument_currency="USD",
        latest_price_row={"price": None},
    )
    _append_shelf_entry_if_missing(
        simulate_request=request,
        instrument_id="SEC_1",
        instrument_row={"asset_class": "Equity"},
    )
    _append_shelf_entry_if_missing(
        simulate_request=request,
        instrument_id="SEC_1",
        instrument_row={"asset_class": "Equity"},
    )
    assert len(request.shelf_entries) == 1
    assert request.market_data_snapshot.prices == []

    fake_client = _FakeClient(
        {
            (
                "GET",
                "http://core-query.dev.lotus/fx-rates/?from_currency=CHF&to_currency=USD",
            ): _FakeResponse({"rates": [{"rate_date": "2026-03-27", "rate": None}]})
        }
    )
    _append_fx_rate_if_missing(
        client=fake_client,  # type: ignore[arg-type]
        simulate_request=request,
        instrument_currency="CHF",
        portfolio_base_currency="USD",
        base_url="http://core-query.dev.lotus",
        as_of="2026-03-27",
    )
    assert request.market_data_snapshot.fx_rates == []

    future_rate_client = _FakeClient(
        {
            (
                "GET",
                "http://core-query.dev.lotus/fx-rates/?from_currency=GBP&to_currency=USD",
            ): _FakeResponse({"rates": [{"rate_date": "2026-03-28", "rate": "1.25"}]})
        }
    )
    _append_fx_rate_if_missing(
        client=future_rate_client,  # type: ignore[arg-type]
        simulate_request=request,
        instrument_currency="GBP",
        portfolio_base_currency="USD",
        base_url="http://core-query.dev.lotus",
        as_of="2026-03-27",
    )
    assert request.market_data_snapshot.fx_rates == []


def test_append_shelf_entry_if_missing_preserves_enrichment_and_taxonomy_metadata() -> None:
    request = ProposalSimulateRequest(
        portfolio_snapshot=PortfolioSnapshot(
            portfolio_id="pf_1",
            base_currency="USD",
            positions=[],
            cash_balances=[],
        ),
        market_data_snapshot=MarketDataSnapshot(prices=[], fx_rates=[]),
        shelf_entries=[],
        options=EngineOptions(enable_proposal_simulation=True),
        proposed_cash_flows=[],
        proposed_trades=[],
        reference_model=None,
    )
    taxonomy = ClassificationTaxonomy(
        labels_by_dimension={
            "ASSET_CLASS": {"EQUITY": "EQUITY"},
            "PRODUCT_TYPE": {"ETF": "ETF"},
        },
        taxonomy_version="rfc_062_v1",
    )

    _append_shelf_entry_if_missing(
        simulate_request=request,
        instrument_id="SEC_1",
        instrument_row={
            "asset_class": "equity",
            "product_type": "ETF",
            "sector": "Technology",
            "country_of_risk": "US",
            "rating": "A",
        },
        enrichment_row={
            "issuer_id": "ISSUER_1",
            "liquidity_tier": "L4",
            "ultimate_parent_issuer_id": "ULTIMATE_1",
            "ultimate_parent_issuer_name": "Issuer Parent",
        },
        classification_taxonomy=taxonomy,
    )

    assert request.shelf_entries[0].model_dump(mode="json") == {
        "instrument_id": "SEC_1",
        "status": "APPROVED",
        "asset_class": "EQUITY",
        "issuer_id": "ISSUER_1",
        "liquidity_tier": "L4",
        "min_notional": None,
        "settlement_days": 2,
        "attributes": {
            "asset_class_source": "lotus_core_classification_taxonomy",
            "classification_taxonomy_version": "rfc_062_v1",
            "country": "US",
            "product_type": "ETF",
            "product_type_source": "lotus_core_classification_taxonomy",
            "rating": "A",
            "sector": "Technology",
            "source": "LOTUS_CORE_STATEFUL_CONTEXT",
            "ultimate_parent_issuer_id": "ULTIMATE_1",
            "ultimate_parent_issuer_name": "Issuer Parent",
        },
    }


def test_enrich_trade_drafts_skips_missing_price_date_and_missing_currency(monkeypatch) -> None:
    simulate_request = ProposalSimulateRequest.model_validate(
        {
            "portfolio_snapshot": {"portfolio_id": "pf_1", "base_currency": "USD"},
            "market_data_snapshot": {"prices": [], "fx_rates": []},
            "shelf_entries": [],
            "options": {"enable_proposal_simulation": True},
            "proposed_cash_flows": [],
            "proposed_trades": [{"side": "BUY", "instrument_id": "SEC_NEW", "quantity": "1"}],
        }
    )
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", "http://core-query.dev.lotus")
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://core-control.dev.lotus")
    fake_client = _FakeClient(
        {
            (
                "POST",
                "http://core-control.dev.lotus/integration/instruments/enrichment-bulk",
            ): _FakeResponse({"records": [{"security_id": "SEC_NEW", "issuer_id": "ISSUER_NEW"}]}),
            (
                "GET",
                "http://core-query.dev.lotus/instruments/?security_id=SEC_NEW",
            ): _FakeResponse(
                {"instruments": [{"security_id": "SEC_NEW", "asset_class": "Equity"}]}
            ),
            (
                "GET",
                "http://core-query.dev.lotus/prices/?security_id=SEC_NEW",
            ): _FakeResponse({"prices": [{"price_date": "2026-03-27", "price": "10"}]}),
        }
    )
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: fake_client,
    )

    enriched = enrich_stateful_simulate_request_for_trade_drafts(
        simulate_request=simulate_request,
        as_of="2026-03-27",
    )

    assert enriched.market_data_snapshot.prices == []
    assert enriched.shelf_entries == []


def test_resolve_stateful_context_rejects_missing_resolved_as_of(
    monkeypatch, stateful_input
) -> None:
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "positions": []}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "resolved_as_of_date": "", "cash_accounts": []}
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    with pytest.raises(LotusCoreStatefulContextUnavailableError) as exc_info:
        resolve_stateful_context_with_lotus_core(stateful_input.model_copy(update={"as_of": ""}))

    assert str(exc_info.value) == "LOTUS_CORE_STATEFUL_CONTEXT_INVALID"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payloads: payloads["portfolio"].update({"portfolio_id": "OTHER_PORTFOLIO"}),
        lambda payloads: payloads["positions"].update({"portfolio_id": "OTHER_PORTFOLIO"}),
        lambda payloads: payloads["cash"].update({"portfolio_id": "OTHER_PORTFOLIO"}),
        lambda payloads: payloads["cash"].update({"resolved_as_of_date": "2026-03-28"}),
        lambda payloads: (
            payloads["positions"].update({"portfolio_snapshot_id": "ps_rev_1"})
            or payloads["cash"].update({"portfolio_snapshot_id": "ps_rev_2"})
        ),
        lambda payloads: (
            payloads["positions"].update({"market_data_snapshot_id": "md_rev_1"})
            or payloads["cash"].update({"market_data_snapshot_id": "md_rev_2"})
        ),
    ],
)
def test_resolve_stateful_context_rejects_upstream_identity_mismatch(
    monkeypatch,
    stateful_input,
    mutator,
) -> None:
    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    payloads = {
        "portfolio": {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"},
        "positions": {"portfolio_id": "DEMO_ADV_USD_001", "positions": []},
        "cash": {
            "portfolio_id": "DEMO_ADV_USD_001",
            "resolved_as_of_date": "2026-03-27",
            "cash_accounts": [],
        },
    }
    mutator(payloads)
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(payloads["portfolio"]),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            payloads["positions"]
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            payloads["cash"]
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/reference/classification-taxonomy",
        ): _FakeResponse({"records": []}),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    with pytest.raises(LotusCoreStatefulContextUnavailableError) as exc_info:
        resolve_stateful_context_with_lotus_core(stateful_input)

    assert str(exc_info.value) == "LOTUS_CORE_STATEFUL_CONTEXT_INVALID"


def test_resolve_stateful_context_preserves_upstream_source_provenance(monkeypatch) -> None:
    from src.core.workspace.models import WorkspaceStatefulInput

    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    responses = {
        ("GET", f"{base_url}/portfolios/PF_REVISIONED"): _FakeResponse(
            {
                "portfolio_id": "PF_REVISIONED",
                "base_currency": "USD",
                "portfolio_snapshot_id": "core-portfolio-snapshot-rev-001",
                "source_version": "portfolio-revision-001",
                "source_event_id": "portfolio-event-001",
                "source_hash": "sha256:portfolio-source",
                "generated_at": "2026-03-27T09:30:00Z",
                "freshness_status": "CURRENT",
            }
        ),
        ("GET", f"{base_url}/portfolios/PF_REVISIONED/positions"): _FakeResponse(
            {
                "portfolio_id": "PF_REVISIONED",
                "portfolio_snapshot_id": "core-portfolio-snapshot-rev-001",
                "market_data_snapshot_id": "core-market-data-snapshot-rev-001",
                "source_version": "market-data-revision-001",
                "source_batch_id": "market-data-batch-001",
                "source_hash": "sha256:market-data-source",
                "valuation_timestamp": "2026-03-27T09:35:00Z",
                "freshness_status": "CURRENT",
                "positions": [],
            }
        ),
        ("GET", f"{base_url}/portfolios/PF_REVISIONED/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "PF_REVISIONED",
                "resolved_as_of_date": "2026-03-27",
                "portfolio_snapshot_id": "core-portfolio-snapshot-rev-001",
                "market_data_snapshot_id": "core-market-data-snapshot-rev-001",
                "cash_accounts": [],
            }
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    resolved = resolve_stateful_context_with_lotus_core(
        WorkspaceStatefulInput(portfolio_id="PF_REVISIONED", as_of="2026-03-27")
    )

    provenance = resolved.resolved_context.source_provenance
    assert provenance is not None
    assert resolved.resolved_context.portfolio_snapshot_id == "core-portfolio-snapshot-rev-001"
    assert resolved.resolved_context.market_data_snapshot_id == "core-market-data-snapshot-rev-001"
    assert resolved.simulate_request.portfolio_snapshot.snapshot_id == (
        "core-portfolio-snapshot-rev-001"
    )
    assert resolved.simulate_request.market_data_snapshot.snapshot_id == (
        "core-market-data-snapshot-rev-001"
    )
    assert provenance.portfolio.source_version == "portfolio-revision-001"
    assert provenance.portfolio.source_event_id == "portfolio-event-001"
    assert provenance.portfolio.source_hash == "sha256:portfolio-source"
    assert provenance.market_data.source_version == "market-data-revision-001"
    assert provenance.market_data.source_batch_id == "market-data-batch-001"
    assert provenance.market_data.valuation_timestamp == "2026-03-27T09:35:00Z"
    assert provenance.raw_payload_stored is False

    result = run_proposal_simulation(
        portfolio=resolved.simulate_request.portfolio_snapshot,
        market_data=resolved.simulate_request.market_data_snapshot,
        shelf=resolved.simulate_request.shelf_entries,
        options=resolved.simulate_request.options,
        proposed_cash_flows=resolved.simulate_request.proposed_cash_flows,
        proposed_trades=resolved.simulate_request.proposed_trades,
        request_hash="sha256:source-revisioned-context",
        simulation_contract_version="advisory-simulation.v1",
    )

    assert result.lineage.portfolio_snapshot_id == "core-portfolio-snapshot-rev-001"
    assert result.lineage.market_data_snapshot_id == "core-market-data-snapshot-rev-001"
    assert result.lineage.source_provenance == provenance
    lineage_payload = result.lineage.model_dump(mode="json")
    assert "positions" not in str(lineage_payload)
    assert "cash_accounts" not in str(lineage_payload)


def test_resolve_stateful_context_accepts_componentized_market_data_hashes(monkeypatch) -> None:
    from src.core.workspace.models import WorkspaceStatefulInput

    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    positions_hash = "sha256:positions-source"
    cash_hash = "sha256:cash-source"
    responses = {
        ("GET", f"{base_url}/portfolios/PB_SG_GLOBAL_BAL_001"): _FakeResponse(
            {
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "base_currency": "USD",
            }
        ),
        ("GET", f"{base_url}/portfolios/PB_SG_GLOBAL_BAL_001/positions"): _FakeResponse(
            {
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "snapshot_id": "holdings_as_of:positions",
                "content_hash": positions_hash,
                "generated_at": "2026-08-01T11:46:22.074848Z",
                "freshness_status": "CURRENT",
                "positions": [],
            }
        ),
        ("GET", f"{base_url}/portfolios/PB_SG_GLOBAL_BAL_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "resolved_as_of_date": "2026-04-10",
                "snapshot_id": "holdings_as_of_cash_balances:cash",
                "content_hash": cash_hash,
                "generated_at": "2026-08-01T11:46:22.097731Z",
                "freshness_status": "CURRENT",
                "cash_accounts": [],
            }
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    resolved = resolve_stateful_context_with_lotus_core(
        WorkspaceStatefulInput(portfolio_id="PB_SG_GLOBAL_BAL_001", as_of="2026-04-10")
    )

    provenance = resolved.resolved_context.source_provenance
    assert provenance is not None
    expected_market_hash = hash_canonical_payload(
        {
            "source_system": "LOTUS_CORE",
            "source_kind": "MARKET_DATA",
            "component_hashes": sorted([positions_hash, cash_hash]),
        }
    )
    assert provenance.market_data.source_hash == expected_market_hash
    assert provenance.market_data.source_id == (
        f"lotus-core:market-data:PB_SG_GLOBAL_BAL_001:2026-04-10:{expected_market_hash}"
    )
    assert provenance.market_data.valuation_timestamp == "2026-08-01T11:46:22.097731Z"
    assert provenance.market_data.freshness_status == "CURRENT"
    assert resolved.resolved_context.market_data_snapshot_id == provenance.market_data.source_id


def test_lotus_core_source_completeness_counts_rejections_without_raw_payloads() -> None:
    report = build_lotus_core_source_completeness(
        portfolio_id="PF_SOURCE_QUALITY",
        resolved_as_of="2026-03-27",
        portfolio_base_currency="USD",
        positions_payload={
            "positions": [
                {
                    "security_id": "SEC_OK",
                    "quantity": "10",
                    "asset_class": "Equity",
                    "currency": "USD",
                    "valuation": {"market_price": "25", "market_value": "250"},
                },
                {
                    "security_id": "SEC_OK",
                    "quantity": "2",
                    "asset_class": "Equity",
                    "currency": "USD",
                    "valuation": {"market_price": "25", "market_value": "50"},
                },
                "raw-sensitive-bad-row",
                {"security_id": "", "asset_class": "Equity", "quantity": "1"},
                {
                    "security_id": "SEC_NAN",
                    "quantity": "NaN",
                    "asset_class": "Equity",
                    "currency": "USD",
                    "valuation": {"market_price": "10", "market_value": "10"},
                },
                {
                    "security_id": "SEC_NO_VAL",
                    "quantity": "1",
                    "asset_class": "Bond",
                    "currency": "USD",
                    "valuation": {"market_price": "99.5"},
                },
            ]
        },
        cash_payload={
            "cash_accounts": [
                {"account_currency": "USD", "balance_account_currency": "100"},
                "raw-sensitive-cash-row",
                {"account_currency": "", "balance_account_currency": "50"},
            ]
        },
        enrichment_by_instrument_id={"SEC_OK": {"security_id": "SEC_OK"}},
        classification_taxonomy=None,
        classification_taxonomy_unavailable=True,
    )

    by_collection = {item.source_collection: item for item in report.collections}

    assert report.status == "INCOMPLETE"
    assert report.raw_payload_stored is False
    assert by_collection["POSITIONS"].received_count == 6
    assert by_collection["POSITIONS"].accepted_count == 2
    assert by_collection["POSITIONS"].rejected_count == 4
    assert by_collection["POSITIONS"].duplicate_count == 1
    assert by_collection["POSITIONS"].rejection_reasons == {
        "INVALID_QUANTITY": 1,
        "INVALID_MARKET_VALUE": 1,
        "MISSING_SECURITY_ID": 1,
        "NON_OBJECT_ROW": 1,
    }
    assert by_collection["CASH_BALANCES"].rejection_reasons == {
        "MISSING_CURRENCY": 1,
        "NON_OBJECT_ROW": 1,
    }
    assert by_collection["PRICES"].received_count == 5
    assert by_collection["PRICES"].accepted_count == 4
    assert by_collection["PRICES"].rejected_count == 1
    assert by_collection["PRICES"].rejection_reasons == {"MISSING_PRICE_VALUATION": 1}
    assert by_collection["INSTRUMENT_ENRICHMENT"].required is False
    assert by_collection["INSTRUMENT_ENRICHMENT"].rejection_reasons == {"MISSING_ENRICHMENT": 2}
    assert by_collection["CLASSIFICATION_TAXONOMY"].rejection_reasons == {
        "CLASSIFICATION_TAXONOMY_UNAVAILABLE": 1
    }
    assert "raw-sensitive" not in str(report.model_dump(mode="json"))


def test_resolve_stateful_context_reports_optional_source_degradation_in_lineage(
    monkeypatch, stateful_input
) -> None:
    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "positions": [
                    {
                        "security_id": "SEC_OPTIONAL_GAP",
                        "quantity": "10",
                        "asset_class": "Equity",
                        "currency": "USD",
                        "valuation": {"market_price": "20", "market_value": "200"},
                    }
                ],
            }
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [{"account_currency": "USD", "balance_account_currency": "50"}],
            }
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse({"records": ["bad-row", {"security_id": ""}]}),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    resolved = resolve_stateful_context_with_lotus_core(stateful_input)

    source_completeness = resolved.resolved_context.source_completeness
    assert source_completeness is not None
    assert source_completeness.status == "DEGRADED"
    by_collection = {item.source_collection: item for item in source_completeness.collections}
    assert by_collection["POSITIONS"].status == "COMPLETE"
    assert by_collection["CASH_BALANCES"].status == "COMPLETE"
    assert by_collection["INSTRUMENT_ENRICHMENT"].rejection_reasons == {
        "MALFORMED_ENRICHMENT": 2,
        "MISSING_ENRICHMENT": 1,
    }
    assert by_collection["CLASSIFICATION_TAXONOMY"].rejection_reasons == {
        "CLASSIFICATION_TAXONOMY_UNAVAILABLE": 1
    }

    result = run_proposal_simulation(
        portfolio=resolved.simulate_request.portfolio_snapshot,
        market_data=resolved.simulate_request.market_data_snapshot,
        shelf=resolved.simulate_request.shelf_entries,
        options=resolved.simulate_request.options,
        proposed_cash_flows=[],
        proposed_trades=[],
        request_hash="sha256:source-completeness",
    )

    assert result.status == "READY"
    assert result.lineage.source_completeness == source_completeness
    assert result.lineage.source_completeness.raw_payload_stored is False


def test_resolve_stateful_context_rejects_silently_dropped_required_source_rows(
    monkeypatch, stateful_input
) -> None:
    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "positions": [
                    {
                        "security_id": "SEC_VALID",
                        "quantity": "10",
                        "asset_class": "Equity",
                        "currency": "USD",
                        "valuation": {"market_price": "10", "market_value": "100"},
                    },
                    "bad-row",
                    {"security_id": "", "asset_class": "Equity", "quantity": "5"},
                    {
                        "security_id": "SEC_MISSING_VALUE",
                        "quantity": "2",
                        "asset_class": "Bond",
                        "currency": "USD",
                        "valuation": {"market_price": "99.5"},
                    },
                ],
            }
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [{"account_currency": "USD", "balance_account_currency": "10"}],
            }
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse({"records": [{"security_id": "SEC_VALID"}]}),
        (
            "POST",
            f"{control_plane_base_url}/integration/reference/classification-taxonomy",
        ): _FakeResponse(
            {"records": [{"dimension_name": "asset_class", "dimension_value": "Equity"}]}
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    with pytest.raises(LotusCoreStatefulContextUnavailableError) as exc_info:
        resolve_stateful_context_with_lotus_core(stateful_input)

    assert str(exc_info.value) == "LOTUS_CORE_STATEFUL_SOURCE_INCOMPLETE"


def test_resolve_stateful_context_with_lotus_core_builds_simulation_request(
    monkeypatch, stateful_input
):
    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    responses = {
        (
            "GET",
            f"{base_url}/portfolios/DEMO_ADV_USD_001",
        ): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "base_currency": "USD",
            }
        ),
        (
            "GET",
            f"{base_url}/portfolios/DEMO_ADV_USD_001/positions",
        ): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "positions": [
                    {
                        "security_id": "CASH_USD",
                        "quantity": 235350.0,
                        "asset_class": "Cash",
                        "currency": "USD",
                        "valuation": {
                            "market_price": "1.0000000000",
                            "market_value": "235350.0000000000",
                            "market_value_local": "235350.0000000000",
                        },
                    },
                    {
                        "security_id": "SEC_AAPL_US",
                        "quantity": 800.0,
                        "asset_class": "Equity",
                        "currency": "USD",
                        "sector": "Information Technology",
                        "country_of_risk": "United States",
                        "product_type": "Equity",
                        "liquidity_tier": "L2",
                        "issuer_id": "ISSUER_AAPL",
                        "ultimate_parent_issuer_id": "ISSUER_AAPL",
                        "ultimate_parent_issuer_name": "Apple Inc.",
                        "valuation": {
                            "market_price": "194.0000000000",
                            "market_value": "155200.0000000000",
                            "market_value_local": "155200.0000000000",
                        },
                    },
                    {
                        "security_id": "SEC_NESN_CH",
                        "quantity": 120.0,
                        "asset_class": "Equity",
                        "currency": "CHF",
                        "sector": "Consumer Staples",
                        "country_of_risk": "Switzerland",
                        "product_type": "Equity",
                        "rating": "AA",
                        "issuer_id": "ISSUER_NESN",
                        "ultimate_parent_issuer_id": "ISSUER_NESN",
                        "ultimate_parent_issuer_name": "Nestle S.A.",
                        "valuation": {
                            "market_price": "94.5000000000",
                            "market_value": "12400.0000000000",
                            "market_value_local": "11340.0000000000",
                        },
                    },
                ],
            }
        ),
        (
            "GET",
            f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances",
        ): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "portfolio_currency": "USD",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [
                    {
                        "cash_account_id": "CASH_USD",
                        "instrument_id": "CASH_USD",
                        "security_id": "CASH_USD",
                        "account_currency": "USD",
                        "balance_account_currency": "235350.0000000000",
                        "balance_portfolio_currency": "235350.0000000000",
                    },
                    {
                        "cash_account_id": "CASH_CHF",
                        "instrument_id": "CASH_CHF",
                        "security_id": "CASH_CHF",
                        "account_currency": "CHF",
                        "balance_account_currency": "1000.0000000000",
                        "balance_portfolio_currency": "1093.0000000000",
                    },
                ],
            }
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse(
            {
                "records": [
                    {
                        "security_id": "SEC_AAPL_US",
                        "issuer_id": "ISSUER_AAPL",
                        "ultimate_parent_issuer_id": "ISSUER_AAPL",
                        "ultimate_parent_issuer_name": "Apple Inc.",
                    },
                    {
                        "security_id": "SEC_NESN_CH",
                        "issuer_id": "ISSUER_NESN",
                        "ultimate_parent_issuer_id": "ISSUER_NESN",
                        "ultimate_parent_issuer_name": "Nestle S.A.",
                    },
                ]
            }
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    resolved = resolve_stateful_context_with_lotus_core(stateful_input)

    assert isinstance(resolved, LotusCoreResolvedAdvisoryContext)
    assert resolved.resolved_context.portfolio_id == "DEMO_ADV_USD_001"
    assert resolved.resolved_context.as_of == "2026-03-27"
    assert resolved.resolved_context.portfolio_snapshot_id == (
        "lotus-core:portfolio:DEMO_ADV_USD_001:2026-03-27"
    )
    request = resolved.simulate_request
    assert request.portfolio_snapshot.base_currency == "USD"
    assert request.portfolio_snapshot.model_dump(mode="json")["positions"] == [
        {
            "instrument_id": "SEC_AAPL_US",
            "quantity": "800.0",
            "market_value": {"amount": "155200.0000000000", "currency": "USD"},
            "lots": [],
        },
        {
            "instrument_id": "SEC_NESN_CH",
            "quantity": "120.0",
            "market_value": {"amount": "12400.0000000000", "currency": "USD"},
            "lots": [],
        },
    ]
    assert request.portfolio_snapshot.model_dump(mode="json")["cash_balances"] == [
        {"currency": "USD", "amount": "235350.0000000000", "settled": None, "pending": None},
        {"currency": "CHF", "amount": "1000.0000000000", "settled": None, "pending": None},
    ]
    assert request.market_data_snapshot.model_dump(mode="json")["prices"] == [
        {"instrument_id": "SEC_AAPL_US", "price": "194.0000000000", "currency": "USD"},
        {"instrument_id": "SEC_NESN_CH", "price": "94.5000000000", "currency": "CHF"},
    ]
    assert [entry.model_dump(mode="json") for entry in request.shelf_entries] == [
        {
            "instrument_id": "CASH_USD",
            "status": "APPROVED",
            "asset_class": "CASH",
            "issuer_id": None,
            "liquidity_tier": "L1",
            "settlement_days": 2,
            "min_notional": None,
            "attributes": {"product_type": "Cash", "source": "LOTUS_CORE_STATEFUL_CONTEXT"},
        },
        {
            "instrument_id": "SEC_AAPL_US",
            "status": "APPROVED",
            "asset_class": "EQUITY",
            "issuer_id": "ISSUER_AAPL",
            "liquidity_tier": "L2",
            "settlement_days": 2,
            "min_notional": None,
            "attributes": {
                "country": "United States",
                "product_type": "Equity",
                "sector": "Information Technology",
                "source": "LOTUS_CORE_STATEFUL_CONTEXT",
                "ultimate_parent_issuer_id": "ISSUER_AAPL",
                "ultimate_parent_issuer_name": "Apple Inc.",
            },
        },
        {
            "instrument_id": "SEC_NESN_CH",
            "status": "APPROVED",
            "asset_class": "EQUITY",
            "issuer_id": "ISSUER_NESN",
            "liquidity_tier": "L1",
            "settlement_days": 2,
            "min_notional": None,
            "attributes": {
                "country": "Switzerland",
                "product_type": "Equity",
                "rating": "AA",
                "sector": "Consumer Staples",
                "source": "LOTUS_CORE_STATEFUL_CONTEXT",
                "ultimate_parent_issuer_id": "ISSUER_NESN",
                "ultimate_parent_issuer_name": "Nestle S.A.",
            },
        },
        {
            "instrument_id": "CASH_CHF",
            "status": "APPROVED",
            "asset_class": "CASH",
            "issuer_id": None,
            "liquidity_tier": "L1",
            "settlement_days": 2,
            "min_notional": None,
            "attributes": {"product_type": "Cash", "source": "LOTUS_CORE_STATEFUL_CONTEXT"},
        },
    ]
    assert request.market_data_snapshot.model_dump(mode="json")["fx_rates"] == [
        {"pair": "CHF/USD", "rate": "1.093"},
    ]
    assert request.options.enable_proposal_simulation is True
    assert request.options.valuation_mode == ValuationMode.TRUST_SNAPSHOT
    assert request.proposed_cash_flows == []
    assert request.proposed_trades == []


def test_resolve_stateful_context_rejects_invalid_source_derived_fx_rate(
    monkeypatch, stateful_input
) -> None:
    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "positions": [
                    {
                        "security_id": "SEC_CHF",
                        "quantity": "10",
                        "asset_class": "Equity",
                        "currency": "CHF",
                        "valuation": {
                            "market_price": "10",
                            "market_value": "-12",
                            "market_value_local": "10",
                        },
                    }
                ],
            }
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [],
            }
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse({"records": [{"security_id": "SEC_CHF"}]}),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    with pytest.raises(LotusCoreStatefulContextUnavailableError) as exc_info:
        resolve_stateful_context_with_lotus_core(stateful_input)

    assert str(exc_info.value) == "LOTUS_CORE_STATEFUL_FX_INVALID"


def test_resolve_stateful_context_with_lotus_core_propagates_as_of_to_positions_and_cash(
    monkeypatch, stateful_input
) -> None:
    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        (
            "GET",
            f"{base_url}{_positions_path(portfolio_id='DEMO_ADV_USD_001', as_of='2026-03-27')}",
        ): _FakeResponse({"portfolio_id": "DEMO_ADV_USD_001", "positions": []}),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [],
            }
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse({"records": []}),
    }
    client = _FakeClient(responses)
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: client,
    )

    resolve_stateful_context_with_lotus_core(stateful_input)

    assert (
        "GET",
        f"{base_url}{_positions_path(portfolio_id='DEMO_ADV_USD_001', as_of='2026-03-27')}",
        None,
    ) in client.requests
    assert (
        "GET",
        f"{base_url}{_cash_balances_path(portfolio_id='DEMO_ADV_USD_001', as_of='2026-03-27')}",
        None,
    ) in client.requests
    assert (
        "POST",
        f"{control_plane_base_url}/integration/reference/classification-taxonomy",
        {"as_of_date": "2026-03-27", "taxonomy_scope": "instrument"},
    ) in client.requests


def test_trust_snapshot_before_state_uses_upstream_market_value_over_local_fx_revaluation() -> None:
    request = ProposalSimulateRequest(
        portfolio_snapshot=PortfolioSnapshot(
            portfolio_id="pf_1",
            base_currency="USD",
            positions=[
                Position(
                    instrument_id="SEC_EUR",
                    quantity="10",
                    market_value=Money(amount="120", currency="USD"),
                )
            ],
            cash_balances=[],
        ),
        market_data_snapshot=MarketDataSnapshot(
            prices=[{"instrument_id": "SEC_EUR", "price": "10", "currency": "EUR"}],
            fx_rates=[{"pair": "EUR/USD", "rate": "1.5"}],
        ),
        shelf_entries=[],
        options=EngineOptions(valuation_mode=ValuationMode.TRUST_SNAPSHOT),
        proposed_cash_flows=[],
        proposed_trades=[],
    )

    state = build_simulated_state(
        request.portfolio_snapshot,
        request.market_data_snapshot,
        request.shelf_entries,
        dq_log={},
        warnings=[],
        options=request.options,
    )

    assert state.total_value.amount == Decimal("120.0")
    assert state.positions[0].value_in_base_ccy.amount == Decimal("120.0")
    assert state.positions[0].value_in_instrument_ccy.amount == Decimal("100")
    assert state.positions[0].instrument_currency == "EUR"


def test_resolve_stateful_context_with_lotus_core_rejects_invalid_portfolio_payload(
    monkeypatch, stateful_input
):
    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse({"portfolio_id": ""}),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "positions": []}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [],
            }
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse(
            {
                "records": [
                    {
                        "security_id": "SEC_AAPL_US",
                        "issuer_id": "ISSUER_AAPL",
                        "ultimate_parent_issuer_id": "ISSUER_AAPL",
                        "ultimate_parent_issuer_name": "Apple Inc.",
                    }
                ]
            }
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    with pytest.raises(LotusCoreStatefulContextUnavailableError) as exc_info:
        resolve_stateful_context_with_lotus_core(stateful_input)

    assert str(exc_info.value) == "LOTUS_CORE_STATEFUL_CONTEXT_INVALID"


def test_resolve_stateful_context_with_lotus_core_reuses_cached_context(
    monkeypatch, stateful_input
):
    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    request_counter = {"count": 0}
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "positions": []}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [],
            }
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse(
            {
                "records": [
                    {
                        "security_id": "SEC_AAPL_US",
                        "issuer_id": "ISSUER_AAPL",
                        "ultimate_parent_issuer_id": "ISSUER_AAPL",
                        "ultimate_parent_issuer_name": "Apple Inc.",
                    }
                ]
            }
        ),
    }

    class _CountingFakeClient(_FakeClient):
        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
        ) -> _FakeResponse:
            request_counter["count"] += 1
            return super().request(method, url, json=json)

    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _CountingFakeClient(responses),
    )

    first = resolve_stateful_context_with_lotus_core(stateful_input)
    second = resolve_stateful_context_with_lotus_core(stateful_input)

    assert first.resolved_context == second.resolved_context
    assert request_counter["count"] == 4
    stats = get_stateful_context_cache_stats_for_tests()
    assert stats["resolved_context"].misses == 1
    assert stats["resolved_context"].hits == 1
    assert stats["resolved_context"].writes == 1
    assert stats["resolved_context"].size == 1
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=1, positions=1, cash=1)


def test_resolve_stateful_context_with_lotus_core_returns_copy_safe_cached_results(
    monkeypatch, stateful_input
):
    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "positions": [
                    {
                        "security_id": "SEC_AAPL_US",
                        "quantity": 800.0,
                        "asset_class": "Equity",
                        "currency": "USD",
                        "valuation": {
                            "market_price": "194.0000000000",
                            "market_value": "155200.0000000000",
                            "market_value_local": "155200.0000000000",
                        },
                    }
                ],
            }
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [],
            }
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse(
            {
                "records": [
                    {
                        "security_id": "SEC_AAPL_US",
                        "issuer_id": "ISSUER_AAPL",
                        "ultimate_parent_issuer_id": "ISSUER_AAPL",
                        "ultimate_parent_issuer_name": "Apple Inc.",
                    }
                ]
            }
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    first = resolve_stateful_context_with_lotus_core(stateful_input)
    first.simulate_request.portfolio_snapshot.positions[0].instrument_id = "MUTATED"

    second = resolve_stateful_context_with_lotus_core(stateful_input)

    assert second.simulate_request.portfolio_snapshot.positions[0].instrument_id == "SEC_AAPL_US"


def test_resolve_stateful_context_with_lotus_core_refetches_when_cache_ttl_is_zero(
    monkeypatch, stateful_input
):
    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    monkeypatch.setenv("LOTUS_CORE_STATEFUL_CONTEXT_CACHE_TTL_SECONDS", "0")
    request_counter = {"count": 0}
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "positions": []}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [],
            }
        ),
    }

    class _CountingFakeClient(_FakeClient):
        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
        ) -> _FakeResponse:
            request_counter["count"] += 1
            return super().request(method, url, json=json)

    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _CountingFakeClient(responses),
    )

    resolve_stateful_context_with_lotus_core(stateful_input)
    resolve_stateful_context_with_lotus_core(stateful_input)

    assert request_counter["count"] == 8
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=2, positions=2, cash=2)


def test_resolve_stateful_context_with_lotus_core_isolates_distinct_as_of_inputs(
    monkeypatch,
):
    from src.core.workspace.models import WorkspaceStatefulInput

    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    request_counter = {"count": 0}
    cash_dates = iter(["2026-03-27", "2026-03-28"])

    class _AsOfAwareFakeClient(_FakeClient):
        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
        ) -> _FakeResponse:
            request_counter["count"] += 1
            is_cash_request = (
                method.upper() == "GET"
                and url.startswith(f"{base_url}/portfolios/")
                and "/cash-balances" in url
            )
            if is_cash_request:
                return _FakeResponse(
                    {
                        "portfolio_id": "DEMO_ADV_USD_001",
                        "resolved_as_of_date": next(cash_dates),
                        "cash_accounts": [],
                    }
                )
            return super().request(method, url, json=json)

    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "positions": []}
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _AsOfAwareFakeClient(responses),
    )

    first = resolve_stateful_context_with_lotus_core(
        WorkspaceStatefulInput(portfolio_id="DEMO_ADV_USD_001", as_of="2026-03-27")
    )
    second = resolve_stateful_context_with_lotus_core(
        WorkspaceStatefulInput(portfolio_id="DEMO_ADV_USD_001", as_of="2026-03-28")
    )

    assert first.resolved_context.as_of == "2026-03-27"
    assert second.resolved_context.as_of == "2026-03-28"
    assert (
        first.resolved_context.portfolio_snapshot_id
        != second.resolved_context.portfolio_snapshot_id
    )
    assert request_counter["count"] == 8
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=2, positions=2, cash=2)


def test_resolve_stateful_context_with_lotus_core_isolates_environment_scope(
    monkeypatch,
):
    from src.core.workspace.models import WorkspaceStatefulInput

    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    request_counter = {"count": 0}
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "positions": []}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [],
            }
        ),
    }

    class _CountingFakeClient(_FakeClient):
        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
        ) -> _FakeResponse:
            request_counter["count"] += 1
            return super().request(method, url, json=json)

    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _CountingFakeClient(responses),
    )

    stateful_input = WorkspaceStatefulInput(
        portfolio_id="DEMO_ADV_USD_001",
        as_of="2026-03-27",
    )
    monkeypatch.setenv("ENVIRONMENT", "dev")
    first = resolve_stateful_context_with_lotus_core(stateful_input)
    monkeypatch.setenv("ENVIRONMENT", "uat")
    second = resolve_stateful_context_with_lotus_core(stateful_input)

    assert first.resolved_context == second.resolved_context
    assert request_counter["count"] == 8
    stats = get_stateful_context_cache_stats_for_tests()
    assert stats["resolved_context"].misses == 2
    assert stats["resolved_context"].hits == 0
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=2, positions=2, cash=2)


def test_resolve_stateful_context_with_lotus_core_isolates_optional_identity_dimensions(
    monkeypatch,
):
    from src.core.workspace.models import WorkspaceStatefulInput

    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    request_counter = {"count": 0}
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "positions": []}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [],
            }
        ),
    }

    class _CountingFakeClient(_FakeClient):
        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
        ) -> _FakeResponse:
            request_counter["count"] += 1
            return super().request(method, url, json=json)

    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _CountingFakeClient(responses),
    )

    first = resolve_stateful_context_with_lotus_core(
        WorkspaceStatefulInput(
            portfolio_id="DEMO_ADV_USD_001",
            as_of="2026-03-27",
            mandate_id="mandate_growth_01",
            benchmark_id="benchmark_balanced_usd",
        )
    )
    second = resolve_stateful_context_with_lotus_core(
        WorkspaceStatefulInput(
            portfolio_id="DEMO_ADV_USD_001",
            as_of="2026-03-27",
            mandate_id="mandate_income_01",
            benchmark_id="benchmark_income_usd",
        )
    )

    assert first.resolved_context == second.resolved_context
    assert request_counter["count"] == 8
    stats = get_stateful_context_cache_stats_for_tests()
    assert stats["resolved_context"].misses == 2
    assert stats["resolved_context"].hits == 0
    assert stats["resolved_context"].writes == 2
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=2, positions=2, cash=2)


def test_resolve_stateful_context_with_lotus_core_evicts_oldest_cache_entry(
    monkeypatch,
):
    from src.core.workspace.models import WorkspaceStatefulInput

    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_STATEFUL_CONTEXT_CACHE_MAX_SIZE", "1")
    request_counter = {"count": 0}
    responses = {
        ("GET", f"{base_url}/portfolios/pf_cache_a"): _FakeResponse(
            {"portfolio_id": "pf_cache_a", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/pf_cache_a/positions"): _FakeResponse(
            {"portfolio_id": "pf_cache_a", "positions": []}
        ),
        ("GET", f"{base_url}/portfolios/pf_cache_b"): _FakeResponse(
            {"portfolio_id": "pf_cache_b", "base_currency": "USD"}
        ),
        ("GET", f"{base_url}/portfolios/pf_cache_b/positions"): _FakeResponse(
            {"portfolio_id": "pf_cache_b", "positions": []}
        ),
    }

    class _CountingFakeClient(_FakeClient):
        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
        ) -> _FakeResponse:
            request_counter["count"] += 1
            pf_cache_a_cash_url = (
                f"{base_url}/portfolios/pf_cache_a/cash-balances?as_of_date=2026-03-27"
            )
            pf_cache_b_cash_url = (
                f"{base_url}/portfolios/pf_cache_b/cash-balances?as_of_date=2026-03-27"
            )
            if method.upper() == "GET" and url == pf_cache_a_cash_url:
                return _FakeResponse(
                    {
                        "portfolio_id": "pf_cache_a",
                        "resolved_as_of_date": "2026-03-27",
                        "cash_accounts": [],
                    }
                )
            if method.upper() == "GET" and url == pf_cache_b_cash_url:
                return _FakeResponse(
                    {
                        "portfolio_id": "pf_cache_b",
                        "resolved_as_of_date": "2026-03-27",
                        "cash_accounts": [],
                    }
                )
            return super().request(method, url, json=json)

    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _CountingFakeClient(responses),
    )

    first = WorkspaceStatefulInput(portfolio_id="pf_cache_a", as_of="2026-03-27")
    second = WorkspaceStatefulInput(portfolio_id="pf_cache_b", as_of="2026-03-27")

    resolve_stateful_context_with_lotus_core(first)
    resolve_stateful_context_with_lotus_core(second)
    resolve_stateful_context_with_lotus_core(first)

    assert request_counter["count"] == 12


def test_resolve_stateful_context_with_lotus_core_does_not_cache_failures(
    monkeypatch, stateful_input
):
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    request_counter = {"count": 0}
    responses = {
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "base_currency": ""}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/positions"): _FakeResponse(
            {"portfolio_id": "DEMO_ADV_USD_001", "positions": []}
        ),
        ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001/cash-balances"): _FakeResponse(
            {
                "portfolio_id": "DEMO_ADV_USD_001",
                "resolved_as_of_date": "2026-03-27",
                "cash_accounts": [],
            }
        ),
    }

    class _CountingFakeClient(_FakeClient):
        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
        ) -> _FakeResponse:
            request_counter["count"] += 1
            return super().request(method, url, json=json)

    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _CountingFakeClient(responses),
    )

    with pytest.raises(LotusCoreStatefulContextUnavailableError):
        resolve_stateful_context_with_lotus_core(stateful_input)
    with pytest.raises(LotusCoreStatefulContextUnavailableError):
        resolve_stateful_context_with_lotus_core(stateful_input)

    assert request_counter["count"] == 8


def test_resolve_stateful_context_with_lotus_core_recovers_after_failed_resolution(
    monkeypatch, stateful_input
):
    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    request_counter = {"count": 0}
    portfolio_payload = {"portfolio_id": "OTHER_PORTFOLIO", "base_currency": "USD"}

    class _RecoveringFakeClient:
        def __enter__(self) -> "_RecoveringFakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
        ) -> _FakeResponse:
            request_counter["count"] += 1
            if (method.upper(), url) == ("GET", f"{base_url}/portfolios/DEMO_ADV_USD_001"):
                return _FakeResponse(dict(portfolio_payload))
            if method.upper() == "GET" and url in {
                f"{base_url}/portfolios/DEMO_ADV_USD_001/positions",
                (
                    f"{base_url}"
                    f"{_positions_path(portfolio_id='DEMO_ADV_USD_001', as_of='2026-03-27')}"
                ),
            }:
                return _FakeResponse({"portfolio_id": "DEMO_ADV_USD_001", "positions": []})
            cash_url = (
                f"{base_url}"
                f"{_cash_balances_path(portfolio_id='DEMO_ADV_USD_001', as_of='2026-03-27')}"
            )
            if method.upper() == "GET" and url == cash_url:
                return _FakeResponse(
                    {
                        "portfolio_id": "DEMO_ADV_USD_001",
                        "resolved_as_of_date": "2026-03-27",
                        "cash_accounts": [],
                    }
                )
            raise AssertionError(f"unexpected request: {(method.upper(), url)} body={json}")

    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _RecoveringFakeClient(),
    )

    with pytest.raises(LotusCoreStatefulContextUnavailableError):
        resolve_stateful_context_with_lotus_core(stateful_input)

    portfolio_payload["portfolio_id"] = "DEMO_ADV_USD_001"
    recovered = resolve_stateful_context_with_lotus_core(stateful_input)

    assert recovered.resolved_context.portfolio_id == "DEMO_ADV_USD_001"
    assert request_counter["count"] == 8
    stats = get_stateful_context_cache_stats_for_tests()
    assert stats["resolved_context"].misses == 2
    assert stats["resolved_context"].expirations == 0
    assert stats["resolved_context"].writes == 1
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert_core_context_fetch_counts(fetch_stats, portfolio=2, positions=2, cash=2)


def test_enrich_stateful_simulate_request_for_trade_drafts_adds_missing_trade_inputs(
    monkeypatch,
):
    from src.core.models import ProposalSimulateRequest

    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    simulate_request = ProposalSimulateRequest.model_validate(
        {
            "portfolio_snapshot": {
                "snapshot_id": "ps_001",
                "portfolio_id": "pf_001",
                "base_currency": "USD",
                "positions": [{"instrument_id": "EQ_OLD", "quantity": "10"}],
                "cash_balances": [{"currency": "USD", "amount": "10000"}],
            },
            "market_data_snapshot": {
                "snapshot_id": "md_001",
                "prices": [{"instrument_id": "EQ_OLD", "price": "100", "currency": "USD"}],
                "fx_rates": [],
            },
            "shelf_entries": [{"instrument_id": "EQ_OLD", "status": "APPROVED"}],
            "options": {"enable_proposal_simulation": True},
            "proposed_cash_flows": [],
            "proposed_trades": [
                {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_NEW_CHF",
                    "quantity": "4",
                }
            ],
        }
    )
    responses = {
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse(
            {
                "records": [
                    {
                        "security_id": "EQ_NEW_CHF",
                        "issuer_id": "ISSUER_EQ_NEW_CHF",
                        "liquidity_tier": "L4",
                        "ultimate_parent_issuer_id": "ULTIMATE_EQ_NEW_CHF",
                        "ultimate_parent_issuer_name": "Issuer Parent AG",
                    }
                ]
            }
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/reference/classification-taxonomy",
        ): _FakeResponse(
            {
                "taxonomy_version": "rfc_062_v1",
                "records": [
                    {
                        "dimension_name": "asset_class",
                        "dimension_value": "Equity",
                    },
                    {
                        "dimension_name": "product_type",
                        "dimension_value": "Equity",
                    },
                ],
            }
        ),
        ("GET", f"{base_url}/instruments/?security_id=EQ_NEW_CHF"): _FakeResponse(
            {
                "total": 1,
                "instruments": [
                    {
                        "security_id": "EQ_NEW_CHF",
                        "currency": "CHF",
                        "asset_class": "Equity",
                        "sector": "Industrials",
                        "country_of_risk": "Switzerland",
                        "product_type": "Equity",
                        "rating": "A",
                    }
                ],
            }
        ),
        ("GET", f"{base_url}/prices/?security_id=EQ_NEW_CHF"): _FakeResponse(
            {
                "security_id": "EQ_NEW_CHF",
                "prices": [
                    {"price_date": "2026-03-24", "price": "49.5", "currency": "CHF"},
                    {"price_date": "2026-03-25", "price": "50.0", "currency": "CHF"},
                ],
            }
        ),
        ("GET", f"{base_url}/fx-rates/?from_currency=CHF&to_currency=USD"): _FakeResponse(
            {
                "from_currency": "CHF",
                "to_currency": "USD",
                "rates": [
                    {"rate_date": "2026-03-25", "rate": "1.10"},
                ],
            }
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    enriched = enrich_stateful_simulate_request_for_trade_drafts(
        simulate_request=simulate_request,
        as_of="2026-03-25",
    )

    assert simulate_request.market_data_snapshot.model_dump(mode="json")["prices"] == [
        {"instrument_id": "EQ_OLD", "price": "100", "currency": "USD"}
    ]
    assert enriched.market_data_snapshot.model_dump(mode="json")["prices"][-1] == {
        "instrument_id": "EQ_NEW_CHF",
        "price": "50.0",
        "currency": "CHF",
    }
    assert enriched.shelf_entries[-1].model_dump(mode="json")["instrument_id"] == "EQ_NEW_CHF"
    assert enriched.shelf_entries[-1].model_dump(mode="json")["issuer_id"] == "ISSUER_EQ_NEW_CHF"
    assert enriched.shelf_entries[-1].model_dump(mode="json")["liquidity_tier"] == "L4"
    assert enriched.shelf_entries[-1].model_dump(mode="json")["attributes"] == {
        "asset_class_source": "lotus_core_classification_taxonomy",
        "classification_taxonomy_version": "rfc_062_v1",
        "country": "Switzerland",
        "product_type": "EQUITY",
        "product_type_source": "lotus_core_classification_taxonomy",
        "rating": "A",
        "sector": "Industrials",
        "source": "LOTUS_CORE_STATEFUL_CONTEXT",
        "ultimate_parent_issuer_id": "ULTIMATE_EQ_NEW_CHF",
        "ultimate_parent_issuer_name": "Issuer Parent AG",
    }
    assert enriched.market_data_snapshot.model_dump(mode="json")["fx_rates"][-1] == {
        "pair": "CHF/USD",
        "rate": "1.10",
    }
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert fetch_stats.instrument_fetches == 3
    assert fetch_stats.price_fetches == 1
    assert fetch_stats.fx_fetches == 1


def test_enrich_stateful_simulate_request_for_trade_drafts_reuses_lookup_cache_stats(
    monkeypatch,
):
    from src.core.models import ProposalSimulateRequest

    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    simulate_request = ProposalSimulateRequest.model_validate(
        {
            "portfolio_snapshot": {
                "snapshot_id": "ps_001",
                "portfolio_id": "pf_001",
                "base_currency": "USD",
                "positions": [],
                "cash_balances": [{"currency": "USD", "amount": "10000"}],
            },
            "market_data_snapshot": {"snapshot_id": "md_001", "prices": [], "fx_rates": []},
            "shelf_entries": [],
            "options": {"enable_proposal_simulation": True},
            "proposed_cash_flows": [],
            "proposed_trades": [
                {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_NEW_CHF",
                    "quantity": "4",
                }
            ],
        }
    )
    request_counter = {"count": 0}
    responses = {
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse(
            {
                "records": [
                    {
                        "security_id": "EQ_NEW_CHF",
                        "issuer_id": "ISSUER_EQ_NEW_CHF",
                        "ultimate_parent_issuer_id": "ULTIMATE_EQ_NEW_CHF",
                        "ultimate_parent_issuer_name": "Issuer Parent AG",
                    }
                ]
            }
        ),
        (
            "POST",
            f"{control_plane_base_url}/integration/reference/classification-taxonomy",
        ): _FakeResponse(
            {
                "taxonomy_version": "rfc_062_v1",
                "records": [
                    {"dimension_name": "asset_class", "dimension_value": "Equity"},
                    {"dimension_name": "product_type", "dimension_value": "Equity"},
                ],
            }
        ),
        ("GET", f"{base_url}/instruments/?security_id=EQ_NEW_CHF"): _FakeResponse(
            {
                "total": 1,
                "instruments": [
                    {
                        "security_id": "EQ_NEW_CHF",
                        "currency": "CHF",
                        "asset_class": "Equity",
                        "sector": "Industrials",
                        "country_of_risk": "Switzerland",
                        "product_type": "Equity",
                        "rating": "A",
                    }
                ],
            }
        ),
        ("GET", f"{base_url}/prices/?security_id=EQ_NEW_CHF"): _FakeResponse(
            {
                "security_id": "EQ_NEW_CHF",
                "prices": [{"price_date": "2026-03-25", "price": "50.0", "currency": "CHF"}],
            }
        ),
        ("GET", f"{base_url}/fx-rates/?from_currency=CHF&to_currency=USD"): _FakeResponse(
            {
                "from_currency": "CHF",
                "to_currency": "USD",
                "rates": [{"rate_date": "2026-03-25", "rate": "1.10"}],
            }
        ),
    }

    class _CountingFakeClient(_FakeClient):
        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
        ) -> _FakeResponse:
            request_counter["count"] += 1
            return super().request(method, url, json=json)

    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _CountingFakeClient(responses),
    )

    enrich_stateful_simulate_request_for_trade_drafts(
        simulate_request=simulate_request,
        as_of="2026-03-25",
    )
    enrich_stateful_simulate_request_for_trade_drafts(
        simulate_request=simulate_request,
        as_of="2026-03-25",
    )

    assert request_counter["count"] == 5
    stats = get_stateful_context_cache_stats_for_tests()
    assert stats["classification_taxonomy"].misses == 1
    assert stats["classification_taxonomy"].hits == 1
    assert stats["instrument_lookup"].misses == 1
    assert stats["instrument_lookup"].hits == 1
    assert stats["price_lookup"].misses == 1
    assert stats["price_lookup"].hits == 1
    assert stats["fx_lookup"].misses == 1
    assert stats["fx_lookup"].hits == 1
    fetch_stats = get_stateful_context_fetch_stats_for_tests()
    assert fetch_stats.instrument_fetches == 3
    assert fetch_stats.price_fetches == 1
    assert fetch_stats.fx_fetches == 1


def test_enrich_stateful_simulate_request_for_trade_drafts_skips_malformed_lookup_rows(
    monkeypatch,
):
    from src.core.models import ProposalSimulateRequest

    base_url = "http://host.docker.internal:8201"
    control_plane_base_url = "http://host.docker.internal:8202"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", control_plane_base_url)
    simulate_request = ProposalSimulateRequest.model_validate(
        {
            "portfolio_snapshot": {
                "snapshot_id": "ps_001",
                "portfolio_id": "pf_001",
                "base_currency": "USD",
                "positions": [],
                "cash_balances": [{"currency": "USD", "amount": "10000"}],
            },
            "market_data_snapshot": {"snapshot_id": "md_001", "prices": [], "fx_rates": []},
            "shelf_entries": [],
            "options": {"enable_proposal_simulation": True},
            "proposed_cash_flows": [],
            "proposed_trades": [
                {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_BAD",
                    "quantity": "2",
                }
            ],
        }
    )
    responses = {
        (
            "POST",
            f"{control_plane_base_url}/integration/instruments/enrichment-bulk",
        ): _FakeResponse({"records": [{"security_id": "EQ_BAD", "issuer_id": "ISSUER_BAD"}]}),
        ("GET", f"{base_url}/instruments/?security_id=EQ_BAD"): _FakeResponse(
            {"total": 1, "instruments": ["not-a-dict"]}
        ),
    }
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: _FakeClient(responses),
    )

    enriched = enrich_stateful_simulate_request_for_trade_drafts(
        simulate_request=simulate_request,
        as_of="2026-03-25",
    )

    assert enriched.model_dump(mode="json") == simulate_request.model_dump(mode="json")


def test_enrich_stateful_simulate_request_for_trade_drafts_avoids_duplicate_entries(
    monkeypatch,
):
    from src.core.models import ProposalSimulateRequest

    base_url = "http://host.docker.internal:8201"
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", base_url)
    simulate_request = ProposalSimulateRequest.model_validate(
        {
            "portfolio_snapshot": {
                "snapshot_id": "ps_001",
                "portfolio_id": "pf_001",
                "base_currency": "USD",
                "positions": [],
                "cash_balances": [{"currency": "USD", "amount": "10000"}],
            },
            "market_data_snapshot": {
                "snapshot_id": "md_001",
                "prices": [{"instrument_id": "EQ_NEW_CHF", "price": "50", "currency": "CHF"}],
                "fx_rates": [{"pair": "CHF/USD", "rate": "1.10"}],
            },
            "shelf_entries": [{"instrument_id": "EQ_NEW_CHF", "status": "APPROVED"}],
            "options": {"enable_proposal_simulation": True},
            "proposed_cash_flows": [],
            "proposed_trades": [
                {
                    "intent_type": "SECURITY_TRADE",
                    "side": "BUY",
                    "instrument_id": "EQ_NEW_CHF",
                    "quantity": "4",
                }
            ],
        }
    )

    enriched = enrich_stateful_simulate_request_for_trade_drafts(
        simulate_request=simulate_request,
        as_of="2026-03-25",
    )

    assert len(enriched.market_data_snapshot.prices) == 1
    assert len(enriched.market_data_snapshot.fx_rates) == 1
    assert len(enriched.shelf_entries) == 1
