from __future__ import annotations

import httpx
import pytest

from src.integrations.lotus_ai.proposal_memo import (
    MAX_MEMO_AI_OUTPUT_SECTIONS,
    LotusAIProposalMemoUnavailableError,
    _build_workflow_pack_request,
    build_proposal_memo_ai_unavailable_commentary,
    generate_proposal_memo_commentary_with_lotus_ai,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _FakeClient:
    def __init__(
        self,
        *args,
        responses: dict[str, _FakeResponse] | None = None,
        raised_error: Exception | None = None,
        **kwargs,
    ) -> None:
        self._responses = responses or {}
        self._raised_error = raised_error

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    def post(
        self,
        url: str,
        json: dict[str, object],
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        if self._raised_error is not None:
            raise self._raised_error
        if headers != {"X-Caller-App": "lotus-advise"}:
            raise AssertionError(f"unexpected authenticated caller headers: {headers}")
        response = self._responses.get(url)
        if response is None:
            raise AssertionError(f"unexpected request url: {url}")
        return response


def _memo_evidence() -> dict[str, object]:
    return {
        "memo_id": "memo_ai_adapter_001",
        "memo_hash": "sha256:memo-ai-adapter",
        "proposal_id": "proposal_ai_adapter_001",
        "source_refs": ["lotus-advise:proposal-version:proposal_ai_adapter_001:1"],
    }


def test_workflow_pack_request_uses_bounded_memo_evidence_without_raw_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", "tenant-private-bank-001")

    request_payload = _build_workflow_pack_request(
        memo_evidence=_memo_evidence(),
        requested_sections=["EXECUTIVE_SUMMARY"],
        requested_by="advisor_123",
        reason={"purpose": "advisor-review"},
        idempotency_key="memo_ai_0123456789abcdef01234567",
    )

    task_request = request_payload["task_request"]
    assert isinstance(task_request, dict)
    caller = task_request["caller"]
    assert isinstance(caller, dict)
    context = task_request["context"]
    assert isinstance(context, dict)
    payload = context["payload"]
    assert isinstance(payload, dict)

    assert request_payload["pack_id"] == "proposal_memo_commentary.pack"
    assert request_payload["version"] == "v1"
    assert request_payload["workflow_surface"] == "advisor-proposal-memo-commentary"
    assert request_payload["idempotency_key"] == "memo_ai_0123456789abcdef01234567"
    assert task_request["input_mode"] == "STRUCTURED_CONTEXT"
    assert task_request["expected_output_label"] == "EXPLANATION_ONLY"
    assert caller["tenant_id"] == "tenant-private-bank-001"
    assert "prompt" not in task_request
    assert "instruction" not in task_request
    assert "prompt" not in payload
    assert "instruction" not in payload
    assert payload["memo_evidence"] == _memo_evidence()
    assert payload["supportability"]["client_ready_publication"] == "BLOCKED"
    assert context["source_refs"] == [
        "lotus-advise:memo:memo_ai_adapter_001",
        "lotus-advise:memo_hash:sha256:memo-ai-adapter",
        "lotus-advise:proposal:proposal_ai_adapter_001",
        "lotus-advise:proposal-version:proposal_ai_adapter_001:1",
    ]


def test_generate_proposal_memo_commentary_returns_review_required_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.proposal_memo.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    200,
                    {
                        "execution": {
                            "status": "COMPLETED",
                            "result": {
                                "model_version": "lotus-ai-governed-model.v1",
                                "structured_output": {
                                    "state": "REVIEW_REQUIRED",
                                    "sections": [
                                        {
                                            "section_key": "EXECUTIVE_SUMMARY",
                                            "title": " Executive Summary ",
                                            "text": " Advisor-use memo commentary. ",
                                        }
                                    ],
                                    "review_guidance": [
                                        "Review against persisted memo hash before advisor use."
                                    ],
                                },
                            },
                        },
                        "workflow_pack_run": {"run_id": "packrun_memo_commentary_001"},
                    },
                )
            },
            **kwargs,
        ),
    )

    response = generate_proposal_memo_commentary_with_lotus_ai(
        memo_evidence=_memo_evidence(),
        requested_sections=["EXECUTIVE_SUMMARY"],
        requested_by="advisor_123",
        reason={"purpose": "advisor-review"},
    )

    assert response.status == "REVIEW_REQUIRED"
    assert response.sections == (
        {
            "section_key": "EXECUTIVE_SUMMARY",
            "title": "Executive Summary",
            "text": "Advisor-use memo commentary.",
            "review_state": "REVIEW_REQUIRED",
        },
    )
    assert response.lineage["workflow_run_id"] == "packrun_memo_commentary_001"
    assert response.lineage["model_version"] == "lotus-ai-governed-model.v1"
    assert response.lineage["fallback_reason"] is None
    assert response.review_guidance == ("Review against persisted memo hash before advisor use.",)


def test_generate_proposal_memo_commentary_rejects_oversized_output_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.proposal_memo.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    200,
                    {
                        "execution": {
                            "status": "COMPLETED",
                            "result": {
                                "structured_output": {
                                    "state": "REVIEW_REQUIRED",
                                    "sections": [
                                        {
                                            "section_key": "EXECUTIVE_SUMMARY",
                                            "title": "Executive Summary",
                                            "text": "x" * 4001,
                                        }
                                    ],
                                },
                            },
                        }
                    },
                )
            },
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIProposalMemoUnavailableError) as exc:
        generate_proposal_memo_commentary_with_lotus_ai(
            memo_evidence=_memo_evidence(),
            requested_sections=["EXECUTIVE_SUMMARY"],
            requested_by="advisor_123",
            reason={"purpose": "advisor-review"},
        )

    assert str(exc.value) == "LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE"


def test_generate_proposal_memo_commentary_bounds_sections_and_review_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.proposal_memo.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    200,
                    {
                        "execution": {
                            "status": "COMPLETED",
                            "result": {
                                "structured_output": {
                                    "state": "REVIEW_REQUIRED",
                                    "sections": [
                                        {
                                            "section_key": f"SECTION_{index}",
                                            "title": f"Section {index}",
                                            "text": "Advisor-use memo commentary.",
                                        }
                                        for index in range(MAX_MEMO_AI_OUTPUT_SECTIONS + 2)
                                    ],
                                    "review_guidance": [
                                        "Review against persisted memo hash.",
                                        "x" * 1001,
                                        "Check advisor-use posture.",
                                    ],
                                },
                            },
                        },
                    },
                )
            },
            **kwargs,
        ),
    )

    response = generate_proposal_memo_commentary_with_lotus_ai(
        memo_evidence=_memo_evidence(),
        requested_sections=["EXECUTIVE_SUMMARY"],
        requested_by="advisor_123",
        reason={"purpose": "advisor-review"},
    )

    assert len(response.sections) == MAX_MEMO_AI_OUTPUT_SECTIONS
    assert response.sections[-1]["section_key"] == "SECTION_7"
    assert response.review_guidance == (
        "Review against persisted memo hash.",
        "Check advisor-use posture.",
    )


def test_generate_proposal_memo_commentary_masks_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOTUS_AI_BASE_URL", "http://lotus-ai.dev.lotus")
    monkeypatch.setattr(
        "src.integrations.lotus_ai.proposal_memo.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            raised_error=httpx.ReadTimeout("timeout"),
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIProposalMemoUnavailableError) as exc:
        generate_proposal_memo_commentary_with_lotus_ai(
            memo_evidence=_memo_evidence(),
            requested_sections=["EXECUTIVE_SUMMARY"],
            requested_by="advisor_123",
            reason={"purpose": "advisor-review"},
        )

    assert str(exc.value) == "LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE"


def test_generate_proposal_memo_commentary_rejects_non_completed_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.proposal_memo.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    200,
                    {"execution": {"status": "ACTION_REQUIRED", "result": {}}},
                )
            },
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIProposalMemoUnavailableError) as exc:
        generate_proposal_memo_commentary_with_lotus_ai(
            memo_evidence=_memo_evidence(),
            requested_sections=["EXECUTIVE_SUMMARY"],
            requested_by="advisor_123",
            reason={"purpose": "advisor-review"},
        )

    assert str(exc.value) == "LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE"


def test_generate_proposal_memo_commentary_masks_non_object_provider_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.proposal_memo.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    200,
                    ["not", "a", "workflow-pack-envelope"],
                )
            },
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIProposalMemoUnavailableError) as exc:
        generate_proposal_memo_commentary_with_lotus_ai(
            memo_evidence=_memo_evidence(),
            requested_sections=["EXECUTIVE_SUMMARY"],
            requested_by="advisor_123",
            reason={"purpose": "advisor-review"},
        )

    assert str(exc.value) == "LOTUS_AI_MEMO_COMMENTARY_UNAVAILABLE"


def test_generate_proposal_memo_commentary_preserves_client_error_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.proposal_memo.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    422,
                    {"detail": "LOTUS_AI_MEMO_COMMENTARY_CALLER_NOT_ALLOWED"},
                )
            },
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIProposalMemoUnavailableError) as exc:
        generate_proposal_memo_commentary_with_lotus_ai(
            memo_evidence=_memo_evidence(),
            requested_sections=["EXECUTIVE_SUMMARY"],
            requested_by="advisor_123",
            reason={"purpose": "advisor-review"},
        )

    assert str(exc.value) == "LOTUS_AI_MEMO_COMMENTARY_CALLER_NOT_ALLOWED"


def test_unavailable_commentary_is_non_authoritative_and_review_guided() -> None:
    fallback = build_proposal_memo_ai_unavailable_commentary("LOTUS_AI_NOT_CONFIGURED")

    assert fallback.status == "UNAVAILABLE"
    assert fallback.sections == ()
    assert fallback.lineage["fallback_reason"] == "LOTUS_AI_NOT_CONFIGURED"
    assert fallback.lineage["workflow_run_id"] is None
    assert any("Do not infer missing suitability" in line for line in fallback.review_guidance)
