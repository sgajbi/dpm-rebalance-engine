from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast

import httpx

from src.core.advisory_copilot import (
    AdvisoryCopilotRuntimeBudget,
    AdvisoryCopilotRuntimeBudgetExceeded,
    AdvisoryCopilotRuntimeUsage,
    CopilotAudience,
    CopilotEvidencePacket,
    CopilotGuardrailPolicyInput,
    CopilotGuardrailReasonCode,
    CopilotGuardrailSourceEvidence,
    CopilotLineageRef,
    CopilotSourceRef,
    advisory_copilot_payload_usage,
    advisory_copilot_runtime_budget_controls,
    advisory_copilot_runtime_budget_telemetry,
    align_copilot_output_claims_to_evidence,
    evaluate_copilot_guardrail_policy,
    validate_advisory_copilot_input_budget,
    validate_advisory_copilot_output_budget,
    workflow_pack_id_for_action,
    workflow_pack_version_for_action,
)
from src.core.advisory_copilot.evaluation_gate import (
    AdvisoryCopilotEvaluationResult,
    evaluate_advisory_copilot_model_risk,
)
from src.core.advisory_copilot.model_governance import (
    ADVISORY_COPILOT_APPROVED_INSTRUCTION_SET,
    ADVISORY_COPILOT_EVALUATION_PACK_REF,
    ADVISORY_COPILOT_OUTPUT_SCHEMA_VERSION,
    ADVISORY_COPILOT_PROMPT_TEMPLATE_VERSION,
    AdvisoryCopilotModelApproval,
    advisory_copilot_model_approval_for_request,
    validate_advisory_copilot_model_response,
)
from src.integrations.lotus_ai.advisory_copilot_request import (
    build_advisory_copilot_workflow_pack_request,
    workflow_surface,
)
from src.integrations.lotus_ai.output_safety import (
    DEFAULT_AI_OUTPUT_SECTION_KEY_LENGTH,
    DEFAULT_AI_OUTPUT_SECTION_LIMIT,
    DEFAULT_AI_OUTPUT_SECTION_TEXT_LENGTH,
    DEFAULT_AI_OUTPUT_SECTION_TITLE_LENGTH,
    DEFAULT_AI_REVIEW_GUIDANCE_LENGTH,
    DEFAULT_AI_REVIEW_GUIDANCE_LIMIT,
    map_bounded_string_list,
    map_review_required_sections,
)
from src.integrations.lotus_ai.runtime_config import (
    LotusAITenantIdentityError,
    resolve_lotus_ai_base_url,
)
from src.integrations.lotus_ai.workflow_request import (
    workflow_pack_authenticated_headers,
    workflow_pack_environment,
)
from src.integrations.lotus_ai.workflow_response import (
    extract_error_detail,
    extract_model_version,
    extract_provider_id,
    extract_workflow_run_id,
    safe_dict,
)
from src.integrations.lotus_core.runtime_config import env_positive_float, env_positive_int

ADAPTER_VERSION = "advisory-copilot-lotus-ai-adapter.v1"
APPROVED_INSTRUCTION_SET = ADVISORY_COPILOT_APPROVED_INSTRUCTION_SET
PROMPT_TEMPLATE_VERSION = ADVISORY_COPILOT_PROMPT_TEMPLATE_VERSION
OUTPUT_SCHEMA_VERSION = ADVISORY_COPILOT_OUTPUT_SCHEMA_VERSION
EVALUATION_PACK_REF = ADVISORY_COPILOT_EVALUATION_PACK_REF
MAX_COPILOT_OUTPUT_SECTIONS = DEFAULT_AI_OUTPUT_SECTION_LIMIT
MAX_COPILOT_SECTION_KEY_LENGTH = DEFAULT_AI_OUTPUT_SECTION_KEY_LENGTH
MAX_COPILOT_SECTION_TITLE_LENGTH = DEFAULT_AI_OUTPUT_SECTION_TITLE_LENGTH
MAX_COPILOT_SECTION_TEXT_LENGTH = DEFAULT_AI_OUTPUT_SECTION_TEXT_LENGTH
MAX_COPILOT_REVIEW_GUIDANCE_ITEMS = DEFAULT_AI_REVIEW_GUIDANCE_LIMIT
MAX_COPILOT_REVIEW_GUIDANCE_LENGTH = DEFAULT_AI_REVIEW_GUIDANCE_LENGTH
MAX_COPILOT_LINEAGE_REF_LENGTH = 160
_CONCURRENCY_LOCK = threading.Lock()
_CONCURRENCY_LIMITS: dict[int, threading.BoundedSemaphore] = {}
_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.ReadTimeout,
)


@dataclass(frozen=True)
class AdvisoryCopilotAiDraft:
    status: str
    sections: tuple[dict[str, Any], ...]
    lineage: dict[str, Any]
    review_guidance: tuple[str, ...]
    guardrail_reasons: tuple[CopilotGuardrailReasonCode, ...]


@dataclass(frozen=True)
class _WorkflowPackExecutionResult:
    response_status: int
    payload: dict[str, Any]
    runtime_budget_telemetry: dict[str, Any]


def generate_advisory_copilot_draft_with_lotus_ai(
    *,
    evidence_packet: CopilotEvidencePacket,
    audience: CopilotAudience,
    requested_outputs: list[str],
    requested_by: str,
    reason: dict[str, Any],
    requested_intents: tuple[str, ...] = (),
    user_instruction: str = "",
) -> AdvisoryCopilotAiDraft:
    preflight_rejection = _preflight_guardrail_rejection(
        evidence_packet=evidence_packet,
        requested_intents=requested_intents,
        user_instruction=user_instruction,
    )
    if preflight_rejection is not None:
        return preflight_rejection

    environment = workflow_pack_environment()
    approval_decision = advisory_copilot_model_approval_for_request(
        action_family=evidence_packet.action_family,
        environment=environment,
        workflow_pack_id=workflow_pack_id_for_action(evidence_packet.action_family),
        workflow_pack_version=workflow_pack_version_for_action(evidence_packet.action_family),
        approved_instruction_set=APPROVED_INSTRUCTION_SET,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        evaluation_pack_ref=EVALUATION_PACK_REF,
    )
    if not approval_decision.approved or approval_decision.approval is None:
        return build_advisory_copilot_unavailable_draft(
            evidence_packet=evidence_packet,
            fallback_reason=approval_decision.code,
            caused_by=None,
            model_environment=environment,
        )

    try:
        execution = _execute_workflow_pack(
            evidence_packet=evidence_packet,
            audience=audience,
            requested_outputs=requested_outputs,
            requested_by=requested_by,
            reason=reason,
            model_approval=approval_decision.approval,
        )
    except LotusAITenantIdentityError as exc:
        return build_advisory_copilot_unavailable_draft(
            evidence_packet=evidence_packet,
            fallback_reason=str(exc) or "LOTUS_AI_TENANT_ID_UNAVAILABLE",
            caused_by=None,
            model_approval=approval_decision.approval,
            model_environment=environment,
        )
    except AdvisoryCopilotRuntimeBudgetExceeded as exc:
        return build_advisory_copilot_unavailable_draft(
            evidence_packet=evidence_packet,
            fallback_reason=exc.reason_code,
            caused_by=None,
            model_approval=approval_decision.approval,
            model_environment=environment,
            runtime_budget_telemetry=exc.telemetry,
        )
    except (httpx.HTTPError, ValueError, LotusAIAdvisoryCopilotUnavailableError) as exc:
        runtime_budget_telemetry = getattr(exc, "runtime_budget_telemetry", None)
        return build_advisory_copilot_unavailable_draft(
            evidence_packet=evidence_packet,
            fallback_reason="LOTUS_AI_ADVISORY_COPILOT_UNAVAILABLE",
            caused_by=exc,
            model_approval=approval_decision.approval,
            model_environment=environment,
            runtime_budget_telemetry=runtime_budget_telemetry,
        )

    return _draft_from_workflow_response(
        evidence_packet=evidence_packet,
        response_status=execution.response_status,
        payload=execution.payload,
        model_approval=approval_decision.approval,
        model_environment=environment,
        runtime_budget_telemetry=execution.runtime_budget_telemetry,
    )


def _preflight_guardrail_rejection(
    *,
    evidence_packet: CopilotEvidencePacket,
    requested_intents: tuple[str, ...],
    user_instruction: str,
) -> AdvisoryCopilotAiDraft | None:
    preflight_reasons = evaluate_copilot_guardrail_policy(
        CopilotGuardrailPolicyInput(
            requested_intents=requested_intents,
            source_evidence=_guardrail_source_evidence(evidence_packet),
            user_instruction=user_instruction,
        )
    )
    if not preflight_reasons:
        return None
    return _guardrail_rejected_draft(
        evidence_packet=evidence_packet,
        guardrail_reasons=preflight_reasons,
        fallback_reason="COPILOT_GUARDRAIL_PREFLIGHT_REJECTED",
    )


def _execute_workflow_pack(
    *,
    evidence_packet: CopilotEvidencePacket,
    audience: CopilotAudience,
    requested_outputs: list[str],
    requested_by: str,
    reason: dict[str, Any],
    model_approval: AdvisoryCopilotModelApproval,
) -> _WorkflowPackExecutionResult:
    runtime_budget = _resolve_runtime_budget()
    base_url = _resolve_base_url()
    request_payload = _build_workflow_pack_request(
        evidence_packet=evidence_packet,
        audience=audience,
        requested_outputs=requested_outputs,
        requested_by=requested_by,
        reason=reason,
        model_approval=model_approval,
        runtime_budget=runtime_budget,
    )
    input_usage = advisory_copilot_payload_usage(request_payload)
    validate_advisory_copilot_input_budget(
        usage=input_usage,
        budget=runtime_budget,
        telemetry=advisory_copilot_runtime_budget_telemetry(
            budget=runtime_budget,
            attempt_count=0,
            latency_ms=0,
            fallback_reason="COPILOT_AI_INPUT_BUDGET_EXHAUSTED",
            retry_exhausted=False,
            last_error_type=None,
            input_usage=input_usage,
        ),
    )

    with _advisory_copilot_capacity(runtime_budget, input_usage):
        return _post_workflow_pack_with_budget(
            base_url=base_url,
            request_payload=request_payload,
            runtime_budget=runtime_budget,
            input_usage=input_usage,
        )


def _post_workflow_pack_with_budget(
    *,
    base_url: str,
    request_payload: dict[str, object],
    runtime_budget: AdvisoryCopilotRuntimeBudget,
    input_usage: AdvisoryCopilotRuntimeUsage,
) -> _WorkflowPackExecutionResult:
    started = time.perf_counter()
    attempt_count = 0
    last_error: httpx.HTTPError | None = None
    with httpx.Client(timeout=_resolve_timeout(runtime_budget)) as client:
        while attempt_count < runtime_budget.max_attempts:
            attempt_count += 1
            try:
                response = client.post(
                    f"{base_url}/platform/workflow-packs/execute",
                    json=request_payload,
                    headers=workflow_pack_authenticated_headers(),
                )
                payload = response.json()
                output_usage = advisory_copilot_payload_usage(
                    _workflow_pack_generated_output_payload(payload)
                )
                telemetry = advisory_copilot_runtime_budget_telemetry(
                    budget=runtime_budget,
                    attempt_count=attempt_count,
                    latency_ms=_elapsed_ms(started),
                    fallback_reason=None,
                    retry_exhausted=False,
                    last_error_type=_error_name(last_error),
                    input_usage=input_usage,
                    output_usage=output_usage,
                )
                validate_advisory_copilot_output_budget(
                    usage=output_usage,
                    budget=runtime_budget,
                    telemetry={
                        **telemetry,
                        "fallback_reason": "COPILOT_AI_OUTPUT_BUDGET_EXHAUSTED",
                    },
                )
                return _WorkflowPackExecutionResult(
                    response_status=response.status_code,
                    payload=payload,
                    runtime_budget_telemetry=telemetry,
                )
            except AdvisoryCopilotRuntimeBudgetExceeded:
                raise
            except _RETRYABLE_TRANSPORT_ERRORS as exc:
                last_error = exc
                if attempt_count >= runtime_budget.max_attempts:
                    raise AdvisoryCopilotRuntimeBudgetExceeded(
                        "COPILOT_AI_RETRY_BUDGET_EXHAUSTED",
                        advisory_copilot_runtime_budget_telemetry(
                            budget=runtime_budget,
                            attempt_count=attempt_count,
                            latency_ms=_elapsed_ms(started),
                            fallback_reason="COPILOT_AI_RETRY_BUDGET_EXHAUSTED",
                            retry_exhausted=True,
                            last_error_type=_error_name(exc),
                            input_usage=input_usage,
                        ),
                    ) from exc
                _sleep_before_retry(runtime_budget)
            except (httpx.HTTPError, ValueError) as exc:
                raise LotusAIAdvisoryCopilotUnavailableError(
                    "LOTUS_AI_ADVISORY_COPILOT_UNAVAILABLE",
                    runtime_budget_telemetry=advisory_copilot_runtime_budget_telemetry(
                        budget=runtime_budget,
                        attempt_count=attempt_count,
                        latency_ms=_elapsed_ms(started),
                        fallback_reason="LOTUS_AI_ADVISORY_COPILOT_UNAVAILABLE",
                        retry_exhausted=False,
                        last_error_type=_error_name(exc),
                        input_usage=input_usage,
                    ),
                ) from exc

    raise AdvisoryCopilotRuntimeBudgetExceeded(
        "COPILOT_AI_RETRY_BUDGET_EXHAUSTED",
        advisory_copilot_runtime_budget_telemetry(
            budget=runtime_budget,
            attempt_count=attempt_count,
            latency_ms=_elapsed_ms(started),
            fallback_reason="COPILOT_AI_RETRY_BUDGET_EXHAUSTED",
            retry_exhausted=True,
            last_error_type=_error_name(last_error),
            input_usage=input_usage,
        ),
    )


def _workflow_pack_generated_output_payload(payload: dict[str, Any]) -> dict[str, Any]:
    execution = safe_dict(payload.get("execution"))
    result = safe_dict(execution.get("result"))
    if not result:
        return payload
    return {
        "message": result.get("message"),
        "structured_output": result.get("structured_output"),
    }


def _draft_from_workflow_response(
    *,
    evidence_packet: CopilotEvidencePacket,
    response_status: int,
    payload: dict[str, Any],
    model_approval: AdvisoryCopilotModelApproval,
    model_environment: str,
    runtime_budget_telemetry: dict[str, Any],
) -> AdvisoryCopilotAiDraft:
    if response_status != 200:
        return build_advisory_copilot_unavailable_draft(
            evidence_packet=evidence_packet,
            fallback_reason=extract_error_detail(
                payload,
                default="LOTUS_AI_ADVISORY_COPILOT_UNAVAILABLE",
                max_length=MAX_COPILOT_LINEAGE_REF_LENGTH,
            ),
            caused_by=None,
            model_approval=model_approval,
            model_environment=model_environment,
            runtime_budget_telemetry={
                **runtime_budget_telemetry,
                "fallback_reason": extract_error_detail(
                    payload,
                    default="LOTUS_AI_ADVISORY_COPILOT_UNAVAILABLE",
                    max_length=MAX_COPILOT_LINEAGE_REF_LENGTH,
                ),
            },
        )

    execution = safe_dict(payload.get("execution"))
    if execution.get("status") != "COMPLETED":
        return build_advisory_copilot_unavailable_draft(
            evidence_packet=evidence_packet,
            fallback_reason="LOTUS_AI_ADVISORY_COPILOT_UNAVAILABLE",
            caused_by=None,
            model_approval=model_approval,
            model_environment=model_environment,
            runtime_budget_telemetry={
                **runtime_budget_telemetry,
                "fallback_reason": "LOTUS_AI_ADVISORY_COPILOT_UNAVAILABLE",
            },
        )

    result = safe_dict(execution.get("result"))
    audit = safe_dict(execution.get("audit"))
    provider_id = extract_provider_id(
        result,
        audit=audit,
        max_length=MAX_COPILOT_LINEAGE_REF_LENGTH,
    )
    model_version = extract_model_version(
        result,
        audit=audit,
        max_length=MAX_COPILOT_LINEAGE_REF_LENGTH,
    )
    response_model_decision = validate_advisory_copilot_model_response(
        expected_approval=model_approval,
        provider_id=provider_id,
        model_version=model_version,
    )
    if not response_model_decision.approved:
        return build_advisory_copilot_unavailable_draft(
            evidence_packet=evidence_packet,
            fallback_reason=response_model_decision.code,
            caused_by=None,
            model_approval=model_approval,
            model_environment=model_environment,
            provider_id=provider_id,
            model_version=model_version,
            runtime_budget_telemetry={
                **runtime_budget_telemetry,
                "fallback_reason": response_model_decision.code,
            },
        )

    structured_output = safe_dict(result.get("structured_output"))
    raw_sections = structured_output.get("sections")
    sections = _map_sections(raw_sections)
    if not sections:
        return build_advisory_copilot_unavailable_draft(
            evidence_packet=evidence_packet,
            fallback_reason="LOTUS_AI_ADVISORY_COPILOT_INVALID_OUTPUT",
            caused_by=None,
            model_approval=model_approval,
            model_environment=model_environment,
            provider_id=provider_id,
            model_version=model_version,
            runtime_budget_telemetry={
                **runtime_budget_telemetry,
                "fallback_reason": "LOTUS_AI_ADVISORY_COPILOT_INVALID_OUTPUT",
            },
        )
    return _draft_from_completed_workflow_output(
        evidence_packet=evidence_packet,
        payload=payload,
        result=result,
        structured_output=structured_output,
        raw_sections=raw_sections,
        sections=sections,
        model_approval=model_approval,
        model_environment=model_environment,
        provider_id=provider_id,
        model_version=model_version,
        runtime_budget_telemetry=runtime_budget_telemetry,
    )


def _draft_from_completed_workflow_output(
    *,
    evidence_packet: CopilotEvidencePacket,
    payload: dict[str, Any],
    result: dict[str, Any],
    structured_output: dict[str, Any],
    raw_sections: Any,
    sections: tuple[dict[str, Any], ...],
    model_approval: AdvisoryCopilotModelApproval,
    model_environment: str,
    provider_id: str | None,
    model_version: str | None,
    runtime_budget_telemetry: dict[str, Any],
) -> AdvisoryCopilotAiDraft:
    output_reasons = evaluate_copilot_guardrail_policy(
        CopilotGuardrailPolicyInput(
            source_evidence=_guardrail_source_evidence(evidence_packet),
            model_output_sections=tuple(str(section.get("text", "")) for section in sections),
        )
    )
    if output_reasons:
        return _guardrail_rejected_draft(
            evidence_packet=evidence_packet,
            guardrail_reasons=output_reasons,
            fallback_reason="COPILOT_OUTPUT_GUARDRAIL_REJECTED",
            workflow_run_id=extract_workflow_run_id(
                payload,
                max_length=MAX_COPILOT_LINEAGE_REF_LENGTH,
            ),
            model_version=model_version,
            provider_id=provider_id,
            model_approval=model_approval,
            model_environment=model_environment,
            runtime_budget_telemetry={
                **runtime_budget_telemetry,
                "fallback_reason": "COPILOT_OUTPUT_GUARDRAIL_REJECTED",
            },
        )

    grounded_sections, grounding_summary = align_copilot_output_claims_to_evidence(
        evidence_packet=evidence_packet,
        raw_sections=raw_sections,
        output_sections=sections,
    )
    evaluation_result = evaluate_advisory_copilot_model_risk(
        action_family=evidence_packet.action_family,
        workflow_pack_id=workflow_pack_id_for_action(evidence_packet.action_family),
        workflow_pack_version=workflow_pack_version_for_action(evidence_packet.action_family),
        provider_id=provider_id,
        model_version=model_version,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        evaluation_pack_ref=EVALUATION_PACK_REF,
        draft_status=str(structured_output.get("state") or "REVIEW_REQUIRED"),
        output_section_count=len(grounded_sections),
        grounding_summary=grounding_summary,
        guardrail_reasons=(),
    )
    draft_status = (
        str(structured_output.get("state") or "REVIEW_REQUIRED")
        if grounding_summary["ready_for_review"] and evaluation_result.approved
        else "UNSUPPORTED"
    )

    return AdvisoryCopilotAiDraft(
        status=draft_status,
        sections=grounded_sections,
        lineage=_build_lineage(
            evidence_packet=evidence_packet,
            workflow_run_id=extract_workflow_run_id(
                payload,
                max_length=MAX_COPILOT_LINEAGE_REF_LENGTH,
            ),
            model_version=model_version,
            provider_id=provider_id,
            model_approval=model_approval,
            model_environment=model_environment,
            fallback_reason=None,
            claim_grounding_summary=grounding_summary,
            model_risk_evaluation=evaluation_result,
            runtime_budget_telemetry=runtime_budget_telemetry,
        ),
        review_guidance=_map_string_list(structured_output.get("review_guidance")),
        guardrail_reasons=(),
    )


class LotusAIAdvisoryCopilotUnavailableError(Exception):
    def __init__(
        self,
        message: str,
        *,
        runtime_budget_telemetry: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.runtime_budget_telemetry = runtime_budget_telemetry


def build_advisory_copilot_unavailable_draft(
    *,
    evidence_packet: CopilotEvidencePacket,
    fallback_reason: str,
    caused_by: Exception | None = None,
    model_approval: AdvisoryCopilotModelApproval | None = None,
    model_environment: str | None = None,
    provider_id: str | None = None,
    model_version: str | None = None,
    runtime_budget_telemetry: dict[str, Any] | None = None,
) -> AdvisoryCopilotAiDraft:
    if caused_by is not None:
        fallback_reason = fallback_reason or caused_by.__class__.__name__
    return AdvisoryCopilotAiDraft(
        status="UNAVAILABLE",
        sections=(),
        lineage=_build_lineage(
            evidence_packet=evidence_packet,
            workflow_run_id=None,
            model_version=model_version,
            provider_id=provider_id,
            fallback_reason=fallback_reason,
            model_approval=model_approval,
            model_environment=model_environment,
            runtime_budget_telemetry=runtime_budget_telemetry,
        ),
        review_guidance=(
            "Advisory copilot support is unavailable; use source evidence and deterministic "
            "advisory workflow sections only.",
            "Do not infer missing suitability, approval, policy, order, or client-ready "
            "communication evidence.",
        ),
        guardrail_reasons=(),
    )


def _guardrail_rejected_draft(
    *,
    evidence_packet: CopilotEvidencePacket,
    guardrail_reasons: tuple[CopilotGuardrailReasonCode, ...],
    fallback_reason: str,
    workflow_run_id: str | None = None,
    model_version: str | None = None,
    provider_id: str | None = None,
    model_approval: AdvisoryCopilotModelApproval | None = None,
    model_environment: str | None = None,
    runtime_budget_telemetry: dict[str, Any] | None = None,
) -> AdvisoryCopilotAiDraft:
    return AdvisoryCopilotAiDraft(
        status="GUARDRAIL_REJECTED",
        sections=(),
        lineage=_build_lineage(
            evidence_packet=evidence_packet,
            workflow_run_id=workflow_run_id,
            model_version=model_version,
            provider_id=provider_id,
            fallback_reason=fallback_reason,
            model_approval=model_approval,
            model_environment=model_environment,
            runtime_budget_telemetry=runtime_budget_telemetry,
        ),
        review_guidance=(
            "The advisory copilot request was blocked by governed safety controls.",
            "Use source evidence and advisor workflow controls; do not bypass review or "
            "client-ready gates.",
        ),
        guardrail_reasons=guardrail_reasons,
    )


def _build_workflow_pack_request(
    *,
    evidence_packet: CopilotEvidencePacket,
    audience: CopilotAudience,
    requested_outputs: list[str],
    requested_by: str,
    reason: dict[str, Any],
    model_approval: AdvisoryCopilotModelApproval,
    runtime_budget: AdvisoryCopilotRuntimeBudget | None = None,
) -> dict[str, object]:
    return cast(
        dict[str, object],
        build_advisory_copilot_workflow_pack_request(
            evidence_packet=evidence_packet,
            audience=audience,
            requested_outputs=requested_outputs,
            requested_by=requested_by,
            reason=reason,
            adapter_version=ADAPTER_VERSION,
            approved_instruction_set=APPROVED_INSTRUCTION_SET,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            output_schema_version=OUTPUT_SCHEMA_VERSION,
            evaluation_pack_ref=EVALUATION_PACK_REF,
            approved_provider_id=model_approval.provider_id,
            approved_model_version=model_approval.model_version,
            approval_reference=model_approval.approval_reference,
            change_reference=model_approval.change_reference,
            release_evidence_ref=model_approval.release_evidence_ref,
            runtime_budget_controls=advisory_copilot_runtime_budget_controls(runtime_budget),
        ),
    )


def _guardrail_source_evidence(
    evidence_packet: CopilotEvidencePacket,
) -> tuple[CopilotGuardrailSourceEvidence, ...]:
    return tuple(
        CopilotGuardrailSourceEvidence(
            section_key=section.section_key,
            title=section.title,
            summary_items=section.summary_items,
            source_ref_count=len(section.source_refs),
        )
        for section in evidence_packet.sections
    )


def _resolve_base_url() -> str:
    return cast(
        str,
        resolve_lotus_ai_base_url(
            unavailable_error_type=LotusAIAdvisoryCopilotUnavailableError,
            unavailable_message="LOTUS_AI_ADVISORY_COPILOT_UNAVAILABLE",
        ),
    )


def _resolve_runtime_budget() -> AdvisoryCopilotRuntimeBudget:
    timeout_seconds = env_positive_float("LOTUS_AI_TIMEOUT_SECONDS", default=10.0, maximum=30.0)
    return AdvisoryCopilotRuntimeBudget(
        timeout_ms=max(1, int(timeout_seconds * 1000)),
        max_attempts=env_positive_int(
            "LOTUS_AI_ADVISORY_COPILOT_RETRY_ATTEMPTS",
            default=2,
            maximum=3,
        ),
        retry_backoff_ms=env_positive_int(
            "LOTUS_AI_ADVISORY_COPILOT_RETRY_BACKOFF_MS",
            default=100,
            maximum=2_000,
        ),
        max_input_characters=env_positive_int(
            "LOTUS_AI_ADVISORY_COPILOT_MAX_INPUT_CHARACTERS",
            default=32_000,
            maximum=128_000,
        ),
        max_output_characters=env_positive_int(
            "LOTUS_AI_ADVISORY_COPILOT_MAX_OUTPUT_CHARACTERS",
            default=20_000,
            maximum=80_000,
        ),
        max_prompt_tokens=env_positive_int(
            "LOTUS_AI_ADVISORY_COPILOT_MAX_PROMPT_TOKENS",
            default=8_000,
            maximum=32_000,
        ),
        max_completion_tokens=env_positive_int(
            "LOTUS_AI_ADVISORY_COPILOT_MAX_COMPLETION_TOKENS",
            default=1_200,
            maximum=8_000,
        ),
        max_total_tokens=env_positive_int(
            "LOTUS_AI_ADVISORY_COPILOT_MAX_TOTAL_TOKENS",
            default=9_200,
            maximum=40_000,
        ),
        max_chargeable_cost_units=env_positive_int(
            "LOTUS_AI_ADVISORY_COPILOT_MAX_CHARGEABLE_COST_UNITS",
            default=50_000,
            maximum=5_000_000,
        ),
        max_concurrent_requests=env_positive_int(
            "LOTUS_AI_ADVISORY_COPILOT_MAX_CONCURRENT_REQUESTS",
            default=4,
            maximum=16,
        ),
    )


def _resolve_timeout(runtime_budget: AdvisoryCopilotRuntimeBudget) -> httpx.Timeout:
    return httpx.Timeout(runtime_budget.timeout_ms / 1000)


@contextmanager
def _advisory_copilot_capacity(
    runtime_budget: AdvisoryCopilotRuntimeBudget,
    input_usage: AdvisoryCopilotRuntimeUsage,
) -> Any:
    semaphore = _semaphore_for_limit(runtime_budget.max_concurrent_requests)
    if not semaphore.acquire(blocking=False):
        raise AdvisoryCopilotRuntimeBudgetExceeded(
            "COPILOT_AI_CONCURRENCY_BUDGET_EXHAUSTED",
            advisory_copilot_runtime_budget_telemetry(
                budget=runtime_budget,
                attempt_count=0,
                latency_ms=0,
                fallback_reason="COPILOT_AI_CONCURRENCY_BUDGET_EXHAUSTED",
                retry_exhausted=False,
                last_error_type=None,
                input_usage=input_usage,
            ),
        )
    try:
        yield
    finally:
        semaphore.release()


def _semaphore_for_limit(limit: int) -> threading.BoundedSemaphore:
    with _CONCURRENCY_LOCK:
        semaphore = _CONCURRENCY_LIMITS.get(limit)
        if semaphore is None:
            semaphore = threading.BoundedSemaphore(limit)
            _CONCURRENCY_LIMITS[limit] = semaphore
        return semaphore


def _sleep_before_retry(runtime_budget: AdvisoryCopilotRuntimeBudget) -> None:
    if runtime_budget.retry_backoff_ms > 0:
        time.sleep(runtime_budget.retry_backoff_ms / 1000)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _error_name(error: Exception | None) -> str | None:
    return None if error is None else error.__class__.__name__


def _map_sections(value: Any) -> tuple[dict[str, Any], ...]:
    return cast(
        tuple[dict[str, Any], ...],
        map_review_required_sections(
            value,
            max_sections=MAX_COPILOT_OUTPUT_SECTIONS,
            max_section_key_length=MAX_COPILOT_SECTION_KEY_LENGTH,
            max_title_length=MAX_COPILOT_SECTION_TITLE_LENGTH,
            max_text_length=MAX_COPILOT_SECTION_TEXT_LENGTH,
        ),
    )


def _map_string_list(value: Any) -> tuple[str, ...]:
    return cast(
        tuple[str, ...],
        map_bounded_string_list(
            value,
            max_items=MAX_COPILOT_REVIEW_GUIDANCE_ITEMS,
            max_item_length=MAX_COPILOT_REVIEW_GUIDANCE_LENGTH,
        ),
    )


def _build_lineage(
    *,
    evidence_packet: CopilotEvidencePacket,
    workflow_run_id: str | None,
    model_version: str | None,
    provider_id: str | None = None,
    fallback_reason: str | None,
    model_approval: AdvisoryCopilotModelApproval | None = None,
    model_environment: str | None = None,
    claim_grounding_summary: dict[str, Any] | None = None,
    model_risk_evaluation: AdvisoryCopilotEvaluationResult | None = None,
    runtime_budget_telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lineage: dict[str, Any] = {
        "adapter_version": ADAPTER_VERSION,
        "workflow_pack_id": workflow_pack_id_for_action(evidence_packet.action_family),
        "workflow_pack_version": workflow_pack_version_for_action(evidence_packet.action_family),
        "workflow_surface": workflow_surface(evidence_packet.action_family),
        "workflow_run_id": workflow_run_id,
        "model_version": model_version,
        "model_provider_id": provider_id,
        "approved_instruction_set": APPROVED_INSTRUCTION_SET,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "evaluation_pack_ref": EVALUATION_PACK_REF,
        "evidence_packet_hash": evidence_packet.evidence_packet_hash,
        "proposal_version_id": _proposal_version_id(evidence_packet),
        "proposal_version_no": _proposal_version_no(evidence_packet),
        "fallback_reason": fallback_reason,
    }
    if model_approval is not None:
        lineage.update(model_approval.lineage(environment=model_environment or "DEVELOPMENT"))
    if claim_grounding_summary is not None:
        lineage["claim_grounding_summary"] = claim_grounding_summary
    if model_risk_evaluation is not None:
        lineage["model_risk_evaluation"] = model_risk_evaluation.lineage()
    if runtime_budget_telemetry is not None:
        lineage["runtime_budget_telemetry"] = runtime_budget_telemetry
    return lineage


def _proposal_version_id(evidence_packet: CopilotEvidencePacket) -> str | None:
    return _proposal_version_lineage_id(evidence_packet) or _proposal_version_source_id(
        evidence_packet
    )


def _proposal_version_lineage_id(evidence_packet: CopilotEvidencePacket) -> str | None:
    for lineage_ref in evidence_packet.lineage_refs:
        if _is_proposal_version_lineage_ref(lineage_ref):
            return cast(str, lineage_ref.lineage_id)
    return None


def _is_proposal_version_lineage_ref(lineage_ref: CopilotLineageRef) -> bool:
    return (
        lineage_ref.source_system == "lotus-advise"
        and lineage_ref.lineage_type == "PROPOSAL_VERSION"
        and _is_present_string(lineage_ref.lineage_id)
    )


def _proposal_version_source_id(evidence_packet: CopilotEvidencePacket) -> str | None:
    for section in evidence_packet.sections:
        for source_ref in section.source_refs:
            if _is_proposal_version_source_ref(source_ref):
                return cast(str, source_ref.source_id)
    return None


def _is_proposal_version_source_ref(source_ref: CopilotSourceRef) -> bool:
    return (
        source_ref.source_system == "lotus-advise"
        and source_ref.source_type == "PROPOSAL_VERSION"
        and _is_present_string(source_ref.source_id)
    )


def _is_present_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _proposal_version_no(evidence_packet: CopilotEvidencePacket) -> int | None:
    for lineage_ref in evidence_packet.lineage_refs:
        if (
            lineage_ref.source_system == "lotus-advise"
            and lineage_ref.lineage_type == "PROPOSAL_VERSION_NO"
            and lineage_ref.lineage_id.isdigit()
        ):
            return int(lineage_ref.lineage_id)
    return None
