from typing import Optional

from pydantic import BaseModel, Field

from src.core.source_completeness_models import SourceCompletenessReport
from src.core.source_provenance_models import SourceProvenanceEnvelope


class AdvisoryStatefulInput(BaseModel):
    """Shared caller-owned dimensions for stateful advisory context resolution."""

    portfolio_id: str = Field(
        description="Canonical Lotus portfolio identifier resolved through upstream services.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    as_of: str = Field(
        description="Business date or timestamp used to resolve the authoritative source context.",
        examples=["2026-03-25"],
    )
    reporting_currency: Optional[str] = Field(
        default=None,
        description=(
            "Optional requested reporting currency. The effective source currency is returned "
            "separately and any mismatch remains explicitly restricted."
        ),
        examples=["USD"],
    )
    household_id: Optional[str] = Field(
        default=None,
        description="Optional household identifier when the advisory workflow is household-scoped.",
        examples=["hh_001"],
    )
    mandate_id: Optional[str] = Field(
        default=None,
        description="Optional mandate identifier used to enrich the advisory context.",
        examples=["mandate_growth_01"],
    )
    benchmark_id: Optional[str] = Field(
        default=None,
        description="Optional benchmark identifier for context-aware evaluation and comparison.",
        examples=["benchmark_balanced_usd"],
    )


class AdvisoryResolvedContext(BaseModel):
    """Shared source context used for stateful advisory evaluation and replay."""

    portfolio_id: str = Field(
        description="Resolved portfolio identifier used by advisory evaluation.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    as_of: str = Field(
        description=(
            "Resolved lifecycle date or timestamp used for evaluation, replay, or upstream "
            "request routing. This is not authoritative valuation evidence; consumers must use "
            "proposal_result.valuation_context.*.effective_as_of_date for valuation dates."
        ),
        examples=["2026-03-25"],
    )
    requested_as_of: Optional[str] = Field(
        default=None,
        description="Requested business date or timestamp before source resolution.",
        examples=["2026-03-25"],
    )
    requested_reporting_currency: Optional[str] = Field(
        default=None,
        description="Requested reporting currency before source resolution.",
        examples=["USD"],
    )
    portfolio_snapshot_id: Optional[str] = Field(
        default=None,
        description="Upstream portfolio snapshot id captured for replay and audit.",
        examples=["ps_20260325_001"],
    )
    market_data_snapshot_id: Optional[str] = Field(
        default=None,
        description="Upstream market-data snapshot id captured for replay and audit.",
        examples=["md_20260325_001"],
    )
    risk_context_id: Optional[str] = Field(
        default=None,
        description="Optional upstream risk-context identifier used for advisory enrichment.",
        examples=["risk_ctx_001"],
    )
    reporting_context_id: Optional[str] = Field(
        default=None,
        description="Optional reporting-context identifier used for downstream correlation.",
        examples=["report_ctx_001"],
    )
    source_provenance: Optional[SourceProvenanceEnvelope] = Field(
        default=None,
        description=(
            "Optional upstream source snapshot, version, freshness, and contract evidence used "
            "to resolve this advisory context."
        ),
    )
    source_completeness: Optional[SourceCompletenessReport] = Field(
        default=None,
        description=(
            "Optional upstream source row completeness and rejection-summary evidence used "
            "to reconcile stateful context hydration."
        ),
    )
