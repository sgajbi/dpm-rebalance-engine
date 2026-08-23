from src.core.advisory.decision_summary_models import (
    ProposalDecisionConfidence,
    ProposalDecisionMissingEvidence,
    ProposalDecisionNextAction,
    ProposalDecisionStatus,
)
from src.core.proposal_result_models import ProposalResult

_GATE_DECISION_STATUS: dict[str, ProposalDecisionStatus] = {
    "COMPLIANCE_REVIEW_REQUIRED": "REQUIRES_COMPLIANCE_REVIEW",
    "RISK_REVIEW_REQUIRED": "REQUIRES_RISK_REVIEW",
    "CLIENT_CONSENT_REQUIRED": "REQUIRES_CLIENT_CONSENT",
}

_DECISION_STATUS_REASON_CODES: dict[ProposalDecisionStatus, str] = {
    "READY_FOR_CLIENT_REVIEW": "PROPOSAL_READY_FOR_CLIENT_REVIEW",
    "REVISION_RECOMMENDED": "PROPOSAL_REVISION_RECOMMENDED",
    "REQUIRES_CLIENT_CONSENT": "CLIENT_CONSENT_REQUIRED",
    "REQUIRES_RISK_REVIEW": "RISK_REVIEW_REQUIRED",
    "REQUIRES_COMPLIANCE_REVIEW": "COMPLIANCE_REVIEW_REQUIRED",
    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
    "BLOCKED_REMEDIATION_REQUIRED": "PROPOSAL_BLOCKED",
}

_DECISION_STATUS_SUMMARIES: dict[ProposalDecisionStatus, str] = {
    "BLOCKED_REMEDIATION_REQUIRED": (
        "Proposal cannot proceed until blocking issues are remediated."
    ),
    "REQUIRES_COMPLIANCE_REVIEW": (
        "Proposal requires compliance review before client progression."
    ),
    "REQUIRES_RISK_REVIEW": "Proposal requires risk review before client progression.",
    "REQUIRES_CLIENT_CONSENT": (
        "Proposal is ready for client discussion and recorded client consent."
    ),
    "INSUFFICIENT_EVIDENCE": (
        "Proposal cannot be fully assessed because required evidence is unavailable."
    ),
    "REVISION_RECOMMENDED": "Proposal should be revised before further progression.",
    "READY_FOR_CLIENT_REVIEW": "Proposal is ready for client review.",
}

_DECISION_STATUS_NEXT_ACTIONS: dict[ProposalDecisionStatus, ProposalDecisionNextAction] = {
    "BLOCKED_REMEDIATION_REQUIRED": "FIX_INPUT",
    "REQUIRES_COMPLIANCE_REVIEW": "REVIEW_COMPLIANCE",
    "REQUIRES_RISK_REVIEW": "REVIEW_RISK",
    "REQUIRES_CLIENT_CONSENT": "DISCUSS_WITH_CLIENT",
    "REVISION_RECOMMENDED": "REVISE_PROPOSAL",
    "READY_FOR_CLIENT_REVIEW": "DISCUSS_WITH_CLIENT",
}

# These pairings are the Advise-owned source contract consumed by downstream
# anti-corruption validators. Keep the runtime derivation rules above and this
# published vocabulary in the same module so a vocabulary change cannot be
# made only in a consumer-owned snapshot.
_DECISION_STATUS_TOP_LEVELS: dict[ProposalDecisionStatus, tuple[str, ...]] = {
    "READY_FOR_CLIENT_REVIEW": ("READY",),
    "REQUIRES_RISK_REVIEW": ("READY", "PENDING_REVIEW"),
    "REQUIRES_COMPLIANCE_REVIEW": ("READY", "PENDING_REVIEW"),
    "REQUIRES_CLIENT_CONSENT": ("READY", "PENDING_REVIEW"),
    "BLOCKED_REMEDIATION_REQUIRED": ("BLOCKED",),
    "INSUFFICIENT_EVIDENCE": ("READY", "PENDING_REVIEW"),
    "REVISION_RECOMMENDED": ("PENDING_REVIEW",),
}
_DECISION_STATUS_ALLOWED_NEXT_ACTIONS: dict[ProposalDecisionStatus, tuple[str, ...]] = {
    **{status: (next_action,) for status, next_action in _DECISION_STATUS_NEXT_ACTIONS.items()},
    "INSUFFICIENT_EVIDENCE": (
        "REQUEST_CLIENT_CONTEXT",
        "REQUEST_MANDATE_CONTEXT",
        "REVISE_PROPOSAL",
    ),
}
_DECISION_STATUS_WORKFLOW_GATES: dict[ProposalDecisionStatus, tuple[str, ...]] = {
    "READY_FOR_CLIENT_REVIEW": ("EXECUTION_READY", "NONE"),
    "REQUIRES_RISK_REVIEW": ("RISK_REVIEW_REQUIRED",),
    "REQUIRES_COMPLIANCE_REVIEW": ("COMPLIANCE_REVIEW_REQUIRED",),
    "REQUIRES_CLIENT_CONSENT": ("CLIENT_CONSENT_REQUIRED",),
    "BLOCKED_REMEDIATION_REQUIRED": ("BLOCKED",),
    "INSUFFICIENT_EVIDENCE": (
        "RISK_REVIEW_REQUIRED",
        "COMPLIANCE_REVIEW_REQUIRED",
        "CLIENT_CONSENT_REQUIRED",
    ),
    "REVISION_RECOMMENDED": ("EXECUTION_READY", "NONE"),
}

_CLIENT_CONTEXT_EVIDENCE_GAPS = {
    "MISSING_CLIENT_CONTEXT",
    "MISSING_CLIENT_PRODUCT_COMPLEXITY_EVIDENCE",
}
_MANDATE_CONTEXT_EVIDENCE_GAPS = {
    "MISSING_MANDATE_CONTEXT",
    "MISSING_MANDATE_RESTRICTED_PRODUCT_EVIDENCE",
}


def derive_decision_status(
    result: ProposalResult,
    missing_evidence: list[ProposalDecisionMissingEvidence],
) -> ProposalDecisionStatus:
    if _is_blocked_result(result):
        return "BLOCKED_REMEDIATION_REQUIRED"
    if _has_blocking_missing_evidence(missing_evidence):
        return "INSUFFICIENT_EVIDENCE"

    if gate_status := _status_from_gate_decision(result):
        return gate_status

    return _status_from_proposal_result(result)


def _is_blocked_result(result: ProposalResult) -> bool:
    return bool(result.status == "BLOCKED")


def _has_blocking_missing_evidence(
    missing_evidence: list[ProposalDecisionMissingEvidence],
) -> bool:
    return any(item.blocking for item in missing_evidence)


def _status_from_gate_decision(result: ProposalResult) -> ProposalDecisionStatus | None:
    gate = result.gate_decision.gate if result.gate_decision is not None else None
    return _GATE_DECISION_STATUS.get(str(gate))


def _status_from_proposal_result(result: ProposalResult) -> ProposalDecisionStatus:
    if result.status == "PENDING_REVIEW":
        return "REVISION_RECOMMENDED"
    return "READY_FOR_CLIENT_REVIEW"


def primary_decision_reason_code(
    result: ProposalResult,
    missing_evidence: list[ProposalDecisionMissingEvidence],
    decision_status: ProposalDecisionStatus,
) -> str:
    if decision_status == "INSUFFICIENT_EVIDENCE" and missing_evidence:
        return str(missing_evidence[0].reason_code)
    gate_reason_code = _gate_reason_code(result)
    if gate_reason_code is not None:
        return gate_reason_code
    if missing_evidence:
        return str(missing_evidence[0].reason_code)
    return _reason_code_for_decision_status(decision_status)


def _gate_reason_code(result: ProposalResult) -> str | None:
    if result.gate_decision is None or not result.gate_decision.reasons:
        return None
    return str(result.gate_decision.reasons[0].reason_code)


def _reason_code_for_decision_status(decision_status: ProposalDecisionStatus) -> str:
    return _DECISION_STATUS_REASON_CODES[decision_status]


def primary_decision_summary(
    decision_status: ProposalDecisionStatus, primary_reason_code: str
) -> str:
    if primary_reason_code == "MISSING_RISK_LENS":
        return "Proposal is ready, but risk evidence is currently unavailable."
    return _DECISION_STATUS_SUMMARIES[decision_status]


def recommended_decision_next_action(
    decision_status: ProposalDecisionStatus,
    missing_evidence: list[ProposalDecisionMissingEvidence],
) -> ProposalDecisionNextAction:
    if decision_status == "INSUFFICIENT_EVIDENCE":
        return _insufficient_evidence_next_action(missing_evidence)
    return _DECISION_STATUS_NEXT_ACTIONS[decision_status]


def _insufficient_evidence_next_action(
    missing_evidence: list[ProposalDecisionMissingEvidence],
) -> ProposalDecisionNextAction:
    for item in missing_evidence:
        if item.reason_code in _CLIENT_CONTEXT_EVIDENCE_GAPS:
            return "REQUEST_CLIENT_CONTEXT"
        if item.reason_code in _MANDATE_CONTEXT_EVIDENCE_GAPS:
            return "REQUEST_MANDATE_CONTEXT"
    return "REVISE_PROPOSAL"


def proposal_decision_vocabulary() -> dict[str, dict[str, tuple[str, ...]]]:
    """Return the versioned decision pairings owned by the Advise rule module."""

    statuses = set(_DECISION_STATUS_TOP_LEVELS)
    if statuses != set(_DECISION_STATUS_ALLOWED_NEXT_ACTIONS) or statuses != set(
        _DECISION_STATUS_WORKFLOW_GATES
    ):
        raise RuntimeError("decision vocabulary maps do not cover the same statuses")
    return {
        status: {
            "allowed_top_level_statuses": _DECISION_STATUS_TOP_LEVELS[status],
            "allowed_recommended_next_actions": _DECISION_STATUS_ALLOWED_NEXT_ACTIONS[status],
            "allowed_workflow_gates": _DECISION_STATUS_WORKFLOW_GATES[status],
        }
        for status in _DECISION_STATUS_TOP_LEVELS
    }


def decision_confidence(
    result: ProposalResult,
    missing_evidence: list[ProposalDecisionMissingEvidence],
) -> ProposalDecisionConfidence:
    if result.status == "BLOCKED" and missing_evidence:
        return "INSUFFICIENT"
    if missing_evidence:
        return "LOW"
    if result.status == "PENDING_REVIEW":
        return "MEDIUM"
    return "HIGH"
