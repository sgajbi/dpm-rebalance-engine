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


def _validate_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    collect_statuses: CollectStatuses,
    assert_condition: AssertCondition,
    objectives: list[str],
    max_alternatives: int,
    constraints: dict[str, Any] | None = None,
    expected_statuses: dict[str, set[str]] | None = None,
    required_rejection_codes: tuple[str, ...] = (),
    exact_rejection_codes: tuple[str, ...] | None = None,
    expected_counts: tuple[int, int] | None = None,
    idempotency_prefix: str,
    path_name: str,
) -> LiveProposalAlternativesSnapshot:
    proposal_body, snapshot = simulate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        idempotency_prefix=idempotency_prefix,
        path_name=path_name,
        objectives=objectives,
        max_alternatives=max_alternatives,
        constraints=constraints,
    )
    assert_condition(
        snapshot.requested_objectives == tuple(objectives),
        f"{path_name}: requested objectives drifted, got {snapshot.requested_objectives}",
    )
    statuses = collect_statuses(proposal_body)
    for objective, expected in (expected_statuses or {}).items():
        assert_condition(
            statuses.get(objective) == expected,
            f"{path_name}: expected {objective} statuses {expected}, got {statuses}",
        )
    for reason_code in required_rejection_codes:
        assert_condition(
            reason_code in snapshot.rejected_reason_codes,
            f"{path_name}: expected rejection {reason_code}, got {snapshot.rejected_reason_codes}",
        )
    if exact_rejection_codes is not None:
        assert_condition(
            snapshot.rejected_reason_codes == exact_rejection_codes,
            f"{path_name}: expected rejections {exact_rejection_codes}, "
            f"got {snapshot.rejected_reason_codes}",
        )
    if expected_counts is not None:
        assert_condition(
            (snapshot.feasible_count, snapshot.feasible_with_review_count) == expected_counts,
            f"{path_name}: expected feasible counts {expected_counts}, got {snapshot}",
        )
    return snapshot


def _validate_live_noop_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    collect_statuses: CollectStatuses,
    assert_condition: AssertCondition,
) -> LiveProposalAlternativesSnapshot:
    return _validate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        simulate_path=simulate_path,
        collect_statuses=collect_statuses,
        assert_condition=assert_condition,
        objectives=[
            "REDUCE_CONCENTRATION",
            "RAISE_CASH",
            "IMPROVE_CURRENCY_ALIGNMENT",
            "AVOID_RESTRICTED_PRODUCTS",
        ],
        max_alternatives=3,
        constraints={
            "cash_floor": {"amount": "25000", "currency": complete_scenario.reporting_currency}
        },
        expected_statuses={
            "REDUCE_CONCENTRATION": {"REJECTED_POLICY_BLOCKED"},
            "IMPROVE_CURRENCY_ALIGNMENT": {"REJECTED_POLICY_BLOCKED"},
        },
        required_rejection_codes=(
            "ALTERNATIVE_CASH_ALREADY_SUFFICIENT",
            "ALTERNATIVE_OBJECTIVE_PENDING_CANONICAL_EVIDENCE",
        ),
        idempotency_prefix="live-alt-noop",
        path_name="no_op_path",
    )


def _validate_live_concentration_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    collect_statuses: CollectStatuses,
    assert_condition: AssertCondition,
) -> LiveProposalAlternativesSnapshot:
    return _validate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        simulate_path=simulate_path,
        collect_statuses=collect_statuses,
        assert_condition=assert_condition,
        objectives=["REDUCE_CONCENTRATION"],
        max_alternatives=1,
        expected_statuses={"REDUCE_CONCENTRATION": {"REJECTED_POLICY_BLOCKED"}},
        idempotency_prefix="live-alt-concentration",
        path_name="concentration_path",
    )


def _validate_live_cash_raise_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    collect_statuses: CollectStatuses,
    assert_condition: AssertCondition,
) -> LiveProposalAlternativesSnapshot:
    return _validate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        simulate_path=simulate_path,
        collect_statuses=collect_statuses,
        assert_condition=assert_condition,
        objectives=["RAISE_CASH"],
        max_alternatives=1,
        constraints={
            "cash_floor": {"amount": "25000", "currency": complete_scenario.reporting_currency}
        },
        exact_rejection_codes=("ALTERNATIVE_CASH_ALREADY_SUFFICIENT",),
        idempotency_prefix="live-alt-cash",
        path_name="cash_raise_path",
    )


def _validate_live_cross_currency_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    collect_statuses: CollectStatuses,
    assert_condition: AssertCondition,
) -> LiveProposalAlternativesSnapshot:
    return _validate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        simulate_path=simulate_path,
        collect_statuses=collect_statuses,
        assert_condition=assert_condition,
        objectives=["IMPROVE_CURRENCY_ALIGNMENT"],
        max_alternatives=1,
        expected_statuses={"IMPROVE_CURRENCY_ALIGNMENT": {"REJECTED_POLICY_BLOCKED"}},
        idempotency_prefix="live-alt-currency",
        path_name="cross_currency_path",
    )


def _validate_live_restricted_product_alternatives_path(
    client: httpx.Client,
    *,
    advise_base_url: str,
    complete_scenario: AlternativesScenario,
    simulate_path: SimulatePath,
    collect_statuses: CollectStatuses,
    assert_condition: AssertCondition,
) -> LiveProposalAlternativesSnapshot:
    return _validate_path(
        client,
        advise_base_url=advise_base_url,
        complete_scenario=complete_scenario,
        simulate_path=simulate_path,
        collect_statuses=collect_statuses,
        assert_condition=assert_condition,
        objectives=["AVOID_RESTRICTED_PRODUCTS"],
        max_alternatives=1,
        required_rejection_codes=("ALTERNATIVE_OBJECTIVE_PENDING_CANONICAL_EVIDENCE",),
        expected_counts=(0, 0),
        idempotency_prefix="live-alt-restricted",
        path_name="restricted_product_path",
    )


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
            f"{snapshot.path_name}: alternatives latency exceeded bound "
            f"{snapshot.latency_ms:.2f}ms > {latency_bound_ms:.2f}ms",
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
    """Validate all canonical live alternatives scenarios and return their snapshots."""
    scenario_args = {
        "client": client,
        "advise_base_url": advise_base_url,
        "complete_scenario": complete_scenario,
        "simulate_path": simulate_path,
        "collect_statuses": collect_statuses,
        "assert_condition": assert_condition,
    }
    snapshots = (
        _validate_live_noop_alternatives_path(**scenario_args),
        _validate_live_concentration_alternatives_path(**scenario_args),
        _validate_live_cash_raise_alternatives_path(**scenario_args),
        _validate_live_cross_currency_alternatives_path(**scenario_args),
        _validate_live_restricted_product_alternatives_path(**scenario_args),
    )
    _assert_alternatives_latency_bound(
        snapshots,
        warm_duration_ms=warm_duration_ms,
        assert_condition=assert_condition,
    )
    return snapshots
