from __future__ import annotations

from typing import Any, cast

import httpx

from src.core.advisory.narrative_ai_models import ProposalNarrativeAiLineage
from src.core.advisory.narrative_ai_ports import (
    ProposalNarrativeDraftResponse,
    ProposalNarrativeDraftSection,
)
from src.core.advisory.narrative_grounding_models import ProposalNarrativeGroundingPacket
from src.core.advisory.narrative_policy_models import ProposalNarrativePolicy
from src.core.advisory.narrative_types import (
    ProposalNarrativeSectionKey,
)
from src.integrations.lotus_ai.output_safety import (
    DEFAULT_AI_OUTPUT_SECTION_LIMIT,
    DEFAULT_AI_OUTPUT_SECTION_TEXT_LENGTH,
    DEFAULT_AI_OUTPUT_SECTION_TITLE_LENGTH,
    map_review_required_sections,
)
from src.integrations.lotus_ai.runtime_config import resolve_lotus_ai_base_url
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

ADAPTER_VERSION = "proposal-narrative-lotus-ai-adapter.v1"
PROMPT_TEMPLATE_VERSION = "proposal-narrative-instructions.v1"
WORKFLOW_PACK_ID = "proposal_narrative_draft.pack"
WORKFLOW_PACK_VERSION = "v1"
WORKFLOW_SURFACE = "advisory-proposal-narrative"
MAX_NARRATIVE_AI_OUTPUT_SECTIONS = DEFAULT_AI_OUTPUT_SECTION_LIMIT
MAX_NARRATIVE_AI_SECTION_TITLE_LENGTH = DEFAULT_AI_OUTPUT_SECTION_TITLE_LENGTH
MAX_NARRATIVE_AI_SECTION_TEXT_LENGTH = DEFAULT_AI_OUTPUT_SECTION_TEXT_LENGTH


class LotusAIProposalNarrativeUnavailableError(Exception):
    pass


def generate_proposal_narrative_draft_with_lotus_ai(
    *,
    grounding_packet: ProposalNarrativeGroundingPacket,
    narrative_policy: ProposalNarrativePolicy,
    requested_sections: list[ProposalNarrativeSectionKey],
    requested_by: str | None,
) -> ProposalNarrativeDraftResponse:
    base_url = _resolve_base_url()
    try:
        request_payload = _build_workflow_pack_request(
            grounding_packet=grounding_packet,
            narrative_policy=narrative_policy,
            requested_sections=requested_sections,
            requested_by=requested_by,
        )
        with httpx.Client(timeout=_resolve_timeout()) as client:
            response = client.post(
                f"{base_url}/platform/workflow-packs/execute",
                json=request_payload,
                headers=workflow_pack_authenticated_headers(),
            )
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LotusAIProposalNarrativeUnavailableError("LOTUS_AI_NARRATIVE_UNAVAILABLE") from exc

    if response.status_code == 200:
        execution = safe_dict(payload.get("execution"))
        if execution.get("status") != "COMPLETED":
            raise LotusAIProposalNarrativeUnavailableError("LOTUS_AI_NARRATIVE_UNAVAILABLE")
        result = safe_dict(execution.get("result"))
        return ProposalNarrativeDraftResponse(
            sections=_map_sections(result.get("sections")),
            lineage=_build_lineage(
                workflow_run_id=extract_workflow_run_id(payload),
                model_version=extract_model_version(result),
                fallback_reason=None,
            ),
        )

    if response.status_code >= 500:
        raise LotusAIProposalNarrativeUnavailableError("LOTUS_AI_NARRATIVE_UNAVAILABLE")
    raise LotusAIProposalNarrativeUnavailableError(
        extract_error_detail(payload, default="LOTUS_AI_NARRATIVE_UNAVAILABLE")
    )


def build_ai_fallback_lineage(reason: str) -> ProposalNarrativeAiLineage:
    return _build_lineage(workflow_run_id=None, model_version=None, fallback_reason=reason)


def _resolve_base_url() -> str:
    return cast(
        str,
        resolve_lotus_ai_base_url(
            unavailable_error_type=LotusAIProposalNarrativeUnavailableError,
            unavailable_message="LOTUS_AI_NARRATIVE_UNAVAILABLE",
        ),
    )


def _resolve_timeout() -> httpx.Timeout:
    return httpx.Timeout(env_positive_float("LOTUS_AI_TIMEOUT_SECONDS", default=10.0))


def _build_workflow_pack_request(
    *,
    grounding_packet: ProposalNarrativeGroundingPacket,
    narrative_policy: ProposalNarrativePolicy,
    requested_sections: list[ProposalNarrativeSectionKey],
    requested_by: str | None,
) -> dict[str, object]:
    return cast(
        dict[str, object],
        build_workflow_pack_execute_request(
            pack_id=WORKFLOW_PACK_ID,
            version=WORKFLOW_PACK_VERSION,
            workflow_surface=WORKFLOW_SURFACE,
            task_id="proposal_narrative_draft.v1",
            correlation_id=f"proposal-narrative-{grounding_packet.packet_id}",
            requested_by=requested_by,
            context_summary="Draft advisor-review proposal narrative from governed evidence.",
            context_payload={
                "grounding_packet": grounding_packet.model_dump(mode="json"),
                "narrative_policy": narrative_policy.model_dump(mode="json"),
                "requested_sections": requested_sections,
                "approved_instructions": _approved_instructions(),
            },
            source_refs=[
                f"{item.ref_type}:{item.ref_id}:{item.field_path}"
                for item in grounding_packet.source_refs
            ],
            expected_output_label="ADVISOR_REVIEW_DRAFT_SECTIONS",
        ),
    )


def _approved_instructions() -> list[dict[str, str]]:
    return [
        {
            "instruction_id": "USE_GROUNDING_FACTS_ONLY",
            "text": "Use only the supplied grounding packet facts and source references.",
        },
        {
            "instruction_id": "NO_CLIENT_READY_LANGUAGE",
            "text": "Do not state that the output is approved or ready for client distribution.",
        },
        {
            "instruction_id": "PRESERVE_LIMITATIONS",
            "text": "Preserve missing evidence, disclosures, and guardrail limitations.",
        },
    ]


def _map_sections(value: Any) -> tuple[ProposalNarrativeDraftSection, ...]:
    sections: list[ProposalNarrativeDraftSection] = []
    for item in map_review_required_sections(
        value,
        max_sections=MAX_NARRATIVE_AI_OUTPUT_SECTIONS,
        max_title_length=MAX_NARRATIVE_AI_SECTION_TITLE_LENGTH,
        max_text_length=MAX_NARRATIVE_AI_SECTION_TEXT_LENGTH,
    ):
        section_key = item["section_key"]
        if section_key not in _allowed_section_keys():
            continue
        sections.append(
            ProposalNarrativeDraftSection(
                section_key=cast(ProposalNarrativeSectionKey, section_key),
                title=item["title"],
                text=item["text"],
            )
        )
    if not sections:
        raise LotusAIProposalNarrativeUnavailableError("LOTUS_AI_NARRATIVE_UNAVAILABLE")
    return tuple(sections)


def _allowed_section_keys() -> set[str]:
    return {
        "EXECUTIVE_SUMMARY",
        "RECOMMENDATION_RATIONALE",
        "RISK_AND_CONCENTRATION",
        "SUITABILITY_AND_MANDATE",
        "MATERIAL_CHANGES",
        "ALTERNATIVES_CONSIDERED",
        "APPROVALS_AND_NEXT_STEPS",
        "LIMITATIONS_AND_DISCLOSURES",
    }


def _build_lineage(
    *,
    workflow_run_id: str | None,
    model_version: str | None,
    fallback_reason: str | None,
) -> ProposalNarrativeAiLineage:
    return ProposalNarrativeAiLineage(
        requested_generation_mode="AI_ASSISTED_DRAFT",
        adapter_version=ADAPTER_VERSION,
        workflow_pack_id=WORKFLOW_PACK_ID,
        workflow_pack_version=WORKFLOW_PACK_VERSION,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        model_version=model_version,
        workflow_run_id=workflow_run_id,
        fallback_reason=fallback_reason,
    )
