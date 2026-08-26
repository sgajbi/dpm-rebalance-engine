"""Shared live-parity contracts and policy-evaluation support helpers."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Protocol, cast

import httpx


class PolicyParityScenario(Protocol):
    """Minimum scenario fields required to build deterministic parity evidence."""

    portfolio_id: str
    reporting_currency: str


Assertion = Callable[[bool, str], None]
FeatureByKey = Callable[[dict[str, Any], str], dict[str, Any]]


class GetJson(Protocol):
    """Typed adapter for an expected-status JSON GET."""

    def __call__(
        self,
        client: httpx.Client,
        *,
        url: str,
        expected_status: int,
    ) -> dict[str, Any]: ...


class AssertPersistedReadSurfaces(Protocol):
    """Typed adapter for the canonical persisted proposal read-surface proof."""

    def __call__(
        self,
        client: httpx.Client,
        *,
        advise_base_url: str,
        proposal_id: str,
        expected_portfolio_id: str,
        created_by_filter: str | None,
        current_version_no: int,
        expected_state: str,
        expected_report_status: str,
        get_json: GetJson,
        assert_condition: Assertion,
    ) -> None: ...


class PostJson(Protocol):
    """Typed adapter for an expected-status JSON POST."""

    def __call__(
        self,
        client: httpx.Client,
        *,
        url: str,
        expected_status: int,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...


class RequestJson(Protocol):
    """Typed adapter for an expected-status JSON request of any HTTP method."""

    def __call__(
        self,
        client: httpx.Client,
        *,
        method: str,
        url: str,
        expected_status: int,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...


class StatefulProposalScenario(Protocol):
    """Minimum source context needed to create a stateful advisory proposal."""

    @property
    def portfolio_id(self) -> str: ...

    @property
    def as_of_date(self) -> str: ...


class CreateStatefulProposal(Protocol):
    """Create a stateful proposal while preserving optional narrative input."""

    def __call__(
        self,
        client: httpx.Client,
        *,
        advise_base_url: str,
        scenario: StatefulProposalScenario,
        created_by: str,
        narrative_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


def stateful_proposal_input(
    scenario: StatefulProposalScenario,
    narrative_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the governed stateful source input shared by proposal and version creation."""
    stateful_input: dict[str, Any] = {
        "portfolio_id": scenario.portfolio_id,
        "as_of": scenario.as_of_date,
    }
    if narrative_request is not None:
        stateful_input["narrative_request"] = narrative_request
    return stateful_input


def ensure_sg_policy_pack_active(
    client: httpx.Client,
    *,
    advise_base_url: str,
    get_json: GetJson,
    post_json: PostJson,
) -> None:
    """Ensure the governed SG reference policy pack is active before evaluation."""
    detail = get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-packs/SG_PRIVATE_BANKING_REFERENCE/versions/2026.05",
        expected_status=200,
    )
    policy_pack = detail["policy_pack"]
    if policy_pack["activation_state"] == "ACTIVE":
        return
    content_hash = str(policy_pack["content_hash"])
    post_json(
        client,
        url=f"{advise_base_url}/advisory/policy-packs/SG_PRIVATE_BANKING_REFERENCE/versions/2026.05/validate",
        expected_status=200,
        json_body={
            "requested_by": "policy_steward_live",
            "reason": {"purpose": "live policy pack validation"},
        },
        headers={"Idempotency-Key": f"live-policy-pack-validate-{uuid.uuid4().hex}"},
    )
    post_json(
        client,
        url=f"{advise_base_url}/advisory/policy-packs/SG_PRIVATE_BANKING_REFERENCE/versions/2026.05/activate",
        expected_status=200,
        json_body={
            "activated_by": "policy_checker_live",
            "source_content_hash": content_hash,
            "reason": {"purpose": "live policy pack activation"},
        },
        headers={"Idempotency-Key": f"live-policy-pack-activate-{uuid.uuid4().hex}"},
    )


def live_policy_evidence_bundle(*, scenario: PolicyParityScenario) -> dict[str, Any]:
    """Build the deterministic evidence bundle used by live policy parity checks."""
    return {
        "context_resolution": {
            "advisory_policy_context": {
                "household_id": "HH-PB-001",
                "jurisdiction": "SG",
                "client_classification": "ACCREDITED_INVESTOR",
                "booking_center_code": "SG",
                "account_id": "ACCT-PB-001",
                "time_horizon": "5Y",
                "liquidity_need": "MEDIUM",
                "mandate_id": "MANDATE-BALANCED-001",
                "objectives": ["capital_preservation", "balanced_growth"],
                "restrictions": ["no_single_name_above_10pct"],
            }
        },
        "inputs": {
            "portfolio_snapshot": {
                "portfolio_id": scenario.portfolio_id,
                "positions": [{"instrument_id": "SG_STRUCTURED_NOTE", "quantity": "100"}],
                "cash_balances": [{"currency": scenario.reporting_currency, "amount": "50000"}],
            },
            "market_data_snapshot": {
                "prices": [
                    {
                        "instrument_id": "SG_STRUCTURED_NOTE",
                        "price": "100",
                        "currency": scenario.reporting_currency,
                    }
                ],
                "fx_rates": [{"pair": "USD/SGD", "rate": "1.35"}],
            },
            "shelf_entries": [
                {
                    "instrument_id": "SG_STRUCTURED_NOTE",
                    "eligibility": {"jurisdictions": ["SG"]},
                    "target_market": {"client_segments": ["ACCREDITED_INVESTOR"]},
                    "complexity": "COMPLEX",
                    "private_asset": False,
                    "structured_product": True,
                }
            ],
            "proposed_trades": [{"instrument_id": "SG_STRUCTURED_NOTE", "side": "BUY"}],
        },
        "risk_lens": {
            "source_service": "lotus-risk",
            "single_position_concentration": {"top_position_weight_current": "0.10"},
            "issuer_concentration": {"hhi_current": "1200"},
            "drawdown": {"max_drawdown_1y": "0.08"},
            "var": {"var_95_1m": "0.04"},
            "stress": {"equity_down_20": "-0.09"},
            "liquidity_risk": {"days_to_liquidate": "3"},
            "private_asset_risk": {"private_asset_weight": "0.00"},
            "climate_geopolitical_risk": {"status": "not_material"},
        },
        "artifact": {
            "assumptions_and_limits": {
                "costs_and_fees": {"included": True},
                "tax": {"included": True},
                "execution": {"included": True},
            },
            "disclosures": {
                "product_docs": [{"instrument_id": "SG_STRUCTURED_NOTE", "doc_ref": "Term sheet"}],
            },
        },
        "conflict_evidence": {
            "material_conflict": False,
            "review_ref": "conflict-review-live-001",
        },
    }


def request_live_policy_report(
    client: httpx.Client,
    *,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
    scenario: PolicyParityScenario,
    assert_condition: Assertion,
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Normalize ready and provider-degraded report-package outcomes for the snapshot."""
    report_response = client.post(
        f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/report-packages",
        json={
            "requested_by": "policy_checker_live",
            "portfolio_id": scenario.portfolio_id,
            "source_evaluation_hash": evaluation_hash,
            "requested_output_formats": ["pdf"],
            "client_ready_document_requested": False,
            "reason": {"purpose": "policy sign-off package live proof"},
        },
        headers={"Idempotency-Key": f"live-policy-report-{uuid.uuid4().hex}"},
    )
    if report_response.status_code == 200:
        report_body = cast(dict[str, Any], report_response.json())
        return str(cast(dict[str, Any], report_body["report"])["status"]), report_body, None

    assert_condition(
        report_response.status_code == 503,
        (
            f"{evaluation_id}: expected policy report package success or degraded 503, got "
            f"{report_response.status_code} body={report_response.text}"
        ),
    )
    return "UNAVAILABLE", None, str(cast(dict[str, Any], report_response.json()).get("detail"))
