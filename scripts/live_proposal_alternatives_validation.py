from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx

from scripts.live_runtime_proposal_alternatives import LiveProposalAlternativesSnapshot


class AlternativesScenario(Protocol):
    portfolio_id: str
    as_of_date: str
    reporting_currency: str


SimulatePath = Callable[..., tuple[dict[str, Any], LiveProposalAlternativesSnapshot]]
CollectStatuses = Callable[[dict[str, Any]], dict[str, set[str]]]
AssertCondition = Callable[[bool, str], None]


def _validate_live_noop_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    collect_statuses: CollectStatuses,
    assert_condition: AssertCondition,
) -> LiveProposalAlternativesSnapshot:
    objectives = [
        "REDUCE_CONCENTRATION",
        "RAISE_CASH",
        "IMPROVE_CURRENCY_ALIGNMENT",
        "AVOID_RESTRICTED_PRODUCTS",
    ]
    proposal_body, snapshot = simulate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        idempotency_prefix="live-alt-noop",
        path_name="no_op_path",
        objectives=objectives,
        max_alternatives=3,
        constraints={
            "cash_floor": {
                "amount": "25000",
                "currency": complete_scenario.reporting_currency,
            }
        },
    )
    statuses = collect_statuses(proposal_body)
    assert_condition(
        snapshot.requested_objectives == tuple(objectives),
        f"no_op_path: requested objectives drifted, got {snapshot.requested_objectives}",
    )
    assert_condition(
        statuses.get("REDUCE_CONCENTRATION") == {"REJECTED_POLICY_BLOCKED"},
        (
            "no_op_path: expected concentration objective to surface as policy-blocked under "
            f"canonical posture, got {statuses}"
        ),
    )
    assert_condition(
        statuses.get("IMPROVE_CURRENCY_ALIGNMENT") == {"REJECTED_POLICY_BLOCKED"},
        (
            "no_op_path: expected currency objective to surface as policy-blocked under "
            f"canonical posture, got {statuses}"
        ),
    )
    assert_condition(
        "ALTERNATIVE_CASH_ALREADY_SUFFICIENT" in snapshot.rejected_reason_codes,
        (
            "no_op_path: expected cash-floor rejection evidence, got "
            f"{snapshot.rejected_reason_codes}"
        ),
    )
    assert_condition(
        "ALTERNATIVE_OBJECTIVE_PENDING_CANONICAL_EVIDENCE" in snapshot.rejected_reason_codes,
        (
            "no_op_path: expected restricted-product deferred evidence, got "
            f"{snapshot.rejected_reason_codes}"
        ),
    )
    return snapshot


def _validate_live_concentration_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    collect_statuses: CollectStatuses,
    assert_condition: AssertCondition,
) -> LiveProposalAlternativesSnapshot:
    proposal_body, snapshot = simulate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        idempotency_prefix="live-alt-concentration",
        path_name="concentration_path",
        objectives=["REDUCE_CONCENTRATION"],
        max_alternatives=1,
    )
    statuses = collect_statuses(proposal_body)
    assert_condition(
        snapshot.requested_objectives == ("REDUCE_CONCENTRATION",),
        (
            "concentration_path: requested objective drifted from concentration posture, got "
            f"{snapshot.requested_objectives}"
        ),
    )
    assert_condition(
        statuses.get("REDUCE_CONCENTRATION") == {"REJECTED_POLICY_BLOCKED"},
        (f"concentration_path: expected policy-blocked concentration alternative, got {statuses}"),
    )
    return snapshot


def _validate_live_cash_raise_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    assert_condition: AssertCondition,
) -> LiveProposalAlternativesSnapshot:
    _, snapshot = simulate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        idempotency_prefix="live-alt-cash",
        path_name="cash_raise_path",
        objectives=["RAISE_CASH"],
        max_alternatives=1,
        constraints={
            "cash_floor": {
                "amount": "25000",
                "currency": complete_scenario.reporting_currency,
            }
        },
    )
    assert_condition(
        snapshot.rejected_reason_codes == ("ALTERNATIVE_CASH_ALREADY_SUFFICIENT",),
        (
            "cash_raise_path: expected cash-floor rejection due to already sufficient base cash, "
            f"got {snapshot.rejected_reason_codes}"
        ),
    )
    return snapshot


def _validate_live_cross_currency_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    collect_statuses: CollectStatuses,
    assert_condition: AssertCondition,
) -> LiveProposalAlternativesSnapshot:
    proposal_body, snapshot = simulate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        idempotency_prefix="live-alt-currency",
        path_name="cross_currency_path",
        objectives=["IMPROVE_CURRENCY_ALIGNMENT"],
        max_alternatives=1,
    )
    statuses = collect_statuses(proposal_body)
    assert_condition(
        snapshot.requested_objectives == ("IMPROVE_CURRENCY_ALIGNMENT",),
        (
            "cross_currency_path: requested objective drifted from currency posture, got "
            f"{snapshot.requested_objectives}"
        ),
    )
    assert_condition(
        statuses.get("IMPROVE_CURRENCY_ALIGNMENT") == {"REJECTED_POLICY_BLOCKED"},
        (f"cross_currency_path: expected policy-blocked currency alternative, got {statuses}"),
    )
    return snapshot


def _validate_live_restricted_product_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    assert_condition: AssertCondition,
) -> LiveProposalAlternativesSnapshot:
    _, snapshot = simulate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        idempotency_prefix="live-alt-restricted",
        path_name="restricted_product_path",
        objectives=["AVOID_RESTRICTED_PRODUCTS"],
        max_alternatives=1,
    )
    assert_condition(
        snapshot.feasible_count == 0 and snapshot.feasible_with_review_count == 0,
        (
            "restricted_product_path: deferred restricted-product path unexpectedly produced "
            f"ranked alternatives {snapshot}"
        ),
    )
    assert_condition(
        "ALTERNATIVE_OBJECTIVE_PENDING_CANONICAL_EVIDENCE" in snapshot.rejected_reason_codes,
        (
            "restricted_product_path: expected deferred canonical-evidence rejection, got "
            f"{snapshot.rejected_reason_codes}"
        ),
    )
    return snapshot


def _assert_alternatives_latency_bound(
    snapshots: tuple[LiveProposalAlternativesSnapshot, ...],
    *,
    warm_duration_ms: float,
    assert_condition: AssertCondition,
) -> None:
    latency_bound_ms = max(warm_duration_ms * 6.0, 5000.0)
    for snapshot in snapshots:
        assert_condition(
            snapshot.latency_ms <= latency_bound_ms,
            (
                f"{snapshot.path_name}: alternatives latency exceeded bound "
                f"{snapshot.latency_ms:.2f}ms > {latency_bound_ms:.2f}ms"
            ),
        )


def validate_live_proposal_alternatives_paths(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    warm_duration_ms: float,
    simulate_path: SimulatePath,
    collect_statuses: CollectStatuses,
    assert_condition: AssertCondition,
) -> tuple[
    LiveProposalAlternativesSnapshot,
    LiveProposalAlternativesSnapshot,
    LiveProposalAlternativesSnapshot,
    LiveProposalAlternativesSnapshot,
    LiveProposalAlternativesSnapshot,
]:
    noop_snapshot = _validate_live_noop_alternatives_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        simulate_path=simulate_path,
        collect_statuses=collect_statuses,
        assert_condition=assert_condition,
    )
    concentration_snapshot = _validate_live_concentration_alternatives_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        simulate_path=simulate_path,
        collect_statuses=collect_statuses,
        assert_condition=assert_condition,
    )
    cash_raise_snapshot = _validate_live_cash_raise_alternatives_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        simulate_path=simulate_path,
        assert_condition=assert_condition,
    )
    cross_currency_snapshot = _validate_live_cross_currency_alternatives_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        simulate_path=simulate_path,
        collect_statuses=collect_statuses,
        assert_condition=assert_condition,
    )
    restricted_product_snapshot = _validate_live_restricted_product_alternatives_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        simulate_path=simulate_path,
        assert_condition=assert_condition,
    )
    snapshots = (
        noop_snapshot,
        concentration_snapshot,
        cash_raise_snapshot,
        cross_currency_snapshot,
        restricted_product_snapshot,
    )
    _assert_alternatives_latency_bound(
        snapshots,
        warm_duration_ms=warm_duration_ms,
        assert_condition=assert_condition,
    )
    return snapshots
