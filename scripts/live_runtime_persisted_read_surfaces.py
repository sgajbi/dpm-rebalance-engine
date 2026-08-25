"""Assertions for the persisted proposal read surfaces used by live parity checks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import httpx

JsonGetter = Callable[..., dict[str, Any]]
AssertCondition = Callable[[bool, str], None]
_DELIVERY_EVENT_TYPES = frozenset(
    "EXECUTION_REQUESTED EXECUTION_ACCEPTED EXECUTION_PARTIALLY_EXECUTED "
    "EXECUTION_REJECTED EXECUTION_CANCELLED EXECUTION_EXPIRED EXECUTED REPORT_REQUESTED".split()
)


@dataclass(frozen=True)
class PersistedReadSurfaces:
    """Typed payload bundle for one proposal's persisted read-surface proof."""

    list_item: dict[str, Any]
    detail: dict[str, Any]
    version: dict[str, Any]
    timeline: dict[str, Any]
    lineage: dict[str, Any]
    approvals: dict[str, Any]
    delivery_summary: dict[str, Any]
    delivery_history: dict[str, Any]


def fetch_persisted_read_surfaces(
    client: httpx.Client,
    *,
    advise_base_url: str,
    proposal_id: str,
    expected_portfolio_id: str,
    created_by_filter: str | None,
    current_version_no: int,
    get_json: JsonGetter,
    assert_condition: AssertCondition,
) -> PersistedReadSurfaces:
    """Fetch the canonical persisted proposal surfaces with their expected statuses."""

    def _get(path: str) -> dict[str, Any]:
        return get_json(client, url=f"{advise_base_url}{path}", expected_status=200)

    list_query = f"/advisory/proposals?portfolio_id={expected_portfolio_id}&limit=100"
    if created_by_filter:
        list_query += f"&created_by={created_by_filter}"
    listed = _get(list_query)
    items = cast(list[dict[str, Any]], listed["items"])
    list_item = next(
        (item for item in items if str(item["proposal_id"]) == proposal_id),
        None,
    )
    assert_condition(
        isinstance(list_item, dict),
        f"{proposal_id}: proposal missing from list response for {expected_portfolio_id}",
    )
    return PersistedReadSurfaces(
        list_item=cast(dict[str, Any], list_item),
        detail=_get(f"/advisory/proposals/{proposal_id}?include_evidence=false"),
        version=_get(
            f"/advisory/proposals/{proposal_id}/versions/"
            f"{current_version_no}?include_evidence=false"
        ),
        timeline=_get(f"/advisory/proposals/{proposal_id}/workflow-events"),
        lineage=_get(f"/advisory/proposals/{proposal_id}/lineage"),
        approvals=_get(f"/advisory/proposals/{proposal_id}/approvals"),
        delivery_summary=_get(f"/advisory/proposals/{proposal_id}/delivery-summary"),
        delivery_history=_get(f"/advisory/proposals/{proposal_id}/delivery-events"),
    )


def assert_persisted_identity_and_version(
    surfaces: PersistedReadSurfaces,
    *,
    proposal_id: str,
    expected_portfolio_id: str,
    current_version_no: int,
    expected_state: str,
    assert_condition: AssertCondition,
) -> None:
    """Prove list, detail, version, and decision-summary agreement."""
    list_item = surfaces.list_item
    detail = surfaces.detail
    version = surfaces.version
    timeline = surfaces.timeline
    delivery_summary = surfaces.delivery_summary
    assert_condition(
        str(list_item["proposal_id"]) == str(detail["proposal"]["proposal_id"]) == proposal_id,
        f"{proposal_id}: list/detail proposal ids diverged",
    )
    assert_condition(
        str(detail["proposal"]["portfolio_id"]) == expected_portfolio_id,
        (
            f"{proposal_id}: detail endpoint returned wrong portfolio "
            f"{detail['proposal']['portfolio_id']}"
        ),
    )
    assert_condition(
        int(list_item["current_version_no"])
        == int(detail["proposal"]["current_version_no"])
        == int(surfaces.lineage["latest_version_no"])
        == current_version_no,
        f"{proposal_id}: current version diverged across list/detail/lineage",
    )
    assert_condition(
        str(list_item["current_state"])
        == str(detail["proposal"]["current_state"])
        == str(timeline["current_state"])
        == str(delivery_summary["proposal"]["current_state"])
        == expected_state,
        f"{proposal_id}: current state diverged across read surfaces",
    )
    assert_condition(
        int(detail["current_version"]["version_no"])
        == int(version["version_no"])
        == current_version_no,
        f"{proposal_id}: detail/version endpoints diverged on current version",
    )
    detail_summary = cast(
        dict[str, Any],
        cast(dict[str, Any], detail["current_version"]["proposal_result"])[
            "proposal_decision_summary"
        ],
    )
    version_summary = cast(
        dict[str, Any],
        cast(dict[str, Any], version["proposal_result"])["proposal_decision_summary"],
    )
    assert_condition(
        detail_summary == version_summary,
        f"{proposal_id}: detail/version decision summaries diverged",
    )
    assert_condition(
        bool(detail_summary.get("decision_status"))
        and bool(detail_summary.get("primary_reason_code")),
        f"{proposal_id}: persisted decision summary omitted required posture fields",
    )
    assert_condition(
        isinstance(detail_summary.get("approval_requirements"), list),
        f"{proposal_id}: persisted decision summary omitted approval requirements list",
    )
    assert_condition(
        str(version["proposal_id"]) == proposal_id,
        f"{proposal_id}: version endpoint returned wrong proposal id",
    )


def _assert_lineage_continuity(
    lineage: dict[str, Any],
    *,
    proposal_id: str,
    current_version_no: int,
    assert_condition: AssertCondition,
) -> None:
    """Prove persisted versions are complete and contiguous."""
    assert_condition(
        int(lineage["version_count"]) == current_version_no,
        f"{proposal_id}: lineage version count did not match latest version",
    )
    lineage_versions = cast(list[dict[str, Any]], lineage["versions"])
    assert_condition(
        [int(item["version_no"]) for item in lineage_versions]
        == list(range(1, current_version_no + 1)),
        f"{proposal_id}: lineage version numbers were not contiguous and ordered",
    )
    assert_condition(
        bool(lineage["lineage_complete"]) is True,
        f"{proposal_id}: lineage unexpectedly incomplete",
    )
    assert_condition(
        list(lineage["missing_version_numbers"]) == [],
        f"{proposal_id}: lineage unexpectedly reported missing versions",
    )


def _assert_timeline_completeness(
    timeline: dict[str, Any],
    delivery_history: dict[str, Any],
    *,
    proposal_id: str,
    current_version_no: int,
    assert_condition: AssertCondition,
) -> None:
    """Prove workflow and delivery histories retain version-creation events."""
    timeline_events = cast(list[dict[str, Any]], timeline["events"])
    delivery_events = cast(list[dict[str, Any]], delivery_history["events"])
    assert_condition(
        int(timeline["event_count"]) == len(timeline_events),
        f"{proposal_id}: timeline event_count mismatch",
    )
    assert_condition(
        int(delivery_history["event_count"]) == len(delivery_events),
        f"{proposal_id}: delivery history event_count mismatch",
    )
    assert_condition(
        len(delivery_events) > 0 and len(timeline_events) >= len(delivery_events),
        f"{proposal_id}: delivery history unexpectedly empty or larger than timeline",
    )
    created_event = next(
        (event for event in timeline_events if event["event_type"] == "CREATED"),
        None,
    )
    assert_condition(
        isinstance(created_event, dict) and created_event["related_version_no"] == 1,
        f"{proposal_id}: missing version-1 CREATED event in workflow timeline",
    )
    if current_version_no > 1:
        new_version_events = [
            event for event in timeline_events if event["event_type"] == "NEW_VERSION_CREATED"
        ]
        assert_condition(
            len(new_version_events) == current_version_no - 1
            and {
                int(event["related_version_no"])
                for event in cast(list[dict[str, Any]], new_version_events)
            }
            == set(range(2, current_version_no + 1)),
            f"{proposal_id}: workflow timeline lost version-creation events",
        )


def assert_persisted_lineage_and_timeline(
    surfaces: PersistedReadSurfaces,
    *,
    proposal_id: str,
    current_version_no: int,
    assert_condition: AssertCondition,
) -> None:
    """Prove lineage continuity and workflow timeline completeness."""
    _assert_lineage_continuity(
        surfaces.lineage,
        proposal_id=proposal_id,
        current_version_no=current_version_no,
        assert_condition=assert_condition,
    )
    _assert_timeline_completeness(
        surfaces.timeline,
        surfaces.delivery_history,
        proposal_id=proposal_id,
        current_version_no=current_version_no,
        assert_condition=assert_condition,
    )


def assert_persisted_delivery_and_approval_surfaces(
    surfaces: PersistedReadSurfaces,
    *,
    proposal_id: str,
    current_version_no: int,
    expected_report_status: str,
    assert_condition: AssertCondition,
) -> None:
    """Prove delivery, approval, execution, and reporting evidence is version-scoped."""
    delivery_history = surfaces.delivery_history
    delivery_summary = surfaces.delivery_summary
    approvals = surfaces.approvals
    delivery_events = cast(list[dict[str, Any]], delivery_history["events"])
    assert_condition(
        all(event["event_type"] in _DELIVERY_EVENT_TYPES for event in delivery_events),
        f"{proposal_id}: delivery history contained non-delivery events",
    )
    assert_condition(
        all(int(event["related_version_no"]) == current_version_no for event in delivery_events),
        f"{proposal_id}: delivery history leaked non-current version events",
    )
    assert_condition(
        int(approvals["approval_count"]) >= 2,
        f"{proposal_id}: approvals endpoint missing lifecycle approval records",
    )
    approval_rows = cast(list[dict[str, Any]], approvals["approvals"])
    assert_condition(
        all(
            int(approval["related_version_no"]) == current_version_no for approval in approval_rows
        ),
        f"{proposal_id}: approvals endpoint leaked non-current version approvals",
    )
    execution = cast(dict[str, Any], delivery_summary["execution"])
    assert_condition(
        execution["handoff_status"] == "EXECUTED",
        f"{proposal_id}: delivery summary execution did not reach EXECUTED",
    )
    assert_condition(
        execution["related_version_no"] == current_version_no,
        f"{proposal_id}: execution summary was not anchored to latest version",
    )
    assert_condition(
        str(cast(dict[str, Any], delivery_history["latest_event"])["event_type"])
        == (
            "REPORT_REQUESTED"
            if expected_report_status == "READY"
            else str(execution["latest_event_type"])
        ),
        f"{proposal_id}: delivery latest event did not match delivery posture",
    )
    reporting = delivery_summary.get("reporting")
    if expected_report_status == "READY":
        reporting_dict = cast(dict[str, Any], reporting)
        assert_condition(
            isinstance(reporting, dict) and reporting_dict["status"] == "READY",
            f"{proposal_id}: delivery summary missing ready reporting posture",
        )
        assert_condition(
            reporting_dict["related_version_no"] == current_version_no,
            f"{proposal_id}: report summary was not anchored to latest version",
        )
    else:
        assert_condition(
            reporting is None,
            f"{proposal_id}: delivery summary unexpectedly contained reporting posture",
        )


def assert_persisted_replay_surfaces(
    client: httpx.Client,
    *,
    advise_base_url: str,
    proposal_id: str,
    current_version_no: int,
    get_json: JsonGetter,
    assert_condition: AssertCondition,
) -> None:
    """Prove replay evidence retains immutable version identity across versions."""
    if current_version_no > 1:
        first_version_replay = get_json(
            client,
            url=f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/1/replay-evidence",
            expected_status=200,
        )
        current_version_replay = get_json(
            client,
            url=(
                f"{advise_base_url}/advisory/proposals/{proposal_id}/versions/"
                f"{current_version_no}/replay-evidence"
            ),
            expected_status=200,
        )
        assert_condition(
            first_version_replay["subject"]["proposal_version_no"] == 1,
            f"{proposal_id}: version-1 replay subject lost immutable version identity",
        )
        assert_condition(
            current_version_replay["subject"]["proposal_version_no"] == current_version_no,
            f"{proposal_id}: current-version replay subject lost version identity",
        )


def assert_persisted_read_surfaces(
    client: httpx.Client,
    *,
    advise_base_url: str,
    proposal_id: str,
    expected_portfolio_id: str,
    created_by_filter: str | None,
    current_version_no: int,
    expected_state: str,
    expected_report_status: str,
    get_json: JsonGetter,
    assert_condition: AssertCondition,
) -> None:
    """Run the complete persisted read-surface proof in cohesive stages."""
    surfaces = fetch_persisted_read_surfaces(
        client,
        advise_base_url=advise_base_url,
        proposal_id=proposal_id,
        expected_portfolio_id=expected_portfolio_id,
        created_by_filter=created_by_filter,
        current_version_no=current_version_no,
        get_json=get_json,
        assert_condition=assert_condition,
    )
    shared: dict[str, Any] = dict(
        proposal_id=proposal_id,
        current_version_no=current_version_no,
        assert_condition=assert_condition,
    )
    assert_persisted_identity_and_version(
        surfaces,
        expected_portfolio_id=expected_portfolio_id,
        expected_state=expected_state,
        **shared,
    )
    assert_persisted_lineage_and_timeline(surfaces, **shared)
    assert_persisted_delivery_and_approval_surfaces(
        surfaces,
        expected_report_status=expected_report_status,
        **shared,
    )
    assert_persisted_replay_surfaces(
        client,
        advise_base_url=advise_base_url,
        get_json=get_json,
        **shared,
    )
