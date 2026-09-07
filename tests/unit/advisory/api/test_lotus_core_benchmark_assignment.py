import json
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
        tenant_id="tenant_sg",
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
            tenant_id="tenant_sg",
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
            tenant_id="tenant_sg",
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
        tenant_id="tenant_sg",
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
        tenant_id="tenant_sg",
    )

    assert (evidence.supportability, evidence.effective_benchmark_id) == (
        "PARTIAL",
        "BM_GLOBAL_BALANCED",
    )


def _fetch(
    monkeypatch,
    *,
    payload: object,
    policy_context: dict[str, object] | None,
    tenant_id: str = "tenant_sg",
):
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
        tenant_id=tenant_id,
    )


def test_fetch_refuses_a_response_whose_echoed_tenant_was_rewritten(monkeypatch) -> None:
    """Echo integrity, and deliberately nothing more.

    Core builds the response tenant as
    `request.policy_context.tenant_id if request.policy_context else None`, so
    this field is the tenant we sent. A value that comes back *different* means
    something rewrote the payload in transit, which is worth refusing. It does
    not mean the assignment belongs to another tenant, because the field never
    carried that claim -- see the test below."""

    with pytest.raises(LotusCoreBenchmarkAssignmentUnavailableError) as exc_info:
        _fetch(
            monkeypatch,
            payload=_payload(tenant_id="tenant_other"),
            policy_context={},
        )

    assert exc_info.value.reason == "CORE_BENCHMARK_ASSIGNMENT_TENANT_MISMATCH"


def test_a_response_that_echoes_no_tenant_is_refused(monkeypatch) -> None:
    """A missing echo means the response did not answer the request we made.

    This test previously asserted the opposite, and the reasoning it carried was
    sound when it was written: a null echo said something about the request, not
    about the assignment, because a request could legitimately carry no policy
    context. `_request_payload` now sends the admitted tenant on every request,
    so that is no longer reachable. A response echoing nothing is stale, from an
    incompatible Core revision, or in breach of the documented echo -- and none
    of those should be mapped and reported READY.

    The two changes were made in the same slice and only one of them was
    reconsidered; the relaxation outlived the condition that justified it.

    This is still not attribution. It says the response corresponds to the
    request, not that the assignment belongs to the tenant.
    """

    with pytest.raises(LotusCoreBenchmarkAssignmentUnavailableError) as exc_info:
        _fetch(
            monkeypatch,
            payload=_payload(tenant_id=None),
            policy_context={},
        )

    assert exc_info.value.reason == "CORE_BENCHMARK_ASSIGNMENT_TENANT_MISMATCH"


def test_every_request_carries_the_admitted_tenant_so_a_missing_echo_is_anomalous(
    monkeypatch,
) -> None:
    """The premise the refusal above depends on, pinned rather than assumed.

    If the payload ever stopped sending the tenant unconditionally, refusing a
    null echo would start rejecting valid responses. This asserts the tenant is
    in the body even when the caller supplies no policy context at all.
    """

    client = _FakeClient(_FakeResponse(status_code=200, payload=_payload()))
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )

    fetch_benchmark_assignment_with_lotus_core(
        portfolio_id="PF_1",
        as_of_date="2026-03-25",
        reporting_currency=None,
        policy_context=None,
        correlation_id="corr-621",
        tenant_id="tenant_sg",
    )

    assert client.calls[0]["json"]["policy_context"] == {"tenant_id": "tenant_sg"}


@pytest.mark.parametrize(
    "tenant_id",
    ["", "   ", "\t"],
    ids=["empty", "spaces", "tab"],
)
def test_fetch_refuses_an_unscoped_read_before_sending_any_request(
    monkeypatch, tenant_id: str
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
            policy_context={"policy_pack_id": "policy_pb_v1", "benchmark_id": "BM_X"},
            correlation_id="corr-589",
            tenant_id=tenant_id,
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
        tenant_id="tenant_sg",
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


def test_the_production_policy_context_shape_is_accepted_and_never_supplies_authority(
    monkeypatch,
) -> None:
    """The exact dictionary the proposal flow builds must work, and must not be authority.

    `build_advisory_policy_context()` returns input_mode, context_source, three
    context statuses, household, mandate, jurisdiction, legal entity, benchmark
    and missing_context. It has no tenant, and it never will have one by design:
    if authority were read from here, adding a tenant key to a business-policy
    dictionary would let policy input choose the scope a read runs under.

    An earlier revision took the tenant from this dictionary, so every call
    carrying the real shape would have been refused before reaching Core, and
    the tests hid it by passing a tenant-bearing context production never builds.
    This uses the real shape, keyed from the production builder's own output.
    """

    from src.core.advisory.policy_context import (
        ProposalPolicySelectors,
        build_advisory_policy_context,
    )

    production_context = build_advisory_policy_context(
        input_mode="STATEFUL",
        resolution_source="CORE",
        selectors=ProposalPolicySelectors(
            household_id="HH_1",
            mandate_id="MD_1",
            jurisdiction="SG",
            legal_entity_code="LE_1",
            benchmark_id="BM_GLOBAL_BALANCED",
        ),
    )
    assert "tenant_id" not in production_context, (
        "the production policy context must stay free of tenant, or authority and "
        "business policy become the same input"
    )

    client = _FakeClient(_FakeResponse(status_code=200, payload=_payload()))
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )

    evidence = fetch_benchmark_assignment_with_lotus_core(
        portfolio_id="PF_1",
        as_of_date="2026-03-25",
        reporting_currency=None,
        policy_context=production_context,
        correlation_id="corr-621",
        tenant_id="tenant_sg",
    )

    assert evidence.effective_benchmark_id == "BM_GLOBAL_BALANCED"
    assert client.calls[0]["headers"]["X-Tenant-Id"] == "tenant_sg"
    assert client.calls[0]["json"]["policy_context"]["tenant_id"] == "tenant_sg"


class _UndecodableResponse(_FakeResponse):
    """A 200 whose body is not JSON, which `_FakeResponse` could never produce.

    The manifest declared malformed-JSON coverage against a case that returned a
    schema-invalid *dictionary*. That exercises field validation, not decoding —
    `json()` returned an object and never raised, so the malformed path had no
    evidence behind it at all.

    httpx raises `json.JSONDecodeError` from `Response.json()` on an undecodable
    body, so that is what this raises.
    """

    def json(self) -> object:
        raise json.JSONDecodeError("Expecting value", "<not json>", 0)


def test_fetch_refuses_a_provider_response_whose_body_cannot_be_decoded(monkeypatch) -> None:
    """An undecodable body is a source-invalid refusal, not an unhandled crash."""

    client = _FakeClient(_UndecodableResponse(status_code=200, payload=None))
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )

    with pytest.raises(LotusCoreBenchmarkAssignmentUnavailableError) as exc_info:
        fetch_benchmark_assignment_with_lotus_core(
            portfolio_id="PF_1",
            as_of_date="2026-03-25",
            reporting_currency=None,
            policy_context={},
            correlation_id="corr-621",
            tenant_id="tenant_sg",
        )

    # The exact reason, not a set. A set membership would pass if an undecodable body
    # were reclassified as SOURCE_UNAVAILABLE, which says "try again later" about a
    # response that will never become valid -- and the manifest declares this case as
    # source-invalid coverage, so a weak assertion would leave the contract lane unable
    # to detect exactly the drift it claims to guard.
    assert exc_info.value.reason == "CORE_BENCHMARK_ASSIGNMENT_SOURCE_INVALID"


class _FailingRecordingClient(_FakeClient):
    """Records every outbound attempt and fails each one at the transport layer."""

    def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        raise httpx.ConnectError("Core is unavailable", request=httpx.Request("POST", url))


def test_a_failed_core_read_is_attempted_once_and_not_retried(monkeypatch) -> None:
    """A failing read under an admitted tenant is attempted exactly once.

    The manifest previously claimed retry coverage from the unscoped-refusal test,
    which supplies a blank tenant and asserts zero calls. That is true and says
    nothing about retry: a call that is never made cannot be made twice.

    This uses an admitted tenant so the request genuinely goes out, then fails it,
    and asserts the attempt count. It is what would detect an accidental repeated
    outbound request, and it pins the adapter's bounded non-retry posture — retry
    belongs to whoever owns the operation's idempotency, not to a read that cannot
    know whether repeating is safe.
    """

    client = _FailingRecordingClient(_FakeResponse(status_code=200, payload=_payload()))
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8202")
    monkeypatch.setattr(
        "src.integrations.lotus_core.benchmark_assignment.httpx.Client", lambda timeout: client
    )

    with pytest.raises(LotusCoreBenchmarkAssignmentUnavailableError) as exc_info:
        fetch_benchmark_assignment_with_lotus_core(
            portfolio_id="PF_1",
            as_of_date="2026-03-25",
            reporting_currency=None,
            policy_context={},
            correlation_id="corr-621",
            tenant_id="tenant_sg",
        )

    assert exc_info.value.reason == "CORE_BENCHMARK_ASSIGNMENT_SOURCE_UNAVAILABLE"
    assert len(client.calls) == 1, (
        f"the adapter attempted the read {len(client.calls)} times; it must not retry a Core read "
        f"whose idempotency it cannot establish"
    )
    assert client.calls[0]["headers"]["X-Tenant-Id"] == "tenant_sg"
