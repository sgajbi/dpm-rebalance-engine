from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.openapi.utils import get_openapi
from pydantic import ValidationError

from src.api.main import app
from src.core.advisory.proposal_review_evidence import build_proposal_review_evidence
from src.core.advisory.proposal_review_evidence_models import (
    BenchmarkAssignmentEvidence,
    MandateLimitObservation,
)
from src.core.advisory.valuation_context_models import (
    ProposalValuationContext,
    ProposalValuationContextState,
)


def _valuation_context() -> ProposalValuationContext:
    states = [
        ProposalValuationContextState(requested_as_of_date=date, supportability="READY")
        for date in ("2026-03-25", "2026-03-26")
    ]
    return ProposalValuationContext(current_state=states[0], simulated_state=states[1])


def test_projection_keeps_requested_context_without_claiming_effective_evidence() -> None:
    evidence = build_proposal_review_evidence(
        policy_context={"benchmark_id": "BM_1", "mandate_id": "MANDATE_1"},
        valuation_context=_valuation_context(),
    )
    assert (
        evidence.benchmark_assignment.requested_benchmark_id,
        evidence.benchmark_assignment.effective_benchmark_id,
        evidence.benchmark_assignment.requested_as_of_date,
        evidence.benchmark_assignment.supportability,
    ) == ("BM_1", None, "2026-03-25", "UNAVAILABLE")
    assert evidence.benchmark_assignment.reason_code == (
        "BENCHMARK_ASSIGNMENT_EVIDENCE_UNAVAILABLE"
    )
    assert (
        evidence.current_mandate_limits.mandate_id,
        evidence.current_mandate_limits.requested_as_of_date,
        evidence.simulated_mandate_limits.requested_as_of_date,
    ) == ("MANDATE_1", "2026-03-25", "2026-03-26")
    unavailable = build_proposal_review_evidence(
        policy_context={"benchmark_id": "  ", "mandate_id": 123},
        valuation_context=_valuation_context(),
    )
    assert (
        unavailable.benchmark_assignment.requested_benchmark_id,
        unavailable.current_mandate_limits.mandate_id,
    ) == (None, None)


def test_mandate_limit_observation_preserves_typed_source_values() -> None:
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
    assert (observation.observed_value, observation.maximum, observation.source_references) == (
        Decimal("0.08"),
        Decimal("0.10"),
        ["lotus-core:mandate:MAX_SINGLE_POSITION:2026-03-25"],
    )


def test_evidence_models_reject_opaque_extension_fields() -> None:
    with pytest.raises(ValidationError):
        BenchmarkAssignmentEvidence(
            supportability="UNAVAILABLE",
            reason_code="BENCHMARK_ASSIGNMENT_EVIDENCE_UNAVAILABLE",
            opaque_payload={"effective_benchmark_id": "BM_INFERRED"},
        )


def test_unavailable_benchmark_evidence_is_revisited_when_core_route_is_added() -> None:
    core_client_source = Path(__file__).parents[4] / "src" / "integrations" / "lotus_core"
    benchmark_assignment_route = "/integration/portfolios/{portfolio_id}/benchmark-assignment"
    route_references = [
        path.read_text(encoding="utf-8") for path in core_client_source.glob("*.py")
    ]
    assert not any(benchmark_assignment_route in source for source in route_references), (
        "Advise now contains a Core benchmark-assignment route; map its source-owned contract "
        "into ProposalReviewEvidence before changing the published UNAVAILABLE posture."
    )


def test_proposal_result_openapi_publishes_additive_review_evidence_contract() -> None:
    schemas = get_openapi(title=app.title, version=app.version, routes=app.routes)["components"][
        "schemas"
    ]
    assert schemas["ProposalResult"]["properties"]["proposal_review_evidence"]["$ref"] == (
        "#/components/schemas/ProposalReviewEvidence"
    )
    assert set(schemas["ProposalReviewEvidence"]["required"]) == {
        "benchmark_assignment",
        "current_mandate_limits",
        "simulated_mandate_limits",
    }
