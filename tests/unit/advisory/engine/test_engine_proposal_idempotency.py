from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.core.common.idempotency import (
    normalize_optional_idempotency_key,
    normalize_required_idempotency_key,
)
from src.core.proposals.context_evidence import build_context_resolution_evidence
from src.core.proposals.context_resolution import resolve_create_request
from src.core.proposals.create_command import (
    _is_matching_legacy_replay,
    _legacy_context_matches,
    _legacy_narrative_request_matches,
    _legacy_proposal_fields_match,
)
from src.core.proposals.exceptions import ProposalValidationError
from src.core.proposals.idempotency import (
    ProposalReplayHashConflictError,
    find_replayed_approval,
    find_replayed_event,
    load_replayed_approval,
    load_replayed_event,
)
from src.core.proposals.idempotency_validation import require_proposal_idempotency_key
from src.core.proposals.input_request_models import ProposalCreateRequest
from src.core.proposals.models import ProposalApprovalRecordData, ProposalWorkflowEventRecord
from src.infrastructure.proposals.in_memory import InMemoryProposalRepository


class _NarrativeRequest:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return self._payload


class _LegacyReplayRepository:
    def __init__(self, proposal: object | None, version: object | None) -> None:
        self._proposal = proposal
        self._version = version

    def get_proposal(self, *, proposal_id: str) -> object | None:
        assert proposal_id == "pp_legacy_replay"
        return self._proposal

    def get_version(self, *, proposal_id: str, version_no: int) -> object | None:
        assert proposal_id == "pp_legacy_replay"
        assert version_no == 1
        return self._version


def _legacy_direct_simulate_request(*, portfolio_id: str = "pf_legacy_direct") -> dict[str, object]:
    return {
        "portfolio_snapshot": {
            "portfolio_id": portfolio_id,
            "base_currency": "USD",
            "positions": [{"instrument_id": "EQ_OLD", "quantity": "10"}],
            "cash_balances": [{"currency": "USD", "amount": "1000"}],
        },
        "market_data_snapshot": {
            "prices": [{"instrument_id": "EQ_OLD", "price": "100", "currency": "USD"}],
            "fx_rates": [],
        },
        "shelf_entries": [{"instrument_id": "EQ_OLD", "status": "APPROVED"}],
        "options": {"enable_proposal_simulation": True},
        "proposed_cash_flows": [{"currency": "USD", "amount": "100"}],
        "proposed_trades": [{"side": "SELL", "instrument_id": "EQ_OLD", "quantity": "1"}],
        "reference_model": {
            "model_id": "bm_balanced",
            "as_of": "2026-05-20",
            "base_currency": "USD",
        },
    }


def _legacy_direct_evidence_inputs(payload: ProposalCreateRequest) -> dict[str, object]:
    resolved = resolve_create_request(payload)
    simulate_request = resolved.simulate_request
    return {
        "portfolio_snapshot": simulate_request.portfolio_snapshot.model_dump(mode="json"),
        "market_data_snapshot": simulate_request.market_data_snapshot.model_dump(mode="json"),
        "shelf_entries": [row.model_dump(mode="json") for row in simulate_request.shelf_entries],
        "options": simulate_request.options.model_dump(mode="json"),
        "proposed_cash_flows": [
            row.model_dump(mode="json") for row in simulate_request.proposed_cash_flows
        ],
        "proposed_trades": [
            row.model_dump(mode="json") for row in simulate_request.proposed_trades
        ],
        "reference_model": (
            simulate_request.reference_model.model_dump(mode="json")
            if simulate_request.reference_model is not None
            else None
        ),
    }


def _event(
    *,
    event_id: str,
    idempotency_key: str,
    request_hash: str,
) -> ProposalWorkflowEventRecord:
    return ProposalWorkflowEventRecord(
        event_id=event_id,
        proposal_id="pp_idem",
        event_type="SUBMITTED_FOR_RISK_REVIEW",
        from_state="DRAFT",
        to_state="RISK_REVIEW",
        actor_id="advisor_idem",
        occurred_at=datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc),
        reason_json={
            "idempotency_key": idempotency_key,
            "idempotency_request_hash": request_hash,
        },
        related_version_no=1,
    )


def _approval(
    *,
    approval_id: str,
    idempotency_key: str,
    request_hash: str,
) -> ProposalApprovalRecordData:
    return ProposalApprovalRecordData(
        approval_id=approval_id,
        proposal_id="pp_idem",
        approval_type="RISK",
        approved=True,
        actor_id="risk_idem",
        occurred_at=datetime(2026, 5, 20, 9, 5, tzinfo=timezone.utc),
        details_json={
            "idempotency_key": idempotency_key,
            "idempotency_request_hash": request_hash,
        },
        related_version_no=1,
    )


def test_find_replayed_event_returns_latest_matching_event():
    first = _event(event_id="pwe_first", idempotency_key="idem_target", request_hash="sha256:a")
    latest = _event(event_id="pwe_latest", idempotency_key="idem_target", request_hash="sha256:a")
    unrelated = _event(
        event_id="pwe_unrelated",
        idempotency_key="idem_other",
        request_hash="sha256:other",
    )

    assert (
        find_replayed_event(
            events=[first, unrelated, latest],
            idempotency_key="idem_target",
            request_hash="sha256:a",
        )
        == latest
    )


def test_normalize_required_idempotency_key_trims_and_rejects_blank_values():
    assert normalize_required_idempotency_key("  idem_target  ") == "idem_target"
    assert normalize_optional_idempotency_key("  idem_optional  ") == "idem_optional"
    assert normalize_optional_idempotency_key("   ") is None

    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REQUIRED"):
        normalize_required_idempotency_key(None)
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REQUIRED"):
        normalize_required_idempotency_key("   ")


def test_normalize_idempotency_key_rejects_control_characters_and_oversized_values():
    assert normalize_optional_idempotency_key("idem-target\x7f") is None
    assert normalize_optional_idempotency_key("i" * 129) is None

    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REQUIRED"):
        normalize_required_idempotency_key("idem-target\x7f")
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REQUIRED"):
        normalize_required_idempotency_key("i" * 129)


def test_require_proposal_idempotency_key_raises_domain_validation_error():
    assert require_proposal_idempotency_key("  idem_domain  ") == "idem_domain"

    with pytest.raises(ProposalValidationError) as exc:
        require_proposal_idempotency_key(" ")

    assert str(exc.value) == "IDEMPOTENCY_KEY_REQUIRED"


def test_find_replayed_event_raises_on_hash_conflict():
    event = _event(event_id="pwe_conflict", idempotency_key="idem_target", request_hash="sha256:a")

    with pytest.raises(ProposalReplayHashConflictError) as exc:
        find_replayed_event(
            events=[event],
            idempotency_key="idem_target",
            request_hash="sha256:b",
        )

    assert str(exc.value) == "IDEMPOTENCY_KEY_CONFLICT: request hash mismatch"


def test_find_replayed_approval_returns_latest_matching_approval():
    first = _approval(
        approval_id="pap_first",
        idempotency_key="idem_target",
        request_hash="sha256:a",
    )
    latest = _approval(
        approval_id="pap_latest",
        idempotency_key="idem_target",
        request_hash="sha256:a",
    )

    assert (
        find_replayed_approval(
            approvals=[first, latest],
            idempotency_key="idem_target",
            request_hash="sha256:a",
        )
        == latest
    )


def test_find_replayed_approval_handles_empty_key_and_hash_conflict():
    approval = _approval(
        approval_id="pap_conflict",
        idempotency_key="idem_target",
        request_hash="sha256:a",
    )

    assert (
        find_replayed_approval(
            approvals=[approval],
            idempotency_key=None,
            request_hash="sha256:a",
        )
        is None
    )
    with pytest.raises(ProposalReplayHashConflictError):
        find_replayed_approval(
            approvals=[approval],
            idempotency_key="idem_target",
            request_hash="sha256:b",
        )


def test_load_replayed_event_reads_repository_events():
    repository = InMemoryProposalRepository()
    first = _event(event_id="pwe_first", idempotency_key="idem_target", request_hash="sha256:a")
    latest = _event(event_id="pwe_latest", idempotency_key="idem_target", request_hash="sha256:a")
    repository.append_event(first)
    repository.append_event(latest)

    replayed = load_replayed_event(
        repository=repository,
        proposal_id="pp_idem",
        idempotency_key="idem_target",
        request_hash="sha256:a",
    )

    assert replayed == latest


def test_load_replayed_approval_reads_repository_approvals():
    repository = InMemoryProposalRepository()
    first = _approval(
        approval_id="pap_first",
        idempotency_key="idem_target",
        request_hash="sha256:a",
    )
    latest = _approval(
        approval_id="pap_latest",
        idempotency_key="idem_target",
        request_hash="sha256:a",
    )
    repository.create_approval(first)
    repository.create_approval(latest)

    replayed = load_replayed_approval(
        repository=repository,
        proposal_id="pp_idem",
        idempotency_key="idem_target",
        request_hash="sha256:a",
    )

    assert replayed == latest


def test_legacy_stateful_create_replay_ignores_version_hash_domain_and_enrichment() -> None:
    stateful_input = SimpleNamespace(
        portfolio_id="pf_legacy_replay",
        as_of="2026-05-20",
        household_id="hh_legacy_replay",
        mandate_id="mandate_stateful",
        benchmark_id="bm_legacy_replay",
        narrative_request=_NarrativeRequest(
            {
                "audience": "ADVISOR_REVIEW",
                "jurisdiction": "SG",
                "client_audience": "RELATIONSHIP_MANAGER",
                "product_types": [],
                "generation_mode": "DETERMINISTIC_TEMPLATE",
                "sections": ["overview", "risk"],
                "requested_by": "advisor_legacy",
            }
        ),
    )
    payload = SimpleNamespace(
        input_mode="stateful",
        stateful_input=stateful_input,
        created_by="advisor_legacy",
        metadata=SimpleNamespace(
            title="Legacy stateful proposal",
            advisor_notes="Replay compatibility proof",
            jurisdiction="SG",
            mandate_id=None,
        ),
    )
    proposal = SimpleNamespace(
        created_by="advisor_legacy",
        portfolio_id="pf_legacy_replay",
        title="Legacy stateful proposal",
        advisor_notes="Replay compatibility proof",
        jurisdiction="SG",
        mandate_id="mandate_stateful",
    )
    version = SimpleNamespace(
        request_hash="sha256:legacy-resolved-version",
        evidence_bundle_json={
            "context_resolution": {
                "resolved_context": {
                    "portfolio_id": "pf_legacy_replay",
                    "as_of": "2026-05-20",
                    "household_id": "hh_legacy_replay",
                    "benchmark_id": "bm_legacy_replay",
                }
            }
        },
        artifact_json={
            "proposal_narrative": {
                "audience": "ADVISOR_REVIEW",
                "narrative_policy": {
                    "context": {
                        "jurisdiction": "SG",
                        "client_audience": "RELATIONSHIP_MANAGER",
                        "product_types": ["EQUITY", "FX"],
                    }
                },
                "generation_mode": "DETERMINISTIC_TEMPLATE",
                "sections": [
                    {"section_key": "overview"},
                    {"section_key": "risk"},
                    "not-a-section",
                ],
            }
        },
    )

    assert _legacy_proposal_fields_match(
        proposal=proposal,
        payload=payload,
        stateful_input=stateful_input,
    )
    assert _legacy_context_matches(version=version, stateful_input=stateful_input)
    assert _legacy_narrative_request_matches(
        artifact=version.artifact_json,
        expected=stateful_input.narrative_request,
        created_by="advisor_legacy",
    )
    assert _is_matching_legacy_replay(
        repository=_LegacyReplayRepository(proposal=proposal, version=version),
        payload=payload,
        proposal_id="pp_legacy_replay",
        proposal_version_no=1,
    )


@pytest.mark.parametrize(
    ("payload_override", "version_override"),
    [
        ({"input_mode": "snapshot"}, {}),
        ({"stateful_input": None}, {}),
        (
            {
                "metadata": SimpleNamespace(
                    title="Changed", advisor_notes=None, jurisdiction=None, mandate_id=None
                )
            },
            {},
        ),
        ({}, {"evidence_bundle_json": {"context_resolution": "malformed"}}),
        ({}, {"evidence_bundle_json": {"context_resolution": {"resolved_context": "malformed"}}}),
        ({}, {"artifact_json": {"proposal_narrative": "malformed"}}),
        ({}, {"artifact_json": {"proposal_narrative": None}}),
    ],
)
def test_legacy_stateful_create_replay_helpers_reject_drift(
    payload_override: dict[str, object],
    version_override: dict[str, object],
) -> None:
    stateful_input = SimpleNamespace(
        portfolio_id="pf_legacy_replay",
        as_of="2026-05-20",
        household_id="hh_legacy_replay",
        mandate_id="mandate_stateful",
        benchmark_id="bm_legacy_replay",
        narrative_request=_NarrativeRequest(
            {
                "audience": "ADVISOR_REVIEW",
                "jurisdiction": "SG",
                "client_audience": "RELATIONSHIP_MANAGER",
                "product_types": ["EQUITY"],
                "generation_mode": "DETERMINISTIC_TEMPLATE",
                "sections": ["overview"],
                "requested_by": "advisor_legacy",
            }
        ),
    )
    payload = SimpleNamespace(
        input_mode="stateful",
        stateful_input=stateful_input,
        created_by="advisor_legacy",
        metadata=SimpleNamespace(
            title="Legacy stateful proposal",
            advisor_notes=None,
            jurisdiction=None,
            mandate_id=None,
        ),
    )
    for key, value in payload_override.items():
        setattr(payload, key, value)
    proposal = SimpleNamespace(
        created_by="advisor_legacy",
        portfolio_id="pf_legacy_replay",
        title="Legacy stateful proposal",
        advisor_notes=None,
        jurisdiction=None,
        mandate_id="mandate_stateful",
    )
    version = SimpleNamespace(
        request_hash="sha256:legacy",
        evidence_bundle_json={
            "context_resolution": {
                "resolved_context": {
                    "portfolio_id": "pf_legacy_replay",
                    "as_of": "2026-05-20",
                    "household_id": "hh_legacy_replay",
                    "benchmark_id": "bm_legacy_replay",
                }
            }
        },
        artifact_json={
            "proposal_narrative": {
                "audience": "ADVISOR_REVIEW",
                "narrative_policy": {
                    "context": {
                        "jurisdiction": "SG",
                        "client_audience": "RELATIONSHIP_MANAGER",
                        "product_types": ["EQUITY"],
                    }
                },
                "generation_mode": "DETERMINISTIC_TEMPLATE",
                "sections": [{"section_key": "overview"}],
            }
        },
    )
    for key, value in version_override.items():
        setattr(version, key, value)

    assert not _is_matching_legacy_replay(
        repository=_LegacyReplayRepository(proposal=proposal, version=version),
        payload=payload,
        proposal_id="pp_legacy_replay",
        proposal_version_no=1,
    )


@pytest.mark.parametrize("normalized", [False, True])
def test_legacy_create_replay_helpers_match_non_stateful_direct_payloads(
    normalized: bool,
) -> None:
    simulate_request = _legacy_direct_simulate_request()
    payload = ProposalCreateRequest(
        created_by="advisor_legacy",
        input_mode="stateless" if normalized else None,
        simulate_request=None if normalized else simulate_request,
        stateless_input={"simulate_request": simulate_request} if normalized else None,
        metadata={
            "title": "Legacy direct proposal",
            "advisor_notes": "Direct replay compatibility proof",
            "jurisdiction": "SG",
            "mandate_id": "mandate_direct",
        },
    )
    resolved = resolve_create_request(payload)
    proposal = SimpleNamespace(
        created_by="advisor_legacy",
        portfolio_id="pf_legacy_direct",
        title="Legacy direct proposal",
        advisor_notes="Direct replay compatibility proof",
        jurisdiction="SG",
        mandate_id="mandate_direct",
    )
    version = SimpleNamespace(
        request_hash="sha256:legacy-direct-resolved",
        evidence_bundle_json={
            "inputs": _legacy_direct_evidence_inputs(payload),
            "context_resolution": build_context_resolution_evidence(resolved),
        },
        artifact_json={"proposal_narrative": None},
    )

    assert _is_matching_legacy_replay(
        repository=_LegacyReplayRepository(proposal=proposal, version=version),
        payload=payload,
        proposal_id="pp_legacy_replay",
        proposal_version_no=1,
    )


def test_legacy_create_replay_helpers_reject_non_stateful_input_drift() -> None:
    original_payload = ProposalCreateRequest(
        created_by="advisor_legacy",
        input_mode="stateless",
        stateless_input={"simulate_request": _legacy_direct_simulate_request()},
        metadata={"title": "Legacy direct proposal"},
    )
    changed_request = _legacy_direct_simulate_request()
    changed_request["portfolio_snapshot"] = {
        **changed_request["portfolio_snapshot"],
        "portfolio_id": "pf_other",
    }
    changed_payload = ProposalCreateRequest(
        created_by="advisor_legacy",
        input_mode="stateless",
        stateless_input={"simulate_request": changed_request},
        metadata={"title": "Legacy direct proposal"},
    )
    resolved = resolve_create_request(original_payload)
    proposal = SimpleNamespace(
        created_by="advisor_legacy",
        portfolio_id="pf_legacy_direct",
        title="Legacy direct proposal",
        advisor_notes=None,
        jurisdiction=None,
        mandate_id=None,
    )
    version = SimpleNamespace(
        request_hash="sha256:legacy-direct-resolved",
        evidence_bundle_json={
            "inputs": _legacy_direct_evidence_inputs(original_payload),
            "context_resolution": build_context_resolution_evidence(resolved),
        },
        artifact_json={"proposal_narrative": None},
    )

    assert not _is_matching_legacy_replay(
        repository=_LegacyReplayRepository(proposal=proposal, version=version),
        payload=changed_payload,
        proposal_id="pp_legacy_replay",
        proposal_version_no=1,
    )


@pytest.mark.parametrize(
    ("context_override", "product_types", "generation_mode"),
    [
        ({"household_id": "hh_other"}, ["EQUITY"], "DETERMINISTIC_TEMPLATE"),
        ({"benchmark_id": "bm_other"}, ["EQUITY"], "DETERMINISTIC_TEMPLATE"),
        ({}, ["EQUITY"], "AI_ASSISTED_DRAFT"),
        ({}, ["STRUCTURED_PRODUCT"], "DETERMINISTIC_TEMPLATE"),
    ],
)
def test_legacy_stateful_create_replay_helpers_reject_stateful_scope_drift(
    context_override: dict[str, object],
    product_types: list[str],
    generation_mode: str,
) -> None:
    stateful_input = SimpleNamespace(
        portfolio_id="pf_legacy_replay",
        as_of="2026-05-20",
        household_id="hh_legacy_replay",
        mandate_id="mandate_stateful",
        benchmark_id="bm_legacy_replay",
        narrative_request=_NarrativeRequest(
            {
                "audience": "ADVISOR_REVIEW",
                "jurisdiction": "SG",
                "client_audience": "RELATIONSHIP_MANAGER",
                "product_types": ["EQUITY"],
                "generation_mode": "DETERMINISTIC_TEMPLATE",
                "sections": ["overview"],
                "requested_by": "advisor_legacy",
            }
        ),
    )
    payload = SimpleNamespace(
        input_mode="stateful",
        stateful_input=stateful_input,
        created_by="advisor_legacy",
        metadata=SimpleNamespace(
            title="Legacy stateful proposal",
            advisor_notes=None,
            jurisdiction=None,
            mandate_id=None,
        ),
    )
    proposal = SimpleNamespace(
        created_by="advisor_legacy",
        portfolio_id="pf_legacy_replay",
        title="Legacy stateful proposal",
        advisor_notes=None,
        jurisdiction=None,
        mandate_id="mandate_stateful",
    )
    resolved_context = {
        "portfolio_id": "pf_legacy_replay",
        "as_of": "2026-05-20",
        "household_id": "hh_legacy_replay",
        "benchmark_id": "bm_legacy_replay",
        **context_override,
    }
    narrative = {
        "audience": "ADVISOR_REVIEW",
        "narrative_policy": {
            "context": {
                "jurisdiction": "SG",
                "client_audience": "RELATIONSHIP_MANAGER",
                "product_types": product_types,
            }
        },
        "generation_mode": generation_mode,
        "sections": [{"section_key": "overview"}],
    }
    version = SimpleNamespace(
        request_hash="sha256:legacy",
        evidence_bundle_json={"context_resolution": {"resolved_context": resolved_context}},
        artifact_json={"proposal_narrative": narrative},
    )

    assert not _is_matching_legacy_replay(
        repository=_LegacyReplayRepository(proposal=proposal, version=version),
        payload=payload,
        proposal_id="pp_legacy_replay",
        proposal_version_no=1,
    )


def test_legacy_stateful_create_replay_helpers_reject_omitted_optional_scope() -> None:
    stateful_input = SimpleNamespace(
        portfolio_id="pf_legacy_replay",
        as_of="2026-05-20",
        household_id=None,
        mandate_id=None,
        benchmark_id=None,
        narrative_request=_NarrativeRequest(
            {
                "audience": "ADVISOR_REVIEW",
                "jurisdiction": "SG",
                "client_audience": "RELATIONSHIP_MANAGER",
                "product_types": ["EQUITY"],
                "generation_mode": "DETERMINISTIC_TEMPLATE",
                "sections": ["overview"],
                "requested_by": "advisor_legacy",
            }
        ),
    )
    payload = SimpleNamespace(
        input_mode="stateful",
        stateful_input=stateful_input,
        created_by="advisor_legacy",
        metadata=SimpleNamespace(
            title="Legacy stateful proposal",
            advisor_notes=None,
            jurisdiction=None,
            mandate_id=None,
        ),
    )
    proposal = SimpleNamespace(
        created_by="advisor_legacy",
        portfolio_id="pf_legacy_replay",
        title="Legacy stateful proposal",
        advisor_notes=None,
        jurisdiction=None,
        mandate_id=None,
    )
    version = SimpleNamespace(
        request_hash="sha256:legacy",
        evidence_bundle_json={
            "context_resolution": {
                "resolved_context": {
                    "portfolio_id": "pf_legacy_replay",
                    "as_of": "2026-05-20",
                    "household_id": "hh_legacy_replay",
                    "benchmark_id": "bm_legacy_replay",
                }
            }
        },
        artifact_json={
            "proposal_narrative": {
                "audience": "ADVISOR_REVIEW",
                "narrative_policy": {
                    "context": {
                        "jurisdiction": "SG",
                        "client_audience": "RELATIONSHIP_MANAGER",
                        "product_types": ["EQUITY"],
                    }
                },
                "generation_mode": "DETERMINISTIC_TEMPLATE",
                "sections": [{"section_key": "overview"}],
            }
        },
    )

    assert not _is_matching_legacy_replay(
        repository=_LegacyReplayRepository(proposal=proposal, version=version),
        payload=payload,
        proposal_id="pp_legacy_replay",
        proposal_version_no=1,
    )
