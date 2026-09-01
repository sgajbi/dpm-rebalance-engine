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
    assert contract["owned_product"] == "lotus-advise:AdvisoryProposalLifecycleRecord:v1"
    assert contract["source_authority"] == "lotus-idea"
    assert contract["proposal_authority"] == "lotus-advise"
    assert contract["target_route"] == "POST /advisory/proposals/idea-intake"
    assert contract["lifecycle_status"] == "implemented"
    assert contract["supportability_status"] == "not_certified"
    assert contract["route_existence_proven"] is True
    assert contract["runtime_intake_receipt_proven"] is True
    assert contract["durable_intake_idempotency_proven"] is True
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


def test_idea_proposal_intake_contract_keeps_non_proof_boundaries_and_blockers() -> None:
    contract = _contract()
    boundaries = " ".join(contract["non_proof_boundaries"])

    assert "Proves a live executable intake receipt" in boundaries
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
        "src/infrastructure/proposals/postgres_idea_intakes.py",
        "src/infrastructure/postgres_migrations/proposals/0011_idea_proposal_intakes.sql",
        "tests/unit/advisory/api/test_idea_proposal_intake_api.py",
    }.issubset(set(contract["evidence_refs"]))
