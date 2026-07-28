import re

from src.core.proposals.identifiers import (
    new_approval_id,
    new_async_operation_id,
    new_execution_request_id,
    new_proposal_id,
    new_proposal_version_id,
    new_report_request_id,
    new_workflow_event_id,
)


def test_proposal_identifier_factories_use_governed_prefixes():
    identifiers = {
        "pp": new_proposal_id(),
        "ppv": new_proposal_version_id(),
        "pwe": new_workflow_event_id(),
        "pex": new_execution_request_id(),
        "pap": new_approval_id(),
        "prr": new_report_request_id(),
    }

    for prefix, identifier in identifiers.items():
        assert re.fullmatch(rf"{prefix}_[0-9a-f]{{12}}", identifier)

    assert re.fullmatch(r"pop_[0-9a-f]{24}", new_async_operation_id())


def test_async_operation_identifiers_are_lexicographically_time_ordered():
    first = new_async_operation_id()
    second = new_async_operation_id()

    assert first.startswith("pop_")
    assert second.startswith("pop_")
    assert first < second
