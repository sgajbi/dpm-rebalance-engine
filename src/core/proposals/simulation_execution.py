from typing import Any

from src.core.advisory.orchestration import evaluate_advisory_proposal
from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposal_result_models import ProposalResult
from src.core.proposals.correlation import resolve_correlation_id


def run_advisory_proposal_simulation(
    *,
    request: ProposalSimulateRequest,
    resolved_as_of: str | None,
    input_mode: str | None = None,
    requested_as_of_date: str | None = None,
    requested_reporting_currency: str | None = None,
    request_hash: str,
    idempotency_key: str | None,
    correlation_id: str | None,
    policy_context: dict[str, Any] | None = None,
) -> ProposalResult:
    return evaluate_advisory_proposal(
        request=request,
        request_hash=request_hash,
        idempotency_key=idempotency_key,
        correlation_id=resolve_correlation_id(correlation_id),
        resolved_as_of=resolved_as_of,
        input_mode=input_mode,
        requested_as_of_date=requested_as_of_date,
        requested_reporting_currency=requested_reporting_currency,
        policy_context=policy_context,
    )
