from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx

from scripts.live_policy_evaluation_support import (
    Assertion,
    CreateStatefulProposal,
    GetJson,
    PostJson,
    StatefulProposalScenario,
)
from scripts.live_runtime_proposal_memo import LiveProposalMemoSnapshot


class MemoSnapshotExtractor(Protocol):
    """Project the fixed memo-certification evidence into its runtime snapshot."""

    def __call__(
        self,
        *,
        proposal_id: str,
        version_no: int,
        memo_body: dict[str, Any],
        projection_body: dict[str, Any],
        review_body: dict[str, Any],
        report_status: str,
        report_body: dict[str, Any] | None,
        ai_body: dict[str, Any],
        lineage_body: dict[str, Any],
        replay_body: dict[str, Any],
        stale_hash_block_status: str,
        client_ready_release_block_status: str,
        client_ready_document_block_status: str,
        report_degraded_reason: str | None,
        latency_ms: float,
    ) -> LiveProposalMemoSnapshot: ...


@dataclass(frozen=True)
class LiveMemoFlowPrimitives:
    """Typed seams for memo certification without importing the live validator module."""

    create_stateful_proposal: CreateStatefulProposal
    post_json: PostJson
    get_json: GetJson
    assertion: Assertion
    extract_snapshot: MemoSnapshotExtractor


@dataclass(frozen=True)
class _MemoArtifact:
    proposal_id: str
    version_no: int
    memo_body: dict[str, Any]
    memo_hash: str
    projection_body: dict[str, Any]


@dataclass(frozen=True)
class _MemoReviewEvidence:
    review_body: dict[str, Any]
    stale_hash_block_status: str
    client_ready_release_block_status: str


@dataclass(frozen=True)
class _MemoReportEvidence:
    report_status: str
    report_body: dict[str, Any] | None
    report_degraded_reason: str | None
    client_ready_document_block_status: str


@dataclass(frozen=True)
class _MemoRuntimeEvidence:
    ai_body: dict[str, Any]
    lineage_body: dict[str, Any]
    replay_body: dict[str, Any]


def _create_memo_artifact(
    client: httpx.Client,
    *,
    primitives: LiveMemoFlowPrimitives,
    advise_base_url: str,
    scenario: StatefulProposalScenario,
) -> _MemoArtifact:
    """Create the memo and prove its advisor projection and hash continuity."""
    created = primitives.create_stateful_proposal(
        client,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by="live-parity-validator-memo",
    )
    proposal_id = str(cast(dict[str, Any], created["proposal"])["proposal_id"])
    version_no = int(cast(dict[str, Any], created["version"])["version_no"])
    memo_body = primitives.post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/memo",
        expected_status=200,
        json_body={
            "created_by": "live-parity-validator",
            "lifecycle_status": "DRAFT",
            "reason": {"purpose": "RFC-0024 Slice 13 live memo implementation proof"},
        },
        headers={"Idempotency-Key": f"live-memo-create-{uuid.uuid4().hex}"},
    )
    memo_hash = str(memo_body["memo_hash"])
    primitives.assertion(
        memo_hash.startswith("sha256:"),
        f"{proposal_id}: memo hash was not canonical sha256: {memo_hash}",
    )
    read_body = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/{version_no}/memo",
        expected_status=200,
    )
    primitives.assertion(
        read_body["memo_hash"] == memo_hash,
        f"{proposal_id}: memo read lost hash continuity",
    )
    projection_body = primitives.get_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/memo/projection?audience=ADVISOR"
        ),
        expected_status=200,
    )
    projection_posture = cast(dict[str, Any], projection_body["projection_posture"])
    primitives.assertion(
        projection_posture["client_ready_publication"] == "BLOCKED",
        f"{proposal_id}: memo projection promoted client-ready publication",
    )
    primitives.assertion(
        bool(projection_body["sections"]),
        f"{proposal_id}: advisor memo projection returned no sections",
    )
    return _MemoArtifact(
        proposal_id=proposal_id,
        version_no=version_no,
        memo_body=memo_body,
        memo_hash=memo_hash,
        projection_body=projection_body,
    )


def _assert_memo_review_controls(
    client: httpx.Client,
    *,
    primitives: LiveMemoFlowPrimitives,
    advise_base_url: str,
    artifact: _MemoArtifact,
) -> _MemoReviewEvidence:
    """Prove stale-hash rejection, client-ready blocking, and valid advisor review."""
    review_url = (
        f"{advise_base_url}/advisory/proposals/{artifact.proposal_id}/versions/"
        f"{artifact.version_no}/memo/review"
    )
    stale_hash_response = client.post(
        review_url,
        json={
            "action": "APPROVE_FOR_ADVISOR_USE",
            "reviewed_by": "live-parity-validator",
            "reason": "Validate stale hash rejection.",
            "source_memo_hash": "sha256:stale",
        },
        headers={"Idempotency-Key": f"live-memo-stale-review-{uuid.uuid4().hex}"},
    )
    primitives.assertion(
        stale_hash_response.status_code == 422,
        f"{artifact.proposal_id}: stale memo hash review was not rejected",
    )
    stale_hash_block_status = str(cast(dict[str, Any], stale_hash_response.json()).get("detail"))

    client_ready_release_response = client.post(
        review_url,
        json={
            "action": "APPROVE_FOR_ADVISOR_USE",
            "reviewed_by": "live-parity-validator",
            "reason": "Validate client-ready memo review remains blocked.",
            "source_memo_hash": artifact.memo_hash,
            "client_ready_release_requested": True,
        },
        headers={"Idempotency-Key": f"live-memo-client-ready-review-{uuid.uuid4().hex}"},
    )
    primitives.assertion(
        client_ready_release_response.status_code == 422,
        f"{artifact.proposal_id}: client-ready memo review request was not blocked",
    )
    client_ready_release_block_status = str(
        cast(dict[str, Any], client_ready_release_response.json()).get("detail")
    )

    review_body = primitives.post_json(
        client,
        url=review_url,
        expected_status=200,
        json_body={
            "action": "APPROVE_FOR_ADVISOR_USE",
            "reviewed_by": "live-parity-validator",
            "reason": "Hash-continuous advisor-use memo proof.",
            "source_memo_hash": artifact.memo_hash,
            "client_ready_release_requested": False,
        },
        headers={"Idempotency-Key": f"live-memo-review-{uuid.uuid4().hex}"},
    )
    review_reason = cast(dict[str, Any], review_body["review_event"])["reason"]
    primitives.assertion(
        cast(dict[str, Any], review_reason)["review_action"] == "APPROVE_FOR_ADVISOR_USE",
        f"{artifact.proposal_id}: memo review did not record advisor-use approval",
    )
    return _MemoReviewEvidence(
        review_body=review_body,
        stale_hash_block_status=stale_hash_block_status,
        client_ready_release_block_status=client_ready_release_block_status,
    )


def _assert_memo_report_package(
    client: httpx.Client,
    *,
    primitives: LiveMemoFlowPrimitives,
    advise_base_url: str,
    artifact: _MemoArtifact,
) -> _MemoReportEvidence:
    """Prove client-ready blocking and preserve success or degraded report outcomes."""
    report_url = (
        f"{advise_base_url}/advisory/proposals/{artifact.proposal_id}/versions/"
        f"{artifact.version_no}/memo/report-packages"
    )
    client_ready_document_response = client.post(
        report_url,
        json={
            "requested_by": "live-parity-validator",
            "source_memo_hash": artifact.memo_hash,
            "client_ready_document_requested": True,
            "reason": {"purpose": "Validate client-ready memo document block"},
        },
        headers={"Idempotency-Key": f"live-memo-client-ready-report-{uuid.uuid4().hex}"},
    )
    primitives.assertion(
        client_ready_document_response.status_code == 422,
        f"{artifact.proposal_id}: client-ready memo report request was not blocked",
    )
    client_ready_document_block_status = str(
        cast(dict[str, Any], client_ready_document_response.json()).get("detail")
    )
    report_response = client.post(
        report_url,
        json={
            "requested_by": "live-parity-validator",
            "source_memo_hash": artifact.memo_hash,
            "requested_output_formats": ["pdf"],
            "client_ready_document_requested": False,
            "reason": {"purpose": "advisor-use memo report package live proof"},
        },
        headers={"Idempotency-Key": f"live-memo-report-{uuid.uuid4().hex}"},
    )
    if report_response.status_code == 200:
        report_body = cast(dict[str, Any], report_response.json())
        report_status = str(cast(dict[str, Any], report_body["report"])["status"])
        return _MemoReportEvidence(
            report_status=report_status,
            report_body=report_body,
            report_degraded_reason=None,
            client_ready_document_block_status=client_ready_document_block_status,
        )

    primitives.assertion(
        report_response.status_code == 503,
        (
            f"{artifact.proposal_id}: expected memo report package success or degraded 503, got "
            f"{report_response.status_code} body={report_response.text}"
        ),
    )
    return _MemoReportEvidence(
        report_status="UNAVAILABLE",
        report_body=None,
        report_degraded_reason=str(cast(dict[str, Any], report_response.json()).get("detail")),
        client_ready_document_block_status=client_ready_document_block_status,
    )


def _assert_memo_ai_and_replay(
    client: httpx.Client,
    *,
    primitives: LiveMemoFlowPrimitives,
    advise_base_url: str,
    artifact: _MemoArtifact,
) -> _MemoRuntimeEvidence:
    """Prove AI commentary remains review-gated and hashes survive lineage and replay."""
    ai_body = primitives.post_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{artifact.proposal_id}/versions/"
            f"{artifact.version_no}/memo/ai-commentary"
        ),
        expected_status=200,
        json_body={
            "requested_by": "live-parity-validator",
            "source_memo_hash": artifact.memo_hash,
            "requested_sections": ["EXECUTIVE_SUMMARY", "LIMITATIONS_AND_DISCLOSURES"],
            "reason": {"purpose": "review-gated memo commentary live proof"},
        },
        headers={"Idempotency-Key": f"live-memo-ai-{uuid.uuid4().hex}"},
    )
    commentary = cast(dict[str, Any], ai_body["commentary"])
    primitives.assertion(
        commentary["authoritative_for_memo_status"] is False,
        f"{artifact.proposal_id}: AI commentary became authoritative for memo status",
    )
    primitives.assertion(
        commentary["review_required"] is True,
        f"{artifact.proposal_id}: AI commentary did not retain review-required posture",
    )

    lineage_body = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{artifact.proposal_id}/memos/lineage",
        expected_status=200,
    )
    primitives.assertion(
        lineage_body["memo_count"] >= 1,
        f"{artifact.proposal_id}: memo lineage was empty",
    )
    replay_body = primitives.get_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{artifact.proposal_id}/versions/"
            f"{artifact.version_no}/memo/replay-evidence"
        ),
        expected_status=200,
    )
    replay_hashes = cast(dict[str, Any], replay_body["hashes"])
    primitives.assertion(
        replay_hashes["memo_hash"] == artifact.memo_hash,
        f"{artifact.proposal_id}: memo replay evidence lost memo hash continuity",
    )
    return _MemoRuntimeEvidence(
        ai_body=ai_body,
        lineage_body=lineage_body,
        replay_body=replay_body,
    )


def assert_live_memo_flow(
    client: httpx.Client,
    *,
    primitives: LiveMemoFlowPrimitives,
    advise_base_url: str,
    scenario: StatefulProposalScenario,
) -> LiveProposalMemoSnapshot:
    """Run memo certification phases and assemble the persisted evidence snapshot."""
    started = time.perf_counter()
    artifact = _create_memo_artifact(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        scenario=scenario,
    )
    review = _assert_memo_review_controls(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        artifact=artifact,
    )
    report = _assert_memo_report_package(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        artifact=artifact,
    )
    runtime = _assert_memo_ai_and_replay(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        artifact=artifact,
    )
    return primitives.extract_snapshot(
        proposal_id=artifact.proposal_id,
        version_no=artifact.version_no,
        memo_body=artifact.memo_body,
        projection_body=artifact.projection_body,
        review_body=review.review_body,
        report_status=report.report_status,
        report_body=report.report_body,
        ai_body=runtime.ai_body,
        lineage_body=runtime.lineage_body,
        replay_body=runtime.replay_body,
        stale_hash_block_status=review.stale_hash_block_status,
        client_ready_release_block_status=review.client_ready_release_block_status,
        client_ready_document_block_status=report.client_ready_document_block_status,
        report_degraded_reason=report.report_degraded_reason,
        latency_ms=(time.perf_counter() - started) * 1000.0,
    )
