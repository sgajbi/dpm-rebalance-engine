from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import live_memo_flow as memo_flow
from scripts import live_narrative_flow as narrative_flow
from scripts import live_policy_evaluation_flow as policy_flow
from scripts import validate_cross_service_parity_live as parity
from scripts.live_parity_orchestration import run_live_parity
from scripts.live_report_delivery import ReportDeliveryPrimitives, assert_report_delivery


def test_policy_flow_adapter_supplies_typed_primitives(monkeypatch) -> None:
    scenario = parity.PortfolioParityScenario("PORTFOLIO", "2026-04-10", "USD", "complete", True)
    captured: dict[str, object] = {}
    expected_snapshot = object()

    def record_policy_flow(*args, **kwargs):
        captured["primitives"] = kwargs["primitives"]
        return expected_snapshot

    monkeypatch.setattr(parity, "assert_live_policy_evaluation", record_policy_flow)

    result = parity._assert_live_policy_evaluation_flow(
        object(),
        advise_base_url="http://advise",
        scenario=scenario,
    )

    primitives = captured["primitives"]
    assert result is expected_snapshot
    assert isinstance(primitives, policy_flow.LivePolicyEvaluationPrimitives)
    assert primitives.assertion is parity._assert
    assert primitives.get_json is parity._get_json
    assert primitives.post_json is parity._post_json


def test_policy_flow_preserves_phase_order_and_snapshot_projection(monkeypatch) -> None:
    scenario = parity.PortfolioParityScenario("PORTFOLIO", "2026-04-10", "USD", "complete", True)
    calls: list[str] = []
    expected_snapshot = object()
    primitives = policy_flow.LivePolicyEvaluationPrimitives(
        assertion=lambda *_args: None,
        get_json=lambda *_args, **_kwargs: {},
        post_json=lambda *_args, **_kwargs: {},
        ensure_policy_pack_active=lambda *_args, **_kwargs: None,
        policy_evidence_bundle=lambda **_kwargs: {},
        request_policy_report=lambda *_args, **_kwargs: ("READY", {}, None),
        extract_snapshot=lambda **_kwargs: expected_snapshot,
    )

    monkeypatch.setattr(
        policy_flow,
        "_create_live_policy_evaluation",
        lambda *_args, **_kwargs: (
            calls.append("create"),
            (
                {"created": True},
                {"source_evidence_hash": "source", "policy_content_hash": "policy"},
                "evaluation",
                "hash",
            ),
        )[1],
    )
    monkeypatch.setattr(
        policy_flow,
        "_assert_live_policy_read_surfaces",
        lambda *_args, **_kwargs: (calls.append("read"), ({}, {}, {}))[1],
    )
    monkeypatch.setattr(
        policy_flow,
        "_assert_live_policy_pre_sign_off_guards",
        lambda *_args, **_kwargs: (calls.append("guards"), ("STALE", "CLIENT_READY"))[1],
    )
    monkeypatch.setattr(
        policy_flow,
        "_sign_off_live_policy_evaluation",
        lambda *_args, **_kwargs: (calls.append("sign_off"), {})[1],
    )
    monkeypatch.setattr(
        policy_flow,
        "_request_live_policy_ai_evidence",
        lambda *_args, **_kwargs: (calls.append("ai"), ("FORBIDDEN", {}))[1],
    )
    monkeypatch.setattr(
        policy_flow,
        "_assert_live_policy_lineage_and_replay",
        lambda *_args, **_kwargs: (calls.append("lineage"), ({}, {}))[1],
    )

    result = policy_flow.assert_live_policy_evaluation(
        object(),
        primitives=primitives,
        advise_base_url="http://advise",
        scenario=scenario,
    )

    assert result is expected_snapshot
    assert calls == ["create", "read", "guards", "sign_off", "ai", "lineage"]


def test_narrative_flow_adapter_supplies_typed_primitives(monkeypatch) -> None:
    scenario = parity.PortfolioParityScenario("PORTFOLIO", "2026-04-10", "USD", "complete", True)
    captured: dict[str, object] = {}
    expected_snapshot = object()

    def record_narrative_flow(*args, **kwargs):
        captured["primitives"] = kwargs["primitives"]
        return expected_snapshot

    monkeypatch.setattr(parity, "assert_live_proposal_narrative_flow", record_narrative_flow)

    result = parity._assert_live_proposal_narrative_flow(
        object(),
        advise_base_url="http://advise",
        scenario=scenario,
    )

    primitives = captured["primitives"]
    assert result is expected_snapshot
    assert isinstance(primitives, narrative_flow.LiveNarrativeFlowPrimitives)
    assert primitives.assertion is parity._assert
    assert primitives.get_json is parity._get_json
    assert primitives.post_json is parity._post_json
    assert primitives.create_stateful_proposal is parity._create_stateful_proposal


def test_narrative_ai_assistance_is_skipped_without_explicit_opt_in(monkeypatch) -> None:
    scenario = parity.PortfolioParityScenario("PORTFOLIO", "2026-04-10", "USD", "complete", True)
    primitives = narrative_flow.LiveNarrativeFlowPrimitives(
        create_stateful_proposal=MagicMock(),
        get_json=MagicMock(),
        post_json=MagicMock(),
        feature_by_key=MagicMock(),
        assertion=MagicMock(),
        extract_snapshot=MagicMock(),
        extract_ai_lineage_status=MagicMock(),
    )
    monkeypatch.delenv("LOTUS_ADVISE_VALIDATE_AI_ASSISTED_NARRATIVE", raising=False)

    result = narrative_flow._assert_ai_assisted_narrative_when_enabled(
        object(),
        primitives=primitives,
        advise_base_url="http://advise",
        scenario=scenario,
    )

    assert result == ("SKIPPED_NOT_ENABLED", None)
    primitives.create_stateful_proposal.assert_not_called()


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
    complete = parity.PortfolioParityScenario("COMPLETE", "2026-04-10", "USD", "complete", True)
    degraded = parity.PortfolioParityScenario("DEGRADED", "2026-04-10", "USD", "partial", False)
    calls: list[str] = []
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    monkeypatch.setattr(
        parity,
        "httpx",
        SimpleNamespace(Client=MagicMock(return_value=client), Timeout=MagicMock()),
    )

    def record(name: str, result=None):
        return MagicMock(side_effect=lambda *_args, **_kwargs: (calls.append(name), result)[1])

    steps = {
        "_select_scenarios": ("select", (complete, degraded)),
        "_validate_live_scenario_parity": ("scenarios", None),
        "_measure_warm_cache": ("warm_cache", (10.0, 2.0)),
        "_validate_live_decision_paths": ("decision", ("READY", "REVIEW", "BLOCKED")),
        "_validate_live_proposal_alternatives_paths": (
            "alternatives",
            ("NOOP", "CONCENTRATION", "CASH", "CURRENCY", "RESTRICTED"),
        ),
        "_assert_lifecycle_and_delivery_flow": (
            "lifecycle",
            ("COMPLETE", 2, "APPROVED", "HANDED_OFF", "REPORT_READY"),
        ),
        "_assert_live_proposal_narrative_flow": ("narrative", "NARRATIVE"),
        "_assert_live_proposal_memo_flow": ("memo", "MEMO"),
        "_assert_live_policy_evaluation_flow": ("policy", "POLICY"),
        "_assert_async_lifecycle_read_surfaces": ("async_lifecycle", ("COMPLETE", 2, "APPROVED")),
        "_assert_new_version_requires_fresh_approvals": ("fresh_approvals", None),
        "_assert_mixed_approval_routes_remain_version_scoped": ("version_scoped_approvals", None),
        "_assert_workspace_flow": ("workspace", ("RUN-1", "RUN-2", "REVIEW", "READY")),
        "_validate_changed_state_workspace_parity": (
            "changed_state",
            ("CHANGED", "CROSS", "NON_HELD"),
        ),
    }
    for attribute, (name, result) in steps.items():
        monkeypatch.setattr(parity, attribute, record(name, result))

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


def test_lifecycle_delivery_flow_preserves_phase_order_and_result(monkeypatch) -> None:
    scenario = parity.PortfolioParityScenario("PORTFOLIO", "2026-04-10", "USD", "complete", True)
    calls: list[str] = []

    monkeypatch.setattr(
        parity,
        "_assert_synchronous_lifecycle_flow",
        lambda *_args, **_kwargs: (calls.append("sync"), ("PROPOSAL", 2))[1],
    )
    monkeypatch.setattr(
        parity,
        "_assert_asynchronous_lifecycle_flow",
        lambda *_args, **_kwargs: calls.append("async"),
    )
    monkeypatch.setattr(
        parity,
        "_assert_execution_flow",
        lambda *_args, **_kwargs: (calls.append("execution"), {"handoff_status": "EXECUTED"})[1],
    )
    monkeypatch.setattr(
        parity,
        "assert_report_delivery",
        lambda *_args, **_kwargs: (calls.append("report"), "READY")[1],
    )

    result = parity._assert_lifecycle_and_delivery_flow(
        object(),
        advise_base_url="http://advise",
        scenario=scenario,
    )

    assert calls == ["sync", "async", "execution", "report"]
    assert result == ("PORTFOLIO", 2, "EXECUTED", "EXECUTED", "READY")


@pytest.mark.parametrize(
    ("operational_ready", "status_code", "response_body", "expected_status"),
    [
        (True, 200, {"report_service": "lotus-report", "status": "READY"}, "READY"),
        (False, 503, {"detail": "LOTUS_REPORT_REQUEST_UNAVAILABLE"}, "UNAVAILABLE"),
    ],
)
def test_report_delivery_preserves_ready_and_degraded_outcomes(
    monkeypatch,
    operational_ready: bool,
    status_code: int,
    response_body: dict[str, str],
    expected_status: str,
) -> None:
    response = MagicMock(status_code=status_code, text="report response")
    response.json.return_value = response_body
    client = MagicMock()
    client.post.return_value = response
    persisted_statuses: list[str] = []
    scenario = parity.PortfolioParityScenario("PORTFOLIO", "2026-04-10", "USD", "complete", True)

    monkeypatch.setattr(parity, "_get_json", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        parity,
        "_feature_by_key",
        lambda *_args, **_kwargs: {"operational_ready": operational_ready},
    )
    monkeypatch.setattr(
        parity,
        "_assert_persisted_read_surfaces",
        lambda *_args, **kwargs: persisted_statuses.append(kwargs["expected_report_status"]),
    )

    result = assert_report_delivery(
        client,
        primitives=ReportDeliveryPrimitives(
            get_json=parity._get_json,
            feature_by_key=parity._feature_by_key,
            assertion=parity._assert,
            assert_persisted_read_surfaces=parity._assert_persisted_read_surfaces,
        ),
        advise_base_url="http://advise",
        proposal_id="PROPOSAL",
        related_version_no=2,
        expected_portfolio_id=scenario.portfolio_id,
    )

    assert result == expected_status
    assert persisted_statuses == [expected_status]
    assert client.post.call_args.kwargs["json"]["related_version_no"] == 2


def test_live_memo_flow_preserves_phase_order_and_snapshot_assembly(monkeypatch) -> None:
    calls: list[str] = []
    artifact = memo_flow._MemoArtifact("PROPOSAL", 2, {}, "sha256:memo", {})
    review = memo_flow._MemoReviewEvidence({}, "STALE_HASH", "CLIENT_RELEASE")
    report = memo_flow._MemoReportEvidence("READY", {}, None, "CLIENT_DOCUMENT")

    def phase(name, value):
        return lambda *_args, **_kwargs: (calls.append(name), value)[1]

    for name, value in {
        "_create_memo_artifact": ("create", artifact),
        "_assert_memo_review_controls": ("review", review),
        "_assert_memo_report_package": ("report", report),
        "_assert_memo_ai_and_replay": ("runtime", memo_flow._MemoRuntimeEvidence({}, {}, {})),
    }.items():
        monkeypatch.setattr(memo_flow, name, phase(*value))

    def extract_snapshot(**kwargs):
        calls.append("extract")
        assert (kwargs["proposal_id"], kwargs["version_no"]) == ("PROPOSAL", 2)
        assert kwargs["report_status"] == "READY"
        assert kwargs["stale_hash_block_status"] == "STALE_HASH"
        assert kwargs["client_ready_document_block_status"] == "CLIENT_DOCUMENT"
        return "SNAPSHOT"

    primitives = memo_flow.LiveMemoFlowPrimitives(
        *(MagicMock() for _ in range(4)), extract_snapshot=extract_snapshot
    )
    result = memo_flow.assert_live_memo_flow(
        object(), primitives=primitives, advise_base_url="http://advise", scenario=object()
    )

    assert calls == ["create", "review", "report", "runtime", "extract"] and result == "SNAPSHOT"
