from collections.abc import Iterable
from dataclasses import dataclass
from typing import Callable, Literal

from src.core.diagnostics_models import DiagnosticsData, RuleResult
from src.core.engine_options_models import EngineOptions
from src.core.gate_models import GateDecision, GateDecisionSummary, GateReason
from src.core.suitability_models import SuitabilityIssue, SuitabilityResult

_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
GateOutcome = tuple[
    Literal[
        "BLOCKED",
        "RISK_REVIEW_REQUIRED",
        "COMPLIANCE_REVIEW_REQUIRED",
        "CLIENT_CONSENT_REQUIRED",
        "EXECUTION_READY",
        "NONE",
    ],
    Literal[
        "FIX_INPUT",
        "RISK_REVIEW",
        "COMPLIANCE_REVIEW",
        "REQUEST_CLIENT_CONSENT",
        "EXECUTE",
        "NONE",
    ],
]


@dataclass(frozen=True)
class GateReasonBundle:
    reasons: list[GateReason]
    hard_fail_count: int
    soft_fail_count: int
    new_high_suitability_count: int
    new_medium_suitability_count: int


@dataclass(frozen=True)
class SuitabilityGateReasonCounts:
    new_high_suitability_count: int
    new_medium_suitability_count: int


@dataclass(frozen=True)
class GateDecisionContext:
    status: Literal["READY", "BLOCKED", "PENDING_REVIEW"]
    reason_bundle: GateReasonBundle
    options: EngineOptions
    default_requires_client_consent: bool


@dataclass(frozen=True)
class GateOutcomeRule:
    applies: Callable[[GateDecisionContext], bool]
    outcome: GateOutcome


def _has_blocking_input(context: GateDecisionContext) -> bool:
    return context.status == "BLOCKED" or context.reason_bundle.hard_fail_count > 0


def _requires_compliance_review(context: GateDecisionContext) -> bool:
    return context.reason_bundle.new_high_suitability_count > 0


def _requires_risk_review(context: GateDecisionContext) -> bool:
    return (
        context.reason_bundle.soft_fail_count > 0
        or context.reason_bundle.new_medium_suitability_count > 0
    )


def _has_client_consent(context: GateDecisionContext) -> bool:
    client_consent_already_obtained: bool = context.options.client_consent_already_obtained
    return client_consent_already_obtained


def _still_requires_client_consent(context: GateDecisionContext) -> bool:
    return _requires_client_consent(
        options=context.options,
        default_requires_client_consent=context.default_requires_client_consent,
    )


_GATE_OUTCOME_RULES: tuple[GateOutcomeRule, ...] = (
    GateOutcomeRule(_has_blocking_input, ("BLOCKED", "FIX_INPUT")),
    GateOutcomeRule(
        _requires_compliance_review,
        ("COMPLIANCE_REVIEW_REQUIRED", "COMPLIANCE_REVIEW"),
    ),
    GateOutcomeRule(_requires_risk_review, ("RISK_REVIEW_REQUIRED", "RISK_REVIEW")),
    GateOutcomeRule(_has_client_consent, ("EXECUTION_READY", "EXECUTE")),
    GateOutcomeRule(
        _still_requires_client_consent,
        ("CLIENT_CONSENT_REQUIRED", "REQUEST_CLIENT_CONSENT"),
    ),
)


def _dq_reasons(diagnostics: DiagnosticsData | None) -> list[GateReason]:
    dq = (
        diagnostics.data_quality
        if diagnostics is not None
        else {"price_missing": [], "fx_missing": []}
    )
    reasons: list[GateReason] = []
    if dq.get("price_missing"):
        reasons.append(
            GateReason(
                reason_code="DATA_QUALITY_MISSING_PRICE",
                severity="HIGH",
                source="DATA_QUALITY",
                details={"count": str(len(dq["price_missing"]))},
            )
        )
    if dq.get("fx_missing"):
        reasons.append(
            GateReason(
                reason_code="DATA_QUALITY_MISSING_FX",
                severity="HIGH",
                source="DATA_QUALITY",
                details={"count": str(len(dq["fx_missing"]))},
            )
        )
    return reasons


def _rule_reasons(rule_results: Iterable[RuleResult]) -> tuple[list[GateReason], int, int]:
    reasons: list[GateReason] = []
    hard_fail_count = 0
    soft_fail_count = 0
    for rule in rule_results:
        if rule.status != "FAIL":
            continue
        if rule.severity == "HARD":
            hard_fail_count += 1
            reasons.append(
                GateReason(
                    reason_code=f"HARD_RULE_FAIL:{rule.rule_id}",
                    severity="HIGH",
                    source="RULE_ENGINE",
                    details={"reason_code": rule.reason_code},
                )
            )
        elif rule.severity == "SOFT":
            soft_fail_count += 1
            reasons.append(
                GateReason(
                    reason_code=f"SOFT_RULE_FAIL:{rule.rule_id}",
                    severity="MEDIUM",
                    source="RULE_ENGINE",
                    details={"reason_code": rule.reason_code},
                )
            )
    return reasons, hard_fail_count, soft_fail_count


def _suitability_reasons(
    suitability: SuitabilityResult | None,
) -> tuple[list[GateReason], int, int]:
    if suitability is None:
        return [], 0, 0
    reasons = [
        reason
        for issue in suitability.issues
        if (reason := _new_suitability_gate_reason(issue)) is not None
    ]
    counts = _suitability_gate_reason_counts(reasons)
    return (
        reasons,
        counts.new_high_suitability_count,
        counts.new_medium_suitability_count,
    )


def _new_suitability_gate_reason(issue: SuitabilityIssue) -> GateReason | None:
    if issue.status_change != "NEW":
        return None
    if issue.severity == "HIGH":
        reason_code = "NEW_HIGH_SUITABILITY_ISSUE"
    elif issue.severity == "MEDIUM":
        reason_code = "NEW_MEDIUM_SUITABILITY_ISSUE"
    else:
        return None
    return GateReason(
        reason_code=reason_code,
        severity=issue.severity,
        source="SUITABILITY",
        details={"issue_id": issue.issue_id, "issue_key": issue.issue_key},
    )


def _suitability_gate_reason_counts(
    reasons: Iterable[GateReason],
) -> SuitabilityGateReasonCounts:
    reason_list = list(reasons)
    return SuitabilityGateReasonCounts(
        new_high_suitability_count=sum(
            reason.reason_code == "NEW_HIGH_SUITABILITY_ISSUE" for reason in reason_list
        ),
        new_medium_suitability_count=sum(
            reason.reason_code == "NEW_MEDIUM_SUITABILITY_ISSUE" for reason in reason_list
        ),
    )


def evaluate_gate_decision(
    *,
    status: Literal["READY", "BLOCKED", "PENDING_REVIEW"],
    rule_results: Iterable[RuleResult],
    suitability: SuitabilityResult | None,
    diagnostics: DiagnosticsData | None,
    options: EngineOptions,
    default_requires_client_consent: bool,
) -> GateDecision:
    reason_bundle = _collect_gate_reason_bundle(
        rule_results=rule_results,
        suitability=suitability,
        diagnostics=diagnostics,
    )
    gate, next_step = _resolve_gate_outcome(
        status=status,
        reason_bundle=reason_bundle,
        options=options,
        default_requires_client_consent=default_requires_client_consent,
    )
    return GateDecision(
        gate=gate,
        recommended_next_step=next_step,
        reasons=_sorted_gate_reasons(reason_bundle.reasons),
        summary=GateDecisionSummary(
            hard_fail_count=reason_bundle.hard_fail_count,
            soft_fail_count=reason_bundle.soft_fail_count,
            new_high_suitability_count=reason_bundle.new_high_suitability_count,
            new_medium_suitability_count=reason_bundle.new_medium_suitability_count,
        ),
    )


def _collect_gate_reason_bundle(
    *,
    rule_results: Iterable[RuleResult],
    suitability: SuitabilityResult | None,
    diagnostics: DiagnosticsData | None,
) -> GateReasonBundle:
    reasons, hard_fail_count, soft_fail_count = _rule_reasons(rule_results)
    suitability_reasons, new_high, new_medium = _suitability_reasons(suitability)
    reasons.extend(suitability_reasons)
    reasons.extend(_dq_reasons(diagnostics))
    return GateReasonBundle(
        reasons=reasons,
        hard_fail_count=hard_fail_count,
        soft_fail_count=soft_fail_count,
        new_high_suitability_count=new_high,
        new_medium_suitability_count=new_medium,
    )


def _resolve_gate_outcome(
    *,
    status: Literal["READY", "BLOCKED", "PENDING_REVIEW"],
    reason_bundle: GateReasonBundle,
    options: EngineOptions,
    default_requires_client_consent: bool,
) -> GateOutcome:
    context = GateDecisionContext(
        status=status,
        reason_bundle=reason_bundle,
        options=options,
        default_requires_client_consent=default_requires_client_consent,
    )
    for rule in _GATE_OUTCOME_RULES:
        if rule.applies(context):
            return rule.outcome
    return "EXECUTION_READY", "EXECUTE"


def _requires_client_consent(
    *,
    options: EngineOptions,
    default_requires_client_consent: bool,
) -> bool:
    return options.workflow_requires_client_consent or default_requires_client_consent


def _sorted_gate_reasons(reasons: list[GateReason]) -> list[GateReason]:
    return sorted(reasons, key=_gate_reason_sort_key)


def _gate_reason_sort_key(reason: GateReason) -> tuple[int, str, str, str]:
    return (
        _SEVERITY_ORDER[reason.severity],
        reason.source,
        reason.reason_code,
        reason.details.get("issue_key", reason.details.get("reason_code", "")),
    )
