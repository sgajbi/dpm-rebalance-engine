from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from src.core.common.canonical import hash_canonical_payload
from src.core.policy_packs.evaluation_models import PolicyPackEvaluationResponse
from src.core.policy_packs.persistence_models import PolicyEvaluationRecord
from src.core.policy_packs.receipt_identity import build_policy_evaluation_receipt_identity
from src.core.policy_packs.supportability import POLICY_EVALUATION_PERSISTENCE_CONTRACT_VERSION
from src.core.proposals.exceptions import ProposalValidationError

_PERSISTENCE_CONTRACT_VERSION = POLICY_EVALUATION_PERSISTENCE_CONTRACT_VERSION


def build_policy_evaluation_record(
    *,
    evaluation: PolicyPackEvaluationResponse,
    evidence_bundle: dict[str, Any],
    proposal_id: str,
    proposal_version_id: str,
    created_by: str,
    source_evidence_hash: str,
    policy_content_hash: str,
    idempotency_key: str,
    reason: dict[str, Any],
    observed_trace_id: str | None,
) -> PolicyEvaluationRecord:
    generated_at = datetime.now(UTC)
    portfolio_id = _portfolio_id(evidence_bundle)
    evaluation_hash = policy_evaluation_hash(
        evaluation=evaluation,
        source_evidence_hash=source_evidence_hash,
        policy_content_hash=policy_content_hash,
    )
    receipt_identity = build_policy_evaluation_receipt_identity(
        evidence_bundle=evidence_bundle,
        proposal_id=proposal_id,
        proposal_version_id=proposal_version_id,
        portfolio_id=portfolio_id,
        reason=reason,
        observed_trace_id=observed_trace_id,
        observed_at=generated_at,
    )
    source_refs = _source_refs(evaluation)
    source_gaps = _source_gaps(evaluation)
    record_identity_hash = hash_canonical_payload(
        {
            "proposal_id": proposal_id,
            "proposal_version_id": proposal_version_id,
            "policy_pack_id": evaluation.policy_pack.policy_pack_id,
            "policy_version": evaluation.policy_pack.policy_version,
            "source_evidence_hash": source_evidence_hash,
        }
    )
    evaluation_id = f"pev_{record_identity_hash.removeprefix('sha256:')[:20]}"
    return PolicyEvaluationRecord(
        evaluation_id=evaluation_id,
        proposal_id=proposal_id,
        proposal_version_id=proposal_version_id,
        portfolio_id=portfolio_id,
        policy_pack_id=evaluation.policy_pack.policy_pack_id,
        policy_version=evaluation.policy_pack.policy_version,
        generated_at=generated_at.isoformat(),
        created_by=created_by,
        evaluation_status=evaluation.evaluation_status,
        policy_content_hash=policy_content_hash,
        source_evidence_hash=source_evidence_hash,
        evaluation_hash=evaluation_hash,
        rule_result_hashes={
            result.rule_id: hash_canonical_payload(result.model_dump(mode="json"))
            for result in evaluation.rule_results
        },
        evaluation_json=evaluation.model_dump(mode="json"),
        source_refs=source_refs,
        source_gaps=source_gaps,
        approval_dependencies=_approval_dependencies(evaluation),
        disclosure_requirements=_disclosure_requirements(evaluation),
        consent_requirements=_consent_requirements(evaluation),
        replay_metadata_json={
            "persistence_contract_version": _PERSISTENCE_CONTRACT_VERSION,
            "policy_evaluation_contract_version": evaluation.contract_version,
            "policy_pack_id": evaluation.policy_pack.policy_pack_id,
            "policy_version": evaluation.policy_pack.policy_version,
            "policy_content_hash": policy_content_hash,
            "source_evidence_hash": source_evidence_hash,
            "evaluation_hash": evaluation_hash,
            "source_refs": source_refs,
            "source_gaps": source_gaps,
            "receipt_identity": receipt_identity.model_dump(mode="json"),
            "as_of_date": receipt_identity.as_of_date,
            "idempotency_key": idempotency_key,
            "creation_reason": reason,
            "replay_policy": "PIN_POLICY_VERSION_AND_COMPARE_SOURCE_HASHES",
        },
    )


def policy_evaluation_hash(
    *,
    evaluation: PolicyPackEvaluationResponse,
    source_evidence_hash: str,
    policy_content_hash: str,
) -> str:
    return cast(
        str,
        hash_canonical_payload(
            {
                "contract_version": _PERSISTENCE_CONTRACT_VERSION,
                "policy_evaluation": evaluation.model_dump(mode="json"),
                "policy_content_hash": policy_content_hash,
                "source_evidence_hash": source_evidence_hash,
            }
        ),
    )


def _portfolio_id(evidence_bundle: dict[str, Any]) -> str:
    portfolio = evidence_bundle.get("inputs", {}).get("portfolio_snapshot", {})
    if isinstance(portfolio, dict):
        value = portfolio.get("portfolio_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ProposalValidationError("POLICY_EVALUATION_PORTFOLIO_ID_REQUIRED")


def _source_refs(evaluation: PolicyPackEvaluationResponse) -> list[str]:
    refs: list[str] = []
    for result in evaluation.rule_results:
        refs.extend(result.source_authority_refs)
        refs.extend(result.evidence_refs)
    return _unique(refs)


def _source_gaps(evaluation: PolicyPackEvaluationResponse) -> list[str]:
    gaps = list(evaluation.applicability.missing_evidence)
    for result in evaluation.rule_results:
        gaps.extend(result.missing_evidence)
    return _unique(gaps)


def _approval_dependencies(evaluation: PolicyPackEvaluationResponse) -> list[str]:
    actions = _required_actions(evaluation)
    return _unique(
        [
            action
            for action in actions
            if action.startswith(("REVIEW_", "SUPERVISORY_", "POLICY_STEWARD_"))
        ]
    )


def _disclosure_requirements(evaluation: PolicyPackEvaluationResponse) -> list[str]:
    values: list[str] = []
    for result in evaluation.rule_results:
        values.extend(
            item
            for item in result.missing_evidence
            if item.startswith("advisor_reviewed_disclosure")
        )
    values.extend(action for action in _required_actions(evaluation) if "DISCLOSURE" in action)
    return _unique(values)


def _consent_requirements(evaluation: PolicyPackEvaluationResponse) -> list[str]:
    values: list[str] = []
    for result in evaluation.rule_results:
        values.extend(item for item in result.missing_evidence if item.startswith("client_consent"))
    values.extend(action for action in _required_actions(evaluation) if "CONSENT" in action)
    return _unique(values)


def _required_actions(evaluation: PolicyPackEvaluationResponse) -> list[str]:
    actions: list[str] = []
    for result in evaluation.rule_results:
        actions.extend(result.required_actions)
    return _unique(actions)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
