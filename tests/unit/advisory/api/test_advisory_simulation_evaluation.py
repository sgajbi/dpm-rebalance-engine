from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

import src.api.services.advisory_simulation_evaluation as simulation_evaluation
from src.core.advisory.alternatives_normalizer import AlternativesRequestNormalizationError


class _ProposalResultStub:
    def __init__(self) -> None:
        self.explanation: dict[str, Any] = {}


def _resolved_request_stub(as_of: str | None = "2026-06-01") -> SimpleNamespace:
    return SimpleNamespace(
        simulate_request=object(),
        resolved_context=SimpleNamespace(as_of=as_of),
        input_mode="stateful",
    )


def test_evaluate_simulation_result_adds_context_resolution(monkeypatch) -> None:
    result = _ProposalResultStub()
    captured: dict[str, Any] = {}
    context_resolution = {"advisory_policy_context": {"mandate_id": "mandate-001"}}

    monkeypatch.setattr(
        simulation_evaluation,
        "resolve_correlation_id",
        lambda correlation_id: f"resolved-{correlation_id}",
    )
    monkeypatch.setattr(
        simulation_evaluation,
        "build_context_resolution_evidence",
        lambda resolved_request: context_resolution,
    )

    def _evaluate_advisory_proposal(**kwargs):
        captured.update(kwargs)
        return result

    monkeypatch.setattr(
        simulation_evaluation,
        "evaluate_advisory_proposal",
        _evaluate_advisory_proposal,
    )

    evaluated = simulation_evaluation.evaluate_simulation_result(
        resolved_request=_resolved_request_stub(),  # type: ignore[arg-type]
        request_hash="sha256:simulation",
        idempotency_key="simulation-idem",
        correlation_id="corr-001",
    )

    assert evaluated is result
    assert evaluated.explanation["context_resolution"] == context_resolution
    assert captured["request_hash"] == "sha256:simulation"
    assert captured["idempotency_key"] == "simulation-idem"
    assert captured["correlation_id"] == "resolved-corr-001"
    assert captured["resolved_as_of"] == "2026-06-01"
    assert captured["input_mode"] == "stateful"
    assert captured["policy_context"] == {"mandate_id": "mandate-001"}


def test_evaluate_simulation_result_preserves_missing_lifecycle_date(monkeypatch) -> None:
    result = _ProposalResultStub()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        simulation_evaluation,
        "resolve_correlation_id",
        lambda correlation_id: f"resolved-{correlation_id}",
    )
    monkeypatch.setattr(
        simulation_evaluation,
        "build_context_resolution_evidence",
        lambda resolved_request: {"advisory_policy_context": {}},
    )
    monkeypatch.setattr(
        simulation_evaluation,
        "evaluate_advisory_proposal",
        lambda **kwargs: captured.update(kwargs) or result,
    )

    simulation_evaluation.evaluate_simulation_result(
        resolved_request=_resolved_request_stub(as_of=None),  # type: ignore[arg-type]
        request_hash="sha256:missing-as-of",
        idempotency_key=None,
        correlation_id="corr-001",
    )

    assert captured["resolved_as_of"] is None


def test_evaluate_simulation_result_translates_alternatives_normalization_error(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        simulation_evaluation,
        "resolve_correlation_id",
        lambda correlation_id: "corr-resolved",
    )
    monkeypatch.setattr(
        simulation_evaluation,
        "build_context_resolution_evidence",
        lambda resolved_request: {"advisory_policy_context": {}},
    )

    def _raise_alternatives_error(**_kwargs):
        raise AlternativesRequestNormalizationError(
            reason_code="ALTERNATIVES_OBJECTIVE_UNSUPPORTED",
            message="unsupported alternatives objective",
        )

    monkeypatch.setattr(
        simulation_evaluation,
        "evaluate_advisory_proposal",
        _raise_alternatives_error,
    )

    with pytest.raises(HTTPException) as exc_info:
        simulation_evaluation.evaluate_simulation_result(
            resolved_request=_resolved_request_stub(),  # type: ignore[arg-type]
            request_hash="sha256:simulation",
            idempotency_key="simulation-idem",
            correlation_id="corr-001",
        )

    assert exc_info.value.status_code == 422
    assert "ALTERNATIVES_OBJECTIVE_UNSUPPORTED" in exc_info.value.detail
