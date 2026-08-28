from __future__ import annotations

from typing import Any, NoReturn, cast

import httpx

from src.core.proposals.memo_ai_ports import (
    ProposalMemoAiCommentaryDraft,
)
from src.core.proposals.memo_ai_ports import (
    build_proposal_memo_ai_unavailable_commentary as _build_core_unavailable_commentary,
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
    build_workflow_pack_execute_request,
    workflow_pack_authenticated_headers,
)
from src.integrations.lotus_ai.workflow_response import (
    extract_error_detail,
    extract_model_version,
    extract_workflow_run_id,
    safe_dict,
)
from src.integrations.lotus_core.runtime_config import env_positive_float

ADAPTER_VERSION = "proposal-memo-commentary-lotus-ai-adapter.v1"
WORKFLOW_PACK_ID = "proposal_memo_commentary.pack"
WORKFLOW_PACK_VERSION = "v1"
WORKFLOW_SURFACE = "advisor-proposal-memo-commentary"
MAX_MEMO_AI_OUTPUT_SECTIONS = DEFAULT_AI_OUTPUT_SECTION_LIMIT
MAX_MEMO_AI_SECTION_KEY_LENGTH = DEFAULT_AI_OUTPUT_SECTION_KEY_LENGTH
MAX_MEMO_AI_SECTION_TITLE_LENGTH = DEFAULT_AI_OUTPUT_SECTION_TITLE_LENGTH
MAX_MEMO_AI_SECTION_TEXT_LENGTH = DEFAULT_AI_OUTPUT_SECTION_TEXT_LENGTH
MAX_MEMO_AI_REVIEW_GUIDANCE_ITEMS = DEFAULT_AI_REVIEW_GUIDANCE_LIMIT
MAX_MEMO_AI_REVIEW_GUIDANCE_LENGTH = DEFAULT_AI_REVIEW_GUIDANCE_LENGTH


class LotusAIProposalMemoUnavailableError(Exception):
    pass


def generate_proposal_memo_commentary_with_lotus_ai(
    *,
    memo_evidence: dict[str, Any],
    requested_sections: list[str],
    requested_by: str,
    reason: dict[str, Any],
    idempotency_key: str | None = None,
) -> ProposalMemoAiCommentaryDraft:
    base_url = _resolve_base_url()
    try:
        request_payload = _build_workflow_pack_request(
            memo_evidence=memo_evidence,
            requested_sections=requested_sections,
            requested_by=requested_by,
            reason=reason,
            idempotency_key=idempotency_key,
        )
    except LotusAITenantIdentityError as exc:
        raise LotusAIProposalMemoUnavailableError("LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE") from exc
    response, payload = _post_workflow_pack_request(
        base_url=base_url,
        request_payload=request_payload,
    )

    if response.status_code == 200:
        return _proposal_memo_commentary_from_success(payload)

    _raise_proposal_memo_response_error(response.status_code, payload)


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
        raise LotusAIProposalMemoUnavailableError("LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE") from exc
    return response, payload


def _proposal_memo_commentary_from_success(
    payload: dict[str, Any],
) -> ProposalMemoAiCommentaryDraft:
    execution = safe_dict(payload.get("execution"))
    if execution.get("status") != "COMPLETED":
        raise LotusAIProposalMemoUnavailableError("LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE")
    result = safe_dict(execution.get("result"))
    structured_output = safe_dict(result.get("structured_output"))
    return ProposalMemoAiCommentaryDraft(
        status=str(structured_output.get("state") or "REVIEW_REQUIRED"),
        sections=_map_sections(structured_output.get("sections")),
        lineage={
            "adapter_version": ADAPTER_VERSION,
            "workflow_pack_id": WORKFLOW_PACK_ID,
            "workflow_pack_version": WORKFLOW_PACK_VERSION,
            "workflow_surface": WORKFLOW_SURFACE,
            "workflow_run_id": extract_workflow_run_id(payload),
            "model_version": extract_model_version(result),
            "fallback_reason": None,
        },
        review_guidance=_map_string_list(structured_output.get("review_guidance")),
    )


def _raise_proposal_memo_response_error(
    status_code: int,
    payload: dict[str, Any],
) -> NoReturn:
    if status_code >= 500:
        raise LotusAIProposalMemoUnavailableError("LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE")
    raise LotusAIProposalMemoUnavailableError(
        extract_error_detail(payload, default="LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE")
    )


def build_proposal_memo_ai_unavailable_commentary(reason: str) -> ProposalMemoAiCommentaryDraft:
    return _build_core_unavailable_commentary(reason)


def _build_workflow_pack_request(
    *,
    memo_evidence: dict[str, Any],
    requested_sections: list[str],
    requested_by: str,
    reason: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return build_workflow_pack_execute_request(
        pack_id=WORKFLOW_PACK_ID,
        version=WORKFLOW_PACK_VERSION,
        workflow_surface=WORKFLOW_SURFACE,
        task_id="explain.v1",
        correlation_id=f"proposal-memo-commentary-{memo_evidence.get('memo_id')}",
        requested_by=requested_by,
        context_summary="Draft review-gated advisor-use proposal memo commentary.",
        context_payload={
            "memo_evidence": memo_evidence,
            "commentary_request": {
                "requested_sections": requested_sections,
                "requested_by": requested_by,
                "reason": reason,
            },
            "supportability": {
                "scope": "advisor_use_only",
                "review_required": True,
                "client_ready_publication": "BLOCKED",
                "unsupported_claims": [
                    "client_ready_memo_publication",
                    "suitability_or_approval_mutation",
                    "missing_evidence_inference",
                ],
            },
        },
        source_refs=_source_refs(memo_evidence),
        expected_output_label="EXPLANATION_ONLY",
        idempotency_key=idempotency_key,
    )


def _resolve_base_url() -> str:
    return cast(
        str,
        resolve_lotus_ai_base_url(
            unavailable_error_type=LotusAIProposalMemoUnavailableError,
            unavailable_message="LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE",
        ),
    )


def _resolve_timeout() -> httpx.Timeout:
    return httpx.Timeout(env_positive_float("LOTUS_AI_TIMEOUT_SECONDS", default=10.0))


def _source_refs(memo_evidence: dict[str, Any]) -> list[str]:
    refs = [
        f"lotus-advise:memo:{memo_evidence.get('memo_id')}",
        f"lotus-advise:memo_hash:{memo_evidence.get('memo_hash')}",
        f"lotus-advise:proposal:{memo_evidence.get('proposal_id')}",
    ]
    source_refs = memo_evidence.get("source_refs")
    if isinstance(source_refs, list):
        refs.extend(item for item in source_refs if isinstance(item, str))
    return refs


def _map_sections(value: Any) -> tuple[dict[str, Any], ...]:
    sections = map_review_required_sections(
        value,
        max_sections=MAX_MEMO_AI_OUTPUT_SECTIONS,
        max_section_key_length=MAX_MEMO_AI_SECTION_KEY_LENGTH,
        max_title_length=MAX_MEMO_AI_SECTION_TITLE_LENGTH,
        max_text_length=MAX_MEMO_AI_SECTION_TEXT_LENGTH,
    )
    if not sections:
        raise LotusAIProposalMemoUnavailableError("LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE")
    return sections


def _map_string_list(value: Any) -> tuple[str, ...]:
    return map_bounded_string_list(
        value,
        max_items=MAX_MEMO_AI_REVIEW_GUIDANCE_ITEMS,
        max_item_length=MAX_MEMO_AI_REVIEW_GUIDANCE_LENGTH,
    )
