from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from src.core.advisory.simulation_decision_support import build_simulation_decision_support
from src.core.advisory.simulation_intent_plan import SimulationIntentPlan
from src.core.common.canonical import hash_canonical_payload
from src.core.common.simulation_shared import derive_status_from_rules
from src.core.diagnostics_models import DiagnosticsData, LineageData, RuleResult
from src.core.gate_models import GateDecision
from src.core.order_intent_models import ProposalOrderIntent
from src.core.proposal_effect_models import Reconciliation
from src.core.proposal_request_models import (
    ProposalSimulateRequest,
    ProposedCashFlow,
    ProposedTrade,
)
from src.core.proposal_result_models import ProposalResult
from src.core.simulation_state_models import ProposalAllocationLens, SimulatedState
from src.core.suitability_models import SuitabilityResult

ADVISE_DECISION_CALCULATION_VERSION = "lotus-advise.advisory-decision-support.v1"

_CORE_DECISION_PAYLOAD_FIELDS = (
    "suitability",
    "gate_decision",
    "proposal_decision_summary",
    "proposal_alternatives",
    "drift_analysis",
)
_ADVISE_DERIVED_PAYLOAD_FIELDS = ("proposal_review_evidence", "valuation_context")


class CoreDecisionCompatibilitySnapshot(BaseModel):
    """Non-authoritative Core decision output retained only for migration parity evidence."""

    model_config = ConfigDict(extra="forbid")

    reported_status: str | None = None
    suitability: dict[str, Any] | None = None
    gate_decision: dict[str, Any] | None = None
    proposal_decision_summary: dict[str, Any] | None = None
    proposal_alternatives: dict[str, Any] | None = None
    drift_analysis: dict[str, Any] | None = None

    def has_core_decision_payload(self) -> bool:
        return any(
            value is not None
            for value in (
                self.reported_status,
                self.suitability,
                self.gate_decision,
                self.proposal_decision_summary,
                self.proposal_alternatives,
                self.drift_analysis,
            )
        )


class CoreProjectedTransactionEffects(BaseModel):
    """Core-owned transaction effects consumed by Advise decision policy."""

    model_config = ConfigDict(extra="forbid")

    proposal_run_id: str
    correlation_id: str
    core_reported_status: Literal["READY", "BLOCKED", "PENDING_REVIEW"]
    before: SimulatedState
    intents: list[Annotated[ProposalOrderIntent, Field(discriminator="intent_type")]]
    after_simulated: SimulatedState
    reconciliation: Reconciliation | None = None
    rule_results: list[RuleResult] = Field(default_factory=list)
    explanation: dict[str, Any]
    diagnostics: DiagnosticsData
    allocation_lens: ProposalAllocationLens = Field(default_factory=ProposalAllocationLens)
    lineage: LineageData


def map_core_payload_to_projected_transaction_effects(
    payload: dict[str, Any],
) -> CoreProjectedTransactionEffects:
    source_effect_payload = {
        key: deepcopy(value)
        for key, value in payload.items()
        if key not in (*_CORE_DECISION_PAYLOAD_FIELDS, *_ADVISE_DERIVED_PAYLOAD_FIELDS, "status")
    }
    source_effect_payload["core_reported_status"] = payload.get("status")
    return cast(
        CoreProjectedTransactionEffects,
        CoreProjectedTransactionEffects.model_validate(source_effect_payload),
    )


def extract_core_decision_compatibility_snapshot(
    payload: dict[str, Any],
) -> CoreDecisionCompatibilitySnapshot:
    return CoreDecisionCompatibilitySnapshot(
        reported_status=payload.get("status") if isinstance(payload.get("status"), str) else None,
        suitability=_dict_or_none(payload.get("suitability")),
        gate_decision=_dict_or_none(payload.get("gate_decision")),
        proposal_decision_summary=_dict_or_none(payload.get("proposal_decision_summary")),
        proposal_alternatives=_dict_or_none(payload.get("proposal_alternatives")),
        drift_analysis=_dict_or_none(payload.get("drift_analysis")),
    )


def build_advise_owned_proposal_result_from_source_effects(
    *,
    request: ProposalSimulateRequest,
    source_effects: CoreProjectedTransactionEffects,
    compatibility_snapshot: CoreDecisionCompatibilitySnapshot,
    policy_context: dict[str, object] | None,
) -> ProposalResult:
    result_status = _advise_status_from_source_effects(source_effects)
    decision_support = build_simulation_decision_support(
        portfolio=request.portfolio_snapshot,
        market_data=request.market_data_snapshot,
        shelf=request.shelf_entries,
        options=request.options,
        diagnostics=source_effects.diagnostics,
        before=source_effects.before,
        after=source_effects.after_simulated,
        intent_plan=_intent_plan_from_source_effects(
            request=request,
            source_effects=source_effects,
        ),
        final_status=result_status,
        rule_results=source_effects.rule_results,
        reference_model=request.reference_model,
        policy_context=policy_context,
    )
    explanation = _advise_source_effect_explanation(
        source_effects=source_effects,
        compatibility_snapshot=compatibility_snapshot,
        advise_status=result_status,
        advise_suitability=decision_support.suitability,
        advise_gate_decision=decision_support.gate_decision,
    )

    return ProposalResult(
        proposal_run_id=source_effects.proposal_run_id,
        correlation_id=source_effects.correlation_id,
        status=result_status,
        before=source_effects.before,
        intents=source_effects.intents,
        after_simulated=source_effects.after_simulated,
        reconciliation=source_effects.reconciliation,
        rule_results=source_effects.rule_results,
        explanation=explanation,
        diagnostics=source_effects.diagnostics,
        drift_analysis=decision_support.drift_analysis,
        suitability=decision_support.suitability,
        gate_decision=decision_support.gate_decision,
        allocation_lens=source_effects.allocation_lens,
        lineage=source_effects.lineage,
    )


def _advise_status_from_source_effects(
    source_effects: CoreProjectedTransactionEffects,
) -> Literal["READY", "BLOCKED", "PENDING_REVIEW"]:
    if (
        source_effects.reconciliation is not None
        and source_effects.reconciliation.status == "MISMATCH"
    ):
        return "BLOCKED"
    return cast(
        Literal["READY", "BLOCKED", "PENDING_REVIEW"],
        derive_status_from_rules(source_effects.rule_results),
    )


def _intent_plan_from_source_effects(
    *,
    request: ProposalSimulateRequest,
    source_effects: CoreProjectedTransactionEffects,
) -> SimulationIntentPlan:
    return SimulationIntentPlan(
        after_portfolio=request.portfolio_snapshot,
        cash_flows=[ProposedCashFlow.model_validate(item) for item in request.proposed_cash_flows],
        trades=[ProposedTrade.model_validate(item) for item in request.proposed_trades],
        intents=list(source_effects.intents),
        hard_failures=[],
        force_pending_review=False,
    )


def _advise_source_effect_explanation(
    *,
    source_effects: CoreProjectedTransactionEffects,
    compatibility_snapshot: CoreDecisionCompatibilitySnapshot,
    advise_status: Literal["READY", "BLOCKED", "PENDING_REVIEW"],
    advise_suitability: SuitabilityResult | None,
    advise_gate_decision: GateDecision | None,
) -> dict[str, Any]:
    explanation = deepcopy(source_effects.explanation)
    explanation["core_projected_transaction_effects"] = {
        "source_service": "lotus-core",
        "contract_version": source_effects.lineage.simulation_contract_version,
        "source_effects_hash": hash_canonical_payload(_source_effect_hash_payload(source_effects)),
        "request_hash": source_effects.lineage.request_hash,
        "portfolio_snapshot_id": source_effects.lineage.portfolio_snapshot_id,
        "market_data_snapshot_id": source_effects.lineage.market_data_snapshot_id,
        "core_reported_status": source_effects.core_reported_status,
        "core_reported_status_authoritative": False,
        "advise_calculation_version": ADVISE_DECISION_CALCULATION_VERSION,
    }
    if compatibility_snapshot.has_core_decision_payload():
        explanation["non_authoritative_core_decisions"] = compatibility_snapshot.model_dump(
            mode="json",
            exclude_none=True,
        )
        explanation["core_decision_parity"] = _core_decision_parity_report(
            compatibility_snapshot=compatibility_snapshot,
            advise_status=advise_status,
            advise_suitability=advise_suitability,
            advise_gate_decision=advise_gate_decision,
        )
    return explanation


def _core_decision_parity_report(
    *,
    compatibility_snapshot: CoreDecisionCompatibilitySnapshot,
    advise_status: Literal["READY", "BLOCKED", "PENDING_REVIEW"],
    advise_suitability: SuitabilityResult | None,
    advise_gate_decision: GateDecision | None,
) -> dict[str, Any]:
    mismatches: list[dict[str, str | None]] = []
    compared_fields: list[str] = []

    _append_parity_mismatch(
        mismatches=mismatches,
        compared_fields=compared_fields,
        field="status",
        core_value=compatibility_snapshot.reported_status,
        advise_value=advise_status,
    )
    _compare_suitability_parity(
        mismatches=mismatches,
        compared_fields=compared_fields,
        core_suitability=compatibility_snapshot.suitability,
        advise_suitability=advise_suitability,
    )
    _compare_gate_parity(
        mismatches=mismatches,
        compared_fields=compared_fields,
        core_gate=compatibility_snapshot.gate_decision,
        advise_gate_decision=advise_gate_decision,
    )

    return {
        "status": "MISMATCH" if mismatches else "MATCH",
        "compared_fields": compared_fields,
        "mismatches": mismatches,
        "core_decisions_authoritative": False,
    }


def _compare_suitability_parity(
    *,
    mismatches: list[dict[str, str | None]],
    compared_fields: list[str],
    core_suitability: dict[str, Any] | None,
    advise_suitability: SuitabilityResult | None,
) -> None:
    if core_suitability is None:
        return
    summary = core_suitability.get("summary")
    if isinstance(summary, dict):
        _append_parity_mismatch(
            mismatches=mismatches,
            compared_fields=compared_fields,
            field="suitability.summary.new_count",
            core_value=_string_value(summary.get("new_count")),
            advise_value=_string_value(
                advise_suitability.summary.new_count if advise_suitability is not None else None
            ),
        )
        _append_parity_mismatch(
            mismatches=mismatches,
            compared_fields=compared_fields,
            field="suitability.summary.persistent_count",
            core_value=_string_value(summary.get("persistent_count")),
            advise_value=_string_value(
                advise_suitability.summary.persistent_count
                if advise_suitability is not None
                else None
            ),
        )
    _append_parity_mismatch(
        mismatches=mismatches,
        compared_fields=compared_fields,
        field="suitability.recommended_gate",
        core_value=_string_value(core_suitability.get("recommended_gate")),
        advise_value=advise_suitability.recommended_gate
        if advise_suitability is not None
        else None,
    )


def _compare_gate_parity(
    *,
    mismatches: list[dict[str, str | None]],
    compared_fields: list[str],
    core_gate: dict[str, Any] | None,
    advise_gate_decision: GateDecision | None,
) -> None:
    if core_gate is None:
        return
    _append_parity_mismatch(
        mismatches=mismatches,
        compared_fields=compared_fields,
        field="gate_decision.gate",
        core_value=_string_value(core_gate.get("gate")),
        advise_value=advise_gate_decision.gate if advise_gate_decision is not None else None,
    )
    _append_parity_mismatch(
        mismatches=mismatches,
        compared_fields=compared_fields,
        field="gate_decision.recommended_next_step",
        core_value=_string_value(core_gate.get("recommended_next_step")),
        advise_value=(
            advise_gate_decision.recommended_next_step if advise_gate_decision is not None else None
        ),
    )


def _append_parity_mismatch(
    *,
    mismatches: list[dict[str, str | None]],
    compared_fields: list[str],
    field: str,
    core_value: str | None,
    advise_value: str | None,
) -> None:
    if core_value is None:
        return
    compared_fields.append(field)
    if core_value != advise_value:
        mismatches.append(
            {
                "field": field,
                "core_value": core_value,
                "advise_value": advise_value,
            }
        )


def _string_value(value: object) -> str | None:
    return None if value is None else str(value)


def _source_effect_hash_payload(
    source_effects: CoreProjectedTransactionEffects,
) -> dict[str, Any]:
    payload = cast(dict[str, Any], source_effects.model_dump(mode="json", by_alias=False))
    payload.pop("core_reported_status", None)
    return payload


def _dict_or_none(value: object) -> dict[str, Any] | None:
    return cast(dict[str, Any], deepcopy(value)) if isinstance(value, dict) else None


__all__ = [
    "ADVISE_DECISION_CALCULATION_VERSION",
    "CoreDecisionCompatibilitySnapshot",
    "CoreProjectedTransactionEffects",
    "build_advise_owned_proposal_result_from_source_effects",
    "extract_core_decision_compatibility_snapshot",
    "map_core_payload_to_projected_transaction_effects",
]
