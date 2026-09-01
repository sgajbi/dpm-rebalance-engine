from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from scripts.durable_state_recovery_contract import (
    build_drill_evidence,
    load_contract,
    validate_contract,
)


def test_durable_state_recovery_contract_matches_migration_namespaces() -> None:
    contract = load_contract()

    assert validate_contract(contract) == []
    assert {namespace["namespace_key"] for namespace in contract["durable_namespaces"]} == {
        "advisory_copilot",
        "policy_packs",
        "proposals",
        "workspace",
    }


def test_durable_state_recovery_contract_requires_every_namespace() -> None:
    contract = load_contract()
    incomplete = deepcopy(contract)
    incomplete["durable_namespaces"] = [
        namespace
        for namespace in incomplete["durable_namespaces"]
        if namespace["namespace_key"] != "workspace"
    ]

    failures = validate_contract(incomplete)

    assert any(
        "Durable recovery namespaces must match migration directories" in failure
        for failure in failures
    )


def test_durable_state_recovery_contract_requires_stop_and_resume_criteria() -> None:
    contract = load_contract()
    missing_criteria = deepcopy(contract)
    missing_criteria["restore_drill_profiles"][0]["stop_criteria"] = []

    failures = validate_contract(missing_criteria)

    assert any("stop_criteria must be a non-empty list" in failure for failure in failures)


def test_durable_state_recovery_drill_evidence_lists_restore_checks() -> None:
    evidence = build_drill_evidence(load_contract())

    assert evidence["schema_version"] == "lotus.advise.durable-state-recovery-drill-evidence.v1"
    assert evidence["contract_path"] == "docs/standards/advisory-durable-state-recovery.v1.json"
    assert {namespace["namespace_key"] for namespace in evidence["durable_namespaces"]} == {
        "advisory_copilot",
        "policy_packs",
        "proposals",
        "workspace",
    }
    assert all(namespace["restore_check_keys"] for namespace in evidence["durable_namespaces"])


def test_proposal_recovery_scope_covers_durable_idea_intake_replay() -> None:
    contract = load_contract()
    proposal_namespace = next(
        item for item in contract["durable_namespaces"] if item["namespace_key"] == "proposals"
    )

    assert {
        "proposal_idea_intakes",
        "proposal_idea_intake_purge_events",
        "proposal_idea_review_realizations",
        "proposal_idea_realization_outcomes",
    }.issubset(proposal_namespace["durable_records"])
    retention = proposal_namespace["idea_intake_retention"]
    assert retention["replay_window_hours"] == 24
    assert retention["automatic_purge"] == (
        "target_prioritized_batches_of_128_before_each_new_intake_claim"
    )
    assert retention["purge_audit"] == "same_transaction_append_only_sanitized_evidence"
    assert (
        retention["legal_hold_behavior"]
        == "expired_claims_remain_replayable_and_conflict-protected_while_held"
    )
    assert (
        retention["restore_integrity"] == "receipt_requires_nonblank_bounded_portfolio_id_"
        "expiry_must_equal_creation_plus_24_hours_and_legal_hold_must_remain_boolean"
    )
    realization_retention = proposal_namespace["idea_review_realization_retention"]
    assert realization_retention == {
        "retention_class": "ADVISORY_PROPOSAL_RECORD",
        "transport_receipt_expiry_independent": True,
        "outcome_history": "append_only_monotonic_source_event_versions",
        "purge_policy": (
            "retain_with_advisory_review_lifecycle_until_governed_records_disposition"
        ),
        "restore_integrity": (
            "scope_identity_review_work_posture_and_exact_outcome_sequence_must_reconcile"
        ),
    }
    restore_checks = {check["check_key"]: check for check in proposal_namespace["restore_checks"]}
    idea_check = restore_checks["idea_intake_restored_claim_integrity"]
    assert idea_check["command"] == "make idea-intake-recovery-check"
    makefile = Path("Makefile").read_text(encoding="utf-8")
    command = makefile.split("idea-intake-recovery-check:", 1)[1].split("\n\n", 1)[0]
    assert "SET TRANSACTION READ ONLY" in command
    assert "PROPOSAL_POSTGRES_DSN" in command and "pytest" not in command
    recovery_sql = Path("scripts/sql/verify_idea_intake_recovery.sql").read_text(encoding="utf-8")
    assert all(
        marker in recovery_sql
        for marker in (
            "proposal_record_created",
            "portfolio_id",
            "certification_blockers",
            "proposal_idea_intake_purge_events",
            "proposal_idea_review_realizations",
            "proposal_idea_realization_outcomes",
            "source_event_version",
            "IS NOT DISTINCT FROM",
        )
    )
