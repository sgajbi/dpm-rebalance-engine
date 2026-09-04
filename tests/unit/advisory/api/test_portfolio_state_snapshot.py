from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from src.integrations.lotus_core.portfolio_state_snapshot import (
    AuthoritativePortfolioStateError,
    core_snapshot_headers,
    core_snapshot_request,
    resolve_authoritative_portfolio_state,
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


@pytest.mark.parametrize("requested_as_of", ["2026-04-10T10:00:00Z", "2026-04-10T23:59:59-05:00"])
def test_core_snapshot_request_normalizes_supported_timestamps_to_business_date(
    requested_as_of: str,
) -> None:
    request = core_snapshot_request(as_of=requested_as_of, tenant_id="tenant-sg-001")

    assert request["as_of_date"] == "2026-04-10"
    effective_as_of, _ = resolve_authoritative_portfolio_state(
        _snapshot_payload(),
        expected_portfolio_id="PB_SG_GLOBAL_BAL_001",
        requested_as_of=requested_as_of,
        expected_tenant_id="tenant-sg-001",
    )
    assert effective_as_of == "2026-04-10"


def test_core_snapshot_request_rejects_invalid_business_date_or_timestamp() -> None:
    with pytest.raises(
        AuthoritativePortfolioStateError, match="LOTUS_CORE_STATEFUL_CONTEXT_INVALID"
    ):
        core_snapshot_request(as_of="not-a-date", tenant_id="tenant-sg-001")


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
        (
            ("source_provenance", "portfolio", "valuation_timestamp"),
            "2026-04-10T10:00:00",
        ),
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


def test_authoritative_snapshot_rejects_future_effective_evidence() -> None:
    payload = _snapshot_payload()
    payload["valuation_context"]["effective_as_of_date"] = "2026-04-11"  # type: ignore[index]
    payload["source_provenance"]["portfolio"]["as_of"] = "2026-04-11"  # type: ignore[index]
    payload["source_provenance"]["market_data"]["as_of"] = "2026-04-11"  # type: ignore[index]

    with pytest.raises(AuthoritativePortfolioStateError):
        _resolve(payload)
