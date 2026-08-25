from scripts import validate_cross_service_parity_live as parity


def test_live_parity_configuration_prefers_explicit_values_and_normalizes_urls() -> None:
    configuration = parity._resolve_live_parity_configuration(
        advise_base_url="http://explicit-advise///",
        core_query_base_url=None,
        core_control_base_url=None,
        risk_base_url=None,
        candidate_portfolios=None,
        environ={
            "LOTUS_ADVISE_BASE_URL": "http://environment-advise/",
            "LOTUS_CORE_QUERY_BASE_URL": "http://environment-query///",
            "LOTUS_CORE_BASE_URL": "http://environment-control/",
            "LOTUS_RISK_BASE_URL": "http://environment-risk///",
            "LOTUS_PARITY_PORTFOLIOS": " complete , , degraded ",
        },
    )

    assert configuration.advise_base_url == "http://explicit-advise"
    assert configuration.core_query_base_url == "http://environment-query"
    assert configuration.core_control_base_url == "http://environment-control"
    assert configuration.risk_base_url == "http://environment-risk"
    assert configuration.candidate_portfolios == ("complete", "degraded")


def test_changed_state_workspace_parity_checks_each_selected_security(
    monkeypatch,
) -> None:
    scenario = parity.PortfolioParityScenario(
        portfolio_id="PORTFOLIO",
        as_of_date="2026-04-10",
        reporting_currency="USD",
        issuer_coverage_status="complete",
        risk_available=True,
    )
    positions = [
        {"asset_class": "equity", "security_id": "CHANGED", "currency": "USD", "weight": "0.9"},
        {"asset_class": "equity", "security_id": "CROSS", "currency": "EUR", "weight": "0.5"},
    ]
    risk_calls: list[str | None] = []
    allocation_calls: list[str] = []

    monkeypatch.setattr(parity, "_query_live_positions", lambda *args, **kwargs: positions)

    def record_risk_check(*args, **kwargs) -> str:
        security_id = kwargs.get("security_id")
        risk_calls.append(security_id)
        return security_id or "CHANGED"

    def record_allocation_check(*args, **kwargs) -> None:
        allocation_calls.append(kwargs["security_id"])

    monkeypatch.setattr(parity, "_assert_changed_state_workspace_risk_parity", record_risk_check)
    monkeypatch.setattr(
        parity,
        "_assert_changed_state_workspace_allocation_parity",
        record_allocation_check,
    )

    result = parity._validate_changed_state_workspace_parity(
        object(),
        advise_base_url="http://advise",
        core_query_base_url="http://core-query",
        core_control_base_url="http://core-control",
        risk_base_url="http://risk",
        scenario=scenario,
    )

    assert result == ("CHANGED", "CROSS", "SEC_FUND_EM_EQ")
    assert risk_calls == [None, "CROSS", "SEC_FUND_EM_EQ"]
    assert allocation_calls == ["CHANGED", "CROSS", "SEC_FUND_EM_EQ"]
