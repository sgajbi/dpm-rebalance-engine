from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProposalReviewEvidenceSupportability = Literal[
    "READY",
    "PARTIAL",
    "RESTRICTED",
    "UNAVAILABLE",
    "NOT_SUPPORTED",
]
BenchmarkAssignmentReasonCode = Literal["BENCHMARK_ASSIGNMENT_UNAVAILABLE"]
MandateLimitReasonCode = Literal["MANDATE_LIMIT_EVIDENCE_UNAVAILABLE"]
MandateLimitOutcome = Literal["WITHIN_LIMIT", "BREACH", "PENDING_REVIEW", "UNAVAILABLE"]
MandateLimitSeverity = Literal["INFO", "WARNING", "BLOCKING"]


class BenchmarkAssignmentEvidence(BaseModel):
    """Source-owned benchmark assignment evidence for proposal review."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["lotus.proposal-benchmark-assignment.v1"] = Field(
        default="lotus.proposal-benchmark-assignment.v1",
        description="Versioned benchmark-assignment evidence contract.",
    )
    requested_benchmark_id: str | None = Field(
        default=None,
        description=(
            "Benchmark identifier requested by the proposal context. This is not evidence that "
            "the benchmark was applied."
        ),
        examples=["BM_GLOBAL_BALANCED_60_40"],
    )
    effective_benchmark_id: str | None = Field(
        default=None,
        description="Source-owned benchmark identifier actually applied to the proposal state.",
        examples=["BM_GLOBAL_BALANCED_60_40"],
    )
    requested_as_of_date: str | None = Field(
        default=None,
        description="As-of date requested for the benchmark evidence.",
        examples=["2026-03-25"],
    )
    effective_as_of_date: str | None = Field(
        default=None,
        description="Source-owned as-of date for the effective benchmark evidence.",
        examples=["2026-03-25"],
    )
    source_service: str | None = Field(
        default=None,
        description="Authoritative source service for effective benchmark evidence.",
        examples=["LOTUS_CORE"],
    )
    source_references: list[str] = Field(
        default_factory=list,
        description="Stable source references backing effective benchmark evidence.",
    )
    supportability: ProposalReviewEvidenceSupportability = Field(
        description=(
            "Whether effective benchmark evidence is source-backed. Requested context alone "
            "never upgrades this posture."
        ),
        examples=["UNAVAILABLE"],
    )
    reason_code: BenchmarkAssignmentReasonCode | None = Field(
        default=None,
        description="Stable reason for unavailable or restricted benchmark evidence.",
        examples=["BENCHMARK_ASSIGNMENT_UNAVAILABLE"],
    )


class MandateLimitObservation(BaseModel):
    """One source-owned mandate-limit observation, when supplied by an upstream owner."""

    model_config = ConfigDict(extra="forbid")

    limit_code: str = Field(description="Stable source-owned mandate-limit code.")
    limit_name: str = Field(description="Human-readable source-owned mandate-limit name.")
    dimension: str = Field(description="Measured portfolio or proposal dimension.")
    scope: str = Field(description="Scope to which the limit applies.")
    observed_value: Decimal | None = Field(
        default=None,
        description="Observed value supplied by the authoritative limit source.",
    )
    minimum: Decimal | None = Field(
        default=None,
        description="Inclusive lower bound supplied by the authoritative limit source.",
    )
    maximum: Decimal | None = Field(
        default=None,
        description="Inclusive upper bound supplied by the authoritative limit source.",
    )
    unit: str | None = Field(default=None, description="Unit of the observed value and bounds.")
    currency: str | None = Field(
        default=None,
        description="Currency of the observed value and bounds when monetary.",
    )
    outcome: MandateLimitOutcome = Field(description="Source-owned outcome for this limit.")
    severity: MandateLimitSeverity | None = Field(
        default=None,
        description="Source-owned materiality or severity, when provided.",
    )
    source_references: list[str] = Field(
        default_factory=list,
        description="Stable source references backing this observation.",
    )


class MandateLimitEvidenceState(BaseModel):
    """Current or simulated source-owned mandate-limit evidence state."""

    model_config = ConfigDict(extra="forbid")

    mandate_id: str | None = Field(
        default=None,
        description="Mandate identifier associated with the requested evaluation context.",
        examples=["MANDATE_PB_SG_GLOBAL_BAL_001"],
    )
    requested_as_of_date: str | None = Field(
        default=None,
        description="As-of date requested for the mandate-limit evidence.",
        examples=["2026-03-25"],
    )
    effective_as_of_date: str | None = Field(
        default=None,
        description="Source-owned as-of date for the effective mandate-limit evidence.",
        examples=["2026-03-25"],
    )
    observations: list[MandateLimitObservation] = Field(
        default_factory=list,
        description="Source-owned mandate-limit observations for this proposal state.",
    )
    source_service: str | None = Field(
        default=None,
        description="Authoritative source service for effective mandate-limit evidence.",
        examples=["LOTUS_CORE"],
    )
    source_references: list[str] = Field(
        default_factory=list,
        description="Stable source references backing effective mandate-limit evidence.",
    )
    supportability: ProposalReviewEvidenceSupportability = Field(
        description=(
            "Whether source-owned mandate-limit evidence is available for this proposal state."
        ),
        examples=["UNAVAILABLE"],
    )
    reason_code: MandateLimitReasonCode | None = Field(
        default=None,
        description="Stable reason for unavailable or restricted mandate-limit evidence.",
        examples=["MANDATE_LIMIT_EVIDENCE_UNAVAILABLE"],
    )


class ProposalReviewEvidence(BaseModel):
    """Versioned benchmark and mandate-limit evidence envelope for proposal consumers."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["lotus.proposal-review-evidence.v1"] = Field(
        default="lotus.proposal-review-evidence.v1",
        description="Versioned proposal-review evidence envelope.",
    )
    benchmark_assignment: BenchmarkAssignmentEvidence = Field(
        description="Requested/effective benchmark assignment evidence.",
    )
    current_mandate_limits: MandateLimitEvidenceState = Field(
        description="Source-owned mandate-limit evidence for the current portfolio state.",
    )
    simulated_mandate_limits: MandateLimitEvidenceState = Field(
        description="Source-owned mandate-limit evidence for the simulated proposal state.",
    )

    @classmethod
    def unavailable(cls) -> "ProposalReviewEvidence":
        return cls(
            benchmark_assignment=BenchmarkAssignmentEvidence(
                supportability="UNAVAILABLE",
                reason_code="BENCHMARK_ASSIGNMENT_UNAVAILABLE",
            ),
            current_mandate_limits=MandateLimitEvidenceState(
                supportability="UNAVAILABLE",
                reason_code="MANDATE_LIMIT_EVIDENCE_UNAVAILABLE",
            ),
            simulated_mandate_limits=MandateLimitEvidenceState(
                supportability="UNAVAILABLE",
                reason_code="MANDATE_LIMIT_EVIDENCE_UNAVAILABLE",
            ),
        )


__all__ = [
    "BenchmarkAssignmentEvidence",
    "BenchmarkAssignmentReasonCode",
    "MandateLimitEvidenceState",
    "MandateLimitObservation",
    "MandateLimitOutcome",
    "MandateLimitReasonCode",
    "MandateLimitSeverity",
    "ProposalReviewEvidence",
    "ProposalReviewEvidenceSupportability",
]
