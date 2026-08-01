import httpx
import pytest

from src.core.workspace.models import (
    WorkspaceAssistantEvidence,
    WorkspaceAssistantRequest,
    WorkspaceAssistantWorkflowPackRunReviewActionRequest,
    WorkspaceEvaluationImpactSummary,
    WorkspaceEvaluationSummary,
    WorkspaceResolvedContext,
)
from src.integrations.lotus_ai.rationale import (
    _MAX_ASSISTANT_OUTPUT_LENGTH,
    _MAX_FINDING_SUMMARY_LENGTH,
    _MAX_FINDINGS,
    _MAX_REVIEW_SUMMARY_ITEMS,
    _MAX_REVIEW_SUMMARY_LENGTH,
    _MAX_RUN_STATE_LENGTH,
    LotusAIRationaleUnavailableError,
    _build_source_refs,
    _build_workflow_pack_request,
    _extract_detail,
    _map_allowed_review_actions,
    _map_workflow_pack_run,
    _normalize_input_mode,
    _resolve_base_url,
    _resolve_timeout,
    apply_workspace_rationale_review_action_with_lotus_ai,
    generate_workspace_rationale_with_lotus_ai,
)
from src.integrations.lotus_core.runtime_config import RuntimeConfigurationError


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


def _build_evidence() -> WorkspaceAssistantEvidence:
    return WorkspaceAssistantEvidence(
        workspace_id="aws_001",
        input_mode="stateless",
        resolved_context=None,
        evaluation_summary=WorkspaceEvaluationSummary(
            status="READY",
            blocking_issue_count=0,
            review_issue_count=0,
            impact_summary=WorkspaceEvaluationImpactSummary(
                portfolio_value_delta_base_ccy="0.00",
                trade_count=1,
                cash_flow_count=0,
            ),
        ),
        proposal_status="READY",
    )


def _build_stateful_evidence() -> WorkspaceAssistantEvidence:
    return WorkspaceAssistantEvidence(
        workspace_id="aws_002",
        input_mode="stateful",
        resolved_context=WorkspaceResolvedContext(
            portfolio_id="pf_001",
            as_of="2026-04-21",
            portfolio_snapshot_id="ps_001",
        ),
        evaluation_summary=WorkspaceEvaluationSummary(
            status="READY",
            blocking_issue_count=0,
            review_issue_count=1,
            impact_summary=WorkspaceEvaluationImpactSummary(
                portfolio_value_delta_base_ccy="125.00",
                trade_count=2,
                cash_flow_count=1,
            ),
        ),
        proposal_status="PENDING_REVIEW",
    )


def _build_request() -> WorkspaceAssistantRequest:
    return WorkspaceAssistantRequest(
        requested_by="advisor_123",
        instruction="Summarize the advisory rationale.",
    )


def _build_review_request() -> WorkspaceAssistantWorkflowPackRunReviewActionRequest:
    return WorkspaceAssistantWorkflowPackRunReviewActionRequest(
        run_id="packrun_workspace_rationale_req_001",
        action_type="SUPERSEDE",
        reviewed_by="advisor_123",
        reason="Replacement lineage is now available.",
        replacement_run_id="packrun_workspace_rationale_req_002",
    )


def test_resolve_base_url_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOTUS_AI_BASE_URL", raising=False)

    with pytest.raises(LotusAIRationaleUnavailableError) as exc:
        _resolve_base_url()

    assert str(exc.value) == "LOTUS_AI_RATIONALE_UNAVAILABLE"


def test_resolve_timeout_uses_positive_float_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOTUS_AI_TIMEOUT_SECONDS", "7.5")
    assert _resolve_timeout().connect == 7.5

    monkeypatch.setenv("LOTUS_AI_TIMEOUT_SECONDS", "invalid")
    with pytest.raises(RuntimeConfigurationError, match="LOTUS_AI_TIMEOUT_SECONDS"):
        _resolve_timeout()


def test_generate_workspace_rationale_returns_unavailable_for_incomplete_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    200,
                    {"execution": {"status": "FAILED", "result": {"message": "ignored"}}},
                )
            },
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIRationaleUnavailableError) as exc:
        generate_workspace_rationale_with_lotus_ai(
            request=_build_request(),
            evidence=_build_evidence(),
        )

    assert str(exc.value) == "LOTUS_AI_RATIONALE_UNAVAILABLE"


def test_generate_workspace_rationale_returns_trimmed_output_and_run_posture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    evidence = _build_stateful_evidence()
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    200,
                    {
                        "execution": {
                            "status": "COMPLETED",
                            "result": {"message": "  Grounded rationale output.  "},
                        },
                        "workflow_pack_run": {
                            "run_id": "packrun_workspace_rationale_req_005",
                            "runtime_state": "COMPLETED",
                            "review_state": "REJECTED",
                            "supportability_status": "DEGRADED",
                            "workflow_authority_owner": "lotus-advise",
                            "allowed_review_actions": ["REVISE", 42],
                            "findings": ["skip-me"],
                        },
                    },
                )
            },
            **kwargs,
        ),
    )

    response = generate_workspace_rationale_with_lotus_ai(
        request=_build_request(),
        evidence=evidence,
    )

    assert response.assistant_output == "Grounded rationale output."
    assert response.workflow_pack_run is not None
    assert response.workflow_pack_run.current_summary_note == (
        "Workflow-pack run posture is available from lotus-ai."
    )
    assert response.workflow_pack_run.allowed_review_actions == ["REVISE"]
    assert response.evidence == evidence


def test_generate_workspace_rationale_rejects_blank_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    200,
                    {
                        "execution": {
                            "status": "COMPLETED",
                            "result": {"message": "   "},
                        }
                    },
                )
            },
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIRationaleUnavailableError) as exc:
        generate_workspace_rationale_with_lotus_ai(
            request=_build_request(),
            evidence=_build_evidence(),
        )

    assert str(exc.value) == "LOTUS_AI_RATIONALE_UNAVAILABLE"


def test_generate_workspace_rationale_rejects_oversized_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    200,
                    {
                        "execution": {
                            "status": "COMPLETED",
                            "result": {"message": "x" * (_MAX_ASSISTANT_OUTPUT_LENGTH + 1)},
                        }
                    },
                )
            },
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIRationaleUnavailableError) as exc:
        generate_workspace_rationale_with_lotus_ai(
            request=_build_request(),
            evidence=_build_evidence(),
        )

    assert str(exc.value) == "LOTUS_AI_RATIONALE_UNAVAILABLE"


def test_generate_workspace_rationale_propagates_non_server_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    409,
                    {"detail": "Replacement run must belong to the same workflow-pack family."},
                )
            },
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIRationaleUnavailableError) as exc:
        generate_workspace_rationale_with_lotus_ai(
            request=_build_request(),
            evidence=_build_evidence(),
        )

    assert str(exc.value) == "Replacement run must belong to the same workflow-pack family."


def test_generate_workspace_rationale_masks_server_and_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)

    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                f"{base_url}/platform/workflow-packs/execute": _FakeResponse(
                    503,
                    {"detail": "upstream unavailable"},
                )
            },
            **kwargs,
        ),
    )
    with pytest.raises(LotusAIRationaleUnavailableError) as server_exc:
        generate_workspace_rationale_with_lotus_ai(
            request=_build_request(),
            evidence=_build_evidence(),
        )
    assert str(server_exc.value) == "LOTUS_AI_RATIONALE_UNAVAILABLE"

    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            raised_error=httpx.ConnectError("boom"),
            **kwargs,
        ),
    )
    with pytest.raises(LotusAIRationaleUnavailableError) as transport_exc:
        generate_workspace_rationale_with_lotus_ai(
            request=_build_request(),
            evidence=_build_evidence(),
        )
    assert str(transport_exc.value) == "LOTUS_AI_RATIONALE_UNAVAILABLE"


def test_generate_workspace_rationale_masks_non_object_provider_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
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

    with pytest.raises(LotusAIRationaleUnavailableError) as exc:
        generate_workspace_rationale_with_lotus_ai(
            request=_build_request(),
            evidence=_build_evidence(),
        )

    assert str(exc.value) == "LOTUS_AI_RATIONALE_UNAVAILABLE"


def test_review_action_requires_returned_run_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    review_url = (
        f"{base_url}/platform/workflow-packs/runs/"
        "packrun_workspace_rationale_req_001/review-actions"
    )
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={review_url: _FakeResponse(200, {"summary": ["missing run"]})},
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIRationaleUnavailableError) as exc:
        apply_workspace_rationale_review_action_with_lotus_ai(_build_review_request())

    assert str(exc.value) == "LOTUS_AI_RATIONALE_UNAVAILABLE"


def test_review_action_masks_server_failures_and_propagates_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    review_url = (
        f"{base_url}/platform/workflow-packs/runs/"
        "packrun_workspace_rationale_req_001/review-actions"
    )
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)

    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={review_url: _FakeResponse(503, {"detail": "upstream unavailable"})},
            **kwargs,
        ),
    )
    with pytest.raises(LotusAIRationaleUnavailableError) as server_exc:
        apply_workspace_rationale_review_action_with_lotus_ai(_build_review_request())
    assert str(server_exc.value) == "LOTUS_AI_RATIONALE_UNAVAILABLE"

    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                review_url: _FakeResponse(
                    409,
                    {"detail": "Replacement run must belong to the same workflow-pack family."},
                )
            },
            **kwargs,
        ),
    )
    with pytest.raises(LotusAIRationaleUnavailableError) as conflict_exc:
        apply_workspace_rationale_review_action_with_lotus_ai(_build_review_request())
    assert str(conflict_exc.value) == (
        "Replacement run must belong to the same workflow-pack family."
    )


def test_review_action_masks_transport_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOTUS_AI_BASE_URL", "http://lotus-ai.dev.lotus")
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            raised_error=httpx.ReadTimeout("boom"),
            **kwargs,
        ),
    )

    with pytest.raises(LotusAIRationaleUnavailableError) as exc:
        apply_workspace_rationale_review_action_with_lotus_ai(_build_review_request())

    assert str(exc.value) == "LOTUS_AI_RATIONALE_UNAVAILABLE"


def test_review_action_returns_trimmed_summary_and_replacement_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    review_url = (
        f"{base_url}/platform/workflow-packs/runs/"
        "packrun_workspace_rationale_req_001/review-actions"
    )
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                review_url: _FakeResponse(
                    200,
                    {
                        "run": {
                            "run_id": "packrun_workspace_rationale_req_001",
                            "runtime_state": "COMPLETED",
                            "review_state": "SUPERSEDED",
                            "supportability_status": "HISTORICAL",
                            "workflow_authority_owner": "lotus-advise",
                            "replacement_run_id": "packrun_workspace_rationale_req_002",
                        },
                        "summary": ["  lineage recorded  ", "", 7],
                    },
                )
            },
            **kwargs,
        ),
    )

    response = apply_workspace_rationale_review_action_with_lotus_ai(_build_review_request())

    assert response.summary == ["lineage recorded"]
    assert response.workflow_pack_run.replacement_run_id == "packrun_workspace_rationale_req_002"
    assert response.workflow_pack_run.superseded is True


def test_review_action_bounds_returned_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    base_url = "http://lotus-ai.dev.lotus"
    review_url = (
        f"{base_url}/platform/workflow-packs/runs/"
        "packrun_workspace_rationale_req_001/review-actions"
    )
    monkeypatch.setenv("LOTUS_AI_BASE_URL", base_url)
    monkeypatch.setattr(
        "src.integrations.lotus_ai.rationale.httpx.Client",
        lambda *args, **kwargs: _FakeClient(
            *args,
            responses={
                review_url: _FakeResponse(
                    200,
                    {
                        "run": {
                            "run_id": "packrun_workspace_rationale_req_001",
                            "runtime_state": "COMPLETED",
                            "review_state": "ACCEPTED",
                            "supportability_status": "READY",
                            "workflow_authority_owner": "lotus-advise",
                        },
                        "summary": [
                            "  Summary accepted.  ",
                            "",
                            "x" * (_MAX_REVIEW_SUMMARY_LENGTH + 1),
                            *[
                                f"Additional note {index}."
                                for index in range(_MAX_REVIEW_SUMMARY_ITEMS + 2)
                            ],
                        ],
                    },
                )
            },
            **kwargs,
        ),
    )

    response = apply_workspace_rationale_review_action_with_lotus_ai(_build_review_request())

    assert response.summary[0] == "Summary accepted."
    assert len(response.summary) == _MAX_REVIEW_SUMMARY_ITEMS
    assert all(len(item) <= _MAX_REVIEW_SUMMARY_LENGTH for item in response.summary)


def test_map_workflow_pack_run_sets_summary_notes_for_key_states() -> None:
    awaiting_review = _map_workflow_pack_run(
        {
            "run_id": "packrun_workspace_rationale_req_001",
            "runtime_state": "COMPLETED",
            "review_state": "AWAITING_REVIEW",
            "supportability_status": "ACTION_REQUIRED",
            "workflow_authority_owner": "lotus-advise",
            "allowed_review_actions": ["ACCEPT"],
            "findings": [{"finding_id": "f1", "severity": "INFO", "summary": "ready"}],
        }
    )
    assert awaiting_review is not None
    assert awaiting_review.current_summary_note == (
        "Run completed but still requires bounded human review before downstream use."
    )

    ready = _map_workflow_pack_run(
        {
            "run_id": "packrun_workspace_rationale_req_002",
            "runtime_state": "COMPLETED",
            "review_state": "ACCEPTED",
            "supportability_status": "READY",
            "workflow_authority_owner": "lotus-advise",
            "allowed_review_actions": [],
            "findings": [{"finding_id": "bad", "severity": "", "summary": "ignored"}],
        }
    )
    assert ready is not None
    assert ready.current_summary_note == "Run is ready for bounded downstream use."
    assert ready.findings == []

    historical = _map_workflow_pack_run(
        {
            "run_id": "packrun_workspace_rationale_req_003",
            "runtime_state": "COMPLETED",
            "review_state": "SUPERSEDED",
            "supportability_status": "HISTORICAL",
            "workflow_authority_owner": "lotus-advise",
            "replacement_run_id": "packrun_workspace_rationale_req_004",
        }
    )
    assert historical is not None
    assert historical.current_summary_note == "Run is historical due to replacement lineage."
    assert historical.replacement_run_id == "packrun_workspace_rationale_req_004"


def test_map_workflow_pack_run_bounds_actions_findings_and_identifiers() -> None:
    run = _map_workflow_pack_run(
        {
            "run_id": "  packrun_workspace_rationale_req_001  ",
            "runtime_state": " COMPLETED ",
            "review_state": " ACCEPTED ",
            "supportability_status": " READY ",
            "workflow_authority_owner": " lotus-advise ",
            "replacement_run_id": "x" * 161,
            "allowed_review_actions": [
                "REVISE",
                "APPROVE_ORDER",
                "REVISE",
                "ACCEPT",
                "",
            ],
            "findings": [
                {
                    "finding_id": f"finding_{index}",
                    "severity": "INFO",
                    "summary": "x" * (_MAX_FINDING_SUMMARY_LENGTH + 1)
                    if index == 0
                    else f"Finding {index}.",
                }
                for index in range(_MAX_FINDINGS + 3)
            ],
        }
    )

    assert run is not None
    assert run.run_id == "packrun_workspace_rationale_req_001"
    assert run.runtime_state == "COMPLETED"
    assert run.workflow_authority_owner == "lotus-advise"
    assert run.allowed_review_actions == ["REVISE", "ACCEPT"]
    assert run.replacement_run_id is None
    assert len(run.findings) == _MAX_FINDINGS
    assert run.findings[0].finding_id == "finding_1"
    assert all(len(finding.summary) <= _MAX_FINDING_SUMMARY_LENGTH for finding in run.findings)


def test_map_allowed_review_actions_preserves_bounded_allowlisted_order() -> None:
    assert _map_allowed_review_actions(
        [
            " REVISE ",
            "APPROVE_ORDER",
            "REVISE",
            "ACCEPT",
            "",
            "SUPERSEDE",
            "ABANDON",
            "REJECT",
            "x" * (_MAX_RUN_STATE_LENGTH + 1),
            42,
        ]
    ) == ["REVISE", "ACCEPT", "SUPERSEDE", "ABANDON", "REJECT"]

    assert _map_allowed_review_actions({"not": "a-list"}) == []


def test_map_workflow_pack_run_requires_identity_and_list_findings() -> None:
    assert _map_workflow_pack_run({"run_id": " "}) is None

    run = _map_workflow_pack_run(
        {
            "run_id": "packrun_workspace_rationale_req_001",
            "findings": {"finding_id": "not-a-list"},
        }
    )

    assert run is not None
    assert run.findings == []


def test_workflow_pack_request_includes_resolved_context_and_portfolio_source_ref(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", "tenant-private-bank-001")

    request_payload = _build_workflow_pack_request(
        request=_build_request(),
        evidence=_build_stateful_evidence(),
    )

    task_request = request_payload["task_request"]
    assert task_request["caller"]["tenant_id"] == "tenant-private-bank-001"
    task_context = request_payload["task_request"]["context"]
    assert task_context["payload"]["resolved_context"]["portfolio_id"] == "pf_001"
    assert "lotus-advise:portfolio:pf_001" in task_context["source_refs"]


def test_workflow_pack_request_uses_configured_tenant_id(monkeypatch) -> None:
    monkeypatch.setenv("LOTUS_ADVISE_TENANT_ID", "tenant-private-bank-001")

    request_payload = _build_workflow_pack_request(
        request=_build_request(),
        evidence=_build_stateful_evidence(),
    )

    assert request_payload["task_request"]["caller"]["tenant_id"] == "tenant-private-bank-001"


def test_build_source_refs_ignores_missing_portfolio_id() -> None:
    evidence = _build_stateful_evidence().model_copy(
        update={
            "resolved_context": WorkspaceResolvedContext(
                portfolio_id="",
                as_of="2026-04-21",
            )
        }
    )

    refs = _build_source_refs(evidence=evidence)

    assert refs == [
        "lotus-advise:workspace:aws_002",
        "lotus-advise:proposal-status:PENDING_REVIEW",
        "lotus-advise:proposal-decision-summary",
    ]


def test_extract_detail_and_normalize_input_mode_cover_fallback_paths() -> None:
    class _EnumLike:
        value = "stateful"

    class _ObjectLike:
        def __str__(self) -> str:
            return "object-mode"

    assert _extract_detail({"detail": "  bounded conflict  "}) == "bounded conflict"
    assert _extract_detail({"detail": {"message": "ignored"}}) == "LOTUS_AI_RATIONALE_UNAVAILABLE"
    assert _normalize_input_mode("stateless") == "stateless"
    assert _normalize_input_mode(_EnumLike()) == "stateful"
    assert _normalize_input_mode(_ObjectLike()) == "object-mode"
