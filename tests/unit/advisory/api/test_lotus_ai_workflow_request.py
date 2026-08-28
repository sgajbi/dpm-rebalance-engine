from __future__ import annotations

import pytest

from src.integrations.lotus_ai.runtime_config import LotusAITenantIdentityError
from src.integrations.lotus_ai.workflow_request import (
    build_workflow_pack_execute_request,
    workflow_pack_authenticated_headers,
)


def test_build_workflow_pack_execute_request_applies_governed_caller_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOTUS_AI_WORKFLOW_PACK_ENVIRONMENT", "UAT")
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", "tenant-private-bank-001")

    request = build_workflow_pack_execute_request(
        pack_id="advisory_copilot_proposal_explanation.pack",
        version="v1",
        workflow_surface="advisory-copilot-proposal-explanation",
        task_id="explain.v1",
        correlation_id="correlation-001",
        requested_by="advisor_001",
        context_summary="Draft advisor-use explanation from governed evidence.",
        context_payload={"evidence_packet_id": "copilot_packet_pb_sg_001"},
        source_refs=["lotus-advise:proposal:proposal_001"],
        expected_output_label="EXPLANATION_ONLY",
    )

    task_request = request["task_request"]
    assert isinstance(task_request, dict)
    caller = task_request["caller"]
    assert isinstance(caller, dict)
    context = task_request["context"]
    assert isinstance(context, dict)

    assert request["environment"] == "UAT"
    assert request["caller_identity_class"] == "INTERNAL_SERVICE"
    assert "idempotency_key" not in request
    assert task_request["input_mode"] == "STRUCTURED_CONTEXT"
    assert caller == {
        "caller_app": "lotus-advise",
        "correlation_id": "correlation-001",
        "requested_by": "advisor_001",
        "tenant_id": "tenant-private-bank-001",
    }
    assert context == {
        "summary": "Draft advisor-use explanation from governed evidence.",
        "payload": {"evidence_packet_id": "copilot_packet_pb_sg_001"},
        "source_refs": ["lotus-advise:proposal:proposal_001"],
    }


def test_build_workflow_pack_execute_request_forwards_stable_idempotency_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", "tenant-private-bank-001")

    request = build_workflow_pack_execute_request(
        pack_id="proposal_memo_commentary.pack",
        version="v1",
        workflow_surface="advisor-proposal-memo-commentary",
        task_id="explain.v1",
        correlation_id="proposal-memo-commentary-memo-001",
        requested_by="advisor_001",
        context_summary="Draft advisor-use commentary.",
        context_payload={"memo_id": "memo-001"},
        source_refs=["lotus-advise:memo:memo-001"],
        expected_output_label="EXPLANATION_ONLY",
        idempotency_key="memo_ai_0123456789abcdef01234567",
    )

    assert request["idempotency_key"] == "memo_ai_0123456789abcdef01234567"


def test_workflow_pack_authenticated_headers_bind_declared_lotus_advise_caller() -> None:
    assert workflow_pack_authenticated_headers() == {"X-Caller-App": "lotus-advise"}


def test_build_workflow_pack_execute_request_requires_trusted_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOTUS_AI_WORKFLOW_PACK_ENVIRONMENT", raising=False)
    monkeypatch.delenv("LOTUS_ADVISE_TENANT_ID", raising=False)

    with pytest.raises(LotusAITenantIdentityError, match="LOTUS_AI_TENANT_ID_UNAVAILABLE"):
        build_workflow_pack_execute_request(
            pack_id="proposal_narrative_draft.pack",
            version="v1",
            workflow_surface="advisory-proposal-narrative",
            task_id="proposal_narrative_draft.v1",
            correlation_id="proposal-narrative-pgp_001",
            requested_by=None,
            context_summary="Draft advisor-review proposal narrative.",
            context_payload={"packet_id": "pgp_001"},
            source_refs=[],
            expected_output_label="ADVISOR_REVIEW_DRAFT_SECTIONS",
        )
