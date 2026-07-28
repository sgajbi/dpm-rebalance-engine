from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.policy_packs.evaluation_models import PolicyEvaluationStatus
from src.core.policy_packs.persistence_models import PolicyEvaluationAuditEvent
from src.core.policy_packs.receipt_identity import PolicyEvaluationReceiptScopeIdentity

PolicyEvaluationRequirementStatus = Literal["OPEN", "SATISFIED", "BLOCKED"]
PolicyEvaluationSignOffStatus = Literal[
    "READY_FOR_SIGN_OFF",
    "SIGNED_OFF",
    "PENDING_REVIEW",
    "BLOCKED",
]
PolicyEvaluationSignOffDecision = Literal[
    "APPROVE_FOR_POLICY_SIGN_OFF",
    "REQUEST_MORE_EVIDENCE",
    "REJECT_POLICY_SIGN_OFF",
]


class PolicyEvaluationRequirementProjection(BaseModel):
    requirement_id: str = Field(
        description="Policy approval, disclosure, consent, or conflict requirement identifier.",
        examples=["REVIEW_DISCLOSURE:SG_STRUCTURED_NOTE"],
    )
    requirement_type: str = Field(
        description="Requirement family such as approval, disclosure, consent, or conflict.",
        examples=["disclosure"],
    )
    status: PolicyEvaluationRequirementStatus = Field(
        description="Current requirement posture derived from policy evidence and review events.",
        examples=["OPEN"],
    )
    owner_role: str = Field(
        description="Expected owner role for reviewing or satisfying this requirement.",
        examples=["INVESTMENT_COUNSELLOR"],
    )
    review_sla: str | None = Field(
        default=None,
        description="Configured review service level where known.",
        examples=["P1D"],
    )
    due_at: str | None = Field(
        default=None,
        description="UTC ISO8601 due time derived from the evaluation timestamp and review SLA.",
        examples=["2026-05-27T01:00:00+00:00"],
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="Reason codes explaining the requirement posture.",
        examples=[["POLICY_REQUIREMENT_OPEN"]],
    )


class PolicyEvaluationWorkflowMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        description="Source data-product identifier for the policy evaluation receipt.",
        examples=["lotus-advise:AdvisoryPolicyEvaluationRecord:v1"],
    )
    product_version: str = Field(description="Source data-product version.", examples=["v1"])
    source_system: str = Field(
        description="Producer system that emitted the receipt.", examples=["LOTUS_ADVISE"]
    )
    evaluation_id: str = Field(
        description="Policy evaluation record identifier.", examples=["pev_123abc"]
    )
    proposal_id: str = Field(description="Proposal identifier.", examples=["pp_001"])
    proposal_version_id: str = Field(
        description="Immutable proposal version identifier.", examples=["ppv_001"]
    )
    portfolio_id: str = Field(
        description="Portfolio identifier from the evaluated evidence.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    policy_pack_id: str = Field(
        description="Policy pack identifier.", examples=["GLOBAL_PRIVATE_BANKING_BASELINE"]
    )
    policy_version: str = Field(description="Policy pack version.", examples=["2026.05"])
    as_of_date: str = Field(
        description="Source-owned business date evaluated by Advise.", examples=["2026-05-26"]
    )
    generated_at: str = Field(
        description="UTC time when Advise finalized the evaluation.",
        examples=["2026-05-26T01:00:00+00:00"],
    )
    content_hash: str = Field(
        description="Canonical hash of immutable policy evaluation truth.",
        examples=["sha256:policy-evaluation"],
    )
    evaluation_hash: str = Field(
        description="Canonical policy evaluation hash.", examples=["sha256:policy-evaluation"]
    )
    source_evidence_hash: str = Field(
        description="Canonical hash of evaluated source evidence.",
        examples=["sha256:source-evidence"],
    )
    policy_content_hash: str = Field(
        description="Canonical policy-pack content hash.", examples=["sha256:policy-content"]
    )
    freshness_state: str = Field(
        description="Source evidence freshness posture.", examples=["current"]
    )
    data_quality_status: str = Field(
        description="Source evidence quality posture.", examples=["complete"]
    )
    source_gap_count: int = Field(
        description="Count of missing source evidence gaps.", examples=[0]
    )
    source_gaps: list[str] = Field(
        description="Missing source evidence gap identifiers.", examples=[[]]
    )
    client_ready_publication: str = Field(
        description="Client-ready publication boundary.", examples=["BLOCKED"]
    )
    scope_identity: PolicyEvaluationReceiptScopeIdentity = Field(
        description="Source-safe trusted tenant/legal-entity/portfolio scope identity.",
        examples=[{"tenant_scope_hash": "sha256:tenant"}],
    )
    observed_correlation_id_hash: str = Field(
        description="Source-safe hash of correlation id observed by Advise.",
        examples=["sha256:correlation"],
    )
    observed_trace_id_hash: str = Field(
        description="Source-safe hash of trace id observed by Advise.",
        examples=["sha256:trace"],
    )


class PolicyEvaluationWorkflowReplayMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_contract_version: str = Field(
        description="Closed receipt identity contract version.",
        examples=["rfc0002.policy-evaluation-receipt-identity.v1"],
    )
    evaluation_id: str = Field(
        description="Policy evaluation record identifier.", examples=["pev_123abc"]
    )
    proposal_id: str = Field(description="Proposal identifier.", examples=["pp_001"])
    proposal_version_id: str = Field(
        description="Immutable proposal version identifier.", examples=["ppv_001"]
    )
    portfolio_id: str = Field(
        description="Portfolio identifier from the evaluated evidence.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    as_of_date: str = Field(
        description="Source-owned business date evaluated by Advise.", examples=["2026-05-26"]
    )
    policy_pack_id: str = Field(
        description="Policy pack identifier.", examples=["GLOBAL_PRIVATE_BANKING_BASELINE"]
    )
    policy_version: str = Field(description="Policy pack version.", examples=["2026.05"])
    source_refs: list[str] = Field(
        description="Persisted source refs used for replay proof.",
        examples=[["lotus-risk:RiskMetricsReport:v1"]],
    )
    source_gaps: list[str] = Field(
        description="Persisted source gaps used for replay proof.", examples=[[]]
    )
    source_evidence_hash: str = Field(
        description="Canonical hash of evaluated source evidence.",
        examples=["sha256:source-evidence"],
    )
    evaluation_hash: str = Field(
        description="Canonical policy evaluation hash.", examples=["sha256:policy-evaluation"]
    )
    policy_content_hash: str = Field(
        description="Canonical policy-pack content hash.", examples=["sha256:policy-content"]
    )
    replay_policy: str = Field(
        description="Replay policy applied to the finalized record.",
        examples=["PIN_POLICY_VERSION_AND_COMPARE_SOURCE_HASHES"],
    )
    scope_identity: PolicyEvaluationReceiptScopeIdentity = Field(
        description="Source-safe trusted tenant/legal-entity/portfolio scope identity.",
        examples=[{"tenant_scope_hash": "sha256:tenant"}],
    )
    observed_correlation_id_hash: str = Field(
        description="Source-safe hash of correlation id observed by Advise.",
        examples=["sha256:correlation"],
    )
    observed_trace_id_hash: str = Field(
        description="Source-safe hash of trace id observed by Advise.",
        examples=["sha256:trace"],
    )


class PolicyEvaluationWorkflowResponse(BaseModel):
    evaluation_id: str = Field(
        description="Policy evaluation record identifier.",
        examples=["pev_123abc"],
    )
    proposal_id: str = Field(description="Proposal identifier.", examples=["pp_001"])
    proposal_version_id: str = Field(
        description="Immutable proposal version identifier.",
        examples=["ppv_001"],
    )
    evaluation_status: PolicyEvaluationStatus = Field(
        description="Aggregate policy evaluation status.",
        examples=["PENDING_REVIEW"],
    )
    approval_dependencies: list[PolicyEvaluationRequirementProjection] = Field(
        description="Approval and review dependencies derived from policy outcomes.",
        examples=[[{"requirement_id": "REVIEW_DISCLOSURE:SG_STRUCTURED_NOTE"}]],
    )
    disclosure_requirements: list[PolicyEvaluationRequirementProjection] = Field(
        description="Disclosure requirements that must stay visible through memo/report prep.",
        examples=[[{"requirement_id": "advisor_reviewed_disclosure:SG_STRUCTURED_NOTE"}]],
    )
    consent_requirements: list[PolicyEvaluationRequirementProjection] = Field(
        description="Consent requirements that must stay visible through memo/report prep.",
        examples=[[{"requirement_id": "client_consent:SG_STRUCTURED_NOTE"}]],
    )
    conflict_posture: dict[str, Any] = Field(
        description="Conflict posture and blocker reason codes derived from policy rule outcomes.",
        examples=[{"status": "BLOCKED", "reason_codes": ["MATERIAL_CONFLICT_REQUIRES_REVIEW"]}],
    )
    sla_posture: dict[str, Any] = Field(
        description="Review queue age, open requirement count, and overdue posture.",
        examples=[{"status": "WITHIN_SLA", "open_requirement_count": 1}],
    )
    sign_off_status: PolicyEvaluationSignOffStatus = Field(
        description="Current sign-off readiness after applying requirement and event evidence.",
        examples=["PENDING_REVIEW"],
    )
    sign_off_blockers: list[str] = Field(
        default_factory=list,
        description="Blockers preventing policy sign-off or client-ready publication.",
        examples=[["DISCLOSURE_REQUIREMENT_OPEN:advisor_reviewed_disclosure:SG_STRUCTURED_NOTE"]],
    )
    maker_checker_required: bool = Field(
        description="Whether policy sign-off requires an actor different from record creator.",
        examples=[True],
    )
    latest_sign_off_event: PolicyEvaluationAuditEvent | None = Field(
        default=None,
        description="Latest append-only policy sign-off event where one exists.",
        examples=[{"event_type": "POLICY_EVALUATION_SIGN_OFF_RECORDED"}],
    )
    client_ready_publication: str = Field(
        description="Client-ready publication boundary for this policy workflow.",
        examples=["BLOCKED"],
    )
    metadata: PolicyEvaluationWorkflowMetadata = Field(
        description=(
            "Source-owned policy evaluation lineage metadata for downstream proof consumers."
        ),
        examples=[
            {
                "product_id": "lotus-advise:AdvisoryPolicyEvaluationRecord:v1",
                "generated_at": "2026-05-26T01:00:00+00:00",
                "content_hash": "sha256:policy-evaluation",
                "freshness_state": "current",
            }
        ],
    )
    replay_metadata: PolicyEvaluationWorkflowReplayMetadata = Field(
        description="Bounded replay metadata proving policy version, source refs, and hashes.",
        examples=[{"replay_policy": "EXACT_SOURCE_HASH_MATCH"}],
    )


class PolicyEvaluationSignOffDecisionRequest(BaseModel):
    actor_id: str = Field(
        description=(
            "Compatibility actor echo for the policy sign-off decision. The route authorizes and "
            "records the trusted policy checker principal from policy-control headers and rejects "
            "a mismatch."
        ),
        examples=["policy_checker_1"],
    )
    decision: PolicyEvaluationSignOffDecision = Field(
        description="Policy sign-off decision to record.",
        examples=["APPROVE_FOR_POLICY_SIGN_OFF"],
    )
    source_evaluation_hash: str = Field(
        description="Expected immutable policy evaluation hash reviewed by the decision actor.",
        examples=["sha256:policy-evaluation"],
    )
    resolved_approval_dependencies: list[str] = Field(
        default_factory=list,
        description="Approval dependencies resolved by this decision evidence.",
        examples=[["REVIEW_DISCLOSURE:SG_STRUCTURED_NOTE"]],
    )
    satisfied_disclosure_requirements: list[str] = Field(
        default_factory=list,
        description="Disclosure requirements satisfied by this decision evidence.",
        examples=[["advisor_reviewed_disclosure:SG_STRUCTURED_NOTE"]],
    )
    satisfied_consent_requirements: list[str] = Field(
        default_factory=list,
        description="Consent requirements satisfied by this decision evidence.",
        examples=[["client_consent:SG_STRUCTURED_NOTE"]],
    )
    conflict_review_outcome: str | None = Field(
        default=None,
        description="Conflict review outcome where conflict evidence was required.",
        examples=["NO_MATERIAL_CONFLICT_REMAINING"],
    )
    reason: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured sign-off rationale retained in append-only audit evidence.",
        examples=[{"purpose": "policy sign-off after disclosure and consent review"}],
    )


class PolicyEvaluationSignOffDecisionResponse(BaseModel):
    workflow: PolicyEvaluationWorkflowResponse = Field(
        description="Workflow posture after applying the sign-off decision."
    )
    sign_off_event: PolicyEvaluationAuditEvent = Field(
        description="Append-only sign-off or review event recorded for the decision."
    )
    replay_metadata: dict[str, Any] = Field(
        description="Hash and boundary metadata proving the decision source.",
        examples=[{"client_ready_publication": "BLOCKED"}],
    )
