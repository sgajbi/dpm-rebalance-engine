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
            "headers": {
                "X-Correlation-Id": "corr-554",
                "X-Tenant-Id": "tenant_sg",
            },
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
            policy_context={"tenant_id": "tenant_sg"},
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
            policy_context={"tenant_id": "tenant_sg"},
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
        policy_context={"tenant_id": "tenant_sg", "benchmark_id": "BM_NOT_FORWARDED"},
        correlation_id="corr-554",
    )

    assert client.calls[0]["json"] == {
        "as_of_date": "2026-03-25",
        "policy_context": {"tenant_id": "tenant_sg"},
    }


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
        policy_context={"tenant_id": "tenant_sg"},
        correlation_id="corr-554",
    )

    assert (evidence.supportability, evidence.effective_benchmark_id) == (
        "PARTIAL",
        "BM_GLOBAL_BALANCED",
    )


def _fetch(monkeypatch, *, payload: object, policy_context: dict[str, object] | None):
    client = _FakeClient(_FakeResponse(status_code=200, payload=payload))
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )
    return fetch_benchmark_assignment_with_lotus_core(
        portfolio_id="PF_1",
        as_of_date="2026-03-25",
        reporting_currency=None,
        policy_context=policy_context,
        correlation_id="corr-589",
    )


@pytest.mark.parametrize(
    "response_tenant_id",
    ["tenant_other", None],
    ids=["a different tenant", "no stated tenant"],
)
def test_fetch_refuses_an_assignment_it_cannot_confirm_belongs_to_the_requested_tenant(
    monkeypatch, response_tenant_id: str | None
) -> None:
    """A matching portfolio and as-of date do not establish tenant scope.

    Core is asked with a tenant and answers with one, and until the two are
    compared a misrouted or cache-collided response is indistinguishable from a
    correct one. A response that states no tenant cannot be confirmed either,
    so it is refused rather than accepted on the strength of the other two
    fields matching."""

    with pytest.raises(LotusCoreBenchmarkAssignmentUnavailableError) as exc_info:
        _fetch(
            monkeypatch,
            payload=_payload(tenant_id=response_tenant_id),
            policy_context={"tenant_id": "tenant_sg"},
        )

    assert exc_info.value.reason == "CORE_BENCHMARK_ASSIGNMENT_TENANT_MISMATCH"


def test_fetch_accepts_the_assignment_when_the_response_states_the_admitted_tenant(
    monkeypatch,
) -> None:
    """The control for the refusals above: same path, matching tenant, accepted."""

    evidence = _fetch(
        monkeypatch,
        payload=_payload(tenant_id="tenant_sg"),
        policy_context={"tenant_id": "tenant_sg"},
    )

    assert evidence.source_tenant_id == "tenant_sg"


@pytest.mark.parametrize(
    "policy_context",
    [None, {}, {"tenant_id": "   "}, {"policy_pack_id": "policy_pb_v1"}],
    ids=["no context", "empty context", "blank tenant", "context without a tenant"],
)
def test_fetch_refuses_an_unscoped_read_before_sending_any_request(
    monkeypatch, policy_context: dict[str, object] | None
) -> None:
    """An unscoped read is refused, and refused before the request is made.

    Core's shared middleware requires a nonblank `X-Tenant-Id` on this route and
    answers 401 without one, so an unscoped call could not have succeeded. It
    must also not be attempted: refusing only after a response came back would
    mean the request had already been made under no established authority. The
    recording client proves the difference -- it registers no call at all.

    This replaces an earlier test asserting the opposite. Tolerating the
    unscoped case was wrong in both directions: Core would have rejected it, and
    had it succeeded it would have let tenant-owned evidence reach READY with no
    tenant established."""

    client = _FakeClient(_FakeResponse(status_code=200, payload=_payload()))
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )

    with pytest.raises(LotusCoreBenchmarkAssignmentUnavailableError) as exc_info:
        fetch_benchmark_assignment_with_lotus_core(
            portfolio_id="PF_1",
            as_of_date="2026-03-25",
            reporting_currency=None,
            policy_context=policy_context,
            correlation_id="corr-589",
        )

    assert exc_info.value.reason == "CORE_BENCHMARK_ASSIGNMENT_TENANT_REQUIRED"
    assert client.calls == [], "the adapter must not reach Core without an admitted tenant"


def test_fetch_sends_the_admitted_tenant_in_the_header_core_actually_reads(monkeypatch) -> None:
    """The tenant must travel in `X-Tenant-Id`, not only in the body.

    Core resolves the tenant from that header in shared middleware before this
    protected route runs; a tenant present only in the body `policy_context`
    reaches a route that was never entered. The body still carries it, because
    that is Core's policy input, but the header is what establishes ingress
    authority."""

    client = _FakeClient(_FakeResponse(status_code=200, payload=_payload()))
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )

    fetch_benchmark_assignment_with_lotus_core(
        portfolio_id="PF_1",
        as_of_date="2026-03-25",
        reporting_currency=None,
        policy_context={"tenant_id": "tenant_sg"},
        correlation_id="corr-589",
    )

    assert client.calls[0]["headers"] == {
        "X-Correlation-Id": "corr-589",
        "X-Tenant-Id": "tenant_sg",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"reconciliation_status": "PENDING"},
        {"data_quality_status": "INCOMPLETE"},
    ],
    ids=["unreconciled", "incomplete data quality"],
)
def test_fetch_reports_partial_when_the_source_states_a_limitation_on_its_own_evidence(
    monkeypatch, overrides: dict[str, str]
) -> None:
    """READY was decided from currency, freshness and degradation alone.

    `reconciliation_status` and `data_quality_status` were parsed and stored
    but excluded from the decision, so an unreconciled or incomplete assignment
    was reported as ready to use. Keeping a limitation in the payload while
    reporting READY discards it exactly where it would have been acted on."""

    evidence = _fetch(
        monkeypatch,
        payload=_payload(**overrides),
        policy_context={"tenant_id": "tenant_sg"},
    )

    assert evidence.supportability == "PARTIAL"
    assert (evidence.source_reconciliation_status, evidence.source_data_quality_status) == (
        overrides.get("reconciliation_status", "RECONCILED"),
        overrides.get("data_quality_status", "COMPLETE"),
    )


def test_fetch_reports_ready_when_every_status_the_source_states_is_healthy(monkeypatch) -> None:
    """The control for the two downgrades above: same fields, healthy values,
    opposite outcome. Case follows the normalization the module already applies
    to freshness and degradation, so a source that lowercases its own
    vocabulary is not downgraded over formatting."""

    evidence = _fetch(
        monkeypatch,
        payload=_payload(reconciliation_status="reconciled", data_quality_status="complete"),
        policy_context={"tenant_id": "tenant_sg"},
    )

    assert evidence.supportability == "READY"
