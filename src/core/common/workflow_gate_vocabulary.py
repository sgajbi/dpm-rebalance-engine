"""Advise-owned workflow-gate vocabulary derived from the gate rules."""

from src.core.common.workflow_gates import _GATE_OUTCOME_RULES

_WORKFLOW_GATE_NEXT_STEPS: dict[str, str] = {
    "BLOCKED": "FIX_INPUT",
    "RISK_REVIEW_REQUIRED": "RISK_REVIEW",
    "COMPLIANCE_REVIEW_REQUIRED": "COMPLIANCE_REVIEW",
    "CLIENT_CONSENT_REQUIRED": "REQUEST_CLIENT_CONSENT",
    "EXECUTION_READY": "EXECUTE",
    "NONE": "NONE",
}


def workflow_gate_vocabulary() -> dict[str, str]:
    """Return the Advise-owned workflow-gate to next-step contract."""

    rule_pairs: dict[str, str] = {}
    for rule in _GATE_OUTCOME_RULES:
        gate, next_step = rule.outcome
        previous = rule_pairs.setdefault(gate, next_step)
        if previous != next_step:
            raise RuntimeError(f"workflow gate {gate} has conflicting next steps")
    rule_pairs["NONE"] = "NONE"
    if rule_pairs != _WORKFLOW_GATE_NEXT_STEPS:
        raise RuntimeError("workflow gate vocabulary drifted from outcome rules")
    return dict(_WORKFLOW_GATE_NEXT_STEPS)
