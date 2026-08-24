from typing import Literal

from pydantic import BaseModel, Field

ValuationContextSupportability = Literal[
    "READY",
    "PARTIAL",
    "RESTRICTED",
    "UNAVAILABLE",
    "NOT_SUPPORTED",
]
ValuationContextReasonCode = Literal[
    "SOURCE_AS_OF_MISMATCH",
    "SOURCE_AS_OF_UNAVAILABLE",
    "REQUESTED_AS_OF_NOT_HONORED",
    "REQUESTED_REPORTING_CURRENCY_NOT_HONORED",
    "VALUATION_CONTEXT_UNAVAILABLE",
]


class ProposalValuationContextState(BaseModel):
    requested_as_of_date: str | None = Field(
        default=None,
        description=(
            "Requested valuation/as-of date or timestamp. Null means the caller did not "
            "request a date explicitly."
        ),
        examples=["2026-03-25"],
    )
    effective_as_of_date: str | None = Field(
        default=None,
        description=(
            "Effective source valuation/as-of date or timestamp. Null means the source did not "
            "provide one that can be trusted for this state."
        ),
        examples=["2026-03-25"],
    )
    requested_reporting_currency: str | None = Field(
        default=None,
        description=(
            "Requested reporting currency. Null means the caller did not request a separate "
            "reporting currency."
        ),
        examples=["USD"],
    )
    effective_reporting_currency: str | None = Field(
        default=None,
        description=(
            "Currency actually used by the state valuation. This is source evidence, not a "
            "permission or suitability decision."
        ),
        examples=["USD"],
    )
    supportability: ValuationContextSupportability = Field(
        description=(
            "Supportability of the typed date/currency evidence. Missing evidence remains "
            "UNAVAILABLE and is never inferred as current, zero, pass, or approval."
        ),
        examples=["READY"],
    )
    reason_code: ValuationContextReasonCode | None = Field(
        default=None,
        description=(
            "Stable primary reason for partial, restricted, or unavailable evidence. When both "
            "requested date and currency are not honored, the date reason takes precedence; "
            "this field is not a complete list of all mismatches. Null means the requested and "
            "effective evidence agree."
        ),
        examples=["REQUESTED_AS_OF_NOT_HONORED"],
    )


class ProposalValuationContext(BaseModel):
    schema_version: Literal["lotus.proposal-valuation-context.v1"] = Field(
        default="lotus.proposal-valuation-context.v1",
        description="Versioned typed proposal valuation-context contract.",
    )
    source_service: str | None = Field(
        default=None,
        description="Authoritative source service for the valuation-context evidence.",
        examples=["LOTUS_CORE"],
    )
    source_references: list[str] = Field(
        default_factory=list,
        description=(
            "Stable source snapshot or revision references. Raw source payloads and opaque "
            "client-invented evidence are not stored here."
        ),
        examples=[["lotus-core:portfolio:PB_SG_GLOBAL_BAL_001:2026-03-25"]],
    )
    current_state: ProposalValuationContextState = Field(
        description="Typed valuation-context evidence for the current portfolio state."
    )
    simulated_state: ProposalValuationContextState = Field(
        description="Typed valuation-context evidence for the simulated proposal state."
    )

    @classmethod
    def unavailable(cls) -> "ProposalValuationContext":
        state = ProposalValuationContextState(
            supportability="UNAVAILABLE",
            reason_code="VALUATION_CONTEXT_UNAVAILABLE",
        )
        return cls(current_state=state, simulated_state=state.model_copy(deep=True))
