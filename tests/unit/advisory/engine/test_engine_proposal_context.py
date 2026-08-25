from pathlib import Path

import pytest

import src.core.proposals.context as context_facade
from src.core.proposal_request_models import ProposalSimulateRequest
from src.core.proposals.context import (
    ProposalContextResolutionError,
    build_create_request_hash,
    build_version_request_hash,
    resolve_create_request,
    resolve_simulation_request,
    resolve_version_request,
)
from src.core.proposals.context_evidence import build_context_resolution_evidence
from src.core.proposals.context_hashing import build_simulation_request_hash
from src.core.proposals.context_ports import (
    ResolvedStatefulProposalContext,
    configure_proposal_stateful_context_resolver,
    reset_proposal_stateful_context_resolver_for_tests,
)
from src.core.proposals.context_resolution import (
    ResolvedProposalContext,
    ResolvedSimulationContext,
    _policy_selectors,
    apply_context_resolution_override,
)
from src.core.proposals.models import (
    ProposalCreateMetadata,
    ProposalCreateRequest,
    ProposalResolvedContext,
    ProposalSimulationRequest,
    ProposalStatefulInput,
    ProposalVersionRequest,
)


def _simulate_request(portfolio_id: str = "pf_context_hash") -> dict:
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


def _workspace_context_override(resolved: ResolvedProposalContext) -> dict:
    return build_context_resolution_evidence(
        ResolvedProposalContext(
            input_mode="stateful",
            resolution_source="LOTUS_CORE",
            simulate_request=resolved.simulate_request,
            resolved_context=resolved.resolved_context.model_copy(
                update={
                    "requested_as_of": "2026-06-15",
                    "requested_reporting_currency": "EUR",
                }
            ),
            metadata=resolved.metadata,
            policy_selectors=_policy_selectors(
                stateful_input=ProposalStatefulInput(
                    portfolio_id="pf_context_hash",
                    as_of="2026-06-15",
                    reporting_currency="EUR",
                )
            ),
            used_legacy_contract=False,
        )
    )


def test_build_create_request_hash_normalizes_legacy_and_stateless_contracts():
    legacy_payload = ProposalCreateRequest(
        created_by="advisor_context",
        simulate_request=_simulate_request(),
        metadata={"title": "Context hash"},
    )
    stateless_payload = ProposalCreateRequest(
        created_by="advisor_context",
        input_mode="stateless",
        stateless_input={"simulate_request": _simulate_request()},
        metadata={"title": "Context hash"},
    )

    legacy_hash = build_create_request_hash(
        payload=legacy_payload,
        resolved=resolve_create_request(legacy_payload),
    )
    stateless_hash = build_create_request_hash(
        payload=stateless_payload,
        resolved=resolve_create_request(stateless_payload),
    )

    assert legacy_hash.startswith("sha256:")
    assert legacy_hash == stateless_hash


def test_stateless_context_does_not_infer_a_lifecycle_date_without_source_input():
    payload = ProposalCreateRequest(
        created_by="advisor_context",
        input_mode="stateless",
        stateless_input={"simulate_request": _simulate_request()},
    )

    resolved = resolve_create_request(payload)
    evidence = build_context_resolution_evidence(resolved)

    assert resolved.resolved_context.as_of is None
    assert resolved.resolved_context.requested_as_of is None
    assert evidence["resolved_context"]["as_of"] is None


def test_stateless_context_preserves_reference_model_date_as_lifecycle_input():
    simulate_request = _simulate_request()
    simulate_request["reference_model"] = {
        "model_id": "model_context",
        "as_of": "2026-06-15",
        "base_currency": "USD",
    }
    payload = ProposalCreateRequest(
        created_by="advisor_context",
        input_mode="stateless",
        stateless_input={"simulate_request": simulate_request},
    )

    resolved = resolve_create_request(payload)

    assert resolved.resolved_context.as_of == "2026-06-15"
    assert resolved.resolved_context.requested_as_of == "2026-06-15"


def _stateful_input_for_missing_resolved_as_of() -> ProposalStatefulInput:
    return ProposalStatefulInput(
        portfolio_id="pf_stateful_missing_as_of",
        as_of="2026-06-15",
    )


def _configure_missing_resolved_as_of_context() -> None:
    configure_proposal_stateful_context_resolver(
        lambda _stateful_input: ResolvedStatefulProposalContext(
            simulate_request=ProposalSimulateRequest.model_validate(
                _simulate_request("pf_stateful_missing_as_of")
            ),
            resolved_context=ProposalResolvedContext(
                portfolio_id="pf_stateful_missing_as_of",
                as_of=None,
            ),
        )
    )


def test_stateful_create_rejects_missing_source_resolved_as_of():
    _configure_missing_resolved_as_of_context()
    try:
        with pytest.raises(
            ProposalContextResolutionError,
            match="WORKSPACE_STATEFUL_CONTEXT_AS_OF_MISSING",
        ):
            resolve_create_request(
                ProposalCreateRequest(
                    created_by="advisor_context",
                    input_mode="stateful",
                    stateful_input=_stateful_input_for_missing_resolved_as_of(),
                )
            )
    finally:
        reset_proposal_stateful_context_resolver_for_tests()


def test_stateful_version_rejects_missing_source_resolved_as_of():
    _configure_missing_resolved_as_of_context()
    try:
        with pytest.raises(
            ProposalContextResolutionError,
            match="WORKSPACE_STATEFUL_CONTEXT_AS_OF_MISSING",
        ):
            resolve_version_request(
                ProposalVersionRequest(
                    created_by="advisor_context",
                    input_mode="stateful",
                    stateful_input=_stateful_input_for_missing_resolved_as_of(),
                )
            )
    finally:
        reset_proposal_stateful_context_resolver_for_tests()


def test_stateful_simulation_rejects_missing_source_resolved_as_of():
    _configure_missing_resolved_as_of_context()
    try:
        with pytest.raises(
            ProposalContextResolutionError,
            match="WORKSPACE_STATEFUL_CONTEXT_AS_OF_MISSING",
        ):
            resolve_simulation_request(
                ProposalSimulationRequest(
                    input_mode="stateful",
                    stateful_input=_stateful_input_for_missing_resolved_as_of(),
                )
            )
    finally:
        reset_proposal_stateful_context_resolver_for_tests()


def test_context_resolution_override_preserves_workspace_request_dimensions_and_draft():
    payload = ProposalCreateRequest(
        created_by="advisor_context",
        simulate_request=_simulate_request(),
    )
    resolved = resolve_create_request(payload)
    override = _workspace_context_override(resolved)

    effective = apply_context_resolution_override(resolved, override)

    assert effective.input_mode == "stateful"
    assert effective.resolution_source == "LOTUS_CORE"
    assert effective.resolved_context.requested_as_of == "2026-06-15"
    assert effective.resolved_context.requested_reporting_currency == "EUR"
    assert effective.simulate_request == resolved.simulate_request


def test_context_resolution_override_rejects_malformed_internal_projection():
    resolved = resolve_create_request(
        ProposalCreateRequest(
            created_by="advisor_context",
            simulate_request=_simulate_request(),
        )
    )

    with pytest.raises(
        ProposalContextResolutionError,
        match="PROPOSAL_CONTEXT_RESOLUTION_OVERRIDE_INVALID",
    ):
        apply_context_resolution_override(resolved, {"input_mode": "stateful"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_mode", None),
        ("input_mode", "unsupported"),
        ("resolution_source", None),
        ("resolution_source", ""),
        ("used_legacy_contract", "false"),
        ("advisory_policy_context", None),
    ],
)
def test_context_resolution_override_rejects_invalid_typed_values(field, value):
    resolved = resolve_create_request(
        ProposalCreateRequest(
            created_by="advisor_context",
            simulate_request=_simulate_request(),
        )
    )
    override = _workspace_context_override(resolved)
    override[field] = value

    with pytest.raises(
        ProposalContextResolutionError,
        match="PROPOSAL_CONTEXT_RESOLUTION_OVERRIDE_INVALID",
    ):
        apply_context_resolution_override(resolved, override)


def test_build_version_request_hash_is_canonical_and_concurrency_sensitive():
    first_payload = ProposalVersionRequest(
        created_by="advisor_context",
        simulate_request=_simulate_request(),
        expected_current_version_no=1,
    )
    same_payload = ProposalVersionRequest(
        created_by="advisor_context",
        input_mode="stateless",
        stateless_input={"simulate_request": _simulate_request()},
        expected_current_version_no=1,
    )
    changed_payload = ProposalVersionRequest(
        created_by="advisor_context",
        simulate_request=_simulate_request(),
        expected_current_version_no=2,
    )

    first_hash = build_version_request_hash(
        payload=first_payload,
        resolved=resolve_version_request(first_payload),
    )
    same_hash = build_version_request_hash(
        payload=same_payload,
        resolved=resolve_version_request(same_payload),
    )
    changed_hash = build_version_request_hash(
        payload=changed_payload,
        resolved=resolve_version_request(changed_payload),
    )

    assert first_hash.startswith("sha256:")
    assert first_hash == same_hash
    assert first_hash != changed_hash


@pytest.mark.parametrize(
    ("payload", "resolver", "expected_message"),
    [
        (
            ProposalCreateRequest.model_construct(
                created_by="advisor_context",
                input_mode="stateful",
                stateful_input=None,
                stateless_input=None,
                simulate_request=None,
                metadata={},
            ),
            resolve_create_request,
            "PROPOSAL_STATEFUL_INPUT_REQUIRED",
        ),
        (
            ProposalCreateRequest.model_construct(
                created_by="advisor_context",
                input_mode="stateless",
                stateful_input=None,
                stateless_input=None,
                simulate_request=None,
                metadata={},
            ),
            resolve_create_request,
            "PROPOSAL_STATELESS_INPUT_REQUIRED",
        ),
        (
            ProposalSimulationRequest.model_construct(
                input_mode="stateful",
                stateful_input=None,
                stateless_input=None,
                simulate_request=None,
                alternatives_request=None,
            ),
            resolve_simulation_request,
            "PROPOSAL_STATEFUL_INPUT_REQUIRED",
        ),
        (
            ProposalSimulationRequest.model_construct(
                input_mode="stateless",
                stateful_input=None,
                stateless_input=None,
                simulate_request=None,
                alternatives_request=None,
            ),
            resolve_simulation_request,
            "PROPOSAL_STATELESS_INPUT_REQUIRED",
        ),
        (
            ProposalVersionRequest.model_construct(
                created_by="advisor_context",
                input_mode="legacy",
                stateful_input=None,
                stateless_input=None,
                simulate_request=None,
                expected_current_version_no=None,
            ),
            resolve_version_request,
            "PROPOSAL_SIMULATE_REQUEST_REQUIRED",
        ),
    ],
)
def test_context_resolution_uses_domain_errors_for_constructed_invalid_payloads(
    payload,
    resolver,
    expected_message: str,
):
    with pytest.raises(ProposalContextResolutionError, match=expected_message):
        resolver(payload)


def test_policy_selectors_prefer_explicit_metadata_mandate_over_stateful_default():
    selectors = _policy_selectors(
        metadata=ProposalCreateMetadata(
            mandate_id="mandate_metadata",
            jurisdiction="SG",
        ),
        stateful_input=ProposalStatefulInput(
            portfolio_id="pf_context_policy",
            as_of="2026-06-15",
            household_id="hh_context_policy",
            mandate_id="mandate_stateful",
            benchmark_id="benchmark_context_policy",
        ),
    )

    assert selectors.household_id == "hh_context_policy"
    assert selectors.mandate_id == "mandate_metadata"
    assert selectors.jurisdiction == "SG"
    assert selectors.benchmark_id == "benchmark_context_policy"


def test_policy_selectors_fall_back_to_stateful_mandate_when_metadata_is_absent():
    selectors = _policy_selectors(
        metadata=ProposalCreateMetadata(jurisdiction="SG"),
        stateful_input=ProposalStatefulInput(
            portfolio_id="pf_context_policy",
            as_of="2026-06-15",
            mandate_id="mandate_stateful",
        ),
    )

    assert selectors.mandate_id == "mandate_stateful"
    assert selectors.jurisdiction == "SG"


def test_proposal_context_facade_reexports_focused_owner_modules():
    assert context_facade.resolve_create_request is resolve_create_request
    assert context_facade.build_simulation_request_hash is build_simulation_request_hash
    assert context_facade.build_context_resolution_evidence is build_context_resolution_evidence
    assert context_facade.ResolvedSimulationContext is ResolvedSimulationContext


def test_proposal_runtime_context_imports_use_focused_owner_modules():
    runtime_paths = [
        Path("src/core/proposals/create_command.py"),
        Path("src/core/proposals/version_command.py"),
        Path("src/core/proposals/async_payloads.py"),
        Path("src/core/workspace/reevaluation.py"),
        Path("src/core/workspace/handoff.py"),
        Path("src/api/services/advisory_simulation_service.py"),
        Path("src/api/services/advisory_simulation_validation.py"),
        Path("src/api/services/advisory_simulation_evaluation.py"),
    ]

    for path in runtime_paths:
        source = path.read_text(encoding="utf-8")

        assert "from src.core.proposals.context import" not in source
        assert "src.core.proposals.context_" in source


def test_proposal_context_facade_stays_thin():
    source = Path("src/core/proposals/context.py").read_text(encoding="utf-8")

    assert "def resolve_create_request(" not in source
    assert "def build_create_request_hash(" not in source
    assert "def build_context_resolution_evidence(" not in source
    assert "from src.core.proposals.context_resolution import" in source
    assert "from src.core.proposals.context_hashing import" in source
    assert "from src.core.proposals.context_evidence import" in source
