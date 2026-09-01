from __future__ import annotations

from src.api.routers.runtime_utils import assert_feature_enabled


def assert_proposal_lifecycle_enabled() -> None:
    assert_feature_enabled(
        name="PROPOSAL_WORKFLOW_LIFECYCLE_ENABLED",
        default=True,
        detail="PROPOSAL_WORKFLOW_LIFECYCLE_DISABLED",
    )


def assert_proposal_support_apis_enabled() -> None:
    assert_feature_enabled(
        name="PROPOSAL_SUPPORT_APIS_ENABLED",
        default=True,
        detail="PROPOSAL_SUPPORT_APIS_DISABLED",
    )


def assert_proposal_async_operations_enabled() -> None:
    assert_feature_enabled(
        name="PROPOSAL_ASYNC_OPERATIONS_ENABLED",
        default=True,
        detail="PROPOSAL_ASYNC_OPERATIONS_DISABLED",
    )


def assert_idea_proposal_reconciliation_enabled() -> None:
    """Keep outcome writes off until every pre-0013 application pod is drained."""

    assert_feature_enabled(
        name="IDEA_PROPOSAL_RECONCILIATION_ENABLED",
        default=False,
        detail="IDEA_PROPOSAL_RECONCILIATION_DISABLED",
    )
