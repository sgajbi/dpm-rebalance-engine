from pathlib import Path
from typing import Any

import pytest

from src.core.common.canonical import hash_canonical_payload
from src.core.policy_packs import (
    DurablePolicyPackCatalogRepository,
    InMemoryPolicyPackCatalogStateStore,
    PolicyPackCatalogStore,
    activate_policy_pack_version,
    configure_policy_pack_catalog_repository,
    get_policy_pack_version,
    list_policy_pack_events,
    reset_policy_pack_catalog_for_tests,
    validate_policy_pack_version,
)
from src.core.policy_packs.catalog_definitions import validate_definition
from src.core.policy_packs.catalog_reference_packs import reference_policy_packs
from src.core.proposals.exceptions import (
    ProposalIdempotencyConflictError,
    ProposalValidationError,
)

SOURCE_ROOT = Path(__file__).resolve().parents[4] / "src" / "core" / "policy_packs"


def setup_function() -> None:
    reset_policy_pack_catalog_for_tests()


def test_policy_pack_catalog_definition_helpers_stay_focused() -> None:
    catalog = (SOURCE_ROOT / "catalog.py").read_text(encoding="utf-8")
    definitions = (SOURCE_ROOT / "catalog_definitions.py").read_text(encoding="utf-8")

    assert "summary_from_definition" in catalog
    assert "validate_policy_pack_catalog_definition" in catalog
    assert "validate_definition" not in catalog
    assert "def _validate_definition" not in catalog
    assert "def _summary_from_definition" not in catalog
    assert "def _prepare_definition" not in catalog

    assert "from src.core.policy_packs.catalog_definition_validation import" in definitions
    assert "def validate_definition" in definitions
    assert "def summary_from_definition" in definitions
    assert "def prepare_definition" in definitions


def test_policy_pack_catalog_delegates_commands_events_and_projection() -> None:
    catalog = (SOURCE_ROOT / "catalog.py").read_text(encoding="utf-8")
    commands = (SOURCE_ROOT / "catalog_commands.py").read_text(encoding="utf-8")
    events = (SOURCE_ROOT / "catalog_events.py").read_text(encoding="utf-8")
    projection = (SOURCE_ROOT / "catalog_projection.py").read_text(encoding="utf-8")

    assert "from src.core.policy_packs.catalog_commands import" in catalog
    assert "from src.core.policy_packs.catalog_projection import" in catalog
    assert "hash_canonical_payload" not in catalog
    assert "datetime.now(UTC)" not in catalog
    assert "PolicyPackActivationResponse(" not in catalog
    assert "PolicyPackValidationResponse(" not in catalog
    assert "PolicyPackDetailResponse(" not in catalog
    assert "def validate_policy_pack_catalog_definition(" in commands
    assert "def activate_policy_pack_catalog_definition(" in commands
    assert "hash_canonical_payload" in commands
    assert "def append_policy_pack_catalog_event(" in events
    assert "def find_replayed_policy_pack_catalog_event(" in events
    assert "def latest_policy_pack_validation_event(" in events
    assert "PolicyPackDetailResponse(" in projection


def test_policy_pack_reference_data_stays_outside_catalog_store() -> None:
    catalog = (SOURCE_ROOT / "catalog.py").read_text(encoding="utf-8")
    reference_packs = (SOURCE_ROOT / "catalog_reference_packs.py").read_text(encoding="utf-8")

    assert "reference_policy_packs" in catalog
    assert "_REFERENCE_PACKS" not in catalog
    assert "SG_PRIVATE_BANKING_REFERENCE" not in catalog
    assert "GLOBAL_PRIVATE_BANKING_BASELINE" not in catalog

    assert "def reference_policy_packs" in reference_packs
    assert "_REFERENCE_PACKS" in reference_packs
    assert "SG_PRIVATE_BANKING_REFERENCE" in reference_packs
    assert "GLOBAL_PRIVATE_BANKING_BASELINE" in reference_packs


def test_policy_pack_validation_is_hash_backed_and_idempotent() -> None:
    detail = get_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
    )

    response = validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="  validate-sg-reference  ",
        reason={"purpose": "pre-activation validation"},
    )
    replayed = validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="validate-sg-reference",
        reason={"purpose": "pre-activation validation"},
    )

    assert response.validation_status == "READY"
    assert response.policy_pack.content_hash == detail.policy_pack.content_hash
    assert response.validation_event.content_hash == detail.policy_pack.content_hash
    assert response.validation_event.idempotency_key == "validate-sg-reference"
    assert response.validation_event.reason["dry_run_status"] == "REFERENCE_FIXTURES_VALIDATED"
    assert "PB_SG_GLOBAL_BAL_001" in response.validation_event.reason["sample_fixture_refs"]
    assert replayed.replayed is True
    assert replayed.validation_event.event_id == response.validation_event.event_id


def test_policy_pack_validation_rejects_idempotency_key_reuse_with_different_payload() -> None:
    validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="validate-conflict",
        reason={"purpose": "first validation"},
    )

    with pytest.raises(ProposalIdempotencyConflictError):
        validate_policy_pack_version(
            policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
            policy_version="2026.05",
            requested_by="policy_steward_1",
            idempotency_key="validate-conflict",
            reason={"purpose": "changed validation"},
        )


def test_policy_pack_validation_replays_when_only_trusted_principal_metadata_changes() -> None:
    first = validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="validate-principal-replay",
        reason={
            "purpose": "pre-activation validation",
            "trusted_principal": {
                "subject": "policy_steward_1",
                "role": "POLICY_STEWARD",
                "correlation_id": "corr-first",
                "trace_id": "trace-first",
            },
        },
    )

    replayed = validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="validate-principal-replay",
        reason={
            "purpose": "pre-activation validation",
            "trusted_principal": {
                "subject": "policy_steward_1",
                "role": "POLICY_STEWARD",
                "correlation_id": "corr-retry",
                "trace_id": "trace-retry",
            },
        },
    )

    assert replayed.replayed is True
    assert replayed.validation_event.event_id == first.validation_event.event_id
    assert (
        first.validation_event.reason["reason"]["trusted_principal"]["correlation_id"]
        == "corr-first"
    )


def test_policy_pack_validation_replays_legacy_volatile_principal_hash() -> None:
    store = PolicyPackCatalogStore(reference_policy_packs())
    reason = {
        "purpose": "pre-activation validation",
        "trusted_principal": {
            "subject": "policy_steward_1",
            "role": "POLICY_STEWARD",
            "correlation_id": "corr-first",
            "trace_id": "trace-first",
        },
    }
    validated = store.validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="validate-legacy-principal-replay",
        reason=reason,
    )
    legacy_hash = hash_canonical_payload(
        {
            "operation": "POLICY_PACK_VALIDATED",
            "policy_pack_id": "SG_PRIVATE_BANKING_REFERENCE",
            "policy_version": "2026.05",
            "requested_by": "policy_steward_1",
            "content_hash": validated.validation_event.content_hash,
            "reason": reason,
        }
    )
    store._idempotency["validate-legacy-principal-replay"] = (  # noqa: SLF001
        legacy_hash,
        validated.validation_event,
    )

    replayed = store.validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="validate-legacy-principal-replay",
        reason={
            "purpose": "pre-activation validation",
            "trusted_principal": {
                "subject": "policy_steward_1",
                "role": "POLICY_STEWARD",
                "correlation_id": "corr-retry",
                "trace_id": "trace-retry",
            },
        },
    )

    assert replayed.replayed is True
    assert replayed.validation_event.event_id == validated.validation_event.event_id


def test_policy_pack_activation_enforces_hash_maker_checker_and_immutability() -> None:
    detail = get_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
    )
    validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="validate-before-activate",
        reason={"purpose": "pre-activation validation"},
    )

    with pytest.raises(ProposalValidationError, match="MAKER_CHECKER"):
        activate_policy_pack_version(
            policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
            policy_version="2026.05",
            activated_by="policy_steward_1",
            source_content_hash=detail.policy_pack.content_hash,
            idempotency_key="activate-same-actor",
            reason={"purpose": "same actor should fail"},
        )

    with pytest.raises(ProposalValidationError, match="CONTENT_HASH"):
        activate_policy_pack_version(
            policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
            policy_version="2026.05",
            activated_by="policy_checker_1",
            source_content_hash="sha256:stale",
            idempotency_key="activate-stale-hash",
            reason={"purpose": "stale hash should fail"},
        )

    activated = activate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        activated_by="policy_checker_1",
        source_content_hash=detail.policy_pack.content_hash,
        idempotency_key="  activate-sg-reference  ",
        reason={"purpose": "activate reference pack"},
    )
    replayed = activate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        activated_by="policy_checker_1",
        source_content_hash=detail.policy_pack.content_hash,
        idempotency_key="activate-sg-reference",
        reason={"purpose": "activate reference pack"},
    )

    assert activated.policy_pack.activation_state == "ACTIVE"
    assert activated.activation_event.idempotency_key == "activate-sg-reference"
    assert activated.policy_pack.content_hash == detail.policy_pack.content_hash
    assert activated.activation_event.reason["validated_by"] == "policy_steward_1"
    assert activated.activation_event.reason["previous_active_policy_version"] is None
    assert activated.activation_event.reason["resulting_active_policy_version"] == "2026.05"
    assert replayed.replayed is True
    assert replayed.activation_event.event_id == activated.activation_event.event_id
    with pytest.raises(ProposalValidationError, match="IMMUTABLE"):
        activate_policy_pack_version(
            policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
            policy_version="2026.05",
            activated_by="policy_checker_2",
            source_content_hash=detail.policy_pack.content_hash,
            idempotency_key="activate-again",
            reason={"purpose": "second activation should fail"},
        )


def test_policy_pack_activation_replays_when_only_trusted_principal_metadata_changes() -> None:
    detail = get_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
    )
    validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="validate-before-principal-replay-activate",
        reason={"purpose": "pre-activation validation"},
    )
    activated = activate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        activated_by="policy_checker_1",
        source_content_hash=detail.policy_pack.content_hash,
        idempotency_key="activate-principal-replay",
        reason={
            "purpose": "activate reference pack",
            "trusted_principal": {
                "subject": "policy_checker_1",
                "role": "POLICY_CHECKER",
                "correlation_id": "corr-first",
                "trace_id": "trace-first",
            },
        },
    )

    replayed = activate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        activated_by="policy_checker_1",
        source_content_hash=detail.policy_pack.content_hash,
        idempotency_key="activate-principal-replay",
        reason={
            "purpose": "activate reference pack",
            "trusted_principal": {
                "subject": "policy_checker_1",
                "role": "POLICY_CHECKER",
                "correlation_id": "corr-retry",
                "trace_id": "trace-retry",
            },
        },
    )

    assert replayed.replayed is True
    assert replayed.activation_event.event_id == activated.activation_event.event_id
    assert (
        activated.activation_event.reason["reason"]["trusted_principal"]["correlation_id"]
        == "corr-first"
    )


def test_policy_pack_activation_supersedes_prior_active_version() -> None:
    store = PolicyPackCatalogStore(_two_version_sg_policy_pack_definitions())
    new_detail = store.get_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.06",
    )
    store.validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.06",
        requested_by="policy_steward_1",
        idempotency_key="validate-sg-reference-2026-06",
        reason={"purpose": "pre-activation validation"},
    )

    activated = store.activate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.06",
        activated_by="policy_checker_1",
        source_content_hash=new_detail.policy_pack.content_hash,
        idempotency_key="activate-sg-reference-2026-06",
        reason={"purpose": "activate superseding reference pack"},
    )
    old_detail = store.get_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
    )
    listed = store.list_policy_pack_versions()

    assert activated.policy_pack.activation_state == "ACTIVE"
    assert old_detail.policy_pack.activation_state == "SUPERSEDED"
    assert [
        item.policy_version
        for item in listed.items
        if (
            item.policy_pack_id == "SG_PRIVATE_BANKING_REFERENCE"
            and item.activation_state == "ACTIVE"
        )
    ] == ["2026.06"]
    assert activated.activation_event.reason["previous_active_policy_version"] == "2026.05"
    assert activated.activation_event.reason["superseded_policy_version"] == "2026.05"
    assert activated.activation_event.reason["resulting_active_policy_version"] == "2026.06"
    assert (
        activated.activation_event.reason["supersession_contract"]
        == "ONE_ACTIVE_VERSION_PER_POLICY_PACK"
    )


def test_policy_pack_activation_blocks_preexisting_duplicate_active_versions() -> None:
    definitions = _two_version_sg_policy_pack_definitions()
    for definition in definitions:
        if definition["policy_pack_id"] == "SG_PRIVATE_BANKING_REFERENCE":
            definition["activation_state"] = "ACTIVE"
    store = PolicyPackCatalogStore(definitions)
    detail = store.get_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.06",
    )

    with pytest.raises(ProposalValidationError, match="POLICY_PACK_ACTIVE_VERSION_CONFLICT"):
        store.activate_policy_pack_version(
            policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
            policy_version="2026.06",
            activated_by="policy_checker_1",
            source_content_hash=detail.policy_pack.content_hash,
            idempotency_key="activate-conflicting-sg-reference",
            reason={"purpose": "duplicate active should fail"},
        )


def test_policy_pack_catalog_repository_port_survives_reinstantiation() -> None:
    state_store = InMemoryPolicyPackCatalogStateStore()
    configure_policy_pack_catalog_repository(
        DurablePolicyPackCatalogRepository(state_store=state_store)
    )
    detail = get_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
    )
    validation = validate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        requested_by="policy_steward_1",
        idempotency_key="validate-restart-catalog",
        reason={"purpose": "restart catalog proof"},
    )
    activation = activate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        activated_by="policy_checker_1",
        source_content_hash=detail.policy_pack.content_hash,
        idempotency_key="activate-restart-catalog",
        reason={"purpose": "restart catalog proof"},
    )

    configure_policy_pack_catalog_repository(
        DurablePolicyPackCatalogRepository(state_store=state_store)
    )
    reloaded = get_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
    )
    events = list_policy_pack_events(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
    )
    replayed_activation = activate_policy_pack_version(
        policy_pack_id="SG_PRIVATE_BANKING_REFERENCE",
        policy_version="2026.05",
        activated_by="policy_checker_1",
        source_content_hash=detail.policy_pack.content_hash,
        idempotency_key="activate-restart-catalog",
        reason={"purpose": "restart catalog proof"},
    )

    assert reloaded.policy_pack.activation_state == "ACTIVE"
    assert [event.event_id for event in events] == [
        validation.validation_event.event_id,
        activation.activation_event.event_id,
    ]
    assert replayed_activation.replayed is True
    assert replayed_activation.activation_event.event_id == activation.activation_event.event_id


def test_invalid_policy_pack_definition_fails_fast_with_diagnostics() -> None:
    store = PolicyPackCatalogStore(
        [
            {
                "policy_pack_id": "BAD_REFERENCE",
                "policy_version": "2026.05",
                "policy_family": "BAD_REFERENCE",
                "display_name": "Bad Reference",
                "activation_state": "DRAFT",
                "maker_checker_required": False,
                "schema_version": "rfc0025.policy-pack-catalog.v1",
                "applicability": {"jurisdiction_scope": ["SG"]},
                "source_requirements": ["client_classification"],
                "rules": [
                    {
                        "rule_id": "bad-rule",
                        "severity": "BLOCKING",
                        "required_evidence_fields": [],
                    }
                ],
                "disclosure_templates": [],
                "consent_templates": [],
                "approval_routes": [],
                "sample_fixture_refs": ["PB_SG_GLOBAL_BAL_001"],
            }
        ]
    )

    with pytest.raises(ProposalValidationError) as exc:
        store.validate_policy_pack_version(
            policy_pack_id="BAD_REFERENCE",
            policy_version="2026.05",
            requested_by="policy_steward_1",
            idempotency_key="validate-bad-reference",
            reason={"purpose": "prove diagnostics"},
        )

    assert "RULE_ID_NOT_UPPER_SNAKE_CASE" in str(exc.value)
    assert "bad-rule_REQUIRED_EVIDENCE_FIELDS_REQUIRED" in str(exc.value)


def test_policy_pack_definition_validation_projects_top_level_diagnostics() -> None:
    diagnostics = validate_definition(
        {
            "policy_pack_id": "BAD_REFERENCE",
            "policy_version": "2026.05",
            "policy_family": "BAD_REFERENCE",
            "rules": "not-a-list",
            "reference_posture": "UNDECLARED",
        }
    )

    assert diagnostics == [
        "APPLICABILITY_REQUIRED",
        "SOURCE_REQUIREMENTS_REQUIRED",
        "SAMPLE_FIXTURE_REFS_REQUIRED",
        "SCHEMA_VERSION_REQUIRED",
        "REFERENCE_POSTURE_NOT_DECLARED",
        "RULES_MUST_BE_LIST",
    ]


def test_policy_pack_definition_validation_rejects_unsafe_rule_wording() -> None:
    diagnostics = validate_definition(
        {
            "policy_pack_id": "BAD_REFERENCE",
            "policy_version": "2026.05",
            "policy_family": "BAD_REFERENCE",
            "applicability": {"jurisdiction_scope": ["SG"]},
            "source_requirements": ["client_classification"],
            "rules": [
                {
                    "rule_id": "SG_UNSAFE_WORDING",
                    "required_evidence_fields": ["conflict_evidence"],
                    "positive_wording_when_missing_evidence": "All evidence is ready.",
                },
                "not-a-rule",
            ],
            "sample_fixture_refs": ["PB_SG_GLOBAL_BAL_001"],
            "schema_version": "rfc0025.policy-pack-catalog.v1",
            "reference_posture": "REFERENCE_EXAMPLE_NOT_LEGAL_ADVICE",
        }
    )

    assert diagnostics == [
        "SG_UNSAFE_WORDING_FORBIDDEN_POSITIVE_MISSING_EVIDENCE_WORDING",
        "RULE_MUST_BE_OBJECT",
    ]


def _two_version_sg_policy_pack_definitions() -> list[dict[str, Any]]:
    definitions = [
        definition
        for definition in reference_policy_packs()
        if definition["policy_pack_id"] == "SG_PRIVATE_BANKING_REFERENCE"
    ]
    old_definition = definitions[0]
    old_definition["activation_state"] = "ACTIVE"
    new_definition = {
        **old_definition,
        "policy_version": "2026.06",
        "activation_state": "DRAFT",
        "effective_from": "2026-06-01",
    }
    return [old_definition, new_definition]
