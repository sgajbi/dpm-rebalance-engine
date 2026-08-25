from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ProposalReviewEvidenceSupportability = Literal[
    "READY", "PARTIAL", "RESTRICTED", "UNAVAILABLE", "NOT_SUPPORTED"
]
BenchmarkAssignmentReasonCode = Literal["BENCHMARK_EVIDENCE_UNAVAILABLE"]
MandateLimitReasonCode = Literal["MANDATE_LIMIT_EVIDENCE_UNAVAILABLE"]
MandateLimitOutcome = Literal["WITHIN_LIMIT", "BREACH", "PENDING_REVIEW", "UNAVAILABLE"]
MandateLimitSeverity = Literal["INFO", "WARNING", "BLOCKING"]


def _field(description: str, example: object, **kwargs: Any) -> Any:
    return Field(description=description, examples=[example], **kwargs)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BenchmarkAssignmentEvidence(_StrictModel):
    requested_benchmark_id: str | None = _field("Requested ID.", "BM_1", default=None)
    effective_benchmark_id: str | None = _field("Applied ID.", "BM_1", default=None)
    requested_as_of_date: str | None = _field("Requested date.", "2026-03-25", default=None)
    effective_as_of_date: str | None = _field("Applied date.", "2026-03-25", default=None)
    source_service: str | None = _field("Evidence source.", "LOTUS_CORE", default=None)
    source_references: list[str] = _field("Evidence references.", ["ref"], default_factory=list)
    supportability: ProposalReviewEvidenceSupportability = _field("Supportability.", "UNAVAILABLE")
    reason_code: BenchmarkAssignmentReasonCode | None = _field(
        "Evidence reason.", "BENCHMARK_EVIDENCE_UNAVAILABLE", default=None
    )


class MandateLimitObservation(_StrictModel):
    limit_code: str = _field("Stable limit code.", "MAX_POSITION")
    limit_name: str = _field("Limit display name.", "Maximum position")
    dimension: str = _field("Measured dimension.", "instrument_weight")
    scope: str = _field("Limit scope.", "portfolio")
    observed_value: Decimal | None = _field("Observed value.", 0.08, default=None)
    minimum: Decimal | None = _field("Inclusive lower bound.", 0, default=None)
    maximum: Decimal | None = _field("Inclusive upper bound.", 0.1, default=None)
    unit: str | None = _field("Value unit.", "PERCENT_OF_NAV", default=None)
    currency: str | None = _field("Monetary currency.", "USD", default=None)
    outcome: MandateLimitOutcome = _field("Limit outcome.", "WITHIN_LIMIT")
    severity: MandateLimitSeverity | None = _field("Limit severity.", "INFO", default=None)
    source_references: list[str] = _field("Observation references.", ["ref"], default_factory=list)


class MandateLimitEvidenceState(_StrictModel):
    mandate_id: str | None = _field("Mandate ID.", "MANDATE_1", default=None)
    requested_as_of_date: str | None = _field("Requested date.", "2026-03-25", default=None)
    effective_as_of_date: str | None = _field("Applied date.", "2026-03-25", default=None)
    observations: list[MandateLimitObservation] = _field(
        "Limit observations.", [], default_factory=list
    )
    source_service: str | None = _field("Evidence source.", "LOTUS_CORE", default=None)
    supportability: ProposalReviewEvidenceSupportability = _field("Supportability.", "UNAVAILABLE")
    reason_code: MandateLimitReasonCode | None = _field(
        "Evidence reason.", "MANDATE_LIMIT_EVIDENCE_UNAVAILABLE", default=None
    )


class ProposalReviewEvidence(_StrictModel):
    schema_version: Literal["lotus.proposal-review-evidence.v1"] = _field(
        "Contract version.",
        "lotus.proposal-review-evidence.v1",
        default="lotus.proposal-review-evidence.v1",
    )
    benchmark_assignment: BenchmarkAssignmentEvidence = _field("Benchmark evidence.", {})
    current_mandate_limits: MandateLimitEvidenceState = _field("Current limit evidence.", {})
    simulated_mandate_limits: MandateLimitEvidenceState = _field("Simulated limit evidence.", {})

    @classmethod
    def unavailable(cls) -> "ProposalReviewEvidence":
        unavailable_mandate = {
            "supportability": "UNAVAILABLE",
            "reason_code": "MANDATE_LIMIT_EVIDENCE_UNAVAILABLE",
        }
        return cls(
            benchmark_assignment=BenchmarkAssignmentEvidence(
                supportability="UNAVAILABLE", reason_code="BENCHMARK_EVIDENCE_UNAVAILABLE"
            ),
            current_mandate_limits=unavailable_mandate,
            simulated_mandate_limits=unavailable_mandate,
        )
