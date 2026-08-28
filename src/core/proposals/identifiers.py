from hashlib import sha256
from threading import Lock
from time import time_ns
from uuid import uuid4

_ASYNC_OPERATION_ID_LOCK = Lock()
_last_async_operation_time_ns = 0


def new_proposal_id() -> str:
    return _new_prefixed_id("pp")


def new_proposal_version_id() -> str:
    return _new_prefixed_id("ppv")


def new_workflow_event_id() -> str:
    return _new_prefixed_id("pwe")


def new_async_operation_id() -> str:
    return _new_time_ordered_prefixed_id("pop")


def new_execution_request_id() -> str:
    return _new_prefixed_id("pex")


def new_approval_id() -> str:
    return _new_prefixed_id("pap")


def new_report_request_id() -> str:
    return _new_prefixed_id("prr")


def stable_memo_report_request_id(
    *,
    proposal_id: str,
    memo_id: str,
    idempotency_key: str,
) -> str:
    identity = f"memo-report-package\x00{proposal_id}\x00{memo_id}\x00{idempotency_key}"
    return f"prr_{sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def new_memo_event_id() -> str:
    return _new_prefixed_id("pme")


def _new_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _new_time_ordered_prefixed_id(prefix: str) -> str:
    global _last_async_operation_time_ns
    with _ASYNC_OPERATION_ID_LOCK:
        current_time_ns = time_ns()
        if current_time_ns <= _last_async_operation_time_ns:
            current_time_ns = _last_async_operation_time_ns + 1
        _last_async_operation_time_ns = current_time_ns
    return f"{prefix}_{current_time_ns:016x}{uuid4().hex[:8]}"
