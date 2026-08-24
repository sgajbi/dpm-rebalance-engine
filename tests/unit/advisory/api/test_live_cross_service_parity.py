from decimal import Decimal
from typing import Any

import pytest

from scripts.live_policy_evaluation_support import (
    ensure_sg_policy_pack_active,
    request_live_policy_report,
)
from scripts.live_runtime_proposal_alternatives import extract_live_proposal_alternatives_snapshot
from scripts.validate_cross_service_parity_live import (
    PortfolioParityScenario,
    _assert_workspace_flow,
    _build_alternatives_request,
    _canonicalize_allocation_bucket_value,
    _collect_alternative_statuses,
    _json_safe_value,
    _normalize_allocation_views,
    _normalize_risk_payload,
    _security_trade_changes_from_proposal_body,
    _select_changed_state_security,
    _select_cross_currency_changed_state_security,
    _select_non_held_changed_state_security,
)


class _FakePolicyResponse:
    def __init__(self, *, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code, self._payload, self.text = status_code, payload, str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakePolicyClient:
    def __init__(self, response: _FakePolicyResponse) -> None:
        self.response = response

    def post(self, *args: Any, **kwargs: Any) -> _FakePolicyResponse:
        return self.response


def test_live_policy_pack_activation_is_idempotent_when_already_active() -> None:
    posts: list[dict[str, Any]] = []

    ensure_sg_policy_pack_active(
        _FakePolicyClient(_FakePolicyResponse(status_code=200, payload={})),
        advise_base_url="http://advise.dev.lotus",
        get_json=lambda *args, **kwargs: {
            "policy_pack": {"activation_state": "ACTIVE", "content_hash": "sha256:pack"}
        },
        post_json=lambda *args, **kwargs: posts.append(kwargs) or {},
    )

    assert posts == []


def test_live_policy_pack_activation_validates_and_binds_content_hash() -> None:
    posts: list[dict[str, Any]] = []

    ensure_sg_policy_pack_active(
        _FakePolicyClient(_FakePolicyResponse(status_code=200, payload={})),
        advise_base_url="http://advise.dev.lotus",
        get_json=lambda *args, **kwargs: {
            "policy_pack": {"activation_state": "DRAFT", "content_hash": "sha256:pack"}
        },
        post_json=lambda *args, **kwargs: posts.append(kwargs) or {},
    )

    assert [post["url"] for post in posts] == [
        "http://advise.dev.lotus/advisory/policy-packs/SG_PRIVATE_BANKING_REFERENCE/versions/2026.05/validate",
        "http://advise.dev.lotus/advisory/policy-packs/SG_PRIVATE_BANKING_REFERENCE/versions/2026.05/activate",
    ]
    assert posts[1]["json_body"]["source_content_hash"] == "sha256:pack"


@pytest.mark.parametrize(
    ("response", "expected"),
    (
        (
            _FakePolicyResponse(status_code=200, payload={"report": {"status": "READY"}}),
            ("READY", {"report": {"status": "READY"}}, None),
        ),
        (
            _FakePolicyResponse(status_code=503, payload={"detail": "provider unavailable"}),
            ("UNAVAILABLE", None, "provider unavailable"),
        ),
    ),
)
def test_live_policy_report_preserves_ready_and_degraded_outcomes(
    response: _FakePolicyResponse,
    expected: tuple[str, dict[str, Any] | None, str | None],
) -> None:
    def assert_condition(condition: bool, message: str) -> None:
        assert condition, message

    result = request_live_policy_report(
        _FakePolicyClient(response),
        advise_base_url="http://advise.dev.lotus",
        evaluation_id="pev_live_policy_001",
        evaluation_hash="sha256:policy",
        scenario=PortfolioParityScenario(
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            as_of_date="2026-03-25",
            reporting_currency="USD",
            issuer_coverage_status="complete",
            risk_available=True,
        ),
        assert_condition=assert_condition,
    )

    assert result == expected


def test_select_changed_state_security_prefers_highest_weight_non_cash_position() -> None:
    positions = [
        {"security_id": "CASH_USD_BOOK_OPERATING", "asset_class": "Cash", "weight": "0.20"},
        {"security_id": "FO_BOND_LOW", "asset_class": "Fixed Income", "weight": "0.08"},
        {"security_id": "FO_FUND_HIGH", "asset_class": "Fund", "weight": "0.24"},
    ]

    selected = _select_changed_state_security(positions)

    assert selected == "FO_FUND_HIGH"


def test_normalize_risk_payload_compares_business_risk_not_transport_mode() -> None:
    payload = {
        "source_service": "lotus-risk",
        "input_mode": "stateless",
        "risk_proxy": {"hhi_current": "5200.0", "hhi_proposed": 5200.0, "hhi_delta": 0.0},
        "single_position_concentration": {"top_position_weight_current": 0.2},
        "issuer_concentration": {
            "coverage_status": "complete",
            "coverage_ratio_current": "1.0",
        },
        "valuation_context": {"reporting_currency": "USD"},
        "metadata": {"portfolio_id": "PB_SG_GLOBAL_BAL_001", "as_of_date": "2026-05-22"},
    }

    normalized = _normalize_risk_payload(payload)

    assert normalized == {
        "source_service": "lotus-risk",
        "risk_proxy": {
            "hhi_current": Decimal("5200.0"),
            "hhi_proposed": Decimal("5200.0"),
            "hhi_delta": Decimal("0.0"),
        },
        "single_position_concentration": {"top_position_weight_current": Decimal("0.2")},
        "issuer_concentration": {
            "coverage_status": "complete",
            "coverage_ratio_current": Decimal("1.0"),
        },
    }


def test_security_trade_changes_from_proposal_body_preserves_trade_quantities_and_notional() -> (
    None
):
    proposal_body = {
        "intents": [
            {
                "intent_type": "SECURITY_TRADE",
                "intent_id": "oi_1",
                "instrument_id": "FO_BOND_UST_2030",
                "side": "BUY",
                "quantity": "1",
                "notional": {"amount": "101.35", "currency": "USD"},
            },
            {
                "intent_type": "SECURITY_TRADE",
                "intent_id": "oi_2",
                "instrument_id": "FO_BOND_SIEMENS_2031",
                "side": "SELL",
                "quantity": "2",
            },
            {
                "intent_type": "CASH_FLOW",
                "intent_id": "oi_3",
            },
        ]
    }

    changes = _security_trade_changes_from_proposal_body(proposal_body)

    assert changes == [
        {
            "security_id": "FO_BOND_UST_2030",
            "transaction_type": "BUY",
            "quantity": Decimal("1"),
            "amount": Decimal("101.35"),
            "currency": "USD",
            "metadata": {
                "proposal_intent_id": "oi_1",
                "proposal_intent_type": "SECURITY_TRADE",
            },
        },
        {
            "security_id": "FO_BOND_SIEMENS_2031",
            "transaction_type": "SELL",
            "quantity": Decimal("2"),
            "metadata": {
                "proposal_intent_id": "oi_2",
                "proposal_intent_type": "SECURITY_TRADE",
            },
        },
    ]


def test_select_cross_currency_changed_state_security_prefers_highest_weight_non_base_holding() -> (
    None
):
    positions = [
        {"security_id": "FO_USD", "asset_class": "Fund", "currency": "USD", "weight": "0.18"},
        {
            "security_id": "FO_EUR_LOW",
            "asset_class": "Bond",
            "currency": "EUR",
            "weight": "0.04",
        },
        {
            "security_id": "FO_EUR_HIGH",
            "asset_class": "Equity",
            "currency": "EUR",
            "weight": "0.16",
        },
        {"security_id": "CASH_EUR", "asset_class": "Cash", "currency": "EUR", "weight": "0.20"},
    ]

    selected = _select_cross_currency_changed_state_security(positions, base_currency="USD")

    assert selected == "FO_EUR_HIGH"


def test_select_non_held_changed_state_security_prefers_known_non_held_candidate() -> None:
    positions = [
        {"security_id": "FO_FUND_PIMCO_INC"},
        {"security_id": "FO_FUND_BLK_ALLOC"},
        {"security_id": "FO_BOND_UST_2030"},
    ]

    selected = _select_non_held_changed_state_security(
        positions,
        candidates=("FO_FUND_PIMCO_INC", "SEC_FUND_EM_EQ", "FO_BOND_UST_2030"),
    )

    assert selected == "SEC_FUND_EM_EQ"


def test_extract_live_proposal_alternatives_snapshot_summarizes_ranked_and_rejected_paths() -> None:
    snapshot = extract_live_proposal_alternatives_snapshot(
        {
            "proposal_alternatives": {
                "requested_objectives": ["REDUCE_CONCENTRATION", "RAISE_CASH"],
                "selected_alternative_id": "alt_reduce",
                "alternatives": [
                    {
                        "alternative_id": "alt_reduce",
                        "objective": "REDUCE_CONCENTRATION",
                        "status": "FEASIBLE",
                        "rank": 1,
                        "selected": True,
                        "ranking_projection": {
                            "ranking_reason_codes": [
                                "STATUS_FEASIBLE",
                                "LOWER_TURNOVER_TIEBREAKER",
                            ]
                        },
                    },
                    {
                        "alternative_id": "alt_cash",
                        "objective": "RAISE_CASH",
                        "status": "FEASIBLE_WITH_REVIEW",
                        "rank": 2,
                        "selected": False,
                    },
                ],
                "rejected_candidates": [
                    {"reason_code": "ALTERNATIVE_OBJECTIVE_PENDING_CANONICAL_EVIDENCE"}
                ],
            }
        },
        path_name="alternatives_path",
        latency_ms=321.0,
    )

    assert snapshot.requested_objectives == ("REDUCE_CONCENTRATION", "RAISE_CASH")
    assert snapshot.feasible_count == 1
    assert snapshot.feasible_with_review_count == 1
    assert snapshot.rejected_count == 1
    assert snapshot.selected_alternative_id == "alt_reduce"
    assert snapshot.selected_rank == 1
    assert snapshot.top_ranked_alternative_id == "alt_reduce"
    assert snapshot.top_ranked_objective == "REDUCE_CONCENTRATION"
    assert snapshot.top_ranked_reason_codes == (
        "STATUS_FEASIBLE",
        "LOWER_TURNOVER_TIEBREAKER",
    )
    assert snapshot.rejected_reason_codes == ("ALTERNATIVE_OBJECTIVE_PENDING_CANONICAL_EVIDENCE",)
    assert snapshot.latency_ms == 321.0


def test_extract_live_proposal_alternatives_snapshot_uses_explicit_selected_fallback() -> None:
    snapshot = extract_live_proposal_alternatives_snapshot(
        {
            "proposal_alternatives": {
                "requested_objectives": ["RAISE_CASH"],
                "selected_alternative_id": "alt_cash",
                "alternatives": [
                    {
                        "alternative_id": "alt_cash",
                        "objective": "RAISE_CASH",
                        "status": "FEASIBLE",
                        "rank": 1,
                        "selected": False,
                    },
                    "ignored malformed alternative",
                ],
                "rejected_candidates": [
                    {"reason_code": "UNSUPPORTED_OBJECTIVE"},
                    {"reason_code": ""},
                    "ignored malformed rejection",
                ],
            }
        },
        path_name="alternatives_path",
        latency_ms=42.0,
    )

    assert snapshot.selected_alternative_id == "alt_cash"
    assert snapshot.selected_rank is None
    assert snapshot.top_ranked_alternative_id == "alt_cash"
    assert snapshot.top_ranked_objective == "RAISE_CASH"
    assert snapshot.top_ranked_reason_codes == ()
    assert snapshot.rejected_reason_codes == ("UNSUPPORTED_OBJECTIVE",)


def test_extract_live_proposal_alternatives_snapshot_requires_payload() -> None:
    with pytest.raises(ValueError, match="proposal_alternatives missing"):
        extract_live_proposal_alternatives_snapshot(
            {},
            path_name="alternatives_path",
            latency_ms=10.0,
        )


def test_extract_live_proposal_alternatives_snapshot_requires_nested_lists() -> None:
    with pytest.raises(ValueError, match="alternatives missing from proposal_alternatives"):
        extract_live_proposal_alternatives_snapshot(
            {
                "proposal_alternatives": {
                    "requested_objectives": ["RAISE_CASH"],
                    "alternatives": None,
                    "rejected_candidates": [],
                }
            },
            path_name="alternatives_path",
            latency_ms=10.0,
        )


def test_normalize_allocation_views_canonicalizes_bucket_labels() -> None:
    direct = [
        {
            "dimension": "asset_class",
            "total_market_value_reporting_currency": "100.0",
            "buckets": [
                {
                    "dimension_value": "Fixed Income",
                    "market_value_reporting_currency": "40.0",
                    "weight": "0.4",
                    "position_count": 1,
                }
            ],
        }
    ]
    proposal = [
        {
            "dimension": "asset_class",
            "total_value": {"amount": "100.0", "currency": "USD"},
            "buckets": [
                {
                    "key": "Fixed_Income",
                    "value": {"amount": "40.0", "currency": "USD"},
                    "weight": "0.4",
                    "position_count": 1,
                }
            ],
        }
    ]

    assert _canonicalize_allocation_bucket_value("Fixed Income") == "FIXED_INCOME"
    assert _canonicalize_allocation_bucket_value("Fixed_Income") == "FIXED_INCOME"
    assert _normalize_allocation_views(direct) == _normalize_allocation_views(proposal)


def test_build_alternatives_request_uses_current_objectives_contract() -> None:
    request = _build_alternatives_request(
        objectives=["REDUCE_CONCENTRATION", "RAISE_CASH"],
        max_alternatives=2,
        constraints={"cash_floor": {"amount": "25000", "currency": "USD"}},
    )

    assert request == {
        "objectives": ["REDUCE_CONCENTRATION", "RAISE_CASH"],
        "max_alternatives": 2,
        "constraints": {"cash_floor": {"amount": "25000", "currency": "USD"}},
    }


def test_collect_alternative_statuses_groups_statuses_by_objective() -> None:
    proposal_body = {
        "proposal_alternatives": {
            "alternatives": [
                {"objective": "REDUCE_CONCENTRATION", "status": "REJECTED_POLICY_BLOCKED"},
                {"objective": "REDUCE_CONCENTRATION", "status": "REJECTED_POLICY_BLOCKED"},
                {"objective": "IMPROVE_CURRENCY_ALIGNMENT", "status": "FEASIBLE_WITH_REVIEW"},
            ]
        }
    }

    assert _collect_alternative_statuses(proposal_body) == {
        "REDUCE_CONCENTRATION": {"REJECTED_POLICY_BLOCKED"},
        "IMPROVE_CURRENCY_ALIGNMENT": {"FEASIBLE_WITH_REVIEW"},
    }


def test_json_safe_value_serializes_decimals_for_http_payloads() -> None:
    payload = [
        {
            "security_id": "FO_BOND_UST_2030",
            "quantity": Decimal("1"),
            "amount": Decimal("101.35"),
            "metadata": {"proposal_intent_id": "oi_1"},
        }
    ]

    assert _json_safe_value(payload) == [
        {
            "security_id": "FO_BOND_UST_2030",
            "quantity": "1",
            "amount": "101.35",
            "metadata": {"proposal_intent_id": "oi_1"},
        }
    ]


def test_assert_workspace_flow_proves_rationale_replacement_lineage(monkeypatch) -> None:
    workspace_id = "aws_live_workspace"
    workspace_version_id = "awv_live_version"
    proposal_id = "ap_live_proposal"
    first_run_id = "packrun_workspace_rationale_req_001"
    replacement_run_id = "packrun_workspace_rationale_req_002"
    posts: list[tuple[str, dict[str, Any]]] = []

    def _fake_post_json(client, *, url, expected_status, json_body, headers=None):  # noqa: ANN001
        assert expected_status in {200, 201}
        posts.append((url, json_body))
        if url.endswith("/advisory/workspaces"):
            return {
                "workspace": {
                    "workspace_id": workspace_id,
                    "resolved_context": {"portfolio_id": "PB_SG_GLOBAL_BAL_001"},
                }
            }
        if url.endswith(f"/advisory/workspaces/{workspace_id}/evaluate"):
            return {
                "latest_proposal_result": {
                    "explanation": {
                        "authority_resolution": {
                            "simulation_authority": "lotus_core",
                            "risk_authority": "lotus_risk",
                            "degraded": False,
                        }
                    }
                }
            }
        if url.endswith(f"/advisory/workspaces/{workspace_id}/save"):
            return {
                "saved_version": {
                    "workspace_version_id": workspace_version_id,
                    "replay_evidence": {"risk_lens": {"source_service": "lotus-risk"}},
                }
            }
        if url.endswith(f"/advisory/workspaces/{workspace_id}/handoff"):
            return {
                "handoff_action": "CREATED_PROPOSAL",
                "proposal": {
                    "proposal": {"proposal_id": proposal_id},
                    "version": {
                        "version_no": 1,
                        "proposal_result": {
                            "explanation": {
                                "authority_resolution": {
                                    "simulation_authority": "lotus_core",
                                    "risk_authority": "lotus_risk",
                                    "degraded": False,
                                }
                            }
                        },
                    },
                },
            }
        if url.endswith(f"/advisory/workspaces/{workspace_id}/assistant/rationale"):
            instruction = json_body["instruction"]
            current_run_id = (
                first_run_id
                if instruction == "Summarize the evaluated workspace rationale for review."
                else replacement_run_id
            )
            return {
                "generated_by": "lotus-ai",
                "assistant_output": "Evidence grounded rationale.",
                "evidence": {"workspace_id": workspace_id, "proposal_status": "READY"},
                "workflow_pack_run": {
                    "run_id": current_run_id,
                    "runtime_state": "COMPLETED",
                    "review_state": "AWAITING_REVIEW",
                    "supportability_status": "ACTION_REQUIRED",
                    "workflow_authority_owner": "lotus-advise",
                    "allowed_review_actions": ["ACCEPT", "REJECT", "REVISE", "SUPERSEDE"],
                },
            }
        if url.endswith(f"/advisory/workspaces/{workspace_id}/assistant/rationale/review-actions"):
            return {
                "workflow_pack_run": {
                    "run_id": first_run_id,
                    "runtime_state": "COMPLETED",
                    "review_state": "SUPERSEDED",
                    "supportability_status": "HISTORICAL",
                    "workflow_authority_owner": "lotus-advise",
                    "allowed_review_actions": [],
                    "superseded": True,
                    "replacement_run_id": replacement_run_id,
                },
                "summary": ["Run superseded in favor of replacement lineage."],
            }
        raise AssertionError(f"unexpected POST url: {url}")

    def _fake_request_json(
        client,
        *,
        method,
        url,
        expected_status,
        json_body=None,
        headers=None,  # noqa: ANN001
    ):
        assert method == "GET"
        assert expected_status == 200
        if url.endswith(
            f"/advisory/workspaces/{workspace_id}/saved-versions/"
            f"{workspace_version_id}/replay-evidence"
        ):
            return {
                "evidence": {"risk_lens": {"source_service": "lotus-risk"}},
                "subject": {"proposal_id": proposal_id},
                "continuity": {},
                "hashes": {"evaluation_request_hash": "hash_live"},
            }
        if url.endswith(f"/advisory/proposals/{proposal_id}/versions/1/replay-evidence"):
            return {
                "evidence": {"risk_lens": {"source_service": "lotus-risk"}},
                "subject": {"proposal_version_no": 1},
                "continuity": {"workspace_version_id": workspace_version_id},
                "hashes": {"evaluation_request_hash": "hash_live"},
            }
        raise AssertionError(f"unexpected GET url: {url}")

    monkeypatch.setattr(
        "scripts.validate_cross_service_parity_live._post_json",
        _fake_post_json,
    )
    monkeypatch.setattr(
        "scripts.validate_cross_service_parity_live._request_json",
        _fake_request_json,
    )

    result = _assert_workspace_flow(
        object(),
        advise_base_url="http://advise.dev.lotus",
        scenario=PortfolioParityScenario(
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            as_of_date="2026-03-25",
            reporting_currency="USD",
            issuer_coverage_status="complete",
            risk_available=True,
        ),
    )

    assert result == (
        first_run_id,
        replacement_run_id,
        "SUPERSEDED",
        "HISTORICAL",
    )
    assert posts[-1][1]["replacement_run_id"] == replacement_run_id
