from __future__ import annotations

from copy import deepcopy

from scripts.advisory_data_lifecycle_inventory import (
    REQUIRED_FIELD_PATHS,
    load_inventory,
    validate_inventory,
)


def test_advisory_data_lifecycle_inventory_covers_required_fields() -> None:
    inventory = load_inventory()
    failures = validate_inventory(inventory)

    assert failures == []
    field_paths = {item["field_path"] for item in inventory["fields"]}
    assert REQUIRED_FIELD_PATHS <= field_paths


def test_advisory_data_lifecycle_inventory_blocks_missing_governance_entry() -> None:
    inventory = load_inventory()
    inventory["fields"] = [
        item
        for item in inventory["fields"]
        if item["field_path"] != "advisory_copilot_runs.evidence_packet_json"
    ]

    failures = validate_inventory(inventory)

    assert any("advisory_copilot_runs.evidence_packet_json" in failure for failure in failures)


def test_advisory_data_lifecycle_inventory_blocks_sensitive_metric_labels() -> None:
    inventory = load_inventory()
    inventory = deepcopy(inventory)
    for item in inventory["fields"]:
        if item["field_path"] == "proposals.portfolio_id":
            item["telemetry_label_allowed"] = True

    failures = validate_inventory(inventory)

    assert any("must not be a telemetry label" in failure for failure in failures)


def test_advisory_data_lifecycle_inventory_requires_raw_payload_masking() -> None:
    inventory = load_inventory()
    inventory = deepcopy(inventory)
    for item in inventory["fields"]:
        if item["field_path"] == "logs.extra_fields":
            item["masking"] = "client_portfolio_proposal_actor_prompt_business_text"

    failures = validate_inventory(inventory)

    assert any("raw sensitive payload copies" in failure for failure in failures)


def test_idea_intake_durable_fields_are_governed_as_non_metric_audit_evidence() -> None:
    inventory = load_inventory()
    fields = {item["field_path"]: item for item in inventory["fields"]}

    for field_path in (
        "proposal_idea_intakes.registry_key",
        "proposal_idea_intakes.request_fingerprint",
        "proposal_idea_intakes.response_json",
        "proposal_idea_intakes.created_at_utc",
        "proposal_idea_intakes.expires_at_utc",
        "proposal_idea_intakes.legal_hold",
    ):
        assert fields[field_path]["retention_policy"] == "OPERATIONAL_AUDIT_RECORD"
        assert fields[field_path]["telemetry_label_allowed"] is False
        assert "postgres" in fields[field_path]["stores"]
