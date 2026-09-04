from __future__ import annotations

import hashlib
from typing import Any


class FakeHttpxResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("boom")

    def json(self) -> Any:
        return self._payload


class CountingLotusCoreQueryClient:
    def __init__(self, responses: dict[tuple[str, str], FakeHttpxResponse]) -> None:
        self._responses = responses
        self.request_count = 0
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def __enter__(self) -> CountingLotusCoreQueryClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def request(
        self,
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeHttpxResponse:
        del headers
        self.request_count += 1
        self.requests.append((method.upper(), url, json))
        if method.upper() == "POST" and url.endswith("/core-snapshot") and json is not None:
            return _authoritative_core_snapshot_response(url=url, request=json)
        key = (method.upper(), url)
        if key not in self._responses and "?" in url:
            key = (method.upper(), url.split("?", 1)[0])
        if key not in self._responses:
            raise AssertionError(f"unexpected request: {key} body={json}")
        return self._responses[key]


def build_basic_stateful_query_responses(
    *,
    base_url: str,
    portfolio_id: str,
    as_of: str,
    base_currency: str = "USD",
) -> dict[tuple[str, str], FakeHttpxResponse]:
    return {
        ("GET", f"{base_url}/portfolios/{portfolio_id}"): FakeHttpxResponse(
            {"portfolio_id": portfolio_id, "base_currency": base_currency}
        ),
        ("GET", f"{base_url}/portfolios/{portfolio_id}/positions"): FakeHttpxResponse(
            {"portfolio_id": portfolio_id, "positions": []}
        ),
        ("GET", f"{base_url}/portfolios/{portfolio_id}/cash-balances"): FakeHttpxResponse(
            {
                "portfolio_id": portfolio_id,
                "resolved_as_of_date": as_of,
                "cash_accounts": [],
            }
        ),
    }


def _authoritative_core_snapshot_response(
    *,
    url: str,
    request: dict[str, Any],
) -> FakeHttpxResponse:
    portfolio_id = url.rsplit("/", 2)[-2]
    as_of = str(request["as_of_date"])
    tenant_id = str(request["tenant_id"])
    portfolio_hash = _source_hash("PORTFOLIO", portfolio_id=portfolio_id, as_of=as_of)
    market_data_hash = _source_hash("MARKET_DATA", portfolio_id=portfolio_id, as_of=as_of)
    return FakeHttpxResponse(
        {
            "product_name": "PortfolioStateSnapshot",
            "product_version": "v1",
            "portfolio_id": portfolio_id,
            "as_of_date": as_of,
            "snapshot_mode": "BASELINE",
            "generated_at": f"{as_of}T10:02:00Z",
            "contract_version": "rfc_081_v1",
            "tenant_id": tenant_id,
            "source_evidence_current": True,
            "freshness_status": "CURRENT",
            "valuation_context": {
                "effective_as_of_date": as_of,
                "supportability": "READY",
                "reason_code": "SOURCE_EVIDENCE_READY",
            },
            "source_provenance": {
                "schema_version": "lotus.source-provenance.v1",
                "source_system": "LOTUS_CORE",
                "portfolio": _source_provenance_record(
                    source_kind="PORTFOLIO",
                    portfolio_id=portfolio_id,
                    as_of=as_of,
                    source_hash=portfolio_hash,
                ),
                "market_data": _source_provenance_record(
                    source_kind="MARKET_DATA",
                    portfolio_id=portfolio_id,
                    as_of=as_of,
                    source_hash=market_data_hash,
                ),
                "raw_payload_stored": False,
            },
        }
    )


def _source_hash(source_kind: str, *, portfolio_id: str, as_of: str) -> str:
    return hashlib.sha256(f"{source_kind}:{portfolio_id}:{as_of}".encode()).hexdigest()


def _source_provenance_record(
    *,
    source_kind: str,
    portfolio_id: str,
    as_of: str,
    source_hash: str,
) -> dict[str, str]:
    return {
        "source_system": "LOTUS_CORE",
        "source_kind": source_kind,
        "source_id": (
            f"lotus-core:portfolio-state-snapshot:{source_kind.lower()}:"
            f"{portfolio_id}:{source_hash[:24]}"
        ),
        "as_of": as_of,
        "contract_version": "PortfolioStateSnapshot:v1",
        "source_hash": source_hash,
        "freshness_status": "CURRENT",
    }
