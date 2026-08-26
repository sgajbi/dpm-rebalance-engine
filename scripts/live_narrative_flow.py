"""Certify the governed live proposal-narrative workflow and review posture."""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx

from scripts.live_policy_evaluation_support import (
    Assertion,
    FeatureByKey,
    GetJson,
    PostJson,
)
from scripts.live_runtime_proposal_narrative import LiveProposalNarrativeSnapshot


class NarrativeParityScenario(Protocol):
    """Minimum scenario fields required by the narrative certification flow."""

    portfolio_id: str
    as_of_date: str


CreateStatefulProposal = Callable[..., dict[str, Any]]
SnapshotExtractor = Callable[..., LiveProposalNarrativeSnapshot]
AiLineageStatusExtractor = Callable[[dict[str, Any]], tuple[str, str | None]]


@dataclass(frozen=True)
class LiveNarrativeFlowPrimitives:
    """Typed dependencies needed by narrative proof without importing the validator module."""

    create_stateful_proposal: CreateStatefulProposal
    get_json: GetJson
    post_json: PostJson
    feature_by_key: FeatureByKey
    assertion: Assertion
    extract_snapshot: SnapshotExtractor
    extract_ai_lineage_status: AiLineageStatusExtractor


def _advisor_review_narrative_request(
    *,
    generation_mode: str = "DETERMINISTIC_TEMPLATE",
) -> dict[str, Any]:
    return {
        "audience": "ADVISOR_REVIEW",
        "jurisdiction": "SG",
        "client_audience": "ADVISOR_REVIEW",
        "sections": ["EXECUTIVE_SUMMARY", "RISK_AND_CONCENTRATION"],
        "requested_by": "live-parity-validator",
        "generation_mode": generation_mode,
    }


def _assert_ai_assisted_narrative_when_enabled(
    client: httpx.Client,
    *,
    primitives: LiveNarrativeFlowPrimitives,
    advise_base_url: str,
    scenario: NarrativeParityScenario,
) -> tuple[str, str | None]:
    """Prove AI assistance remains explicitly opt-in and preserves bounded lineage."""
    if os.getenv("LOTUS_ADVISE_VALIDATE_AI_ASSISTED_NARRATIVE") != "1":
        return "SKIPPED_NOT_ENABLED", None

    created = primitives.create_stateful_proposal(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator-ai-narrative",
        narrative_request=_advisor_review_narrative_request(generation_mode="AI_ASSISTED_DRAFT"),
    )
    version = cast(dict[str, Any], created["version"])
    narrative = cast(
        dict[str, Any],
        cast(dict[str, Any], version["artifact"])["proposal_narrative"],
    )
    primitives.assertion(
        narrative["generation_mode"] in {"AI_ASSISTED_DRAFT", "DETERMINISTIC_TEMPLATE"},
        f"AI-assisted narrative returned unsupported generation mode {narrative}",
    )
    primitives.assertion(
        isinstance(narrative.get("sections"), list) and narrative["sections"],
        "AI-assisted narrative proof returned no narrative sections",
    )
    return primitives.extract_ai_lineage_status(narrative)


def assert_live_proposal_narrative_flow(
    client: httpx.Client,
    *,
    primitives: LiveNarrativeFlowPrimitives,
    advise_base_url: str,
    scenario: NarrativeParityScenario,
) -> LiveProposalNarrativeSnapshot:
    """Run the narrative proof and project its stable advisor-review snapshot."""
    started = time.perf_counter()
    created = primitives.create_stateful_proposal(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator-narrative",
        narrative_request=_advisor_review_narrative_request(),
    )
    proposal_id = str(created["proposal"]["proposal_id"])
    version = cast(dict[str, Any], created["version"])
    version_no = int(version["version_no"])
    version_artifact = cast(dict[str, Any], version["artifact"])
    narrative = cast(dict[str, Any], version_artifact["proposal_narrative"])
    primitives.assertion(
        narrative["generation_mode"] == "DETERMINISTIC_TEMPLATE",
        f"{proposal_id}: deterministic narrative generation mode drifted: {narrative}",
    )
    summarize = [
        item
        for item in cast(list[dict[str, Any]], narrative["guardrail_results"])
        if item.get("status") == "PASS"
    ]
    primitives.assertion(
        bool(summarize),
        f"{proposal_id}: deterministic narrative did not emit pass guardrail evidence",
    )
    primitives.assertion(bool(summarize), f"{proposal_id}: guardrail pass posture missing")

    read_body = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/narrative",
        expected_status=200,
    )
    regeneration_body = primitives.post_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/narrative/regenerate"
        ),
        expected_status=200,
        json_body={
            "requested_by": "live-parity-validator",
            "reason": "Live validation of non-persistent regeneration posture.",
            "sections": ["EXECUTIVE_SUMMARY"],
        },
    )
    primitives.assertion(
        cast(dict[str, Any], regeneration_body["regeneration_posture"])["persistence_status"]
        == "NOT_PERSISTED_REVIEW_REQUIRED",
        f"{proposal_id}: regeneration unexpectedly persisted candidate narrative",
    )
    reread_body = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/narrative",
        expected_status=200,
    )
    primitives.assertion(
        reread_body["proposal_narrative"]["narrative_id"] == narrative["narrative_id"],
        f"{proposal_id}: regeneration mutated persisted narrative",
    )
    review_body = primitives.post_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/narrative/review"
        ),
        expected_status=200,
        json_body={
            "action": "APPROVE",
            "reviewed_by": "live-parity-validator",
            "reason": "Evidence-grounded advisor-review narrative live validation.",
            "client_ready_release_requested": False,
        },
        headers={"Idempotency-Key": f"live-narrative-review-{uuid.uuid4().hex}"},
    )
    primitives.assertion(
        review_body["narrative_review"]["review_state"] == "APPROVED_FOR_ADVISOR_USE",
        f"{proposal_id}: narrative review did not approve advisor-use posture",
    )
    primitives.assertion(
        review_body["narrative_review"]["client_ready_status"] == "NOT_REQUESTED",
        f"{proposal_id}: narrative review incorrectly promoted client-ready posture",
    )
    replay_body = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/replay-evidence",
        expected_status=200,
    )
    replay_evidence = cast(dict[str, Any], replay_body["evidence"])
    primitives.assertion(
        cast(dict[str, Any], replay_evidence["proposal_narrative"])["narrative_id"]
        == narrative["narrative_id"],
        f"{proposal_id}: replay evidence lost proposal narrative identity",
    )
    primitives.assertion(
        cast(dict[str, Any], replay_evidence["proposal_narrative_review"])["source_narrative_hash"]
        == review_body["narrative_review"]["source_narrative_hash"],
        f"{proposal_id}: replay evidence lost narrative review source hash",
    )

    capabilities = primitives.get_json(
        client,
        url=f"{advise_base_url}/platform/capabilities",
        expected_status=200,
    )
    report_feature = primitives.feature_by_key(capabilities, "advisory.proposals.reporting")
    report_response = client.post(
        f"{advise_base_url}/advisory/proposals/{proposal_id}/report-requests",
        json={
            "report_type": "CLIENT_PROPOSAL_SUMMARY",
            "requested_by": "live-parity-validator",
            "related_version_no": version_no,
            "include_execution_summary": False,
            "include_reviewed_narrative": True,
        },
    )
    report_body: dict[str, Any] | None
    report_status: str
    if report_feature["operational_ready"]:
        primitives.assertion(
            report_response.status_code == 200,
            (
                f"{proposal_id}: expected reviewed narrative report package success, got "
                f"{report_response.status_code} body={report_response.text}"
            ),
        )
        report_body = cast(dict[str, Any], report_response.json())
        report_status = str(report_body["status"])
        package = cast(dict[str, Any], report_body["explanation"])["proposal_narrative_package"]
        primitives.assertion(
            package["package_status"] == "INCLUDED_REVIEWED_NARRATIVE",
            f"{proposal_id}: reviewed narrative package was not included",
        )
        primitives.assertion(
            package["review_state"] == "APPROVED_FOR_ADVISOR_USE",
            f"{proposal_id}: reviewed narrative package lost review state",
        )
    else:
        primitives.assertion(
            report_response.status_code == 503,
            (
                f"{proposal_id}: expected reviewed narrative report package degraded 503, got "
                f"{report_response.status_code} body={report_response.text}"
            ),
        )
        report_body = None
        report_status = "UNAVAILABLE"

    ai_assisted_status, ai_fallback_reason = _assert_ai_assisted_narrative_when_enabled(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        scenario=scenario,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return primitives.extract_snapshot(
        proposal_id=proposal_id,
        version_no=version_no,
        created_version=version,
        read_body=read_body,
        regeneration_body=regeneration_body,
        review_body=review_body,
        replay_body=replay_body,
        report_status=report_status,
        report_body=report_body,
        latency_ms=latency_ms,
        ai_assisted_status=ai_assisted_status,
        ai_fallback_reason=ai_fallback_reason,
    )
