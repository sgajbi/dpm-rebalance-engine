from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.api.capabilities.feature_models import ConsumerSystem as ConsumerSystem
from src.api.capabilities.feature_models import FeatureCapability as FeatureCapability
from src.api.capabilities.feature_models import WorkflowCapability as WorkflowCapability
from src.api.capabilities.readiness_models import DependencyReadiness as DependencyReadiness
from src.api.capabilities.readiness_models import OperationalReadiness as OperationalReadiness
from src.api.capabilities.readiness_models import ReadinessBasis as ReadinessBasis
from src.api.capabilities.supportability_models import (
    AdvisorySupportability as AdvisorySupportability,
)
from src.api.capabilities.supportability_models import FreshnessBucket as FreshnessBucket
from src.api.capabilities.supportability_models import (
    SupportabilityReason as SupportabilityReason,
)
from src.api.capabilities.supportability_models import (
    SupportabilityState as SupportabilityState,
)


class IntegrationCapabilitiesResponse(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "contract_version": "v1",
                "source_service": "lotus-advise",
                "consumer_system": "lotus-gateway",
                "tenant_id": "deployment-wide",
                "publication_scope": "deployment",
                "tenant_policy_evaluated": False,
                "consumer_identity_source": "bounded_query_parameter",
                "authorization_scope": "informational_not_authorization",
                "generated_at": "2026-03-25T00:00:00Z",
                "as_of_date": "2026-03-25",
                "policy_version": "advisory.v1",
                "supported_input_modes": ["stateless", "stateful"],
                "features": [
                    {
                        "key": "advisory.proposals.lifecycle",
                        "enabled": True,
                        "operational_ready": True,
                        "owner_service": "ADVISORY",
                        "description": "Advisory proposal lifecycle APIs.",
                        "fallback_mode": "NONE",
                        "dependency_keys": [],
                        "degraded_reason": None,
                    }
                ],
                "workflows": [
                    {
                        "workflow_key": "advisory_proposal_lifecycle",
                        "enabled": True,
                        "operational_ready": True,
                        "required_features": ["advisory.proposals.lifecycle"],
                        "dependency_keys": [],
                        "degraded_reason": None,
                    }
                ],
                "readiness": {
                    "operational_ready": False,
                    "degraded": True,
                    "degraded_reasons": ["LOTUS_CORE_DEPENDENCY_UNAVAILABLE"],
                    "dependencies": [
                        {
                            "dependency_key": "lotus_core",
                            "service_name": "lotus-core",
                            "description": (
                                "Canonical portfolio state and portfolio simulation authority."
                            ),
                            "base_url_env": "LOTUS_CORE_BASE_URL",
                            "configured": False,
                            "operational_ready": False,
                            "required_by_enabled_capability": True,
                            "runtime_probe_enabled": False,
                            "readiness_basis": "not_configured",
                            "degraded_reason": "LOTUS_CORE_DEPENDENCY_UNAVAILABLE",
                            "fallback_mode": "CONTROLLED_LOCAL_SIMULATION_FALLBACK",
                        }
                    ],
                },
                "supportability": {
                    "state": "degraded",
                    "reason": "dependency_degraded",
                    "freshness_bucket": "unknown",
                    "dependency_count": 5,
                    "ready_dependency_count": 1,
                    "degraded_dependency_count": 4,
                    "enabled_feature_count": 8,
                    "ready_feature_count": 4,
                },
            }
        }
    }

    contract_version: str = Field(description="Integration contract version.", examples=["v1"])
    source_service: str = Field(
        description="Source service generating this capability contract.",
        examples=["lotus-advise"],
    )
    consumer_system: ConsumerSystem = Field(
        description="Consumer system requesting capabilities.",
        examples=["lotus-gateway"],
    )
    tenant_id: str = Field(
        description=(
            "Compatibility scope marker for this deployment-wide capability contract; this "
            "endpoint does not evaluate tenant-specific policy."
        ),
        examples=["deployment-wide"],
    )
    publication_scope: Literal["deployment"] = Field(
        default="deployment",
        description=(
            "Scope of published capability truth. Current capabilities are deployment-wide "
            "readiness and feature posture, not tenant-specific entitlement decisions."
        ),
        examples=["deployment"],
    )
    tenant_policy_evaluated: bool = Field(
        default=False,
        description="False because this endpoint does not resolve tenant-specific policy state.",
        examples=[False],
        json_schema_extra={"example": False},
    )
    consumer_identity_source: Literal["bounded_query_parameter"] = Field(
        default="bounded_query_parameter",
        description=(
            "Consumer view selector source. It is bounded to known consumer values and is not an "
            "authenticated caller identity."
        ),
        examples=["bounded_query_parameter"],
    )
    authorization_scope: Literal["informational_not_authorization"] = Field(
        default="informational_not_authorization",
        description=(
            "Capability discovery is informational and must not be used as endpoint authorization."
        ),
        examples=["informational_not_authorization"],
    )
    generated_at: datetime = Field(
        description="UTC timestamp when capability payload is generated.",
        examples=["2026-03-02T00:00:00Z"],
    )
    as_of_date: date = Field(
        description="Business date that the capability contract applies to.",
        examples=["2026-03-02"],
    )
    policy_version: str = Field(
        description="Capability policy pack version.",
        examples=["advisory.v1"],
    )
    supported_input_modes: list[str] = Field(
        description="Supported request input modes for integrations.",
        examples=[["stateless", "stateful"]],
    )
    features: list[FeatureCapability] = Field(
        description="Feature-level capability flags and ownership."
    )
    workflows: list[WorkflowCapability] = Field(
        description="Workflow-level capability flags and feature dependencies."
    )
    readiness: OperationalReadiness = Field(
        description="Operational readiness metadata for Lotus platform dependency boundaries."
    )
    supportability: AdvisorySupportability = Field(
        description=(
            "Source-backed advisory supportability summary for Gateway and Workbench consumers."
        )
    )
