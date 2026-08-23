from collections.abc import Iterable
from typing import Protocol

from src.integrations.lotus_ai import build_lotus_ai_dependency_state
from src.integrations.lotus_core import build_lotus_core_dependency_state, lotus_core_fallback_mode
from src.integrations.lotus_performance import build_lotus_performance_dependency_state
from src.integrations.lotus_report import build_lotus_report_dependency_state
from src.integrations.lotus_risk import build_lotus_risk_dependency_state


class _CapabilityDependencyDeclaration(Protocol):
    enabled: bool
    dependency_keys: list[str]


def build_operational_readiness() -> dict[str, object]:
    dependencies = [
        build_lotus_core_dependency_state(),
        build_lotus_risk_dependency_state(),
        build_lotus_report_dependency_state(),
        build_lotus_ai_dependency_state(),
        build_lotus_performance_dependency_state(),
    ]
    degraded = any(not dependency.operational_ready for dependency in dependencies)
    degraded_reasons = [
        f"{dependency.key.upper()}_DEPENDENCY_UNAVAILABLE"
        for dependency in dependencies
        if not dependency.operational_ready
    ]

    fallback_modes = {
        "lotus_core": lotus_core_fallback_mode(),
        "lotus_risk": "LOCAL_RISK_FALLBACK",
        "lotus_ai": "NONE",
        "lotus_report": "NONE",
        "lotus_performance": "NONE",
    }
    return {
        "operational_ready": not degraded,
        "degraded": degraded,
        "degraded_reasons": degraded_reasons,
        "dependencies": [
            {
                "dependency_key": dependency.key,
                "service_name": dependency.service_name,
                "description": dependency.description,
                "base_url_env": dependency.base_url_env,
                "configured": dependency.configured,
                "operational_ready": dependency.operational_ready,
                "runtime_probe_enabled": dependency.runtime_probe_enabled,
                "readiness_basis": dependency.readiness_basis,
                "degraded_reason": dependency.degraded_reason,
                "fallback_mode": fallback_modes.get(dependency.key, "NONE"),
            }
            for dependency in dependencies
        ],
    }


def enabled_capability_dependency_keys(
    *,
    features: Iterable[_CapabilityDependencyDeclaration],
    workflows: Iterable[_CapabilityDependencyDeclaration],
) -> set[str]:
    """Return dependencies that affect at least one enabled capability boundary."""

    return {
        dependency_key
        for capability in (*features, *workflows)
        if capability.enabled
        for dependency_key in capability.dependency_keys
    }


def classify_operational_readiness(
    readiness: dict[str, object],
    *,
    required_dependency_keys: set[str],
) -> dict[str, object]:
    """Mark optional dependency posture without hiding required dependency failures."""

    dependencies = readiness.get("dependencies", [])
    classified_dependencies: list[object] = []
    observed_dependency_keys: set[str] = set()
    degraded_reasons: list[str] = []

    if isinstance(dependencies, list):
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                classified_dependencies.append(dependency)
                continue

            classified_dependency = dict(dependency)
            dependency_key = classified_dependency.get("dependency_key")
            required = (
                isinstance(dependency_key, str) and dependency_key in required_dependency_keys
            )
            if isinstance(dependency_key, str):
                observed_dependency_keys.add(dependency_key)
            classified_dependency["required_by_enabled_capability"] = required
            classified_dependencies.append(classified_dependency)

            if required and not bool(classified_dependency.get("operational_ready")):
                degraded_reasons.append(
                    _dependency_unavailable_reason(
                        dependency_key=dependency_key,
                        degraded_reason=classified_dependency.get("degraded_reason"),
                    )
                )

    for dependency_key in sorted(required_dependency_keys - observed_dependency_keys):
        degraded_reasons.append(_dependency_unavailable_reason(dependency_key=dependency_key))

    deduplicated_reasons = list(dict.fromkeys(degraded_reasons))
    return {
        **readiness,
        "operational_ready": not deduplicated_reasons,
        "degraded": bool(deduplicated_reasons),
        "degraded_reasons": deduplicated_reasons,
        "dependencies": classified_dependencies,
    }


def _dependency_unavailable_reason(
    *,
    dependency_key: object,
    degraded_reason: object = None,
) -> str:
    if isinstance(degraded_reason, str) and degraded_reason:
        return degraded_reason
    if isinstance(dependency_key, str) and dependency_key:
        return f"{dependency_key.upper()}_DEPENDENCY_UNAVAILABLE"
    return "LOTUS_DEPENDENCY_UNAVAILABLE"


__all__ = [
    "build_operational_readiness",
    "classify_operational_readiness",
    "enabled_capability_dependency_keys",
]
