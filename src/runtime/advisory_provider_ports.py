from __future__ import annotations

from src.core.advisory.narrative_ai_ports import (
    ProposalNarrativeDraftResponse,
    ProposalNarrativeDraftUnavailableError,
    configure_proposal_narrative_draft_generator,
)
from src.core.advisory.narrative_grounding_models import ProposalNarrativeGroundingPacket
from src.core.advisory.narrative_policy_models import ProposalNarrativePolicy
from src.core.advisory.narrative_types import ProposalNarrativeSectionKey
from src.core.advisory.provider_ports import (
    AdvisoryProviderDependencyState,
    AdvisoryRiskEnrichmentUnavailableError,
    AdvisorySimulationUnavailableError,
    configure_advisory_risk_dependency_state_provider,
    configure_advisory_risk_enrichment_provider,
    configure_advisory_simulation_provider,
)
from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposal_result_models import ProposalResult
from src.core.proposals.context_ports import (
    ResolvedStatefulProposalContext,
    configure_proposal_stateful_context_resolver,
)
from src.core.proposals.memo_ai_ports import (
    ProposalMemoAiCommentaryDraft,
    ProposalMemoAiCommentaryUnavailableError,
    configure_proposal_memo_ai_commentary_generator,
)
from src.core.proposals.memo_report_ports import (
    ProposalMemoReportPackageUnavailableError,
    configure_proposal_memo_report_package_requester,
)
from src.core.proposals.models import ProposalReportResponse, ProposalStatefulInput
from src.integrations.lotus_ai import (
    LotusAIProposalMemoUnavailableError,
    LotusAIProposalNarrativeUnavailableError,
    generate_proposal_memo_commentary_with_lotus_ai,
    generate_proposal_narrative_draft_with_lotus_ai,
)
from src.integrations.lotus_core import (
    LotusCoreContextResolutionError,
    LotusCoreSimulationUnavailableError,
    resolve_lotus_core_advisory_context,
    simulate_with_lotus_core,
)
from src.integrations.lotus_report import (
    LotusReportUnavailableError,
    request_proposal_memo_report_package_with_lotus_report,
)
from src.integrations.lotus_risk import (
    LotusRiskEnrichmentUnavailableError,
    build_lotus_risk_dependency_state,
    enrich_with_lotus_risk,
)


def configure_advisory_external_provider_ports() -> None:
    configure_advisory_simulation_provider(_simulate_with_lotus_core_port)
    configure_advisory_risk_enrichment_provider(_enrich_with_lotus_risk_port)
    configure_advisory_risk_dependency_state_provider(_lotus_risk_dependency_state_port)
    configure_advisory_stateful_context_provider_port()
    configure_proposal_narrative_draft_generator(_generate_narrative_draft_with_lotus_ai_port)
    configure_proposal_memo_ai_commentary_generator(_generate_memo_commentary_with_lotus_ai_port)
    configure_proposal_memo_report_package_requester(_request_memo_report_package_with_lotus_report)


def configure_advisory_stateful_context_provider_port() -> None:
    configure_proposal_stateful_context_resolver(_resolve_stateful_context_with_lotus_core_port)


def _simulate_with_lotus_core_port(
    request: ProposalSimulateRequest,
    request_hash: str,
    idempotency_key: str | None,
    correlation_id: str,
    policy_context: dict[str, object] | None,
) -> ProposalResult:
    try:
        return simulate_with_lotus_core(
            request=request,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            policy_context=policy_context,
        )
    except LotusCoreSimulationUnavailableError as exc:
        raise AdvisorySimulationUnavailableError(
            str(exc),
            status_code=exc.status_code,
        ) from exc


def _enrich_with_lotus_risk_port(
    request: ProposalSimulateRequest,
    proposal_result: ProposalResult,
    correlation_id: str,
    resolved_as_of: str | None,
    input_mode: str | None,
) -> ProposalResult:
    try:
        return enrich_with_lotus_risk(
            request=request,
            proposal_result=proposal_result,
            correlation_id=correlation_id,
            resolved_as_of=resolved_as_of,
            input_mode=input_mode,
        )
    except LotusRiskEnrichmentUnavailableError as exc:
        raise AdvisoryRiskEnrichmentUnavailableError(str(exc)) from exc


def _lotus_risk_dependency_state_port() -> AdvisoryProviderDependencyState:
    dependency_state = build_lotus_risk_dependency_state()
    return AdvisoryProviderDependencyState(
        configured=bool(dependency_state.configured),
        degraded_reason=dependency_state.degraded_reason,
    )


def _resolve_stateful_context_with_lotus_core_port(
    stateful_input: ProposalStatefulInput,
) -> ResolvedStatefulProposalContext:
    try:
        resolved = resolve_lotus_core_advisory_context(stateful_input)
    except LotusCoreContextResolutionError as exc:
        from src.core.proposals.context_ports import (
            ProposalStatefulContextResolutionUnavailableError,
        )

        raise ProposalStatefulContextResolutionUnavailableError(str(exc)) from exc
    return ResolvedStatefulProposalContext(
        simulate_request=resolved.simulate_request,
        resolved_context=resolved.resolved_context,
    )


def _generate_narrative_draft_with_lotus_ai_port(
    grounding_packet: ProposalNarrativeGroundingPacket,
    narrative_policy: ProposalNarrativePolicy,
    requested_sections: list[ProposalNarrativeSectionKey],
    requested_by: str | None,
) -> ProposalNarrativeDraftResponse:
    try:
        return generate_proposal_narrative_draft_with_lotus_ai(
            grounding_packet=grounding_packet,
            narrative_policy=narrative_policy,
            requested_sections=requested_sections,
            requested_by=requested_by,
        )
    except LotusAIProposalNarrativeUnavailableError as exc:
        raise ProposalNarrativeDraftUnavailableError(str(exc)) from exc


def _generate_memo_commentary_with_lotus_ai_port(
    memo_evidence: dict[str, object],
    requested_sections: list[str],
    requested_by: str,
    reason: dict[str, object],
    idempotency_key: str | None,
) -> ProposalMemoAiCommentaryDraft:
    try:
        return generate_proposal_memo_commentary_with_lotus_ai(
            memo_evidence=memo_evidence,
            requested_sections=requested_sections,
            requested_by=requested_by,
            reason=reason,
            idempotency_key=idempotency_key,
        )
    except LotusAIProposalMemoUnavailableError as exc:
        raise ProposalMemoAiCommentaryUnavailableError(str(exc)) from exc


def _request_memo_report_package_with_lotus_report(
    request: dict[str, object],
) -> ProposalReportResponse:
    try:
        return request_proposal_memo_report_package_with_lotus_report(request=request)
    except LotusReportUnavailableError as exc:
        raise ProposalMemoReportPackageUnavailableError(str(exc)) from exc


__all__ = [
    "configure_advisory_external_provider_ports",
    "configure_advisory_stateful_context_provider_port",
]
