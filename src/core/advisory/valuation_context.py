from src.core.advisory.valuation_context_models import (
    ProposalValuationContext,
    ProposalValuationContextState,
    ValuationContextReasonCode,
    ValuationContextSupportability,
)
from src.core.simulation_state_models import SimulatedState
from src.core.source_provenance_models import SourceProvenanceEnvelope


def build_proposal_valuation_context(
    *,
    before: SimulatedState,
    simulated: SimulatedState,
    source_provenance: SourceProvenanceEnvelope | None,
    requested_as_of_date: str | None,
    requested_reporting_currency: str | None,
) -> ProposalValuationContext:
    effective_as_of_date, as_of_reason = _effective_as_of_date(
        source_provenance=source_provenance,
    )
    source_service, source_references = (
        (
            source_provenance.source_system,
            sorted(
                {
                    source_provenance.portfolio.source_id,
                    source_provenance.market_data.source_id,
                }
            ),
        )
        if source_provenance is not None
        else (None, [])
    )
    return ProposalValuationContext(
        source_service=source_service,
        source_references=source_references,
        current_state=_build_state(
            requested_as_of_date=requested_as_of_date,
            effective_as_of_date=effective_as_of_date,
            requested_reporting_currency=requested_reporting_currency,
            effective_reporting_currency=before.total_value.currency,
            as_of_reason=as_of_reason,
        ),
        simulated_state=_build_state(
            requested_as_of_date=requested_as_of_date,
            effective_as_of_date=effective_as_of_date,
            requested_reporting_currency=requested_reporting_currency,
            effective_reporting_currency=simulated.total_value.currency,
            as_of_reason=as_of_reason,
        ),
    )


def _effective_as_of_date(
    *, source_provenance: SourceProvenanceEnvelope | None
) -> tuple[str | None, ValuationContextReasonCode | None]:
    if source_provenance is None:
        return None, "SOURCE_AS_OF_UNAVAILABLE"
    values = (
        source_provenance.portfolio.as_of,
        source_provenance.market_data.as_of,
    )
    if values[0] != values[1]:
        return None, "SOURCE_AS_OF_MISMATCH"
    return values[0], None


def _build_state(
    *,
    requested_as_of_date: str | None,
    effective_as_of_date: str | None,
    requested_reporting_currency: str | None,
    effective_reporting_currency: str | None,
    as_of_reason: ValuationContextReasonCode | None,
) -> ProposalValuationContextState:
    reason_code = (
        _primary_requested_mismatch_reason(
            requested_as_of_date=requested_as_of_date,
            effective_as_of_date=effective_as_of_date,
            requested_reporting_currency=requested_reporting_currency,
            effective_reporting_currency=effective_reporting_currency,
        )
        or as_of_reason
    )
    return ProposalValuationContextState(
        requested_as_of_date=requested_as_of_date,
        effective_as_of_date=effective_as_of_date,
        requested_reporting_currency=requested_reporting_currency,
        effective_reporting_currency=effective_reporting_currency,
        supportability=_supportability(
            effective_as_of_date=effective_as_of_date,
            effective_reporting_currency=effective_reporting_currency,
            reason_code=reason_code,
        ),
        reason_code=reason_code,
    )


def _primary_requested_mismatch_reason(
    *,
    requested_as_of_date: str | None,
    effective_as_of_date: str | None,
    requested_reporting_currency: str | None,
    effective_reporting_currency: str | None,
) -> ValuationContextReasonCode | None:
    if _values_mismatch(requested_as_of_date, effective_as_of_date):
        return "REQUESTED_AS_OF_NOT_HONORED"
    if _values_mismatch(requested_reporting_currency, effective_reporting_currency):
        return "REQUESTED_REPORTING_CURRENCY_NOT_HONORED"
    return None


def _values_mismatch(requested: str | None, effective: str | None) -> bool:
    return requested is not None and effective is not None and requested != effective


def _supportability(
    *,
    effective_as_of_date: str | None,
    effective_reporting_currency: str | None,
    reason_code: ValuationContextReasonCode | None,
) -> ValuationContextSupportability:
    missing_evidence = sum(
        value is None for value in (effective_as_of_date, effective_reporting_currency)
    )
    if missing_evidence == 2:
        return "UNAVAILABLE"
    if missing_evidence:
        return "PARTIAL"
    if _is_requested_mismatch(reason_code):
        return "RESTRICTED"
    return "READY"


def _is_requested_mismatch(reason_code: ValuationContextReasonCode | None) -> bool:
    return reason_code is not None and reason_code.startswith("REQUESTED_")
