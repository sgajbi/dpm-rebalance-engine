from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

ReplayEvidenceScope = Literal["WORKSPACE_SAVED_VERSION", "PROPOSAL_VERSION", "ASYNC_OPERATION"]


class AdvisoryReplaySubject(BaseModel):
    scope: ReplayEvidenceScope = Field(
        description="Replay-evidence scope being described.",
        examples=["PROPOSAL_VERSION"],
    )
    workspace_id: Optional[str] = Field(
        default=None,
        description="Workspace identifier when the replay subject originates from workspace flows.",
        examples=["aws_001"],
    )
    workspace_version_id: Optional[str] = Field(
        default=None,
        description="Saved workspace version identifier when applicable.",
        examples=["awv_001"],
    )
    proposal_id: Optional[str] = Field(
        default=None,
        description="Proposal identifier when the replay subject originates from lifecycle flows.",
        examples=["pp_001"],
    )
    proposal_version_id: Optional[str] = Field(
        default=None,
        description="Proposal version identifier when applicable.",
        examples=["ppv_001"],
    )
    proposal_version_no: Optional[int] = Field(
        default=None,
        description="Proposal version number when applicable.",
        examples=[1],
    )
    operation_id: Optional[str] = Field(
        default=None,
        description="Async operation identifier when the replay subject is an async operation.",
        examples=["pop_001"],
    )


class AdvisoryReplayResolvedContext(BaseModel):
    portfolio_id: str = Field(
        description="Resolved portfolio identifier used by the replayable advisory evaluation.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    as_of: Optional[str] = Field(
        default=None,
        description=(
            "Optional resolved lifecycle date or timestamp preserved by replay evidence. It is "
            "null when the direct/stateless source context has no explicit date; valuation "
            "consumers must use nested valuation-context effective dates."
        ),
        examples=["2026-03-25"],
    )
    portfolio_snapshot_id: Optional[str] = Field(
        default=None,
        description="Resolved upstream portfolio snapshot identifier, when known.",
        examples=["ps_20260325_001"],
    )
    market_data_snapshot_id: Optional[str] = Field(
        default=None,
        description="Resolved upstream market-data snapshot identifier, when known.",
        examples=["md_20260325_001"],
    )
    risk_context_id: Optional[str] = Field(
        default=None,
        description="Resolved upstream risk-context identifier, when known.",
        examples=["risk_ctx_001"],
    )
    reporting_context_id: Optional[str] = Field(
        default=None,
        description="Resolved upstream reporting-context identifier, when known.",
        examples=["report_ctx_001"],
    )


class AdvisoryReplayHashes(BaseModel):
    request_hash: Optional[str] = Field(
        default=None,
        description="Canonical lifecycle request hash when persisted proposal evidence exists.",
        examples=["sha256:req"],
    )
    evaluation_request_hash: Optional[str] = Field(
        default=None,
        description="Canonical evaluation-request hash captured during workspace replay evidence.",
        examples=["sha256:eval"],
    )
    draft_state_hash: Optional[str] = Field(
        default=None,
        description="Canonical workspace draft-state hash when workspace replay evidence exists.",
        examples=["sha256:draft"],
    )
    simulation_hash: Optional[str] = Field(
        default=None,
        description="Canonical simulation-output hash when persisted proposal evidence exists.",
        examples=["sha256:sim"],
    )
    artifact_hash: Optional[str] = Field(
        default=None,
        description="Canonical artifact hash when persisted proposal evidence exists.",
        examples=["sha256:artifact"],
    )


class AdvisoryReplayContinuity(BaseModel):
    lifecycle_origin: Optional[str] = Field(
        default=None,
        description="Lifecycle origin classification for proposal-backed replay evidence.",
        examples=["WORKSPACE_HANDOFF"],
    )
    source_workspace_id: Optional[str] = Field(
        default=None,
        description="Workspace identifier recorded as the lifecycle source when applicable.",
        examples=["aws_001"],
    )
    workspace_version_id: Optional[str] = Field(
        default=None,
        description="Saved workspace version identifier linked into replay continuity when known.",
        examples=["awv_001"],
    )
    handoff_action: Optional[str] = Field(
        default=None,
        description="Workspace-to-lifecycle handoff action represented by this replay continuity.",
        examples=["CREATED_PROPOSAL"],
    )
    handoff_at: Optional[str] = Field(
        default=None,
        description="UTC ISO8601 timestamp of the continuity-preserving handoff, when known.",
        examples=["2026-03-25T10:00:00+00:00"],
    )
    handoff_by: Optional[str] = Field(
        default=None,
        description="Actor identifier that performed the continuity-preserving handoff.",
        examples=["advisor_123"],
    )
    async_operation_id: Optional[str] = Field(
        default=None,
        description="Async operation identifier linked to the replay evidence when applicable.",
        examples=["pop_001"],
    )
    async_operation_type: Optional[str] = Field(
        default=None,
        description="Async operation type linked to the replay evidence when applicable.",
        examples=["CREATE_PROPOSAL"],
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Correlation id linked to the replay evidence when applicable.",
        examples=["corr_001"],
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Idempotency key linked to the replay evidence when applicable.",
        examples=["proposal-create-idem-001"],
    )


class AdvisoryReplayEvidenceResponse(BaseModel):
    subject: AdvisoryReplaySubject = Field(
        description="Normalized subject identifier block for the replay evidence payload."
    )
    resolved_context: Optional[AdvisoryReplayResolvedContext] = Field(
        default=None,
        description="Normalized resolved advisory context captured by the replayable evidence.",
    )
    hashes: AdvisoryReplayHashes = Field(
        description="Canonical hashes captured across workspace and lifecycle replay surfaces."
    )
    continuity: AdvisoryReplayContinuity = Field(
        description="Normalized lineage and continuity metadata across replay surfaces."
    )
    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Supporting evidence references and metadata preserved for audit and replay.",
    )
    explanation: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured explanation of how the normalized replay evidence was assembled.",
    )
