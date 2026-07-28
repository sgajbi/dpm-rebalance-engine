from fastapi.testclient import TestClient

from src.api.main import app
from src.core.common.idempotency import MAX_IDEMPOTENCY_KEY_LENGTH


def _assert_property_has_docs(schema: dict, property_name: str) -> None:
    prop = schema["properties"][property_name]
    assert "description" in prop and prop["description"]
    assert ("example" in prop) or ("examples" in prop)


def test_openapi_uses_business_facing_integration_boundary_language():
    openapi_text = repr(app.openapi()).lower()

    assert " seam" not in openapi_text
    assert "seam " not in openapi_text


def test_tactical_house_view_openapi_uses_private_banking_portfolio_management_language():
    operation = app.openapi()["paths"]["/advisory/tactical-house-view/cohorts/evaluate"]["post"]
    description = operation["description"]

    assert "DPM workflows" not in description
    assert "discretionary portfolio-management workflows" in description


def test_advisor_cockpit_openapi_exposes_business_owner_role_label():
    schemas = app.openapi()["components"]["schemas"]
    action_schema = schemas["AdvisoryActionItem"]
    owner_role = action_schema["properties"]["owner_role"]
    owner_role_label = action_schema["properties"]["owner_role_label"]

    assert "PORTFOLIO_MANAGER" in repr(schemas)
    assert "Use owner_role_label for business-facing display." in owner_role["description"]
    assert "Business-facing owner label" in owner_role_label["description"]


def test_idempotency_header_openapi_contract_is_bounded_and_business_clear():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    idempotency_headers = []
    for methods in openapi["paths"].values():
        for operation in methods.values():
            if not isinstance(operation, dict):
                continue
            idempotency_headers.extend(
                parameter
                for parameter in operation.get("parameters", [])
                if parameter.get("name") == "Idempotency-Key" and parameter.get("in") == "header"
            )

    assert idempotency_headers
    for header in idempotency_headers:
        assert header["schema"]["maxLength"] == MAX_IDEMPOTENCY_KEY_LENGTH
        assert "replay-safe client request identifiers" in header["description"]
        assert "visible characters" in header["description"]
        assert "control characters" in header["description"]


def test_lifecycle_async_and_support_schemas_have_descriptions_and_examples():
    openapi = app.openapi()
    schemas = openapi["components"]["schemas"]

    create_request_schema = schemas["ProposalCreateRequest"]
    _assert_property_has_docs(create_request_schema, "input_mode")
    _assert_property_has_docs(create_request_schema, "simulate_request")
    _assert_property_has_docs(create_request_schema, "stateless_input")
    _assert_property_has_docs(create_request_schema, "stateful_input")

    proposal_summary_schema = schemas["ProposalSummary"]
    _assert_property_has_docs(proposal_summary_schema, "lifecycle_origin")
    _assert_property_has_docs(proposal_summary_schema, "source_workspace_id")

    version_request_schema = schemas["ProposalVersionRequest"]
    _assert_property_has_docs(version_request_schema, "input_mode")
    _assert_property_has_docs(version_request_schema, "expected_current_version_no")
    _assert_property_has_docs(version_request_schema, "simulate_request")
    _assert_property_has_docs(version_request_schema, "stateless_input")
    _assert_property_has_docs(version_request_schema, "stateful_input")

    lineage_schema = schemas["ProposalLineageResponse"]
    _assert_property_has_docs(lineage_schema, "version_count")
    _assert_property_has_docs(lineage_schema, "latest_version_no")
    _assert_property_has_docs(lineage_schema, "latest_version_created_at")
    _assert_property_has_docs(lineage_schema, "lineage_complete")
    _assert_property_has_docs(lineage_schema, "missing_version_numbers")

    timeline_schema = schemas["ProposalWorkflowTimelineResponse"]
    _assert_property_has_docs(timeline_schema, "proposal")
    _assert_property_has_docs(timeline_schema, "event_count")
    _assert_property_has_docs(timeline_schema, "latest_event")

    approvals_schema = schemas["ProposalApprovalsResponse"]
    _assert_property_has_docs(approvals_schema, "proposal")
    _assert_property_has_docs(approvals_schema, "approval_count")
    _assert_property_has_docs(approvals_schema, "latest_approval_at")

    report_request_schema = schemas["ProposalReportRequest"]
    _assert_property_has_docs(report_request_schema, "report_type")
    _assert_property_has_docs(report_request_schema, "requested_by")
    _assert_property_has_docs(report_request_schema, "related_version_no")
    _assert_property_has_docs(report_request_schema, "include_execution_summary")
    _assert_property_has_docs(report_request_schema, "include_reviewed_narrative")

    report_response_schema = schemas["ProposalReportResponse"]
    _assert_property_has_docs(report_response_schema, "proposal")
    _assert_property_has_docs(report_response_schema, "report_request_id")
    _assert_property_has_docs(report_response_schema, "report_service")
    _assert_property_has_docs(report_response_schema, "report_reference_id")
    _assert_property_has_docs(report_response_schema, "explanation")

    execution_handoff_schema = schemas["ProposalExecutionHandoffRequest"]
    _assert_property_has_docs(execution_handoff_schema, "actor_id")
    _assert_property_has_docs(execution_handoff_schema, "execution_provider")
    _assert_property_has_docs(execution_handoff_schema, "expected_state")
    _assert_property_has_docs(execution_handoff_schema, "notes")

    execution_update_schema = schemas["ProposalExecutionUpdateRequest"]
    _assert_property_has_docs(execution_update_schema, "update_id")
    _assert_property_has_docs(execution_update_schema, "execution_request_id")
    _assert_property_has_docs(execution_update_schema, "execution_provider")
    _assert_property_has_docs(execution_update_schema, "update_status")
    _assert_property_has_docs(execution_update_schema, "external_execution_id")
    _assert_property_has_docs(execution_update_schema, "occurred_at")
    _assert_property_has_docs(execution_update_schema, "details")

    execution_status_schema = schemas["ProposalExecutionStatusResponse"]
    _assert_property_has_docs(execution_status_schema, "handoff_status")
    _assert_property_has_docs(execution_status_schema, "execution_request_id")
    _assert_property_has_docs(execution_status_schema, "execution_provider")
    _assert_property_has_docs(execution_status_schema, "external_execution_id")
    _assert_property_has_docs(execution_status_schema, "execution_ownership")
    _assert_property_has_docs(execution_status_schema, "explanation")

    execution_handoff_response_schema = schemas["ProposalExecutionHandoffResponse"]
    _assert_property_has_docs(execution_handoff_response_schema, "execution_ownership")

    delivery_execution_schema = schemas["ProposalDeliveryExecutionSummary"]
    _assert_property_has_docs(delivery_execution_schema, "execution_ownership")

    idempotency_schema = schemas["ProposalIdempotencyLookupResponse"]
    _assert_property_has_docs(idempotency_schema, "idempotency_key")
    _assert_property_has_docs(idempotency_schema, "request_hash")
    _assert_property_has_docs(idempotency_schema, "proposal_id")
    _assert_property_has_docs(idempotency_schema, "proposal_version_no")
    _assert_property_has_docs(idempotency_schema, "created_at")

    async_accepted_schema = schemas["ProposalAsyncAcceptedResponse"]
    _assert_property_has_docs(async_accepted_schema, "operation_id")
    _assert_property_has_docs(async_accepted_schema, "operation_type")
    _assert_property_has_docs(async_accepted_schema, "status")
    _assert_property_has_docs(async_accepted_schema, "correlation_id")
    _assert_property_has_docs(async_accepted_schema, "created_at")
    _assert_property_has_docs(async_accepted_schema, "attempt_count")
    _assert_property_has_docs(async_accepted_schema, "max_attempts")
    _assert_property_has_docs(async_accepted_schema, "status_url")

    async_status_schema = schemas["ProposalAsyncOperationStatusResponse"]
    _assert_property_has_docs(async_status_schema, "operation_id")
    _assert_property_has_docs(async_status_schema, "operation_type")
    _assert_property_has_docs(async_status_schema, "status")
    _assert_property_has_docs(async_status_schema, "correlation_id")
    _assert_property_has_docs(async_status_schema, "created_by")
    _assert_property_has_docs(async_status_schema, "created_at")
    _assert_property_has_docs(async_status_schema, "attempt_count")
    _assert_property_has_docs(async_status_schema, "max_attempts")
    _assert_property_has_docs(async_status_schema, "lease_expires_at")
    _assert_property_has_docs(async_status_schema, "result")
    _assert_property_has_docs(async_status_schema, "error")

    replay_schema = schemas["AdvisoryReplayEvidenceResponse"]
    _assert_property_has_docs(replay_schema, "subject")
    _assert_property_has_docs(replay_schema, "resolved_context")
    _assert_property_has_docs(replay_schema, "hashes")
    _assert_property_has_docs(replay_schema, "continuity")
    _assert_property_has_docs(replay_schema, "evidence")
    _assert_property_has_docs(replay_schema, "explanation")

    narrative_review_request_schema = schemas["ProposalNarrativeReviewRequest"]
    _assert_property_has_docs(narrative_review_request_schema, "action")
    _assert_property_has_docs(narrative_review_request_schema, "reviewed_by")
    _assert_property_has_docs(narrative_review_request_schema, "reason")
    _assert_property_has_docs(narrative_review_request_schema, "client_ready_release_requested")
    _assert_property_has_docs(narrative_review_request_schema, "replacement_narrative_id")

    narrative_review_schema = schemas["ProposalNarrativeReviewRecord"]
    _assert_property_has_docs(narrative_review_schema, "review_id")
    _assert_property_has_docs(narrative_review_schema, "proposal_id")
    _assert_property_has_docs(narrative_review_schema, "proposal_version_no")
    _assert_property_has_docs(narrative_review_schema, "narrative_id")
    _assert_property_has_docs(narrative_review_schema, "client_ready_status")
    _assert_property_has_docs(narrative_review_schema, "source_narrative_hash")
    _assert_property_has_docs(narrative_review_schema, "replayed")
    assert "APPROVED_FOR_CLIENT_READY" not in repr(narrative_review_schema)

    narrative_review_response_schema = schemas["ProposalNarrativeReviewResponse"]
    _assert_property_has_docs(narrative_review_response_schema, "proposal")
    _assert_property_has_docs(narrative_review_response_schema, "narrative_review")
    _assert_property_has_docs(narrative_review_response_schema, "latest_workflow_event")

    narrative_read_response_schema = schemas["ProposalNarrativeReadResponse"]
    _assert_property_has_docs(narrative_read_response_schema, "proposal_narrative")
    _assert_property_has_docs(narrative_read_response_schema, "narrative_review")
    _assert_property_has_docs(narrative_read_response_schema, "source_narrative_hash")
    _assert_property_has_docs(narrative_read_response_schema, "replay_evidence_path")
    _assert_property_has_docs(narrative_read_response_schema, "read_posture")

    narrative_regeneration_request_schema = schemas["ProposalNarrativeRegenerationRequest"]
    _assert_property_has_docs(narrative_regeneration_request_schema, "requested_by")
    _assert_property_has_docs(narrative_regeneration_request_schema, "reason")
    _assert_property_has_docs(narrative_regeneration_request_schema, "sections")
    _assert_property_has_docs(narrative_regeneration_request_schema, "generation_mode")
    _assert_property_has_docs(narrative_regeneration_request_schema, "client_audience")

    narrative_regeneration_response_schema = schemas["ProposalNarrativeRegenerationResponse"]
    _assert_property_has_docs(narrative_regeneration_response_schema, "current_narrative_id")
    _assert_property_has_docs(narrative_regeneration_response_schema, "regenerated_narrative")
    _assert_property_has_docs(narrative_regeneration_response_schema, "source_artifact_hash")
    _assert_property_has_docs(narrative_regeneration_response_schema, "source_request_hash")
    _assert_property_has_docs(narrative_regeneration_response_schema, "regeneration_posture")

    memo_create_schema = schemas["ProposalMemoCreateRequest"]
    _assert_property_has_docs(memo_create_schema, "created_by")
    _assert_property_has_docs(memo_create_schema, "lifecycle_status")
    _assert_property_has_docs(memo_create_schema, "reason")

    memo_response_schema = schemas["ProposalMemoResponse"]
    _assert_property_has_docs(memo_response_schema, "memo_id")
    _assert_property_has_docs(memo_response_schema, "memo_status")
    _assert_property_has_docs(memo_response_schema, "lifecycle_status")
    _assert_property_has_docs(memo_response_schema, "source_input_hash")
    _assert_property_has_docs(memo_response_schema, "memo_hash")
    _assert_property_has_docs(memo_response_schema, "projection")
    _assert_property_has_docs(memo_response_schema, "review_posture")
    _assert_property_has_docs(memo_response_schema, "report_package_posture")
    _assert_property_has_docs(memo_response_schema, "replay_metadata")
    _assert_property_has_docs(memo_response_schema, "audit_events")
    _assert_property_has_docs(memo_response_schema, "replay_evidence_path")
    _assert_property_has_docs(memo_response_schema, "read_posture")

    memo_projection_schema = schemas["ProposalMemoProjectionResponse"]
    _assert_property_has_docs(memo_projection_schema, "projection")
    _assert_property_has_docs(memo_projection_schema, "sections")
    _assert_property_has_docs(memo_projection_schema, "projection_posture")

    memo_review_schema = schemas["ProposalMemoReviewRequest"]
    _assert_property_has_docs(memo_review_schema, "action")
    _assert_property_has_docs(memo_review_schema, "reviewed_by")
    _assert_property_has_docs(memo_review_schema, "source_memo_hash")
    _assert_property_has_docs(memo_review_schema, "client_ready_release_requested")
    assert (
        "unsupported in Slice 7"
        not in memo_review_schema["properties"]["client_ready_release_requested"]["description"]
    )

    memo_report_event_schema = schemas["ProposalMemoReportPackageEventRequest"]
    _assert_property_has_docs(memo_report_event_schema, "recorded_by")
    _assert_property_has_docs(memo_report_event_schema, "report_package_id")
    _assert_property_has_docs(memo_report_event_schema, "report_package_status")
    _assert_property_has_docs(memo_report_event_schema, "source_memo_hash")

    memo_report_package_schema = schemas["ProposalMemoReportPackageRequest"]
    _assert_property_has_docs(memo_report_package_schema, "requested_by")
    _assert_property_has_docs(memo_report_package_schema, "source_memo_hash")
    _assert_property_has_docs(memo_report_package_schema, "requested_output_formats")
    _assert_property_has_docs(memo_report_package_schema, "client_ready_document_requested")
    assert (
        "later RFC-0024 client-ready gates"
        not in memo_report_package_schema["properties"]["client_ready_document_requested"][
            "description"
        ]
    )

    memo_lineage_schema = schemas["ProposalMemoLineageResponse"]
    _assert_property_has_docs(memo_lineage_schema, "memo_count")
    _assert_property_has_docs(memo_lineage_schema, "latest_memo_id")
    _assert_property_has_docs(memo_lineage_schema, "lineage_complete")
    _assert_property_has_docs(memo_lineage_schema, "lineage_posture")

    memo_replay_schema = schemas["ProposalMemoReplayEvidenceResponse"]
    _assert_property_has_docs(memo_replay_schema, "subject")
    _assert_property_has_docs(memo_replay_schema, "hashes")
    _assert_property_has_docs(memo_replay_schema, "replay_metadata")
    _assert_property_has_docs(memo_replay_schema, "audit_events")
    _assert_property_has_docs(memo_replay_schema, "evidence")
    _assert_property_has_docs(memo_replay_schema, "explanation")

    policy_evaluation_create_schema = schemas["PolicyEvaluationCreateRequest"]
    _assert_property_has_docs(policy_evaluation_create_schema, "policy_pack_id")
    _assert_property_has_docs(policy_evaluation_create_schema, "policy_version")
    _assert_property_has_docs(policy_evaluation_create_schema, "created_by")
    _assert_property_has_docs(policy_evaluation_create_schema, "evidence_bundle")
    _assert_property_has_docs(policy_evaluation_create_schema, "reason")

    policy_evaluation_event_schema = schemas["PolicyEvaluationEventRequest"]
    _assert_property_has_docs(policy_evaluation_event_schema, "event_type")
    _assert_property_has_docs(policy_evaluation_event_schema, "actor_id")
    _assert_property_has_docs(policy_evaluation_event_schema, "reason")

    policy_evaluation_replay_request_schema = schemas["PolicyEvaluationReplayRequest"]
    _assert_property_has_docs(policy_evaluation_replay_request_schema, "evidence_bundle")

    policy_evaluation_lineage_schema = schemas["PolicyEvaluationLineageResponse"]
    _assert_property_has_docs(policy_evaluation_lineage_schema, "evaluation_id")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "proposal_id")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "proposal_version_id")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "policy_pack_id")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "policy_version")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "policy_content_hash")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "source_evidence_hash")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "evaluation_hash")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "rule_result_hashes")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "source_refs")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "source_gaps")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "audit_events")
    _assert_property_has_docs(policy_evaluation_lineage_schema, "lineage_posture")

    policy_evaluation_queue_schema = schemas["PolicyEvaluationReviewQueueResponse"]
    _assert_property_has_docs(policy_evaluation_queue_schema, "items")
    _assert_property_has_docs(policy_evaluation_queue_schema, "queue_posture")

    policy_evaluation_sign_off_schema = schemas["PolicyEvaluationSignOffPackageResponse"]
    _assert_property_has_docs(policy_evaluation_sign_off_schema, "evaluation")
    _assert_property_has_docs(policy_evaluation_sign_off_schema, "lineage")
    _assert_property_has_docs(policy_evaluation_sign_off_schema, "package_posture")

    policy_requirement_schema = schemas["PolicyEvaluationRequirementProjection"]
    _assert_property_has_docs(policy_requirement_schema, "requirement_id")
    _assert_property_has_docs(policy_requirement_schema, "requirement_type")
    _assert_property_has_docs(policy_requirement_schema, "status")
    _assert_property_has_docs(policy_requirement_schema, "owner_role")
    _assert_property_has_docs(policy_requirement_schema, "review_sla")
    _assert_property_has_docs(policy_requirement_schema, "due_at")
    _assert_property_has_docs(policy_requirement_schema, "reason_codes")

    policy_workflow_schema = schemas["PolicyEvaluationWorkflowResponse"]
    _assert_property_has_docs(policy_workflow_schema, "evaluation_id")
    _assert_property_has_docs(policy_workflow_schema, "proposal_id")
    _assert_property_has_docs(policy_workflow_schema, "proposal_version_id")
    _assert_property_has_docs(policy_workflow_schema, "evaluation_status")
    _assert_property_has_docs(policy_workflow_schema, "approval_dependencies")
    _assert_property_has_docs(policy_workflow_schema, "disclosure_requirements")
    _assert_property_has_docs(policy_workflow_schema, "consent_requirements")
    _assert_property_has_docs(policy_workflow_schema, "conflict_posture")
    _assert_property_has_docs(policy_workflow_schema, "sla_posture")
    _assert_property_has_docs(policy_workflow_schema, "sign_off_status")
    _assert_property_has_docs(policy_workflow_schema, "sign_off_blockers")
    _assert_property_has_docs(policy_workflow_schema, "maker_checker_required")
    _assert_property_has_docs(policy_workflow_schema, "latest_sign_off_event")
    _assert_property_has_docs(policy_workflow_schema, "client_ready_publication")
    _assert_property_has_docs(policy_workflow_schema, "metadata")
    _assert_property_has_docs(policy_workflow_schema, "replay_metadata")

    policy_workflow_metadata_schema = schemas["PolicyEvaluationWorkflowMetadata"]
    for property_name in (
        "product_id",
        "product_version",
        "source_system",
        "evaluation_id",
        "proposal_id",
        "proposal_version_id",
        "portfolio_id",
        "policy_pack_id",
        "policy_version",
        "as_of_date",
        "generated_at",
        "content_hash",
        "evaluation_hash",
        "source_evidence_hash",
        "policy_content_hash",
        "freshness_state",
        "data_quality_status",
        "source_gap_count",
        "source_gaps",
        "client_ready_publication",
        "scope_identity",
        "observed_correlation_id_hash",
        "observed_trace_id_hash",
    ):
        _assert_property_has_docs(policy_workflow_metadata_schema, property_name)

    policy_workflow_replay_schema = schemas["PolicyEvaluationWorkflowReplayMetadata"]
    for property_name in (
        "receipt_contract_version",
        "evaluation_id",
        "proposal_id",
        "proposal_version_id",
        "portfolio_id",
        "as_of_date",
        "policy_pack_id",
        "policy_version",
        "source_refs",
        "source_gaps",
        "source_evidence_hash",
        "evaluation_hash",
        "policy_content_hash",
        "replay_policy",
        "scope_identity",
        "observed_correlation_id_hash",
        "observed_trace_id_hash",
    ):
        _assert_property_has_docs(policy_workflow_replay_schema, property_name)

    policy_receipt_scope_schema = schemas["PolicyEvaluationReceiptScopeIdentity"]
    for property_name in (
        "identity_contract_version",
        "authority_source",
        "tenant_scope_hash",
        "legal_entity_code",
        "booking_center_code",
        "service_identity_hash",
        "proposal_id",
        "proposal_version_id",
        "portfolio_id",
    ):
        _assert_property_has_docs(policy_receipt_scope_schema, property_name)

    policy_signoff_request_schema = schemas["PolicyEvaluationSignOffDecisionRequest"]
    _assert_property_has_docs(policy_signoff_request_schema, "actor_id")
    _assert_property_has_docs(policy_signoff_request_schema, "decision")
    _assert_property_has_docs(policy_signoff_request_schema, "source_evaluation_hash")
    _assert_property_has_docs(policy_signoff_request_schema, "resolved_approval_dependencies")
    _assert_property_has_docs(policy_signoff_request_schema, "satisfied_disclosure_requirements")
    _assert_property_has_docs(policy_signoff_request_schema, "satisfied_consent_requirements")
    _assert_property_has_docs(policy_signoff_request_schema, "conflict_review_outcome")
    _assert_property_has_docs(policy_signoff_request_schema, "reason")

    policy_signoff_response_schema = schemas["PolicyEvaluationSignOffDecisionResponse"]
    _assert_property_has_docs(policy_signoff_response_schema, "workflow")
    _assert_property_has_docs(policy_signoff_response_schema, "sign_off_event")
    _assert_property_has_docs(policy_signoff_response_schema, "replay_metadata")

    policy_report_request_schema = schemas["PolicyEvaluationReportPackageRequest"]
    _assert_property_has_docs(policy_report_request_schema, "requested_by")
    _assert_property_has_docs(policy_report_request_schema, "portfolio_id")
    _assert_property_has_docs(policy_report_request_schema, "source_evaluation_hash")
    _assert_property_has_docs(policy_report_request_schema, "requested_output_formats")
    _assert_property_has_docs(policy_report_request_schema, "client_ready_document_requested")
    _assert_property_has_docs(policy_report_request_schema, "reason")

    policy_report_response_schema = schemas["PolicyEvaluationReportPackageResponse"]
    _assert_property_has_docs(policy_report_response_schema, "evaluation")
    _assert_property_has_docs(policy_report_response_schema, "report_package_event")
    _assert_property_has_docs(policy_report_response_schema, "report")
    _assert_property_has_docs(policy_report_response_schema, "replayed")

    policy_ai_request_schema = schemas["PolicyEvaluationAiEvidenceRequest"]
    _assert_property_has_docs(policy_ai_request_schema, "requested_by")
    _assert_property_has_docs(policy_ai_request_schema, "source_evaluation_hash")
    _assert_property_has_docs(policy_ai_request_schema, "requested_actions")
    _assert_property_has_docs(policy_ai_request_schema, "reason")

    policy_ai_response_schema = schemas["PolicyEvaluationAiEvidenceResponse"]
    _assert_property_has_docs(policy_ai_response_schema, "evaluation")
    _assert_property_has_docs(policy_ai_response_schema, "ai_event")
    _assert_property_has_docs(policy_ai_response_schema, "policy_evidence")
    _assert_property_has_docs(policy_ai_response_schema, "replayed")


def test_lifecycle_endpoints_use_separate_request_and_response_objects():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    create_sync = openapi["paths"]["/advisory/proposals"]["post"]
    create_async = openapi["paths"]["/advisory/proposals/async"]["post"]
    create_version_async = openapi["paths"]["/advisory/proposals/{proposal_id}/versions/async"][
        "post"
    ]

    create_sync_body_ref = create_sync["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    create_sync_response_ref = create_sync["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert create_sync_body_ref.endswith("/ProposalCreateRequest")
    assert create_sync_response_ref.endswith("/ProposalCreateResponse")

    create_async_body_ref = create_async["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    create_async_response_ref = create_async["responses"]["202"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert create_async_body_ref.endswith("/ProposalCreateRequest")
    assert create_async_response_ref.endswith("/ProposalAsyncAcceptedResponse")

    create_version_async_body_ref = create_version_async["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    create_version_async_response_ref = create_version_async["responses"]["202"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert create_version_async_body_ref.endswith("/ProposalVersionRequest")
    assert create_version_async_response_ref.endswith("/ProposalAsyncAcceptedResponse")

    report_request = openapi["paths"]["/advisory/proposals/{proposal_id}/report-requests"]["post"]
    report_request_body_ref = report_request["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    report_request_response_ref = report_request["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert report_request_body_ref.endswith("/ProposalReportRequest")
    assert report_request_response_ref.endswith("/ProposalReportResponse")

    proposal_replay = openapi["paths"][
        "/advisory/proposals/{proposal_id}/versions/{version_no}/replay-evidence"
    ]["get"]
    proposal_replay_ref = proposal_replay["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert proposal_replay_ref.endswith("/AdvisoryReplayEvidenceResponse")

    async_replay = openapi["paths"][
        "/advisory/proposals/operations/{operation_id}/replay-evidence"
    ]["get"]
    async_replay_ref = async_replay["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert async_replay_ref.endswith("/AdvisoryReplayEvidenceResponse")

    narrative_review = openapi["paths"][
        "/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review"
    ]["post"]
    narrative_review_body_ref = narrative_review["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    narrative_review_response_ref = narrative_review["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    narrative_review_parameter_names = [param["name"] for param in narrative_review["parameters"]]
    assert narrative_review_body_ref.endswith("/ProposalNarrativeReviewRequest")
    assert narrative_review_response_ref.endswith("/ProposalNarrativeReviewResponse")
    assert "Idempotency-Key" in narrative_review_parameter_names
    assert _parameter(narrative_review, "Idempotency-Key")["required"] is True

    transition = openapi["paths"]["/advisory/proposals/{proposal_id}/transitions"]["post"]
    assert _parameter(transition, "Idempotency-Key")["required"] is True

    approval = openapi["paths"]["/advisory/proposals/{proposal_id}/approvals"]["post"]
    assert _parameter(approval, "Idempotency-Key")["required"] is True

    narrative_read = openapi["paths"][
        "/advisory/proposals/{proposal_id}/versions/{version_no}/narrative"
    ]["get"]
    narrative_read_ref = narrative_read["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert narrative_read_ref.endswith("/ProposalNarrativeReadResponse")

    narrative_regeneration = openapi["paths"][
        "/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/regenerate"
    ]["post"]
    narrative_regeneration_body_ref = narrative_regeneration["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    narrative_regeneration_response_ref = narrative_regeneration["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert narrative_regeneration_body_ref.endswith("/ProposalNarrativeRegenerationRequest")
    assert narrative_regeneration_response_ref.endswith("/ProposalNarrativeRegenerationResponse")

    execution_handoff = openapi["paths"]["/advisory/proposals/{proposal_id}/execution-handoffs"][
        "post"
    ]
    parameter_names = [param["name"] for param in execution_handoff["parameters"]]
    assert "Idempotency-Key" in parameter_names
    execution_handoff_body_ref = execution_handoff["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    execution_handoff_response_ref = execution_handoff["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert execution_handoff_body_ref.endswith("/ProposalExecutionHandoffRequest")
    assert execution_handoff_response_ref.endswith("/ProposalExecutionHandoffResponse")

    execution_update = openapi["paths"]["/advisory/proposals/{proposal_id}/execution-updates"][
        "post"
    ]
    execution_update_body_ref = execution_update["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    execution_update_response_ref = execution_update["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert execution_update_body_ref.endswith("/ProposalExecutionUpdateRequest")
    assert execution_update_response_ref.endswith("/ProposalExecutionStatusResponse")

    memo_create = openapi["paths"]["/advisory/proposals/{proposal_id}/versions/{version_no}/memo"][
        "post"
    ]
    memo_create_body_ref = memo_create["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    memo_create_response_ref = memo_create["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert memo_create_body_ref.endswith("/ProposalMemoCreateRequest")
    assert memo_create_response_ref.endswith("/ProposalMemoResponse")
    assert "Idempotency-Key" in [param["name"] for param in memo_create["parameters"]]

    memo_review = openapi["paths"][
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/review"
    ]["post"]
    assert memo_review["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ProposalMemoReviewRequest"
    )
    assert memo_review["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ProposalMemoReviewResponse")
    assert "Idempotency-Key" in [param["name"] for param in memo_review["parameters"]]

    memo_report_event = openapi["paths"][
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/report-package-events"
    ]["post"]
    assert memo_report_event["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ProposalMemoReportPackageEventRequest")
    assert memo_report_event["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ProposalMemoReportPackageEventResponse")

    policy_report_package = openapi["paths"][
        "/advisory/policy-evaluations/{evaluation_id}/report-packages"
    ]["post"]
    assert policy_report_package["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/PolicyEvaluationReportPackageRequest")
    assert policy_report_package["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/PolicyEvaluationReportPackageResponse")
    assert "Idempotency-Key" in [param["name"] for param in policy_report_package["parameters"]]

    policy_ai_evidence = openapi["paths"][
        "/advisory/policy-evaluations/{evaluation_id}/ai-evidence"
    ]["post"]
    assert policy_ai_evidence["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/PolicyEvaluationAiEvidenceRequest")
    assert policy_ai_evidence["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/PolicyEvaluationAiEvidenceResponse")
    assert "Idempotency-Key" in [param["name"] for param in policy_ai_evidence["parameters"]]


def test_rfc0023_narrative_route_family_is_canonical_and_error_documented():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    paths = openapi["paths"]
    narrative_paths = sorted(path for path in paths if "narrative" in path.lower())
    assert narrative_paths == [
        "/advisory/proposals/{proposal_id}/versions/{version_no}/narrative",
        "/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/regenerate",
        "/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review",
    ]

    narrative_read = paths["/advisory/proposals/{proposal_id}/versions/{version_no}/narrative"][
        "get"
    ]
    assert narrative_read["summary"] == "Read Persisted Proposal Narrative"
    assert "never regenerates text" in narrative_read["description"]
    assert narrative_read["tags"] == ["Advisory Proposal Lifecycle"]
    read_responses = narrative_read["responses"]
    assert "proposal version was not found" in read_responses["404"]["description"]
    assert "no persisted `proposal_narrative`" in read_responses["422"]["description"]

    narrative_regeneration = paths[
        "/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/regenerate"
    ]["post"]
    assert narrative_regeneration["summary"] == "Regenerate Proposal Narrative Candidate"
    assert "does not mutate proposal state" in narrative_regeneration["description"]
    assert "does not publish client-ready commentary" in narrative_regeneration["description"]
    regeneration_responses = narrative_regeneration["responses"]
    assert "proposal version was not found" in regeneration_responses["404"]["description"]
    assert "no persisted `proposal_narrative`" in regeneration_responses["422"]["description"]

    narrative_review = paths[
        "/advisory/proposals/{proposal_id}/versions/{version_no}/narrative/review"
    ]["post"]
    assert narrative_review["summary"] == "Review Persisted Proposal Narrative"
    assert "never regenerates narrative text" in narrative_review["description"]
    assert narrative_review["tags"] == ["Advisory Proposal Lifecycle"]

    parameter_docs = {param["name"]: param for param in narrative_review["parameters"]}
    assert parameter_docs["proposal_id"]["schema"]["type"] == "string"
    assert parameter_docs["version_no"]["schema"]["type"] == "integer"
    idempotency_header = parameter_docs["Idempotency-Key"]
    assert idempotency_header["in"] == "header"
    assert "replay-safe narrative review writes" in idempotency_header["description"]
    assert "proposal-narrative-review-idem-001" in str(idempotency_header)

    responses = narrative_review["responses"]
    assert responses["200"]["description"] == "Successful Response"
    assert "proposal version was not found" in responses["404"]["description"]
    assert "Idempotency key was reused" in responses["409"]["description"]
    assert "no reviewable `proposal_narrative`" in responses["422"]["description"]
    assert "runtime persistence is unavailable" in responses["503"]["description"]

    for stale_fragment in ("/narratives", "/narrative/lineage"):
        assert not any(stale_fragment in path.lower() for path in paths)


def test_rfc0023_narrative_additive_fields_are_openapi_documented():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    schemas = openapi["components"]["schemas"]
    proposal_artifact = schemas["ProposalArtifact"]
    assert "proposal_narrative" in proposal_artifact["properties"]
    assert (
        "advisor-review narrative"
        in (proposal_artifact["properties"]["proposal_narrative"]["description"])
    )

    replay_response = schemas["AdvisoryReplayEvidenceResponse"]
    evidence_description = replay_response["properties"]["evidence"]["description"]
    assert "Supporting evidence references" in evidence_description

    narrative_schema = schemas["ProposalNarrative"]
    for property_name in (
        "narrative_id",
        "status",
        "audience",
        "generation_mode",
        "review_state",
        "narrative_policy",
        "ai_lineage",
        "grounding_packet",
        "sections",
        "disclosures",
        "guardrail_results",
        "limitations",
    ):
        _assert_property_has_docs(narrative_schema, property_name)
    narrative_descriptions = " ".join(
        str(property_schema.get("description", ""))
        for property_schema in narrative_schema["properties"].values()
    )
    assert "RFC-0023 Slice 7" not in narrative_descriptions
    assert "Slice 5 creates" not in narrative_descriptions


def test_openapi_does_not_expose_api_v1_compatibility_paths():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    assert not any(path.startswith("/api/v1/") for path in openapi["paths"])


def test_openapi_tag_groups_are_documented_for_self_service_discovery():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    tags = {item["name"]: item["description"] for item in openapi["tags"]}

    assert "Advisory Simulation" in tags
    assert "evaluate a proposed set of portfolio actions" in tags["Advisory Simulation"]
    assert "Advisory Proposal Lifecycle" in tags
    assert (
        "creation, versioning, state transitions, approvals, report requests, and execution handoff"
    ) in tags["Advisory Proposal Lifecycle"]
    assert "Advisory Proposal Memo" in tags
    assert "persisted memo evidence packs" in tags["Advisory Proposal Memo"]
    assert "client-ready memo publication gated" in tags["Advisory Proposal Memo"]
    assert "Advisory Policy Packs" in tags
    assert "governed version lookup" in tags["Advisory Policy Packs"]
    assert "Advisory Operations & Support" in tags
    assert (
        "async status, workflow history, lineage, approval history, idempotency tracing"
    ) in tags["Advisory Operations & Support"]
    assert "Advisory Workspace" in tags
    assert "iterative advisory preparation" in tags["Advisory Workspace"]
    assert "Integration" in tags
    assert "service capability and contract discovery" in tags["Integration"]
    assert "Health" in tags
    assert "liveness and readiness probes" in tags["Health"]
    assert "Monitoring" in tags
    assert "metrics scraping and observability tooling" in tags["Monitoring"]


def test_openapi_separates_business_and_support_proposal_tags():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    assert openapi["paths"]["/advisory/proposals"]["post"]["tags"] == [
        "Advisory Proposal Lifecycle"
    ]
    assert openapi["paths"]["/advisory/proposals/{proposal_id}/approvals"]["post"]["tags"] == [
        "Advisory Proposal Lifecycle"
    ]
    assert openapi["paths"]["/advisory/proposals/{proposal_id}/report-requests"]["post"][
        "tags"
    ] == ["Advisory Proposal Lifecycle"]
    assert openapi["paths"]["/advisory/proposals/{proposal_id}/execution-updates"]["post"][
        "tags"
    ] == ["Advisory Proposal Lifecycle"]
    assert openapi["paths"]["/advisory/proposals/operations/{operation_id}"]["get"]["tags"] == [
        "Advisory Operations & Support"
    ]
    assert openapi["paths"]["/advisory/proposals/{proposal_id}/workflow-events"]["get"]["tags"] == [
        "Advisory Operations & Support"
    ]
    assert openapi["paths"]["/advisory/proposals/{proposal_id}/execution-status"]["get"][
        "tags"
    ] == ["Advisory Operations & Support"]
    assert openapi["paths"][
        "/advisory/proposals/{proposal_id}/versions/{version_no}/replay-evidence"
    ]["get"]["tags"] == ["Advisory Operations & Support"]
    assert openapi["paths"]["/advisory/proposals/{proposal_id}/versions/{version_no}/memo"]["post"][
        "tags"
    ] == ["Advisory Proposal Memo"]
    assert openapi["paths"][
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/replay-evidence"
    ]["get"]["tags"] == ["Advisory Proposal Memo"]


def test_rfc0024_memo_route_family_is_canonical_and_error_documented():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    paths = openapi["paths"]
    memo_paths = sorted(path for path in paths if "/memo" in path)
    assert memo_paths == [
        "/advisory/proposals/{proposal_id}/memos/lineage",
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo",
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/ai-commentary",
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/projection",
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/replay-evidence",
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/report-package-events",
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/report-packages",
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/review",
    ]

    memo_create = paths["/advisory/proposals/{proposal_id}/versions/{version_no}/memo"]["post"]
    assert memo_create["summary"] == "Create Or Replay Proposal Memo"
    assert "does not publish client-ready memo content" in memo_create["description"]
    assert "different memo-create payload" in memo_create["responses"]["409"]["description"]
    assert "finalization is blocked" in memo_create["responses"]["422"]["description"]

    memo_read = paths["/advisory/proposals/{proposal_id}/versions/{version_no}/memo"]["get"]
    assert memo_read["summary"] == "Read Proposal Memo"
    assert "audit events" in memo_read["description"]
    assert "persisted memo was not found" in memo_read["responses"]["404"]["description"]

    memo_review = paths["/advisory/proposals/{proposal_id}/versions/{version_no}/memo/review"][
        "post"
    ]
    assert memo_review["summary"] == "Record Proposal Memo Review"
    assert "rejects stale memo hashes" in memo_review["description"]
    assert "cannot release client-ready publication" in memo_review["description"]
    assert "different memo-review payload" in memo_review["responses"]["409"]["description"]

    memo_report_package = paths[
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/report-packages"
    ]["post"]
    assert memo_report_package["summary"] == "Request Proposal Memo Report Package"
    assert "deterministic render/archive handling" in memo_report_package["description"]
    assert "Client-ready document release remains blocked" in memo_report_package["description"]
    assert (
        "lotus-report report/render/archive materialization"
        in memo_report_package["responses"]["503"]["description"]
    )

    memo_report_package_event = paths[
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/report-package-events"
    ]["post"]
    assert memo_report_package_event["summary"] == "Record Proposal Memo Report-Package Event"
    assert "reporting owner" in memo_report_package_event["description"]
    assert "use the report-package request endpoint" in memo_report_package_event["description"]
    assert "later scope" not in memo_report_package_event["description"].lower()

    memo_ai = paths["/advisory/proposals/{proposal_id}/versions/{version_no}/memo/ai-commentary"][
        "post"
    ]
    assert memo_ai["summary"] == "Request Proposal Memo AI Commentary"
    assert "requires memo hash continuity and advisor-use review" in memo_ai["description"]
    assert "cannot alter memo evidence" in memo_ai["description"]
    assert "different AI commentary payload" in memo_ai["responses"]["409"]["description"]

    memo_replay = paths[
        "/advisory/proposals/{proposal_id}/versions/{version_no}/memo/replay-evidence"
    ]["get"]
    assert memo_replay["summary"] == "Get Proposal Memo Replay Evidence"
    assert "memo replay evidence" in memo_replay["description"]

    for stale_fragment in ("/memos/{memo_id}", "/memo/client-ready", "/memo/render"):
        assert not any(stale_fragment in path.lower() for path in paths)


def test_rfc0025_policy_report_package_route_is_canonical_and_error_documented():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    paths = openapi["paths"]
    policy_paths = sorted(path for path in paths if "/advisory/policy-evaluations" in path)
    assert "/advisory/policy-evaluations/{evaluation_id}/diagnostics" in policy_paths
    assert "/advisory/policy-evaluations/{evaluation_id}/report-packages" in policy_paths
    assert "/advisory/policy-evaluations/{evaluation_id}/ai-evidence" in policy_paths

    diagnostics = paths["/advisory/policy-evaluations/{evaluation_id}/diagnostics"]["get"]
    assert diagnostics["summary"] == "Read Policy Evaluation Diagnostics"
    assert "support-safe diagnostic projection" in diagnostics["description"]
    assert "safe next-action" in diagnostics["description"]
    assert diagnostics["tags"] == ["Advisory Policy Evaluation"]

    policy_report_package = paths["/advisory/policy-evaluations/{evaluation_id}/report-packages"][
        "post"
    ]
    assert policy_report_package["summary"] == "Request Policy Report Package"
    assert "signed-off policy evaluation package" in policy_report_package["description"]
    assert "deterministic report/render/archive handling" in policy_report_package["description"]
    assert "Client-ready document release remains blocked" in policy_report_package["description"]
    assert policy_report_package["tags"] == ["Advisory Policy Evaluation"]
    assert (
        "Policy evaluation was not found"
        in policy_report_package["responses"]["404"]["description"]
    )
    assert (
        "different report-package request"
        in policy_report_package["responses"]["409"]["description"]
    )
    assert (
        "client-ready document request" in policy_report_package["responses"]["422"]["description"]
    )
    assert (
        "lotus-report report/render/archive materialization"
        in policy_report_package["responses"]["503"]["description"]
    )

    policy_ai_evidence = paths["/advisory/policy-evaluations/{evaluation_id}/ai-evidence"]["post"]
    assert policy_ai_evidence["summary"] == "Request Policy AI Evidence"
    assert "redacted policy status" in policy_ai_evidence["description"]
    assert "requires human review" in policy_ai_evidence["description"]
    assert "cannot alter policy status" in policy_ai_evidence["description"]
    assert "approvals, waivers, disclosures, consent" in policy_ai_evidence["description"]
    assert policy_ai_evidence["tags"] == ["Advisory Policy Evaluation"]
    assert "different AI evidence request" in policy_ai_evidence["responses"]["409"]["description"]
    assert "forbidden action" in policy_ai_evidence["responses"]["422"]["description"]


def _parameter(operation: dict, name: str) -> dict:
    return next(parameter for parameter in operation["parameters"] if parameter["name"] == name)
