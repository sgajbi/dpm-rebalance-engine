from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

import src.core.proposals.create_command as proposal_create_command_module
import src.core.proposals.service as proposal_service_module
import src.core.proposals.service_async_facade as proposal_service_async_facade_module
import src.core.proposals.service_async_operations as proposal_service_async_module
import src.core.proposals.service_command_operations as proposal_service_command_module
import src.core.proposals.service_delivery_operations as proposal_service_delivery_module
import src.core.proposals.service_narrative_operations as proposal_service_narrative_module
import src.core.proposals.service_operation_registry as proposal_service_operation_registry_module
import src.core.proposals.service_read_facade as proposal_service_read_facade_module
import src.core.proposals.service_read_operations as proposal_service_read_module
from src.core.advisory.narrative_review_models import ProposalNarrativeReviewRequest
from src.core.advisory_engine import run_proposal_simulation
from src.core.common.canonical import hash_canonical_payload
from src.core.proposals.command_validation import resolve_proposal_approval_transition
from src.core.proposals.context import ProposalContextResolutionError
from src.core.proposals.context_ports import configure_proposal_stateful_context_resolver
from src.core.proposals.models import (
    ProposalApprovalRecordData,
    ProposalApprovalRequest,
    ProposalCreateRequest,
    ProposalExecutionHandoffRequest,
    ProposalExecutionUpdateRequest,
    ProposalIdempotencyRecord,
    ProposalRecord,
    ProposalStateTransitionRequest,
    ProposalVersionRecord,
    ProposalVersionRequest,
    ProposalWorkflowEventRecord,
)
from src.core.proposals.replay_views import build_create_response_from_replay_referents
from src.core.proposals.service import (
    ProposalIdempotencyConflictError,
    ProposalLifecycleError,
    ProposalNotFoundError,
    ProposalStateConflictError,
    ProposalTransitionError,
    ProposalValidationError,
    ProposalWorkflowService,
)
from src.infrastructure.proposals.in_memory import InMemoryProposalRepository
from tests.shared.stateful_context_builders import build_resolved_stateful_context


class CountingListEventsRepository(InMemoryProposalRepository):
    def __init__(self) -> None:
        super().__init__()
        self.list_events_calls = 0

    def list_events(self, *, proposal_id: str) -> list[ProposalWorkflowEventRecord]:
        self.list_events_calls += 1
        return super().list_events(proposal_id=proposal_id)


class CountingLineageRepository(InMemoryProposalRepository):
    def __init__(self) -> None:
        super().__init__()
        self.get_version_calls = 0
        self.list_versions_calls = 0

    def get_version(self, *, proposal_id: str, version_no: int) -> ProposalVersionRecord | None:
        self.get_version_calls += 1
        return super().get_version(proposal_id=proposal_id, version_no=version_no)

    def list_versions(self, *, proposal_id: str) -> list[ProposalVersionRecord]:
        self.list_versions_calls += 1
        return super().list_versions(proposal_id=proposal_id)


def test_service_delegates_async_operations_to_focused_module() -> None:
    service_text = Path(proposal_service_module.__file__).read_text(encoding="utf-8")
    async_facade_text = Path(proposal_service_async_facade_module.__file__).read_text(
        encoding="utf-8"
    )
    registry_text = Path(proposal_service_operation_registry_module.__file__).read_text(
        encoding="utf-8"
    )
    async_text = Path(proposal_service_async_module.__file__).read_text(encoding="utf-8")

    assert "build_proposal_workflow_operation_registry" in service_text
    assert "ProposalWorkflowAsyncFacadeMixin" in service_text
    assert "ProposalWorkflowAsyncOperations" in registry_text
    assert "def accept_create_proposal_async_submission(" not in service_text
    assert "def execute_create_version_async(" not in service_text
    assert "def recover_async_operations(" not in service_text
    assert "def accept_create_proposal_async_submission(" in async_facade_text
    assert "def execute_create_version_async(" in async_facade_text
    assert "def recover_async_operations(" in async_facade_text
    for helper_name in (
        "accept_create_proposal_async_submission_command",
        "accept_create_version_async_submission_command",
        "execute_create_proposal_async_operation",
        "execute_create_version_async_operation",
        "recover_async_operation_batch",
        "build_async_operation_status_view",
        "build_async_operation_replay_view",
        "build_async_operation_correlation_view",
    ):
        assert helper_name not in service_text
        assert helper_name in async_text


def test_service_delegates_command_operations_to_focused_module() -> None:
    service_text = Path(proposal_service_module.__file__).read_text(encoding="utf-8")
    registry_text = Path(proposal_service_operation_registry_module.__file__).read_text(
        encoding="utf-8"
    )
    command_text = Path(proposal_service_command_module.__file__).read_text(encoding="utf-8")

    assert "build_proposal_workflow_operation_registry" in service_text
    assert "ProposalWorkflowCommandOperations" in registry_text
    for import_name in (
        "from src.core.proposals.create_command import",
        "from src.core.proposals.lifecycle_command import",
        "from src.core.proposals.version_command import",
    ):
        assert import_name not in service_text
        assert import_name in command_text
    for helper_name in (
        "create_proposal_command",
        "create_proposal_version",
        "transition_proposal_state",
        "record_proposal_approval",
    ):
        assert helper_name not in service_text
        assert helper_name in command_text


def test_service_delegates_delivery_operations_to_focused_module() -> None:
    service_text = Path(proposal_service_module.__file__).read_text(encoding="utf-8")
    registry_text = Path(proposal_service_operation_registry_module.__file__).read_text(
        encoding="utf-8"
    )
    delivery_text = Path(proposal_service_delivery_module.__file__).read_text(encoding="utf-8")

    assert "build_proposal_workflow_operation_registry" in service_text
    assert "ProposalWorkflowDeliveryOperations" in registry_text
    for helper_name in (
        "request_proposal_execution_handoff",
        "record_proposal_execution_update",
        "build_execution_status_view",
        "build_delivery_summary_view",
        "build_delivery_history_view",
        "TERMINAL_STATES",
    ):
        assert helper_name not in service_text
        assert helper_name in delivery_text


def test_service_delegates_narrative_operations_to_focused_module() -> None:
    service_text = Path(proposal_service_module.__file__).read_text(encoding="utf-8")
    registry_text = Path(proposal_service_operation_registry_module.__file__).read_text(
        encoding="utf-8"
    )
    narrative_text = Path(proposal_service_narrative_module.__file__).read_text(encoding="utf-8")

    assert "build_proposal_workflow_operation_registry" in service_text
    assert "ProposalWorkflowNarrativeOperations" in registry_text
    assert "from src.core.proposals.narrative_views import" not in service_text
    assert "from src.core.proposals.report_request_command import" not in service_text
    for helper_name in (
        "build_narrative_view",
        "regenerate_narrative_view",
        "record_proposal_report_request",
    ):
        assert helper_name not in service_text
        assert helper_name in narrative_text
    assert "record_narrative_review" in narrative_text


def test_service_delegates_read_operations_to_focused_module() -> None:
    service_text = Path(proposal_service_module.__file__).read_text(encoding="utf-8")
    registry_text = Path(proposal_service_operation_registry_module.__file__).read_text(
        encoding="utf-8"
    )
    read_facade_text = Path(proposal_service_read_facade_module.__file__).read_text(
        encoding="utf-8"
    )
    read_text = Path(proposal_service_read_module.__file__).read_text(encoding="utf-8")

    assert "build_proposal_workflow_operation_registry" in service_text
    assert "ProposalWorkflowReadFacadeMixin" in service_text
    assert "ProposalWorkflowReadOperations" in registry_text
    assert "def get_proposal(" not in service_text
    assert "def list_proposals(" not in service_text
    assert "def get_version_replay(" not in service_text
    assert "def get_proposal(" in read_facade_text
    assert "def list_proposals(" in read_facade_text
    assert "def get_version_replay(" in read_facade_text
    for import_name in (
        "from src.core.proposals.activity_views import",
        "from src.core.proposals.read_views import",
        "from src.core.proposals.replay_views import",
    ):
        assert import_name not in service_text
        assert import_name in read_text
    for helper_name in (
        "build_proposal_detail_view",
        "build_proposal_list_view",
        "build_proposal_version_replay_view",
    ):
        assert helper_name not in service_text
        assert helper_name in read_text


def test_service_delegates_operation_wiring_to_registry_module() -> None:
    service_text = Path(proposal_service_module.__file__).read_text(encoding="utf-8")
    registry_text = Path(proposal_service_operation_registry_module.__file__).read_text(
        encoding="utf-8"
    )

    assert "build_proposal_workflow_operation_registry" in service_text
    assert "ProposalWorkflowOperationRegistry" in registry_text
    assert "ProposalWorkflowCommandOperations" not in service_text
    assert "ProposalWorkflowAsyncOperations" not in service_text
    assert "ProposalWorkflowDeliveryOperations" not in service_text
    assert "ProposalWorkflowNarrativeOperations" not in service_text
    assert "ProposalWorkflowReadOperations" not in service_text
    for operation_owner in (
        "ProposalWorkflowCommandOperations",
        "ProposalWorkflowAsyncOperations",
        "ProposalWorkflowDeliveryOperations",
        "ProposalWorkflowNarrativeOperations",
        "ProposalWorkflowReadOperations",
    ):
        assert operation_owner in registry_text


def _risk_enriched_result(result):  # noqa: ANN001
    result.explanation["risk_lens"] = {
        "source_service": "lotus-risk",
        "input_mode": "simulation",
        "risk_proxy": {"hhi_current": 5200.0, "hhi_proposed": 6800.0, "hhi_delta": 1600.0},
        "single_position_concentration": {
            "top_position_weight_current": 0.5,
            "top_position_weight_proposed": 0.6,
        },
        "issuer_concentration": {
            "hhi_current": 5200.0,
            "hhi_proposed": 5800.0,
        },
    }
    return result


def _simulate_request(portfolio_id: str = "pf_service_1") -> dict:
    return {
        "portfolio_snapshot": {
            "portfolio_id": portfolio_id,
            "base_currency": "USD",
            "positions": [{"instrument_id": "EQ_OLD", "quantity": "10"}],
            "cash_balances": [{"currency": "USD", "amount": "1000"}],
        },
        "market_data_snapshot": {
            "prices": [
                {"instrument_id": "EQ_OLD", "price": "100", "currency": "USD"},
                {"instrument_id": "EQ_NEW", "price": "50", "currency": "USD"},
            ],
            "fx_rates": [],
        },
        "shelf_entries": [
            {"instrument_id": "EQ_OLD", "status": "APPROVED"},
            {"instrument_id": "EQ_NEW", "status": "APPROVED"},
        ],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [{"currency": "USD", "amount": "100"}],
        "proposed_trades": [{"side": "BUY", "instrument_id": "EQ_NEW", "quantity": "2"}],
    }


def _create_payload() -> ProposalCreateRequest:
    return ProposalCreateRequest(
        created_by="advisor_service",
        simulate_request=_simulate_request(),
        metadata={"title": "Service test"},
    )


def test_create_proposal_redacts_sensitive_context_resolution_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    def _raise_sensitive_context_error(_payload):
        raise ProposalContextResolutionError(
            "raw payload includes Authorization Bearer token material"
        )

    monkeypatch.setattr(
        proposal_create_command_module,
        "resolve_create_request",
        _raise_sensitive_context_error,
    )

    with pytest.raises(ProposalValidationError) as exc:
        service.create_proposal(
            payload=_create_payload(),
            idempotency_key="prop-sensitive-context",
            correlation_id="corr-sensitive-context",
        )

    assert str(exc.value) == "PROPOSAL_CONTEXT_RESOLUTION_FAILED"
    assert "token" not in str(exc.value).lower()


def _create_payload_with_narrative(portfolio_id: str) -> ProposalCreateRequest:
    simulate_request = _simulate_request(portfolio_id)
    simulate_request["narrative_request"] = {
        "audience": "ADVISOR_REVIEW",
        "jurisdiction": "SG",
        "client_audience": "ADVISOR_REVIEW",
        "sections": ["EXECUTIVE_SUMMARY", "RISK_AND_CONCENTRATION"],
        "requested_by": "advisor_service",
    }
    return ProposalCreateRequest(
        created_by="advisor_service",
        simulate_request=simulate_request,
        metadata={"title": "Narrative review service test", "jurisdiction": "SG"},
    )


def _stateful_narrative_payload_without_product_constraints() -> ProposalCreateRequest:
    return ProposalCreateRequest(
        created_by="advisor_service",
        input_mode="stateful",
        stateful_input={
            "portfolio_id": "pf_service_stateful_replay",
            "as_of": "2026-04-10",
            "narrative_request": {
                "audience": "ADVISOR_REVIEW",
                "generation_mode": "DETERMINISTIC_TEMPLATE",
                "jurisdiction": "SG",
                "client_audience": "ADVISOR_REVIEW",
                "sections": ["EXECUTIVE_SUMMARY", "RISK_AND_CONCENTRATION"],
                "requested_by": "advisor_service",
            },
        },
        metadata={"title": "Stateful narrative replay", "jurisdiction": "SG"},
    )


def _resolved_stateful_context_for_replay(stateful_input):
    return build_resolved_stateful_context(
        stateful_input.portfolio_id,
        stateful_input.as_of,
        positions=[{"instrument_id": "EQ_OLD", "quantity": "10"}],
        prices=[
            {"instrument_id": "EQ_OLD", "price": "100", "currency": "USD"},
            {"instrument_id": "EQ_NEW", "price": "50", "currency": "USD"},
        ],
        shelf_entries=[
            {"instrument_id": "EQ_OLD", "status": "APPROVED"},
            {"instrument_id": "EQ_NEW", "status": "APPROVED"},
        ],
        proposed_trades=[{"side": "BUY", "instrument_id": "EQ_NEW", "quantity": "2"}],
        include_context_ids=False,
    )


def _replace_create_idempotency_hash_with_legacy_value(
    *,
    repository: InMemoryProposalRepository,
    idempotency_key: str,
    proposal_id: str,
    source_resolved_product_types: list[str],
) -> None:
    legacy_request_hash = "sha256:legacy-narrative-product-type-replay"
    version = repository.get_version(proposal_id=proposal_id, version_no=1)
    idempotency = repository.get_idempotency(idempotency_key=idempotency_key)
    assert version is not None
    assert idempotency is not None

    artifact = deepcopy(version.artifact_json)
    narrative_context = artifact["proposal_narrative"]["narrative_policy"]["context"]
    narrative_context["product_types"] = source_resolved_product_types
    repository.create_version(
        version.model_copy(
            update={
                "request_hash": legacy_request_hash,
                "artifact_json": artifact,
            }
        )
    )
    repository.save_idempotency(
        idempotency.model_copy(update={"request_hash": legacy_request_hash})
    )


@pytest.fixture(autouse=True)
def reset_upstream_authority_overrides(monkeypatch):
    monkeypatch.delenv("LOTUS_CORE_BASE_URL", raising=False)
    monkeypatch.delenv("LOTUS_RISK_BASE_URL", raising=False)
    monkeypatch.delenv("LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK", raising=False)

    def _simulate_with_lotus_core(**kwargs):
        request = kwargs["request"]
        return run_proposal_simulation(
            portfolio=request.portfolio_snapshot,
            market_data=request.market_data_snapshot,
            shelf=request.shelf_entries,
            options=request.options,
            proposed_cash_flows=request.proposed_cash_flows,
            proposed_trades=request.proposed_trades,
            reference_model=request.reference_model,
            request_hash=kwargs["request_hash"],
            idempotency_key=kwargs["idempotency_key"],
            correlation_id=kwargs["correlation_id"],
            simulation_contract_version="advisory-simulation.v1",
            policy_context=kwargs.get("policy_context"),
        )

    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        _simulate_with_lotus_core,
    )


def test_service_version_payload_is_immutable_from_caller_mutation():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-1",
        correlation_id="corr-service-1",
    )
    proposal_id = created.proposal.proposal_id

    version_one = service.get_version(proposal_id=proposal_id, version_no=1, include_evidence=True)
    version_one.evidence_bundle["hashes"]["artifact_hash"] = "tampered"

    version_again = service.get_version(
        proposal_id=proposal_id, version_no=1, include_evidence=True
    )
    assert version_again.evidence_bundle["hashes"]["artifact_hash"].startswith("sha256:")


def test_service_create_proposal_normalizes_required_idempotency_key():
    repository = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repository)

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="  service-idem-normalized  ",
        correlation_id="corr-service-normalized",
    )

    assert repository.get_idempotency(idempotency_key="service-idem-normalized") is not None
    assert repository.get_idempotency(idempotency_key="  service-idem-normalized  ") is None
    assert created.proposal.proposal_id.startswith("pp_")

    with pytest.raises(ProposalValidationError, match="IDEMPOTENCY_KEY_REQUIRED"):
        service.create_proposal(
            payload=_create_payload(),
            idempotency_key="   ",
            correlation_id="corr-service-blank-idem",
        )


def test_service_create_proposal_uses_upstream_simulation_authority_when_available(
    monkeypatch,
):
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    def _simulate_with_lotus_core(**kwargs):
        request = kwargs["request"]
        return run_proposal_simulation(
            portfolio=request.portfolio_snapshot,
            market_data=request.market_data_snapshot,
            shelf=request.shelf_entries,
            options=request.options,
            proposed_cash_flows=request.proposed_cash_flows,
            proposed_trades=request.proposed_trades,
            reference_model=request.reference_model,
            request_hash=kwargs["request_hash"],
            idempotency_key=kwargs["idempotency_key"],
            correlation_id=kwargs["correlation_id"],
            policy_context=kwargs.get("policy_context"),
        )

    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setattr(
        "src.core.advisory.orchestration.simulate_with_lotus_core",
        _simulate_with_lotus_core,
    )

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-upstream",
        correlation_id="corr-service-upstream",
    )

    authority = created.version.proposal_result.explanation["authority_resolution"]
    assert authority["simulation_authority"] == "lotus_core"
    assert authority["risk_authority"] == "unavailable"


def test_service_create_proposal_persists_decision_summary() -> None:
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-decision-summary-persisted",
        correlation_id="corr-service-decision-summary-persisted",
    )

    summary = created.version.proposal_result.proposal_decision_summary

    assert summary is not None
    assert summary.top_level_status == created.version.proposal_result.status
    assert summary.decision_status
    assert created.version.proposal_result.suitability is not None
    assert created.version.proposal_result.suitability.policy_version
    assert (
        created.version.proposal_result.suitability.policy_version
        == summary.suitability_policy_version
    )


def test_service_create_proposal_persists_proposal_alternatives() -> None:
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=ProposalCreateRequest(
            created_by="advisor_service",
            simulate_request={
                **_simulate_request("pf_service_alt_1"),
                "alternatives_request": {
                    "enabled": True,
                    "objectives": ["LOWER_TURNOVER", "REDUCE_CONCENTRATION"],
                    "include_rejected_candidates": True,
                },
            },
            metadata={"title": "Alternatives proposal"},
        ),
        idempotency_key="service-idem-alt-persisted",
        correlation_id="corr-service-alt-persisted",
    )

    proposal_alternatives = created.version.proposal_result.proposal_alternatives

    assert proposal_alternatives is not None
    assert proposal_alternatives.requested_objectives == [
        "LOWER_TURNOVER",
        "REDUCE_CONCENTRATION",
    ]
    assert len(proposal_alternatives.rejected_candidates) == 2


def test_service_create_proposal_persists_selected_proposal_alternative_into_version_and_artifact(
    monkeypatch,
) -> None:
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())
    monkeypatch.setattr(
        "src.core.advisory.orchestration.enrich_with_lotus_risk",
        lambda **kwargs: _risk_enriched_result(kwargs["proposal_result"]),
    )

    created = service.create_proposal(
        payload=ProposalCreateRequest(
            created_by="advisor_service",
            simulate_request={
                **_simulate_request("pf_service_alt_selected_1"),
                "alternatives_request": {
                    "enabled": True,
                    "objectives": ["LOWER_TURNOVER"],
                    "selected_alternative_id": (
                        "alt_lower_turnover_pf_service_alt_selected_1_eq_new"
                    ),
                    "include_rejected_candidates": True,
                },
            },
            metadata={"title": "Selected alternatives proposal"},
        ),
        idempotency_key="service-idem-alt-selected",
        correlation_id="corr-service-alt-selected",
    )

    proposal_alternatives = created.version.proposal_result.proposal_alternatives

    assert proposal_alternatives is not None
    assert proposal_alternatives.selected_alternative_id == (
        "alt_lower_turnover_pf_service_alt_selected_1_eq_new"
    )
    assert proposal_alternatives.alternatives[0].selected is True
    assert created.version.artifact.proposal_alternatives is not None
    assert created.version.artifact.proposal_alternatives.selected_alternative_id == (
        "alt_lower_turnover_pf_service_alt_selected_1_eq_new"
    )


def test_service_create_proposal_persists_material_change_projection() -> None:
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=ProposalCreateRequest(
            created_by="advisor_service",
            simulate_request={
                "portfolio_snapshot": {
                    "portfolio_id": "pf_service_fx_1",
                    "base_currency": "USD",
                    "positions": [],
                    "cash_balances": [{"currency": "USD", "amount": "1000"}],
                },
                "market_data_snapshot": {
                    "prices": [{"instrument_id": "EUR_EQ_1", "price": "100", "currency": "EUR"}],
                    "fx_rates": [{"pair": "EUR/USD", "rate": "1.2"}],
                },
                "shelf_entries": [
                    {
                        "instrument_id": "EUR_EQ_1",
                        "status": "APPROVED",
                        "issuer_id": "ISS_EUR_1",
                        "liquidity_tier": "L1",
                    }
                ],
                "options": {"enable_proposal_simulation": True},
                "proposed_cash_flows": [],
                "proposed_trades": [{"side": "BUY", "instrument_id": "EUR_EQ_1", "quantity": "1"}],
            },
            metadata={"title": "FX proposal"},
        ),
        idempotency_key="service-idem-fx-material-change",
        correlation_id="corr-service-fx-material-change",
    )

    families = {
        item.family
        for item in created.version.proposal_result.proposal_decision_summary.material_changes
    }
    assert "CURRENCY_EXPOSURE_CHANGE" in families


def test_service_create_proposal_persists_policy_context_for_stateful_requests():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    def _resolved_stateful_context(stateful_input):
        return build_resolved_stateful_context(
            stateful_input.portfolio_id,
            stateful_input.as_of,
        )

    configure_proposal_stateful_context_resolver(_resolved_stateful_context)

    try:
        created = service.create_proposal(
            payload=ProposalCreateRequest(
                created_by="advisor_service",
                input_mode="stateful",
                stateful_input={
                    "portfolio_id": "pf_service_stateful_1",
                    "as_of": "2026-03-25",
                    "household_id": "hh_001",
                    "mandate_id": "mandate_growth_01",
                },
                metadata={"title": "Stateful service test", "jurisdiction": "SG"},
            ),
            idempotency_key="service-idem-stateful-policy",
            correlation_id="corr-service-stateful-policy",
        )
    finally:
        configure_proposal_stateful_context_resolver(None)

    policy_context = created.version.evidence_bundle["context_resolution"][
        "advisory_policy_context"
    ]
    assert policy_context["client_context_status"] == "AVAILABLE"
    assert policy_context["mandate_context_status"] == "AVAILABLE"
    assert policy_context["jurisdiction_context_status"] == "AVAILABLE"
    assert (
        created.version.proposal_result.proposal_decision_summary.client_and_mandate_posture.status
        == "AVAILABLE"
    )


def test_stateful_proposal_replay_allows_source_resolved_narrative_product_types() -> None:
    repository = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repository)
    idempotency_key = "service-idem-stateful-narrative-legacy-products"
    payload = _stateful_narrative_payload_without_product_constraints()

    configure_proposal_stateful_context_resolver(_resolved_stateful_context_for_replay)
    try:
        created = service.create_proposal(
            payload=payload,
            idempotency_key=idempotency_key,
            correlation_id="corr-service-stateful-narrative-legacy-products",
        )
        _replace_create_idempotency_hash_with_legacy_value(
            repository=repository,
            idempotency_key=idempotency_key,
            proposal_id=created.proposal.proposal_id,
            source_resolved_product_types=["BOND", "CASH", "EQUITY", "ETF"],
        )

        replayed = service.create_proposal(
            payload=payload,
            idempotency_key=idempotency_key,
            correlation_id="corr-service-stateful-narrative-legacy-products-replay",
        )
    finally:
        configure_proposal_stateful_context_resolver(None)

    assert replayed.proposal.proposal_id == created.proposal.proposal_id
    assert replayed.version.proposal_version_id == created.version.proposal_version_id


def test_stateful_proposal_replay_rejects_changed_product_type_constraint() -> None:
    repository = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repository)
    idempotency_key = "service-idem-stateful-narrative-product-conflict"
    original_payload = _stateful_narrative_payload_without_product_constraints()
    changed_payload = _stateful_narrative_payload_without_product_constraints()
    changed_payload.stateful_input.narrative_request.product_types = ["EQUITY"]

    configure_proposal_stateful_context_resolver(_resolved_stateful_context_for_replay)
    try:
        created = service.create_proposal(
            payload=original_payload,
            idempotency_key=idempotency_key,
            correlation_id="corr-service-stateful-narrative-product-conflict",
        )
        _replace_create_idempotency_hash_with_legacy_value(
            repository=repository,
            idempotency_key=idempotency_key,
            proposal_id=created.proposal.proposal_id,
            source_resolved_product_types=["BOND", "CASH"],
        )

        with pytest.raises(ProposalIdempotencyConflictError):
            service.create_proposal(
                payload=changed_payload,
                idempotency_key=idempotency_key,
                correlation_id="corr-service-stateful-narrative-product-conflict-replay",
            )
    finally:
        configure_proposal_stateful_context_resolver(None)


def test_service_new_version_recomputes_decision_summary_without_bleeding_forward() -> None:
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-decision-summary-version-1",
        correlation_id="corr-service-decision-summary-version-1",
    )
    proposal_id = created.proposal.proposal_id
    version_one_summary = created.version.proposal_result.proposal_decision_summary

    blocked_request = _simulate_request()
    blocked_request["market_data_snapshot"]["prices"] = [
        {"instrument_id": "EQ_OLD", "price": "100", "currency": "USD"}
    ]
    blocked_version = service.create_version(
        proposal_id=proposal_id,
        payload=ProposalVersionRequest(
            created_by="advisor_service",
            simulate_request=blocked_request,
        ),
        correlation_id="corr-service-decision-summary-version-2",
    )
    version_two_summary = blocked_version.version.proposal_result.proposal_decision_summary

    assert version_one_summary is not None
    assert version_two_summary is not None
    assert version_one_summary.decision_status != version_two_summary.decision_status
    assert version_two_summary.decision_status == "BLOCKED_REMEDIATION_REQUIRED"
    assert version_two_summary.primary_reason_code == "DATA_QUALITY_MISSING_PRICE"


def test_service_request_hash_is_stable_between_legacy_and_stateless_create_contracts():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())
    legacy_payload = ProposalCreateRequest(
        created_by="advisor_service",
        simulate_request=_simulate_request(),
        metadata={"title": "Service test"},
    )
    stateless_payload = ProposalCreateRequest(
        created_by="advisor_service",
        input_mode="stateless",
        stateless_input={"simulate_request": _simulate_request()},
        metadata={"title": "Service test"},
    )

    legacy = service.create_proposal(
        payload=legacy_payload,
        idempotency_key="service-idem-legacy-hash",
        correlation_id="corr-service-legacy-hash",
    )
    stateless = service.create_proposal(
        payload=stateless_payload,
        idempotency_key="service-idem-stateless-hash",
        correlation_id="corr-service-stateless-hash",
    )

    assert legacy.version.request_hash == stateless.version.request_hash
    assert legacy.version.simulation_hash == stateless.version.simulation_hash


def test_service_rejects_version_with_portfolio_context_mismatch():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-2",
        correlation_id="corr-service-2",
    )
    proposal_id = created.proposal.proposal_id

    version_payload = ProposalVersionRequest(
        created_by="advisor_service",
        simulate_request=_simulate_request(portfolio_id="pf_other"),
    )

    try:
        service.create_version(
            proposal_id=proposal_id,
            payload=version_payload,
            correlation_id="corr-version-1",
        )
    except ProposalValidationError as exc:
        assert str(exc) == "PORTFOLIO_CONTEXT_MISMATCH"
    else:
        raise AssertionError("Expected PORTFOLIO_CONTEXT_MISMATCH")


def test_service_rejects_version_when_expected_current_version_mismatches():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-version-conflict",
        correlation_id="corr-service-version-conflict",
    )
    proposal_id = created.proposal.proposal_id

    version_payload = ProposalVersionRequest(
        created_by="advisor_service",
        expected_current_version_no=2,
        simulate_request=_simulate_request(),
    )

    try:
        service.create_version(
            proposal_id=proposal_id,
            payload=version_payload,
            correlation_id="corr-version-conflict",
        )
    except ProposalStateConflictError as exc:
        assert str(exc) == "VERSION_CONFLICT: expected_current_version_no mismatch"
    else:
        raise AssertionError("Expected VERSION_CONFLICT: expected_current_version_no mismatch")


def test_service_rejects_invalid_transition_for_current_state():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-3",
        correlation_id="corr-service-3",
    )

    try:
        service.transition_state(
            proposal_id=created.proposal.proposal_id,
            payload=ProposalStateTransitionRequest(
                event_type="RISK_APPROVED",
                actor_id="risk_1",
                expected_state="DRAFT",
                reason={"comment": "invalid"},
            ),
        )
    except ProposalTransitionError as exc:
        assert str(exc) == "INVALID_TRANSITION"
    else:
        raise AssertionError("Expected INVALID_TRANSITION")


def test_service_allows_cancel_from_non_terminal_state():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-4",
        correlation_id="corr-service-4",
    )
    result = service.transition_state(
        proposal_id=created.proposal.proposal_id,
        payload=ProposalStateTransitionRequest(
            event_type="CANCELLED",
            actor_id="advisor_service",
            expected_state="DRAFT",
            reason={"comment": "client withdrew"},
        ),
    )
    assert result.current_state == "CANCELLED"


def test_service_rejects_new_version_for_terminal_state():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-5",
        correlation_id="corr-service-5",
    )
    service.transition_state(
        proposal_id=created.proposal.proposal_id,
        payload=ProposalStateTransitionRequest(
            event_type="CANCELLED",
            actor_id="advisor_service",
            expected_state="DRAFT",
            reason={},
        ),
    )

    try:
        service.create_version(
            proposal_id=created.proposal.proposal_id,
            payload=ProposalVersionRequest(
                created_by="advisor_service",
                simulate_request=_simulate_request(),
            ),
            correlation_id="corr-service-5-version",
        )
    except ProposalValidationError as exc:
        assert str(exc) == "PROPOSAL_TERMINAL_STATE: cannot create version"
    else:
        raise AssertionError("Expected PROPOSAL_TERMINAL_STATE")


def test_service_records_rejected_client_consent_path():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())
    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-6",
        correlation_id="corr-service-6",
    )

    service.transition_state(
        proposal_id=created.proposal.proposal_id,
        payload=ProposalStateTransitionRequest(
            event_type="SUBMITTED_FOR_RISK_REVIEW",
            actor_id="advisor_service",
            expected_state="DRAFT",
            reason={},
        ),
    )
    service.record_approval(
        proposal_id=created.proposal.proposal_id,
        payload=ProposalApprovalRequest(
            approval_type="RISK",
            approved=True,
            actor_id="risk_officer",
            expected_state="RISK_REVIEW",
            details={},
        ),
    )
    rejected = service.record_approval(
        proposal_id=created.proposal.proposal_id,
        payload=ProposalApprovalRequest(
            approval_type="CLIENT_CONSENT",
            approved=False,
            actor_id="client",
            expected_state="AWAITING_CLIENT_CONSENT",
            details={"reason": "declined"},
        ),
    )

    assert rejected.current_state == "REJECTED"
    assert rejected.latest_workflow_event.event_type == "REJECTED"


def test_service_get_proposal_and_version_raise_not_found_paths():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    try:
        service.get_proposal(proposal_id="pp_missing", include_evidence=True)
    except ProposalNotFoundError as exc:
        assert str(exc) == "PROPOSAL_NOT_FOUND"
    else:
        raise AssertionError("Expected PROPOSAL_NOT_FOUND")

    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    now = datetime.now(timezone.utc)
    repo.create_proposal(
        ProposalRecord(
            proposal_id="pp_only_proposal",
            portfolio_id="pf_service_1",
            mandate_id=None,
            jurisdiction=None,
            created_by="advisor",
            created_at=now,
            last_event_at=now,
            current_state="DRAFT",
            current_version_no=1,
            title=None,
            advisor_notes=None,
        )
    )
    try:
        service.get_proposal(proposal_id="pp_only_proposal", include_evidence=True)
    except ProposalNotFoundError as exc:
        assert str(exc) == "PROPOSAL_VERSION_NOT_FOUND"
    else:
        raise AssertionError("Expected PROPOSAL_VERSION_NOT_FOUND")


@pytest.mark.parametrize(
    ("service_method_name", "view_function_name"),
    [
        ("get_workflow_timeline", "build_workflow_timeline_view"),
    ],
)
def test_service_delegates_activity_views(
    monkeypatch,
    service_method_name: str,
    view_function_name: str,
):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_view(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(proposal_service_read_module, view_function_name, fake_view)

    response = getattr(service, service_method_name)(proposal_id="pp_activity_view")

    assert response is sentinel
    assert captured == {
        "repository": repo,
        "proposal_id": "pp_activity_view",
    }


@pytest.mark.parametrize(
    ("service_method_name", "view_function_name"),
    [
        ("get_execution_status", "build_execution_status_view"),
        ("get_delivery_summary", "build_delivery_summary_view"),
        ("get_delivery_history", "build_delivery_history_view"),
    ],
)
def test_service_delegates_delivery_activity_views(
    monkeypatch,
    service_method_name: str,
    view_function_name: str,
):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_view(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(proposal_service_delivery_module, view_function_name, fake_view)

    response = getattr(service, service_method_name)(proposal_id="pp_delivery_activity_view")

    assert response is sentinel
    assert captured == {
        "repository": repo,
        "proposal_id": "pp_delivery_activity_view",
    }


@pytest.mark.parametrize(
    ("service_method_name", "view_function_name", "call_kwargs", "expected_kwargs"),
    [
        (
            "get_proposal",
            "build_proposal_detail_view",
            {"proposal_id": "pp_detail_view", "include_evidence": False},
            {"proposal_id": "pp_detail_view", "include_evidence": False},
        ),
        (
            "get_approvals",
            "build_proposal_approvals_view",
            {"proposal_id": "pp_approval_view"},
            {"proposal_id": "pp_approval_view"},
        ),
        (
            "get_lineage",
            "build_proposal_lineage_view",
            {"proposal_id": "pp_lineage_view"},
            {"proposal_id": "pp_lineage_view"},
        ),
        (
            "get_idempotency_lookup",
            "build_idempotency_lookup_view",
            {"idempotency_key": "idem-read-view"},
            {"idempotency_key": "idem-read-view"},
        ),
        (
            "get_version",
            "build_proposal_version_view",
            {
                "proposal_id": "pp_version_view",
                "version_no": 3,
                "include_evidence": False,
            },
            {
                "proposal_id": "pp_version_view",
                "version_no": 3,
                "include_evidence": False,
            },
        ),
    ],
)
def test_service_delegates_simple_read_views(
    monkeypatch,
    service_method_name: str,
    view_function_name: str,
    call_kwargs: dict[str, object],
    expected_kwargs: dict[str, object],
):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_view(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(proposal_service_read_module, view_function_name, fake_view)

    response = getattr(service, service_method_name)(**call_kwargs)

    assert response is sentinel
    assert captured == {"repository": repo, **expected_kwargs}


def test_service_delegates_proposal_list_view(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    created_from = datetime(2026, 1, 2, tzinfo=timezone.utc)
    created_to = datetime(2026, 1, 3, tzinfo=timezone.utc)
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_build_proposal_list_view(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        proposal_service_read_module,
        "build_proposal_list_view",
        fake_build_proposal_list_view,
    )

    response = service.list_proposals(
        portfolio_id="pf_read_view",
        state="DRAFT",
        created_by="advisor",
        created_from=created_from,
        created_to=created_to,
        limit=25,
        cursor="cursor-read-view",
    )

    assert response is sentinel
    assert captured == {
        "repository": repo,
        "portfolio_id": "pf_read_view",
        "state": "DRAFT",
        "created_by": "advisor",
        "created_from": created_from,
        "created_to": created_to,
        "limit": 25,
        "cursor": "cursor-read-view",
    }


def test_service_delegates_version_replay_view(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_build_proposal_version_replay_view(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        proposal_service_read_module,
        "build_proposal_version_replay_view",
        fake_build_proposal_version_replay_view,
    )

    response = service.get_version_replay(proposal_id="pp_replay_view", version_no=5)

    assert response is sentinel
    assert captured == {
        "repository": repo,
        "proposal_id": "pp_replay_view",
        "version_no": 5,
    }


def test_service_delegates_create_version_command(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(
        repository=repo,
        store_evidence_bundle=False,
        require_proposal_simulation_flag=False,
        allow_portfolio_id_change_on_new_version=True,
    )
    payload = ProposalVersionRequest(
        created_by="advisor_service",
        simulate_request=_simulate_request(),
    )
    replay_lineage = {"source": "async-replay"}
    context_resolution_override = {"source": "test-context"}
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_create_proposal_version(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        proposal_service_command_module,
        "create_proposal_version",
        fake_create_proposal_version,
    )

    response = service.create_version(
        proposal_id="pp_create_version_delegate",
        payload=payload,
        correlation_id="corr-create-version-delegate",
        replay_lineage=replay_lineage,
        context_resolution_override=context_resolution_override,
    )

    assert response is sentinel
    assert captured["repository"] is repo
    assert captured["proposal_id"] == "pp_create_version_delegate"
    assert captured["payload"] is payload
    assert captured["correlation_id"] == "corr-create-version-delegate"
    assert captured["replay_lineage"] is replay_lineage
    assert captured["context_resolution_override"] is context_resolution_override
    assert captured["store_evidence_bundle"] is False
    assert captured["require_proposal_simulation_flag"] is False
    assert captured["allow_portfolio_id_change_on_new_version"] is True
    assert callable(captured["utc_now"])


def test_service_delegates_create_proposal_command(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(
        repository=repo,
        store_evidence_bundle=False,
        require_proposal_simulation_flag=False,
    )
    payload = _create_payload()
    replay_lineage = {"source": "create-replay"}
    context_resolution_override = {"source": "create-context"}
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_create_proposal_command(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        proposal_service_command_module,
        "create_proposal_command",
        fake_create_proposal_command,
    )

    response = service.create_proposal(
        payload=payload,
        idempotency_key="idem-create-delegate",
        correlation_id="corr-create-delegate",
        lifecycle_origin="WORKSPACE_HANDOFF",
        source_workspace_id="workspace-create-delegate",
        replay_lineage=replay_lineage,
        context_resolution_override=context_resolution_override,
    )

    assert response is sentinel
    assert captured["repository"] is repo
    assert captured["payload"] is payload
    assert captured["idempotency_key"] == "idem-create-delegate"
    assert captured["correlation_id"] == "corr-create-delegate"
    assert captured["lifecycle_origin"] == "WORKSPACE_HANDOFF"
    assert captured["source_workspace_id"] == "workspace-create-delegate"
    assert captured["replay_lineage"] is replay_lineage
    assert captured["context_resolution_override"] is context_resolution_override
    assert captured["store_evidence_bundle"] is False
    assert captured["require_proposal_simulation_flag"] is False
    assert callable(captured["utc_now"])


def test_service_delegates_create_proposal_async_submission(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    payload = _create_payload()
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_accept_create_proposal_async_submission_command(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        proposal_service_async_module,
        "accept_create_proposal_async_submission_command",
        fake_accept_create_proposal_async_submission_command,
    )

    response = service.accept_create_proposal_async_submission(
        payload=payload,
        idempotency_key="idem-create-async-delegate",
        correlation_id="corr-create-async-delegate",
    )

    assert response is sentinel
    assert captured["repository"] is repo
    assert captured["payload"] is payload
    assert captured["idempotency_key"] == "idem-create-async-delegate"
    assert captured["correlation_id"] == "corr-create-async-delegate"
    assert captured["max_attempts"] == 3
    assert callable(captured["utc_now"])
    assert captured["submission_stats"] is service._async_create_submission_stats  # noqa: SLF001


def test_service_delegates_create_version_async_submission(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    payload = ProposalVersionRequest(
        created_by="advisor_service",
        simulate_request=_simulate_request(),
    )
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_accept_create_version_async_submission_command(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        proposal_service_async_module,
        "accept_create_version_async_submission_command",
        fake_accept_create_version_async_submission_command,
    )

    response = service.accept_create_version_async_submission(
        proposal_id="pp-version-async-delegate",
        payload=payload,
        correlation_id="corr-version-async-delegate",
    )

    assert response is sentinel
    assert captured["repository"] is repo
    assert captured["proposal_id"] == "pp-version-async-delegate"
    assert captured["payload"] is payload
    assert captured["correlation_id"] == "corr-version-async-delegate"
    assert captured["max_attempts"] == 3
    assert callable(captured["utc_now"])


def test_service_delegates_narrative_read_view(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_build_narrative_view(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        proposal_service_narrative_module,
        "build_narrative_view",
        fake_build_narrative_view,
    )

    response = service.get_narrative(proposal_id="pp_narrative_view", version_no=2)

    assert response is sentinel
    assert captured == {
        "repository": repo,
        "proposal_id": "pp_narrative_view",
        "version_no": 2,
    }


def test_service_delegates_narrative_regeneration_view(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    payload = object()
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_regenerate_narrative_view(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        proposal_service_narrative_module,
        "regenerate_narrative_view",
        fake_regenerate_narrative_view,
    )

    response = service.regenerate_narrative(
        proposal_id="pp_narrative_regenerate",
        version_no=3,
        payload=payload,  # type: ignore[arg-type]
    )

    assert response is sentinel
    assert captured == {
        "repository": repo,
        "proposal_id": "pp_narrative_regenerate",
        "version_no": 3,
        "payload": payload,
    }


def test_service_delegates_narrative_review_command(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    payload = object()
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_record_narrative_review(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        proposal_service_narrative_module,
        "record_narrative_review",
        fake_record_narrative_review,
    )

    response = service.record_narrative_review(
        proposal_id="pp_narrative_review",
        version_no=4,
        payload=payload,  # type: ignore[arg-type]
        idempotency_key="idem-narrative-review",
    )

    assert response is sentinel
    assert captured["repository"] is repo
    assert captured["proposal_id"] == "pp_narrative_review"
    assert captured["version_no"] == 4
    assert captured["payload"] is payload
    assert captured["idempotency_key"] == "idem-narrative-review"
    assert isinstance(captured["event_id"], str)
    assert callable(captured["occurred_at"])


def test_service_missing_version_paths_and_helper_branches():
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)

    try:
        service.get_version(proposal_id="pp_missing", version_no=1, include_evidence=True)
    except ProposalNotFoundError as exc:
        assert str(exc) == "PROPOSAL_VERSION_NOT_FOUND"
    else:
        raise AssertionError("Expected PROPOSAL_VERSION_NOT_FOUND")

    try:
        service.create_version(
            proposal_id="pp_missing",
            payload=ProposalVersionRequest(
                created_by="advisor",
                simulate_request=_simulate_request(),
            ),
            correlation_id=None,
        )
    except ProposalNotFoundError as exc:
        assert str(exc) == "PROPOSAL_NOT_FOUND"
    else:
        raise AssertionError("Expected PROPOSAL_NOT_FOUND")

    try:
        service.transition_state(
            proposal_id="pp_missing",
            payload=ProposalStateTransitionRequest(
                event_type="SUBMITTED_FOR_RISK_REVIEW",
                actor_id="advisor",
                expected_state="DRAFT",
                reason={},
            ),
        )
    except ProposalNotFoundError as exc:
        assert str(exc) == "PROPOSAL_NOT_FOUND"
    else:
        raise AssertionError("Expected PROPOSAL_NOT_FOUND")

    try:
        service.record_approval(
            proposal_id="pp_missing",
            payload=ProposalApprovalRequest(
                approval_type="RISK",
                approved=True,
                actor_id="risk",
                expected_state="RISK_REVIEW",
                details={},
            ),
        )
    except ProposalNotFoundError as exc:
        assert str(exc) == "PROPOSAL_NOT_FOUND"
    else:
        raise AssertionError("Expected PROPOSAL_NOT_FOUND")

    repo.save_idempotency(
        ProposalIdempotencyRecord(
            idempotency_key="idem-bad-ref",
            request_hash="sha256:x",
            proposal_id="pp_missing",
            proposal_version_no=1,
            created_at=datetime.now(timezone.utc),
        )
    )
    try:
        build_create_response_from_replay_referents(
            repository=repo,
            proposal_id="pp_missing",
            version_no=1,
        )
    except ProposalNotFoundError as exc:
        assert str(exc) == "PROPOSAL_IDEMPOTENCY_REFERENT_NOT_FOUND"
    else:
        raise AssertionError("Expected PROPOSAL_IDEMPOTENCY_REFERENT_NOT_FOUND")


def test_service_rejects_simulation_flag_and_invalid_approval_type():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())
    payload = _create_payload()
    payload.simulate_request.options.enable_proposal_simulation = False

    try:
        service.create_proposal(
            payload=payload,
            idempotency_key="service-idem-disabled",
            correlation_id=None,
        )
    except ProposalValidationError as exc:
        assert "PROPOSAL_SIMULATION_DISABLED" in str(exc)
    else:
        raise AssertionError("Expected PROPOSAL_SIMULATION_DISABLED")

    try:
        resolve_proposal_approval_transition(
            current_state="DRAFT",
            approval_type="UNKNOWN",
            approved=True,
        )
    except ProposalTransitionError as exc:
        assert str(exc) == "INVALID_APPROVAL_TYPE"
    else:
        raise AssertionError("Expected INVALID_APPROVAL_TYPE")


def test_service_invalid_approval_state_variants():
    for approval_type, expected_state in [
        ("RISK", "COMPLIANCE_REVIEW"),
        ("COMPLIANCE", "RISK_REVIEW"),
        ("CLIENT_CONSENT", "DRAFT"),
    ]:
        try:
            resolve_proposal_approval_transition(
                current_state=expected_state,
                approval_type=approval_type,
                approved=True,
            )
        except ProposalTransitionError as exc:
            assert str(exc) == "INVALID_APPROVAL_STATE"
        else:
            raise AssertionError("Expected INVALID_APPROVAL_STATE")


def test_service_execute_async_returns_when_operation_missing():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())
    service.execute_create_proposal_async(
        operation_id="pop_missing",
    )
    service.execute_create_version_async(
        operation_id="pop_missing",
    )


@pytest.mark.parametrize(
    ("service_method_name", "view_function_name", "call_kwargs", "expected_identity"),
    [
        (
            "get_async_operation",
            "build_async_operation_status_view",
            {"operation_id": "pop_status_view"},
            {"operation_id": "pop_status_view"},
        ),
        (
            "get_async_operation_replay",
            "build_async_operation_replay_view",
            {"operation_id": "pop_replay_view"},
            {"operation_id": "pop_replay_view"},
        ),
        (
            "get_async_operation_by_correlation",
            "build_async_operation_correlation_view",
            {"correlation_id": "corr_async_view"},
            {"correlation_id": "corr_async_view"},
        ),
    ],
)
def test_service_delegates_async_operation_views(
    monkeypatch,
    service_method_name: str,
    view_function_name: str,
    call_kwargs: dict[str, str],
    expected_identity: dict[str, str],
):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_view(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(proposal_service_async_module, view_function_name, fake_view)

    response = getattr(service, service_method_name)(**call_kwargs)

    assert response is sentinel
    assert captured == {"repository": repo, **expected_identity}


def test_service_delegates_create_proposal_async_execution(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    payload = _create_payload()
    captured: dict[str, object] = {}

    def fake_execute_create_proposal_async_operation(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        proposal_service_async_module,
        "execute_create_proposal_async_operation",
        fake_execute_create_proposal_async_operation,
    )

    service.execute_create_proposal_async(
        operation_id="pop_delegate_create",
        payload=payload,
        idempotency_key="idem-delegate-create",
        correlation_id="corr-delegate-create",
    )

    assert captured["repository"] is repo
    assert captured["operation_id"] == "pop_delegate_create"
    assert captured["fallback_payload"] is payload
    assert captured["fallback_idempotency_key"] == "idem-delegate-create"
    assert captured["fallback_correlation_id"] == "corr-delegate-create"
    assert callable(captured["create_proposal"])


def test_service_delegates_create_version_async_execution(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    payload = ProposalVersionRequest(
        created_by="advisor_service",
        simulate_request=_simulate_request(),
    )
    captured: dict[str, object] = {}

    def fake_execute_create_version_async_operation(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        proposal_service_async_module,
        "execute_create_version_async_operation",
        fake_execute_create_version_async_operation,
    )

    service.execute_create_version_async(
        operation_id="pop_delegate_version",
        proposal_id="pp_delegate_version",
        payload=payload,
        correlation_id="corr-delegate-version",
    )

    assert captured["repository"] is repo
    assert captured["operation_id"] == "pop_delegate_version"
    assert captured["fallback_proposal_id"] == "pp_delegate_version"
    assert captured["fallback_payload"] is payload
    assert captured["fallback_correlation_id"] == "corr-delegate-version"
    assert callable(captured["create_version"])


def test_service_execute_create_proposal_async_marks_failed_on_lifecycle_error():
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    accepted = service.submit_create_proposal_async(
        payload=_create_payload(),
        idempotency_key="idem-async-fail",
        correlation_id="corr-async-fail",
    )

    stored_operation = repo.get_operation(operation_id=accepted.operation_id)
    assert stored_operation is not None
    stored_operation.payload_json["payload"]["simulate_request"]["options"][
        "enable_proposal_simulation"
    ] = False
    repo.update_operation(stored_operation)

    service.execute_create_proposal_async(operation_id=accepted.operation_id)

    operation = service.get_async_operation(operation_id=accepted.operation_id)
    assert operation.status == "FAILED"
    assert operation.error is not None
    assert operation.error.code == "ProposalValidationError"
    assert operation.attempt_count == 1
    assert operation.max_attempts == 3
    assert operation.lease_expires_at is None


def test_service_execute_create_version_async_marks_failed_on_lifecycle_error():
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    accepted = service.submit_create_version_async(
        proposal_id="pp_missing_for_async_version",
        payload=ProposalVersionRequest(
            created_by="advisor_service",
            simulate_request=_simulate_request(),
        ),
        correlation_id="corr-async-version-fail",
    )

    service.execute_create_version_async(
        operation_id=accepted.operation_id,
        proposal_id="pp_missing_for_async_version",
        payload=ProposalVersionRequest(
            created_by="advisor_service",
            simulate_request=_simulate_request(),
        ),
        correlation_id="corr-async-version-fail",
    )

    operation = service.get_async_operation(operation_id=accepted.operation_id)
    assert operation.status == "FAILED"
    assert operation.error is not None
    assert operation.error.code == "ProposalNotFoundError"
    assert operation.error.message == "PROPOSAL_NOT_FOUND"
    assert operation.attempt_count == 1
    assert operation.max_attempts == 3
    assert operation.lease_expires_at is None


def test_service_accept_async_version_submission_replays_duplicate_correlation() -> None:
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="idem-async-version-replay-base",
        correlation_id="corr-async-version-replay-base",
    )
    payload = ProposalVersionRequest(
        created_by="advisor_service",
        simulate_request=_simulate_request(),
    )

    first, first_is_new = service.accept_create_version_async_submission(
        proposal_id=created.proposal.proposal_id,
        payload=payload,
        correlation_id="corr-async-version-replay",
    )
    replayed, replayed_is_new = service.accept_create_version_async_submission(
        proposal_id=created.proposal.proposal_id,
        payload=payload,
        correlation_id="corr-async-version-replay",
    )

    assert first_is_new is True
    assert replayed_is_new is False
    assert replayed.operation_id == first.operation_id
    assert replayed.correlation_id == first.correlation_id


def test_service_accept_async_version_submission_rejects_correlation_mismatch() -> None:
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="idem-async-version-conflict-base",
        correlation_id="corr-async-version-conflict-base",
    )
    payload = ProposalVersionRequest(
        created_by="advisor_service",
        simulate_request=_simulate_request(),
    )
    conflicting_payload = ProposalVersionRequest(
        created_by="advisor_service_conflict",
        simulate_request=_simulate_request(),
    )

    accepted, accepted_is_new = service.accept_create_version_async_submission(
        proposal_id=created.proposal.proposal_id,
        payload=payload,
        correlation_id="corr-async-version-conflict",
    )

    with pytest.raises(ProposalIdempotencyConflictError) as exc_info:
        service.accept_create_version_async_submission(
            proposal_id=created.proposal.proposal_id,
            payload=conflicting_payload,
            correlation_id="corr-async-version-conflict",
        )

    assert accepted_is_new is True
    assert accepted.operation_id.startswith("pop_")
    assert str(exc_info.value) == "CORRELATION_ID_CONFLICT: async version submission mismatch"


def test_service_submit_async_create_persists_restart_safe_payload():
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    payload = _create_payload()

    accepted = service.submit_create_proposal_async(
        payload=payload,
        idempotency_key="idem-async-persisted-payload",
        correlation_id="corr-async-persisted-payload",
    )

    stored = repo.get_operation(operation_id=accepted.operation_id)
    assert stored is not None
    assert stored.payload_json["idempotency_key"] == "idem-async-persisted-payload"
    assert stored.payload_json["payload"]["created_by"] == payload.created_by
    assert stored.attempt_count == 0
    assert stored.max_attempts == 3
    assert accepted.attempt_count == 0
    assert accepted.max_attempts == 3


def test_service_accept_async_create_submission_marks_replayed_duplicates() -> None:
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    payload = _create_payload()

    first, first_is_new = service.accept_create_proposal_async_submission(
        payload=payload,
        idempotency_key="idem-async-replayed-create",
        correlation_id="corr-async-replayed-create-1",
    )
    duplicate, duplicate_is_new = service.accept_create_proposal_async_submission(
        payload=payload,
        idempotency_key="idem-async-replayed-create",
        correlation_id="corr-async-replayed-create-2",
    )

    assert first_is_new is True
    assert duplicate_is_new is False
    assert duplicate.operation_id == first.operation_id
    assert duplicate.correlation_id == first.correlation_id
    stats = service.get_async_create_submission_stats_for_tests()
    assert stats.accepted_new == 1
    assert stats.accepted_replayed == 1
    assert stats.conflicts == 0


def test_service_accept_async_create_submission_is_concurrency_safe() -> None:
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    payload = _create_payload()

    def _submit() -> tuple[str, bool]:
        accepted, is_new = service.accept_create_proposal_async_submission(
            payload=payload,
            idempotency_key="idem-async-concurrent-create",
            correlation_id=None,
        )
        return accepted.operation_id, is_new

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _submit(), range(24)))

    operation_ids = {operation_id for operation_id, _ in results}
    new_flags = [is_new for _, is_new in results]
    assert len(operation_ids) == 1
    assert sum(1 for value in new_flags if value) == 1
    stats = service.get_async_create_submission_stats_for_tests()
    assert stats.accepted_new == 1
    assert stats.accepted_replayed == 23
    assert stats.conflicts == 0


def test_service_accept_async_create_submission_tracks_conflicts() -> None:
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    payload = _create_payload()

    service.accept_create_proposal_async_submission(
        payload=payload,
        idempotency_key="idem-async-conflict-stats",
        correlation_id="corr-async-conflict-stats-1",
    )

    conflicting_payload = _create_payload()
    conflicting_payload.metadata.title = "Conflicting async stats payload"

    with pytest.raises(ProposalIdempotencyConflictError):
        service.accept_create_proposal_async_submission(
            payload=conflicting_payload,
            idempotency_key="idem-async-conflict-stats",
            correlation_id="corr-async-conflict-stats-2",
        )

    stats = service.get_async_create_submission_stats_for_tests()
    assert stats.accepted_new == 1
    assert stats.accepted_replayed == 0
    assert stats.conflicts == 1


def test_service_execute_create_proposal_async_retries_runtime_failure(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    accepted = service.submit_create_proposal_async(
        payload=_create_payload(),
        idempotency_key="idem-async-runtime-retry",
        correlation_id="corr-async-runtime-retry",
    )

    original_create_proposal = service.create_proposal
    attempts = {"count": 0}

    def flaky_create_proposal(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("transient runtime outage")
        return original_create_proposal(**kwargs)

    monkeypatch.setattr(service, "create_proposal", flaky_create_proposal)

    service.execute_create_proposal_async(operation_id=accepted.operation_id)

    operation = service.get_async_operation(operation_id=accepted.operation_id)
    assert operation.status == "SUCCEEDED"
    assert operation.result is not None
    assert operation.error is None
    assert operation.attempt_count == 2
    assert attempts["count"] == 2


def test_service_recover_async_operations_replays_pending_create_from_persisted_payload():
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    accepted = service.submit_create_proposal_async(
        payload=_create_payload(),
        idempotency_key="idem-async-recover-pending",
        correlation_id="corr-async-recover-pending",
    )

    recovered = service.recover_async_operations()

    operation = service.get_async_operation(operation_id=accepted.operation_id)
    assert recovered == 1
    assert operation.status == "SUCCEEDED"
    assert operation.result is not None
    assert operation.result.proposal.proposal_id


def test_service_recover_async_operations_respects_max_operations_batch():
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    first = service.submit_create_proposal_async(
        payload=_create_payload(),
        idempotency_key="idem-async-recover-batch-1",
        correlation_id="corr-async-recover-batch-1",
    )
    second = service.submit_create_proposal_async(
        payload=_create_payload(),
        idempotency_key="idem-async-recover-batch-2",
        correlation_id="corr-async-recover-batch-2",
    )

    recovered = service.recover_async_operations(max_operations=1)

    first_operation = service.get_async_operation(operation_id=first.operation_id)
    second_operation = service.get_async_operation(operation_id=second.operation_id)
    assert recovered == 1
    assert first_operation.status == "SUCCEEDED"
    assert first_operation.result is not None
    assert second_operation.status == "PENDING"
    assert second_operation.result is None


def test_service_recover_async_operations_replays_expired_running_version_operation():
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="idem-async-expired-running-base",
        correlation_id="corr-async-expired-running-base",
    )
    accepted = service.submit_create_version_async(
        proposal_id=created.proposal.proposal_id,
        payload=ProposalVersionRequest(
            created_by="advisor_service",
            simulate_request=_simulate_request(),
        ),
        correlation_id="corr-async-expired-running-version",
    )
    operation = repo.get_operation(operation_id=accepted.operation_id)
    assert operation is not None
    operation.status = "RUNNING"
    operation.attempt_count = 1
    operation.started_at = datetime.now(timezone.utc)
    operation.lease_expires_at = datetime.now(timezone.utc)
    repo.update_operation(operation)

    recovered = service.recover_async_operations()

    status = service.get_async_operation(operation_id=accepted.operation_id)
    assert recovered == 1
    assert status.status == "SUCCEEDED"
    assert status.attempt_count == 2
    assert status.result is not None


def test_service_delegates_async_recovery_batch(monkeypatch):
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    captured: dict[str, object] = {}

    def fake_recover_async_operation_batch(**kwargs):
        captured.update(kwargs)
        return 7

    monkeypatch.setattr(
        proposal_service_async_module,
        "recover_async_operation_batch",
        fake_recover_async_operation_batch,
    )

    recovered = service.recover_async_operations(max_operations=3)

    assert recovered == 7
    assert captured["repository"] is repo
    assert captured["max_operations"] == 3
    assert callable(captured["execute_create_proposal_async"])
    assert callable(captured["execute_create_version_async"])


def test_service_expected_state_can_be_optional_when_disabled():
    service = ProposalWorkflowService(
        repository=InMemoryProposalRepository(),
        require_expected_state=False,
    )
    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-optional-state",
        correlation_id="corr-service-optional-state",
    )
    transitioned = service.transition_state(
        proposal_id=created.proposal.proposal_id,
        payload=ProposalStateTransitionRequest(
            event_type="SUBMITTED_FOR_RISK_REVIEW",
            actor_id="advisor_service",
            expected_state=None,
            reason={},
        ),
    )
    assert transitioned.current_state == "RISK_REVIEW"

    strict_service = ProposalWorkflowService(
        repository=InMemoryProposalRepository(),
        require_expected_state=True,
    )
    strict_created = strict_service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-required-state",
        correlation_id="corr-service-required-state",
    )
    try:
        strict_service.transition_state(
            proposal_id=strict_created.proposal.proposal_id,
            payload=ProposalStateTransitionRequest(
                event_type="SUBMITTED_FOR_RISK_REVIEW",
                actor_id="advisor_service",
                expected_state=None,
                reason={},
            ),
        )
    except ProposalStateConflictError as exc:
        assert "expected_state is required" in str(exc)
    else:
        raise AssertionError("Expected ProposalStateConflictError")


def test_service_lineage_skips_missing_version_rows():
    repo = CountingLineageRepository()
    service = ProposalWorkflowService(repository=repo)
    now = datetime.now(timezone.utc)
    repo.create_proposal(
        ProposalRecord(
            proposal_id="pp_lineage_gap",
            portfolio_id="pf_lineage_gap",
            mandate_id=None,
            jurisdiction=None,
            created_by="advisor",
            created_at=now,
            last_event_at=now,
            current_state="DRAFT",
            current_version_no=2,
            title="lineage gap",
            advisor_notes=None,
        )
    )
    repo.create_version(
        ProposalVersionRecord(
            proposal_version_id="ppv_lineage_gap_1",
            proposal_id="pp_lineage_gap",
            version_no=1,
            created_at=now,
            request_hash="sha256:req-lineage-gap-1",
            artifact_hash="sha256:artifact-lineage-gap-1",
            simulation_hash="sha256:sim-lineage-gap-1",
            status_at_creation="READY",
            proposal_result_json={"proposal_run_id": "pr_lineage_gap_1", "status": "READY"},
            artifact_json={"artifact_id": "pa_lineage_gap_1"},
            evidence_bundle_json={},
            gate_decision_json=None,
        )
    )
    repo.append_event(
        ProposalWorkflowEventRecord(
            event_id="pwe_lineage_gap_created",
            proposal_id="pp_lineage_gap",
            event_type="CREATED",
            from_state=None,
            to_state="DRAFT",
            actor_id="advisor",
            occurred_at=now,
            reason_json={},
            related_version_no=1,
        )
    )

    lineage = service.get_lineage(proposal_id="pp_lineage_gap")
    assert lineage.proposal.proposal_id == "pp_lineage_gap"
    assert lineage.version_count == 1
    assert lineage.latest_version_no == 1
    assert lineage.lineage_complete is False
    assert lineage.missing_version_numbers == [2]
    assert [version.version_no for version in lineage.versions] == [1]
    assert repo.list_versions_calls == 1
    assert repo.get_version_calls == 0


def test_transition_idempotency_replay_and_conflict():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())
    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-transition",
        correlation_id="corr-transition",
    )
    proposal_id = created.proposal.proposal_id
    payload = ProposalStateTransitionRequest(
        event_type="SUBMITTED_FOR_RISK_REVIEW",
        actor_id="advisor_service",
        expected_state="DRAFT",
        reason={"comment": "first submit"},
    )
    first = service.transition_state(
        proposal_id=proposal_id,
        payload=payload,
        idempotency_key="  idem-transition-1  ",
    )
    replay = service.transition_state(
        proposal_id=proposal_id,
        payload=payload,
        idempotency_key="idem-transition-1",
    )
    assert replay.latest_workflow_event.event_id == first.latest_workflow_event.event_id
    assert replay.current_state == "RISK_REVIEW"
    assert first.latest_workflow_event.reason["idempotency_key"] == "idem-transition-1"

    try:
        service.transition_state(
            proposal_id=proposal_id,
            payload=ProposalStateTransitionRequest(
                event_type="SUBMITTED_FOR_COMPLIANCE_REVIEW",
                actor_id="advisor_service",
                expected_state="RISK_REVIEW",
                reason={"comment": "different request"},
            ),
            idempotency_key="idem-transition-1",
        )
    except ProposalIdempotencyConflictError as exc:
        assert "IDEMPOTENCY_KEY_CONFLICT" in str(exc)
    else:
        raise AssertionError("Expected ProposalIdempotencyConflictError")


def test_approval_idempotency_replay_and_conflict():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())
    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-idem-approval",
        correlation_id="corr-approval",
    )
    proposal_id = created.proposal.proposal_id
    service.transition_state(
        proposal_id=proposal_id,
        payload=ProposalStateTransitionRequest(
            event_type="SUBMITTED_FOR_RISK_REVIEW",
            actor_id="advisor_service",
            expected_state="DRAFT",
            reason={},
        ),
    )
    approval_payload = ProposalApprovalRequest(
        approval_type="RISK",
        approved=True,
        actor_id="risk_officer",
        expected_state="RISK_REVIEW",
        details={"comment": "approved"},
    )
    first = service.record_approval(
        proposal_id=proposal_id,
        payload=approval_payload,
        idempotency_key="  idem-approval-1  ",
    )
    replay = service.record_approval(
        proposal_id=proposal_id,
        payload=approval_payload,
        idempotency_key="idem-approval-1",
    )
    assert replay.latest_workflow_event.event_id == first.latest_workflow_event.event_id
    assert replay.approval is not None
    assert first.approval is not None
    assert replay.approval.approval_id == first.approval.approval_id
    assert first.approval.details["idempotency_key"] == "idem-approval-1"

    try:
        service.record_approval(
            proposal_id=proposal_id,
            payload=ProposalApprovalRequest(
                approval_type="RISK",
                approved=False,
                actor_id="risk_officer",
                expected_state="RISK_REVIEW",
                details={"comment": "different decision"},
            ),
            idempotency_key="idem-approval-1",
        )
    except ProposalIdempotencyConflictError as exc:
        assert "IDEMPOTENCY_KEY_CONFLICT" in str(exc)
    else:
        raise AssertionError("Expected ProposalIdempotencyConflictError")


def test_narrative_review_records_version_scoped_replayable_event() -> None:
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())
    created = service.create_proposal(
        payload=_create_payload_with_narrative("pf_service_narrative_review_001"),
        idempotency_key="idem-narrative-review-create",
        correlation_id="corr-narrative-review-create",
    )

    first = service.record_narrative_review(
        proposal_id=created.proposal.proposal_id,
        version_no=1,
        payload=ProposalNarrativeReviewRequest(
            action="APPROVE",
            reviewed_by="compliance_001",
            reason="Evidence-grounded advisor-review narrative.",
        ),
        idempotency_key="  idem-narrative-review-approve  ",
    )
    replayed = service.record_narrative_review(
        proposal_id=created.proposal.proposal_id,
        version_no=1,
        payload=ProposalNarrativeReviewRequest(
            action="APPROVE",
            reviewed_by="compliance_001",
            reason="Evidence-grounded advisor-review narrative.",
        ),
        idempotency_key="idem-narrative-review-approve",
    )
    replay = service.get_version_replay(
        proposal_id=created.proposal.proposal_id,
        version_no=1,
    )

    assert first.latest_workflow_event.event_type == "NARRATIVE_REVIEWED"
    assert first.narrative_review.review_state == "APPROVED_FOR_ADVISOR_USE"
    assert first.narrative_review.client_ready_status == "NOT_REQUESTED"
    assert replayed.narrative_review.replayed is True
    assert replayed.narrative_review.review_id == first.narrative_review.review_id
    assert first.latest_workflow_event.reason["idempotency_key"] == (
        "idem-narrative-review-approve"
    )
    assert replay.evidence["proposal_narrative"]["narrative_id"] == (
        first.narrative_review.narrative_id
    )
    assert replay.evidence["proposal_narrative_review"]["review_id"] == (
        first.narrative_review.review_id
    )
    assert replay.evidence["proposal_narrative_review"]["source_narrative_hash"] == (
        first.narrative_review.source_narrative_hash
    )


def test_narrative_review_idempotency_conflict_rejects_payload_drift() -> None:
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())
    created = service.create_proposal(
        payload=_create_payload_with_narrative("pf_service_narrative_review_conflict"),
        idempotency_key="idem-narrative-review-conflict-create",
        correlation_id="corr-narrative-review-conflict-create",
    )

    service.record_narrative_review(
        proposal_id=created.proposal.proposal_id,
        version_no=1,
        payload=ProposalNarrativeReviewRequest(
            action="APPROVE",
            reviewed_by="compliance_001",
            reason="Evidence-grounded advisor-review narrative.",
        ),
        idempotency_key="idem-narrative-review-conflict",
    )

    with pytest.raises(ProposalIdempotencyConflictError):
        service.record_narrative_review(
            proposal_id=created.proposal.proposal_id,
            version_no=1,
            payload=ProposalNarrativeReviewRequest(
                action="REJECT",
                reviewed_by="compliance_001",
                reason="Rejecting with same idempotency key must not mutate review truth.",
            ),
            idempotency_key="idem-narrative-review-conflict",
        )


def test_narrative_client_ready_release_requires_positive_review_and_clear_policy() -> None:
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())
    created = service.create_proposal(
        payload=_create_payload_with_narrative("pf_service_narrative_client_ready_blocked"),
        idempotency_key="idem-narrative-client-ready-create",
        correlation_id="corr-narrative-client-ready-create",
    )

    rejected = service.record_narrative_review(
        proposal_id=created.proposal.proposal_id,
        version_no=1,
        payload=ProposalNarrativeReviewRequest(
            action="REJECT",
            reviewed_by="compliance_001",
            reason="Client-ready release cannot proceed after rejection.",
            client_ready_release_requested=True,
        ),
        idempotency_key="idem-narrative-client-ready-reject",
    )
    approved = service.record_narrative_review(
        proposal_id=created.proposal.proposal_id,
        version_no=1,
        payload=ProposalNarrativeReviewRequest(
            action="APPROVE",
            reviewed_by="compliance_001",
            reason="Approval still cannot make a blocked artifact client-ready.",
            client_ready_release_requested=True,
        ),
        idempotency_key="idem-narrative-client-ready-approve",
    )

    assert rejected.narrative_review.client_ready_status == "BLOCKED_REVIEW_REQUIRED"
    assert approved.narrative_review.client_ready_status == "BLOCKED_POLICY_OR_GUARDRAIL"


def test_narrative_client_ready_release_stays_gated_for_clean_advisor_review_narrative() -> None:
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    created = service.create_proposal(
        payload=_create_payload_with_narrative("pf_service_narrative_client_ready_gated"),
        idempotency_key="idem-narrative-client-ready-gated-create",
        correlation_id="corr-narrative-client-ready-gated-create",
    )
    version = repo.get_version(proposal_id=created.proposal.proposal_id, version_no=1)
    assert version is not None

    artifact = deepcopy(version.artifact_json)
    narrative = artifact["proposal_narrative"]
    narrative["status"] = "READY_FOR_ADVISOR_REVIEW"
    narrative["review_state"] = "DRAFT"
    narrative["limitations"] = []
    narrative["narrative_policy"]["client_ready_blockers"] = []
    for result in narrative["guardrail_results"]:
        result["status"] = "PASS"
    repo.create_version(version.model_copy(update={"artifact_json": artifact}))

    approved = service.record_narrative_review(
        proposal_id=created.proposal.proposal_id,
        version_no=1,
        payload=ProposalNarrativeReviewRequest(
            action="APPROVE",
            reviewed_by="compliance_001",
            reason="Advisor-review approval must not promote client-ready release.",
            client_ready_release_requested=True,
        ),
        idempotency_key="idem-narrative-client-ready-gated-approve",
    )

    assert approved.narrative_review.review_state == "APPROVED_FOR_ADVISOR_USE"
    assert approved.narrative_review.client_ready_status == "BLOCKED_POLICY_OR_GUARDRAIL"
    assert approved.narrative_review.client_ready_status != "APPROVED_FOR_CLIENT_READY"


def test_approval_replay_requires_matching_event_referent():
    now = datetime.now(timezone.utc)
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="idem-approval-referent",
        correlation_id="corr-approval-referent",
    )
    proposal_id = created.proposal.proposal_id
    service.transition_state(
        proposal_id=proposal_id,
        payload=ProposalStateTransitionRequest(
            event_type="SUBMITTED_FOR_RISK_REVIEW",
            actor_id="advisor_service",
            expected_state="DRAFT",
            reason={},
        ),
    )

    approval_payload = ProposalApprovalRequest(
        approval_type="RISK",
        approved=True,
        actor_id="risk_officer",
        expected_state="RISK_REVIEW",
        details={},
    )
    request_hash = hash_canonical_payload(approval_payload.model_dump(mode="json"))

    repo.create_approval(
        ProposalApprovalRecordData(
            approval_id="pap_orphan",
            proposal_id=proposal_id,
            approval_type="RISK",
            approved=True,
            actor_id="risk_officer",
            occurred_at=now,
            details_json={
                "idempotency_key": "idem-approval-orphan",
                "idempotency_request_hash": request_hash,
            },
            related_version_no=1,
        )
    )

    try:
        service.record_approval(
            proposal_id=proposal_id,
            payload=approval_payload,
            idempotency_key="idem-approval-orphan",
        )
    except ProposalLifecycleError as exc:
        assert str(exc) == "PROPOSAL_IDEMPOTENCY_REFERENT_NOT_FOUND"
    else:
        raise AssertionError("Expected PROPOSAL_IDEMPOTENCY_REFERENT_NOT_FOUND")


def test_approval_replay_skips_unrelated_idempotency_records():
    now = datetime.now(timezone.utc)
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="idem-approval-skip",
        correlation_id="corr-approval-skip",
    )
    proposal_id = created.proposal.proposal_id
    service.transition_state(
        proposal_id=proposal_id,
        payload=ProposalStateTransitionRequest(
            event_type="SUBMITTED_FOR_RISK_REVIEW",
            actor_id="advisor_service",
            expected_state="DRAFT",
            reason={},
        ),
    )

    payload = ProposalApprovalRequest(
        approval_type="RISK",
        approved=True,
        actor_id="risk_officer",
        expected_state="RISK_REVIEW",
        details={},
    )
    first = service.record_approval(
        proposal_id=proposal_id,
        payload=payload,
        idempotency_key="idem-target",
    )
    repo.create_approval(
        ProposalApprovalRecordData(
            approval_id="pap_unrelated",
            proposal_id=proposal_id,
            approval_type="CLIENT_CONSENT",
            approved=False,
            actor_id="client_1",
            occurred_at=now,
            details_json={
                "idempotency_key": "idem-unrelated",
                "idempotency_request_hash": "sha256:unrelated",
            },
            related_version_no=1,
        )
    )

    replay = service.record_approval(
        proposal_id=proposal_id,
        payload=payload,
        idempotency_key="idem-target",
    )
    assert replay.approval is not None
    assert first.approval is not None
    assert replay.approval.approval_id == first.approval.approval_id


def test_service_create_proposal_persists_direct_create_origin_by_default():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    created = service.create_proposal(
        payload=_create_payload(),
        idempotency_key="service-origin-direct",
        correlation_id="corr-service-origin-direct",
    )

    assert created.proposal.lifecycle_origin == "DIRECT_CREATE"
    assert created.proposal.source_workspace_id is None


def test_service_create_proposal_requires_workspace_reference_for_workspace_handoff_origin():
    service = ProposalWorkflowService(repository=InMemoryProposalRepository())

    try:
        service.create_proposal(
            payload=_create_payload(),
            idempotency_key="service-origin-workspace-missing",
            correlation_id="corr-service-origin-workspace-missing",
            lifecycle_origin="WORKSPACE_HANDOFF",
            source_workspace_id=None,
        )
    except ProposalValidationError as exc:
        assert str(exc) == "WORKSPACE_HANDOFF_SOURCE_WORKSPACE_ID_REQUIRED"
    else:
        raise AssertionError("Expected WORKSPACE_HANDOFF_SOURCE_WORKSPACE_ID_REQUIRED")


def test_service_execution_handoff_normalizes_idempotency_key_for_replay():
    repo = InMemoryProposalRepository()
    service = ProposalWorkflowService(repository=repo)
    occurred_at = datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)
    proposal = ProposalRecord(
        proposal_id="pp_execution_handoff_replay",
        portfolio_id="pf_execution_handoff_replay",
        mandate_id="mandate_execution_handoff_replay",
        jurisdiction="SG",
        created_by="advisor_execution_handoff",
        created_at=occurred_at,
        last_event_at=occurred_at,
        current_state="EXECUTION_READY",
        current_version_no=3,
        title="Execution handoff replay",
    )
    repo.create_proposal(proposal)
    payload = ProposalExecutionHandoffRequest(
        actor_id="advisor_execution_handoff",
        execution_provider="lotus-manage",
        expected_state="EXECUTION_READY",
        correlation_id="corr-execution-handoff",
        notes={"desk": "ADVISORY_EXECUTION"},
    )

    first = service.request_execution_handoff(
        proposal_id=proposal.proposal_id,
        payload=payload,
        idempotency_key="  idem-execution-handoff  ",
    )
    replay = service.request_execution_handoff(
        proposal_id=proposal.proposal_id,
        payload=payload,
        idempotency_key="idem-execution-handoff",
    )

    assert replay.latest_workflow_event.event_id == first.latest_workflow_event.event_id
    assert replay.latest_workflow_event.reason["idempotency_key"] == "idem-execution-handoff"
    assert len(repo.list_events(proposal_id=proposal.proposal_id)) == 1


def test_execution_update_replay_uses_loaded_events_for_status_projection():
    repo = CountingListEventsRepository()
    service = ProposalWorkflowService(repository=repo)
    occurred_at = datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)
    proposal = ProposalRecord(
        proposal_id="pp_execution_update_replay",
        portfolio_id="pf_execution_update_replay",
        mandate_id="mandate_execution_update_replay",
        jurisdiction="SG",
        created_by="advisor_execution_update",
        created_at=occurred_at,
        last_event_at=occurred_at,
        current_state="EXECUTION_READY",
        current_version_no=3,
        title="Execution update replay",
    )
    payload = ProposalExecutionUpdateRequest(
        update_id="exec_update_replay",
        actor_id="lotus-manage",
        execution_request_id="pex_execution_update_replay",
        execution_provider="lotus-manage",
        update_status="PARTIALLY_EXECUTED",
        external_execution_id="oms_partial_replay",
        details={"filled_quantity": "50", "remaining_quantity": "25"},
    )
    request_hash = hash_canonical_payload(payload.model_dump(mode="json"))
    repo.create_proposal(proposal)
    repo.append_event(
        ProposalWorkflowEventRecord(
            event_id="pwe_execution_requested_replay",
            proposal_id=proposal.proposal_id,
            event_type="EXECUTION_REQUESTED",
            from_state="EXECUTION_READY",
            to_state="EXECUTION_READY",
            actor_id="advisor_execution_update",
            occurred_at=occurred_at,
            reason_json={
                "execution_request_id": "pex_execution_update_replay",
                "execution_provider": "lotus-manage",
            },
            related_version_no=3,
        )
    )
    repo.append_event(
        ProposalWorkflowEventRecord(
            event_id="pwe_execution_update_replay",
            proposal_id=proposal.proposal_id,
            event_type="EXECUTION_PARTIALLY_EXECUTED",
            from_state="EXECUTION_READY",
            to_state="EXECUTION_READY",
            actor_id="lotus-manage",
            occurred_at=occurred_at,
            reason_json={
                "update_id": "exec_update_replay",
                "execution_request_id": "pex_execution_update_replay",
                "execution_provider": "lotus-manage",
                "external_execution_id": "oms_partial_replay",
                "idempotency_key": "execution-update:exec_update_replay",
                "idempotency_request_hash": request_hash,
            },
            related_version_no=3,
        )
    )

    response = service.record_execution_update(
        proposal_id=proposal.proposal_id,
        payload=payload,
    )

    assert repo.list_events_calls == 1
    assert response.handoff_status == "PARTIALLY_EXECUTED"
    assert response.latest_workflow_event is not None
    assert response.latest_workflow_event.event_id == "pwe_execution_update_replay"
