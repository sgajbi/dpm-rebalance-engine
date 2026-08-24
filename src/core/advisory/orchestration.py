from dataclasses import dataclass
from typing import cast

from src.core.advisory.alternatives_projection import build_proposal_alternatives
from src.core.advisory.decision_summary import build_proposal_decision_summary
from src.core.advisory.explanation_contracts import (
    attach_governed_explanation_sections,
    build_authority_resolution_explanation,
)
from src.core.advisory.provider_ports import (
    AdvisoryProviderDependencyState,
    AdvisoryRiskEnrichmentUnavailableError,
    AdvisorySimulationUnavailableError,
    build_advisory_risk_dependency_state,
    enrich_with_advisory_risk_provider,
    resolve_advisory_simulation_fallback_policy,
    simulate_with_advisory_simulation_provider,
)
from src.core.advisory.valuation_context import build_proposal_valuation_context
from src.core.advisory_engine import run_proposal_simulation
from src.core.common.idempotency import normalize_optional_idempotency_key
from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposal_result_models import ProposalResult

_LOTUS_RISK_ENRICHMENT_UNAVAILABLE = "LOTUS_RISK_ENRICHMENT_UNAVAILABLE"
_LOTUS_RISK_DEPENDENCY_UNAVAILABLE = "LOTUS_RISK_DEPENDENCY_UNAVAILABLE"


@dataclass(frozen=True)
class _SimulationResolution:
    proposal_result: ProposalResult
    authority: str
    degraded_reasons: list[str]


@dataclass(frozen=True)
class _RiskResolution:
    proposal_result: ProposalResult
    authority: str
    degraded_reasons: list[str]


def simulate_with_lotus_core(
    *,
    request: ProposalSimulateRequest,
    request_hash: str,
    idempotency_key: str | None,
    correlation_id: str,
    policy_context: dict[str, object] | None = None,
) -> ProposalResult:
    return cast(
        ProposalResult,
        simulate_with_advisory_simulation_provider(
            request=request,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            policy_context=policy_context,
        ),
    )


def enrich_with_lotus_risk(
    *,
    request: ProposalSimulateRequest,
    proposal_result: ProposalResult,
    correlation_id: str,
    resolved_as_of: str | None = None,
    input_mode: str | None = None,
) -> ProposalResult:
    return cast(
        ProposalResult,
        enrich_with_advisory_risk_provider(
            request=request,
            proposal_result=proposal_result,
            correlation_id=correlation_id,
            resolved_as_of=resolved_as_of,
            input_mode=input_mode,
        ),
    )


def build_lotus_risk_dependency_state() -> AdvisoryProviderDependencyState:
    return build_advisory_risk_dependency_state()


def evaluate_advisory_proposal(
    *,
    request: ProposalSimulateRequest,
    request_hash: str,
    idempotency_key: str | None,
    correlation_id: str,
    resolved_as_of: str | None = None,
    input_mode: str | None = None,
    requested_as_of_date: str | None = None,
    requested_reporting_currency: str | None = None,
    policy_context: dict[str, object] | None = None,
) -> ProposalResult:
    idempotency_key = normalize_optional_idempotency_key(idempotency_key)
    simulation = _resolve_simulation(
        request=request,
        request_hash=request_hash,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        policy_context=policy_context,
    )
    risk = _resolve_risk_enrichment(
        request=request,
        proposal_result=simulation.proposal_result,
        correlation_id=correlation_id,
        resolved_as_of=resolved_as_of,
        input_mode=input_mode,
        degraded_reasons=simulation.degraded_reasons,
    )
    _attach_authority_explanation(
        proposal_result=risk.proposal_result,
        simulation_authority=simulation.authority,
        risk_authority=risk.authority,
        degraded_reasons=risk.degraded_reasons,
        policy_context=policy_context,
    )
    _attach_proposal_outputs(
        request=request,
        proposal_result=risk.proposal_result,
        correlation_id=correlation_id,
        resolved_as_of=resolved_as_of,
        policy_context=policy_context,
    )
    risk.proposal_result.valuation_context = build_proposal_valuation_context(
        portfolio=request.portfolio_snapshot,
        before=risk.proposal_result.before,
        simulated=risk.proposal_result.after_simulated,
        source_provenance=risk.proposal_result.lineage.source_provenance,
        requested_as_of_date=requested_as_of_date,
        requested_reporting_currency=requested_reporting_currency,
        input_mode=input_mode,
    )
    return cast(ProposalResult, risk.proposal_result)


def _resolve_simulation(
    *,
    request: ProposalSimulateRequest,
    request_hash: str,
    idempotency_key: str | None,
    correlation_id: str,
    policy_context: dict[str, object] | None,
) -> _SimulationResolution:
    try:
        return _SimulationResolution(
            proposal_result=simulate_with_lotus_core(
                request=request,
                request_hash=request_hash,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                policy_context=policy_context,
            ),
            authority="lotus_core",
            degraded_reasons=[],
        )
    except AdvisorySimulationUnavailableError as exc:
        proposal_result = _run_local_fallback_simulation(
            request=request,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            policy_context=policy_context,
            original_error=exc,
        )
        return _SimulationResolution(
            proposal_result=proposal_result,
            authority="lotus_advise_local_fallback",
            degraded_reasons=["LOTUS_CORE_SIMULATION_UNAVAILABLE"],
        )


def _run_local_fallback_simulation(
    *,
    request: ProposalSimulateRequest,
    request_hash: str,
    idempotency_key: str | None,
    correlation_id: str,
    policy_context: dict[str, object] | None,
    original_error: AdvisorySimulationUnavailableError,
) -> ProposalResult:
    fallback_policy = resolve_advisory_simulation_fallback_policy()
    if fallback_policy.requested and not fallback_policy.permitted:
        raise AdvisorySimulationUnavailableError(
            "LOTUS_CORE_SIMULATION_REQUIRED_IN_THIS_ENVIRONMENT",
            status_code=original_error.status_code,
        ) from original_error
    if not fallback_policy.enabled:
        raise original_error

    proposal_result = cast(
        ProposalResult,
        run_proposal_simulation(
            portfolio=request.portfolio_snapshot,
            market_data=request.market_data_snapshot,
            shelf=request.shelf_entries,
            options=request.options,
            proposed_cash_flows=request.proposed_cash_flows,
            proposed_trades=request.proposed_trades,
            reference_model=request.reference_model,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            simulation_contract_version="advisory-simulation.v1",
            policy_context=policy_context,
        ),
    )
    proposal_result.allocation_lens.source = "LOTUS_ADVISE_LOCAL_FALLBACK"
    return proposal_result


def _resolve_risk_enrichment(
    *,
    request: ProposalSimulateRequest,
    proposal_result: ProposalResult,
    correlation_id: str,
    resolved_as_of: str | None,
    input_mode: str | None,
    degraded_reasons: list[str],
) -> _RiskResolution:
    combined_degraded_reasons = list(degraded_reasons)
    lotus_risk_state = build_lotus_risk_dependency_state()
    try:
        proposal_result = enrich_with_lotus_risk(
            request=request,
            proposal_result=proposal_result,
            correlation_id=correlation_id,
            resolved_as_of=resolved_as_of,
            input_mode=input_mode,
        )
        return _RiskResolution(proposal_result, "lotus_risk", combined_degraded_reasons)
    except AdvisoryRiskEnrichmentUnavailableError:
        combined_degraded_reasons.append(_risk_degraded_reason(lotus_risk_state))
        return _RiskResolution(proposal_result, "unavailable", combined_degraded_reasons)


def _risk_degraded_reason(lotus_risk_state: object) -> str:
    state_reason = getattr(lotus_risk_state, "degraded_reason", None)
    if isinstance(state_reason, str) and state_reason:
        return state_reason
    if getattr(lotus_risk_state, "configured", True) is False:
        return _LOTUS_RISK_DEPENDENCY_UNAVAILABLE
    return _LOTUS_RISK_ENRICHMENT_UNAVAILABLE


def _attach_authority_explanation(
    *,
    proposal_result: ProposalResult,
    simulation_authority: str,
    risk_authority: str,
    degraded_reasons: list[str],
    policy_context: dict[str, object] | None,
) -> None:
    authority_resolution = build_authority_resolution_explanation(
        simulation_authority=simulation_authority,
        risk_authority=risk_authority,
        degraded_reasons=degraded_reasons,
    )
    proposal_result.explanation = attach_governed_explanation_sections(
        explanation=proposal_result.explanation,
        authority_resolution=authority_resolution,
        policy_context=policy_context,
    )


def _attach_proposal_outputs(
    *,
    request: ProposalSimulateRequest,
    proposal_result: ProposalResult,
    correlation_id: str,
    resolved_as_of: str | None,
    policy_context: dict[str, object] | None,
) -> None:
    proposal_result.proposal_decision_summary = build_proposal_decision_summary(proposal_result)
    proposal_result.proposal_alternatives = build_proposal_alternatives(
        request=request,
        baseline_result=proposal_result,
        correlation_id=correlation_id,
        resolved_as_of=resolved_as_of,
        policy_context=policy_context,
    )
