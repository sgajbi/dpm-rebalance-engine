from __future__ import annotations

from typing import Any, cast

from src.core.common.canonical import hash_canonical_payload
from src.core.proposals.context_resolution import (
    ResolvedProposalContext,
    ResolvedSimulationContext,
)
from src.core.proposals.models import ProposalCreateRequest, ProposalVersionRequest


def canonicalize_create_command_payload(
    *,
    payload: ProposalCreateRequest,
) -> dict[str, Any]:
    return cast(dict[str, Any], payload.model_dump(mode="json"))


def build_create_command_idempotency_hash(
    *,
    payload: ProposalCreateRequest,
) -> str:
    return cast(str, hash_canonical_payload(canonicalize_create_command_payload(payload=payload)))


def canonicalize_create_request_payload(
    *,
    payload: ProposalCreateRequest,
    resolved: ResolvedProposalContext,
) -> dict[str, Any]:
    return {
        "created_by": payload.created_by,
        "metadata": resolved.metadata.model_dump(mode="json"),
        "advisory_context": {
            "input_mode": resolved.input_mode,
            "resolution_source": resolved.resolution_source,
            "resolved_context": resolved.resolved_context.model_dump(mode="json"),
            "simulate_request": resolved.simulate_request.model_dump(mode="json"),
        },
    }


def build_create_request_hash(
    *,
    payload: ProposalCreateRequest,
    resolved: ResolvedProposalContext,
) -> str:
    return cast(
        str,
        hash_canonical_payload(
            canonicalize_create_request_payload(payload=payload, resolved=resolved)
        ),
    )


def canonicalize_simulation_request_payload(
    *,
    resolved: ResolvedSimulationContext,
) -> dict[str, Any]:
    return {
        "advisory_context": {
            "input_mode": resolved.input_mode,
            "resolution_source": resolved.resolution_source,
            "resolved_context": resolved.resolved_context.model_dump(mode="json"),
            "simulate_request": resolved.simulate_request.model_dump(mode="json"),
        }
    }


def build_simulation_request_hash(*, resolved: ResolvedSimulationContext) -> str:
    return cast(
        str,
        hash_canonical_payload(canonicalize_simulation_request_payload(resolved=resolved)),
    )


def canonicalize_version_request_payload(
    *,
    payload: ProposalVersionRequest,
    resolved: ResolvedProposalContext,
) -> dict[str, Any]:
    return {
        "created_by": payload.created_by,
        "expected_current_version_no": payload.expected_current_version_no,
        "advisory_context": {
            "input_mode": resolved.input_mode,
            "resolution_source": resolved.resolution_source,
            "resolved_context": resolved.resolved_context.model_dump(mode="json"),
            "simulate_request": resolved.simulate_request.model_dump(mode="json"),
        },
    }


def build_version_request_hash(
    *,
    payload: ProposalVersionRequest,
    resolved: ResolvedProposalContext,
) -> str:
    return cast(
        str,
        hash_canonical_payload(
            canonicalize_version_request_payload(payload=payload, resolved=resolved)
        ),
    )


__all__ = [
    "build_create_command_idempotency_hash",
    "build_create_request_hash",
    "canonicalize_create_command_payload",
    "build_simulation_request_hash",
    "build_version_request_hash",
    "canonicalize_create_request_payload",
    "canonicalize_simulation_request_payload",
    "canonicalize_version_request_payload",
]
