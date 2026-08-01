from __future__ import annotations

import httpx
import pytest

from src.integrations.lotus_ai.policy_evidence import (
    MAX_POLICY_AI_OUTPUT_SECTIONS,
    LotusAIPolicyEvidenceUnavailableError,
    _build_workflow_pack_request,
    build_policy_ai_unavailable_evidence,
    generate_policy_evidence_summary_with_lotus_ai,
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


def _policy_evidence() -> dict[str, object]:
    return {
        "evaluation_id": "pev_ai_adapter_001",
        "evaluation_hash": "sha256:policy-ai-adapter",
        "policy_pack_id": "SG_PRIVATE_BANKING_REFERENCE",
        "source_refs": ["lotus-advise:policy-pack:SG_PRIVATE_BANKING_REFERENCE:2026.05"],
        "redaction_profile": {"raw_source_evidence_included": False},
    }


def test_workflow_pack_request_uses_redacted_policy_evidence_without_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", "tenant-private-bank-001")

    request_payload = _build_workflow_pack_request(
        policy_evidence=_policy_evidence(),
        requested_actions=["SUMMARIZE_POLICY_POSTURE"],
        requested_by="policy_checker_1",
        reason={"purpose": "compliance explanation"},
    )

    task_request = request_payload["task_request"]
    assert isinstance(task_request, dict)
    caller = task_request["caller"]
    assert isinstance(caller, dict)
    context = task_request["context"]
    assert isinstance(context, dict)
    payload = context["payload"]
    assert isinstance(payload, dict)

    assert request_payload["pack_id"] == "policy_evidence_summary.pack"
    assert request_payload["version"] == "v1"
    assert request_payload["workflow_surface"] == "policy-evidence-summary"
    assert task_request["input_mode"] == "STRUCTURED_CONTEXT"
    assert task_request["expected_output_label"] == "EXPLANATION_ONLY"
    assert caller["tenant_id"] == "tenant-private-bank-001"
    assert "prompt" not in task_request
    assert "instruction" not in task_request
    assert "prompt" not in payload
    assert "instruction" not in payload
    assert payload["policy_evidence"] == _policy_evidence()
    assert payload["supportability"]["client_ready_publication"] == "BLOCKED"
    assert payload["supportability"]["authoritative_for_policy_status"] is False
    assert "approval_or_waiver_creation" in payload["supportability"]["unsupported_claims"]
    assert context["source_refs"] == [
        "lotus-advise:policy-evaluation:pev_ai_adapter_001",
        "lotus-advise:policy-evaluation-hash:sha256:policy-ai-adapter",
        "lotus-advise:policy-pack:SG_PRIVATE_BANKING_REFERENCE",
        "lotus-advise:policy-pack:SG_PRIVATE_BANKING_REFERENCE:2026.05",
    ]


def test_generate_policy_evidence_summary_returns_review_required_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.policy_evidence.httpx.Client",
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
                                            "section_key": "POLICY_POSTURE",
                                            "title": " Policy Posture ",
                                            "text": " Policy evidence summary. ",
                                        }
                                    ],
                                    "review_guidance": [
                                        "Review against immutable policy evaluation hash."
                                    ],
                                },
                            },
                        },
                        "workflow_pack_run": {"run_id": "packrun_policy_ai_001"},
                    },
                )
            },
            **kwargs,
        ),
    )

    response = generate_policy_evidence_summary_with_lotus_ai(
        policy_evidence=_policy_evidence(),
        requested_actions=["SUMMARIZE_POLICY_POSTURE"],
        requested_by="policy_checker_1",
        reason={"purpose": "compliance explanation"},
    )

    assert response.status == "REVIEW_REQUIRED"
    assert response.sections == (
        {
            "section_key": "POLICY_POSTURE",
            "title": "Policy Posture",
            "text": "Policy evidence summary.",
            "review_state": "REVIEW_REQUIRED",
        },
    )
    assert response.lineage["workflow_run_id"] == "packrun_policy_ai_001"
    assert response.lineage["model_version"] == "lotus-ai-governed-model.v1"
    assert response.lineage["fallback_reason"] is None


def test_generate_policy_evidence_rejects_oversized_ai_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.policy_evidence.httpx.Client",
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
                                    "sections": [
                                        {
                                            "section_key": "POLICY_POSTURE",
                                            "title": "Policy Posture",
                                            "text": "x" * 4001,
                                        }
                                    ]
                                }
                            },
                        }
                    },
                )
            },
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIPolicyEvidenceUnavailableError) as exc:
        generate_policy_evidence_summary_with_lotus_ai(
            policy_evidence=_policy_evidence(),
            requested_actions=["SUMMARIZE_POLICY_POSTURE"],
            requested_by="policy_checker_1",
            reason={"purpose": "compliance explanation"},
        )

    assert str(exc.value) == "LOTUS_AI_POLICY_EVIDENCE_UNAVAILABLE"


def test_generate_policy_evidence_bounds_sections_and_review_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.policy_evidence.httpx.Client",
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
                                    "sections": [
                                        {
                                            "section_key": f"SECTION_{index}",
                                            "title": f"Section {index}",
                                            "text": "Policy evidence summary.",
                                        }
                                        for index in range(MAX_POLICY_AI_OUTPUT_SECTIONS + 2)
                                    ],
                                    "review_guidance": [
                                        "Review immutable policy hash.",
                                        "x" * 1001,
                                        "Check sign-off posture.",
                                    ],
                                }
                            },
                        }
                    },
                )
            },
            **kwargs,
        ),
    )

    response = generate_policy_evidence_summary_with_lotus_ai(
        policy_evidence=_policy_evidence(),
        requested_actions=["SUMMARIZE_POLICY_POSTURE"],
        requested_by="policy_checker_1",
        reason={"purpose": "compliance explanation"},
    )

    assert len(response.sections) == MAX_POLICY_AI_OUTPUT_SECTIONS
    assert response.sections[-1]["section_key"] == "SECTION_7"
    assert response.review_guidance == (
        "Review immutable policy hash.",
        "Check sign-off posture.",
    )


def test_generate_policy_evidence_masks_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOTUS_AI_BASE_URL", "http://lotus-ai.dev.lotus")
    monkeypatch.setattr(
        "src.integrations.lotus_ai.policy_evidence.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            raised_error=httpx.ReadTimeout("timeout"),
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIPolicyEvidenceUnavailableError) as exc:
        generate_policy_evidence_summary_with_lotus_ai(
            policy_evidence=_policy_evidence(),
            requested_actions=["SUMMARIZE_POLICY_POSTURE"],
            requested_by="policy_checker_1",
            reason={"purpose": "compliance explanation"},
        )

    assert str(exc.value) == "LOTUS_AI_POLICY_EVIDENCE_UNAVAILABLE"


def test_generate_policy_evidence_masks_non_object_provider_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.policy_evidence.httpx.Client",
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

    with pytest.raises(LotusAIPolicyEvidenceUnavailableError) as exc:
        generate_policy_evidence_summary_with_lotus_ai(
            policy_evidence=_policy_evidence(),
            requested_actions=["SUMMARIZE_POLICY_POSTURE"],
            requested_by="policy_checker_1",
            reason={"purpose": "compliance explanation"},
        )

    assert str(exc.value) == "LOTUS_AI_POLICY_EVIDENCE_UNAVAILABLE"


@pytest.mark.parametrize(
    ("status_code", "payload", "expected_reason"),
    [
        (
            200,
            {"execution": {"status": "RUNNING"}},
            "LOTUS_AI_POLICY_EVIDENCE_UNAVAILABLE",
        ),
        (
            200,
            {
                "execution": {
                    "status": "COMPLETED",
                    "result": {
                        "structured_output": {
                            "sections": [
                                "not-a-section",
                                {
                                    "section_key": "POLICY_POSTURE",
                                    "title": " ",
                                    "text": "No usable section title.",
                                },
                            ],
                            "review_guidance": "not-a-list",
                        }
                    },
                }
            },
            "LOTUS_AI_POLICY_EVIDENCE_UNAVAILABLE",
        ),
        (
            503,
            {"detail": "model unavailable"},
            "LOTUS_AI_POLICY_EVIDENCE_UNAVAILABLE",
        ),
        (
            422,
            {"detail": "policy evidence packet rejected with internal/provider text"},
            "LOTUS_AI_POLICY_EVIDENCE_REJECTED",
        ),
        (
            400,
            {},
            "LOTUS_AI_POLICY_EVIDENCE_REJECTED",
        ),
    ],
)
def test_generate_policy_evidence_fails_closed_for_unusable_ai_responses(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    payload: dict[str, object],
    expected_reason: str,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.policy_evidence.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    status_code,
                    payload,
                )
            },
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIPolicyEvidenceUnavailableError) as exc:
        generate_policy_evidence_summary_with_lotus_ai(
            policy_evidence=_policy_evidence(),
            requested_actions=["SUMMARIZE_POLICY_POSTURE"],
            requested_by="policy_checker_1",
            reason={"purpose": "compliance explanation"},
        )

    assert str(exc.value) == expected_reason


def test_generate_policy_evidence_fails_closed_when_lotus_ai_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOTUS_AI_BASE_URL", raising=False)

    with pytest.raises(LotusAIPolicyEvidenceUnavailableError) as exc:
        generate_policy_evidence_summary_with_lotus_ai(
            policy_evidence=_policy_evidence(),
            requested_actions=["SUMMARIZE_POLICY_POSTURE"],
            requested_by="policy_checker_1",
            reason={"purpose": "compliance explanation"},
        )

    assert str(exc.value) == "LOTUS_AI_POLICY_EVIDENCE_UNAVAILABLE"


def test_unavailable_policy_evidence_is_non_authoritative_and_review_guided() -> None:
    fallback = build_policy_ai_unavailable_evidence("LOTUS_AI_NOT_CONFIGURED")

    assert fallback.status == "UNAVAILABLE"
    assert fallback.sections == ()
    assert fallback.lineage["fallback_reason"] == "LOTUS_AI_NOT_CONFIGURED"
    assert fallback.lineage["workflow_run_id"] is None
    assert any("Do not infer missing approvals" in line for line in fallback.review_guidance)
