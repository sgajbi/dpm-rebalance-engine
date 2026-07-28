from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.policy_packs import (
    PolicyEvaluationSignOffDecisionRequest,
    activate_policy_pack_version,
    finalize_policy_evaluation_record,
    get_policy_evaluation_workflow,
    get_policy_pack_version,
    record_policy_evaluation_sign_off_decision,
    reset_policy_evaluation_store_for_tests,
    reset_policy_pack_catalog_for_tests,
    validate_policy_pack_version,
)
from src.core.policy_packs.persistence_models import PolicyEvaluationAuditEvent
from src.core.policy_packs.workflow_conflict_projection import conflict_posture_for_workflow
from src.core.policy_packs.workflow_projection import (
    build_policy_evaluation_workflow_projection,
)
from src.core.proposals.exceptions import ProposalValidationError

REPO_ROOT = Path(__file__).resolve().parents[4]


def setup_function() -> None:
    reset_policy_pack_catalog_for_tests()
    reset_policy_evaluation_store_for_tests()


def test_policy_workflow_delegates_projection_and_decision_helpers() -> None:
    workflow_source = (REPO_ROOT / "src/core/policy_packs/workflow.py").read_text(encoding="utf-8")
    projection_source = (REPO_ROOT / "src/core/policy_packs/workflow_projection.py").read_text(
        encoding="utf-8"
    )
    decision_source = (REPO_ROOT / "src/core/policy_packs/workflow_decision.py").read_text(
        encoding="utf-8"
    )

    assert "from src.core.policy_packs.workflow_projection import" in workflow_source
    assert "from src.core.policy_packs.workflow_decision import" in workflow_source
    assert "from src.core.policy_packs.workflow_conflict_projection import" in projection_source
    assert "def build_policy_evaluation_workflow_projection(" not in workflow_source
    assert "def validate_policy_sign_off_decision(" not in workflow_source
    assert "def build_policy_evaluation_workflow_projection(" in projection_source
    assert "def validate_policy_sign_off_decision(" in decision_source
    assert "POLICY_EVALUATION_SIGN_OFF_REQUIRES_MAKER_CHECKER" not in workflow_source
    assert "POLICY_EVALUATION_SIGN_OFF_REQUIRES_MAKER_CHECKER" in decision_source
    assert "CONFLICT_REVIEW_OUTCOME_REQUIRED" not in workflow_source
    assert "CONFLICT_REVIEW_OUTCOME_REQUIRED" in decision_source


def _base_evidence_bundle() -> dict:
    return {
        "context_resolution": {
            "as_of_date": "2026-05-26",
            "advisory_policy_context": {
                "jurisdiction": "SG",
                "client_classification": "ACCREDITED_INVESTOR",
                "booking_center_code": "SG",
                "legal_entity_code": "REFERENCE",
                "household_id": "HH-PB-001",
                "account_id": "ACCT-PB-001",
                "time_horizon": "5Y",
                "liquidity_need": "MEDIUM",
                "mandate_id": "MANDATE-BALANCED-001",
                "objectives": ["capital_preservation", "balanced_growth"],
                "restrictions": ["no_single_name_above_10pct"],
            },
        },
        "inputs": {
            "portfolio_snapshot": {
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "as_of_date": "2026-05-26",
                "positions": [{"instrument_id": "US_EQ_ETF", "quantity": "100"}],
                "cash_balances": [{"currency": "USD", "amount": "50000"}],
            },
            "market_data_snapshot": {
                "as_of_date": "2026-05-26",
                "prices": [{"instrument_id": "US_EQ_ETF", "price": "100", "currency": "USD"}],
                "fx_rates": [{"pair": "USD/SGD", "rate": "1.35"}],
            },
            "shelf_entries": [
                {
                    "instrument_id": "SG_STRUCTURED_NOTE",
                    "eligibility": {"jurisdictions": ["SG"]},
                    "target_market": {"client_segments": ["ACCREDITED_INVESTOR"]},
                    "complexity": "COMPLEX",
                    "structured_product": True,
                }
            ],
            "proposed_trades": [{"instrument_id": "SG_STRUCTURED_NOTE", "side": "BUY"}],
        },
        "risk_lens": {
            "source_service": "lotus-risk",
            "single_position_concentration": {"top_position_weight_current": "0.10"},
            "issuer_concentration": {"hhi_current": "1200"},
            "drawdown": {"max_drawdown_1y": "0.08"},
            "var": {"var_95_1m": "0.04"},
            "stress": {"equity_down_20": "-0.09"},
            "liquidity_risk": {"days_to_liquidate": "3"},
            "private_asset_risk": {"private_asset_weight": "0.00"},
            "climate_geopolitical_risk": {"status": "not_material"},
        },
        "artifact": {
            "assumptions_and_limits": {
                "costs_and_fees": {"included": True},
                "tax": {"included": True},
                "execution": {"included": True},
            },
            "disclosures": {
                "product_docs": [{"instrument_id": "SG_STRUCTURED_NOTE", "doc_ref": "Term sheet"}],
            },
        },
        "conflict_evidence": {"material_conflict": False, "review_ref": "conflict-review-001"},
    }


def _trusted_reason(purpose: str) -> dict:
    return {
        "purpose": purpose,
        "trusted_principal": {
            "subject": "advisor_1",
            "role": "ADVISOR",
            "tenant_id": "tenant_sg_001",
            "legal_entity_code": "REFERENCE",
            "correlation_id": "corr-policy-workflow-test",
            "trace_id": "trace-policy-workflow-test",
            "service_identity": "lotus-gateway",
            "capability": "advisory.policy_evaluation.finalize",
        },
    }


def _activate_sg_policy_pack() -> None:
    detail = get_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
    )
    validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="validate-sg-workflow",
        reason={"purpose": "slice 9 workflow test"},
    )
    activate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        activated_by="policy_checker_1",
        source_content_hash=detail.policy_pack.content_hash,
        idempotency_key="activate-sg-workflow",
        reason={"purpose": "slice 9 workflow test"},
    )


def _create_policy_evaluation(*, material_conflict: bool = False):
    _activate_sg_policy_pack()
    evidence = _base_evidence_bundle()
    evidence["conflict_evidence"]["material_conflict"] = material_conflict
    return finalize_policy_evaluation_record(
        evidence_bundle=evidence,
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        proposal_id="pp_policy_workflow",
        proposal_version_id="ppv_policy_workflow",
        created_by="advisor_1",
        idempotency_key=f"policy-workflow-{material_conflict}",
        reason=_trusted_reason("workflow projection"),
    ).record


def _audit_event_with_reason(reason: dict) -> PolicyEvaluationAuditEvent:
    return PolicyEvaluationAuditEvent(
        event_id="peev_conflict_review",
        evaluation_id="pev_conflict_review",
        proposal_id="pp_conflict_review",
        proposal_version_id="ppv_conflict_review",
        event_type="POLICY_EVALUATION_SIGN_OFF_RECORDED",
        actor_id="policy_checker_1",
        occurred_at="2026-05-26T01:00:00+00:00",
        content_hash="sha256:policy-evaluation",
        reason_json=reason,
    )


def test_policy_workflow_conflict_projection_blocks_unresolved_material_conflicts() -> None:
    record = SimpleNamespace(
        evaluation_json={
            "rule_results": [
                {
                    "rule_id": "SG_CONFLICT_REVIEW",
                    "reason_codes": [
                        "MATERIAL_CONFLICT_REQUIRES_SUPERVISORY_REVIEW",
                        "MATERIAL_CONFLICT_REQUIRES_SUPERVISORY_REVIEW",
                    ],
                    "required_actions": [
                        "SUPERVISORY_CONFLICT_REVIEW",
                        "REVIEW_CONFLICT_OF_INTEREST",
                    ],
                },
                {
                    "rule_id": "SG_DISCLOSURE_REVIEW",
                    "reason_codes": ["PRODUCT_DOCUMENTATION_INCOMPLETE"],
                    "required_actions": ["REVIEW_PRODUCT_DOCUMENT:NOTE_A"],
                },
            ]
        }
    )

    posture = conflict_posture_for_workflow(record=record, events=[])

    assert posture == {
        "status": "BLOCKED",
        "reason_codes": ["MATERIAL_CONFLICT_REQUIRES_SUPERVISORY_REVIEW"],
        "blockers": ["SUPERVISORY_CONFLICT_REVIEW", "REVIEW_CONFLICT_OF_INTEREST"],
        "review_outcome": None,
    }


def test_policy_workflow_conflict_projection_honours_resolution_event() -> None:
    record = SimpleNamespace(
        evaluation_json={
            "rule_results": [
                {
                    "rule_id": "SG_CONFLICT_REVIEW",
                    "reason_codes": ["MATERIAL_CONFLICT_REQUIRES_SUPERVISORY_REVIEW"],
                    "required_actions": ["SUPERVISORY_CONFLICT_REVIEW"],
                }
            ]
        }
    )
    events = [
        _audit_event_with_reason({"conflict_review_outcome": "MORE_EVIDENCE_REQUIRED"}),
        _audit_event_with_reason({"conflict_review_outcome": "NO_MATERIAL_CONFLICT_REMAINING"}),
    ]

    posture = conflict_posture_for_workflow(record=record, events=events)

    assert posture == {
        "status": "SATISFIED",
        "reason_codes": ["MATERIAL_CONFLICT_REQUIRES_SUPERVISORY_REVIEW"],
        "blockers": [],
        "review_outcome": "NO_MATERIAL_CONFLICT_REMAINING",
    }


def test_policy_workflow_projects_open_approval_disclosure_consent_and_sla_posture() -> None:
    record = _create_policy_evaluation()
    workflow = get_policy_evaluation_workflow(evaluation_id=record.evaluation_id)

    assert workflow.sign_off_status == "PENDING_REVIEW"
    assert workflow.client_ready_publication == "BLOCKED"
    assert workflow.approval_dependencies[0].requirement_id == (
        "REVIEW_DISCLOSURE:SG_STRUCTURED_NOTE"
    )
    assert workflow.approval_dependencies[0].owner_role == "INVESTMENT_COUNSELLOR"
    assert workflow.disclosure_requirements[0].status == "OPEN"
    assert workflow.consent_requirements[0].status == "OPEN"
    assert workflow.sla_posture["open_requirement_count"] == 5
    assert workflow.conflict_posture["status"] == "SATISFIED"
    assert workflow.metadata.product_id == ("lotus-advise:AdvisoryPolicyEvaluationRecord:v1")
    assert workflow.metadata.generated_at == record.generated_at
    assert workflow.metadata.as_of_date == "2026-05-26"
    assert workflow.metadata.content_hash == record.evaluation_hash
    assert workflow.metadata.freshness_state == "current"
    assert workflow.metadata.data_quality_status == "incomplete"
    assert workflow.metadata.source_gap_count == len(record.source_gaps)
    assert workflow.metadata.source_gaps == record.source_gaps
    assert workflow.metadata.scope_identity.authority_source == ("trusted_policy_control_principal")
    assert workflow.metadata.scope_identity.tenant_scope_hash.startswith("sha256:")
    assert workflow.metadata.scope_identity.legal_entity_code == "REFERENCE"
    assert workflow.metadata.scope_identity.booking_center_code == "SG"
    assert workflow.metadata.observed_correlation_id_hash.startswith("sha256:")
    assert workflow.metadata.observed_trace_id_hash.startswith("sha256:")
    assert workflow.replay_metadata.source_evidence_hash == record.source_evidence_hash
    assert workflow.replay_metadata.evaluation_hash == record.evaluation_hash
    assert workflow.replay_metadata.as_of_date == workflow.metadata.as_of_date
    assert workflow.replay_metadata.scope_identity == workflow.metadata.scope_identity
    assert (
        workflow.replay_metadata.observed_trace_id_hash == workflow.metadata.observed_trace_id_hash
    )


def test_policy_workflow_projects_legacy_records_without_receipt_identity() -> None:
    record = SimpleNamespace(
        evaluation_id="pev_legacy_policy",
        proposal_id="pp_legacy_policy",
        proposal_version_id="ppv_legacy_policy",
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        generated_at="2026-05-26T01:00:00+00:00",
        evaluation_status="PENDING_REVIEW",
        evaluation_hash="sha256:legacy-evaluation",
        source_evidence_hash="sha256:legacy-source",
        policy_content_hash="sha256:legacy-policy",
        source_refs=[],
        source_gaps=[],
        approval_dependencies=[],
        disclosure_requirements=[],
        consent_requirements=[],
        evaluation_json={"rule_results": []},
        replay_metadata_json={
            "as_of_date": "2026-05-26",
            "replay_policy": "PIN_POLICY_VERSION_AND_COMPARE_SOURCE_HASHES",
        },
    )

    workflow = build_policy_evaluation_workflow_projection(
        record=record,
        events=[],
        now=datetime(2026, 5, 26, 2, tzinfo=timezone.utc),
        client_ready_publication="READY",
    )

    assert workflow.metadata.as_of_date == "2026-05-26"
    assert workflow.metadata.scope_identity.legal_entity_code == "LEGACY_UNAVAILABLE"
    assert workflow.metadata.scope_identity.tenant_scope_hash.startswith("sha256:")
    assert workflow.replay_metadata.observed_trace_id_hash.startswith("sha256:")


def test_policy_sign_off_requires_maker_checker_and_all_requirements_resolved() -> None:
    record = _create_policy_evaluation()

    with pytest.raises(ProposalValidationError, match="MAKER_CHECKER"):
        record_policy_evaluation_sign_off_decision(
            evaluation_id=record.evaluation_id,
            payload=PolicyEvaluationSignOffDecisionRequest(
                actor_id="advisor_1",
                decision="APPROVE_FOR_POLICY_SIGN_OFF",
                source_evaluation_hash=record.evaluation_hash,
            ),
        )

    with pytest.raises(ProposalValidationError, match="REQUIREMENTS_OPEN"):
        record_policy_evaluation_sign_off_decision(
            evaluation_id=record.evaluation_id,
            payload=PolicyEvaluationSignOffDecisionRequest(
                actor_id="policy_checker_1",
                decision="APPROVE_FOR_POLICY_SIGN_OFF",
                source_evaluation_hash=record.evaluation_hash,
            ),
        )

    response = record_policy_evaluation_sign_off_decision(
        evaluation_id=record.evaluation_id,
        payload=PolicyEvaluationSignOffDecisionRequest(
            actor_id="policy_checker_1",
            decision="APPROVE_FOR_POLICY_SIGN_OFF",
            source_evaluation_hash=record.evaluation_hash,
            resolved_approval_dependencies=record.approval_dependencies,
            satisfied_disclosure_requirements=record.disclosure_requirements,
            satisfied_consent_requirements=record.consent_requirements,
            reason={"purpose": "all requirements reviewed"},
        ),
        idempotency_key="  policy-sign-off-decision-001  ",
    )

    assert response.workflow.sign_off_status == "SIGNED_OFF"
    assert response.workflow.sign_off_blockers == []
    assert response.sign_off_event.event_type == "POLICY_EVALUATION_SIGN_OFF_RECORDED"
    assert response.sign_off_event.idempotency_key == "policy-sign-off-decision-001"
    assert response.replay_metadata["client_ready_publication"] == "BLOCKED"


def test_policy_sign_off_rejection_does_not_satisfy_requirements() -> None:
    record = _create_policy_evaluation()

    response = record_policy_evaluation_sign_off_decision(
        evaluation_id=record.evaluation_id,
        payload=PolicyEvaluationSignOffDecisionRequest(
            actor_id="policy_checker_1",
            decision="REQUEST_MORE_EVIDENCE",
            source_evaluation_hash=record.evaluation_hash,
            resolved_approval_dependencies=record.approval_dependencies,
            satisfied_disclosure_requirements=record.disclosure_requirements,
            satisfied_consent_requirements=record.consent_requirements,
            reason={"purpose": "missing documented consent evidence"},
        ),
        idempotency_key="policy-sign-off-request-more-evidence-001",
    )

    assert response.sign_off_event.event_type == "POLICY_EVALUATION_REVIEW_RECORDED"
    assert response.workflow.sign_off_status == "PENDING_REVIEW"
    assert response.workflow.sla_posture["open_requirement_count"] == 5
    assert response.workflow.approval_dependencies[0].status == "OPEN"
    assert response.workflow.disclosure_requirements[0].status == "OPEN"
    assert response.workflow.consent_requirements[0].status == "OPEN"


def test_policy_sign_off_blocks_material_conflict_until_review_outcome_is_recorded() -> None:
    record = _create_policy_evaluation(material_conflict=True)
    workflow = get_policy_evaluation_workflow(evaluation_id=record.evaluation_id)

    assert workflow.conflict_posture["status"] == "BLOCKED"
    assert workflow.sign_off_status == "BLOCKED"

    with pytest.raises(ProposalValidationError, match="REQUIREMENTS_OPEN"):
        record_policy_evaluation_sign_off_decision(
            evaluation_id=record.evaluation_id,
            payload=PolicyEvaluationSignOffDecisionRequest(
                actor_id="policy_checker_1",
                decision="APPROVE_FOR_POLICY_SIGN_OFF",
                source_evaluation_hash=record.evaluation_hash,
                conflict_review_outcome="NO_MATERIAL_CONFLICT_REMAINING",
            ),
        )
