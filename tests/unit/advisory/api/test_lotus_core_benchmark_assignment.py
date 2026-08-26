from typing import Any

import httpx
import pytest

from src.integrations.lotus_core.benchmark_assignment import (
    LotusCoreBenchmarkAssignmentUnavailableError,
    fetch_benchmark_assignment_with_lotus_core,
)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "product_name": "BenchmarkAssignment",
        "product_version": "v1",
        "portfolio_id": "PF_1",
        "benchmark_id": "BM_GLOBAL_BALANCED",
        "as_of_date": "2026-03-25",
        "effective_from": "2026-01-01",
        "effective_to": None,
        "assignment_source": "benchmark_policy_engine",
        "assignment_status": "active",
        "assignment_recorded_at": "2026-03-25T09:15:00Z",
        "assignment_version": 3,
        "policy_pack_id": "policy_pb_v1",
        "source_system": "mandate-booking-system",
        "contract_version": "rfc_062_v1",
        "tenant_id": "tenant_sg",
        "generated_at": "2026-03-25T09:16:00Z",
        "restatement_version": "v1",
        "reconciliation_status": "RECONCILED",
        "data_quality_status": "COMPLETE",
        "latest_evidence_timestamp": "2026-03-25T09:14:00Z",
        "source_batch_fingerprint": "batch_20260325_0001",
        "snapshot_id": "snapshot_554",
        "content_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "source_refs": ["lotus-core://benchmark/PF_1/2026-03-25", "  "],
        "source_lineage": {
            "source_owner": "lotus-core",
            "source_product": "BenchmarkAssignment",
        },
        "source_evidence_current": True,
        "freshness_status": "CURRENT",
        "policy_version": "policy-v1",
        "degradation": {"status": "NONE"},
    }
    payload.update(overrides)
    return payload


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "upstream error",
                request=httpx.Request("POST", "http://lotus-core/benchmark-assignment"),
                response=httpx.Response(status_code=self.status_code, json=self._payload),
            )

    def json(self) -> object:
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.response


class _UnavailableClient:
    def __enter__(self) -> "_UnavailableClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]) -> _FakeResponse:
        raise httpx.ConnectError("Core is unavailable", request=httpx.Request("POST", url))


def test_fetch_maps_core_v1_assignment_with_full_source_audit_context(monkeypatch) -> None:
    client = _FakeClient(_FakeResponse(status_code=200, payload=_payload()))
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202/api")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )

    evidence = fetch_benchmark_assignment_with_lotus_core(
        portfolio_id="PF_1",
        as_of_date="2026-03-25",
        reporting_currency="USD",
        policy_context={"tenant_id": "tenant_sg", "policy_pack_id": "policy_pb_v1"},
        correlation_id="corr-554",
    )

    assert evidence.effective_benchmark_id == "BM_GLOBAL_BALANCED"
    assert evidence.effective_from_date == "2026-01-01"
    assert evidence.assignment_version == 3
    assert evidence.assignment_source == "benchmark_policy_engine"
    assert evidence.assignment_contract_version == "rfc_062_v1"
    assert evidence.source_policy_version == "policy-v1"
    assert evidence.source_lineage == {
        "source_owner": "lotus-core",
        "source_product": "BenchmarkAssignment",
    }
    assert evidence.source_references == ("lotus-core://benchmark/PF_1/2026-03-25",)
    assert evidence.supportability == "READY"
    assert client.calls == [
        {
            "url": "http://lotus-core:8202/api/integration/portfolios/PF_1/benchmark-assignment",
            "json": {
                "as_of_date": "2026-03-25",
                "reporting_currency": "USD",
                "policy_context": {"tenant_id": "tenant_sg", "policy_pack_id": "policy_pb_v1"},
            },
            "headers": {"X-Correlation-Id": "corr-554"},
        }
    ]


@pytest.mark.parametrize(
    ("status_code", "payload", "reason_code"),
    [
        (404, {"detail": "not found"}, "CORE_BENCHMARK_ASSIGNMENT_SOURCE_NOT_FOUND"),
        (200, {"unexpected": True}, "CORE_BENCHMARK_ASSIGNMENT_SOURCE_INVALID"),
        (
            200,
            _payload(content_hash="sha256:not-a-valid-content-hash"),
            "CORE_BENCHMARK_ASSIGNMENT_SOURCE_INVALID",
        ),
        (
            200,
            _payload(assignment_source=""),
            "CORE_BENCHMARK_ASSIGNMENT_SOURCE_INVALID",
        ),
        (200, _payload(portfolio_id="PF_OTHER"), "CORE_BENCHMARK_ASSIGNMENT_PORTFOLIO_MISMATCH"),
        (200, _payload(as_of_date="2026-03-26"), "CORE_BENCHMARK_ASSIGNMENT_AS_OF_MISMATCH"),
        (
            200,
            _payload(effective_from="2026-03-26"),
            "CORE_BENCHMARK_ASSIGNMENT_AS_OF_MISMATCH",
        ),
        (
            200,
            _payload(effective_from="2026-03-26", effective_to="2026-03-25"),
            "CORE_BENCHMARK_ASSIGNMENT_SOURCE_INVALID",
        ),
        (
            200,
            _payload(effective_to="2026-03-24"),
            "CORE_BENCHMARK_ASSIGNMENT_AS_OF_MISMATCH",
        ),
    ],
)
def test_fetch_rejects_missing_or_mismatched_source_evidence(
    monkeypatch,
    status_code: int,
    payload: object,
    reason_code: str,
) -> None:
    client = _FakeClient(_FakeResponse(status_code=status_code, payload=payload))
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )

    with pytest.raises(LotusCoreBenchmarkAssignmentUnavailableError) as exc_info:
        fetch_benchmark_assignment_with_lotus_core(
            portfolio_id="PF_1",
            as_of_date="2026-03-25",
            reporting_currency=None,
            policy_context=None,
            correlation_id="corr-554",
        )

    assert exc_info.value.reason == reason_code


def test_fetch_maps_core_transport_failure_to_typed_unavailable_evidence(monkeypatch) -> None:
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client",
        lambda timeout: _UnavailableClient(),
    )

    with pytest.raises(LotusCoreBenchmarkAssignmentUnavailableError) as exc_info:
        fetch_benchmark_assignment_with_lotus_core(
            portfolio_id="PF_1",
            as_of_date="2026-03-25",
            reporting_currency=None,
            policy_context=None,
            correlation_id="corr-554",
        )

    assert exc_info.value.reason == "CORE_BENCHMARK_ASSIGNMENT_SOURCE_UNAVAILABLE"


def test_fetch_omits_blank_optional_context_without_forwarding_unowned_fields(monkeypatch) -> None:
    client = _FakeClient(_FakeResponse(status_code=200, payload=_payload()))
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )

    fetch_benchmark_assignment_with_lotus_core(
        portfolio_id="PF_1",
        as_of_date="2026-03-25",
        reporting_currency="  ",
        policy_context={"tenant_id": " ", "benchmark_id": "BM_NOT_FORWARDED"},
        correlation_id="corr-554",
    )

    assert client.calls[0]["json"] == {"as_of_date": "2026-03-25"}


def test_fetch_maps_source_degradation_to_partial_without_discarding_source_facts(
    monkeypatch,
) -> None:
    client = _FakeClient(
        _FakeResponse(
            status_code=200,
            payload=_payload(
                source_evidence_current=False,
                freshness_status="STALE",
                degradation={"status": "STALE"},
            ),
        )
    )
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )

    evidence = fetch_benchmark_assignment_with_lotus_core(
        portfolio_id="PF_1",
        as_of_date="2026-03-25",
        reporting_currency=None,
        policy_context=None,
        correlation_id="corr-554",
    )

    assert (evidence.supportability, evidence.effective_benchmark_id) == (
        "PARTIAL",
        "BM_GLOBAL_BALANCED",
    )
