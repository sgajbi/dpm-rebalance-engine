from typing import Literal

from pydantic import BaseModel, Field

from src.api.observability_contracts import ADVISORY_SUPPORTABILITY_METRIC_LABELS

SupportabilityState = Literal["ready", "degraded", "stale", "empty", "unsupported"]
SupportabilityReason = Literal[
    "advisory_ready",
    "dependency_degraded",
    "lifecycle_disabled",
    "supportability_unsupported",
]
FreshnessBucket = Literal["current", "stale", "unknown"]


class AdvisorySupportability(BaseModel):
    state: SupportabilityState = Field(
        description="Source-backed advisory supportability state for UI-facing advisory workflows.",
        examples=["ready"],
    )
    reason: SupportabilityReason = Field(
        description="Bounded reason code explaining the advisory supportability state.",
        examples=["advisory_ready"],
    )
    freshness_bucket: FreshnessBucket = Field(
        description="Bounded freshness bucket for advisory dependency and lifecycle posture.",
        examples=["current"],
    )
    metric_labels: tuple[str, ...] = Field(
        default=ADVISORY_SUPPORTABILITY_METRIC_LABELS,
        description=(
            "Prometheus labels emitted by lotus_advise_advisory_supportability_total. "
            "The tuple is intentionally bounded and excludes portfolio, client, request, "
            "response, correlation, trace, transaction, security, proposal, workspace, and "
            "payload identifiers."
        ),
        examples=[list(ADVISORY_SUPPORTABILITY_METRIC_LABELS)],
    )
    dependency_count: int = Field(
        ge=0,
        description=(
            "Number of advisory dependency boundaries evaluated for supportability, including "
            "required boundaries absent from the readiness inventory."
        ),
        examples=[5],
    )
    ready_dependency_count: int = Field(
        ge=0,
        description=(
            "Number of advisory dependency boundaries currently operationally ready; this may "
            "be lower than dependency_count when an optional dependency is unconfigured."
        ),
        examples=[5],
    )
    degraded_dependency_count: int = Field(
        ge=0,
        description=(
            "Number of required advisory dependency boundaries currently degraded. Optional "
            "unconfigured dependencies are excluded from this count; required boundaries absent "
            "from the readiness inventory are counted as degraded."
        ),
        examples=[0],
    )
    enabled_feature_count: int = Field(
        ge=0,
        description="Number of advisory features enabled in the current runtime policy.",
        examples=[8],
    )
    ready_feature_count: int = Field(
        ge=0,
        description="Number of enabled advisory features currently operationally ready.",
        examples=[8],
    )


__all__ = [
    "AdvisorySupportability",
    "FreshnessBucket",
    "SupportabilityReason",
    "SupportabilityState",
]
