from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.core.advisory.alternatives_models import ProposalAlternatives
from src.core.advisory.decision_summary_models import ProposalDecisionSummary
from src.core.advisory.valuation_context_models import ProposalValuationContext
from src.core.diagnostics_models import DiagnosticsData, LineageData, RuleResult
from src.core.drift_models import DriftAnalysis
from src.core.gate_models import GateDecision
from src.core.order_intent_models import ProposalOrderIntent
from src.core.proposal_effect_models import Reconciliation
from src.core.simulation_state_models import ProposalAllocationLens, SimulatedState
from src.core.suitability_models import SuitabilityResult


class ProposalResult(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "proposal_run_id": "pr_abc12345",
                "correlation_id": "corr_123abc",
                "status": "READY",
                "intents": [],
                "diagnostics": {
                    "warnings": [],
                    "data_quality": {"price_missing": [], "fx_missing": []},
                },
                "lineage": {"request_hash": "sha256:...", "idempotency_key": "idem-1"},
            }
        }
    }

    proposal_run_id: str = Field(description="Proposal run identifier.", examples=["pr_abc12345"])
    correlation_id: str = Field(
        description="Correlation id used by request logging context.",
        examples=["corr_123abc"],
    )
    status: Literal["READY", "BLOCKED", "PENDING_REVIEW"] = Field(
        description="Top-level domain outcome.",
        examples=["READY"],
    )
    before: SimulatedState = Field(description="Before-state valuation snapshot.")
    intents: List[Annotated[ProposalOrderIntent, Field(discriminator="intent_type")]] = Field(
        description="Deterministically ordered proposal intents applied during simulation.",
        examples=[
            [
                {
                    "intent_type": "CASH_FLOW",
                    "intent_id": "oi_cf_1",
                    "currency": "USD",
                    "amount": "2000.00",
                },
                {
                    "intent_type": "SECURITY_TRADE",
                    "intent_id": "oi_1",
                    "side": "BUY",
                    "instrument_id": "EQ_GROWTH",
                    "quantity": "40",
                },
            ]
        ],
    )
    after_simulated: SimulatedState = Field(description="After-state simulation snapshot.")
    reconciliation: Optional[Reconciliation] = Field(
        default=None, description="Reconciliation output."
    )
    rule_results: List[RuleResult] = Field(
        default_factory=list, description="Rule engine evaluations."
    )
    explanation: Dict[str, Any] = Field(
        description=(
            "Governed explanatory payload. Material authority and policy-context sections must "
            "use the typed advisory explanation contracts; opaque extension metadata must remain "
            "explicitly bounded by the owning projection."
        ),
    )
    diagnostics: DiagnosticsData = Field(description="Diagnostics and warnings for the run.")
    drift_analysis: Optional[DriftAnalysis] = Field(
        default=None,
        description="Reference-model drift analytics when provided and enabled.",
    )
    suitability: Optional[SuitabilityResult] = Field(
        default=None,
        description="Advisory suitability scanner output with NEW/RESOLVED/PERSISTENT issues.",
    )
    gate_decision: Optional[GateDecision] = Field(
        default=None,
        description="Deterministic workflow gate decision for advisory workflow routing.",
    )
    proposal_decision_summary: Optional[ProposalDecisionSummary] = Field(
        default=None,
        description=(
            "Backend-owned advisory decision summary for UI, artifact, and replay consumers."
        ),
    )
    proposal_alternatives: ProposalAlternatives | None = Field(
        default=None,
        description="Backend-owned proposal alternatives envelope when alternatives are requested.",
    )
    allocation_lens: ProposalAllocationLens = Field(
        default_factory=ProposalAllocationLens,
        description="Canonical allocation-lens metadata for proposal before/after states.",
    )
    valuation_context: ProposalValuationContext = Field(
        default_factory=ProposalValuationContext.unavailable,
        description=(
            "Typed requested/effective valuation-date and reporting-currency evidence for "
            "current and simulated states. Missing source evidence is explicit and unavailable."
        ),
    )
    lineage: LineageData = Field(description="Lineage identifiers and request hash.")


__all__ = [
    "ProposalResult",
]
