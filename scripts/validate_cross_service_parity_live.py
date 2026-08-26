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
from typing import Any, Literal, NoReturn, cast

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.live_async_lifecycle_flow import (  # noqa: E402
    AsyncLifecycleScenario,
    LiveAsyncLifecyclePrimitives,
    assert_async_proposal_lifecycle,
    assert_live_async_lifecycle,
)
from scripts.live_memo_flow import (  # noqa: E402
    LiveMemoFlowPrimitives,
    assert_live_memo_flow,
)
from scripts.live_narrative_flow import (  # noqa: E402
    LiveNarrativeFlowPrimitives,
    assert_live_proposal_narrative_flow,
)
from scripts.live_policy_evaluation_flow import (  # noqa: E402
    LivePolicyEvaluationPrimitives,
    assert_live_policy_evaluation,
)
from scripts.live_policy_evaluation_support import (  # noqa: E402
    StatefulProposalScenario,
    ensure_sg_policy_pack_active,
    live_policy_evidence_bundle,
    request_live_policy_report,
    stateful_proposal_input,
)
from scripts.live_proposal_alternatives_validation import (  # noqa: E402
    validate_live_proposal_alternatives_paths,
)
from scripts.live_report_delivery import (  # noqa: E402
    ReportDeliveryPrimitives,
    assert_report_delivery,
)
from scripts.live_runtime_decision_summary import (  # noqa: E402
    LiveDecisionSnapshot,
    extract_live_decision_snapshot,
)
from scripts.live_runtime_persisted_read_surfaces import (  # noqa: E402
    assert_persisted_read_surfaces,
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
from scripts.live_workspace_flow import (  # noqa: E402
    LiveWorkspacePrimitives,
    assert_live_workspace_flow,
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


def _raise_live_error(message: str) -> NoReturn:
    raise LiveParityValidationError(message)


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


def _simulate_live_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: PortfolioParityScenario,
    idempotency_prefix: str,
    path_name: str,
    objectives: list[str],
    max_alternatives: int,
    constraints: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], LiveProposalAlternativesSnapshot]:
    proposal_body, latency_ms = _simulate_stateful_alternatives(
        client,
        advise_base_url=advise_base_url,
        portfolio_id=complete_scenario.portfolio_id,
        as_of_date=complete_scenario.as_of_date,
        idempotency_key=f"{idempotency_prefix}-{uuid.uuid4().hex}",
        alternatives_request=_build_alternatives_request(
            objectives=objectives,
            max_alternatives=max_alternatives,
            constraints=constraints,
        ),
    )
    return proposal_body, _extract_live_proposal_alternatives_snapshot(
        proposal_body=proposal_body,
        path_name=path_name,
        latency_ms=latency_ms,
    )


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
    return validate_live_proposal_alternatives_paths(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        warm_duration_ms=warm_duration_ms,
        simulate_path=_simulate_live_alternatives_path,
        collect_statuses=_collect_alternative_statuses,
        assert_condition=_assert,
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


def _create_stateful_proposal(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: StatefulProposalScenario,
    created_by: str,
    narrative_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stateful_input = stateful_proposal_input(scenario, narrative_request)
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
    scenario: StatefulProposalScenario,
    created_by: str,
    expected_current_version_no: int,
    narrative_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stateful_input = stateful_proposal_input(scenario, narrative_request)
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


def _assert_synchronous_lifecycle_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> tuple[str, int]:
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
    return proposal_id, related_version_no


def _live_async_lifecycle_primitives() -> LiveAsyncLifecyclePrimitives:
    def assert_async_authority_posture(
        *, scenario: AsyncLifecycleScenario, proposal_body: dict[str, Any]
    ) -> None:
        _assert_authority_posture(
            scenario=cast(PortfolioParityScenario, scenario),
            proposal_body=proposal_body,
        )

    return LiveAsyncLifecyclePrimitives(
        post_json=_post_json,
        get_json=_get_json,
        assertion=_assert,
        feature_by_key=_feature_by_key,
        assert_authority_posture=assert_async_authority_posture,
        assert_persisted_read_surfaces=assert_persisted_read_surfaces,
        promote_to_execution_ready=_promote_to_execution_ready,
        fail=_raise_live_error,
        utc_iso_after=_utc_iso_after,
    )


def _assert_asynchronous_lifecycle_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> None:
    assert_async_proposal_lifecycle(
        client,
        primitives=_live_async_lifecycle_primitives(),
        advise_base_url=advise_base_url,
        scenario=scenario,
    )


def _assert_execution_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    proposal_id: str,
    related_version_no: int,
) -> dict[str, Any]:

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
    return handoff


def _assert_lifecycle_and_delivery_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> tuple[str, int, str, str, str]:
    proposal_id, related_version_no = _assert_synchronous_lifecycle_flow(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
    )
    _assert_asynchronous_lifecycle_flow(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
    )
    handoff = _assert_execution_flow(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        related_version_no=related_version_no,
    )
    report_status = assert_report_delivery(
        client,
        primitives=ReportDeliveryPrimitives(
            get_json=_get_json,
            feature_by_key=_feature_by_key,
            assertion=_assert,
            assert_persisted_read_surfaces=assert_persisted_read_surfaces,
        ),
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        related_version_no=related_version_no,
        expected_portfolio_id=scenario.portfolio_id,
    )
    return (
        scenario.portfolio_id,
        related_version_no,
        "EXECUTED",
        handoff["handoff_status"],
        report_status,
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
    """Run narrative certification through an explicit typed primitive seam."""
    return assert_live_proposal_narrative_flow(
        client,
        primitives=LiveNarrativeFlowPrimitives(
            create_stateful_proposal=_create_stateful_proposal,
            get_json=_get_json,
            post_json=_post_json,
            feature_by_key=_feature_by_key,
            assertion=_assert,
            extract_snapshot=extract_live_narrative_snapshot,
            extract_ai_lineage_status=extract_ai_lineage_status,
        ),
        advise_base_url=advise_base_url,
        scenario=scenario,
    )


def _assert_live_proposal_memo_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> LiveProposalMemoSnapshot:
    return assert_live_memo_flow(
        client,
        primitives=LiveMemoFlowPrimitives(
            create_stateful_proposal=_create_stateful_proposal,
            post_json=_post_json,
            get_json=_get_json,
            assertion=_assert,
            extract_snapshot=extract_live_memo_snapshot,
        ),
        advise_base_url=advise_base_url,
        scenario=scenario,
    )


def _assert_live_policy_evaluation_flow(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> LivePolicyEvaluationSnapshot:
    """Run policy certification through an explicit typed primitive seam."""
    primitives = LivePolicyEvaluationPrimitives(
        assertion=_assert,
        get_json=_get_json,
        post_json=_post_json,
        ensure_policy_pack_active=ensure_sg_policy_pack_active,
        policy_evidence_bundle=live_policy_evidence_bundle,
        request_policy_report=request_live_policy_report,
        extract_snapshot=extract_live_policy_evaluation_snapshot,
    )
    return assert_live_policy_evaluation(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        scenario=scenario,
    )


def _assert_async_lifecycle_read_surfaces(
    client: httpx.Client,
    *,
    advise_base_url: str,
    scenario: PortfolioParityScenario,
) -> tuple[str, int, str]:
    return assert_live_async_lifecycle(
        client,
        primitives=_live_async_lifecycle_primitives(),
        advise_base_url=advise_base_url,
        scenario=scenario,
    )


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
    def _assert_workspace_authority_posture(
        *, portfolio_id: str, proposal_body: dict[str, Any]
    ) -> None:
        _assert_authority_posture(scenario=scenario, proposal_body=proposal_body)

    return assert_live_workspace_flow(
        client,
        primitives=LiveWorkspacePrimitives(
            post_json=_post_json,
            request_json=_request_json,
            assertion=_assert,
            assert_authority_posture=_assert_workspace_authority_posture,
        ),
        advise_base_url=advise_base_url,
        scenario=scenario,
    )


def _validate_live_scenario_parity(
    client: httpx.Client,
    *,
    advise_base_url: str,
    core_query_base_url: str,
    risk_base_url: str,
    scenarios: tuple[PortfolioParityScenario, ...],
) -> None:
    for scenario in scenarios:
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
            _assert_authority_posture(scenario=scenario, proposal_body=proposal_body)
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
            continue

        authority_resolution = proposal_body.get("explanation", {}).get("authority_resolution")
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
            (f"{scenario.portfolio_id}: degraded risk-unavailable scenario exposed risk_lens"),
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


def _assert_changed_state_workspace_parity_for_security(
    client: httpx.Client,
    *,
    advise_base_url: str,
    core_query_base_url: str,
    core_control_base_url: str,
    risk_base_url: str,
    scenario: PortfolioParityScenario,
    security_id: str,
) -> None:
    _assert_changed_state_workspace_risk_parity(
        client,
        advise_base_url=advise_base_url,
        core_query_base_url=core_query_base_url,
        risk_base_url=risk_base_url,
        scenario=scenario,
        security_id=security_id,
    )
    _assert_changed_state_workspace_allocation_parity(
        client,
        advise_base_url=advise_base_url,
        core_query_base_url=core_query_base_url,
        core_control_base_url=core_control_base_url,
        scenario=scenario,
        security_id=security_id,
    )


def _validate_changed_state_workspace_parity(
    client: httpx.Client,
    *,
    advise_base_url: str,
    core_query_base_url: str,
    core_control_base_url: str,
    risk_base_url: str,
    scenario: PortfolioParityScenario,
) -> tuple[str, str, str]:
    changed_state_security_id = _assert_changed_state_workspace_risk_parity(
        client,
        advise_base_url=advise_base_url,
        core_query_base_url=core_query_base_url,
        risk_base_url=risk_base_url,
        scenario=scenario,
    )
    _assert_changed_state_workspace_allocation_parity(
        client,
        advise_base_url=advise_base_url,
        core_query_base_url=core_query_base_url,
        core_control_base_url=core_control_base_url,
        scenario=scenario,
        security_id=changed_state_security_id,
    )

    cross_currency_security_id = _select_cross_currency_changed_state_security(
        _query_live_positions(
            client,
            core_query_base_url=core_query_base_url,
            portfolio_id=scenario.portfolio_id,
            as_of_date=scenario.as_of_date,
        ),
        base_currency=scenario.reporting_currency,
    )
    _assert_changed_state_workspace_parity_for_security(
        client,
        advise_base_url=advise_base_url,
        core_query_base_url=core_query_base_url,
        core_control_base_url=core_control_base_url,
        risk_base_url=risk_base_url,
        scenario=scenario,
        security_id=cross_currency_security_id,
    )

    non_held_security_id = _select_non_held_changed_state_security(
        _query_live_positions(
            client,
            core_query_base_url=core_query_base_url,
            portfolio_id=scenario.portfolio_id,
            as_of_date=scenario.as_of_date,
        )
    )
    _assert_changed_state_workspace_parity_for_security(
        client,
        advise_base_url=advise_base_url,
        core_query_base_url=core_query_base_url,
        core_control_base_url=core_control_base_url,
        risk_base_url=risk_base_url,
        scenario=scenario,
        security_id=non_held_security_id,
    )
    return changed_state_security_id, cross_currency_security_id, non_held_security_id


def validate_live_cross_service_parity(
    *,
    advise_base_url: str | None = None,
    core_query_base_url: str | None = None,
    core_control_base_url: str | None = None,
    risk_base_url: str | None = None,
    candidate_portfolios: tuple[str, ...] | None = None,
) -> LiveParityResult:
    from scripts.live_parity_orchestration import run_live_parity

    environment = os.environ

    def base_url(value: str | None, name: str, default: str) -> str:
        return (value or environment.get(name) or default).rstrip("/")

    candidates = candidate_portfolios or tuple(
        value.strip()
        for value in environment.get(
            "LOTUS_PARITY_PORTFOLIOS", ",".join(_DEFAULT_PORTFOLIO_CANDIDATES)
        ).split(",")
        if value.strip()
    )
    return run_live_parity(
        sys.modules[__name__],
        advise_base_url=base_url(
            advise_base_url, "LOTUS_ADVISE_BASE_URL", _DEFAULT_ADVISE_BASE_URL
        ),
        core_query_base_url=base_url(
            core_query_base_url, "LOTUS_CORE_QUERY_BASE_URL", _DEFAULT_CORE_QUERY_BASE_URL
        ),
        core_control_base_url=base_url(
            core_control_base_url, "LOTUS_CORE_BASE_URL", _DEFAULT_CORE_CONTROL_BASE_URL
        ),
        risk_base_url=base_url(risk_base_url, "LOTUS_RISK_BASE_URL", _DEFAULT_RISK_BASE_URL),
        candidate_portfolios=candidates,
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
