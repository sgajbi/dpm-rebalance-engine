from decimal import Decimal

from src.api.main import app
from src.core.advisory.valuation_context import build_proposal_valuation_context
from src.core.advisory.valuation_context_models import ProposalValuationContext
from src.core.portfolio_models import Money, PortfolioSnapshot
from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposals.context_ports import (
    ResolvedStatefulProposalContext,
    configure_proposal_stateful_context_resolver,
    reset_proposal_stateful_context_resolver_for_tests,
)
from src.core.proposals.context_resolution import resolve_create_request
from src.core.proposals.input_context_models import ProposalResolvedContext
from src.core.proposals.input_request_models import ProposalCreateRequest
from src.core.simulation_state_models import SimulatedState
from src.core.source_provenance_models import (
    SourceProvenanceEnvelope,
    SourceProvenanceRecord,
)


def _state(currency: str) -> SimulatedState:
    return SimulatedState(total_value=Money(amount=Decimal("100"), currency=currency))


def _provenance(*, portfolio_as_of: str = "2026-03-25", market_as_of: str | None = None):
    return SourceProvenanceEnvelope(
        source_system="LOTUS_CORE",
        portfolio=SourceProvenanceRecord(
            source_system="LOTUS_CORE",
            source_kind="PORTFOLIO",
            source_id="portfolio-snapshot-001",
            as_of=portfolio_as_of,
            contract_version="advisory-simulation.v1",
        ),
        market_data=SourceProvenanceRecord(
            source_system="LOTUS_CORE",
            source_kind="MARKET_DATA",
            source_id="market-snapshot-001",
            as_of=market_as_of or portfolio_as_of,
            contract_version="advisory-simulation.v1",
        ),
    )


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(portfolio_id="PB_SG_GLOBAL_BAL_001", base_currency="USD")


def _context(
    *,
    currency: str = "USD",
    source_provenance: SourceProvenanceEnvelope | None = None,
    requested_as_of_date: str | None = None,
    requested_reporting_currency: str | None = None,
) -> ProposalValuationContext:
    return build_proposal_valuation_context(
        before=_state(currency),
        simulated=_state(currency),
        source_provenance=source_provenance,
        requested_as_of_date=requested_as_of_date,
        requested_reporting_currency=requested_reporting_currency,
    )


def test_valuation_context_preserves_ready_source_evidence_for_both_states() -> None:
    context = _context(
        source_provenance=_provenance(),
        requested_as_of_date="2026-03-25",
        requested_reporting_currency="USD",
    )

    assert context.schema_version == "lotus.proposal-valuation-context.v1"
    assert context.source_service == "LOTUS_CORE"
    assert context.source_references == ["market-snapshot-001", "portfolio-snapshot-001"]
    assert context.current_state.model_dump() == context.simulated_state.model_dump()
    assert context.current_state.supportability == "READY"
    assert context.current_state.effective_as_of_date == "2026-03-25"
    assert context.current_state.effective_reporting_currency == "USD"
    assert context.current_state.reason_code is None


def test_valuation_context_restricts_unhonored_requested_date_and_currency() -> None:
    context = _context(
        currency="EUR",
        source_provenance=_provenance(portfolio_as_of="2026-03-26"),
        requested_as_of_date="2026-03-25",
        requested_reporting_currency="USD",
    )

    assert context.current_state.supportability == "RESTRICTED"
    assert context.current_state.reason_code == "REQUESTED_AS_OF_NOT_HONORED"
    assert context.current_state.effective_as_of_date == "2026-03-26"
    assert context.current_state.effective_reporting_currency == "EUR"


def test_valuation_context_reports_source_date_mismatch_without_inference() -> None:
    context = _context(
        source_provenance=_provenance(portfolio_as_of="2026-03-25", market_as_of="2026-03-26"),
        requested_as_of_date="2026-03-25",
        requested_reporting_currency="USD",
    )

    assert context.current_state.effective_as_of_date is None
    assert context.current_state.supportability == "PARTIAL"
    assert context.current_state.reason_code == "SOURCE_AS_OF_MISMATCH"


def test_valuation_context_preserves_missing_source_and_omitted_request_posture() -> None:
    missing_source = _context(requested_reporting_currency="USD")
    omitted_request = _context(source_provenance=_provenance())

    assert missing_source.current_state.effective_as_of_date is None
    assert missing_source.current_state.effective_reporting_currency == "USD"
    assert missing_source.current_state.supportability == "PARTIAL"
    assert missing_source.current_state.reason_code == "SOURCE_AS_OF_UNAVAILABLE"
    assert omitted_request.current_state.requested_reporting_currency is None
    assert omitted_request.current_state.effective_reporting_currency == "USD"
    assert omitted_request.current_state.supportability == "READY"


def test_openapi_publishes_typed_valuation_context_fields() -> None:
    schemas = app.openapi()["components"]["schemas"]
    state_schema = schemas["ProposalValuationContextState"]
    context_schema = schemas["ProposalValuationContext"]

    assert {
        "requested_as_of_date",
        "effective_as_of_date",
        "requested_reporting_currency",
        "effective_reporting_currency",
        "supportability",
        "reason_code",
    } <= set(state_schema["properties"])
    assert set(context_schema["properties"]) >= {
        "schema_version",
        "source_service",
        "source_references",
        "current_state",
        "simulated_state",
    }
    assert (
        "not authoritative valuation evidence"
        in schemas["WorkspaceResolvedContext"]["properties"]["as_of"]["description"]
    )
    assert (
        "date reason takes precedence" in state_schema["properties"]["reason_code"]["description"]
    )
    assert "valuation_context" in schemas["ProposalResult"]["properties"]


def test_stateful_resolution_preserves_requested_date_and_currency_for_lifecycle_evidence() -> None:
    resolved_context = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of": "2026-03-26",
        "portfolio_snapshot_id": "portfolio-snapshot-001",
        "market_data_snapshot_id": "market-snapshot-001",
    }
    request = ProposalCreateRequest(
        created_by="advisor_001",
        input_mode="stateful",
        stateful_input={
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "as_of": "2026-03-25",
            "reporting_currency": "USD",
        },
    )

    try:
        configure_proposal_stateful_context_resolver(
            lambda _input: ResolvedStatefulProposalContext(
                simulate_request=ProposalSimulateRequest.model_validate(
                    {
                        "portfolio_snapshot": _portfolio().model_dump(mode="json"),
                        "market_data_snapshot": {},
                        "shelf_entries": [],
                        "options": {"enable_proposal_simulation": True},
                        "proposed_cash_flows": [],
                        "proposed_trades": [],
                    }
                ),
                resolved_context=ProposalResolvedContext.model_validate(resolved_context),
            )
        )
        resolved = resolve_create_request(request)
    finally:
        reset_proposal_stateful_context_resolver_for_tests()

    assert resolved.resolved_context.requested_as_of == "2026-03-25"
    assert resolved.resolved_context.as_of == "2026-03-26"
    assert resolved.resolved_context.requested_reporting_currency == "USD"
