import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.proposal_decision_vocabulary import validate_contract
from src.core.advisory import decision_summary_status_rules
from src.core.common import workflow_gate_vocabulary
from src.core.common.workflow_gates import GateOutcomeRule

CONTRACT_PATH = Path("docs/standards/proposal-decision-vocabulary.v1.json")


def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_published_decision_vocabulary_matches_advise_rule_owners() -> None:
    assert validate_contract(_contract()) == []


def test_canonical_consent_pairing_and_gate_next_step_are_published() -> None:
    contract = _contract()
    decision = next(
        item
        for item in contract["decision_statuses"]
        if item["status"] == "REQUIRES_CLIENT_CONSENT"
    )
    consent_gate = next(
        item for item in contract["workflow_gates"] if item["gate"] == "CLIENT_CONSENT_REQUIRED"
    )

    assert decision["allowed_top_level_statuses"] == ["READY", "PENDING_REVIEW"]
    assert decision["allowed_recommended_next_actions"] == ["DISCUSS_WITH_CLIENT"]
    assert decision["allowed_workflow_gates"] == ["CLIENT_CONSENT_REQUIRED"]
    assert consent_gate["recommended_next_step"] == "REQUEST_CLIENT_CONSENT"
    assert "approval_requirements" not in decision
    assert "reasons" not in consent_gate


def test_decision_pairing_drift_names_the_changed_status_and_field() -> None:
    contract = copy.deepcopy(_contract())
    decision = next(
        item
        for item in contract["decision_statuses"]
        if item["status"] == "REQUIRES_CLIENT_CONSENT"
    )
    decision["allowed_workflow_gates"] = ["EXECUTION_READY"]

    errors = validate_contract(contract)

    assert any(
        "REQUIRES_CLIENT_CONSENT" in error and "allowed_workflow_gates pairing drift" in error
        for error in errors
    )


def test_workflow_gate_drift_names_the_changed_gate() -> None:
    contract = copy.deepcopy(_contract())
    gate = next(
        item for item in contract["workflow_gates"] if item["gate"] == "CLIENT_CONSENT_REQUIRED"
    )
    gate["recommended_next_step"] = "EXECUTE"

    errors = validate_contract(contract)

    assert any(
        "CLIENT_CONSENT_REQUIRED pairing drift" in error and "REQUEST_CLIENT_CONSENT" in error
        for error in errors
    )


def test_decision_vocabulary_fails_when_rule_maps_do_not_cover_same_statuses(monkeypatch) -> None:
    monkeypatch.setattr(decision_summary_status_rules, "_DECISION_STATUS_WORKFLOW_GATES", {})

    with pytest.raises(RuntimeError, match="maps do not cover the same statuses"):
        decision_summary_status_rules.proposal_decision_vocabulary()


def test_workflow_vocabulary_fails_on_conflicting_rule_outcomes(monkeypatch) -> None:
    conflicting_rule = GateOutcomeRule(lambda _context: False, ("BLOCKED", "EXECUTE"))
    monkeypatch.setattr(
        workflow_gate_vocabulary,
        "_GATE_OUTCOME_RULES",
        (*workflow_gate_vocabulary._GATE_OUTCOME_RULES, conflicting_rule),
    )

    with pytest.raises(RuntimeError, match="BLOCKED has conflicting next steps"):
        workflow_gate_vocabulary.workflow_gate_vocabulary()


def test_workflow_vocabulary_fails_when_expected_next_step_map_drifts(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_gate_vocabulary,
        "_WORKFLOW_GATE_NEXT_STEPS",
        {**workflow_gate_vocabulary._WORKFLOW_GATE_NEXT_STEPS, "BLOCKED": "EXECUTE"},
    )

    with pytest.raises(RuntimeError, match="vocabulary drifted from outcome rules"):
        workflow_gate_vocabulary.workflow_gate_vocabulary()
