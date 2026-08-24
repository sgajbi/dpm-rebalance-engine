from src.api.services.advisory_simulation_errors import simulation_validation_exception
from src.core.advisory.alternatives_normalizer import AlternativesRequestNormalizationError
from src.core.advisory.orchestration import evaluate_advisory_proposal
from src.core.proposal_result_models import ProposalResult
from src.core.proposals.context_evidence import build_context_resolution_evidence
from src.core.proposals.context_resolution import ResolvedSimulationContext
from src.core.proposals.correlation import resolve_correlation_id


def evaluate_simulation_result(
    *,
    resolved_request: ResolvedSimulationContext,
    request_hash: str,
    idempotency_key: str,
    correlation_id: str | None,
) -> ProposalResult:
    resolved_correlation_id = resolve_correlation_id(correlation_id)
    context_resolution = build_context_resolution_evidence(resolved_request)
    try:
        result = evaluate_advisory_proposal(
            request=resolved_request.simulate_request,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            correlation_id=resolved_correlation_id,
            resolved_as_of=resolved_request.resolved_context.as_of,
            input_mode=resolved_request.input_mode,
            requested_as_of_date=getattr(
                resolved_request.resolved_context, "requested_as_of", None
            ),
            requested_reporting_currency=getattr(
                resolved_request.resolved_context, "requested_reporting_currency", None
            ),
            policy_context=context_resolution["advisory_policy_context"],
        )
    except AlternativesRequestNormalizationError as exc:
        raise simulation_validation_exception(f"{exc.reason_code}: {exc}") from exc
    result.explanation["context_resolution"] = context_resolution
    return result
