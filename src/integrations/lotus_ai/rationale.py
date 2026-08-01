from __future__ import annotations

from typing import Any, NoReturn, cast

import httpx

from src.core.workspace.assistant_models import (
    WorkspaceAssistantEvidence,
    WorkspaceAssistantRequest,
    WorkspaceAssistantResponse,
    WorkspaceAssistantWorkflowPackRun,
    WorkspaceAssistantWorkflowPackRunFinding,
    WorkspaceAssistantWorkflowPackRunReviewActionRequest,
    WorkspaceAssistantWorkflowPackRunReviewActionResponse,
)
from src.integrations.lotus_ai.output_safety import (
    DEFAULT_AI_REVIEW_GUIDANCE_LENGTH,
    DEFAULT_AI_REVIEW_GUIDANCE_LIMIT,
    map_bounded_string_list,
    map_bounded_text,
)
from src.integrations.lotus_ai.runtime_config import (
    LotusAITenantIdentityError,
    resolve_lotus_ai_base_url,
)
from src.integrations.lotus_ai.workflow_request import (
    build_workflow_pack_execute_request,
    workflow_pack_authenticated_headers,
)
from src.integrations.lotus_ai.workflow_response import extract_error_detail, safe_dict
from src.integrations.lotus_core.runtime_config import env_positive_float

_WORKFLOW_PACK_ID = "workspace_rationale.pack"
_WORKFLOW_PACK_VERSION = "v1"
_WORKFLOW_SURFACE = "advisory-workspace-assistant"
_MAX_ASSISTANT_OUTPUT_LENGTH = 4000
_MAX_RUN_ID_LENGTH = 160
_MAX_RUN_STATE_LENGTH = 80
_MAX_OWNER_LENGTH = 120
_MAX_FINDINGS = DEFAULT_AI_REVIEW_GUIDANCE_LIMIT
_MAX_FINDING_ID_LENGTH = 120
_MAX_FINDING_SEVERITY_LENGTH = 80
_MAX_FINDING_SUMMARY_LENGTH = DEFAULT_AI_REVIEW_GUIDANCE_LENGTH
_MAX_REVIEW_SUMMARY_ITEMS = DEFAULT_AI_REVIEW_GUIDANCE_LIMIT
_MAX_REVIEW_SUMMARY_LENGTH = DEFAULT_AI_REVIEW_GUIDANCE_LENGTH
_ALLOWED_REVIEW_ACTIONS = frozenset({"ACCEPT", "REJECT", "REVISE", "SUPERSEDE", "ABANDON"})


class LotusAIRationaleUnavailableError(Exception):
    pass


def generate_workspace_rationale_with_lotus_ai(
    *,
    request: WorkspaceAssistantRequest,
    evidence: WorkspaceAssistantEvidence,
) -> WorkspaceAssistantResponse:
    base_url = _resolve_base_url()
    try:
        request_payload = _build_workflow_pack_request(request=request, evidence=evidence)
    except LotusAITenantIdentityError as exc:
        raise LotusAIRationaleUnavailableError("LOTUS_AI_RATIONALE_UNAVAILABLE") from exc
    response, payload = _post_workflow_pack_request(
        base_url=base_url,
        request_payload=request_payload,
    )

    if response.status_code == 200:
        return _workspace_rationale_response_from_success(payload=payload, evidence=evidence)

    _raise_rationale_response_error(response.status_code, payload)


def _post_workflow_pack_request(
    *,
    base_url: str,
    request_payload: dict[str, object],
) -> tuple[httpx.Response, dict[str, Any]]:
    try:
        with httpx.Client(timeout=_resolve_timeout()) as client:
            response = client.post(
                f"{base_url}/platform/workflow-packs/execute",
                json=request_payload,
                headers=workflow_pack_authenticated_headers(),
            )
            payload = safe_dict(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise LotusAIRationaleUnavailableError("LOTUS_AI_RATIONALE_UNAVAILABLE") from exc
    return response, payload


def _workspace_rationale_response_from_success(
    *,
    payload: dict[str, Any],
    evidence: WorkspaceAssistantEvidence,
) -> WorkspaceAssistantResponse:
    execution = safe_dict(payload.get("execution"))
    result = safe_dict(execution.get("result"))
    assistant_output = map_bounded_text(
        result.get("message"),
        max_length=_MAX_ASSISTANT_OUTPUT_LENGTH,
    )
    if execution.get("status") != "COMPLETED":
        raise LotusAIRationaleUnavailableError("LOTUS_AI_RATIONALE_UNAVAILABLE")
    if assistant_output is None:
        raise LotusAIRationaleUnavailableError("LOTUS_AI_RATIONALE_UNAVAILABLE")
    return WorkspaceAssistantResponse(
        assistant_output=assistant_output,
        generated_by="lotus-ai",
        evidence=evidence.model_copy(deep=True),
        workflow_pack_run=_map_workflow_pack_run(safe_dict(payload.get("workflow_pack_run"))),
    )


def _raise_rationale_response_error(status_code: int, payload: dict[str, Any]) -> NoReturn:
    if status_code >= 500:
        raise LotusAIRationaleUnavailableError("LOTUS_AI_RATIONALE_UNAVAILABLE")
    raise LotusAIRationaleUnavailableError(_extract_detail(payload))


def apply_workspace_rationale_review_action_with_lotus_ai(
    request: WorkspaceAssistantWorkflowPackRunReviewActionRequest,
    *,
    workspace_id: str | None = None,
) -> WorkspaceAssistantWorkflowPackRunReviewActionResponse:
    base_url = _resolve_base_url()
    try:
        with httpx.Client(timeout=_resolve_timeout()) as client:
            response = client.post(
                f"{base_url}/platform/workflow-packs/runs/{request.run_id}/review-actions",
                json=_build_review_action_request(request, workspace_id=workspace_id),
                headers=workflow_pack_authenticated_headers(),
            )
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LotusAIRationaleUnavailableError("LOTUS_AI_RATIONALE_UNAVAILABLE") from exc

    if response.status_code == 200:
        workflow_pack_run = _map_workflow_pack_run(safe_dict(payload.get("run")))
        if workflow_pack_run is None:
            raise LotusAIRationaleUnavailableError("LOTUS_AI_RATIONALE_UNAVAILABLE")
        return WorkspaceAssistantWorkflowPackRunReviewActionResponse(
            workflow_pack_run=workflow_pack_run,
            summary=list(
                map_bounded_string_list(
                    payload.get("summary"),
                    max_items=_MAX_REVIEW_SUMMARY_ITEMS,
                    max_item_length=_MAX_REVIEW_SUMMARY_LENGTH,
                )
            ),
        )

    detail = _extract_detail(payload)
    if response.status_code >= 500:
        raise LotusAIRationaleUnavailableError("LOTUS_AI_RATIONALE_UNAVAILABLE")
    raise LotusAIRationaleUnavailableError(detail)


def _resolve_base_url() -> str:
    return cast(
        str,
        resolve_lotus_ai_base_url(
            unavailable_error_type=LotusAIRationaleUnavailableError,
            unavailable_message="LOTUS_AI_RATIONALE_UNAVAILABLE",
        ),
    )


def _resolve_timeout() -> httpx.Timeout:
    return httpx.Timeout(env_positive_float("LOTUS_AI_TIMEOUT_SECONDS", default=10.0))


def _build_workflow_pack_request(
    *,
    request: WorkspaceAssistantRequest,
    evidence: WorkspaceAssistantEvidence,
) -> dict[str, object]:
    return cast(
        dict[str, object],
        build_workflow_pack_execute_request(
            pack_id=_WORKFLOW_PACK_ID,
            version=_WORKFLOW_PACK_VERSION,
            workflow_surface=_WORKFLOW_SURFACE,
            task_id="explain.v1",
            correlation_id=f"workspace-rationale-{evidence.workspace_id}",
            requested_by=request.requested_by,
            context_summary=(
                f"Advisory workspace rationale for {evidence.workspace_id} with proposal "
                f"status {evidence.proposal_status}."
            ),
            context_payload=_build_task_payload(request=request, evidence=evidence),
            source_refs=_build_source_refs(evidence=evidence),
            expected_output_label="EXPLANATION_ONLY",
        ),
    )


def _build_task_payload(
    *,
    request: WorkspaceAssistantRequest,
    evidence: WorkspaceAssistantEvidence,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "workspace": {
            "workspace_id": evidence.workspace_id,
            "input_mode": _normalize_input_mode(evidence.input_mode),
            "requested_by": request.requested_by,
        },
        "evaluation_summary": evidence.evaluation_summary.model_dump(mode="json"),
        "proposal_status": {"value": evidence.proposal_status},
        "instruction": {"text": request.instruction},
    }
    if evidence.resolved_context is not None:
        payload["resolved_context"] = evidence.resolved_context.model_dump(mode="json")
    return payload


def _build_review_action_request(
    request: WorkspaceAssistantWorkflowPackRunReviewActionRequest,
    *,
    workspace_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "action_type": request.action_type,
        "caller_app": "lotus-advise",
        "workflow_surface": _WORKFLOW_SURFACE,
        "pack_id": _WORKFLOW_PACK_ID,
        "version": _WORKFLOW_PACK_VERSION,
        "reviewed_by": request.reviewed_by,
        "reason": request.reason,
    }
    if request.replacement_run_id is not None:
        payload["replacement_run_id"] = request.replacement_run_id
    normalized_workspace_id = _normalize_optional_text(workspace_id)
    if normalized_workspace_id is not None:
        payload["correlation_id"] = f"workspace-rationale-review-{normalized_workspace_id}"
        payload["review_context"] = {
            "workspace_id": normalized_workspace_id,
            "source_refs": [f"lotus-advise:workspace:{normalized_workspace_id}"],
        }
    return payload


def _build_source_refs(*, evidence: WorkspaceAssistantEvidence) -> list[str]:
    refs = [
        f"lotus-advise:workspace:{evidence.workspace_id}",
        f"lotus-advise:proposal-status:{evidence.proposal_status}",
        "lotus-advise:proposal-decision-summary",
    ]
    if evidence.resolved_context is not None and evidence.resolved_context.portfolio_id:
        refs.append(f"lotus-advise:portfolio:{evidence.resolved_context.portfolio_id}")
    return refs


def _extract_detail(payload: dict[str, Any]) -> str:
    return cast(str, extract_error_detail(payload, default="LOTUS_AI_RATIONALE_UNAVAILABLE"))


def _normalize_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_input_mode(value: Any) -> str:
    if isinstance(value, str):
        return value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    return str(value)


def _map_workflow_pack_run(
    payload: dict[str, Any],
) -> WorkspaceAssistantWorkflowPackRun | None:
    run_id = map_bounded_text(payload.get("run_id"), max_length=_MAX_RUN_ID_LENGTH)
    if run_id is None:
        return None
    return WorkspaceAssistantWorkflowPackRun(
        run_id=run_id,
        runtime_state=_map_run_text(payload.get("runtime_state")),
        review_state=_map_run_text(payload.get("review_state")),
        allowed_review_actions=_map_allowed_review_actions(payload.get("allowed_review_actions")),
        supportability_status=_map_run_text(payload.get("supportability_status")),
        review_pending=bool(payload.get("review_state") == "AWAITING_REVIEW"),
        superseded=bool(payload.get("supportability_status") == "HISTORICAL"),
        workflow_authority_owner=(
            map_bounded_text(payload.get("workflow_authority_owner"), max_length=_MAX_OWNER_LENGTH)
            or ""
        ),
        current_summary_note=_build_summary_note(payload),
        replacement_run_id=(
            map_bounded_text(payload.get("replacement_run_id"), max_length=_MAX_RUN_ID_LENGTH)
        ),
        findings=_map_workflow_pack_run_findings(payload.get("findings")),
    )


def _map_workflow_pack_run_findings(value: Any) -> list[WorkspaceAssistantWorkflowPackRunFinding]:
    if not isinstance(value, list):
        return []
    findings: list[WorkspaceAssistantWorkflowPackRunFinding] = []
    for item in value:
        finding = _map_workflow_pack_run_finding(item)
        if finding is None:
            continue
        findings.append(finding)
        if len(findings) >= _MAX_FINDINGS:
            break
    return findings


def _map_workflow_pack_run_finding(
    value: Any,
) -> WorkspaceAssistantWorkflowPackRunFinding | None:
    if not isinstance(value, dict):
        return None
    finding_id = map_bounded_text(
        value.get("finding_id"),
        max_length=_MAX_FINDING_ID_LENGTH,
    )
    severity = map_bounded_text(
        value.get("severity"),
        max_length=_MAX_FINDING_SEVERITY_LENGTH,
    )
    summary = map_bounded_text(
        value.get("summary"),
        max_length=_MAX_FINDING_SUMMARY_LENGTH,
    )
    if finding_id is None or severity is None or summary is None:
        return None
    return WorkspaceAssistantWorkflowPackRunFinding(
        finding_id=finding_id,
        severity=severity,
        summary=summary,
    )


def _map_run_text(value: Any) -> str:
    return map_bounded_text(value, max_length=_MAX_RUN_STATE_LENGTH) or ""


def _map_allowed_review_actions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    actions: list[str] = []
    for item in value:
        action = _mapped_allowed_review_action(item)
        if action is not None and action not in actions:
            actions.append(action)
    return actions


def _mapped_allowed_review_action(value: Any) -> str | None:
    action = map_bounded_text(value, max_length=_MAX_RUN_STATE_LENGTH)
    if action is None or action not in _ALLOWED_REVIEW_ACTIONS:
        return None
    return action


def _build_summary_note(payload: dict[str, Any]) -> str:
    review_state = str(payload.get("review_state", ""))
    supportability_status = str(payload.get("supportability_status", ""))
    if supportability_status == "HISTORICAL":
        return "Run is historical due to replacement lineage."
    if review_state == "AWAITING_REVIEW":
        return "Run completed but still requires bounded human review before downstream use."
    if supportability_status == "READY":
        return "Run is ready for bounded downstream use."
    return "Workflow-pack run posture is available from lotus-ai."
