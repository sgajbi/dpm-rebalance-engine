from typing import Literal

from pydantic import BaseModel, Field

ReadinessBasis = Literal[
    "not_configured",
    "invalid_configuration",
    "configuration_only",
    "probe_succeeded",
    "probe_failed",
]


class DependencyReadiness(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "dependency_key": "lotus_core",
                "service_name": "lotus-core",
                "description": "Canonical portfolio state and portfolio simulation authority.",
                "base_url_env": "LOTUS_CORE_BASE_URL",
                "configured": True,
                "operational_ready": True,
                "required_by_enabled_capability": True,
                "runtime_probe_enabled": True,
                "readiness_basis": "probe_succeeded",
                "degraded_reason": None,
                "fallback_mode": "NONE",
            }
        }
    }

    dependency_key: str = Field(
        description="Canonical dependency key for the Lotus platform integration boundary.",
        examples=["lotus_core"],
    )
    service_name: str = Field(
        description="Lotus service name for the dependency.",
        examples=["lotus-core"],
    )
    description: str = Field(
        description="Lotus-branded summary of what this dependency provides.",
        examples=["Canonical portfolio state and portfolio simulation authority."],
    )
    base_url_env: str = Field(
        description="Environment variable used to configure the dependency base URL.",
        examples=["LOTUS_CORE_BASE_URL"],
    )
    configured: bool = Field(
        description="Whether the dependency base URL is configured for this lotus-advise runtime.",
        examples=[True],
    )
    operational_ready: bool = Field(
        description=(
            "Whether the dependency boundary is currently ready for use by lotus-advise. "
            "An optional, unconfigured dependency may be false without degrading the runtime "
            "when no enabled feature or workflow requires it."
        ),
        examples=[True],
    )
    required_by_enabled_capability: bool = Field(
        default=True,
        description=(
            "Whether at least one enabled feature or workflow currently requires this "
            "dependency. Optional unconfigured dependencies are published for transparency "
            "but do not degrade overall readiness or supportability."
        ),
        examples=[True],
    )
    runtime_probe_enabled: bool = Field(
        description=(
            "Whether this readiness decision used runtime health probing instead of "
            "configuration-only posture."
        ),
        examples=[True],
    )
    readiness_basis: ReadinessBasis = Field(
        description=(
            "Bounded evidence basis for the readiness decision: missing configuration, "
            "configuration-only non-production posture, successful runtime probe, or failed "
            "runtime probe. Invalid configuration is reported separately when a dependency URL "
            "is present but unusable."
        ),
        examples=["probe_succeeded"],
    )
    degraded_reason: str | None = Field(
        default=None,
        description=(
            "Bounded dependency-level degraded reason when this integration boundary is not "
            "operationally ready."
        ),
        examples=["LOTUS_CORE_DEPENDENCY_UNAVAILABLE"],
    )
    fallback_mode: str = Field(
        description="Fallback posture used when the dependency is unavailable.",
        examples=["CONTROLLED_LOCAL_SIMULATION_FALLBACK"],
    )


class OperationalReadiness(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
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
            }
        }
    }

    operational_ready: bool = Field(
        description=(
            "Whether all integration boundaries required by enabled lotus-advise features and "
            "workflows are ready. Optional unconfigured dependencies do not make this false."
        ),
        examples=[False],
    )
    degraded: bool = Field(
        description="Whether lotus-advise is running in a degraded integration posture.",
        examples=[True],
    )
    degraded_reasons: list[str] = Field(
        default_factory=list,
        description="Structured reasons describing why the runtime is degraded.",
        examples=[["LOTUS_CORE_DEPENDENCY_UNAVAILABLE"]],
    )
    dependencies: list[DependencyReadiness] = Field(
        default_factory=list,
        description=(
            "Lotus platform dependency readiness details for advisory integration boundaries."
        ),
    )


__all__ = ["DependencyReadiness", "OperationalReadiness", "ReadinessBasis"]
