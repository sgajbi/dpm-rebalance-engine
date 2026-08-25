from dataclasses import dataclass, replace
from typing import cast

from pydantic import ValidationError

from src.core.advisory.policy_context import ProposalPolicySelectors
from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposals.context_ports import (
    ProposalStatefulContextResolutionUnavailableError,
    resolve_proposal_stateful_context,
)
from src.core.proposals.models import (
    ProposalCreateMetadata,
    ProposalCreateRequest,
    ProposalInputMode,
    ProposalResolvedContext,
    ProposalSimulationRequest,
    ProposalStatefulInput,
    ProposalVersionRequest,
)


class ProposalContextResolutionError(Exception):
    pass


@dataclass(frozen=True)
class ResolvedProposalContext:
    input_mode: ProposalInputMode
    resolution_source: str
    simulate_request: ProposalSimulateRequest
    resolved_context: ProposalResolvedContext
    metadata: ProposalCreateMetadata
    policy_selectors: ProposalPolicySelectors
    used_legacy_contract: bool


@dataclass(frozen=True)
class ResolvedSimulationContext:
    input_mode: ProposalInputMode
    resolution_source: str
    simulate_request: ProposalSimulateRequest
    resolved_context: ProposalResolvedContext
    policy_selectors: ProposalPolicySelectors
    used_legacy_contract: bool


def apply_context_resolution_override(
    resolved: ResolvedProposalContext,
    override: dict[str, object] | None,
) -> ResolvedProposalContext:
    """Apply an internal source-context projection without replacing the edited simulation."""

    if override is None:
        return resolved
    try:
        input_mode_value = override["input_mode"]
        resolution_source = override["resolution_source"]
        resolved_context = ProposalResolvedContext.model_validate(override["resolved_context"])
        used_legacy_contract = override["used_legacy_contract"]
        policy_context = override["advisory_policy_context"]
    except (KeyError, TypeError, ValidationError) as exc:
        raise ProposalContextResolutionError(
            "PROPOSAL_CONTEXT_RESOLUTION_OVERRIDE_INVALID"
        ) from exc
    input_mode = _require_override_input_mode(input_mode_value)
    resolution_source = _require_override_resolution_source(resolution_source)
    used_legacy_contract = _require_override_legacy_contract(used_legacy_contract)
    _require_override_policy_context(policy_context)
    return replace(
        resolved,
        input_mode=input_mode,
        resolution_source=resolution_source,
        resolved_context=resolved_context,
        used_legacy_contract=used_legacy_contract,
    )


def _require_override_input_mode(value: object) -> ProposalInputMode:
    if not isinstance(value, str):
        raise ProposalContextResolutionError("PROPOSAL_CONTEXT_RESOLUTION_OVERRIDE_INVALID")
    if value not in {"stateless", "stateful"}:
        raise ProposalContextResolutionError("PROPOSAL_CONTEXT_RESOLUTION_OVERRIDE_INVALID")
    return cast(ProposalInputMode, value)


def _require_override_resolution_source(value: object) -> str:
    if not isinstance(value, str):
        raise ProposalContextResolutionError("PROPOSAL_CONTEXT_RESOLUTION_OVERRIDE_INVALID")
    if not value:
        raise ProposalContextResolutionError("PROPOSAL_CONTEXT_RESOLUTION_OVERRIDE_INVALID")
    return value


def _require_override_legacy_contract(value: object) -> bool:
    if not isinstance(value, bool):
        raise ProposalContextResolutionError("PROPOSAL_CONTEXT_RESOLUTION_OVERRIDE_INVALID")
    return value


def _require_override_policy_context(value: object) -> None:
    if not isinstance(value, dict):
        raise ProposalContextResolutionError("PROPOSAL_CONTEXT_RESOLUTION_OVERRIDE_INVALID")


def resolve_create_request(payload: ProposalCreateRequest) -> ResolvedProposalContext:
    if payload.input_mode == "stateful":
        stateful_input = _require_stateful_input(payload.stateful_input)
        simulate_request, resolved_context = _resolve_stateful_input(stateful_input)
        metadata = _metadata_with_stateful_defaults(payload.metadata, stateful_input)
        return ResolvedProposalContext(
            input_mode="stateful",
            resolution_source="LOTUS_CORE",
            simulate_request=simulate_request,
            resolved_context=resolved_context,
            metadata=metadata,
            policy_selectors=_policy_selectors(
                metadata=metadata,
                stateful_input=stateful_input,
            ),
            used_legacy_contract=False,
        )

    if payload.input_mode == "stateless":
        simulate_request = _require_stateless_simulate_request(payload)
        return ResolvedProposalContext(
            input_mode="stateless",
            resolution_source="DIRECT_REQUEST",
            simulate_request=simulate_request,
            resolved_context=_build_resolved_context_from_simulate_request(simulate_request),
            metadata=payload.metadata.model_copy(deep=True),
            policy_selectors=_policy_selectors(metadata=payload.metadata),
            used_legacy_contract=False,
        )

    simulate_request = _require_legacy_simulate_request(payload.simulate_request)
    return ResolvedProposalContext(
        input_mode="stateless",
        resolution_source="DIRECT_REQUEST",
        simulate_request=simulate_request,
        resolved_context=_build_resolved_context_from_simulate_request(simulate_request),
        metadata=payload.metadata.model_copy(deep=True),
        policy_selectors=_policy_selectors(metadata=payload.metadata),
        used_legacy_contract=True,
    )


def resolve_simulation_request(payload: ProposalSimulationRequest) -> ResolvedSimulationContext:
    if payload.input_mode == "stateful":
        stateful_input = _require_stateful_input(payload.stateful_input)
        simulate_request, resolved_context = _resolve_stateful_input(stateful_input)
        simulate_request = _merge_alternatives_request(
            simulate_request,
            alternatives_request=payload.alternatives_request,
        )
        return ResolvedSimulationContext(
            input_mode="stateful",
            resolution_source="LOTUS_CORE",
            simulate_request=simulate_request,
            resolved_context=resolved_context,
            policy_selectors=_policy_selectors(stateful_input=stateful_input),
            used_legacy_contract=False,
        )

    if payload.input_mode == "stateless":
        simulate_request = _require_stateless_simulate_request(payload)
        return ResolvedSimulationContext(
            input_mode="stateless",
            resolution_source="DIRECT_REQUEST",
            simulate_request=simulate_request,
            resolved_context=_build_resolved_context_from_simulate_request(simulate_request),
            policy_selectors=_policy_selectors(),
            used_legacy_contract=False,
        )

    simulate_request = _require_legacy_simulate_request(payload.simulate_request)
    return ResolvedSimulationContext(
        input_mode="stateless",
        resolution_source="DIRECT_REQUEST",
        simulate_request=simulate_request,
        resolved_context=_build_resolved_context_from_simulate_request(simulate_request),
        policy_selectors=_policy_selectors(),
        used_legacy_contract=True,
    )


def resolve_version_request(payload: ProposalVersionRequest) -> ResolvedProposalContext:
    metadata = ProposalCreateMetadata()
    if payload.input_mode == "stateful":
        stateful_input = _require_stateful_input(payload.stateful_input)
        simulate_request, resolved_context = _resolve_stateful_input(stateful_input)
        resolved_metadata = _metadata_with_stateful_defaults(metadata, stateful_input)
        return ResolvedProposalContext(
            input_mode="stateful",
            resolution_source="LOTUS_CORE",
            simulate_request=simulate_request,
            resolved_context=resolved_context,
            metadata=resolved_metadata,
            policy_selectors=_policy_selectors(
                metadata=resolved_metadata,
                stateful_input=stateful_input,
            ),
            used_legacy_contract=False,
        )

    if payload.input_mode == "stateless":
        simulate_request = _require_stateless_simulate_request(payload)
        return ResolvedProposalContext(
            input_mode="stateless",
            resolution_source="DIRECT_REQUEST",
            simulate_request=simulate_request,
            resolved_context=_build_resolved_context_from_simulate_request(simulate_request),
            metadata=metadata,
            policy_selectors=_policy_selectors(metadata=metadata),
            used_legacy_contract=False,
        )

    simulate_request = _require_legacy_simulate_request(payload.simulate_request)
    return ResolvedProposalContext(
        input_mode="stateless",
        resolution_source="DIRECT_REQUEST",
        simulate_request=simulate_request,
        resolved_context=_build_resolved_context_from_simulate_request(simulate_request),
        metadata=metadata,
        policy_selectors=_policy_selectors(metadata=metadata),
        used_legacy_contract=True,
    )


def _require_stateful_input(
    stateful_input: ProposalStatefulInput | None,
) -> ProposalStatefulInput:
    if stateful_input is None:
        raise ProposalContextResolutionError("PROPOSAL_STATEFUL_INPUT_REQUIRED")
    return stateful_input


def _require_stateless_simulate_request(
    payload: ProposalCreateRequest | ProposalSimulationRequest | ProposalVersionRequest,
) -> ProposalSimulateRequest:
    if payload.stateless_input is None:
        raise ProposalContextResolutionError("PROPOSAL_STATELESS_INPUT_REQUIRED")
    return cast(
        ProposalSimulateRequest,
        payload.stateless_input.simulate_request.model_copy(deep=True),
    )


def _require_legacy_simulate_request(
    simulate_request: ProposalSimulateRequest | None,
) -> ProposalSimulateRequest:
    if simulate_request is None:
        raise ProposalContextResolutionError("PROPOSAL_SIMULATE_REQUEST_REQUIRED")
    return cast(ProposalSimulateRequest, simulate_request.model_copy(deep=True))


def _build_resolved_context_from_simulate_request(
    simulate_request: ProposalSimulateRequest,
) -> ProposalResolvedContext:
    return ProposalResolvedContext(
        portfolio_id=simulate_request.portfolio_snapshot.portfolio_id,
        as_of=(
            simulate_request.reference_model.as_of
            if simulate_request.reference_model is not None
            else None
        ),
        requested_as_of=(
            simulate_request.reference_model.as_of
            if simulate_request.reference_model is not None
            else None
        ),
        requested_reporting_currency=None,
        portfolio_snapshot_id=simulate_request.portfolio_snapshot.snapshot_id,
        market_data_snapshot_id=simulate_request.market_data_snapshot.snapshot_id,
    )


def _metadata_with_stateful_defaults(
    metadata: ProposalCreateMetadata,
    stateful_input: ProposalStatefulInput | None,
) -> ProposalCreateMetadata:
    if stateful_input is None or metadata.mandate_id is not None:
        return cast(ProposalCreateMetadata, metadata.model_copy(deep=True))
    return cast(
        ProposalCreateMetadata,
        metadata.model_copy(update={"mandate_id": stateful_input.mandate_id}),
    )


def _merge_alternatives_request(
    simulate_request: ProposalSimulateRequest,
    *,
    alternatives_request: object | None,
) -> ProposalSimulateRequest:
    if alternatives_request is None:
        return simulate_request
    return cast(
        ProposalSimulateRequest,
        simulate_request.model_copy(
            update={"alternatives_request": alternatives_request},
            deep=True,
        ),
    )


def _merge_stateful_narrative_request(
    simulate_request: ProposalSimulateRequest,
    *,
    stateful_input: ProposalStatefulInput,
) -> ProposalSimulateRequest:
    if stateful_input.narrative_request is None:
        return simulate_request
    return cast(
        ProposalSimulateRequest,
        simulate_request.model_copy(
            update={"narrative_request": stateful_input.narrative_request},
            deep=True,
        ),
    )


def _resolve_stateful_input(
    stateful_input: ProposalStatefulInput,
) -> tuple[ProposalSimulateRequest, ProposalResolvedContext]:
    try:
        resolved = resolve_proposal_stateful_context(stateful_input)
    except ProposalStatefulContextResolutionUnavailableError as exc:
        raise ProposalContextResolutionError(
            "PROPOSAL_STATEFUL_CONTEXT_RESOLUTION_UNAVAILABLE"
        ) from exc

    resolved_context = ProposalResolvedContext.model_validate(
        resolved.resolved_context.model_dump(mode="json")
    ).model_copy(
        update={
            "requested_as_of": stateful_input.as_of,
            "requested_reporting_currency": stateful_input.reporting_currency,
        }
    )
    return (
        _merge_stateful_narrative_request(
            resolved.simulate_request,
            stateful_input=stateful_input,
        ),
        resolved_context,
    )


def _policy_selectors(
    *,
    metadata: ProposalCreateMetadata | None = None,
    stateful_input: ProposalStatefulInput | None = None,
) -> ProposalPolicySelectors:
    return ProposalPolicySelectors(
        household_id=_stateful_household_id(stateful_input),
        mandate_id=_resolved_policy_mandate_id(
            metadata=metadata,
            stateful_input=stateful_input,
        ),
        jurisdiction=_metadata_jurisdiction(metadata),
        benchmark_id=_stateful_benchmark_id(stateful_input),
    )


def _stateful_household_id(stateful_input: ProposalStatefulInput | None) -> str | None:
    return stateful_input.household_id if stateful_input is not None else None


def _resolved_policy_mandate_id(
    *,
    metadata: ProposalCreateMetadata | None,
    stateful_input: ProposalStatefulInput | None,
) -> str | None:
    metadata_mandate_id = _metadata_mandate_id(metadata)
    if metadata_mandate_id is not None:
        return metadata_mandate_id
    return _stateful_mandate_id(stateful_input)


def _metadata_mandate_id(metadata: ProposalCreateMetadata | None) -> str | None:
    return metadata.mandate_id if metadata is not None else None


def _stateful_mandate_id(stateful_input: ProposalStatefulInput | None) -> str | None:
    return stateful_input.mandate_id if stateful_input is not None else None


def _metadata_jurisdiction(metadata: ProposalCreateMetadata | None) -> str | None:
    return metadata.jurisdiction if metadata is not None else None


def _stateful_benchmark_id(stateful_input: ProposalStatefulInput | None) -> str | None:
    return stateful_input.benchmark_id if stateful_input is not None else None


__all__ = [
    "ProposalContextResolutionError",
    "ResolvedProposalContext",
    "ResolvedSimulationContext",
    "apply_context_resolution_override",
    "resolve_create_request",
    "resolve_simulation_request",
    "resolve_version_request",
]
