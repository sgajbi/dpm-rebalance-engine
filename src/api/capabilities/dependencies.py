from __future__ import annotations

from dataclasses import dataclass

from src.api.capabilities.degraded_reasons import (
    ADVISORY_LIFECYCLE_DISABLED,
    RFC0028_PROOF_DEPENDENCY_UNAVAILABLE,
)

DependencyMap = dict[str, dict[str, object]]

BANK_DEMO_PROOF_DEPENDENCY_KEYS = ("lotus_core", "lotus_risk", "lotus_ai", "lotus_report")


@dataclass(frozen=True)
class CapabilityDependencyStatus:
    lotus_core_ready: bool
    lotus_risk_ready: bool
    lotus_ai_ready: bool
    lotus_report_ready: bool
    bank_demo_operational_ready: bool
    bank_demo_degraded_reason: str | None


def dependency_rows(readiness: dict[str, object]) -> list[dict[str, object]]:
    rows = readiness.get("dependencies", [])
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


def bank_demo_proof_dependency_keys() -> list[str]:
    return list(BANK_DEMO_PROOF_DEPENDENCY_KEYS)


def dependency_map(readiness: dict[str, object]) -> DependencyMap:
    return {
        str(item["dependency_key"]): item
        for item in dependency_rows(readiness)
        if "dependency_key" in item
    }


def dependency_ready(dependencies: DependencyMap, dependency_key: str) -> bool:
    dependency = dependencies.get(dependency_key)
    if dependency is None:
        return False
    return bool(dependency.get("operational_ready"))


def _dependency_degraded_reason(
    dependencies: DependencyMap,
    dependency_key: str,
) -> str | None:
    dependency = dependencies.get(dependency_key)
    if dependency is None:
        return None
    reason = dependency.get("degraded_reason")
    if not isinstance(reason, str) or not reason:
        return None
    return reason


def _unready_dependency_reason(
    dependencies: DependencyMap,
    dependency_key: str,
) -> str | None:
    if dependency_ready(dependencies, dependency_key):
        return None
    return _dependency_degraded_reason(dependencies, dependency_key)


def first_unready_dependency_reason(
    dependencies: DependencyMap,
    dependency_keys: tuple[str, ...],
    *,
    fallback_reason: str,
) -> str:
    for dependency_key in dependency_keys:
        reason = _unready_dependency_reason(dependencies, dependency_key)
        if reason is not None:
            return reason
    return fallback_reason


def bank_demo_proof_readiness(
    *,
    lifecycle_enabled: bool,
    dependencies: DependencyMap,
) -> tuple[bool, str | None]:
    operational_ready = lifecycle_enabled and all(
        dependency_ready(dependencies, dependency_key)
        for dependency_key in BANK_DEMO_PROOF_DEPENDENCY_KEYS
    )
    if operational_ready:
        return True, None
    if not lifecycle_enabled:
        return False, ADVISORY_LIFECYCLE_DISABLED
    return False, first_unready_dependency_reason(
        dependencies,
        BANK_DEMO_PROOF_DEPENDENCY_KEYS,
        fallback_reason=RFC0028_PROOF_DEPENDENCY_UNAVAILABLE,
    )


def resolve_capability_dependency_status(
    *,
    lifecycle_enabled: bool,
    dependencies: DependencyMap,
) -> CapabilityDependencyStatus:
    bank_demo_operational_ready, bank_demo_degraded_reason = bank_demo_proof_readiness(
        lifecycle_enabled=lifecycle_enabled,
        dependencies=dependencies,
    )
    return CapabilityDependencyStatus(
        lotus_core_ready=dependency_ready(dependencies, "lotus_core"),
        lotus_risk_ready=dependency_ready(dependencies, "lotus_risk"),
        lotus_ai_ready=dependency_ready(dependencies, "lotus_ai"),
        lotus_report_ready=dependency_ready(dependencies, "lotus_report"),
        bank_demo_operational_ready=bank_demo_operational_ready,
        bank_demo_degraded_reason=bank_demo_degraded_reason,
    )


__all__ = [
    "BANK_DEMO_PROOF_DEPENDENCY_KEYS",
    "CapabilityDependencyStatus",
    "DependencyMap",
    "bank_demo_proof_dependency_keys",
    "bank_demo_proof_readiness",
    "dependency_map",
    "dependency_ready",
    "dependency_rows",
    "first_unready_dependency_reason",
    "resolve_capability_dependency_status",
]
