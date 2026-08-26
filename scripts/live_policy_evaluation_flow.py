"""Certify the governed live policy-evaluation workflow and evidence lineage."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx

from scripts.live_policy_evaluation_support import (
    Assertion,
    GetJson,
    PolicyParityScenario,
    PostJson,
)
from scripts.live_runtime_policy_evaluation import LivePolicyEvaluationSnapshot


class EnsurePolicyPackActive(Protocol):
    """Activate the governed policy pack through the validator's HTTP seam."""

    def __call__(
        self,
        client: httpx.Client,
        *,
        advise_base_url: str,
        get_json: GetJson,
        post_json: PostJson,
    ) -> None: ...


class PolicyEvidenceBundle(Protocol):
    """Build deterministic, source-shaped policy evidence for a scenario."""

    def __call__(self, *, scenario: PolicyParityScenario) -> dict[str, Any]: ...


class RequestPolicyReport(Protocol):
    """Request policy report evidence while preserving READY/UNAVAILABLE semantics."""

    def __call__(
        self,
        client: httpx.Client,
        *,
        advise_base_url: str,
        evaluation_id: str,
        evaluation_hash: str,
        scenario: PolicyParityScenario,
        assert_condition: Assertion,
    ) -> tuple[str, dict[str, Any] | None, str | None]: ...


class PolicyEvaluationSnapshotExtractor(Protocol):
    """Project fixed policy-certification evidence into its runtime snapshot."""

    def __call__(
        self,
        *,
        created_body: dict[str, Any],
        read_body: dict[str, Any],
        queue_body: dict[str, Any],
        workflow_body: dict[str, Any],
        sign_off_body: dict[str, Any],
        report_status: str,
        report_body: dict[str, Any] | None,
        ai_body: dict[str, Any],
        lineage_body: dict[str, Any],
        replay_body: dict[str, Any],
        stale_hash_block_status: str,
        client_ready_document_block_status: str,
        forbidden_ai_action_block_status: str,
        report_degraded_reason: str | None,
        latency_ms: float,
    ) -> LivePolicyEvaluationSnapshot: ...


@dataclass(frozen=True)
class LivePolicyEvaluationPrimitives:
    """Typed dependencies needed by the policy flow without importing the validator module."""

    assertion: Assertion
    get_json: GetJson
    post_json: PostJson
    ensure_policy_pack_active: EnsurePolicyPackActive
    policy_evidence_bundle: PolicyEvidenceBundle
    request_policy_report: RequestPolicyReport
    extract_snapshot: PolicyEvaluationSnapshotExtractor


def _create_live_policy_evaluation(
    client: httpx.Client,
    *,
    primitives: LivePolicyEvaluationPrimitives,
    advise_base_url: str,
    scenario: PolicyParityScenario,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """Create a policy evaluation and prove its initial hash-backed requirements."""
    primitives.ensure_policy_pack_active(
        client,
        advise_base_url=advise_base_url,
        get_json=primitives.get_json,
        post_json=primitives.post_json,
    )
    proposal_id = f"pp_live_policy_{uuid.uuid4().hex[:10]}"
    proposal_version_id = f"ppv_live_policy_{uuid.uuid4().hex[:10]}"
    created_body = primitives.post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
        f"{proposal_version_id}/policy-evaluations",
        expected_status=200,
        json_body={
            "policy_pack_id": "SG_PRIVATE_BANKING_REFERENCE",
            "policy_version": "2026.05",
            "created_by": "live-parity-validator-policy",
            "evidence_bundle": primitives.policy_evidence_bundle(scenario=scenario),
            "reason": {"purpose": "RFC-0025 Slice 14 live policy implementation proof"},
        },
        headers={"Idempotency-Key": f"live-policy-eval-{uuid.uuid4().hex}"},
    )
    record = cast(dict[str, Any], created_body["record"])
    evaluation_id = str(record["evaluation_id"])
    evaluation_hash = str(record["evaluation_hash"])
    primitives.assertion(
        evaluation_hash.startswith("sha256:"),
        f"{evaluation_id}: policy evaluation hash was not canonical sha256",
    )
    primitives.assertion(
        bool(record["approval_dependencies"])
        and bool(record["disclosure_requirements"])
        and bool(record["consent_requirements"]),
        f"{evaluation_id}: policy evaluation did not expose review requirements",
    )
    return created_body, record, evaluation_id, evaluation_hash


def _assert_live_policy_read_surfaces(
    client: httpx.Client,
    *,
    primitives: LivePolicyEvaluationPrimitives,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Verify persisted policy evaluation, queue, workflow, and sign-off read surfaces."""
    read_body = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}",
        expected_status=200,
    )
    primitives.assertion(
        read_body["evaluation_hash"] == evaluation_hash,
        f"{evaluation_id}: policy read lost hash continuity",
    )
    queue_body = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/review-queue",
        expected_status=200,
    )
    primitives.assertion(
        any(item.get("evaluation_id") == evaluation_id for item in queue_body["items"]),
        f"{evaluation_id}: policy review queue omitted finalized evaluation",
    )
    workflow_body = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/workflow",
        expected_status=200,
    )
    primitives.assertion(
        workflow_body["client_ready_publication"] == "BLOCKED",
        f"{evaluation_id}: policy workflow promoted client-ready publication",
    )
    sign_off_package = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/sign-off-package",
        expected_status=200,
    )
    primitives.assertion(
        sign_off_package["evaluation"]["evaluation_id"] == evaluation_id,
        f"{evaluation_id}: sign-off package lost evaluation identity",
    )
    return read_body, queue_body, workflow_body


def _assert_live_policy_pre_sign_off_guards(
    client: httpx.Client,
    *,
    primitives: LivePolicyEvaluationPrimitives,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
    scenario: PolicyParityScenario,
) -> tuple[str, str]:
    """Verify stale-hash and client-ready publication requests remain blocked."""
    stale_hash_response = client.post(
        f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/sign-off-decisions",
        json={
            "actor_id": "policy_checker_live",
            "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
            "source_evaluation_hash": "sha256:stale",
        },
        headers={"Idempotency-Key": f"live-policy-stale-signoff-{uuid.uuid4().hex}"},
    )
    primitives.assertion(
        stale_hash_response.status_code == 422,
        f"{evaluation_id}: stale policy hash sign-off was not rejected",
    )
    stale_hash_block_status = str(cast(dict[str, Any], stale_hash_response.json()).get("detail"))

    client_ready_document_response = client.post(
        f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/report-packages",
        json={
            "requested_by": "policy_checker_live",
            "portfolio_id": scenario.portfolio_id,
            "source_evaluation_hash": evaluation_hash,
            "requested_output_formats": ["pdf"],
            "client_ready_document_requested": True,
        },
        headers={"Idempotency-Key": f"live-policy-client-ready-report-{uuid.uuid4().hex}"},
    )
    primitives.assertion(
        client_ready_document_response.status_code == 422,
        f"{evaluation_id}: client-ready policy document request was not blocked",
    )
    client_ready_document_block_status = str(
        cast(dict[str, Any], client_ready_document_response.json()).get("detail")
    )
    return stale_hash_block_status, client_ready_document_block_status


def _sign_off_live_policy_evaluation(
    client: httpx.Client,
    *,
    primitives: LivePolicyEvaluationPrimitives,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Sign off the policy evaluation after satisfying its recorded requirements."""
    sign_off_body = primitives.post_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/sign-off-decisions",
        expected_status=200,
        json_body={
            "actor_id": "policy_checker_live",
            "decision": "APPROVE_FOR_POLICY_SIGN_OFF",
            "source_evaluation_hash": evaluation_hash,
            "resolved_approval_dependencies": record["approval_dependencies"],
            "satisfied_disclosure_requirements": record["disclosure_requirements"],
            "satisfied_consent_requirements": record["consent_requirements"],
            "reason": {"purpose": "live policy sign-off proof"},
        },
        headers={"Idempotency-Key": f"live-policy-signoff-{uuid.uuid4().hex}"},
    )
    primitives.assertion(
        cast(dict[str, Any], sign_off_body["workflow"])["sign_off_status"] == "SIGNED_OFF",
        f"{evaluation_id}: policy sign-off did not close requirements",
    )
    return cast(dict[str, Any], sign_off_body)


def _request_live_policy_ai_evidence(
    client: httpx.Client,
    *,
    primitives: LivePolicyEvaluationPrimitives,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
) -> tuple[str, dict[str, Any]]:
    """Verify forbidden policy AI actions are blocked and bounded evidence is non-authoritative."""
    forbidden_ai_response = client.post(
        f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/ai-evidence",
        json={
            "requested_by": "policy_checker_live",
            "source_evaluation_hash": evaluation_hash,
            "requested_actions": ["APPROVE_POLICY"],
        },
        headers={"Idempotency-Key": f"live-policy-forbidden-ai-{uuid.uuid4().hex}"},
    )
    primitives.assertion(
        forbidden_ai_response.status_code == 422,
        f"{evaluation_id}: forbidden policy AI action was not rejected",
    )
    forbidden_ai_action_block_status = str(
        cast(dict[str, Any], forbidden_ai_response.json()).get("detail")
    )
    ai_body = primitives.post_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/ai-evidence",
        expected_status=200,
        json_body={
            "requested_by": "policy_checker_live",
            "source_evaluation_hash": evaluation_hash,
            "requested_actions": [
                "SUMMARIZE_POLICY_POSTURE",
                "EXPLAIN_OPEN_REQUIREMENTS",
            ],
            "reason": {"purpose": "bounded policy AI evidence live proof"},
        },
        headers={"Idempotency-Key": f"live-policy-ai-{uuid.uuid4().hex}"},
    )
    policy_evidence = cast(dict[str, Any], ai_body["policy_evidence"])
    primitives.assertion(
        policy_evidence["authoritative_for_policy_status"] is False,
        f"{evaluation_id}: AI evidence became authoritative for policy status",
    )
    primitives.assertion(
        policy_evidence["human_review_required"] is True,
        f"{evaluation_id}: AI evidence did not preserve human review posture",
    )
    primitives.assertion(
        cast(dict[str, Any], policy_evidence["redaction_profile"])["raw_source_evidence_included"]
        is False,
        f"{evaluation_id}: AI evidence included raw source evidence",
    )
    return forbidden_ai_action_block_status, ai_body


def _assert_live_policy_lineage_and_replay(
    client: httpx.Client,
    *,
    primitives: LivePolicyEvaluationPrimitives,
    advise_base_url: str,
    evaluation_id: str,
    evaluation_hash: str,
    source_evidence_hash: str,
    policy_content_hash: str,
    scenario: PolicyParityScenario,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify hash-backed lineage and deterministic replay continuity."""
    lineage_body = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/lineage",
        expected_status=200,
    )
    lineage_posture = cast(dict[str, Any], lineage_body["lineage_posture"])
    primitives.assertion(
        lineage_body["evaluation_hash"] == evaluation_hash
        and lineage_body["source_evidence_hash"] == source_evidence_hash
        and lineage_body["policy_content_hash"] == policy_content_hash
        and bool(lineage_body["rule_result_hashes"])
        and bool(lineage_body["source_refs"])
        and bool(lineage_body["audit_events"])
        and lineage_posture["client_ready_publication"] == "BLOCKED",
        f"{evaluation_id}: policy lineage did not retain complete hash-backed evidence",
    )
    replay_body = primitives.post_json(
        client,
        url=f"{advise_base_url}/advisory/policy-evaluations/{evaluation_id}/replay",
        expected_status=200,
        json_body={"evidence_bundle": primitives.policy_evidence_bundle(scenario=scenario)},
    )
    primitives.assertion(
        cast(dict[str, Any], replay_body["hash_comparison"])["evaluation_hash_matches"] is True,
        f"{evaluation_id}: replay lost evaluation hash continuity",
    )
    return lineage_body, replay_body


def assert_live_policy_evaluation(
    client: httpx.Client,
    *,
    primitives: LivePolicyEvaluationPrimitives,
    advise_base_url: str,
    scenario: PolicyParityScenario,
) -> LivePolicyEvaluationSnapshot:
    """Run the complete policy evidence flow and project its stable result snapshot."""
    started = time.perf_counter()
    created_body, record, evaluation_id, evaluation_hash = _create_live_policy_evaluation(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        scenario=scenario,
    )
    read_body, queue_body, workflow_body = _assert_live_policy_read_surfaces(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        evaluation_id=evaluation_id,
        evaluation_hash=evaluation_hash,
    )
    stale_hash_block_status, client_ready_document_block_status = (
        _assert_live_policy_pre_sign_off_guards(
            client,
            primitives=primitives,
            advise_base_url=advise_base_url,
            evaluation_id=evaluation_id,
            evaluation_hash=evaluation_hash,
            scenario=scenario,
        )
    )
    sign_off_body = _sign_off_live_policy_evaluation(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        evaluation_id=evaluation_id,
        evaluation_hash=evaluation_hash,
        record=record,
    )
    report_status, report_body, report_degraded_reason = primitives.request_policy_report(
        client,
        advise_base_url=advise_base_url,
        evaluation_id=evaluation_id,
        evaluation_hash=evaluation_hash,
        scenario=scenario,
        assert_condition=primitives.assertion,
    )
    forbidden_ai_action_block_status, ai_body = _request_live_policy_ai_evidence(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        evaluation_id=evaluation_id,
        evaluation_hash=evaluation_hash,
    )
    lineage_body, replay_body = _assert_live_policy_lineage_and_replay(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        evaluation_id=evaluation_id,
        evaluation_hash=evaluation_hash,
        source_evidence_hash=str(record["source_evidence_hash"]),
        policy_content_hash=str(record["policy_content_hash"]),
        scenario=scenario,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return primitives.extract_snapshot(
        created_body=created_body,
        read_body=read_body,
        queue_body=queue_body,
        workflow_body=workflow_body,
        sign_off_body=sign_off_body,
        report_status=report_status,
        report_body=report_body,
        ai_body=ai_body,
        lineage_body=lineage_body,
        replay_body=replay_body,
        stale_hash_block_status=stale_hash_block_status,
        client_ready_document_block_status=client_ready_document_block_status,
        forbidden_ai_action_block_status=forbidden_ai_action_block_status,
        report_degraded_reason=report_degraded_reason,
        latency_ms=latency_ms,
    )
