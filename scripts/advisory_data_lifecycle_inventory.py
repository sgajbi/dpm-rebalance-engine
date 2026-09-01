from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY_PATH = (
    REPO_ROOT
    / "contracts"
    / "data-governance"
    / "advisory-evidence-telemetry-field-inventory.v1.json"
)
EXPECTED_SCHEMA_VERSION = "lotus.advise.advisory-evidence-telemetry-field-inventory.v1"
REQUIRED_FIELD_PATHS = frozenset(
    {
        "advisory_copilot_runs.portfolio_id",
        "advisory_copilot_runs.proposal_id",
        "advisory_copilot_runs.tenant_id",
        "advisory_copilot_runs.created_by",
        "advisory_copilot_runs.correlation_id",
        "advisory_copilot_runs.evidence_packet_json",
        "advisory_copilot_runs.request_summary_json",
        "advisory_copilot_runs.output_sections_json",
        "advisory_copilot_runs.review_guidance_json",
        "advisory_copilot_runs.guardrail_results_json",
        "advisory_copilot_runs.lineage_json",
        "advisory_copilot_evidence_packets.packet_json",
        "advisory_copilot_evidence_packets.reason_json",
        "advisory_copilot_reviews.actor_id",
        "advisory_copilot_reviews.reason_json",
        "proposals.portfolio_id",
        "proposals.advisor_notes",
        "workspace_sessions.session_json",
        "workspace_saved_versions.replay_evidence_json",
        "idea_proposal_intake_response.trusted_scope",
        "idea_proposal_intake_response.idempotency_key_hash",
        "idea_proposal_intake_response.request_fingerprint",
        "idea_proposal_intake_response.outcome_reason_codes",
        "proposal_idea_intakes.registry_key",
        "proposal_idea_intakes.request_fingerprint",
        "proposal_idea_intakes.response_json",
        "proposal_idea_intakes.created_at_utc",
        "proposal_idea_intakes.expires_at_utc",
        "proposal_idea_intakes.legal_hold",
        "proposal_idea_review_realizations.realization_id",
        "proposal_idea_review_realizations.intake_id",
        "proposal_idea_review_realizations.review_work_id",
        "proposal_idea_review_realizations.review_work_status",
        "proposal_idea_review_realizations.tenant_id",
        "proposal_idea_review_realizations.legal_entity_code",
        "proposal_idea_review_realizations.portfolio_id",
        "proposal_idea_review_realizations.idea_candidate_id",
        "proposal_idea_review_realizations.conversion_intent_id",
        "proposal_idea_review_realizations.source_evidence_fingerprint",
        "proposal_idea_review_realizations.current_status",
        "proposal_idea_review_realizations.current_source_event_version",
        "proposal_idea_review_realizations.created_at_utc",
        "proposal_idea_review_realizations.updated_at_utc",
        "proposal_idea_realization_outcomes.outcome_id",
        "proposal_idea_realization_outcomes.realization_id",
        "proposal_idea_realization_outcomes.source_event_version",
        "proposal_idea_realization_outcomes.status",
        "proposal_idea_realization_outcomes.reason_code",
        "proposal_idea_realization_outcomes.occurred_at_utc",
        "proposal_idea_realization_outcomes.review_work_id",
        "proposal_idea_realization_outcomes.proposal_id",
        "proposal_idea_realization_outcomes.terminal",
        "proposal_idea_intake_purge_events.registry_key_digest",
        "proposal_idea_intake_purge_events.request_fingerprint",
        "proposal_idea_intake_purge_events.claim_created_at_utc",
        "proposal_idea_intake_purge_events.claim_expired_at_utc",
        "proposal_idea_intake_purge_events.purged_at_utc",
        "proposal_idea_intake_purge_events.reason_code",
        "logs.extra_fields",
        "metrics.labels",
        "traces.attributes",
        "lotus_ai.context_payload.copilot_evidence_packet",
    }
)
FIELD_REQUIRED_KEYS = frozenset(
    {
        "field_path",
        "purpose",
        "classification",
        "owner",
        "allowed_consumers",
        "retention_policy",
        "purge_policy",
        "masking",
        "stores",
        "telemetry_label_allowed",
        "api_projection_allowed",
        "downstream_payload_allowed",
        "source_boundary",
    }
)
HIGH_CARDINALITY_OR_BUSINESS_CLASSIFICATIONS = frozenset(
    {
        "HIGH_CARDINALITY_IDENTIFIER",
        "ADVISOR_USE_SUMMARY",
        "COMPLIANCE_REVIEW_EVIDENCE",
        "MODEL_RISK_AUDIT",
        "OPERATIONAL_AUDIT",
    }
)
RAW_DATA_MARKERS = ("raw_prompt", "raw_provider_payload", "business_text", "client_", "portfolio_")


def load_inventory(path: Path = DEFAULT_INVENTORY_PATH) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def validate_inventory(inventory: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if inventory.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        failures.append(
            "schema_version must be lotus.advise.advisory-evidence-telemetry-field-inventory.v1"
        )
    fields = inventory.get("fields")
    if not isinstance(fields, list) or not fields:
        failures.append("fields must be a non-empty list")
        return failures

    seen: set[str] = set()
    field_paths: set[str] = set()
    for index, item in enumerate(fields):
        if not isinstance(item, dict):
            failures.append(f"fields[{index}] must be an object")
            continue
        failures.extend(_validate_field(item, index=index, seen=seen))
        field_path = item.get("field_path")
        if isinstance(field_path, str):
            field_paths.add(field_path)

    missing = REQUIRED_FIELD_PATHS - field_paths
    if missing:
        failures.append(f"required field paths missing from lifecycle inventory: {sorted(missing)}")
    return failures


def _validate_field(item: dict[str, Any], *, index: int, seen: set[str]) -> list[str]:
    failures: list[str] = []
    missing_keys = FIELD_REQUIRED_KEYS - set(item)
    if missing_keys:
        failures.append(f"fields[{index}] missing required keys: {sorted(missing_keys)}")

    field_path = item.get("field_path")
    if not isinstance(field_path, str) or not field_path.strip():
        failures.append(f"fields[{index}].field_path must be a non-empty string")
    elif field_path in seen:
        failures.append(f"duplicate field_path in lifecycle inventory: {field_path}")
    else:
        seen.add(field_path)

    for key in (
        "purpose",
        "classification",
        "owner",
        "retention_policy",
        "purge_policy",
        "masking",
    ):
        if not isinstance(item.get(key), str) or not item[key].strip():
            failures.append(f"{field_path or f'fields[{index}]'}.{key} must be a non-empty string")

    for key in ("allowed_consumers", "stores"):
        values = item.get(key)
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) for value in values)
        ):
            failures.append(
                f"{field_path or f'fields[{index}]'}.{key} must be a non-empty string list"
            )

    for key in ("telemetry_label_allowed", "api_projection_allowed", "downstream_payload_allowed"):
        if not isinstance(item.get(key), bool):
            failures.append(f"{field_path or f'fields[{index}]'}.{key} must be boolean")

    if _unsafe_telemetry_label(item):
        failures.append(
            f"{field_path}: high-cardinality or business evidence must not be a telemetry label"
        )
    if _raw_data_masking_policy(item):
        failures.append(f"{field_path}: masking policy cannot permit raw sensitive payload copies")
    return failures


def _unsafe_telemetry_label(item: dict[str, Any]) -> bool:
    return (
        bool(item.get("telemetry_label_allowed"))
        and item.get("classification") in HIGH_CARDINALITY_OR_BUSINESS_CLASSIFICATIONS
        and item.get("field_path")
        not in {
            "advisory_copilot_runs.guardrail_results_json",
            "logs.extra_fields",
            "metrics.labels",
            "traces.attributes",
        }
    )


def _raw_data_masking_policy(item: dict[str, Any]) -> bool:
    masking = str(item.get("masking", "")).lower()
    protective_terms = ("no_", "do_not", "forbidden", "redact", "tokenize", "hash", "omit")
    return any(
        marker in masking and not any(term in masking for term in protective_terms)
        for marker in RAW_DATA_MARKERS
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate advisory evidence lifecycle inventory.")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()
    failures = validate_inventory(load_inventory(args.inventory))
    if failures:
        print("Advisory data lifecycle inventory validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Advisory data lifecycle inventory validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
