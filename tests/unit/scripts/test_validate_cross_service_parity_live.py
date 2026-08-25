from types import SimpleNamespace

from scripts import validate_cross_service_parity_live as parity
from scripts.live_parity_orchestration import run_live_parity


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


def test_live_parity_orchestration_preserves_order_and_result_assembly(monkeypatch) -> None:
    complete = parity.PortfolioParityScenario(
        portfolio_id="COMPLETE",
        as_of_date="2026-04-10",
        reporting_currency="USD",
        issuer_coverage_status="complete",
        risk_available=True,
    )
    degraded = parity.PortfolioParityScenario(
        portfolio_id="DEGRADED",
        as_of_date="2026-04-10",
        reporting_currency="USD",
        issuer_coverage_status="partial",
        risk_available=False,
    )
    calls: list[str] = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(
        parity,
        "httpx",
        SimpleNamespace(
            Client=lambda **_kwargs: FakeClient(),
            Timeout=lambda _seconds: object(),
        ),
    )

    def record(name: str, result=None):
        def _record(*_args, **_kwargs):
            calls.append(name)
            return result

        return _record

    monkeypatch.setattr(parity, "_select_scenarios", record("select", (complete, degraded)))
    monkeypatch.setattr(parity, "_validate_live_scenario_parity", record("scenarios"))
    monkeypatch.setattr(parity, "_measure_warm_cache", record("warm_cache", (10.0, 2.0)))
    monkeypatch.setattr(
        parity,
        "_validate_live_decision_paths",
        record("decision", ("READY", "REVIEW", "BLOCKED")),
    )
    monkeypatch.setattr(
        parity,
        "_validate_live_proposal_alternatives_paths",
        record("alternatives", ("NOOP", "CONCENTRATION", "CASH", "CURRENCY", "RESTRICTED")),
    )
    monkeypatch.setattr(
        parity,
        "_assert_lifecycle_and_delivery_flow",
        record("lifecycle", ("COMPLETE", 2, "APPROVED", "HANDED_OFF", "REPORT_READY")),
    )
    monkeypatch.setattr(
        parity, "_assert_live_proposal_narrative_flow", record("narrative", "NARRATIVE")
    )
    monkeypatch.setattr(parity, "_assert_live_proposal_memo_flow", record("memo", "MEMO"))
    monkeypatch.setattr(parity, "_assert_live_policy_evaluation_flow", record("policy", "POLICY"))
    monkeypatch.setattr(
        parity,
        "_assert_async_lifecycle_read_surfaces",
        record("async_lifecycle", ("COMPLETE", 2, "APPROVED")),
    )
    monkeypatch.setattr(
        parity,
        "_assert_new_version_requires_fresh_approvals",
        record("fresh_approvals"),
    )
    monkeypatch.setattr(
        parity,
        "_assert_mixed_approval_routes_remain_version_scoped",
        record("version_scoped_approvals"),
    )
    monkeypatch.setattr(
        parity,
        "_assert_workspace_flow",
        record("workspace", ("RUN-1", "RUN-2", "REVIEW", "READY")),
    )
    monkeypatch.setattr(
        parity,
        "_validate_changed_state_workspace_parity",
        record("changed_state", ("CHANGED", "CROSS", "NON_HELD")),
    )

    result = run_live_parity(
        parity,
        advise_base_url="http://advise",
        core_query_base_url="http://core-query",
        core_control_base_url="http://core-control",
        risk_base_url="http://risk",
        candidate_portfolios=("COMPLETE", "DEGRADED"),
    )

    assert calls == [
        "select",
        "scenarios",
        "warm_cache",
        "decision",
        "alternatives",
        "lifecycle",
        "narrative",
        "memo",
        "policy",
        "async_lifecycle",
        "fresh_approvals",
        "version_scoped_approvals",
        "workspace",
        "changed_state",
    ]
    assert result.complete_issuer_portfolio == "COMPLETE"
    assert result.degraded_issuer_portfolio == "DEGRADED"
    assert result.changed_state_security_id == "CHANGED"
    assert result.cross_currency_security_id == "CROSS"
    assert result.non_held_security_id == "NON_HELD"
    assert result.proposal_memo == "MEMO"
    assert result.proposal_policy == "POLICY"
