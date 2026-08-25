from __future__ import annotations

from collections.abc import Mapping

from src.core.advisory.proposal_review_evidence_models import (
    BenchmarkAssignmentEvidence,
    MandateLimitEvidenceState,
    ProposalReviewEvidence,
)
from src.core.advisory.valuation_context_models import ProposalValuationContext


def build_proposal_review_evidence(
    *,
    policy_context: Mapping[str, object] | None,
    valuation_context: ProposalValuationContext,
) -> ProposalReviewEvidence:
    """Project requested selectors while keeping absent source evidence explicit."""

    benchmark_id = _optional_text(policy_context, "benchmark_id")
    mandate_id = _optional_text(policy_context, "mandate_id")
    return ProposalReviewEvidence(
        benchmark_assignment=BenchmarkAssignmentEvidence(
            requested_benchmark_id=benchmark_id,
            requested_as_of_date=valuation_context.current_state.requested_as_of_date,
            supportability="UNAVAILABLE",
            reason_code="BENCHMARK_EVIDENCE_UNAVAILABLE",
        ),
        current_mandate_limits=_build_mandate_limit_state(
            mandate_id=mandate_id,
            requested_as_of_date=valuation_context.current_state.requested_as_of_date,
        ),
        simulated_mandate_limits=_build_mandate_limit_state(
            mandate_id=mandate_id,
            requested_as_of_date=valuation_context.simulated_state.requested_as_of_date,
        ),
    )


def _build_mandate_limit_state(
    mandate_id: str | None, requested_as_of_date: str | None
) -> MandateLimitEvidenceState:
    return MandateLimitEvidenceState(
        mandate_id=mandate_id,
        requested_as_of_date=requested_as_of_date,
        supportability="UNAVAILABLE",
        reason_code="MANDATE_LIMIT_EVIDENCE_UNAVAILABLE",
    )


def _optional_text(context: Mapping[str, object] | None, key: str) -> str | None:
    value = context.get(key) if context is not None else None
    return value.strip() if isinstance(value, str) and value.strip() else None
