from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from src.core.workspace.input_models import WorkspaceStatefulInput
from src.integrations.lotus_core.portfolio_state_snapshot import (
    AuthoritativePortfolioStateError,
    core_snapshot_headers,
    core_snapshot_request,
    resolve_authoritative_portfolio_state,
)
from src.integrations.lotus_core.stateful_context import (
    LotusCoreStatefulContextUnavailableError,
    resolve_stateful_context_with_lotus_core,
)

CORE_SNAPSHOT_FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "tests"
    / "fixtures"
    / "lotus_core"
    / "portfolio_state_snapshot_v1.json"
)


def _snapshot_payload() -> dict[str, object]:
    return cast(dict[str, object], json.loads(CORE_SNAPSHOT_FIXTURE.read_text(encoding="utf-8")))


def _resolve(payload: dict[str, object]):
    return resolve_authoritative_portfolio_state(
        payload,
        expected_portfolio_id="PB_SG_GLOBAL_BAL_001",
        requested_as_of="2026-04-10",
        expected_tenant_id="tenant-sg-001",
    )


def test_core_snapshot_request_declares_advise_consumer_and_bounded_section() -> None:
    assert core_snapshot_request(as_of="2026-04-10", tenant_id="tenant-sg-001") == {
        "as_of_date": "2026-04-10",
        "snapshot_mode": "BASELINE",
        "consumer_system": "lotus-advise",
        "tenant_id": "tenant-sg-001",
        "sections": ["portfolio_state"],
        "options": {
            "include_zero_quantity_positions": False,
            "include_cash_positions": True,
            "position_basis": "market_value_base",
            "weight_basis": "total_market_value_base",
        },
    }

    assert core_snapshot_headers(tenant_id="tenant-sg-001") == {
        "X-Tenant-Id": "tenant-sg-001",
        "X-Service-Identity": "lotus-advise",
        "X-Role": "service",
    }


def test_authoritative_snapshot_preserves_core_owned_date_identity_and_hashes() -> None:
    effective_as_of, provenance = _resolve(_snapshot_payload())

    assert effective_as_of == "2026-04-10"
    assert provenance.portfolio.source_id == (
        "lotus-core:portfolio-state-snapshot:portfolio:"
        "PB_SG_GLOBAL_BAL_001:aaaaaaaaaaaaaaaaaaaaaaaa"
    )
    assert provenance.market_data.source_id == (
        "lotus-core:portfolio-state-snapshot:market_data:"
        "PB_SG_GLOBAL_BAL_001:bbbbbbbbbbbbbbbbbbbbbbbb"
    )
    assert provenance.portfolio.contract_version == "PortfolioStateSnapshot:v1"
    assert provenance.portfolio.source_hash == "a" * 64
    assert provenance.market_data.source_hash == "b" * 64
    assert provenance.raw_payload_stored is False


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("snapshot_mode",), "SIMULATION"),
        (("generated_at",), "2026-04-10T10:02:00"),
        (("contract_version",), "rfc_081_v2"),
        (("source_evidence_current",), False),
        (("freshness_status",), "STALE"),
        (("valuation_context", "effective_as_of_date"), None),
        (("valuation_context", "supportability"), "UNAVAILABLE"),
        (("source_provenance", "portfolio", "as_of"), "2026-03-26"),
        (("source_provenance", "market_data", "as_of"), "2026-03-26"),
        (("source_provenance", "portfolio", "source_hash"), "not-a-hash"),
    ],
)
def test_authoritative_snapshot_rejects_missing_stale_or_conflicting_evidence(
    path: tuple[str, ...], value: object
) -> None:
    payload = deepcopy(_snapshot_payload())
    target: dict[str, object] = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[assignment]
    target[path[-1]] = value

    with pytest.raises(AuthoritativePortfolioStateError) as exc_info:
        _resolve(payload)

    assert str(exc_info.value) == "LOTUS_CORE_STATEFUL_CONTEXT_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("portfolio_id", "OTHER_PORTFOLIO"),
        ("as_of_date", "2026-03-26"),
        ("tenant_id", "other-tenant"),
    ],
)
def test_authoritative_snapshot_rejects_scope_mismatch(field: str, value: str) -> None:
    payload = _snapshot_payload()
    payload[field] = value

    with pytest.raises(AuthoritativePortfolioStateError):
        _resolve(payload)


class _SnapshotResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _SnapshotOnlyClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.requests: list[tuple[str, str, dict[str, object] | None, dict[str, str] | None]] = []

    def __enter__(self) -> "_SnapshotOnlyClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def request(
        self,
        method: str,
        url: str,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _SnapshotResponse:
        self.requests.append((method, url, json, headers))
        return _SnapshotResponse(self._payload)


def test_stateful_resolver_rejects_invalid_snapshot_before_weaker_source_reads(
    monkeypatch,
) -> None:
    payload = _snapshot_payload()
    payload["source_evidence_current"] = False
    client = _SnapshotOnlyClient(payload)
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", "http://core-query.test")
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://core-control.test")
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", "tenant-sg-001")
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: client,
    )

    with pytest.raises(
        LotusCoreStatefulContextUnavailableError,
        match="LOTUS_CORE_STATEFUL_CONTEXT_INVALID",
    ):
        resolve_stateful_context_with_lotus_core(
            WorkspaceStatefulInput(
                portfolio_id="PB_SG_GLOBAL_BAL_001",
                as_of="2026-04-10",
            )
        )

    assert len(client.requests) == 1
    _, url, request, headers = client.requests[0]
    assert url.endswith("/integration/portfolios/PB_SG_GLOBAL_BAL_001/core-snapshot")
    assert request is not None and request["consumer_system"] == "lotus-advise"
    assert headers is not None and headers["X-Tenant-Id"] == "tenant-sg-001"


def test_stateful_resolver_requires_tenant_before_opening_core_client(monkeypatch) -> None:
    monkeypatch.setenv("LOTUS_CORE_QUERY_BASE_URL", "http://core-query.test")
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://core-control.test")
    monkeypatch.delenv("LOTUS_ADVISE_TENANT_ID", raising=False)
    monkeypatch.setattr(
        "src.integrations.lotus_core.stateful_context.httpx.Client",
        lambda timeout: pytest.fail("Core client must not open without tenant authority"),
    )

    with pytest.raises(
        LotusCoreStatefulContextUnavailableError,
        match="LOTUS_CORE_STATEFUL_CONTEXT_UNAVAILABLE",
    ):
        resolve_stateful_context_with_lotus_core(
            WorkspaceStatefulInput(
                portfolio_id="PB_SG_GLOBAL_BAL_001",
                as_of="2026-04-10",
            )
        )
