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

    assert "proposal_idea_intakes" in proposal_namespace["durable_records"]
    retention = proposal_namespace["idea_intake_retention"]
    assert retention["replay_window_hours"] == 24
    assert retention["automatic_purge"] == "before_each_new_intake_claim"
    assert (
        retention["legal_hold_behavior"]
        == "expired_claims_remain_replayable_and_conflict-protected_while_held"
    )
    assert (
        retention["restore_integrity"]
        == "expiry_must_equal_creation_plus_24_hours_and_legal_hold_must_remain_boolean"
    )
    restore_checks = {check["check_key"]: check for check in proposal_namespace["restore_checks"]}
    idea_check = restore_checks["idea_intake_restored_claim_integrity"]
    assert idea_check["command"] == "make idea-intake-recovery-check"
    makefile = Path("Makefile").read_text(encoding="utf-8")
    command = makefile.split("idea-intake-recovery-check:", 1)[1].split("\n\n", 1)[0]
    assert "SET TRANSACTION READ ONLY" in command
    assert "PROPOSAL_POSTGRES_DSN" in command and "pytest" not in command
