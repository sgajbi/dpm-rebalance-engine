from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT_PATH = str(PROJECT_ROOT)
if ROOT_PATH not in sys.path:
    sys.path.insert(0, ROOT_PATH)

from src.core.advisory.decision_summary_status_rules import (  # noqa: E402
    proposal_decision_vocabulary,
)
from src.core.common.workflow_gates import workflow_gate_vocabulary  # noqa: E402

DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "standards" / "proposal-decision-vocabulary.v1.json"
SCHEMA_VERSION = "lotus.advise.proposal-decision-vocabulary.v1"
CONTRACT_VERSION = "proposal-decision-vocabulary.v1"
SOURCE_OWNER = {
    "service": "lotus-advise",
    "authority": (
        "Advise owns proposal decision statuses, top-level status pairings, recommended next "
        "actions, workflow gates, and gate next-step mappings."
    ),
    "rule_modules": [
        "src/core/advisory/decision_summary_status_rules.py",
        "src/core/common/workflow_gates.py",
    ],
}


def build_contract() -> dict[str, Any]:
    """Build the published artifact directly from the Advise rule owners."""

    decision_vocabulary = proposal_decision_vocabulary()
    gate_vocabulary = workflow_gate_vocabulary()
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "source_owner": SOURCE_OWNER,
        "decision_statuses": [
            {
                "status": status,
                **pairings,
            }
            for status, pairings in decision_vocabulary.items()
        ],
        "workflow_gates": [
            {"gate": gate, "recommended_next_step": next_step}
            for gate, next_step in gate_vocabulary.items()
        ],
    }


def validate_contract(candidate: object) -> list[str]:
    """Return actionable drift errors between the artifact and source-owned pairings."""

    if not isinstance(candidate, dict):
        return ["proposal decision vocabulary must be a JSON object"]

    expected = build_contract()
    errors: list[str] = []
    for field in ("schema_version", "contract_version", "source_owner"):
        if candidate.get(field) != expected[field]:
            errors.append(f"{field} drift: expected {expected[field]!r}")

    errors.extend(
        _validate_decision_statuses(
            candidate.get("decision_statuses"), expected["decision_statuses"]
        )
    )
    errors.extend(
        _validate_workflow_gates(candidate.get("workflow_gates"), expected["workflow_gates"])
    )
    return errors


def _validate_decision_statuses(actual: object, expected: object) -> list[str]:
    if not isinstance(actual, list):
        return ["decision_statuses must be a JSON array"]
    if not isinstance(expected, list):
        raise TypeError("generated decision statuses must be a JSON array")

    expected_by_status = {str(item["status"]): item for item in expected}
    actual_by_status = {
        str(item["status"]): item for item in actual if isinstance(item, dict) and "status" in item
    }
    errors: list[str] = []
    missing = sorted(set(expected_by_status) - set(actual_by_status))
    unexpected = sorted(set(actual_by_status) - set(expected_by_status))
    if missing:
        errors.append(f"missing decision statuses: {', '.join(missing)}")
    if unexpected:
        errors.append(f"unexpected decision statuses: {', '.join(unexpected)}")

    for status, expected_item in expected_by_status.items():
        actual_item = actual_by_status.get(status)
        if actual_item is None:
            continue
        for field in (
            "allowed_top_level_statuses",
            "allowed_recommended_next_actions",
            "allowed_workflow_gates",
        ):
            expected_values = list(expected_item[field])
            if actual_item.get(field) != expected_values:
                errors.append(
                    f"decision status {status} {field} pairing drift: "
                    f"expected {expected_values!r}, got {actual_item.get(field)!r}"
                )
    return errors


def _validate_workflow_gates(actual: object, expected: object) -> list[str]:
    if not isinstance(actual, list):
        return ["workflow_gates must be a JSON array"]
    if not isinstance(expected, list):
        raise TypeError("generated workflow gates must be a JSON array")

    expected_by_gate = {str(item["gate"]): item for item in expected}
    actual_by_gate = {
        str(item["gate"]): item for item in actual if isinstance(item, dict) and "gate" in item
    }
    errors: list[str] = []
    missing = sorted(set(expected_by_gate) - set(actual_by_gate))
    unexpected = sorted(set(actual_by_gate) - set(expected_by_gate))
    if missing:
        errors.append(f"missing workflow gates: {', '.join(missing)}")
    if unexpected:
        errors.append(f"unexpected workflow gates: {', '.join(unexpected)}")

    for gate, expected_item in expected_by_gate.items():
        actual_item = actual_by_gate.get(gate)
        if actual_item is None:
            continue
        field = "recommended_next_step"
        if actual_item.get(field) != expected_item[field]:
            errors.append(
                f"workflow gate {gate} pairing drift: expected "
                f"{expected_item[field]!r}, got {actual_item.get(field)!r}"
            )
    return errors


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON contract {path}: {exc}") from exc


def main() -> int:
    parser = ArgumentParser(description="Generate and validate the Advise decision vocabulary")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    output_path: Path = args.output
    if args.validate_only:
        if not output_path.exists():
            print(f"Proposal decision vocabulary missing: {output_path}")
            return 1
        try:
            errors = validate_contract(_read_json(output_path))
        except ValueError as exc:
            print(exc)
            return 1
        if errors:
            print("Proposal decision vocabulary drift detected:")
            for error in errors:
                print(f" - {error}")
            print(
                "Regenerate with: python scripts/proposal_decision_vocabulary.py "
                f"--output {output_path}"
            )
            return 1
        print("Proposal decision vocabulary gate passed (no drift).")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(build_contract(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote proposal decision vocabulary: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
