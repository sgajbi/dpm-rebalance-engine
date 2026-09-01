from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, field_validator

from src.core.common.idempotency import normalize_required_idempotency_key
from src.core.proposals.exceptions import ProposalValidationError
from src.core.proposals.idea_intake_authority import (
    IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY,
    IdeaProposalIntakePrincipal,
)
from src.core.proposals.idea_intake_persistence import (
    IDEA_PROPOSAL_INTAKE_REPLAY_RETENTION,
    IdeaProposalIntakeRecord,
)
from src.core.proposals.repository import ProposalRepository

IdeaProposalIntakeStatus = Literal["ACCEPTED", "ACCEPTED_REPLAYED", "REJECTED"]
IdeaProposalIntakeSupportabilityStatus = Literal["not_certified"]
IdeaProposalIntentType = Literal[
    "REVIEW_FOR_ADVISORY_PROPOSAL",
    "CREATE_ADVISORY_PROPOSAL_DRAFT",
]

IDEA_PROPOSAL_INTAKE_CERTIFICATION_BLOCKERS = [
    "suitability_policy_authority_remains_lotus_advise",
    "advisory_proposal_creation_not_certified",
    "advisory_review_work_realization_not_certified",
    "source_owned_outcome_stream_not_certified",
    "client_publication_authority_blocked",
]

IDEA_PROPOSAL_INTAKE_REQUEST_EXAMPLE: dict[str, Any] = {
    "source_system": "lotus-idea",
    "source_product": "lotus-idea:IdeaCandidate:v1",
    "idea_candidate_id": "idea_candidate_001",
    "conversion_intent_id": "conversion_intent_001",
    "intent_type": "REVIEW_FOR_ADVISORY_PROPOSAL",
    "source_refs": [
        {
            "source_system": "lotus-idea",
            "source_type": "IdeaCandidate",
            "source_id": "idea_candidate_001",
            "content_hash": "sha256:abc123",
        }
    ],
}

IDEA_PROPOSAL_INTAKE_RESPONSE_EXAMPLE: dict[str, Any] = {
    "intake_id": "ipi_7a1d2b3c4d5e",
    "intake_status": "ACCEPTED",
    "supportability_status": "not_certified",
    "source_authority": "lotus-idea",
    "proposal_authority": "lotus-advise",
    "target_product": "lotus-advise:AdvisoryProposalLifecycleRecord:v1",
    "route_existence_proven": True,
    "intake_receipt_accepted": True,
    "idempotency_replay": False,
    "idempotency_key_hash": "sha256:71d5d5d1fbf0",
    "request_fingerprint": "sha256:a4e9afedc3cb",
    "trusted_scope": {
        "subject": "svc-lotus-idea",
        "role": "SERVICE",
        "tenant_id": "tenant-private-bank-sg",
        "legal_entity_code": "SGPB",
        "correlation_id": "corr-idea-proposal-001",
        "service_identity": "lotus-idea",
        "capability": IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY,
    },
    "outcome_reason_codes": ["idea_intake_receipt_accepted"],
    "proposal_record_created": False,
    "suitability_authority_granted": False,
    "order_created": False,
    "client_publication_authorized": False,
    "certification_blockers": IDEA_PROPOSAL_INTAKE_CERTIFICATION_BLOCKERS,
    "evidence_refs": [
        "contracts/idea-proposal-intake/lotus-advise-idea-proposal-intake.v1.json",
        "src/api/proposals/routes_idea_intake.py",
        "src/core/proposals/idea_proposal_intake.py",
        "src/infrastructure/postgres_migrations/proposals/0011_idea_proposal_intakes.sql",
    ],
    "received_at": "2026-06-21T10:10:00+00:00",
    "correlation_id": "corr-idea-proposal-001",
}

IDEA_PROPOSAL_INTAKE_ERROR_EXAMPLE: dict[str, Any] = {
    "detail": "UNSUPPORTED_QUERY_PARAMETER: dry_run not supported for this endpoint"
}


class IdeaProposalSourceRef(BaseModel):
    source_system: Literal["lotus-idea"] = Field(
        description="Source system that owns the referenced opportunity evidence.",
        examples=["lotus-idea"],
    )
    source_type: str = Field(
        min_length=1,
        max_length=96,
        description="Source-owned evidence type or product name.",
        examples=["IdeaCandidate"],
    )
    source_id: str = Field(
        min_length=1,
        max_length=160,
        description=(
            "Source-owned identifier. Advise does not infer portfolio, account, client, or "
            "product facts from this value."
        ),
        examples=["idea_candidate_001"],
    )
    content_hash: str | None = Field(
        default=None,
        max_length=160,
        description="Optional source-owned content hash for replay and lineage checks.",
        examples=["sha256:abc123"],
    )

    @field_validator("source_type", "source_id", "content_hash")
    @classmethod
    def _trim_source_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("IDEA_PROPOSAL_SOURCE_REF_REQUIRED")
        return trimmed


class IdeaProposalIntakeRequest(BaseModel):
    model_config = {"json_schema_extra": {"example": IDEA_PROPOSAL_INTAKE_REQUEST_EXAMPLE}}

    source_system: Literal["lotus-idea"] = Field(
        description="Producer system submitting the reviewed opportunity handoff.",
        examples=["lotus-idea"],
    )
    source_product: Literal["lotus-idea:IdeaCandidate:v1"] = Field(
        description="Source data product represented by the handoff.",
        examples=["lotus-idea:IdeaCandidate:v1"],
    )
    idea_candidate_id: str = Field(
        min_length=1,
        max_length=160,
        description=(
            "lotus-idea candidate identifier. Advise uses it only for source-safe lineage and "
            "does not infer advisory suitability from it."
        ),
        examples=["idea_candidate_001"],
    )
    conversion_intent_id: str = Field(
        min_length=1,
        max_length=160,
        description="lotus-idea conversion-intent identifier used for deterministic intake proof.",
        examples=["conversion_intent_001"],
    )
    intent_type: IdeaProposalIntentType = Field(
        description=(
            "Requested advisory-side intake posture. This route acknowledges only the handoff "
            "foundation and does not create proposal lifecycle state or suitability evidence."
        ),
        examples=["REVIEW_FOR_ADVISORY_PROPOSAL"],
    )
    source_refs: list[IdeaProposalSourceRef] = Field(
        min_length=1,
        max_length=16,
        description="Source-safe idea evidence references supplied by lotus-idea.",
    )

    @field_validator("idea_candidate_id", "conversion_intent_id")
    @classmethod
    def _trim_required_identifier(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("IDEA_PROPOSAL_IDENTIFIER_REQUIRED")
        return trimmed


class IdeaProposalIntakeResponse(BaseModel):
    model_config = {"json_schema_extra": {"example": IDEA_PROPOSAL_INTAKE_RESPONSE_EXAMPLE}}

    intake_id: str = Field(
        description=(
            "Deterministic source-safe intake identifier derived from handoff identifiers, "
            "intent, and source evidence fingerprint."
        ),
        examples=["ipi_7a1d2b3c4d5e"],
    )
    intake_status: IdeaProposalIntakeStatus = Field(
        description="Bounded intake receipt status; not an advisory proposal status.",
        examples=["ACCEPTED"],
    )
    supportability_status: IdeaProposalIntakeSupportabilityStatus = Field(
        description="Certification posture for this route foundation.",
        examples=["not_certified"],
    )
    source_authority: Literal["lotus-idea"] = Field(
        description="Source authority for idea candidate and conversion-intent evidence.",
        examples=["lotus-idea"],
    )
    proposal_authority: Literal["lotus-advise"] = Field(
        description="Advisory proposal and suitability authority retained by lotus-advise.",
        examples=["lotus-advise"],
    )
    target_product: Literal["lotus-advise:AdvisoryProposalLifecycleRecord:v1"] = Field(
        description="Advise-owned product that future certified realization may update.",
        examples=["lotus-advise:AdvisoryProposalLifecycleRecord:v1"],
    )
    route_existence_proven: bool = Field(
        description="True because this route exists and is covered by contract tests.",
        examples=[True],
    )
    intake_receipt_accepted: bool = Field(
        description=(
            "True only when Advise accepted the handoff into its bounded intake receipt layer. "
            "This is not proposal lifecycle persistence."
        ),
        examples=[True],
    )
    idempotency_replay: bool = Field(
        description="True when the response is a safe replay for the same idempotency key/request.",
        examples=[False],
    )
    idempotency_key_hash: str = Field(
        description="Hashed idempotency key reference; raw idempotency keys are not echoed.",
        examples=["sha256:71d5d5d1fbf0"],
    )
    request_fingerprint: str = Field(
        description="Source-safe request fingerprint used for idempotency conflict detection.",
        examples=["sha256:a4e9afedc3cb"],
    )
    trusted_scope: dict[str, Any] = Field(
        description=(
            "Bounded trusted principal scope derived from local/dev headers. Production IdP "
            "integration remains external to this route until available."
        ),
    )
    outcome_reason_codes: list[str] = Field(
        description="Machine-readable outcome reasons for accepted, replayed, or rejected intake.",
        examples=[["idea_intake_receipt_accepted"]],
    )
    proposal_record_created: bool = Field(
        description="False until a later certified advisory proposal realization persists one.",
        examples=[False],
    )
    suitability_authority_granted: bool = Field(
        description="False; this route does not run suitability or approve advisory use.",
        examples=[False],
    )
    order_created: bool = Field(
        description="False; no order, OMS instruction, fill, or settlement evidence is created.",
        examples=[False],
    )
    client_publication_authorized: bool = Field(
        description="False; this route does not authorize client communication or publication.",
        examples=[False],
    )
    certification_blockers: list[str] = Field(
        description="Remaining blockers before this route can support certified realization.",
        examples=[IDEA_PROPOSAL_INTAKE_CERTIFICATION_BLOCKERS],
    )
    evidence_refs: list[str] = Field(
        description="Implementation and contract evidence references for the route foundation.",
    )
    received_at: str = Field(
        description="UTC timestamp when the handoff envelope was acknowledged.",
        examples=["2026-06-21T10:10:00+00:00"],
    )
    correlation_id: str = Field(
        description="Caller or generated correlation id for source-safe operational tracing.",
        examples=["corr-idea-proposal-001"],
    )


def acknowledge_idea_proposal_intake(
    request: IdeaProposalIntakeRequest,
    *,
    correlation_id: str,
    idempotency_key: str = "domain-determinism-only",
    principal: IdeaProposalIntakePrincipal | None = None,
    received_at: datetime | None = None,
) -> IdeaProposalIntakeResponse:
    timestamp = received_at or datetime.now(timezone.utc)
    source_refs_fingerprint = _source_refs_fingerprint(request.source_refs)
    request_fingerprint = _request_fingerprint(
        request,
        source_refs_fingerprint=source_refs_fingerprint,
    )
    intake_id = _intake_id(
        idea_candidate_id=request.idea_candidate_id,
        conversion_intent_id=request.conversion_intent_id,
        intent_type=request.intent_type,
        source_refs_fingerprint=source_refs_fingerprint,
    )
    accepted = request.intent_type == "REVIEW_FOR_ADVISORY_PROPOSAL"
    return IdeaProposalIntakeResponse(
        intake_id=intake_id,
        intake_status="ACCEPTED" if accepted else "REJECTED",
        supportability_status="not_certified",
        source_authority="lotus-idea",
        proposal_authority="lotus-advise",
        target_product="lotus-advise:AdvisoryProposalLifecycleRecord:v1",
        route_existence_proven=True,
        intake_receipt_accepted=accepted,
        idempotency_replay=False,
        idempotency_key_hash=_safe_key_hash(idempotency_key),
        request_fingerprint=request_fingerprint,
        trusted_scope=_trusted_scope(principal=principal, correlation_id=correlation_id),
        outcome_reason_codes=_outcome_reason_codes(request),
        proposal_record_created=False,
        suitability_authority_granted=False,
        order_created=False,
        client_publication_authorized=False,
        certification_blockers=list(IDEA_PROPOSAL_INTAKE_CERTIFICATION_BLOCKERS),
        evidence_refs=[
            "contracts/idea-proposal-intake/lotus-advise-idea-proposal-intake.v1.json",
            "src/api/proposals/routes_idea_intake.py",
            "src/core/proposals/idea_proposal_intake.py",
            "src/infrastructure/postgres_migrations/proposals/0011_idea_proposal_intakes.sql",
        ],
        received_at=timestamp.isoformat(),
        correlation_id=correlation_id,
    )


def process_idea_proposal_intake(
    request: IdeaProposalIntakeRequest,
    *,
    correlation_id: str,
    idempotency_key: str,
    principal: IdeaProposalIntakePrincipal,
    repository: ProposalRepository,
    received_at: datetime | None = None,
) -> IdeaProposalIntakeResponse:
    try:
        normalized_idempotency_key = normalize_required_idempotency_key(idempotency_key)
    except ValueError as exc:
        raise ProposalValidationError(str(exc)) from exc

    response = acknowledge_idea_proposal_intake(
        request,
        correlation_id=correlation_id,
        idempotency_key=normalized_idempotency_key,
        principal=principal,
        received_at=received_at,
    )
    created_at_utc = _parse_received_at(response.received_at)
    claim = repository.claim_idea_proposal_intake(
        IdeaProposalIntakeRecord(
            registry_key=_registry_key(
                idempotency_key=normalized_idempotency_key,
                trusted_scope=response.trusted_scope,
            ),
            request_fingerprint=response.request_fingerprint,
            response_json=response.model_dump_json(),
            created_at_utc=created_at_utc,
            expires_at_utc=created_at_utc + IDEA_PROPOSAL_INTAKE_REPLAY_RETENTION,
        )
    )
    if not claim.replayed:
        return response
    stored = IdeaProposalIntakeResponse.model_validate_json(claim.record.response_json)
    return cast(
        IdeaProposalIntakeResponse,
        stored.model_copy(
            update={
                "intake_status": (
                    "ACCEPTED_REPLAYED" if stored.intake_receipt_accepted else "REJECTED"
                ),
                "idempotency_replay": True,
                "correlation_id": response.correlation_id,
                "trusted_scope": response.trusted_scope,
                "received_at": response.received_at,
                "outcome_reason_codes": _replay_reason_codes(stored),
            }
        ),
    )


def _source_refs_fingerprint(source_refs: list[IdeaProposalSourceRef]) -> str:
    canonical_refs = sorted(
        (source_ref.model_dump(mode="json", exclude_none=False) for source_ref in source_refs),
        key=lambda item: (
            item["source_system"],
            item["source_type"],
            item["source_id"],
            item.get("content_hash") or "",
        ),
    )
    canonical_payload = json.dumps(canonical_refs, sort_keys=True, separators=(",", ":"))
    return sha256(canonical_payload.encode()).hexdigest()


def _request_fingerprint(
    request: IdeaProposalIntakeRequest,
    *,
    source_refs_fingerprint: str,
) -> str:
    canonical_payload = json.dumps(
        {
            "source_system": request.source_system,
            "source_product": request.source_product,
            "idea_candidate_id": request.idea_candidate_id,
            "conversion_intent_id": request.conversion_intent_id,
            "intent_type": request.intent_type,
            "source_refs_fingerprint": source_refs_fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{sha256(canonical_payload.encode()).hexdigest()[:12]}"


def _safe_key_hash(idempotency_key: str) -> str:
    normalized = idempotency_key.strip()
    return f"sha256:{sha256(normalized.encode()).hexdigest()[:12]}"


def _full_key_digest(idempotency_key: str) -> str:
    normalized = idempotency_key.strip()
    return f"sha256:{sha256(normalized.encode()).hexdigest()}"


def _registry_key(*, idempotency_key: str, trusted_scope: dict[str, Any]) -> str:
    scope_payload = json.dumps(
        {
            "tenant_id": trusted_scope.get("tenant_id"),
            "legal_entity_code": trusted_scope.get("legal_entity_code"),
            "service_identity": trusted_scope.get("service_identity"),
            "subject": trusted_scope.get("subject"),
            "capability": trusted_scope.get("capability"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    scope_digest = sha256(scope_payload.encode()).hexdigest()
    return f"{scope_digest}:{_full_key_digest(idempotency_key)}"


def _parse_received_at(received_at: str) -> datetime:
    parsed = datetime.fromisoformat(received_at)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _trusted_scope(
    *,
    principal: IdeaProposalIntakePrincipal | None,
    correlation_id: str,
) -> dict[str, Any]:
    if principal is None:
        return {
            "subject": "domain-only",
            "role": "DOMAIN_TEST",
            "tenant_id": "domain-only",
            "legal_entity_code": "DOMAIN",
            "correlation_id": correlation_id,
            "service_identity": "domain-only",
            "capability": IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY,
        }
    metadata: dict[str, Any] = dict(
        principal.audit_metadata(capability=IDEA_PROPOSAL_INTAKE_ACCEPT_CAPABILITY)
    )
    metadata["correlation_id"] = correlation_id
    return metadata


def _outcome_reason_codes(request: IdeaProposalIntakeRequest) -> list[str]:
    if request.intent_type == "REVIEW_FOR_ADVISORY_PROPOSAL":
        return ["idea_intake_receipt_accepted"]
    return [
        "advisory_proposal_creation_not_certified",
        "idea_intake_receipt_rejected_no_proposal_created",
    ]


def _replay_reason_codes(response: IdeaProposalIntakeResponse) -> list[str]:
    if response.intake_receipt_accepted:
        return ["idea_intake_receipt_replayed"]
    return ["idea_intake_rejection_replayed"]


def _intake_id(
    *,
    idea_candidate_id: str,
    conversion_intent_id: str,
    intent_type: str,
    source_refs_fingerprint: str,
) -> str:
    digest = sha256(
        (
            f"{idea_candidate_id}|{conversion_intent_id}|{intent_type}|{source_refs_fingerprint}"
        ).encode()
    ).hexdigest()
    return f"ipi_{digest[:12]}"
