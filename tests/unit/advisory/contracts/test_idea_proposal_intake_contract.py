from __future__ import annotations

import json
from pathlib import Path

from src.core.proposals.idea_proposal_intake import IDEA_PROPOSAL_INTAKE_CERTIFICATION_BLOCKERS

ROOT = Path(__file__).resolve().parents[4]
CONTRACT_PATH = ROOT / "contracts/idea-proposal-intake/lotus-advise-idea-proposal-intake.v1.json"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_idea_proposal_intake_contract_preserves_advise_authority_boundary() -> None:
    contract = _contract()

    assert contract["schema_version"] == "lotus-advise.idea-proposal-intake.v1"
    assert contract["repository"] == "lotus-advise"
    assert contract["approved_producer_repository"] == "lotus-idea"
    assert contract["approved_producer_product"] == "lotus-idea:IdeaCandidate:v1"
    assert contract["approved_producer_wire_contract_version"] == "1.6.0"
    assert contract["owned_product"] == "lotus-advise:AdvisoryProposalLifecycleRecord:v1"
    assert contract["source_authority"] == "lotus-idea"
    assert contract["proposal_authority"] == "lotus-advise"
    assert contract["target_route"] == "POST /advisory/proposals/idea-intake"
    assert contract["realization_read_route"] == (
        "GET /advisory/proposals/idea-intake/{intake_id}/realization"
    )
    assert contract["lifecycle_status"] == "implemented"
    assert contract["supportability_status"] == "not_certified"
    assert contract["route_existence_proven"] is True
    assert contract["runtime_intake_receipt_proven"] is True
    assert contract["durable_intake_idempotency_proven"] is True
    assert contract["durable_adviser_review_work_proven"] is True
    assert contract["initial_source_owned_outcome_proven"] is True
    assert contract["proposal_linkage_outcomes_proven"] is False
    assert contract["terminal_lifecycle_outcomes_proven"] is False
    assert contract["required_request_fields"] == [
        "source_system",
        "source_product",
        "idea_candidate_id",
        "conversion_intent_id",
        "intent_type",
        "portfolio_id",
        "source_refs",
    ]
    assert contract["portfolio_scope"] == {
        "required": True,
        "source": "producer_authorized_governed_candidate_scope",
        "inference_from_opaque_identifiers_forbidden": True,
        "included_in_request_fingerprint": True,
        "included_in_intake_identity": True,
        "persisted_in_durable_receipt": True,
        "production_idp_entitlement_validation_proven": False,
        "pre_scope_contract_transition": {
            "prior_wire_contract_version": "1.5.0",
            "same_key_behavior": "conflict_fail_closed",
            "operator_action": "reconcile_prior_receipt_then_use_new_idempotency_key",
        },
    }
    assert contract["idempotency_retention"] == {
        "replay_window_hours": 24,
        "expiry_boundary": "created_at_utc_plus_24_hours",
        "purge_policy": "target_prioritized_batches_before_new_claim_unless_legal_hold",
        "purge_batch_size": 128,
        "purge_audit_evidence": "proposal_idea_intake_purge_events",
        "legal_hold_supported": True,
        "raw_idempotency_key_persisted": False,
    }
    assert contract["downstream_execution_proven"] is False
    assert contract["supported_feature_promoted"] is False
    assert contract["realization_read_capability"] == "advisory.idea_proposal_realization.read"
    assert contract["initial_realization_outcomes"] == {
        "REVIEW_FOR_ADVISORY_PROPOSAL": {
            "status": "ACCEPTED_FOR_REVIEW",
            "review_work_status": "PENDING_ADVISER_REVIEW",
            "source_event_version": 1,
            "terminal": False,
        },
        "CREATE_ADVISORY_PROPOSAL_DRAFT": {
            "status": "REJECTED_BEFORE_WORK",
            "review_work_status": None,
            "source_event_version": 1,
            "terminal": True,
        },
    }


def test_idea_proposal_intake_contract_keeps_non_proof_boundaries_and_blockers() -> None:
    contract = _contract()
    boundaries = " ".join(contract["non_proof_boundaries"])

    assert "durable Advise adviser-review work item" in boundaries
    assert "rejected before work" in boundaries
    assert "Does not grant suitability" in boundaries
    assert "Does not create orders" in boundaries
    assert "Does not promote a supported feature" in boundaries
    assert contract["certification_blockers"] == IDEA_PROPOSAL_INTAKE_CERTIFICATION_BLOCKERS
    assert "advise_live_contract_proof_missing" not in contract["certification_blockers"]
    assert {
        "src/api/proposals/routes_idea_intake.py",
        "src/api/proposals/idea_intake_principal.py",
        "src/core/proposals/idea_intake_authority.py",
        "src/core/proposals/idea_proposal_intake.py",
        "src/core/proposals/idea_intake_persistence.py",
        "src/core/proposals/idea_review_realization.py",
        "src/core/proposals/idea_realization_read_model.py",
        "src/infrastructure/proposals/postgres_idea_intakes.py",
        "src/infrastructure/postgres_migrations/proposals/0011_idea_proposal_intakes.sql",
        "src/infrastructure/postgres_migrations/proposals/0012_idea_review_realizations.sql",
        "scripts/sql/verify_idea_intake_recovery.sql",
        "tests/unit/advisory/api/test_idea_proposal_intake_api.py",
    }.issubset(set(contract["evidence_refs"]))


def test_recovery_contract_accepts_only_the_exact_pre_realization_receipt_shape() -> None:
    recovery_sql = Path("scripts/sql/verify_idea_intake_recovery.sql").read_text(encoding="utf-8")

    assert "NOT response_json::jsonb ?| ARRAY[" in recovery_sql
    assert '"advisory_review_work_realization_not_certified"' in recovery_sql
    assert '"source_owned_outcome_stream_not_certified"' in recovery_sql
    assert "response_json::jsonb ?& ARRAY[" in recovery_sql
    assert '"proposal_linkage_outcome_not_certified"' in recovery_sql
    assert '"terminal_realization_outcomes_not_certified"' in recovery_sql
