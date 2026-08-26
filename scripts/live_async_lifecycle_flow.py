"""Typed live certification flow for asynchronous proposal lifecycle surfaces."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, Protocol, cast

import httpx

from scripts.live_policy_evaluation_support import (
    Assertion,
    AssertPersistedReadSurfaces,
    FeatureByKey,
    GetJson,
    PostJson,
)


class AsyncLifecycleScenario(Protocol):
    """Scenario fields required by the asynchronous proposal lifecycle proof."""

    @property
    def portfolio_id(self) -> str: ...

    @property
    def as_of_date(self) -> str: ...


class AssertAuthorityPosture(Protocol):
    """Typed adapter for the shared simulation and risk authority assertion."""

    def __call__(
        self, *, scenario: AsyncLifecycleScenario, proposal_body: dict[str, Any]
    ) -> None: ...


class PromoteToExecutionReady(Protocol):
    """Typed adapter for the validator's version-scoped approval progression."""

    def __call__(
        self,
        client: httpx.Client,
        *,
        advise_base_url: str,
        proposal_id: str,
        related_version_no: int,
        route: Literal["risk", "compliance"] = "risk",
    ) -> None: ...


class Fail(Protocol):
    """Typed adapter preserving the validator's governed failure exception."""

    def __call__(self, message: str) -> NoReturn: ...


class UtcIsoAfter(Protocol):
    """Typed adapter for deterministic timestamp construction in request payloads."""

    def __call__(self, *, seconds: int = 0) -> str: ...


@dataclass(frozen=True)
class LiveAsyncLifecyclePrimitives:
    """Dependencies supplied by the live validator without importing its module."""

    post_json: PostJson
    get_json: GetJson
    assertion: Assertion
    feature_by_key: FeatureByKey
    assert_authority_posture: AssertAuthorityPosture
    assert_persisted_read_surfaces: AssertPersistedReadSurfaces
    promote_to_execution_ready: PromoteToExecutionReady
    fail: Fail
    utc_iso_after: UtcIsoAfter


@dataclass(frozen=True)
class _AsyncLifecycleArtifacts:
    create_result: dict[str, Any]
    version_result: dict[str, Any]


def _submit_async_create(
    client: httpx.Client,
    *,
    primitives: LiveAsyncLifecyclePrimitives,
    advise_base_url: str,
    scenario: AsyncLifecycleScenario,
    created_by: str,
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        primitives.post_json(
            client,
            url=f"{advise_base_url}/advisory/proposals/async",
            expected_status=202,
            json_body={
                "created_by": created_by,
                "input_mode": "stateful",
                "stateful_input": {
                    "portfolio_id": scenario.portfolio_id,
                    "as_of": scenario.as_of_date,
                },
            },
            headers={
                "Idempotency-Key": f"live-async-create-{uuid.uuid4().hex}",
                "X-Correlation-Id": f"live-async-create-{uuid.uuid4().hex}",
            },
        ),
    )


def _submit_async_version(
    client: httpx.Client,
    *,
    primitives: LiveAsyncLifecyclePrimitives,
    advise_base_url: str,
    proposal_id: str,
    scenario: AsyncLifecycleScenario,
    created_by: str,
    expected_current_version_no: int,
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        primitives.post_json(
            client,
            url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/async",
            expected_status=202,
            json_body={
                "created_by": created_by,
                "expected_current_version_no": expected_current_version_no,
                "input_mode": "stateful",
                "stateful_input": {
                    "portfolio_id": scenario.portfolio_id,
                    "as_of": scenario.as_of_date,
                },
            },
            headers={"X-Correlation-Id": f"live-async-version-{uuid.uuid4().hex}"},
        ),
    )


def _wait_for_async_success(
    client: httpx.Client,
    *,
    primitives: LiveAsyncLifecyclePrimitives,
    advise_base_url: str,
    operation_id: str,
    expected_type: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        status_body = primitives.get_json(
            client,
            url=f"{advise_base_url}/advisory/proposals/operations/{operation_id}",
            expected_status=200,
        )
        primitives.assertion(
            status_body["operation_type"] == expected_type,
            f"{operation_id}: unexpected operation type {status_body['operation_type']}",
        )
        if status_body["status"] == "SUCCEEDED":
            result = status_body.get("result")
            primitives.assertion(
                isinstance(result, dict),
                f"{operation_id}: async success missing result",
            )
            return cast(dict[str, Any], result)
        if status_body["status"] == "FAILED":
            primitives.fail(f"{operation_id}: async operation failed {status_body.get('error')}")
        time.sleep(0.5)
    primitives.fail(f"{operation_id}: async operation did not finish in time")


def _assert_async_operation_surfaces(
    client: httpx.Client,
    *,
    primitives: LiveAsyncLifecyclePrimitives,
    advise_base_url: str,
    accepted_body: dict[str, Any],
    expected_type: str,
    result_body: dict[str, Any],
) -> None:
    operation_id = str(accepted_body["operation_id"])
    correlation_id = str(accepted_body["correlation_id"])
    operation = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/operations/{operation_id}",
        expected_status=200,
    )
    by_correlation = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/operations/by-correlation/{correlation_id}",
        expected_status=200,
    )
    replay = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/operations/{operation_id}/replay-evidence",
        expected_status=200,
    )
    proposal = cast(dict[str, Any], result_body["proposal"])
    version = cast(dict[str, Any], result_body["version"])
    proposal_id = str(proposal["proposal_id"])
    version_no = int(version["version_no"])
    version_replay = primitives.get_json(
        client,
        url=(
            f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
            f"{version_no}/replay-evidence"
        ),
        expected_status=200,
    )
    detail = primitives.get_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{proposal_id}?include_evidence=false",
        expected_status=200,
    )

    assertion = primitives.assertion
    operation_result = cast(dict[str, Any], operation["result"])
    replay_subject = cast(dict[str, Any], replay["subject"])
    replay_continuity = cast(dict[str, Any], replay["continuity"])
    replay_hashes = cast(dict[str, Any], replay["hashes"])
    operation_identity = tuple(
        operation[key] for key in ("operation_type", "operation_id", "correlation_id", "status")
    )
    correlation_identity = tuple(
        by_correlation[key]
        for key in ("operation_type", "operation_id", "correlation_id", "status")
    )
    replay_subject_identity = tuple(
        replay_subject[key]
        for key in ("scope", "operation_id", "proposal_id", "proposal_version_no")
    )
    replay_continuity_identity = tuple(
        replay_continuity[key] for key in ("correlation_id", "async_operation_id")
    )
    checks = (
        (
            operation_identity
            == correlation_identity
            == (expected_type, operation_id, correlation_id, "SUCCEEDED"),
            f"{operation_id}: operation read surfaces diverged",
        ),
        (
            (
                str(operation_result["proposal"]["proposal_id"]),
                int(operation_result["version"]["version_no"]),
            )
            == (proposal_id, version_no),
            f"{operation_id}: operation result diverged from async result",
        ),
        (
            replay_subject_identity == ("ASYNC_OPERATION", operation_id, proposal_id, version_no),
            f"{operation_id}: async replay subject diverged",
        ),
        (
            replay_continuity_identity == (correlation_id, operation_id),
            f"{operation_id}: async replay continuity diverged",
        ),
        (
            replay_hashes["request_hash"] == version_replay["hashes"]["request_hash"]
            and replay_hashes["simulation_hash"] == version_replay["hashes"]["simulation_hash"],
            f"{operation_id}: async/proposal replay hashes diverged",
        ),
        (
            replay["resolved_context"] == version_replay["resolved_context"],
            f"{operation_id}: async/proposal replay context diverged",
        ),
        (
            int(detail["proposal"]["current_version_no"]) >= version_no,
            f"{operation_id}: proposal detail current version regressed behind async result",
        ),
    )
    for condition, message in checks:
        assertion(condition, message)


def _run_async_lifecycle(
    client: httpx.Client,
    *,
    primitives: LiveAsyncLifecyclePrimitives,
    advise_base_url: str,
    scenario: AsyncLifecycleScenario,
    create_actor: str,
    version_actor: str,
) -> _AsyncLifecycleArtifacts:
    accepted_create = _submit_async_create(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        scenario=scenario,
        created_by=create_actor,
    )
    create_result = _wait_for_async_success(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        operation_id=str(accepted_create["operation_id"]),
        expected_type="CREATE_PROPOSAL",
    )
    _assert_async_operation_surfaces(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        accepted_body=accepted_create,
        expected_type="CREATE_PROPOSAL",
        result_body=create_result,
    )
    proposal_id = str(create_result["proposal"]["proposal_id"])
    version_no = int(create_result["version"]["version_no"])
    accepted_version = _submit_async_version(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        scenario=scenario,
        created_by=version_actor,
        expected_current_version_no=version_no,
    )
    version_result = _wait_for_async_success(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        operation_id=str(accepted_version["operation_id"]),
        expected_type="CREATE_PROPOSAL_VERSION",
    )
    _assert_async_operation_surfaces(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        accepted_body=accepted_version,
        expected_type="CREATE_PROPOSAL_VERSION",
        result_body=version_result,
    )
    return _AsyncLifecycleArtifacts(
        create_result=create_result,
        version_result=version_result,
    )


def assert_async_proposal_lifecycle(
    client: httpx.Client,
    *,
    primitives: LiveAsyncLifecyclePrimitives,
    advise_base_url: str,
    scenario: AsyncLifecycleScenario,
) -> None:
    """Certify asynchronous create/version operations and authority evidence."""
    artifacts = _run_async_lifecycle(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        scenario=scenario,
        create_actor="live-parity-validator-async",
        version_actor="live-parity-validator-async-version",
    )
    primitives.assert_authority_posture(
        scenario=scenario,
        proposal_body=artifacts.create_result["version"]["proposal_result"],
    )
    create_version_no = int(artifacts.create_result["version"]["version_no"])
    current_version_no = int(artifacts.version_result["proposal"]["current_version_no"])
    primitives.assertion(
        current_version_no == create_version_no + 1,
        (
            f"{artifacts.create_result['proposal']['proposal_id']}: async version did not "
            "increment current_version_no"
        ),
    )
    primitives.assert_authority_posture(
        scenario=scenario,
        proposal_body=artifacts.version_result["version"]["proposal_result"],
    )


def assert_live_async_lifecycle(
    client: httpx.Client,
    *,
    primitives: LiveAsyncLifecyclePrimitives,
    advise_base_url: str,
    scenario: AsyncLifecycleScenario,
) -> tuple[str, int, str]:
    """Certify async lifecycle, execution handoff, reporting, and persisted read surfaces."""
    artifacts = _run_async_lifecycle(
        client,
        primitives=primitives,
        advise_base_url=advise_base_url,
        scenario=scenario,
        create_actor="live-parity-validator-async-lifecycle",
        version_actor="live-parity-validator-async-lifecycle-version",
    )
    async_proposal_id = str(artifacts.create_result["proposal"]["proposal_id"])
    async_portfolio_id = str(artifacts.create_result["proposal"]["portfolio_id"])
    current_version_no = int(artifacts.version_result["proposal"]["current_version_no"])
    primitives.promote_to_execution_ready(
        client,
        advise_base_url=advise_base_url,
        proposal_id=async_proposal_id,
        related_version_no=current_version_no,
    )
    handoff = primitives.post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{async_proposal_id}/execution-handoffs",
        expected_status=200,
        json_body={
            "actor_id": "ops_async_001",
            "execution_provider": "lotus-manage",
            "expected_state": "EXECUTION_READY",
            "related_version_no": current_version_no,
            "external_request_id": f"oms_async_req_{uuid.uuid4().hex[:10]}",
            "notes": {"channel": "OMS", "priority": "STANDARD"},
        },
        headers={"Idempotency-Key": f"live-async-lifecycle-handoff-{uuid.uuid4().hex}"},
    )
    primitives.assertion(
        handoff["handoff_status"] == "REQUESTED",
        f"{async_proposal_id}: async lifecycle handoff did not start in REQUESTED",
    )
    executed = primitives.post_json(
        client,
        url=f"{advise_base_url}/advisory/proposals/{async_proposal_id}/execution-updates",
        expected_status=200,
        json_body={
            "update_id": f"async_exec_done_{uuid.uuid4().hex[:10]}",
            "actor_id": "lotus-manage",
            "execution_request_id": handoff["execution_request_id"],
            "execution_provider": "lotus-manage",
            "update_status": "EXECUTED",
            "related_version_no": current_version_no,
            "external_execution_id": f"oms_async_fill_{uuid.uuid4().hex[:10]}",
            "occurred_at": primitives.utc_iso_after(seconds=2),
            "details": {"filled_quantity": "100"},
        },
    )
    primitives.assertion(
        executed["handoff_status"] == "EXECUTED",
        f"{async_proposal_id}: async lifecycle execution did not reach EXECUTED",
    )
    capabilities = primitives.get_json(
        client,
        url=f"{advise_base_url}/platform/capabilities",
        expected_status=200,
    )
    report_feature = primitives.feature_by_key(capabilities, "advisory.proposals.reporting")
    report_response = client.post(
        f"{advise_base_url}/advisory/proposals/{async_proposal_id}/report-requests",
        json={
            "report_type": "CLIENT_PROPOSAL_SUMMARY",
            "requested_by": "advisor_async_1",
            "related_version_no": current_version_no,
            "include_execution_summary": True,
        },
    )
    expected_report_status = "READY" if report_feature["operational_ready"] else "UNAVAILABLE"
    expected_report_http_status = 200 if report_feature["operational_ready"] else 503
    primitives.assertion(
        report_response.status_code == expected_report_http_status,
        (
            f"{async_proposal_id}: expected lotus-report status {expected_report_http_status}, "
            f"got {report_response.status_code} body={report_response.text}"
        ),
    )
    primitives.assert_persisted_read_surfaces(
        client,
        advise_base_url=advise_base_url,
        proposal_id=async_proposal_id,
        expected_portfolio_id=async_portfolio_id,
        created_by_filter="live-parity-validator-async-lifecycle",
        current_version_no=current_version_no,
        expected_state="EXECUTED",
        expected_report_status=expected_report_status,
        get_json=primitives.get_json,
        assert_condition=primitives.assertion,
    )
    return async_portfolio_id, current_version_no, "EXECUTED"
