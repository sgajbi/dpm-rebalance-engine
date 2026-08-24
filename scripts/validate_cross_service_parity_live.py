from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from numbers import Real
from pathlib import Path
from typing import Any, Literal, cast

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.live_policy_evaluation_support import (  # noqa: E402
    ensure_sg_policy_pack_active,
    live_policy_evidence_bundle,
    request_live_policy_report,
)
from scripts.live_runtime_decision_summary import (  # noqa: E402
    LiveDecisionSnapshot,
    extract_live_decision_snapshot,
)
from scripts.live_runtime_policy_evaluation import (  # noqa: E402
    LivePolicyEvaluationSnapshot,
    extract_live_policy_evaluation_snapshot,
)
from scripts.live_runtime_proposal_alternatives import (  # noqa: E402
    LiveProposalAlternativesSnapshot,
    extract_live_proposal_alternatives_snapshot,
)
from scripts.live_runtime_proposal_memo import (  # noqa: E402
    LiveProposalMemoSnapshot,
    extract_live_memo_snapshot,
)
from scripts.live_runtime_proposal_narrative import (  # noqa: E402
    LiveProposalNarrativeSnapshot,
    extract_ai_lineage_status,
    extract_live_narrative_snapshot,
)
from src.core.common.canonical import hash_canonical_payload
from src.core.models import ProposalSimulateRequest, ProposedTrade

_DEFAULT_ADVISE_BASE_URL = "http://advise.dev.lotus"
_DEFAULT_CORE_QUERY_BASE_URL = "http://core-query.dev.lotus"
_DEFAULT_CORE_CONTROL_BASE_URL = "http://core-control.dev.lotus"
_DEFAULT_RISK_BASE_URL = "http://risk.dev.lotus"
_NON_HELD_CANDIDATES = (
    "SEC_FUND_EM_EQ",
    "FO_EQ_NOVO_NORDISK_DK",
)
_DEFAULT_PORTFOLIO_CANDIDATES = (
    "DEMO_ADV_USD_001",
    "PB_SG_GLOBAL_BAL_001",
    "DEMO_REBAL_USD_001",
    "DEMO_INCOME_CHF_001",
)
_PROPOSAL_ALLOCATION_DIMENSIONS = [
    "asset_class",
    "currency",
    "sector",
    "country",
    "region",
    "product_type",
    "rating",
]
_WARM_CACHE_TOLERANCE_MULTIPLIER = 1.75
_WARM_CACHE_TOLERANCE_ABSOLUTE_MS = 125.0


class LiveParityValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PortfolioParityScenario:
    portfolio_id: str
    as_of_date: str
    reporting_currency: str
    issuer_coverage_status: str
    risk_available: bool


@dataclass(frozen=True)
class LiveParityResult:
    complete_issuer_portfolio: str
    degraded_issuer_portfolio: str
    degraded_issuer_coverage_status: str
    cold_duration_ms: float
    warm_duration_ms: float
    changed_state_portfolio: str
    changed_state_security_id: str
    cross_currency_security_id: str
    non_held_security_id: str
    workspace_handoff_portfolio: str
    workspace_rationale_initial_run_id: str
    workspace_rationale_replacement_run_id: str
    workspace_rationale_review_state: str
    workspace_rationale_supportability_status: str
    lifecycle_portfolio: str
    lifecycle_latest_version_no: int
    lifecycle_current_state: str
    async_lifecycle_portfolio: str
    async_lifecycle_latest_version_no: int
    async_lifecycle_current_state: str
    execution_handoff_status: str
    execution_terminal_status: str
    report_status: str
    proposal_narrative: LiveProposalNarrativeSnapshot
    proposal_memo: LiveProposalMemoSnapshot
    proposal_policy: LivePolicyEvaluationSnapshot
    ready_decision: LiveDecisionSnapshot
    review_decision: LiveDecisionSnapshot
    blocked_decision: LiveDecisionSnapshot
    noop_alternatives: LiveProposalAlternativesSnapshot
    concentration_alternatives: LiveProposalAlternativesSnapshot
    cash_raise_alternatives: LiveProposalAlternativesSnapshot
    cross_currency_alternatives: LiveProposalAlternativesSnapshot
    restricted_product_alternatives: LiveProposalAlternativesSnapshot


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise LiveParityValidationError(message)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _utc_iso_after(*, seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _request_json(
    client: httpx.Client,
    *,
    method: str,
    url: str,
    expected_status: int,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = client.request(method, url, json=json_body, headers=headers)
    _assert(
        response.status_code == expected_status,
        (
            f"{method} {url}: expected HTTP {expected_status}, "
            f"got {response.status_code}, body={response.text}"
        ),
    )
    payload = cast(dict[str, Any], response.json())
    _assert(isinstance(payload, dict), f"{method} {url}: expected JSON object payload")
    return payload


def _extract_live_decision_snapshot(
    *,
    proposal_body: dict[str, Any],
    path_name: str,
) -> LiveDecisionSnapshot:
    try:
        snapshot = extract_live_decision_snapshot(proposal_body, path_name=path_name)
    except ValueError as exc:
        raise LiveParityValidationError(str(exc)) from exc
    _assert(
        bool(snapshot.top_level_status)
        and bool(snapshot.decision_status)
        and bool(snapshot.primary_reason_code)
        and bool(snapshot.recommended_next_action),
        f"{path_name}: decision summary snapshot was incomplete {snapshot}",
    )
    return snapshot


def _canonicalize_allocation_bucket_value(value: Any) -> str:
    return "_".join(str(value).strip().upper().replace("-", " ").split())


def _normalize_allocation_views(views: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for view in views:
        dimension = str(view["dimension"])
        if "total_market_value_reporting_currency" in view:
            total = _decimal(view["total_market_value_reporting_currency"])
            buckets = [
                {
                    "value": _canonicalize_allocation_bucket_value(bucket["dimension_value"]),
                    "market_value": _decimal(bucket["market_value_reporting_currency"]),
                    "weight": _decimal(bucket["weight"]),
                    "position_count": int(bucket["position_count"]),
                }
                for bucket in view["buckets"]
            ]
        else:
            total = _decimal(view["total_value"]["amount"])
            buckets = [
                {
                    "value": _canonicalize_allocation_bucket_value(bucket["key"]),
                    "market_value": _decimal(bucket["value"]["amount"]),
                    "weight": _decimal(bucket["weight"]),
                    "position_count": int(bucket["position_count"]),
                }
                for bucket in view["buckets"]
            ]
        normalized[dimension] = {
            "total": total,
            "buckets": buckets,
        }
    return normalized


def _normalize_risk_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_service": payload["source_service"],
        "risk_proxy": _normalize_risk_numeric_values(dict(payload["risk_proxy"])),
        "single_position_concentration": _normalize_risk_numeric_values(
            dict(payload["single_position_concentration"])
        ),
        "issuer_concentration": _normalize_risk_numeric_values(
            dict(payload["issuer_concentration"])
        ),
    }


def _normalize_risk_numeric_values(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Real | Decimal):
        return _decimal(value)
    if isinstance(value, str):
        try:
            return _decimal(value)
        except ArithmeticError:
            return value
    if isinstance(value, list):
        return [_normalize_risk_numeric_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_risk_numeric_values(item) for key, item in value.items()}
    return value


def _feature_by_key(capabilities: dict[str, Any], key: str) -> dict[str, Any]:
    features = capabilities.get("features")
    _assert(isinstance(features, list), "/platform/capabilities: features must be a list")
    feature_list = cast(list[Any], features)
    for feature in feature_list:
        if isinstance(feature, dict) and feature.get("key") == key:
            return cast(dict[str, Any], feature)
    raise LiveParityValidationError(f"/platform/capabilities: missing feature {key}")


def _resolve_latest_portfolio_context(
    client: httpx.Client,
    *,
    core_query_base_url: str,
    portfolio_id: str,
) -> tuple[str, str]:
    payload = _request_json(
        client,
        method="POST",
        url=f"{core_query_base_url}/reporting/portfolio-summary/query",
        expected_status=200,
        json_body={"portfolio_id": portfolio_id},
    )
    return str(payload["resolved_as_of_date"]), str(payload["reporting_currency"])


def _stateful_noop_request(*, portfolio_id: str, as_of_date: str) -> dict[str, Any]:
    return {
        "input_mode": "stateful",
        "stateful_input": {
            "portfolio_id": portfolio_id,
            "as_of": as_of_date,
        },
    }


def _build_alternatives_request(
    *,
    objectives: list[str],
    max_alternatives: int,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "objectives": objectives,
        "max_alternatives": max_alternatives,
    }
    if constraints:
        request["constraints"] = constraints
    return request


def _simulate_stateful_noop(
    client: httpx.Client,
    *,
    advise_base_url: str,
    portfolio_id: str,
    as_of_date: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _request_json(
        client,
        method="POST",
        url=f"{advise_base_url}/advisory/proposals/simulate",
        expected_status=200,
        json_body=_stateful_noop_request(portfolio_id=portfolio_id, as_of_date=as_of_date),
        headers={"Idempotency-Key": idempotency_key or f"live-parity-{uuid.uuid4().hex}"},
    )


def _simulate_stateful_alternatives(
    client: httpx.Client,
    *,
    advise_base_url: str,
    portfolio_id: str,
    as_of_date: str,
    alternatives_request: dict[str, Any],
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], float]:
    start = time.perf_counter()
    body = _request_json(
        client,
        method="POST",
        url=f"{advise_base_url}/advisory/proposals/simulate",
        expected_status=200,
        json_body={
            "input_mode": "stateful",
            "stateful_input": {"portfolio_id": portfolio_id, "as_of": as_of_date},
            "alternatives_request": alternatives_request,
        },
        headers={"Idempotency-Key": idempotency_key or f"live-alt-{uuid.uuid4().hex}"},
    )
    return body, (time.perf_counter() - start) * 1000.0


def _simulate_stateless_payload(
    client: httpx.Client,
    *,
    advise_base_url: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    return _request_json(
        client,
        method="POST",
        url=f"{advise_base_url}/advisory/proposals/simulate",
        expected_status=200,
        json_body=payload,
        headers={"Idempotency-Key": idempotency_key},
    )


def _build_review_decision_payload() -> dict[str, Any]:
    return {
        "portfolio_snapshot": {
            "portfolio_id": "pf_live_review_decision",
            "base_currency": "USD",
            "positions": [
                {"instrument_id": "EQ_OLD", "quantity": "7"},
                {"instrument_id": "BD_OLD", "quantity": "2"},
            ],
            "cash_balances": [{"currency": "USD", "amount": "100"}],
        },
        "market_data_snapshot": {
            "prices": [
                {"instrument_id": "EQ_OLD", "price": "100", "currency": "USD"},
                {"instrument_id": "BD_OLD", "price": "100", "currency": "USD"},
                {"instrument_id": "EQ_NEW", "price": "100", "currency": "USD"},
            ],
            "fx_rates": [],
        },
        "shelf_entries": [
            {"instrument_id": "EQ_OLD", "status": "APPROVED", "asset_class": "EQUITY"},
            {"instrument_id": "BD_OLD", "status": "APPROVED", "asset_class": "FIXED_INCOME"},
            {"instrument_id": "EQ_NEW", "status": "APPROVED", "asset_class": "EQUITY"},
        ],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [],
        "proposed_trades": [{"side": "BUY", "instrument_id": "EQ_NEW", "quantity": "1"}],
    }


def _build_blocked_decision_payload() -> dict[str, Any]:
    return {
        "portfolio_snapshot": {
            "portfolio_id": "pf_live_blocked_decision",
            "base_currency": "SGD",
            "positions": [],
            "cash_balances": [{"currency": "SGD", "amount": "10000"}],
        },
        "market_data_snapshot": {
            "prices": [{"instrument_id": "US_EQ", "price": "100", "currency": "USD"}],
            "fx_rates": [],
        },
        "shelf_entries": [{"instrument_id": "US_EQ", "status": "APPROVED"}],
        "options": {"enable_proposal_simulation": True, "block_on_missing_fx": True},
        "proposed_cash_flows": [],
        "proposed_trades": [{"side": "BUY", "instrument_id": "US_EQ", "quantity": "1"}],
    }


def _query_live_allocation(
    client: httpx.Client,
    *,
    core_query_base_url: str,
    portfolio_id: str,
    as_of_date: str,
    reporting_currency: str,
) -> dict[str, Any]:
    return _request_json(
        client,
        method="POST",
        url=f"{core_query_base_url}/reporting/asset-allocation/query",
        expected_status=200,
        json_body={
            "scope": {"portfolio_id": portfolio_id},
            "as_of_date": as_of_date,
            "reporting_currency": reporting_currency,
            "dimensions": _PROPOSAL_ALLOCATION_DIMENSIONS,
            "look_through_mode": "direct_only",
        },
    )


def _query_direct_concentration(
    client: httpx.Client,
    *,
    risk_base_url: str,
    portfolio_id: str,
    as_of_date: str,
    reporting_currency: str,
    simulation_changes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _request_json(
        client,
        method="POST",
        url=f"{risk_base_url}/analytics/risk/concentration",
        expected_status=200,
        json_body={
            "input_mode": "simulation",
            "simulation_input": {
                "portfolio_id": portfolio_id,
                "as_of_date": as_of_date,
                "reporting_currency": reporting_currency,
                "include_cash_positions": True,
                "include_zero_quantity_positions": False,
                "top_n": 10,
                "simulation_changes": _json_safe_value(simulation_changes or []),
            },
            "issuer_grouping_level": "ultimate_parent",
            "enrichment_policy": "merge_caller_then_core",
        },
    )


def _query_live_positions(
    client: httpx.Client,
    *,
    core_query_base_url: str,
    portfolio_id: str,
    as_of_date: str,
) -> list[dict[str, Any]]:
    response = client.get(
        f"{core_query_base_url}/portfolios/{portfolio_id}/positions",
        params={"as_of_date": as_of_date},
    )
    _assert(
        response.status_code == 200,
        (
            f"GET /portfolios/{portfolio_id}/positions: expected HTTP 200, "
            f"got {response.status_code}, body={response.text}"
        ),
    )
    payload = cast(dict[str, Any], response.json())
    positions = payload.get("positions")
    _assert(isinstance(positions, list), f"{portfolio_id}: positions response missing list payload")
    return cast(list[dict[str, Any]], positions)


def _validate_live_decision_paths(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: PortfolioParityScenario,
) -> tuple[LiveDecisionSnapshot, LiveDecisionSnapshot, LiveDecisionSnapshot]:
    ready_body = _simulate_stateful_noop(
        client,
        advise_base_url=advise_base_url,
        portfolio_id=complete_scenario.portfolio_id,
        as_of_date=complete_scenario.as_of_date,
        idempotency_key=f"live-decision-ready-{uuid.uuid4().hex}",
    )
    ready_snapshot = _extract_live_decision_snapshot(
        proposal_body=ready_body,
        path_name="ready_path",
    )
    _assert(
        ready_snapshot.top_level_status == "READY",
        f"ready_path: expected READY top-level status, got {ready_snapshot.top_level_status}",
    )
    _assert(
        ready_snapshot.decision_status in {"READY_FOR_CLIENT_REVIEW", "REQUIRES_CLIENT_CONSENT"},
        (
            "ready_path: expected ready or client-consent posture, got "
            f"{ready_snapshot.decision_status}"
        ),
    )

    review_body = _simulate_stateless_payload(
        client,
        advise_base_url=advise_base_url,
        payload=_build_review_decision_payload(),
        idempotency_key=f"live-decision-review-{uuid.uuid4().hex}",
    )
    review_snapshot = _extract_live_decision_snapshot(
        proposal_body=review_body,
        path_name="review_path",
    )
    _assert(
        review_snapshot.decision_status in {"REQUIRES_RISK_REVIEW", "REQUIRES_COMPLIANCE_REVIEW"},
        (
            "review_path: expected risk or compliance review posture, got "
            f"{review_snapshot.decision_status}"
        ),
    )
    _assert(
        bool(review_snapshot.approval_requirement_types),
        "review_path: approval requirements were unexpectedly empty",
    )

    blocked_body = _simulate_stateless_payload(
        client,
        advise_base_url=advise_base_url,
        payload=_build_blocked_decision_payload(),
        idempotency_key=f"live-decision-blocked-{uuid.uuid4().hex}",
    )
    blocked_snapshot = _extract_live_decision_snapshot(
        proposal_body=blocked_body,
        path_name="blocked_path",
    )
    _assert(
        blocked_snapshot.top_level_status == "BLOCKED",
        (
            "blocked_path: expected BLOCKED top-level status, got "
            f"{blocked_snapshot.top_level_status}"
        ),
    )
    _assert(
        blocked_snapshot.decision_status == "BLOCKED_REMEDIATION_REQUIRED",
        (
            "blocked_path: expected BLOCKED_REMEDIATION_REQUIRED decision status, got "
            f"{blocked_snapshot.decision_status}"
        ),
    )
    _assert(
        "DATA_REMEDIATION" in blocked_snapshot.approval_requirement_types,
        "blocked_path: data remediation requirement missing from decision summary",
    )

    return ready_snapshot, review_snapshot, blocked_snapshot


def _extract_live_proposal_alternatives_snapshot(
    *,
    proposal_body: dict[str, Any],
    path_name: str,
    latency_ms: float,
) -> LiveProposalAlternativesSnapshot:
    try:
        snapshot = extract_live_proposal_alternatives_snapshot(
            proposal_body,
            path_name=path_name,
            latency_ms=latency_ms,
        )
    except ValueError as exc:
        raise LiveParityValidationError(str(exc)) from exc
    _assert(
        bool(snapshot.requested_objectives),
        f"{path_name}: alternatives snapshot omitted requested objectives",
    )
    return snapshot


def _collect_alternative_statuses(
    proposal_body: dict[str, Any],
) -> dict[str, set[str]]:
    proposal_alternatives = proposal_body.get("proposal_alternatives")
    if not isinstance(proposal_alternatives, dict):
        return {}

    alternatives = proposal_alternatives.get("alternatives")
    if not isinstance(alternatives, list):
        return {}

    statuses_by_objective: dict[str, set[str]] = {}
    for alternative in alternatives:
        if not isinstance(alternative, dict):
            continue
        objective = str(alternative.get("objective") or "").strip()
        status = str(alternative.get("status") or "").strip()
        if not objective or not status:
            continue
        statuses_by_objective.setdefault(objective, set()).add(status)
    return statuses_by_objective


def _validate_live_proposal_alternatives_paths(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: PortfolioParityScenario,
    warm_duration_ms: float,
) -> tuple[
    LiveProposalAlternativesSnapshot,
    LiveProposalAlternativesSnapshot,
    LiveProposalAlternativesSnapshot,
    LiveProposalAlternativesSnapshot,
    LiveProposalAlternativesSnapshot,
]:
    noop_body, noop_latency_ms = _simulate_stateful_alternatives(
        client,
        advise_base_url=advise_base_url,
        portfolio_id=complete_scenario.portfolio_id,
        as_of_date=complete_scenario.as_of_date,
        idempotency_key=f"live-alt-noop-{uuid.uuid4().hex}",
        alternatives_request=_build_alternatives_request(
            objectives=[
                "REDUCE_CONCENTRATION",
                "RAISE_CASH",
                "IMPROVE_CURRENCY_ALIGNMENT",
                "AVOID_RESTRICTED_PRODUCTS",
            ],
            max_alternatives=3,
            constraints={
                "cash_floor": {
                    "amount": "25000",
                    "currency": complete_scenario.reporting_currency,
                }
            },
        ),
    )
    noop_snapshot = _extract_live_proposal_alternatives_snapshot(
        proposal_body=noop_body,
        path_name="no_op_path",
        latency_ms=noop_latency_ms,
    )
    noop_statuses = _collect_alternative_statuses(noop_body)
    _assert(
        noop_snapshot.requested_objectives
        == (
            "REDUCE_CONCENTRATION",
            "RAISE_CASH",
            "IMPROVE_CURRENCY_ALIGNMENT",
            "AVOID_RESTRICTED_PRODUCTS",
        ),
        f"no_op_path: requested objectives drifted, got {noop_snapshot.requested_objectives}",
    )
    _assert(
        noop_statuses.get("REDUCE_CONCENTRATION") == {"REJECTED_POLICY_BLOCKED"},
        (
            "no_op_path: expected concentration objective to surface as policy-blocked under "
            f"canonical posture, got {noop_statuses}"
        ),
    )
    _assert(
        noop_statuses.get("IMPROVE_CURRENCY_ALIGNMENT") == {"REJECTED_POLICY_BLOCKED"},
        (
            "no_op_path: expected currency objective to surface as policy-blocked under "
            f"canonical posture, got {noop_statuses}"
        ),
    )
    _assert(
        "ALTERNATIVE_CASH_ALREADY_SUFFICIENT" in noop_snapshot.rejected_reason_codes,
        (
            "no_op_path: expected cash-floor rejection evidence, got "
            f"{noop_snapshot.rejected_reason_codes}"
        ),
    )
    _assert(
        "ALTERNATIVE_OBJECTIVE_PENDING_CANONICAL_EVIDENCE" in noop_snapshot.rejected_reason_codes,
        (
            "no_op_path: expected restricted-product deferred evidence, got "
            f"{noop_snapshot.rejected_reason_codes}"
        ),
    )

    concentration_body, concentration_latency_ms = _simulate_stateful_alternatives(
        client,
        advise_base_url=advise_base_url,
        portfolio_id=complete_scenario.portfolio_id,
        as_of_date=complete_scenario.as_of_date,
        idempotency_key=f"live-alt-concentration-{uuid.uuid4().hex}",
        alternatives_request=_build_alternatives_request(
            objectives=["REDUCE_CONCENTRATION"],
            max_alternatives=1,
        ),
    )
    concentration_snapshot = _extract_live_proposal_alternatives_snapshot(
        proposal_body=concentration_body,
        path_name="concentration_path",
        latency_ms=concentration_latency_ms,
    )
    concentration_statuses = _collect_alternative_statuses(concentration_body)
    _assert(
        concentration_snapshot.requested_objectives == ("REDUCE_CONCENTRATION",),
        (
            "concentration_path: requested objective drifted from concentration posture, got "
            f"{concentration_snapshot.requested_objectives}"
        ),
    )
    _assert(
        concentration_statuses.get("REDUCE_CONCENTRATION") == {"REJECTED_POLICY_BLOCKED"},
        (
            "concentration_path: expected policy-blocked concentration alternative, got "
            f"{concentration_statuses}"
        ),
    )

    cash_raise_body, cash_raise_latency_ms = _simulate_stateful_alternatives(
        client,
        advise_base_url=advise_base_url,
        portfolio_id=complete_scenario.portfolio_id,
        as_of_date=complete_scenario.as_of_date,
        idempotency_key=f"live-alt-cash-{uuid.uuid4().hex}",
        alternatives_request=_build_alternatives_request(
            objectives=["RAISE_CASH"],
            max_alternatives=1,
            constraints={
                "cash_floor": {
                    "amount": "25000",
                    "currency": complete_scenario.reporting_currency,
                }
            },
        ),
    )
    cash_raise_snapshot = _extract_live_proposal_alternatives_snapshot(
        proposal_body=cash_raise_body,
        path_name="cash_raise_path",
        latency_ms=cash_raise_latency_ms,
    )
    _assert(
        cash_raise_snapshot.rejected_reason_codes == ("ALTERNATIVE_CASH_ALREADY_SUFFICIENT",),
        (
            "cash_raise_path: expected cash-floor rejection due to already sufficient base cash, "
            f"got {cash_raise_snapshot.rejected_reason_codes}"
        ),
    )

    cross_currency_body, cross_currency_latency_ms = _simulate_stateful_alternatives(
        client,
        advise_base_url=advise_base_url,
        portfolio_id=complete_scenario.portfolio_id,
        as_of_date=complete_scenario.as_of_date,
        idempotency_key=f"live-alt-currency-{uuid.uuid4().hex}",
        alternatives_request=_build_alternatives_request(
            objectives=["IMPROVE_CURRENCY_ALIGNMENT"],
            max_alternatives=1,
        ),
    )
    cross_currency_snapshot = _extract_live_proposal_alternatives_snapshot(
        proposal_body=cross_currency_body,
        path_name="cross_currency_path",
        latency_ms=cross_currency_latency_ms,
    )
    cross_currency_statuses = _collect_alternative_statuses(cross_currency_body)
    _assert(
        cross_currency_snapshot.requested_objectives == ("IMPROVE_CURRENCY_ALIGNMENT",),
        (
            "cross_currency_path: requested objective drifted from currency posture, got "
            f"{cross_currency_snapshot.requested_objectives}"
        ),
    )
    _assert(
        cross_currency_statuses.get("IMPROVE_CURRENCY_ALIGNMENT") == {"REJECTED_POLICY_BLOCKED"},
        (
            "cross_currency_path: expected policy-blocked currency alternative, got "
            f"{cross_currency_statuses}"
        ),
    )

    restricted_product_body, restricted_product_latency_ms = _simulate_stateful_alternatives(
        client,
        advise_base_url=advise_base_url,
        portfolio_id=complete_scenario.portfolio_id,
        as_of_date=complete_scenario.as_of_date,
        idempotency_key=f"live-alt-restricted-{uuid.uuid4().hex}",
        alternatives_request=_build_alternatives_request(
            objectives=["AVOID_RESTRICTED_PRODUCTS"],
            max_alternatives=1,
        ),
    )
    restricted_product_snapshot = _extract_live_proposal_alternatives_snapshot(
        proposal_body=restricted_product_body,
        path_name="restricted_product_path",
        latency_ms=restricted_product_latency_ms,
    )
    _assert(
        restricted_product_snapshot.feasible_count == 0
        and restricted_product_snapshot.feasible_with_review_count == 0,
        (
            "restricted_product_path: deferred restricted-product path unexpectedly produced "
            f"ranked alternatives {restricted_product_snapshot}"
        ),
    )
    _assert(
        "ALTERNATIVE_OBJECTIVE_PENDING_CANONICAL_EVIDENCE"
        in restricted_product_snapshot.rejected_reason_codes,
        (
            "restricted_product_path: expected deferred canonical-evidence rejection, got "
            f"{restricted_product_snapshot.rejected_reason_codes}"
        ),
    )

    latency_bound_ms = max(warm_duration_ms * 6.0, 5000.0)
    for snapshot in (
        noop_snapshot,
        concentration_snapshot,
        cash_raise_snapshot,
        cross_currency_snapshot,
        restricted_product_snapshot,
    ):
        _assert(
            snapshot.latency_ms <= latency_bound_ms,
            (
                f"{snapshot.path_name}: alternatives latency exceeded bound "
                f"{snapshot.latency_ms:.2f}ms > {latency_bound_ms:.2f}ms"
            ),
        )

    return (
        noop_snapshot,
        concentration_snapshot,
        cash_raise_snapshot,
        cross_currency_snapshot,
        restricted_product_snapshot,
    )


def _select_changed_state_security(positions: list[dict[str, Any]]) -> str:
    non_cash_positions = [
        position
        for position in positions
        if str(position.get("asset_class", "")).lower() != "cash" and position.get("security_id")
    ]
    _assert(
        bool(non_cash_positions),
        "No non-cash positions available for changed-state risk parity",
    )
    selected = max(
        non_cash_positions,
        key=lambda position: _decimal(position.get("weight", "0")),
    )
    return str(selected["security_id"])


def _select_cross_currency_changed_state_security(
    positions: list[dict[str, Any]],
    *,
    base_currency: str,
) -> str:
    cross_currency_positions = [
        position
        for position in positions
        if str(position.get("asset_class", "")).lower() != "cash"
        and position.get("security_id")
        and str(position.get("currency") or "").strip().upper() != base_currency.upper()
    ]
    _assert(
        bool(cross_currency_positions),
        f"No cross-currency non-cash positions available outside base currency {base_currency}",
    )
    selected = max(
        cross_currency_positions,
        key=lambda position: _decimal(position.get("weight", "0")),
    )
    return str(selected["security_id"])


def _select_non_held_changed_state_security(
    positions: list[dict[str, Any]],
    *,
    candidates: tuple[str, ...] = _NON_HELD_CANDIDATES,
) -> str:
    held_security_ids = {
        str(position.get("security_id") or "").strip()
        for position in positions
        if str(position.get("security_id") or "").strip()
    }
    for candidate in candidates:
        if candidate not in held_security_ids:
            return candidate
    raise LiveParityValidationError(
        f"No non-held candidate available from preferred list {list(candidates)}"
    )


def _security_trade_changes_from_proposal_body(
    proposal_body: dict[str, Any],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for intent in cast(list[dict[str, Any]], proposal_body.get("intents", [])):
        if str(intent.get("intent_type")) != "SECURITY_TRADE":
            continue
        change: dict[str, Any] = {
            "security_id": intent["instrument_id"],
            "transaction_type": intent["side"],
            "quantity": _decimal(intent["quantity"]),
            "metadata": {
                "proposal_intent_id": intent["intent_id"],
                "proposal_intent_type": intent["intent_type"],
            },
        }
        notional = intent.get("notional")
        if isinstance(notional, dict):
            change["amount"] = _decimal(notional["amount"])
            change["currency"] = notional["currency"]
        changes.append(change)
    return changes


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    return value


def _select_scenarios(
    client: httpx.Client,
    *,
    advise_base_url: str,
    core_query_base_url: str,
    candidates: tuple[str, ...],
) -> tuple[PortfolioParityScenario, PortfolioParityScenario]:
    complete: PortfolioParityScenario | None = None
    degraded: PortfolioParityScenario | None = None
    examined: list[tuple[str, str]] = []

    for portfolio_id in candidates:
        as_of_date, reporting_currency = _resolve_latest_portfolio_context(
            client,
            core_query_base_url=core_query_base_url,
            portfolio_id=portfolio_id,
        )
        simulate = _simulate_stateful_noop(
            client,
            advise_base_url=advise_base_url,
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
        )
        authority = simulate.get("explanation", {}).get("authority_resolution") or {}
        risk_lens = simulate.get("explanation", {}).get("risk_lens")
        risk_available = isinstance(risk_lens, dict)
        coverage_status = (
            str(risk_lens["issuer_concentration"]["coverage_status"])
            if risk_available
            else "unavailable"
        )
        examined.append((portfolio_id, coverage_status))
        scenario = PortfolioParityScenario(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            reporting_currency=reporting_currency,
            issuer_coverage_status=coverage_status,
            risk_available=risk_available,
        )
        if risk_available and coverage_status == "complete" and complete is None:
            complete = scenario
        elif coverage_status in {"partial", "unavailable"} and degraded is None:
            degraded = scenario
        elif (
            coverage_status == "partial"
            and degraded is not None
            and degraded.issuer_coverage_status != "partial"
        ):
            degraded = scenario
        elif (
            not risk_available
            and authority.get("risk_authority") == "unavailable"
            and degraded is None
        ):
            degraded = scenario
        if complete is not None and degraded is not None:
            return complete, degraded

    raise LiveParityValidationError(
        "Could not find both complete and degraded issuer-coverage parity scenarios from seeded "
        f"portfolios. examined={examined}"
    )


def _assert_allocation_parity(
    *,
    scenario: PortfolioParityScenario,
    direct_allocation: dict[str, Any],
    proposal_body: dict[str, Any],
) -> None:
    direct_views = _normalize_allocation_views(direct_allocation["views"])
    before_views = _normalize_allocation_views(proposal_body["before"]["allocation_views"])
    after_views = _normalize_allocation_views(proposal_body["after_simulated"]["allocation_views"])

    _assert(
        direct_views == before_views,
        (
            f"{scenario.portfolio_id}: proposal before allocation views diverged "
            "from live lotus-core allocation"
        ),
    )
    _assert(
        direct_views == after_views,
        (
            f"{scenario.portfolio_id}: no-op proposal after allocation views diverged "
            "from live lotus-core allocation"
        ),
    )


def _assert_authority_posture(
    *,
    scenario: PortfolioParityScenario,
    proposal_body: dict[str, Any],
) -> None:
    authority_resolution = proposal_body.get("explanation", {}).get("authority_resolution")
    _assert(
        isinstance(authority_resolution, dict),
        f"{scenario.portfolio_id}: proposal response missing authority_resolution",
    )
    _assert(
        authority_resolution.get("simulation_authority") == "lotus_core",
        (
            f"{scenario.portfolio_id}: expected lotus_core simulation authority, got "
            f"{authority_resolution}"
        ),
    )
    _assert(
        authority_resolution.get("risk_authority") == "lotus_risk",
        (
            f"{scenario.portfolio_id}: expected lotus_risk risk authority, got "
            f"{authority_resolution}"
        ),
    )
    _assert(
        authority_resolution.get("degraded") is False,
        (
            f"{scenario.portfolio_id}: proposal response unexpectedly degraded on live parity "
            f"path: {authority_resolution}"
        ),
    )


def _assert_risk_parity(
    *,
    scenario: PortfolioParityScenario,
    direct_risk: dict[str, Any],
    proposal_body: dict[str, Any],
) -> None:
    direct_normalized = _normalize_risk_payload(direct_risk)
    proposal_normalized = _normalize_risk_payload(proposal_body["explanation"]["risk_lens"])
    _assert(
        direct_normalized == proposal_normalized,
        (
            f"{scenario.portfolio_id}: proposal risk_lens diverged from direct "
            "lotus-risk concentration"
        ),
    )


def _measure_warm_cache(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> tuple[float, float]:
    def _timed_call() -> tuple[dict[str, Any], float]:
        started = time.perf_counter()
        body = _simulate_stateful_noop(
            client,
            advise_base_url=advise_base_url,
            portfolio_id=scenario.portfolio_id,
            as_of_date=scenario.as_of_date,
        )
        return body, (time.perf_counter() - started) * 1000.0

    cold_body, cold_ms = _timed_call()
    warm_body, warm_ms = _timed_call()
    _assert(
        _normalize_allocation_views(cold_body["before"]["allocation_views"])
        == _normalize_allocation_views(warm_body["before"]["allocation_views"]),
        f"{scenario.portfolio_id}: repeated stateful simulate changed before allocation views",
    )
    warm_threshold_ms = max(
        cold_ms * _WARM_CACHE_TOLERANCE_MULTIPLIER,
        cold_ms + _WARM_CACHE_TOLERANCE_ABSOLUTE_MS,
    )
    _assert(
        warm_ms <= warm_threshold_ms,
        (
            f"{scenario.portfolio_id}: warm cache regression detected "
            f"cold_ms={cold_ms:.2f} warm_ms={warm_ms:.2f} "
            f"threshold_ms={warm_threshold_ms:.2f}"
        ),
    )
    return cold_ms, warm_ms


def _post_json(
    client: httpx.Client,
    *,
    url: str,
    expected_status: int,
    json_body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return _request_json(
        client,
        method="POST",
        url=url,
        expected_status=expected_status,
        json_body=json_body,
        headers=headers,
    )


def _get_json(
    client: httpx.Client,
    *,
    url: str,
    expected_status: int,
) -> dict[str, Any]:
    return _request_json(
        client,
        method="GET",
        url=url,
        expected_status=expected_status,
    )


def _assert_workspace_rationale_response(
    *,
    scenario: PortfolioParityScenario,
    workspace_id: str,
    response_body: dict[str, Any],
) -> dict[str, Any]:
    _assert(
        response_body.get("generated_by") == "lotus-ai",
        f"{scenario.portfolio_id}: workspace rationale was not generated by lotus-ai",
    )
    evidence = response_body.get("evidence")
    _assert(
        isinstance(evidence, dict) and evidence.get("workspace_id") == workspace_id,
        f"{scenario.portfolio_id}: workspace rationale evidence lost workspace identity",
    )
    workflow_pack_run = response_body.get("workflow_pack_run")
    _assert(
        isinstance(workflow_pack_run, dict),
        f"{scenario.portfolio_id}: workspace rationale omitted workflow-pack run posture",
    )
    _assert(
        workflow_pack_run.get("workflow_authority_owner") == "lotus-advise",
        (
            f"{scenario.portfolio_id}: workspace rationale run owner drifted "
            "from lotus-advise, "
            f"got {workflow_pack_run}"
        ),
    )
    _assert(
        workflow_pack_run.get("runtime_state") == "COMPLETED",
        f"{scenario.portfolio_id}: workspace rationale run was not completed",
    )
    _assert(
        workflow_pack_run.get("review_state") == "AWAITING_REVIEW",
        f"{scenario.portfolio_id}: workspace rationale run lost awaiting-review posture",
    )
    _assert(
        workflow_pack_run.get("supportability_status") == "ACTION_REQUIRED",
        (
            f"{scenario.portfolio_id}: workspace rationale run lost action-required posture, "
            f"got {workflow_pack_run}"
        ),
    )
    allowed_review_actions = workflow_pack_run.get("allowed_review_actions")
    _assert(
        isinstance(allowed_review_actions, list)
        and "REVISE" in allowed_review_actions
        and "SUPERSEDE" in allowed_review_actions,
        (
            f"{scenario.portfolio_id}: workspace rationale run omitted bounded replacement "
            f"review actions {workflow_pack_run}"
        ),
    )
    return cast(dict[str, Any], workflow_pack_run)


def _assert_workspace_rationale_review_action(
    *,
    scenario: PortfolioParityScenario,
    initial_run_id: str,
    replacement_run_id: str,
    review_action: dict[str, Any],
) -> tuple[str, str]:
    review_run = review_action.get("workflow_pack_run")
    _assert(
        isinstance(review_run, dict),
        f"{scenario.portfolio_id}: workspace rationale review action omitted workflow-pack run",
    )
    _assert(
        review_run.get("run_id") == initial_run_id,
        f"{scenario.portfolio_id}: workspace rationale review action returned the wrong run",
    )
    _assert(
        review_run.get("replacement_run_id") == replacement_run_id,
        (
            f"{scenario.portfolio_id}: workspace rationale review action lost replacement "
            f"lineage {review_run}"
        ),
    )
    _assert(
        review_run.get("review_state") == "SUPERSEDED",
        f"{scenario.portfolio_id}: workspace rationale review state drifted after supersede",
    )
    _assert(
        review_run.get("supportability_status") == "HISTORICAL"
        and review_run.get("superseded") is True,
        (
            f"{scenario.portfolio_id}: workspace rationale review action did not produce "
            f"historical superseded posture {review_run}"
        ),
    )
    _assert(
        isinstance(review_action.get("summary"), list) and review_action["summary"],
        f"{scenario.portfolio_id}: workspace rationale review action omitted summary evidence",
    )
    _assert(
        "assistant_output" not in review_action,
        (
            f"{scenario.portfolio_id}: workspace rationale review action unexpectedly implied a "
            "rewritten narrative"
        ),
    )
    return str(review_run["review_state"]), str(review_run["supportability_status"])


def _create_stateful_proposal(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
    created_by: str,
    narrative_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stateful_input: dict[str, Any] = {
        "portfolio_id": scenario.portfolio_id,
        "as_of": scenario.as_of_date,
    }
    if narrative_request is not None:
        stateful_input["narrative_request"] = narrative_request
    return _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals",
        expected_status=200,
        json_body={
            "created_by": created_by,
            "input_mode": "stateful",
            "stateful_input": stateful_input,
        },
        headers={"Idempotency-Key": f"live-create-{uuid.uuid4().hex}"},
    )


def _create_stateful_version(
    client: httpx.Client,
    *,
    advise_base_url: str,
    proposal_id: str,
    scenario: PortfolioParityScenario,
    created_by: str,
    expected_current_version_no: int,
    narrative_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stateful_input: dict[str, Any] = {
        "portfolio_id": scenario.portfolio_id,
        "as_of": scenario.as_of_date,
    }
    if narrative_request is not None:
        stateful_input["narrative_request"] = narrative_request
    return _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions",
        expected_status=200,
        json_body={
            "created_by": created_by,
            "expected_current_version_no": expected_current_version_no,
            "input_mode": "stateful",
            "stateful_input": stateful_input,
        },
    )


def _submit_async_create(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
    created_by: str,
) -> dict[str, Any]:
    return _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/async",
        expected_status=202,
        json_body={
            "created_by": created_by,
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": scenario.portfolio_id,
                "as_of": scenario.as_of_date,
            },
        },
        headers={
            "Idempotency-Key": f"live-async-create-{uuid.uuid4().hex}",
            "X-Correlation-Id": f"live-async-create-{uuid.uuid4().hex}",
        },
    )


def _submit_async_version(
    client: httpx.Client,
    *,
    advise_base_url: str,
    proposal_id: str,
    scenario: PortfolioParityScenario,
    created_by: str,
    expected_current_version_no: int,
) -> dict[str, Any]:
    return _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/async",
        expected_status=202,
        json_body={
            "created_by": created_by,
            "expected_current_version_no": expected_current_version_no,
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": scenario.portfolio_id,
                "as_of": scenario.as_of_date,
            },
        },
        headers={"X-Correlation-Id": f"live-async-version-{uuid.uuid4().hex}"},
    )


def _wait_for_async_success(
    client: httpx.Client,
    *,
    advise_base_url: str,
    operation_id: str,
    expected_type: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        status_body = _get_json(
            client,
            url=f"{advise_base_url}/advisory/proposals/operations/{operation_id}",
            expected_status=200,
        )
        _assert(
            status_body["operation_type"] == expected_type,
            f"{operation_id}: unexpected operation type {status_body['operation_type']}",
        )
        if status_body["status"] == "SUCCEEDED":
            result = status_body.get("result")
            _assert(isinstance(result, dict), f"{operation_id}: async success missing result")
            return cast(dict[str, Any], result)
        if status_body["status"] == "FAILED":
            raise LiveParityValidationError(
                f"{operation_id}: async operation failed {status_body.get('error')}"
            )
        time.sleep(0.5)
    raise LiveParityValidationError(f"{operation_id}: async operation did not finish in time")


def _assert_async_operation_surfaces(
    client: httpx.Client,
    *,
    advise_base_url: str,
    accepted_body: dict[str, Any],
    expected_type: str,
    result_body: dict[str, Any],
) -> None:
    operation_id = str(accepted_body["operation_id"])
    correlation_id = str(accepted_body["correlation_id"])
    operation = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/operations/{operation_id}",
        expected_status=200,
    )
    by_correlation = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/operations/by-correlation/{correlation_id}",
        expected_status=200,
    )
    replay = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/operations/{operation_id}/replay-evidence",
        expected_status=200,
    )
    proposal = cast(dict[str, Any], result_body["proposal"])
    version = cast(dict[str, Any], result_body["version"])
    proposal_id = str(proposal["proposal_id"])
    version_no = int(version["version_no"])
    version_replay = _get_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/replay-evidence"
        ),
        expected_status=200,
    )
    detail = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}?include_evidence=false",
        expected_status=200,
    )

    _assert(
        operation["operation_type"] == by_correlation["operation_type"] == expected_type,
        f"{operation_id}: async operation type diverged across read surfaces",
    )
    _assert(
        operation["operation_id"] == by_correlation["operation_id"] == operation_id,
        f"{operation_id}: operation lookup diverged across id/correlation surfaces",
    )
    _assert(
        operation["correlation_id"] == by_correlation["correlation_id"] == correlation_id,
        f"{operation_id}: correlation lookup diverged across id/correlation surfaces",
    )
    _assert(
        operation["status"] == by_correlation["status"] == "SUCCEEDED",
        f"{operation_id}: async operation did not stay in succeeded state",
    )
    _assert(
        str(cast(dict[str, Any], operation["result"])["proposal"]["proposal_id"]) == proposal_id,
        f"{operation_id}: operation result proposal id diverged from async result",
    )
    _assert(
        int(cast(dict[str, Any], operation["result"])["version"]["version_no"]) == version_no,
        f"{operation_id}: operation result version diverged from async result",
    )
    _assert(
        replay["subject"]["scope"] == "ASYNC_OPERATION",
        f"{operation_id}: async replay subject scope was not ASYNC_OPERATION",
    )
    _assert(
        replay["subject"]["operation_id"] == operation_id,
        f"{operation_id}: async replay subject lost operation id",
    )
    _assert(
        replay["subject"]["proposal_id"] == proposal_id,
        f"{operation_id}: async replay subject lost proposal id",
    )
    _assert(
        replay["subject"]["proposal_version_no"] == version_no,
        f"{operation_id}: async replay subject lost proposal version",
    )
    _assert(
        replay["continuity"]["correlation_id"] == correlation_id,
        f"{operation_id}: async replay continuity lost correlation id",
    )
    _assert(
        replay["continuity"]["async_operation_id"] == operation_id,
        f"{operation_id}: async replay continuity lost operation id",
    )
    _assert(
        replay["hashes"]["request_hash"] == version_replay["hashes"]["request_hash"],
        f"{operation_id}: async/proposal replay request hash diverged",
    )
    _assert(
        replay["hashes"]["simulation_hash"] == version_replay["hashes"]["simulation_hash"],
        f"{operation_id}: async/proposal replay simulation hash diverged",
    )
    _assert(
        replay["resolved_context"] == version_replay["resolved_context"],
        f"{operation_id}: async/proposal replay resolved context diverged",
    )
    _assert(
        int(detail["proposal"]["current_version_no"]) >= version_no,
        f"{operation_id}: proposal detail current version regressed behind async result",
    )


def _post_transition(
    client: httpx.Client,
    *,
    advise_base_url: str,
    proposal_id: str,
    event_type: str,
    actor_id: str,
    expected_state: str,
    related_version_no: int,
    reason: dict[str, Any],
) -> dict[str, Any]:
    return _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/transitions",
        expected_status=200,
        json_body={
            "event_type": event_type,
            "actor_id": actor_id,
            "expected_state": expected_state,
            "related_version_no": related_version_no,
            "reason": reason,
        },
    )


def _post_approval(
    client: httpx.Client,
    *,
    advise_base_url: str,
    proposal_id: str,
    approval_type: str,
    actor_id: str,
    expected_state: str,
    related_version_no: int,
    details: dict[str, Any],
) -> dict[str, Any]:
    return _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/approvals",
        expected_status=200,
        json_body={
            "approval_type": approval_type,
            "approved": True,
            "actor_id": actor_id,
            "expected_state": expected_state,
            "related_version_no": related_version_no,
            "details": details,
        },
    )


def _promote_to_execution_ready(
    client: httpx.Client,
    *,
    advise_base_url: str,
    proposal_id: str,
    related_version_no: int,
    route: Literal["risk", "compliance"] = "risk",
) -> None:
    current_state = "DRAFT"
    if current_state == "DRAFT":
        route_event_type = (
            "SUBMITTED_FOR_RISK_REVIEW" if route == "risk" else "SUBMITTED_FOR_COMPLIANCE_REVIEW"
        )
        route_target_state = "RISK_REVIEW" if route == "risk" else "COMPLIANCE_REVIEW"
        transition = _post_transition(
            client,
            advise_base_url=advise_base_url,
            proposal_id=proposal_id,
            event_type=route_event_type,
            actor_id="live-parity-validator",
            expected_state="DRAFT",
            related_version_no=related_version_no,
            reason={"comment": "live delivery validation"},
        )
        current_state = str(transition["current_state"])
        _assert(
            current_state == route_target_state,
            f"{proposal_id}: unexpected state after {route} submission {current_state}",
        )
    if current_state == "RISK_REVIEW":
        approval = _post_approval(
            client,
            advise_base_url=advise_base_url,
            proposal_id=proposal_id,
            approval_type="RISK",
            actor_id="risk-approver",
            expected_state="RISK_REVIEW",
            related_version_no=related_version_no,
            details={"channel": "LIVE_VALIDATOR"},
        )
        current_state = str(approval["current_state"])
    if current_state == "COMPLIANCE_REVIEW":
        approval = _post_approval(
            client,
            advise_base_url=advise_base_url,
            proposal_id=proposal_id,
            approval_type="COMPLIANCE",
            actor_id="compliance-approver",
            expected_state="COMPLIANCE_REVIEW",
            related_version_no=related_version_no,
            details={"channel": "LIVE_VALIDATOR"},
        )
        current_state = str(approval["current_state"])
    if current_state == "AWAITING_CLIENT_CONSENT":
        approval = _post_approval(
            client,
            advise_base_url=advise_base_url,
            proposal_id=proposal_id,
            approval_type="CLIENT_CONSENT",
            actor_id="client-consent",
            expected_state="AWAITING_CLIENT_CONSENT",
            related_version_no=related_version_no,
            details={"channel": "LIVE_VALIDATOR"},
        )
        current_state = str(approval["current_state"])
    _assert(
        current_state == "EXECUTION_READY",
        f"{proposal_id}: could not promote proposal to execution ready, final={current_state}",
    )


def _assert_mixed_approval_routes_remain_version_scoped(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> None:
    created = _create_stateful_proposal(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator-route-scope",
    )
    proposal_id = str(created["proposal"]["proposal_id"])
    _promote_to_execution_ready(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        related_version_no=1,
        route="compliance",
    )

    version_created = _create_stateful_version(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        scenario=scenario,
        created_by="live-parity-validator-route-scope-version",
        expected_current_version_no=1,
    )
    _assert(
        version_created["proposal"]["current_state"] == "DRAFT",
        f"{proposal_id}: mixed-route scope version did not reset to DRAFT",
    )
    _promote_to_execution_ready(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        related_version_no=2,
        route="risk",
    )
    handoff = _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/execution-handoffs",
        expected_status=200,
        json_body={
            "actor_id": "ops_mixed_001",
            "execution_provider": "lotus-manage",
            "expected_state": "EXECUTION_READY",
            "related_version_no": 2,
            "external_request_id": f"oms_req_mixed_{uuid.uuid4().hex[:10]}",
            "notes": {"channel": "OMS"},
        },
        headers={"Idempotency-Key": f"live-mixed-route-handoff-{uuid.uuid4().hex}"},
    )
    _assert(
        handoff["handoff_status"] == "REQUESTED",
        f"{proposal_id}: mixed-route handoff did not enter REQUESTED",
    )
    executed = _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/execution-updates",
        expected_status=200,
        json_body={
            "update_id": f"exec_update_mixed_{uuid.uuid4().hex[:10]}",
            "actor_id": "lotus-manage",
            "execution_request_id": handoff["execution_request_id"],
            "execution_provider": "lotus-manage",
            "update_status": "EXECUTED",
            "related_version_no": 2,
            "external_execution_id": f"oms_fill_mixed_{uuid.uuid4().hex[:10]}",
            "occurred_at": _utc_iso_after(seconds=2),
        },
    )
    _assert(
        executed["handoff_status"] == "EXECUTED",
        f"{proposal_id}: mixed-route execution did not reach EXECUTED",
    )
    report_response = client.post(
        f"{advise_base_url}/advisory/proposals/{proposal_id}/report-requests",
        json={
            "report_type": "CLIENT_PROPOSAL_SUMMARY",
            "requested_by": "advisor_mixed_1",
            "related_version_no": 2,
            "include_execution_summary": True,
        },
    )
    _assert(
        report_response.status_code in {200, 503},
        (
            f"{proposal_id}: mixed-route report request returned unexpected "
            f"{report_response.status_code} body={report_response.text}"
        ),
    )
    approvals = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/approvals",
        expected_status=200,
    )
    timeline = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/workflow-events",
        expected_status=200,
    )
    delivery_summary = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/delivery-summary",
        expected_status=200,
    )
    delivery_history = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/delivery-events",
        expected_status=200,
    )
    approval_rows = cast(list[dict[str, Any]], approvals["approvals"])
    timeline_events = cast(list[dict[str, Any]], timeline["events"])
    delivery_events = cast(list[dict[str, Any]], delivery_history["events"])
    _assert(
        {str(approval["approval_type"]) for approval in approval_rows}
        == {"COMPLIANCE", "RISK", "CLIENT_CONSENT"},
        f"{proposal_id}: approvals endpoint lost mixed-route approval lineage",
    )
    _assert(
        {int(approval["related_version_no"]) for approval in approval_rows} == {1, 2},
        f"{proposal_id}: approvals endpoint lost mixed-route version lineage",
    )
    _assert(
        any(
            event["event_type"] == "COMPLIANCE_APPROVED" and int(event["related_version_no"]) == 1
            for event in timeline_events
        )
        and any(
            event["event_type"] == "RISK_APPROVED" and int(event["related_version_no"]) == 2
            for event in timeline_events
        ),
        f"{proposal_id}: workflow timeline lost mixed-route approval lineage",
    )
    _assert(
        int(cast(dict[str, Any], delivery_summary["execution"])["related_version_no"]) == 2,
        f"{proposal_id}: mixed-route execution summary was not anchored to version 2",
    )
    _assert(
        cast(dict[str, Any], delivery_summary["execution"])["handoff_status"] == "EXECUTED",
        f"{proposal_id}: mixed-route execution summary did not reach EXECUTED",
    )
    reporting = delivery_summary.get("reporting")
    if report_response.status_code == 200:
        _assert(
            isinstance(reporting, dict)
            and int(cast(dict[str, Any], reporting)["related_version_no"]) == 2
            and cast(dict[str, Any], reporting)["status"] == "READY",
            f"{proposal_id}: mixed-route reporting summary was not anchored to version 2",
        )
    else:
        _assert(
            reporting is None,
            f"{proposal_id}: mixed-route delivery summary exposed reporting during degraded path",
        )
    _assert(
        all(int(event["related_version_no"]) == 2 for event in delivery_events),
        f"{proposal_id}: mixed-route delivery history leaked non-current version events",
    )
    _assert(
        [str(event["event_type"]) for event in delivery_events]
        == (
            ["EXECUTION_REQUESTED", "EXECUTED", "REPORT_REQUESTED"]
            if report_response.status_code == 200
            else ["EXECUTION_REQUESTED", "EXECUTED"]
        ),
        f"{proposal_id}: mixed-route delivery history was not anchored to latest version",
    )


def _assert_lifecycle_and_delivery_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> tuple[str, int, str, str, str]:
    created = _create_stateful_proposal(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator",
    )
    proposal = created["proposal"]
    version = created["version"]
    proposal_id = str(proposal["proposal_id"])
    related_version_no = int(version["version_no"])
    _assert_authority_posture(scenario=scenario, proposal_body=version["proposal_result"])

    version_created = _create_stateful_version(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        scenario=scenario,
        created_by="live-parity-validator-version",
        expected_current_version_no=related_version_no,
    )
    _assert(
        int(version_created["proposal"]["current_version_no"]) == related_version_no + 1,
        f"{proposal_id}: new version did not increment current_version_no",
    )
    related_version_no = int(version_created["proposal"]["current_version_no"])
    _assert_authority_posture(
        scenario=scenario,
        proposal_body=version_created["version"]["proposal_result"],
    )

    async_created = _submit_async_create(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator-async",
    )
    async_create_result = _wait_for_async_success(
        client,
        advise_base_url=advise_base_url,
        operation_id=str(async_created["operation_id"]),
        expected_type="CREATE_PROPOSAL",
    )
    _assert_async_operation_surfaces(
        client,
        advise_base_url=advise_base_url,
        accepted_body=async_created,
        expected_type="CREATE_PROPOSAL",
        result_body=async_create_result,
    )
    async_proposal = async_create_result["proposal"]
    async_version = async_create_result["version"]
    async_proposal_id = str(async_proposal["proposal_id"])
    async_version_no = int(async_version["version_no"])
    _assert_authority_posture(scenario=scenario, proposal_body=async_version["proposal_result"])

    async_version_created = _submit_async_version(
        client,
        advise_base_url=advise_base_url,
        proposal_id=async_proposal_id,
        scenario=scenario,
        created_by="live-parity-validator-async-version",
        expected_current_version_no=async_version_no,
    )
    async_version_result = _wait_for_async_success(
        client,
        advise_base_url=advise_base_url,
        operation_id=str(async_version_created["operation_id"]),
        expected_type="CREATE_PROPOSAL_VERSION",
    )
    _assert_async_operation_surfaces(
        client,
        advise_base_url=advise_base_url,
        accepted_body=async_version_created,
        expected_type="CREATE_PROPOSAL_VERSION",
        result_body=async_version_result,
    )
    _assert(
        int(async_version_result["proposal"]["current_version_no"]) == async_version_no + 1,
        f"{async_proposal_id}: async version did not increment current_version_no",
    )
    _assert_authority_posture(
        scenario=scenario,
        proposal_body=async_version_result["version"]["proposal_result"],
    )

    _promote_to_execution_ready(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        related_version_no=related_version_no,
    )
    handoff = _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/execution-handoffs",
        expected_status=200,
        json_body={
            "actor_id": "ops_001",
            "execution_provider": "lotus-manage",
            "expected_state": "EXECUTION_READY",
            "related_version_no": related_version_no,
            "external_request_id": f"oms_req_{uuid.uuid4().hex[:10]}",
            "notes": {"channel": "OMS", "priority": "STANDARD"},
        },
        headers={"Idempotency-Key": f"live-handoff-{uuid.uuid4().hex}"},
    )
    _assert(
        handoff["handoff_status"] == "REQUESTED",
        f"{proposal_id}: unexpected handoff status {handoff['handoff_status']}",
    )

    requested_status = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/execution-status",
        expected_status=200,
    )
    _assert(
        requested_status["handoff_status"] == "REQUESTED",
        (
            f"{proposal_id}: unexpected requested execution status "
            f"{requested_status['handoff_status']}"
        ),
    )

    accepted_status = _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/execution-updates",
        expected_status=200,
        json_body={
            "update_id": f"exec_accept_{uuid.uuid4().hex[:10]}",
            "actor_id": "lotus-manage",
            "execution_request_id": handoff["execution_request_id"],
            "execution_provider": "lotus-manage",
            "update_status": "ACCEPTED",
            "related_version_no": related_version_no,
            "occurred_at": _utc_iso_after(seconds=1),
            "details": {"desk": "SG"},
        },
    )
    _assert(
        accepted_status["handoff_status"] == "ACCEPTED",
        f"{proposal_id}: unexpected accepted execution status {accepted_status['handoff_status']}",
    )

    executed_status = _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/execution-updates",
        expected_status=200,
        json_body={
            "update_id": f"exec_done_{uuid.uuid4().hex[:10]}",
            "actor_id": "lotus-manage",
            "execution_request_id": handoff["execution_request_id"],
            "execution_provider": "lotus-manage",
            "update_status": "EXECUTED",
            "related_version_no": related_version_no,
            "external_execution_id": f"oms_fill_{uuid.uuid4().hex[:10]}",
            "occurred_at": _utc_iso_after(seconds=2),
            "details": {"filled_quantity": "100"},
        },
    )
    _assert(
        executed_status["handoff_status"] == "EXECUTED",
        f"{proposal_id}: unexpected terminal execution status {executed_status['handoff_status']}",
    )

    capabilities = _get_json(
        client,
        url=f"{advise_base_url}/platform/capabilities",
        expected_status=200,
    )
    report_feature = _feature_by_key(capabilities, "advisory.proposals.reporting")
    report_response = client.post(
        f"{advise_base_url}/advisory/proposals/{proposal_id}/report-requests",
        json={
            "report_type": "CLIENT_PROPOSAL_SUMMARY",
            "requested_by": "advisor_1",
            "related_version_no": related_version_no,
            "include_execution_summary": True,
        },
    )
    if report_feature["operational_ready"]:
        _assert(
            report_response.status_code == 200,
            (
                f"{proposal_id}: expected live report request success, got "
                f"{report_response.status_code} body={report_response.text}"
            ),
        )
        report_body = cast(dict[str, Any], report_response.json())
        _assert(
            report_body["report_service"] == "lotus-report",
            f"{proposal_id}: unexpected report service {report_body['report_service']}",
        )
        _assert(
            report_body["status"] == "READY",
            f"{proposal_id}: unexpected report status {report_body['status']}",
        )
        _assert_persisted_read_surfaces(
            client,
            advise_base_url=advise_base_url,
            proposal_id=proposal_id,
            expected_portfolio_id=scenario.portfolio_id,
            created_by_filter="live-parity-validator",
            current_version_no=related_version_no,
            expected_state="EXECUTED",
            expected_report_status=report_body["status"],
        )
        return (
            scenario.portfolio_id,
            related_version_no,
            "EXECUTED",
            handoff["handoff_status"],
            report_body["status"],
        )

    _assert(
        report_response.status_code == 503,
        (
            f"{proposal_id}: expected lotus-report degraded 503, got "
            f"{report_response.status_code} body={report_response.text}"
        ),
    )
    detail = cast(dict[str, Any], report_response.json()).get("detail")
    _assert(
        detail == "LOTUS_REPORT_REQUEST_UNAVAILABLE",
        f"{proposal_id}: unexpected degraded report detail {detail}",
    )
    _assert_persisted_read_surfaces(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        expected_portfolio_id=scenario.portfolio_id,
        created_by_filter="live-parity-validator",
        current_version_no=related_version_no,
        expected_state="EXECUTED",
        expected_report_status="UNAVAILABLE",
    )
    return (
        scenario.portfolio_id,
        related_version_no,
        "EXECUTED",
        handoff["handoff_status"],
        "UNAVAILABLE",
    )


def _advisor_review_narrative_request(
    *,
    generation_mode: str = "DETERMINISTIC_TEMPLATE",
) -> dict[str, Any]:
    return {
        "audience": "ADVISOR_REVIEW",
        "jurisdiction": "SG",
        "client_audience": "ADVISOR_REVIEW",
        "sections": ["EXECUTIVE_SUMMARY", "RISK_AND_CONCENTRATION"],
        "requested_by": "live-parity-validator",
        "generation_mode": generation_mode,
    }


def _assert_live_proposal_narrative_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> LiveProposalNarrativeSnapshot:
    started = time.perf_counter()
    created = _create_stateful_proposal(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator-narrative",
        narrative_request=_advisor_review_narrative_request(),
    )
    proposal_id = str(created["proposal"]["proposal_id"])
    version = cast(dict[str, Any], created["version"])
    version_no = int(version["version_no"])
    version_artifact = cast(dict[str, Any], version["artifact"])
    narrative = cast(dict[str, Any], version_artifact["proposal_narrative"])
    _assert(
        narrative["generation_mode"] == "DETERMINISTIC_TEMPLATE",
        f"{proposal_id}: deterministic narrative generation mode drifted: {narrative}",
    )
    _assert(
        summarize := [
            item
            for item in cast(list[dict[str, Any]], narrative["guardrail_results"])
            if item.get("status") == "PASS"
        ],
        f"{proposal_id}: deterministic narrative did not emit pass guardrail evidence",
    )
    _assert(bool(summarize), f"{proposal_id}: guardrail pass posture missing")

    read_body = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/narrative",
        expected_status=200,
    )
    regeneration_body = _post_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/narrative/regenerate"
        ),
        expected_status=200,
        json_body={
            "requested_by": "live-parity-validator",
            "reason": "Live validation of non-persistent regeneration posture.",
            "sections": ["EXECUTIVE_SUMMARY"],
        },
    )
    _assert(
        cast(dict[str, Any], regeneration_body["regeneration_posture"])["persistence_status"]
        == "NOT_PERSISTED_REVIEW_REQUIRED",
        f"{proposal_id}: regeneration unexpectedly persisted candidate narrative",
    )
    reread_body = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/narrative",
        expected_status=200,
    )
    _assert(
        reread_body["proposal_narrative"]["narrative_id"] == narrative["narrative_id"],
        f"{proposal_id}: regeneration mutated persisted narrative",
    )
    review_body = _post_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/narrative/review"
        ),
        expected_status=200,
        json_body={
            "action": "APPROVE",
            "reviewed_by": "live-parity-validator",
            "reason": "Evidence-grounded advisor-review narrative live validation.",
            "client_ready_release_requested": False,
        },
        headers={"Idempotency-Key": f"live-narrative-review-{uuid.uuid4().hex}"},
    )
    _assert(
        review_body["narrative_review"]["review_state"] == "APPROVED_FOR_ADVISOR_USE",
        f"{proposal_id}: narrative review did not approve advisor-use posture",
    )
    _assert(
        review_body["narrative_review"]["client_ready_status"] == "NOT_REQUESTED",
        f"{proposal_id}: narrative review incorrectly promoted client-ready posture",
    )
    replay_body = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/replay-evidence",
        expected_status=200,
    )
    _assert(
        cast(dict[str, Any], replay_body["evidence"])["proposal_narrative"]["narrative_id"]
        == narrative["narrative_id"],
        f"{proposal_id}: replay evidence lost proposal narrative identity",
    )
    _assert(
        cast(dict[str, Any], replay_body["evidence"])["proposal_narrative_review"][
            "source_narrative_hash"
        ]
        == review_body["narrative_review"]["source_narrative_hash"],
        f"{proposal_id}: replay evidence lost narrative review source hash",
    )

    capabilities = _get_json(
        client,
        url=f"{advise_base_url}/platform/capabilities",
        expected_status=200,
    )
    report_feature = _feature_by_key(capabilities, "advisory.proposals.reporting")
    report_response = client.post(
        f"{advise_base_url}/advisory/proposals/{proposal_id}/report-requests",
        json={
            "report_type": "CLIENT_PROPOSAL_SUMMARY",
            "requested_by": "live-parity-validator",
            "related_version_no": version_no,
            "include_execution_summary": False,
            "include_reviewed_narrative": True,
        },
    )
    report_body: dict[str, Any] | None
    report_status: str
    if report_feature["operational_ready"]:
        _assert(
            report_response.status_code == 200,
            (
                f"{proposal_id}: expected reviewed narrative report package success, got "
                f"{report_response.status_code} body={report_response.text}"
            ),
        )
        report_body = cast(dict[str, Any], report_response.json())
        report_status = str(report_body["status"])
        package = cast(dict[str, Any], report_body["explanation"])["proposal_narrative_package"]
        _assert(
            package["package_status"] == "INCLUDED_REVIEWED_NARRATIVE",
            f"{proposal_id}: reviewed narrative package was not included",
        )
        _assert(
            package["review_state"] == "APPROVED_FOR_ADVISOR_USE",
            f"{proposal_id}: reviewed narrative package lost review state",
        )
    else:
        _assert(
            report_response.status_code == 503,
            (
                f"{proposal_id}: expected reviewed narrative report package degraded 503, got "
                f"{report_response.status_code} body={report_response.text}"
            ),
        )
        report_body = None
        report_status = "UNAVAILABLE"

    ai_assisted_status, ai_fallback_reason = _assert_ai_assisted_narrative_when_enabled(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return extract_live_narrative_snapshot(
        proposal_id=proposal_id,
        version_no=version_no,
        created_version=version,
        read_body=read_body,
        regeneration_body=regeneration_body,
        review_body=review_body,
        replay_body=replay_body,
        report_status=report_status,
        report_body=report_body,
        latency_ms=latency_ms,
        ai_assisted_status=ai_assisted_status,
        ai_fallback_reason=ai_fallback_reason,
    )


def _assert_ai_assisted_narrative_when_enabled(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> tuple[str, str | None]:
    if os.getenv("LOTUS_ADVISE_VALIDATE_AI_ASSISTED_NARRATIVE") != "1":
        return "SKIPPED_NOT_ENABLED", None

    created = _create_stateful_proposal(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator-ai-narrative",
        narrative_request=_advisor_review_narrative_request(generation_mode="AI_ASSISTED_DRAFT"),
    )
    version = cast(dict[str, Any], created["version"])
    narrative = cast(
        dict[str, Any],
        cast(dict[str, Any], version["artifact"])["proposal_narrative"],
    )
    _assert(
        narrative["generation_mode"] in {"AI_ASSISTED_DRAFT", "DETERMINISTIC_TEMPLATE"},
        f"AI-assisted narrative returned unsupported generation mode {narrative}",
    )
    _assert(
        isinstance(narrative.get("sections"), list) and narrative["sections"],
        "AI-assisted narrative proof returned no narrative sections",
    )
    return extract_ai_lineage_status(narrative)


def _assert_live_proposal_memo_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> LiveProposalMemoSnapshot:
    started = time.perf_counter()
    created = _create_stateful_proposal(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator-memo",
    )
    proposal_id = str(created["proposal"]["proposal_id"])
    version_no = int(cast(dict[str, Any], created["version"])["version_no"])
    memo_body = _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/memo",
        expected_status=200,
        json_body={
            "created_by": "live-parity-validator",
            "lifecycle_status": "DRAFT",
            "reason": {"purpose": "RFC-0024 Slice 13 live memo implementation proof"},
        },
        headers={"Idempotency-Key": f"live-memo-create-{uuid.uuid4().hex}"},
    )
    memo_hash = str(memo_body["memo_hash"])
    _assert(
        memo_hash.startswith("sha256:"),
        f"{proposal_id}: memo hash was not canonical sha256: {memo_hash}",
    )
    read_body = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/memo",
        expected_status=200,
    )
    _assert(
        read_body["memo_hash"] == memo_hash,
        f"{proposal_id}: memo read lost hash continuity",
    )
    projection_body = _get_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/memo/projection?audience=ADVISOR"
        ),
        expected_status=200,
    )
    projection_posture = cast(dict[str, Any], projection_body["projection_posture"])
    _assert(
        projection_posture["client_ready_publication"] == "BLOCKED",
        f"{proposal_id}: memo projection promoted client-ready publication",
    )
    _assert(
        bool(projection_body["sections"]),
        f"{proposal_id}: advisor memo projection returned no sections",
    )

    stale_hash_response = client.post(
        f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/memo/review",
        json={
            "action": "APPROVE_FOR_ADVISOR_USE",
            "reviewed_by": "live-parity-validator",
            "reason": "Validate stale hash rejection.",
            "source_memo_hash": "sha256:stale",
        },
        headers={"Idempotency-Key": f"live-memo-stale-review-{uuid.uuid4().hex}"},
    )
    _assert(
        stale_hash_response.status_code == 422,
        f"{proposal_id}: stale memo hash review was not rejected",
    )
    stale_hash_block_status = str(cast(dict[str, Any], stale_hash_response.json()).get("detail"))

    client_ready_release_response = client.post(
        f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/memo/review",
        json={
            "action": "APPROVE_FOR_ADVISOR_USE",
            "reviewed_by": "live-parity-validator",
            "reason": "Validate client-ready memo review remains blocked.",
            "source_memo_hash": memo_hash,
            "client_ready_release_requested": True,
        },
        headers={"Idempotency-Key": f"live-memo-client-ready-review-{uuid.uuid4().hex}"},
    )
    _assert(
        client_ready_release_response.status_code == 422,
        f"{proposal_id}: client-ready memo review request was not blocked",
    )
    client_ready_release_block_status = str(
        cast(dict[str, Any], client_ready_release_response.json()).get("detail")
    )

    review_body = _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/memo/review",
        expected_status=200,
        json_body={
            "action": "APPROVE_FOR_ADVISOR_USE",
            "reviewed_by": "live-parity-validator",
            "reason": "Hash-continuous advisor-use memo proof.",
            "source_memo_hash": memo_hash,
            "client_ready_release_requested": False,
        },
        headers={"Idempotency-Key": f"live-memo-review-{uuid.uuid4().hex}"},
    )
    review_reason = cast(dict[str, Any], review_body["review_event"])["reason"]
    _assert(
        cast(dict[str, Any], review_reason)["review_action"] == "APPROVE_FOR_ADVISOR_USE",
        f"{proposal_id}: memo review did not record advisor-use approval",
    )

    client_ready_document_response = client.post(
        (
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/memo/report-packages"
        ),
        json={
            "requested_by": "live-parity-validator",
            "source_memo_hash": memo_hash,
            "client_ready_document_requested": True,
            "reason": {"purpose": "Validate client-ready memo document block"},
        },
        headers={"Idempotency-Key": f"live-memo-client-ready-report-{uuid.uuid4().hex}"},
    )
    _assert(
        client_ready_document_response.status_code == 422,
        f"{proposal_id}: client-ready memo report request was not blocked",
    )
    client_ready_document_block_status = str(
        cast(dict[str, Any], client_ready_document_response.json()).get("detail")
    )

    report_response = client.post(
        (
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/memo/report-packages"
        ),
        json={
            "requested_by": "live-parity-validator",
            "source_memo_hash": memo_hash,
            "requested_output_formats": ["pdf"],
            "client_ready_document_requested": False,
            "reason": {"purpose": "advisor-use memo report package live proof"},
        },
        headers={"Idempotency-Key": f"live-memo-report-{uuid.uuid4().hex}"},
    )
    report_body: dict[str, Any] | None
    report_status: str
    report_degraded_reason: str | None
    if report_response.status_code == 200:
        report_body = cast(dict[str, Any], report_response.json())
        report_status = str(cast(dict[str, Any], report_body["report"])["status"])
        report_degraded_reason = None
    else:
        _assert(
            report_response.status_code == 503,
            (
                f"{proposal_id}: expected memo report package success or degraded 503, got "
                f"{report_response.status_code} body={report_response.text}"
            ),
        )
        report_body = None
        report_status = "UNAVAILABLE"
        report_degraded_reason = str(cast(dict[str, Any], report_response.json()).get("detail"))

    ai_body = _post_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/memo/ai-commentary"
        ),
        expected_status=200,
        json_body={
            "requested_by": "live-parity-validator",
            "source_memo_hash": memo_hash,
            "requested_sections": ["EXECUTIVE_SUMMARY", "LIMITATIONS_AND_DISCLOSURES"],
            "reason": {"purpose": "review-gated memo commentary live proof"},
        },
        headers={"Idempotency-Key": f"live-memo-ai-{uuid.uuid4().hex}"},
    )
    commentary = cast(dict[str, Any], ai_body["commentary"])
    _assert(
        commentary["authoritative_for_memo_status"] is False,
        f"{proposal_id}: AI commentary became authoritative for memo status",
    )
    _assert(
        commentary["review_required"] is True,
        f"{proposal_id}: AI commentary did not retain review-required posture",
    )

    lineage_body = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/memos/lineage",
        expected_status=200,
    )
    _assert(lineage_body["memo_count"] >= 1, f"{proposal_id}: memo lineage was empty")
    replay_body = _get_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/memo/replay-evidence"
        ),
        expected_status=200,
    )
    replay_hashes = cast(dict[str, Any], replay_body["hashes"])
    _assert(
        replay_hashes["memo_hash"] == memo_hash,
        f"{proposal_id}: memo replay evidence lost memo hash continuity",
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return extract_live_memo_snapshot(
        proposal_id=proposal_id,
        version_no=version_no,
        memo_body=memo_body,
        projection_body=projection_body,
        review_body=review_body,
        report_status=report_status,
        report_body=report_body,
        ai_body=ai_body,
        lineage_body=lineage_body,
        replay_body=replay_body,
        stale_hash_block_status=stale_hash_block_status,
        client_ready_release_block_status=client_ready_release_block_status,
        client_ready_document_block_status=client_ready_document_block_status,
        report_degraded_reason=report_degraded_reason,
        latency_ms=latency_ms,
    )


def _create_live_policy_evaluation(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """Create a policy evaluation and return its creation body, record, and hashes."""
    ensure_sg_policy_pack_active(
        client,
        advise_base_url=advise_base_url,
        get_json=_get_json,
        post_json=_post_json,
    )
    proposal_id = f"pp_live_policy_{uuid.uuid4().hex[:10]}"
    proposal_version_id = f"ppv_live_policy_{uuid.uuid4().hex[:10]}"
    created_body = _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
        f"{proposal_version_id}/policy-evaluations",
        expected_status=200,
        json_body={
            "policy_pack_id": "SG_PRIVATE_BANKING_REFERENCE",
            "policy_version": "2026.05",
            "created_by": "live-parity-validator-policy",
            "evidence_bundle": live_policy_evidence_bundle(scenario=scenario),
            "reason": {"purpose": "RFC-0025 Slice 14 live policy implementation proof"},
        },
        headers={"Idempotency-Key": f"live-policy-eval-{uuid.uuid4().hex}"},
    )
    record = cast(dict[str, Any], created_body["record"])
    evaluation_id = str(record["evaluation_id"])
    evaluation_hash = str(record["evaluation_hash"])
    _assert(
        evaluation_hash.startswith("sha256:"),
        f"{evaluation_id}: policy evaluation hash was not canonical sha256",
    )
    _assert(
        bool(record["approval_dependencies"])
        and bool(record["disclosure_requirements"])
        and bool(record["consent_requirements"]),
        f"{evaluation_id}: policy evaluation did not expose review requirements",
    )
    return created_body, record, evaluation_id, evaluation_hash


def _assert_live_policy_read_surfaces(
    client: httpx.Client,
    *,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Verify persisted policy evaluation, queue, workflow, and sign-off read surfaces."""
    read_body = _get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}",
        expected_status=200,
    )
    _assert(
        read_body["evaluation_hash"] == evaluation_hash,
        f"{evaluation_id}: policy read lost hash continuity",
    )
    queue_body = _get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/review-queue",
        expected_status=200,
    )
    _assert(
        any(item.get("evaluation_id") == evaluation_id for item in queue_body["items"]),
        f"{evaluation_id}: policy review queue omitted finalized evaluation",
    )
    workflow_body = _get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/workflow",
        expected_status=200,
    )
    _assert(
        workflow_body["client_ready_publication"] == "BLOCKED",
        f"{evaluation_id}: policy workflow promoted client-ready publication",
    )
    sign_off_package = _get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/sign-off-package",
        expected_status=200,
    )
    _assert(
        sign_off_package["evaluation"]["evaluation_id"] == evaluation_id,
        f"{evaluation_id}: sign-off package lost evaluation identity",
    )
    return read_body, queue_body, workflow_body


def _assert_live_policy_pre_sign_off_guards(
    client: httpx.Client,
    *,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
    scenario: PortfolioParityScenario,
) -> tuple[str, str]:
    """Verify stale-hash and client-ready publication requests remain blocked."""
    stale_hash_response = client.post(
        f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/sign-off-decisions",
        json={
            "actor_id": "policy_checker_live",
            "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
            "source_evaluation_hash": "sha256:stale",
        },
        headers={"Idempotency-Key": f"live-policy-stale-signoff-{uuid.uuid4().hex}"},
    )
    _assert(
        stale_hash_response.status_code == 422,
        f"{evaluation_id}: stale policy hash sign-off was not rejected",
    )
    stale_hash_block_status = str(cast(dict[str, Any], stale_hash_response.json()).get("detail"))

    client_ready_document_response = client.post(
        f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/report-packages",
        json={
            "requested_by": "policy_checker_live",
            "portfolio_id": scenario.portfolio_id,
            "source_evaluation_hash": evaluation_hash,
            "requested_output_formats": ["pdf"],
            "client_ready_document_requested": True,
        },
        headers={"Idempotency-Key": f"live-policy-client-ready-report-{uuid.uuid4().hex}"},
    )
    _assert(
        client_ready_document_response.status_code == 422,
        f"{evaluation_id}: client-ready policy document request was not blocked",
    )
    client_ready_document_block_status = str(
        cast(dict[str, Any], client_ready_document_response.json()).get("detail")
    )
    return stale_hash_block_status, client_ready_document_block_status


def _sign_off_live_policy_evaluation(
    client: httpx.Client,
    *,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Sign off the policy evaluation after satisfying its recorded requirements."""
    sign_off_body = _post_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/sign-off-decisions",
        expected_status=200,
        json_body={
            "actor_id": "policy_checker_live",
            "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
            "source_evaluation_hash": evaluation_hash,
            "resolved_approval_dependencies": record["approval_dependencies"],
            "satisfied_disclosure_requirements": record["disclosure_requirements"],
            "satisfied_consent_requirements": record["consent_requirements"],
            "reason": {"purpose": "live policy sign-off proof"},
        },
        headers={"Idempotency-Key": f"live-policy-signoff-{uuid.uuid4().hex}"},
    )
    _assert(
        cast(dict[str, Any], sign_off_body["workflow"])["sign_off_status"] == "SIGNED_OFF",
        f"{evaluation_id}: policy sign-off did not close requirements",
    )
    return sign_off_body


def _request_live_policy_ai_evidence(
    client: httpx.Client,
    *,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
) -> tuple[str, dict[str, Any]]:
    """Verify forbidden policy AI actions are blocked and bounded evidence is non-authoritative."""
    forbidden_ai_response = client.post(
        f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/ai-evidence",
        json={
            "requested_by": "policy_checker_live",
            "source_evaluation_hash": evaluation_hash,
            "requested_actions": ["APPROVE_POLICY"],
        },
        headers={"Idempotency-Key": f"live-policy-forbidden-ai-{uuid.uuid4().hex}"},
    )
    _assert(
        forbidden_ai_response.status_code == 422,
        f"{evaluation_id}: forbidden policy AI action was not rejected",
    )
    forbidden_ai_action_block_status = str(
        cast(dict[str, Any], forbidden_ai_response.json()).get("detail")
    )

    ai_body = _post_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/ai-evidence",
        expected_status=200,
        json_body={
            "requested_by": "policy_checker_live",
            "source_evaluation_hash": evaluation_hash,
            "requested_actions": [
                "SUMMARIZE_POLICY_POSTURE",
                "EXPLAIN_OPEN_REQUIREMENTS",
            ],
            "reason": {"purpose": "bounded policy AI evidence live proof"},
        },
        headers={"Idempotency-Key": f"live-policy-ai-{uuid.uuid4().hex}"},
    )
    policy_evidence = cast(dict[str, Any], ai_body["policy_evidence"])
    _assert(
        policy_evidence["authoritative_for_policy_status"] is False,
        f"{evaluation_id}: AI evidence became authoritative for policy status",
    )
    _assert(
        policy_evidence["human_review_required"] is True,
        f"{evaluation_id}: AI evidence did not preserve human review posture",
    )
    _assert(
        cast(dict[str, Any], policy_evidence["redaction_profile"])["raw_source_evidence_included"]
        is False,
        f"{evaluation_id}: AI evidence included raw source evidence",
    )
    return forbidden_ai_action_block_status, ai_body


def _assert_live_policy_lineage_and_replay(
    client: httpx.Client,
    *,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
    source_evidence_hash: str,
    policy_content_hash: str,
    scenario: PortfolioParityScenario,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify hash-backed lineage and deterministic replay continuity."""
    lineage_body = _get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/lineage",
        expected_status=200,
    )
    lineage_posture = cast(dict[str, Any], lineage_body["lineage_posture"])
    _assert(
        lineage_body["evaluation_hash"] == evaluation_hash
        and lineage_body["source_evidence_hash"] == source_evidence_hash
        and lineage_body["policy_content_hash"] == policy_content_hash
        and bool(lineage_body["rule_result_hashes"])
        and bool(lineage_body["source_refs"])
        and bool(lineage_body["audit_events"])
        and lineage_posture["client_ready_publication"] == "BLOCKED",
        f"{evaluation_id}: policy lineage did not retain complete hash-backed evidence",
    )
    replay_body = _post_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/replay",
        expected_status=200,
        json_body={"evidence_bundle": live_policy_evidence_bundle(scenario=scenario)},
    )
    _assert(
        cast(dict[str, Any], replay_body["hash_comparison"])["evaluation_hash_matches"] is True,
        f"{evaluation_id}: replay lost evaluation hash continuity",
    )
    return lineage_body, replay_body


def _assert_live_policy_evaluation_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> LivePolicyEvaluationSnapshot:
    started = time.perf_counter()
    created_body, record, evaluation_id, evaluation_hash = _create_live_policy_evaluation(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
    )
    read_body, queue_body, workflow_body = _assert_live_policy_read_surfaces(
        client,
        advise_base_url=advise_base_url,
        evaluation_id=evaluation_id,
        evaluation_hash=evaluation_hash,
    )
    stale_hash_block_status, client_ready_document_block_status = (
        _assert_live_policy_pre_sign_off_guards(
            client,
            advise_base_url=advise_base_url,
            evaluation_id=evaluation_id,
            evaluation_hash=evaluation_hash,
            scenario=scenario,
        )
    )
    sign_off_body = _sign_off_live_policy_evaluation(
        client,
        advise_base_url=advise_base_url,
        evaluation_id=evaluation_id,
        evaluation_hash=evaluation_hash,
        record=record,
    )
    report_status, report_body, report_degraded_reason = request_live_policy_report(
        client,
        advise_base_url=advise_base_url,
        evaluation_id=evaluation_id,
        evaluation_hash=evaluation_hash,
        scenario=scenario,
        assert_condition=_assert,
    )
    forbidden_ai_action_block_status, ai_body = _request_live_policy_ai_evidence(
        client,
        advise_base_url=advise_base_url,
        evaluation_id=evaluation_id,
        evaluation_hash=evaluation_hash,
    )
    lineage_body, replay_body = _assert_live_policy_lineage_and_replay(
        client,
        advise_base_url=advise_base_url,
        evaluation_id=evaluation_id,
        evaluation_hash=evaluation_hash,
        source_evidence_hash=str(record["source_evidence_hash"]),
        policy_content_hash=str(record["policy_content_hash"]),
        scenario=scenario,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return extract_live_policy_evaluation_snapshot(
        created_body=created_body,
        read_body=read_body,
        queue_body=queue_body,
        workflow_body=workflow_body,
        sign_off_body=sign_off_body,
        report_status=report_status,
        report_body=report_body,
        ai_body=ai_body,
        lineage_body=lineage_body,
        replay_body=replay_body,
        stale_hash_block_status=stale_hash_block_status,
        client_ready_document_block_status=client_ready_document_block_status,
        forbidden_ai_action_block_status=forbidden_ai_action_block_status,
        report_degraded_reason=report_degraded_reason,
        latency_ms=latency_ms,
    )


def _assert_async_lifecycle_read_surfaces(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> tuple[str, int, str]:
    async_created = _submit_async_create(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator-async-lifecycle",
    )
    async_create_result = _wait_for_async_success(
        client,
        advise_base_url=advise_base_url,
        operation_id=str(async_created["operation_id"]),
        expected_type="CREATE_PROPOSAL",
    )
    _assert_async_operation_surfaces(
        client,
        advise_base_url=advise_base_url,
        accepted_body=async_created,
        expected_type="CREATE_PROPOSAL",
        result_body=async_create_result,
    )
    async_proposal_id = str(async_create_result["proposal"]["proposal_id"])
    async_portfolio_id = str(async_create_result["proposal"]["portfolio_id"])
    async_version_no = int(async_create_result["version"]["version_no"])

    async_version_created = _submit_async_version(
        client,
        advise_base_url=advise_base_url,
        proposal_id=async_proposal_id,
        scenario=scenario,
        created_by="live-parity-validator-async-lifecycle-version",
        expected_current_version_no=async_version_no,
    )
    async_version_result = _wait_for_async_success(
        client,
        advise_base_url=advise_base_url,
        operation_id=str(async_version_created["operation_id"]),
        expected_type="CREATE_PROPOSAL_VERSION",
    )
    _assert_async_operation_surfaces(
        client,
        advise_base_url=advise_base_url,
        accepted_body=async_version_created,
        expected_type="CREATE_PROPOSAL_VERSION",
        result_body=async_version_result,
    )
    current_version_no = int(async_version_result["proposal"]["current_version_no"])
    _assert(
        current_version_no == async_version_no + 1,
        f"{async_proposal_id}: async lifecycle version did not increment current_version_no",
    )
    _promote_to_execution_ready(
        client,
        advise_base_url=advise_base_url,
        proposal_id=async_proposal_id,
        related_version_no=current_version_no,
    )
    handoff = _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{async_proposal_id}/execution-handoffs",
        expected_status=200,
        json_body={
            "actor_id": "ops_async_001",
            "execution_provider": "lotus-manage",
            "expected_state": "EXECUTION_READY",
            "related_version_no": current_version_no,
            "external_request_id": f"oms_async_req_{uuid.uuid4().hex[:10]}",
            "notes": {"channel": "OMS", "priority": "STANDARD"},
        },
        headers={"Idempotency-Key": f"live-async-lifecycle-handoff-{uuid.uuid4().hex}"},
    )
    _assert(
        handoff["handoff_status"] == "REQUESTED",
        f"{async_proposal_id}: async lifecycle handoff did not start in REQUESTED",
    )
    executed = _post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{async_proposal_id}/execution-updates",
        expected_status=200,
        json_body={
            "update_id": f"async_exec_done_{uuid.uuid4().hex[:10]}",
            "actor_id": "lotus-manage",
            "execution_request_id": handoff["execution_request_id"],
            "execution_provider": "lotus-manage",
            "update_status": "EXECUTED",
            "related_version_no": current_version_no,
            "external_execution_id": f"oms_async_fill_{uuid.uuid4().hex[:10]}",
            "occurred_at": _utc_iso_after(seconds=2),
            "details": {"filled_quantity": "100"},
        },
    )
    _assert(
        executed["handoff_status"] == "EXECUTED",
        f"{async_proposal_id}: async lifecycle execution did not reach EXECUTED",
    )
    capabilities = _get_json(
        client,
        url=f"{advise_base_url}/platform/capabilities",
        expected_status=200,
    )
    report_feature = _feature_by_key(capabilities, "advisory.proposals.reporting")
    report_response = client.post(
        f"{advise_base_url}/advisory/proposals/{async_proposal_id}/report-requests",
        json={
            "report_type": "CLIENT_PROPOSAL_SUMMARY",
            "requested_by": "advisor_async_1",
            "related_version_no": current_version_no,
            "include_execution_summary": True,
        },
    )
    if report_feature["operational_ready"]:
        _assert(
            report_response.status_code == 200,
            (
                f"{async_proposal_id}: expected lotus-report ready path for async lifecycle, "
                f"got {report_response.status_code} body={report_response.text}"
            ),
        )
    else:
        _assert(
            report_response.status_code == 503,
            (
                f"{async_proposal_id}: expected lotus-report degraded 503 for async lifecycle, "
                f"got {report_response.status_code} body={report_response.text}"
            ),
        )
    _assert_persisted_read_surfaces(
        client,
        advise_base_url=advise_base_url,
        proposal_id=async_proposal_id,
        expected_portfolio_id=async_portfolio_id,
        created_by_filter="live-parity-validator-async-lifecycle",
        current_version_no=current_version_no,
        expected_state="EXECUTED",
        expected_report_status="READY" if report_feature["operational_ready"] else "UNAVAILABLE",
    )
    return async_portfolio_id, current_version_no, "EXECUTED"


def _assert_new_version_requires_fresh_approvals(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> None:
    created = _create_stateful_proposal(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator-approval-reset",
    )
    proposal_id = str(created["proposal"]["proposal_id"])
    _promote_to_execution_ready(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        related_version_no=int(created["version"]["version_no"]),
    )

    version_created = _create_stateful_version(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        scenario=scenario,
        created_by="live-parity-validator-approval-reset-version",
        expected_current_version_no=1,
    )
    proposal = cast(dict[str, Any], version_created["proposal"])
    _assert(
        int(proposal["current_version_no"]) == 2 and proposal["current_state"] == "DRAFT",
        f"{proposal_id}: new version did not reset lifecycle state after prior approvals",
    )

    handoff_response = client.post(
        f"{advise_base_url}/advisory/proposals/{proposal_id}/execution-handoffs",
        json={
            "actor_id": "ops_reset_001",
            "execution_provider": "lotus-manage",
            "expected_state": "EXECUTION_READY",
            "related_version_no": 2,
            "external_request_id": f"oms_req_reset_{uuid.uuid4().hex[:10]}",
            "notes": {"channel": "OMS"},
        },
    )
    _assert(
        handoff_response.status_code == 409,
        (
            f"{proposal_id}: expected stale-approval handoff conflict, got "
            f"{handoff_response.status_code} body={handoff_response.text}"
        ),
    )
    detail = cast(dict[str, Any], handoff_response.json()).get("detail", "")
    _assert(
        "STATE_CONFLICT" in str(detail) and "expected_state mismatch" in str(detail),
        f"{proposal_id}: stale-approval conflict detail unexpected {detail}",
    )


def _assert_workspace_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> tuple[str, str, str, str]:
    create_body = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces",
        expected_status=201,
        json_body={
            "workspace_name": f"Live parity {scenario.portfolio_id}",
            "created_by": "live-parity-validator",
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": scenario.portfolio_id,
                "as_of": scenario.as_of_date,
            },
        },
    )
    workspace = create_body["workspace"]
    workspace_id = str(workspace["workspace_id"])
    _assert(
        workspace["resolved_context"]["portfolio_id"] == scenario.portfolio_id,
        f"{scenario.portfolio_id}: workspace resolved wrong portfolio context",
    )

    evaluated = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces/{workspace_id}/evaluate",
        expected_status=200,
        json_body={},
    )
    latest_result = evaluated.get("latest_proposal_result")
    _assert(
        isinstance(latest_result, dict),
        f"{scenario.portfolio_id}: workspace evaluate missing proposal result",
    )
    latest_result_dict = cast(dict[str, Any], latest_result)
    _assert_authority_posture(scenario=scenario, proposal_body=latest_result_dict)

    saved = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces/{workspace_id}/save",
        expected_status=200,
        json_body={"saved_by": "live-parity-validator", "version_label": "live-parity-baseline"},
    )
    saved_version = saved["saved_version"]
    workspace_version_id = str(saved_version["workspace_version_id"])
    saved_risk_lens = saved_version["replay_evidence"].get("risk_lens")
    _assert(
        isinstance(saved_risk_lens, dict) and saved_risk_lens.get("source_service") == "lotus-risk",
        f"{scenario.portfolio_id}: workspace saved replay evidence missing lotus-risk lens",
    )

    handoff = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces/{workspace_id}/handoff",
        expected_status=200,
        json_body={"handoff_by": "live-parity-validator"},
        headers={"Idempotency-Key": f"live-workspace-handoff-{uuid.uuid4().hex}"},
    )
    _assert(
        handoff["handoff_action"] == "CREATED_PROPOSAL",
        f"{scenario.portfolio_id}: unexpected workspace handoff action {handoff['handoff_action']}",
    )
    version = handoff["proposal"]["version"]
    proposal = handoff["proposal"]["proposal"]
    proposal_result = version["proposal_result"]
    _assert_authority_posture(scenario=scenario, proposal_body=proposal_result)

    workspace_replay = _request_json(
        client,
        method="GET",
        url=(
            f"{advise_base_url}/advisory/workspaces/{workspace_id}/saved-versions/"
            f"{workspace_version_id}/replay-evidence"
        ),
        expected_status=200,
    )
    proposal_replay = _request_json(
        client,
        method="GET",
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal['proposal_id']}/versions/"
            f"{version['version_no']}/replay-evidence"
        ),
        expected_status=200,
    )
    _assert(
        workspace_replay["evidence"]["risk_lens"]["source_service"] == "lotus-risk",
        f"{scenario.portfolio_id}: workspace replay evidence missing lotus-risk source",
    )
    _assert(
        proposal_replay["evidence"]["risk_lens"]["source_service"] == "lotus-risk",
        f"{scenario.portfolio_id}: proposal replay evidence missing lotus-risk source",
    )
    _assert(
        workspace_replay["subject"]["proposal_id"] == proposal["proposal_id"],
        f"{scenario.portfolio_id}: workspace replay subject missing proposal linkage",
    )
    _assert(
        proposal_replay["continuity"]["workspace_version_id"] == workspace_version_id,
        f"{scenario.portfolio_id}: proposal replay continuity missing workspace version linkage",
    )
    _assert(
        workspace_replay["hashes"]["evaluation_request_hash"]
        == proposal_replay["hashes"]["evaluation_request_hash"],
        f"{scenario.portfolio_id}: workspace/proposal replay hashes diverged after handoff",
    )

    first_rationale = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces/{workspace_id}/assistant/rationale",
        expected_status=200,
        json_body={
            "requested_by": "live-parity-validator",
            "instruction": "Summarize the evaluated workspace rationale for review.",
        },
    )
    second_rationale = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces/{workspace_id}/assistant/rationale",
        expected_status=200,
        json_body={
            "requested_by": "live-parity-validator",
            "instruction": "Refresh the rationale to produce a replacement review run.",
        },
    )
    first_run = _assert_workspace_rationale_response(
        scenario=scenario,
        workspace_id=workspace_id,
        response_body=first_rationale,
    )
    second_run = _assert_workspace_rationale_response(
        scenario=scenario,
        workspace_id=workspace_id,
        response_body=second_rationale,
    )
    initial_run_id = str(first_run["run_id"])
    replacement_run_id = str(second_run["run_id"])
    _assert(
        initial_run_id != replacement_run_id,
        (
            f"{scenario.portfolio_id}: workspace rationale replacement run did not "
            "produce a new run id"
        ),
    )

    review_action = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces/{workspace_id}/assistant/rationale/review-actions",
        expected_status=200,
        json_body={
            "run_id": initial_run_id,
            "action_type": "SUPERSEDE",
            "reviewed_by": "live-parity-validator",
            "reason": "Replacement rationale run supersedes the earlier draft.",
            "replacement_run_id": replacement_run_id,
        },
    )
    review_state, supportability_status = _assert_workspace_rationale_review_action(
        scenario=scenario,
        initial_run_id=initial_run_id,
        replacement_run_id=replacement_run_id,
        review_action=review_action,
    )
    return (
        initial_run_id,
        replacement_run_id,
        review_state,
        supportability_status,
    )


def _assert_changed_state_workspace_risk_parity(
    client: httpx.Client,
    *,
    advise_base_url: str,
    core_query_base_url: str,
    risk_base_url: str,
    scenario: PortfolioParityScenario,
    security_id: str | None = None,
) -> str:
    positions = _query_live_positions(
        client,
        core_query_base_url=core_query_base_url,
        portfolio_id=scenario.portfolio_id,
        as_of_date=scenario.as_of_date,
    )
    selected_security_id = security_id or _select_changed_state_security(positions)
    create_body = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces",
        expected_status=201,
        json_body={
            "workspace_name": f"Live risk delta {scenario.portfolio_id}",
            "created_by": "live-parity-validator",
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": scenario.portfolio_id,
                "as_of": scenario.as_of_date,
            },
        },
    )
    workspace_id = str(create_body["workspace"]["workspace_id"])
    drafted = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces/{workspace_id}/draft-actions",
        expected_status=200,
        json_body={
            "actor_id": "live-parity-validator",
            "action_type": "ADD_TRADE",
            "trade": {
                "intent_type": "SECURITY_TRADE",
                "side": "BUY",
                "instrument_id": selected_security_id,
                "quantity": "1",
            },
        },
    )
    latest_result = cast(dict[str, Any], drafted["workspace"]["latest_proposal_result"])
    _assert_authority_posture(scenario=scenario, proposal_body=latest_result)
    simulation_changes = _security_trade_changes_from_proposal_body(latest_result)
    _assert(
        len(simulation_changes) == 1
        and simulation_changes[0]["security_id"] == selected_security_id,
        f"{scenario.portfolio_id}: changed-state workspace did not produce expected trade intent",
    )
    risk_proxy = cast(dict[str, Any], latest_result["explanation"]["risk_lens"]["risk_proxy"])
    _assert(
        any(abs(_decimal(risk_proxy[key])) > 0 for key in ("hhi_current", "hhi_proposed"))
        and abs(_decimal(risk_proxy["hhi_delta"])) > 0,
        f"{scenario.portfolio_id}: changed-state workspace risk lens did not produce a real delta",
    )
    direct_risk = _query_direct_concentration(
        client,
        risk_base_url=risk_base_url,
        portfolio_id=scenario.portfolio_id,
        as_of_date=scenario.as_of_date,
        reporting_currency=scenario.reporting_currency,
        simulation_changes=simulation_changes,
    )
    _assert_risk_parity(
        scenario=scenario,
        direct_risk=direct_risk,
        proposal_body=latest_result,
    )
    return selected_security_id


def _build_changed_state_simulate_request(
    *,
    portfolio_id: str,
    as_of_date: str,
    security_id: str,
    core_query_base_url: str,
    core_control_base_url: str,
) -> ProposalSimulateRequest:
    import src.api.main as api_main
    from src.core.workspace.models import WorkspaceStatefulInput
    from src.integrations.lotus_core.stateful_context import (
        enrich_stateful_simulate_request_for_trade_drafts,
    )

    os.environ["LOTUS_CORE_QUERY_BASE_URL"] = core_query_base_url
    os.environ["LOTUS_CORE_BASE_URL"] = core_control_base_url
    resolved_stateful_context = api_main.resolve_lotus_core_advisory_context(
        WorkspaceStatefulInput(portfolio_id=portfolio_id, as_of=as_of_date)
    )
    base_request = resolved_stateful_context.simulate_request.model_copy(deep=True)
    base_request.proposed_trades = [
        ProposedTrade(
            intent_type="SECURITY_TRADE",
            side="BUY",
            instrument_id=security_id,
            quantity=Decimal("1"),
        )
    ]
    return enrich_stateful_simulate_request_for_trade_drafts(
        simulate_request=base_request,
        as_of=resolved_stateful_context.resolved_context.as_of,
    )


def _assert_changed_state_workspace_allocation_parity(
    client: httpx.Client,
    *,
    advise_base_url: str,
    core_query_base_url: str,
    core_control_base_url: str,
    scenario: PortfolioParityScenario,
    security_id: str,
) -> None:
    create_body = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces",
        expected_status=201,
        json_body={
            "workspace_name": f"Live allocation delta {scenario.portfolio_id}",
            "created_by": "live-parity-validator",
            "input_mode": "stateful",
            "stateful_input": {
                "portfolio_id": scenario.portfolio_id,
                "as_of": scenario.as_of_date,
            },
        },
    )
    workspace_id = str(create_body["workspace"]["workspace_id"])
    drafted = _post_json(
        client,
        url=f"{advise_base_url}/advisory/workspaces/{workspace_id}/draft-actions",
        expected_status=200,
        json_body={
            "actor_id": "live-parity-validator",
            "action_type": "ADD_TRADE",
            "trade": {
                "intent_type": "SECURITY_TRADE",
                "side": "BUY",
                "instrument_id": security_id,
                "quantity": "1",
            },
        },
    )
    latest_result = cast(dict[str, Any], drafted["workspace"]["latest_proposal_result"])
    direct_request = _build_changed_state_simulate_request(
        portfolio_id=scenario.portfolio_id,
        as_of_date=scenario.as_of_date,
        security_id=security_id,
        core_query_base_url=core_query_base_url,
        core_control_base_url=core_control_base_url,
    )
    direct_response = client.post(
        f"{core_control_base_url}/integration/advisory/proposals/simulate-execution",
        json=direct_request.model_dump(mode="json"),
        headers={
            "X-Correlation-Id": f"live-direct-core-allocation-{uuid.uuid4().hex}",
            "X-Request-Hash": cast(
                str, hash_canonical_payload(direct_request.model_dump(mode="json"))
            ),
            "Idempotency-Key": f"live-direct-core-allocation-{uuid.uuid4().hex}",
            "X-Lotus-Contract-Version": "advisory-simulation.v1",
        },
    )
    _assert(
        direct_response.status_code == 200,
        (
            f"{scenario.portfolio_id}: direct lotus-core changed-state simulation failed "
            f"with {direct_response.status_code}, body={direct_response.text}"
        ),
    )
    direct_payload = cast(dict[str, Any], direct_response.json())
    _assert(
        _normalize_allocation_views(direct_payload["before"]["allocation_views"])
        == _normalize_allocation_views(latest_result["before"]["allocation_views"]),
        (
            f"{scenario.portfolio_id}: changed-state workspace before allocation diverged "
            "from direct lotus-core simulation"
        ),
    )
    _assert(
        _normalize_allocation_views(direct_payload["after_simulated"]["allocation_views"])
        == _normalize_allocation_views(latest_result["after_simulated"]["allocation_views"]),
        (
            f"{scenario.portfolio_id}: changed-state workspace after allocation diverged "
            "from direct lotus-core simulation"
        ),
    )


def _assert_persisted_read_surfaces(
    client: httpx.Client,
    *,
    advise_base_url: str,
    proposal_id: str,
    expected_portfolio_id: str,
    created_by_filter: str | None,
    current_version_no: int,
    expected_state: str,
    expected_report_status: str,
) -> None:
    list_query = (
        f"{advise_base_url}/advisory/proposals?portfolio_id={expected_portfolio_id}&limit=100"
    )
    if created_by_filter:
        list_query += f"&created_by={created_by_filter}"
    listed = _get_json(
        client,
        url=list_query,
        expected_status=200,
    )
    items = cast(list[dict[str, Any]], listed["items"])
    list_item = next(
        (item for item in items if str(item["proposal_id"]) == proposal_id),
        None,
    )
    _assert(
        isinstance(list_item, dict),
        f"{proposal_id}: proposal missing from list response for {expected_portfolio_id}",
    )
    list_item_dict = cast(dict[str, Any], list_item)

    detail = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}?include_evidence=false",
        expected_status=200,
    )
    version = _get_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{current_version_no}?include_evidence=false"
        ),
        expected_status=200,
    )
    timeline = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/workflow-events",
        expected_status=200,
    )
    lineage = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/lineage",
        expected_status=200,
    )
    approvals = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/approvals",
        expected_status=200,
    )
    delivery_summary = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/delivery-summary",
        expected_status=200,
    )
    delivery_history = _get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/delivery-events",
        expected_status=200,
    )

    _assert(
        str(list_item_dict["proposal_id"]) == str(detail["proposal"]["proposal_id"]) == proposal_id,
        f"{proposal_id}: list/detail proposal ids diverged",
    )
    _assert(
        str(detail["proposal"]["portfolio_id"]) == expected_portfolio_id,
        (
            f"{proposal_id}: detail endpoint returned wrong portfolio "
            f"{detail['proposal']['portfolio_id']}"
        ),
    )
    _assert(
        int(list_item_dict["current_version_no"])
        == int(detail["proposal"]["current_version_no"])
        == int(lineage["latest_version_no"])
        == current_version_no,
        f"{proposal_id}: current version diverged across list/detail/lineage",
    )
    _assert(
        str(list_item_dict["current_state"])
        == str(detail["proposal"]["current_state"])
        == str(timeline["current_state"])
        == str(delivery_summary["proposal"]["current_state"])
        == expected_state,
        f"{proposal_id}: current state diverged across read surfaces",
    )
    _assert(
        int(detail["current_version"]["version_no"])
        == int(version["version_no"])
        == current_version_no,
        f"{proposal_id}: detail/version endpoints diverged on current version",
    )
    detail_summary = cast(
        dict[str, Any],
        cast(dict[str, Any], detail["current_version"]["proposal_result"])[
            "proposal_decision_summary"
        ],
    )
    version_summary = cast(
        dict[str, Any],
        cast(dict[str, Any], version["proposal_result"])["proposal_decision_summary"],
    )
    _assert(
        detail_summary == version_summary,
        f"{proposal_id}: detail/version decision summaries diverged",
    )
    _assert(
        bool(detail_summary.get("decision_status"))
        and bool(detail_summary.get("primary_reason_code")),
        f"{proposal_id}: persisted decision summary omitted required posture fields",
    )
    _assert(
        isinstance(detail_summary.get("approval_requirements"), list),
        f"{proposal_id}: persisted decision summary omitted approval requirements list",
    )
    _assert(
        str(version["proposal_id"]) == proposal_id,
        f"{proposal_id}: version endpoint returned wrong proposal id",
    )
    _assert(
        int(lineage["version_count"]) == current_version_no,
        f"{proposal_id}: lineage version count did not match latest version",
    )
    lineage_versions = cast(list[dict[str, Any]], lineage["versions"])
    _assert(
        [int(item["version_no"]) for item in lineage_versions]
        == list(range(1, current_version_no + 1)),
        f"{proposal_id}: lineage version numbers were not contiguous and ordered",
    )
    _assert(
        bool(lineage["lineage_complete"]) is True,
        f"{proposal_id}: lineage unexpectedly incomplete",
    )
    _assert(
        list(lineage["missing_version_numbers"]) == [],
        f"{proposal_id}: lineage unexpectedly reported missing versions",
    )
    timeline_events = cast(list[dict[str, Any]], timeline["events"])
    delivery_events = cast(list[dict[str, Any]], delivery_history["events"])
    _assert(
        int(timeline["event_count"]) == len(timeline_events),
        f"{proposal_id}: timeline event_count mismatch",
    )
    _assert(
        int(delivery_history["event_count"]) == len(delivery_events),
        f"{proposal_id}: delivery history event_count mismatch",
    )
    _assert(
        len(delivery_events) > 0 and len(timeline_events) >= len(delivery_events),
        f"{proposal_id}: delivery history unexpectedly empty or larger than timeline",
    )
    created_event = next(
        (event for event in timeline_events if event["event_type"] == "CREATED"),
        None,
    )
    _assert(
        isinstance(created_event, dict) and created_event["related_version_no"] == 1,
        f"{proposal_id}: missing version-1 CREATED event in workflow timeline",
    )
    if current_version_no > 1:
        new_version_events = [
            event for event in timeline_events if event["event_type"] == "NEW_VERSION_CREATED"
        ]
        _assert(
            len(new_version_events) == current_version_no - 1
            and {
                int(event["related_version_no"])
                for event in cast(list[dict[str, Any]], new_version_events)
            }
            == set(range(2, current_version_no + 1)),
            f"{proposal_id}: workflow timeline lost version-creation events",
        )
    _assert(
        all(
            event["event_type"]
            in {
                "EXECUTION_REQUESTED",
                "EXECUTION_ACCEPTED",
                "EXECUTION_PARTIALLY_EXECUTED",
                "EXECUTION_REJECTED",
                "EXECUTION_CANCELLED",
                "EXECUTION_EXPIRED",
                "EXECUTED",
                "REPORT_REQUESTED",
            }
            for event in delivery_events
        ),
        f"{proposal_id}: delivery history contained non-delivery events",
    )
    _assert(
        all(int(event["related_version_no"]) == current_version_no for event in delivery_events),
        f"{proposal_id}: delivery history leaked non-current version events",
    )
    _assert(
        int(approvals["approval_count"]) >= 2,
        f"{proposal_id}: approvals endpoint missing lifecycle approval records",
    )
    approval_rows = cast(list[dict[str, Any]], approvals["approvals"])
    _assert(
        all(
            int(approval["related_version_no"]) == current_version_no for approval in approval_rows
        ),
        f"{proposal_id}: approvals endpoint leaked non-current version approvals",
    )
    execution = cast(dict[str, Any], delivery_summary["execution"])
    _assert(
        execution["handoff_status"] == "EXECUTED",
        f"{proposal_id}: delivery summary execution did not reach EXECUTED",
    )
    _assert(
        execution["related_version_no"] == current_version_no,
        f"{proposal_id}: execution summary was not anchored to latest version",
    )
    _assert(
        str(cast(dict[str, Any], delivery_history["latest_event"])["event_type"])
        == (
            "REPORT_REQUESTED"
            if expected_report_status == "READY"
            else str(execution["latest_event_type"])
        ),
        f"{proposal_id}: delivery latest event did not match delivery posture",
    )
    reporting = delivery_summary.get("reporting")
    if expected_report_status == "READY":
        reporting_dict = cast(dict[str, Any], reporting)
        _assert(
            isinstance(reporting, dict) and reporting_dict["status"] == "READY",
            f"{proposal_id}: delivery summary missing ready reporting posture",
        )
        _assert(
            reporting_dict["related_version_no"] == current_version_no,
            f"{proposal_id}: report summary was not anchored to latest version",
        )
    else:
        _assert(
            reporting is None,
            f"{proposal_id}: delivery summary unexpectedly contained reporting posture",
        )
    if current_version_no > 1:
        first_version_replay = _get_json(
            client,
            url=(f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/1/replay-evidence"),
            expected_status=200,
        )
        current_version_replay = _get_json(
            client,
            url=(
                f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
                f"{current_version_no}/replay-evidence"
            ),
            expected_status=200,
        )
        _assert(
            first_version_replay["subject"]["proposal_version_no"] == 1,
            f"{proposal_id}: version-1 replay subject lost immutable version identity",
        )
        _assert(
            current_version_replay["subject"]["proposal_version_no"] == current_version_no,
            f"{proposal_id}: current-version replay subject lost version identity",
        )


def validate_live_cross_service_parity(
    *,
    advise_base_url: str | None = None,
    core_query_base_url: str | None = None,
    core_control_base_url: str | None = None,
    risk_base_url: str | None = None,
    candidate_portfolios: tuple[str, ...] | None = None,
) -> LiveParityResult:
    advise_base_url = (
        advise_base_url or os.getenv("LOTUS_ADVISE_BASE_URL") or _DEFAULT_ADVISE_BASE_URL
    ).rstrip("/")
    core_query_base_url = (
        core_query_base_url
        or os.getenv("LOTUS_CORE_QUERY_BASE_URL")
        or _DEFAULT_CORE_QUERY_BASE_URL
    ).rstrip("/")
    core_control_base_url = (
        core_control_base_url or os.getenv("LOTUS_CORE_BASE_URL") or _DEFAULT_CORE_CONTROL_BASE_URL
    ).rstrip("/")
    risk_base_url = (
        risk_base_url or os.getenv("LOTUS_RISK_BASE_URL") or _DEFAULT_RISK_BASE_URL
    ).rstrip("/")
    candidates = candidate_portfolios or tuple(
        value.strip()
        for value in os.getenv(
            "LOTUS_PARITY_PORTFOLIOS",
            ",".join(_DEFAULT_PORTFOLIO_CANDIDATES),
        ).split(",")
        if value.strip()
    )

    with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
        complete, degraded = _select_scenarios(
            client,
            advise_base_url=advise_base_url,
            core_query_base_url=core_query_base_url,
            candidates=candidates,
        )

        for scenario in (complete, degraded):
            proposal_body = _simulate_stateful_noop(
                client,
                advise_base_url=advise_base_url,
                portfolio_id=scenario.portfolio_id,
                as_of_date=scenario.as_of_date,
            )
            direct_allocation = _query_live_allocation(
                client,
                core_query_base_url=core_query_base_url,
                portfolio_id=scenario.portfolio_id,
                as_of_date=scenario.as_of_date,
                reporting_currency=scenario.reporting_currency,
            )
            _assert_allocation_parity(
                scenario=scenario,
                direct_allocation=direct_allocation,
                proposal_body=proposal_body,
            )
            if scenario.risk_available:
                _assert_authority_posture(
                    scenario=scenario,
                    proposal_body=proposal_body,
                )
                direct_risk = _query_direct_concentration(
                    client,
                    risk_base_url=risk_base_url,
                    portfolio_id=scenario.portfolio_id,
                    as_of_date=scenario.as_of_date,
                    reporting_currency=scenario.reporting_currency,
                )
                _assert_risk_parity(
                    scenario=scenario,
                    direct_risk=direct_risk,
                    proposal_body=proposal_body,
                )
            else:
                authority_resolution = proposal_body.get("explanation", {}).get(
                    "authority_resolution"
                )
                _assert(
                    isinstance(authority_resolution, dict)
                    and authority_resolution.get("risk_authority") == "unavailable"
                    and authority_resolution.get("degraded") is True,
                    (
                        f"{scenario.portfolio_id}: expected degraded risk-unavailable posture, got "
                        f"{authority_resolution}"
                    ),
                )
                _assert(
                    "risk_lens" not in proposal_body.get("explanation", {}),
                    (
                        f"{scenario.portfolio_id}: degraded risk-unavailable scenario "
                        "exposed risk_lens"
                    ),
                )

        cold_ms, warm_ms = _measure_warm_cache(
            client,
            advise_base_url=advise_base_url,
            scenario=complete,
        )
        ready_decision, review_decision, blocked_decision = _validate_live_decision_paths(
            client,
            advise_base_url=advise_base_url,
            complete_scenario=complete,
        )
        (
            noop_alternatives,
            concentration_alternatives,
            cash_raise_alternatives,
            cross_currency_alternatives,
            restricted_product_alternatives,
        ) = _validate_live_proposal_alternatives_paths(
            client,
            advise_base_url=advise_base_url,
            complete_scenario=complete,
            warm_duration_ms=warm_ms,
        )
        (
            lifecycle_portfolio,
            lifecycle_latest_version_no,
            lifecycle_current_state,
            handoff_status,
            report_status,
        ) = _assert_lifecycle_and_delivery_flow(
            client,
            advise_base_url=advise_base_url,
            scenario=complete,
        )
        proposal_narrative = _assert_live_proposal_narrative_flow(
            client,
            advise_base_url=advise_base_url,
            scenario=complete,
        )
        proposal_memo = _assert_live_proposal_memo_flow(
            client,
            advise_base_url=advise_base_url,
            scenario=complete,
        )
        proposal_policy = _assert_live_policy_evaluation_flow(
            client,
            advise_base_url=advise_base_url,
            scenario=complete,
        )
        (
            async_lifecycle_portfolio,
            async_lifecycle_latest_version_no,
            async_lifecycle_current_state,
        ) = _assert_async_lifecycle_read_surfaces(
            client,
            advise_base_url=advise_base_url,
            scenario=complete,
        )
        _assert_new_version_requires_fresh_approvals(
            client,
            advise_base_url=advise_base_url,
            scenario=complete,
        )
        _assert_mixed_approval_routes_remain_version_scoped(
            client,
            advise_base_url=advise_base_url,
            scenario=complete,
        )
        (
            workspace_rationale_initial_run_id,
            workspace_rationale_replacement_run_id,
            workspace_rationale_review_state,
            workspace_rationale_supportability_status,
        ) = _assert_workspace_flow(
            client,
            advise_base_url=advise_base_url,
            scenario=complete,
        )
        changed_state_security_id = _assert_changed_state_workspace_risk_parity(
            client,
            advise_base_url=advise_base_url,
            core_query_base_url=core_query_base_url,
            risk_base_url=risk_base_url,
            scenario=complete,
        )
        _assert_changed_state_workspace_allocation_parity(
            client,
            advise_base_url=advise_base_url,
            core_query_base_url=core_query_base_url,
            core_control_base_url=core_control_base_url,
            scenario=complete,
            security_id=changed_state_security_id,
        )
        cross_currency_security_id = _select_cross_currency_changed_state_security(
            _query_live_positions(
                client,
                core_query_base_url=core_query_base_url,
                portfolio_id=complete.portfolio_id,
                as_of_date=complete.as_of_date,
            ),
            base_currency=complete.reporting_currency,
        )
        _assert_changed_state_workspace_risk_parity(
            client,
            advise_base_url=advise_base_url,
            core_query_base_url=core_query_base_url,
            risk_base_url=risk_base_url,
            scenario=complete,
            security_id=cross_currency_security_id,
        )
        _assert_changed_state_workspace_allocation_parity(
            client,
            advise_base_url=advise_base_url,
            core_query_base_url=core_query_base_url,
            core_control_base_url=core_control_base_url,
            scenario=complete,
            security_id=cross_currency_security_id,
        )
        non_held_security_id = _select_non_held_changed_state_security(
            _query_live_positions(
                client,
                core_query_base_url=core_query_base_url,
                portfolio_id=complete.portfolio_id,
                as_of_date=complete.as_of_date,
            )
        )
        _assert_changed_state_workspace_risk_parity(
            client,
            advise_base_url=advise_base_url,
            core_query_base_url=core_query_base_url,
            risk_base_url=risk_base_url,
            scenario=complete,
            security_id=non_held_security_id,
        )
        _assert_changed_state_workspace_allocation_parity(
            client,
            advise_base_url=advise_base_url,
            core_query_base_url=core_query_base_url,
            core_control_base_url=core_control_base_url,
            scenario=complete,
            security_id=non_held_security_id,
        )

    return LiveParityResult(
        complete_issuer_portfolio=complete.portfolio_id,
        degraded_issuer_portfolio=degraded.portfolio_id,
        degraded_issuer_coverage_status=degraded.issuer_coverage_status,
        cold_duration_ms=cold_ms,
        warm_duration_ms=warm_ms,
        changed_state_portfolio=complete.portfolio_id,
        changed_state_security_id=changed_state_security_id,
        cross_currency_security_id=cross_currency_security_id,
        non_held_security_id=non_held_security_id,
        workspace_handoff_portfolio=complete.portfolio_id,
        workspace_rationale_initial_run_id=workspace_rationale_initial_run_id,
        workspace_rationale_replacement_run_id=workspace_rationale_replacement_run_id,
        workspace_rationale_review_state=workspace_rationale_review_state,
        workspace_rationale_supportability_status=workspace_rationale_supportability_status,
        lifecycle_portfolio=lifecycle_portfolio,
        lifecycle_latest_version_no=lifecycle_latest_version_no,
        lifecycle_current_state=lifecycle_current_state,
        async_lifecycle_portfolio=async_lifecycle_portfolio,
        async_lifecycle_latest_version_no=async_lifecycle_latest_version_no,
        async_lifecycle_current_state=async_lifecycle_current_state,
        execution_handoff_status=handoff_status,
        execution_terminal_status="EXECUTED",
        report_status=report_status,
        proposal_narrative=proposal_narrative,
        proposal_memo=proposal_memo,
        proposal_policy=proposal_policy,
        ready_decision=ready_decision,
        review_decision=review_decision,
        blocked_decision=blocked_decision,
        noop_alternatives=noop_alternatives,
        concentration_alternatives=concentration_alternatives,
        cash_raise_alternatives=cash_raise_alternatives,
        cross_currency_alternatives=cross_currency_alternatives,
        restricted_product_alternatives=restricted_product_alternatives,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate live cross-service allocation and risk parity across "
            "lotus-advise, lotus-core, and lotus-risk."
        )
    )
    parser.add_argument("--advise-base-url", default=None)
    parser.add_argument("--core-query-base-url", default=None)
    parser.add_argument("--core-control-base-url", default=None)
    parser.add_argument("--risk-base-url", default=None)
    parser.add_argument(
        "--candidate-portfolio",
        action="append",
        dest="candidate_portfolios",
        help="Candidate seeded portfolio_id to probe for complete/partial issuer coverage.",
    )
    args = parser.parse_args()

    result = validate_live_cross_service_parity(
        advise_base_url=args.advise_base_url,
        core_query_base_url=args.core_query_base_url,
        core_control_base_url=args.core_control_base_url,
        risk_base_url=args.risk_base_url,
        candidate_portfolios=(
            tuple(args.candidate_portfolios) if args.candidate_portfolios else None
        ),
    )
    print(
        "Cross-service parity validation passed "
        f"(complete={result.complete_issuer_portfolio}, "
        f"degraded={result.degraded_issuer_portfolio}:"
        f"{result.degraded_issuer_coverage_status}, "
        f"cold_ms={result.cold_duration_ms:.2f}, "
        f"warm_ms={result.warm_duration_ms:.2f})"
    )


if __name__ == "__main__":
    main()
