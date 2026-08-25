from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.validate_cross_service_parity_live import LiveParityResult


def run_live_parity(
    primitives: ModuleType,
    *,
    advise_base_url: str | None = None,
    core_query_base_url: str | None = None,
    core_control_base_url: str | None = None,
    risk_base_url: str | None = None,
    candidate_portfolios: tuple[str, ...] | None = None,
) -> LiveParityResult:
    """Run the ordered live certification using the validator's proof primitives."""
    p = primitives
    configuration = p._resolve_live_parity_configuration(
        advise_base_url=advise_base_url,
        core_query_base_url=core_query_base_url,
        core_control_base_url=core_control_base_url,
        risk_base_url=risk_base_url,
        candidate_portfolios=candidate_portfolios,
    )

    with p.httpx.Client(timeout=p.httpx.Timeout(30.0)) as client:
        complete, degraded = p._select_scenarios(
            client,
            advise_base_url=configuration.advise_base_url,
            core_query_base_url=configuration.core_query_base_url,
            candidates=configuration.candidate_portfolios,
        )
        p._validate_live_scenario_parity(
            client,
            advise_base_url=configuration.advise_base_url,
            core_query_base_url=configuration.core_query_base_url,
            risk_base_url=configuration.risk_base_url,
            scenarios=(complete, degraded),
        )

        cold_ms, warm_ms = p._measure_warm_cache(
            client,
            advise_base_url=configuration.advise_base_url,
            scenario=complete,
        )
        ready_decision, review_decision, blocked_decision = p._validate_live_decision_paths(
            client,
            advise_base_url=configuration.advise_base_url,
            complete_scenario=complete,
        )
        (
            noop_alternatives,
            concentration_alternatives,
            cash_raise_alternatives,
            cross_currency_alternatives,
            restricted_product_alternatives,
        ) = p._validate_live_proposal_alternatives_paths(
            client,
            advise_base_url=configuration.advise_base_url,
            complete_scenario=complete,
            warm_duration_ms=warm_ms,
        )
        (
            lifecycle_portfolio,
            lifecycle_latest_version_no,
            lifecycle_current_state,
            handoff_status,
            report_status,
        ) = p._assert_lifecycle_and_delivery_flow(
            client,
            advise_base_url=configuration.advise_base_url,
            scenario=complete,
        )
        proposal_narrative = p._assert_live_proposal_narrative_flow(
            client,
            advise_base_url=configuration.advise_base_url,
            scenario=complete,
        )
        proposal_memo = p._assert_live_proposal_memo_flow(
            client,
            advise_base_url=configuration.advise_base_url,
            scenario=complete,
        )
        proposal_policy = p._assert_live_policy_evaluation_flow(
            client,
            advise_base_url=configuration.advise_base_url,
            scenario=complete,
        )
        (
            async_lifecycle_portfolio,
            async_lifecycle_latest_version_no,
            async_lifecycle_current_state,
        ) = p._assert_async_lifecycle_read_surfaces(
            client,
            advise_base_url=configuration.advise_base_url,
            scenario=complete,
        )
        p._assert_new_version_requires_fresh_approvals(
            client,
            advise_base_url=configuration.advise_base_url,
            scenario=complete,
        )
        p._assert_mixed_approval_routes_remain_version_scoped(
            client,
            advise_base_url=configuration.advise_base_url,
            scenario=complete,
        )
        (
            workspace_rationale_initial_run_id,
            workspace_rationale_replacement_run_id,
            workspace_rationale_review_state,
            workspace_rationale_supportability_status,
        ) = p._assert_workspace_flow(
            client,
            advise_base_url=configuration.advise_base_url,
            scenario=complete,
        )
        (
            changed_state_security_id,
            cross_currency_security_id,
            non_held_security_id,
        ) = p._validate_changed_state_workspace_parity(
            client,
            advise_base_url=configuration.advise_base_url,
            core_query_base_url=configuration.core_query_base_url,
            core_control_base_url=configuration.core_control_base_url,
            risk_base_url=configuration.risk_base_url,
            scenario=complete,
        )

    return p.LiveParityResult(
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
