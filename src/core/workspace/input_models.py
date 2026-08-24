from typing import Literal

from pydantic import BaseModel, Field

from src.core.advisory.context_models import AdvisoryResolvedContext, AdvisoryStatefulInput
from src.core.proposal_request_models import ProposalSimulateRequest

WorkspaceInputMode = Literal["stateless", "stateful"]


class WorkspaceStatelessInput(BaseModel):
    simulate_request: ProposalSimulateRequest = Field(
        description=(
            "Full advisory simulation payload supplied directly by the caller for sandbox, replay, "
            "or external integration workflows."
        ),
        examples=[
            {
                "portfolio_snapshot": {
                    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "250000"}],
                },
                "market_data_snapshot": {"prices": [], "fx_rates": []},
                "shelf_entries": [],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [],
            }
        ],
    )


class WorkspaceStatefulInput(AdvisoryStatefulInput):
    pass


class WorkspaceResolvedContext(AdvisoryResolvedContext):
    pass
