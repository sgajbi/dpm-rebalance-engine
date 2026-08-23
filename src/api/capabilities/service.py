from datetime import UTC, date, datetime

from src.api.capabilities.dependencies import dependency_map
from src.api.capabilities.feature_catalog import build_feature_capabilities
from src.api.capabilities.models import (
    ConsumerSystem,
    IntegrationCapabilitiesResponse,
    OperationalReadiness,
)
from src.api.capabilities.readiness import (
    build_operational_readiness,
    classify_operational_readiness,
    enabled_capability_dependency_keys,
)
from src.api.capabilities.runtime_flags import resolve_capability_runtime_flags
from src.api.capabilities.supportability import build_advisory_supportability
from src.api.capabilities.workflow_catalog import build_workflow_capabilities

DEPLOYMENT_CAPABILITY_TENANT_ID = "deployment-wide"


def build_integration_capabilities(
    *,
    consumer_system: ConsumerSystem,
    readiness: dict[str, object] | None = None,
) -> IntegrationCapabilitiesResponse:
    runtime_flags = resolve_capability_runtime_flags()
    readiness_payload = readiness if readiness is not None else build_operational_readiness()
    dependencies = dependency_map(readiness_payload)
    features = build_feature_capabilities(
        lifecycle_enabled=runtime_flags.lifecycle_enabled,
        async_enabled=runtime_flags.async_enabled,
        ai_rationale_enabled=runtime_flags.ai_rationale_enabled,
        dependencies=dependencies,
    )
    workflows = build_workflow_capabilities(
        lifecycle_enabled=runtime_flags.lifecycle_enabled,
        ai_rationale_enabled=runtime_flags.ai_rationale_enabled,
        dependencies=dependencies,
    )
    readiness_payload = classify_operational_readiness(
        readiness_payload,
        required_dependency_keys=enabled_capability_dependency_keys(
            features=features,
            workflows=workflows,
        ),
    )

    return IntegrationCapabilitiesResponse(
        contract_version="v1",
        source_service="lotus-advise",
        consumer_system=consumer_system,
        tenant_id=DEPLOYMENT_CAPABILITY_TENANT_ID,
        publication_scope="deployment",
        tenant_policy_evaluated=False,
        consumer_identity_source="bounded_query_parameter",
        authorization_scope="informational_not_authorization",
        generated_at=datetime.now(UTC),
        as_of_date=date.today(),
        policy_version="advisory.v1",
        supported_input_modes=["stateless", "stateful"],
        features=features,
        workflows=workflows,
        readiness=OperationalReadiness.model_validate(readiness_payload),
        supportability=build_advisory_supportability(
            readiness=readiness_payload,
            lifecycle_enabled=runtime_flags.lifecycle_enabled,
            features=features,
        ),
    )
