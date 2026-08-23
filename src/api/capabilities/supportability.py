from __future__ import annotations

from dataclasses import dataclass

from src.api.capabilities.dependencies import dependency_rows
from src.api.capabilities.models import (
    AdvisorySupportability,
    FeatureCapability,
    FreshnessBucket,
    SupportabilityReason,
    SupportabilityState,
)
from src.api.observability import record_advisory_supportability


@dataclass(frozen=True)
class _SupportabilityCounts:
    dependency_count: int
    ready_dependency_count: int
    degraded_dependency_count: int
    enabled_feature_count: int
    ready_feature_count: int


@dataclass(frozen=True)
class _SupportabilityPosture:
    state: SupportabilityState
    reason: SupportabilityReason
    freshness_bucket: FreshnessBucket


def build_advisory_supportability(
    *,
    readiness: dict[str, object],
    lifecycle_enabled: bool,
    features: list[FeatureCapability],
) -> AdvisorySupportability:
    counts = _supportability_counts(readiness=readiness, features=features)
    posture = _supportability_posture(lifecycle_enabled=lifecycle_enabled, counts=counts)
    supportability = AdvisorySupportability(
        state=posture.state,
        reason=posture.reason,
        freshness_bucket=posture.freshness_bucket,
        dependency_count=counts.dependency_count,
        ready_dependency_count=counts.ready_dependency_count,
        degraded_dependency_count=counts.degraded_dependency_count,
        enabled_feature_count=counts.enabled_feature_count,
        ready_feature_count=counts.ready_feature_count,
    )
    _record_supportability_metric(supportability)
    return supportability


def _supportability_counts(
    *,
    readiness: dict[str, object],
    features: list[FeatureCapability],
) -> _SupportabilityCounts:
    dependency_count, ready_dependency_count, degraded_dependency_count = _dependency_counts(
        readiness
    )
    enabled_feature_count, ready_feature_count = _feature_counts(features)
    return _SupportabilityCounts(
        dependency_count=dependency_count,
        ready_dependency_count=ready_dependency_count,
        degraded_dependency_count=degraded_dependency_count,
        enabled_feature_count=enabled_feature_count,
        ready_feature_count=ready_feature_count,
    )


def _dependency_counts(readiness: dict[str, object]) -> tuple[int, int, int]:
    rows = dependency_rows(readiness)
    ready_dependency_count = sum(
        1 for dependency in rows if bool(dependency.get("operational_ready"))
    )
    degraded_dependency_count = sum(
        1
        for dependency in rows
        if bool(dependency.get("required_by_enabled_capability", True))
        and not bool(dependency.get("operational_ready"))
    )
    return len(rows), ready_dependency_count, degraded_dependency_count


def _feature_counts(features: list[FeatureCapability]) -> tuple[int, int]:
    enabled_features = [feature for feature in features if feature.enabled]
    return len(enabled_features), sum(
        1 for feature in enabled_features if feature.operational_ready
    )


def _supportability_posture(
    *,
    lifecycle_enabled: bool,
    counts: _SupportabilityCounts,
) -> _SupportabilityPosture:
    if not lifecycle_enabled:
        return _SupportabilityPosture("unsupported", "lifecycle_disabled", "unknown")
    if _has_degraded_supportability(counts):
        return _SupportabilityPosture("degraded", "dependency_degraded", "unknown")
    return _SupportabilityPosture("ready", "advisory_ready", "current")


def _has_degraded_supportability(counts: _SupportabilityCounts) -> bool:
    return (
        counts.degraded_dependency_count > 0
        or counts.ready_feature_count < counts.enabled_feature_count
    )


def _record_supportability_metric(supportability: AdvisorySupportability) -> None:
    record_advisory_supportability(
        state=supportability.state,
        reason=supportability.reason,
        freshness_bucket=supportability.freshness_bucket,
    )


__all__ = ["build_advisory_supportability"]
