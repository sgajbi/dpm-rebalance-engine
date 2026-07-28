from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.policy_packs.persistence_models import PolicyEvaluationAuditEvent
from src.core.policy_packs.receipt_identity import receipt_identity_from_record
from src.core.policy_packs.workflow_conflict_projection import conflict_posture_for_workflow
from src.core.policy_packs.workflow_models import (
    PolicyEvaluationRequirementProjection,
    PolicyEvaluationWorkflowMetadata,
    PolicyEvaluationWorkflowReplayMetadata,
    PolicyEvaluationWorkflowResponse,
)


def build_policy_evaluation_workflow_projection(
    *,
    record: Any,
    events: list[PolicyEvaluationAuditEvent],
    now: datetime,
    client_ready_publication: str,
) -> PolicyEvaluationWorkflowResponse:
    latest_sign_off = latest_sign_off_event(events)
    resolved = approved_sign_off_values(events, "resolved_approval_dependencies")
    disclosures = approved_sign_off_values(events, "satisfied_disclosure_requirements")
    consents = approved_sign_off_values(events, "satisfied_consent_requirements")
    conflict_posture = conflict_posture_for_workflow(record=record, events=events)
    approval_dependencies = approval_requirement_projections(
        record=record,
        now=now,
        satisfied_values=resolved,
    )
    disclosure_requirements = fixed_owner_requirement_projections(
        requirement_ids=record.disclosure_requirements,
        requirement_type="disclosure",
        owner_role="INVESTMENT_COUNSELLOR",
        generated_at=record.generated_at,
        now=now,
        satisfied_values=disclosures,
    )
    consent_requirements = fixed_owner_requirement_projections(
        requirement_ids=record.consent_requirements,
        requirement_type="consent",
        owner_role="ADVISOR",
        generated_at=record.generated_at,
        now=now,
        satisfied_values=consents,
    )
    all_requirements = collect_requirements(
        approval_dependencies,
        disclosure_requirements,
        consent_requirements,
    )
    blockers = workflow_blockers(
        record=record,
        requirements=all_requirements,
        conflict_posture=conflict_posture,
    )
    return PolicyEvaluationWorkflowResponse(
        evaluation_id=record.evaluation_id,
        proposal_id=record.proposal_id,
        proposal_version_id=record.proposal_version_id,
        evaluation_status=record.evaluation_status,
        approval_dependencies=approval_dependencies,
        disclosure_requirements=disclosure_requirements,
        consent_requirements=consent_requirements,
        conflict_posture=conflict_posture,
        sla_posture=sla_posture(requirements=all_requirements, now=now),
        sign_off_status=sign_off_status(
            blockers=blockers,
            latest_sign_off=latest_sign_off,
            evaluation_status=record.evaluation_status,
        ),
        sign_off_blockers=blockers,
        maker_checker_required=True,
        latest_sign_off_event=latest_sign_off,
        client_ready_publication=client_ready_publication,
        metadata=workflow_lineage_metadata(
            record=record,
            client_ready_publication=client_ready_publication,
        ),
        replay_metadata=workflow_replay_metadata(record=record),
    )


def latest_sign_off_event(
    events: list[PolicyEvaluationAuditEvent],
) -> PolicyEvaluationAuditEvent | None:
    sign_off_events = [event for event in events if is_sign_off_recorded_event(event)]
    return sign_off_events[-1] if sign_off_events else None


def is_sign_off_recorded_event(event: PolicyEvaluationAuditEvent) -> bool:
    return event.event_type == "POLICY_EVALUATION_SIGN_OFF_RECORDED"


def approved_sign_off_values(events: list[PolicyEvaluationAuditEvent], key: str) -> set[str]:
    values: set[str] = set()
    for event in events:
        if not is_approved_sign_off_event(event):
            continue
        values.update(sign_off_reason_values(event, key))
    return values


def is_approved_sign_off_event(event: PolicyEvaluationAuditEvent) -> bool:
    return (
        is_sign_off_recorded_event(event)
        and event.reason_json.get("decision") == "APPROVE_FOR_POLICY_SIGN_OFF"
    )


def sign_off_reason_values(event: PolicyEvaluationAuditEvent, key: str) -> set[str]:
    raw = event.reason_json.get(key, [])
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw}


def approval_requirement_projections(
    *,
    record: Any,
    now: datetime,
    satisfied_values: set[str],
) -> list[PolicyEvaluationRequirementProjection]:
    return [
        requirement_projection(
            requirement_id=item,
            requirement_type="approval",
            owner_role=owner_role(item),
            generated_at=record.generated_at,
            now=now,
            satisfied=item in satisfied_values,
        )
        for item in record.approval_dependencies
    ]


def fixed_owner_requirement_projections(
    *,
    requirement_ids: list[str],
    requirement_type: str,
    owner_role: str,
    generated_at: str,
    now: datetime,
    satisfied_values: set[str],
) -> list[PolicyEvaluationRequirementProjection]:
    return [
        requirement_projection(
            requirement_id=item,
            requirement_type=requirement_type,
            owner_role=owner_role,
            generated_at=generated_at,
            now=now,
            satisfied=item in satisfied_values,
        )
        for item in requirement_ids
    ]


def collect_requirements(
    *groups: list[PolicyEvaluationRequirementProjection],
) -> list[PolicyEvaluationRequirementProjection]:
    return [requirement for group in groups for requirement in group]


def requirement_projection(
    *,
    requirement_id: str,
    requirement_type: str,
    owner_role: str,
    generated_at: str,
    now: datetime,
    satisfied: bool,
) -> PolicyEvaluationRequirementProjection:
    review_sla = review_sla_for_requirement(requirement_id=requirement_id, owner_role=owner_role)
    due_at = due_at_for_requirement(generated_at=generated_at, review_sla=review_sla)
    overdue = bool(due_at and parse_datetime(due_at) < now)
    return PolicyEvaluationRequirementProjection(
        requirement_id=requirement_id,
        requirement_type=requirement_type,
        status="SATISFIED" if satisfied else "OPEN",
        owner_role=owner_role,
        review_sla=review_sla,
        due_at=due_at,
        reason_codes=["POLICY_REQUIREMENT_SATISFIED"]
        if satisfied
        else ["POLICY_REQUIREMENT_OVERDUE" if overdue else "POLICY_REQUIREMENT_OPEN"],
    )


def workflow_blockers(
    *,
    record: Any,
    requirements: list[PolicyEvaluationRequirementProjection],
    conflict_posture: dict[str, Any],
) -> list[str]:
    return unique(
        [
            *open_requirement_blockers(requirements),
            *conflict_posture_blockers(conflict_posture),
            *evaluation_status_blockers(record.evaluation_status),
        ]
    )


def open_requirement_blockers(
    requirements: list[PolicyEvaluationRequirementProjection],
) -> list[str]:
    return [
        f"{requirement.requirement_type.upper()}_REQUIREMENT_OPEN:{requirement.requirement_id}"
        for requirement in requirements
        if requirement.status != "SATISFIED"
    ]


def conflict_posture_blockers(conflict_posture: dict[str, Any]) -> list[str]:
    if conflict_posture["status"] != "BLOCKED":
        return []
    return [str(item) for item in conflict_posture["blockers"]]


def evaluation_status_blockers(evaluation_status: str) -> list[str]:
    if evaluation_status != "BLOCKED":
        return []
    return ["BLOCKED_POLICY_EVALUATION_CANNOT_BE_SIGNED_OFF"]


def sign_off_status(
    *,
    blockers: list[str],
    latest_sign_off: PolicyEvaluationAuditEvent | None,
    evaluation_status: str,
) -> str:
    if latest_sign_off is not None and is_approved_sign_off_event(latest_sign_off):
        return "SIGNED_OFF"
    if sign_off_has_blocking_conflict(blockers=blockers, evaluation_status=evaluation_status):
        return "BLOCKED"
    if blockers:
        return "PENDING_REVIEW"
    return "READY_FOR_SIGN_OFF"


def sign_off_has_blocking_conflict(*, blockers: list[str], evaluation_status: str) -> bool:
    return evaluation_status == "BLOCKED" or any("CONFLICT" in blocker for blocker in blockers)


def sla_posture(
    *, requirements: list[PolicyEvaluationRequirementProjection], now: datetime
) -> dict[str, Any]:
    open_requirements = open_requirements_for_sla(requirements)
    overdue = overdue_requirement_ids(open_requirements, now=now)
    return {
        "status": "OVERDUE" if overdue else "WITHIN_SLA",
        "open_requirement_count": len(open_requirements),
        "overdue_requirement_ids": overdue,
        "as_of": now.isoformat(),
    }


def open_requirements_for_sla(
    requirements: list[PolicyEvaluationRequirementProjection],
) -> list[PolicyEvaluationRequirementProjection]:
    return [item for item in requirements if item.status != "SATISFIED"]


def overdue_requirement_ids(
    requirements: list[PolicyEvaluationRequirementProjection],
    *,
    now: datetime,
) -> list[str]:
    return [item.requirement_id for item in requirements if requirement_is_overdue(item, now=now)]


def requirement_is_overdue(
    requirement: PolicyEvaluationRequirementProjection,
    *,
    now: datetime,
) -> bool:
    return requirement.due_at is not None and parse_datetime(requirement.due_at) < now


def owner_role(requirement_id: str) -> str:
    if requirement_id.startswith("SUPERVISORY_"):
        return "SUPERVISOR"
    if requirement_id.startswith("POLICY_STEWARD_"):
        return "POLICY_STEWARD"
    if "DISCLOSURE" in requirement_id:
        return "INVESTMENT_COUNSELLOR"
    if "CONFLICT" in requirement_id:
        return "SUPERVISOR"
    return "ADVISOR"


def review_sla_for_requirement(*, requirement_id: str, owner_role: str) -> str:
    if owner_role == "SUPERVISOR" or "CONFLICT" in requirement_id:
        return "P2D"
    return "P1D"


def due_at_for_requirement(*, generated_at: str, review_sla: str) -> str | None:
    generated = parse_datetime(generated_at)
    if review_sla == "P2D":
        return (generated + timedelta(days=2)).isoformat()
    if review_sla == "P1D":
        return (generated + timedelta(days=1)).isoformat()
    return None


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def workflow_lineage_metadata(
    *, record: Any, client_ready_publication: str
) -> PolicyEvaluationWorkflowMetadata:
    source_gaps = list(record.source_gaps)
    receipt_identity = receipt_identity_from_record(record)
    return PolicyEvaluationWorkflowMetadata(
        product_id="lotus-advise:AdvisoryPolicyEvaluationRecord:v1",
        product_version="v1",
        source_system="LOTUS_ADVISE",
        evaluation_id=record.evaluation_id,
        proposal_id=record.proposal_id,
        proposal_version_id=record.proposal_version_id,
        portfolio_id=record.portfolio_id,
        policy_pack_id=record.policy_pack_id,
        policy_version=record.policy_version,
        as_of_date=receipt_identity.as_of_date,
        generated_at=record.generated_at,
        content_hash=record.evaluation_hash,
        evaluation_hash=record.evaluation_hash,
        source_evidence_hash=record.source_evidence_hash,
        policy_content_hash=record.policy_content_hash,
        freshness_state="current",
        data_quality_status="incomplete" if source_gaps else "complete",
        source_gap_count=len(source_gaps),
        source_gaps=source_gaps,
        client_ready_publication=client_ready_publication,
        scope_identity=receipt_identity.scope_identity,
        observed_correlation_id_hash=receipt_identity.observed_correlation_id_hash,
        observed_trace_id_hash=receipt_identity.observed_trace_id_hash,
    )


def workflow_replay_metadata(*, record: Any) -> PolicyEvaluationWorkflowReplayMetadata:
    receipt_identity = receipt_identity_from_record(record)
    return PolicyEvaluationWorkflowReplayMetadata(
        receipt_contract_version=receipt_identity.receipt_contract_version,
        evaluation_id=record.evaluation_id,
        proposal_id=record.proposal_id,
        proposal_version_id=record.proposal_version_id,
        portfolio_id=record.portfolio_id,
        as_of_date=receipt_identity.as_of_date,
        policy_pack_id=record.policy_pack_id,
        policy_version=record.policy_version,
        source_refs=list(record.source_refs),
        source_gaps=list(record.source_gaps),
        source_evidence_hash=record.source_evidence_hash,
        evaluation_hash=record.evaluation_hash,
        policy_content_hash=record.policy_content_hash,
        replay_policy=record.replay_metadata_json.get(
            "replay_policy",
            "EXACT_SOURCE_HASH_MATCH",
        ),
        scope_identity=receipt_identity.scope_identity,
        observed_correlation_id_hash=receipt_identity.observed_correlation_id_hash,
        observed_trace_id_hash=receipt_identity.observed_trace_id_hash,
    )


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = ["build_policy_evaluation_workflow_projection"]
