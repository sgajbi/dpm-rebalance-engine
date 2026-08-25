from decimal import Decimal

import pytest
from fastapi.openapi.utils import get_openapi
from pydantic import ValidationError

from src.api.main import app
from src.core.advisory.proposal_review_evidence import build_proposal_review_evidence
from src.core.advisory.proposal_review_evidence_models import (
    BenchmarkAssignmentEvidence,
    MandateLimitObservation,
    ProposalReviewEvidence,
)
from src.core.advisory.valuation_context_models import (
    ProposalValuationContext,
    ProposalValuationContextState,
)


def _valuation_context() -> ProposalValuationContext:
    return ProposalValuationContext(
        current_state=ProposalValuationContextState(
            requested_as_of_date="2026-03-25",
            effective_as_of_date="2026-03-25",
            requested_reporting_currency="USD",
            effective_reporting_currency="USD",
            supportability="READY",
        ),
        simulated_state=ProposalValuationContextState(
            requested_as_of_date="2026-03-26",
            effective_as_of_date="2026-03-26",
            requested_reporting_currency="USD",
            effective_reporting_currency="USD",
            supportability="READY",
        ),
    )


def test_unavailable_review_evidence_is_explicit_and_fail_closed() -> None:
    evidence = ProposalReviewEvidence.unavailable()

    assert evidence.schema_version == "lotus.proposal-review-evidence.v1"
    assert evidence.benchmark_assignment.effective_benchmark_id is None
    assert evidence.benchmark_assignment.supportability == "UNAVAILABLE"
    assert evidence.benchmark_assignment.reason_code == "BENCHMARK_ASSIGNMENT_UNAVAILABLE"
    assert evidence.current_mandate_limits.observations == []
    assert evidence.current_mandate_limits.supportability == "UNAVAILABLE"
    assert evidence.simulated_mandate_limits.supportability == "UNAVAILABLE"


def test_projection_retains_requested_context_without_claiming_effective_source_evidence() -> None:
    evidence = build_proposal_review_evidence(
        policy_context={
            "benchmark_id": "BM_GLOBAL_BALANCED_60_40",
            "mandate_id": "MANDATE_PB_SG_GLOBAL_BAL_001",
        },
        valuation_context=_valuation_context(),
    )

    assert evidence.benchmark_assignment.requested_benchmark_id == "BM_GLOBAL_BALANCED_60_40"
    assert evidence.benchmark_assignment.effective_benchmark_id is None
    assert evidence.benchmark_assignment.requested_as_of_date == "2026-03-25"
    assert evidence.benchmark_assignment.supportability == "UNAVAILABLE"
    assert evidence.current_mandate_limits.mandate_id == "MANDATE_PB_SG_GLOBAL_BAL_001"
    assert evidence.current_mandate_limits.requested_as_of_date == "2026-03-25"
    assert evidence.simulated_mandate_limits.requested_as_of_date == "2026-03-26"
    assert evidence.simulated_mandate_limits.effective_as_of_date is None
    assert evidence.simulated_mandate_limits.observations == []


def test_projection_ignores_blank_or_non_text_selectors() -> None:
    evidence = build_proposal_review_evidence(
        policy_context={"benchmark_id": "  ", "mandate_id": 123},
        valuation_context=_valuation_context(),
    )

    assert evidence.benchmark_assignment.requested_benchmark_id is None
    assert evidence.current_mandate_limits.mandate_id is None


def test_mandate_limit_observation_is_typed_and_preserves_source_values() -> None:
    observation = MandateLimitObservation(
        limit_code="MAX_SINGLE_POSITION",
        limit_name="Maximum single position weight",
        dimension="instrument_weight",
        scope="portfolio",
        observed_value=Decimal("0.08"),
        maximum=Decimal("0.10"),
        unit="PERCENT_OF_NAV",
        outcome="WITHIN_LIMIT",
        severity="INFO",
        source_references=["lotus-core:mandate:MAX_SINGLE_POSITION:2026-03-25"],
    )

    assert observation.observed_value == Decimal("0.08")
    assert observation.maximum == Decimal("0.10")
    assert observation.source_references == ["lotus-core:mandate:MAX_SINGLE_POSITION:2026-03-25"]


def test_evidence_models_reject_opaque_extension_fields() -> None:
    with pytest.raises(ValidationError):
        BenchmarkAssignmentEvidence(
            supportability="UNAVAILABLE",
            reason_code="BENCHMARK_ASSIGNMENT_UNAVAILABLE",
            opaque_payload={"effective_benchmark_id": "BM_INFERRED"},
        )


def test_proposal_result_openapi_publishes_additive_review_evidence_contract() -> None:
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    proposal_result = schema["components"]["schemas"]["ProposalResult"]
    evidence_ref = proposal_result["properties"]["proposal_review_evidence"]["$ref"]

    assert evidence_ref == "#/components/schemas/ProposalReviewEvidence"
    evidence_schema = schema["components"]["schemas"]["ProposalReviewEvidence"]
    assert set(evidence_schema["required"]) == {
        "benchmark_assignment",
        "current_mandate_limits",
        "simulated_mandate_limits",
    }
