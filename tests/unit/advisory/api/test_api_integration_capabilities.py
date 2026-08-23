from fastapi.testclient import TestClient

from src.api.capabilities.degraded_reasons import (
    LOTUS_AI_DEPENDENCY_UNAVAILABLE,
    dependency_unavailable_reason,
    gated_dependency_unavailable_reason,
    lifecycle_disabled_reason,
)
from src.api.capabilities.dependencies import (
    bank_demo_proof_dependency_keys,
    bank_demo_proof_readiness,
    dependency_map,
    first_unready_dependency_reason,
    resolve_capability_dependency_status,
)
from src.api.capabilities.models import FeatureCapability
from src.api.capabilities.readiness import (
    classify_operational_readiness,
    enabled_capability_dependency_keys,
)
from src.api.capabilities.runtime_flags import resolve_capability_runtime_flags
from src.api.capabilities.service import build_integration_capabilities
from src.api.capabilities.supportability import build_advisory_supportability
from src.api.main import app
from src.api.observability_contracts import ADVISORY_SUPPORTABILITY_METRIC_LABELS

_FORBIDDEN_SUPPORTABILITY_METRIC_LABELS = (
    "portfolio_id",
    "account_id",
    "client_id",
    "advisor_id",
    "proposal_id",
    "workspace_id",
    "correlation_id",
    "trace_id",
    "request_id",
    "transaction_id",
    "security_id",
    "request_body",
    "response_body",
)


def test_integration_capabilities_response_uses_canonical_snake_case_fields():
    with TestClient(app) as client:
        response = client.get(
            "/platform/capabilities",
            params={"consumer_system": "lotus-gateway", "tenant_id": "default"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert "contract_version" in payload
    assert "source_service" in payload
    assert "consumer_system" in payload
    assert "tenant_id" in payload
    assert payload["tenant_id"] == "deployment-wide"
    assert payload["publication_scope"] == "deployment"
    assert payload["tenant_policy_evaluated"] is False
    assert payload["consumer_identity_source"] == "bounded_query_parameter"
    assert payload["authorization_scope"] == "informational_not_authorization"
    assert "generated_at" in payload
    assert "as_of_date" in payload
    assert "policy_version" in payload
    assert "supported_input_modes" in payload
    assert payload["supported_input_modes"] == ["stateless", "stateful"]

    for legacy_key in (
        "contractVersion",
        "sourceService",
        "consumerSystem",
        "tenantId",
        "publicationScope",
        "tenantPolicyEvaluated",
        "consumerIdentitySource",
        "authorizationScope",
        "generatedAt",
        "asOfDate",
        "policyVersion",
        "supportedInputModes",
    ):
        assert legacy_key not in payload


def test_rfc0023_capabilities_advertise_reviewed_narrative_evidence_only():
    with TestClient(app) as client:
        response = client.get(
            "/platform/capabilities",
            params={"consumer_system": "lotus-gateway", "tenant_id": "default"},
        )

    assert response.status_code == 200
    payload = response.json()
    feature_keys = {item["key"] for item in payload["features"]}
    workflow_keys = {item["workflow_key"] for item in payload["workflows"]}
    payload_text = str(payload).lower()

    assert "advisory.proposals.reviewed_narrative_evidence" in feature_keys
    assert "advisory.proposals.client_ready_commentary" not in feature_keys
    assert "advisory_proposal_reviewed_narrative_evidence" in workflow_keys
    assert "reviewed_narrative_evidence" in payload_text
    assert "compliance-review, client-draft, client-ready publication" in payload_text
    assert "client_ready_commentary" not in payload_text


def test_rfc0024_capabilities_advertise_advisor_use_memo_evidence_only():
    with TestClient(app) as client:
        response = client.get(
            "/platform/capabilities",
            params={"consumer_system": "lotus-gateway", "tenant_id": "default"},
        )

    assert response.status_code == 200
    payload = response.json()
    feature_keys = {item["key"] for item in payload["features"]}
    workflow_keys = {item["workflow_key"] for item in payload["workflows"]}
    payload_text = str(payload).lower()

    assert "advisory.proposals.memo_evidence_pack" in feature_keys
    assert "advisory_proposal_memo_evidence_pack" in workflow_keys
    assert "memo evidence product" in payload_text
    assert "client-ready memo publication" in payload_text
    assert "external client communication" in payload_text
    assert "client_ready_memo_publication" not in payload_text


def test_rfc0025_capabilities_advertise_policy_evaluation_after_slice16_closure():
    with TestClient(app) as client:
        response = client.get(
            "/platform/capabilities",
            params={"consumer_system": "lotus-gateway", "tenant_id": "default"},
        )

    assert response.status_code == 200
    payload = response.json()
    feature_keys = {item["key"] for item in payload["features"]}
    workflow_keys = {item["workflow_key"] for item in payload["workflows"]}
    payload_text = str(payload).lower()

    assert "advisory.proposals.policy_evaluation" in feature_keys
    assert "advisory_policy_evaluation" in workflow_keys
    assert "advisory.policy_pack_catalog" in feature_keys
    assert "advisory_policy_pack_catalog" in workflow_keys
    assert "policy evaluation data product" in payload_text
    assert "completed approval/waiver authority" in payload_text
    assert "client-ready publication" in payload_text


def test_rfc0026_capabilities_advertise_advisor_cockpit_after_canonical_proof():
    with TestClient(app) as client:
        response = client.get(
            "/platform/capabilities",
            params={"consumer_system": "lotus-gateway", "tenant_id": "default"},
        )

    assert response.status_code == 200
    payload = response.json()
    feature_keys = {item["key"] for item in payload["features"]}
    workflow_keys = {item["workflow_key"] for item in payload["workflows"]}
    payload_text = str(payload).lower()

    assert "advisory.advisor_cockpit" in feature_keys
    assert "advisor_cockpit_operating_workflow" in workflow_keys
    assert "advisor cockpit operating workflow" in payload_text
    assert "gateway/workbench canonical proof" in payload_text
    assert "client-ready publication" in payload_text
    assert "oms order lifecycle" in payload_text


def test_rfc0027_capabilities_advertise_copilot_after_canonical_proof():
    with TestClient(app) as client:
        response = client.get(
            "/platform/capabilities",
            params={"consumer_system": "lotus-gateway", "tenant_id": "default"},
        )

    assert response.status_code == 200
    payload = response.json()
    feature_keys = {item["key"] for item in payload["features"]}
    workflow_keys = {item["workflow_key"] for item in payload["workflows"]}
    payload_text = str(payload).lower()

    assert "advisory.advisory_copilot" in feature_keys
    assert "advisory_copilot_interaction" in workflow_keys
    assert "advisorycopilotinteractionrecord" in payload_text
    assert "gateway/workbench canonical proof" in payload_text
    assert "client-ready publication" in payload_text
    assert "policy approval/sign-off authority" in payload_text


def test_rfc0028_capabilities_advertise_bank_demo_proof_after_canonical_proof():
    with TestClient(app) as client:
        response = client.get(
            "/platform/capabilities",
            params={"consumer_system": "lotus-gateway", "tenant_id": "default"},
        )

    assert response.status_code == 200
    payload = response.json()
    feature_keys = {item["key"] for item in payload["features"]}
    workflow_keys = {item["workflow_key"] for item in payload["workflows"]}
    feature_by_key = {item["key"]: item for item in payload["features"]}
    workflow_by_key = {item["workflow_key"]: item for item in payload["workflows"]}
    payload_text = str(payload).lower()

    assert "advisory.bank_demo_proof" in feature_keys
    assert "advisory_bank_demo_proof" in workflow_keys
    assert feature_by_key["advisory.bank_demo_proof"]["owner_service"] == "ADVISORY"
    assert feature_by_key["advisory.bank_demo_proof"]["enabled"] is True
    assert feature_by_key["advisory.bank_demo_proof"]["dependency_keys"] == [
        "lotus_core",
        "lotus_risk",
        "lotus_ai",
        "lotus_report",
    ]
    assert workflow_by_key["advisory_bank_demo_proof"]["required_features"] == [
        "advisory.proposals.lifecycle",
        "advisory.proposals.reviewed_narrative_evidence",
        "advisory.proposals.memo_evidence_pack",
        "advisory.policy_pack_catalog",
        "advisory.proposals.policy_evaluation",
        "advisory.advisor_cockpit",
        "advisory.advisory_copilot",
        "advisory.bank_demo_proof",
    ]
    assert workflow_by_key["advisory_bank_demo_proof"]["dependency_keys"] == [
        "lotus_core",
        "lotus_risk",
        "lotus_ai",
        "lotus_report",
    ]
    assert "supported-claim register" in payload_text
    assert "gateway/workbench canonical proof" in payload_text
    assert "client-ready publication" in payload_text
    assert "oms order lifecycle" in payload_text


def test_integration_capabilities_openapi_exposes_deployment_scoped_query_parameters_only():
    openapi = app.openapi()
    operation = openapi["paths"]["/platform/capabilities"]["get"]
    parameter_names = [param["name"] for param in operation["parameters"]]
    assert "consumer_system" in parameter_names
    assert "tenant_id" not in parameter_names
    assert "consumerSystem" not in parameter_names
    assert "tenantId" not in parameter_names
    description = operation["description"]
    assert "deployment-scoped" in description
    assert "Tenant-specific entitlement decisions are not published" in description


def test_integration_capabilities_do_not_echo_arbitrary_tenant_scope():
    with TestClient(app) as client:
        tenant_a = client.get(
            "/platform/capabilities",
            params={"consumer_system": "lotus-gateway", "tenant_id": "tenant-a"},
        ).json()
        tenant_b = client.get(
            "/platform/capabilities",
            params={"consumer_system": "lotus-gateway", "tenant_id": "tenant-b"},
        ).json()

    for payload in (tenant_a, tenant_b):
        assert payload["tenant_id"] == "deployment-wide"
        assert payload["publication_scope"] == "deployment"
        assert payload["tenant_policy_evaluated"] is False
        assert "tenant-a" not in str(payload)
        assert "tenant-b" not in str(payload)
    assert tenant_a["features"] == tenant_b["features"]
    assert tenant_a["workflows"] == tenant_b["workflows"]
    assert tenant_a["supportability"] == tenant_b["supportability"]


def test_integration_capabilities_reports_lotus_dependency_readiness(monkeypatch):
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")
    monkeypatch.delenv("LOTUS_REPORT_BASE_URL", raising=False)
    monkeypatch.delenv("LOTUS_AI_BASE_URL", raising=False)
    monkeypatch.delenv("LOTUS_PERFORMANCE_BASE_URL", raising=False)

    with TestClient(app) as client:
        response = client.get("/platform/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness"]["degraded"] is True
    assert payload["readiness"]["operational_ready"] is False
    assert "LOTUS_AI_DEPENDENCY_UNAVAILABLE" in payload["readiness"]["degraded_reasons"]

    dependencies = {item["dependency_key"]: item for item in payload["readiness"]["dependencies"]}
    assert dependencies["lotus_core"]["configured"] is True
    assert dependencies["lotus_core"]["operational_ready"] is True
    assert dependencies["lotus_core"]["runtime_probe_enabled"] is False
    assert dependencies["lotus_core"]["readiness_basis"] == "configuration_only"
    assert dependencies["lotus_core"]["degraded_reason"] is None
    assert dependencies["lotus_core"]["fallback_mode"] == "NONE"
    assert dependencies["lotus_risk"]["configured"] is True
    assert dependencies["lotus_risk"]["readiness_basis"] == "configuration_only"
    assert dependencies["lotus_risk"]["fallback_mode"] == "LOCAL_RISK_FALLBACK"
    assert dependencies["lotus_report"]["configured"] is False
    assert dependencies["lotus_report"]["readiness_basis"] == "not_configured"
    assert dependencies["lotus_report"]["degraded_reason"] == "LOTUS_REPORT_DEPENDENCY_UNAVAILABLE"
    assert dependencies["lotus_ai"]["configured"] is False
    assert dependencies["lotus_ai"]["readiness_basis"] == "not_configured"

    features = {item["key"]: item for item in payload["features"]}
    assert features["advisory.proposals.simulation"]["operational_ready"] is True
    assert features["advisory.proposals.simulation"]["owner_service"] == "LOTUS_CORE"
    assert features["advisory.proposals.simulation"]["fallback_mode"] == "NONE"
    assert features["advisory.proposals.simulation"]["dependency_keys"] == ["lotus_core"]
    assert features["advisory.proposals.risk_lens"]["operational_ready"] is True
    assert features["advisory.proposals.risk_lens"]["owner_service"] == "LOTUS_RISK"
    assert features["advisory.proposals.risk_lens"]["dependency_keys"] == ["lotus_risk"]
    assert features["advisory.workspaces.stateful"]["operational_ready"] is True
    assert features["advisory.workspaces.stateful"]["fallback_mode"] == "NONE"
    assert features["advisory.workspaces.stateful"]["dependency_keys"] == ["lotus_core"]
    assert features["advisory.workspaces.ai_rationale"]["operational_ready"] is False
    assert features["advisory.workspaces.ai_rationale"]["dependency_keys"] == ["lotus_ai"]
    assert (
        features["advisory.workspaces.ai_rationale"]["degraded_reason"]
        == "LOTUS_AI_DEPENDENCY_UNAVAILABLE"
    )
    assert features["advisory.proposals.reporting"]["operational_ready"] is False
    assert features["advisory.proposals.reporting"]["dependency_keys"] == ["lotus_report"]
    assert (
        features["advisory.proposals.reporting"]["degraded_reason"]
        == "LOTUS_REPORT_DEPENDENCY_UNAVAILABLE"
    )
    assert features["advisory.proposals.reviewed_narrative_evidence"]["enabled"] is True
    assert features["advisory.proposals.reviewed_narrative_evidence"]["operational_ready"] is True
    assert features["advisory.proposals.reviewed_narrative_evidence"]["owner_service"] == "ADVISORY"
    assert features["advisory.proposals.memo_evidence_pack"]["enabled"] is True
    assert features["advisory.proposals.memo_evidence_pack"]["operational_ready"] is False
    assert features["advisory.proposals.memo_evidence_pack"]["owner_service"] == "ADVISORY"
    assert features["advisory.proposals.memo_evidence_pack"]["dependency_keys"] == ["lotus_report"]
    assert (
        features["advisory.proposals.memo_evidence_pack"]["degraded_reason"]
        == "LOTUS_REPORT_DEPENDENCY_UNAVAILABLE"
    )
    assert features["advisory.proposals.policy_evaluation"]["enabled"] is True
    assert features["advisory.proposals.policy_evaluation"]["operational_ready"] is False
    assert features["advisory.proposals.policy_evaluation"]["owner_service"] == "ADVISORY"
    assert features["advisory.proposals.policy_evaluation"]["dependency_keys"] == ["lotus_report"]
    assert (
        features["advisory.proposals.policy_evaluation"]["degraded_reason"]
        == "LOTUS_REPORT_DEPENDENCY_UNAVAILABLE"
    )
    assert features["advisory.advisor_cockpit"]["enabled"] is True
    assert features["advisory.advisor_cockpit"]["operational_ready"] is True
    assert features["advisory.advisor_cockpit"]["owner_service"] == "ADVISORY"
    assert features["advisory.advisory_copilot"]["enabled"] is True
    assert features["advisory.advisory_copilot"]["operational_ready"] is False
    assert features["advisory.advisory_copilot"]["owner_service"] == "ADVISORY"
    assert features["advisory.advisory_copilot"]["dependency_keys"] == ["lotus_ai"]
    assert (
        features["advisory.advisory_copilot"]["degraded_reason"]
        == "LOTUS_AI_DEPENDENCY_UNAVAILABLE"
    )
    assert features["advisory.bank_demo_proof"]["enabled"] is True
    assert features["advisory.bank_demo_proof"]["operational_ready"] is False
    assert features["advisory.bank_demo_proof"]["owner_service"] == "ADVISORY"
    assert features["advisory.bank_demo_proof"]["dependency_keys"] == [
        "lotus_core",
        "lotus_risk",
        "lotus_ai",
        "lotus_report",
    ]
    assert (
        features["advisory.bank_demo_proof"]["degraded_reason"] == "LOTUS_AI_DEPENDENCY_UNAVAILABLE"
    )
    assert features["advisory.proposals.execution_handoff"]["operational_ready"] is True
    assert features["advise.observability.advisory_supportability"]["enabled"] is True
    assert features["advise.observability.advisory_supportability"]["owner_service"] == "ADVISORY"

    workflows = {item["workflow_key"]: item for item in payload["workflows"]}
    assert workflows["advisory_proposal_simulation"]["operational_ready"] is True
    assert workflows["advisory_proposal_risk_lens"]["operational_ready"] is True
    assert workflows["advisory_workspace_stateful"]["operational_ready"] is True
    assert workflows["advisory_workspace_ai_rationale"]["operational_ready"] is False
    assert workflows["advisory_proposal_reporting"]["operational_ready"] is False
    assert workflows["advisory_proposal_reviewed_narrative_evidence"]["enabled"] is True
    assert workflows["advisory_proposal_reviewed_narrative_evidence"]["required_features"] == [
        "advisory.proposals.lifecycle",
        "advisory.proposals.reviewed_narrative_evidence",
    ]
    assert workflows["advisory_proposal_memo_evidence_pack"]["enabled"] is True
    assert workflows["advisory_proposal_memo_evidence_pack"]["operational_ready"] is False
    assert workflows["advisory_proposal_memo_evidence_pack"]["required_features"] == [
        "advisory.proposals.lifecycle",
        "advisory.proposals.memo_evidence_pack",
        "advisory.proposals.reporting",
    ]
    assert workflows["advisory_policy_evaluation"]["enabled"] is True
    assert workflows["advisory_policy_evaluation"]["operational_ready"] is False
    assert workflows["advisory_policy_evaluation"]["required_features"] == [
        "advisory.proposals.lifecycle",
        "advisory.policy_pack_catalog",
        "advisory.proposals.policy_evaluation",
        "advisory.proposals.reporting",
    ]
    assert workflows["advisor_cockpit_operating_workflow"]["enabled"] is True
    assert workflows["advisor_cockpit_operating_workflow"]["operational_ready"] is True
    assert workflows["advisor_cockpit_operating_workflow"]["required_features"] == [
        "advisory.proposals.lifecycle",
        "advisory.policy_pack_catalog",
        "advisory.proposals.policy_evaluation",
        "advisory.proposals.memo_evidence_pack",
        "advisory.advisor_cockpit",
    ]
    assert workflows["advisory_copilot_interaction"]["enabled"] is True
    assert workflows["advisory_copilot_interaction"]["operational_ready"] is False
    assert workflows["advisory_copilot_interaction"]["required_features"] == [
        "advisory.proposals.lifecycle",
        "advisory.advisory_copilot",
    ]
    assert workflows["advisory_copilot_interaction"]["dependency_keys"] == ["lotus_ai"]
    assert workflows["advisory_bank_demo_proof"]["enabled"] is True
    assert workflows["advisory_bank_demo_proof"]["operational_ready"] is False
    assert (
        workflows["advisory_bank_demo_proof"]["degraded_reason"]
        == "LOTUS_AI_DEPENDENCY_UNAVAILABLE"
    )
    assert workflows["advisory_proposal_execution_handoff"]["operational_ready"] is True
    assert payload["supportability"] == {
        "state": "degraded",
        "reason": "dependency_degraded",
        "freshness_bucket": "unknown",
        "metric_labels": list(ADVISORY_SUPPORTABILITY_METRIC_LABELS),
        "dependency_count": 5,
        "ready_dependency_count": 2,
        "degraded_dependency_count": 2,
        "enabled_feature_count": 16,
        "ready_feature_count": 10,
    }


def test_integration_capabilities_mark_risk_lens_degraded_when_risk_missing(monkeypatch):
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.delenv("LOTUS_RISK_BASE_URL", raising=False)

    with TestClient(app) as client:
        response = client.get("/platform/capabilities")

    assert response.status_code == 200
    payload = response.json()
    features = {item["key"]: item for item in payload["features"]}
    workflows = {item["workflow_key"]: item for item in payload["workflows"]}

    assert features["advisory.proposals.risk_lens"]["operational_ready"] is False
    assert (
        features["advisory.proposals.risk_lens"]["degraded_reason"]
        == "LOTUS_RISK_DEPENDENCY_UNAVAILABLE"
    )
    assert workflows["advisory_proposal_risk_lens"]["operational_ready"] is False
    assert (
        workflows["advisory_proposal_risk_lens"]["degraded_reason"]
        == "LOTUS_RISK_DEPENDENCY_UNAVAILABLE"
    )


def test_integration_capabilities_mark_risk_lens_degraded_when_production_probe_fails(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")
    monkeypatch.setattr(
        "src.integrations.base.probe_dependency_health",
        lambda base_url: "lotus-risk" not in base_url,
    )

    with TestClient(app) as client:
        response = client.get("/platform/capabilities")

    assert response.status_code == 200
    payload = response.json()
    dependencies = {item["dependency_key"]: item for item in payload["readiness"]["dependencies"]}
    features = {item["key"]: item for item in payload["features"]}
    workflows = {item["workflow_key"]: item for item in payload["workflows"]}

    assert dependencies["lotus_risk"]["operational_ready"] is False
    assert dependencies["lotus_risk"]["runtime_probe_enabled"] is True
    assert dependencies["lotus_risk"]["readiness_basis"] == "probe_failed"
    assert dependencies["lotus_risk"]["degraded_reason"] == "LOTUS_RISK_DEPENDENCY_UNAVAILABLE"
    assert features["advisory.proposals.risk_lens"]["operational_ready"] is False
    assert (
        features["advisory.proposals.risk_lens"]["degraded_reason"]
        == "LOTUS_RISK_DEPENDENCY_UNAVAILABLE"
    )
    assert workflows["advisory_proposal_risk_lens"]["operational_ready"] is False
    assert (
        workflows["advisory_proposal_risk_lens"]["degraded_reason"]
        == "LOTUS_RISK_DEPENDENCY_UNAVAILABLE"
    )


def test_integration_capabilities_mark_simulation_degraded_when_core_missing(monkeypatch):
    monkeypatch.delenv("LOTUS_CORE_BASE_URL", raising=False)
    monkeypatch.setenv("LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK", "true")

    with TestClient(app) as client:
        response = client.get("/platform/capabilities")

    assert response.status_code == 200
    payload = response.json()
    features = {item["key"]: item for item in payload["features"]}
    workflows = {item["workflow_key"]: item for item in payload["workflows"]}
    dependencies = {item["dependency_key"]: item for item in payload["readiness"]["dependencies"]}

    assert features["advisory.proposals.simulation"]["operational_ready"] is False
    assert (
        features["advisory.proposals.simulation"]["fallback_mode"]
        == "CONTROLLED_LOCAL_SIMULATION_FALLBACK"
    )
    assert (
        features["advisory.proposals.simulation"]["degraded_reason"]
        == "LOTUS_CORE_DEPENDENCY_UNAVAILABLE"
    )
    assert workflows["advisory_proposal_simulation"]["operational_ready"] is False
    assert dependencies["lotus_core"]["fallback_mode"] == "CONTROLLED_LOCAL_SIMULATION_FALLBACK"
    assert dependencies["lotus_core"]["required_by_enabled_capability"] is True
    assert payload["readiness"]["operational_ready"] is False
    assert payload["readiness"]["degraded"] is True
    assert "LOTUS_CORE_DEPENDENCY_UNAVAILABLE" in payload["readiness"]["degraded_reasons"]


def test_integration_capabilities_mark_core_unready_when_production_probe_fails(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")
    monkeypatch.setattr(
        "src.integrations.base.probe_dependency_health",
        lambda base_url: "lotus-core" not in base_url,
    )

    with TestClient(app) as client:
        response = client.get("/platform/capabilities")

    assert response.status_code == 200
    payload = response.json()
    dependencies = {item["dependency_key"]: item for item in payload["readiness"]["dependencies"]}
    features = {item["key"]: item for item in payload["features"]}
    workflows = {item["workflow_key"]: item for item in payload["workflows"]}

    assert dependencies["lotus_core"]["operational_ready"] is False
    assert dependencies["lotus_core"]["runtime_probe_enabled"] is True
    assert dependencies["lotus_core"]["readiness_basis"] == "probe_failed"
    assert dependencies["lotus_core"]["degraded_reason"] == "LOTUS_CORE_DEPENDENCY_UNAVAILABLE"
    assert dependencies["lotus_core"]["fallback_mode"] == "NONE"
    assert features["advisory.proposals.simulation"]["operational_ready"] is False
    assert features["advisory.proposals.simulation"]["fallback_mode"] == "NONE"
    assert (
        features["advisory.proposals.simulation"]["degraded_reason"]
        == "LOTUS_CORE_DEPENDENCY_UNAVAILABLE"
    )
    assert workflows["advisory_proposal_simulation"]["operational_ready"] is False
    assert (
        workflows["advisory_proposal_simulation"]["degraded_reason"]
        == "LOTUS_CORE_DEPENDENCY_UNAVAILABLE"
    )


def test_integration_capabilities_mark_invalid_dependency_configuration_unready(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "ftp://lotus-core:8201")
    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")
    monkeypatch.delenv("LOTUS_REPORT_BASE_URL", raising=False)
    monkeypatch.delenv("LOTUS_AI_BASE_URL", raising=False)
    monkeypatch.delenv("LOTUS_PERFORMANCE_BASE_URL", raising=False)

    with TestClient(app) as client:
        response = client.get("/platform/capabilities")

    assert response.status_code == 200
    payload = response.json()
    dependencies = {item["dependency_key"]: item for item in payload["readiness"]["dependencies"]}
    features = {item["key"]: item for item in payload["features"]}
    workflows = {item["workflow_key"]: item for item in payload["workflows"]}

    assert dependencies["lotus_core"]["configured"] is True
    assert "base_url" not in dependencies["lotus_core"]
    assert dependencies["lotus_core"]["operational_ready"] is False
    assert dependencies["lotus_core"]["runtime_probe_enabled"] is False
    assert dependencies["lotus_core"]["readiness_basis"] == "invalid_configuration"
    assert dependencies["lotus_core"]["degraded_reason"] == "LOTUS_CORE_DEPENDENCY_UNAVAILABLE"
    assert features["advisory.proposals.simulation"]["operational_ready"] is False
    assert workflows["advisory_proposal_simulation"]["operational_ready"] is False


def test_integration_capabilities_quarantine_local_fallback_in_production(monkeypatch):
    monkeypatch.delenv("LOTUS_CORE_BASE_URL", raising=False)
    monkeypatch.setenv("LOTUS_ADVISE_ALLOW_LOCAL_SIMULATION_FALLBACK", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with TestClient(app) as client:
        response = client.get("/platform/capabilities")

    assert response.status_code == 200
    payload = response.json()
    features = {item["key"]: item for item in payload["features"]}
    workflows = {item["workflow_key"]: item for item in payload["workflows"]}
    dependencies = {item["dependency_key"]: item for item in payload["readiness"]["dependencies"]}

    assert features["advisory.proposals.simulation"]["operational_ready"] is False
    assert features["advisory.proposals.simulation"]["fallback_mode"] == "NONE"
    assert workflows["advisory_proposal_simulation"]["operational_ready"] is False
    assert dependencies["lotus_core"]["runtime_probe_enabled"] is False
    assert dependencies["lotus_core"]["readiness_basis"] == "not_configured"
    assert dependencies["lotus_core"]["degraded_reason"] == "LOTUS_CORE_DEPENDENCY_UNAVAILABLE"
    assert dependencies["lotus_core"]["fallback_mode"] == "NONE"


def test_integration_capabilities_disable_reporting_and_execution_with_lifecycle(monkeypatch):
    monkeypatch.setenv("PROPOSAL_WORKFLOW_LIFECYCLE_ENABLED", "false")
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://lotus-report:8300")

    with TestClient(app) as client:
        response = client.get("/platform/capabilities")

    assert response.status_code == 200
    payload = response.json()
    features = {item["key"]: item for item in payload["features"]}
    workflows = {item["workflow_key"]: item for item in payload["workflows"]}
    assert features["advisory.proposals.reporting"]["enabled"] is False
    assert features["advisory.proposals.reporting"]["operational_ready"] is False
    assert features["advisory.proposals.reviewed_narrative_evidence"]["enabled"] is False
    assert (
        features["advisory.proposals.reviewed_narrative_evidence"]["degraded_reason"]
        == "ADVISORY_LIFECYCLE_DISABLED"
    )
    assert features["advisory.proposals.memo_evidence_pack"]["enabled"] is False
    assert features["advisory.advisor_cockpit"]["enabled"] is False
    assert features["advisory.advisor_cockpit"]["degraded_reason"] == "ADVISORY_LIFECYCLE_DISABLED"
    assert features["advisory.proposals.execution_handoff"]["enabled"] is False
    assert workflows["advisory_proposal_reporting"]["enabled"] is False
    assert workflows["advisory_proposal_reviewed_narrative_evidence"]["enabled"] is False
    assert workflows["advisory_proposal_memo_evidence_pack"]["enabled"] is False
    assert workflows["advisor_cockpit_operating_workflow"]["enabled"] is False
    assert workflows["advisory_copilot_interaction"]["enabled"] is False
    assert workflows["advisory_proposal_execution_handoff"]["enabled"] is False
    assert features["advise.observability.advisory_supportability"]["operational_ready"] is False
    assert payload["supportability"]["state"] == "unsupported"
    assert payload["supportability"]["reason"] == "lifecycle_disabled"


def test_integration_capabilities_reports_ready_advisory_supportability(monkeypatch):
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://lotus-report:8300")
    monkeypatch.setenv("LOTUS_AI_BASE_URL", "http://lotus-ai:8400")
    monkeypatch.setenv("LOTUS_PERFORMANCE_BASE_URL", "http://lotus-performance:8301")

    with TestClient(app) as client:
        response = client.get("/platform/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["supportability"] == {
        "state": "ready",
        "reason": "advisory_ready",
        "freshness_bucket": "current",
        "metric_labels": list(ADVISORY_SUPPORTABILITY_METRIC_LABELS),
        "dependency_count": 5,
        "ready_dependency_count": 5,
        "degraded_dependency_count": 0,
        "enabled_feature_count": 16,
        "ready_feature_count": 16,
    }


def test_integration_capabilities_treats_unused_performance_as_optional(monkeypatch):
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://lotus-report:8300")
    monkeypatch.setenv("LOTUS_AI_BASE_URL", "http://lotus-ai:8400")
    monkeypatch.delenv("LOTUS_PERFORMANCE_BASE_URL", raising=False)

    with TestClient(app) as client:
        response = client.get("/platform/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness"]["operational_ready"] is True
    assert payload["readiness"]["degraded"] is False
    assert payload["readiness"]["degraded_reasons"] == []
    performance = {item["dependency_key"]: item for item in payload["readiness"]["dependencies"]}[
        "lotus_performance"
    ]
    assert performance["configured"] is False
    assert performance["operational_ready"] is False
    assert performance["readiness_basis"] == "not_configured"
    assert performance["required_by_enabled_capability"] is False
    assert payload["supportability"]["state"] == "ready"
    assert payload["supportability"]["reason"] == "advisory_ready"
    assert payload["supportability"]["dependency_count"] == 5
    assert payload["supportability"]["ready_dependency_count"] == 4
    assert payload["supportability"]["degraded_dependency_count"] == 0


def test_optional_dependency_becomes_required_when_enabled_capability_declares_it():
    readiness = {
        "dependencies": [
            {
                "dependency_key": "lotus_performance",
                "operational_ready": False,
                "degraded_reason": "LOTUS_PERFORMANCE_DEPENDENCY_UNAVAILABLE",
            }
        ]
    }
    feature = FeatureCapability(
        key="advisory.performance.valuation",
        enabled=True,
        operational_ready=False,
        owner_service="ADVISORY",
        description="Synthetic future capability for dependency classification coverage.",
        fallback_mode="NONE",
        dependency_keys=["lotus_performance"],
        degraded_reason="LOTUS_PERFORMANCE_DEPENDENCY_UNAVAILABLE",
    )

    optional = classify_operational_readiness(
        readiness,
        required_dependency_keys=enabled_capability_dependency_keys(
            features=[],
            workflows=[],
        ),
    )
    required = classify_operational_readiness(
        readiness,
        required_dependency_keys=enabled_capability_dependency_keys(
            features=[feature],
            workflows=[],
        ),
    )

    assert optional["operational_ready"] is True
    assert optional["degraded_reasons"] == []
    assert optional["dependencies"][0]["required_by_enabled_capability"] is False
    assert required["operational_ready"] is False
    assert required["degraded_reasons"] == ["LOTUS_PERFORMANCE_DEPENDENCY_UNAVAILABLE"]
    assert required["dependencies"][0]["required_by_enabled_capability"] is True


def test_integration_capabilities_records_bounded_supportability_metric(monkeypatch):
    monkeypatch.setenv("LOTUS_CORE_BASE_URL", "http://lotus-core:8201")
    monkeypatch.setenv("LOTUS_RISK_BASE_URL", "http://lotus-risk:8130")
    monkeypatch.setenv("LOTUS_REPORT_BASE_URL", "http://lotus-report:8300")
    monkeypatch.setenv("LOTUS_AI_BASE_URL", "http://lotus-ai:8400")
    monkeypatch.setenv("LOTUS_PERFORMANCE_BASE_URL", "http://lotus-performance:8301")

    with TestClient(app) as client:
        capabilities_response = client.get("/platform/capabilities")
        metrics_response = client.get("/metrics")

    assert capabilities_response.status_code == 200
    assert metrics_response.status_code == 200
    metrics_text = metrics_response.text
    assert "lotus_advise_advisory_supportability_total" in metrics_text
    assert 'freshness_bucket="current"' in metrics_text
    assert 'reason="advisory_ready"' in metrics_text
    assert 'state="ready"' in metrics_text
    for forbidden_label in _FORBIDDEN_SUPPORTABILITY_METRIC_LABELS:
        assert f"{forbidden_label}=" not in metrics_text


def test_integration_capabilities_openapi_documents_supportability_metric_labels():
    openapi = app.openapi()
    supportability_schema = openapi["components"]["schemas"]["AdvisorySupportability"]
    metric_labels = supportability_schema["properties"]["metric_labels"]

    assert metric_labels["default"] == list(ADVISORY_SUPPORTABILITY_METRIC_LABELS)
    assert "lotus_advise_advisory_supportability_total" in metric_labels["description"]
    assert "portfolio" in metric_labels["description"]
    assert "trace" in metric_labels["description"]


def test_advisory_supportability_projection_handles_malformed_dependency_rows():
    supportability = build_advisory_supportability(
        readiness={"dependencies": ["not-a-row", {"operational_ready": True}]},
        lifecycle_enabled=True,
        features=[],
    )

    assert supportability.dependency_count == 1
    assert supportability.ready_dependency_count == 1
    assert supportability.degraded_dependency_count == 0
    assert supportability.state == "ready"


def test_capability_dependency_helpers_fail_closed_for_missing_proof_dependency():
    dependencies = dependency_map(
        {
            "dependencies": [
                {"dependency_key": "lotus_core", "operational_ready": True},
                "malformed-row",
                {"dependency_key": "lotus_risk", "operational_ready": True},
                {
                    "dependency_key": "lotus_ai",
                    "operational_ready": False,
                    "degraded_reason": "LOTUS_AI_DEPENDENCY_UNAVAILABLE",
                },
            ]
        }
    )

    ready, reason = bank_demo_proof_readiness(
        lifecycle_enabled=True,
        dependencies=dependencies,
    )

    assert "malformed-row" not in dependencies
    assert ready is False
    assert reason == "LOTUS_AI_DEPENDENCY_UNAVAILABLE"


def test_first_unready_dependency_reason_ignores_empty_or_malformed_reason_values():
    dependencies = dependency_map(
        {
            "dependencies": [
                {
                    "dependency_key": "lotus_core",
                    "operational_ready": False,
                    "degraded_reason": "",
                },
                {
                    "dependency_key": "lotus_risk",
                    "operational_ready": False,
                    "degraded_reason": ["LOTUS_RISK_DEPENDENCY_UNAVAILABLE"],
                },
                {
                    "dependency_key": "lotus_ai",
                    "operational_ready": False,
                    "degraded_reason": "LOTUS_AI_DEPENDENCY_UNAVAILABLE",
                },
            ]
        }
    )

    assert (
        first_unready_dependency_reason(
            dependencies,
            tuple(bank_demo_proof_dependency_keys()),
            fallback_reason="RFC0028_PROOF_DEPENDENCY_UNAVAILABLE",
        )
        == "LOTUS_AI_DEPENDENCY_UNAVAILABLE"
    )


def test_first_unready_dependency_reason_uses_fallback_when_no_public_reason_is_available():
    dependencies = dependency_map(
        {
            "dependencies": [
                {"dependency_key": "lotus_core", "operational_ready": False},
                {"dependency_key": "lotus_risk", "operational_ready": False},
            ]
        }
    )

    assert (
        first_unready_dependency_reason(
            dependencies,
            tuple(bank_demo_proof_dependency_keys()),
            fallback_reason="RFC0028_PROOF_DEPENDENCY_UNAVAILABLE",
        )
        == "RFC0028_PROOF_DEPENDENCY_UNAVAILABLE"
    )


def test_capability_dependency_status_projects_common_readiness_once():
    dependencies = dependency_map(
        {
            "dependencies": [
                {"dependency_key": "lotus_core", "operational_ready": True},
                {"dependency_key": "lotus_risk", "operational_ready": True},
                {"dependency_key": "lotus_ai", "operational_ready": True},
                {"dependency_key": "lotus_report", "operational_ready": False},
            ]
        }
    )

    status = resolve_capability_dependency_status(
        lifecycle_enabled=True,
        dependencies=dependencies,
    )

    assert status.lotus_core_ready is True
    assert status.lotus_risk_ready is True
    assert status.lotus_ai_ready is True
    assert status.lotus_report_ready is False
    assert status.bank_demo_operational_ready is False
    assert status.bank_demo_degraded_reason == "RFC0028_PROOF_DEPENDENCY_UNAVAILABLE"


def test_capability_degraded_reason_helpers_preserve_public_reason_values():
    assert (
        dependency_unavailable_reason(
            ready=False,
            reason=LOTUS_AI_DEPENDENCY_UNAVAILABLE,
        )
        == "LOTUS_AI_DEPENDENCY_UNAVAILABLE"
    )
    assert (
        dependency_unavailable_reason(
            ready=True,
            reason=LOTUS_AI_DEPENDENCY_UNAVAILABLE,
        )
        is None
    )
    assert (
        gated_dependency_unavailable_reason(
            enabled=False,
            ready=False,
            reason=LOTUS_AI_DEPENDENCY_UNAVAILABLE,
        )
        is None
    )
    assert (
        gated_dependency_unavailable_reason(
            enabled=True,
            ready=False,
            reason=LOTUS_AI_DEPENDENCY_UNAVAILABLE,
        )
        == "LOTUS_AI_DEPENDENCY_UNAVAILABLE"
    )
    assert lifecycle_disabled_reason(lifecycle_enabled=False) == "ADVISORY_LIFECYCLE_DISABLED"


def test_capability_runtime_flags_resolve_shared_boolean_environment(monkeypatch):
    monkeypatch.setenv("PROPOSAL_WORKFLOW_LIFECYCLE_ENABLED", "off")
    monkeypatch.setenv("PROPOSAL_ASYNC_OPERATIONS_ENABLED", "YES")
    monkeypatch.setenv("LOTUS_AI_WORKSPACE_RATIONALE_ENABLED", "0")

    flags = resolve_capability_runtime_flags()

    assert flags.lifecycle_enabled is False
    assert flags.async_enabled is True
    assert flags.ai_rationale_enabled is False


def test_integration_capabilities_service_fails_closed_for_missing_dependency():
    readiness = {
        "operational_ready": True,
        "degraded": False,
        "degraded_reasons": [],
        "dependencies": [
            {
                "dependency_key": "lotus_core",
                "service_name": "lotus-core",
                "description": "Canonical portfolio state and portfolio simulation authority.",
                "base_url_env": "LOTUS_CORE_BASE_URL",
                "configured": True,
                "operational_ready": True,
                "runtime_probe_enabled": True,
                "readiness_basis": "probe_succeeded",
                "degraded_reason": None,
                "fallback_mode": "NONE",
            },
            {
                "dependency_key": "lotus_risk",
                "service_name": "lotus-risk",
                "description": "Canonical advisory risk-lens authority.",
                "base_url_env": "LOTUS_RISK_BASE_URL",
                "configured": True,
                "operational_ready": True,
                "runtime_probe_enabled": True,
                "readiness_basis": "probe_succeeded",
                "degraded_reason": None,
                "fallback_mode": "LOCAL_RISK_FALLBACK",
            },
            {
                "dependency_key": "lotus_report",
                "service_name": "lotus-report",
                "description": "Advisory proposal report-request integration boundary.",
                "base_url_env": "LOTUS_REPORT_BASE_URL",
                "configured": True,
                "operational_ready": True,
                "runtime_probe_enabled": True,
                "readiness_basis": "probe_succeeded",
                "degraded_reason": None,
                "fallback_mode": "NONE",
            },
        ],
    }

    response = build_integration_capabilities(
        consumer_system="lotus-gateway",
        readiness=readiness,
    )

    features = {feature.key: feature for feature in response.features}
    workflows = {workflow.workflow_key: workflow for workflow in response.workflows}

    assert features["advisory.workspaces.ai_rationale"].operational_ready is False
    assert (
        features["advisory.workspaces.ai_rationale"].degraded_reason
        == "LOTUS_AI_DEPENDENCY_UNAVAILABLE"
    )
    assert workflows["advisory_workspace_ai_rationale"].operational_ready is False
    assert (
        workflows["advisory_workspace_ai_rationale"].degraded_reason
        == "LOTUS_AI_DEPENDENCY_UNAVAILABLE"
    )
    assert response.supportability.state == "degraded"
    assert (
        response.supportability.ready_feature_count < response.supportability.enabled_feature_count
    )
