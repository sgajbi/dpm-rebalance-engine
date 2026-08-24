from typing import Optional

from pydantic import BaseModel, Field

from src.core.advisory.context_models import AdvisoryResolvedContext, AdvisoryStatefulInput
from src.core.advisory.narrative_request_models import ProposalNarrativeRequest
from src.core.proposal_request_models import ProposalSimulateRequest


class ProposalCreateMetadata(BaseModel):
    title: Optional[str] = Field(
        default=None,
        description="Optional advisor-facing proposal title.",
        examples=["2026 client portfolio transition plan"],
    )
    advisor_notes: Optional[str] = Field(
        default=None,
        description="Optional free-text advisor notes captured at proposal creation.",
        examples=["Client asked for controlled equity rotation with cash discipline."],
    )
    jurisdiction: Optional[str] = Field(
        default=None,
        description="Optional proposal jurisdiction code.",
        examples=["SG"],
    )
    mandate_id: Optional[str] = Field(
        default=None,
        description="Optional mandate identifier for the proposal context.",
        examples=["mandate_growth_01"],
    )


class ProposalStatelessInput(BaseModel):
    simulate_request: ProposalSimulateRequest = Field(
        description=(
            "Full advisory simulation payload supplied directly by the caller for deterministic "
            "proposal create and replay-safe lifecycle workflows."
        ),
        examples=[
            {
                "portfolio_snapshot": {
                    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                    "base_currency": "USD",
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        ],
    )


class ProposalStatefulInput(AdvisoryStatefulInput):
    narrative_request: Optional[ProposalNarrativeRequest] = Field(
        default=None,
        description=(
            "Optional advisor-review narrative request applied after authoritative portfolio "
            "context is resolved from Lotus Core. Client-ready publication remains gated."
        ),
    )


class ProposalResolvedContext(AdvisoryResolvedContext):
    pass
