from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

ADAPTER_VERSION = "proposal-memo-commentary-lotus-ai-adapter.v1"
WORKFLOW_PACK_ID = "proposal_memo_commentary.pack"
WORKFLOW_PACK_VERSION = "v1"
WORKFLOW_SURFACE = "advisor-proposal-memo-commentary"


class ProposalMemoAiCommentaryUnavailableError(Exception):
    authority = "lotus_ai"
    degraded_reason = "LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE"


@dataclass(frozen=True)
class ProposalMemoAiCommentaryDraft:
    status: str
    sections: tuple[dict[str, Any], ...]
    lineage: dict[str, Any]
    review_guidance: tuple[str, ...]


ProposalMemoAiCommentaryGenerator: TypeAlias = Callable[
    [dict[str, Any], list[str], str, dict[str, Any], str | None],
    ProposalMemoAiCommentaryDraft,
]

_commentary_generator: ProposalMemoAiCommentaryGenerator | None = None


def configure_proposal_memo_ai_commentary_generator(
    generator: ProposalMemoAiCommentaryGenerator | None,
) -> None:
    global _commentary_generator
    _commentary_generator = generator


def generate_proposal_memo_ai_commentary(
    *,
    memo_evidence: dict[str, Any],
    requested_sections: list[str],
    requested_by: str,
    reason: dict[str, Any],
    idempotency_key: str | None = None,
) -> ProposalMemoAiCommentaryDraft:
    if _commentary_generator is None:
        raise ProposalMemoAiCommentaryUnavailableError("LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE")
    return _commentary_generator(
        memo_evidence,
        requested_sections,
        requested_by,
        reason,
        idempotency_key,
    )


def build_proposal_memo_ai_unavailable_commentary(
    reason: str,
) -> ProposalMemoAiCommentaryDraft:
    return ProposalMemoAiCommentaryDraft(
        status="UNAVAILABLE",
        sections=(),
        lineage={
            "adapter_version": ADAPTER_VERSION,
            "workflow_pack_id": WORKFLOW_PACK_ID,
            "workflow_pack_version": WORKFLOW_PACK_VERSION,
            "workflow_surface": WORKFLOW_SURFACE,
            "workflow_run_id": None,
            "model_version": None,
            "fallback_reason": reason,
        },
        review_guidance=(
            "AI memo commentary is unavailable; use persisted memo evidence "
            "and deterministic sections only.",
            "Do not infer missing suitability, eligibility, fee, tax, conflict, "
            "or approval evidence.",
        ),
    )


__all__ = [
    "ProposalMemoAiCommentaryDraft",
    "ProposalMemoAiCommentaryGenerator",
    "ProposalMemoAiCommentaryUnavailableError",
    "build_proposal_memo_ai_unavailable_commentary",
    "configure_proposal_memo_ai_commentary_generator",
    "generate_proposal_memo_ai_commentary",
]
