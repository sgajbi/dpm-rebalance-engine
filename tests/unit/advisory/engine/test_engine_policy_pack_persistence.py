from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.core.common.canonical import hash_canonical_payload
from src.core.policy_packs import (
    DurablePolicyEvaluationRepository,
    InMemoryPolicyEvaluationStateStore,
    PolicyPackCatalogStore,
    activate_policy_pack_version,
    append_policy_evaluation_event,
    configure_policy_evaluation_repository,
    configure_policy_pack_catalog_repository,
    finalize_policy_evaluation_record,
    get_policy_evaluation_record,
    get_policy_pack_version,
    list_policy_evaluation_events,
    list_policy_evaluation_records,
    replay_policy_evaluation_record,
    reset_policy_evaluation_store_for_tests,
    reset_policy_pack_catalog_for_tests,
    validate_policy_pack_version,
)
from src.core.policy_packs.catalog_reference_packs import reference_policy_packs
from src.core.policy_packs.receipt_identity import build_policy_evaluation_receipt_identity
from src.core.proposals.exceptions import ProposalIdempotencyConflictError, ProposalValidationError

SOURCE_ROOT = Path(__file__).resolve().parents[4] / "src" / "core" / "policy_packs"


def setup_function() -> None:
    reset_policy_pack_catalog_for_tests()
    reset_policy_evaluation_store_for_tests()


def test_policy_evaluation_persistence_record_builder_stays_focused() -> None:
    persistence = (SOURCE_ROOT / "persistence.py").read_text(encoding="utf-8")
    store = (SOURCE_ROOT / "persistence_store.py").read_text(encoding="utf-8")
    record_builder = (SOURCE_ROOT / "persistence_record_builder.py").read_text(encoding="utf-8")

    assert "build_policy_evaluation_record" not in persistence
    assert "build_policy_evaluation_record" in store
    assert "policy_evaluation_hash" not in persistence
    assert "def _portfolio_id" not in persistence
    assert "def _approval_dependencies" not in persistence
    assert "def _disclosure_requirements" not in persistence
    assert "def _consent_requirements" not in persistence

    assert "def build_policy_evaluation_record" in record_builder
    assert "def policy_evaluation_hash" in record_builder
    assert "def _portfolio_id" in record_builder
    assert "def _approval_dependencies" in record_builder


def test_policy_evaluation_persistence_projection_stays_focused() -> None:
    persistence = (SOURCE_ROOT / "persistence.py").read_text(encoding="utf-8")
    store = (SOURCE_ROOT / "persistence_store.py").read_text(encoding="utf-8")
    projection = (SOURCE_ROOT / "persistence_projection.py").read_text(encoding="utf-8")

    assert "from src.core.policy_packs.persistence_projection import" not in persistence
    assert "from src.core.policy_packs.persistence_projection import" in store
    for helper_name in (
        "attach_policy_evaluation_event",
        "build_policy_evaluation_lineage_response",
        "policy_evaluation_api_posture",
    ):
        assert f"def {helper_name}(" not in persistence
        assert f"def {helper_name}(" in projection

    assert "PolicyEvaluationLineageResponse(" not in persistence
    assert "PolicyEvaluationLineageResponse(" in projection
    assert "policy_runtime_supportability" not in persistence
    assert "policy_runtime_supportability" in projection


def test_policy_evaluation_persistence_replay_stays_focused() -> None:
    persistence = (SOURCE_ROOT / "persistence.py").read_text(encoding="utf-8")
    store = (SOURCE_ROOT / "persistence_store.py").read_text(encoding="utf-8")
    replay = (SOURCE_ROOT / "persistence_replay.py").read_text(encoding="utf-8")

    assert "from src.core.policy_packs.persistence_replay import" not in persistence
    assert "from src.core.policy_packs.persistence_replay import" in store
    assert "def build_policy_evaluation_replay_response(" not in persistence
    assert "def build_policy_evaluation_replay_response(" in replay
    assert "policy_evaluation_hash" not in persistence
    assert "policy_evaluation_hash" in replay
    assert "evaluate_policy_pack_version" not in persistence
    assert "evaluate_policy_pack_version" in store
    assert "evaluate_policy_pack_version" in replay
    assert "PolicyEvaluationReplayResponse(" not in persistence
    assert "PolicyEvaluationReplayResponse(" in replay


def test_policy_evaluation_persistence_store_stays_focused() -> None:
    persistence = (SOURCE_ROOT / "persistence.py").read_text(encoding="utf-8")
    store = (SOURCE_ROOT / "persistence_store.py").read_text(encoding="utf-8")

    assert "from src.core.policy_packs.persistence_store import PolicyEvaluationRecordStore" in (
        persistence
    )
    assert "class PolicyEvaluationRecordStore" not in persistence
    assert "class PolicyEvaluationRecordStore" in store
    assert "def _find_replayed_event(" not in persistence
    assert "def _find_replayed_event(" in store
    assert "POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT" not in persistence
    assert "POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT" in store


def _base_evidence_bundle() -> dict:
    return {
        "context_resolution": {
            "as_of_date": "2026-05-26",
            "advisory_policy_context": {
                "household_id": "HH-PB-001",
                "jurisdiction": "SG",
                "client_classification": "ACCREDITED_INVESTOR",
                "booking_center_code": "SG",
                "legal_entity_code": "REFERENCE",
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
                    "instrument_id": "US_EQ_ETF",
                    "eligibility": {"jurisdictions": ["SG"]},
                    "target_market": {"client_segments": ["ACCREDITED_INVESTOR"]},
                    "complexity": "NON_COMPLEX",
                    "private_asset": False,
                    "structured_product": False,
                }
            ],
            "proposed_trades": [{"instrument_id": "US_EQ_ETF", "side": "BUY"}],
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
                "product_docs": [{"instrument_id": "US_EQ_ETF", "doc_ref": "Factsheet"}],
            },
        },
        "conflict_evidence": {"material_conflict": False, "review_ref": "conflict-review-001"},
    }


def _trusted_reason(
    purpose: str,
    *,
    correlation_id: str = "corr-policy-evaluation-test",
    trace_id: str = "trace-policy-evaluation-test",
) -> dict[str, Any]:
    return {
        "purpose": purpose,
        "trusted_principal": {
            "subject": "advisor_1",
            "role": "ADVISOR",
            "tenant_id": "tenant_sg_001",
            "legal_entity_code": "REFERENCE",
            "correlation_id": correlation_id,
            "trace_id": trace_id,
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
        idempotency_key="validate-sg-for-persistence",
        reason={"purpose": "slice 7 persistence test"},
    )
    activate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        activated_by="policy_checker_1",
        source_content_hash=detail.policy_pack.content_hash,
        idempotency_key="activate-sg-for-persistence",
        reason={"purpose": "slice 7 persistence test"},
    )


def _sg_structured_note_evidence() -> dict[str, Any]:
    evidence = _base_evidence_bundle()
    evidence["inputs"]["shelf_entries"][0]["instrument_id"] = "SG_STRUCTURED_NOTE"
    evidence["inputs"]["shelf_entries"][0]["complexity"] = "COMPLEX"
    evidence["inputs"]["shelf_entries"][0]["structured_product"] = True
    evidence["inputs"]["proposed_trades"][0]["instrument_id"] = "SG_STRUCTURED_NOTE"
    evidence["artifact"]["disclosures"]["product_docs"] = [
        {"instrument_id": "SG_STRUCTURED_NOTE", "doc_ref": "Term sheet"}
    ]
    return evidence


def _without_policy_legal_entity(evidence: dict[str, Any]) -> dict[str, Any]:
    missing = deepcopy(evidence)
    missing["context_resolution"]["advisory_policy_context"].pop("legal_entity_code")
    return missing


def _trusted_legal_entity_repair_reason(purpose: str) -> dict[str, Any]:
    reason = _trusted_reason(purpose)
    reason["system_repair_intent"] = {
        "repair_code": "POLICY_EVALUATION_TRUSTED_LEGAL_ENTITY_BINDING_REPAIR",
        "source_gap": "legal_entity_code",
        "authority_source": "trusted_policy_control_principal",
    }
    return reason


def _two_version_global_policy_pack_definitions() -> list[dict[str, Any]]:
    definitions = [
        definition
        for definition in reference_policy_packs()
        if definition["policy_pack_id"] == "GLOBAL_PRIVATE_BANKING_BASELINE"
    ]
    old_definition = definitions[0]
    old_definition["activation_state"] = "ACTIVE"
    old_definition["maker_checker_required"] = True
    new_definition = {
        **old_definition,
        "policy_version": "2026.06",
        "activation_state": "DRAFT",
        "effective_from": "2026-06-01",
    }
    return [old_definition, new_definition]


def test_policy_evaluation_record_is_immutable_hash_backed_and_idempotent() -> None:
    created = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_persist_001",
        proposal_version_id="ppv_policy_persist_001",
        created_by="advisor_1",
        idempotency_key="  policy-eval-finalize-001  ",
        reason=_trusted_reason("advisor policy review"),
    )
    replayed = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_persist_001",
        proposal_version_id="ppv_policy_persist_001",
        created_by="advisor_1",
        idempotency_key="policy-eval-finalize-001",
        reason=_trusted_reason(
            "advisor policy review",
            correlation_id="corr-policy-evaluation-test-retry",
            trace_id="trace-policy-evaluation-test-retry",
        ),
    )
    duplicate_identity = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_persist_001",
        proposal_version_id="ppv_policy_persist_001",
        created_by="advisor_1",
        idempotency_key="policy-eval-finalize-duplicate-identity",
        reason=_trusted_reason("advisor policy review"),
    )

    assert created.created is True
    assert created.replayed is False
    assert created.audit_event is not None
    assert created.audit_event.event_type == "POLICY_EVALUATION_FINALIZED"
    assert created.audit_event.idempotency_key == "policy-eval-finalize-001"
    assert created.record.replay_metadata_json["idempotency_key"] == "policy-eval-finalize-001"
    assert created.record.evaluation_hash.startswith("sha256:")
    assert (
        created.record.policy_content_hash
        == created.record.evaluation_json["policy_pack"]["content_hash"]
    )
    assert created.record.rule_result_hashes
    assert created.record.replay_metadata_json["replay_policy"] == (
        "PIN_POLICY_VERSION_AND_COMPARE_SOURCE_HASHES"
    )
    receipt_identity = created.record.replay_metadata_json["receipt_identity"]
    assert created.record.replay_metadata_json["as_of_date"] == "2026-05-26"
    assert receipt_identity["receipt_contract_version"] == (
        "rfc0002.policy-evaluation-receipt-identity.v1"
    )
    assert receipt_identity["as_of_date"] == "2026-05-26"
    assert receipt_identity["scope_identity"]["authority_source"] == (
        "trusted_policy_control_principal"
    )
    assert receipt_identity["scope_identity"]["tenant_scope_hash"].startswith("sha256:")
    assert receipt_identity["scope_identity"]["legal_entity_code"] == "REFERENCE"
    assert receipt_identity["scope_identity"]["booking_center_code"] == "SG"
    assert receipt_identity["observed_correlation_id_hash"].startswith("sha256:")
    assert receipt_identity["observed_trace_id_hash"].startswith("sha256:")
    assert receipt_identity["trace_identity_source"] == "trusted_policy_control_principal"
    assert (
        "subject" not in created.record.replay_metadata_json["creation_reason"]["trusted_principal"]
    )
    assert (
        "tenant_id"
        not in created.record.replay_metadata_json["creation_reason"]["trusted_principal"]
    )
    assert (
        "correlation_id"
        not in created.record.replay_metadata_json["creation_reason"]["trusted_principal"]
    )
    assert (
        "trace_id"
        not in created.record.replay_metadata_json["creation_reason"]["trusted_principal"]
    )
    assert (
        "service_identity"
        not in created.record.replay_metadata_json["creation_reason"]["trusted_principal"]
    )
    assert created.record.evaluation_json["supportability"]["policy_evaluation_persistence"] == (
        "SUPPORTED_BY_RFC0025_SLICE7_INTERNAL"
    )
    assert (
        created.record.evaluation_json["applicability"]["matched_selectors"]["legal_entity_code"]
        == "REFERENCE"
    )
    assert (
        created.record.evaluation_json["applicability"]["matched_selectors"]["product_scope"]
        == "MULTI_ASSET"
    )
    assert replayed.replayed is True
    assert replayed.record.evaluation_id == created.record.evaluation_id
    assert duplicate_identity.created is False
    assert duplicate_identity.record.evaluation_id == created.record.evaluation_id
    assert (
        replayed.record.replay_metadata_json["receipt_identity"]
        == created.record.replay_metadata_json["receipt_identity"]
    )


def test_policy_evaluation_repository_port_survives_reinstantiation() -> None:
    state_store = InMemoryPolicyEvaluationStateStore()
    configure_policy_evaluation_repository(
        DurablePolicyEvaluationRepository(state_store=state_store)
    )
    created = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_restart",
        proposal_version_id="ppv_policy_restart",
        created_by="advisor_1",
        idempotency_key="policy-eval-restart",
        reason=_trusted_reason("restart proof"),
    )
    review = append_policy_evaluation_event(
        evaluation_id=created.record.evaluation_id,
        event_type="POLICY_EVALUATION_REVIEW_RECORDED",
        actor_id="compliance_1",
        idempotency_key="policy-eval-restart-review",
        reason={"review_action": "REQUEST_MORE_EVIDENCE"},
    )

    configure_policy_evaluation_repository(
        DurablePolicyEvaluationRepository(state_store=state_store)
    )
    reloaded = get_policy_evaluation_record(evaluation_id=created.record.evaluation_id)
    events = list_policy_evaluation_events(evaluation_id=created.record.evaluation_id)
    replayed_review = append_policy_evaluation_event(
        evaluation_id=created.record.evaluation_id,
        event_type="POLICY_EVALUATION_REVIEW_RECORDED",
        actor_id="compliance_1",
        idempotency_key="policy-eval-restart-review",
        reason={"review_action": "REQUEST_MORE_EVIDENCE"},
    )

    assert reloaded.evaluation_id == created.record.evaluation_id
    assert reloaded.evaluation_hash == created.record.evaluation_hash
    assert [event.event_id for event in events] == ["peev_000001", review.event_id]
    assert replayed_review.event_id == review.event_id


def test_policy_evaluation_idempotency_rejects_payload_drift() -> None:
    finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_conflict",
        proposal_version_id="ppv_policy_conflict",
        created_by="advisor_1",
        idempotency_key="policy-eval-conflict",
        reason=_trusted_reason("first request"),
    )

    with pytest.raises(ProposalIdempotencyConflictError):
        finalize_policy_evaluation_record(
            evidence_bundle=_base_evidence_bundle(),
            policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
            policy_version="2026.05",
            proposal_id="pp_policy_conflict",
            proposal_version_id="ppv_policy_conflict",
            created_by="advisor_1",
            idempotency_key="policy-eval-conflict",
            reason=_trusted_reason("changed request"),
        )


def test_policy_evaluation_idempotency_repairs_trusted_legal_entity_gap_once() -> None:
    _activate_sg_policy_pack()
    state_store = InMemoryPolicyEvaluationStateStore()
    configure_policy_evaluation_repository(
        DurablePolicyEvaluationRepository(state_store=state_store)
    )
    repaired_evidence = _sg_structured_note_evidence()
    pre_fix_evidence = _without_policy_legal_entity(repaired_evidence)
    reason = _trusted_reason("trusted legal entity repair proof")

    blocked = finalize_policy_evaluation_record(
        evidence_bundle=pre_fix_evidence,
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        proposal_id="pp_policy_legal_repair",
        proposal_version_id="ppv_policy_legal_repair",
        created_by="advisor_1",
        idempotency_key="policy-eval-legal-repair",
        reason=reason,
    )
    repaired = finalize_policy_evaluation_record(
        evidence_bundle=repaired_evidence,
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        proposal_id="pp_policy_legal_repair",
        proposal_version_id="ppv_policy_legal_repair",
        created_by="advisor_1",
        idempotency_key="policy-eval-legal-repair",
        reason=_trusted_legal_entity_repair_reason("trusted legal entity repair proof"),
    )
    replayed_repaired = finalize_policy_evaluation_record(
        evidence_bundle=repaired_evidence,
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        proposal_id="pp_policy_legal_repair",
        proposal_version_id="ppv_policy_legal_repair",
        created_by="advisor_1",
        idempotency_key="policy-eval-legal-repair",
        reason=_trusted_legal_entity_repair_reason("trusted legal entity repair proof"),
    )
    records = list_policy_evaluation_records()

    assert blocked.record.evaluation_status == "BLOCKED"
    assert "legal_entity_code" in blocked.record.source_gaps
    assert repaired.created is True
    assert repaired.replayed is False
    assert repaired.record.evaluation_status == "PENDING_REVIEW"
    assert "legal_entity_code" not in repaired.record.source_gaps
    assert repaired.record.evaluation_id != blocked.record.evaluation_id
    assert replayed_repaired.replayed is True
    assert replayed_repaired.record.evaluation_id == repaired.record.evaluation_id
    assert [record.evaluation_id for record in records] == [
        blocked.record.evaluation_id,
        repaired.record.evaluation_id,
    ]
    assert (
        blocked.record.replay_metadata_json["creation_reason"]
        == repaired.record.replay_metadata_json["creation_reason"]
    )
    assert "system_repair_intent" not in repaired.record.replay_metadata_json["creation_reason"]


def test_policy_evaluation_idempotency_replays_legacy_correlation_sensitive_hash() -> None:
    state_store = InMemoryPolicyEvaluationStateStore()
    configure_policy_evaluation_repository(
        DurablePolicyEvaluationRepository(state_store=state_store)
    )
    original_reason = _trusted_reason(
        "legacy correlation replay proof",
        correlation_id="corr-policy-evaluation-legacy",
        trace_id="trace-policy-evaluation-legacy",
    )
    created = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_legacy_corr",
        proposal_version_id="ppv_policy_legacy_corr",
        created_by="advisor_1",
        idempotency_key="policy-eval-legacy-correlation",
        reason=original_reason,
    )
    legacy_reason = dict(original_reason)
    legacy_reason["trusted_principal"] = {
        key: value
        for key, value in original_reason["trusted_principal"].items()
        if key != "trace_id"
    }
    legacy_hash = hash_canonical_payload(
        {
            "operation": "POLICY_EVALUATION_FINALIZED",
            "proposal_id": created.record.proposal_id,
            "proposal_version_id": created.record.proposal_version_id,
            "policy_pack_id": created.record.policy_pack_id,
            "policy_version": created.record.policy_version,
            "source_evidence_hash": created.record.source_evidence_hash,
            "reason": legacy_reason,
        }
    )
    snapshot = state_store.load_snapshot()
    snapshot["idempotency"][0]["request_hash"] = legacy_hash
    state_store.save_snapshot(snapshot)

    replayed = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_legacy_corr",
        proposal_version_id="ppv_policy_legacy_corr",
        created_by="advisor_1",
        idempotency_key="policy-eval-legacy-correlation",
        reason=_trusted_reason(
            "legacy correlation replay proof",
            correlation_id="corr-policy-evaluation-new",
            trace_id="trace-policy-evaluation-new",
        ),
    )

    assert replayed.replayed is True
    assert replayed.record.evaluation_id == created.record.evaluation_id


def test_policy_evaluation_idempotency_repair_requires_server_repair_intent() -> None:
    _activate_sg_policy_pack()
    repaired_evidence = _sg_structured_note_evidence()
    pre_fix_evidence = _without_policy_legal_entity(repaired_evidence)

    finalize_policy_evaluation_record(
        evidence_bundle=pre_fix_evidence,
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        proposal_id="pp_policy_legal_repair_no_intent",
        proposal_version_id="ppv_policy_legal_repair_no_intent",
        created_by="advisor_1",
        idempotency_key="policy-eval-legal-repair-no-intent",
        reason=_trusted_reason("trusted legal entity repair proof"),
    )

    with pytest.raises(
        ProposalIdempotencyConflictError,
        match="POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT",
    ):
        finalize_policy_evaluation_record(
            evidence_bundle=repaired_evidence,
            policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
            policy_version="2026.05",
            proposal_id="pp_policy_legal_repair_no_intent",
            proposal_version_id="ppv_policy_legal_repair_no_intent",
            created_by="advisor_1",
            idempotency_key="policy-eval-legal-repair-no-intent",
            reason=_trusted_reason("trusted legal entity repair proof"),
        )


def test_policy_evaluation_idempotency_repair_rejects_business_reason_drift() -> None:
    _activate_sg_policy_pack()
    repaired_evidence = _sg_structured_note_evidence()
    pre_fix_evidence = _without_policy_legal_entity(repaired_evidence)

    finalize_policy_evaluation_record(
        evidence_bundle=pre_fix_evidence,
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        proposal_id="pp_policy_legal_repair_reason_drift",
        proposal_version_id="ppv_policy_legal_repair_reason_drift",
        created_by="advisor_1",
        idempotency_key="policy-eval-legal-repair-reason-drift",
        reason=_trusted_reason("trusted legal entity repair proof"),
    )

    with pytest.raises(
        ProposalIdempotencyConflictError,
        match="POLICY_EVALUATION_IDEMPOTENCY_KEY_CONFLICT",
    ):
        finalize_policy_evaluation_record(
            evidence_bundle=repaired_evidence,
            policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
            policy_version="2026.05",
            proposal_id="pp_policy_legal_repair_reason_drift",
            proposal_version_id="ppv_policy_legal_repair_reason_drift",
            created_by="advisor_1",
            idempotency_key="policy-eval-legal-repair-reason-drift",
            reason=_trusted_legal_entity_repair_reason("changed repair proof"),
        )


def test_policy_evaluation_receipt_identity_fails_closed_without_trusted_principal() -> None:
    with pytest.raises(ProposalValidationError, match="TRUSTED_PRINCIPAL_REQUIRED"):
        finalize_policy_evaluation_record(
            evidence_bundle=_base_evidence_bundle(),
            policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
            policy_version="2026.05",
            proposal_id="pp_policy_no_principal",
            proposal_version_id="ppv_policy_no_principal",
            created_by="advisor_1",
            idempotency_key="policy-eval-no-principal",
            reason={"purpose": "missing principal"},
        )


def test_policy_evaluation_receipt_identity_fails_closed_without_trace() -> None:
    reason = _trusted_reason("missing trace")
    reason["trusted_principal"].pop("trace_id")

    with pytest.raises(ProposalValidationError, match="OBSERVED_TRACE_ID_REQUIRED"):
        finalize_policy_evaluation_record(
            evidence_bundle=_base_evidence_bundle(),
            policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
            policy_version="2026.05",
            proposal_id="pp_policy_no_trace",
            proposal_version_id="ppv_policy_no_trace",
            created_by="advisor_1",
            idempotency_key="policy-eval-no-trace",
            reason=reason,
        )


def test_policy_evaluation_receipt_identity_fails_closed_without_source_as_of() -> None:
    evidence = _base_evidence_bundle()
    evidence["context_resolution"].pop("as_of_date")
    evidence["inputs"]["portfolio_snapshot"].pop("as_of_date")
    evidence["inputs"]["market_data_snapshot"].pop("as_of_date")

    with pytest.raises(ProposalValidationError, match="SOURCE_AS_OF_DATE_REQUIRED"):
        finalize_policy_evaluation_record(
            evidence_bundle=evidence,
            policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
            policy_version="2026.05",
            proposal_id="pp_policy_no_as_of",
            proposal_version_id="ppv_policy_no_as_of",
            created_by="advisor_1",
            idempotency_key="policy-eval-no-as-of",
            reason=_trusted_reason("missing source as-of"),
        )


def test_policy_evaluation_receipt_identity_reads_canonical_resolved_context_as_of() -> None:
    evidence = _base_evidence_bundle()
    evidence["context_resolution"].pop("as_of_date")
    evidence["context_resolution"]["resolved_context"] = {"as_of": "2026-05-26"}
    evidence["inputs"]["portfolio_snapshot"].pop("as_of_date")
    evidence["inputs"]["market_data_snapshot"].pop("as_of_date")

    receipt_identity = build_policy_evaluation_receipt_identity(
        evidence_bundle=evidence,
        proposal_id="pp_policy_canonical_as_of",
        proposal_version_id="ppv_policy_canonical_as_of",
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        reason=_trusted_reason("canonical resolved context as-of"),
        observed_trace_id="trace-observed-canonical-as-of",
        observed_at=datetime(2026, 5, 26, 1, tzinfo=UTC),
    )

    assert receipt_identity.as_of_date == "2026-05-26"
    assert receipt_identity.trace_identity_source == "advise_observability_context"


def test_policy_evaluation_receipt_identity_preserves_source_local_timestamp_date() -> None:
    evidence = _base_evidence_bundle()
    evidence["context_resolution"]["as_of_date"] = "2026-05-26T00:30:00+08:00"
    evidence["inputs"]["portfolio_snapshot"].pop("as_of_date")
    evidence["inputs"]["market_data_snapshot"].pop("as_of_date")

    receipt_identity = build_policy_evaluation_receipt_identity(
        evidence_bundle=evidence,
        proposal_id="pp_policy_source_local_date",
        proposal_version_id="ppv_policy_source_local_date",
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        reason=_trusted_reason("source local timestamp"),
        observed_trace_id="trace-observed-source-local",
        observed_at=datetime(2026, 5, 25, 17, tzinfo=UTC),
    )

    assert receipt_identity.as_of_date == "2026-05-26"


def test_policy_evaluation_receipt_identity_allows_booking_center_local_today() -> None:
    evidence = _base_evidence_bundle()
    evidence["context_resolution"]["as_of_date"] = "2026-07-29"
    evidence["inputs"]["portfolio_snapshot"]["as_of_date"] = "2026-07-29"
    evidence["inputs"]["market_data_snapshot"]["as_of_date"] = "2026-07-29"

    receipt_identity = build_policy_evaluation_receipt_identity(
        evidence_bundle=evidence,
        proposal_id="pp_policy_booking_center_today",
        proposal_version_id="ppv_policy_booking_center_today",
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        reason=_trusted_reason("booking center local business date"),
        observed_trace_id="trace-observed-booking-center",
        observed_at=datetime(2026, 7, 28, 16, 30, tzinfo=UTC),
    )

    assert receipt_identity.as_of_date == "2026-07-29"


def test_policy_evaluation_receipt_identity_rejects_source_as_of_drift() -> None:
    evidence = _base_evidence_bundle()
    evidence["inputs"]["market_data_snapshot"]["as_of_date"] = "2026-05-27"

    with pytest.raises(ProposalValidationError, match="SOURCE_AS_OF_DATE_MISMATCH"):
        finalize_policy_evaluation_record(
            evidence_bundle=evidence,
            policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
            policy_version="2026.05",
            proposal_id="pp_policy_as_of_mismatch",
            proposal_version_id="ppv_policy_as_of_mismatch",
            created_by="advisor_1",
            idempotency_key="policy-eval-as-of-mismatch",
            reason=_trusted_reason("mismatched source as-of"),
        )


def test_policy_evaluation_receipt_identity_rejects_naive_source_datetime() -> None:
    evidence = _base_evidence_bundle()
    evidence["context_resolution"]["as_of_date"] = "2026-05-26T00:00:00"
    evidence["inputs"]["portfolio_snapshot"].pop("as_of_date")
    evidence["inputs"]["market_data_snapshot"].pop("as_of_date")

    with pytest.raises(ProposalValidationError, match="SOURCE_AS_OF_DATE_TIMEZONE_REQUIRED"):
        finalize_policy_evaluation_record(
            evidence_bundle=evidence,
            policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
            policy_version="2026.05",
            proposal_id="pp_policy_naive_as_of",
            proposal_version_id="ppv_policy_naive_as_of",
            created_by="advisor_1",
            idempotency_key="policy-eval-naive-as-of",
            reason=_trusted_reason("naive source as-of"),
        )


def test_policy_evaluation_receipt_identity_rejects_future_source_as_of() -> None:
    evidence = _base_evidence_bundle()
    evidence["context_resolution"]["as_of_date"] = "2999-01-01"
    evidence["inputs"]["portfolio_snapshot"]["as_of_date"] = "2999-01-01"
    evidence["inputs"]["market_data_snapshot"]["as_of_date"] = "2999-01-01"

    with pytest.raises(ProposalValidationError, match="SOURCE_AS_OF_DATE_IN_FUTURE"):
        finalize_policy_evaluation_record(
            evidence_bundle=evidence,
            policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
            policy_version="2026.05",
            proposal_id="pp_policy_future_as_of",
            proposal_version_id="ppv_policy_future_as_of",
            created_by="advisor_1",
            idempotency_key="policy-eval-future-as-of",
            reason=_trusted_reason("future source as-of"),
        )


def test_policy_evaluation_review_events_are_append_only_without_mutating_final_hash() -> None:
    persisted = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_events",
        proposal_version_id="ppv_policy_events",
        created_by="advisor_1",
        idempotency_key="policy-eval-events",
        reason=_trusted_reason("event audit test"),
    )
    immutable_hash = persisted.record.evaluation_hash

    review = append_policy_evaluation_event(
        evaluation_id=persisted.record.evaluation_id,
        event_type="POLICY_EVALUATION_REVIEW_RECORDED",
        actor_id="compliance_1",
        idempotency_key="  policy-eval-review-event  ",
        reason={"review_action": "REQUEST_MORE_EVIDENCE"},
    )
    review_replay = append_policy_evaluation_event(
        evaluation_id=persisted.record.evaluation_id,
        event_type="POLICY_EVALUATION_REVIEW_RECORDED",
        actor_id="compliance_1",
        idempotency_key="policy-eval-review-event",
        reason={"review_action": "REQUEST_MORE_EVIDENCE"},
    )
    stored = get_policy_evaluation_record(evaluation_id=persisted.record.evaluation_id)

    assert review.event_id == "peev_000002"
    assert review_replay.event_id == review.event_id
    assert stored.evaluation_hash == immutable_hash
    assert len(stored.review_events_json) == 1
    assert stored.sign_off_events_json == []
    assert stored.report_archive_refs_json == []


def test_policy_evaluation_event_idempotency_ignores_volatile_nested_trusted_principal() -> None:
    persisted = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_event_stable_reason",
        proposal_version_id="ppv_policy_event_stable_reason",
        created_by="advisor_1",
        idempotency_key="policy-eval-event-stable-reason",
        reason=_trusted_reason("event stable reason"),
    )
    event_reason = {
        "review_action": "REQUEST_MORE_EVIDENCE",
        "reason": _trusted_reason(
            "policy support action",
            correlation_id="corr-policy-support-action-1",
            trace_id="trace-policy-support-action-1",
        ),
    }

    review = append_policy_evaluation_event(
        evaluation_id=persisted.record.evaluation_id,
        event_type="POLICY_EVALUATION_REVIEW_RECORDED",
        actor_id="compliance_1",
        idempotency_key="policy-eval-review-event-stable-reason",
        reason=event_reason,
    )
    review_replay = append_policy_evaluation_event(
        evaluation_id=persisted.record.evaluation_id,
        event_type="POLICY_EVALUATION_REVIEW_RECORDED",
        actor_id="compliance_1",
        idempotency_key="policy-eval-review-event-stable-reason",
        reason={
            **event_reason,
            "reason": _trusted_reason(
                "policy support action",
                correlation_id="corr-policy-support-action-2",
                trace_id="trace-policy-support-action-2",
            ),
        },
    )

    assert review_replay.event_id == review.event_id
    with pytest.raises(ProposalIdempotencyConflictError, match="POLICY_EVALUATION"):
        append_policy_evaluation_event(
            evaluation_id=persisted.record.evaluation_id,
            event_type="POLICY_EVALUATION_REVIEW_RECORDED",
            actor_id="compliance_1",
            idempotency_key="policy-eval-review-event-stable-reason",
            reason={
                **event_reason,
                "review_action": "DIFFERENT_BUSINESS_DECISION",
                "reason": _trusted_reason(
                    "policy support action",
                    correlation_id="corr-policy-support-action-3",
                    trace_id="trace-policy-support-action-3",
                ),
            },
        )


def test_policy_evaluation_event_idempotency_replays_legacy_volatile_event_hash() -> None:
    state_store = InMemoryPolicyEvaluationStateStore()
    configure_policy_evaluation_repository(
        DurablePolicyEvaluationRepository(state_store=state_store)
    )
    persisted = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_legacy_event_hash",
        proposal_version_id="ppv_policy_legacy_event_hash",
        created_by="advisor_1",
        idempotency_key="policy-eval-legacy-event-hash",
        reason=_trusted_reason("legacy event hash"),
    )
    legacy_reason = {
        "review_action": "REQUEST_MORE_EVIDENCE",
        "reason": _trusted_reason(
            "policy support action legacy hash",
            correlation_id="corr-policy-support-action-legacy",
            trace_id="trace-policy-support-action-legacy",
        ),
    }
    review = append_policy_evaluation_event(
        evaluation_id=persisted.record.evaluation_id,
        event_type="POLICY_EVALUATION_REVIEW_RECORDED",
        actor_id="compliance_1",
        idempotency_key="policy-eval-review-event-legacy-hash",
        reason=legacy_reason,
    )
    legacy_hash = hash_canonical_payload(
        {
            "operation": "POLICY_EVALUATION_REVIEW_RECORDED",
            "evaluation_id": persisted.record.evaluation_id,
            "actor_id": "compliance_1",
            "reason": legacy_reason,
            "evaluation_hash": persisted.record.evaluation_hash,
        }
    )
    snapshot = state_store.load_snapshot()
    for item in snapshot["idempotency"]:
        if item["idempotency_key"] == "policy-eval-review-event-legacy-hash":
            item["request_hash"] = legacy_hash
            break
    else:
        raise AssertionError("legacy event idempotency row was not persisted")
    for event in snapshot["events"][persisted.record.evaluation_id]:
        if event["event_id"] == review.event_id:
            event["reason_json"]["idempotency_request_hash"] = legacy_hash
            break
    for event in snapshot["records"][persisted.record.evaluation_id]["review_events_json"]:
        if event["event_id"] == review.event_id:
            event["reason_json"]["idempotency_request_hash"] = legacy_hash
            break
    state_store.save_snapshot(snapshot)

    replayed = append_policy_evaluation_event(
        evaluation_id=persisted.record.evaluation_id,
        event_type="POLICY_EVALUATION_REVIEW_RECORDED",
        actor_id="compliance_1",
        idempotency_key="policy-eval-review-event-legacy-hash",
        reason={
            **legacy_reason,
            "reason": _trusted_reason(
                "policy support action legacy hash",
                correlation_id="corr-policy-support-action-new",
                trace_id="trace-policy-support-action-new",
            ),
        },
    )
    stored_events = list_policy_evaluation_events(evaluation_id=persisted.record.evaluation_id)

    assert replayed.event_id == review.event_id
    assert len(stored_events) == 2


def test_policy_evaluation_privileged_events_require_specialized_command_authority() -> None:
    persisted = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_privileged_events",
        proposal_version_id="ppv_policy_privileged_events",
        created_by="advisor_1",
        idempotency_key="policy-eval-privileged-events",
        reason=_trusted_reason("event authority test"),
    )

    privileged_events = [
        (
            "POLICY_EVALUATION_FINALIZED",
            {"evaluation_status": "PENDING_REVIEW"},
            "POLICY_EVALUATION_FINALIZED_EVENT_REQUIRES_FINALIZE_COMMAND",
        ),
        (
            "POLICY_EVALUATION_SIGN_OFF_RECORDED",
            {
                "workflow_contract_version": "rfc0025.policy-workflow.v1",
                "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
                "source_evaluation_hash": persisted.record.evaluation_hash,
                "client_ready_publication": "BLOCKED",
            },
            "POLICY_EVALUATION_PRIVILEGED_EVENT_REQUIRES_COMMAND",
        ),
        (
            "POLICY_EVALUATION_REPORT_ARCHIVE_RECORDED",
            {
                "policy_report_package_contract_version": (
                    "rfc0025.policy-report-package-realization.v1"
                ),
                "policy_report_package_request_hash": "sha256:request",
                "report_package_status": "RECORDED",
                "source_evaluation_hash": persisted.record.evaluation_hash,
                "report_request_id": "rreq_001",
                "policy_sign_off_package": {},
                "client_ready_publication": "BLOCKED",
            },
            "POLICY_EVALUATION_PRIVILEGED_EVENT_REQUIRES_COMMAND",
        ),
        (
            "POLICY_EVALUATION_AI_EVIDENCE_RECORDED",
            {
                "policy_ai_contract_version": "rfc0025.policy-ai-evidence-boundary.v1",
                "policy_ai_request_hash": "sha256:request",
                "ai_status": "REVIEW_REQUIRED",
                "source_evaluation_hash": persisted.record.evaluation_hash,
                "requested_actions": ["SUMMARIZE_POLICY_POSTURE"],
                "human_review_required": True,
                "authoritative_for_policy_status": False,
                "client_ready_publication": "BLOCKED",
                "lineage": {},
            },
            "POLICY_EVALUATION_PRIVILEGED_EVENT_REQUIRES_COMMAND",
        ),
    ]
    for event_type, reason, expected_error in privileged_events:
        with pytest.raises(ProposalValidationError, match=expected_error):
            append_policy_evaluation_event(
                evaluation_id=persisted.record.evaluation_id,
                event_type=event_type,
                actor_id="spoofed_actor",
                reason=reason,
                idempotency_key=f"policy-eval-forged-{event_type.lower()}",
            )

    events = list_policy_evaluation_events(evaluation_id=persisted.record.evaluation_id)
    assert [event.event_type for event in events] == ["POLICY_EVALUATION_FINALIZED"]


def test_policy_evaluation_replay_compares_policy_source_and_evaluation_hashes() -> None:
    evidence = _base_evidence_bundle()
    persisted = finalize_policy_evaluation_record(
        evidence_bundle=evidence,
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_replay",
        proposal_version_id="ppv_policy_replay",
        created_by="advisor_1",
        idempotency_key="policy-eval-replay",
        reason=_trusted_reason("replay proof"),
    )
    matching = replay_policy_evaluation_record(
        evaluation_id=persisted.record.evaluation_id,
        evidence_bundle=deepcopy(evidence),
    )
    changed_evidence = deepcopy(evidence)
    changed_evidence["inputs"]["market_data_snapshot"]["fx_rates"][0]["rate"] = "1.36"
    changed = replay_policy_evaluation_record(
        evaluation_id=persisted.record.evaluation_id,
        evidence_bundle=changed_evidence,
    )

    assert matching.hash_comparison["policy_version_matches"] is True
    assert matching.hash_comparison["policy_content_hash_matches"] is True
    assert matching.hash_comparison["source_evidence_hash_matches"] is True
    assert matching.hash_comparison["evaluation_hash_matches"] is True
    assert changed.hash_comparison["source_evidence_hash_matches"] is False
    assert changed.hash_comparison["evaluation_hash_matches"] is False
    assert changed.hash_comparison["stored_evaluation_hash"].startswith("sha256:")
    assert changed.hash_comparison["replayed_evaluation_hash"].startswith("sha256:")


def test_policy_evaluation_replay_allows_superseded_policy_version() -> None:
    configure_policy_pack_catalog_repository(
        PolicyPackCatalogStore(_two_version_global_policy_pack_definitions())
    )
    evidence = _base_evidence_bundle()
    persisted = finalize_policy_evaluation_record(
        evidence_bundle=evidence,
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_replay_superseded",
        proposal_version_id="ppv_policy_replay_superseded",
        created_by="advisor_1",
        idempotency_key="policy-eval-replay-superseded",
        reason=_trusted_reason("superseded replay proof"),
    )
    new_detail = get_policy_pack_version(
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.06",
    )
    validate_policy_pack_version(
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.06",
        requested_by="policy_steward_1",
        idempotency_key="validate-global-2026-06",
        reason={"purpose": "activate superseding policy"},
    )
    activate_policy_pack_version(
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.06",
        activated_by="policy_checker_1",
        source_content_hash=new_detail.policy_pack.content_hash,
        idempotency_key="activate-global-2026-06",
        reason={"purpose": "activate superseding policy"},
    )
    superseded_detail = get_policy_pack_version(
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
    )

    matching = replay_policy_evaluation_record(
        evaluation_id=persisted.record.evaluation_id,
        evidence_bundle=deepcopy(evidence),
    )
    changed_evidence = deepcopy(evidence)
    changed_evidence["risk_lens"]["var"]["var_95_1m"] = "0.07"
    changed = replay_policy_evaluation_record(
        evaluation_id=persisted.record.evaluation_id,
        evidence_bundle=changed_evidence,
    )

    assert superseded_detail.policy_pack.activation_state == "SUPERSEDED"
    assert matching.hash_comparison["current_policy_version"] == "2026.05"
    assert matching.hash_comparison["policy_activation_state"] == "SUPERSEDED"
    assert matching.hash_comparison["policy_content_hash_matches"] is True
    assert matching.hash_comparison["source_evidence_hash_matches"] is True
    assert matching.hash_comparison["evaluation_hash_matches"] is True
    assert matching.hash_comparison["replay_reason_code"] == "POLICY_REPLAY_EXACT_MATCH"
    assert changed.hash_comparison["current_policy_version"] == "2026.05"
    assert changed.hash_comparison["policy_activation_state"] == "SUPERSEDED"
    assert changed.hash_comparison["source_evidence_hash_matches"] is False
    assert changed.hash_comparison["evaluation_hash_matches"] is False
    assert changed.hash_comparison["replay_reason_code"] == "POLICY_REPLAY_HASH_DRIFT"


def test_policy_evaluation_persists_disclosure_consent_and_approval_dependencies() -> None:
    _activate_sg_policy_pack()
    evidence = _base_evidence_bundle()
    evidence["inputs"]["shelf_entries"][0]["instrument_id"] = "SG_STRUCTURED_NOTE"
    evidence["inputs"]["shelf_entries"][0]["complexity"] = "COMPLEX"
    evidence["inputs"]["shelf_entries"][0]["structured_product"] = True
    evidence["inputs"]["proposed_trades"][0]["instrument_id"] = "SG_STRUCTURED_NOTE"
    evidence["artifact"]["disclosures"]["product_docs"] = [
        {"instrument_id": "SG_STRUCTURED_NOTE", "doc_ref": "Term sheet"}
    ]

    persisted = finalize_policy_evaluation_record(
        evidence_bundle=evidence,
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        proposal_id="pp_policy_requirements",
        proposal_version_id="ppv_policy_requirements",
        created_by="advisor_1",
        idempotency_key="policy-eval-requirements",
        reason=_trusted_reason("requirement mapping proof"),
    )

    assert persisted.record.evaluation_status == "PENDING_REVIEW"
    assert "REVIEW_DISCLOSURE:SG_STRUCTURED_NOTE" in persisted.record.approval_dependencies
    assert "advisor_reviewed_disclosure:SG_STRUCTURED_NOTE" in (
        persisted.record.disclosure_requirements
    )
    assert "client_consent:SG_STRUCTURED_NOTE" in persisted.record.consent_requirements


def test_policy_evaluation_record_listing_filters_orders_and_returns_copies() -> None:
    first = finalize_policy_evaluation_record(
        evidence_bundle=_base_evidence_bundle(),
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_list_first",
        proposal_version_id="ppv_policy_list_first",
        created_by="advisor_1",
        idempotency_key="policy-eval-list-first",
        reason=_trusted_reason("record listing first"),
    )
    other_portfolio_evidence = _base_evidence_bundle()
    other_portfolio_evidence["inputs"]["portfolio_snapshot"]["portfolio_id"] = "PB_SG_ALT_BAL_002"
    second = finalize_policy_evaluation_record(
        evidence_bundle=other_portfolio_evidence,
        policy_pack_id="GLOBAL_PRIVATE_BANKING_BASELINE",
        policy_version="2026.05",
        proposal_id="pp_policy_list_second",
        proposal_version_id="ppv_policy_list_second",
        created_by="advisor_1",
        idempotency_key="policy-eval-list-second",
        reason=_trusted_reason("record listing second"),
    )
    _activate_sg_policy_pack()
    pending_evidence = _base_evidence_bundle()
    pending_evidence["inputs"]["shelf_entries"][0]["instrument_id"] = "SG_STRUCTURED_NOTE"
    pending_evidence["inputs"]["shelf_entries"][0]["complexity"] = "COMPLEX"
    pending_evidence["inputs"]["shelf_entries"][0]["structured_product"] = True
    pending_evidence["inputs"]["proposed_trades"][0]["instrument_id"] = "SG_STRUCTURED_NOTE"
    pending_evidence["artifact"]["disclosures"]["product_docs"] = [
        {"instrument_id": "SG_STRUCTURED_NOTE", "doc_ref": "Term sheet"}
    ]
    pending = finalize_policy_evaluation_record(
        evidence_bundle=pending_evidence,
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        proposal_id="pp_policy_list_pending",
        proposal_version_id="ppv_policy_list_pending",
        created_by="advisor_1",
        idempotency_key="policy-eval-list-pending",
        reason=_trusted_reason("record listing pending"),
    )

    all_records = list_policy_evaluation_records()
    filtered_records = list_policy_evaluation_records(
        evaluation_status="PENDING_REVIEW",
        portfolio_id="PB_SG_GLOBAL_BAL_001",
    )
    portfolio_records = list_policy_evaluation_records(portfolio_id="PB_SG_GLOBAL_BAL_001")
    all_records[0].portfolio_id = "MUTATED_RETURNED_COPY"
    reloaded_first = get_policy_evaluation_record(evaluation_id=first.record.evaluation_id)

    assert [record.evaluation_id for record in all_records] == [
        first.record.evaluation_id,
        second.record.evaluation_id,
        pending.record.evaluation_id,
    ]
    assert [record.evaluation_id for record in filtered_records] == [
        first.record.evaluation_id,
        pending.record.evaluation_id,
    ]
    assert [record.evaluation_id for record in portfolio_records] == [
        first.record.evaluation_id,
        pending.record.evaluation_id,
    ]
    assert reloaded_first.portfolio_id == "PB_SG_GLOBAL_BAL_001"
